"""c6 — compaction survival: one constraint of each status.

Deliberately small and cheap. Three user constraints are placed so that after
the scripted compaction:
  - the deploy-window rule survives verbatim in a kept turn      -> present
  - the PII rule is restated in the summary in different words   -> reframed
  - the connection-limit rule is dropped and never restated      -> absent

That is the minimum shape exercising all three branches of the survival
matcher, and the shape that would have caught the whole-entry scoring bug.
"""
from ..case_schema import Backtrack, Case, Compaction, GoldConstraint, GoldSurvival, Segment, T

TURNS = [
    T("user",
      "我们要给客服系统做一个导出工单的脚本。先说三条硬性要求：\n"
      "1. 绝对不能在日志里打印客户手机号；\n"
      "2. 运维只给了我们 5 个数据库连接，不能再多开；\n"
      "3. 上线只能在每天凌晨 1 点到 3 点的发布窗口内做。"),
    T("assistant",
      "明白，我先确认数据源。三条要求我记下了：手机号脱敏、连接数上限 5、发布窗口 01:00-03:00。\n"
      "我先看一下工单表的结构。"),
    T("tool",
      "$ psql -c '\\d tickets'\n"
      "                 Table \"public.tickets\"\n"
      "   Column    |            Type             | Nullable\n"
      "-------------+-----------------------------+----------\n"
      " id          | bigint                      | not null\n"
      " customer_id | bigint                      | not null\n"
      " phone       | character varying(20)       |\n"
      " status      | character varying(16)       | not null\n"
      " created_at  | timestamp with time zone    | not null\n"
      "Indexes:\n"
      "    \"tickets_pkey\" PRIMARY KEY, btree (id)\n"
      "    \"tickets_created_at_idx\" btree (created_at)",
      tool_name="bash"),
    T("assistant",
      "表结构清楚了。phone 字段是明文存储的，所以导出和日志两个地方都要做脱敏处理。\n"
      "我打算用游标分页，每批 5000 行，避免一次性把整表读进内存。"),
    T("user",
      "可以。另外导出格式用 CSV，字段顺序按 id, customer_id, status, created_at，不要带 phone 列。"),
    T("assistant",
      "好的，导出列里直接不含 phone。我写第一版 export_tickets.py。"),
    T("tool",
      "$ cat > export_tickets.py <<'EOF'\n"
      "import csv, logging, os, psycopg2\n"
      "logger = logging.getLogger(__name__)\n"
      "BATCH = 5000\n"
      "FIELDS = ['id', 'customer_id', 'status', 'created_at']\n"
      "def export(conn, out_path):\n"
      "    with conn.cursor(name='tickets_cur') as cur, open(out_path, 'w', newline='') as fh:\n"
      "        cur.itersize = BATCH\n"
      "        cur.execute('SELECT id, customer_id, status, created_at FROM tickets ORDER BY id')\n"
      "        writer = csv.writer(fh)\n"
      "        writer.writerow(FIELDS)\n"
      "        for row in cur:\n"
      "            writer.writerow(row)\n"
      "EOF\n"
      "$ python -c 'import ast,sys; ast.parse(open(\"export_tickets.py\").read()); print(\"syntax ok\")'\n"
      "syntax ok",
      tool_name="bash"),
    T("assistant",
      "第一版写好了：服务端游标 + 每批 5000 行，导出列不含 phone，日志里也没有打印任何行内容。"),
    T("user", "跑一下试试，先导 1000 行看看。"),
    T("tool",
      "$ python -m export_tickets --limit 1000 --out /tmp/tickets.csv\n"
      "INFO:export_tickets:opened cursor tickets_cur\n"
      "INFO:export_tickets:wrote 1000 rows to /tmp/tickets.csv\n"
      "$ head -2 /tmp/tickets.csv\n"
      "id,customer_id,status,created_at\n"
      "1,88213,closed,2026-05-02T09:14:33+08:00\n"
      "$ grep -c phone /tmp/tickets.csv\n"
      "0",
      tool_name="bash"),
    T("assistant",
      "导出正常：1000 行写入成功，表头和字段顺序符合要求，文件里没有任何 phone 字段。"),
    T("user", "不错。接下来把它接到定时任务里，每天跑一次全量导出。"),
    T("assistant",
      "我用 cron 来调度。考虑到只能在发布窗口内动线上，我把首次部署安排在窗口内，"
      "但定时任务本身的执行时间可以放在业务低峰。"),
    T("tool",
      "$ crontab -l\n"
      "# m h  dom mon dow   command\n"
      "30 4 * * * /usr/local/bin/python -m export_tickets --out /var/exports/tickets.csv\n"
      "$ systemctl status cron | head -3\n"
      "● cron.service - Regular background program processing daemon\n"
      "     Loaded: loaded (/lib/systemd/system/cron.service; enabled)\n"
      "     Active: active (running)",
      tool_name="bash"),
    T("assistant",
      "定时任务已经加好，每天 04:30 跑一次全量导出，写到 /var/exports/tickets.csv。"),
    T("user", "部署这件事必须守住那个时间窗口。现在把这个脚本的使用说明写一下。"),
    T("assistant",
      "我写一份 README，包含用法、参数、定时任务配置和注意事项。"),
    T("tool",
      "$ cat > README.md <<'EOF'\n"
      "# 工单导出脚本\n"
      "## 用法\n"
      "    python -m export_tickets --out /var/exports/tickets.csv\n"
      "## 参数\n"
      "- `--out`   输出 CSV 路径（必填）\n"
      "- `--limit` 仅导出前 N 行，用于验证\n"
      "## 定时任务\n"
      "    30 4 * * * /usr/local/bin/python -m export_tickets --out /var/exports/tickets.csv\n"
      "EOF\n"
      "$ wc -l README.md\n"
      "10 README.md",
      tool_name="bash"),
    T("assistant",
      "README 写完了，涵盖用法、两个参数和 cron 配置。脚本这部分就算交付了。"),
    T("user", "好，那就这样。上线前你再跟我确认一次。"),
]

CASE = Case(
    case_id="c6",
    title="压缩存活：导出脚本的三条约束在压缩后各自的命运",
    turns=TURNS,
    segments=[
        Segment(name="需求与表结构", start=0, end=3),
        Segment(name="实现导出脚本", start=4, end=10),
        Segment(name="接入定时任务", start=11, end=14),
        Segment(name="文档与收尾", start=15, end=19),
    ],
    constraints=[
        GoldConstraint(turn=0, text="绝对不能在日志里打印客户手机号"),
        GoldConstraint(turn=0, text="运维只给了我们 5 个数据库连接，不能再多开"),
        GoldConstraint(turn=15, text="部署这件事必须守住那个时间窗口"),
    ],
    backtracks=[],
    # Turn 0 (holding constraints 0 and 1) is compacted away; turn 15 survives.
    # The summary restates the PII rule in different words and says nothing at
    # all about the connection limit.
    compaction=Compaction(
        kept_turns=[15, 16, 17, 18, 19],
        summary=(
            "用户要求为客服系统编写工单导出脚本。已完成的工作：确认了 tickets 表结构，"
            "实现了基于服务端游标的分批导出（每批 5000 行），导出的 CSV 不包含 phone 列，"
            "并已验证 1000 行导出结果正确。随后接入了 cron 定时任务，每天 04:30 执行全量导出。\n"
            "过程中用户强调过：任何日志输出都必须对客户的手机号码做脱敏，不得让其出现在日志中。"
        ),
    ),
    survival=[
        GoldSurvival(constraint=0, status="reframed"),  # restated as 手机号码脱敏
        GoldSurvival(constraint=1, status="absent"),    # dropped, never restated
        GoldSurvival(constraint=2, status="present"),   # lives in a kept turn
    ],
)
