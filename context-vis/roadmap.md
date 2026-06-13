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

### 语义分块(实验)
把 history 的"按轮"换成**主题聚类**(主线/支线)、tool_schema 换成**相似工具合并**。
**只改 ChunkStrategy**,契约/渲染不变。效果待实验,架构已为它留好口。

---

## 待决方向

观察(占用 / 构成 / 原文)已闭环。下一步候选:

- **A. 交互式压缩(旗舰)**:①标记 + ②预览 + ③应用 **v1(drop)+ v2(fold)均已建成**——
  观察→治理→落地闭环打通(`context.apply` 删 / `context.fold` 折,实测 TUI/treemap 同步回落)。
  fold 复用 `_generate_summary` + 重心 prompt + 非连续 splice,失败整笔中止。**剩**
  keep-as-pin、系统建议命运、sub-agent 执行。
- **G. 压缩闸门**:第一阶段(预览 + 确认)**已建成**。**剩第二阶段 = 闸门内编辑**(见上路线图),
  与 A-v2 互补——A 是用户主动治理,G 是系统触发时用户把关。
- **B. 语义分块实验**:把 history「按轮」换主题聚类(主线/支线)、tool_schema 换相似工具
  合并——只改 ChunkStrategy,契约/渲染不变。效果待验。服务 [needs.md](needs.md) §E
  「主线/支线同 session」的 E3(识别支线)。
- **E4. treemap 语义排列模式**(本文新提,源自 A-v2 讨论):新增「时间序 ⇄ 语义聚类」
  **模式切换**,让同语义块聚拢、好框选(服务 needs §E 的 E4)。**红线:模式切换而非替换**
  ——按语义重排会丢掉时间读法,与 CLAUDE.md 第 5 条冲突,时间序必须保底。纯渲染/排列层,
  不碰 fold 落地路。
- **C2. 检视器类型化渲染**:assistant 文本走 Markdown、代码/JSON 语法高亮、
  tool_result 结构化(退出码/匹配数高亮)。在方向 C 的纯原文之上做体验优化。
- **D. 打磨与收尾**:移动端 sheet 触发按钮文案仍是 i18n 的 "model/tools"(需多语言清理);
  treemap 视觉(配色/字号/带顺序)、浮层交互(拖动/缩放)、截断上限可配;
  小块标签体感(降阈值 / 选中强制显标签 / band 级兜底标签)。

> 建议优先级:**E3/E4 语义选择**(语义分块 + treemap 语义排列,让"收支线"从逐块手选
> 升级到框选同语义,见 [needs.md](needs.md) §E)或 **G 闸门第二阶段**(闸门内编辑,复用
> 已建成的 fold/drop)> C2(增量) > D(收尾)。
> A 的 ①②③(drop+fold)已闭环出手感;下一步分叉:把 fold 的"选择层"做智能(E3/E4),
> 或把 fold/drop 接进系统触发侧的闸门(G2)。
