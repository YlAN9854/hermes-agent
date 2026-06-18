# 路线图 & 待决方向

> 接下来去哪。seam 已埋、未动工的方向 + 优先级建议。
> 每个方向**满足哪条用户需求**见 [needs.md](needs.md);现状基线(要接管的压缩引擎)
> 见 [compression-baseline.md](compression-baseline.md)。

---

## 路线图(已埋 seam)

### 交互式压缩(旗舰,下一步)
让视图从"观察"升级到"治理":agent 出错 / 窗口将满时,用户手动控制上下文。
**这不是另造引擎,而是可视化并接管 Hermes 既有压缩**(基线见
[compression-baseline.md](compression-baseline.md))。

分阶段(由易到难):
1. ✅ **选中 + fate 标记(纯前端,零风险)** — 已建成,见 [built.md](built.md)。
   检视器按钮标 `keep/fold/drop`,treemap 叠加渲染。
2. ✅ **预览(纯函数,无副作用)** — 已建成(`plan.ts` `projectFates`)。
   占用条幽灵刻度 + 预览行"预计释放 / 占用投影"。
3. ✅ **应用(真正动上下文)** — **v1(drop)+ v2(fold)均已建成**,见 [built.md](built.md)
   与 [fold.md](fold.md)。`context.apply` 删消息 / `context.fold` 折成摘要(复用
   `_generate_summary` + `focus_topic` 重心 prompt + 非连续 splice);共用
   `_sanitize_tool_pairs` 缝合 + 一步撤销;实测 TUI/treemap 同步回落、token 真减少。
   **剩** keep-as-pin / 系统建议命运 / sub-agent 执行。

四项交互能力(用户预想):①系统建议 drop/keep/merge ②用户编辑(丢弃/固定/合并 +
合并重心)③预览影响 ④sub-agent 应用。

**命令通道 —— 原判"硬骨头"已被推翻,实测可用**(证据链见
[phase3-channel.md](archive/phase3-channel.md)):dashboard 部署里 PTY 子进程走 **attach 模式**
(`HERMES_TUI_GATEWAY_URL`),真实 agent 就活在 **web_server 进程的 `_sessions`**,与
`/api/ws` dispatch 同进程。前端新开 `/api/ws` 即可**按 sid** 调 `session.*`;sid 从
`_emit` 每帧带的 `session_id` 免费拿到。浏览器只读探针已坐实跨连接按 sid 读到真实会话
(usage 非零、与 treemap 一致)。**剩下的不是通道有无,而是**:扩 `session.compress` /
新增 `context.apply` 吃 fate 选择 + 按 `sourceRefs` 映射 message 索引 + 前端 apply 路 +
并发闸(`session["running"]` 时拒)。

**地基已备**:`sourceRefs`(provenance,编辑能落到真实 message)、`fate` 字段、
预留 `context.plan`(纯预览投影)/`context.apply`(落地)RPC 命名空间、建议策略注册表。

### 任务态识别(ContextVis 的自适应总开关)
ContextVis 的**脑**:压缩闸门从"逢阈值就弹"升级为**自适应**——只在"位置式压缩将要背叛
你的任务"时才打断。设计、判定依据、原理见 [regime.md](regime.md)。
1. ✅ **第一刀:廉价嗅探 + 两级门控** — **已建成**。跨 turn 复现产物的启发式 + A∧B 门控。
2. ✅ **第二刀:LLM 语义判定** — **已建成并实测**。turn 骨架喂 aux 模型按目标/主题判,
   产出 mainline_turns/focus,失败回退启发式。森林静默、任务才弹。
3. ✅ **后续①:焦点压缩(focus → `focus_topic`)** — **已建成并实测**。闸门检测出的主线 focus 接进
   既有 `_generate_summary`(仅闸门压缩路);`agent.log` `compression started … focus=` 从 `None` → 主线串。见 [built.md](built.md)。
4. ✅ **后续②:死重清单** — **首刀(主动「建议清理」)✅ + 喂闸门 ✅ 已建成实测**:逐轮 `done` → 共用 `chunk_topic_map`
   挑已完成支线(`done ∧ !mainline`)→ ① turn 带按钮预填 fold(主动);② 闸门弹出时自动预填进 `system_fate`(被迫压缩前,
   含首尾、带来由)。两条都复用 `apply_gate_plan` 落地。**死重建议用 fold 不 drop**(决策见 [built.md](built.md))。
5. ✅ **后续⑤:drop 残值信号 — 已建成实测**。`regime.residual_drop_map` 三信号(被取代旧 read〔结构〕/ 失败 tool〔内容启发式〕/ 窄闲聊
   〔`!mainline∧done∧无产物∧短`〕)→ 喂闸门预填 **drop**(覆盖死重 fold/位置式,优先级 drop>fold>keep);轮次版 chunk 级 drop 角标 `✕N` + drop 优先沟 + tooltip 来由;
   `apply_plan` 在系统有建议时即可见。env `HERMES_CONTEXTVIS_RESIDUAL`。**残值 drop vs 死重 fold 的精度分界**见 [built.md](built.md)。
6. ✅ **主题着色升级:持久 + 压缩后不退 + 按线程定色 — 已建成实测**。用户需求(2026-06-16/18)。
   三个痛点(纯前端、零后端/Hermes,全在 [ContextVisPanel.tsx](../web/src/components/ContextVisPanel.tsx)):
   - **① 同主题跨多次着色保持同色**:`resolveCellColors` 取代旧 `buildTopicColorMap`(旧版按 topic 串**排序下标**分色 + 每 render 从零重建无记忆 → 一加键就整排重洗)。
     色按**归一化字符串键**存 **localStorage `cv-topics:${sid}`**(浮层折叠会重挂载 panel → 内存 ref 会丢)、**只增不洗**。
   - **② 压缩后不回退中性**(踩坑修正):根因 = `colorsFresh` 钉死精确 hv 相等,而压缩后 hv **二次跳动**("按 compressionCount 重取"只抓第一拍)。改为 **(a) 显示放宽(不再要求 colorsFresh,着色一旦点亮就持续)+ (b) 结构变更才重取**(仅"此前着色的某 chunkId 在当前 chunks 消失"=压缩/删/折才取,纯追加零成本;**顺带覆盖手动 drop/fold 与 apply_plan**)。粘滞 `setColorOn(true)` 保留。
   - **③ 按线程定色(方案 A)**:色键 = `(mainline && focus) ? focus : topic`——**主线收 `focus` 一色、支线各自 topic 一色**;逐轮 topic 仅作 tooltip 标签。键变少→顺带解撞色。
   **决策痕迹**:**① 色键用 `focus` 不用 `session_title`**——title agent([title_generator.py](../agent/title_generator.py),Hermes 自带、= opencode 的 session 主题总结)**首轮一次定**、跟不上 session 内主题漂移;`focus` 反映当下主线。**② 两拍着色**:闸门期(应用前)按**压缩前**着色(压缩后 context 此刻不存在、模拟有副作用;新 turn 必活过压缩,如实标当下主线),落地后由结构变更重取按**压缩后**补上;焦点漂移是白盒该有的忠实、非 bug。
   - ✗ **否决:启发式连通分量聚类着色**(用户经验上效果差)。
   - ✗ **否决:LLM 增量着色 / 按 turn 内容 hash 缓存 / 只判新轮**——用户**不要求**每轮检测,无需此基建(原"与滚动增量同机器"的动机消失)。
   - **v1 局限(已接受)**:只收**当下**主线为一色;已完成的旧主任务退为非主线后仍按逐轮 topic(可能多色)。回溯每条历史线程各收一色需"线程 id",留后。
   - **残留**:focus/topic **显著**改名仍可能跳色(漂移时主线色会换)→ 留白(实测确碍眼再加保守模糊匹配)。
7. ⬜ **后续(未做)**:死重②剩项(②→①完成自动触发 / 回收量排序)、自动**护主线中段轮**、产品门槛(纯浏览算不算任务)、非闸门路喂 focus、闸门内编辑 focus、
   残值留后项(read 行区间精细取代 / 失败 tool 结构化 is_error / 主动路喂残值 / 森林态喂残值)。
   - 🅿 **滚动增量已降级(非活跃·留后根治)**:其"增量评估"那条原是为持久着色服务,**持久着色已改用前端注册表解决**(零后端)→ 动机被抽走;
     仅剩窄的"**压缩前快照根治检测器跑在压缩后历史**"——不紧迫(样板隐形已缓解、误判代价不对称)且**会动 Hermes**(撞少改 Hermes 偏好)。

### 压缩闸门(把静默 auto-compress 改成用户确认)
ContextVis 最贴使命的一块,**交互式压缩的对偶**:用户主动治理(上面 A 路)之外,
**系统想动手(到阈值要压)时也必须经用户**。证据链与设计见 [compaction-gate.md](compaction-gate.md)。
1. ✅ **第一阶段(纯预览 + 确认)** — **已建成**,见 [built.md](built.md)。拦
   [conversation_loop.py:3812](../agent/conversation_loop.py#L3812) → treemap 画系统计划 +
   占用投影 → 继续 / 推迟(300s 超时自动继续)。复用审批基建,opt-in
   `HERMES_CONTEXTVIS_GATE`。实测次数/占用与 TUI 一致。
2. ◑ **第二阶段(闸门内编辑)· drop ✅ + fold/keep ✅ 已建成实测**:闸门内标 drop/fold/keep + 四选择
   (直接压缩 / 应用计划 / 仅删除 / 推迟)。**两暗礁被架构消解**(非打补丁):编辑随应答带回、由循环线程作用于
   **本地 `messages`**;落地统一进 `apply_gate_plan`(方案 A:编辑后的有效 fateMap = 权威计划,直接 apply、
   跳过位置式 `_compress_context`;复用手动 `context.fold` 的 `_generate_summary`+`splice_fold_summary`)。keystone =
   应答带回编辑(`approval.py` 的 `result_extra`)。命运沟可读性 + 在途 spinner 已打磨。见 [built.md](built.md) / [compaction-gate.md](compaction-gate.md)。
   **剩**:keep-as-pin(持久免压区)、纠正 focus。
3. ◑ **第三阶段 / 横切:死重清单喂闸门 ✅ 已建成实测**:闸门预填 = 位置式 ∪ 死重语义(done∧!mainline 自动预标 fold,
   `system_fate[cid]="fold"` 覆盖位置式 keep → **够首尾**)。抽 `chunk_topic_map` 与「建议清理」共用判据、复用门控那次 assessment(零新 LLM)、
   复用 `apply_gate_plan` 落地。点 1(够首尾)+ 点 3(banner/band 标来由)已兑现。**死重建议 fold 不 drop**(决策见 [built.md](built.md))。
4. ✅ **drop 残值信号(第三阶段横切续)— 已建成实测**:`residual_drop_map` 三信号(被取代旧 read / 失败 tool / 窄闲聊)→ 喂闸门预填 **drop**
   (覆盖死重 fold,优先级 drop>fold>keep);轮次版 chunk 级 drop 角标 `✕N` + drop 优先沟 + tooltip 来由;`apply_plan` 系统有建议即可见。见 [built.md](built.md)。
   **剩**:自动**护主线中段轮**、keep-as-pin、纠正 focus。

### 主视图主轴翻转:turn 优先 + 逐轮主题(设计定稿,见 [turn-band.md](turn-band.md))
把主视图从"类型优先"(5 类型带)翻成 **"turn 优先"**:纵向时间序、与 TUI 同向、逐轮主题着色。
**吸收原"语义分块(E3)/语义排列(E4)"实验**——不造新 ChunkStrategy,主题取自 regime 逐轮 topic;
旧类型带留作 toggle。同时兑现 CLAUDE.md 第 5 条(时间轴),并在大窗口下成为 ContextVis **主操作台**。
分四刀(带先行→着色→联动导航→主动梳理),详见 [turn-band.md](turn-band.md)。

---

## 待决方向

观察(占用 / 构成 / 原文)已闭环。下一步候选:

- **A. 交互式压缩(旗舰)**:①标记 + ②预览 + ③应用 **v1(drop)+ v2(fold)均已建成**——
  观察→治理→落地闭环打通(`context.apply` 删 / `context.fold` 折,实测 TUI/treemap 同步回落)。
  fold 复用 `_generate_summary` + 重心 prompt + 非连续 splice,失败整笔中止。**剩**
  keep-as-pin、系统建议命运、sub-agent 执行。
- **R. 任务态识别(自适应总开关)**:**第一刀(启发式)+ 第二刀(LLM 语义)均已建成并实测**——
  闸门从"逢阈值弹"升级为 **regime ∧ collision 才弹**(森林闭嘴、任务出声)。检测器常驻 agent,
  LLM 按目标/主题判 + 启发式回退。见 [regime.md](regime.md)、[needs.md](needs.md) §E E0。
  **后续①焦点压缩 ✅ + 后续②死重清单(「建议清理」✅ + 喂闸门 ✅)+ drop 残值信号 ✅ 均已建成实测**。
  **剩(活跃)**:②→①完成自动触发 / 自动护主线中段 / 产品门槛 / 非闸门路喂 focus / 闸门内编辑 focus。
  **滚动增量已降级**(非活跃·留后根治:增量评估动机随持久着色改前端注册表而失;仅剩压缩前快照硬限,不紧迫且会动 Hermes)。
- **G. 压缩闸门**:第一阶段(预览 + 确认)**已建成**;已与 R 合流——闸门现"**regime ∧ collision
  才弹**"。**第二阶段 drop ✅ + fold/keep ✅ 编辑 + 死重清单喂闸门 ✅ 均已建成**(两暗礁经"编辑随应答带回、作用本地 messages"消解;
  keystone=应答带回编辑 payload;落地统一 `apply_gate_plan`,方案 A:编辑后计划即权威、跳过位置式压缩;
  死重把 detector 已完成支线预填进 system_fate、含首尾、共用 `chunk_topic_map`)。**drop 残值信号 ✅ 已建成**
  (`residual_drop_map` 三信号预填 drop、轮次版 chunk 级角标、`apply_plan` 系统建议即可见)。
  **剩**:keep-as-pin、纠正压缩焦点、自动护主线中段(均复用 extra keystone / apply_gate_plan)。
- **M. 压缩块诚实显示(✅ 已建成,取代废弃的"结构突变账本")**:压缩/fold 产物**如实标注、摆正位置、
  不冒充对话轮**,但**不重建被销毁的拓扑**——分块层识别对齐 `regime._is_boilerplate` 全集 → 标 `folded`
  → band 画「压缩 context」块。**原"结构突变账本"(突变前快照 + 折叠出处 + 两咽喉一本账)已判过度设计、
  废弃**(不变量归突变层、折叠后已是单一可操作单元),决策痕迹见 [mutation-ledger.md](archive/mutation-ledger.md)、
  设计见 [turn-band.md](turn-band.md) §4。
- **T. turn 带(主视图主轴翻转)**:turn 优先 + 纵向时间序 + 逐轮主题着色,见
  [turn-band.md](turn-band.md) §9。**第一刀(时间序 + 压缩块诚实显示)✅、第二刀(逐轮主题着色 +
  `context.regime_colors` + 闸门自动着色)✅、第三刀(inspector 本轮构成 + 点轮跳 TUI)✅、
  第四刀(整轮 fold/drop 预填 fateMap 复用落地 + 闸门折叠碰撞高亮)✅ 全部建成并实测**(视口高亮框延后)。
  四刀闭环:band 概览 + inspector 类型细节 = 大窗口下的语义 minimap / **主操作台**。
  **取代原 E4**(语义排列)、**吸收 E3**(语义化 chunk):同 topic
  的轮天然聚拢,不造新分块器;时间序保底(踩 E4 红线安全侧)。大窗口下闸门罕触发→**turn 带是
  日常主操作台**。分四刀:带先行(无 LLM)→ 逐轮主题着色 → 联动导航/minimap → 主动梳理(预填
  fateMap 复用 fold)。
- **C2. 检视器类型化渲染**:assistant 文本走 Markdown、代码/JSON 语法高亮、
  tool_result 结构化(退出码/匹配数高亮)。在方向 C 的纯原文之上做体验优化。
- **D. 打磨与收尾**:移动端 sheet 触发按钮文案仍是 i18n 的 "model/tools"(需多语言清理);
  treemap 视觉(配色/字号/带顺序)、浮层交互(拖动/缩放)、截断上限可配;
  小块标签体感(降阈值 / 选中强制显标签 / band 级兜底标签)。

> 建议优先级:**R 后续**(焦点压缩 ✅ + 死重清单(主动清理 ✅ + 喂闸门 ✅)+ 闸门内 drop/fold/keep 编辑 ✅ + 主题着色升级 ✅ + drop 残值信号 ✅ →
> 下一步**自动护主线中段 / ②→①完成自动触发 / keep-as-pin**,在已建成的自适应总开关 + 闸门编辑/建议地基上加智能,见 [regime.md](regime.md))>
> C2(增量)> D/E4(收尾/可选)。
> 观察→治理(drop+fold)→落地、系统压缩前用户把关、**自适应总开关**(森林闭嘴/任务出声)、
> **焦点压缩**(focus 接进压缩)、**死重清单**(主动清理 + **喂闸门**:被迫压缩前自动建议折已完成支线、含首尾、带来由)、
> **闸门内 drop/fold/keep 编辑**(被迫压缩前改写折叠计划,方案 A 直接落地)、**主题着色升级**(持久 + 压缩后不退 + 按线程定色)、
> **drop 残值信号**(被取代旧读/失败工具/窄闲聊精准预填 drop、轮次版 chunk 级角标)均已闭环;
> 下一步候选:自动护主线中段、keep-as-pin、闸门内纠正 focus、②→①完成自动触发。
> (**滚动增量已降级**:非活跃·留后根治——增量评估动机随持久着色改前端注册表而失,仅剩压缩前快照硬限,不紧迫且会动 Hermes。)
