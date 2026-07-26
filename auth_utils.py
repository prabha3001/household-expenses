# -*- coding: utf-8 -*-
import os
import secrets
import smtplib
import datetime
from email.mime.text import MIMEText
from functools import wraps
from flask import session, redirect, url_for, flash, request

from werkzeug.security import generate_password_hash, check_password_hash
import db

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')


def hash_password(pw):
    return generate_password_hash(pw)

def check_password(pw, pw_hash):
    return check_password_hash(pw_hash, pw)


def generate_otp():
    return f"{secrets.randbelow(1000000):06d}"


def send_otp_email(to_email, code, name=''):
    subject = "Your household expense dashboard login code"
    body = (
        f"Hi {name or ''},\n\n"
        f"Your one-time login code is: {code}\n"
        f"It expires in {OTP_TTL_MINUTES} minutes.\n\n"
        f"If you didn't try to log in, you can ignore this email.\n"
    )
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        # Dev/test fallback: no email credentials configured, so print the
        # code to the server log instead of failing. Real deployments must
        # set GMAIL_ADDRESS + GMAIL_APP_PASSWORD (see .env.example).
        print(f"[DEV OTP - no email credentials configured] {to_email} code={code}", flush=True)
        return True, None
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = GMAIL_ADDRESS
        msg['To'] = to_email
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, [to_email], msg.as_string())
        return True, None
    except Exception as e:
        print(f"[OTP EMAIL SEND FAILED] {to_email}: {e}", flush=True)
        return False, str(e)


def create_and_send_otp(user_row):
    code = generate_otp()
    code_hash = generate_password_hash(code)
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
    db.run(
        "INSERT INTO otp_codes (user_id, code_hash, expires_at, consumed, attempts, created_at) VALUES (?,?,?,0,0,?)",
        (user_row['id'], code_hash, expires_at, db.now_iso()), commit=True,
    )
    ok, err = send_otp_email(user_row['email'], code, user_row['name'])
    return ok, err


def verify_otp(user_id, submitted_code):
    row = db.run(
        "SELECT * FROM otp_codes WHERE user_id=? AND consumed=0 ORDER BY id DESC LIMIT 1",
        (user_id,), fetch='one',
    )
    if not row:
        return False, "No pending code — request a new one."
    if row['attempts'] >= OTP_MAX_ATTEMPTS:
        return False, "Too many incorrect attempts — request a new code."
    expires_at = datetime.datetime.fromisoformat(row['expires_at'])
    if datetime.datetime.utcnow() > expires_at:
        return False, "Code expired — request a new one."
    db.run("UPDATE otp_codes SET attempts = attempts + 1 WHERE id=?", (row['id'],), commit=True)
    if check_password_hash(row['code_hash'], submitted_code.strip()):
        db.run("UPDATE otp_codes SET consumed=1 WHERE id=?", (row['id'],), commit=True)
        return True, None
    return False, "Incorrect code."


# ---------------- session / role helpers ----------------

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.run("SELECT * FROM users WHERE id=?", (uid,), fetch='one')

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id') or not session.get('otp_verified'):
            flash("Please log in to continue.", "error")
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id') or not session.get('otp_verified'):
            flash("Please log in to continue.", "error")
            return redirect(url_for('login', next=request.path))
        if session.get('role') != 'admin':
            flash("That page is only available to the admin account.", "error")
            return redirect(url_for('dashboard', period='recent6'))
        return view(*args, **kwargs)
    return wrapped
