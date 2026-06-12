# CONTEXTVIS — 工程记录入口

> ContextVis 的**工程记录索引**。这是 skill 式入口:本文件保持精简(使命 + 架构速览 +
> 契约 + **文档地图**),细节按需读子文档。
>
> 与 [../CLAUDE.md](../CLAUDE.md) 分工:CLAUDE.md 是**设计理念**(使命/隐喻/不变量,
> 与渲染无关);本目录是**落地决策 + 路线图**。
>
> 状态:分支 `feat/contextvis-occupancy-panel`。档1 / 档3 / resume 修复 / 原文检视器 /
> 方向 A 阶段 1+2(标记+预览)/ **阶段 3 v1(应用 drop)** 完成——观察→治理→落地闭环打通;
> 已同步上游。下一步:方向 A **v2 = fold**(复用 `_generate_summary`),详见 [roadmap.md](roadmap.md)。

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

## 文档地图(按需读取)

| 想知道… | 读 |
|---|---|
| 做了什么 & 每个取舍为什么 | [built.md](built.md) — 已建成 + 决策日志 |
| 真实数据怎么流、怎么本地跑起来调试 | [dataflow.md](dataflow.md) — 数据流 + 部署坑 |
| Hermes 现在自动怎么压缩上下文(方向 A 的基线) | [compression-baseline.md](compression-baseline.md) |
| 阶段 3 命令通道为何可行(架构真相 + 实测证据) | [phase3-channel.md](phase3-channel.md) |
| 接下来去哪、优先级 | [roadmap.md](roadmap.md) — 路线图 + 待决方向 |
| 设计理念 / 不变量(渲染无关) | [../CLAUDE.md](../CLAUDE.md) |
