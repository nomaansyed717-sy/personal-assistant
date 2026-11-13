"""Deliver one-time sign-in codes by email or SMS.

Providers: Resend or SMTP for email; MSG91 (India, DLT-registered template) or Twilio for SMS.
With no provider configured (development), codes are logged and kept in OUTBOX so the local
app and the tests can read them. Production refuses to fall back to the log.
"""
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
OUTBOX: list[tuple[str, str]] = []  # (address, text), development and tests only


class DeliveryError(Exception):
    pass


def _dev(address: str, text: str) -> None:
    if get_settings().env == "prod":
        raise DeliveryError("no email or SMS provider is configured")
    OUTBOX.append((address, text))
    log.warning("DEV sign-in code for %s: %s", address[-6:], text)


def send_email_code(email: str, code: str) -> None:
    s = get_settings()
    subject = f"{code} is your {s.app_name} sign-in code"
    body = (f"Your {s.app_name} sign-in code is {code}. It expires in 10 minutes.\n\n"
            "If you didn't ask for it, ignore this email. Never share this code with anyone.")
    if s.email_provider == "resend" and s.resend_api_key:
        r = httpx.post("https://api.resend.com/emails", timeout=15,
                       headers={"Authorization": f"Bearer {s.resend_api_key}"},
                       json={"from": s.email_from, "to": [email], "subject": subject, "text": body})
        if r.status_code >= 400:
            log.error("resend failed %s: %s", r.status_code, r.text[:300])
            raise DeliveryError("email could not be sent")
        return
    if s.email_provider == "smtp" and s.smtp_host:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.email_from, email, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            log.error("smtp failed: %s", exc)
            raise DeliveryError("email could not be sent") from exc
        return
    _dev(email, body)


def send_sms_code(phone: str, code: str) -> None:
    s = get_settings()
    text = f"{code} is your {s.app_name} sign-in code. It expires in 10 minutes. Never share it."
    if s.sms_provider == "msg91" and s.msg91_auth_key:
        r = httpx.post("https://control.msg91.com/api/v5/otp", timeout=15,
                       headers={"authkey": s.msg91_auth_key},
                       params={"template_id": s.msg91_template_id, "mobile": phone.lstrip("+"), "otp": code})
        if r.status_code >= 400 or r.json().get("type") == "error":
            log.error("msg91 failed %s: %s", r.status_code, r.text[:300])
            raise DeliveryError("SMS could not be sent")
        return
    if s.sms_provider == "twilio" and s.twilio_account_sid:
        r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json", timeout=15,
                       auth=(s.twilio_account_sid, s.twilio_auth_token),
                       data={"To": phone, "From": s.twilio_from, "Body": text})
        if r.status_code >= 400:
            log.error("twilio failed %s: %s", r.status_code, r.text[:300])
            raise DeliveryError("SMS could not be sent")
        return
    _dev(phone, text)
