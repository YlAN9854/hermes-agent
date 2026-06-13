"""ContextVis 方向 A-v2 fold 纯逻辑单测。

覆盖 fold 落地路里**零依赖、纯函数**的两块(摘要放置 + 非连续 splice),它们是
风险集中处(role 合法性 / 非连续重排)。RPC 编排(LLM 调用、版本校验、emit)走端到端,
不在此单测。

环境无 pytest → 文件末尾自带 standalone runner,可直接
``venv/bin/python tests/test_contextvis_fold.py`` 运行。
"""

import os
import sys

# 自定位:把仓库根插到 sys.path 最前,确保导入的是工作树而非 ~/.hermes 安装副本
# (editable 安装的 MAPPING 把 agent 指向 ~/.hermes;PathFinder 命中仓库根即可绕过)。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent.context_compressor import (
    _SUMMARY_END_MARKER,
    _summary_message,
    splice_fold_summary,
)
from agent.contextvis import (
    drop_indices_for_chunks,
    message_indices_for_chunks,
)


# ── _summary_message:role 选择 + 合并兜底 ────────────────────────────────

def test_summary_role_avoids_prev_assistant():
    # 前邻 assistant → 摘要取 user(避免与前邻同 role);后邻不冲突 → standalone。
    standalone, merge = _summary_message("assistant", "assistant", "S")
    assert merge is None
    assert standalone["role"] == "user"
    assert standalone["content"].endswith(_SUMMARY_END_MARKER)


def test_summary_role_user_when_prev_tool():
    standalone, merge = _summary_message("tool", "assistant", "S")
    assert merge is None and standalone["role"] == "user"


def test_summary_role_assistant_when_prev_user():
    # 前邻 user → 取 assistant;后邻 user 不冲突 → standalone;assistant 不加 END 标。
    standalone, merge = _summary_message("user", "user", "S")
    assert merge is None
    assert standalone["role"] == "assistant"
    assert standalone["content"] == "S"


def test_summary_flips_to_avoid_tail_collision():
    # 前邻 user → 初选 assistant,撞后邻 assistant → 翻 user,又撞前邻 user。
    # 两头都堵 → 合并进尾。
    standalone, merge = _summary_message("user", "assistant", "S")
    assert standalone is None
    assert merge is not None
    assert merge.startswith("S")
    assert merge.endswith("\n\n")


def test_summary_no_tail_forces_standalone():
    # 后邻为空串(无保留尾)→ 永不合并,必 standalone。
    standalone, merge = _summary_message("user", "", "S")
    assert merge is None and standalone is not None


# ── splice_fold_summary:非连续替换 ──────────────────────────────────────

def _msgs(*roles):
    return [{"role": r, "content": f"m{i}"} for i, r in enumerate(roles)]


def test_splice_contiguous_middle():
    before = _msgs("user", "assistant", "user", "assistant", "user")
    out = splice_fold_summary(before, [1, 2, 3], "SUM")
    # 3 块折成 1 → 长度 5-3+1=3;摘要落在 index1 原位。
    assert len(out) == 3
    assert out[0]["content"] == "m0"
    assert "SUM" in _flatten(out[1]["content"])
    assert out[2]["content"] == "m4"


def test_splice_noncontiguous_places_one_summary_at_earliest():
    # 支线交错:折 {1,3},保留 0,2,4 → 一条摘要落在最早位(1),仅一条。
    before = _msgs("user", "assistant", "user", "assistant", "user")
    out = splice_fold_summary(before, [3, 1], "SUM")  # 乱序输入也要按最早位
    contents = [_flatten(m["content"]) for m in out]
    sum_count = sum("SUM" in c for c in contents)
    assert sum_count == 1
    # 保留的原文都在,被折的 m1/m3 消失。
    assert "m0" in contents[0]
    assert "m2" in " ".join(contents)
    assert "m4" in " ".join(contents)
    assert not any(c == "m1" or c == "m3" for c in contents)


def test_splice_empty_indices_noop():
    before = _msgs("user", "assistant")
    out = splice_fold_summary(before, [], "SUM")
    assert out == before


def test_splice_out_of_range_ignored():
    before = _msgs("user", "assistant")
    out = splice_fold_summary(before, [1, 99, -1], "SUM")
    # 仅 index1 有效 → 折它,摘要落 index1。
    assert len(out) == 2
    assert out[0]["content"] == "m0"
    assert "SUM" in _flatten(out[1]["content"])


# ── 索引别名 ────────────────────────────────────────────────────────────

def test_index_alias_identity():
    # drop_indices_for_chunks 现在是 message_indices_for_chunks 的别名(fold/drop 共用)。
    assert drop_indices_for_chunks is message_indices_for_chunks


def _flatten(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return str(content)


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
