# 方向 A-v2 · fold —— 让"应用"能折叠(不只删除)

> **状态:已建成并实测通过**(单测 10/10 + dashboard 端到端:跨轮非连续折叠 →
> treemap/TUI 占用回落、token 真减、原位出现摘要、可撤销)。要点见 [built.md](built.md)。
> 满足的用户需求:[needs.md](needs.md) R10(折成摘要)、R11(跨类型同语义合并)、
> §E 工作流的 E1(收纳支线)。

> **一句话**:方向 A 的「应用」v1 只能 `drop`(删整条消息)。fold 让用户把选中的几块
> **折成一条摘要**——保留要点、丢掉冗长。这是 needs §E「主线/支线同 session」里**收纳支线**
> 的核心动作:用户把一个支线涉及的跨类型块(提问 + 工具调用 + 结果)一起折成一句话。

---

## 范围(已与用户敲定)

- **仅非对话态 treemap 交互**:session 空闲时操作。**这不是妥协,是主动避开两暗礁**——
  空闲无 running 锁冲突(`context.apply` 本就放行),且 `session["history"]` 是唯一真相,
  不存在"循环本地 `messages` ↔ history 对账"(那两坑留给压缩闸门第二阶段,见
  [compaction-gate.md](compaction-gate.md))。
- **单隐式组**:所有当前 fold 标记 → **一条**摘要。多命名组 = 多次单组操作即可等价,留后。
- **action 原子化**:一次 apply 只 fold 或只 drop,不混。混用留 v1 测过之后。
- **支持非连续**:用户的核心诉求(收支线)本质就是非连续;靠自动缝合工具对 +
  `_sanitize_tool_pairs` + 透明预览兜住。

---

## 增量很小(已有 vs 缺失)

fold 的**标记**其实早已建好(方向 A 阶段 1+2):检视器「折叠」按钮写入 `fateMap`、
`projectFates` 已按 `summary_target_ratio=0.20` 投影释放 ~80%、treemap 已画虚线边。
**缺的只是落地路**——`droppableChunkIds` 只挑 drop、`context.apply` 只删不折。

| 环节 | 现状 | A-v2 |
|---|---|---|
| 标记 fold / 预览 / treemap 叠加 | ✅ 已建成 | 不动 |
| 选 message 索引 | ✅ `drop_indices_for_chunks` | 泛化为可复用 |
| 摘要轮子 | ✅ `_generate_summary(turns, focus_topic)` | **直接复用** |
| 落地 | ❌ 只有 drop | **新增 `context.fold`** |

---

## 关键复用(不造轮子)

| 复用 | 位置 | 用途 |
|---|---|---|
| `_generate_summary(turns, focus_topic)` | [context_compressor.py:1233](../agent/context_compressor.py#L1233) | 把 fold 块摘要化;`focus_topic` **正好**装用户重心 prompt(灵感本就是 `/compact`) |
| 摘要消息 role 选择 + END 尾标 | [context_compressor.py:2130-2164](../agent/context_compressor.py#L2130) | 抽成 `_summary_message(prev_role, next_role, summary)`,fold 与默认压缩共用 |
| `_sanitize_tool_pairs` | [context_compressor.py:1618](../agent/context_compressor.py#L1618) | splice 后缝合孤儿 tool 配对 |
| `context.apply` 落地骨架 | [server.py:4657](../tui_gateway/server.py#L4657) | 抽 `_commit_history_mutation` 供 drop/fold 共用 |
| `context.undo` | [server.py:4746](../tui_gateway/server.py#L4746) | fold 同写 `_contextvis_undo` → **零改动复用** |
| LLM-in-handler + `_status_update` 模式 | [server.py:4561](../tui_gateway/server.py#L4561) `session.compress` | fold 是同形态(handler 里跑摘要、进度提示) |
| `projectFates` / treemap fold 叠加 | web plan.ts / ContextVisPanel.tsx | 预览不动 |

---

## 后端

1. **泛化索引解析**(chunking.py):`drop_indices_for_chunks` → `message_indices_for_chunks`
   (逻辑不变,只收 `messageIndex`;system/tool_schema 自动忽略)。旧名留 thin alias。drop/fold 共用。
2. **新 RPC `context.fold`**(server.py),镜像 `context.apply`:
   - 入参 `fold_chunk_ids: []` + `focus_prompt: str`(可空);门控 / running 拒 4009 / 陈旧拒 4409 同 apply。
   - 摘要:`turns = [before[i] for i in sorted(fold_idx)]` → `_generate_summary(turns, focus_topic=focus_prompt or None)`;
     跑前 `_status_update(sid,"compressing","⠋ 折叠 N 块…")`,`finally` 复位。
   - **非连续 splice**:在**最早 fold 索引位**插摘要消息、跳过所有 fold 索引、其余原样 →
     `_sanitize_tool_pairs`。
   - 失败(`_generate_summary→None`)→ **整笔中止**:history 不动,返回 5006「摘要不可用,请重试」。
3. **共享落地 helper** `_commit_history_mutation(session, agent, before, new_history, v0, sid)`:
   快照 undo + 写 history + bump 版本 + 重算 `last_prompt_tokens` + emit + 返回。drop/fold 都调,去重。
4. **撤销**:`context.undo` 复用,fold 写同一 `_contextvis_undo`。

## 前端

5. **plan.ts**:`foldableChunkIds(snapshot, fateMap)`(镜像 droppable,挑 `fate==="fold"` 且 message 背书)。
6. **apply.ts**:`applyFold(sessionId, historyVersion, foldChunkIds, focusPrompt)` → `request("context.fold",…)`,复用 `ensureClient`。
7. **ContextVisPanel.tsx**:预览行加「应用 fold」(与「应用 drop」并列,action 原子化);
   fold 确认态展开**重心 prompt 输入框**(可空);running 文案"折叠中…";成功后复用现有撤销。

---

## 非连续 splice 的三个保真点(护栏)

1. **工具对完整**:`_sanitize_tool_pairs` 在最终列表缝合任何因 fold 留下的孤儿
   `tool_call`/`tool_result`(摘要已含其内容,删孤儿安全)。
2. **摘要落点**:一条摘要落在**最早被选消息的原位**——支线被"收"在它开始的地方,符合心智。
3. **role 合法**:`_summary_message` 选不撞左右邻居的 role;两头都撞 → 合并进下一条(抄压缩器既有兜底)。

---

## 安全 / 不变量

- **透明,绝不静默**:失败整笔中止、绝不半落地;预览(`projectFates` + treemap)先于落地(CLAUDE.md 第 6 条)。
- **非对话态限定**:无 running 闸冲突、无 messages↔history 对账(两暗礁留压缩闸门二阶段)。
- **可撤销**:一步 `_contextvis_undo`;`history_version` 陈旧校验防过时视图误折。
- **token 比例真实**:落地后 `estimate_request_tokens_rough` 重算占用(摘要文本可数),不冒充精确。

## 不做(本轮排除)

多命名组 · fold+drop 一次混用 · 闸门内 fold(二阶段)· 语义分块/排列(选择层,另立 needs E3/E4)。

---

## 与方向 A 阶段 3(drop)的关系

fold = drop 的同胞:同一套标记 / 预览 / treemap / undo / 陈旧校验 / `_commit_history_mutation`,
只把"删消息"换成"摘要替换"、多一次 LLM 调用 + 失败中止。落地后,方向 A 的命运三件套
(keep/fold/drop)在用户主动治理一侧**补齐**;系统触发一侧(压缩闸门)的 fold 留二阶段。
