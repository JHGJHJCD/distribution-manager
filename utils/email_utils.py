"""שליחת מייל אוטומטית (SMTP) — למשל שליחת רשימת חלוקה למתנדב.

משתמש רק בספריית הסטנדרט של פייתון (smtplib/email) — אין תלות חיצונית
חדשה. הגדרות השליחה (כתובת שולח + סיסמת אפליקציה) נשמרות בטבלת ה-settings
המקומית, כמו כל שאר הגדרות התוכנה.

הערת אבטחה: סיסמת האפליקציה נשמרת כטקסט רגיל במסד הנתונים המקומי (כמו כל
שאר נתוני התוכנה) כדי שהשליחה תוכל לפעול אוטומטית בלי להקליד סיסמה כל פעם.
היא לא יוצאת מהמחשב של המשתמש.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication

import database as db

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587


def get_smtp_config() -> dict:
    return {
        "email": db.get_setting("smtp_email") or "",
        "app_password": db.get_setting("smtp_app_password") or "",
        "host": db.get_setting("smtp_host") or DEFAULT_HOST,
        "port": int(db.get_setting("smtp_port") or DEFAULT_PORT),
    }


def set_smtp_config(email: str, app_password: str, host: str = "", port=None):
    db.set_setting("smtp_email", (email or "").strip())
    db.set_setting("smtp_app_password", app_password or "")
    db.set_setting("smtp_host", (host or DEFAULT_HOST).strip())
    db.set_setting("smtp_port", str(int(port) if port else DEFAULT_PORT))


def is_configured() -> bool:
    cfg = get_smtp_config()
    return bool(cfg["email"] and cfg["app_password"])


def _connect(cfg: dict) -> smtplib.SMTP:
    server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
    server.starttls()
    server.login(cfg["email"], cfg["app_password"])
    return server


def test_connection():
    """Try to log in only (no email sent). Returns (ok: bool, message: str)."""
    cfg = get_smtp_config()
    if not (cfg["email"] and cfg["app_password"]):
        return False, "יש למלא כתובת מייל וסיסמת אפליקציה תחילה."
    try:
        server = _connect(cfg)
        server.quit()
        return True, "החיבור הצליח ✓ ניתן לשלוח מיילים."
    except smtplib.SMTPAuthenticationError:
        return False, "החיבור נכשל — שם משתמש/סיסמת אפליקציה שגויים."
    except Exception as e:
        return False, f"החיבור נכשל: {e}"


def send_email(to_addr: str, subject: str, html_body: str,
               attachment_path: str = None, inline_logo_path: str = None):
    """Send an HTML email, optionally with a file attached and an inline logo
    image (referenced in html_body via <img src="cid:logo">). Raises on failure
    — the caller is expected to show the error to the user."""
    cfg = get_smtp_config()
    if not (cfg["email"] and cfg["app_password"]):
        raise RuntimeError("הגדרות שליחת מייל לא הוגדרו (ראה לשונית הגדרות).")

    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["From"] = cfg["email"]
    root["To"] = to_addr

    related = MIMEMultipart("related")
    related.attach(MIMEText(html_body, "html", "utf-8"))
    if inline_logo_path and os.path.exists(inline_logo_path):
        with open(inline_logo_path, "rb") as f:
            img = MIMEImage(f.read())
        img.add_header("Content-ID", "<logo>")
        img.add_header("Content-Disposition", "inline", filename="logo.png")
        related.attach(img)
    root.attach(related)

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(attachment_path)}"'
        root.attach(part)

    server = _connect(cfg)
    try:
        server.sendmail(cfg["email"], [to_addr], root.as_string())
    finally:
        server.quit()
