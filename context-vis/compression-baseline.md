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

## 与 ContextVis 的关系 —— 定位区分 + 复用边界

> 阶段 3 动手前的核心判断。结论:**我们与默认压缩正交、互补,不是替代**;
> 而**摘要/剪枝/缝合的轮子几乎全可复用,我们只新增"选择"那一环**。

### 1. 为什么不能只用默认压缩?——两者不在同一个轴上

默认压缩器的选择逻辑全是**位置启发式**:保头(前 3)+ 保尾(~20% token)+ 摘中间,
判据是"旧 = 该压"。它**自动、不可见、零用户话语权**。它的盲区正源于"按位置切":

| 默认压缩做不到 | 场景 |
|---|---|
| **按内容选** | 受保护的尾巴里有 5 条失败 grep(垃圾),它不动;中段有关键 spec,它给摘掉 |
| **按语义选** | 想"丢这条支线、留那个文件",但二者位置交错,位置切法分不开 |
| **逐块不同命运** | 它只有一种动作(中段→摘要);用户想这块 drop、那块 fold、第三块 pin |
| **主动治理** | 没到 50% 就想提前清掉明显噪音 |
| **透明** | CLAUDE.md 立身之本"干预必须透明";默认压缩恰恰是**静默**改动 |

ContextVis 交互式压缩走的是**内容/意图轴**,与"位置/新旧"**正交**:

> **默认压缩 = 自动安全网**(你没看时按位置兜底)
> **交互式压缩 = 手动手术刀**(自动网做错、或想主动策展时上场)
> 后者全部理由 = 把前者"固定策略 + 零话语权"的黑盒,变成可治理的白盒。
> 二者**并存**:默认继续兜底,我们加一条"用户随时可介入"的并行路径。

### 2. 复用边界 —— 把压缩拆成「选择层 / 执行层」

```
选择层(选哪些块、什么命运) ←── ContextVis 唯一要新增的(用户经 UI 驱动)
   ↓ 喂给
执行层(怎么摘要 / 剪枝 / 缝合) ←── ContextCompressor 已造好,直接复用
```

**执行层现成轮子(复用,勿重写)**:

| 轮子 | 位置 | 复用为 |
|---|---|---|
| `_generate_summary(turns, focus_topic=)` | [:1233](../agent/context_compressor.py#L1233) | **fold**:一组消息 → 辅助模型结构化摘要。签名干净(吃任意 msg list) |
| `_prune_old_tool_results` | [:770](../agent/context_compressor.py#L770) | **drop/fold tool_result**:去重 + 工具结果转 1 行,无 LLM |
| `_sanitize_tool_pairs` | [:1619](../agent/context_compressor.py#L1619) | **删除后必跑**:修复孤儿 tool_call/result 配对,API 不收错配 ID |
| `_summarize_tool_result` | [:400](../agent/context_compressor.py#L400) | 已在 chunking 复用做标签(可视化与压缩共享语义) |
| `focus_topic` 管道 | [:1420](../agent/context_compressor.py#L1420) | "keep 某主题"可映射成软提示(该主题给 60-70% 摘要预算) |

**唯一不复用的一环** = 它**按位置选窗口**(`_protect_head_size` /
[`_find_tail_cut_by_tokens`](../agent/context_compressor.py#L1792) / `_align_boundary_forward`)。
我们用**按命运选**取而代之:

```
fate=drop → 收集这些块的真实 message 索引 → 删 + 跑 _sanitize_tool_pairs
fate=fold → 收集索引 → 喂 _generate_summary(复用)→ 替换
fate=keep → 排除在可压集合外(内容寻址的"保护",取代位置寻址的头/尾保护)
```

而"块 → 真实 message 索引"这座桥,**档3 早已埋好** = 每个 chunk 的 `sourceRefs`
(provenance)。当初留这个字段就是为这一刻。

> **结论**:阶段 3 = 新增一层薄薄的「fate → 消息选择」映射,把活儿**转包给现有引擎**。
> 不造摘要轮子、不造缝合轮子。新增代码量小;**风险集中在"选择",不在"压缩"本身**。
> (那条命令通道**已实测可用**,不再是风险点,见 [phase3-channel.md](phase3-channel.md)。)

详见 [roadmap.md](roadmap.md) §交互式压缩、[phase3-channel.md](phase3-channel.md) §命令通道证据链。
