import os
import sys
import html
from PyQt6.QtWidgets import QWidget
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QTextDocument, QImage, QPageLayout
from PyQt6.QtCore import QUrl, QSizeF, QMarginsF
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
    pad = max(2, fs // 3)
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
    th {{ background-color: #1a4a7a; color: white; padding: {pad}px; text-align: right;
         border: 1px solid #305090; font-size: {fs}pt; }}
    td {{ padding: {pad}px; text-align: right; border: 1px solid #aac; font-size: {fs}pt; }}
    tr:nth-child(even) {{ background-color: #eef3ff; }}
    .reserve-h {{ text-align: right; color: #b45309; font-size: {fs + 1}pt; font-weight: bold;
                 margin-top: 12px; border-bottom: 1px solid #f0c890; padding-bottom: 3px; }}
    table.reserve th {{ background-color: #b45309; border-color: #92400e; }}
    .footer {{ text-align: center; font-size: {small}pt; color: #888; margin-top: 6px; }}
    .chk {{ text-align: center; font-size: {fs + 3}pt; }}
    .resgrid {{ width: 100%; border-collapse: collapse; margin-top: 6px; direction: rtl; }}
    .resgrid td {{ border: 1px solid #f0c890; padding: {pad}px 8px; text-align: right;
                  font-size: {fs}pt; vertical-align: top; }}
    """


_PRINT_CSS = _css(11)   # default (kept for any external caller)

_THEAD = ("<thead><tr>"
          "<th>✓ ביצוע</th><th>אזור</th><th>טלפון / ים</th><th>שם מלא</th><th>מס'</th>"
          "</tr></thead>")


def _esc(v) -> str:
    """HTML-escape any cell value so '&', '<', '>' in names/data don't break the
    printed table markup."""
    return html.escape(str(v if v is not None else ""))


def _table_rows(rows: List[Dict]) -> str:
    # Columns are emitted RIGHT-TO-LEFT (✓/אזור/טלפון/שם/מס') because Qt's
    # QTextDocument lays table columns in source order regardless of dir/layout —
    # reversing the source order is what puts the index column on the right.
    out = ""
    for i, rec in enumerate(rows, 1):
        phones = " / ".join(
            p for p in [rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", "")]
            if p
        )
        out += (
            f"<tr>"
            f"<td class='chk'>☐</td>"
            f"<td>{_esc(rec.get('area', ''))}</td>"
            f"<td>{_esc(phones)}</td>"
            f"<td><b>{_esc(rec.get('full_name', ''))}</b></td>"
            f"<td>{i}</td>"
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


def print_distribution_list(recipients: List[Dict], dist_date: str, parent: QWidget = None,
                            dist_name: str = ""):
    """Open print dialog and print distribution list — portrait, right-to-left."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    # Reasonable margins so nothing is clipped at the page edges.
    printer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)

    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return

    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    html = _build_html(recipients, dist_date, has_logo, dist_name)
    page_size = QSizeF(printer.pageLayout().paintRectPixels(printer.resolution()).size())

    doc = QTextDocument()
    # Measure against the PRINTER's resolution so pageCount() is accurate (without
    # this the doc measures at screen DPI and the fit loop would be fooled).
    try:
        doc.documentLayout().setPaintDevice(printer)
    except Exception:
        pass
    if has_logo:
        doc.addResource(QTextDocument.ResourceType.ImageResource,
                        QUrl("orglogo"), QImage(logo_path))

    # Auto-shrink to save the distributor pages: start at a comfortable size and
    # step the font down until the whole list fits on ONE page, or we hit a
    # readable floor (then a very long list still spans the fewest pages it can).
    for fs in (11, 10, 9, 8, 7, 6):
        doc.setDefaultStyleSheet(_css(fs))
        doc.setHtml(html)
        doc.setPageSize(page_size)
        if doc.pageCount() <= 1:
            break
    doc.print(printer)


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
    details = "".join(
        f"<tr><th style='width:150px;background:#eef3ff;color:#1a4a7a;'>{label}</th>"
        f"<td>{val}</td></tr>"
        for label, val in rows
    )

    hist_rows = ""
    for i, h in enumerate(history, 1):
        hist_rows += (
            f"<tr><td>{i}</td>"
            f"<td>{_esc(_fmt(h.get('dist_date')))}</td>"
            f"<td>{_esc(h.get('what_dist', ''))}</td>"
            f"<td>{_esc(h.get('quantity', '') or '')}</td>"
            f"<td>{_esc(h.get('distributor', ''))}</td>"
            f"<td>{_esc(h.get('notes', ''))}</td></tr>"
        )
    hist_table = (
        "<div class='reserve-h'>היסטוריית חלוקות</div>"
        "<table><thead><tr>"
        "<th>מס'</th><th>תאריך</th><th>מה חולק</th><th>כמות</th><th>מחלק</th><th>הערות</th>"
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
    <table>{details}</table>
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
    """Open the print dialog and print a single recipient's card + history."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)

    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return

    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    doc = QTextDocument()
    if has_logo:
        doc.addResource(QTextDocument.ResourceType.ImageResource,
                        QUrl("orglogo"), QImage(logo_path))
    doc.setDefaultStyleSheet(_css(11))
    doc.setHtml(_card_html(rec, history, has_logo))
    doc.setPageSize(QSizeF(printer.pageLayout().paintRectPixels(printer.resolution()).size()))
    doc.print(printer)
