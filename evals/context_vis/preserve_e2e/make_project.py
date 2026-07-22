"""Generate the scratch project the end-to-end session works on.

Realistic Python source rather than filler: the agent genuinely reads it, and
the volume is what drives the context past the compaction threshold.
"""
import random
import sys
from pathlib import Path

root = Path(sys.argv[1])
(root / "logpipe").mkdir(parents=True, exist_ok=True)
(root / "data").mkdir(parents=True, exist_ok=True)
random.seed(7)

(root / "README.md").write_text('''# logpipe

Batch ingestion and analysis for application logs.

## Layout
- `logpipe/ingest.py`  — reads raw log files, normalises records
- `logpipe/parser.py`  — line-format parsers per log source
- `logpipe/store.py`   — SQLite persistence
- `logpipe/report.py`  — aggregation and report rendering
- `schema.sql`         — table definitions (legacy, shared with the billing team)
- `data/app-2026-07.log` — a sample month of production logs

## Running
    python -m logpipe.ingest --src data/app-2026-07.log --db logs.db
    python -m logpipe.report --db logs.db --out report.txt
''', encoding="utf-8")

(root / "schema.sql").write_text('''-- Shared with the billing team's nightly reconciliation job.
CREATE TABLE IF NOT EXISTS log_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    level        TEXT    NOT NULL,
    user_id      INTEGER,
    phone        TEXT,
    message      TEXT    NOT NULL,
    latency_ms   INTEGER,
    status_code  INTEGER
);
CREATE INDEX IF NOT EXISTS log_records_ts_idx     ON log_records(ts);
CREATE INDEX IF NOT EXISTS log_records_source_idx ON log_records(source, ts);
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id     TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    src_path   TEXT NOT NULL,
    row_count  INTEGER NOT NULL DEFAULT 0
);
''', encoding="utf-8")


def padded_module(name: str, header: str, funcs: int) -> str:
    """Build a plausible module of a few hundred lines."""
    out = [header, ""]
    for i in range(funcs):
        out.append(f'''
def {name}_step_{i:02d}(records, *, strict: bool = False):
    """Stage {i} of the {name} pipeline.

    Returns the records that passed this stage. When ``strict`` is set, a
    malformed record raises instead of being dropped, which the nightly job
    relies on to fail loudly rather than silently shrinking a batch.
    """
    kept = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            if strict:
                raise TypeError(f"record {{index}} is not a mapping: {{record!r}}")
            continue
        value = record.get("{name}_field_{i:02d}")
        if value is None and strict:
            raise ValueError(f"record {{index}} missing {name}_field_{i:02d}")
        if value is None:
            continue
        normalised = str(value).strip()
        if not normalised:
            continue
        record["{name}_field_{i:02d}"] = normalised
        kept.append(record)
    return kept
''')
    return "\n".join(out)


(root / "logpipe" / "__init__.py").write_text('__version__ = "0.4.2"\n', encoding="utf-8")

(root / "logpipe" / "ingest.py").write_text(padded_module(
    "ingest",
    '''"""Raw log ingestion.

Reads a log file, hands each line to the right parser, and writes normalised
records to the store in batches.
"""
import argparse
import logging
import os
import sqlite3

from .parser import parse_line
from .store import LogStore

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
API_KEY = os.environ.get("LOGPIPE_API_KEY", "")


def ingest_file(src_path, db_path):
    store = LogStore(db_path)
    batch = []
    total = 0
    with open(src_path, "r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            record = parse_line(line)
            if record is None:
                logger.warning("unparseable line %d: %s", line_no, line.rstrip())
                continue
            batch.append(record)
            if len(batch) >= BATCH_SIZE:
                total += store.write_batch(batch)
                batch.clear()
    if batch:
        total += store.write_batch(batch)
    logger.info("ingested %d records from %s", total, src_path)
    return total
''', 22), encoding="utf-8")

(root / "logpipe" / "parser.py").write_text(padded_module(
    "parser",
    '''"""Line-format parsers.

Each log source writes a slightly different line format; parse_line sniffs the
prefix and dispatches. Unknown formats return None so the caller can log and
skip rather than aborting a whole batch.
"""
import re

APP_RE = re.compile(
    r"^(?P<ts>\\S+) \\[(?P<level>[A-Z]+)\\] (?P<source>[\\w.-]+): (?P<message>.*)$"
)
ACCESS_RE = re.compile(
    r"^(?P<ts>\\S+) (?P<source>[\\w.-]+) (?P<status_code>\\d{3}) "
    r"(?P<latency_ms>\\d+)ms user=(?P<user_id>\\d+) phone=(?P<phone>[\\d+]*) (?P<message>.*)$"
)


def parse_line(line):
    line = line.rstrip("\\n")
    if not line.strip():
        return None
    match = ACCESS_RE.match(line)
    if match:
        record = match.groupdict()
        record["level"] = "INFO"
        record["status_code"] = int(record["status_code"])
        record["latency_ms"] = int(record["latency_ms"])
        record["user_id"] = int(record["user_id"])
        return record
    match = APP_RE.match(line)
    if match:
        record = match.groupdict()
        record.setdefault("phone", None)
        return record
    return None
''', 20), encoding="utf-8")

(root / "logpipe" / "store.py").write_text(padded_module(
    "store",
    '''"""SQLite persistence for normalised log records."""
import logging
import sqlite3

logger = logging.getLogger(__name__)

COLUMNS = ("ts", "source", "level", "user_id", "phone", "message", "latency_ms", "status_code")


class LogStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")

    def write_batch(self, records):
        rows = [tuple(r.get(c) for c in COLUMNS) for r in records]
        placeholders = ",".join("?" for _ in COLUMNS)
        with self.conn:
            self.conn.executemany(
                f"INSERT INTO log_records ({','.join(COLUMNS)}) VALUES ({placeholders})",
                rows,
            )
        logger.debug("wrote batch of %d records", len(rows))
        return len(rows)
''', 18), encoding="utf-8")

(root / "logpipe" / "report.py").write_text(padded_module(
    "report",
    '''"""Aggregation and report rendering.

The billing team's reconciliation job reads the output of render_daily by
column position, so the column order here is load-bearing.
"""
import argparse
import sqlite3

DAILY_SQL = """
SELECT date(ts) AS day, source, count(*) AS n,
       avg(latency_ms) AS avg_latency, sum(status_code >= 500) AS errors
FROM log_records GROUP BY day, source ORDER BY day, source
"""


def render_daily(conn):
    rows = conn.execute(DAILY_SQL).fetchall()
    lines = ["day\\tsource\\tcount\\tavg_latency_ms\\terrors"]
    for day, source, n, avg_latency, errors in rows:
        lines.append(f"{day}\\t{source}\\t{n}\\t{avg_latency:.1f}\\t{errors}")
    return "\\n".join(lines)
''', 16), encoding="utf-8")

sources = ["api.orders", "api.users", "worker.billing", "web.frontend", "auth.session"]
levels = ["INFO"] * 12 + ["WARN"] * 3 + ["ERROR"]
lines = []
for day in range(1, 29):
    for n in range(random.randint(28, 46)):
        ts = f"2026-07-{day:02d}T{random.randint(0,23):02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}+08:00"
        source = random.choice(sources)
        if random.random() < 0.55:
            lines.append(
                f"{ts} {source} {random.choice([200]*14+[201,404,500,503])} "
                f"{random.randint(4, 2400)}ms user={random.randint(10000, 99999)} "
                f"phone=1{random.randint(3000000000, 9999999999)} "
                f"{random.choice(['GET /v1/orders','POST /v1/users','GET /v1/invoices','POST /v1/session'])}"
            )
        else:
            lines.append(
                f"{ts} [{random.choice(levels)}] {source}: "
                f"{random.choice(['batch flushed', 'retry scheduled', 'cache miss', 'connection reset by peer', 'slow query detected'])} "
                f"(took {random.randint(2, 3100)}ms)"
            )
(root / "data" / "app-2026-07.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
print(f"project at {root}")
for p in sorted(root.rglob("*")):
    if p.is_file():
        print(f"  {p.relative_to(root)}  {p.stat().st_size:>7,}B")
print(f"total {total:,}B  (~{total // 4:,} tokens if fully read)")
