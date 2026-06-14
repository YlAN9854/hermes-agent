"""ContextVis 任务态检测器（R 第一刀:廉价嗅探,零 LLM,确定性）。

判一个 session 处于**森林**(turns 相互独立,Hermes 自带压缩已够)还是**任务**态
(存在长程主线),并标出哪些消息属于主线(on-thread)。供压缩闸门的两级门控用:
森林 → 闸门闭嘴、静默自动压;任务且这次压缩会碰到主线 → 才打断请用户把关。

原理(见 context-vis/regime.md):森林里位置式压缩本就语义正确(留近=相关),
主线里位置偏离语义——ContextVis 是"位置式压缩将要背叛任务时才启动的纠偏器"。

第一刀只用**确定性信号**(**跨 turn** 复现的文件路径 / 代码标识符 = 主线纽带),无状态、
每次重算;第二刀换 aux 模型深析 + 滚动增量,接口不变。

注意纽带按 **turn** 而非消息计:否则一个工具密集 turn 内部反复引用同一文件会"自我结网"、
冒充主线。任务的本质是**跨 turn 延续**。

**误判代价不对称**:漏报(主线被压)损失大、误报(森林弹窗)损失小 → 检测器**偏保守**:
拿不准就判森林、不打扰。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)

# ── salient token 抽取 ──────────────────────────────────────────────────

# 文件路径 / 含扩展名文件名(最干净的"产物"信号)。
_PATH_RE = re.compile(r"(?:[A-Za-z0-9_.~-]*/){1,}[A-Za-z0-9_.~-]+|[A-Za-z0-9_-]+\.[A-Za-z]{1,5}\b")
# 反引号内 token。
_BACKTICK_RE = re.compile(r"`([^`\n]{2,64})`")
# 代码标识符:snake_case / camelCase(混合大小写或含下划线),长度 ≥ 4。
_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b")

# 超常见词:作 identifier 会在无关轮间制造假纽带 → 排除,保守不误判为任务。
_STOPWORDS: Set[str] = {
    "true", "false", "null", "none", "self", "this", "that", "function", "return",
    "import", "from", "value", "values", "content", "type", "types", "name", "names",
    "data", "result", "results", "error", "errors", "string", "number", "object",
    "array", "list", "dict", "index", "items", "params", "args", "kwargs", "print",
    "class", "async", "await", "const", "default", "export", "field", "fields",
    "request", "response", "session", "message", "messages", "user", "agent", "tool",
    "tools", "file", "files", "path", "code", "test", "tests", "with", "your", "have",
    "this", "what", "when", "then", "else", "will", "would", "should", "could", "about",
    "which", "there", "their", "these", "those", "into", "more", "some", "than", "they",
    # 工具名:任何文件/检索任务都用,太通用,不作主线纽带。
    "read_file", "write_file", "search_files", "list_files", "edit_file", "create_file",
    "delete_file", "apply_patch", "run_command", "str_replace", "view_file",
    "bash", "grep", "glob", "find", "rgrep", "todowrite", "todoread",
    # 压缩 / 任务清单注记的样板词(实测从压缩注记泄漏成假纽带)。
    "in_progress", "preserved", "compacted", "compaction", "handoff", "tasklist",
    "pending", "completed", "active", "todo", "todos", "summary",
}

# 路径里的基础设施段(无辨识度,丢弃;真信号是项目/模块/文件名段)。
_PATH_INFRA: Set[str] = {
    "home", "users", "usr", "var", "tmp", "opt", "etc", "apps", "workspace",
    "packages", "package", "src", "lib", "bin", "dist", "build", "node_modules",
    "__pycache__", "venv", "env", "git", "github", "com", "www", "http", "https",
    "index", "main", "app", "test", "tests", "docs", "doc", "assets",
}

# 压缩 / 续接注记的特征标记:含之即视为样板消息,不抽 salient(从源头掐噪音)。
_BOILERPLATE_MARKERS = (
    "active task list was preserved",
    "end of context summary",
    "compacted into a handoff summary",
    "context summary",
    "earlier conversation turns have been compacted",
)


def _raw_text(msg: Dict[str, Any]) -> str:
    """把一条消息摊成纯文本:正文(str / 多模态 text 块)+ tool_call 函数名与参数。"""
    parts: List[str] = []
    content = msg.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for p in content:
            if isinstance(p, dict):
                t = p.get("text")
                if isinstance(t, str):
                    parts.append(t)
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") if isinstance(tc, dict) else None
        if isinstance(fn, dict):
            if isinstance(fn.get("name"), str):
                parts.append(fn["name"])
            if isinstance(fn.get("arguments"), str):
                parts.append(fn["arguments"])
    return "\n".join(parts)


def _is_boilerplate(text: str) -> bool:
    """是否压缩 / 任务清单注记(注入的样板)。这类消息须对检测器**完全隐形**:
    不抽 salient、不算 turn、不算权重——否则压缩残骸会把内容摊进假 turn、制造假主线。
    """
    low = text.lower()
    return any(mark in low for mark in _BOILERPLATE_MARKERS)


def _message_text(msg: Dict[str, Any]) -> str:
    """salient 用:样板消息返回空(从源头掐假纽带)。"""
    text = _raw_text(msg)
    return "" if _is_boilerplate(text) else text


def _salient_tokens(text: str) -> Set[str]:
    """抽 salient token:路径段(强)+ 反引号 token + 代码标识符(去停用词)。"""
    out: Set[str] = set()
    # 路径:拆成段,丢基础设施段,留项目/模块/文件名(如 opencode / registry)。
    for m in _PATH_RE.findall(text):
        for seg in re.split(r"[/.\\]", m.lower()):
            if len(seg) >= 4 and seg not in _PATH_INFRA and seg not in _STOPWORDS:
                out.add(seg)
    for m in _BACKTICK_RE.findall(text):
        tok = m.strip().lower()
        if 2 <= len(tok) <= 64 and tok not in _STOPWORDS:
            out.add(tok)
    for m in _IDENT_RE.findall(text):
        low = m.lower()
        if low in _STOPWORDS or low in _PATH_INFRA:
            continue
        # 只要"像代码":含下划线、或混合大小写(camelCase)。纯小写普通词不收(降假纽带)。
        if "_" in m or (m != low and m != m.upper()):
            out.add(low)
    return out


# ── turn 切分 + LLM 骨架(方向 B 复用) ──────────────────────────────────

def _segment_turns(messages: List[Dict[str, Any]]):
    """按 **真实** user 发言切 turns;压缩样板的 role=user 块不算新 turn。

    返回 (turn_of, n_turns, boiler, raw)——heuristic _compute 与 LLM 骨架共用,
    确保两条路的 turn 编号一致(LLM 回的 mainline_turns 能映射回 message 下标)。
    """
    raw = [_raw_text(m) for m in messages]
    boiler = [_is_boilerplate(raw[i]) for i in range(len(messages))]
    turn_of: List[int] = []
    cur = -1
    for i, m in enumerate(messages):
        if m.get("role") == "user" and not boiler[i]:
            cur += 1
        turn_of.append(max(cur, 0))
    n_turns = (max(turn_of) + 1) if turn_of else 0
    return turn_of, n_turns, boiler, raw


def _path_basename(p: str) -> str:
    return re.split(r"[/\\]", p.strip("/\\"))[-1][:48]


def _build_skeleton(messages: List[Dict[str, Any]]):
    """把对话压成 turn-by-turn 骨架:每轮 = 用户意图 + 用了哪些工具 / 碰了哪些文件。

    只喂骨架、不喂全文——这是 1M 下"为省 token 而通读 1M"反讽的关键缓解。
    返回 (skeleton_text, turn_of, n_turns)。
    """
    turn_of, n_turns, boiler, raw = _segment_turns(messages)
    intents = [""] * n_turns
    tools: List[Set[str]] = [set() for _ in range(n_turns)]
    files: List[Set[str]] = [set() for _ in range(n_turns)]
    for i, m in enumerate(messages):
        if boiler[i]:
            continue
        t = turn_of[i]
        if m.get("role") == "user" and not intents[t] and isinstance(m.get("content"), str):
            intents[t] = m["content"][:180].replace("\n", " ").strip()
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") if isinstance(tc, dict) else None
            if isinstance(fn, dict):
                if isinstance(fn.get("name"), str):
                    tools[t].add(fn["name"])
                if isinstance(fn.get("arguments"), str):
                    for pm in _PATH_RE.findall(fn["arguments"])[:8]:
                        files[t].add(_path_basename(pm))
    lines: List[str] = []
    for t in range(n_turns):
        line = f"Turn {t}: {intents[t] or '(no user text)'}"
        meta = []
        if tools[t]:
            meta.append("tools=" + ",".join(sorted(tools[t])[:6]))
        if files[t]:
            meta.append("files=" + ",".join(sorted(files[t])[:6]))
        if meta:
            line += "\n  " + " | ".join(meta)
        lines.append(line)
    return "\n".join(lines), turn_of, n_turns


_REGIME_PROMPT = """You analyze a conversation between a user and an AI agent. A \
session OFTEN MIXES a current, ongoing task with earlier, unrelated one-off \
exchanges. Your job is NOT to label the whole session — it is to decide whether \
there is a CURRENT multi-turn task in progress, and which turns belong to it.

- CURRENT TASK = two or more RECENT turns building toward ONE goal (same \
codebase/files, one investigation, iterating on one piece of work). Later turns \
depend on earlier ones.
- mainline_turns = the turns that belong to that current task (the load-bearing \
ones to protect). Earlier turns about a DIFFERENT subject are NOT part of it — \
they are disposable noise; leave them OUT of mainline_turns.
- regime = "task" if such a current multi-turn task exists, EVEN IF some earlier \
turns are unrelated. regime = "forest" ONLY if there is no current task at all — \
the recent turns are themselves disconnected one-offs.

CRITICAL:
- The mere presence of an unrelated EARLIER turn does NOT make it a forest. Judge \
by whether the RECENT activity is a coherent multi-turn task.
- Using the SAME TOOLS is NOT the same task. Two unrelated questions that both use \
web search are still unrelated. Judge by GOAL/SUBJECT, not tools.

Turn-by-turn skeleton (user intent + what the agent did each turn):

{skeleton}

Respond with ONLY a JSON object, no prose:
{{"regime": "task" | "forest",
  "focus": "<=8 word label of the current task, or empty if forest",
  "turns": [{{"turn": <number>, "topic": "<=4 word subject of THIS turn", \
"mainline": true|false}}, ... EXACTLY ONE entry per turn shown above],
  "reason": "<=20 word justification"}}

For EACH turn give a SHORT topic = its own subject (e.g. "valorant prediction", \
"read opencode source", "tarot reading"). Set mainline=true ONLY for turns that \
belong to the current ongoing task; earlier unrelated one-offs get mainline=false. \
If regime is "forest", every turn is mainline=false."""


def _parse_json_object(text: str) -> Dict[str, Any]:
    """从 LLM 回复里抠出第一个 JSON 对象(容忍 ```json 围栏 / 前后赘述)。"""
    import json

    s = (text or "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1 or b <= a:
        raise ValueError("no json object in response")
    return json.loads(s[a : b + 1])


def _llm_enabled() -> bool:
    return os.environ.get("HERMES_CONTEXTVIS_REGIME_LLM", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ── 检测结果 ────────────────────────────────────────────────────────────

@dataclass
class RegimeAssessment:
    """一次任务态评估。``on_thread_indices`` 是 messages 列表里的下标。

    ``focus`` / ``turn_topics`` 仅 LLM 路填充(turn 带主题着色用,按 **regime turn** 编号);
    启发式回退留空。门控只读 ``regime`` / ``on_thread_indices``,不依赖这两者。
    """

    regime: str  # "forest" | "task"
    on_thread_indices: Set[int] = field(default_factory=set)
    reason: str = ""
    focus: str = ""
    # regime turn → {"topic": str, "mainline": bool}
    turn_topics: Dict[int, Dict[str, Any]] = field(default_factory=dict)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (ValueError, TypeError):
        return default


class RegimeDetector:
    """廉价、确定性的任务态嗅探(第一刀,零 LLM,无状态)。

    挂在 agent 上常驻(`get_regime_detector`);第二刀会把启发式换成 aux 深析 +
    滚动增量状态,``assess`` 接口不变。
    """

    def __init__(self) -> None:
        # 阈值以 **turn** 为单位(见下:纽带必须跨 turn)。
        self.min_turns = _env_int("HERMES_CONTEXTVIS_REGIME_MIN_TURNS", 2)
        self.min_ratio = _env_float("HERMES_CONTEXTVIS_REGIME_RATIO", 0.5)
        self.min_span = _env_int("HERMES_CONTEXTVIS_REGIME_SPAN", 3)
        self._llm_cache = None  # (skeleton_hash, RegimeAssessment) — 同历史不重复调 aux

    def _compute(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """跑一遍 turn 粒度的判定,返回全部中间量(assess / debug 共用)。"""
        n = len(messages or [])
        if n == 0:
            return {"n": 0, "n_turns": 0, "is_task": False, "on_thread_indices": set(),
                    "on_turns": set(), "ratio": 0.0, "span": 0, "linking": set(),
                    "token_turns": {}, "turn_salient": [], "turn_weight": [],
                    "turn_of": [], "turn_preview": []}

        # turn 切分 + 样板标记(与 LLM 骨架共用 _segment_turns,turn 编号一致)。
        turn_of, n_turns, boiler, raw = _segment_turns(messages)

        # 每条消息 salient + 权重(字符数代理 token);聚合到 turn。样板消息整条跳过。
        turn_salient: List[Set[str]] = [set() for _ in range(n_turns)]
        turn_weight: List[int] = [0] * n_turns
        turn_preview: List[str] = [""] * n_turns
        for i, m in enumerate(messages):
            if boiler[i]:
                continue  # 压缩残骸:不抽 salient、不算权重
            t = turn_of[i]
            turn_salient[t] |= _salient_tokens(raw[i])
            turn_weight[t] += max(1, len(raw[i]))
            if not turn_preview[t] and m.get("role") == "user" and isinstance(m.get("content"), str):
                turn_preview[t] = m["content"][:60].replace("\n", " ")

        # 纽带 token = 出现在 **≥2 个不同 turn** 的 salient(跨 turn 复现 = 主线)。
        # 关键:用 turn 而非消息——否则一个工具密集 turn 内部反复引用同一文件会自我结网,
        # 冒充主线。任务的本质是**跨 turn 延续**。
        token_turns: Dict[str, Set[int]] = {}
        for t, s in enumerate(turn_salient):
            for tok in s:
                token_turns.setdefault(tok, set()).add(t)
        linking = {tok for tok, ts in token_turns.items() if len(ts) >= 2}

        on_turns = {t for t, s in enumerate(turn_salient) if s & linking}
        on_thread_indices = {i for i in range(n) if turn_of[i] in on_turns}

        total_w = sum(turn_weight) or 1
        on_w = sum(turn_weight[t] for t in on_turns)
        ratio = on_w / total_w
        span = (max(on_turns) - min(on_turns) + 1) if on_turns else 0
        is_task = (
            len(on_turns) >= self.min_turns
            and ratio >= self.min_ratio
            and span >= self.min_span
        )
        return {"n": n, "n_turns": n_turns, "is_task": is_task,
                "on_thread_indices": on_thread_indices, "on_turns": on_turns,
                "ratio": ratio, "span": span, "linking": linking,
                "token_turns": token_turns, "turn_salient": turn_salient,
                "turn_weight": turn_weight, "turn_of": turn_of, "turn_preview": turn_preview}

    def _assess_heuristic(self, messages: List[Dict[str, Any]]) -> RegimeAssessment:
        """廉价、确定性的嗅探(第一刀 / LLM 不可用时的回退)。"""
        c = self._compute(messages)
        if c["n"] == 0:
            return RegimeAssessment("forest", set(), "empty")
        reason = (
            f"heuristic:{'task' if c['is_task'] else 'forest'} "
            f"on_turns={len(c['on_turns'])}/{c['n_turns']} ratio={c['ratio']:.2f} "
            f"span={c['span']} links={len(c['linking'])}"
        )
        return RegimeAssessment(
            "task" if c["is_task"] else "forest", c["on_thread_indices"], reason
        )

    def _assess_llm(self, messages: List[Dict[str, Any]], agent: Any) -> RegimeAssessment:
        """方向 B:辅助模型按"语义"判任务/森林。复用压缩的 aux runtime(便宜模型)。

        只喂 turn 骨架(意图 + 工具/文件),不喂全文。失败时由 ``assess`` 回退启发式。
        """
        comp = getattr(agent, "context_compressor", None)
        if comp is None:
            raise RuntimeError("no context_compressor for aux runtime")
        skeleton, turn_of, n_turns = _build_skeleton(messages)
        if n_turns < 2:
            return RegimeAssessment("forest", set(), "llm:too-short")
        key = hash(skeleton)
        if self._llm_cache is not None and self._llm_cache[0] == key:
            return self._llm_cache[1]

        from agent.auxiliary_client import call_llm

        call_kwargs: Dict[str, Any] = {
            "task": "compression",  # 复用 auxiliary.compression 的模型/超时配置
            "main_runtime": {
                "model": getattr(comp, "model", None),
                "provider": getattr(comp, "provider", None),
                "base_url": getattr(comp, "base_url", None),
                "api_key": getattr(comp, "api_key", None),
                "api_mode": getattr(comp, "api_mode", None),
            },
            "messages": [{"role": "user", "content": _REGIME_PROMPT.format(skeleton=skeleton)}],
            # 长会话每轮一条 topic,留足输出免截断。
            "max_tokens": 800,
        }
        if getattr(comp, "summary_model", ""):
            call_kwargs["model"] = comp.summary_model
        response = call_llm(**call_kwargs)
        content = response.choices[0].message.content
        if not isinstance(content, str):
            content = str(content) if content else ""
        data = _parse_json_object(content)

        regime = "task" if str(data.get("regime", "")).strip().lower() == "task" else "forest"

        # 逐轮 topic + mainline(turn 带着色用),按 regime turn 编号。
        turn_topics: Dict[int, Dict[str, Any]] = {}
        for item in (data.get("turns") or []):
            if not isinstance(item, dict):
                continue
            tn = item.get("turn")
            if not isinstance(tn, (int, float)):
                continue
            turn_topics[int(tn)] = {
                "topic": str(item.get("topic", "")).strip()[:40],
                "mainline": bool(item.get("mainline", False)),
            }

        # 主线轮:优先逐轮 mainline 标记,回退旧 mainline_turns 字段(向后兼容)。
        if turn_topics:
            mainline = {t for t, v in turn_topics.items() if v["mainline"]}
        else:
            mainline = {
                int(t) for t in (data.get("mainline_turns") or [])
                if isinstance(t, (int, float))
            }
        on_thread = (
            {i for i in range(len(messages)) if turn_of[i] in mainline}
            if regime == "task" else set()
        )
        focus = str(data.get("focus", ""))[:80]
        reason = f"llm:{regime} focus={focus!r} :: {str(data.get('reason', ''))[:80]}"
        result = RegimeAssessment(regime, on_thread, reason, focus, turn_topics)
        self._llm_cache = (key, result)
        return result

    def assess(
        self, messages: List[Dict[str, Any]], agent: Any = None
    ) -> RegimeAssessment:
        """权威判定:有 agent 且开启 LLM → aux 语义判定,失败回退启发式;否则启发式。"""
        if agent is not None and _llm_enabled():
            try:
                return self._assess_llm(messages, agent)
            except Exception as e:  # noqa: BLE001 — 检测绝不能挡住压缩流程
                logger.debug("regime LLM failed → heuristic fallback: %s", e)
        return self._assess_heuristic(messages)

    def debug(
        self, messages: List[Dict[str, Any]], agent: Any = None
    ) -> Dict[str, Any]:
        """完整拆解,供 context.regime 调试 RPC。顶层 regime 是**权威**判定(LLM 优先),
        另附启发式拆解(linking_tokens / turns)做对照。"""
        c = self._compute(messages)
        linking_tokens = sorted(
            ({"token": tok, "turns": sorted(c["token_turns"][tok]),
              "n_turns": len(c["token_turns"][tok])} for tok in c["linking"]),
            key=lambda d: (-d["n_turns"], d["token"]),
        )
        turns = [
            {"turn": t, "on_thread": t in c["on_turns"], "salient": len(c["turn_salient"][t]),
             "weight": c["turn_weight"][t], "preview": c["turn_preview"][t]}
            for t in range(c["n_turns"])
        ]
        auth = self.assess(messages, agent)
        return {
            "regime": auth.regime,
            "engine": "llm" if auth.reason.startswith("llm") else "heuristic",
            "reason": auth.reason,
            "on_thread_count": len(auth.on_thread_indices),
            "heuristic_regime": "task" if c["is_task"] else "forest",
            "n_turns": c["n_turns"],
            "on_turns": sorted(c["on_turns"]),
            "ratio": round(c["ratio"], 3),
            "span": c["span"],
            "thresholds": {"min_turns": self.min_turns, "ratio": self.min_ratio,
                           "min_span": self.min_span},
            "linking_tokens": linking_tokens,
            "turns": turns,
        }


def get_regime_detector(agent: Any) -> RegimeDetector:
    """懒创建并缓存到 agent(常驻姿态,呼应 context_compressor)。"""
    det = getattr(agent, "_contextvis_regime", None)
    if det is None:
        det = RegimeDetector()
        try:
            agent._contextvis_regime = det
        except Exception:
            pass
    return det
