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
[phase3-channel.md](phase3-channel.md)),v1 **只做 drop、确定性、零 LLM**(fold 留 v2)。
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
  浏览器只读探针**实测可用**,原判"独立架构决策/硬骨头"已推翻,见 [phase3-channel.md](phase3-channel.md)。
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
