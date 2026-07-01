import os
import sys
import html
from PyQt6.QtWidgets import QWidget
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QTextDocument, QImage
from PyQt6.QtCore import QUrl
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

_PRINT_CSS = """
    body { font-family: 'Segoe UI', Arial; direction: rtl; font-size: 11pt; }
    .logo { text-align: center; margin-bottom: 2px; }
    .org { text-align: center; font-size: 16pt; font-weight: bold; color: #1a4a7a; }
    h2 { text-align: center; color: #1a4a7a; margin-top: 2px; }
    .notice { text-align: center; font-size: 9pt; color: #b45309;
              border: 1px solid #f0c890; background-color: #fff8ec;
              padding: 5px; margin: 8px 0; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; direction: rtl; }
    th { background-color: #1a4a7a; color: white; padding: 6px; text-align: right; border: 1px solid #305090; }
    td { padding: 5px 6px; text-align: right; border: 1px solid #aac; }
    tr:nth-child(even) { background-color: #eef3ff; }
    .reserve-h { text-align: right; color: #b45309; font-size: 12pt; font-weight: bold;
                 margin-top: 16px; border-bottom: 1px solid #f0c890; padding-bottom: 3px; }
    table.reserve th { background-color: #b45309; border-color: #92400e; }
    .footer { text-align: center; font-size: 9pt; color: #888; margin-top: 8px; }
"""

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
            f"<td style='width:60px;'>&nbsp;</td>"
            f"<td>{_esc(rec.get('area', ''))}</td>"
            f"<td>{_esc(phones)}</td>"
            f"<td><b>{_esc(rec.get('full_name', ''))}</b></td>"
            f"<td>{i}</td>"
            f"</tr>"
        )
    return out


def _build_html(recipients: List[Dict], dist_date: str, has_logo: bool = False) -> str:
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
            f"<table class='reserve'>{_THEAD}<tbody>{_table_rows(reserves)}</tbody></table>"
        )

    logo_html = "<div class='logo'><img src='orglogo' width='150'></div>" if has_logo else ""
    return f"""
    <html><body>
    {logo_html}
    <div class='org'>{_esc(ORG_NAME)}</div>
    <h2>רשימת חלוקה — {_esc(dist_date)}</h2>
    <div class='notice'>{_esc(DISCLAIMER)}</div>
    {body}
    <p class='footer'>הודפס: {date.today().strftime('%d/%m/%Y')} | חלוקה: {len(mains)} · רזרבה: {len(reserves)}</p>
    </body></html>
    """


def print_distribution_list(recipients: List[Dict], dist_date: str, parent: QWidget = None):
    """Open print dialog and print distribution list — portrait, right-to-left."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(printer.pageLayout().orientation().Portrait)

    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return

    doc = QTextDocument()
    doc.setDefaultStyleSheet(_PRINT_CSS)
    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    if has_logo:
        doc.addResource(QTextDocument.ResourceType.ImageResource,
                        QUrl("orglogo"), QImage(logo_path))
    doc.setHtml(_build_html(recipients, dist_date, has_logo))
    doc.print(printer)
