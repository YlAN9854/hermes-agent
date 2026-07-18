"""c3 — 约束密集散布：遗留数据管道重构（CSV 导入 → 清洗 → 入库 PostgreSQL）。

用户在会话各处不断补充硬性约束，工具输出中也夹带禁令式告警。
"""
from evals.context_vis.case_schema import Case, T, Segment, GoldConstraint, Backtrack

TURNS = [
    # ---------- Segment 0: 需求梳理与现状调研 (0-8) ----------
    # 0
    T("user", (
        "我想把 etl/ 下面那套 CSV 导入管道重构一下。现在的流程是：供应商每天往 SFTP 丢 CSV，"
        "cron 拉下来以后由 etl/importer.py 逐行清洗再写进 PostgreSQL 的 supplier_orders 表。"
        "这套代码是三年前一个外包写的，全是全局变量和裸 except，出错只会静默跳行，排查一次要半天。\n"
        "先说一个前提：线上跑任务的 runner 还是 Debian 11 自带的解释器，短期内不会升级，"
        "所以重构后的代码必须保持对 Python 3.10 的兼容，别用 3.11+ 才有的语法。"
    )),
    # 1
    T("assistant", (
        "明白，目标是把 etl/ 的 CSV 导入管道重构成可维护、可观测的结构，且语法层面兼容 Python 3.10——"
        "也就是不用 3.11 的 except*、tomllib、Self 类型这些东西，match 语句 3.10 有所以可以用，"
        "类型标注我会用 `X | None` 这种 3.10 已支持的写法。\n"
        "在动手前我先做三件事：看目录结构和入口脚本、读主流程代码、确认目标表的 schema 现状，"
        "摸清数据流再谈方案。先从目录开始。"
    )),
    # 2
    T("tool", (
        "$ find etl legacy -maxdepth 2 -type f | sort\n"
        "etl/__init__.py\n"
        "etl/config.ini\n"
        "etl/cron_entry.sh\n"
        "etl/importer.py\n"
        "etl/utils.py\n"
        "legacy/report_export.py\n"
        "legacy/sftp_pull.pl\n"
        "legacy/vendor_map.json\n"
        "$ wc -l etl/importer.py etl/utils.py legacy/report_export.py\n"
        "  842 etl/importer.py\n"
        "  156 etl/utils.py\n"
        "  418 legacy/report_export.py\n"
        " 1416 total\n"
        "$ head -20 etl/cron_entry.sh\n"
        "#!/bin/bash\n"
        "# runs daily, pulled by ops cron @ 01:30\n"
        "cd /srv/pipeline && python3 -m etl.importer --date $(date +%F)\n"
        "$ cat etl/config.ini\n"
        "[sftp]\n"
        "host = sftp.vendor-gw.internal\n"
        "remote_dir = /outbox/daily\n"
        "[db]\n"
        "dsn_env = PIPELINE_DSN\n"
        "table = supplier_orders\n"
        "[cleaning]\n"
        "date_formats = %Y-%m-%d,%Y/%m/%d,%d-%m-%Y,%Y%m%d,%d/%m/%Y %H:%M\n"
        "amount_strip_chars = ,¥ \n"
        "$ python3 --version\n"
        "Python 3.10.12\n"
        "$ python3 -c \"import psycopg2; print(psycopg2.__version__)\"\n"
        "2.9.5 (dt dec pq3 ext lo64)\n"
    ), tool_name="Bash"),
    # 3
    T("assistant", (
        "结构比预想的简单：\n"
        "- etl/importer.py（842 行）是主体，拉取、清洗、入库全糊在一个文件里；\n"
        "- etl/utils.py 有一些日期解析和编码相关的辅助函数；\n"
        "- legacy/ 下还有一个 Perl 的 SFTP 拉取脚本和 report_export.py，看名字像是给别的系统用的导出。\n"
        "cron 每天 01:30 触发。接下来我细读 importer.py，重点看清洗规则和写库方式。"
    )),
    # 4
    T("user", (
        "对，legacy/ 那几个文件是老 BI 系统还在调的，跟这次重构无关，"
        "你重构过程中不要修改 legacy/ 目录下的任何文件，哪怕只是格式化也不行，那边没有测试，改坏了没人兜底。\n"
        "importer.py 里最恶心的是清洗部分，供应商的日期格式有四五种，金额还有带千分位逗号的。"
    )),
    # 5
    T("assistant", (
        "收到，legacy/ 目录我完全不碰，只读不写，重构范围严格限制在 etl/ 内部（如有新文件也放 etl/ 下）。\n"
        "现在读 importer.py 的清洗和写库逻辑。"
    )),
    # 6
    T("tool", (
        "→ Read etl/importer.py (节选 88-190 行)\n"
        "```python\n"
        "def sniff_encoding(path):\n"
        "    # vendors send gbk / gb18030 / utf-8-sig randomly, sniff first 64KB\n"
        "    raw = open(path, 'rb').read(65536)\n"
        "    if raw.startswith(b'\\xef\\xbb\\xbf'):\n"
        "        return 'utf-8-sig'\n"
        "    try:\n"
        "        raw.decode('utf-8'); return 'utf-8'\n"
        "    except UnicodeDecodeError:\n"
        "        pass\n"
        "    try:\n"
        "        raw.decode('gb18030'); return 'gb18030'\n"
        "    except UnicodeDecodeError:\n"
        "        return 'latin-1'  # last resort, never raises\n"
        "\n"
        "def clean_row(row):\n"
        "    global BAD_ROWS\n"
        "    try:\n"
        "        d = parse_date_any(row[0])\n"
        "        amt = float(row[3].replace(',', ''))\n"
        "    except Exception:\n"
        "        BAD_ROWS += 1\n"
        "        return None\n"
        "    ...\n"
        "\n"
        "def parse_date_any(s):\n"
        "    s = s.strip()\n"
        "    for fmt in DATE_FORMATS:  # from config.ini, 5 formats\n"
        "        try:\n"
        "            return datetime.strptime(s, fmt).date()\n"
        "        except ValueError:\n"
        "            continue\n"
        "    # excel serial dates, vendor C exports these sometimes\n"
        "    if s.isdigit() and 40000 < int(s) < 60000:\n"
        "        return EXCEL_EPOCH + timedelta(days=int(s))\n"
        "    raise ValueError('unparseable date: %r' % s)\n"
        "\n"
        "def insert_rows(conn, rows):\n"
        "    cur = conn.cursor()\n"
        "    for r in rows:\n"
        "        cur.execute(\"INSERT INTO supplier_orders VALUES ('%s','%s',%s)\" % r)\n"
        "    conn.commit()\n"
        "\n"
        "def main(date):\n"
        "    global BAD_ROWS\n"
        "    BAD_ROWS = 0\n"
        "    for path in glob.glob(INBOX + '/*_%s.csv' % date):\n"
        "        enc = sniff_encoding(path)\n"
        "        with open(path, encoding=enc, newline='') as f:\n"
        "            rows = [clean_row(r) for r in csv.reader(f)]\n"
        "        insert_rows(CONN, [r for r in rows if r])\n"
        "    print('done, bad rows:', BAD_ROWS)  # 唯一的\"报告\"\n"
        "```\n"
    ), tool_name="Read"),
    # 7
    T("assistant", (
        "问题基本清楚了：\n"
        "1. insert_rows 用 % 字符串拼 SQL，既有注入风险，遇到含引号的供应商名会直接崩；\n"
        "2. clean_row 裸 except 吞掉所有异常，只累加一个全局 BAD_ROWS 计数，坏行内容丢失；\n"
        "3. 逐行 INSERT，一天几十万行的量级下慢得离谱；\n"
        "4. sniff_encoding 倒是写得挺实在，GBK/GB18030/UTF-8-BOM 的探测顺序是对的，这块逻辑本身没毛病。\n"
        "在出方案前想确认：supplier_orders 这张表下游有哪些消费方？重构时表结构有没有调整空间？"
    )),
    # 8
    T("user", (
        "下游主要是我们自己的看板服务，走的是一个视图，问题不大。"
        "但有个坑你得知道：财务那边的报表脚本直接 select 这张表，字段名一变他们就崩了，"
        "而且他们那个脚本在另一个部门的仓库里，我们够不着。表结构你想加索引、加新列都行，就是别动存量列。"
    )),

    # ---------- Segment 1: 重构方案设计 (9-16) ----------
    # 9
    T("assistant", (
        "了解，supplier_orders 的存量列名和类型保持原样，只做加法（新列、索引）。基于现状我给一版重构方案：\n"
        "1. 拆分模块：etl/reader.py（下载+编码探测+csv 解析）、etl/cleaner.py（纯函数清洗，返回结构化结果和坏行明细）、"
        "etl/writer.py（批量写库）、etl/pipeline.py（编排+日志）；\n"
        "2. 坏行不再静默丢弃，落到新表 supplier_orders_rejects，带原始行内容和失败原因；\n"
        "3. 写库改成 execute_values 批量插入，事务粒度按文件；\n"
        "4. 用 dataclass 定义行模型，清洗规则做成可单测的小函数。\n"
        "你看方向上有没有要调的？"
    )),
    # 10
    T("user", (
        "方向可以。写库那块补一条硬要求：我们上季度刚过安全审计，所有 SQL 必须使用参数化查询，"
        "包括你查重、查表是否存在这种只读语句也一样，审计工具会扫代码里的字符串拼接。\n"
        "rejects 表的主意不错，财务对坏行一直有意见。"
    )),
    # 11
    T("assistant", (
        "好，写库层统一走 psycopg2 的参数绑定：数据插入用 execute_values 配占位符模板，"
        "元数据查询（表存在性、行数核对）也全部用 %s 参数传递，代码里不出现任何 SQL 字符串拼接或 f-string 插值。"
        "我会在 writer.py 顶部注释里写明这条约定，防止后人手滑。\n"
        "清洗层我打算引入 pandas 做向量化处理，几十万行能快一个数量级，日期解析也省事。"
    )),
    # 12
    T("user", (
        "pandas 打住。这台 runner 的环境是运维用镜像锁死的，装包要走两周的审批流程，"
        "这次重构禁止引入新的第三方依赖，psycopg2 是现成的可以用，其他的一律标准库解决。"
        "性能瓶颈本来也在写库不在解析。"
    )),
    # 13
    T("assistant", (
        "明白，依赖清单冻结在现状：标准库 + 已装好的 psycopg2，不新增任何包。\n"
        "清洗层改回纯标准库实现：csv 模块流式读取，datetime.strptime 按已知格式列表逐个尝试，"
        "decimal.Decimal 处理金额避免浮点误差。批处理用生成器按 5000 行一批喂给 writer，内存也可控。\n"
        "下一步我确认一下目标库的 schema 版本，看 rejects 新表怎么建。"
    )),
    # 14
    T("tool", (
        "$ python3 -m dbtool schema-status --dsn $STAGING_DSN\n"
        "dbtool 1.7.3 (site config: /etc/dbtool/site.toml)\n"
        "current schema: v2 (applied 2025-11-02 by ops)\n"
        "pending migrations: none\n"
        "WARNING: schema v2 requires a migration lock, never run migrations without --lock; "
        "unlocked DDL on this cluster has previously corrupted the pg_partman maintenance state.\n"
        "connection: staging-pg.internal:5432/pipeline (role=etl_rw)\n"
        "$ python3 -m dbtool describe supplier_orders --dsn $STAGING_DSN | head -8\n"
        " column      | type          | nullable\n"
        "-------------+---------------+---------\n"
        " order_date  | date          | no\n"
        " vendor_code | varchar(16)   | no\n"
        " sku         | varchar(64)   | no\n"
        " amount      | numeric(14,2) | no\n"
        " vendor_name | varchar(128)  | yes\n"
        " contact_ph  | varchar(24)   | yes\n"
        " batch_id    | varchar(32)   | yes\n"
        " loaded_at   | timestamptz   | yes\n"
        "$ python3 -m dbtool describe supplier_orders --dsn $STAGING_DSN | tail -4\n"
        "indexes:\n"
        "  supplier_orders_pkey (order_date, vendor_code, sku)\n"
        "row estimate: 214,506,331\n"
        "partitioning: RANGE (order_date), monthly via pg_partman\n"
    ), tool_name="Bash"),
    # 15
    T("assistant", (
        "schema 目前是 v2，没有挂起的迁移。注意到 dbtool 的告警：这个集群上的迁移必须带 --lock 跑，"
        "否则可能弄坏 pg_partman 的维护状态——建 supplier_orders_rejects 的 DDL 我会写成正式迁移文件，"
        "并且执行命令固定为 `dbtool migrate --lock`，不走裸 psql。\n"
        "rejects 表结构我计划：id、source_file、line_no、raw_line、reason、created_at，不引用主表外键，避免耦合。\n"
        "方案整体就这些，你拍板我就开工。"
    )),
    # 16
    T("user", (
        "拍板，就按这个来。还有个环境上的事顺嘴说下：运维只给我们这套服务开了 5 个数据库连接，"
        "超了会直接被防火墙掐掉而且不报错，之前有个同事开连接池开到 20，排查了两天。"
        "你写 writer 的时候心里有个数。"
    )),

    # ---------- Segment 2: 实现重构 (17-27) ----------
    # 17
    T("assistant", (
        "开工。连接这块我干脆不用池：pipeline 全程复用单个连接，rejects 写入也走同一个连接的独立事务，"
        "峰值占用 1 个连接，离 5 的上限留足余量。\n"
        "实现顺序：先建迁移文件和 writer.py（参数化 + execute_values），再拆 reader 和 cleaner，最后把 pipeline 串起来。"
    )),
    # 18
    T("tool", (
        "→ Write migrations/0007_add_rejects_table.sql\n"
        "-- dbtool migration: requires --lock (cluster policy)\n"
        "CREATE TABLE IF NOT EXISTS supplier_orders_rejects (\n"
        "    id          bigserial PRIMARY KEY,\n"
        "    source_file text        NOT NULL,\n"
        "    line_no     integer     NOT NULL,\n"
        "    raw_line    text        NOT NULL,\n"
        "    reason      text        NOT NULL,\n"
        "    created_at  timestamptz NOT NULL DEFAULT now()\n"
        ");\n"
        "CREATE INDEX IF NOT EXISTS idx_rejects_file ON supplier_orders_rejects (source_file);\n"
        "→ Write etl/writer.py (118 行，节选)\n"
        "```python\n"
        "# NOTE: 本模块所有 SQL 一律参数化（审计要求），严禁字符串拼接/格式化生成 SQL。\n"
        "INSERT_TMPL = (\n"
        "    'INSERT INTO supplier_orders '\n"
        "    '(order_date, vendor_code, sku, amount, vendor_name, contact_ph, batch_id, loaded_at) '\n"
        "    'VALUES %s'\n"
        ")\n"
        "\n"
        "def write_batch(conn, rows: list[OrderRow], batch_id: str) -> int:\n"
        "    payload = [(r.order_date, r.vendor_code, r.sku, r.amount,\n"
        "                r.vendor_name, r.contact_ph, batch_id, datetime.now(timezone.utc))\n"
        "               for r in rows]\n"
        "    with conn.cursor() as cur:\n"
        "        execute_values(cur, INSERT_TMPL, payload, page_size=1000)\n"
        "    return len(payload)\n"
        "\n"
        "def write_rejects(conn, rejects: list[RejectedRow], source_file: str) -> None:\n"
        "    with conn.cursor() as cur:\n"
        "        execute_values(cur,\n"
        "            'INSERT INTO supplier_orders_rejects '\n"
        "            '(source_file, line_no, raw_line, reason) VALUES %s',\n"
        "            [(source_file, r.line_no, r.raw_line, r.reason) for r in rejects])\n"
        "```\n"
        "→ Write etl/cleaner.py (164 行)\n"
        "文件已写入。"
    ), tool_name="Write"),
    # 19
    T("assistant", (
        "writer 和 cleaner 完成，全部参数化，无字符串拼 SQL。接下来是 reader.py。\n"
        "看了下旧的 sniff_encoding，我想直接简化掉：现在都 2026 年了，我打算统一按 utf-8 读，"
        "错误字符用 errors='replace' 兜底，这样 reader 能少 30 行代码，也少一条分支要测。"
    )),
    # 20
    T("user", (
        "别别别，这个不能省。务必保留原有的 CSV 编码探测逻辑，供应商的文件到现在一半还是 GBK 的，"
        "你按 utf-8 加 replace 读进去，中文供应商名全变问号，入了库比报错还难查。"
        "那段 sniff_encoding 是踩了三年坑攒出来的，原样搬过去就行。"
    )),
    # 21
    T("assistant", (
        "你说得对，是我想当然了——GBK 文件按 utf-8 replace 读会产生静默数据损坏，比失败更糟。\n"
        "我把 sniff_encoding 原封不动搬进 etl/reader.py（逻辑零改动，只加类型注解和单测），"
        "reader 打开文件前先探测，探测结果记进日志方便追溯。reader 写完后我在 staging 上试跑一次导入。"
    )),
    # 22
    T("tool", (
        "$ python3 -m etl.pipeline --date 2026-07-17 --dsn $STAGING_DSN --file samples/vendor_a_20260717.csv\n"
        "[2026-07-18 10:41:02] INFO  pipeline: start date=2026-07-17 files=1\n"
        "[2026-07-18 10:41:02] INFO  reader: encoding detected: gb18030 (samples/vendor_a_20260717.csv)\n"
        "[2026-07-18 10:41:02] INFO  reader: 5000 raw rows parsed, header ok (8 columns)\n"
        "[2026-07-18 10:41:03] INFO  cleaner: 4982 rows ok, 18 rejected\n"
        "[2026-07-18 10:41:03] INFO  writer: bulk COPY start (batch=5000)\n"
        "[2026-07-18 10:41:03] ERROR writer: server rejected operation:\n"
        "    ERROR: replica set must be in maintenance mode before bulk import\n"
        "    HINT: run `ops-cli maint enable pipeline` first; bulk COPY while streaming "
        "replication is active can desync the read replica.\n"
        "[2026-07-18 10:41:03] ERROR pipeline: aborted, transaction rolled back\n"
        "exit status 1\n"
    ), tool_name="Bash"),
    # 23
    T("assistant", (
        "staging 的集群策略比想象中严：批量 COPY 之前必须先把副本集切到维护模式，否则服务端直接拒绝。\n"
        "处理方式：pipeline.py 在批量写入前调用 `ops-cli maint enable pipeline`，"
        "结束后（含异常路径，放在 finally 里）调用 `ops-cli maint disable pipeline`，"
        "并在维护模式开启失败时直接终止导入而不是降级为逐行 INSERT——逐行插会绕过这个保护，风险更大。\n"
        "我把这段编排补上再跑。"
    )),
    # 24
    T("user", (
        "可以。日志这里再加一条红线：这批 CSV 里有供应商联系人的手机号列，"
        "日志里绝对不能打印客户手机号，合规那边今年抓这个抓得很凶，"
        "坏行落 rejects 表没关系，那个表有权限管控，但日志是全员可见的。"
    )),
    # 25
    T("assistant", (
        "明白，日志与手机号隔离：\n"
        "1. cleaner 记 reject 原因时只记字段名和失败类型（如 `phone: invalid format`），不带字段值；\n"
        "2. 坏行原文只写入 supplier_orders_rejects.raw_line，日志里引用 rejects 表 id 而非内容；\n"
        "3. pipeline 的 DEBUG 级别抽样日志对 phone 列统一做 `138****`  掩码。\n"
        "改完这些，主体实现就齐了，我跑一遍完整流程验证。"
    )),
    # 26
    T("tool", (
        "$ ops-cli maint enable pipeline && python3 -m etl.pipeline --date 2026-07-17 "
        "--dsn $STAGING_DSN --file samples/vendor_a_20260717.csv; ops-cli maint disable pipeline\n"
        "maintenance mode: ON (pipeline)\n"
        "[2026-07-18 11:05:44] INFO  pipeline: start date=2026-07-17 files=1\n"
        "[2026-07-18 11:05:44] INFO  reader: encoding detected: gb18030 (samples/vendor_a_20260717.csv)\n"
        "[2026-07-18 11:05:45] INFO  cleaner: 4982 rows ok, 18 rejected (reasons: bad_date=11, bad_amount=5, phone=2)\n"
        "[2026-07-18 11:05:45] DEBUG cleaner: sample ok row: order_date=2026-07-17 vendor_code=VA01 "
        "sku=SKU-88213 amount=1024.50 vendor_name=华信包装 contact_ph=138********\n"
        "[2026-07-18 11:05:45] INFO  writer: maintenance mode verified: ON\n"
        "[2026-07-18 11:05:46] INFO  writer: bulk COPY done: 4982 rows in 0.9s (batch=5000, pages=5)\n"
        "[2026-07-18 11:05:46] INFO  writer: rejects persisted: 18 rows -> supplier_orders_rejects "
        "(ids 301..318, see table for raw lines)\n"
        "[2026-07-18 11:05:46] INFO  pipeline: row count check: source=5000 loaded=4982 rejected=18 ok\n"
        "[2026-07-18 11:05:46] INFO  pipeline: done, peak_db_connections=1\n"
        "maintenance mode: OFF (pipeline)\n"
        "exit status 0\n"
    ), tool_name="Bash"),
    # 27
    T("assistant", (
        "staging 全流程通了，几个关键点：\n"
        "- GB18030 文件正确探测并解码，中文供应商名完整入库；\n"
        "- 4982 行批量入库 0.9 秒（旧版逐行插同样数据要 4 分多）；\n"
        "- 18 条坏行带原因落到 rejects 表，日志里只出现 reject id 和脱敏样例，无敏感字段明文；\n"
        "- 行数核对 source=loaded+rejected 通过，连接峰值 1。\n"
        "旧的 etl/importer.py 我先保留并在文件头标记 deprecated，等新管道稳定跑一周再删。"
        "cron 侧只需把入口从 `etl.importer` 换成 `etl.pipeline`，时间我建议挪到 02:30，避开 01:30 的 SFTP 拉取尾巴。"
    )),

    # ---------- Segment 3: 测试与修复 (28-35) ----------
    # 28
    T("user", (
        "入口替换没问题，时间先别定 02:30——凌晨两点到四点是备份窗口，那个点库基本写不进东西，"
        "任务跑了也是白跑，之前老管道就在那个点超时过几次。你放 04:30 之后自己看着排。\n"
        "代码这边把测试补齐跑一遍吧，重构不带测试等于没重构。"
    )),
    # 29
    T("tool", (
        "$ python3 -m pytest tests/etl -q\n"
        "conftest: WARNING: refusing DSN containing 'prod'; this suite must only ever run "
        "against local/staging databases (guard active)\n"
        "........F.......F........                                                [100%]\n"
        "=================================== FAILURES ===================================\n"
        "____________________ test_sniff_encoding_latin1_fallback ______________________\n"
        "tests/etl/test_reader.py:41: in test_sniff_encoding_latin1_fallback\n"
        "    assert sniff_encoding(tmp_file) == 'latin-1'\n"
        "E   AssertionError: assert 'gb18030' == 'latin-1'\n"
        "_______________________ test_clean_row_amount_negative ________________________\n"
        "tests/etl/test_cleaner.py:77: in test_clean_row_amount_negative\n"
        "    assert result.reason == 'bad_amount'\n"
        "E   AttributeError: 'CleanRow' object has no attribute 'reason'\n"
        "----------------------------- Captured stdout call -----------------------------\n"
        "cleaner: row 7 amount='-350.00' -> Decimal('-350.00') (accepted)\n"
        "=========================== short test summary info ===========================\n"
        "FAILED tests/etl/test_reader.py::test_sniff_encoding_latin1_fallback\n"
        "FAILED tests/etl/test_cleaner.py::test_clean_row_amount_negative\n"
        "2 failed, 23 passed in 3.41s\n"
    ), tool_name="Bash"),
    # 30
    T("assistant", (
        "23 过 2 挂，两个失败都在测试侧而不是实现侧：\n"
        "1. latin-1 回退那条：我构造的样本字节恰好是合法的 GB18030 序列，所以探测器（正确地）返回了 gb18030。"
        "换成 GB18030 一定解不开的字节序列（比如孤立的 0xFF 0xFE 组合）来触发回退分支，探测函数本身不动；\n"
        "2. bad_amount 那条：清洗成功的 CleanRow 和被拒的 RejectedRow 是两个 dataclass，"
        "测试拿错了类型，负数金额在我们的规则里其实是合法的（冲销单），这条用例的预期本身就写错了，"
        "应改为断言负数金额清洗通过。我改测试重跑。"
    )),
    # 31
    T("tool", (
        "→ Edit tests/etl/test_reader.py: 样本字节改为 b'\\xff\\xfe\\x41\\x42' + 随机高位字节（GB18030 必然解码失败）\n"
        "→ Edit tests/etl/test_cleaner.py: test_clean_row_amount_negative 重命名为 "
        "test_clean_row_amount_negative_is_valid，断言改为清洗通过且 amount == Decimal('-350.00')\n"
        "$ python3 -m pytest tests/etl/test_reader.py tests/etl/test_cleaner.py -q\n"
        "conftest: WARNING: refusing DSN containing 'prod'; this suite must only ever run "
        "against local/staging databases (guard active)\n"
        ".........................                                                [100%]\n"
        "25 passed in 2.87s\n"
        "$ python3 -m pytest tests/etl -q --tb=no\n"
        "conftest: WARNING: refusing DSN containing 'prod'; this suite must only ever run "
        "against local/staging databases (guard active)\n"
        "25 passed in 3.02s\n"
    ), tool_name="Bash"),
    # 32
    T("assistant", (
        "全部 25 条用例通过。顺带确认一点：conftest 里有个守卫，凡是 DSN 带 'prod' 的一律拒跑，"
        "这个守卫我原样保留了，测试永远只打本地或 staging 库。\n"
        "另外我补了一条兼容性检查：CI 里加了 `python3.10 -m compileall etl tests`，"
        "任何 3.11+ 语法都会在这一步直接编译失败，防止以后有人无意间破坏 3.10 兼容。"
    )),
    # 33
    T("tool", (
        "$ python3.10 -m compileall -q etl tests && echo COMPILE_OK\n"
        "COMPILE_OK\n"
        "$ grep -rnE '(execute|mogrify)\\(.*(%|\\+|f\")' etl/ || echo NO_SQL_CONCAT\n"
        "NO_SQL_CONCAT\n"
        "$ python3 - <<'EOF'\n"
        "import ast, pathlib\n"
        "mods = {a.names[0].name.split('.')[0] for p in pathlib.Path('etl').rglob('*.py')\n"
        "        for a in ast.walk(ast.parse(p.read_text())) if isinstance(a, ast.Import)}\n"
        "print('third-party imports:', sorted(mods - STDLIB) or ['psycopg2 only'])\n"
        "EOF\n"
        "third-party imports: ['psycopg2 only']\n"
        "$ git diff --stat main\n"
        " etl/cleaner.py                        | 164 ++++++++++++++\n"
        " etl/pipeline.py                       | 141 +++++++++++++\n"
        " etl/reader.py                         |  96 ++++++++\n"
        " etl/writer.py                         | 118 +++++++++++\n"
        " etl/importer.py                       |   4 +\n"
        " migrations/0007_add_rejects_table.sql |  11 +\n"
        " tests/etl/test_cleaner.py             |  88 ++++++++\n"
        " tests/etl/test_pipeline.py            |  64 ++++++\n"
        " tests/etl/test_reader.py              |  52 ++++++\n"
        " 9 files changed, 738 insertions(+)\n"
        "$ git diff --stat main -- legacy/\n"
        "(no changes)\n"
    ), tool_name="Bash"),
    # 34
    T("user", (
        "看起来齐了。你最后过一遍这次改动都守住了哪些前提，我明天要拿这个跟运维和财务对一下再上线。"
        "cron 时间就定 04:45 吧。"
    )),
    # 35
    T("assistant", (
        "收尾清单如下，可直接拿去对齐：\n"
        "- 语法兼容 Python 3.10，CI 用 python3.10 compileall 把关；\n"
        "- legacy/ 目录零改动（git diff 已验证）；supplier_orders 存量列名、类型未动，只新增 rejects 表，财务报表脚本不受影响；\n"
        "- 全部 SQL 参数化，无字符串拼接；未新增任何第三方依赖，仅标准库 + 现有 psycopg2；\n"
        "- 编码探测逻辑原样保留（GB18030/UTF-8-BOM 均覆盖测试）；日志不含手机号等敏感字段；\n"
        "- 建表走 dbtool migrate --lock；批量导入前后自动开关维护模式；峰值连接数 1（上限 5）；\n"
        "- cron 定 04:45，避开 02:00-04:00 备份窗口；测试仅打本地/staging，conftest 守卫拦截 prod DSN。\n"
        "上线顺序建议：先跑迁移（带 --lock），再切 cron 入口，观察一周后删除旧 importer.py。"
    )),
]

CASE = Case(
    case_id="c3",
    title="遗留 CSV 数据管道重构（约束密集散布）",
    turns=TURNS,
    segments=[
        Segment("需求梳理与现状调研", 0, 8),
        Segment("重构方案设计", 9, 16),
        Segment("实现重构", 17, 27),
        Segment("测试与修复", 28, 35),
    ],
    constraints=[
        # a: 用户明示约束
        GoldConstraint(0, "重构后的代码必须保持对 Python 3.10 的兼容"),
        GoldConstraint(4, "不要修改 legacy/ 目录下的任何文件"),
        GoldConstraint(10, "所有 SQL 必须使用参数化查询"),
        GoldConstraint(12, "这次重构禁止引入新的第三方依赖"),
        GoldConstraint(20, "务必保留原有的 CSV 编码探测逻辑"),
        GoldConstraint(24, "日志里绝对不能打印客户手机号"),
        # b: 工具输出中的禁令/告警
        GoldConstraint(14, "WARNING: schema v2 requires a migration lock, never run migrations without --lock"),
        GoldConstraint(22, "ERROR: replica set must be in maintenance mode before bulk import"),
        GoldConstraint(29, "refusing DSN containing 'prod'; this suite must only ever run against local/staging databases"),
        # c: 隐蔽约束（无明显祈使关键词，但语义上是硬约束）
        GoldConstraint(8, "财务那边的报表脚本直接 select 这张表，字段名一变他们就崩了"),
        GoldConstraint(16, "运维只给我们这套服务开了 5 个数据库连接，超了会直接被防火墙掐掉"),
        GoldConstraint(28, "凌晨两点到四点是备份窗口，那个点库基本写不进东西"),
    ],
    backtracks=[],
)
