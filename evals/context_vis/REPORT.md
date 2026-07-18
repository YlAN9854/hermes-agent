# context-vis 语义单元生成评估报告

日期：2026-07-18 · 分支：`vis-demo` · 被测功能：`generate semantic view`（`ContextVisService.generate_units`，c3/c5 附带 `detect_salient`）· 生成模型：Hermes auxiliary 通道（deepseek-v4-pro）

## TL;DR

- **忠实度与溯源是系统强项**：5 个 case、200+ 个 source span 全部解析有效（`bad_spans=0`），盲评抽查 span 支持率 0.91–1.0，摘要**零捏造**（含 48k 字符日志中的具体数字全部核对无误）。
- **发现并修复一个阻断性缺陷**：LLM 引用跨硬换行的原文时将换行写成空格，`_resolve_quote` 精确匹配失败且重试无法逃逸——c5 连续两轮生成完全失败。修复（空白折叠归一化）后 c5 一次通过。
- **主要质量短板是过度切分**：会话越长单元越碎（c2/c3/c4 生成 17/12/24 个单元 vs gold 5/4/7 段），好在单元纯度极高（0.92–0.98，几乎不跨话题），损害的是导航效率而非正确性。
- **英文标题被 15 字符上限硬截断**（c4 有 5/24 个标题截在单词中间），规格的"≤15 字"是中文导向的。
- **salient 检测暴露 3 个真实问题**：ai_guessed 与 reliable 重复计数、ASCII 句点分句把 "Python 3.10" 截成 "Python 3."、`detect_salient` 不分批（超长会话必爆 prompt）。

## 评估方法

- **数据**：5 个合成长程任务会话（36–80 turns，15k–137k 字符），预埋 gold 标注（话题边界 / 约束 / 回溯点），以 `synth-c1..c5` 注入 `~/.hermes/state.db`，走与 Dashboard 完全相同的 service 代码路径生成。
- **双轨评估**：
  1. **程序化指标**（对照 gold）：边界 P/R/F1（精确 + ±1 turn 容差）、单元纯度、覆盖完整性、span 有效性、标题合规、约束召回；
  2. **子 agent 盲评**：每 case 一个独立 judge agent，只给 transcript + model JSON（不给 gold、不知生成机制），按 rubric（边界/忠实/覆盖/标题/溯源，c3/c5 加 salient）1–5 打分，强制用脚本抽取 span 验证、禁止目测偏移。
- 完整复现方法见文末。

## Case 一览

| case | 场景 | turns / chars | gold 段 | 生成单元 | 边界 F1(±1) | 纯度 | 生成耗时 |
|---|---|---|---|---|---|---|---|
| c1 | 多话题切换（中文） | 40 / 15k | 5 | **5** | **1.00** | **1.00** | 799s |
| c2 | 回溯/放弃路线（英文） | 50 / 21k | 5 | 17 | 0.30 | 0.92 | 377s |
| c3 | 约束密集散布（中文） | 36 / 15k | 4 | 12 | 0.43 | 0.97 | 638s* |
| c4 | 超长 3 批次（中英混合） | 80 / 137k | 7 | 24 | 0.41 | 0.98 | 1971s |
| c5 | 综合（英文为主+回溯+约束） | 60 / 26k | 6 | **7** | **0.73** | 0.97 | 591s*† |

\* 含 detect_salient 耗时。† 修复引文锚定缺陷后的成功运行；修复前两轮均整体失败（862s / 438s 后报错）。

## 盲评分数（1–5）

| case | 边界 | 忠实 | 覆盖 | 标题 | 溯源 | salient | span 支持率 |
|---|---|---|---|---|---|---|---|
| c1 | 5 | 5 | 4 | 4 | 4 | — | 0.92 (24 spans) |
| c2 | 4 | 5 | 4 | 4 | 4 | — | 1.00 (20 spans) |
| c3 | 4 | 5 | 4 | 3 | 4 | **2** | 0.91 (33 spans) |
| c4 | 3 | 4 | 5 | 3 | 5 | — | 0.95 (77 spans) |
| c5 | 5 | 5 | 4 | 3 | 4 | 3 | 0.96 (26 spans) |

盲评均一致确认：**无任何捏造事实**；判死路/结论的表述精准（c2 的 "Listener Parked" 而非 "disproven"；c5 的 PyMuPDF 单元恰好收在放弃建议处、下一单元开在用户明确折返的决定上，与 judge 的独立分段完全一致）；长日志中引用的数字（9m41s、89%=32/36、-62%/-56% 等）全部与原文吻合。

## 主要发现

### F1（阻断级，已修复）：跨换行引文锚定失败

`generate_units` 要求 LLM 返回逐字引文再解析为字符偏移。当原文含硬换行（`"no such\nproblem"`）时，模型引用必然写成空格（`"no such problem"`），`_resolve_quote` 的精确匹配与 Markdown 归一化回退都无法命中；温度 0.1 下重试会收敛到同类引文，导致**整批失败、无部分写入**。c5 两轮生成（4 次 LLM 尝试）全部死在同一个 turn 的散文段落上。

**修复**：`context_vis/service.py` 的 `_without_markdown_decorators` 扩展为同时折叠空白串（保持原始偏移映射，SpanRef 仍指向不可变原文）。13 个 context_vis 单测全绿，c5 修复后一次通过。证据：`runs/c5/error_before_fix.txt`。

**建议补充**：为该场景添加回归单测（跨换行引文 + 偏移正确性）。

### F2（设计级）：长会话系统性过度切分

c1（5=5）和 c5（7≈6）粒度正确，但 c2/c3/c4 切出 2.4–3.4 倍于 gold 的单元数：单 turn 成单元（c4 "Fix Request"）、连续动作被拦腰切断（flaky 修复弧 t036–t046 切成 5 个单元、性能优化循环在"我加上再跑一轮"和实际 diff 之间断开）。±1 容差下边界召回 0.75–1.0 而精确率 0.19–0.27——**真实边界几乎都被命中，问题是多切了大量假边界**。纯度 0.92–0.98 说明错误是"碎"而非"混"。

**影响**：总览导航效率下降；聚合层（Step 4，顶层 ≤8）可以兜底，但裁决模式下用户面对的单元清单会偏长。
**建议**：prompt 中加入粒度锚定（如"一个单元应覆盖一个完整任务弧，通常 ≥3 turns，除非发生真实话题切换"），或生成后追加一个轻量合并 pass（相邻单元同主题即并）。

### F3：15 字符标题上限对英文不友好

代码 `str(title)[:15]` 硬截断。c4 有 5/24 个标题截在单词中间（"IndexRebuild Fi"、"Migration summa"），c2/c3 各 1 个。中文 15 字信息量足够，英文 15 字符只有 2–3 个词。
**建议**：按显示宽度计（CJK 计 2、Latin 计 1，上限 30），或让模型自行控制长度、超限时重试而非硬切。

### F4：多子句摘要的 span 覆盖不完整（全部 judge 一致发现）

摘要句常含多个子句/事实，但只附 1 个 span，只证明其中一个子句（c1 "~400ms→9ms" 只引了 miss 侧日志；"422 validation" 子句无任何 span）。span 本身从不出错，但 hover 联动会让用户以为整句都有出处。
**建议**：prompt 要求"每个独立事实一个 span"，或让摘要分句更短（规格 §6.1 本就要求"分句要短、可独立映射"，当前生成偏长）。

### F5：salient 检测的三个具体问题（c3 salient_quality=2）

1. **重复计数**：去重条件要求 `detected_text` 与 span 完全相等，LLM 探索级返回的引文与 regex 保底级略有出入即通过去重——c3 的 prod-DSN 约束出现 4 次，全部 3 条 ai_guessed 都是 reliable 的变体重复。**建议**：按 span 重叠（而非相等）去重。
2. **分句正则截断**：`[^。.!?\n]+[。.!?]?` 把 ASCII 句点当句界，"Python 3.10" 被截成 "Python 3."，约束的实质（版本号）丢失。**建议**：句点后跟数字/小写字母时不断句。
3. **隐蔽约束全漏**：c3 的 4 条无祈使关键词约束（报表脚本依赖字段名、5 连接上限、备份窗口、"绝对不能打印手机号"——后者连 regex 关键词表都没覆盖"不能"）salient 层全部漏检；c5 同样：judge 独立找出 14 条硬约束，模型只检出 7 条（零误报、reliable 标注诚实），漏掉的包括用户明述的增值税税率白名单（3/6/9/13%）和驱动整个库选型折返的 AGPL 分发禁令。值得注意的是**漏检的约束大多出现在了摘要句里**——摘要层比 salient 层更能兜住隐式约束。这与铁律 6"宁可漏标"一致，但探索级 LLM pass 本应捕捉这类约束，c3 实际产出全是重复项、c5 零 ai_guessed 产出。**建议**：探索级 prompt 明确排除已检出内容、专注隐式约束；关键词表补"不能/别/绝不"。
4. **（附）`detect_salient` 不分批**：整个 transcript 塞单次 LLM 调用，c4 规模（137k 字符）必然超限，本评估只对 c3/c5 运行了它。**建议**：复用 `_turn_batches` 分批。

### F6：性能与 UX

单 case 生成 6–33 分钟（deepseek 通道，含语义校验重试），c4 三批耗时 33 分钟。Dashboard 目前只有 queued/running 状态轮询。**建议**：job 状态中透出批次进度（"batch 2/3"），必要时并行处理批次（当前串行）。

### 验证成立的设计不变量

- SpanRef 全部指向 B 且解析有效（5 case、0 bad span）；
- 覆盖完整性：所有 case `coverage_complete=true`，单元有序不重叠；
- 失败无部分写入：c5 两次整批失败后 state 干净，修复后重跑无残留干扰；
- reliable / ai_guessed 分开呈现（计数分离正确，但见 F5.1 的重复问题）。

## 产物与复现

```
evals/context_vis/
├── case_schema.py        # case 数据结构 + 校验
├── cases/c1..c5.py       # 5 个合成 case（含 gold 标注）
├── seed.py               # 注入 state.db（可重复执行，自动重置 synth-* 会话）
├── run_generate.py       # 走 service 层生成，导出 runs/<cid>/{transcript,model}.json
├── metrics.py            # gold 对照程序化指标
└── runs/<cid>/           # transcript / model / metrics / judge 判决 / c5 修复前错误
```

复现：
```bash
uv run --extra dev python -m evals.context_vis.seed          # 注入（默认 HERMES_HOME）
uv run --extra dev python -m evals.context_vis.run_generate  # 生成（真实 LLM 调用）
uv run --extra dev python -m evals.context_vis.metrics       # 指标
```

清理合成会话：
```bash
uv run --extra dev python -c "
from hermes_state import SessionDB; from hermes_constants import get_hermes_home
from pathlib import Path
db = SessionDB(db_path=Path(get_hermes_home())/'state.db')
def _wipe(conn):
    for cid in ['c1','c2','c3','c4','c5']:
        conn.execute('DELETE FROM messages WHERE session_id = ?', (f'synth-{cid}',))
        conn.execute('DELETE FROM sessions WHERE id = ?', (f'synth-{cid}',))
db._execute_write(_wipe); db.close(); print('cleaned')"
```

## 改进建议优先级

| 优先级 | 项 | 对应发现 |
|---|---|---|
| P0 | 提交空白折叠修复 + 跨换行引文回归测试 | F1 |
| P0 | salient 去重改为 span 重叠判定；分句正则修复 | F5.1 / F5.2 |
| P1 | 粒度锚定 prompt 或合并 pass | F2 |
| P1 | 标题按显示宽度限长，禁止 mid-word 硬截断 | F3 |
| P1 | 每个事实一个 span / 更短分句 | F4 |
| P2 | detect_salient 分批 | F5.4 |
| P2 | 批次进度透出 | F6 |
