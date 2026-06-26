# Case · invalidate「DB_URL 迁库」(驱动脚本 + 三路对照)

> v2 `invalidate` 的**存在性证明** case(对偶 add 的 B1)。选它因为它**砸不塌**——
> 同时满足必要性尺子的两条:`(内容已假) ∧ (drop 会砸引用)`,keep/drop/fold 都不成立,
> **只有 invalidate** 同时满足"别用假值"+"别砸下游"。见 [operations.md](operations.md) §2 + §7 Case 2。

## 这个 case 在证什么

| 选项 | 结果 | 为什么不对 |
|---|---|---|
| **keep / 不动** | agent 用 `prod-old`(已下线) | 内容已假 → healthcheck 指向死 host |
| **drop 旧块** | db.py/migrate.py/report.py 对 `DATABASE_URL` 的引用悬空 | 砸下游(爆炸半径)→ agent 丢"这常量从哪来"、可能重造错 |
| **fold 旧块** | 摘要进一句,但**仍是旧值** | fold 只压缩、不纠正真假 |
| **✅ invalidate** | 旧块留作历史(引用链不断)+ pinned 说明注入新 host | 唯一同时"别用假值"+"别砸下游" |

**剃刀**:新 host 是**外部真相**,agent 结构上拿不到(我们故意全程不在普通轮里告诉它)——
新值**只经 invalidate 的作废说明注入**,这正是"人注入了机器没有的信息"的最干净证明。

---

## 前置

- **脚手架**(对偶 B1 的 `b1-acct-service/`):`~/contextvis-cases/inv-dburl-pipeline/` ——
  一个**预接线的真实迷你 repo**,import 链已搭好:`config.py(DATABASE_URL=old)` ← `db.py` ←
  {`migrate.py`, `report.py`}。**要真 repo 不要纯对话**:只有真 import,drop 才真砸下游、
  引用图层①/②才亮、作废目标才是个干净的 `file` 块。
- 一个**干净的**真实 Hermes session,**工作目录设在该脚手架**(`hermes dashboard --no-open`,
  仓库代码启动法见 memory「部署坑」)。`HERMES_CONTEXTVIS=1`(默认)。
- 三路对照用 **`session.branch`**(fork)在同一 brink 上分叉,互不污染(对偶 B1)。
- **⚠ 磁盘隔离(必读)**:`session.branch` 只 fork **上下文**,**三分支共享同一磁盘工作目录**。
  分支 A 会让 agent 把 `config.py` 改成 `prod-new` **落盘** → 不重置的话 B/C 从被污染的盘起步,
  对照失效。故 case 已 **git 版本管理**(pristine = T7-brink 态:`config.py=prod-old`、无各分支产物),
  **每个分支开跑前执行 `./reset.sh`**(= `git reset --hard && git clean -fd`)重置磁盘。
  **三分支只能串行**(共享盘,不能并行)。

---

## 第一幕 · 让 agent 探索 repo,把旧 DB_URL 读进上下文(turn 1–3)

逐条贴(要 agent 真**读** config.py —— 老 `DATABASE_URL` 由此作为一个 `file` 块进上下文,
那就是后面 invalidate 的目标块;真 import 让层①/②引用图亮起来):

**T1(读进事实):**
```
看看这个项目,跟我讲讲它的库连接是怎么走的、连接串配在哪。
```
> agent 会读 README + `config.py` + `db.py` → 老 `DATABASE_URL=prod-old` 进上下文(file 块)。

**T2(踩出引用链):**
```
migrate.py 和 report.py 各自怎么拿到连接的?帮我确认它们没各自硬编码 host。
```
> agent 读 `migrate.py`/`report.py` → 坐实 config ← db ← {migrate, report} 的引用结构。

**T3(在 repo 上干点真活,顺带加深引用):**
```
给 db.py 的 get_connection() 加上重试(最多 3 次)+ 连接失败打日志。
```

> 此刻结构:`config.py(DB_URL=old)` ← db.py ← {migrate.py, report.py},且老值已在上下文里。
> 旧值是整条引用链的根 → **drop 它必砸下游**(这就是 invalidate 的存在理由)。

## 第二幕 · 把旧块埋下去(turn 4–6,可选但更真)

让 config.py 那次读远离 tail、贴近压缩,放大"近因偏置淹没"——这正是 invalidate 的 pinned
说明要破的(对偶 promote 必要性"在场≠被遵守"):

**T4:**`给 report.py 写两个 pytest 用例,mock 掉 get_connection。`
**T5:**`把 migrate/report 的用法补进 README。`
**T6:**`给整个项目加个 .gitignore 和一段安装说明。`

## 第三幕 · brink(turn 7 —— 全程没告诉它迁库了)

```
写 healthcheck.py:验证所有服务都能连上生产库,打印每个的连通状态。
```

> agent 只见过 `prod-old`(repo 里 config.py 写的值)→ 默认会拿它写 healthcheck。**到此打住,
> 先别让它跑偏**——在这个 brink 上分三路。

---

## 三路对照(在 T7 brink 上 `session.branch` 分叉)

> 你**独知**迁库已完成、新串是 `postgres://prod-new.internal:5432/app`、`prod-old` 今天下线。
> agent 全程没听过这条 —— 它是外部真相(全程没在任何普通轮里说过)。

> **每条分支的固定流程(串行,别并行)**:`./reset.sh`(磁盘回到 pristine)→ `session.branch` 从 T7
> 分叉 → 做该分支的干预 → 发 brink T7 → 记录 agent 行为 + 截图 →(下一条前再 `./reset.sh`)。
> 不重置 = A 改的 `prod-new` 会让 B/C 失真。建议跑序 **A → B → C**。

### 分支 A · ✅ invalidate(主张)
1. 画布里点 **agent 读 config.py 的那个 `file` 块**(含 `DATABASE_URL=prod-old`)→ inspector
   右上 **⊘ 作废**。
2. reason 填:
   ```
   生产库已迁移:DATABASE_URL 现在是 postgres://prod-new.internal:5432/app,
   旧 host prod-old 今天下线。所有地方改用新 host,并更新 config.py。
   ```
3. 提交 → 旧块显**琥珀删除线**(原文还在);tail 落一条 **pinned 作废说明**。
4. 发 brink T7 → **预期**:healthcheck 用 `prod-new`,且 agent 会回头**改 config.py**。

### 分支 B · ✗ drop(反例:砸引用)
1. 同一旧块 → 标 **drop** → 应用。
2. 发 brink T7 → **预期**:db.py `from config import DATABASE_URL` 的来源读**已被删**,
   agent 丢了"这常量从哪定义/为何是这值"的线索 → 重读 / 重造 / 反问,**且仍可能落回 old**
   (config.py 磁盘上还是 old)。= 爆炸半径字面发生。

### 分支 C · ✗ keep(控制组:啥也不做)
1. 直接发 brink T7。
2. **预期**:agent 用 `prod-old` 写 healthcheck → 指向已下线 host。

---

## 观察清单(= 论文证据)

- [ ] **A vs C**:同一 brink、同一句话,**仅因一次 invalidate** 就从 `prod-old`(C)翻成 `prod-new`(A)
      → 坐实"人注入了机器结构上拿不到的外部真相,可测地改了结果"(对偶 B1 的 add 证据)。
- [ ] **A vs B**:A 里 db.py/migrate.py/report.py 的引用**仍解析得到**(旧块在、引用链不断);
      B 里同样的引用**悬空** → 证 drop 的爆炸半径、invalidate 的"留着但剥夺权威"独有价值。
- [ ] **白盒可见**:A 分支旧块是**琥珀删除线**(≠ drop 的消失、≠ keep 的原样)+ tail 有 violet📌
      作废说明 → 守不变量 #6(改了什么 + 系统如何衔接,都看得见)。
- [ ] **恢复**:点 **⊘ 已作废** → 旧块复原、按链移除作废说明 → 验 revalidate 可逆。
- [ ] (可选,引用图)选旧块看**下游弧**:A 里弧还在(引用未断),直观对照 B 的"删了就断"。

---

## 录 fixture(给 UI 开发用,可选)

A 分支落地后,面板 header **⬇ fixture** 一键录 `invalidate-dburl.json`(冻结 snapshot +
regime_colors,含琥珀块 + 作废说明 + 引用弧)→ 之后 `?fixture=invalidate-dburl` 零-token 重放,
做 UI 微调不再烧 session(对偶 `add-prod-readonly`)。

## 与 add·B1 的分工(别混)

- **B1(add)**:缺口 = 未来意图/约束(周五只读)→ 用户**写新内容**进 context。
- **本 case(invalidate)**:缺口 = **已记录的事实变假 + 它被引用**→ 用户**改现有块的真假状态**。
  两个 case 合起来覆盖剃刀的两类不可约信息(外部真相 / 意图)× 两个入口(写新 / 治理旧)。
