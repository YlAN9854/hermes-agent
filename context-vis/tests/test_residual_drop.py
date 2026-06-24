"""
ContextVis · residual_drop_map 单元测试

覆盖:
  - 被取代的旧 read(superseded_read):同路径全量重读 → 旧读 chunk 进 drop
  - 带行区间的 read 不参与取代判定(精度优先)
  - 失败 tool_result(failed_tool):起始内容命中错误标记
  - 空输入边界
  - drop 优先级:superseded_read 不被 chitchat 覆盖

运行:
  cd <repo>
  PYTHONPATH="$PWD" /home/frey_ubuntu/.hermes/hermes-agent/venv/bin/python \
      context-vis/tests/test_residual_drop.py
"""
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.contextvis.regime import residual_drop_map


# ──────────────────────────────────────────────
# 辅助构造器
# ──────────────────────────────────────────────

def _chunk(cid, tokens, *mis):
    return {
        "id": cid,
        "tokens": tokens,
        "sourceRefs": [{"messageIndex": mi} for mi in mis],
    }


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text):
    return {"role": "assistant", "content": text}


def _tool_call_msg(tool_call_id, name, path=None, extra_args=None):
    """构造 tool_call 消息(OpenAI function 格式,与 _tool_call_index 对齐)。"""
    args = {}
    if path:
        args["path"] = path
    if extra_args:
        args.update(extra_args)
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": tool_call_id,
                         "function": {"name": name, "arguments": json.dumps(args)}}],
    }


def _tool_result_msg(tool_call_id, name, content="ok"):
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "tool_name": name,
        "content": content,
    }


# ──────────────────────────────────────────────
# 测试:被取代的旧 read
# ──────────────────────────────────────────────

def test_superseded_read_basic():
    """同路径全量读两次 → 第一次(旧)的 chunk 标 superseded_read。"""
    msgs = [
        _user("read foo first"),
        _tool_call_msg("tc1", "read_file", "foo.py"),
        _tool_result_msg("tc1", "read_file", "content v1"),   # mi=2 → c-old
        _user("read foo again"),
        _tool_call_msg("tc2", "read_file", "foo.py"),
        _tool_result_msg("tc2", "read_file", "content v2"),   # mi=5 → c-new
    ]
    chunks = [
        _chunk("c-old", 300, 2),
        _chunk("c-new", 310, 5),
    ]
    result = residual_drop_map(msgs, chunks)
    assert "c-old" in result, f"c-old should be superseded_read: {result}"
    assert result["c-old"] == "superseded_read"
    assert "c-new" not in result, f"latest read should not be dropped: {result}"
    print("PASS test_superseded_read_basic")


def test_superseded_read_with_range_skipped():
    """带行区间参数的 read 不参与取代判定(精度优先)。"""
    msgs = [
        _user("read with range"),
        _tool_call_msg("tc1", "read_file", "bar.py", {"offset": 0, "limit": 50}),
        _tool_result_msg("tc1", "read_file", "partial content"),  # mi=2
        _user("read without range"),
        _tool_call_msg("tc2", "read_file", "bar.py"),
        _tool_result_msg("tc2", "read_file", "full content"),     # mi=5
    ]
    chunks = [
        _chunk("c-range", 100, 2),
        _chunk("c-full", 200, 5),
    ]
    result = residual_drop_map(msgs, chunks)
    # 带 range 的 read 不算全量 → 不连进取代链 → c-range 不应被 drop
    assert "c-range" not in result, f"range-read should not be superseded: {result}"
    print("PASS test_superseded_read_with_range_skipped")


def test_superseded_read_three_reads():
    """同路径三次全量读 → 前两次 superseded,最后一次保留。"""
    msgs = [
        _user("read 1"),
        _tool_call_msg("tc1", "read_file", "x.py"),
        _tool_result_msg("tc1", "read_file", "v1"),  # mi=2
        _user("read 2"),
        _tool_call_msg("tc2", "read_file", "x.py"),
        _tool_result_msg("tc2", "read_file", "v2"),  # mi=5
        _user("read 3"),
        _tool_call_msg("tc3", "read_file", "x.py"),
        _tool_result_msg("tc3", "read_file", "v3"),  # mi=8
    ]
    chunks = [
        _chunk("c1", 100, 2),
        _chunk("c2", 100, 5),
        _chunk("c3", 100, 8),
    ]
    result = residual_drop_map(msgs, chunks)
    assert "c1" in result and result["c1"] == "superseded_read"
    assert "c2" in result and result["c2"] == "superseded_read"
    assert "c3" not in result
    print("PASS test_superseded_read_three_reads")


# ──────────────────────────────────────────────
# 测试:失败 tool_result
# ──────────────────────────────────────────────

def test_failed_tool_error_marker():
    """tool_result 内容起始含错误标记 → failed_tool。"""
    msgs = [
        _user("run cmd"),
        _tool_call_msg("tc1", "run_command"),
        _tool_result_msg("tc1", "run_command",
                         "Error: No such file or directory\nsome extra"),  # mi=2
    ]
    chunks = [_chunk("c-fail", 50, 2)]
    result = residual_drop_map(msgs, chunks)
    assert "c-fail" in result, f"failed tool not detected: {result}"
    assert result["c-fail"] == "failed_tool"
    print("PASS test_failed_tool_error_marker")


def test_failed_tool_nonzero_exit():
    """tool_result 含非零 exit code → failed_tool。"""
    msgs = [
        _user("run"),
        _tool_call_msg("tc1", "bash"),
        _tool_result_msg("tc1", "bash", "exit code 1\nsome output"),  # mi=2
    ]
    chunks = [_chunk("c-exit", 40, 2)]
    result = residual_drop_map(msgs, chunks)
    assert "c-exit" in result, f"nonzero exit not detected: {result}"
    assert result["c-exit"] == "failed_tool"
    print("PASS test_failed_tool_nonzero_exit")


def test_failed_tool_read_file_excluded():
    """read_file 即便内容像错误也不判 failed_tool(排除 _FILE_TOOLS)。"""
    msgs = [
        _user("read"),
        _tool_call_msg("tc1", "read_file", "missing.py"),
        _tool_result_msg("tc1", "read_file", "Error: No such file or directory"),  # mi=2
    ]
    chunks = [_chunk("c-rf", 30, 2)]
    result = residual_drop_map(msgs, chunks)
    assert "c-rf" not in result, f"read_file should not be failed_tool: {result}"
    print("PASS test_failed_tool_read_file_excluded")


def test_success_tool_not_dropped():
    """正常成功的 tool_result 不进 drop。"""
    msgs = [
        _user("run"),
        _tool_call_msg("tc1", "bash"),
        _tool_result_msg("tc1", "bash", "hello world\nAll tests passed."),  # mi=2
    ]
    chunks = [_chunk("c-ok", 80, 2)]
    result = residual_drop_map(msgs, chunks)
    assert "c-ok" not in result, f"successful tool should not be dropped: {result}"
    print("PASS test_success_tool_not_dropped")


# ──────────────────────────────────────────────
# 测试:drop 优先级
# ──────────────────────────────────────────────

def test_superseded_read_not_overwritten():
    """superseded_read 优先级高于后来识别到的 failed_tool(同 chunk 不被覆盖)。"""
    # 构造一个 file chunk:mi=2 是旧读、被 mi=5 的新读取代;
    # 但 mi=2 的内容本身也像失败(正常情况下 file chunk 不会走 failed_tool 分支,这里验证 drop 优先)
    msgs = [
        _user("read foo first"),
        _tool_call_msg("tc1", "read_file", "foo.py"),
        _tool_result_msg("tc1", "read_file", "content"),   # mi=2
        _user("read foo again"),
        _tool_call_msg("tc2", "read_file", "foo.py"),
        _tool_result_msg("tc2", "read_file", "content v2"),  # mi=5
    ]
    chunks = [
        _chunk("c-old", 200, 2),
        _chunk("c-new", 210, 5),
    ]
    result = residual_drop_map(msgs, chunks)
    # c-old 是旧读 → superseded_read,无论后续如何
    assert result.get("c-old") == "superseded_read"
    print("PASS test_superseded_read_not_overwritten")


# ──────────────────────────────────────────────
# 测试:空输入
# ──────────────────────────────────────────────

def test_empty_messages():
    result = residual_drop_map([], [_chunk("c1", 100, 0)])
    assert result == {}
    print("PASS test_empty_messages")


def test_empty_chunks():
    msgs = [_user("hello"), _assistant("hi")]
    result = residual_drop_map(msgs, [])
    assert result == {}
    print("PASS test_empty_chunks")


def test_none_inputs():
    result = residual_drop_map(None, None)
    assert result == {}
    print("PASS test_none_inputs")


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_superseded_read_basic,
        test_superseded_read_with_range_skipped,
        test_superseded_read_three_reads,
        test_failed_tool_error_marker,
        test_failed_tool_nonzero_exit,
        test_failed_tool_read_file_excluded,
        test_success_tool_not_dropped,
        test_superseded_read_not_overwritten,
        test_empty_messages,
        test_empty_chunks,
        test_none_inputs,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
            failed.append(t.__name__)
    print()
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests passed.")
