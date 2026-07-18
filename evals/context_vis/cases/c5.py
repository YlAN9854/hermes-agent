"""Case c5: combined realistic scenario — PDF invoice parser CLI.

Topic switches, one abandoned-then-revisited library choice (pdfplumber ->
pymupdf -> back to pdfplumber + OCR fallback), and scattered constraints.
Mostly English with occasional Chinese from the user.
"""
from evals.context_vis.case_schema import Case, T, Segment, GoldConstraint, Backtrack

TURNS = [
    # ---- Project scaffolding & requirements ----
    T("user", """I want to build a small CLI tool called `invoiceparse` that takes a PDF invoice
and emits structured JSON: vendor name, line items (description, qty, unit price,
amount), subtotal, tax, and grand total. It will run inside our finance team's
internal environment, so one hard requirement up front: the tool must never send invoice data over the network.
Everything has to work fully offline — no cloud OCR APIs, no telemetry, nothing.
Can you start with the project skeleton? Python, argparse is fine, no click."""),
    T("assistant", """Good, an offline-only constraint actually simplifies the design space — we'll rule
out any hosted extraction APIs from the start and stick to local libraries.

Proposed layout:

    invoiceparse/
      pyproject.toml
      src/invoiceparse/
        __init__.py
        cli.py        # argparse entry point
        extract.py    # PDF -> raw text/tables
        parse.py      # raw text -> structured fields
        models.py     # dataclasses for Invoice, LineItem
      tests/
        test_parse.py

`cli.py` gets subcommand-free usage for now: `invoiceparse INPUT.pdf -o OUT_DIR`.
Shall I scaffold this with a stub extractor that just echoes page count?"""),
    T("user", """Yes, scaffold it. Use Python 3.11, src layout exactly as you proposed.
For the models use dataclasses, and keep `extract.py` and `parse.py` strictly
separated — I want to be able to swap the extraction backend later without
touching the parsing logic. That separation is deliberate."""),
    T("assistant", """Scaffolding now. The extract/parse boundary will be a single function contract:

    def extract_document(path: Path) -> RawDocument

where `RawDocument` holds per-page text plus any tables found. `parse.py` only
ever sees a `RawDocument`, never a PDF path, so swapping backends later is a
one-file change. Creating the tree and stub files."""),
    T("tool", """$ mkdir -p src/invoiceparse tests && tree .
.
├── pyproject.toml
├── src
│   └── invoiceparse
│       ├── __init__.py
│       ├── cli.py
│       ├── extract.py
│       ├── models.py
│       └── parse.py
└── tests
    └── test_parse.py

3 directories, 7 files""", tool_name="Bash"),
    T("tool", """$ python -m invoiceparse --help
usage: invoiceparse [-h] [-o OUT_DIR] [--pretty] [-v] input

Parse a PDF invoice into structured JSON.

positional arguments:
  input                 path to the input PDF invoice

options:
  -h, --help            show this help message and exit
  -o OUT_DIR, --out-dir OUT_DIR
                        directory to write JSON output (default: ./out)
  --pretty              indent the JSON output
  -v, --verbose         enable debug logging

$ python -m invoiceparse samples/acme_2026_001.pdf
{"input": "samples/acme_2026_001.pdf", "pages": 2, "status": "stub"}""", tool_name="Bash"),
    T("assistant", """Skeleton is up and the argparse wiring works — the stub reports page count via a
placeholder. `models.py` has `Invoice` and `LineItem` dataclasses, and `cli.py`
resolves the output directory but doesn't write anything yet.

Next decisions: (1) which extraction library to use in `extract.py`, and
(2) how amounts should be represented in the output JSON. Any preference on
the second before I pick number types?"""),
    T("user", """关于金额有一个硬性要求：输出 JSON 的金额字段必须用字符串，不要用浮点数。
财务系统那边用 0.01 精度对账，浮点数会出问题。内部计算你可以用 Decimal，
但序列化的时候一律转成字符串，比如 "1234.50"。
Also, for now just support a single input file; batch directory mode can come later."""),
    T("assistant", """Understood — amounts as strings in the JSON, `Decimal` internally, never float.
I'll add a custom JSON encoder that serializes `Decimal` as `str(d.quantize(Decimal("0.01")))`
so every amount lands as e.g. "1234.50", and a unit test asserting no float ever
appears in the money fields. Single-file mode only for now; the argparse `input`
stays a single positional argument and I'll leave a TODO for batch mode."""),

    # ---- PDF text extraction with pdfplumber ----
    T("user", """OK, extraction time. I've used pdfplumber before and liked its table support.
Let's implement `extract_document` with pdfplumber first. I dropped a few real
(anonymized) samples into samples/: two clean digital invoices, one scanned one,
and one where the vendor rotated the page 90 degrees for some reason."""),
    T("assistant", """pdfplumber it is — its `page.extract_tables()` is genuinely good for line-item
grids. Implementing `extract.py`:

- open with `pdfplumber.open(path)`
- per page: `page.extract_text(layout=True)` into `RawDocument.pages`
- per page: `page.extract_tables()` into `RawDocument.tables`

Installing and running against the clean samples first, then the nasty ones."""),
    T("tool", """$ pip install pdfplumber
Collecting pdfplumber
  Downloading pdfplumber-0.11.6-py3-none-any.whl (60 kB)
Collecting pdfminer.six==20250506 (from pdfplumber)
  Downloading pdfminer_six-20250506-py3-none-any.whl (5.6 MB)
Collecting Pillow>=9.1 (from pdfplumber)
  Using cached pillow-11.2.1-cp311-cp311-manylinux_2_28_x86_64.whl (4.6 MB)
Collecting pypdfium2>=4.18.0 (from pdfplumber)
  Downloading pypdfium2-4.30.1-py3-none-manylinux_2_17_x86_64.whl (2.9 MB)
Installing collected packages: pypdfium2, Pillow, pdfminer.six, pdfplumber
Successfully installed Pillow-11.2.1 pdfminer.six-20250506 pdfplumber-0.11.6 pypdfium2-4.30.1""", tool_name="Bash"),
    T("tool", """$ python -m invoiceparse.extract samples/acme_2026_001.pdf --dump-text
--- page 1 ---
ACME Industrial Supplies Ltd.
Invoice No: INV-2026-0114        Date: 2026-06-30
Bill To: Northwind Logistics GmbH

Description                     Qty    Unit Price      Amount
Steel brackets M8 (box 100)      12       45.00        540.00
Anchor bolts 10mm (box 50)        8       32.50        260.00
Delivery & handling               1       40.00         40.00

                               Subtotal:              840.00
                               VAT (19%):             159.60
                               Total:                 999.60

--- tables: 1 found on page 1, 4 rows x 4 cols ---""", tool_name="Bash"),
    T("assistant", """Clean digital invoices extract beautifully — the text layout is preserved well
enough that the totals block is trivially findable, and the line-item table came
out as a proper 4x4 grid with headers intact. Same result on the second clean
sample. Now let's see how it behaves on the scanned and the rotated ones, which
is where text-layer extractors usually suffer."""),
    T("user", "Run it on scanned_003.pdf and rotated_007.pdf. I'm braced for the worst."),
    T("tool", """$ python -m invoiceparse.extract samples/scanned_003.pdf --dump-text
--- page 1 ---

--- page 2 ---

--- tables: 0 found ---
WARNING: extract_text() returned empty string for all pages;
this PDF appears to contain only raster images (no text layer).""", tool_name="Bash"),
    T("tool", """$ python -m invoiceparse.extract samples/rotated_007.pdf --dump-text
--- page 1 ---
I n v o
i c e
N
o :
7 0 0
2
- 6 2 0 2
铝 型 材   6 0 6 3
lat oT
00.5 12,3
段 落 错 位
Q t y 4 2   e c i r P   t i n U
--- tables: 1 found on page 1, 11 rows x 1 cols (all cells single characters or reversed fragments) ---""", tool_name="Bash"),
    T("assistant", """As feared, two distinct failure modes:

1. **scanned_003.pdf** — no text layer at all, so pdfplumber returns empty
   strings. Nothing pdfplumber-side can fix this; it's not an OCR engine.
2. **rotated_007.pdf** — the text layer exists but the glyph coordinates are in
   the rotated frame, so extraction produces character-by-character garbage,
   reversed fragments ("lat oT" is "Total" backwards), and a useless 11x1 table.

My conclusion: pdfplumber alone can't handle the scanned and rotated invoices in
your sample set. We either pre-process these PDFs or use a different extraction
library that handles page rotation natively. Want to explore alternatives?"""),
    T("user", """Yeah, agreed — this output is unusable for those two. A colleague keeps
recommending PyMuPDF (fitz), says it respects page rotation and is much faster.
Let's try another approach with that. What do you think before we commit?"""),
    T("assistant", """PyMuPDF is a reasonable candidate: it reads the page `/Rotate` entry and returns
text in reading order, so rotated_007 should come out clean. It's also 5-10x
faster than pdfminer-based stacks. Two caveats worth flagging now: its table
extraction (`page.find_tables()`) is newer and historically weaker than
pdfplumber's, and note it won't magically fix scanned_003 either — no text
layer is no text layer regardless of library. Worth a spike though; the
extract/parse separation you insisted on means this is a one-file swap."""),

    # ---- Switch to pymupdf ----
    T("user", """好，那就先试 PyMuPDF。把 extract.py 换成 fitz 的实现，跑一遍全部样本。
Keep the pdfplumber version around in git history in case we need it."""),
    T("assistant", """Switching the backend. New `extract.py`:

- `doc = fitz.open(path)`
- per page: `page.get_text("text", sort=True)` — `sort=True` gives reading order
  and fitz applies the page rotation matrix before emitting coordinates
- tables via `page.find_tables()` -> `tab.extract()`

The `RawDocument` contract is unchanged, so `parse.py` and the CLI don't move.
Committing the pdfplumber version first so it stays recoverable, then installing."""),
    T("tool", """$ git add -A && git commit -m "extract: pdfplumber backend (works on digital, fails scanned/rotated)"
[main 4c1f2ab] extract: pdfplumber backend (works on digital, fails scanned/rotated)
 3 files changed, 118 insertions(+)
$ pip install pymupdf
Collecting pymupdf
  Downloading pymupdf-1.25.5-cp39-abi3-manylinux2014_x86_64.whl (20.0 MB)
Installing collected packages: pymupdf
Successfully installed pymupdf-1.25.5""", tool_name="Bash"),
    T("tool", """$ python -m invoiceparse.extract samples/rotated_007.pdf --dump-text
--- page 1 ---
深圳市恒力金属制品有限公司
Invoice No: 2026-007          Date: 2026-05-18
Description          Qty   Unit Price   Amount
铝型材 6063 (米)      420       6.80     2,856.00
不锈钢板 304 (张)      15      23.90       358.50
运费                    1       0.60         0.60
Subtotal:  3,215.10
Total:     3,215.10

--- tables: find_tables() found 1 table, 4 rows x 4 cols ---""", tool_name="Bash"),
    T("assistant", """Big improvement on the rotated sample — fitz applied the rotation matrix and the
text now reads correctly, Chinese vendor name and all. "Total: 3,215.10" is
finally a parseable line instead of "lat oT". The table also came out 4x4.

Let me now stress the table path on the clean multi-column invoices, since
that's where I expect find_tables() to be shakier than pdfplumber, and re-check
the scanned file for completeness."""),
    T("tool", """$ python -m invoiceparse.extract samples/acme_2026_001.pdf --dump-tables
--- page 1: find_tables() found 2 tables ---
table 0: 3 rows x 6 cols
  ['Description', None, 'Qty', 'Unit', 'Price', 'Amount']
  ['Steel brackets M8 (box', '100)', '12', '45.00', None, '540.00']
  ['Anchor bolts 10mm (box 50) 8', None, None, '32.50', '260.00', None]
table 1: 1 rows x 2 cols
  ['Delivery & handling 1 40.00', '40.00']

$ python -m invoiceparse.extract samples/scanned_003.pdf --dump-text
--- page 1 ---
--- page 2 ---
(no text extracted; pages contain only images)""", tool_name="Bash"),
    T("user", """Ouch, those tables are a mess — merged cells, columns split in the wrong place,
and it didn't even help with the scanned one. And a bigger problem: 我刚查了一下
PyMuPDF 的许可证，是 AGPL-3.0。我们这个工具以后可能会打包给外部合作的会计师
事务所用，法务肯定不会批 AGPL，商业授权又要花钱。这点你怎么看？"""),
    T("assistant", """The licensing concern is real and probably decisive. PyMuPDF (and the underlying
MuPDF) are AGPL-3.0: fine for purely internal use, but the moment you distribute
the tool to the external accounting firms, AGPL obligations attach, and Artifex's
commercial license is the only way out — that's an ongoing cost and a legal
review you'd rather avoid. pdfplumber's stack (pdfminer.six, MIT) has no such
problem.

Combined with what we just saw — find_tables() mangling exactly the line-item
grids we care most about, and zero help on scanned input — the case for staying
on PyMuPDF is weak. Its only real win was rotation handling."""),
    T("tool", """$ python scripts/compare_backends.py samples/
backend        clean_001  clean_002  scanned_003  rotated_007
pdfplumber     text OK    text OK    EMPTY        GARBLED
               table 4x4  table 5x4  no tables    junk 11x1
pymupdf        text OK    text OK    EMPTY        text OK
               2 broken   3 broken   no tables    table 4x4
               tables     tables

license:  pdfplumber=MIT  pymupdf=AGPL-3.0
timing:   pdfplumber 1.84s total, pymupdf 0.31s total""", tool_name="Bash"),
    T("assistant", """The comparison makes it stark. PyMuPDF wins on speed and on the one rotated
file; pdfplumber wins on every table, and neither touches the scanned file.
Given that line-item tables are the core of your output schema and the AGPL
issue blocks external distribution, my recommendation is to abandon the PyMuPDF
backend. The rotation problem is solvable another way: rasterize the rotated or
scanned page and OCR it locally. Your call on direction."""),

    # ---- Return to pdfplumber + hybrid OCR approach ----
    T("user", """Decision made: let's go back to the pdfplumber implementation from earlier —
the one you committed before the fitz experiment — and drop pymupdf entirely,
including from the dependency list. For scanned pages, add a local OCR fallback
with pytesseract, used only when pdfplumber finds no text layer. Two rules:
always keep the original PDF untouched — write outputs to a separate directory,
and the OCR must run fully locally, consistent with the no-network rule."""),
    T("assistant", """Reverting to the pdfplumber backend from commit 4c1f2ab and layering the hybrid
on top:

1. `extract_document` tries pdfplumber first (text + tables), as before.
2. Per page, if `extract_text()` yields fewer than 20 non-whitespace chars,
   mark the page `needs_ocr`.
3. For `needs_ocr` pages only: render the page to a 300-dpi PNG in a temp dir
   via pypdfium2 (already a pdfplumber dependency — no new heavyweight dep),
   then run local `pytesseract.image_to_string`.
4. All rendering happens on in-memory copies; the source PDF is opened
   read-only and outputs go exclusively to `--out-dir`. Nothing network-bound.

Restoring the old extractor now and adding the fallback module."""),
    T("tool", """$ pip uninstall -y pymupdf
Found existing installation: pymupdf 1.25.5
Successfully uninstalled pymupdf-1.25.5
$ git checkout 4c1f2ab -- src/invoiceparse/extract.py
$ git status --short
 M src/invoiceparse/extract.py
 M pyproject.toml
?? src/invoiceparse/ocr.py""", tool_name="Bash"),
    T("tool", """$ pip install pytesseract && tesseract --version
Collecting pytesseract
  Downloading pytesseract-0.3.13-py3-none-any.whl (14 kB)
Requirement already satisfied: Pillow>=8.0.0 in ./venv/lib/python3.11/site-packages
Installing collected packages: pytesseract
Successfully installed pytesseract-0.3.13
tesseract 5.3.4
 leptonica-1.84.1
  libgif 5.2.1 : libjpeg 8d (libjpeg-turbo 2.1.5) : libpng 1.6.43 : libtiff 4.5.1
 Found AVX2, AVX, SSE4.1""", tool_name="Bash"),
    T("assistant", """OCR fallback is wired in. `ocr.py` exposes `ocr_page(pdf_path, page_no) -> str`
and `extract.py` calls it only for pages flagged `needs_ocr`, so the two clean
invoices never touch tesseract at all — their path through the code is byte-for-
byte identical to the original pdfplumber implementation we restored. Running
the scanned sample now; it's a Chinese-language invoice, which will be the real
test for tesseract."""),
    T("tool", """$ python -m invoiceparse.extract samples/scanned_003.pdf --dump-text
page 1: no text layer, falling back to OCR (300 dpi render)
WARNING: tesseract requires the chi_sim language pack for Chinese invoices; OCR must not run without it
ERROR: language data 'chi_sim' not found in /usr/share/tesseract-ocr/5/tessdata
Traceback (most recent call last):
  File "src/invoiceparse/ocr.py", line 41, in ocr_page
    return pytesseract.image_to_string(img, lang="chi_sim+eng")
  File "venv/lib/python3.11/site-packages/pytesseract/pytesseract.py", line 486, in image_to_string
    return run_and_get_output(*args)
pytesseract.pytesseract.TesseractError: (1, 'Error opening data file chi_sim.traineddata')""", tool_name="Bash"),
    T("assistant", """That warning is one I emitted deliberately in `ocr.py` before invoking
tesseract, and the hard error confirms it: the chi_sim traineddata isn't
installed. I've made this a fail-fast check — `ocr.py` now probes the tessdata
directory at startup and refuses to run OCR at all if `chi_sim` is missing,
rather than silently producing mojibake from the `eng` model on Chinese
invoices. Installing the language pack and re-running."""),
    T("tool", """$ sudo apt-get install -y tesseract-ocr-chi-sim
Setting up tesseract-ocr-chi-sim (1:4.1.0-2) ...
$ python -m invoiceparse.extract samples/scanned_003.pdf --dump-text
page 1: no text layer, falling back to OCR (300 dpi render)
--- page 1 (OCR) ---
杭州云帆贸易有限公司
发票号码: HZYF-2026-0330    开票日期: 2026-04-02
品名             数量    单价      金额
办公椅 人体工学    10    458.00   4,580.00
升降桌 1.4m        6    899.00   5,394.00
合计金额:  9,974.00
税率: 13%    税额: 1,296.62
价税合计:  11,270.62
--- page 2 (OCR) ---
(盖章页, 无表格内容)""", tool_name="Bash"),
    T("user", """Nice, that's actually readable OCR. What about rotated_007.pdf though? We
dropped fitz, and plain pdfplumber was garbling it. Does it go down the OCR
path too, or do we special-case rotation?"""),
    T("assistant", """Good catch — rotation needs its own branch. The rotated page *has* a text layer,
so the `needs_ocr` heuristic wouldn't trigger. I've extended the detection:

- read `page.rotation` from pdfplumber's page object
- if rotation is 90/180/270, rasterize the page (pypdfium2 applies the rotation
  when rendering) and send it down the same local OCR path
- otherwise use the normal text/table extraction

So: digital upright -> pdfplumber, scanned -> OCR, rotated -> render+OCR.
Running the whole sample set to confirm nothing regressed."""),
    T("tool", """$ python -m invoiceparse.extract samples/ --all --summary
samples/acme_2026_001.pdf   path=pdfplumber   pages=2  tables=1  chars=612   OK
samples/nwtrade_002.pdf     path=pdfplumber   pages=1  tables=1  chars=548   OK
samples/scanned_003.pdf     path=ocr          pages=2  tables=0  chars=387   OK
samples/rotated_007.pdf     path=render+ocr   pages=1  tables=0  chars=298   OK

4/4 documents extracted; 0 empty pages; 0 errors
originals untouched (opened read-only); outputs written to ./out/""", tool_name="Bash"),
    T("assistant", """The hybrid extractor now covers the full sample set: the two digital invoices
go through the exact pdfplumber path we validated at the start (tables intact),
and the scanned and rotated ones come back as OCR text. OCR'd pages don't yield
structured tables, so the parser will need text-based heuristics for those —
which is fine, because that's the next stage anyway. Extraction is done;
pyproject now lists pdfplumber and pytesseract only, no AGPL code anywhere."""),

    # ---- Parsing logic & validation ----
    T("user", """Right, parsing. Targets: vendor name, invoice number, date, line items,
subtotal, tax, total. Mixed English/Chinese labels as you've seen (Total /
合计 / 价税合计, Tax / 税额, etc.). One domain rule for validation:
税率只可能是 3%、6%、9% 或 13%，其他值一律标记为异常，parse 出别的税率
就在 JSON 里加 "anomalies" 字段说明。These are the current Chinese VAT brackets."""),
    T("assistant", """Parser design for `parse.py`:

- **Vendor**: first non-empty line of page 1, unless a table header appears first.
- **Invoice no**: regex `(?:Invoice No|发票号码)[:：]\\s*([A-Z0-9-]+)`.
- **Line items**: prefer the extracted table if present; else a text heuristic
  matching `desc qty unit_price amount` rows where amount ≈ qty × unit_price.
- **Totals block**: labeled-line regexes for Subtotal/合计金额, VAT/税额 with an
  optional rate capture, Total/价税合计.
- **Validation**: tax rate must be one of {3, 6, 9, 13}%; anything else appends
  to `anomalies`. Also checks subtotal + tax == total to the cent, in Decimal.

All amounts flow through a `parse_amount()` normalizer, then out as strings."""),
    T("tool", """$ python -m invoiceparse samples/acme_2026_001.pdf --pretty
{
  "vendor": "ACME Industrial Supplies Ltd.",
  "invoice_no": "INV-2026-0114",
  "date": "2026-06-30",
  "line_items": [
    {"description": "Steel brackets M8 (box 100)", "qty": 12, "unit_price": "45.00", "amount": "540.00"},
    {"description": "Anchor bolts 10mm (box 50)", "qty": 8, "unit_price": "32.50", "amount": "260.00"},
    {"description": "Delivery & handling", "qty": 1, "unit_price": "40.00", "amount": "40.00"}
  ],
  "subtotal": "840.00",
  "tax": {"rate": "19%", "amount": "159.60"},
  "total": "999.60",
  "anomalies": ["tax rate 19% not in allowed set {3%, 6%, 9%, 13%}"]
}""", tool_name="Bash"),
    T("user", """The 19% flag is correct behavior — that's a German invoice, so the anomaly field
doing its job is exactly what I want, not a bug. Now edge cases I know exist in
our real corpus: thousands separators ("3,215.10"), fullwidth digits and the
¥ prefix on Chinese invoices ("¥1,234.50"), discount lines with negative
amounts, and invoices where subtotal+tax genuinely doesn't equal total because
of per-line rounding. Handle those and get tests around all of it."""),
    T("assistant", """Handling each in `parse_amount()` and the validator:

- strip `¥ $ € ,` and fullwidth chars via `unicodedata.normalize("NFKC", s)`
  before Decimal conversion
- accept a leading `-` or parenthesized `(123.45)` as negative for discounts
- totals check: exact match passes; off-by ≤ 0.02 (per-line rounding drift)
  passes but records `"rounding_drift": "0.01"`; larger gaps -> anomaly
- line items with negative amounts are kept, tagged `"kind": "discount"`

Writing `tests/test_parse.py` covering all four cases plus the tax-rate rule
and the strings-not-floats invariant, then running pytest."""),
    T("tool", """$ pytest -q
........F..F............                                          [100%]
=================================== FAILURES ===================================
____________________ test_fullwidth_yen_amount _____________________
    assert parse_amount("￥１，２３４.５０") == Decimal("1234.50")
E   decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]
E   note: NFKC normalized value was '¥1,234.50' — currency symbol not stripped
____________________ test_rounding_drift_flagged ___________________
    assert invoice.anomalies == []
E   AssertionError: assert ['total mismatch: 11270.62 != 11270.63'] == []
E    where drift was 0.01 and should have been tolerated
========================= 2 failed, 22 passed in 1.47s =========================""", tool_name="Bash"),
    T("assistant", """Two genuine bugs, both mine:

1. I stripped currency symbols *before* NFKC normalization, so the fullwidth
   `￥` slipped through as a halfwidth `¥` afterwards. Fix: normalize first,
   then strip the symbol set.
2. The drift tolerance compared `abs(diff) < Decimal("0.02")` but I computed
   `diff` before quantizing, so 0.010000...1 artifacts failed the check.
   Fix: quantize both sides to 0.01 before subtracting.

Patched both; re-running the suite."""),
    T("tool", """$ pytest -q
........................                                          [100%]
24 passed in 1.52s

$ python -m invoiceparse samples/scanned_003.pdf --pretty | head -12
{
  "vendor": "杭州云帆贸易有限公司",
  "invoice_no": "HZYF-2026-0330",
  "date": "2026-04-02",
  "line_items": [
    {"description": "办公椅 人体工学", "qty": 10, "unit_price": "458.00", "amount": "4580.00"},
    {"description": "升降桌 1.4m", "qty": 6, "unit_price": "899.00", "amount": "5394.00"}
  ],
  "subtotal": "9974.00",
  "tax": {"rate": "13%", "amount": "1296.62"},
  "total": "11270.62",""", tool_name="Bash"),
    T("user", """Suite is green and the OCR'd Chinese invoice parses end to end — that's the
whole pipeline working. Last parsing ask: if any of the required fields
(vendor, total) can't be found, don't emit partial JSON silently; exit
non-zero with the missing field named on stderr."""),
    T("assistant", """Done. `parse.py` now raises `MissingFieldError("vendor")` etc. when a required
field can't be recovered, and `cli.py` catches it, prints
`error: could not extract required field 'vendor' from <file>` to stderr, and
exits with code 2 (code 1 stays reserved for I/O errors). The partial data is
still written to `<out_dir>/<stem>.partial.json` so nothing is lost for manual
review, but the exit code makes the failure impossible to miss in scripts.
Added a test with a deliberately vendor-less fixture; 26 tests passing now."""),

    # ---- Packaging & docs ----
    T("user", """Let's finish up: proper packaging with a `pyproject.toml` entry point so
`invoiceparse` works as a command, plus a README. One logging rule for the
release build: never log line-item contents at any log level — log only file names and counts.
Invoices are confidential and log files get shipped to a central collector."""),
    T("assistant", """On the logging rule: I audited the existing `logger.debug` calls and two of them
printed raw extracted text — both now log `"%s: extracted %d chars, %d tables"`
style summaries instead, and I added a test that captures logs at DEBUG during a
full parse and asserts no line-item description or amount string appears in the
records.

Packaging: `pyproject.toml` gets

    [project.scripts]
    invoiceparse = "invoiceparse.cli:main"

with `requires-python = ">=3.11"` and pinned lower bounds on pdfplumber and
pytesseract. Installing editable and smoke-testing the console script."""),
    T("tool", """$ pip install -e .
Obtaining file:///home/dev/invoiceparse
  Installing build dependencies ... done
  Building editable for invoiceparse (pyproject.toml) ... done
Successfully installed invoiceparse-0.1.0

$ invoiceparse --help | head -4
usage: invoiceparse [-h] [-o OUT_DIR] [--pretty] [-v] input

Parse a PDF invoice into structured JSON.

$ invoiceparse --version
invoiceparse 0.1.0""", tool_name="Bash"),
    T("assistant", """Console script installed and answering. README.md drafted with: install
instructions (including the `tesseract-ocr` and `tesseract-ocr-chi-sim` system
packages OCR needs), usage examples, the output JSON schema with a note that
all monetary fields are strings, the allowed tax-rate validation rule, and a
prominent "fully offline" section stating that no invoice data ever leaves the
machine and originals are never modified. Want a final demo run for the README's
example section?"""),
    T("user", """要，跑一个完整的最终演示：对 samples/ 里所有文件依次执行，把其中一个输出的
JSON 也展示出来，我直接截给团队看。"""),
    T("tool", """$ for f in samples/*.pdf; do invoiceparse "$f" -o out/ && echo "OK  $f"; done
OK  samples/acme_2026_001.pdf
OK  samples/nwtrade_002.pdf
OK  samples/scanned_003.pdf
OK  samples/rotated_007.pdf

$ ls out/
acme_2026_001.json  nwtrade_002.json  rotated_007.json  scanned_003.json""", tool_name="Bash"),
    T("tool", """$ cat out/rotated_007.json
{
  "vendor": "深圳市恒力金属制品有限公司",
  "invoice_no": "2026-007",
  "date": "2026-05-18",
  "line_items": [
    {"description": "铝型材 6063 (米)", "qty": 420, "unit_price": "6.80", "amount": "2856.00"},
    {"description": "不锈钢板 304 (张)", "qty": 15, "unit_price": "23.90", "amount": "358.50"},
    {"description": "运费", "qty": 1, "unit_price": "0.60", "amount": "0.60"}
  ],
  "subtotal": "3215.10",
  "tax": {"rate": null, "amount": "0.00"},
  "total": "3215.10",
  "anomalies": ["no tax line found; assumed tax-exempt"]
}""", tool_name="Bash"),
    T("assistant", """All four samples parse cleanly through the installed console script — including
the rotated Chinese invoice that started this whole detour, which now comes out
as clean structured JSON with string amounts and a sensible anomaly note for
its missing tax line. Final state: pdfplumber for digital pages, local
tesseract OCR for scanned or rotated ones, MIT-licensed dependencies only,
26 passing tests, packaged with a console entry point and a README. The tool
is ready to hand to the finance team."""),
]

CASE = Case(
    case_id="c5",
    title="PDF invoice parser CLI — library switch, backtrack, scattered constraints",
    turns=TURNS,
    segments=[
        Segment("Project scaffolding & requirements", 0, 8),
        Segment("PDF text extraction with pdfplumber", 9, 19),
        Segment("Switch to pymupdf", 20, 29),
        Segment("Return to pdfplumber + hybrid OCR approach", 30, 41),
        Segment("Parsing logic & validation", 42, 51),
        Segment("Packaging & docs", 52, 59),
    ],
    constraints=[
        GoldConstraint(0, "the tool must never send invoice data over the network"),
        GoldConstraint(7, "输出 JSON 的金额字段必须用字符串，不要用浮点数"),
        GoldConstraint(30, "always keep the original PDF untouched — write outputs to a separate directory"),
        GoldConstraint(35, "WARNING: tesseract requires the chi_sim language pack for Chinese invoices; OCR must not run without it"),
        GoldConstraint(42, "税率只可能是 3%、6%、9% 或 13%，其他值一律标记为异常"),
        GoldConstraint(52, "never log line-item contents at any log level — log only file names and counts"),
    ],
    backtracks=[
        Backtrack(
            from_segment=3,
            to_segment=1,
            note="returned to pdfplumber after pymupdf licensing and table-quality issues",
        ),
    ],
)
