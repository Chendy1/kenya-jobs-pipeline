"""Alerts to Telegram and/or email. Never raises: a broken alert must not break the pipeline.

    python -m src.ops.notify --test
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests
from dotenv import load_dotenv

from src.storage.postgres import get_conn

load_dotenv()
log = logging.getLogger(__name__)
TAGS = {"error": "[FAIL]", "warn": "[WARN]", "info": "[INFO]"}


def _telegram(text: str) -> str:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return "not configured"
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": chat, "text": text[:3900]}, timeout=15)
        return "sent" if resp.ok else f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        return f"failed ({type(exc).__name__})"  # never include the URL: it contains the token


def _email(subject: str, body: str) -> str:
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    if not (host and to and user and password):
        return "not configured"
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, user, to
    message.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, password)
            server.send_message(message)
        return "sent"
    except Exception as exc:
        return f"failed ({type(exc).__name__})"


def _recently_sent(fingerprint: str, hours: int) -> bool:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM ops.alert_log WHERE fingerprint = %s "
                "AND sent_at > now() - make_interval(hours => %s) LIMIT 1", (fingerprint, hours)).fetchone()
        return row is not None
    except Exception:
        return False  # if we cannot tell, send: a duplicate is better than silence


def _remember(fingerprint: str, level: str, subject: str, channels: str) -> None:
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO ops.alert_log (fingerprint, level, subject, channels) "
                         "VALUES (%s, %s, %s, %s)", (fingerprint, level, subject, channels))
    except Exception:
        log.exception("could not record alert")



def notify(subject: str, body: str, level: str = "error",
           dedupe_key: str | None = None, dedupe_hours: int = 12) -> dict:
    tag = TAGS.get(level, "")
    fingerprint = hashlib.sha1(dedupe_key.encode()).hexdigest()[:16] if dedupe_key else None
    if fingerprint and _recently_sent(fingerprint, dedupe_hours):
        log.info("alert suppressed (same problem alerted within %dh): %s", dedupe_hours, subject)
        return {"skipped": "duplicate"}
    result = {"telegram": _telegram(f"{tag} {subject}\n\n{body}"), "email": _email(f"{tag} {subject}", body)}
    sent = [name for name, status in result.items() if status == "sent"]
    if fingerprint and sent:
        _remember(fingerprint, level, subject, ",".join(sent))
    log.log(logging.ERROR if level == "error" else logging.WARNING,
            "ALERT %s | %s | delivery: %s", subject, body.replace("\n", " | "), result)
    return result

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="send a test alert to every configured channel")
    args = ap.parse_args()
    if not args.test:
        ap.error("use --test")
    print(notify("Kenya jobs pipeline: test alert", "If you can read this, alerting works.", level="info"))