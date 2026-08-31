# -*- coding: utf-8 -*-
"""המרת טקסט לדיבור (TTS) + מאגר הקלטות מקומי — ללשונית הצינתוקים.

ההקראה נעשית עם הקולות הנוירליים החינמיים של מיקרוסופט (חבילת ``edge-tts``,
קולות עברית טבעיים: אברי/הילה). דורש אינטרנט; אין צורך במפתח או בתשלום.
התוצר הוא MP3 — שרת ימות ממיר אותו בעצמו לפורמט הטלפוני בהעלאה
(``convertAudio=1`` שכבר קיים ב-``utils/yemot.py``).

מאגר ההקלטות (#kgmcw) הוא תיקייה מקומית ליד ה-DB
(``%APPDATA%\\ManhalHaluka\\recordings``) + קובץ אינדקס JSON. פר-מחשב, לא
מסונכרן — קבצי שמע כבדים מדי ליומן הסנכרון.

מודול טהור (בלי Qt) — הלשונית רק קוראת לו.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import ssl
import time
import uuid

import database as db

# הקולות העבריים הזמינים ב-Edge (שם תצוגה, מזהה).
VOICES = [
    ("אברי (קול גבר)", "he-IL-AvriNeural"),
    ("הילה (קול אישה)", "he-IL-HilaNeural"),
]

# מהירות דיבור: תווית ← ערך rate של Edge.
RATES = [
    ("רגילה", "+0%"),
    ("איטית", "-15%"),
    ("מהירה", "+15%"),
]

DEFAULT_TEXT = (
    "שלום, זוהי הודעה מקופה של צדקה הר יונה. "
    "יש לך חלוקה ביום רביעי. "
    "לאישור הגעה הקש 7. לשמיעה חוזרת הקש 1."
)

# settings keys (מסונכרנים — נוח ששני המחשבים רואים את אותו נוסח אחרון)
SET_LAST_TEXT = "tzintuk_tts_text"
SET_LAST_VOICE = "tzintuk_tts_voice"


class TtsError(Exception):
    """שגיאת יצירת הקלטה — ההודעה כבר בעברית, מוכנה להצגה."""


# ─── יצירת ההקלטה ────────────────────────────────────────────────────────────

def synthesize(text: str, voice: str, out_path: str, rate: str = "+0%"):
    """טקסט עברי → קובץ MP3 בקול נוירלי. חוסם (שניות בודדות) — לקרוא מ-thread.

    מנסה רגיל, ועל בעיית SSL (מכונות NetFree) מזריק truststore ומנסה שוב —
    אותו דפוס כמו ב-utils/yemot.py.
    """
    text = (text or "").strip()
    if not text:
        raise TtsError("לא הוזן טקסט להקראה")
    try:
        import edge_tts
    except ImportError:
        raise TtsError("רכיב ההקראה חסר בגרסה זו — עדכן את התוכנה")

    async def _run():
        tts = edge_tts.Communicate(text, voice, rate=rate)
        await tts.save(out_path)

    last_err = None
    for attempt in (1, 2):
        try:
            asyncio.run(_run())
            if not os.path.exists(out_path) or os.path.getsize(out_path) < 512:
                raise TtsError("השרת לא החזיר הקלטה — נסה שוב עוד רגע")
            return
        except TtsError:
            raise
        except ssl.SSLError as e:
            last_err = e
            try:
                import truststore
                truststore.inject_into_ssl()
                continue                      # ניסיון שני עם אישורי Windows
            except ImportError:
                break
        except Exception as e:
            last_err = e
            # שגיאת SSL עטופה בתוך שגיאת חיבור של aiohttp — לזהות לפי הטקסט.
            if attempt == 1 and "ssl" in str(e).lower():
                try:
                    import truststore
                    truststore.inject_into_ssl()
                    continue
                except ImportError:
                    pass
            break
    detail = str(last_err) or type(last_err).__name__
    if "netfree" in detail.lower():
        raise TtsError("שירות ההקראה נחסם ע\"י הסינון — יש לבקש מנטפרי לפתוח "
                       "את speech.platform.bing.com")
    raise TtsError("יצירת ההקלטה נכשלה — בדוק את חיבור האינטרנט.\n"
                   f"פרטים טכניים: {detail}")


def suggest_name(text: str) -> str:
    """שם מוצע להקלטה — המילים הראשונות של הטקסט."""
    words = re.sub(r"\s+", " ", (text or "").strip()).split(" ")
    name = " ".join(words[:5]).strip(" .,!?:;-")
    return name or "הקלטה"


# ─── מאגר ההקלטות (#kgmcw) ───────────────────────────────────────────────────

def recordings_dir() -> str:
    path = os.path.join(db._data_dir(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path


def _index_path() -> str:
    return os.path.join(recordings_dir(), "index.json")


def library_list() -> list:
    """ההקלטות השמורות, חדשה ראשונה: [{id, name, file, created, text, voice,
    source}] — רק רשומות שהקובץ שלהן עדיין קיים."""
    try:
        with open(_index_path(), encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    out = [it for it in items
           if isinstance(it, dict) and os.path.exists(library_path(it))]
    out.sort(key=lambda it: it.get("created") or "", reverse=True)
    return out


def _save_index(items: list):
    tmp = _index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _index_path())


def library_path(item: dict) -> str:
    return os.path.join(recordings_dir(), item.get("file") or "")


def _file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def library_add(src_path: str, name: str, text: str = "", voice: str = "",
                source: str = "file") -> dict:
    """מעתיק קובץ שמע למאגר ורושם באינדקס. קובץ זהה שכבר במאגר לא נשמר
    שוב — מוחזרת הרשומה הקיימת (רק השם מתעדכן אם ניתן שם חדש)."""
    sha = _file_sha1(src_path)
    items = library_list()
    for it in items:
        if it.get("sha1") == sha:
            if name and name != it.get("name"):
                it["name"] = name
                _save_index(items)
            return it
    ext = os.path.splitext(src_path)[1].lower() or ".mp3"
    item = {
        "id": uuid.uuid4().hex,
        "name": (name or "הקלטה").strip()[:80],
        "file": f"rec_{time.strftime('%Y%m%d_%H%M%S')}_{sha[:8]}{ext}",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "text": (text or "")[:2000],
        "voice": voice,
        "source": source,          # 'tts' = נוצרה מטקסט, 'file' = קובץ שהועלה
        "sha1": sha,
    }
    dst = library_path(item)
    if os.path.abspath(src_path) != os.path.abspath(dst):
        shutil.copy2(src_path, dst)
    items.insert(0, item)
    _save_index(items)
    return item


def library_rename(item_id: str, new_name: str):
    items = library_list()
    for it in items:
        if it.get("id") == item_id:
            it["name"] = (new_name or "הקלטה").strip()[:80]
            break
    _save_index(items)


def library_delete(item_id: str):
    items = library_list()
    keep = []
    for it in items:
        if it.get("id") == item_id:
            try:
                os.remove(library_path(it))
            except OSError:
                pass
        else:
            keep.append(it)
    _save_index(keep)
