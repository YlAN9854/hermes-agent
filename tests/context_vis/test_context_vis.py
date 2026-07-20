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


def test_generation_rejects_ambiguous_source_quote_without_partial_save(tmp_path):
    turns = [Turn("t1", "user", "same same", None, 1)]
    response = {"units": [{"title": "Bad", "covered_turn_ids": ["t1"], "summary_sentences": [{"text": "bad", "sources": [{"turn_id": "t1", "quote": "same"}]}]}]}
    repo = ContextVisRepository(tmp_path)
    with pytest.raises(ValueError, match="invalid after retry"):
        ContextVisService(FakeAdapter(turns, [response, response]), repo).generate_units(False)
    assert repo.load("session-1")[0] is None
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
    assert payload["capabilities"] == {"tier": 1, "compression_events": False, "preserve": False}
    assert payload["transcript"][0]["content"] == "immutable truth"
    assert payload["model"]["tier"] == 1


def test_tier_one_survival_is_always_unknown():
    from context_vis.domain import SalientInfo, SemanticUnit, SpanRef, SummarySentence
    turn = Turn("t1", "user", "Never delete the source.", None, 1)
    info = SalientInfo("i1", "user_stated_constraint", "Never delete the source.", SpanRef("t1", 0, 24))
    model = ContextVisModel(units=[SemanticUnit("u1", "rule", [SummarySentence("rule", [SpanRef("t1", 0, 4)])], ["t1"], [info])], tier=1)
    update_survival(model, [turn], [turn])
    assert info.status_in_A == "unknown"


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
