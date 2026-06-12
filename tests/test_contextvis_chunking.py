"""ContextVis 服务端分块流水线单测（agent/contextvis/chunking.py）。

覆盖：5 个渲染带产出、token 整体缩放校准、file/tool_result 分流、
tool_schema 按 toolset 合并、history 按轮分组、每 chunk 带 provenance。
"""

import json

import pytest

from agent.contextvis import chunking
from agent.contextvis.chunking import (
    build_snapshot_chunks,
    drop_indices_for_chunks,
)


class _FakeCompressor:
    last_prompt_tokens = 1000


class _FakeAgent:
    def __init__(self, tools):
        self.tools = tools
        self.context_compressor = _FakeCompressor()
        self._cached_system_prompt = "fallback system prompt"


@pytest.fixture
def patched(monkeypatch):
    # system prompt → 3 节（避免拉起真实装配）
    import agent.system_prompt as sp

    monkeypatch.setattr(
        sp,
        "build_system_prompt_parts",
        lambda agent, system_message=None: {
            "stable": "S" * 400,
            "context": "C" * 200,
            "volatile": "V" * 100,
        },
    )
    # tool → toolset 映射
    import model_tools

    monkeypatch.setattr(
        model_tools,
        "get_toolset_for_tool",
        lambda name: {"read_file": "filesystem", "write_file": "filesystem"}.get(name, "web"),
    )


def _build():
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {}}},
        {"type": "function", "function": {"name": "write_file", "parameters": {}}},
        {"type": "function", "function": {"name": "web_search", "parameters": {}}},
    ]
    agent, session = _make()
    return build_snapshot_chunks(agent, session)


def _make():
    """构造 (agent, session)，供 build_snapshot_chunks / drop_indices_for_chunks 共用。"""
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {}}},
        {"type": "function", "function": {"name": "write_file", "parameters": {}}},
        {"type": "function", "function": {"name": "web_search", "parameters": {}}},
    ]
    agent = _FakeAgent(tools)
    history = [
        {"role": "user", "content": "fix the bug in auth"},
        {
            "role": "assistant",
            "content": "sure",
            "tool_calls": [
                {"id": "c1", "function": {"name": "read_file", "arguments": json.dumps({"path": "auth/session.py"})}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "tool_name": "read_file", "content": "file contents here"},
        {
            "role": "assistant",
            "content": "now run tests",
            "tool_calls": [
                {"id": "c2", "function": {"name": "terminal", "arguments": json.dumps({"command": "pytest"})}}
            ],
        },
        {"role": "tool", "tool_call_id": "c2", "tool_name": "terminal", "content": '{"exit_code": 1}\n5 failed'},
    ]
    return agent, {"history": history}


def test_all_bands_present(patched):
    out = _build()
    bands = {c["type"] for c in out["chunks"]}
    assert bands == {"system", "tool_schema", "history", "file", "tool_result"}


def test_system_three_chunks(patched):
    out = _build()
    system = [c for c in out["chunks"] if c["type"] == "system"]
    assert len(system) == 3
    assert {c["label"] for c in system} == {"stable", "context", "volatile"}


def test_tool_schema_grouped_by_toolset(patched):
    out = _build()
    schema = [c for c in out["chunks"] if c["type"] == "tool_schema"]
    groups = {c["group"] for c in schema}
    assert groups == {"filesystem", "web"}
    fs = next(c for c in schema if c["group"] == "filesystem")
    assert fs["members"] == 2  # read_file + write_file 合并


def test_file_vs_tool_result_split(patched):
    out = _build()
    files = [c for c in out["chunks"] if c["type"] == "file"]
    results = [c for c in out["chunks"] if c["type"] == "tool_result"]
    assert any(c["label"] == "auth/session.py" for c in files)
    assert any("terminal" in c["label"] for c in results)


def test_history_grouped_by_turn(patched):
    out = _build()
    history = [c for c in out["chunks"] if c["type"] == "history"]
    # 全程一个 user → 一轮；assistant 段并入同轮
    assert len(history) == 1
    assert history[0]["turn"] == 1
    assert history[0]["members"] >= 1


def test_tokens_scaled_to_real_total(patched):
    out = _build()
    total = sum(c["tokens"] for c in out["chunks"])
    # 缩放目标 1000；逐块取整误差 ≤ chunk 数。
    assert abs(total - 1000) <= len(out["chunks"])
    assert out["scaled_to"] == 1000


def test_every_chunk_has_provenance(patched):
    out = _build()
    for c in out["chunks"]:
        assert c["sourceRefs"], f"chunk {c['id']} missing sourceRefs"


def test_disabled_sources_dont_crash(patched):
    # 空 agent.tools + 空 history 不应抛
    agent = _FakeAgent([])
    out = build_snapshot_chunks(agent, {"history": []})
    assert "chunks" in out and isinstance(out["chunks"], list)


# ── 阶段 3：chunk → message 索引映射（drop_indices_for_chunks） ──────────


def _chunk_id(out, *, type_):
    return next(c["id"] for c in out["chunks"] if c["type"] == type_)


def test_drop_indices_file_chunk_resolves_message(patched):
    agent, session = _make()
    out = build_snapshot_chunks(agent, session)
    fid = _chunk_id(out, type_="file")  # read_file 结果 = history[2]
    assert drop_indices_for_chunks(agent, session, [fid]) == {2}


def test_drop_indices_history_turn_resolves_user_assistant(patched):
    agent, session = _make()
    out = build_snapshot_chunks(agent, session)
    hid = _chunk_id(out, type_="history")  # 第1轮 = user(0)+assistant(1)+assistant(3)
    assert drop_indices_for_chunks(agent, session, [hid]) == {0, 1, 3}


def test_drop_indices_ignores_system_and_tool_schema(patched):
    # system / tool_schema 无 messageIndex → 永远解析成空（apply 不触碰它们）
    agent, session = _make()
    out = build_snapshot_chunks(agent, session)
    sys_id = _chunk_id(out, type_="system")
    schema_id = _chunk_id(out, type_="tool_schema")
    assert drop_indices_for_chunks(agent, session, [sys_id, schema_id]) == set()


def test_drop_indices_unknown_or_empty(patched):
    agent, session = _make()
    assert drop_indices_for_chunks(agent, session, []) == set()
    assert drop_indices_for_chunks(agent, session, ["no:such:chunk"]) == set()


def test_drop_indices_union_across_chunks(patched):
    agent, session = _make()
    out = build_snapshot_chunks(agent, session)
    fid = _chunk_id(out, type_="file")
    rid = _chunk_id(out, type_="tool_result")  # terminal 结果 = history[4]
    assert drop_indices_for_chunks(agent, session, [fid, rid]) == {2, 4}
