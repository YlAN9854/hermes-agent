import json

import pytest

from context_vis.domain import BacktrackLink, ContextVisModel, Turn, validate_model
from context_vis.hermes_adapter import HermesContextAdapter
from context_vis.repository import ContextVisRepository
from context_vis.service import ContextVisService
from context_vis.survival import update_survival
from hermes_state import SessionDB


class FakeAdapter:
    tier = 1
    session_id = "session-1"
    legacy_warning = None

    def __init__(self, turns, responses):
        self.turns = turns
        self.responses = iter(responses)
        self.prompts = []

    def get_full_transcript(self): return self.turns
    def llm_complete(self, prompt, **_opts):
        self.prompts.append(prompt)
        return json.dumps(next(self.responses))


def test_generation_resolves_exact_spans_and_incrementally_appends(tmp_path):
    turns = [Turn("t1", "user", "Build the index.", None, 1), Turn("t2", "assistant", "I will build it.", None, 2)]
    initial = {"units": [{"title": "Index", "covered_turn_ids": ["t1", "t2"], "summary_sentences": [{"text": "Index requested", "sources": [{"turn_id": "t1", "quote": "Build the index."}]}]}]}
    adapter = FakeAdapter(turns, [initial])
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(adapter, repo)
    result = service.generate_units(False)
    assert result["units"][0]["summary_sentences"][0]["source_spans"][0] == {"turn_id": "t1", "char_start": 0, "char_end": 16}
    original_id = result["units"][0]["unit_id"]

    adapter.turns.append(Turn("t3", "user", "Add a dashboard.", None, 3))
    adapter.responses = iter([{"units": [{"title": "Dashboard", "covered_turn_ids": ["t3"], "summary_sentences": [{"text": "Dashboard added", "sources": [{"turn_id": "t3", "quote": "Add a dashboard."}]}]}]}])
    updated = service.generate_units(True)
    assert [u["unit_id"] for u in updated["units"]][:1] == [original_id]
    assert len(updated["units"]) == 2
    repo.close()


def test_generation_rejects_absent_source_quote_without_partial_save(tmp_path):
    turns = [Turn("t1", "user", "alpha beta", None, 1)]
    response = {"units": [{"title": "Bad", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "bad", "sources": [{"turn_id": "t1", "quote": "gamma"}]}]}]}
    repo = ContextVisRepository(tmp_path)
    with pytest.raises(ValueError, match="invalid after retry"):
        ContextVisService(FakeAdapter(turns, [response, response]), repo).generate_units(False)
    assert repo.load("session-1")[0] is None
    repo.close()


def test_generation_ambiguous_quote_falls_back_to_first_occurrence_on_retry(tmp_path):
    turns = [Turn("t1", "user", "same same", None, 1)]
    response = {"units": [{"title": "Dup", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "dup", "sources": [{"turn_id": "t1", "quote": "same"}]}]}]}
    adapter = FakeAdapter(turns, [response, response])
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(adapter, repo).generate_units(False)

    # Strict on the first attempt (char_start demanded), first-occurrence
    # fallback on the retry instead of failing the batch.
    assert len(adapter.prompts) == 2
    assert result["units"][0]["summary_sentences"][0]["source_spans"][0] == {"turn_id": "t1", "char_start": 0, "char_end": 4}
    repo.close()


def test_generation_retry_includes_invalid_response_and_supports_char_start(tmp_path):
    turns = [Turn("t1", "user", "same same", None, 1)]
    invalid = {"units": [{"title": "Bad", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "bad", "sources": [{"turn_id": "t1", "quote": "same"}]}]}]}
    corrected = {"units": [{"title": "Good", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "good", "sources": [{"turn_id": "t1", "quote": "same", "char_start": 5}]}]}]}
    adapter = FakeAdapter(turns, [invalid, corrected])
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(adapter, repo).generate_units(False)

    assert result["units"][0]["summary_sentences"][0]["source_spans"][0]["char_start"] == 5
    assert "PREVIOUS_RESPONSE_JSON" in adapter.prompts[1]
    assert json.dumps(invalid) in adapter.prompts[1]
    repo.close()


def test_generation_retries_invalid_json_with_the_raw_response(tmp_path):
    class RawAdapter(FakeAdapter):
        def llm_complete(self, prompt, **_opts):
            self.prompts.append(prompt)
            return next(self.responses)

    turns = [Turn("t1", "user", "Build the index.", None, 1)]
    invalid = '{"units": ['
    corrected = json.dumps({"units": [{
        "title": "Index",
        "covered_turn_ids": ["t1"],
        "summary_sentences": [{
            "text": "Index requested",
            "sources": [{"turn_id": "t1", "quote": "Build the index.", "char_start": 0}],
        }],
    }]})
    adapter = RawAdapter(turns, [invalid, corrected])
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(adapter, repo).generate_units(False)

    assert len(result["units"]) == 1
    assert invalid in adapter.prompts[1]
    repo.close()


def test_generation_does_not_semantically_retry_transport_failure(tmp_path):
    class FailingAdapter(FakeAdapter):
        def __init__(self, turns):
            super().__init__(turns, [])
            self.calls = 0

        def llm_complete(self, prompt, **opts):
            self.calls += 1
            raise TimeoutError("provider timed out")

    adapter = FailingAdapter([Turn("t1", "user", "hello", None, 1)])
    repo = ContextVisRepository(tmp_path)

    with pytest.raises(TimeoutError, match="provider timed out"):
        ContextVisService(adapter, repo).generate_units(False)

    assert adapter.calls == 1
    assert repo.load("session-1")[0] is None
    repo.close()


def test_generation_resolves_rendered_markdown_quote_to_raw_source_span(tmp_path):
    content = "- **当前仓库绝对路径**：`/home/hermes/project`"
    turns = [Turn("t1", "assistant", content, None, 1)]
    response = {"units": [{
        "title": "路径",
        "covered_turn_ids": ["t1"],
        "summary_sentences": [{
            "text": "记录仓库路径",
            "sources": [{"turn_id": "t1", "quote": "当前仓库绝对路径：/home/hermes/project"}],
        }],
    }]}
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(FakeAdapter(turns, [response]), repo).generate_units(False)

    span = result["units"][0]["summary_sentences"][0]["source_spans"][0]
    assert content[span["char_start"]:span["char_end"]] == "当前仓库绝对路径**：`/home/hermes/project"
    repo.close()


def test_generation_resolves_quote_across_hard_line_wraps(tmp_path):
    content = "The listener stalls because there is no such\nproblem in the parked consumer group, and restarts drain it."
    turns = [Turn("t1", "assistant", content, None, 1)]
    response = {"units": [{"title": "Wrap", "covered_turn_ids": ["t1"], "summary_sentences": [{
        "text": "Wrapped quote",
        "sources": [{"turn_id": "t1", "quote": "there is no such problem in the parked consumer group"}],
    }]}]}
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(FakeAdapter(turns, [response]), repo).generate_units(False)

    span = result["units"][0]["summary_sentences"][0]["source_spans"][0]
    assert content[span["char_start"]:span["char_end"]] == "there is no such\nproblem in the parked consumer group"
    repo.close()


@pytest.mark.parametrize("raw_title, clamped", [
    ("缓存优化与失效策略的完整重构方", "缓存优化与失效策略的完整重构方"),
    ("缓存优化与失效策略的完整重构方案", "缓存优化与失效策略的完整重构…"),
    ("IndexRebuild Finalization And Migration Summary", "IndexRebuild Finalization And…"),
    ("Migration summary for the rebuilt index pipeline", "Migration summary for the…"),
])
def test_titles_clamp_by_display_width_without_mid_word_cuts(tmp_path, raw_title, clamped):
    turns = [Turn("t1", "user", "Rebuild the search index.", None, 1)]
    response = {"units": [{"title": raw_title, "covered_turn_ids": ["t1"], "summary_sentences": [{
        "text": "t", "sources": [{"turn_id": "t1", "quote": "Rebuild the search index."}],
    }]}]}
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(FakeAdapter(turns, [response]), repo).generate_units(False)

    assert result["units"][0]["title"] == clamped
    repo.close()


def test_salient_dedup_by_span_overlap_and_decimal_safe_sentences(tmp_path):
    content = "部署脚本必须使用 Python 3.10 运行。其他版本未验证。\n另外绝不改动 schema 定义。"
    turns = [Turn("t1", "user", content, None, 1)]
    generated = {"units": [{"title": "版本", "covered_turn_ids": ["t1"], "summary_sentences": [{
        "text": "版本要求", "sources": [{"turn_id": "t1", "quote": "必须使用 Python 3.10"}],
    }]}]}
    guessed = {"items": [{"turn_id": "t1", "quote": "部署脚本必须使用 Python 3.10 运行", "kind": "other"}]}
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(FakeAdapter(turns, [generated, guessed]), repo)
    service.generate_units(False)

    result = service.detect_salient()

    infos = result["units"][0]["salient_infos"]
    # The decimal point in "3.10" must not end the sentence, "绝不" must be a
    # reliable keyword, and the overlapping ai_guessed re-quote must be dropped.
    assert [i["detected_text"] for i in infos] == [
        "部署脚本必须使用 Python 3.10 运行。",
        "另外绝不改动 schema 定义。",
    ]
    assert [i["confidence"] for i in infos] == ["reliable", "reliable"]
    repo.close()


def _four_turn_batch_response():
    return {"units": [
        {"title": "Reproduce leak", "covered_turn_ids": ["t1", "t2"], "summary_sentences": [{
            "text": "Leak reproduced", "sources": [{"turn_id": "t1", "quote": "Reproduce the leak."}],
        }]},
        {"title": "Leak rerun", "covered_turn_ids": ["t3", "t4"], "summary_sentences": [{
            "text": "Rerun confirms leak", "sources": [{"turn_id": "t3", "quote": "Rerun shows the leak."}],
        }]},
    ]}


def _four_turns():
    return [
        Turn("t1", "user", "Reproduce the leak.", None, 1),
        Turn("t2", "assistant", "Reproducing now.", None, 2),
        Turn("t3", "tool", "Rerun shows the leak.", "bash", 3),
        Turn("t4", "assistant", "Confirmed.", None, 4),
    ]


def test_merge_pass_joins_adjacent_same_topic_units(tmp_path):
    merge = {"groups": [{"indexes": [0, 1], "title": "Leak reproduction"}]}
    adapter = FakeAdapter(_four_turns(), [_four_turn_batch_response(), merge])
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(adapter, repo).generate_units(False)

    assert len(result["units"]) == 1
    unit = result["units"][0]
    assert unit["title"] == "Leak reproduction"
    assert unit["covered_turns"] == ["t1", "t2", "t3", "t4"]
    assert [s["text"] for s in unit["summary_sentences"]] == ["Leak reproduced", "Rerun confirms leak"]
    assert unit["frozen"] is True
    repo.close()


def test_merge_pass_falls_back_to_unmerged_units_on_invalid_grouping(tmp_path):
    bad_merge = {"groups": [{"indexes": [1, 0], "title": "Backwards"}]}
    adapter = FakeAdapter(_four_turns(), [_four_turn_batch_response(), bad_merge])
    repo = ContextVisRepository(tmp_path)

    result = ContextVisService(adapter, repo).generate_units(False)

    assert [u["title"] for u in result["units"]] == ["Reproduce leak", "Leak rerun"]
    repo.close()


def test_salient_cross_position_duplicates_collapse_to_first_with_count(tmp_path):
    turns = [
        Turn("t1", "user", "必须先备份数据库。然后再执行迁移。", None, 1),
        Turn("t2", "tool", "migrate: 检查前置条件\n必须先备份数据库。\n检查通过", "bash", 2),
    ]
    generated = {"units": [{"title": "迁移", "covered_turn_ids": ["t1", "t2"], "summary_sentences": [{
        "text": "迁移前置", "sources": [{"turn_id": "t1", "quote": "必须先备份数据库。然后再执行迁移。"}],
    }]}]}
    guessed = {"items": [{"turn_id": "t2", "quote": "必须先备份数据库。", "kind": "other"}]}
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(FakeAdapter(turns, [generated, guessed]), repo)
    service.generate_units(False)

    result = service.detect_salient()

    infos = result["units"][0]["salient_infos"]
    assert len(infos) == 1
    assert infos[0]["detected_text"] == "必须先备份数据库。"
    assert infos[0]["span_in_B"]["turn_id"] == "t1"
    assert infos[0]["occurrences"] == 3  # t1 reliable + t2 reliable repeat + ai_guessed re-quote
    assert infos[0]["confidence"] == "reliable"
    repo.close()


def test_repository_delete_model_allows_regeneration(tmp_path):
    turns = [Turn("t1", "user", "Build the index.", None, 1)]
    response = {"units": [{"title": "Index", "covered_turn_ids": ["t1"], "summary_sentences": [{
        "text": "Index requested", "sources": [{"turn_id": "t1", "quote": "Build the index."}],
    }]}]}
    repo = ContextVisRepository(tmp_path)
    ContextVisService(FakeAdapter(turns, [response]), repo).generate_units(False)

    repo.delete_model("session-1")

    regenerated = ContextVisService(FakeAdapter(turns, [response]), repo).generate_units(False)
    assert len(regenerated["units"]) == 1
    repo.close()


def test_adapter_deduplicates_provenance_copies_and_hides_summary(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("s", "cli")
    db.append_message("s", "user", "original")
    loaded = db.get_messages_as_conversation("s")
    db.archive_and_compact("s", [loaded[0], {"role": "assistant", "content": "[CONTEXT SUMMARY]: hidden", "_compressed_summary": True}])
    turns = HermesContextAdapter(db, "s").get_full_transcript()
    assert [(t.turn_id, t.content) for t in turns] == [("hermes-msg:1", "original")]
    db.close()


def _compacted_session(tmp_path, summary="[CONTEXT SUMMARY]: the user forbade dropping production"):
    """Build a session that has been compacted in place, plus its adapter."""
    db = SessionDB(tmp_path / "state.db")
    db.create_session("s", "cli")
    db.append_message("s", "user", "never drop the production database")
    db.append_message("s", "assistant", "understood")
    db.append_message("s", "user", "carry on")
    loaded = db.get_messages_as_conversation("s")
    db.archive_and_compact("s", [
        {"role": "assistant", "content": summary, "_compressed_summary": True},
        loaded[2],
    ])
    return db, HermesContextAdapter(db, "s", tmp_path)


def test_active_context_keeps_the_summary_that_transcript_b_excludes(tmp_path):
    db, adapter = _compacted_session(tmp_path)

    active = adapter.get_active_context()
    transcript = adapter.get_full_transcript()

    # A holds the summary (the model sees it); B never does.
    summary_entries = [e for e in active.entries if e.synthetic]
    assert len(summary_entries) == 1
    assert summary_entries[0].origin_turn_id is None
    assert not any("CONTEXT SUMMARY" in t.content for t in transcript)
    # The surviving turn keeps its B linkage.
    assert [e.origin_turn_id for e in active.entries if not e.synthetic] == ["hermes-msg:3"]
    assert adapter.tier == 2
    db.close()


def test_tier_degrades_to_one_without_an_active_context(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("empty", "cli")
    adapter = HermesContextAdapter(db, "empty", tmp_path)

    assert adapter.get_active_context() is None
    assert adapter.tier == 1
    assert adapter.get_compression_events() == []
    db.close()


def test_adapter_reads_probe_events_and_skips_unknown_versions(tmp_path):
    db, adapter = _compacted_session(tmp_path)
    directory = tmp_path / "context-vis" / "compaction"
    directory.mkdir(parents=True)
    (directory / "s.jsonl").write_text("\n".join([
        json.dumps({"v": 1, "event_id": "e2", "ts": 200.0, "before_turn_ids": ["hermes-msg:1", "hermes-msg:3"],
                    "after_turn_ids": ["hermes-msg:3"], "summary_text": "second", "unlinked_before": 2}),
        json.dumps({"v": 1, "event_id": "e1", "ts": 100.0, "before_turn_ids": ["hermes-msg:1", "hermes-msg:2"],
                    "after_turn_ids": ["hermes-msg:2"], "summary_text": "first"}),
        json.dumps({"v": 99, "event_id": "future", "ts": 300.0}),
        "not json at all",
    ]), encoding="utf-8")

    events = adapter.get_compression_events()

    # Sorted by time, sequence-numbered, unknown version and torn line skipped.
    assert [e.event_id for e in events] == ["e1", "e2"]
    assert [e.sequence for e in events] == [1, 2]
    assert events[0].dropped_turn_ids == ["hermes-msg:1"]
    assert events[0].fidelity == "observed"
    assert events[0].note is None
    assert "no transcript provenance" in events[1].note
    db.close()


def test_reconstructs_history_for_sessions_that_predate_the_probe(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("s", "cli")
    for role, text in [("user", "rule one"), ("assistant", "ok"), ("user", "more"), ("assistant", "done")]:
        db.append_message("s", role, text)
    loaded = db.get_messages_as_conversation("s")
    db.archive_and_compact("s", [{"role": "assistant", "content": "[CONTEXT SUMMARY]: gen1", "_compressed_summary": True}, loaded[3]])
    db.append_message("s", "user", "after gen1")
    loaded2 = db.get_messages_as_conversation("s")
    db.archive_and_compact("s", [{"role": "assistant", "content": "[CONTEXT SUMMARY]: gen2", "_compressed_summary": True}, loaded2[-1]])

    events = HermesContextAdapter(db, "s", tmp_path).get_compression_events()

    assert [e.fidelity for e in events] == ["reconstructed", "reconstructed"]
    assert [e.sequence for e in events] == [1, 2]
    # Generation 1 kept only the last turn; generation 2 kept only the newer one.
    assert events[0].dropped_turn_ids == ["hermes-msg:1", "hermes-msg:2", "hermes-msg:3"]
    assert events[0].kept_turn_ids == ["hermes-msg:4"]
    assert events[0].summary_text == "[CONTEXT SUMMARY]: gen1"
    assert events[1].dropped_turn_ids == ["hermes-msg:4"]
    assert all("approximate" in e.note for e in events)
    db.close()


def test_probe_records_suppress_reconstruction_of_the_same_boundary(tmp_path):
    db, adapter = _compacted_session(tmp_path)
    assert adapter.get_compression_events()[0].fidelity == "reconstructed"

    directory = tmp_path / "context-vis" / "compaction"
    directory.mkdir(parents=True)
    (directory / "s.jsonl").write_text(json.dumps({
        "v": 1, "event_id": "observed-1", "ts": 1e12,  # after the archived rows
        "before_turn_ids": ["hermes-msg:1", "hermes-msg:3"], "after_turn_ids": ["hermes-msg:3"],
        "summary_text": "observed summary",
    }) + "\n", encoding="utf-8")

    events = HermesContextAdapter(db, "s", tmp_path).get_compression_events()

    # The older boundary is still reconstructed; the observed one is not duplicated.
    assert [e.fidelity for e in events] == ["reconstructed", "observed"]
    assert [e.event_id for e in events][-1] == "observed-1"
    db.close()


def test_backlinks_only_point_backwards():
    transcript = [Turn("t1", "user", "one", None, 1), Turn("t2", "user", "two", None, 2)]
    from context_vis.domain import SemanticUnit, SummarySentence, SpanRef
    units = [
        SemanticUnit("u1", "one", [SummarySentence("one", [SpanRef("t1", 0, 3)])], ["t1"]),
        SemanticUnit("u2", "two", [SummarySentence("two", [SpanRef("t2", 0, 3)])], ["t2"]),
    ]
    validate_model(ContextVisModel(units=units, backlinks=[BacktrackLink("u2", "u1", "resume")]), transcript)
    with pytest.raises(ValueError, match="later unit"):
        validate_model(ContextVisModel(units=units, backlinks=[BacktrackLink("u1", "u2", "forward")]), transcript)


def test_dashboard_context_vis_endpoint_reads_isolated_profile_home(_isolate_hermes_home):
    from hermes_constants import get_hermes_home
    from context_vis.api import get_context_session

    db = SessionDB(get_hermes_home() / "state.db")
    db.create_session("api-session", "cli")
    db.append_message("api-session", "user", "immutable truth")
    db.close()

    payload = get_context_session("api-session")
    # A is readable, so Tier 2 — but this session was never compressed, so the
    # compression affordances stay off. Those are separate axes.
    assert payload["capabilities"] == {
        "tier": 2, "compression_events": False, "compression_fidelity": "observed", "preserve": False,
    }
    assert payload["transcript"][0]["content"] == "immutable truth"
    assert payload["model"]["tier"] == 2


def _survival_fixture(constraint: str, active_texts: list[tuple[str, bool]], tier: int = 2):
    """Build (model, transcript, active, info) for one constraint."""
    from context_vis.domain import ActiveContext, ActiveEntry, SalientInfo, SemanticUnit, SpanRef, SummarySentence
    content = f"Before. {constraint} After."
    start = content.index(constraint)
    turn = Turn("t1", "user", content, None, 1)
    info = SalientInfo("i1", "user_stated_constraint", constraint, SpanRef("t1", start, start + len(constraint)))
    unit = SemanticUnit("u1", "rule", [SummarySentence("rule", [SpanRef("t1", 0, 6)])], ["t1"], [info])
    model = ContextVisModel(units=[unit], tier=tier)
    active = ActiveContext([
        ActiveEntry("assistant" if synthetic else "user", text, None if synthetic else "t1", synthetic)
        for text, synthetic in active_texts
    ])
    return model, [turn], active, info


def test_tier_one_survival_is_always_unknown():
    model, transcript, active, info = _survival_fixture("Never delete the source.", [("Never delete the source.", False)], tier=1)
    update_survival(model, transcript, active)
    assert info.status_in_A == "unknown"


def test_survival_none_active_context_is_unknown():
    model, transcript, _, info = _survival_fixture("Never delete the source.", [])
    update_survival(model, transcript, None)
    assert info.status_in_A == "unknown"


def test_survival_detects_reframing_inside_a_long_summary():
    """The flagship Tier 2 case: a short constraint restated in a long summary.

    Scoring against whole entries (the pre-fix behaviour) gives ~0.02 here, so
    this was misclassified `absent` and the compare view had nothing to show.
    """
    constraint = "the production database must never be deleted"
    reframed = "the team agreed the production database must never be dropped"
    summary = (
        "[CONTEXT COMPACTION - REFERENCE ONLY] Earlier turns were compacted. "
        + "The user built a FastAPI weather service with Redis caching. " * 20
        + reframed + ". "
        + "Work then moved on to Docker packaging and deployment. " * 20
    )
    assert len(summary) > 2000 and constraint not in summary
    model, transcript, active, info = _survival_fixture(constraint, [(summary, True)])

    update_survival(model, transcript, active)

    assert info.status_in_A == "reframed"
    assert info.reframed_text_in_A
    assert info.reframed_text_in_A != summary
    assert len(info.reframed_text_in_A) < 4 * len(constraint)
    assert "must never be dropped" in info.reframed_text_in_A


def test_survival_present_absent_and_short_needle_paths():
    verbatim = "Cache TTL must not exceed 10 minutes"
    model, transcript, active, info = _survival_fixture(verbatim, [(f"Reminder: {verbatim} in all environments.", True)])
    update_survival(model, transcript, active)
    assert (info.status_in_A, info.reframed_text_in_A) == ("present", None)

    model, transcript, active, info = _survival_fixture(verbatim, [("Totally unrelated content about billing exports.", True)])
    update_survival(model, transcript, active)
    assert (info.status_in_A, info.reframed_text_in_A) == ("absent", None)

    # Below MIN_FRAGMENT_NEEDLE_CHARS: containment only, never fuzzy. The
    # active text is a near-miss that would score well above the threshold if
    # fragment scoring ran, so this pins the short-circuit rather than luck.
    model, transcript, active, info = _survival_fixture("Use TLS 1.3", [("use tls 1.2 everywhere", True)])
    update_survival(model, transcript, active)
    assert info.status_in_A == "absent"


def test_survival_does_not_invent_reframing_from_shared_stopwords():
    constraint = "the migration must run with the --lock flag enabled"
    noise = "The user asked about the weather and the time of the meeting. " * 30
    model, transcript, active, info = _survival_fixture(constraint, [(noise, True)])

    update_survival(model, transcript, active)

    assert info.status_in_A == "absent"


def test_salient_detection_keeps_rule_and_ai_guess_separate(tmp_path):
    turns = [Turn("t1", "user", "You must keep citations. Prefer short titles.", None, 1)]
    generated = {"units": [{"title": "Rules", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "Rules stated", "sources": [{"turn_id": "t1", "quote": "You must keep citations."}]}]}]}
    guessed = {"items": [{"turn_id": "t1", "quote": "Prefer short titles.", "kind": "other"}]}
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(FakeAdapter(turns, [generated, guessed]), repo)
    service.generate_units(False)
    result = service.detect_salient()
    assert [item["confidence"] for item in result["units"][0]["salient_infos"]] == ["reliable", "ai_guessed"]
    repo.close()


class Tier2FakeAdapter(FakeAdapter):
    """Duck-typed Tier 2 adapter. Survival makes no LLM calls, so tests can
    pass responses=[] and any accidental call surfaces as StopIteration."""

    tier = 2

    def __init__(self, turns, responses, active_texts, events=()):
        super().__init__(turns, responses)
        from context_vis.domain import ActiveContext, ActiveEntry
        self.active = ActiveContext([
            ActiveEntry("assistant" if synthetic else "user", text, None if synthetic else origin, synthetic)
            for text, synthetic, origin in active_texts
        ])
        self.events = list(events)

    def get_active_context(self): return self.active
    def get_compression_events(self): return self.events


def test_detect_salient_computes_survival_without_an_extra_llm_call(tmp_path):
    turns = [Turn("t1", "user", "You must keep citations. Prefer short titles.", None, 1)]
    generated = {"units": [{"title": "Rules", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "Rules stated", "sources": [{"turn_id": "t1", "quote": "You must keep citations."}]}]}]}
    guessed = {"items": []}
    # A dropped the turn entirely and replaced it with an unrelated summary.
    adapter = Tier2FakeAdapter(turns, [generated, guessed], [("Unrelated compaction summary.", True, None)])
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(adapter, repo)
    service.generate_units(False)

    result = service.detect_salient()

    assert [i["status_in_A"] for i in result["units"][0]["salient_infos"]] == ["absent"]
    assert result["survival"]["event_count"] == 0
    assert result["survival"]["active_fingerprint"]
    # Exactly two LLM calls: units + exploratory salient. Survival adds none.
    assert len(adapter.prompts) == 2
    repo.close()


def test_refresh_survival_job_persists_statuses_and_flags_staleness(tmp_path):
    constraint = "You must keep citations."
    turns = [Turn("t1", "user", f"{constraint} Prefer short titles.", None, 1)]
    generated = {"units": [{"title": "Rules", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "Rules", "sources": [{"turn_id": "t1", "quote": constraint}]}]}]}
    adapter = Tier2FakeAdapter(turns, [generated, {"items": []}], [(f"Reminder: {constraint}", True, None)])
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(adapter, repo)
    service.generate_units(False)
    service.detect_salient()

    model, _, _ = service.load()
    assert service.survival_is_stale(model) is False

    # A changes: the constraint is gone from what the model sees.
    from context_vis.domain import ActiveContext, ActiveEntry
    adapter.active = ActiveContext([ActiveEntry("assistant", "Totally different summary.", None, True)])
    model, _, _ = service.load()
    assert service.survival_is_stale(model) is True

    refreshed = service.refresh_survival()

    assert [i["status_in_A"] for i in refreshed["units"][0]["salient_infos"]] == ["absent"]
    model, _, _ = service.load()
    assert service.survival_is_stale(model) is False
    repo.close()


def test_survival_stale_is_false_without_salient_infos_or_tier_two(tmp_path):
    turns = [Turn("t1", "user", "Build the index.", None, 1)]
    generated = {"units": [{"title": "Index", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "Index", "sources": [{"turn_id": "t1", "quote": "Build the index."}]}]}]}
    repo = ContextVisRepository(tmp_path)
    service = ContextVisService(Tier2FakeAdapter(turns, [generated], [("anything", True, None)]), repo)
    service.generate_units(False)

    model, _, _ = service.load()
    assert service.survival_is_stale(model) is False  # no salient infos to judge
    repo.close()


def test_repository_rejects_stale_revision_and_only_recovers_jobs_explicitly(tmp_path):
    repo = ContextVisRepository(tmp_path)
    revision = repo.save("s", ContextVisModel().to_dict(), None)
    with pytest.raises(RuntimeError, match="revision_conflict"):
        repo.save("s", ContextVisModel().to_dict(), None, expected_revision=revision - 1)
    repo.create_job("j", "s", "generate_units", {})
    repo.update_job("j", "running")
    repo.close()
    reopened = ContextVisRepository(tmp_path)
    assert reopened.get_job("j")["status"] == "running"
    assert reopened.recover_interrupted_jobs() == 1
    assert reopened.get_job("j")["status"] == "failed"
    reopened.close()


def test_dashboard_recovery_runs_once_and_does_not_fail_live_jobs(tmp_path):
    from context_vis.api import _ensure_recovered, _RECOVERED_HOMES

    _RECOVERED_HOMES.discard(tmp_path.resolve())
    repo = ContextVisRepository(tmp_path)
    repo.create_job("old", "s", "generate_units", {})
    repo.update_job("old", "running")
    repo.close()

    _ensure_recovered(tmp_path)
    repo = ContextVisRepository(tmp_path)
    assert repo.get_job("old")["status"] == "failed"
    repo.create_job("live", "s", "generate_units", {})
    repo.update_job("live", "running")
    repo.close()

    # Polling/worker repository opens call this again, but the active process's
    # live job must remain untouched.
    _ensure_recovered(tmp_path)
    repo = ContextVisRepository(tmp_path)
    assert repo.get_job("live")["status"] == "running"
    repo.close()
