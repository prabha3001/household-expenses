# -*- coding: utf-8 -*-
import os
import json
import tempfile
import datetime
import hashlib
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, flash, render_template,
    render_template_string, send_file, abort, jsonify
)
from werkzeug.utils import secure_filename

import db
import auth_utils
import parsers
import categorization
import summary

APP_SECRET = os.environ.get('APP_SECRET_KEY', 'dev-insecure-secret-change-me')

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB per statement upload

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'ChangeMe123!')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
ADMIN_NAME = os.environ.get('ADMIN_NAME', 'Admin')


def ensure_admin_bootstrap():
    db.init_db()
    row = db.run("SELECT * FROM users WHERE role='admin' LIMIT 1", fetch='one')
    if not row:
        db.run(
            "INSERT INTO users (username, password_hash, email, name, role, is_active, must_change_password, created_at) "
            "VALUES (?,?,?,?, 'admin', 1, 0, ?)",
            (ADMIN_USERNAME, auth_utils.hash_password(ADMIN_PASSWORD), ADMIN_EMAIL, ADMIN_NAME, db.now_iso()),
            commit=True,
        )
        print(f"[bootstrap] created admin user '{ADMIN_USERNAME}' — change the password after first login.", flush=True)


def mask_email(email):
    if '@' not in email:
        return email
    name, domain = email.split('@', 1)
    if len(name) <= 2:
        masked = name[0] + '*'
    else:
        masked = name[0] + '*' * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"


# ---------------- auth routes ----------------

@app.route('/', methods=['GET'])
def index():
    if session.get('user_id') and session.get('otp_verified'):
        return redirect(url_for('dashboard', period='recent6'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        row = db.run("SELECT * FROM users WHERE username=?", (username,), fetch='one')
        if not row or not auth_utils.check_password(password, row['password_hash']):
            flash("Incorrect username or password.", "error")
            return render_template('login.html', page_title="Sign in")
        if not row['is_active']:
            flash("This account has been disabled. Ask the admin to re-enable it.", "error")
            return render_template('login.html', page_title="Sign in")
        ok, err = auth_utils.create_and_send_otp(row)
        if not ok:
            flash(f"Couldn't send the login code by email ({err}). Contact the admin.", "error")
            return render_template('login.html', page_title="Sign in")
        session['pending_user_id'] = row['id']
        session.pop('otp_verified', None)
        flash("We've emailed you a 6-digit login code.", "success")
        return redirect(url_for('verify_otp'))
    return render_template('login.html', page_title="Sign in")


@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    uid = session.get('pending_user_id')
    if not uid:
        return redirect(url_for('login'))
    row = db.run("SELECT * FROM users WHERE id=?", (uid,), fetch='one')
    if not row:
        session.pop('pending_user_id', None)
        return redirect(url_for('login'))
    if request.method == 'POST':
        code = request.form.get('code', '')
        ok, err = auth_utils.verify_otp(uid, code)
        if ok:
            session.pop('pending_user_id', None)
            session['user_id'] = row['id']
            session['role'] = row['role']
            session['name'] = row['name']
            session['otp_verified'] = True
            return redirect(url_for('dashboard', period='recent6'))
        flash(err, "error")
    return render_template('otp.html', page_title="Enter your code", masked_email=mask_email(row['email']))


@app.route('/resend-otp', methods=['POST'])
def resend_otp():
    uid = session.get('pending_user_id')
    if not uid:
        return redirect(url_for('login'))
    row = db.run("SELECT * FROM users WHERE id=?", (uid,), fetch='one')
    if row:
        ok, err = auth_utils.create_and_send_otp(row)
        flash("A new code has been sent." if ok else f"Couldn't resend the code ({err}).",
              "success" if ok else "error")
    return redirect(url_for('verify_otp'))


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for('login'))


# ---------------- dashboard ----------------

def get_all_months():
    rows = db.run("SELECT DISTINCT month FROM transactions WHERE month IS NOT NULL ORDER BY month", fetch='all')
    return [r['month'] for r in rows]


def load_txns_for_months(months):
    if not months:
        return []
    placeholders = ','.join('?' for _ in months)
    rows = db.run(
        f"SELECT * FROM transactions WHERE month IN ({placeholders})",
        tuple(months), fetch='all',
    )
    out = []
    for r in rows:
        out.append({
            'account': r['account'], 'date': r['date'], 'month': r['month'],
            'desc': r['txn_desc'], 'amount': r['amount'], 'dir': r['dir'], 'type': r['type'],
            'category': r['category'], 'subcategory': r['subcategory'],
            'shopping_subcategory': r['shopping_subcategory'],
            'canonical_merchant': r['canonical_merchant'],
            'is_dd': bool(r['is_dd']), 'is_atm': bool(r['is_atm']), 'is_refund': bool(r['is_refund']),
        })
    return out


def build_dashboard_context(period):
    all_months = get_all_months()
    ranges = summary.pick_report_ranges(all_months)
    if not ranges:
        return None
    if period not in ranges:
        period = 'recent6' if 'recent6' in ranges else list(ranges.keys())[0]
    months = ranges[period]['months']
    txns = load_txns_for_months(months)
    s = summary.build_summary(txns, months)
    labels = ranges[period]['label']
    first, last = summary.month_label(months[0]), summary.month_label(months[-1])
    period_label = f"{first} – {last}" if len(months) > 1 else first
    return {
        'data_json': json.dumps(s),
        'ranges': ranges,
        'period': period,
        'period_label': period_label,
        'page_title': f"Household Expense Dashboard — {labels}",
    }


@app.route('/dashboard/<period>')
@auth_utils.login_required
def dashboard(period):
    user = auth_utils.current_user()
    ctx = build_dashboard_context(period)
    if ctx is None:
        return render_template('base_app.html', user=user, ranges={}, page_title="Household Expenses",
                                active_page=None) + EMPTY_STATE_HTML if False else _empty_state(user)
    return render_template('dashboard.html', user=user, **ctx)


def _empty_state(user):
    body = """
    {% extends "base_app.html" %}
    {% block content %}
    <h1>No statements uploaded yet</h1>
    <div class="card">
      <p>Once the admin uploads the first monthly statement, reports will appear here automatically.</p>
      {% if user.role == 'admin' %}<a href="{{ url_for('upload_page') }}">Go to upload page →</a>{% endif %}
    </div>
    {% endblock %}
    """
    return render_template_string(body, user=user, ranges={}, page_title="Household Expenses", active_page=None)


@app.route('/report/pdf/<period>')
@auth_utils.login_required
def pdf_report(period):
    user = auth_utils.current_user()
    ctx = build_dashboard_context(period)
    if ctx is None:
        flash("No data to export yet.", "error")
        return redirect(url_for('dashboard', period='recent6'))
    html = render_template('dashboard.html', user=user, **ctx)

    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as td:
        html_path = os.path.join(td, 'report.html')
        pdf_path = os.path.join(td, 'report.pdf')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium') \
                if os.path.exists('/opt/pw-browsers/chromium') else p.chromium.launch()
            page = browser.new_page(color_scheme='light')
            page.goto(f'file://{html_path}')
            page.wait_for_timeout(500)
            page.emulate_media(media='print')
            page.pdf(path=pdf_path, format='A4', landscape=True, print_background=True,
                     margin={'top': '10mm', 'bottom': '12mm', 'left': '8mm', 'right': '8mm'})
            browser.close()
        return send_file(pdf_path, as_attachment=True,
                          download_name=f"household_expense_dashboard_{period}.pdf",
                          mimetype='application/pdf')


# ---------------- admin: upload ----------------

def _process_one_statement(f, user):
    """Parse, categorise and store one uploaded statement PDF.

    Returns (category, message) where category is 'success' or 'error',
    so multiple files can each report their own outcome in one batch.
    """
    filename = secure_filename(f.filename)
    raw_bytes = f.read()
    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    with tempfile.TemporaryDirectory() as td:
        tmp_path = os.path.join(td, filename or 'statement.pdf')
        with open(tmp_path, 'wb') as out:
            out.write(raw_bytes)
        try:
            account, txns = parsers.detect_and_parse(tmp_path)
        except parsers.UnknownStatementType as e:
            return "error", f"{filename}: {e}"
        except Exception as e:
            return "error", f"{filename}: couldn't read this PDF ({e})"

        # This exact file was already uploaded for this account — a
        # harmless no-op instead of a second, identical set of
        # transactions.
        dup_file = db.run("SELECT * FROM statements WHERE account=? AND file_hash=?",
                           (account, file_hash), fetch='one')
        if dup_file:
            return "success", (f"{filename}: this exact {account} statement was already uploaded on "
                                f"{dup_file['uploaded_at'][:10]} — nothing new to add.")

        for t in txns:
            categorization.categorize_transaction(t)

        # Barclaycard prints its own cover-period end date, which is a
        # more reliable statement month than the latest transaction date
        # (a billing cycle can end on a quiet week with no purchases).
        # For the other 3 types, the latest transaction date is used.
        period = None
        if account == 'Barclaycard':
            period = parsers.barclaycard_statement_period(tmp_path)
        if not period:
            period = parsers.infer_statement_month(txns)
        if not period:
            return "error", f"{filename}: couldn't work out which month this statement covers — no readable transaction dates found."

        # All transactions on one statement are bucketed into that one
        # statement's own reporting month (not each transaction's own
        # individual date) — matches the original analysis pipeline, and
        # keeps a statement's transactions from splitting across two
        # different monthly reports just because a few dates fall right
        # at the start/end of the billing period.
        for t in txns:
            t['month'] = period

        _, statement_id = db.run(
            "INSERT INTO statements (account, period, filename, file_hash, uploaded_by, uploaded_at, txn_count) "
            "VALUES (?,?,?,?,?,?,?)",
            (account, period, filename, file_hash, user['id'], db.now_iso(), len(txns)),
            commit=True, returning_id=True,
        )

        # One round-trip for every transaction on this statement, instead of
        # one round-trip per transaction — the latter was the main reason a
        # 12-file batch upload could run long enough to hit gunicorn's
        # worker timeout on Render's free instance (each query to the remote
        # Neon database costs real network latency, and a dozen statements
        # can easily add up to several hundred individual transactions).
        rows = [
            (statement_id, t['account'], t['date'], t['month'], t['desc'], t['amount'], t['dir'],
             t.get('type', ''), t['category'], t.get('subcategory', ''), t.get('shopping_subcategory', ''),
             t.get('canonical_merchant', ''), int(t.get('is_dd', False)), int(t.get('is_atm', False)),
             int(t.get('is_refund', False)))
            for t in txns
        ]
        db.run_many(
            "INSERT INTO transactions (statement_id, account, date, month, txn_desc, amount, dir, type, "
            "category, subcategory, shopping_subcategory, canonical_merchant, is_dd, is_atm, is_refund) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows, commit=True,
        )

        return "success", f"{filename}: {account} statement for {summary.month_label(period)} — {len(txns)} transactions added."


@app.route('/admin/upload', methods=['GET', 'POST'])
@auth_utils.admin_required
def upload_page():
    user = auth_utils.current_user()
    if request.method == 'POST':
        files = [f for f in request.files.getlist('file') if f and f.filename]
        if not files:
            flash("Please choose at least one PDF file.", "error")
            return redirect(url_for('upload_page'))

        for f in files:
            category, message = _process_one_statement(f, user)
            flash(message, category)

        return redirect(url_for('upload_page'))

    recent = db.run("SELECT * FROM statements ORDER BY uploaded_at DESC LIMIT 15", fetch='all')
    return render_template('upload.html', user=user, ranges=summary.pick_report_ranges(get_all_months()),
                            active_page='upload', page_title="Upload statement", recent=recent,
                            month_label=summary.month_label)


@app.route('/admin/upload/one', methods=['POST'])
@auth_utils.admin_required
def upload_one():
    """Process a single statement PDF and reply with JSON.

    Called from the upload page's JavaScript, once per selected file, so the
    page can show a real progress bar (X of N files processed) and a
    per-file success/error result as each one finishes, instead of a single
    all-or-nothing form submission. Splitting the batch into one short
    request per file also means one slow or failing PDF can no longer drag
    the rest of the batch down with it or risk tripping a server-side
    request timeout on a large batch.
    """
    user = auth_utils.current_user()
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify(category='error', message='No file received.'), 400
    try:
        category, message = _process_one_statement(f, user)
    except Exception as e:
        # Belt-and-braces: turn any unexpected parsing/database error into a
        # normal JSON error result for this one file, rather than a raw 500
        # that the page's JavaScript would have to guess how to interpret.
        category, message = 'error', f"{secure_filename(f.filename)}: something went wrong processing this file ({e})."
    status_code = 200 if category == 'success' else 422
    return jsonify(category=category, message=message), status_code


# ---------------- self-service: change own password ----------------

@app.route('/account/password', methods=['GET', 'POST'])
@auth_utils.login_required
def change_password():
    user = auth_utils.current_user()
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new1 = request.form.get('new_password', '')
        new2 = request.form.get('new_password2', '')
        if not auth_utils.check_password(current, user['password_hash']):
            flash("Current password is incorrect.", "error")
        elif len(new1) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new1 != new2:
            flash("New passwords don't match.", "error")
        else:
            db.run("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                   (auth_utils.hash_password(new1), user['id']), commit=True)
            flash("Password updated.", "success")
            return redirect(url_for('dashboard', period='recent6'))
    return render_template('change_password.html', user=user, ranges=summary.pick_report_ranges(get_all_months()),
                            active_page=None, page_title="Change password")


# ---------------- admin: family accounts ----------------

@app.route('/admin/users', methods=['GET'])
@auth_utils.admin_required
def users_page():
    user = auth_utils.current_user()
    users = db.run("SELECT * FROM users ORDER BY role DESC, name", fetch='all')
    return render_template('users.html', user=user, ranges=summary.pick_report_ranges(get_all_months()),
                            active_page='users', page_title="Family accounts", users=users)


@app.route('/admin/users/create', methods=['POST'])
@auth_utils.admin_required
def create_user():
    name = request.form.get('name', '').strip()
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    if not (name and username and email and password):
        flash("All fields are required.", "error")
        return redirect(url_for('users_page'))
    existing = db.run("SELECT id FROM users WHERE username=?", (username,), fetch='one')
    if existing:
        flash("That username is already taken.", "error")
        return redirect(url_for('users_page'))
    db.run(
        "INSERT INTO users (username, password_hash, email, name, role, is_active, must_change_password, created_at) "
        "VALUES (?,?,?,?, 'member', 1, 1, ?)",
        (username, auth_utils.hash_password(password), email, name, db.now_iso()),
        commit=True,
    )
    flash(f"Created family account for {name}.", "success")
    return redirect(url_for('users_page'))


@app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@auth_utils.admin_required
def toggle_user(user_id):
    row = db.run("SELECT * FROM users WHERE id=?", (user_id,), fetch='one')
    if not row:
        abort(404)
    if row['role'] == 'admin':
        flash("The admin account can't be disabled.", "error")
        return redirect(url_for('users_page'))
    db.run("UPDATE users SET is_active = ? WHERE id=?", (0 if row['is_active'] else 1, user_id), commit=True)
    flash(f"{'Disabled' if row['is_active'] else 'Enabled'} {row['name']}'s account.", "success")
    return redirect(url_for('users_page'))


ensure_admin_bootstrap()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG') == '1')
