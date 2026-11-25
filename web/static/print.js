/* מנהל חלוקה — דף ההדפסה: עמוד A4 לכל שבוע בטווח שנבחר.
   הכתובת: /print?from=YYYY-MM-DD&weeks=N. הדף רק מציג את מה שהשרת מחזיר ב־/api/print;
   כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד. */
(function () {
  "use strict";

  var FUND = "קופה של צדקה הר יונה";
  var HEADERS = ["#", "שם", "טלפון", "נפשות", "✓"];
  var COLUMNS = ["c-n", "c-name", "c-phone", "c-souls", "c-box"];
  var FIT_STEPS = 4;                    // print.css: .sheet.fit-1 .. .fit-4
  var PHONE_CHARS = 26;                 // the widest the phones' column gets, in characters
  var PHONE_FONT = 0.9;                 // print.css: td.c-phone is set at .86 of the sheet's size (plus a little air)

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }
  function full(iso) { var p = iso.split("-"); return p[2] + "/" + p[1] + "/" + p[0]; }
  function two(n) { return (n < 10 ? "0" : "") + n; }

  function notice(text) {
    var n = $("notice");
    n.textContent = text || "";
    n.hidden = !text;
  }

  function phonesOf(row) {
    return String(row.phones || "").split(" · ").filter(function (p) { return p; });
  }

  // How wide the phones' column has to be, in characters: for one number, and for two side
  // by side. The same for all the tables of a week, so that they line up; fit() picks
  // between the two, and the name gets all that is left.
  function phoneWidths(rows) {
    var one = 5, two = 5;
    rows.forEach(function (r) {
      var list = phonesOf(r);
      one = Math.max(one, (list[0] || "").length);
      two = Math.max(two, list.slice(0, 2).join(" ").length);
    });
    return { one: Math.min(one, PHONE_CHARS), two: Math.min(two, PHONE_CHARS) };
  }

  function table(rows, widths) {
    var t = el("table", "list");
    var group = t.appendChild(el("colgroup"));
    COLUMNS.forEach(function (c) {
      var col = group.appendChild(el("col", c));
      if (c === "c-phone") {
        col.setAttribute("data-one", String(widths.one));
        col.setAttribute("data-two", String(widths.two));
      }
    });
    var head = el("tr");
    HEADERS.forEach(function (h, i) { head.appendChild(el("th", COLUMNS[i], h)); });
    t.appendChild(el("thead")).appendChild(head);
    var body = t.appendChild(el("tbody"));
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", "c-n", String(r.n)));
      tr.appendChild(el("td", "c-name", r.name));
      var phones = el("td", "c-phone");
      phonesOf(r).forEach(function (p) {
        var one = el("span", "ph", p);
        one.dir = "ltr";                         // digits and dashes keep their order inside Hebrew
        phones.appendChild(one);
        phones.appendChild(document.createTextNode(" "));
      });
      tr.appendChild(phones);
      tr.appendChild(el("td", "c-souls", r.souls === "" || r.souls === null || r.souls === undefined ? "" : String(r.souls)));
      tr.appendChild(el("td", "c-box")).appendChild(el("span", "box"));
      body.appendChild(tr);
    });
    return t;
  }

  // Two tables side by side, half the rows in each, so that 52 names fit one A4 page.
  function halves(rows, widths) {
    var cols = el("div", "cols");
    var mid = Math.ceil(rows.length / 2);
    [rows.slice(0, mid), rows.slice(mid)].forEach(function (part) {
      var side = el("div", "col");
      if (part.length) { side.appendChild(table(part, widths)); }
      cols.appendChild(side);
    });
    return cols;
  }

  function sheet(week, made) {
    var outer = el("section", "sheet");
    var s = outer.appendChild(el("div", "sheet-in"));
    var head = el("header", "sheet-head");
    head.appendChild(el("h2", null, FUND + " · חלוקת רביעי " + full(week.date)));
    head.appendChild(el("p", "numbers", week.main.length + " מקבלים · " + week.reserve_list.length +
                        " ברזרבה · " + week.portions + " מנות · הופק ב־" + made));
    s.appendChild(head);
    // notes for the manager: on the screen only, above the part that is measured and printed
    (week.warnings || []).forEach(function (w) { outer.insertBefore(el("p", "warn no-print", w), s); });

    var widths = phoneWidths(week.main.concat(week.reserve_list));
    if (week.main.length) {
      s.appendChild(halves(week.main, widths));
    } else {
      s.appendChild(el("p", "none", "אין מקבלים בשבוע הזה."));
    }
    if (week.reserve_list.length) {
      s.appendChild(el("h3", null, "רזרבה · לפי הסדר, נכנסים רק אם מישהו לא מגיע"));
      s.appendChild(halves(week.reserve_list, widths));
    }
    return outer;
  }

  function phoneColumns(outer, both) {
    Array.prototype.forEach.call(outer.querySelectorAll("col.c-phone"), function (col) {
      var chars = Number(col.getAttribute(both ? "data-two" : "data-one"));
      col.style.width = "calc(" + (chars * PHONE_FONT).toFixed(1) + "ch + 1.5em)";
    });
  }

  // Each week gets the largest letters with which it still fits one page. At every size
  // two layouts are tried: the phones' column wide enough for two numbers side by side, and
  // then narrow (a second number goes under the first, the names get more room). The sheet
  // on the screen is exactly as wide as the paper, so what is measured here is what the
  // printer gets. A week that fits at no size simply runs on to a second page.
  function fit(pages) {
    var probe = document.body.appendChild(el("div", "probe"));
    var limit = probe.offsetHeight;
    Array.prototype.forEach.call(pages.children, function (outer) {
      var inner = outer.querySelector(".sheet-in");
      for (var step = 0; step <= FIT_STEPS; step++) {
        outer.className = "sheet" + (step ? " fit-" + step : "");
        phoneColumns(outer, true);
        if (inner.offsetHeight <= limit) { return; }
        phoneColumns(outer, false);
        if (inner.offsetHeight <= limit) { return; }
      }
      phoneColumns(outer, true);
    });
    probe.remove();
  }

  function show(weeks) {
    var now = new Date();
    var made = two(now.getDate()) + "/" + two(now.getMonth() + 1) + "/" + now.getFullYear() + " " +
               two(now.getHours()) + ":" + two(now.getMinutes());
    var pages = $("pages");
    weeks.forEach(function (w) { pages.appendChild(sheet(w, made)); });
    fit(pages);
    var first = full(weeks[0].date), last = full(weeks[weeks.length - 1].date);
    $("summary").textContent = weeks.length === 1 ? "רביעי " + first + " · עמוד לשבוע"
      : weeks.length + " שבועות, מ־" + first + " עד " + last + " · עמוד לכל שבוע";
    document.title = "חלוקת רביעי " + first.replace(/\//g, "-") + (weeks.length > 1 ? " עד " + last.replace(/\//g, "-") : "");
    $("go").disabled = false;
  }

  function fail(text) {
    $("summary").textContent = "";
    notice(text);
  }

  $("go").addEventListener("click", function () { window.print(); });

  var params = new URLSearchParams(window.location.search);
  var from = params.get("from") || "";
  var count = parseInt(params.get("weeks") || "1", 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !(count >= 1)) {
    fail("חסר בכתובת מאיזה שבוע להדפיס. חזרו למסך השבועות ולחצו שם על \"הדפס\".");
    return;
  }
  fetch("/api/print?from=" + encodeURIComponent(from) + "&weeks=" + count, { headers: { "Accept": "application/json" } })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) {
          throw new Error(body.message || (typeof body.detail === "string" ? body.detail : "") || ("שגיאה " + r.status));
        }
        return body;
      });
    })
    .then(function (body) {
      if (!body.weeks || !body.weeks.length) { fail("אין שבועות בטווח הזה."); return; }
      show(body.weeks);
    })
    .catch(function (e) { fail("לא הצלחתי לקבל את הרשימות. " + (e.message || "")); });
}());
