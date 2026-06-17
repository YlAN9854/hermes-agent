# 压缩闸门 —— 把"自动压缩"改成"用户确认的压缩"（调研证据链）

> **状态:第一阶段(预览 + 确认)+ 第二阶段 drop / fold / keep 编辑均已建成并实测通过**,见 [built.md](built.md)。
> 两暗礁被"编辑随应答带回、作用于本地 messages"的架构**消解**(非打补丁);keep-as-pin、死重喂闸门、纠正 focus 留后(见文末分期)。

> **动机**:Hermes 现在到阈值(默认 50%)就**静默** auto-compress——用户看不到改了什么、
> 无从干预。这违背 CLAUDE.md 第 6 条「干预必须透明,永不静默改动上下文」。压缩闸门:
> 在 auto-compress 触发处**拦一道**,先给用户看"会压成什么样 + 前后差异",确认后才压。
>
> **结论先行**:技术上**几乎完全复用 Hermes 已有的审批(human-in-the-loop)基建**,
> 不需要造新控制流。三个动工前未知已全部钉死(下)。这是 ContextVis 把"治理"从
> 用户主动(方向 A)扩展到"系统想动手时也必须经用户"的关键一步——覆盖面比 A-v2 更大。

---

## 统一心智模型(为何省力)

不要当成新功能,当成 **方向 A 的对偶**:

- **A 路**:**用户**写一份命运计划(drop/fold/keep)→ 预览 → `context.apply` 落地。
- **闸门**:**系统的压缩策略本身就是一份命运计划**(保头/保尾=keep、中段=fold、
  旧工具结果=drop)→ 用**同一套 treemap 叠加 + 占用投影**画出来 → 用户看→(改)→确认 → 落地。

> **fate 计划,无论作者是系统策略还是用户,都用同一种方式预览、同一条路径落地。**
> 三个阶段、乃至未来"编辑建议",都是这个抽象的变体。UI 与渲染几乎不用改。

---

## 未知 1 — 拦截点:已定位

主动压缩(到阈值就压)的确切插桩点 = [conversation_loop.py:3812](../agent/conversation_loop.py#L3812):

```python
if agent.compression_enabled and _compressor.should_compress(_real_tokens):
    agent._safe_print("  ⟳ compacting context…")
    messages, active_system_prompt = agent._compress_context(messages, ...)
```

闸门插在 `should_compress()` 命中之后、`_compress_context()` 之前。

另有 3 处**反应式**压缩(API 溢出 / 413 / long-context-tier 恢复:
[2527](../agent/conversation_loop.py#L2527) / [2701](../agent/conversation_loop.py#L2701) /
[2857](../agent/conversation_loop.py#L2857))——**v1 不碰这些**,它们是兜底安全路,保持自动。
闸门只拦**主动阈值**这一条。

---

## 未知 2 — 富载荷 + 结构化响应:支持,有现成原语

[`_await_gateway_decision(session_key, notify_cb, approval_data)`](../tools/approval.py#L1172)
是打磨好的「阻塞 agent 线程直到用户决定」原语(工具审批/危险命令/clarify 共用):

- `approval_data` 是**任意 dict** → 装得下完整预览(fate 计划 + 占用投影 + 折叠/删除清单)。
- 返回 `{"resolved": bool, "choice": str|None}`;`choice` 是**任意字符串**(现有
  "once/session/always/deny",可换成 "continue/edit/defer")→ 不止是非。
- 内置 **timeout**(默认 300s,config `gateway_timeout`)+ **每秒心跳**
  ([approval.py:1247](../tools/approval.py#L1247),防 watchdog 杀掉等待中的 agent)。

底层数据结构 [`_ApprovalEntry`](../tools/approval.py#L627):`event=threading.Event()` +
`data=dict` + `result=str`;`register_gateway_notify` 发请求、`resolve_gateway_approval`
解阻塞([approval.py:666](../tools/approval.py#L666))。server.py 已把它接成
`register_gateway_notify(key, lambda data: _emit("approval.request", sid, data))`
+ `@method("approval.respond")`。

> 压缩闸门 = **新增 `kind="compaction"` 载荷 + 新增 `compaction.respond` 方法**
> (转 `resolve_gateway_approval(key, choice)`),其余直接套用。新基建极少。

---

## 未知 3 — 交互判定 + 超时回退:免费,且天然保护无人值守

- 闸门只在 `_gateway_notify_cbs.get(session_key)` **存在**(有 dashboard 附着)时触发;
  无人值守 CLI / cron **没有这个 cb → 直接走原 auto-compress**,行为不变。
- 超时(300s 无人理)→ `resolved=False` → 按"继续"自动压。
- **无人值守绝不被挂死**——结构性保证,无需额外代码。

闸门因此是「自动」与「`compression.enabled=false` 全禁」之间的**第三档**:交互时确认、
非交互时自动。

---

## 分期 + 第二阶段的两个暗礁

- **阶段 1(纯预览 + 继续)**:拦 3812 → 发**结构预览** → 用户「继续 / 推迟」→ 跑原
  `_compress_context`。**不编辑**,故无下列暗礁,真低风险。复用 A 路视觉 + approval 原语。
- **阶段 2 首刀(闸门内 drop 编辑)— ✅ 已建成实测**。两暗礁原以为"必须先解",实则被一个**更干净的
  架构直接消解**(而非给 `context.apply` 打补丁):**把编辑随闸门应答带回,由被阻塞的那个循环线程自己
  把 drop 作用到本地 `messages`**(`compaction_gate.apply_gate_drops` 用 `message_indices_for_chunks({"history": messages})`
  解析 → 删 → `_sanitize_tool_pairs` 缝合)。单线程、无并发、不碰 `session["history"]`、不调 `context.apply`:
  1. **running 守卫**——压根不调 `context.apply`,守卫不动、其他 running 期仍拒(安全)。**消解**。
  2. **messages/history 对账**——直接改循环本地 `messages`(就是会被压缩的那份),无两份历史。**消解**。
  - **keystone**:让应答携带编辑载荷(`tools/approval.py` 的 `_ApprovalEntry.result_extra` +
    `resolve_gateway_approval(extra=)` + `_await_gateway_decision` 返回 `extra`;`compaction.respond` 经 extra 带回
    `drop_chunk_ids`)。加法兼容,工具审批不传 → None。**此通道同时解锁"闸门内纠正 focus""死重喂闸门"**。
  - **band↔inspector 同步**:闸门时两者都画 `systemFate ∪ 用户 fateMap`(`ContextVisPanel.effectiveFateMap` /
    `ChatPage.displayFateMap`),用户标记覆盖系统计划。见 [built.md](built.md)。
- **阶段 2 第二刀(闸门内 fold/keep 编辑,方案 A)— ✅ 已建成实测**。把"只能删"升级到"**改写折叠计划**":
  保护中段某轮不进摘要(keep)、补折系统漏掉的支线(fold)。**方案 A**:用户编辑出的有效 fateMap = 权威落地计划,
  直接 apply、**跳过位置式 `_compress_context`**(它纯位置式、不认手标 fold/keep,要让编辑生效就不能再当落地器;且不碰
  与三条反应式路共用的核心压缩函数)。落地复用手动 `context.fold` 同一套(`_generate_summary` + `splice_fold_summary` +
  `_sanitize_tool_pairs`),统一进 `compaction_gate.apply_gate_plan(drop_ids, fold_ids, focus)`(drop/fold 按同一份原始
  messages 解析、drop 优先、**先过滤 drop 再重映射 fold 下标消除漂移**、摘要失败降级仅删除);`apply_gate_drops` 委托它。
  - **四选择 + 推迟**:直接压缩(`continue`,位置式不动)/ 应用计划(`apply_plan`,有效 fold+drop 直接落地)/
    仅删除(`edit_only`,只删不折)/ 推迟。banner 占用投影改用 `projectFates(effective)`(确认前看得见)。
  - **keep 的归宿**:本刀 keep = **「取消系统预折」**(合并里用户覆盖 systemFate 的 fold,**免费**);
    用户设想的"提升到持久免压区"= **keep-as-pin**(正向持久保护、场景小)单独设计,本刀不做。
  - **可读性「命运沟」**:闸门时每轮都被派命运,改为 **fold 压暗后退 + 左缘 4px 命运沟**(keep 绿/fold 橙/drop 红)一眼分清。
  - **在途 spinner**:应答后→压缩后快照前的沉默期(后端跑摘要数秒)显示「正在应用计划…」,新快照到达自动消失。
  - **剩(各自后续,均复用 extra keystone / apply_gate_plan)**:**keep-as-pin**、**死重清单喂闸门**、**纠正 focus**。
- **横切:编辑建议**:系统预先 mark 一份建议 fate(失败工具结果 / 重复读同一文件 /
  久未触及支线)→ 用户增删 → 确认。即 roadmap 的"建议策略注册表",UI 一行不改。

---

## 两点顺带钉死

- **"推迟/不压"天然有界**:即便一直推迟,占用最终撞 provider 硬上限,触发那 3 条**反应式**
  压缩兜底(或 `compression.enabled=false` 时终端报错)。推迟是安全的——硬顶会接住。
- **预览保真度(阶段 1 的设计叉)**:压缩器 keep/drop 选择是**位置式、确定性**的,只有
  中段**摘要文本**要跑辅助模型。故"结构预览"(哪些轮折叠、哪些旧工具结果删、占用
  `78%→41%`)**可零 LLM 即时算出**;真实摘要文本留到点「继续」之后。
  → 阶段 1 建议做**结构预览**,不预付 LLM 成本。

---

## 与方向 A 的复用边界

| 复用自 A | 闸门里用作 |
|---|---|
| treemap 命运叠加 + `projectFates` 占用投影 | 画"系统的压缩计划" + 前后占用差异 |
| `context.apply`(drop)/ 未来 fold | 阶段 2 的"在闸门内编辑" |
| `_await_gateway_decision` + approval 基建(本调研) | 拦截 + 阻塞 + 超时 + 交互判定 |

**新增的只有**:拦截插桩(3812)、算"系统 fate 计划"用于展示、`compaction.request/respond`
事件对、前端闸门 UI。
