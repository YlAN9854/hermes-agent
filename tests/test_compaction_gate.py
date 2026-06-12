"""压缩闸门(ContextVis 方向 A 对偶)单测。

覆盖:ContextCompressor.plan_compaction 的非破坏性边界划分、闸门的 chunk→系统命运
映射、以及 request_compaction_decision 的安全短路(未开闸 / 无中段 / 非交互 → None,
绝不挂起无人值守的 agent)。
"""

from unittest.mock import patch

import pytest

from agent.compaction_gate import (
    _system_fate_for_chunks,
    request_compaction_decision,
)
from agent.context_compressor import ContextCompressor


# ── plan_compaction:非破坏性预览 ────────────────────────────────────


@pytest.fixture()
def compressor():
    with patch(
        "agent.context_compressor.get_model_context_length", return_value=100000
    ):
        return ContextCompressor(
            model="test/model",
            threshold_percent=0.50,
            protect_first_n=2,
            protect_last_n=2,
            quiet_mode=True,
        )


def _big(role, i):
    return {"role": role, "content": f"[{i}] " + "x" * 4000}


def test_plan_compaction_partitions_long_history(compressor):
    # system + 30 大消息:头尾被保护、中段可折叠。
    msgs = [{"role": "system", "content": "sys"}] + [
        _big("user" if i % 2 == 0 else "assistant", i) for i in range(30)
    ]
    plan = compressor.plan_compaction(msgs)
    assert plan["head_end"] == compressor._protect_head_size(msgs)  # 1(sys)+2
    assert 0 < plan["head_end"] < plan["tail_start"] <= plan["n"]
    assert plan["has_middle"] is True
    assert plan["context_length"] == 100000
    # 非破坏:不改原 messages
    assert len(msgs) == 31


def test_plan_compaction_no_middle_when_short(compressor):
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    plan = compressor.plan_compaction(msgs)
    assert plan["has_middle"] is False


def test_plan_compaction_does_not_mutate(compressor):
    msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    before = [dict(m) for m in msgs]
    compressor.plan_compaction(msgs)
    assert msgs == before


# ── chunk → 系统命运映射 ─────────────────────────────────────────────


def _chunk(cid, ctype, *idxs):
    return {
        "id": cid,
        "type": ctype,
        "tokens": 100,
        "sourceRefs": [{"messageIndex": i} for i in idxs],
    }


def test_system_fate_fold_middle_keep_ends():
    # 折叠区 [3, 8)
    chunks = [
        _chunk("history:turn1", "history", 1, 2),  # 头 → keep
        _chunk("history:turn3", "history", 4, 5),  # 中 → fold
        _chunk("file:msg:6", "file", 6),  # 中 → fold
        _chunk("history:turn9", "history", 9, 10),  # 尾 → keep
    ]
    fate = _system_fate_for_chunks(chunks, head_end=3, tail_start=8)
    assert fate == {
        "history:turn1": "keep",
        "history:turn3": "fold",
        "file:msg:6": "fold",
        "history:turn9": "keep",
    }


def test_system_fate_ignores_partless_chunks():
    # system / tool_schema 无 messageIndex → 不出现在映射里
    chunks = [
        {"id": "system:sys:stable", "type": "system", "sourceRefs": [{"part": "system:stable"}]},
        {"id": "schema:read_file", "type": "tool_schema", "sourceRefs": [{"part": "tool:read_file"}]},
    ]
    assert _system_fate_for_chunks(chunks, 1, 5) == {}


# ── request_compaction_decision:安全短路 ────────────────────────────


class _FakeComp:
    def __init__(self, has_middle):
        self._hm = has_middle
        self.last_prompt_tokens = 60000
        self.threshold_tokens = 50000
        self.context_length = 100000

    def plan_compaction(self, messages):
        return {
            "head_end": 1,
            "tail_start": 3 if self._hm else 1,
            "has_middle": self._hm,
            "summary_target_ratio": 0.2,
            "context_length": 100000,
        }


class _FakeAgent:
    def __init__(self, has_middle=True):
        self.context_compressor = _FakeComp(has_middle)


def test_decision_none_when_gate_disabled(monkeypatch):
    monkeypatch.delenv("HERMES_CONTEXTVIS_GATE", raising=False)
    assert request_compaction_decision(_FakeAgent(), [{"role": "user", "content": "x"}]) is None


def test_decision_none_when_no_middle(monkeypatch):
    monkeypatch.setenv("HERMES_CONTEXTVIS_GATE", "1")
    assert request_compaction_decision(_FakeAgent(has_middle=False), []) is None


def test_decision_none_when_not_interactive(monkeypatch):
    # 开闸 + 有中段,但非 gateway 交互上下文(无 dashboard)→ 必须返回 None,
    # 绝不阻塞无人值守的 agent。
    monkeypatch.setenv("HERMES_CONTEXTVIS_GATE", "1")
    monkeypatch.delenv("HERMES_GATEWAY_SESSION", raising=False)
    with patch("tools.approval._is_gateway_approval_context", return_value=False):
        assert request_compaction_decision(_FakeAgent(has_middle=True), []) is None
