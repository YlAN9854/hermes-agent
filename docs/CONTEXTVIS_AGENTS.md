# ContextVis — Agent 文档

> 本文件供 AI 编码助手（Claude Code、Codex、OpenCode 等）快速理解 context-vis 项目。
> 阅读本文件后，agent 应能理解项目全貌并开始工作，无需阅读原始对话历史。
>
> 最后更新：2026-07-27（V1.5 实施后）

---

## 1. 项目是什么

context-vis 解决长程 AI agent 对话中的两个用户问题：

1. **重要信息失效**：用户之前提出的约束/规则/决策在 context window 压缩后被稀释、扭曲或丢弃，且用户无法感知。
2. **心路历程不可回顾**：用户的意图从最初想法到现在方向，发生了哪些偏移？什么导致了偏移？只能靠手动滚动重读原文。

解决方案：在对话之上构建一个**可折叠的语义层级视图**，让用户不必重读全文即可总览、定位原文，并在压缩/分叉时按自己的意图决定保留什么。

**一条贯穿全系统的铁律**：语义层是"索引"，原文是"真相"。所有 AI 生成的摘要/单元/聚合都可能出错，因此用户的一切理解与裁决最终都要能落回不可变的原文。

### 载体

当前实现载体是 **Hermes agent** 的 fork（本仓库，分支 `vis-demo`）。但 context-vis 的设计**刻意与 Hermes 解耦**——任何 agent 只需实现一个 adapter 接口，即可接入 context-vis 核心。核心层和 UI 层**禁止出现 Hermes 专有名词**。

### 治理规格

完整 V1 规格在 `../../docs/contextVis-spec.md`（项目根目录，git 仓库外）。本文件是其摘要和当前状态的快速参考。

---

## 2. 架构

三层架构，自上而下依赖，禁止反向依赖：

```
[UI 层]      前端视图（层级视图 + 原文视图 + 联动）       — agent-无关
[核心层]     单元生成 / 聚合 / 重要信息检测 / 压缩状态比对 — agent-无关，纯数据处理
[适配层]     ContextAdapter 接口                         — 每种 agent 实现一次
```

### ContextAdapter 接口

```python
class ContextAdapter(Protocol):
    # Tier 1（必需）
    def get_full_transcript(self) -> list[Turn]: ...
    def llm_complete(self, prompt: str, **opts) -> str: ...

    # Tier 2（增强）
    def get_active_context(self) -> ActiveContext | None: ...
    def get_compression_events(self) -> list[CompressionEvent]: ...

    # Tier 3（完整）
    def request_preserve(self, spans_in_B, drop_spans_in_B=None) -> PreserveResult: ...
```

**能力分级**（UI 必须根据 adapter 声明的 tier 优雅降级）：

| Tier | 能力 | 解锁功能 |
|------|------|----------|
| 1 | transcript + LLM | 语义单元、总览、定位、重要信息检测 |
| 2 | + active context + compression events | 存活状态可视化（present/reframed/absent） |
| 3 | + preserve/pin | 用户主导的压缩处置（keep/summary/drop） |

**降级 = 隐藏，绝不造假数据**。缺 Tier 2 就隐藏存活状态列，不显示假数据或报错。

### Hermes Adapter

`HermesContextAdapter` 在 `context_vis/hermes_adapter.py` 实现。它：
- 从 Hermes 的 `SessionDB` 读取会话消息（B = 完整记录）
- 沿 compression lineage 合并消息，排除合成摘要行
- 通过 compaction probe（`agent/compaction_probe.py`）获取压缩事件
- 将 pin/drop 写入 `<HERMES_HOME>/context-vis/pins/` 和 `drops/`

---

## 3. 数据结构

所有模型定义在 `context_vis/domain.py`：

| 类型 | 说明 |
|------|------|
| `Turn` | 原子单位：turn_id, role, content, tool_name, timestamp。**B 侧，不可变** |
| `SpanRef` | 指向 B 的指针：turn_id + char_start/char_end。**永远只指向 B，绝不指向 A** |
| `ActiveEntry` | A 侧条目：刻意**没有 turn_id**（只有 origin_turn_id 溯源）。防止 SpanRef 误指 A |
| `ActiveContext` | 模型当前看到的上下文（压缩后）：entries + fidelity |
| `CompressionEvent` | 压缩事件：event_id, kept_turn_ids, dropped_turn_ids, summary_text, fidelity |
| `SemanticUnit` | 语义单元：title, summary_sentences（每句带 source_spans）, covered_turns, salient_infos, frozen |
| `SalientInfo` | 重要信息：双指针——span_in_B（静，永久有效）+ status_in_A（动，每次压缩后更新） |
| `AggregateNode` | 聚合节点：child_unit_ids, origin（llm_draft/user_edited）, intent_tag |
| `BacktrackLink` | 回溯标注：from_unit_id → to_unit_id + note |
| `IntentSegment` | 意图区段：from_unit_id → to_unit_id（闭合区间）+ label + trigger_span + origin |
| `ContextVisModel` | 顶层模型：units, aggregates, decision_aggregates, backlinks, intent_segments, preserved, dropped |

### A/B 分离

这是系统的核心设计：

- **B（完整记录）**：append-only，不可变。所有 SpanRef 指向 B。
- **A（活动上下文）**：模型实际看到的，会被压缩修改。
- 语义单元建在 B 上 → 压缩动 A 不动 B → 单元层天然稳定。
- 每条 SalientInfo 的 `status_in_A` 照的是 A → **压缩不是威胁，是本系统要可视化的核心现象**。

### 存储

`context_vis/repository.py`：SQLite（`<HERMES_HOME>/context-vis.db`），仅两表：
- `context_models`：整个 `ContextVisModel` 存为 JSON blob（无迁移负担）
- `context_jobs`：异步任务状态

乐观锁：`revision` 字段做 CAS（compare-and-swap）。后台 job 绕过锁（`expected_revision=None`）。

---

## 4. 铁律（不可违反）

1. **SpanRef 只指 B**。ActiveEntry 刻意无 turn_id。任何指向 A 的指针都是设计缺陷。
2. **Frozen 单元不改**。增量更新只追加新单元，不修改已有 frozen 单元的 id/边界/标题/摘要。
3. **降级 = 隐藏**。tier 不足时隐藏功能，绝不显示假数据或零值占位。
4. **reliable / ai_guessed 不合并计数**。重要信息检测的保底级（规则匹配）和探索级（LLM 推测）必须分开呈现。
5. **llm_draft / user_edited 分开存储**。job 不覆盖用户编辑。
6. **线性布局 + 标注图层**。不引入树/图布局。回溯和意图轨道都是线性脊柱上的标注。
7. **不碰 `origin/feat/contextvis-occupancy-panel`**。废弃的 v2 测试分支。
8. **核心/UI 零 Hermes 名词**。Hermes 专有逻辑只在 `hermes_adapter.py` 和 `agent/` 文件中。

---

## 5. 文件地图

### 后端（Python）

| 文件 | 行数 | 职责 |
|------|------|------|
| `context_vis/domain.py` | 276 | 所有 dataclass 模型 + `validate_model` 不变量检查 |
| `context_vis/service.py` | 595 | 业务逻辑：generate_units, detect_salient, draft_aggregates, refresh_survival, request_preserve, save_edits |
| `context_vis/api.py` | 277 | FastAPI 路由：GET sessions, GET session/{id}, POST jobs, PUT model, POST preserve |
| `context_vis/hermes_adapter.py` | 567 | Hermes 适配：会话读取、lineage 合并、pin/drop 文件写入、compression events |
| `context_vis/survival.py` | 187 | 存活状态计算：present/reframed/absent 判定（SequenceMatcher + token containment） |
| `context_vis/codec.py` | 89 | JSON ↔ dataclass 序列化/反序列化（含嵌套 SpanRef rehydrate） |
| `context_vis/repository.py` | 123 | SQLite 存储 + 乐观锁 |
| `agent/context_compressor.py` | 3406 | Hermes 压缩器（patched：三路 keep/summary/drop 切分） |
| `agent/conversation_compression.py` | 1457 | 压缩编排（patched：加载 pin/drop turn ids） |
| `agent/compaction_probe.py` | 158 | 压缩探针：写 JSONL 事件到 `<HERMES_HOME>/context-vis/compaction/` |

### 前端（TypeScript/React）

| 文件/目录 | 说明 |
|-----------|------|
| `web/src/pages/ContextVisPage.tsx` (72L) | 顶层编排器：PageChrome + ConversationPanel + SpineWorkspace |
| `web/src/pages/context-vis/` (22 文件, ~3000L) | 所有子组件 |
| `web/src/lib/context-vis.ts` (237L) | 纯 helper 函数（受测层）：buildLedgerRows, groupTranscriptForALens, unitAliveness, intentLaneMarks, validateIntentSegments 等 |
| `web/src/lib/api.ts` | API 类型 + 请求函数（ContextVisModel, ContextVisUnit, ContextVisInfo, ContextVisCompression 等） |
| `web/src/context-vis-theme.css` (142L) | 作用域主题 `[data-contextvis-shell]`，学术可视化浅色风格 |

**关键子组件**：

| 组件 | 功能 |
|------|------|
| `ConversationPanel` | 左侧面板：transcript / model view / live 三模式切换 |
| `TranscriptView` | B 侧原文视图（turn 卡片 + 字符高亮） |
| `ModelViewTranscript` | A 侧模型视角（合成摘要块 + 存活 turn + 死亡 turn 折叠） |
| `SpineWorkspace` | 右侧语义脊柱（工具栏 + 聚合编辑器 + 单元列表 + 回溯区） |
| `SpineUnit` / `SpineUnitList` | 单元块渲染 + 存活度 pill + 意图 lane |
| `ConstraintLedger` | 约束总账：session 级 salient 聚合，absent 置顶 |
| `CompressionEvents` | 压缩事件面板（可折叠） |
| `IntentTrack` / `IntentLane` / `IntentTrackForms` | 意图轨道：脊柱 lane 渲染 + CRUD |
| `AggregateEditor` | 聚合节点编辑器（overview/decision 模式） |
| `BacktrackSection` | 回溯链接管理 |
| `useContextVisController` | 状态管理 hook（sessions, jobs, edits, navigation） |

### 测试

| 文件 | 覆盖 |
|------|------|
| `tests/context_vis/test_context_vis.py` | V1 核心测试（~48 个） |
| `tests/context_vis/test_v15_backend.py` | V1.5 压缩序列化 |
| `tests/context_vis/test_v15_intent.py` | V1.5 意图区段 CRUD + 验证 |
| `tests/context_vis/test_v15_dispositions.py` | V1.5 三档处置 adapter 侧 |
| `tests/context_vis/test_v15_disposition_atomicity.py` | V1.5 原子性 CAS 测试 |
| `tests/context_vis/test_eval_c7.py` | c7 case schema 验证 |
| `tests/test_compaction_pin.py` | 压缩器 pin 测试 |
| `tests/test_compaction_dispositions.py` | 压缩器三路切分 |
| `tests/test_compaction_disposition_edges.py` | 压缩器边界情况 |
| `tests/test_compaction_disposition_recompaction.py` | 重压缩交互 |
| `tests/test_false_boundary_regression.py` | 合并摘要误分类负面回归（20 个） |
| `web/src/lib/context-vis-p1.test.ts` | 前端 helper 测试 |
| `web/src/pages/ContextVisPage.p1.test.tsx` | 前端组件测试 |

### 评估（Eval）

| 文件 | 说明 |
|------|------|
| `evals/context_vis/case_schema.py` | 合成 case schema：Turn, Segment, GoldConstraint, Backtrack, IntentShift, Compaction, GoldSurvival |
| `evals/context_vis/cases/c1.py`–`c7.py` | 7 个合成 case |
| `evals/context_vis/seed.py` | 将 case 写入 Hermes SessionDB |
| `evals/context_vis/run_generate.py` | 驱动语义单元生成 |
| `evals/context_vis/run_survival.py` | 驱动存活状态计算 |
| `evals/context_vis/metrics.py` | 计算评估指标 |
| `evals/context_vis/preserve_e2e/` | Tier 3 端到端验证（真实压缩器 + 独立 sub-agent 审计） |

---

## 6. 当前实现状态

### V1（已完成，已验收）

- **Step 0** 数据结构 ✅
- **Step 1** 语义单元生成（LLM 切话题 + 摘要分句 + source_spans 回指 B） ✅
- **Step 2** 原文联动（双向定位 + 字符级 hover 高亮） ✅
- **Step 3** 重要信息检测（保底级规则 + 探索级 LLM，分开计数） ✅
- **Step 4** 聚合层（总览模式 ≤8 节点 + 裁决模式带 intent） ✅
- **Step 5** 回溯标注（手动 BacktrackLink，线性布局上叠加） ✅
- **Tier 2** 存活状态探针 + survival 三态计算（present/reframed/absent） ✅
- **Tier 3** 用户主导 pin 保留（端到端验收，独立 sub-agent 审计 PASS） ✅

### V1.5（已实施，未修复 blocker）

| Step | 内容 | 状态 |
|------|------|------|
| 1 | 后端暴露压缩事件 + live_turn_ids | ✅ |
| 2 | 前端重构：534 行单文件 → 22 子组件 | ✅ |
| 3 | 约束总账（ConstraintLedger） | ✅ |
| 4 | A-lens 模型视角（ModelViewTranscript + CompressionEvents） | ✅ |
| 5 | 意图区段后端（IntentSegment + validate_model） | ✅ |
| 6 | 意图轨道前端（IntentLane + IntentTrack） | ✅ |
| 7 | 三档处置（keep/summary/drop） | ✅（blocker 已修复） |
| 8 | Eval c7 + IntentShift schema | ✅ |

**测试状态**：230 测试全绿（133 Python + 97 前端），TypeScript 编译零错误。

### Step 7 Blocker（已修复 2026-07-27）

**`T4-P2-NO-FALSE-BOUNDARY-ON-USER-TEXT`**：`_strip_summary_prefix` 和 `_is_context_summary_content` 在任意文本上调用 `_split_merged_summary_text()`，会误分类包含 delimiter+prefix 模式的普通用户文本。

**修复**（`8a17d455c`）：两个调用点现在要求文本以 `_MERGED_PRIOR_CONTEXT_HEADER` 开头才调用 split。20 个负面回归测试覆盖 current/legacy/historical 全变体。

---

## 7. 如何运行和测试

### 后端测试

```bash
cd hermes-agent
uv run pytest tests/context_vis/ tests/test_compaction_pin.py tests/test_compaction_dispositions.py tests/test_compaction_disposition_edges.py tests/test_compaction_disposition_recompaction.py --tb=short
```

### 前端测试

```bash
cd hermes-agent/web
npx tsc --noEmit -p tsconfig.app.json   # 类型检查
npx vite build                           # 构建
npx vitest run                           # 测试
```

### 启动 Dashboard

```bash
cd hermes-agent
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main dashboard --no-open
# 访问 http://127.0.0.1:<port>/context-vis
```

### Eval 流程

```bash
cd hermes-agent
HERMES_HOME=$(mktemp -d) uv run python -m evals.context_vis.seed c7
HERMES_HOME=$(mktemp -d) uv run python -m evals.context_vis.run_generate c7
# ... run_survival c7 → metrics c7
```

---

## 8. 关键设计决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| A-lens 落点 | 原文面板侧（ModelViewTranscript） | 脊柱折叠会视觉暗示"单元层被压缩破坏"，与铁律矛盾 |
| 意图轨道标注方式 | 纯手动标注 | 符合 spec "LLM 切话题、人补意图"精神 |
| 三档处置交互 | 单元级 keep/summary/drop | 语义层存在意义 = 可操作的中间粒度 |
| Drop 存储 | 独立文件 `drops/<session>.json` | 与 pin 解耦，不必同 commit 发布 |
| Eval c7 题材 | 研究方法设计头脑风暴 | 贴合 general-agent 探索场景 |
| 意图轨道数据模型 | 稀疏标注（BacktrackLink 模式），非第三个聚合列表 | 聚合 validator 要求全分区，不适合稀疏区段 |
| 增量生成 + 意图区段 | 区段必须闭合，新单元落入未标注空隙 | 防止新单元被静默吞并 |

---

## 9. 约定和约束

- **Git 分支**：`vis-demo` 是 context-vis 的工作分支，领先 `main` 37+ commits
- **不碰的分支**：`origin/feat/contextvis-occupancy-panel`（废弃 v2）
- **Eval 判断**：验收判断必须来自独立 sub-agent，不能自评（防偏差）
- **提交规范**：`feat(context-vis):`, `fix(context-vis):`, `eval(context-vis):`, `test(context-vis):`
- **API 版本**：所有 API 路由前缀 `/api/context-vis`，profile-aware（`?profile=` 参数）
- **数据隔离**：context-vis 状态存 `<HERMES_HOME>/context-vis.db`，不混入 Hermes `state.db`
- **Pin/Drop 文件**：`<HERMES_HOME>/context-vis/pins/<session>.json` 和 `drops/<session>.json`，v1 JSON 格式

---

## 10. 相关文档索引

| 文件 | 内容 |
|------|------|
| `../../docs/contextVis-spec.md` | V1 权威规格（完整，中文） |
| `../../docs/plans/context-vis V1 开发计划.md` | V1 开发计划 |
| `docs/CONTEXTVIS_HANDOFF.md` | V1 跨设备交接文档（V1.5 前的状态快照） |
| `docs/CONTEXTVIS_AGENTS.md` | **本文件**——跨 Agent 快速参考 |
| `web/DESIGN.md` | 前端设计系统合约（视觉语言、色彩、排版） |
| `evals/context_vis/REPORT.md` | 评估方法论 + 历史结果 |
| `evals/context_vis/E2E_ACCEPTANCE.md` | 端到端验收报告（含独立审计） |
