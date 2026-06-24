# ContextVis fixtures（dev-only 录制 / 重放）

把一次真实 context 状态**冻结成 JSON**，之后无限次**零-token、完全确定**地重放。
用于迭代 v2 的前端视图/交互（add / invalidate / promote、轮盘、画布）而不必每次新开
session、按序敲 prompt（费时、费 token、LLM 还带随机性）。

## 为什么能给「幂等」

渲染层有**两个数据源**，fixture 都冻结：

| 数据源 | 来自 | fixture 字段 |
|---|---|---|
| 占用 + chunks | `useContextSnapshot` 的 WS feed | `snapshot` |
| 着色 + 引用图 + 产物/关键词 | `fetchRegimeColors` 的 RPC | `regimeColors` |

连**检测器的判定**（主线 / focus / 引用图）都钉死 —— 这正是 `session.branch`（fork）
给不了的：fork 会让 `context.regime_colors` 重跑 aux LLM、每次主线/弧都抖。

## 工作流

1. **录制**（一次性、需真实 session）：dev 模式下在 ContextVis 面板 header 点 **`⬇ fixture`**
   → 浏览器下载 `<name>.json` → 放进**本目录**。
2. **重放**：访问 `/chat?fixture=<name>` → 面板每次刷新都是那个冻结状态、零 token、HMR 即时。
   找不到该名 → 控制台 warn + 退回真实模式（不打断）。

> **fork 是产 fixture 的作者工具，fixture 是日常主力。** 先 fork / 手敲到一个有趣前态
> → 录成 fixture → 之后所有 UI 迭代打这份 fixture。

## 注入点（守适配器边界）

只两处短路，渲染组件不知 fixture 存在：
- [`useContextSnapshot.ts`](../../../hooks/useContextSnapshot.ts)：fixture 命中即以冻结 snapshot 初始化、不开 WS。
- [`apply.ts` `fetchRegimeColors`](../apply.ts)：fixture 命中即返回冻结 `regimeColors`、不发 RPC。

## fixture 测得到 / 测不到

- ✅ **渲染 + 本地预览**（占用、画布、弧、索引列；add/invalidate 的纯函数投影）。
- ❌ **真改 session / system-prompt 的落地**（`context.add` 等 mutation）→ 那是 Layer 2，
  用 `session.branch` 在真实会话上验证。fixture 模式下点「应用 / fold」会打到真实
  gateway，但那个 sid 没有活会话 → 会报错，**预期如此**。
- ⚠️ **左侧 TUI 占比恒为 0%**：fixture 只喂右侧 React ContextVis 面板，**不驱动左侧 TUI**
  （它是真实 PTY 子进程、有自己的状态行）。fixture 模式下没有活会话 → TUI 自画的 context
  占比是 0%，**预期如此**。占用真相看右侧面板。

## 写手写 fixture 的不变量

录制下来的 fixture 自然满足；手写时务必对齐，否则视图自相矛盾：
- **`snapshot.chunks` 的 token 合计 ≈ `snapshot.used`** —— chunks 是 prompt 的分解，画布按
  chunk token 铺、占用条按 `used`，两者不一致 → 画布占比对不上占用条（曾踩）。
- **`compactAt` = 真实压缩阈值**（如 budget 的 50% → `compactAt = budget*0.5`）；画布顶
  锚定 `阈值占比×1.2`、阈值线画在 `compactAt`，设错则"离上限多远"失真。
- chunk `id` 在 `snapshot.chunks` 与 `regimeColors.chunk_topics` / `reference_graph` 间一致。

## 文件形状

见 [`index.ts`](index.ts) 的 `ContextVisFixture`。`snapshot` = `ContextSnapshot`，
`regimeColors` = `fetchRegimeColors` 的原始返回（含 `reference_graph`）。
`demo.json` 是手写占位样例（可直接 `?fixture=demo` 验证管路，随时删）。
