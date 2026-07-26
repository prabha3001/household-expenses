import requests, re, glob, json, sys

BASE = 'http://127.0.0.1:5000'
LOG = '/tmp/flask_server.log'

def get_latest_otp():
    with open(LOG) as f:
        content = f.read()
    m = list(re.finditer(r'\[DEV OTP.*?\] (\S+) code=(\d{6})', content))
    return m[-1].group(2)

s = requests.Session()
r = s.post(f'{BASE}/login', data={'username': 'admin', 'password': 'ChangeMe123!'})
code = get_latest_otp()
r = s.post(f'{BASE}/verify-otp', data={'code': code})
assert '/dashboard' in r.url

all_files = []
all_files += sorted(glob.glob('/mnt/user-data/uploads/HSBC_Current Account_Jul2025ToJun2026/*.pdf'))
all_files += sorted(glob.glob('/mnt/user-data/uploads/HSBC_Credit Card_Jul2025ToJun2026/*.pdf'))
all_files += sorted(glob.glob('/mnt/user-data/uploads/House Expense Research/Barclay_Credit Card_Jul2025ToJun2026/*.pdf'))
all_files += sorted(glob.glob('/mnt/user-data/uploads/House Expense Research/Halifax_Current Account_Jul2025ToJun2026/*.pdf'))
print(f"Uploading {len(all_files)} statement files...")

errors = []
for path in all_files:
    with open(path, 'rb') as fh:
        r = s.post(f'{BASE}/admin/upload', files={'file': (path.split('/')[-1], fh, 'application/pdf')})
    m = re.search(r'<div class="flash (success|error)">(.*?)</div>', r.text, re.S)
    status = m.group(1) if m else '?'
    msg = m.group(2).strip() if m else '(no flash found)'
    tag = 'OK ' if status == 'success' else 'ERR'
    print(f"[{tag}] {path.split('/')[-1]:55s} -> {msg}")
    if status != 'success':
        errors.append((path, msg))

print(f"\n{len(all_files)-len(errors)}/{len(all_files)} uploaded successfully")
if errors:
    print("ERRORS:")
    for p, m in errors:
        print(" ", p, '->', m)

r = s.get(f'{BASE}/dashboard/all')
mjson = re.search(r'const DATA = (\{.*?\});', r.text, re.S)
data = json.loads(mjson.group(1))
print("\n=== Aggregate check (should match original static analysis) ===")
print("months:", data['months'])
print("category_totals:", {k: round(v,2) for k,v in data['category_totals'].items()})
print("total_spend:", round(data['total_spend'],2))
print("total_income:", round(data['total_income'],2))
print("total_excluded:", round(data['total_excluded'],2))
print("total_dd:", round(data['total_dd'],2), "n=", data['dd_count'])
print("total_atm:", round(data['total_atm'],2), "n=", data['atm_count'])
print("total_ca_in:", round(data['total_ca_in'],2), "total_ca_out:", round(data['total_ca_out'],2))
