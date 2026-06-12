# 阶段 3 命令通道 —— 证据链(原"硬骨头"已推翻)

> **结论先行**:方向 A 阶段 3「应用」需要的"浏览器 → 真实 agent"命令通道,
> 在 **dashboard 部署里已经存在**,且**已运行时实测坐实**。早期判断"无此路 / 硬骨头"
> 基于一个错误前提(以为真实 agent 在另一个进程)。本文记录架构真相 + 证据。

---

## 一、早期的错误前提

旧记录(见 [roadmap.md](roadmap.md) 修订前 / [dataflow.md](dataflow.md))认为:

- `/api/events` 是**单向 push**,浏览器无法回发命令;
- dashboard 的 `/api/ws` JSON-RPC sidecar 是**另一个 throwaway 会话**(usage≈0),
  够不到 PTY 跑的真实会话;
- 于是"浏览器 → 真实 PTY 会话"**无通道**,需新建中转。

错在第二条:**以为真实 agent 在 PTY 子进程里、与 web_server 隔离**。

---

## 二、架构真相:dashboard 下 PTY 走 attach 模式,真实 agent 在 web_server 进程内

证据(代码层):

1. **dashboard 总是注入 `HERMES_TUI_GATEWAY_URL`** —— `_resolve_chat_argv`
   ([web_server.py:9151](../hermes_cli/web_server.py#L9151)),docstring 明说"so the PTY child
   can **attach to this process's in-memory tui_gateway instance instead of spawning its own**"。
2. **ui-tui 见到该 URL 即 attach、不再自起 Python gateway** ——
   [gatewayClient.ts:515](../ui-tui/src/gatewayClient.ts#L515):`if (attachUrl) startAttachedGateway(...)`,
   否则才 `startSpawnedGateway`。
3. **`session.active_list` 枚举的是"this gateway process"内的 live TUI sessions** ——
   [server.py:4119](../tui_gateway/server.py#L4119)。即真实会话注册在 web_server 进程的 `_sessions`,
   与 `/api/ws` dispatch、所有 REST 同进程同注册表。
4. **会话 id 发现是免费的** —— `_emit` 每帧 params 都带 `session_id`
   ([server.py:748](../tui_gateway/server.py#L748));ContextVis 适配器消费的 `context.snapshot`
   帧里就有,读出来即可,无需额外发现机制。

> 所以"sidecar usage≈0"不是进程隔离,而是 **dashboard 的 React sidecar 自建了空会话、
> 没去 attach TUI 那个真实会话**。问题是**目标 sid 选错**,不是"够不到"。

---

## 三、运行时实测(只读探针)

**方法**:dashboard Chat 开着、跑过几轮对话后,在浏览器 console 跑一段**纯只读**探针:
新开一条 `/api/ws`(用 `buildWsAuthParam` 同款鉴权)→ `session.active_list` →
对返回的每个 sid 调 `session.usage`。全程不调 `session.create/resume`,连接关闭不持有会话,
**不动任何上下文**。

**结果**(实测一次):

```
[probe] /api/ws connected
session.active_list → [{…}]   // 1 个 live 会话
per-session usage:
  session_id  title             context_used  context_max  context_percent  calls
  5f6d320f    模型型号与平台 #4   86670         202752       43               0
[probe] ✅ 通道可用:前端按 sid 读到了 1 个非零会话。
```

**证明**:**前端新开的 `/api/ws`,跨连接、按 sid 读到了 TUI 那个真实 agent**
(`context_used 86670/202752=43%`,与 treemap / TUI 占比条一致;非 sidecar 的空会话)。
`calls:0` 是 resume 计数器归零,不影响——`context_used` 是从已载入 history 真实算出的。

> 读既然能跨连接命中真实 agent,**同一套 dispatch + `_sess(session_id)` 解析下,
> 写(`session.compress`)几乎必然同样命中**。

---

## 四、对阶段 3 的影响:从"架构决策"降级为"工程实现"

通道既通,阶段 3 不再需要造新通道,剩下都是可控的工程:

1. **选择式压缩 RPC**:`session.compress`([server.py:4559](../tui_gateway/server.py#L4559))
   现做**位置式全量**压缩、只吃 `focus_topic`。扩它 / 新增 `context.apply`,改吃**结构化
   fate 选择**(drop/fold/keep 的 chunk 集),内部**复用** `_generate_summary` /
   `_prune_old_tool_results` / `_sanitize_tool_pairs`(见 [compression-baseline.md](compression-baseline.md)
   复用表),但**用显式 message 索引定边界**,而非头/尾位置。
2. **fate → message 索引映射**:用 chunk 的 `sourceRefs`(档3 已埋 provenance)把"标记的块"
   翻成"真实消息下标"。
3. **前端 apply 路**:新 `web/src/lib/contextvis/apply.ts` —— 复用/开 `/api/ws`,
   带 `session_id`(事件帧取)+ fateMap 发 RPC;面板加**带确认**的「应用」按钮。
   压缩完后端 re-emit `session.info` + `context.snapshot`,UI 与 fateMap 自动刷新。
4. **并发闸**:`session.compress` 在 `session["running"]` 时拒(已有);apply 按钮仅空闲可点。
   irreversible → 配合 `session.undo`([server.py:4531](../tui_gateway/server.py#L4531))做安全网。

**写路径已实测通过**(阶段 3 v1):浏览器 `context.apply` 跨连接按 sid 删消息,真实
agent 的 TUI 占比条 + treemap 同步回落、token 真减少、撤销还原、对话进行中被礼貌拒绝。
读已证、写已证,通道完全坐实。

---

## 五、注意:仅限 dashboard 部署

attach 模式由 dashboard 启动 PTY 时注入 `HERMES_TUI_GATEWAY_URL` 触发。
**独立 `hermes --tui`(不经 dashboard)** 会自起 gateway 子进程、且没有 web_server——
但 ContextVis 本就只在 dashboard 内运行,此约束不影响。
