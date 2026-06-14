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
[phase3-channel.md](phase3-channel.md)):dashboard 部署里 PTY 子进程走 **attach 模式**
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
3. ⬜ **后续**:focus 喂压缩 `focus_topic`(焦点压缩)、深析**死重清单**(喂闸门 + 方向 A 主动清理)、
   ②→① 完成检测触发清理、滚动增量(压缩前快照,根治"跑在压缩后历史")、产品门槛(纯浏览算不算任务)。

### 压缩闸门(把静默 auto-compress 改成用户确认)
ContextVis 最贴使命的一块,**交互式压缩的对偶**:用户主动治理(上面 A 路)之外,
**系统想动手(到阈值要压)时也必须经用户**。证据链与设计见 [compaction-gate.md](compaction-gate.md)。
1. ✅ **第一阶段(纯预览 + 确认)** — **已建成**,见 [built.md](built.md)。拦
   [conversation_loop.py:3812](../agent/conversation_loop.py#L3812) → treemap 画系统计划 +
   占用投影 → 继续 / 推迟(300s 超时自动继续)。复用审批基建,opt-in
   `HERMES_CONTEXTVIS_GATE`。实测次数/占用与 TUI 一致。
2. ⬜ **第二阶段(闸门内编辑)**:在闸门里开放 A-v1 的 drop 编辑 + "阈值线驱动的三选择"
   (接受系统方案 / 编辑后直接继续 / 编辑后让系统补压)。**先解两暗礁**:① running 闸冲突
   (`context.apply` 在 running 时拒,闸门窗口需放行)② 循环本地 `messages` 与
   `session["history"]` 对账。
3. ⬜ **第三阶段**:A-v2(fold)就绪后编辑更丰富;横切"编辑建议"(系统预 mark 建议 fate)。

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
  **剩**:focus 喂焦点压缩、深析死重清单(喂闸门 + 方向 A 主动清理)、滚动增量、产品门槛。
- **G. 压缩闸门**:第一阶段(预览 + 确认)**已建成**;已与 R 合流——闸门现"**regime ∧ collision
  才弹**"。**剩**:闸门内确认/纠正压缩焦点、闸门内编辑(drop/fold,需先解 running/对账两暗礁)。
- **M. 结构突变账本(修法②,设计定稿)**:让轮次拓扑扛过压缩/折叠/删除,见
  [mutation-ledger.md](mutation-ledger.md)。**钩"结构突变"非"压缩"**(统摄手动 drop/fold + 自动压缩
  三场景),突变前算折叠出处挂回折叠块,band 画"已折叠 第1–5轮〔主题〕→ 摘要"。两咽喉
  (`_commit_history_mutation` / `_compress_context`)一原语一本账。第 0 步先 boilerplate 对齐
  (复用 `regime._is_boilerplate` 全集)。**turn 带二刀主题着色的地基**——不解它,着色也画在压坏历史上。
- **T. turn 带(主视图主轴翻转,设计定稿)**:turn 优先 + 纵向时间序 + 逐轮主题着色,见
  [turn-band.md](turn-band.md)。**取代原 E4**(语义排列)、**吸收 E3**(语义化 chunk):同 topic
  的轮天然聚拢,不造新分块器;时间序保底(踩 E4 红线安全侧)。大窗口下闸门罕触发→**turn 带是
  日常主操作台**。分四刀:带先行(无 LLM)→ 逐轮主题着色 → 联动导航/minimap → 主动梳理(预填
  fateMap 复用 fold)。
- **C2. 检视器类型化渲染**:assistant 文本走 Markdown、代码/JSON 语法高亮、
  tool_result 结构化(退出码/匹配数高亮)。在方向 C 的纯原文之上做体验优化。
- **D. 打磨与收尾**:移动端 sheet 触发按钮文案仍是 i18n 的 "model/tools"(需多语言清理);
  treemap 视觉(配色/字号/带顺序)、浮层交互(拖动/缩放)、截断上限可配;
  小块标签体感(降阈值 / 选中强制显标签 / band 级兜底标签)。

> 建议优先级:**R 后续**(focus 喂焦点压缩 / 深析死重清单 / 滚动增量,在已建成的自适应
> 总开关上加智能,见 [regime.md](regime.md))> C2(增量)> D/E4(收尾/可选)。
> 观察→治理(drop+fold)→落地、系统压缩前用户把关、**自适应总开关**(森林闭嘴/任务出声)均已闭环;
> 下一步是把检测出的 `focus` 接进压缩、把死重清单接进闸门与主动清理。
