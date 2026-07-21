# Tier 2 端到端验收（真实长会话）

日期：2026-07-21 · 分支：`vis-demo` · 目的：用真实 agent 会话（而非脚本化 `archive_and_compact` 重放）验证 Tier 2 压缩可视化，填补 REPORT.md Tier 2 轮标注的 P2 缺口。验收判定由独立 sub agent 完成，不与实现/运行同体。

## 场景

隔离 HERMES_HOME，`model.context_length=64000`（Hermes 允许的下限）、压缩阈值 0.75 → 约 48K tokens 触发。一个 164KB 的真实 Python 项目 `logpipe`（5 模块 + 88KB 样本日志），11 轮审计会话，**第 1 轮交代三条硬约束**（不得改 schema.sql / 保持 Python 3.9 / API key 走环境变量），后续读码、读日志、统计、改码、验证。

**真实压缩确实发生**：第 6 轮 `last_prompt_tokens` 到 49,842 越过阈值 → Hermes 自动压缩，上下文 26K→12.5K tokens，`compression_count` 0→1，探针写入 1 条记录。无任何脚本直接调用压缩函数。

## 结果：核心机制成立，但真实会话暴露 3 个合成用例碰不到的 bug

### PASS（独立 auditor 确认）

- **探针记录准确**：dropped 集合（msg 5–17）、摘要文本（忠实前缀、end-marker 正确剥除）、各计数与 DB 完全一致，无 off-by-one。
- **B 层完整（铁律）**：59 turns 全部可取回，含被压缩丢弃的；B 中不含摘要文本。
- **A 与 B 分离正确**：A=37 条/59.7K 字符 vs B=59 turns/148.5K；恰好一条合成摘要 `origin_turn_id=None`，其余均链接回 B。
- **关闭降级**：`HERMES_CONTEXT_VIS_PROBE` 未设时连目录都不建。

### FAIL-1：同一次 in-place 压缩返回两个事件（时间戳 precedence 失效）

`get_compression_events()` 对 1 次真实压缩返回 2 个事件：正确的 `observed`（探针）+ 幽灵 `reconstructed`（重建）。根因：Tier2-6 的去重靠时间戳比较，而探针 `ts`(…215.980) 比 synthetic 摘要行的 DB `ts`(…215.965) 晚约 **15ms**（`archive_and_compact` 先写行、探针在调用点之后才触发），故重建块永远略早于观测记录，抑制条件 `block.ts >= before_ts` 永不成立。单测用相距极远的合成时间戳（观测 `ts=1e12`）恰好掩盖了它。

### FAIL-2：重建事件本身在 in-place 下不准

幽灵事件把存活的 head 行（msg 1–4）误判为 dropped（观测 dropped=13/kept=17，重建 dropped=17/kept=13，近乎对调）。in-place 压缩下存活 head 行位于摘要行之前，分块归属错误。影响：`event_count` 双计、survival note "1 of 2 compaction(s) reconstructed" 错误。

### FAIL-3：`generate_units` 在真实工具输出上整批失败（B 内容保真）

`generate_units` 崩于 `source quote is absent from turn hermes-msg:3`。根因：**adapter 的 `_text()` 不解包工具结果的 JSON 信封**。22 个 tool turns 里有 **13 个**的 B 内容是 `{"content": "1|# logpipe\n2|..."}` 形态——read 工具输出被存成 JSON 编码字符串（含 `N|` 行号前缀、转义换行、`{"content":…}` 外壳）。`_text()` 原样返回，于是 B 对这些 turn 暴露的是转义 JSON 而非可读文本。后果有二：(a) LLM 引用可读文本，无法在转义信封里解析到，整批失败；(b) 用户在"真相层"看到的是 JSON blob 而非模型实际看到的文本——直接触及铁律。`json.loads(content)["content"]` 可还原可读文本，确认是解包缺失。

**注**：因 FAIL-3 阻断 `generate_units`，本会话上的存活状态（present/reframed/absent）三态判定未能端到端跑通。存活匹配器本身已在 c6 独立验证为 3/3（P/R 均 1.0），故此处缺口是 B 内容保真问题所致，非匹配器问题。

## 结论

Tier 2 的骨架是对的——探针忠实、A/B 分离正确、B 不可变性守住、降级诚实、匹配器（c6 验证）可用。但**真实会话把三个合成用例结构上碰不到的缺陷抖了出来**：一个 15ms 级的时序去重 bug、一个 in-place 重建的分块 bug、一个工具结果 JSON 信封的解包缺失。这正是端到端验收的价值——它们全都逃过了单元测试与合成 eval。

## 修复优先级

| 优先级 | 项 | 对应 | 影响面 |
|---|---|---|---|
| P0 | `_text()` 解包 `{"content":…}` 工具结果信封（并考虑 `N|` 行号归一化） | FAIL-3 | B 保真 + generate_units 在真实会话可用 |
| P0 | 事件去重改为非时间戳（按 lineage 成员 observed 数抑制最近 K 个重建块） | FAIL-1 | 事件计数正确 |
| P1 | in-place 重建分块修正（存活 head 行归属） | FAIL-2 | 重建保真 |
| P1 | 补真实相邻时间戳 / JSON 信封 / 行号前缀的回归测试 | 三者 | 防回归 |

复现：驱动脚本 `/home/hermes/.claude/jobs/13d26faf/tmp/run_session3.py`（关键：必须把 `result["messages"]` 回填为下一轮 `conversation_history`，否则上下文不累积、压缩不触发——`-z` oneshot 无状态，chat REPL 吞整段 stdin）。

## 修复（2026-07-21，全部按优先级顺序完成并在真实会话数据上验证）

| 项 | commit | 验证 |
|---|---|---|
| FAIL-3 `_text()` 解包工具 JSON 信封 | `fb573b1f` | 22 个 tool turns 0 残留 JSON；auditor 报的失败引文 `API_KEY = os.environ.get("LOGPIPE_API_KEY", "")` 现可解析 |
| FAIL-1 事件去重改摘要匹配（非时间戳） | `fb573b1f` | 真实会话 `get_compression_events()` 返回 1 个事件（原 2 个） |
| FAIL-2 重建把 active turn 计入幸存 | `8a9e5958` | 真实边界重建 dropped=13/kept=17，head msg 1–4 正确在 kept，与探针一致 |
| FAIL-4（附加发现）全角 ； 断句 | `b903630b` | 三条枚举约束由 1 条拆为 3 条，"Python 3.10" 不误拆 |
| FAIL-5（贯通时新发现）行号前缀 NN\| 引文归一化 | `610c055e` | LLM 引 `55\|` 而 B 是 `54\|`（错行号），归一化忽略前缀后可解析；B 保留行号 |

单测 44→50 全绿。

**最终贯通确认（provider 恢复后，2026-07-21）**：完整 `generate_units→detect_salient→refresh_survival` 在真实压缩会话上**一次跑通**，机械完整性核查全部通过：
- 41 个摘要 span **0 个失效**（全部解析回 B）——五个引文族修复协同生效，`generate_units` 干净完成；
- 5 条 salient，`span_in_B` 与 `detected_text` **全部精确一致**（指针纪律贯穿全链）；
- **FAIL-4 真实数据确认**：三条约束是三条独立 badge（第一/第二/第三），各判 `present`（turn 1 逐字存活）；
- **`absent` 路径真实触发**：被压缩丢弃的 report.py 约束 "the column order is load-bearing" 正确判 `absent`；
- **FAIL-1 真实数据确认**：`event_count=1`，无重复。

`reframed` 路径本会话未真实触发（turn 1 逐字存活），已在 c6 合成用例独立验证 3/3。**存活判定正确性**此前已由独立 auditor 在真实 A/B 上复现确认。至此端到端验收全部闭环。

---

# Tier 3 preserve 端到端验收（2026-07-21）

用户主导保留：勾选的原文轮次被 pin，压缩时保留 verbatim 而非摘要掉。后端全做，UI 往后（见 plan）。实现 5 提交：`31f96111`（domain+adapter+核心 pin 感知压缩）、`a19a9f45`（同步 preserve 端点）、`1de06ad7`/`8555b21f`（loader + 全链去混淆测试）、`8809ae30`（拒绝不可保留轮的修复）。单测 72 全绿。

**关键前提**：规格 §5.5 说的"Hermes 方向一已验证的机制"不存在——压缩保护纯位置式（头 N + 尾按 token），无逐消息 keep 标记。本轮建成：adapter 写 pin 文件 `<HOME>/context-vis/pins/<session>.json`，核心 `compress_context` 读纯 JSON（不 import context_vis）设 `_keep_turn_ids`，`compress()` 把 pin 轮移出摘要窗口、摘要后 verbatim 重插。

## 多层验证

- **核心（确定性）**：`compress()` 单测——pin 的中间轮 verbatim 存活、未 pin 的被摘要；无 pin 时逐字节不变。
- **loader（确定性）**：`_load_pinned_turn_ids` 读 pin 文件，缺失/坏文件/未知版本降级为空集。
- **全链去混淆（确定性）**：真实 pin 文件 → 真实 loader → 真实 `compress()`，受控消息布局使 pin 轮确在窗口内——pin 轮保留、未 pin 邻居被摘要。
- **真实会话（独立 auditor 判定）**：见下。

## 真实会话验收（独立 sub agent 判定，两轮）

驱动真实 Hermes agent 连续会话至真实自动压缩，中途 pin 一轮，独立 auditor 从产物+DB 自行核验。

**第一轮 PARTIAL（auditor 抓出真实缺陷）**：盲位置选中的 pin 轮恰是一个"只含 tool_call、无文本"的 assistant 轮；pin 保住了槽位，但其配对 tool_result 被压缩丢弃，`_sanitize_tool_pairs` 剥掉了孤立的 call → 该轮以 `"(tool call removed)"` 存活，**非 verbatim**。这是真实正确性缺陷，非测试假象。

**修复（`8809ae30`）**：`request_preserve` 现在**透明拒绝**不可保留轮（tool 轮、无文本 assistant 轮），在 PreserveResult.note 说明并指向文本轮，而非 pin 一个注定被剥离的东西。预期用途（pin 用户约束＝实质文本轮）不受影响。

**第二轮 PASS（独立 auditor 复核）**：pin 一条实质用户约束轮（msg 5）。真实压缩丢弃了 msg 4 与 6–29 连续块，**只留下 pin 的 msg 5**——`B.content == A.content` 逐字节一致，作为独立 `synthetic=false, role=user` 条目存在（非摘要内引用），两个邻居（4、6）均被摘要。auditor 四点全过 + 回归确认 `"(tool call removed)"` 失败模式消失。

## 结论

Tier 3 后端完成并端到端验证：pin 使一个本会被压缩丢弃的实质文本轮 verbatim 存活于 A。独立验收先抓出 tool-call 轮的真实缺陷、修复后复核为 PASS。安全性：pin 总量有上限（防 thrash），不可保留轮被拒。剩余：UI 勾选/取消（端点已就绪）。
