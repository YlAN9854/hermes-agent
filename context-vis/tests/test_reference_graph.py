"""
ContextVis · reference_graph 单元测试

覆盖:
  - files 索引(≥1 次触及,按 token 降序)
  - keywords 索引(≥2 块复现,按出现数降序)
  - 工具溯源边(read/revision)
  - 空输入边界

运行:
  cd <repo>
  PYTHONPATH="$PWD" /home/frey_ubuntu/.hermes/hermes-agent/venv/bin/python \
      context-vis/tests/test_reference_graph.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.contextvis.reference_graph import reference_graph


# ──────────────────────────────────────────────
# 辅助构造器
# ──────────────────────────────────────────────

def _chunk(cid, tokens, *mis):
    """构造一个 chunk,sourceRefs 按 messageIndex 列表生成。"""
    return {
        "id": cid,
        "tokens": tokens,
        "sourceRefs": [{"messageIndex": mi} for mi in mis],
    }


def _tool_call(idx, tool_call_id, name, path):
    """构造 assistant 消息里的 tool_call(OpenAI function 格式,与 _tool_call_index 对齐)。"""
    import json
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": tool_call_id,
                         "function": {"name": name, "arguments": json.dumps({"path": path})}}],
        "_mi": idx,
    }


def _tool_result(idx, tool_call_id, name, content="ok"):
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "tool_name": name,
        "content": content,
        "_mi": idx,
    }


def _user(idx, text):
    return {"role": "user", "content": text, "_mi": idx}


def _assistant(idx, text):
    return {"role": "assistant", "content": text, "_mi": idx}


def _msgs(*items):
    """按传入顺序赋 messageIndex(忽略 _mi 字段,直接用列表下标)。"""
    out = []
    for m in items:
        d = {k: v for k, v in m.items() if k != "_mi"}
        out.append(d)
    return out


# ──────────────────────────────────────────────
# 测试:files 索引
# ──────────────────────────────────────────────

def test_files_basic():
    """单次触及文件 → files 有条目(≥1);按 token 降序。"""
    msgs = _msgs(
        _user(0, "read foo"),
        _tool_call(1, "tc1", "write_file", "a.py"),
        _tool_result(2, "tc1", "write_file", "ok"),
        _tool_call(3, "tc2", "read_file", "b.py"),
        _tool_result(4, "tc2", "read_file", "content b"),
    )
    chunks = [
        _chunk("c-write", 500, 2),
        _chunk("c-read", 200, 4),
    ]
    g = reference_graph(msgs, chunks)
    keys = [f["key"] for f in g["files"]]
    assert "a.py" in keys, f"a.py missing from files: {keys}"
    assert "b.py" in keys, f"b.py missing from files: {keys}"
    # 按 token 降序:a.py(500) > b.py(200)
    assert keys.index("a.py") < keys.index("b.py"), f"token order wrong: {keys}"
    print("PASS test_files_basic")


def test_files_single_touch_included():
    """files 收 ≥1 次触及(与 artifacts 的 ≥2 不同)。"""
    msgs = _msgs(
        _user(0, "write once"),
        _tool_call(1, "tc1", "write_file", "once.py"),
        _tool_result(2, "tc1", "write_file", "ok"),
    )
    chunks = [_chunk("c1", 100, 2)]
    g = reference_graph(msgs, chunks)
    keys = [f["key"] for f in g["files"]]
    assert "once.py" in keys, f"single-touch file missing: {keys}"
    # artifacts 需要 ≥2 次触及,应为空
    assert g["artifacts"] == [], f"artifacts should be empty: {g['artifacts']}"
    print("PASS test_files_single_touch_included")


def test_files_tokens_sum():
    """同一文件对应多个 chunk 时,files.tokens = 各 chunk token 之和。"""
    msgs = _msgs(
        _user(0, "write foo"),
        _tool_call(1, "tc1", "write_file", "foo.py"),
        _tool_result(2, "tc1", "write_file", "ok"),
        _user(3, "read foo"),
        _tool_call(4, "tc2", "read_file", "foo.py"),
        _tool_result(5, "tc2", "read_file", "content"),
    )
    chunks = [
        _chunk("c-w", 300, 2),
        _chunk("c-r", 250, 5),
    ]
    g = reference_graph(msgs, chunks)
    foo = next((f for f in g["files"] if f["key"] == "foo.py"), None)
    assert foo is not None, "foo.py not in files"
    assert foo["tokens"] == 550, f"expected 550 tokens, got {foo['tokens']}"
    print("PASS test_files_tokens_sum")


# ──────────────────────────────────────────────
# 测试:keywords 索引
# ──────────────────────────────────────────────

def test_keywords_recurrence():
    """出现 ≥2 个 chunk 的 salient token → 进 keywords;单次出现的不进。

    _salient_tokens 只收:路径段 / 反引号 token / 含下划线或驼峰的标识符。
    测试用 `open_code`(含下划线)和 `/project/main.py`(路径段)触发收录。
    """
    msgs = _msgs(
        _user(0, "open_code analysis started"),
        _assistant(1, "running open_code checks"),
        _user(2, "what about /project/main.py"),
        _assistant(3, "/project/main.py looks fine"),
    )
    chunks = [
        _chunk("c0", 50, 0),
        _chunk("c1", 50, 1),
        _chunk("c2", 50, 2),
        _chunk("c3", 50, 3),
    ]
    g = reference_graph(msgs, chunks)
    kw_keys = [k["key"] for k in g["keywords"]]
    # "open_code" 含下划线 → 被 _salient_tokens 收录 → 出现在 c0+c1 → keywords
    assert "open_code" in kw_keys, f"'open_code' should be in keywords: {kw_keys}"
    print("PASS test_keywords_recurrence")


def test_keywords_sorted_by_count():
    """keywords 按 n(出现块数)降序。"""
    msgs = _msgs(
        _user(0, "opencode opencode tool"),
        _assistant(1, "opencode tool result"),
        _user(2, "opencode analysis"),
        _assistant(3, "tool done"),
    )
    chunks = [_chunk(f"c{i}", 50, i) for i in range(4)]
    g = reference_graph(msgs, chunks)
    kws = g["keywords"]
    if len(kws) >= 2:
        for i in range(len(kws) - 1):
            assert kws[i]["n"] >= kws[i + 1]["n"], \
                f"keywords not sorted by n: {[(k['key'], k['n']) for k in kws]}"
    print("PASS test_keywords_sorted_by_count")


def test_keywords_max_40():
    """keywords 最多返回 40 条。"""
    # 构造 50 个不同 salient token,各出现 2 次
    words = [f"uniqueword{i:03d}" for i in range(50)]
    text_a = " ".join(words[:25])
    text_b = " ".join(words[25:])
    text_c = " ".join(words[:25])   # 重复 a 的词(让 a 组词出现 2 次)
    text_d = " ".join(words[25:])   # 重复 b 的词
    msgs = _msgs(
        _user(0, text_a),
        _assistant(1, text_b),
        _user(2, text_c),
        _assistant(3, text_d),
    )
    chunks = [_chunk(f"c{i}", 50, i) for i in range(4)]
    g = reference_graph(msgs, chunks)
    assert len(g["keywords"]) <= 40, f"keywords exceeded 40: {len(g['keywords'])}"
    print("PASS test_keywords_max_40")


# ──────────────────────────────────────────────
# 测试:工具溯源边
# ──────────────────────────────────────────────

def test_edges_write_then_read():
    """write → read 同路径 → rel=read 边。"""
    msgs = _msgs(
        _user(0, "write"),
        _tool_call(1, "tc1", "write_file", "x.py"),
        _tool_result(2, "tc1", "write_file", "ok"),
        _user(3, "read"),
        _tool_call(4, "tc2", "read_file", "x.py"),
        _tool_result(5, "tc2", "read_file", "content"),
    )
    chunks = [
        _chunk("cw", 100, 2),
        _chunk("cr", 100, 5),
    ]
    g = reference_graph(msgs, chunks)
    tool_edges = [e for e in g["edges"] if e["kind"] == "tool"]
    assert len(tool_edges) == 1, f"expected 1 tool edge: {tool_edges}"
    assert tool_edges[0]["rel"] == "read", f"rel should be 'read': {tool_edges[0]}"
    assert tool_edges[0]["via"] == "x.py"
    print("PASS test_edges_write_then_read")


def test_edges_write_then_write():
    """write → write 同路径 → rel=revision 边。"""
    msgs = _msgs(
        _user(0, "write v1"),
        _tool_call(1, "tc1", "write_file", "x.py"),
        _tool_result(2, "tc1", "write_file", "ok"),
        _user(3, "write v2"),
        _tool_call(4, "tc2", "write_file", "x.py"),
        _tool_result(5, "tc2", "write_file", "ok"),
    )
    chunks = [
        _chunk("cw1", 100, 2),
        _chunk("cw2", 100, 5),
    ]
    g = reference_graph(msgs, chunks)
    tool_edges = [e for e in g["edges"] if e["kind"] == "tool"]
    assert len(tool_edges) == 1
    assert tool_edges[0]["rel"] == "revision"
    print("PASS test_edges_write_then_write")


def test_edges_read_without_prior_write():
    """读一个本对话没写过的文件 → 无边。"""
    msgs = _msgs(
        _user(0, "read external"),
        _tool_call(1, "tc1", "read_file", "external.py"),
        _tool_result(2, "tc1", "read_file", "content"),
    )
    chunks = [_chunk("cr", 100, 2)]
    g = reference_graph(msgs, chunks)
    tool_edges = [e for e in g["edges"] if e["kind"] == "tool"]
    assert tool_edges == [], f"expected no edges: {tool_edges}"
    print("PASS test_edges_read_without_prior_write")


# ──────────────────────────────────────────────
# 测试:空输入
# ──────────────────────────────────────────────

def test_empty_inputs():
    g = reference_graph([], [])
    assert g["edges"] == []
    assert g["artifacts"] == []
    assert g["files"] == []
    assert g["keywords"] == []
    assert "tool" in g["layers"]
    print("PASS test_empty_inputs")


def test_none_inputs():
    g = reference_graph(None, None)
    assert g["edges"] == []
    assert g["files"] == []
    print("PASS test_none_inputs")


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_files_basic,
        test_files_single_touch_included,
        test_files_tokens_sum,
        test_keywords_recurrence,
        test_keywords_sorted_by_count,
        test_keywords_max_40,
        test_edges_write_then_read,
        test_edges_write_then_write,
        test_edges_read_without_prior_write,
        test_empty_inputs,
        test_none_inputs,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed.append(t.__name__)
    print()
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests passed.")
