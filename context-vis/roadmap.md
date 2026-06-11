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
1. **选中 + fate 标记(纯前端,零风险)**:点 chunk → 标 `drop/keep/fold`,
   treemap 按 fate 着色/描边。
2. **预览(纯函数,无副作用)**:据 fate 算"预计释放 token / 新分布"。
3. **应用(真正动上下文)**:把 fate map 下发,**驱动既有
   trajectory/context_compressor 落地**(`compress(focus_topic=...)` 已支持聚焦压缩),
   可由 sub-agent 执行。

四项交互能力(用户预想):①系统建议 drop/keep/merge ②用户编辑(丢弃/固定/合并 +
合并重心)③预览影响 ④sub-agent 应用。

**未解的硬骨头(阶段 3 前必须解决)**:**"浏览器 → 真实 PTY 会话"的命令通道不存在**——
`/api/events` 是单向 push;sidecar 是另一个 throwaway 会话,够不到 PTY 真实会话
(详见 [dataflow.md](dataflow.md))。候选:PTY 侧网关暴露 method + sid 中转 /
经 sidecar 转发 / 新建命令 WS。

**地基已备**:`sourceRefs`(provenance,编辑能落到真实 message)、`fate` 字段、
预留 `context.plan`(纯预览投影)/`context.apply`(落地)RPC 命名空间、建议策略注册表。

### 语义分块(实验)
把 history 的"按轮"换成**主题聚类**(主线/支线)、tool_schema 换成**相似工具合并**。
**只改 ChunkStrategy**,契约/渲染不变。效果待实验,架构已为它留好口。

---

## 待决方向

观察(占用 / 构成 / 原文)已闭环。下一步候选:

- **A. 交互式压缩(旗舰)**:让视图能"治理"。从纯前端的 ①选中+fate 标记 +
  ②预览释放量 起步(零风险),并行调研 ③应用 的"浏览器→真实 PTY 会话"命令通道
  (见上文硬骨头)。地基(`fate`/`sourceRefs`/`context.plan·apply` 命名空间)已备。
- **B. 语义分块实验**:把 history「按轮」换主题聚类、tool_schema 换相似工具合并——
  只改 ChunkStrategy,契约/渲染不变。效果待验。
- **C2. 检视器类型化渲染**:assistant 文本走 Markdown、代码/JSON 语法高亮、
  tool_result 结构化(退出码/匹配数高亮)。在方向 C 的纯原文之上做体验优化。
- **D. 打磨与收尾**:移动端 sheet 触发按钮文案仍是 i18n 的 "model/tools"(需多语言清理);
  treemap 视觉(配色/字号/带顺序)、浮层交互(拖动/缩放)、截断上限可配;
  小块标签体感(降阈值 / 选中强制显标签 / band 级兜底标签)。

> 建议优先级:**A**(产品定位的核心价值)> B/C2(增量) > D(收尾)。A 的 ①② 可先落地
> 出手感,③ 的命令通道是全项目下一个真正的架构决策点。
