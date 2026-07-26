import requests, re, sys

BASE = 'http://127.0.0.1:5000'
LOG = '/tmp/flask_server.log'

def get_latest_otp():
    with open(LOG) as f:
        content = f.read()
    m = list(re.finditer(r'\[DEV OTP.*?\] (\S+) code=(\d{6})', content))
    return m[-1].group(2)

s = requests.Session()
s.post(f'{BASE}/login', data={'username': 'admin', 'password': 'ChangeMe123!'})
code = get_latest_otp()
r = s.post(f'{BASE}/verify-otp', data={'code': code})
assert '/dashboard' in r.url, r.url

for period in ['all', 'recent6', 'prev6']:
    r = s.get(f'{BASE}/dashboard/{period}')
    print(period, '-> status', r.status_code, 'len', len(r.text),
          'has-error' if 'Traceback' in r.text or r.status_code != 200 else 'OK')

print("\n--- PDF export ---")
r = s.get(f'{BASE}/report/pdf/all', timeout=60)
print('pdf status', r.status_code, 'content-type', r.headers.get('content-type'), 'bytes', len(r.content))
if r.status_code == 200 and r.headers.get('content-type','').startswith('application/pdf'):
    with open('/tmp/test_export.pdf', 'wb') as f:
        f.write(r.content)
    print('saved to /tmp/test_export.pdf')
else:
    print(r.text[:2000])
