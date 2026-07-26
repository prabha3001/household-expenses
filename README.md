# Household Expense Dashboard — web app

A small multi-user web app version of the household expense dashboard:
login with username + password + a one-time email code, an admin account
that uploads monthly bank/card statements (auto-detected, auto-categorised),
and family member accounts that can only view and export reports.

## How it works

- **Upload & auto-detect** (`parsers.py`): admin uploads any PDF for the 4
  known statement types (HSBC Current Account, HSBC Credit Card, Halifax
  Current Account, Barclaycard). The app reads the PDF's own letterhead to
  work out which type it is, extracts every transaction, and — for Halifax —
  shells out to `pdftotext -layout` the same way the original analysis did.
- **Categorisation** (`categorization.py`): the exact keyword rules, Direct
  Debit/ATM type-code detection, merchant canonicalisation and refund-netting
  logic from the original analysis, ported unchanged.
- **Duplicate protection**: re-uploading the exact same PDF is a safe no-op
  (detected by a hash of the file itself), so nothing is ever double-counted
  — and nothing is lost either, since two different statements are never
  merged into one just because they cover a similar month.
- **Reports** (`summary.py`): the same aggregations as before (monthly/yearly
  totals, money in vs out, Direct Debits, ATM withdrawals, monthly deep-dive),
  now computed live from the database instead of a static JSON file, across 4
  auto-updating windows: full history, last 12 months, most recent 6 months,
  previous 6 months.
- **Auth** (`auth_utils.py`): password + a 6-digit one-time code emailed via
  your own Gmail account. Sessions are signed cookies (Flask's built-in
  session, no extra dependency).
- **Roles**: `admin` can upload statements and create/disable family
  accounts; `member` can only view and export reports (HTML in the browser,
  or a PDF download of the same dashboard, rendered with Playwright/Chromium
  — same technique used for the PDF reports already shared with you).

This was verified against your real 12 months of statements before being
handed over: every one of the 48 PDFs you'd already provided was re-uploaded
through the app, and the resulting totals (income, spend by category, Direct
Debits, ATM withdrawals, money in/out) match the previously-delivered
dashboards to the penny.

## Running it locally (to try before deploying)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # only needed for the PDF export button
cp .env.example .env                    # then edit .env (see below)
python app.py                           # http://localhost:5000
```

The first time it starts, it creates an admin account from `ADMIN_USERNAME`
/ `ADMIN_PASSWORD` / `ADMIN_EMAIL` in your `.env` (defaults: `admin` /
`ChangeMe123!` — change these before you actually deploy). Log in, then use
"Change password" and "Family accounts" to set things up properly.

If `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` aren't set, the login code is
printed to the server console instead of emailed — handy for trying it out
locally, but you'll want real email sending for actual use (see below).

## Deploying for real: Render (hosting) + Neon (database)

Render's free web service is a great fit for a small app like this, but its
free tier's disk is **not persistent** — it resets on every redeploy. So the
database lives on **Neon** instead (a separate free, persistent Postgres
database) while Render just runs the app itself. Both have genuinely free
tiers with no card required to start.

### 1. Create the free database (Neon)

1. Go to [neon.tech](https://neon.tech) and sign up (free).
2. Create a new project (any name, e.g. "household-expenses").
3. On the project dashboard, open **Connection Details** and copy the
   **connection string** — it looks like
   `postgresql://user:password@ep-xxxx.neon.tech/neondb?sslmode=require`.
   Keep this handy for step 3.

### 2. Get a Gmail App Password (for login codes)

1. On the Gmail account you want login codes sent from, turn on
   **2-Step Verification** (Google Account → Security) if it isn't already.
2. Go to <https://myaccount.google.com/apppasswords>, create a new app
   password (any name, e.g. "household expenses"), and copy the 16-character
   code it gives you.

### 3. Create the free web service (Render)

1. Push this folder to a GitHub repository (Render deploys from a repo).
2. On [render.com](https://render.com), **New → Web Service**, connect that
   repo, and choose:
   - Environment: **Docker** (it will pick up the included `Dockerfile`
     automatically)
   - Instance type: **Free**
3. Under **Environment** add these variables (see `.env.example` for the
   full list with explanations):

   | Key | Value |
   |---|---|
   | `APP_SECRET_KEY` | a random string — generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
   | `ADMIN_USERNAME` | your admin login name |
   | `ADMIN_PASSWORD` | a real password (not the default!) |
   | `ADMIN_EMAIL` | your email (login codes go here for the admin account) |
   | `ADMIN_NAME` | your name |
   | `GMAIL_ADDRESS` | the Gmail address from step 2 |
   | `GMAIL_APP_PASSWORD` | the 16-character app password from step 2 |
   | `DATABASE_URL` | the Neon connection string from step 1 |

4. Click **Create Web Service**. First deploy takes a few minutes (it
   installs Chromium for the PDF export). Render gives you a URL like
   `https://household-expenses.onrender.com` — that's the app.
5. Log in with the admin username/password you set, enter the code emailed
   to `ADMIN_EMAIL`, then go to **Family accounts** to create logins for
   everyone else.

Render's free instance goes to sleep after 15 minutes with no visits and
takes about a minute to wake back up on the next request — normal for the
free tier, not a bug. Since the actual data lives in Neon, that sleep/wake
cycle never risks losing anything.

### A note on the database code path

The app supports both SQLite (default, used above for local testing) and
Postgres (used automatically once `DATABASE_URL` is set) behind one shared
set of queries. The Postgres path is written to the standard `psycopg2` API
and mirrors the SQLite path query-for-query, but this build environment's
own network access is restricted enough that `psycopg2` couldn't be
installed here to actually run it against a live Postgres server — only the
SQLite path got to run end-to-end (against all 48 of your real statements,
matching the previous dashboards exactly, as above).

**Do one smoke test right after your first deploy**: log in, upload one
statement, confirm it shows up on the dashboard. If anything about the
Postgres path misbehaves, it's a quick, well-scoped fix — let me know what
you see and I'll sort it out.

## Security notes

- Change `ADMIN_PASSWORD` and `APP_SECRET_KEY` from the defaults before
  deploying for real.
- Every account (including family members) can change their own password
  from the "Change password" link once logged in.
- The admin account can disable (but not delete) family member accounts at
  any time from **Family accounts**.
- Login codes expire after 10 minutes and allow 5 incorrect attempts before
  you need to request a new one.
- Consider rotating your Render account password if you ever paste it into
  a chat/AI tool, as a general habit — not specific to this app.

## Files

- `app.py` — routes (auth, dashboard, upload, family accounts, PDF export)
- `auth_utils.py` — password hashing, OTP generation/email, session helpers
- `db.py` — SQLite/Postgres data layer + schema
- `parsers.py` — the 4 statement parsers + auto-detection
- `categorization.py` — categorisation rules (ported unchanged)
- `summary.py` — report aggregation (ported, now DB-driven)
- `templates/` — `dashboard.html` (the big interactive report, reused from
  the earlier static version), plus login/OTP/upload/family-accounts pages
- `Dockerfile`, `requirements.txt`, `.env.example` — deployment
- `test_bulk_upload.py`, `test_flow.py`, `test_dashboard_pdf.py` — the
  scripts used to verify this build; safe to delete, or keep as smoke tests
  (point `BASE` at your deployed URL to re-run them there)
