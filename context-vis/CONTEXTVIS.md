# CONTEXTVIS — 工程记录入口

> ContextVis 的**工程记录索引**。这是 skill 式入口:本文件保持精简(使命 + 架构速览 +
> 契约 + **文档地图**),细节按需读子文档。
>
> 与 [../CLAUDE.md](../CLAUDE.md) 分工:CLAUDE.md 是**设计理念**(使命/隐喻/不变量,
> 与渲染无关);本目录是**落地决策 + 路线图**。
>
> 状态:分支 `feat/contextvis-occupancy-panel`。档1 / 档3 / resume 修复 / 原文检视器 /
> 方向 A 阶段 1+2(标记+预览)/ **阶段 3 应用 drop + A-v2 fold** / **压缩闸门第一阶段 + 第二阶段 drop/fold/keep 编辑 + 死重清单喂闸门** /
> **任务态识别(自适应总开关:启发式 + LLM)+ 焦点压缩(focus→focus_topic,仅闸门路)
> + 死重清单(主动「建议清理」+ 喂闸门:detector 已完成支线自动预填进 system_fate、含首尾、共用 chunk_topic_map)** /
> **turn 带主轴翻转(第一刀时间序 + 第二刀逐轮主题着色
> + 压缩块诚实显示 + 闸门自动着色 + 第三刀联动导航/细节层:点轮跳 TUI + inspector 本轮构成
> + 第四刀主动梳理:整轮 fold/drop 预填 fateMap 复用落地 + 闸门折叠碰撞高亮)** 完成——
> 观察→治理(删/折)→落地 + 系统压缩前用户把关 + 自适应介入 + **焦点压缩(把关时确认主线焦点→喂压缩)** +
> **死重清单(主动清理 + 喂闸门:被迫压缩前自动建议折已完成支线、含首尾、banner/band 标来由;建议用 fold 不 drop)** + **闸门内 drop/fold/keep 编辑(被迫压缩前改写折叠计划:删垃圾/补折支线/护住中段轮,经应答落地、方案 A 直接落地、两暗礁消解)** +
> **按 turn 看时间/主题、点轮跳对话、整轮主动 fold/drop 的语义 minimap / 主操作台(band 概览 + inspector 类型细节)** 均闭环。
> **下一步:R 滚动增量(长会话健壮)/ drop 残值信号(失败 tool/被取代 read/闲聊,比 done→drop 准)/ 自动护主线中段 / keep-as-pin / 纠正 focus / ②→①完成自动触发;
> 视口高亮框、非闸门路喂 focus 延后**,详见 [turn-band.md](turn-band.md) §9 / [roadmap.md](roadmap.md)。

---

## 一句话

把 agent 的上下文窗口从黑盒变成**可读、可追溯、可治理的白盒**。中心真相:
**占用对抗上限**——装了多少、还剩多少、被什么吃掉、怎么涨上来、何时压缩。

定位:平时用户只管对话、不必关心 context;**当 agent 开始出错或窗口将满时**,
才需要可视化并(未来)交互编辑来手动控制上下文。

---

## 架构速览:三段流水线 + 三层隔离

```
原始上下文 ─①分割→ 原子 segment[] ─②分块(策略可插拔)→ chunk[] ─③渲染→ 视图
```

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

## 数据契约(`web/src/lib/contextvis/types.ts`)

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

## 文档地图(按状态分组)

> 三类:🟢 **活跃**(当前在动 / 常查)· 📘 **参考**(已建成机制的设计 + 基线 + 理念,稳定、按需查)·
> 🗄 **归档**([`archive/`](archive/),已废弃 / 调研完成,留作决策痕迹,平时不必读)。
> 文档**状态**以各文件顶部的「状态」行为准;本表是入口索引。

### 🟢 活跃 — 当前在动 / 常查
| 文档 | 是什么 | 状态 |
|---|---|---|
| [turn-band.md](turn-band.md) | 主视图主轴翻转(turn 优先 + 逐轮主题 + 主动梳理,语义 minimap / 主操作台) | **第一~第四刀✅**(§9),视口高亮框延后 |
| [roadmap.md](roadmap.md) | 接下来去哪、优先级、待决方向 | 活跃 |
| [built.md](built.md) | 做了什么 + 每个取舍为什么(里程碑日志) | 持续追加 |
| [needs.md](needs.md) | 用户需求 → 解决方案地图(每条需求挂方案 + 状态) | 活跃 |

### 📘 参考 — 已建成机制的设计 / 基线 / 理念(稳定,按需查)
| 文档 | 是什么 | 状态 |
|---|---|---|
| [../CLAUDE.md](../CLAUDE.md) | 设计理念 / 不变量(渲染无关,最高纲领) | 纲领 |
| [regime.md](regime.md) | 任务态识别原理 + 判定(ContextVis 的"脑",喂闸门 + turn 带着色) | ✅ 已建成 |
| [fold.md](fold.md) | 方向 A-v2 fold(折成摘要而非整删)设计 | ✅ 已建成 |
| [compaction-gate.md](compaction-gate.md) | 压缩闸门(拦 auto-compress 改用户确认) | ◑ 一阶段 + 二阶段 drop/fold/keep 编辑 + 死重喂闸门已建成;keep-as-pin/纠正 focus/drop 残值信号待做 |
| [compression-baseline.md](compression-baseline.md) | Hermes 自动压缩基线(要接管/复用的引擎) | 参考 |
| [dataflow.md](dataflow.md) | 真实数据怎么流 + 本地跑起来调试(踩坑必看) | 参考 |

### 🗄 归档 — 已废弃 / 调研完成(决策痕迹,平时不必读)
| 文档 | 是什么 | 状态 |
|---|---|---|
| [archive/mutation-ledger.md](archive/mutation-ledger.md) | "结构突变账本"——曾想重建被压缩销毁的轮次拓扑 | ⛔ 已废弃(被"诚实显示压缩块"取代,见 [turn-band.md](turn-band.md) §4) |
| [archive/phase3-channel.md](archive/phase3-channel.md) | 阶段 3 命令通道可行性调研(架构真相 + 实测证据) | ✅ 结论已落地为生产代码 |
