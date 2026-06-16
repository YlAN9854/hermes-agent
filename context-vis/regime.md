# 任务态识别 —— ContextVis 的自适应总开关

> **状态:已建成并实测通过**(廉价启发式第一刀 + LLM 语义第二刀;闸门两级门控接通;
> 森林静默压、任务才弹,实测一致)。这是 ContextVis 的**中枢**:一个常驻后端检测器,
> 决定 ContextVis 何时该醒。动作原语(fold/drop/闸门)已建成,本件是它们的**脑 + 门控**。
> 相关:[needs.md](needs.md) §E、[compaction-gate.md](compaction-gate.md)、[fold.md](fold.md)、[built.md](built.md)。

---

## 一句话

ContextVis 不该常驻打扰。它应当**在"位置式压缩将要背叛你的任务"时才启动**——
平时像普通 Hermes,有主线时才介入治理。这个判断由一个常驻检测器给出。

---

## 定位:两种 session 形态,只主攻其一

| 形态 | 特征 | 谁来管 |
|---|---|---|
| **① 森林** | 无明显 task 导向,turns 相互独立、像一片散树 | **Hermes 自带**压缩 + 记忆自进化已够;ContextVis **休眠** |
| **② 主线** | 有长期目标(科研探索 / 项目代码修改),存在主线任务 | **ContextVis 主战场** |

> 这两态**不是静止的**,会流转:随意问答 → 确认方向 → 深入(①→②);主线完成 →
> 开新任务 / 漫谈(②→①)。检测器必须**持续跟踪**当前态。

---

## 核心命题:ContextVis 是"位置≠语义"时的纠偏器

为什么 ① 不需要、② 才需要,有统一原理:

- **森林**:turns 独立 → 无长程依赖 → **最近的 context 就是相关的 context** →
  位置式压缩(留近压远)**本身就语义正确**。位置 = 语义,**无偏差**,介入纯添乱。
- **主线**:存在长程主线 → 早期目标/约束**仍承重** → 位置式会当旧的压掉 →
  **位置偏离语义** → 出现偏差 → ContextVis 来补这个偏差。

> **ContextVis = 一个"位置式压缩将要背叛你的任务"时才启动的纠偏器。**
> 触发条件因此可测:**存在会被位置式压缩搞错的长程相关性**(信号:turns 间回指密度、
> 共享产物、早期目标仍被后续引用)。

---

## 原理与判定依据(一图读懂)

整条链:**检测器判森林/任务 → 两级门控决定闸门弹不弹 → 弹则用户把关、不弹则静默自动压。**

### 两级门控(判出 task ≠ 一定弹)

[`compaction_gate._should_gate_for_regime`](../agent/compaction_gate.py):

1. **A 级(regime)**:有没有正在进行的主线任务?没有 → 森林 → 静默压。
2. **B 级(collision)**:这次压缩**要折叠的消息区间** `[head_end, tail_start)` 是否**触及主线 turn**?
   只压到森林噪音 → 也静默;真碰到主线 → 才弹。
3. **A ∧ B 才弹窗。**

### 检测的依据 —— 两个引擎([`RegimeDetector.assess`](../agent/contextvis/regime.py))

我们先做廉价启发式,撞墙后换 LLM;LLM 为权威,启发式作回退/对照。

**引擎一 · 廉价启发式(第一刀)—— 依据"跨 turn 复现的具体产物"**
- 直觉:真任务反复碰同样的具体东西(同几个文件/代码符号);森林不会。
- salient = 每条消息抽**文件路径段 + 代码标识符 + 反引号词**,再减去**工具名 / 基础设施段 / 压缩样板**(样板消息整条隐形)。
- 纽带 = 出现在 **≥2 个不同 turn** 的 salient;纽带覆盖 ≥2 turn、占 token 比 ≥50%、跨度 ≥3 turn → task。
- **天花板**:`web_search`/`browser_snapshot` 等**共享工具/搜索词**把无关话题硬串成纽带——**分不清"都用了网页搜索"和"在做同一件事"**。

**引擎二 · LLM 语义(第二刀,当前权威)—— 依据"目标/主题是否一致"**
- 不喂全文,喂 **turn 骨架**([`_build_skeleton`](../agent/contextvis/regime.py)):每轮 = `用户意图(180字) + 用了哪些工具 + 碰了哪些文件`(1M 下"为省 token 通读 1M"反讽的缓解)。
- prompt 命门:问"**当前有没有正在进行的多轮任务?哪些 turn 属于它?**"(不是"整段是不是一个任务"——否则一个无关早先 turn 会把整体拖成森林),并钉死"**用同样的工具 ≠ 同一个任务,按 GOAL/SUBJECT 判**"。
- 回 `{regime, mainline_turns, focus, reason}`;`mainline_turns` 映射回消息下标 → 喂 B 级 collision。

| 引擎 | 判定依据 | 抓得住 / 抓不住 |
|---|---|---|
| 启发式 | 跨 turn **复现的具体 token** | ✅同文件/同符号的代码任务 · ❌被共享工具骗 |
| LLM | 最近几轮**目标/主题是否一致** | ✅"都用网页搜索但话题无关=森林"、"读代码→钻 treemap=同一任务" |

### 安全与回退

- 只在**交互会话 + 即将弹闸门**时才调 LLM;无人值守更早返回、根本不调(不花钱不挂)。
- **LLM 失败/超时/无 provider → 回退启发式 → 再不行保守判森林**;绝不挡压缩。
- 偏保守:漏弹 = 退回今天的静默自动压(无损),滥弹才烦——故拿不准倾向不扰。

### 调试入口

`await __cvRegime()` / RPC `context.regime`:顶层 `regime`/`engine`/`reason` = **LLM 权威裁决 + 理由**;
`linking_tokens`/`turns` = **启发式拆解**(对照,看它被什么 token 骗)。

---

## 架构:常驻 agent 侧检测器,廉价嗅探 → 按需深析

检测器是**持久后端机制**,住在 agent 对话循环旁(像压缩器一样常驻、跨轮维护滚动状态),
**不在前端、不在网关**。两段式以摊平成本——尤其 1M 窗口下"为省 token 而通读 1M"是反讽:

1. **常驻嗅探(每轮、极廉价)**:用启发式/小信号判"像不像任务"——回指密度、是否共享产物、
   用户是否仍在追同一目标。**森林回指稀疏 → 廉价即可判定 → 保持休眠,绝不深读。**
2. **按需深析(仅当嗅探越阈)**:升级到 aux 模型,产出 ② 态所需:**护住的主线焦点** +
   **死重清单**(散落 context 里的已完成支线 / 放弃的尝试 / 过期工具结果,带可回收 token +
   与当前焦点的无关度,按收益排序)。

> 这样**森林几乎零成本**,成本只花在真有主线、真有价值的 ② 上。增量维护的滚动结构是
> **可修正**的(一段岔路等用户回主线时被追认为支线),始终是最佳猜测,终由用户在闸门确认。

---

## 两级闸门:即使在 ②,也别逢压必扰

压缩闸门(G)的触发从"到阈值就弹"升级为**两级**:

- **A 级(regime)**:有没有值得护的主线?**没有 → 全程像普通 Hermes,静默自动压。**
- **B 级(collision)**:**这一次**压缩会不会动到该护的段(或踩中 case 2:你在支线、主线要被摘要)?
  **不会 → 即使在 ② 也静默压。**
- **A ∧ B 才打断**,请用户编辑 context 再压。

> 避免"任务模式下天天弹窗"的体验灾难。闸门第一阶段(已建成)是"逢阈值弹";这是它该走向的下一形态。

---

## 转移即动作:两个流转沿就是两个出手点

- **①→②(主线刚结晶)**:**武装闸门,开始保护。** 有延迟(主线要几轮才显形)——但主线 context
  还没厚、压缩还没来之前,迟启动零损失。
- **②→①(主线验收完成)**:它的整段 context **瞬间变最大一坨死重** → **主动清理**最该出手:
  "你完成了 X,整段折叠/归档?" 把"主动清理"精确挂到"任务完成"事件上。

---

## 焦点压缩:当前任务 ≈ `focus_topic`(复用,不造新机)—— ✅ 已建成(R 后续①,仅闸门路)

Hermes 的 `_generate_summary(turns, focus_topic)` 语义就是"保住与该主题相关的、狠压其余"。
所以 ContextVis 在压缩时刻的活,不是发明机制,而是**把 focus 摆正**:

> **"当前任务" = `focus_topic`。**

把"当前在做什么"浮出来让用户确认 → **既有压缩机器自己**就保相关、压无关。位置式默认只是 focus
摆错时的退路。检测器产出的焦点,直接喂给这个既有参数。

---

## 死重清单:一份脑,喂两个时机

深析产出的"死重清单",同时服务两条路:

- **G 闸门(被迫压缩时)**:"这些该折,确认?"
- **方向 A 主动清理(随时、非对话态)**:"这是你做完的支线,折掉?"——**大窗口下压缩很少触发,
  这条主动路可能才是主场。**

一个被检测出的"已完成支线" = 用户提问轮 + 相关工具调用 + 结果 = **跨类型、非连续的一组 chunk** =
正好是已建成的 `context.fold` **单隐式组**能吃的东西。检测只需**预填 `fateMap`**,落地复用 fold。
**检测层只产"选什么",fold/drop 一行不改。**

---

## 与 Hermes "记忆自进化" 的边界(别重造轮子)

- **记忆(MEMORY.md)= 跨 session 的稳定事实**(项目约定、验收标准)——② 里主线的持久事实
  该流进记忆,靠记忆结构化扛过压缩。**这块归 Hermes。**
- **ContextVis = 护住 session 内的在飞工作态**(当前子目标、半成推理、刚读的关键文件)——
  它还不够格进记忆,却必须在本 session 压缩里活下来。**这块归 ContextVis。**

两者互补、不重叠。开发时勿与记忆系统打架。

---

## 默认折叠、不删除(吸收"关联性不可知")

已完成单元与未来任务相不相关,在当下**不可知**。故默认:

> **已完成单元 = 折叠候选(有损摘要,留一道 trace),不是删除候选。**

折叠保住要点——万一下个任务用得上,摘要还在;**全删只留给用户明确判定的纯噪音**。用"保留压缩痕迹"
吸收不确定性,而非赌它无关然后销毁。

---

## 分期

- ✅ **第一刀:廉价嗅探 + 两级门控** — 已建成。跨 turn 复现产物的启发式 + A∧B 门控,
  先把门控骨架跑通。撞墙(共享工具/基础设施假纽带)后转 LLM。
- ✅ **第二刀:LLM 语义判定** — 已建成并实测。turn 骨架喂 aux 模型,按目标/主题判 +
  产出 mainline_turns/focus;失败回退启发式。实测森林静默、任务才弹。
- ✅ **后续①:焦点压缩(focus → focus_topic)** — 已建成并实测。闸门触发时检测出的 `focus`
  接进既有 `_generate_summary` 的 `focus_topic`(仅闸门压缩路;`compaction_gate` 回传 + `conversation_loop`
  喂参 + 闸门条只读显示「将按焦点压缩」)。实测 `agent.log` 的 `compression started … focus=` 从 `None`
  变成检测出的主线串。见 [built.md](built.md)「R 后续①」。
- ⬜ **后续(未做)**:深析**死重清单**(喂闸门 + 方向 A 主动清理)、②→① 完成检测触发清理、
  滚动增量(压缩前快照任务结构,根治"跑在压缩后历史")、产品门槛(纯浏览式读代码是否算任务——
  当前"多轮连贯本地工作即任务",可抬高到需编辑/明确目标)。**焦点压缩仅接了闸门路**,非闸门的
  自动压缩三处仍焦点盲(喂 focus 需无条件 assess,留后续);闸门内**编辑** focus 需扩 shared 审批 payload。

---

## 第一刀实现计划(廉价嗅探 + 两级门控)

> 零 LLM、确定性。只证明"自适应门控"命题:森林闭嘴、任务出声。深析死重留第二刀。

**新件 1 · `agent/contextvis/regime.py`(检测器)**
- `get_regime_detector(agent)` 懒创建并缓存到 `agent._contextvis_regime`(呼应 `context_compressor` 常驻姿态)。
- `assess(messages) -> RegimeAssessment{regime, on_thread_indices, reason}`,第一刀**无状态**(每次重算),滚动状态留第二刀、接口不变。
- **信号(由强到弱,确定性)**:① 共享产物连续性——抽文件路径 + 代码标识符(tool_call args 的 path 最干净;正文 `` `backtick` ``/camelCase/snake_case/含扩展名路径,正则取),**跨 turn 复现**的产物 = 主线纽带;② salient ascii token 跨 turn 重叠(中文不强切分,避免脆弱分词)。
- **判定(turn 粒度)**:先按 user 发言切 turns;`linking token` = 出现在 **≥2 个不同 turn** 的 salient → `on_turns` = salient 与 linking 相交的 turn → `regime="task"` 当 `len(on_turns)≥MIN_TURNS ∧ on_turns token 占比≥THR ∧ turn 跨度≥MIN_SPAN`,否则 `forest`。`on_thread_indices` 由 on_turns 展开成消息下标供 B 级 collision。
- **纽带必须跨 turn,不是跨消息**:否则一个工具密集 turn 内部反复引用同一文件会自我结网、冒充主线(实测踩过此坑)。任务本质 = 跨 turn 延续。
- 阈值 `MIN_TURNS=2 / THR=0.5 / MIN_SPAN=3`(turn),env `HERMES_CONTEXTVIS_REGIME_MIN_TURNS / _RATIO / _SPAN` 可调,默认偏保守(拿不准 → forest → 不扰)。

**新件 2 · 两级门控嵌进 `request_compaction_decision`**(确认交互 + notify 之后、构建预览之前):
```
if not _should_gate_for_regime(agent, messages, plan): return None   # 静默自动压
```
`_should_gate_for_regime`:env `HERMES_CONTEXTVIS_REGIME=0` → 恒 True(逃生阀,回退一级门控);否则
`a = assess(messages)`;**A 级** `a.regime!="task" → False`;**B 级** `collision = 任一 on_thread 落在 plan 的折叠区 [head_end,tail_start) → 返回 collision`。两级共用一份廉价信号。

**门控开关**:`HERMES_CONTEXTVIS_GATE`(已有 opt-in,不变)+ `HERMES_CONTEXTVIS_REGIME`(新,默认 1;0=回退逢阈值弹)。**本刀不改默认**——两级门控是未来 GATE 敢默认开的前提,但仍 opt-in。

**前端(最小)**:闸门 payload 加 `regime` + `collision_reason`;闸门条加一行"检测到主线任务 · 本次压缩将触及主线"。森林态不弹、无事件,无需改。

**测试**:detector(森林→forest / 任务共享路径→task 且 on_thread 覆盖 / salient 抽取)+ 两级门控(森林→False / 任务但折叠区全 off-thread→False / 含 on-thread→True / REGIME=0→恒 True)+ 保守性(空输入→forest)。

**E2E**(GATE=1):① 互不相关问答顶阈值 → 不弹、静默压;② 项目里反复改同几文件顶阈值 → 弹、标"检测到主线";REGIME=0 → 回到逢阈值必弹。

**复用**:fold/drop/闸门/`plan_compaction` 全复用;新增仅一个检测器模块 + 一段两级判断 + 一个 env 逃生阀 + 一行前端小字。

---

## 第二刀实现(方向 B:LLM 语义判定)—— 已建成

> 廉价启发式连撞天花板:**"共享 token" 把"共享工具/基础设施"误当"共享任务"**——压缩残骸、
> 网页搜索词(duckduckgo/html/blog)、记忆/任务样板(memory/context/state)、工具名,
> 每个都让无关话题假性结网。打地鼠到头,改用 aux 模型按**语义**判。

**核心**:`RegimeDetector.assess(messages, agent)` 现在**优先走 LLM**,失败回退启发式:
- **只喂 turn 骨架,不喂全文**(`_build_skeleton`:每轮 = 用户意图 180 字 + 用了哪些工具 / 碰了哪些文件)——1M 下"为省 token 通读 1M"反讽的关键缓解。
- **复用压缩的 aux runtime**:`agent.auxiliary_client.call_llm(task="compression", main_runtime=…, model=summary_model)`——同一个便宜模型 / 超时配置,**不造新调用栈**。
- **prompt 命门**(`_REGIME_PROMPT`)明确钉死启发式踩的坑:**"用同样的工具 ≠ 同一个任务;两个都用网页搜索的无关问题仍是 forest;按 GOAL/SUBJECT 判,别按工具判。"**
- 回 JSON `{regime, mainline_turns, focus, reason}`;`mainline_turns` 经 `_segment_turns`(与 heuristic 同一套 turn 编号)映射回 message 下标 → 喂 B 级 collision。
- **缓存**:同骨架不重复调 aux(`_llm_cache`)。**失败/超时/无 provider → 回退启发式**,绝不挡压缩。

**门控**:`HERMES_CONTEXTVIS_REGIME_LLM`(默认 1;0 = 只用启发式)。仅交互会话 + 即将弹闸门时才调 aux(无人值守路径在更早就返回 None,不花钱)。

**调试**:`context.regime` / `await __cvRegime()` 现在顶层 `regime` 是**权威判定**(LLM 优先),
带 `engine`(llm/heuristic)+ `reason`(含 focus + 理由),另附启发式 `linking_tokens`/`turns` 做对照。

**复用**:闸门两级门控、collision、fold/drop、前端小字全不变——只把 `assess` 的脑从启发式换成 LLM。

**风险**:prompt 质量、aux 成本(每次弹闸门一调,已缓存 + 仅交互)、骨架可能丢掉判定所需细节
(第一版只给意图 + 工具/文件名,不给正文)。

---

## 开放问题 / 风险

- **嗅探信号选型**:回指密度 / 共享产物 / 目标延续——哪几个最省且最准?需实测。
- **滚动结构的失效与修正**:历史被 fold/drop/压缩改动后,结构怎么增量更新、何时重析。
- **深析成本**:即便 aux 小模型,深读候选段仍有成本;读骨架(轮边界 + user 意图 + 工具/文件签名)
  而非全文,只深读候选,是关键约束。
- **检测质量的 prompt 命门**:怎么定义"主线 vs 支线""done vs live""焦点"——整条路质量系于此。
- **误判的代价不对称**:漏报(该护没护)= 主线被压,损失大;误报(森林里弹窗)= 烦扰,损失小。
  门控应**偏保守**:拿不准时倾向"不打扰、自动压",而非频繁弹。

---

## 复用边界(已备的轮子)

| 复用 | 用作 |
|---|---|
| `_generate_summary(turns, focus_topic)` | 焦点压缩——检测出的焦点直接喂 `focus_topic` |
| 压缩闸门(`_await_gateway_decision` + `compaction.respond`,已建成) | 两级门控的"打断 + 请用户编辑"载体 |
| `context.fold` / `context.apply` 单隐式组(已建成) | 死重清单确认后的落地——检测只预填 fateMap |
| 滚动检测器常驻位置 | 参照 `ContextCompressor` 挂在 agent 上的常驻姿态 |

**新增的只有**:常驻 regime 检测器(嗅探 + 深析)、两级门控逻辑、焦点/死重清单的产出与预填。
