import os
import sys
import html
from PyQt6.QtWidgets import QWidget
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PyQt6.QtGui import QTextDocument, QImage, QPageLayout
from PyQt6.QtCore import QUrl, QSizeF, QMarginsF, Qt
from datetime import date
from typing import List, Dict


def _resource_path(rel: str) -> str:
    """Locate a bundled resource in both dev and frozen (onefile) modes."""
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)

# Organisation name shown at the top of every printed distribution list.
ORG_NAME = "קופה של צדקה הר יונה"
# Disclaimer printed on every page — the data is produced by software still in
# trial, so the user should double-check it.
DISCLAIMER = ("⚠ דף זה הופק אוטומטית על־ידי מערכת בהרצה — "
              "יש לבדוק את הנתונים ולהיות ערניים.")

def _css(fs: int = 11) -> str:
    """Print stylesheet at a given base font size (pt). Cell padding scales with
    the font so a smaller font also packs rows tighter — this lets a long list be
    shrunk to fit fewer pages (see the fit loop in print_distribution_list)."""
    pad = max(1, fs // 4)          # tighter rows so more people fit per page
    small = max(7, fs - 2)
    return f"""
    body {{ font-family: 'Segoe UI', Arial; direction: rtl; font-size: {fs}pt; }}
    .logo {{ text-align: center; margin-bottom: 2px; }}
    .org {{ text-align: center; font-size: {fs + 5}pt; font-weight: bold; color: #1a4a7a; }}
    h2 {{ text-align: center; color: #1a4a7a; margin-top: 2px; font-size: {fs + 3}pt; }}
    .notice {{ text-align: center; font-size: {small}pt; color: #b45309;
              border: 1px solid #f0c890; background-color: #fff8ec;
              padding: 4px; margin: 6px 0; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; direction: rtl; }}
    th {{ background-color: #1a4a7a; color: white; padding: {pad}px {pad + 2}px; text-align: right;
         border: 1px solid #305090; font-size: {fs}pt; }}
    td {{ padding: {pad}px {pad + 2}px; text-align: right; border: 1px solid #aac; font-size: {fs}pt; }}
    tr:nth-child(even) {{ background-color: #eef3ff; }}
    .reserve-h {{ text-align: right; color: #b45309; font-size: {fs + 1}pt; font-weight: bold;
                 margin-top: 12px; border-bottom: 1px solid #f0c890; padding-bottom: 3px; }}
    th.sec-title {{ background-color: #b45309; color: white; text-align: right;
                   font-size: {fs + 1}pt; border-color: #92400e; }}
    table.reserve th {{ background-color: #b45309; border-color: #92400e; }}
    .footer {{ text-align: center; font-size: {small}pt; color: #888; margin-top: 6px; }}
    .chk {{ text-align: center; font-size: {fs + 1}pt; width: {fs * 2}px; color: #305090; }}
    .num {{ text-align: center; width: {fs * 3}px; color: #555; }}
    .resgrid {{ width: 100%; border-collapse: collapse; margin-top: 6px; direction: rtl; }}
    .resgrid td {{ border: 1px solid #f0c890; padding: {pad}px 8px; text-align: right;
                  font-size: {fs}pt; vertical-align: top; }}
    """


_PRINT_CSS = _css(11)   # default (kept for any external caller)

# Column order is written left-to-right in SOURCE, which lands right-to-left on
# the printed page. So the checkmark column, written LAST, prints as the first
# (right-most) column — where the distributor marks כן/לא by hand.
_THEAD = ("<thead><tr>"
          "<th>אזור</th><th>טלפון / ים</th><th>שם מלא</th>"
          "<th class='num'>מס'</th><th class='chk'>✓ סימון</th>"
          "</tr></thead>")


def _esc(v) -> str:
    """HTML-escape any cell value so '&', '<', '>' in names/data don't break the
    printed table markup."""
    return html.escape(str(v if v is not None else ""))


def _table_rows(rows: List[Dict]) -> str:
    # Emitted in SOURCE order אזור/טלפון/שם/מס'/✓ — QTextDocument lays columns in
    # source order regardless of RTL, so this prints (right→left) as
    # ✓ · מס' · שם · טלפון · אזור, putting the manual-mark column on the right.
    out = ""
    for i, rec in enumerate(rows, 1):
        phones = " / ".join(
            p for p in [rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", "")]
            if p
        )
        out += (
            f"<tr>"
            f"<td>{_esc(rec.get('area', ''))}</td>"
            f"<td>{_esc(phones)}</td>"
            f"<td><b>{_esc(rec.get('full_name', ''))}</b></td>"
            f"<td class='num'>{i}</td>"
            f"<td class='chk'>☐</td>"
            f"</tr>"
        )
    return out


def _reserve_grid(reserves: List[Dict], per_row: int = 3) -> str:
    """Reserve list laid out ACROSS the page width (compact, several per row) in
    priority/call order, instead of one tall column."""
    cells = []
    for i, rec in enumerate(reserves, 1):
        phones = " / ".join(
            p for p in [rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", "")] if p)
        txt = f"{i}. <b>{_esc(rec.get('full_name', ''))}</b>"
        if phones:
            txt += f" — {_esc(phones)}"
        cells.append(txt)
    out = "<table class='resgrid'>"
    for r in range(0, len(cells), per_row):
        chunk = cells[r:r + per_row]
        out += "<tr>" + "".join(f"<td>{c}</td>" for c in chunk)
        out += "<td></td>" * (per_row - len(chunk)) + "</tr>"
    out += "</table>"
    return out


def _build_html(recipients: List[Dict], dist_date: str, has_logo: bool = False,
                dist_name: str = "") -> str:
    """Build the printable HTML for a distribution list — right-to-left (Hebrew),
    with the fund name and a trial-system disclaimer. Recipients flagged
    `_reserve` are split into a separate, clearly-marked 'רזרבה' section kept in
    priority order (call order = row number). The נפשות column is omitted."""
    mains = [r for r in recipients if not r.get("_reserve")]
    reserves = [r for r in recipients if r.get("_reserve")]
    mains = sorted(mains, key=lambda r: r.get("full_name", ""))
    # reserves are NOT re-sorted — they arrive in priority order (call order).

    body = f"<table>{_THEAD}<tbody>{_table_rows(mains)}</tbody></table>"
    if reserves:
        body += (
            "<div class='reserve-h'>רזרבה — לפי סדר עדיפות (להתקשר לפי הסדר)</div>"
            + _reserve_grid(reserves)
        )

    logo_html = "<div class='logo'><img src='orglogo' width='150'></div>" if has_logo else ""
    heading = f"{_esc(dist_name)} — {_esc(dist_date)}" if dist_name else f"רשימת חלוקה — {_esc(dist_date)}"
    return f"""
    <html><body>
    {logo_html}
    <div class='org'>{_esc(ORG_NAME)}</div>
    <h2>{heading}</h2>
    <div class='notice'>{_esc(DISCLAIMER)}</div>
    {body}
    <p class='footer'>הודפס: {date.today().strftime('%d/%m/%Y')} | חלוקה: {len(mains)} · רזרבה: {len(reserves)}</p>
    </body></html>
    """


def _preview(printer: QPrinter, render, parent: QWidget, title: str):
    """Show a full print-preview dialog (RTL, Hebrew) whose pages are drawn by
    `render(printer)`. The user prints from the dialog's own toolbar."""
    dlg = QPrintPreviewDialog(printer, parent)
    dlg.setWindowTitle(title)
    # NOTE: do NOT force RightToLeft on the dialog itself — that reverses the
    # preview toolbar and pushed the print button off the visible area (the user
    # had to widen the window to reach it). The page CONTENT is already RTL via
    # the HTML (direction:rtl), so the printout is unaffected.
    dlg.paintRequested.connect(render)
    # Open maximized so the full toolbar — including the print button — and a
    # large, readable preview are visible immediately.
    dlg.resize(1100, 800)
    dlg.setWindowState(Qt.WindowState.WindowMaximized)
    dlg.exec()


def print_distribution_list(recipients: List[Dict], dist_date: str, parent: QWidget = None,
                            dist_name: str = ""):
    """Open a print PREVIEW of the distribution list — portrait, right-to-left —
    so the user sees exactly what will print before sending it to the printer."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    # Reasonable margins so nothing is clipped at the page edges.
    printer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)

    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    html = _build_html(recipients, dist_date, has_logo, dist_name)

    def render(pr: QPrinter):
        page_size = QSizeF(pr.pageLayout().paintRectPixels(pr.resolution()).size())
        doc = QTextDocument()
        # Measure against the PRINTER's resolution so pageCount() is accurate
        # (without this the doc measures at screen DPI and the fit loop is fooled).
        try:
            doc.documentLayout().setPaintDevice(pr)
        except Exception:
            pass
        if has_logo:
            doc.addResource(QTextDocument.ResourceType.ImageResource,
                            QUrl("orglogo"), QImage(logo_path))
        # Layout target: pack the list tightly — up to ~85 recipients per page.
        # Compute the minimum pages needed at that density, then pick the LARGEST
        # font that still fits the list into that many pages, so each page is
        # filled (many people per page) while staying as readable as possible.
        PER_PAGE = 85
        n_main = sum(1 for r in recipients if not r.get("_reserve"))
        target_pages = max(1, (n_main + PER_PAGE - 1) // PER_PAGE)
        for fs in (12, 11, 10, 9, 8, 7, 6):
            doc.setDefaultStyleSheet(_css(fs))
            doc.setHtml(html)
            doc.setPageSize(page_size)
            if doc.pageCount() <= target_pages:
                break
        doc.print(pr)

    _preview(printer, render, parent, "תצוגה מקדימה — רשימת חלוקה")


_PRIORITY_LABELS = {4: "קבוע", 3: "עדיפות ראשונה", 2: "עדיפות שנייה"}


def _priority_text(rec: Dict) -> str:
    pr = rec.get("priority")
    if pr in _PRIORITY_LABELS:
        return _PRIORITY_LABELS[pr]
    return "חובת בירור" if "בירור" in (rec.get("priority_raw") or "") else ""


def _card_html(rec: Dict, history: List[Dict], has_logo: bool) -> str:
    """A single recipient's printable card: details block + distribution history."""
    def _v(key):
        return _esc(rec.get(key) or "")

    phones = " / ".join(p for p in [rec.get("phone1"), rec.get("phone2"), rec.get("phone3")] if p)
    rows = [
        ("טלפונים", _esc(phones)),
        ("ת.ז. בעל / אשה", f"{_v('id_number')} / {_v('spouse_id_number')}"),
        ("כתובת", _v("address")),
        ("אזור", _v("area")),
        ("נפשות", _esc(rec.get("souls") or "")),
        ("עדיפות", _esc(_priority_text(rec))),
        ("תדירות", _v("frequency")),
        ("סטטוס", _v("status")),
        ("חלוקה אחרונה", _esc(_fmt(rec.get("last_distribution")))),
        ("חלוקה הבאה", _esc(_fmt(rec.get("next_distribution")))),
        ("הערות", _v("notes")),
    ]
    # QTextDocument lays table columns in SOURCE order and ignores direction:rtl,
    # so a naive label→value order prints label on the LEFT and reads
    # left-to-right (bug #rxurn). Emit value FIRST, label LAST, so the label lands
    # on the right where a Hebrew reader starts.
    details = "".join(
        f"<tr><td style='width:70%;'>{val}</td>"
        f"<th style='width:30%;background:#eef3ff;color:#1a4a7a;'>{label}</th></tr>"
        for label, val in rows
    )

    # Same reason: write the history columns in REVERSE source order so the
    # printed table reads right-to-left (מס' on the right, הערות on the left).
    hist_rows = ""
    for i, h in enumerate(history, 1):
        hist_rows += (
            f"<tr><td>{_esc(h.get('notes', ''))}</td>"
            f"<td>{_esc(h.get('distributor', ''))}</td>"
            f"<td>{_esc(h.get('quantity', '') or '')}</td>"
            f"<td>{_esc(h.get('what_dist', ''))}</td>"
            f"<td>{_esc(_fmt(h.get('dist_date')))}</td>"
            f"<td>{i}</td></tr>"
        )
    # The title must sit directly ABOVE the table. A standalone <div> before the
    # table drifted to the opposite side of the page under QTextDocument's RTL
    # layout (bug #rxurn), so make the title a full-width header row INSIDE the
    # table (colspan spanning all columns) — it can't detach from the columns.
    hist_table = (
        "<table><thead>"
        "<tr><th colspan='6' class='sec-title'>היסטוריית חלוקות</th></tr>"
        "<tr>"
        "<th>הערות</th><th>מחלק</th><th>כמות</th><th>מה חולק</th><th>תאריך</th><th>מס'</th>"
        "</tr></thead><tbody>" + (hist_rows or
            "<tr><td colspan='6' style='text-align:center;color:#888;'>אין חלוקות רשומות</td></tr>")
        + "</tbody></table>"
    )

    logo_html = "<div class='logo'><img src='orglogo' width='130'></div>" if has_logo else ""
    return f"""
    <html><body>
    {logo_html}
    <div class='org'>{_esc(ORG_NAME)}</div>
    <h2>כרטיס מקבל — {_esc(rec.get('full_name', ''))}</h2>
    <table width='100%'>{details}</table>
    {hist_table}
    <p class='footer'>הודפס: {date.today().strftime('%d/%m/%Y')} · סה\"כ חלוקות: {len(history)}</p>
    </body></html>
    """


def _fmt(s) -> str:
    s = str(s or "")
    if len(s) >= 10 and s[4] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s


def print_recipient_card(rec: Dict, history: List[Dict], parent: QWidget = None):
    """Open a print PREVIEW of a single recipient's card + history."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)

    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    card_html = _card_html(rec, history, has_logo)

    def render(pr: QPrinter):
        doc = QTextDocument()
        if has_logo:
            doc.addResource(QTextDocument.ResourceType.ImageResource,
                            QUrl("orglogo"), QImage(logo_path))
        # A single recipient's card has a whole A4 page to itself, so print it at
        # a much larger base font (~3–4× the list's 11pt) — the previous size came
        # out tiny and hard to read (bug #18).
        doc.setDefaultStyleSheet(_css(30))
        doc.setHtml(card_html)
        doc.setPageSize(QSizeF(pr.pageLayout().paintRectPixels(pr.resolution()).size()))
        doc.print(pr)

    _preview(printer, render, parent, "תצוגה מקדימה — כרטיס מקבל")
