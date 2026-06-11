# CONTEXTVIS.md — ContextVis 工程决策与路线图

> 本文件是 ContextVis 的**工程记录**:已建成什么、为什么这么定、接下来去哪。
> 与 [CLAUDE.md](CLAUDE.md) 分工:CLAUDE.md 是**设计理念**(使命/隐喻/不变量,
> 与渲染形式无关),本文件是**落地决策 + 路线图**。回顾项目看这一份即可。
>
> 状态:分支 `feat/contextvis-occupancy-panel`。档1 / 档3 / resume 修复 / 原文检视器
> 完成;已同步上游。

---

## 1. 一句话

把 agent 的上下文窗口从黑盒变成**可读、可追溯、可治理的白盒**。中心真相:
**占用对抗上限**——装了多少、还剩多少、被什么吃掉、怎么涨上来、何时压缩。

定位:平时用户只管对话、不必关心 context;**当 agent 开始出错或窗口将满时**,
才需要可视化并(未来)交互编辑来手动控制上下文。

---

## 2. 架构:三段流水线 + 三层隔离

```
原始上下文 ─①分割→ 原子 segment[] ─②分块(策略可插拔)→ chunk[] ─③渲染→ 视图
```

三层隔离(CLAUDE.md「集成姿态」):

| 层 | 职责 | 文件 |
|---|---|---|
| **适配器**(宿主专属) | 订阅 `/api/events`,把真实数据折成 snapshot;唯一碰宿主事件结构的地方 | `web/src/lib/contextvis/adapter.ts` |
| **核心**(形态无关) | 数据契约 + 一种渲染;只吃 snapshot | `web/src/lib/contextvis/{types,treemap}.ts`、`web/src/components/ContextVisPanel.tsx` |
| **挂载壳**(宿主专属) | 浮层定位/折叠 + 右侧栏原文检视 + 持有 snapshot/选中态联动 | `web/src/components/{ContextVisOverlay,ChunkInspector}.tsx`、挂载于 `web/src/pages/ChatPage.tsx` |
| **后端分块**(服务端) | segment→chunk 流水线,策略注册表,chunk 原文 | `agent/contextvis/chunking.py` |
| **网关挂钩** | co-emit `context.snapshot` | `tui_gateway/server.py` |

> 黄金法则:渲染层永不直接依赖宿主数据结构;耦合全收敛到适配器与挂载壳。
> 换语义分块策略 / 换渲染皮肤 / 加交互,都不应翻动契约。

---

## 3. 已建成

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

### 原文检视器（方向 C，commit `68ce781a0`）
点浮层 treemap 某 chunk → 右侧栏 `ChunkInspector` 显示**完整原文**:system
prompt 节、tool schema JSON、工具调用详情、文件内容、对话原文。其中
**system/tools 在终端对话里根本看不到,检视器是唯一入口**——补全白盒的
「可追溯」。后端每 chunk 随 `context.snapshot` 带原文(成员拼接,**32KB 截断**,
`HERMES_CONTEXTVIS_RAW=0` 可关)。选中态上提 ChatPage,浮层(地图)↔侧栏(详情)
master-detail 联动。**删除右侧栏 MODEL/TOOLS**(原 `ChatSidebar`),右侧栏改作检视器。

---

## 4. 决策日志(辩过并定下的)

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
  (产出 `[terminal] ... exit 1`、`... 14 matches` 等)。
- **file vs tool_result 分流**:`role=tool` 且来源工具是 `read_file` → file 带(绿);
  其余 → tool_result 带(橙)。
- **形态迁移**:ChatSidebar 内嵌 → **终端对话区右上角浮层**(可折叠),腾出右侧栏给
  后续功能。开发阶段默认展开、不透明;美观/默认折叠/半透明留待功能完备后。
- **双模式**(用户要的两种):
  - **比例划分**:treemap 填满,chunk 间比例真实,始终可读(默认);
  - **实际占用**:按 `used/budget` 决定填充高度,上方留 headroom + token 轴 +
    compact 阈值线(读自真实 `compressor.threshold_tokens`)。
- **原文随快照 push(非 pull)**:浏览器够不到真实 PTY 会话(命令通道未解,见 §7.1),
  原文只能随 `context.snapshot` 推。每 chunk **截断 32KB** + flag 可关,localhost 可接受。
- **右侧栏改作 chunk 原文检视器**,删 MODEL/TOOLS(信息在 TUI/浮层已有)。
  master-detail:浮层=地图、侧栏=详情;选中态上提 ChatPage 共享。
- **检视器 v1 纯原文**(仅 tool_schema 已是 JSON);按类型的渲染优化(markdown /
  代码高亮 / 结构化)留后续。

---

## 5. 数据契约(`web/src/lib/contextvis/types.ts`)

```
ChunkType   = system | tool_schema | history | file | tool_result   // 5 渲染带
SegmentRef  { messageIndex?, part? }                                // provenance
ContextChunk{ id, type, tokens, turn, label, sourceRefs[],
              group?, members?, turnSpan?, fate?, raw? }            // raw=原文(检视器用)
ContextSnapshot{ budget, used, percent, turn, history[],
                 compactions[], chunks[], compactAt? }
```
`fate?: keep|fold|drop` 与 `sourceRefs` 是**交互式压缩的地基**,v1 `fate` 留空/只读。
`raw?` 由检视器消费(后端截断推送)。

---

## 6. 数据流 & 部署(备查)

- **真实数据通道**:dashboard 的 Chat 是 PTY 子进程跑的 TUI(xterm 嵌入)。真实
  `usage`/`context.snapshot` 走 PTY 子进程 gateway「mirror every emit」→ `/api/pub`
  → 服务端 `pub_ws` verbatim → `/api/events?channel=`(与 tool 事件同一条 feed)。
  **不在** dashboard 的 JSON-RPC sidecar(`/api/ws`,throwaway 会话,usage≈0;
  原 ChatSidebar 已删,但 `gatewayClient` 仍被别处用)。
- **测试启动**(关键坑):`hermes` 命令默认跑独立安装 `~/.hermes/hermes-agent/`,
  **不是本仓库**;且 `-m tui_gateway.entry` 会先定位包,使 `HERMES_PYTHON_SRC_ROOT`
  单独设无效。正确启动:
  ```bash
  cd <repo>
  PYTHONPATH="$PWD" HERMES_PYTHON_SRC_ROOT="$PWD" \
    ~/.hermes/hermes-agent/venv/bin/python ./hermes dashboard --no-open
  # 前端：cd web && npm run dev（vite 代理 /api 到后端）
  ```
  前端改动 HMR 即时;后端 Python 改动需重启网关。本机无 pytest,后端逻辑用
  stub 脚本验证(`tests/test_contextvis_chunking.py` 是 pytest 版,留给有 pytest 的环境)。
- **压缩阈值**:Hermes 源码默认 50%(`compression.threshold`,可 `hermes config set`
  改;注意 per-model autoraise)。我们只读 `threshold_tokens` 画 compact 线。

---

## 7. 路线图(已埋 seam,未动工)

### 7.1 交互式压缩(旗舰,下一步)
让视图从"观察"升级到"治理":agent 出错 / 窗口将满时,用户手动控制上下文。

分阶段(由易到难):
1. **选中 + fate 标记(纯前端,零风险)**:点 chunk → 标 `drop/keep/fold`,
   treemap 按 fate 着色/描边。
2. **预览(纯函数,无副作用)**:据 fate 算"预计释放 token / 新分布"。
3. **应用(真正动上下文)**:把 fate map 下发,**驱动既有 trajectory/context_compressor
   落地**(不造新压缩引擎),可由 sub-agent 执行。

四项交互能力(用户预想):①系统建议 drop/keep/merge ②用户编辑(丢弃/固定/合并 +
合并重心)③预览影响 ④sub-agent 应用。

**未解的硬骨头(阶段 3 前必须解决)**:**"浏览器 → 真实 PTY 会话"的命令通道不存在**——
`/api/events` 是单向 push;ChatSidebar 的 sidecar 是另一个 throwaway 会话,够不到 PTY
真实会话。候选:PTY 侧网关暴露 method + sid 中转 / 经 sidecar 转发 / 新建命令 WS。

**地基已备**:`sourceRefs`(provenance,编辑能落到真实 message)、`fate` 字段、
预留 `context.plan`(纯预览投影)/`context.apply`(落地)RPC 命名空间、建议策略注册表。

### 7.2 语义分块(实验)
把 history 的"按轮"换成**主题聚类**(主线/支线)、tool_schema 换成**相似工具合并**。
**只改 ChunkStrategy**,契约/渲染不变。效果待实验,架构已为它留好口。

---

## 8. 待决方向

观察(占用/构成/原文)已闭环。下一步候选:

- **A. 交互式压缩(旗舰)**:让视图能"治理"。从纯前端的 ①选中+fate 标记 +
  ②预览释放量 起步(零风险),并行调研 ③应用 的"浏览器→真实 PTY 会话"命令通道
  (见 §7.1 硬骨头)。地基(`fate`/`sourceRefs`/`context.plan·apply` 命名空间)已备。
- **B. 语义分块实验**:把 history「按轮」换主题聚类、tool_schema 换相似工具合并——
  只改 ChunkStrategy,契约/渲染不变。效果待验。
- **C2. 检视器类型化渲染**:assistant 文本走 Markdown、代码/JSON 语法高亮、
  tool_result 结构化(退出码/匹配数高亮)。在方向 C 的纯原文之上做体验优化。
- **D. 打磨与收尾**:移动端 sheet 触发按钮文案仍是 i18n 的 "model/tools"(需多语言清理);
  treemap 视觉(配色/字号/带顺序)、浮层交互(拖动/缩放)、截断上限可配。

> 建议优先级:**A**(产品定位的核心价值)> B/C2(增量) > D(收尾)。A 的 ①② 可先落地
> 出手感,③ 的命令通道是全项目下一个真正的架构决策点。
