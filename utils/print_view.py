import os
import sys
import html
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFrame, QLabel)
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewWidget, QPrintDialog
from PyQt6.QtGui import QTextDocument, QImage, QPageLayout
from PyQt6.QtCore import QUrl, QSizeF, QMarginsF, Qt
from datetime import date, datetime
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
    .org {{ text-align: center; font-size: {fs + 1}pt; font-weight: bold; color: #1a4a7a; }}
    h2 {{ text-align: center; color: #1a4a7a; margin-top: 2px; font-size: {fs + 1}pt; }}
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
# Header text colour is set INLINE (#nne2s): QTextDocument applied the th
# background from the stylesheet but not its `color`, so the captions printed
# dark-on-dark. The <font> wrapper is the belt-and-braces for the PDF path.
_TH = "<th style='color:#ffffff;'{attrs}><font color='#ffffff'>{txt}</font></th>"


def _th(txt: str, cls: str = "", extra: str = "") -> str:
    return _TH.format(attrs=(f" class='{cls}'" if cls else "") + (f" {extra}" if extra else ""), txt=txt)


_THEAD = ("<thead><tr>"
          + _th("אזור") + _th("טלפון / ים") + _th("תשובה", "chk") + _th("שם מלא")
          + _th("מס'", "num") + _th("✓ סימון", "chk")
          + "</tr></thead>")


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
            f"<td class='chk'>{_esc(rec.get('_answer') or ('✓' if rec.get('_confirmed') else ''))}</td>"
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

    # Logo at half its old size (#dyunn) — the list, not the letterhead, is the point.
    logo_html = "<div class='logo'><img src='orglogo' width='75'></div>" if has_logo else ""
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


class _PreviewDialog(QDialog):
    """Clean, self-built print-preview window (#sdj7g). Instead of Qt's cramped
    default toolbar of tiny unlabeled icons, it shows a clear Hebrew action bar
    with a big, emphasised 'הדפס' button plus obvious zoom / fit / close
    controls. The page is rendered by `render(printer)`."""

    def __init__(self, printer: QPrinter, render, parent, title: str, on_pdf=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._printer = printer
        self._render = render

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Action bar ────────────────────────────────────────────────────────
        bar = QFrame()
        bar.setObjectName("prev-bar")
        bar.setStyleSheet(
            "QFrame#prev-bar{background:#f4faf7; border-bottom:1px solid #dce7e2;}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size:15px; font-weight:700; color:#0f766e;")
        bl.addWidget(title_lbl)
        bl.addStretch()

        _ghost = ("QPushButton{background:#ffffff; color:#0f766e; border:1px solid #b6d8cd;"
                  "border-radius:9px; padding:8px 14px; font-size:14px; font-weight:600;}"
                  "QPushButton:hover{background:#eafaf3;}")
        btn_zoom_out = QPushButton("‒ הקטן")
        btn_zoom_out.setStyleSheet(_ghost)
        btn_zoom_out.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_zoom_out.clicked.connect(lambda: self.preview.zoomOut(1.15))
        bl.addWidget(btn_zoom_out)

        btn_zoom_in = QPushButton("+ הגדל")
        btn_zoom_in.setStyleSheet(_ghost)
        btn_zoom_in.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_zoom_in.clicked.connect(lambda: self.preview.zoomIn(1.15))
        bl.addWidget(btn_zoom_in)

        btn_fit = QPushButton("התאם לרוחב")
        btn_fit.setStyleSheet(_ghost)
        btn_fit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_fit.clicked.connect(lambda: self.preview.fitToWidth())
        bl.addWidget(btn_fit)

        if on_pdf is not None:
            btn_pdf = QPushButton("שמור PDF")
            btn_pdf.setStyleSheet(_ghost)
            btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_pdf.clicked.connect(lambda: (on_pdf(), self.accept()))
            bl.addWidget(btn_pdf)

        # The primary action — big, teal, impossible to miss.
        btn_print = QPushButton("🖨  הדפס")
        btn_print.setStyleSheet(
            "QPushButton{background:#0f9d78; color:#ffffff; border:none;"
            "border-radius:10px; padding:10px 26px; font-size:16px; font-weight:800;}"
            "QPushButton:hover{background:#0c8a69;}")
        btn_print.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_print.setMinimumHeight(44)
        btn_print.clicked.connect(self._do_print)
        bl.addWidget(btn_print)

        btn_close = QPushButton("סגור")
        btn_close.setStyleSheet(_ghost)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        bl.addWidget(btn_close)

        root.addWidget(bar)

        # ── Preview surface ───────────────────────────────────────────────────
        # NOTE: keep the preview widget itself LTR — forcing RTL on it mirrors the
        # page navigation. The page CONTENT is RTL via the HTML, unaffected.
        self.preview = QPrintPreviewWidget(printer)
        self.preview.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.preview.paintRequested.connect(render)
        root.addWidget(self.preview, 1)

        self.resize(1000, 800)
        self.setWindowState(Qt.WindowState.WindowMaximized)

    def showEvent(self, e):
        super().showEvent(e)
        self.preview.fitToWidth()

    def _do_print(self):
        d = QPrintDialog(self._printer, self)
        d.setWindowTitle("הדפסה")
        if d.exec() == QDialog.DialogCode.Accepted:
            self._render(self._printer)
            self.accept()


def _preview(printer: QPrinter, render, parent: QWidget, title: str, on_pdf=None):
    """Show the custom print-preview window (RTL, Hebrew). `render(printer)` draws
    the pages; the user prints from the big 'הדפס' button (#sdj7g)."""
    _PreviewDialog(printer, render, parent, title, on_pdf).exec()


def _make_dist_renderer(recipients: List[Dict], html: str, has_logo: bool, logo_path: str):
    """Build the paint callback that draws the distribution list onto a QPrinter,
    picking the largest font that still fits the target page count. Shared by the
    on-screen preview and the PDF export so both look identical."""
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
    return render


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

    render = _make_dist_renderer(recipients, html, has_logo, logo_path)
    _preview(printer, render, parent, "תצוגה מקדימה — רשימת חלוקה",
             on_pdf=lambda: export_distribution_pdf(recipients, dist_date, dist_name))


def _safe_filename(text: str) -> str:
    """Turn a distribution name into a filesystem-safe file stem."""
    text = (text or "").strip()
    for ch in '\\/:*?"<>|':
        text = text.replace(ch, "")
    text = "_".join(text.split())
    return text[:60] or "חלוקה"


def export_distribution_pdf(recipients: List[Dict], dist_date: str,
                            dist_name: str = "") -> str:
    """Render the distribution list straight to a PDF in the user's Downloads
    folder (no printer needed), then open it automatically. Returns the file path.

    Same layout as the print preview — reuses the exact HTML + fit renderer."""
    from utils.excel_utils import export_dir   # lazy: avoid import cycle

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)

    stem = _safe_filename(dist_name or "רשימת_חלוקה")
    # Date AND time (like the Excel exports): a second export the same day must
    # not overwrite the first — especially while the first is still open in a
    # PDF viewer, where the overwrite silently produced a 0-byte file.
    fname = f"{stem}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.pdf"
    out_path = os.path.join(str(export_dir("dist")), fname)
    printer.setOutputFileName(out_path)

    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    html = _build_html(recipients, dist_date, has_logo, dist_name)

    render = _make_dist_renderer(recipients, html, has_logo, logo_path)
    render(printer)   # writes the PDF file
    # QPrinter reports nothing when the file could not be written (locked,
    # folder unwritable) — verify the result instead of opening an empty file.
    try:
        size = os.path.getsize(out_path)
    except OSError:
        size = 0
    if size <= 0:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise RuntimeError(
            "קובץ ה-PDF לא נכתב (יצא ריק).\n"
            "בדוק שתיקיית הייצוא זמינה ושאין קובץ PDF פתוח באותו שם, ונסה שוב.")

    # Open the finished PDF automatically (best-effort — never fail the export).
    try:
        os.startfile(out_path)   # Windows: opens in the default PDF viewer
    except Exception:
        pass
    return out_path


def _priority_text(rec: Dict) -> str:
    from utils.excel_utils import _priority_text as _pt   # lazy: avoid import cycle
    return _pt(rec)


def _holidays_text(rec: Dict) -> str:
    import holidays
    return holidays.display(rec)


CARD_FONT_PT = 12   # base font of the printed recipient card
_CELL_BORDER = "border:1px solid #aaaacc;"


def _cell(val, head: bool = False, extra: str = "") -> str:
    """One printed card cell: always right-aligned and with its own visible border
    (inline, because QTextDocument drops stylesheet borders on styled cells)."""
    txt = _esc(val)
    if head:
        return ("<th class='cc' dir='rtl' align='left' style='text-align:left;"
                f"background-color:#eef3ff;color:#1a4a7a;{_CELL_BORDER}' width='28%'>{txt}</th>")
    return (f"<td class='cc' dir='rtl' align='left' {extra} "
            f"style='text-align:left;{_CELL_BORDER}'>{txt}</td>")


def _card_th(txt: str, extra: str = "") -> str:
    """Card column header: like `_th`, but its own paragraph is RTL (so a trailing
    apostrophe in "מס'" stays at the word's end) and right-aligned."""
    return _th(txt, "cc", f"dir='rtl' align='left' {extra}".strip())


def _card_html(rec: Dict, history: List[Dict], has_logo: bool) -> str:
    """A single recipient's printable card: details block + distribution history."""
    def _v(key):
        return rec.get(key) or ""

    # Raw values only — `_cell` HTML-escapes them exactly once.
    phones = " / ".join(p for p in [rec.get("phone1"), rec.get("phone2"), rec.get("phone3")] if p)
    ids = " / ".join(x for x in (_v("id_number"), _v("spouse_id_number")) if x)
    rows = [
        ("טלפונים", phones),
        ("ת.ז. בעל / אשה", ids),
        ("כתובת", _v("address")),
        ("אזור", _v("area")),
        ("נפשות", rec.get("souls") or ""),
        ("עדיפות", _priority_text(rec)),
        ("נתמך חגים", _holidays_text(rec)),
        ("תדירות", _v("frequency")),
        ("סטטוס", _v("status")),
        ("חלוקה אחרונה", _fmt(rec.get("last_distribution"))),
        ("חלוקה הבאה", _fmt(rec.get("next_distribution"))),
        ("הערות", _v("notes")),
    ]
    # Column order: QTextDocument honours `direction: rtl` on the table, so the
    # column written LAST in the source prints right-most. Label therefore comes
    # last (right side, where a Hebrew reader starts), value first.
    details = (
        "<table class='card' border='1' cellspacing='0' cellpadding='6' width='100%'>"
        "<thead><tr>" + _th("פרטי המקבל", "sec-title", "colspan='2' dir='rtl' align='left'")
        + "</tr></thead><tbody>"
        + "".join(
            f"<tr>{_cell(val)}{_cell(label, head=True)}</tr>"
            for label, val in rows)
        + "</tbody></table>")

    # History: columns written in REVERSE so the printed table reads right-to-left
    # (מס' on the right, הערות on the left). Every cell is explicitly right-aligned.
    hist_rows = ""
    for i, h in enumerate(history, 1):
        hist_rows += (
            "<tr>"
            + _cell(h.get('notes', ''))
            + _cell(h.get('distributor', ''))
            + _cell(h.get('quantity', '') or '')
            + _cell(h.get('what_dist', ''))
            + _cell(_fmt(h.get('dist_date')))
            + _cell(i)
            + "</tr>"
        )
    # The title is a full-width header row INSIDE the table (colspan) so it can't
    # detach from the columns under QTextDocument's RTL layout (bug #rxurn).
    hist_table = (
        "<table class='card' border='1' cellspacing='0' cellpadding='6' width='100%'>"
        "<thead>"
        + "<tr>" + _th("היסטוריית חלוקות", "sec-title", "colspan='6' dir='rtl' align='left'") + "</tr>"
        + "<tr>" + "".join(_card_th(t, f"width='{w}%'") for t, w in
                           (("הערות", 34), ("מחלק", 14), ("כמות", 9),
                            ("מה חולק", 17), ("תאריך", 18), ("מס'", 8))) + "</tr>"
        + "</thead><tbody>" + (hist_rows or
            "<tr>" + _cell("אין חלוקות רשומות", extra="colspan='6'") + "</tr>")
        + "</tbody></table>"
    )

    logo_html = "<div class='logo'><img src='orglogo' width='130'></div>" if has_logo else ""
    return f"""
    <html><body>
    {logo_html}
    <div class='org'>{_esc(ORG_NAME)}</div>
    <h2>כרטיס מקבל — {_esc(rec.get('full_name', ''))}</h2>
    {details}
    <p></p>
    {hist_table}
    <p class='footer'>הודפס: {date.today().strftime('%d/%m/%Y')} · סה\"כ חלוקות: {len(history)}</p>
    </body></html>
    """


def _fmt(s) -> str:
    s = str(s or "")
    if len(s) >= 10 and s[4] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s


def _card_css() -> str:
    """Printed-card stylesheet: the list's look + roomy cell padding (every cell has
    the 'cc' class; the section title rows 'sec-title')."""
    return (_css(CARD_FONT_PT)
            + ".cc, th.sec-title { padding: 5px 8px; }")


def render_recipient_card(pr: QPrinter, rec: Dict, history: List[Dict]):
    """Draw a single recipient's card onto a QPrinter (preview, paper or PDF)."""
    logo_path = _resource_path("org_logo.png")
    has_logo = os.path.exists(logo_path)
    doc = QTextDocument()
    if has_logo:
        doc.addResource(QTextDocument.ResourceType.ImageResource,
                        QUrl("orglogo"), QImage(logo_path))
    # Measure against the PRINTER's resolution (like the list does) so the font is a
    # real 14pt on paper; without it the card came out tiny on a mostly empty page.
    try:
        doc.documentLayout().setPaintDevice(pr)
    except Exception:
        pass
    doc.setDefaultStyleSheet(_card_css())
    doc.setHtml(_card_html(rec, history, has_logo))
    doc.setPageSize(QSizeF(pr.pageLayout().paintRectPixels(pr.resolution()).size()))
    doc.print(pr)


def print_recipient_card(rec: Dict, history: List[Dict], parent: QWidget = None):
    """Open a print PREVIEW of a single recipient's card + history."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    _preview(printer, lambda pr: render_recipient_card(pr, rec, history),
             parent, "תצוגה מקדימה — כרטיס מקבל")
