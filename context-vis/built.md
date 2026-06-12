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
- **零副作用**:不碰 chunking.py / server.py / adapter.ts,不发命令、不改真实上下文。
  **阶段 3(应用)**——把 fateMap 下发驱动 `compress()`——其命令通道**已实测可用**
  (原判"硬骨头"已推翻,证据链见 [phase3-channel.md](phase3-channel.md)),剩选择式 RPC +
  `sourceRefs` 映射 + 前端 apply 路,纯工程实现。

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
