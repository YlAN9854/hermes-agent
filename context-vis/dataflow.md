# 数据流 & 部署(备查)

> 真实数据怎么从 PTY 会话流到浏览器,以及怎么把改动跑起来调试。踩坑前看这份。

---

## 真实数据通道

dashboard 的 Chat 是 **PTY 子进程跑的 TUI**(xterm 嵌入)。真实
`usage` / `context.snapshot` 的路径:

```
PTY 子进程 gateway「mirror every emit」
  → /api/pub
  → 服务端 pub_ws verbatim 扇出
  → /api/events?channel=   (与 tool 事件同一条 feed,单向 push)
  → 浏览器 adapter.ts
```

**不在** dashboard 的 React JSON-RPC sidecar 自建的那个会话(usage≈0)。注意:那只是
sidecar **自己**的空会话;同一条 `/api/ws` 的 gateway 进程里**也持有 TUI 那个真实会话**
(attach 模式),按 sid 可达 —— 见下。

> **观测**这条 events feed 是单向 push。但"浏览器发不回命令"是早期**误判**:
> dashboard 下 PTY 走 attach 模式,真实 agent 就在 web_server 进程的 `_sessions`,
> 前端新开 `/api/ws` 按 sid 即可调 `session.*`(命令通道**已实测可用**)。
> 详见 [phase3-channel.md](archive/phase3-channel.md);方向 A 阶段 3 据此从"架构决策"降级为工程实现。

---

## 测试启动(关键坑)

`hermes` 命令默认跑独立安装 `~/.hermes/hermes-agent/`,**不是本仓库**;且
`-m tui_gateway.entry` 会先定位包,使 `HERMES_PYTHON_SRC_ROOT` 单独设无效。
正确启动:

```bash
cd <repo>
PYTHONPATH="$PWD" HERMES_PYTHON_SRC_ROOT="$PWD" \
  ~/.hermes/hermes-agent/venv/bin/python ./hermes dashboard --no-open
# 前端：cd web && npm run dev（vite 代理 /api 到后端）
```

- 前端改动 **HMR 即时**;后端 Python 改动需**重启网关**。
- 本机无 pytest,后端逻辑用 stub 脚本验证(`tests/test_contextvis_chunking.py`
  是 pytest 版,留给有 pytest 的环境)。

---

## 压缩阈值

Hermes 源码默认 50%(`compression.threshold`,可 `hermes config set` 改;注意
per-model autoraise)。ContextVis 只**读** `threshold_tokens` 画 compact 阈值线,
不改压缩行为。完整压缩策略见 [compression-baseline.md](compression-baseline.md)。
