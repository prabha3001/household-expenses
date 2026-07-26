import requests, re, time, sys

BASE = 'http://127.0.0.1:5000'
LOG = '/tmp/flask_server.log'

def get_latest_otp(marker_pos=None):
    with open(LOG) as f:
        content = f.read()
    m = list(re.finditer(r'\[DEV OTP.*?\] (\S+) code=(\d{6})', content))
    if not m:
        print("NO OTP FOUND in log tail:", content[-500:])
        sys.exit(1)
    return m[-1].group(2), len(content)

def log_pos():
    with open(LOG) as f:
        return len(f.read())

s = requests.Session()
pos = log_pos()
r = s.post(f'{BASE}/login', data={'username': 'admin', 'password': 'ChangeMe123!'})
print('login status', r.status_code, r.url)
code, pos = get_latest_otp(pos)
print('otp code', code)
r = s.post(f'{BASE}/verify-otp', data={'code': code})
print('verify status', r.status_code, r.url)
assert '/dashboard' in r.url, "login failed to reach dashboard"

r = s.get(f'{BASE}/dashboard/recent6')
print('dashboard (empty) status', r.status_code, 'len', len(r.text))
assert 'No statements uploaded yet' in r.text

# ---- upload all 4 statement types (one month each first) ----
files_to_test = [
    ('/mnt/user-data/uploads/HSBC_Current Account_Jul2025ToJun2026/2025-07-27_Statement.pdf', 'HSBC CA'),
    ('/mnt/user-data/uploads/HSBC_Credit Card_Jul2025ToJun2026/2025-07-17_Statement.pdf', 'HSBC CC'),
    ('/mnt/user-data/uploads/House Expense Research/Barclay_Credit Card_Jul2025ToJun2026/', 'Barclaycard(dir)'),
    ('/mnt/user-data/uploads/House Expense Research/Halifax_Current Account_Jul2025ToJun2026/', 'Halifax(dir)'),
]

import glob
bc_files = sorted(glob.glob('/mnt/user-data/uploads/House Expense Research/Barclay_Credit Card_Jul2025ToJun2026/*.pdf'))
hf_files = sorted(glob.glob('/mnt/user-data/uploads/House Expense Research/Halifax_Current Account_Jul2025ToJun2026/*.pdf'))
print('barclay sample', bc_files[0])
print('halifax sample', hf_files[0])

upload_targets = [
    '/mnt/user-data/uploads/HSBC_Current Account_Jul2025ToJun2026/2025-07-27_Statement.pdf',
    '/mnt/user-data/uploads/HSBC_Credit Card_Jul2025ToJun2026/2025-07-17_Statement.pdf',
    bc_files[0],
    hf_files[0],
]

for path in upload_targets:
    with open(path, 'rb') as fh:
        r = s.post(f'{BASE}/admin/upload', files={'file': (path.split('/')[-1], fh, 'application/pdf')})
    print('upload', path.split('/')[-1], '->', r.status_code)
    # flash message rendered in the resulting page
    m = re.search(r'<div class="flash (success|error)">(.*?)</div>', r.text, re.S)
    print('   flash:', m.group(1) if m else None, (m.group(2).strip() if m else None))

r = s.get(f'{BASE}/dashboard/all')
print('dashboard(all) status', r.status_code, 'len', len(r.text))
assert 'No statements uploaded yet' not in r.text
# sanity: does it mention the categories?
for cat in ['Groceries', 'Utility Bills', 'Loans', 'Hotel/Food']:
    assert cat in r.text, f"missing {cat}"
print("Category labels present: OK")

# ---- create family member ----
r = s.post(f'{BASE}/admin/users/create', data={
    'name': 'Test Family Member', 'username': 'familytest', 'email': 'family@example.com', 'password': 'FamilyPass123'
})
print('create user status', r.status_code)

# ---- log in as family member, check role gating ----
s2 = requests.Session()
pos2 = log_pos()
r = s2.post(f'{BASE}/login', data={'username': 'familytest', 'password': 'FamilyPass123'})
code2, pos2 = get_latest_otp(pos2)
r = s2.post(f'{BASE}/verify-otp', data={'code': code2})
print('family verify ->', r.status_code, r.url)
assert '/dashboard' in r.url

r = s2.get(f'{BASE}/admin/upload')
print('family GET /admin/upload ->', r.status_code, r.url)
assert '/admin/upload' not in r.url or 'Upload a monthly statement' not in r.text, "member should NOT see upload page"

r = s2.get(f'{BASE}/admin/users')
print('family GET /admin/users ->', r.status_code, r.url)
assert 'Family accounts' not in r.text or '/admin/users' not in r.url, "member should NOT see users page"

print("\nALL CHECKS PASSED")
