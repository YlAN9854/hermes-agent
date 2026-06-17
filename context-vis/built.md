# 已建成 & 决策日志

> 做了什么(按里程碑)+ 每个关键取舍为什么这么定。回顾"现在到哪了"看这份。
> 入口与契约见 [CONTEXTVIS.md](CONTEXTVIS.md);运行/调试见 [dataflow.md](dataflow.md)。

---

## 已建成

### 档1 — 真实占用容器视图(commit `cb9cab85f`)
占用条 + `used/budget/percent` + 压缩标记 + 占用率 sparkline。数据来自网关
`session.info` 事件里的 `usage`(真实计数 + 真实窗口)。零后端改动。

### 档3 — 真值分块 + 带状 treemap 浮层(commit `510e72699`)
- **后端** `agent/contextvis/chunking.py`:
  - **Segmenter** 读三源:`build_system_prompt_parts(agent)`(system 3 段)、
    `agent.tools`(每工具一段)、`session["history"]`(历史/文件/工具结果,按
    `tool_call_id` 配对回参数)。token 用 `estimate_messages_tokens_rough`(chars//4),
    **整体缩放**到真实 `last_prompt_tokens`。每 chunk 带 `sourceRefs`(provenance)。
  - **ChunkStrategy 注册表**(按渲染带可插拔)。
- **网关** `tui_gateway/server.py`:`_emit_session_info` 包装在 `session.info` 旁
  co-emit `context.snapshot`(同 `/api/events` 通道),带 `compact_at`(压缩阈值)。
  `HERMES_CONTEXTVIS` 可关、best-effort。
- **前端**:`ContextVisOverlay`(浮层,440px,可折叠)+ `ContextVisPanel`
  (squarified 带状 treemap,双模式)+ `treemap.ts`(squarify 布局)。

### resume 占用修复(commit `efc56bd9e`)
resume 重建 agent → `last_prompt_tokens=0` → 原生条与 ContextVis 都显示 0。
两处修:后端 `_seed_context_tokens_from_history`(按已载入历史粗估播种)+ 前端
adapter 回退(usage=0 时用 chunk 总和补出占用)。

### 原文检视器(方向 C,commit `68ce781a0`)
点浮层 treemap 某 chunk → 右侧栏 `ChunkInspector` 显示**完整原文**:system
prompt 节、tool schema JSON、工具调用详情、文件内容、对话原文。其中
**system/tools 在终端对话里根本看不到,检视器是唯一入口**——补全白盒的
「可追溯」。后端每 chunk 随 `context.snapshot` 带原文(成员拼接,**32KB 截断**,
`HERMES_CONTEXTVIS_RAW=0` 可关)。选中态上提 ChatPage,浮层(地图)↔侧栏(详情)
master-detail 联动。**删除右侧栏 MODEL/TOOLS**(原 `ChatSidebar`),右侧栏改作检视器。

### 交互式压缩 · 阶段 1+2(方向 A,纯前端零风险)
视图从"观察"升级到"治理"的第一步:用户**手动标记** chunk 的命运 + **实时预览**释放量。
- **核心层** `web/src/lib/contextvis/plan.ts`:`projectFates(snapshot, fateMap)` 纯函数
  (即 roadmap 的 `context.plan` 纯投影),按 Hermes 压缩语义算释放——
  **drop 释放 100% / fold 释放 80%(对齐 `summary_target_ratio=0.20`)/ keep 0**。
- **检视器** 加 **保留/折叠/丢弃** 按钮(各带"释放 ~Xtok"估算)+ 恢复。
- **浮层** treemap 命运叠加(drop 红斜划+降透明 / fold 虚线边 / keep 实线边)+ 占用条
  **幽灵目标刻度** + 预览行 `丢弃×2 折叠×1 · 预计释放 ~45K · 78%→52%` + 清除标记。
- **状态**:命运存 ChatPage 的 `fateMap`(用户意图),**不写回 `snapshot.chunks`**
  (`ContextChunk.fate` 留给阶段 3 的后端确认)。chunk id 确定性,标记跨快照重发存活;
  孤儿条目惰性(消费方只按当前 chunks 查表),无需主动剪除。
- **零副作用**:阶段 1+2 不碰 server.py、不发命令、不改真实上下文(命运只是前端意图)。

### 交互式压缩 · 阶段 3 v1(应用 drop,落地真实上下文)
治理闭环最后一步:把标记的 **drop 真正从真实 agent 的上下文删除**。通道已坐实(见
[phase3-channel.md](archive/phase3-channel.md)),v1 **只做 drop、确定性、零 LLM**(fold 留 v2)。
- **后端**`tui_gateway/server.py`:新 RPC `context.apply`(删消息 → 复用
  `ContextCompressor._sanitize_tool_pairs` 缝合孤儿 tool 配对 → 写回 `session["history"]`
  + bump `history_version` + 重置 `last_prompt_tokens` 让占用即时回落 → re-emit)与
  `context.undo`(一步撤销快照)。`context.snapshot` 载荷补 `history_version`。
- **映射**`agent/contextvis/chunking.py`:`drop_indices_for_chunks` 用 `sourceRefs.messageIndex`
  把 drop 的 chunk 翻成真实 history 下标;**只认 history/file/tool_result**,system/tool_schema
  无 messageIndex 自动忽略。
- **前端**`web/src/lib/contextvis/apply.ts`(复用 `GatewayClient` 发 RPC,sid 从事件帧拿);
  浮层预览行加「应用 drop」+ 两步确认 + 不可逆提示 + 成功后「撤销」+ 错误行;
  检视器对 system/tool_schema 禁用命运按钮。
- **守卫**:`running` 拒(4009)、`history_version` 陈旧拒(4409)、门控 `HERMES_CONTEXTVIS`。
- **实测通过**:标多轮用户输入 → 丢弃 → TUI 占比 + treemap 同步回落、token 真减少;撤销还原;
  对话进行中应用被礼貌拒绝。**v2 = fold**(复用 `_generate_summary`),见 [roadmap.md](roadmap.md)。

### 压缩闸门 · 第一阶段(把 auto-compress 从静默改成用户确认)
ContextVis 最贴使命的一块:Hermes 到阈值就**静默**压缩,违背「干预必须透明」。闸门在
auto-compress 触发处拦一道,把"系统的压缩计划"用 treemap 画给用户看 + 占用前后投影,
**确认(继续)或推迟**后才压。调研证据链见 [compaction-gate.md](compaction-gate.md)。
- **复用审批基建,不造新控制流**:`agent/compaction_gate.py` `request_compaction_decision`
  用 [tools/approval.py] 的 `_await_gateway_decision`(阻塞 agent 线程 + 300s 超时 + 心跳)。
  超时 / 无 dashboard(无 notify_cb)/ 未开闸 → 返回 None → 照常自动压(**无人值守天然安全**)。
- **统一模型**:系统压缩策略 = 一份 fate 计划(保头尾=keep、中段=fold)。
  `ContextCompressor.plan_compaction`(纯函数,零 LLM,复用 `_protect_head_size` /
  `_find_tail_cut_by_tokens` 算边界)→ chunk 按 `sourceRefs` 落点派系统 fate →
  **用 A 路同一套 treemap 叠加 + 占用投影**画出来,作者从"用户"换成"系统"。
- **插桩** [conversation_loop.py:3812](../agent/conversation_loop.py#L3812)(should_compress 命中后、压缩前);
  只拦主动阈值路,反应式溢出压缩保持自动兜底。
- **RPC**:server.py 注册的 notify lambda 加 `_event` 路由 + 新 `compaction.respond`(镜像 approval.respond)。
- **前端**:`gate.ts respondCompaction`(复用 apply 的 `/api/ws`);`ContextVisPanel` 闸门条
  (`X%→~Y%` + 折叠 N 轮 + 继续/推迟)+ 闸门激活时 treemap 改画系统计划(`effectiveFateMap`);
  `ContextVisOverlay` 待决时自动展开。门控 env `HERMES_CONTEXTVIS_GATE`(默认关,opt-in)。
- **闸门 turn 中途触发的两个一致性修复**:① 闸门事件 + 压缩后都**主动补发新鲜快照**
  (`emit_post_compaction_snapshot`,经 notify 桥,`build_snapshot_chunks(scale_to=)` 缩放)——
  否则 treemap 卡在轮初/压缩前;② 「压缩 ×N」改用**真实累计计数** `compressionCount`
  (一轮多次 mid-turn 压缩,推断事件会少计)。
- **实测通过**:顶过阈值 → 闸门条 + treemap 画系统计划 → 继续→真压、treemap/占用/次数同步回落
  与 TUI 一致 / 推迟→本轮不压、下轮再问;关旗标 → 回到静默自动压。**第二阶段 = 闸门内编辑**
  (开放 drop/fold),需先解 running 闸冲突 + `messages`↔history 对账,见 [compaction-gate.md](compaction-gate.md)。

### 交互式压缩 · A-v2 fold(折成摘要而非整删)
方向 A「应用」从 drop(整删)补齐到 **fold(折成摘要)**:用户跨轮、跨类型、可非连续地
选几块 → 一条摘要替换它们,**收纳支线**(needs §E E1)。设计与复用边界见 [fold.md](fold.md)。
- **增量极小**:fold 的标记/预览/treemap 叠加在阶段 1+2 早已建好;只缺落地路。
- **复用摘要轮子**:`ContextCompressor._generate_summary(turns, focus_topic)` 直接吃任意
  message 列表 + 用户重心 prompt(`focus_topic` 本就是 `/compact` 的灵感)——一行不改。
- **两个纯函数抽取(fold 与默认压缩共用)**:`_summary_message(prev,next,summary)`(摘要
  role 选择 + 两头堵则合并进尾,默认压缩 `compress()` 改用它、行为不变)、`splice_fold_summary`
  (**非连续** splice:一条摘要落最早 fold 位、其余移除,`_sanitize_tool_pairs` 缝合孤儿工具对)。
- **后端**:`message_indices_for_chunks`(泛化自 `drop_indices_for_chunks`,drop/fold 共用)、
  `_commit_history_mutation`(抽自 `context.apply`,drop/fold 共享落地)、新 RPC
  [`context.fold`](../tui_gateway/server.py)(摘要失败 → **整笔中止** 5006、绝不半落地;
  running 拒 4009 含 LLM 期间二次确认;陈旧拒 4409;`context.undo` 零改动复用)。
- **前端**:`foldableChunkIds`、`applyFold(…, focusPrompt)`、`ContextVisPanel` 加「应用 fold」
  (action 原子化,与 drop 并列)+ 确认态展开**重心 prompt 输入框** + 「折叠中…」态。
- **单测 10/10**:role 选择全组合、非连续/乱序/越界 splice、索引别名(`tests/test_contextvis_fold.py`,自定位 sys.path 绕开 `~/.hermes` 安装副本)。
- **实测通过**:跨轮非连续标 fold → treemap/TUI 占用回落、token 真减、原位现摘要、可撤销。
  **单位文案修正**:TUI 进度从「折叠 N 块」改「折叠 N 块(M 条消息)」——treemap 数 chunk、
  消息数是其展开(一轮捆多条),两者本就不同,讲清单位免误判。

### 任务态识别 · 自适应总开关(让闸门"森林闭嘴、任务才出声")
ContextVis 的**脑**:压缩闸门从"逢阈值就弹"升级为**自适应**——只在"位置式压缩将要背叛
你的任务"时才打断。设计与判定依据见 [regime.md](regime.md)。
- **两级门控**(`compaction_gate._should_gate_for_regime`):**A 级** regime(有没有主线)∧
  **B 级** collision(这次压缩的折叠区是否触及主线 turn)才弹;否则静默自动压。复用
  `plan_compaction` 的折叠区间,接进已建成的 `request_compaction_decision`。
- **检测器** [`agent/contextvis/regime.py`](../agent/contextvis/regime.py)`RegimeDetector.assess(messages, agent)`,
  常驻挂 agent。**两个引擎**:
  - **第一刀 · 廉价启发式**:依据**跨 turn 复现的具体产物**(文件路径段 + 代码标识符,减去
    工具名/基础设施段/压缩样板)→ 纽带覆盖 turn 数 + 占比 + 跨度判 task。turn 切分**剔除压缩样板**
    (否则摘要残骸制造假 turn)。
  - **第二刀 · LLM 语义(权威)**:依据**目标/主题是否一致**。喂 **turn 骨架**(`_build_skeleton`:
    意图 + 工具/文件,**不喂全文**),复用压缩 aux runtime(`auxiliary_client.call_llm`),
    prompt 钉死"**用同样的工具 ≠ 同一任务,按 GOAL/SUBJECT 判**"+"**判当前多轮任务、非整段二选一**"。
    回 `{regime, mainline_turns, focus, reason}`,`mainline_turns` 映射回消息下标喂 collision。
- **为何要第二刀**:启发式被**共享工具/基础设施**骗(`web_search`/`browser_snapshot`/记忆样板
  把无关话题硬串成纽带)——这是确定性信号的天花板,实测连撞四个泄漏源(压缩残骸、网页搜索词、
  记忆/任务样板、工具名)。LLM 按语义一举分清。
- **安全**:只交互会话 + 即将弹时才调 LLM;失败/超时/无 provider → 回退启发式 → 保守森林;绝不挡压缩。
  opt-in `HERMES_CONTEXTVIS_GATE`,`HERMES_CONTEXTVIS_REGIME`(两级门控)/`_REGIME_LLM`(LLM)默认开、可关。
- **调试**:只读 RPC `context.regime` + 前端 `window.__cvRegime()`(挂当前 sid)→ 顶层 LLM 权威裁决 +
  理由,附启发式 `linking_tokens`/`turns` 对照(直接看它被什么 token 骗)。
- **单测 22/22**:salient 抽取/过滤、森林 vs 任务、压缩残骸不冒充任务、两级门控四态、逃生阀、
  LLM 路(mock aux)task/forest/失败回退/禁用。**实测**:森林(电竞/塔罗/Rust 混问)静默自动压、
  `engine:llm reason` 正确;多轮读代码任务弹闸门 + 标 focus。

### R 后续① · 焦点压缩(把检测出的 focus 接进自动压缩)
闸门触发时 `assess` 已产出的主线 `focus`,过去**弹完即弃**、自动压缩 `focus_topic=None`(焦点盲、纯位置)。
①**把脑接到手**:`focus` → 既有 `focus_topic`(`_generate_summary` 焦点 prompt:相关留全细节 60–70% 预算、
无关狠压)。**几乎全是接线,零新机制/RPC,regime.py 零改。**
- **后端**:`compaction_gate._should_gate_for_regime` 回传 `(should_gate, reason, focus)`;
  `request_compaction_decision` 把 `focus` 进闸门 payload + 返回 `{choice, focus}`;
  [conversation_loop.py:3825](../agent/conversation_loop.py#L3825) continue 时 `_compress_context(…, focus_topic=focus or None)`
  (**仅闸门这一处**;另三处压缩 + turn_context 不接,需无条件 assess、留后续)。focus 空 → 位置式回退。
- **前端(只读)**:`PendingCompaction.focus` + adapter 映射 + 闸门条加一行「将按焦点压缩: …」。
  「继续压缩」即确认该 focus(编辑 focus 需扩 shared 审批 payload,留 gate 第二阶段)。
- **验证**:stub 证 `_should_gate_for_regime` 回传 focus、`request_compaction_decision` payload 含 focus 且返回
  `{choice,focus}`;web build+lint 干净。**实测铁证**:`~/.hermes/logs/agent.log`「compression started … focus=」
  从历来 `None` → 本次 `focus='opencode agent architecture analysis'`,摘要 `## Goal` 收窄到 agent 模块。

### R 后续② 首刀 · 死重清单「建议清理」(按需主动梳理)
把"选谁折"也变聪明:**检测器自动认出"已完成的支线"→ 预填 fateMap fold → 复用第四刀的落地手**。
这是 regime.md §死重清单 的"方向 A 主动清理"路(大窗口下闸门罕触发,按需主动路才是日常主场)。
**检测器只多一个 `done` 字段,落地一行不改(铁律:检测层只产"选什么")。**
- **后端**:`regime.py` `_REGIME_PROMPT` 的 `turns[]` 加 `done`(钉死:仅线程明显完成/放弃才 true、**主线 NEVER done**、
  拿不准 false),`_assess_llm` 解析进 `turn_topics[t]["done"]`;`server.py` `context.regime_colors` 的 `chunk_topics[cid]`
  加 `done`(沿用挑 topic 同一轮取 done)。启发式路无 done → 无建议(保守)。
- **前端**:`apply.ts` `RegimeColors.chunk_topics` 加 `done?`;`setFates` 透传 ChatPage→Overlay→Panel;
  Panel turn 视图加「建议清理」按钮 → `fetchRegimeColors` → 挑 `done ∧ !mainline ∧ message-backed` → `onSetFates(ids,"fold")`
  + 顺带着色;**此后完全复用** fate 预览 +「应用 fold (N)」+ 撤销。0 条/非 LLM 给小字提示。默认 **fold 不 delete**(留痕)。
- **验证**:stub 证 `done` 经 `_assess_llm` 进 `turn_topics`、dead-weight=`done ∧ !mainline` 精确挑出已完成支线、
  **排除主线**;web build+lint 干净。**实测**:会话(opencode 主线 + "你知道opencode"引子 + "星座"跑题)→「建议清理」
  预填 7 块 fold(引子 + 跑题,主线不动)→「应用 fold」→ 44%→21%、释放 ~34.5K、可撤销;幸存轮重编号。

### G 压缩闸门 · 第二阶段首刀 · 闸门内 drop 编辑(经应答落地)
闸门从"只读二选一"升级到"**可编辑**":被迫压缩时先删垃圾再压。
**架构选择(关键):不给 `context.apply` 的 running 守卫打补丁,而是把编辑随闸门应答带回、由被阻塞的
循环线程自己作用到本地 `messages`**——单线程、无并发、不碰 `session["history"]`、不调 `context.apply`,
**两暗礁(running 守卫 / messages-history 对账)直接消解**。
- **keystone(共享审批基建,加法兼容)**:`tools/approval.py` `_ApprovalEntry` 加 `result_extra`、
  `resolve_gateway_approval(..., extra=)`、`_await_gateway_decision` 返回加 `extra`(工具审批不传 → None,回归不破)。
  **此通道同时解锁后续"闸门内纠正 focus""死重清单喂闸门"**(都需应答带回编辑)。
- **后端**:`server.py` `compaction.respond` 经 extra 带回 `drop_chunk_ids`;`compaction_gate.apply_gate_drops`
  (`message_indices_for_chunks({"history": messages})` → 删 → `_sanitize_tool_pairs` 缝合,纯函数);
  `request_compaction_decision` 返回加 `drop_chunk_ids`;`conversation_loop` 闸门处:`defer` 不变,否则先 `apply_gate_drops`,
  `edit_only` 跳过压缩、其余照常压(`continue`/`edit_compress`),统一补发快照。
- **前端**:`gate.ts` `CompactionChoice` 扩 4 值 + `respondCompaction(…, dropChunkIds?)`;`ContextVisPanel` 闸门时
  `effectiveFateMap = {...systemFate, ...fateMap}`(band 显用户 drop)+ 闸门条按 `gateDrops` 显「删除并压缩 / 仅删除」;
  `ChatPage` 同样把 `displayFateMap`(systemFate ∪ fateMap)喂 inspector,**band↔inspector 命运显示同步**(实测踩坑修复)。
- **验证**:stub 证 `apply_gate_drops`(删对消息 + 孤儿 tool 缝合 + 空/无效原样)、`extra` roundtrip(带回 drop_chunk_ids、
  无 extra→None 回归);web build+lint 干净。**实测**:两支线 + opencode 主线会话顶阈值弹闸门 → band 标 drop →「删除并压缩 / 仅删除」生效、占用回落;直接压缩 / 推迟照旧。
- **首刀边界**:闸门编辑只认 **drop**;fold/keep 改写系统计划、死重喂闸门、纠正 focus 留后(均复用上面的 extra keystone)。

### G 压缩闸门 · 第二阶段第二刀 · 闸门内 fold/keep 编辑(方案 A:编辑后的计划即权威)
闸门从"只能删"升级到"**改写折叠计划**":保护中段某轮不进摘要(keep)、补折系统漏掉的支线(fold)。
**方案 A(用户敲定)**:用户编辑出的有效 fateMap = 权威落地计划,直接 apply、**跳过位置式 `_compress_context`**——
因为 `_compress_context` 纯位置式、不认手标的 fold/keep,要让编辑生效就不能再让它当落地器;且不碰核心压缩函数(与三条反应式路共用),爆炸半径小。
- **复用(零新机制)**:fold 落地全用手动 `context.fold` 同一套——`_generate_summary(turns, focus_topic)` +
  `splice_fold_summary` + `_sanitize_tool_pairs`;解析复用 `message_indices_for_chunks({"history": messages})`。
- **后端**:`apply_gate_plan(agent, messages, drop_ids, fold_ids, focus_topic)`——drop/fold 按**同一份原始 messages**
  解析(drop 优先去重),**先按 drop 过滤再把 fold 下标重映射**到过滤后列表(消除下标漂移),生成一条摘要 splice,
  摘要失败**降级仅删除**(不半落地、不抛),异常原样返回;`apply_gate_drops` 改为薄封装委托它(单一实现)。
  `compaction.respond`/`request_compaction_decision` 多带 `fold_chunk_ids`;`conversation_loop` 闸门分支重整为
  `defer / apply_plan|edit_only(走 apply_gate_plan、跳过位置式压缩) / 否则 continue(位置式不动)`,
  `conversation_history=None`+补发快照上提为 `if choice != "defer"`(编辑路也补发)。
- **keep 的归宿(与用户讨论定)**:本刀 keep = **「取消系统预折」**(把被 systemFate 预标 fold 的中段轮改回不动,
  靠 `{...systemFate, ...fateMap}` 合并里用户覆盖系统**免费**得到);用户设想的"提升到持久免压区"= keep-as-pin,
  正向持久保护、场景小、单独设计,本刀不做。
- **前端**:`gate.ts` `CompactionChoice` = `continue/defer/apply_plan/edit_only`,`respondCompaction(…, dropIds?, foldIds?)`;
  `ContextVisPanel` 闸门时 `gateFolds=foldableChunkIds(effective)`(systemFate 中段折 ∪ 用户加折 − 用户 keep)、
  按钮重整为 **直接压缩 / 应用计划(折N删M) / 仅删除(M) / 推迟**,banner 占用投影改用 `projectFates(effective)`(确认前看得见)。
  **标记入口零新增**:cut-4 FateControls 已能标 fold/keep/drop、经 `effectiveFateMap`/`displayFateMap` 同步显示。
- **可读性打磨(用户复测点 2)**:闸门时 systemFate 给每轮都派命运,旧版只用细描边、被主题色盖住 →
  改为 **fold 压暗后退(fillOpacity 0.42)+ 左缘 4px「命运沟」**(keep 绿 / fold 橙 / drop 红),折/留一眼分清(同时改善手动标记)。
- **在途反馈(用户复测:无加载提示)**:应答后→压缩后快照到达前(后端跑摘要数秒)是沉默期 → 派生 `applying` 态
  (沿用 pending 引用比较,无 effect)在闸门原位显示 spinner「正在应用计划…」,新快照到达自动消失,60s 兜底撤销。
- **验证**:stub 证 `apply_gate_plan`(纯 fold / fold+drop 无漂移 / 重叠 drop 优先 / 空·无效原样 / 摘要失败降级 / 委托回归);
  web build+lint 干净。**实测**:opencode 主线会话顶阈值弹闸门 → 标 keep/fold/drop →「应用计划」spinner→ 占用回落、命运沟分明。
- **第二刀边界**:**keep-as-pin(持久免压区)** + **死重清单喂闸门** + **闸门内纠正 focus** 留后(均复用 extra keystone / apply_gate_plan)。
  另记两 backlog(用户复测提出,归死重喂闸门):① 自动推荐够到**首尾**(引擎已位置无关、手动可折首尾,缺自动);② 标注每个 fate 的**理由**(推荐层产物,落点 inspector 顶/band 悬浮)。

---

### turn 带 · 主视图主轴翻转(第一~第四刀,设计见 [turn-band.md](turn-band.md))
主视图从"类型优先"翻成"**turn 优先**":纵向、与 TUI 同向、按 token 排——兑现 CLAUDE.md 第 5 条
(时间轴),并成为大窗口下的**语义 minimap / 主操作台**。
- **第一刀 · 时间序 turn 带(零 LLM)**:`web/src/lib/contextvis/turns.ts` `buildTurnCells`(按
  `chunk.turn` 聚合,折叠产物各自成格)+ `ContextVisPanel` 的 `TurnBand`(纵向、顶老底新、占用轴、
  比例/占用双模式)+ 视图开关「轮次/类型」(**默认轮次**,旧类型树图一键可回)。点轮 → inspector 显该轮原文。
- **压缩块诚实显示(取代废弃的"结构突变账本",决策痕迹见 [mutation-ledger.md](archive/mutation-ledger.md))**:
  `chunking._is_compression_artifact` 对齐 `regime._is_boilerplate` 全 5 marker → 压缩产物标 `folded`、
  **不计轮号**、画成「压缩 context」斜纹块、摆在正确位置。**不重建**被销毁的拓扑(folded 后已是单一可操作单元)。
  实测:多次压缩合并为一坨、真实轮号不乱。
- **第二刀 · 逐轮主题着色**:`regime.py` prompt 扩产 `turns:[{turn,topic,mainline}]`(`RegimeAssessment`
  加 `focus`/`turn_topics`,`assess` 签名/门控不变);新轻量 RPC `context.regime_colors`(server.py,
  **按 messageIndex** join chunk→`{topic,mainline}`,规避 regime 0-indexed vs chunking 1-indexed);
  前端「主题着色」**按需** toggle + `fetchRegimeColors` + `TurnBand` 按 topic 上色(主线饱和、支线压暗)。
  数据带 `historyVersion` 判新鲜度(snapshot 推进即失效),**非每帧调 aux**。
- **闸门自动着色(闸门与着色同一个脑)**:闸门 `assess` 与着色 `assess` 同实例同 `_llm_cache` → 闸门一弹,
  前端 `gateActive` 即自动 `fetchRegimeColors`(命中缓存即免费)+ 强制着色(`wantColor = colorOn || gateActive`),
  把关压缩时直接看到主线/支线。
- **第三刀 · 联动导航 + 细节层(纯前端,无后端改动)**:① `ChunkInspector` 新增「本轮构成」
  (`TurnComposition`:类型堆叠条 + 成员块 chips,点 chip 钻进该块原文)——选中对话轮时显,**底座/压缩块单块不显**
  (点压缩块=读摘要原文)。响应侧(tool_result/file)常远大于提问侧,这段让用户看清"一轮里谁在吃 context"。
  ② 点对话轮 → `ChatPage.jumpToTurn` 按该轮用户首句搜 xterm `buffer.active` + `scrollToLine`(启发式、尽力而为);
  `onActivateTurn` 穿 Overlay→Panel→TurnBand,**仅对话轮触发**(底座/折叠块无锚点不跳)。**TUI 耦合全收敛在挂载壳**
  (renderer 不碰 xterm,守三层隔离)。视口高亮框延后。
- **第四刀 · 主动梳理闭环 + 闸门折叠碰撞高亮(纯前端,无后端改动)**:把 band 从"看/导航"升级到"治理"。
  ① **band 命运叠加**:`TurnBand` 接 `fateMap`,纯函数 `aggregateCellFate` 逐格聚合 message-backed 成员命运 →
  整轮同命运=强叠加(drop 压暗+红斜划、fold 虚线 warning 边、keep success 边,与 Treemap 一致)、部分/混合=左缘
  竖条弱提示(诚实区分"还没标全")。② **闸门碰撞高亮**:喂的是 `effectiveFateMap`(闸门时=systemFate)→ 待折叠
  的轮自动亮 fold 叠加 = turn-band.md §4 末的碰撞高亮,**零额外代码**。③ **inspector 整轮命运**:`TurnComposition`
  加「整轮 保留/折叠/丢弃 + 清除」一行,批量预填该轮全部 message-backed 成员;成员 chip 加命运色点。
  `ChatPage.setFates` 批量增删 fateMap。**铁律兑现**:band/inspector 只**预填 fateMap**,落地复用既有
  `applyFold`/`applyDrops` + "应用 fold/drop (N)" 按钮,一行未改;多条支线逐轮标后一次应用即并折(非连续 splice)。
  ④ **折叠块=终点叶子(修)**:`ChatPage.turnChunks` 对齐 `buildTurnCells`——选中压缩块不显本轮构成(只读摘要原文)、
  某轮构成排除同 turn 号的折叠块,免压缩产物冒充该轮成员。
- **第四刀后续修(实测发现)**:
  - **turn 带布局溢出 = 最新轮被裁(关键修)**:旧逻辑每格 `max(TURN_MIN_H, 比例高)`,格多时保底高**累加溢出**
    `fillH`→ 顶老底新堆叠下,**排在最后的最新轮被挤出视口下沿、被 SVG 裁掉**(resume 老 session=底座+折叠块+多轮
    最易触发;类型版用 squarify 二维铺排不溢出故能看到——曾据此误判为数据问题)。改为**保底 + 余量按 token 占比**:
    每格之和**恰为 fillH**,永不裁掉任何轮;格太多时保底自动缩到 `fillH/n`。时间轴视图绝不能丢"现在"。
  - **本轮构成视觉优化**(`TurnComposition`):成员 chip 列表**限高 120px + 滚动**(整块 `shrink-0`)→ 工具调用再多
    也不挤占下方原文视图;文件 chip 只显**末两段路径**(`tui_gateway/server.py`,全路径留 title)→ 一行并排多个;
    **按 token 降序(history 置顶)** → 大块/谁在吃 context 先露头。
- **验证**:web build + lint 干净;后端 mock-LLM 测森林(三话题三色全支线)+ 任务(主线轮同色高亮、
  工具结果归对轮)+ join off-by-one 正确吸收。第三刀实测:点轮 inspector 显本轮构成 + TUI 同步滚动。
  第四刀实测:整轮 fold/drop → band 叠加 → 应用落地 token 真减;闸门弹起待折叠轮自动碰撞高亮;压缩块点击只读摘要不混入轮;
  resume 老 session 续轮 → 最新轮在带内正常显示(布局溢出修复后)。

---

## 决策日志(辩过并定下的)

- **token 保真度分档**:
  - 档1 = 真实 `usage`;
  - **档2(浏览器端估算)否决** —— 违背「tokens 必须真实,可信度系于此」;
  - 档3 = Hermes 既有 **chars//4 整体缩放**校准到真实总占用。
    用户明确:**不关注计数精度,只关注分块**。逐块绝对值是重建,比例与总量真实。
- **分块按类型用不同策略**(用户强调点):system=identity(3 段)、
  tool_schema=**按 toolset 合并**、history=**按轮**、file/tool_result=identity。
  策略**可插拔**——未来换语义版只改注册表,契约/渲染不变。
- **5 个渲染带**:`system / tool_schema / history / file / tool_result`。
  细粒度 `user/assistant/tool_call` 只在 segment 层保留(给 provenance / 未来聚类);
  history 带聚合它们。
- **标签**:file 按文件路径;tool_result 复用 `_summarize_tool_result`
  (产出 `[terminal] ... exit 1`、`... 14 matches` 等;与压缩引擎共享同一标签逻辑,
  见 [compression-baseline.md](compression-baseline.md))。
- **file vs tool_result 分流**:`role=tool` 且来源工具是 `read_file` → file 带(绿);
  其余 → tool_result 带(橙)。
- **形态迁移**:ChatSidebar 内嵌 → **终端对话区右上角浮层**(可折叠),腾出右侧栏给
  后续功能。开发阶段默认展开、不透明;美观/默认折叠/半透明留待功能完备后。
- **双模式**(用户要的两种):
  - **比例划分**:treemap 填满,chunk 间比例真实,始终可读(默认);
  - **实际占用**:按 `used/budget` 决定填充高度,上方留 headroom + token 轴 +
    compact 阈值线(读自真实 `compressor.threshold_tokens`)。
- **原文随快照 push(非 pull)**:浏览器够不到真实 PTY 会话(命令通道未解,见
  [roadmap.md](roadmap.md) 硬骨头),原文只能随 `context.snapshot` 推。每 chunk
  **截断 32KB** + flag 可关,localhost 可接受。
- **右侧栏改作 chunk 原文检视器**,删 MODEL/TOOLS(信息在 TUI/浮层已有)。
  master-detail:浮层=地图、侧栏=详情;选中态上提 ChatPage 共享。
- **检视器 v1 纯原文**(仅 tool_schema 已是 JSON);按类型的渲染优化(markdown /
  代码高亮 / 结构化)留后续。
- **小块不显标签是刻意的**:`showLabel = w>44 && h>26`(`ContextVisPanel.tsx`)。
  面积 ∝ token,小块放不下文字会变噪音;信息不丢——悬停 `<title>` + 点击进检视器兜底。
- **方向 A 先做阶段 1+2、不碰阶段 3**(用户敲定):标记+预览是纯前端零风险,
  先出"治理"手感;应用(动真上下文)留下一轮。**[后续]** 阶段 3 命令通道经调研 +
  浏览器只读探针**实测可用**,原判"独立架构决策/硬骨头"已推翻,见 [phase3-channel.md](archive/phase3-channel.md)。
- **命运标记入口在检视器按钮,不在 treemap 点击**(用户敲定):treemap 点击保持
  =选中看原文;命运靠按钮设、靠叠加渲染显,分工清晰、有空间放释放量估算。
- **命运意图与后端真值分离**:用户标记存 `fateMap`,**不写回 `snapshot.chunks`**;
  `ContextChunk.fate` 留给阶段 3 的"后端已应用命运"。两者互不污染。
- **孤儿命运不主动剪除**:lint 禁止 effect 内同步 setState;且所有消费方只按当前
  chunks 查表,孤儿天然惰性。改"主动剪除"为"惰性无效",代码更简、行为等价。
- **释放量估算对齐 Hermes 压缩语义**:fold≈80% / drop≈100% / keep=0
  (`summary_target_ratio=0.20`)。与逐块 token 一样:比例真实、不冒充精确值。
- **阶段 3 v1 只做 drop**(用户敲定):确定性、零 LLM,先把"浏览器→真实 agent 写"
  这条路用最小风险跑通;fold(复用 `_generate_summary`)留 v2。
- **apply 不复用 `_compress_context` 的位置式逻辑**:那是按头/尾位置切;我们要**按内容
  选**。直接在 `session["history"]` 上删指定下标(与 `session.undo` 同款内存写回),
  只复用 `_sanitize_tool_pairs` 缝合——选择层我们写,执行层转包既有引擎。
- **apply 只作用于 message 背书的块**(history/file/tool_result):system/tool_schema 每轮
  由 agent 重建、无 messageIndex,删不掉 → 检视器对这两类**禁用命运按钮**(诚实)。
- **一步内存撤销,非 DB 续写**:`session["_contextvis_undo"]` 存 apply 前快照,其间无新
  turn 时可还原;`session.undo` 只 pop 末轮、救不了中段编辑,故自带快照。不做
  session_id 轮转/DB 续写(v1 够用,留待需要持久化时再说)。
- **陈旧校验靠 `history_version`**:快照随事件带版本,apply 回传;其间发生 turn/压缩 →
  版本变 → 后端拒(4409),前端提示刷新。避免在过时视图上误删。
- **压缩闸门复用审批基建,不造新控制流**(调研结论):`_await_gateway_decision` 已是
  "阻塞 agent 线程等用户决定 + 超时 + 心跳"的成熟原语;闸门只是新增一个 `kind=compaction`
  载荷 + `compaction.respond`。证据见 [compaction-gate.md](compaction-gate.md)。
- **闸门 opt-in、默认关**(`HERMES_CONTEXTVIS_GATE`):改的是核心 agent 行为;无 notify_cb
  (无 dashboard)/ 超时 → 自动继续,**无人值守天然不被挂死**,是结构性保证。
- **闸门第一阶段纯预览、不编辑**(用户敲定):绕开"闸门内编辑"的两暗礁(running 闸冲突、
  `messages`↔`session["history"]` 对账),真低风险。编辑留第二阶段。
- **系统计划 = 用户计划同一套渲染**:闸门激活时 treemap 喂 `pending.systemFate` 而非
  用户 `fateMap`(`effectiveFateMap`)。fate 计划无论作者是系统还是用户,预览/落地同一条路。
- **turn 中途变更要主动补发快照**:闸门/压缩都发生在 turn 中途,而常规 `context.snapshot`
  只在轮末发 → 必须 `emit_post_compaction_snapshot` 经 notify 桥即时补发,否则 treemap 滞后。
  真实 token 未回来时用 `estimate_request_tokens_rough` + `build_snapshot_chunks(scale_to=)`。
- **「压缩 ×N」用真实累计计数,不用推断事件数**:一轮多次 mid-turn 压缩,session.info 只
  采样一次会少计 → 改用 `usage.compressions` / `comp.compression_count`(`compressionCount`)。
- **A-v2 fold 仅非对话态(用户敲定)**:主动避开"闸门内编辑"两暗礁——空闲无 running 锁冲突、
  `session["history"]` 是唯一真相(无 messages↔history 对账)。fold 因此**与 drop 共用** apply
  落地路 + 撤销 + 陈旧校验。对话中触发的 fold 留压缩闸门第二阶段。
- **fold 单隐式组 + action 原子化(用户敲定)**:所有 fold 标记→一条摘要(多命名组=多次单组,
  后做);一次 apply 只 fold 或只 drop(混用索引数学绕,留 v1 测过后)。
- **fold 支持非连续(用户敲定)**:用户核心诉求(收支线)本质非连续。一条摘要落最早 fold 位、
  其余移除,`_sanitize_tool_pairs` 缝合孤儿工具对、`_summary_message` 保 role 合法——
  只允许连续等于砍掉主要价值。
- **摘要放置抽成纯函数,fold 与默认压缩共用**:`_summary_message` / `splice_fold_summary`
  从 `compress()` 抽出,默认压缩改用前者**行为不变**。一处逻辑、两处复用,role/工具对的护栏只写一遍。
- **fold 失败整笔中止,不半落地**:`_generate_summary` 返回 None(失败/冷却)→ history 不动 +
  报 5006。绝不静默删——透明优先(CLAUDE.md 第 6 条)。
- **chunk 计数 ≠ message 计数**:treemap「折叠×N」数 chunk(用户选的块),TUI 进度数其展开的
  真实消息(一轮 chunk 捆 user+assistant+tool 多条)。二者本就不同 → 文案写「N 块(M 条消息)」讲清,免误判。
- **闸门加"任务态"前置,而非每次都弹(用户驱动)**:违背"森林里别打扰";改成两级门控
  (regime ∧ collision)。判出 task 还不够,得这次压缩**真碰到主线**才弹。
- **检测纽带按 turn 而非消息**:工具密集的单 turn 内部反复引用同一文件会"自我结网"冒充主线 →
  纽带须跨 ≥2 个**真实** user turn(压缩样板的 role=user 块不算 turn)。
- **廉价启发式有天花板,转 LLM(连撞四次后定)**:"共享 token"分不清"共享工具"与"共享任务"——
  压缩残骸、网页搜索词、记忆/任务样板、工具名逐个泄漏成假纽带,打地鼠到头。LLM 按**目标/主题**语义判,
  一举分清"都用网页搜索但话题无关 = 森林"。启发式降为回退/对照。
- **LLM 只喂 turn 骨架不喂全文**:1M 下"为省 token 通读 1M"是反讽 → 每轮只给意图 + 工具/文件名。
- **prompt 问"当前多轮任务",不是"整段二选一"**:否则一个无关早先 turn 会把混合 session 拖成森林。
  改后稳定输出 `mainline_turns`(护当前任务)+ 把早先无关 turn 当可压噪音(off-thread)。
- **LLM 失败必回退、绝不挡压缩**:无 provider / 超时 / 解析失败 → 启发式 → 保守森林。误判代价不对称
  (漏弹=退回静默自动压无损,滥弹才烦)→ 拿不准倾向不扰。
- **检测器跑在压缩后历史是已知硬限(留滚动增量根治)**:压缩重写历史(摘要残骸),当前靠"样板隐形"
  缓解——不再被残骸骗;彻底根治需压缩前快照任务结构(后续)。
