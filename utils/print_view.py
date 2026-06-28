import html
from PyQt6.QtWidgets import QWidget
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QTextDocument
from datetime import date
from typing import List, Dict


def _esc(v) -> str:
    """HTML-escape any cell value so '&', '<', '>' in names/data don't break the
    printed table markup."""
    return html.escape(str(v if v is not None else ""))


def print_distribution_list(recipients: List[Dict], dist_date: str, parent: QWidget = None):
    """Open print dialog and print distribution list — portrait, sorted alphabetically."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(printer.pageLayout().orientation().Portrait)

    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return

    doc = QTextDocument()
    doc.setDefaultStyleSheet("""
        body { font-family: 'Segoe UI', Arial; direction: rtl; font-size: 11pt; }
        h2 { text-align: center; color: #1a4a7a; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th { background-color: #1a4a7a; color: white; padding: 6px; text-align: right; border: 1px solid #305090; }
        td { padding: 5px 6px; text-align: right; border: 1px solid #aac; }
        tr:nth-child(even) { background-color: #eef3ff; }
        .footer { text-align: center; font-size: 9pt; color: #888; margin-top: 8px; }
    """)

    rows_sorted = sorted(recipients, key=lambda r: r.get("full_name", ""))

    rows_html = ""
    for i, rec in enumerate(rows_sorted, 1):
        phones = " / ".join(
            p for p in [rec.get("phone1", ""), rec.get("phone2", ""), rec.get("phone3", "")]
            if p
        )
        rows_html += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td><b>{_esc(rec.get('full_name', ''))}</b></td>"
            f"<td>{_esc(phones)}</td>"
            f"<td>{_esc(rec.get('area', ''))}</td>"
            f"<td>{_esc(rec.get('souls', ''))}</td>"
            f"<td style='width:60px;'>&nbsp;</td>"
            f"</tr>"
        )

    html = f"""
    <html><body>
    <h2>רשימת חלוקה — {_esc(dist_date)}</h2>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>שם מלא</th>
                <th>טלפון / ים</th>
                <th>אזור</th>
                <th>נפשות</th>
                <th>✓ ביצוע</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    <p class='footer'>הודפס: {date.today().strftime('%d/%m/%Y')} | סה"כ: {len(recipients)} מקבלים</p>
    </body></html>
    """

    doc.setHtml(html)
    doc.print(printer)
