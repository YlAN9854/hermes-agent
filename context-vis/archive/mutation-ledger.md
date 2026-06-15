# 结构突变账本（mutation ledger）—— ⚠️ 已废弃（被简化取代）

> **状态:⛔ 已废弃,不实现。** 经讨论判定**过度设计**——见下「为什么废弃」。
> 取而代之的简化方案:**诚实显示压缩块即可,不重建被销毁的拓扑**,落在
> [turn-band.md](../turn-band.md) §4。本文作为**决策痕迹**保留,别让后人重走这条弯路。

## 为什么废弃（决策痕迹）

本设计的前提是:「Hermes 压缩销毁了轮次拓扑 → ContextVis 必须把它**找回来**」。
这个前提**站不住**,有两个致命反驳:

1. **不变量是突变层的事,不是可视化的事。** 维护 agent 运行所需的结构不变量(角色交替、
   工具对配对、头尾完整)由**改 context 的那一刻**负责——Hermes 自动压缩已做,ContextVis 的
   `context.fold`/`context.apply` 也已复用 `_sanitize_tool_pairs`。可视化只显示一段**已合法**的历史,
   不该也不需要管这些。所以"扛过突变"不是 viz 要解的题。

2. **turn 带的目的是"选中一个可操作的语义单元"——而折叠后,中段已经是一个单元了。** 原始轮
   (提问/工具/结果)被折成摘要后**已不存在、无法再单独选中**。所以"重建压缩前的逐轮拓扑
   (第1–5轮〔topics〕)"对核心目的**毫无用处**——你只能、也只需对**整个压缩块**操作。审计需求
   也由"点开折叠块读摘要"满足,不需要账本。

⇒ 正确做法不是"找回被销毁的拓扑",而是**如实标注"这里有一个压缩块"**:识别压缩产物 →
画成「压缩 context」折叠块、**摆在正确位置、不冒充对话轮**。代价:幸存的近几轮会**重编号**
(原第8轮显示成第3轮)——接受它(连续编号反而不易困惑)。这套**无需任何突变期机器**
(账本/出处/稳定键/递归合并全不要),只是把分块层的 boilerplate 识别**对齐 regime 全集**。

> 若将来真需要"折叠了几轮"这种轻量信息,那也只是在突变点记一个**计数**(非全账本),
> 届时单独评估。本文档的"两咽喉一本账"重机器**不予采纳**。

---

<details>
<summary>以下为已废弃的原设计(仅存档,不实现)</summary>

> **(原)一句话**:上下文的轮次拓扑会被三种突变损毁(自动压缩 / 手动 fold / 手动 drop)。
> 损害**同质**,故不钩"压缩"而钩"**结构突变**":每次突变前算出被折/删轮次的结构,作为
> **折叠出处(fold provenance)**记进账本、挂上折叠块。band 据此画"已折叠 第1–5轮〔主题〕→ 摘要"。

---

## 1. 问题:band 跑在压坏的历史上(为什么是本质)

压缩的**工作就是销毁中段真实轮**(折成摘要)以回收 token。它一跑,原始轮次拓扑就**真的从
context 消失**,被换成几坨摘要块。turn 带靠数当前(突变后)history 的 user 消息切轮,于是:

- 看不见被折掉的真实轮(电竞/精酿轮已不存在);
- 把摘要/todo-注记等**压缩产物当成对话轮**(实测:第2/3轮全是 `[active task list preserved…]`);
- 轮号错乱(产物冒充轮、顶高编号)。

> 这不是 bug,是**信息已被销毁**。光在残骸上修分块永远是打地鼠——必须在**销毁发生之前**留痕。

---

## 2. 范围纠偏:钩"结构突变",不钩"压缩"(统摄三场景)

原"压缩前快照"只盯自动压缩。真相:**三种突变损害同质**——都是"把一组真实轮折叠/删除、拓扑就地损毁"。
故 ② 的正确范围:**在任何会折叠/删除轮次的突变前,快照当时结构。**(keep 不改 history → 无突变 → 不留痕。)

| 场景 | 突变入口(代码) | 钩点 |
|---|---|---|
| **1. 未达阈值,手动 drop/fold** | `context.apply`([server.py:4694](../../tui_gateway/server.py#L4694))/ `context.fold`([:4795](../../tui_gateway/server.py#L4795)) → 都走 [`_commit_history_mutation`](../../tui_gateway/server.py#L4657) | **手动咽喉**:该函数已在突变前抓 `before` 快照(undo,[:4672](../../tui_gateway/server.py#L4672))——留痕几乎免费 |
| **2. 达阈值后,手动管理** | 同上(闸门二阶段"闸内编辑"也落到 fold/drop) | 同场景 1,**同一咽喉** |
| **3. 自动压缩** | `_compress_context`(4 处:阈值路 [3825](../../agent/conversation_loop.py#L3825) + 反应式 2527/2701/2857) | **自动咽喉**:在 `_compress_context` **入口**抓 before,一钩覆盖 4 个调用点 |

> **两咽喉、一原语、一本账。** 手动侧已现成 `before`;自动侧加一处入口钩子。

---

## 3. 核心数据:折叠出处(fold provenance)挂在折叠块上

**不做全局重编号、不给每条消息盖 id**(消息会被压缩重写、易丢)。改为最小且抗递归的模型:

> **每个折叠块携带它subsume 的原始轮结构。**

```
FoldProvenance = [ { turn, label, tokens, topic? } , … ]   // 被这块折叠的原始轮
```

- **产生(突变时)**:突变握有 `before` + 被折/删的 message 下标集。对 `before` 跑现有分块的
  轮派生([chunking._segment_history](../../agent/contextvis/chunking.py))→ 得这些下标落在哪些真实轮 +
  其 label/tokens → 即 provenance。(`topic` 待 [turn-band.md](../turn-band.md) 第二刀的逐轮主题落地后填。)
- **抗递归(关键)**:若 `before` 里**本就含**更早的折叠块(压缩的压缩),那块**自带 provenance**
  (从账本查)。新折叠的 provenance = (折叠范围内的真实轮,分块派生) **∪** (范围内旧折叠块的 provenance,
  账本查表后**合并**)。于是"摘要的摘要"自然展开成全部原始轮,无需全局重放。
- **drop**:无摘要块承载 → 记一条 `kind=drop` 的 provenance(被删轮),供"墓碑"展示(§6)。

> 相比给每轮盖稳定 id(要把 id 串过压缩重写,易丢),**出处只挂在我们自己创建的折叠块上**(数量少、可控),
> 递归靠"再折叠时合并旧出处"消化——更省、更稳。

---

## 4. 两咽喉一原语:`record_structural_mutation`

```
record_structural_mutation(session, before_history, folded_indices, summary_key, kind)
    # 1. 用 _segment_history(before) 把 folded_indices → [{turn,label,tokens}]
    # 2. 合并 folded_indices 命中的旧折叠块的 provenance（账本查表）
    # 3. 写账本： session["_cv_fold_ledger"][summary_key] = merged_provenance
```

- **手动侧**:在 [`_commit_history_mutation`](../../tui_gateway/server.py#L4657) 抓 `before` 的同一处调用
  (drop/fold 共用);`summary_key` = 新摘要块的稳定键(§7),drop 无摘要 → 记墓碑条目。
- **自动侧**:在 `_compress_context` 入口抓 `before`、出口拿 `head_end/tail_start` 与新摘要 → 调同一原语。
- **与 undo 配对**:手动突变可撤销([context.undo](../../tui_gateway/server.py#L4897) 还原 `before`)→
  撤销时**同步回滚账本**(弹出刚记的条目)。账本与 history 必须同生共死,否则出现孤儿出处。

> 一个原语、两处调用。`kind` 标 fold/drop/compress,但 provenance 形状一致——**对具体 action 不可知**,
> 故未来交互升级(多命名组/合并/闸内批量)不推翻本设计。

---

## 5. band 如何消费

1. **后端附挂**:[build_snapshot_chunks](../../agent/contextvis/chunking.py#L411) 给每个 `folded` 块
   按 `summary_key` 查账本 → 在 [`_chunk_dict`](../../agent/contextvis/chunking.py#L499) 写
   `foldedTurns: [{turn,label,tokens,topic?}]`。
2. **契约**:`ContextChunk` 加 `foldedTurns?: {turn,label,tokens,topic?}[]`(承接 A 已加的 `folded`)。
3. **渲染**:[`TurnBand`](../../web/src/components/ContextVisPanel.tsx) 把折叠块标题从"已折叠摘要"升级为
   **"已折叠 第1–5轮〔主题〕→ 摘要"**;点击 → inspector 列出被折轮的 label(原文已无,见 §9)。

闭环:A 把摘要标成 `folded` 块(不冒充轮)→ ② 给该块补"折了哪些轮"→ band 还原拓扑。

---

## 6. drop 的处理(待定 UX)

drop 删消息、无摘要。两种画法:
- **墓碑**:画一条极薄的"已删 第N轮"刻度(CLAUDE.md 第 6 条干预透明),可折叠隐藏;
- **隐去**:用户主动删的就是噪音,不留痕,只在账本留审计。

倾向**默认极薄墓碑 + 可一键隐藏**:既守透明,又不让清理过的会话被墓碑塞满。**这是本 doc 唯一的纯 UX 待决点。**

---

## 7. 稳定键 / 持久化(主要实现风险)

**`summary_key` 怎么稳定标识一个折叠块**(它会随 history 突变位移):

- **首选**:摘要消息上挂自定义元字段(如 `_cv_fold_key`)。**前提需先验证**:`session["history"]` 的
  自定义键能否扛过对话循环 + 压缩重写而不被剥离(发模型的清洗副本可丢,**内部 history 须留**)。
- **回退**:摘要内容 hash 作键(非侵入,但摘要被下游改写则失效);或在摘要文本里嵌一个短 id token。

**持久化**:账本 `session["_cv_fold_ledger"]` 随 session 常驻(像 `_contextvis_undo`/`history`),
跨轮存活、**进程重启丢失**(v1 可接受——快照/usage 本就是运行时态)。长会话只增不大(每折叠块一条)。

> 实现第 0 步即验证"自定义键能否存活"。存活 → 首选;否则回退 hash。这决定整套的健壮度。

---

## 8. 前置依赖:先把 ① 做进来(boilerplate 对齐)

② 算 `before` 结构时,要求**所有压缩产物都已被认成 `folded` 块**(否则旧摘要又被当真实轮、出处算错)。
A 只认了 `_SUMMARY_END_MARKER` 一种;须扩成 **regime 的全集**——复用
[`regime._is_boilerplate`](../../agent/contextvis/regime.py#L99) 的 `_BOILERPLATE_MARKERS`(5 个),
让 `[active task list preserved…]` 等也标 `folded`。**这是 ② 的第 0 步,非可选。**

> 区别牢记:regime 为**检测**把样板隐形;band 为**占用诚实**(CLAUDE.md 第 1 条)须**显示成折叠块**,
> 只是不当轮次。两层对齐 marker 集,但可见性相反。

---

## 9. 诚实边界

② 还原的是**轮次结构/拓扑 + 标签(+ 以后主题)**——能画"已折叠 第1–5轮〔电竞〕→ 摘要"。
但**折叠掉的原文回不来**(那正是压缩回收的 token,本就该没)。点折叠块只能看摘要 + 被折轮的 label,
**看不到被折轮的完整原文**。② 是还原"**有过哪些轮、谁被折了**",不是还原内容。

---

## 10. 分期

0. **boilerplate 对齐(§8)** — 分块层认全 5 个 marker → 所有压缩产物成 `folded` 块。先止血。
1. **手动咽喉留痕** — `_commit_history_mutation` 接 `record_structural_mutation` + undo 回滚;
   `foldedTurns` 串到契约 + band 渲染。先打通 fold/drop 路(场景 1/2),纯非 LLM。
2. **自动咽喉留痕** — `_compress_context` 入口钩子,覆盖 4 调用点(场景 3)。两咽喉合一本账。
3. **递归合并 + drop 墓碑** — 摘要的摘要展开(§3 合并)、drop 墓碑(§6)。
4. **(接 turn 带二刀)** — provenance 填 `topic`,折叠块按主题着色。

> 0→1 即让 band 在压坏历史上**诚实**(不冒充轮);2 补齐自动路;3 抗递归与审计;4 与主题着色合流。

---

## 11. 开放问题 / 风险

- **自定义键存活性**(§7):最大不确定项,实现第 0 步先验证。
- **`before` 的洁净度**:② 依赖 §8 把旧摘要正确标 `folded`;marker 集若漏(新版本加新样板)→ 出处算错。
- **递归合并的正确性**:压缩的压缩、fold 后又 auto-compress——合并逻辑需单测覆盖(造多级折叠)。
- **并发/版本**:手动突变在 `history_lock` 下与 `history_version` 配套;账本写入须同锁同事务,避免与并发 turn 撕裂。
- **drop 墓碑 UX**(§6):唯一纯体验待决。
- **进程重启丢账本**:v1 接受;若要跨重启,需把账本随 session 持久化(另案)。

</details>
