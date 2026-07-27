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

## 改进建议优先级（首轮，已被 Hardening 轮消化，见下）

| 优先级 | 项 | 对应发现 | 状态 |
|---|---|---|---|
| P0 | 提交空白折叠修复 + 跨换行引文回归测试 | F1 | ✅ 已修复+回归测试 |
| P0 | salient 去重改为 span 重叠判定；分句正则修复 | F5.1 / F5.2 | ✅ 已修复 |
| P1 | 粒度锚定 prompt 或合并 pass | F2 | ◐ prompt 锚定已做，合并 pass 仍缺 |
| P1 | 标题按显示宽度限长，禁止 mid-word 硬截断 | F3 | ◐ 限宽已做，"…"截断仍被扣分 |
| P1 | 每个事实一个 span / 更短分句 | F4 | ✗ 未做，三 judge 共同扣分点 |
| P2 | detect_salient 分批 | F5.4 | ✗ 未做 |
| P2 | 批次进度透出 | F6 | ✗ 未做 |

---

# Hardening 轮（2026-07-19）

对首轮 P0/P1 的修复与复验。代码改动：`9effe046`（salient 去重/分句/关键词/探索 prompt、标题限宽、粒度锚定、跨换行回归测试）+ eval 支撑（`delete_model` 重生成、`run_incremental` 增量验收）。单测 13→20，全绿。

## H1：粒度是 prompt 敏感的——单向措辞直接塌缩（重要教训）

第一版粒度锚定含 "prefer fewer, larger units"（单向压缩压力），结果 c2（50 turns）、c3（36 turns）**整场塌缩为 1 个单元**（纯度掉到 0.24/0.31），c4 靠三批次强制边界才剩 8 个。改为**双侧锚定**（"典型 3–12 turns；一 turn 一单元和一单元吞掉长会话都错"+ 以子目标/组件/bug/交付物为切换判据）后收敛：

| case | gold 段 | 首轮 units | 单向锚定 | 双侧锚定 | 边界 F1(±1) 首轮→现在 | 纯度 首轮→现在 |
|---|---|---|---|---|---|---|
| c2 | 5 | 17 | **1** | **7** | 0.30 → **0.60** | 0.92 → 0.92 |
| c3 | 4 | 12 | **1** | **7** | 0.43 → **0.667** | 0.97 → 0.972 |
| c4 | 7 | 24 | 8* | 18 | 0.41 → 0.435 | 0.98 → 0.975 |

\* 三批次强制边界下的最小值附近，不代表 prompt 收敛。

c2/c3 单元数减半以上、F1 显著上升、纯度不损。c4（137k 字符、3 批次）仍 2.6× gold——**批内可控、跨批粒度漂移**，结构性修复（生成后相邻同主题合并 pass）仍是 P1。

**方法论发现**：c2 盲评 judge 的独立分段与生成的 7 个单元完全一致（边界 5 分），而 gold 只有 5 段——gold 粒度不是唯一合理答案，对 gold 的边界 F1 系统性低估切分质量，应结合盲评读数。

## H2：增量追加验收通过，Step 0–2 里程碑关闭

`run_incremental`（synth-c1 + 5 个新 turns 的新话题，真实 LLM，132.6s）全部 5 项断言通过：旧单元**逐字节不变**、用户 `user_edited` 聚合原样保留、新 turns 恰好生成 1 个新单元且只追加、草稿节点正确挂接。计划书首个里程碑的验收缺口（铁律 3 端到端）已补上。

## H3：salient 修复生效，暴露下一层问题

c3（12 条 gold 约束）：首轮探索级产出全是重复项、隐蔽约束全漏 → 现在 **recall_any 0.917**、reliable 13 / ai_guessed 3、16 条全部逐字精确且值完整（"Python 3.10" 不再被截断）。残留（按影响排序）：

1. **跨位置重复**（新发现）：同一约束文本在 B 中多处出现（conftest 警告出现在 t029 与 t031 两处）→ 3 条独立 salient。span 重叠去重管不了不同位置的相同文本。候选：按归一化文本全局去重（保留首现、记录出现次数），或 UI 层聚合。
2. **kind 语义**：LLM 探索级找到的逐字用户约束被标 `other/ai_guessed`。confidence 语义正确（表达检测通道可信度），但 kind 可依据 span 所在 turn 的 role 细化为 user_stated_constraint。
3. 相邻分句把一条约束拆成两条（"别别别，这个不能省。"+ 后续完整句）——轻微，属分句粒度问题。

## H4：盲评分数对比（首轮 → hardening 轮）

| case | 边界 | 忠实 | 覆盖 | 标题 | 溯源 | salient | span 支持率 |
|---|---|---|---|---|---|---|---|
| c2 | 4→**5** | 5→5 | 4→4 | 4→4 | 4→4 | — | 1.00→0.95 |
| c3 | 4→4 | 5→5 | 4→4 | 3→3 | 4→4 | 2→**3** | 0.91→0.85* |
| c4 | 3→**4** | 4→**5** | 5→4 | 3→**4** | 5→5 | — | 0.95→**1.00** |

\* 本轮 c3 judge 对"多子句句仅锚定单子句"计半分，口径比首轮更严；按首轮口径无回退。

三 judge 再次一致确认**零捏造**（c4 judge 复算了 -62%/-56% 的三次均值算术；c2 judge 核对了 +14,382 泄漏连接等全部数字）。共同的最大扣分点仍是 **F4（多子句摘要句仅一个 span）**——升为 P1 首位。标题"…"截断（每 case 1–2 个）仍被扣分：限宽止住了 mid-word 破坏，根治需让模型自控长度、超限重试。

## Hardening 轮剩余改进优先级

| 优先级 | 项 | 来源 |
|---|---|---|
| P1 | 每个独立事实一个 span / 更短摘要分句 | F4，三 judge 一致 |
| P1 | 生成后相邻同主题合并 pass（治 c4 类超长跨批碎化） | H1 |
| P1 | salient 跨位置文本去重（保留首现+出现计数） | H3.1 |
| P2 | 标题模型自控长度+超限重试（替代"…"截断） | H4 |
| P2 | salient kind 按 span 来源 role 细化 | H3.2 |
| P2 | detect_salient 分批（解锁 c4 类会话） | F5.4 |
| P2 | 批次进度透出 | F6 |

复现本轮：`run_generate c2 c3 c4` → `metrics c2 c3 c4` → 盲评产物在 `runs/<cid>/judge_v2.json`；增量验收 `python -m evals.context_vis.run_incremental`（产物 `runs/c1/incremental_check.json`）。

---

# P1 轮（2026-07-19）

消化 Hardening 轮遗留的三个 P1。代码：`e155ff6c`（合并 pass、每事实一句、salient 跨位置去重）+ 歧义引文重试兜底。单测 20→24。

## P1-A：合并 pass 让单元数收敛到 gold 量级

批内生成看不见批边界，长会话必然跨批碎化。新增生成后合并 pass：对**本次新生成**的单元跑一次 LLM 相邻同主题归组（连续索引、全覆盖校验，任何非法响应静默回退到未合并结果，永不触碰 frozen 单元、永不改动 SpanRef）。

| case | gold 段 | 首轮 | 单向锚定 | 双侧锚定 | **+合并 pass** |
|---|---|---|---|---|---|
| c2 | 5 | 17 | 1 | 7 | **5** |
| c3 | 4 | 12 | 1 | 7 | **4** |
| c4 | 7 | 24 | 8 | 18 | **6** |

三个 case 全部落到 gold 量级（首轮为 2.4–3.4×）。边界质量：

| case | 边界 F1(±1) 首轮→双侧→**+合并** | 纯度 首轮→**+合并** | 盲评边界分 |
|---|---|---|---|
| c2 | 0.30 → 0.60 → 0.50 | 0.92 → 0.84 | 4 |
| c3 | 0.43 → 0.667 → **0.667** | 0.97 → 0.917 | —(未重评) |
| c4 | 0.41 → 0.435 → **0.909** | 0.98 → 0.863 | 4 → **5** |

**c4（137k 字符、跨 3 批）是最大赢家**：F1(±1) 0.435→0.909，judge 独立任务图与 6 个单元**逐 turn 吻合**，边界给满分——跨批碎化这个结构性问题被治住了。

**代价要诚实记录**：纯度普遍下降（c2 0.92→0.84，c4 0.98→0.863），c2 judge 指出最大单元（17 turns）把根因诊断、修复、验证、CI 加固折叠在一起，标题 "Heartbeat Leak Fix" 低估了范围。**合并 pass 把误差从"切太碎"移到了"偶尔并太宽"**，总体是净收益（导航效率提升、边界更贴合真实里程碑），但下一步应给合并 pass 一个上限约束（如单元不超过 ~12 turns 或不跨越显式里程碑声明）。

## P1-B：每事实一句显著提升引文覆盖

prompt 改为"每句只述一个事实、引文须覆盖句内每个断言"后，摘要分句数大幅上升（c4 22→69，c3 20→43，c2 16→22），句子变短、每句仍配约 1.1 个 span，但**每个 span 现在能覆盖整句**：

- c4 judge 校验**全部 78 个 span**（此前 32），span 支持率 **0.98**；
- c2 judge 校验全部 23 个，支持率 **0.96**（仅 2 句为部分覆盖）；
- 两位 judge 都不再把"多子句仅锚一子句"列为主要问题——首轮三 judge 一致的最大扣分点基本消解。

残留：c4 有 1 句跨 turn 归纳（用户提问 + 助手回答合并为一句）只引了助手侧；c2 有 2 句把因果前提与结论捆在一句只引结论半边。属长尾。

## P1-C：salient 跨位置去重生效

c3 的 conftest 警告此前在 B 中三处出现→3 条独立 salient；现在合并为 1 条 `occurrences=3`（新字段，`span_in_B` 保留首现，向后兼容）。c3 salient 总数 16→14，gold 约束 `recall_any` 保持 **1.0**、reliable 11 / ai_guessed 3。

## P1-D：歧义引文不再整批失败（新修）

c3 第四轮首次生成整批失败于 `source quote is ambiguous: 'NO_SQL_CONCAT'`——该标识符在同一 turn 出现多次，模型未给 `char_start`，重试仍给不出。同一文本的每次出现携带的证据完全相同，因此**重试轮**放宽为锚定首次出现（首轮仍严格要求 `char_start`，保持精确优先）。修复后 c3 一次通过。这与 F1（跨换行）同类：**引文解析的严格性不该成为整批失败的单点**。

## 增量不变量复验

改动涉及生成主路径，重跑 `run_incremental`：5 项断言依旧全过（旧单元逐字节不变、用户聚合未动、新 turns 只追加），74.5s。合并 pass 只作用于本次新生成单元的设计得到验证。

## 当前状态与后续

Step 0–2 的质量问题（过度切分、引文覆盖、salient 噪声、两类整批失败）已系统性解决，三个 case 的单元数、边界 F1、span 支持率、约束召回全部达到或接近 gold 量级，忠实度自始至终零捏造。**建议下一步转入 Tier 2（压缩可视化 + Hermes compression probe）**，剩余长尾随后续迭代处理：

| 优先级 | 项 | 来源 |
|---|---|---|
| P2 | 合并 pass 上限约束（防 c2 类过度合并） | P1-A |
| P2 | 标题模型自控长度 + 超限重试（替代"…"截断） | H4 |
| P2 | salient kind 按 span 来源 role 细化 | H3.2 |
| P2 | detect_salient 分批（解锁 c4 类超长会话） | F5.4 |
| P2 | 批次进度透出（c4 单次 19 分钟无进度反馈） | F6 |
| P3 | 跨 turn 归纳句的多 span 引用 | P1-B 残留 |

复现 P1 轮：`run_generate c2 c3 c4` → `metrics c2 c3 c4` → 盲评产物 `runs/<cid>/judge_v3.json`；增量验收同上。

---

# Tier 2 轮（2026-07-19）：压缩可视化

规格 §5 的差异化核心。代码：`0fcd4398`（类型 + survival 修复）、`2a0b6a20`（探针）、`f4b08200`（adapter 探针路径 + 动态 tier）、`c1d67478`（历史重建）、`9da146f8`（service/API 接线 + 阈值校准）、`c761b60d`（前端）。单测 24→44，前端 vitest 73 全绿。

## T1：规格声称的探针不存在，本轮建成

§1 写「Hermes：由现有探针插件的 dump 提供（messages_before/after/summary）」——探查确认 `VALID_HOOKS` 里**没有任何 compaction 钩子**，唯一现有信号 `conversation_compression.py:948` 的 `session:compress` 事件只带 id 与计数器。

新增 `agent/compaction_probe.py`：默认关（`HERMES_CONTEXT_VIS_PROBE`），核心调用点 8 行（import 置于自身 try 内），模块内吞 `BaseException`。**只记 turn id 与摘要全文，不记消息体**——消息体已在 state.db 且可由这些 id 寻址，再存一份就是复制真相层（正是「索引 vs 真相」铁律要防的）；唯一事后不可恢复的是被后续压缩取代的摘要，故只全文存它。杠杆点是 `run_agent.py:1911` 把 `_transcript_turn_id` 盖在活的内存 dict 上、且 `_fresh_compaction_message_copy` 保留它，故探针点上 before/after 两侧都带 B 溯源。

**历史会话不依赖探针**：`archive_and_compact` 非破坏性，压缩会留下「摘要行 + 其保留的 turn 副本」，故合成行即分代边界，**同时出现在相邻两代的 turn 即为跨越该边界存活者**。据此重建 pre-probe 历史，全部标 `fidelity="reconstructed"` + note。仅重建早于最早观测记录的边界，避免同一边界被两种来源各算一次。

## T2：survival 引擎此前不可能工作（本轮两次修正）

`survival.py` 是死代码，且有一个上线即失效的缺陷：reframed 拿**整条 turn 正文**做 `SequenceMatcher.ratio()`，而 ratio 是 2M/T——43 字符约束落在 2.8k 字符、确实包含其重述的摘要里得分 **0.0035**（默认 `autojunk=True` 还会把散文里的空格与多数元音当噪声丢弃，再恶化约 5.6 倍）。reframed 分支永不触发，§5.3 的旗舰功能会直接死掉。

改为**片段窗口评分**后，用真实压缩会话验证时又发现两个问题，均由数据而非推测定位：

1. **锚点门限只看最长公共块**，导致重写较重的英文改述（匹配散落在多个短块）被拒——改为按全部公共块之和计量。
2. **0.62 阈值从未被验证**：真实改述隔离比对也只有 0.51–0.57。校准后降到 0.50。

随后 c6 评估暴露了第三个、也是最根本的问题：**中文改述会重排字符**，「绝对不能在日志里打印客户手机号」→「任何日志输出都必须对客户的手机号码做脱敏」只剩 5 个连续匹配字符，字符相似度 0.359——**低于不相关英文文本的 0.442**。字符序列相似度单独使用在中文上不成立。

最终方案：**窗口分数 = 字符序列相似度与 token 覆盖率的均值**。两个信号缺一不可——中文靠 token 覆盖率（0.667 vs 不相关 0.158），英文靠序列相似度（token 覆盖率会被 stopword 抬高）。混合后跨两种语言：

| | 正例（真实改述） | 负例（不相关） |
|---|---|---|
| 单用字符序列 | 0.359–0.890 | 0.0–0.442（**重叠**） |
| 单用 token 覆盖 | 0.667–0.857 | 0.0–0.143 |
| **混合（采用）** | **0.479–0.890** | **全部 0.0** |

阈值定 0.40，落在完全分离的间隙中。`reframed_text_in_A` 存的是窗口对应的原文片段（词边界吸附、上限 4× 约束长度），而非整条 turn——`reframed_fragment_ratio` 实测 0.108。

## T3：c6 评估（新增 case）

20 turns、2.8k 字符的小案例，脚本化重放一次压缩，三条约束分别对应三种命运：一条在保留的 turn 里逐字存活、一条被摘要改述、一条被丢弃且从未重述。`case_schema` 的校验强制 gold 自洽（标 `reframed` 的约束原文**不得**逐字出现在 A 中，否则诚实答案是 `present`，测的就是错的分支）。

| 指标 | 结果 |
|---|---|
| A/B 分离 | B 保留全部 20 turns；A 为 6 条（5 保留 + 1 合成摘要）；事件 1 次，丢弃 15 / 保留 5 |
| 三状态判定 | **3/3 正确**，present / reframed / absent 的 P 与 R 均为 **1.0** |
| `reframed_fragment_ratio` | 0.108（接近 1.0 即代表整条 turn 的老 bug 复发） |
| tier / fidelity | 2 / observed |

指标区分「未被检出」与「检出但判错」——salient 检出率是另一项测量，不应污染存活判定的分数。

## T4：铁律核对

- **A 侧永不产生指针**：`ActiveEntry` 刻意不设 `turn_id`，只有可空的 `origin_turn_id`；复用 `Turn` 会诱导 `SpanRef(active.turn_id, …)` 而类型系统拦不住。A 的匹配结果只以纯文本进 `reframed_text_in_A`。
- **降级是隐藏**：`summariseSurvival` 在 tier<2 或无已知状态时返回 `null` 而非零值——「0 条被改述」会被读成结论，而非「没有可见性」。Tier 1 会话 UI 与本轮之前逐像素一致（有测试断言）。
- **tier 由「A 是否可读」判定**，而非「有无压缩事件」：从未压缩的会话事件数为 0 但状态真实全为 present，隐藏属过度降级；压缩相关表述另由 `capabilities.compression_events` 把关。
- **陈旧不谎报**：`reframed_text_in_A` 是可变 A 的快照，下次压缩即过期。`load()` 只比对 A 的指纹并给出 `survival_stale`，**不在读路径持久化**（否则每次 GET 顶掉 revision，用户下次保存必 409）。

## 后续

| 优先级 | 项 |
|---|---|
| P1 | 用更多语言/改述强度扩充 c6，把阈值 0.40 放到更大样本上复核 |
| P1 | 压缩事件面板（历次压缩、丢弃了哪些 turn、摘要全文）——本轮有数据无 UI |
| P2 | §5.2 提到的 LLM 细判（当前确定性版本已达 3/3，暂无必要） |
| P2 | Tier 3 `request_preserve` 回写 |
| P2 | 真实长会话跑满压缩阈值的端到端验收（本轮用脚本化重放） |

复现：`seed c6` → `run_generate c6` → `run_survival c6` → `metrics c6`；探针端到端：置 `HERMES_CONTEXT_VIS_PROBE=1` 后跑真实压缩，记录落在 `<HERMES_HOME>/context-vis/compaction/<session>.jsonl`。

## c7（2026-07-26）：研究方法头脑风暴的意图漂移 gold

c7 是一个 28 turns、5,105 字符的检索 agent 评估方法头脑风暴，gold 分成四段：A（benchmark question，0–6）→ B（annotation protocol，7–13）→ C（statistical pilot，14–20）→ B return（21–27）。确定性校验观测到 4 个约束、1 个合法 Backtrack（segment 3 → 1）和 3 个 `IntentShift`：segment 1 drift（cause turn 6）、segment 2 drift（cause turn 13）、segment 3 return（cause turn 20）。存活 gold 覆盖 present、reframed、absent 各一条。

三条研究式约束（license 不得再分发 raw passages、annotation budget 上限 `$200`、预注册 query-difficulty 分层）在 `CONSTRAINT_RE` 上均未命中；另一条 `Do not change the held-out test split after analysis begins.` 命中 imperative 规则。该分布是 c7 的确定性输入设计，不是模型召回率结论。

隔离 `HERMES_HOME` 下运行 `uv run --extra dev python -m evals.context_vis.seed c7` 成功创建 `synth-c7`，输出 stats 为 `turns=28`、`chars=5105`、`segments=4`、`constraints=4`、`backtracks=1`、`intent_shifts=3`；随后检查到 11 条存储行、存在合成摘要且 `validate_case` 返回空错误列表。本次隔离 home 未配置 auxiliary provider，故未运行 `run_generate`/survival/metrics，也没有预先声称 c7 的模型 recall 或 survival 分数。
