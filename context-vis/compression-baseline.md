# 压缩基线 — Hermes 默认上下文压缩策略

> **现状基线**:ContextVis 方向 A(交互式压缩)不是从零造引擎,而是**可视化并接管**
> Hermes 已有的这套自动压缩。要让用户"治理"上下文,先得讲清楚系统现在**自动、不可见地**
> 怎么治理。源码:[`agent/context_compressor.py`](../agent/context_compressor.py)。

默认引擎 = `ContextCompressor`(`ContextEngine` 的默认实现)。一句话:
**保头、保尾,把中间多轮用辅助模型有损摘要掉**。

---

## 触发时机

[`should_compress()`](../agent/context_compressor.py#L744):当 `last_prompt_tokens >= threshold_tokens` 触发。

- `threshold_tokens = context_length × threshold_percent`,**`threshold_percent` 默认 0.50**
  (即占用过半就压;`hermes config set compression.threshold` 可改,注意 per-model autoraise)。
- **防抖**:若最近 2 次压缩**每次都只省了 <10%**,就停手不再压(避免每轮删 1-2 条的
  无限循环),并提示用户 `/new` 或 `/compress <topic>`。

---

## 压缩算法(5 个阶段)

[`compress()`](../agent/context_compressor.py#L1909):

| 阶段 | 做什么 | 映射到 ContextVis 的"命运"(`fate`) |
|---|---|---|
| **1. 预剪枝**(无 LLM,廉价) | [`_prune_old_tool_results`](../agent/context_compressor.py#L770):旧**工具结果**换成 1 行摘要(`[terminal] ran npm test → exit 0, 47 lines`);**同一文件读多次只留最新一份**;截断超长 tool_call 参数;[`_strip_historical_media`](../agent/context_compressor.py#L343) 剥离历史图片 | 旧 `file` / `tool_result` 带 → 多数 **fold/drop** |
| **2. 定边界** | 保**头** `protect_first_n=3`(system prompt + 首轮交换);保**尾**——不是固定条数,而是按 **token 预算**从后往前留(`tail_token_budget`,见下) | 头、尾 = **keep** |
| **3. 摘要中段** | 用**辅助模型**(便宜/快,可 `summary_model_override`)把头尾之间所有轮压成一段**结构化摘要**:带 Resolved/Pending 问题追踪、防注入"filter-safe"前缀(把旧轮当作素材而非指令) | 中段 `history` = **fold 成 summary** |
| **4. 迭代更新** | 再次压缩时,在**上一份摘要**基础上增量更新而非重头摘要,保信息跨多次压缩不丢 | summary 块自身被重写 |
| **5. 清理** | 修复因删除产生的**孤儿 tool_call / tool_result 配对**,保证 API 不收到错配 ID | 衔接修复(干预透明的前提) |

---

## 关键预算参数(构造函数默认值)

[`__init__`](../agent/context_compressor.py#L600) / [`update_model`](../agent/context_compressor.py#L572):

| 参数 | 默认 | 含义 |
|---|---|---|
| `threshold_percent` | `0.50` | 占用过半即压;`threshold_tokens = context_length × 此值`(带下限) |
| `protect_first_n` | `3` | 保护头部消息数(system prompt + 首轮) |
| `protect_last_n` | `20` | 保护尾部的**回退**条数(真实尾巴由 token 预算决定) |
| `summary_target_ratio` | `0.20` | 摘要目标 ≈ 被压内容的 20%;同时 `tail_token_budget = threshold_tokens × 此值` |
| `max_summary_tokens` | min 256 / 有上限封顶 | 摘要 token 的下限与天花板 |
| `abort_on_summary_failure` | `False` | 摘要失败时:False=插"summary unavailable"占位 + 丢中段(默认);True=整体放弃、冻结对话等手动 `/compress` |

> **直觉换算**:200K 窗口 → 阈值 100K(过半压)→ 尾巴保护 ≈ 20K(`100K × 0.20`)、
> 摘要目标 ≈ 被压内容的 20%。

---

## 与 ContextVis 的关系(为何这是方向 A 的基线)

现在这套策略是**自动、不可见、按 token 预算**地决定"谁 keep / 谁 fold / 谁 drop":

- ContextVis 的 `fate`(`keep | fold | drop`)字段正是为把这套**隐式策略画到 treemap 上**
  而设:头尾描"锁"(keep)、中段画"折叠"(fold→summary)、旧工具结果画"划掉"(drop)。
- 方向 A 阶段 3「应用」要**复用这个引擎**(把用户的 fate map 下发驱动 `compress()`),
  而非另造压缩逻辑。`compress(focus_topic=...)` 已支持"聚焦主题"压缩(类似 `/compact`),
  是用户交互式"合并重心 / 引导压缩"的天然落点。
- `_summarize_tool_result`、`_prune_old_tool_results` 的标签逻辑,ContextVis 分块已在
  复用(见 [built.md](built.md) tool_result 标签)——可视化层与压缩层共享同一套语义。

详见 [roadmap.md](roadmap.md) §交互式压缩。
