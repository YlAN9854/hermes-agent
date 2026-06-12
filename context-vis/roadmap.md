# 路线图 & 待决方向

> 接下来去哪。seam 已埋、未动工的方向 + 优先级建议。
> 现状基线(要接管的压缩引擎)见 [compression-baseline.md](compression-baseline.md)。

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
3. ◑ **应用(真正动上下文)** — **v1(drop)已建成**,见 [built.md](built.md)。
   `context.apply` 删消息 + 复用 `_sanitize_tool_pairs` 缝合;一步撤销;实测 TUI/treemap
   同步回落、token 真减少。**剩 v2 = fold**(复用 `_generate_summary` 把 fold 块摘要化)、
   以及 keep-as-pin / sub-agent 执行。

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

### 语义分块(实验)
把 history 的"按轮"换成**主题聚类**(主线/支线)、tool_schema 换成**相似工具合并**。
**只改 ChunkStrategy**,契约/渲染不变。效果待实验,架构已为它留好口。

---

## 待决方向

观察(占用 / 构成 / 原文)已闭环。下一步候选:

- **A. 交互式压缩(旗舰)**:①标记 + ②预览 + ③应用 **v1(drop)均已建成**——观察→治理→
  落地闭环打通(`context.apply`,实测 TUI/treemap 同步回落)。**剩 A-v2 = fold**:复用
  `context_compressor._generate_summary` 把 fold 块摘要化(LLM 路,需失败处理 + 多段摘要置放);
  再往后 keep-as-pin、系统建议命运、sub-agent 执行。
- **B. 语义分块实验**:把 history「按轮」换主题聚类、tool_schema 换相似工具合并——
  只改 ChunkStrategy,契约/渲染不变。效果待验。
- **C2. 检视器类型化渲染**:assistant 文本走 Markdown、代码/JSON 语法高亮、
  tool_result 结构化(退出码/匹配数高亮)。在方向 C 的纯原文之上做体验优化。
- **D. 打磨与收尾**:移动端 sheet 触发按钮文案仍是 i18n 的 "model/tools"(需多语言清理);
  treemap 视觉(配色/字号/带顺序)、浮层交互(拖动/缩放)、截断上限可配;
  小块标签体感(降阈值 / 选中强制显标签 / band 级兜底标签)。

> 建议优先级:**A-v2 fold**(把治理能力补全,复用现成摘要轮子)> B/C2(增量) > D(收尾)。
> A 的 ①②③(drop)已闭环出手感;下一步是 fold —— 风险在 LLM 摘要的失败处理与多段置放。
