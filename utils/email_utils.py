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
import imaplib
import email as _email
from email.header import decode_header as _decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from io import BytesIO

import database as db

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587
DEFAULT_IMAP_HOST = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993


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


def get_checklist_password() -> str:
    """Password used to encrypt the volunteer checklist xlsx (open-password).
    Empty string = no protection. Stored locally like the other settings."""
    return db.get_setting("checklist_password") or ""


def set_checklist_password(pw: str):
    db.set_setting("checklist_password", pw or "")


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


# ─── Incoming: auto-pull volunteer replies over IMAP ──────────────────────────
# When a volunteer replies to the checklist email, the filled xlsx comes back as
# an attachment. We poll the inbox (same Gmail account + app password), pick out
# only messages that carry a *volunteer checklist* xlsx (identified by its hidden
# "meta" sheet), save those to disk and mark just those messages as read — so
# unrelated mail is never touched and nothing is processed twice.

def _decode_filename(raw) -> str:
    if not raw:
        return ""
    try:
        parts = _decode_header(raw)
        out = ""
        for text, enc in parts:
            out += text.decode(enc or "utf-8", "ignore") if isinstance(text, bytes) else text
        return out
    except Exception:
        return str(raw)


def _looks_like_checklist(payload: bytes) -> bool:
    """True if the xlsx bytes are one of OUR volunteer checklists (has the hidden
    'meta' sheet). Cheap read-only structural check — never mutates anything.
    Handles both plain and password-encrypted files (the volunteer keeps the
    open-password when they save & send the filled file back)."""
    import openpyxl

    def _has_meta(bio) -> bool:
        wb = openpyxl.load_workbook(bio, read_only=True)
        try:
            return "meta" in wb.sheetnames
        finally:
            wb.close()

    try:
        return _has_meta(BytesIO(payload))
    except Exception:
        pass
    pw = get_checklist_password()
    if not pw:
        return False
    try:
        import msoffcrypto
        dec = BytesIO()
        off = msoffcrypto.OfficeFile(BytesIO(payload))
        off.load_key(password=pw)
        off.decrypt(dec)
        dec.seek(0)
        return _has_meta(dec)
    except Exception:
        return False


def fetch_unseen_checklists(save_dir: str) -> list:
    """Connect over IMAP, find UNSEEN messages that contain a volunteer-checklist
    xlsx attachment, save each to save_dir and mark that message read. Returns the
    list of saved file paths. Never raises to the caller for expected network/auth
    problems — returns [] and lets the poller stay silent."""
    cfg = get_smtp_config()
    if not (cfg["email"] and cfg["app_password"]):
        return []
    host = db.get_setting("imap_host") or DEFAULT_IMAP_HOST
    try:
        port = int(db.get_setting("imap_port") or DEFAULT_IMAP_PORT)
    except (ValueError, TypeError):
        port = DEFAULT_IMAP_PORT

    os.makedirs(save_dir, exist_ok=True)
    saved = []
    m = None
    try:
        m = imaplib.IMAP4_SSL(host, port)
        m.login(cfg["email"], cfg["app_password"])
        m.select("INBOX")
        typ, data = m.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []
        for num in data[0].split():
            # PEEK: read the message WITHOUT setting the \Seen flag, so we only
            # mark ones we actually consume.
            typ, msg_data = m.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = _email.message_from_bytes(msg_data[0][1])
            got_one = False
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                fn = _decode_filename(part.get_filename())
                if not fn or not fn.lower().endswith(".xlsx"):
                    continue
                payload = part.get_payload(decode=True)
                if not payload or not _looks_like_checklist(payload):
                    continue
                base = "".join(c for c in os.path.splitext(fn)[0]
                               if c not in '\\/:*?"<>|').strip() or "checklist"
                out_path = os.path.join(save_dir, f"{base}_{num.decode()}.xlsx")
                with open(out_path, "wb") as f:
                    f.write(payload)
                saved.append(out_path)
                got_one = True
            if got_one:
                try:
                    m.store(num, "+FLAGS", "\\Seen")
                except Exception:
                    pass
        return saved
    except Exception:
        return saved
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass
