import os
import re
import sys
from datetime import datetime, date as _date_type
from pathlib import Path
from typing import List, Dict


def _app_dir() -> Path:
    """Return the app root directory — works in dev and as PyInstaller EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _parse_date(val) -> str:
    """Convert any date representation to ISO yyyy-mm-dd string."""
    if val is None or val == "":
        return ""
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, _date_type):
        return val.isoformat()
    val = str(val).strip()
    if not val or val == "None":
        return ""
    # yyyy-mm-dd or yyyy-mm-dd HH:MM:SS
    if len(val) >= 10 and val[4] == "-" and val[7] == "-":
        return val[:10]
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(val, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _normalize_phone(val: str) -> str:
    """Add leading 0 to 9-digit Israeli mobile numbers that lost it in Excel."""
    if val and val.isdigit() and len(val) == 9 and val[0] == "5":
        return "0" + val
    return val


def import_from_excel(path: str) -> List[Dict]:
    """Read recipients from תבנית ליהודה format Excel file."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Find header row: look for template-specific columns
    header_row_idx = None
    header = []
    for i, row in enumerate(rows):
        texts = [str(c).strip() if c else "" for c in row]
        if any(t in ("משפחה", "מספר מזהה", "נייד בעל") for t in texts):
            header = texts
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(
            "לא נמצאה שורת כותרת בפורמט תבנית ליהודה.\n"
            "הקובץ חייב להכיל עמודות: 'משפחה', 'פרטי', 'נייד בעל' וכו'."
        )

    # Map column indices — explicit template column names only
    col_map = {}
    for idx, h in enumerate(header):
        h_s = h.strip() if h else ""
        if not h_s:
            continue
        if h_s == "מספר מזהה":
            col_map["external_id"] = idx
        elif h_s == "מקור":
            col_map["source"] = idx
        elif h_s == "משפחה":
            col_map["family_name"] = idx
        elif h_s == "פרטי":
            col_map.setdefault("first_name", idx)
        elif h_s in ("ת. לידה", "ת.לידה") and "birth_date" not in col_map:
            col_map["birth_date"] = idx
        elif h_s in ("ת. לידה בן /בת הזוג", "ת. לידה בן/בת הזוג"):
            col_map["spouse_birth_date"] = idx
        elif h_s == "תז בעל":
            col_map["id_number"] = idx
        elif h_s == "תז אשה":
            col_map["spouse_id_number"] = idx
        # "ללא מקף" columns have clean digits — prefer them for phone storage
        elif h_s == "נייד בעל ללא מקף":
            col_map.setdefault("phone1", idx)
        elif h_s == "נייד אשה ללא מקף":
            col_map.setdefault("phone2", idx)
        elif h_s == "נייד בעל":
            col_map.setdefault("phone1", idx)
        elif h_s == "נייד אשה":
            col_map.setdefault("phone2", idx)
        elif h_s == "טלפון בבית":
            col_map.setdefault("phone3", idx)
        elif h_s == "טלפון נוסף":
            col_map.setdefault("phone3", idx)
        elif h_s == "ילדים בבית":
            col_map["children_home"] = idx
        elif h_s == "ילדים נשואים":
            col_map["children_married"] = idx
        elif h_s == "מספר ילדים":
            col_map["children_total"] = idx
        elif h_s == "מצב אישי":
            col_map["marital_status"] = idx
        elif h_s in ("אימייל", "email", "Email"):
            col_map["email"] = idx
        elif h_s == "בית כנסת":
            col_map["synagogue"] = idx
        elif h_s == "הוצאות דיור":
            col_map["housing_expenses"] = idx
        elif h_s == "הוצאות רפואיות":
            col_map["medical_expenses"] = idx
        elif h_s == "הכנסות":
            col_map["income"] = idx
        elif h_s == "פנוי לנפש":
            col_map["per_soul"] = idx
        elif "הקף משרה" in h_s or "היקף משרה" in h_s:
            col_map["work_scope"] = idx
        elif h_s == "סוג הורה":
            col_map["parent_type"] = idx
        elif h_s == "עיסוק בעל":
            col_map["occupation"] = idx
        elif h_s == "קהילה":
            col_map["area"] = idx
        elif h_s == "רחוב":
            col_map["street"] = idx
        elif h_s == "מספר" and "house_num" not in col_map:
            col_map["house_num"] = idx
        elif h_s == "שם נציג":
            col_map["representative"] = idx

    # Priority code column — unnamed, sits right before "משפחה". Holds the
    # distribution code (e.g. 4=קבוע, 3=עדיפות ראשונה, 2=שנייה, חובת בירור...).
    priority_idx = None
    _fam_idx = col_map.get("family_name")
    if _fam_idx is not None and _fam_idx - 1 >= 0 and not str(header[_fam_idx - 1] or "").strip():
        priority_idx = _fam_idx - 1

    results = []
    for row in rows[header_row_idx + 1:]:
        if not any(row):
            continue

        def cell(key):
            idx = col_map.get(key)
            if idx is None or idx >= len(row):
                return ""
            v = row[idx]
            return str(v).strip() if v is not None else ""

        def raw_cell(key):
            idx = col_map.get(key)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        def _int_cell(key):
            v = cell(key)
            try:
                return int(float(v)) if v else 0
            except (ValueError, TypeError):
                return 0

        # Name: combine משפחה + פרטי
        family = cell("family_name")
        first  = cell("first_name")
        name   = (family + " " + first).strip() if (family or first) else ""
        if not name or name in ("None", "0"):
            continue

        # Address: combine רחוב + מספר
        street = cell("street")
        house  = cell("house_num")
        address = (street + " " + house).strip() if street else house

        # Souls: ילדים בבית + 2 parents
        children_home = _int_cell("children_home")
        souls = children_home + 2

        # Priority code → priority number + frequency.
        # 4 = קבוע → weekly regular flow; 3/2/1/0 = one-time (priority tiers);
        # 'חובת בירור' (no digit) = one-time, kept as data only. The V/X letters
        # are ignored — only the number matters.
        priority = None
        priority_raw = ""
        if priority_idx is not None and priority_idx < len(row):
            rawv = row[priority_idx]
            if rawv is not None:
                priority_raw = str(rawv).strip()
                m = re.search(r"\d+", priority_raw)
                if m:
                    priority = int(m.group())
        if priority == 4:
            frequency = "שבועי"
        elif priority in (2, 3) or "בירור" in priority_raw:
            frequency = "חד-פעמי"
        else:
            # Codes 1/0, stray non-priority marks (V/X/text), or nothing at all
            # carry no real distribution meaning — don't invent 'חד-פעמי' for
            # them. Take the file's own frequency column if present, otherwise
            # leave it blank (an unmarked recipient stays unmarked).
            frequency = cell("frequency")

        results.append({
            "full_name":         name,
            "phone1":            _normalize_phone(cell("phone1")),
            "phone2":            _normalize_phone(cell("phone2")),
            "phone3":            _normalize_phone(cell("phone3")),
            "address":           address,
            "area":              cell("area"),
            "souls":             souls,
            "frequency":         frequency,
            "priority":          priority,
            "priority_raw":      priority_raw,
            "status":            cell("status") or "פעיל",
            "last_distribution": _parse_date(raw_cell("last_distribution")),
            "next_distribution": _parse_date(raw_cell("next_distribution")),
            "start_date":        _parse_date(raw_cell("start_date")),
            "external_id":       cell("external_id"),
            "source":            cell("source"),
            "birth_date":        _parse_date(raw_cell("birth_date")),
            "spouse_birth_date": _parse_date(raw_cell("spouse_birth_date")),
            "id_number":         cell("id_number"),
            "spouse_id_number":  cell("spouse_id_number"),
            "children_home":     children_home,
            "children_married":  _int_cell("children_married"),
            "children_total":    _int_cell("children_total"),
            "marital_status":    cell("marital_status"),
            "email":             cell("email"),
            "synagogue":         cell("synagogue"),
            "housing_expenses":  cell("housing_expenses"),
            "medical_expenses":  cell("medical_expenses"),
            "income":            cell("income"),
            "per_soul":          cell("per_soul"),
            "work_scope":        cell("work_scope"),
            "parent_type":       cell("parent_type"),
            "occupation":        cell("occupation"),
            "representative":    cell("representative"),
        })

    return results


def export_distribution_to_excel(recipients: List[Dict], dist_date: str) -> str:
    """Export distribution list to Excel. Returns saved file path."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "רשימת חלוקה"
    ws.sheet_view.rightToLeft = True

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="2563EB")
    header_align = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = ["מס'", "שם מלא", "טלפון 1", "טלפון 2", "טלפון 3", "אזור", "נפשות", "✓ ביצוע"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border
    ws.row_dimensions[1].height = 22

    alt_fill = PatternFill("solid", fgColor="F8FAFC")
    normal_fill = PatternFill("solid", fgColor="FFFFFF")
    # Build the style objects ONCE and reuse them. Creating a fresh Alignment per
    # cell meant ~32k objects for a few-thousand-row export, which took seconds.
    cell_align = Alignment(horizontal="right", vertical="center")

    for i, rec in enumerate(recipients, 1):
        row = [i, rec.get("full_name", ""), rec.get("phone1", ""),
               rec.get("phone2", ""), rec.get("phone3", ""),
               rec.get("area", ""), rec.get("souls", ""), ""]
        ws.append(row)
        fill = alt_fill if i % 2 == 0 else normal_fill
        for cell in ws[i + 1]:
            cell.alignment = cell_align
            cell.fill = fill
            cell.border = border
        ws.row_dimensions[i + 1].height = 18

    col_widths = [6, 26, 16, 16, 16, 10, 8, 10]
    for col, width in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(1, col).column_letter].width = width

    ws.insert_rows(1)
    ws.merge_cells("A1:H1")
    title_cell = ws["A1"]
    title_cell.value = f"רשימת חלוקה — {dist_date}"
    title_cell.font = Font(bold=True, size=14, color="1D4ED8")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # Save to exports subfolder next to the app
    exports_dir = _app_dir() / "exports"
    exports_dir.mkdir(exist_ok=True)
    filename = f"חלוקה_{dist_date.replace('/', '-')}_{datetime.now().strftime('%H%M%S')}.xlsx"
    path = str(exports_dir / filename)
    wb.save(path)
    return path


# Full recipient field set for the detailed export (key, Hebrew header).
_FULL_FIELDS = [
    ("full_name", "שם מלא"), ("priority", "עדיפות"),
    ("phone1", "טלפון 1"), ("phone2", "טלפון 2"), ("phone3", "טלפון 3"),
    ("address", "כתובת"), ("area", "אזור"), ("souls", "נפשות"),
    ("frequency", "תדירות"), ("last_distribution", "חלוקה אחרונה"),
    ("next_distribution", "חלוקה הבאה"), ("status", "סטטוס"), ("notes", "הערות"),
    ("external_id", "מס' מזהה"), ("source", "מקור"),
    ("birth_date", "ת. לידה"), ("spouse_birth_date", "ת. לידה בן/בת זוג"),
    ("id_number", "ת.ז. בעל"), ("spouse_id_number", "ת.ז. אשה"),
    ("children_home", "ילדים בבית"), ("children_married", "ילדים נשואים"),
    ("children_total", "מספר ילדים"), ("marital_status", "מצב אישי"),
    ("email", "אימייל"), ("synagogue", "בית כנסת"),
    ("housing_expenses", "הוצ' דיור"), ("medical_expenses", "הוצ' רפואיות"),
    ("income", "הכנסות"), ("per_soul", "פנוי לנפש"),
    ("work_scope", "היקף משרה"), ("parent_type", "סוג הורה"),
    ("occupation", "עיסוק בעל"), ("representative", "שם נציג"),
]

_PRIORITY_LABELS = {4: "קבוע", 3: "עדיפות ראשונה", 2: "עדיפות שנייה"}


def _priority_text(rec: Dict) -> str:
    pr = rec.get("priority")
    if pr in _PRIORITY_LABELS:
        return _PRIORITY_LABELS[pr]
    return "חובת בירור" if "בירור" in (rec.get("priority_raw") or "") else ""


def _fmt_date(v) -> str:
    s = str(v or "")
    if len(s) >= 10 and s[4] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s


def export_full_distribution_to_excel(recipients: List[Dict], dist_date: str) -> str:
    """Detailed export of a distribution: EVERY recipient field stored in the app,
    plus a 'קיבל חלוקה' column marking that the people listed received. Returns
    the saved file path."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "חלוקה מלאה"
    ws.sheet_view.rightToLeft = True

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="2563EB")
    got_fill = PatternFill("solid", fgColor="16A34A")   # green for 'קיבל חלוקה'
    header_align = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = ["מס'", "קיבל חלוקה"] + [h for _, h in _FULL_FIELDS]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border
    ws[1][1].fill = got_fill   # highlight the 'קיבל חלוקה' header
    ws.row_dimensions[1].height = 22

    alt_fill = PatternFill("solid", fgColor="F8FAFC")
    normal_fill = PatternFill("solid", fgColor="FFFFFF")
    got_cell_fill = PatternFill("solid", fgColor="DCFCE7")
    cell_align = Alignment(horizontal="right", vertical="center")
    _DATE_KEYS = {"last_distribution", "next_distribution", "birth_date", "spouse_birth_date"}

    for i, rec in enumerate(recipients, 1):
        row = [i, "כן"]
        for key, _ in _FULL_FIELDS:
            if key == "priority":
                row.append(_priority_text(rec))
            elif key in _DATE_KEYS:
                row.append(_fmt_date(rec.get(key)))
            else:
                v = rec.get(key)
                row.append("" if v is None else v)
        ws.append(row)
        fill = alt_fill if i % 2 == 0 else normal_fill
        for cell in ws[i + 1]:
            cell.alignment = cell_align
            cell.fill = fill
            cell.border = border
        ws[i + 1][1].fill = got_cell_fill   # the 'קיבל חלוקה' cell
        ws.row_dimensions[i + 1].height = 18

    # column widths — index, got, then a sensible width per field
    widths = [6, 12] + [26 if k == "address" else 20 if k in ("full_name", "email", "synagogue")
                        else 14 for k, _ in _FULL_FIELDS]
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(1, col).column_letter].width = width

    ncols = len(headers)
    last_col = ws.cell(1, ncols).column_letter
    ws.insert_rows(1)
    ws.merge_cells(f"A1:{last_col}1")
    title_cell = ws["A1"]
    title_cell.value = f"רשימת חלוקה מלאה — {dist_date}  (המופיעים קיבלו חלוקה)"
    title_cell.font = Font(bold=True, size=14, color="1D4ED8")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A3"   # keep title + header visible while scrolling

    exports_dir = _app_dir() / "exports"
    exports_dir.mkdir(exist_ok=True)
    filename = f"חלוקה_מלאה_{dist_date.replace('/', '-')}_{datetime.now().strftime('%H%M%S')}.xlsx"
    path = str(exports_dir / filename)
    wb.save(path)
    return path
