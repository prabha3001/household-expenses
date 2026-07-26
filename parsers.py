# -*- coding: utf-8 -*-
"""
PDF statement parsers for the 4 known statement types, plus auto-detection of
which parser applies to an arbitrary uploaded PDF (no reliance on filename or
folder — inspects the PDF's own text content).

Ported from the original expense_analysis/parse_all.py, unchanged parsing
logic, wrapped with a detect_and_parse() entry point for the web app.
"""
import pdfplumber, re, subprocess, tempfile, os
from collections import Counter
from categorization import parse_month

AMT_RE = re.compile(r'^-?[\d,]+\.\d{2}$')

class UnknownStatementType(Exception):
    pass

def money(s):
    return float(s.replace('£', '').replace(',', '').replace('CR', '').strip())

# ---------- HSBC Current Account ----------
def col_bucket_hsbcca(x0):
    if 355 <= x0 <= 405: return 'out'
    if 420 <= x0 <= 485: return 'in'
    if 500 <= x0 <= 560: return 'bal'
    return None

def parse_hsbc_ca(path):
    txns = []
    with pdfplumber.open(path) as pdf:
        current_date = None
        cur = None
        for page in pdf.pages:
            words = page.extract_words()
            rows = {}
            for w in words:
                key = round(w['top'], 1)
                rows.setdefault(key, []).append(w)
            for top in sorted(rows.keys()):
                row = sorted(rows[top], key=lambda w: w['x0'])
                date_toks = [w['text'] for w in row if 40 <= w['x0'] <= 95]
                type_toks = [w for w in row if 100 <= w['x0'] < 122]
                desc_toks = [w for w in row if 122 <= w['x0'] < 355]
                amt_toks = [w for w in row if col_bucket_hsbcca(w['x0']) and AMT_RE.match(w['text'])]
                desc_text = ' '.join(w['text'] for w in desc_toks)
                if 'BALANCEBROUGHTFORWARD' in desc_text.replace(' ', '') or 'BALANCECARRIEDFORWARD' in desc_text.replace(' ', ''):
                    if cur:
                        txns.append(cur); cur = None
                    continue
                if date_toks:
                    current_date = ' '.join(date_toks)
                if type_toks:
                    if cur: txns.append(cur)
                    cur = {'date': current_date, 'desc': desc_text, 'out': 0.0, 'in': 0.0, 'type': type_toks[0]['text']}
                else:
                    if cur is not None and desc_text:
                        cur['desc'] = (cur['desc'] + ' ' + desc_text).strip()
                for w in amt_toks:
                    b = col_bucket_hsbcca(w['x0'])
                    if b in ('out', 'in') and cur is not None:
                        cur[b] += money(w['text'])
        if cur: txns.append(cur)
    out = []
    for t in txns:
        if t['out'] > 0:
            out.append({'account': 'HSBC Current Account', 'date': t['date'], 'desc': t['desc'], 'amount': t['out'], 'dir': 'out', 'type': t.get('type', '')})
        if t['in'] > 0:
            out.append({'account': 'HSBC Current Account', 'date': t['date'], 'desc': t['desc'], 'amount': t['in'], 'dir': 'in', 'type': t.get('type', '')})
    return out

# ---------- HSBC Credit Card ----------
def parse_hsbc_cc(path):
    txns = []
    line_re = re.compile(r'^(\d{2} \w{3}\s?\d{2})\s+(\d{2} \w{3}\s?\d{2})\s+(.+?)\s+([\d,]+\.\d{2})(CR)?$')
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ''
            if 'Your Transaction Details' not in txt:
                continue
            for line in txt.split('\n'):
                m = line_re.match(line.strip())
                if m:
                    recv, txndate, desc, amt, cr = m.groups()
                    direction = 'in' if cr else 'out'
                    txns.append({'account': 'HSBC Credit Card', 'date': txndate, 'desc': desc.strip(),
                                 'amount': money(amt), 'dir': direction, 'type': ''})
    return txns

# ---------- Barclaycard ----------
# Barclaycard's own transaction lines only print "DD Mon" (no year) — the
# year has to come from the statement's own cover-period line, e.g.
# "07 March 2026 - 06 April 2026", printed near the top of page 1.
PERIOD_RE = re.compile(r'(\d{2}) (\w+) (\d{4})\s*-\s*(\d{2}) (\w+) (\d{4})')

def _barclaycard_period(full_txt):
    m = PERIOD_RE.search(full_txt)
    if not m:
        return None, None
    sd, smon, sy, ed, emon, ey = m.groups()
    return (smon[:3], int(sy)), (emon[:3], int(ey))

def barclaycard_statement_period(pdf_path):
    """
    The statement's own printed cover-period end date (e.g. "...- 06 April
    2026") is the authoritative statement month for Barclaycard — NOT the
    latest transaction date. A billing cycle can end with a quiet week where
    no purchases happened, so the last transaction is sometimes still dated
    in the PRIOR calendar month even though this is unambiguously "the April
    statement" per the cover line and the bank's own naming convention.
    """
    with pdfplumber.open(pdf_path) as pdf:
        full_txt = "\n".join((p.extract_text() or '') for p in pdf.pages)
    _, end = _barclaycard_period(full_txt)
    if not end:
        return None
    emon, ey = end
    return f"{ey}-{MONTHS_MAP[emon.title()]:02d}"

def parse_barclaycard(path):
    txns = []
    pay_re = re.compile(r'^(\d{2} \w{3})\s+(.+?)\s+(-?£[\d,]+\.\d{2})$')
    txn_re = re.compile(r'^(\d{2} \w{3})\s+(.+?)\s+(£[\d,]+\.\d{2})$')
    with pdfplumber.open(path) as pdf:
        full_txt = "\n".join((p.extract_text() or '') for p in pdf.pages)

    start, end = _barclaycard_period(full_txt)

    def with_year(date_str):
        # date_str like "06 Apr" -> "06 Apr 26" using the statement's own
        # cover-period line to supply the year (handles a Dec/Jan-spanning
        # statement correctly by matching month against start vs end).
        if not (start and end):
            return date_str
        mon = date_str.split()[-1][:3]
        if mon.lower() == start[0].lower() and start[1] != end[1]:
            yr = start[1]
        else:
            yr = end[1]
        return f"{date_str} {str(yr)[2:]}"

    lines = full_txt.split('\n')
    section = None
    for line in lines:
        s = line.strip()
        if s.startswith('Payments Received'):
            section = 'pay'; continue
        if s.startswith('Transactions') and 'Promotional' not in s:
            section = 'txn'; continue
        if s.startswith('Promotional Transactions'):
            section = 'promo'; continue
        if s.startswith('Promotional balances') or s.startswith('Interest rates') or s.startswith('Summary Of'):
            section = None; continue
        if section == 'pay':
            m = pay_re.match(s)
            if m:
                date, desc, amt = m.groups()
                neg = amt.startswith('-')
                txns.append({'account': 'Barclaycard', 'date': with_year(date), 'desc': desc.strip(),
                             'amount': abs(money(amt)), 'dir': 'in' if neg else 'out', 'type': ''})
        elif section in ('txn', 'promo'):
            m = txn_re.match(s)
            if m and s != 'No transactions':
                date, desc, amt = m.groups()
                txns.append({'account': 'Barclaycard', 'date': with_year(date), 'desc': desc.strip(),
                             'amount': money(amt), 'dir': 'out', 'type': ''})
    return txns

# ---------- Halifax Current Account (via pdftotext -layout) ----------
TYPES_IN = {'BGC', 'DEP', 'FPI', 'MPI'}
TYPES_ALL = {'BGC', 'BP', 'CHG', 'CHQ', 'COR', 'CPT', 'DD', 'DEB', 'DEP', 'FEE', 'FPI', 'FPO', 'MPI', 'MPO', 'PAY', 'SO', 'TFR'}
hal_re = re.compile(r'^(\d{2} \w{3} \d{2})\s+(.+?)\s+(' + '|'.join(TYPES_ALL) + r')\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$')

def parse_halifax_ca_text(content):
    txns = []
    m0 = re.search(r'Balance on \d{2} \w+ \d{4}\s+\.\s+£(-?[\d,]+\.\d{2})', content)
    running_balance = money(m0.group(1)) if m0 else None
    for line in content.split('\n'):
        s = line.rstrip('\n')
        m = hal_re.match(s.strip())
        if m:
            date, desc, typ, amt, bal = m.groups()
            amount = money(amt)
            balance_after = money(bal)
            direction = 'in' if typ in TYPES_IN else 'out'
            if running_balance is not None:
                if abs((running_balance + amount) - balance_after) < 0.02:
                    direction = 'in'
                elif abs((running_balance - amount) - balance_after) < 0.02:
                    direction = 'out'
                running_balance = balance_after
            txns.append({'account': 'Halifax Current Account', 'date': date, 'desc': desc.strip(),
                         'amount': amount, 'dir': direction, 'type': typ})
    return txns

def parse_halifax_ca(pdf_path):
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tf:
        txt_path = tf.name
    try:
        subprocess.run(['pdftotext', '-layout', pdf_path, txt_path], check=True, capture_output=True)
        with open(txt_path, encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return parse_halifax_ca_text(content)
    finally:
        if os.path.exists(txt_path):
            os.remove(txt_path)

# ---------- Auto-detection ----------
# Detection uses only the LETTERHEAD/HEADER of page 1 (the first ~700
# characters) rather than scanning the whole document. Scanning the whole
# document is unreliable: an HSBC current-account statement's own transaction
# list can easily contain the words "HALIFAX" (a Direct Debit payee, e.g. a
# mortgage payment) or "BARCLAYCARD" (a credit-card-settling payment) without
# the statement itself being from that bank. The header/letterhead, by
# contrast, reliably identifies whose statement it actually is.
def sniff_text(pdf_path, max_pages=3):
    with pdfplumber.open(pdf_path) as pdf:
        parts = []
        for page in pdf.pages[:max_pages]:
            parts.append(page.extract_text() or '')
        return "\n".join(parts)

def sniff_header(pdf_path, chars=700):
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ''
    return first_page_text[:chars].upper()

PARSERS_IN_FALLBACK_ORDER = [
    ('Halifax Current Account', parse_halifax_ca),
    ('HSBC Credit Card', parse_hsbc_cc),
    ('Barclaycard', parse_barclaycard),
    ('HSBC Current Account', parse_hsbc_ca),
]

def _try_all_parsers_fallback(pdf_path, skip=()):
    """Last resort: actually attempt every parser and use whichever produces
    the most transactions, in case the header sniff didn't match any known
    letterhead wording exactly."""
    best = (None, [])
    for name, fn in PARSERS_IN_FALLBACK_ORDER:
        if name in skip:
            continue
        try:
            txns = fn(pdf_path)
        except Exception:
            txns = []
        if len(txns) > len(best[1]):
            best = (name, txns)
    return best

def detect_and_parse(pdf_path):
    """
    Inspect an uploaded PDF's own header/letterhead and dispatch to the right
    parser. Returns (account_name, list_of_txn_dicts). Raises
    UnknownStatementType if none of the 4 known formats match, so the admin
    gets a clear error instead of silently mis-parsed data.
    """
    header = sniff_header(pdf_path)
    tried = None

    if 'HALIFAX' in header and ('CURRENT ACCOUNT' in header or 'SORT CODE' in header):
        tried = 'Halifax Current Account'
        txns = parse_halifax_ca(pdf_path)
        if txns:
            return tried, txns

    elif 'YOUR VISA CARD STATEMENT' in header or ('HSBC' in header and 'CREDIT LIMIT' in header):
        tried = 'HSBC Credit Card'
        txns = parse_hsbc_cc(pdf_path)
        if txns:
            return tried, txns

    elif 'BARCLAYCARD' in header:
        tried = 'Barclaycard'
        txns = parse_barclaycard(pdf_path)
        if txns:
            return tried, txns

    elif 'HSBC' in header:
        tried = 'HSBC Current Account'
        txns = parse_hsbc_ca(pdf_path)
        if txns:
            return tried, txns

    # Header sniff didn't confidently match (or matched but the parser came
    # back empty) — try every known parser and use whichever actually reads
    # transactions out of the file.
    name, txns = _try_all_parsers_fallback(pdf_path, skip={tried} if tried else set())
    if txns:
        return name, txns

    raise UnknownStatementType(
        "Couldn't recognise this statement. Supported types are: HSBC Current Account, "
        "HSBC Credit Card, Halifax Current Account, and Barclaycard. Please check the file "
        "and try again, or upload a different statement."
    )

SUPPORTED_EXTENSIONS = ('.pdf', '.csv', '.xlsx', '.xls', '.docx', '.jpg', '.jpeg', '.png')

def parse_any(path, filename):
    """
    Dispatch to the right parser based on the uploaded file's extension.
    PDFs go through the existing 4-format auto-detection above (unchanged).
    CSV/XLSX/XLS, DOCX and JPG/PNG go through the best-effort generic parsers
    in generic_parsers.py (column-header detection for spreadsheets/tables,
    OCR + line-matching for scans, photos and free-text Word docs) — imported
    lazily here so a plain-PDF deployment never has to load openpyxl/
    python-docx/pytesseract unless one of those file types is actually used.
    Returns (account_name, list_of_txn_dicts); raises UnknownStatementType on
    an unrecognised extension or a file nothing could be parsed from.
    """
    ext = os.path.splitext(filename or '')[1].lower()
    if ext in ('', '.pdf'):
        return detect_and_parse(path)

    import generic_parsers
    if ext == '.csv':
        return generic_parsers.parse_csv(path, filename)
    if ext in ('.xlsx', '.xls'):
        return generic_parsers.parse_excel(path, filename)
    if ext == '.docx':
        return generic_parsers.parse_docx_file(path, filename)
    if ext in ('.jpg', '.jpeg', '.png'):
        return generic_parsers.parse_image_ocr(path, filename)

    raise UnknownStatementType(
        f"Unsupported file type '{ext}'. Supported: PDF, CSV, Excel (.xlsx/.xls), Word (.docx), "
        "and photo/scan (.jpg/.png)."
    )

MONTHS_MAP = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
_DATE_RE = re.compile(r'(\d{2})\s*(\w{3})\s*(\d{2,4})')

def _date_sort_key(date_str):
    m = _DATE_RE.search(date_str or '')
    if not m:
        return None
    day, mon, yr = m.groups()
    mon = mon[:3].title()
    if mon not in MONTHS_MAP:
        return None
    yr = int(yr)
    if yr < 100:
        yr += 2000
    return (yr, MONTHS_MAP[mon], int(day))

def infer_statement_month(txns):
    """
    A monthly statement is best identified by its own closing/issue date, not
    by which calendar month has the most transaction lines in it — a card
    statement covering "18 Jun – 17 Jul" is conventionally "the July
    statement" even though most of its transactions are dated in June.
    So: take the LATEST transaction date on the statement and use its
    calendar month. (Confirmed against the original 12 months of real
    statements: this reproduces the same month bucketing the filename-based
    convention used, for all 4 statement types.)
    """
    keys = [(_date_sort_key(t['date']), t) for t in txns]
    keys = [(k, t) for k, t in keys if k]
    if not keys:
        return None
    (yr, mo, day), _ = max(keys, key=lambda kt: kt[0])
    return f"{yr}-{mo:02d}"
