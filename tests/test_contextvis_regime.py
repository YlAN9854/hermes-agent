"""ContextVis 任务态检测器 + 两级压缩门控单测(R 第一刀,零 LLM,确定性)。

覆盖:salient 抽取、森林 vs 任务判定、保守性(空/弱输入→forest)、两级门控
(A 级 regime + B 级 collision)、逃生阀 HERMES_CONTEXTVIS_REGIME=0。

环境无 pytest → 文件末尾自带 standalone runner;自定位 sys.path 绕开 ~/.hermes 安装副本。
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent.compaction_gate import _should_gate_for_regime
from agent.contextvis.regime import (
    RegimeDetector,
    _message_text,
    _salient_tokens,
    get_regime_detector,
)


def _u(text):
    return {"role": "user", "content": text}


def _a(text):
    return {"role": "assistant", "content": text}


# ── salient 抽取 ────────────────────────────────────────────────────────

def test_salient_picks_paths():
    s = _salient_tokens("请看 agent/context_compressor.py 里的实现")
    assert any("context_compressor" in t for t in s)


def test_salient_picks_backtick_and_identifier():
    s = _salient_tokens("调用 `plan_compaction` 然后看 buildSnapshotChunks")
    assert "plan_compaction" in s
    assert "buildsnapshotchunks" in s


def test_salient_drops_common_words():
    # 纯小写普通词 / 停用词不收 → 不在无关轮间制造假纽带。
    s = _salient_tokens("this is the result value with content type name")
    assert s == set()


def test_salient_drops_tool_names():
    # 工具名太通用,不作纽带(实测 read_file/search_files 串了无关轮)。
    s = _salient_tokens("我用 read_file 和 search_files 看了一下")
    assert "read_file" not in s and "search_files" not in s


def test_salient_path_keeps_project_drops_infra():
    # 路径取有辨识度的段(opencode/registry),丢 home/apps/workspace/src/packages。
    s = _salient_tokens(
        "看 /home/frey_ubuntu/apps/workspace/agent/opencode/packages/opencode/src/tool/registry.ts"
    )
    assert "opencode" in s and "registry" in s
    assert "home" not in s and "workspace" not in s and "packages" not in s and "src" not in s


def test_boilerplate_message_yields_no_salient():
    # 压缩 / 任务清单注记 → 整条跳过,不贡献 salient(掐掉 context/in_progress/preserved 假纽带)。
    msg = {"role": "user", "content": "[Your active task list was preserved across context compression] in_progress: foo"}
    assert _message_text(msg) == ""
    assert _salient_tokens(_message_text(msg)) == set()


# ── 森林 vs 任务 ────────────────────────────────────────────────────────

def test_forest_independent_turns():
    # 互不相关、无共享产物 → forest。
    msgs = [
        _u("讲讲法国大革命"), _a("1789 年…"),
        _u("写首关于海的诗"), _a("海……"),
        _u("python 怎么读文件"), _a("用 open……"),
        _u("番茄炒蛋怎么做"), _a("先打蛋……"),
    ]
    a = RegimeDetector().assess(msgs)
    assert a.regime == "forest", a.reason


def test_task_shared_artifacts():
    # 反复围绕同几个文件/标识符 → task,且 on_thread 覆盖它们。
    msgs = [
        _u("帮我改 agent/compaction_gate.py 里的 request_compaction_decision"),
        _a("好,我看了 `request_compaction_decision`"),
        _u("在 agent/compaction_gate.py 加一个 `_should_gate_for_regime`"),
        _a("已加 `_should_gate_for_regime` 到 compaction_gate.py"),
        _u("现在 request_compaction_decision 里调用 _should_gate_for_regime"),
        _a("已接好 request_compaction_decision"),
        _u("给 _should_gate_for_regime 补个测试"),
        _a("测试覆盖 _should_gate_for_regime 的两级判定"),
    ]
    a = RegimeDetector().assess(msgs)
    assert a.regime == "task", a.reason
    assert len(a.on_thread_indices) >= 4


def test_tool_heavy_single_turn_is_forest():
    # 回归:一个工具密集的 turn 内部反复引用同一文件,不该被当成主线(纽带须跨 turn)。
    msgs = [
        _u("看看番茄炒蛋怎么做"),
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": '{"path": "recipe_tomato.md"}'}}]},
        {"role": "tool", "content": "recipe_tomato.md: 先打蛋…"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": '{"path": "recipe_tomato.md"}'}}]},
        {"role": "tool", "content": "recipe_tomato.md: 热锅…"},
        _a("番茄炒蛋:先打蛋,热锅下蛋…"),
    ]
    a = RegimeDetector().assess(msgs)
    assert a.regime == "forest", a.reason


def test_compression_residue_does_not_fake_a_task():
    # 复现实测:森林(星座+电竞+读代码,各独立)经压缩后,注入的摘要块(role=user,含
    # 任务清单注记 + 摊进的 opencode 内容)会跨"假 turn"复现 opencode/registry,冒充主线。
    # 样板块须对检测器完全隐形 → 仍判 forest(真实 turn 只有星座 + 一个读代码 tail,无跨 turn 纽带)。
    note = "[Your active task list was preserved across context compression]"
    msgs = [
        _u("我想了解星座,我是摩羯座"), _a("摩羯座……"),
        # 第 1 次压缩注入的摘要块(role=user)——含 opencode 内容,但是样板,须无视。
        {"role": "user", "content": f"{note} read_file opencode registry.ts processor state"},
        {"role": "user", "content": f"{note} opencode registry processor in_progress"},
        # 最近一个真实 user turn:读代码(单 turn,凑不出跨 turn 主线)。
        _u("读一下 opencode 的源码"),
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": '{"path":"opencode/registry.ts"}'}}]},
        _a("registry.ts 里有 processor……"),
    ]
    a = RegimeDetector().assess(msgs)
    assert a.regime == "forest", a.reason


def test_empty_is_forest():
    assert RegimeDetector().assess([]).regime == "forest"


def test_short_task_below_min_msgs_is_forest():
    # 只有两轮共享,不够 MIN_MSGS → 保守判 forest(不扰)。
    msgs = [
        _u("看 foo_bar.py"), _a("foo_bar.py 收到"),
    ]
    assert RegimeDetector().assess(msgs).regime == "forest"


# ── 两级门控 ────────────────────────────────────────────────────────────

class _FakeAgent:
    pass


def _task_msgs():
    return [
        _u("改 agent/compaction_gate.py 的 request_compaction_decision"),
        _a("看了 `request_compaction_decision`"),
        _u("加 `_should_gate_for_regime` 到 compaction_gate.py"),
        _a("已加 `_should_gate_for_regime`"),
        _u("request_compaction_decision 调 _should_gate_for_regime"),
        _a("接好 request_compaction_decision"),
        _u("给 _should_gate_for_regime 写测试"),
        _a("测试覆盖 _should_gate_for_regime"),
    ]


def test_gate_forest_no_interrupt(monkeypatch=None):
    os.environ.pop("HERMES_CONTEXTVIS_REGIME", None)
    forest = [
        _u("讲法国大革命"), _a("1789…"), _u("写海的诗"), _a("海…"),
        _u("python 读文件"), _a("open…"), _u("番茄炒蛋"), _a("打蛋…"),
    ]
    plan = {"head_end": 1, "tail_start": 7}
    should, reason = _should_gate_for_regime(_FakeAgent(), forest, plan)
    assert should is False and "forest" in reason


def test_gate_task_collision_interrupts():
    os.environ.pop("HERMES_CONTEXTVIS_REGIME", None)
    msgs = _task_msgs()
    # 折叠区覆盖中段(含 on-thread)→ 打断。
    plan = {"head_end": 1, "tail_start": 7}
    should, reason = _should_gate_for_regime(_FakeAgent(), msgs, plan)
    assert should is True and "collision" in reason


def test_gate_task_no_collision_silent():
    os.environ.pop("HERMES_CONTEXTVIS_REGIME", None)
    msgs = _task_msgs()
    # 折叠区是空区间(head_end==tail_start)→ 不触及任何 on-thread → 静默压。
    plan = {"head_end": 3, "tail_start": 3}
    should, reason = _should_gate_for_regime(_FakeAgent(), msgs, plan)
    assert should is False and "no-collision" in reason


def test_gate_escape_hatch_forces_interrupt():
    # REGIME=0 → 回退一级门控,恒打断(森林也弹)。
    os.environ["HERMES_CONTEXTVIS_REGIME"] = "0"
    try:
        forest = [_u("讲法国大革命"), _a("1789…")]
        should, reason = _should_gate_for_regime(_FakeAgent(), forest, {"head_end": 0, "tail_start": 1})
        assert should is True and "off" in reason
    finally:
        os.environ.pop("HERMES_CONTEXTVIS_REGIME", None)


def test_debug_breakdown_shape():
    # debug() 返回完整拆解,linking_tokens 按出现 turn 数降序(太普遍的浮顶)。
    msgs = _task_msgs()
    d = RegimeDetector().debug(msgs)
    assert d["regime"] == "task"
    assert "thresholds" in d and "linking_tokens" in d and "turns" in d
    assert len(d["turns"]) == d["n_turns"]
    lt = d["linking_tokens"]
    if len(lt) >= 2:
        assert lt[0]["n_turns"] >= lt[-1]["n_turns"]  # 降序
        assert all("token" in x and "turns" in x for x in lt)


def test_detector_cached_on_agent():
    ag = _FakeAgent()
    d1 = get_regime_detector(ag)
    d2 = get_regime_detector(ag)
    assert d1 is d2


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
