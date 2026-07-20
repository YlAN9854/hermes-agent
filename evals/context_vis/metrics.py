"""Programmatic (gold-referenced) evaluation of generated semantic units.

Usage: python -m evals.context_vis.metrics [case_id ...]

Reads runs/<case_id>/{transcript.json,model.json} plus the case's gold
annotations and emits runs/<case_id>/metrics.json and runs/metrics_all.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .case_schema import Case
from .seed import CASE_IDS, load_case

RUNS_DIR = Path(__file__).parent / "runs"


def _turn_index(turn_id: str) -> int:
    return int(turn_id.rsplit("-t", 1)[1])


def _boundary_prf(gold: set[int], pred: set[int], tolerance: int = 0) -> dict:
    if tolerance == 0:
        hit = len(gold & pred)
        matched_pred = len(pred & gold)
    else:
        remaining = set(pred)
        hit = 0
        for g in sorted(gold):
            near = [p for p in remaining if abs(p - g) <= tolerance]
            if near:
                remaining.discard(min(near, key=lambda p: abs(p - g)))
                hit += 1
        matched_pred = len(pred) - len(remaining)
    precision = matched_pred / len(pred) if pred else 1.0
    recall = hit / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def _survival_metrics(case: Case, case_id: str, run_dir: Path, turns_by_id: dict) -> dict | None:
    """Score predicted survival statuses against the case's gold labels.

    Also reports reframed_fragment_ratio: the stored reframing's length over
    the active entry it came from. A value near 1.0 means whole entries are
    being stored again instead of the matching fragment.
    """
    path = run_dir / "model_survival.json"
    if not case.survival or not path.exists():
        return None
    model = json.loads(path.read_text(encoding="utf-8"))
    active = json.loads((run_dir / "active_context.json").read_text(encoding="utf-8"))
    entry_lengths = [len(e["content"]) for e in active.get("entries", [])]
    detected = [info for u in model["units"] for info in u["salient_infos"]]

    per_status: dict[str, dict[str, int]] = {s: {"tp": 0, "fp": 0, "fn": 0} for s in ("present", "reframed", "absent")}
    matched = []
    for gold in case.survival:
        gc = case.constraints[gold.constraint]
        tid = f"synth-{case_id}-t{gc.turn:03d}"
        g_start = case.turns[gc.turn].content.find(gc.text)
        g_end = g_start + len(gc.text)
        hits = [
            info for info in detected
            if info["span_in_B"]["turn_id"] == tid
            and info["span_in_B"]["char_start"] < g_end and info["span_in_B"]["char_end"] > g_start
        ]
        if not hits:
            # Never detected as salient, so its survival cannot be judged.
            # Counted apart from misclassification: detection recall is a
            # different measurement and must not pollute this one.
            matched.append({"constraint": gc.text[:40], "gold": gold.status, "predicted": None})
            continue
        predicted = hits[0]["status_in_A"]
        matched.append({"constraint": gc.text[:40], "gold": gold.status, "predicted": predicted})
        if predicted == gold.status:
            per_status[gold.status]["tp"] += 1
        else:
            per_status[gold.status]["fn"] += 1
            if predicted in per_status:
                per_status[predicted]["fp"] += 1

    fragments = [len(i["reframed_text_in_A"]) for i in detected if i.get("reframed_text_in_A")]
    longest_entry = max(entry_lengths, default=0)
    judged = [m for m in matched if m["predicted"] is not None]
    return {
        "gold_labelled": len(case.survival),
        "judged": len(judged),
        "not_detected": len(matched) - len(judged),
        "correct": sum(1 for m in judged if m["gold"] == m["predicted"]),
        "per_status": {
            status: {
                **counts,
                "precision": round(counts["tp"] / (counts["tp"] + counts["fp"]), 3) if counts["tp"] + counts["fp"] else None,
                "recall": round(counts["tp"] / (counts["tp"] + counts["fn"]), 3) if counts["tp"] + counts["fn"] else None,
            }
            for status, counts in per_status.items()
        },
        "detail": matched,
        "reframed_fragment_ratio": round(max(fragments) / longest_entry, 3) if fragments and longest_entry else None,
        "compression_events": len(active.get("events", [])),
        "active_fidelity": active.get("fidelity"),
    }


def evaluate_case(case_id: str) -> dict:
    case: Case = load_case(case_id)
    run_dir = RUNS_DIR / case_id
    transcript = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
    model = json.loads((run_dir / "model.json").read_text(encoding="utf-8"))
    turns_by_id = {t["turn_id"]: t for t in transcript}
    units = model["units"]

    # --- segmentation vs gold ---
    unit_ranges = [sorted(_turn_index(tid) for tid in u["covered_turns"]) for u in units]
    pred_starts = {r[0] for r in unit_ranges} - {0}
    gold_starts = {s.start for s in case.segments} - {0}
    seg_of_turn = {}
    for si, seg in enumerate(case.segments):
        for i in range(seg.start, seg.end + 1):
            seg_of_turn[i] = si
    # purity: fraction of a unit's turns that fall in its majority gold segment
    total_turns = 0
    pure_turns = 0
    straddling_units = 0
    for r in unit_ranges:
        segs = [seg_of_turn[i] for i in r]
        majority = max(set(segs), key=segs.count)
        pure = sum(1 for s in segs if s == majority)
        total_turns += len(segs)
        pure_turns += pure
        if pure != len(segs):
            straddling_units += 1
    coverage_complete = sorted(i for r in unit_ranges for i in r) == list(range(len(case.turns)))

    # --- span integrity (re-verified from raw JSON, not trusting the validator) ---
    n_sentences = 0
    n_spans = 0
    bad_spans = 0
    span_lengths = []
    for u in units:
        for s in u["summary_sentences"]:
            n_sentences += 1
            for span in s["source_spans"]:
                n_spans += 1
                turn = turns_by_id.get(span["turn_id"])
                if turn is None or not (0 <= span["char_start"] < span["char_end"] <= len(turn["content"])):
                    bad_spans += 1
                else:
                    span_lengths.append(span["char_end"] - span["char_start"])

    # --- titles ---
    titles = [u["title"] for u in units]
    title_at_cap = sum(1 for t in titles if len(t) == 15)
    empty_titles = sum(1 for t in titles if not t.strip())

    # --- salient info vs gold constraints (only meaningful if detect_salient ran) ---
    salient = [info for u in units for info in u["salient_infos"]]
    constraint_eval = None
    if case.constraints and salient:
        detected_reliable = 0
        detected_any = 0
        for gc in case.constraints:
            tid = f"synth-{case_id}-t{gc.turn:03d}"
            g_start = case.turns[gc.turn].content.find(gc.text)
            g_end = g_start + len(gc.text)
            hits = [
                info for info in salient
                if info["span_in_B"]["turn_id"] == tid
                and info["span_in_B"]["char_start"] < g_end
                and info["span_in_B"]["char_end"] > g_start
            ]
            if hits:
                detected_any += 1
                if any(h["confidence"] == "reliable" for h in hits):
                    detected_reliable += 1
        constraint_eval = {
            "gold_constraints": len(case.constraints),
            "recall_reliable": round(detected_reliable / len(case.constraints), 3),
            "recall_any": round(detected_any / len(case.constraints), 3),
            "detected_total": len(salient),
            "detected_reliable": sum(1 for i in salient if i["confidence"] == "reliable"),
            "detected_ai_guessed": sum(1 for i in salient if i["confidence"] == "ai_guessed"),
        }

    survival_eval = _survival_metrics(case, case_id, run_dir, turns_by_id)

    return {
        "case_id": case_id,
        "n_gold_segments": len(case.segments),
        "survival": survival_eval,
        "n_units": len(units),
        "coverage_complete": coverage_complete,
        "boundary_exact": _boundary_prf(gold_starts, pred_starts),
        "boundary_tol1": _boundary_prf(gold_starts, pred_starts, tolerance=1),
        "unit_purity": round(pure_turns / total_turns, 3) if total_turns else None,
        "straddling_units": straddling_units,
        "sentences": n_sentences,
        "spans": n_spans,
        "bad_spans": bad_spans,
        "spans_per_sentence": round(n_spans / n_sentences, 2) if n_sentences else None,
        "median_span_chars": sorted(span_lengths)[len(span_lengths) // 2] if span_lengths else None,
        "titles_at_15char_cap": title_at_cap,
        "empty_titles": empty_titles,
        "constraints": constraint_eval,
    }


def main() -> int:
    case_ids = sys.argv[1:] or CASE_IDS
    results = []
    for case_id in case_ids:
        run_dir = RUNS_DIR / case_id
        if not (run_dir / "model.json").exists():
            print(f"[{case_id}] skipped (no model.json)")
            continue
        result = evaluate_case(case_id)
        (run_dir / "metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        results.append(result)
    (RUNS_DIR / "metrics_all.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
