/* מנהל חלוקה — מסך השבועות (שלב 1: קריאה בלבד).
   הדף לא מחשב שום כלל בעצמו: הוא מבקש מהשרת את הרשימות ומציג אותן.
   כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד. */
(function () {
  "use strict";

  var STEP = 8;                         // כמה שבועות נוספים בכל לחיצה על "עוד שבועות"
  var state = { weeks: STEP, plan: null, people: null, index: 0, who: null, details: {}, token: 0 };

  var TYPE = { "שבועי": "w1", "דו-שבועי": "w2", "תלת-שבועי": "w3", "חודשי": "w4" };
  var ROLE_TEXT = { main: "מקבל", reserve: "ברזרבה", out: "לא בשבוע הזה" };
  var OUT_GROUPS = [
    ["reg_cut", "קבועים שתורם הגיע, ולא נשאר להם מקום"],
    ["no_portions", "אין מנות בשבוע הזה"],
    ["one_queue", "חד־פעמיים שמחכים בתור"],
    ["reg_wait", "קבועים שתורם עוד לא הגיע"],
    ["one_pause", "חד־פעמיים בהפסקה אחרי שקיבלו"]
  ];

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  function dm(iso) { var p = iso.split("-"); return Number(p[2]) + "/" + Number(p[1]); }
  function typeOf(kind, freq) { return kind === "onetime" ? "one" : (TYPE[freq] || "w1"); }

  function getJSON(url) {
    return fetch(url, { headers: { "Accept": "application/json" } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) {
          var err = new Error(body.message || body.detail || ("שגיאה " + r.status));
          err.status = r.status;
          throw err;
        }
        return body;
      });
    });
  }

  function notice(text, isError) {
    var n = $("notice");
    n.textContent = text || "";
    n.className = "notice" + (isError ? " error" : "");
    n.hidden = !text;
  }

  // ── loading ────────────────────────────────────────────────────────────────
  function load(keepDate) {
    return getJSON("/api/plan?weeks=" + state.weeks).then(function (plan) {
      state.plan = plan;
      state.details = {};
      if (keepDate) {
        var i = plan.weeks.findIndex(function (w) { return w.date === keepDate; });
        state.index = i >= 0 ? i : 0;
      } else if (state.index >= plan.weeks.length) {
        state.index = 0;
      }
      if (plan.closed_now && plan.closed_now.length) {
        notice("השבוע של " + plan.closed_now.map(dm).join(", ") +
               " עבר, והרשימה שלו נכנסה להיסטוריה כמו שהייתה.");
      }
      render();
      return loadDetail();
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את הרשימות מהשרת. " + (e.message || ""), true);
    });
  }

  function loadDetail() {
    var week = state.plan.weeks[state.index];
    if (!week) { return Promise.resolve(); }
    if (state.details[week.date]) { renderWeek(); return Promise.resolve(); }
    var token = ++state.token;
    renderWeek();
    return getJSON("/api/week?date=" + week.date).then(function (detail) {
      state.details[week.date] = detail;
      if (token === state.token) { renderWeek(); }
    }).catch(function (e) {
      if (e.status === 404 && !state.retried) {          // the week closed meanwhile: start over, once
        state.retried = true;
        state.index = 0;
        return load();
      }
      notice("לא הצלחתי לקבל את פרטי השבוע. " + (e.message || ""), true);
    }).then(function () { if (state.details[week.date]) { state.retried = false; } });
  }

  function loadPeople() {
    return getJSON("/api/people").then(function (p) { state.people = p; }).catch(function () { state.people = null; });
  }

  // ── the strip of weeks ─────────────────────────────────────────────────────
  function render() {
    var plan = state.plan;
    $("today").textContent = "היום " + dm(plan.today) + " · מכינים את רביעי " + dm(plan.current_week) +
      " · ברירת המחדל: " + plan.defaults.portions + " מנות ו־" + plan.defaults.reserve + " ברזרבה";
    var box = $("weeks");
    var keepScroll = box.scrollLeft;
    clear(box);
    plan.weeks.forEach(function (w, i) {
      var b = el("button", "wk");
      b.type = "button";
      b.setAttribute("aria-pressed", i === state.index ? "true" : "false");
      var d = el("div", "d", i === 0 ? "השבוע " : "רביעי ");
      d.appendChild(el("b", null, dm(w.date)));
      b.appendChild(d);
      var bar = el("div", "bar");
      [["שבועי", "w1"], ["דו-שבועי", "w2"], ["תלת-שבועי", "w3"], ["חודשי", "w4"], ["חד-פעמי", "one"]].forEach(function (t) {
        var n = w.counts[t[0]] || 0;
        var col = el("i", "t-" + t[1]);
        col.style.height = Math.round(Math.min(1, n / Math.max(1, w.portions) * 1.6) * 36) + "px";
        col.title = t[0] + ": " + n;
        bar.appendChild(col);
      });
      b.appendChild(bar);
      b.appendChild(el("div", "n", w.main_regulars + " קבועים · " + w.main_one_timers + " חד״פ"));
      if (w.empty_portions > 0 || w.cut) {
        var flag = el("span", "flag", "⚠");
        flag.title = w.warnings.join(" · ");
        b.appendChild(flag);
      }
      if (state.who) {
        if (w.main.indexOf(state.who) >= 0) { b.appendChild(el("span", "who")); }
        else if (w.reserve_list.indexOf(state.who) >= 0) { b.appendChild(el("span", "who res")); }
      }
      b.addEventListener("click", function () { state.index = i; render(); loadDetail(); });
      box.appendChild(b);
    });
    var more = el("button", "wk more", "עוד שבועות");
    more.type = "button";
    more.addEventListener("click", function () {
      state.weeks += STEP;
      load(state.plan.weeks[state.index].date).then(function () {
        var all = $("weeks").querySelectorAll(".wk");
        if (all.length > 1) { all[all.length - 2].scrollIntoView({ block: "nearest", inline: "end" }); }
      });
    });
    box.appendChild(more);
    box.scrollLeft = keepScroll;
    $("whoLegend").hidden = !state.who;
  }

  // ── the selected week ──────────────────────────────────────────────────────
  function chip(entry) {
    var b = el("button", "chip t-" + typeOf(entry.kind, entry.freq) + (entry.guid === state.who ? " sel" : ""), entry.name);
    b.type = "button";
    b.addEventListener("click", function () { state.who = entry.guid; render(); renderWeek(); });
    return b;
  }
  function group(title, entries) {
    var g = el("div", "grp");
    var h = el("h4", null, title + " ");
    h.appendChild(el("b", null, String(entries.length)));
    g.appendChild(h);
    var chips = el("div", "chips");
    entries.forEach(function (e) { chips.appendChild(chip(e)); });
    g.appendChild(chips);
    return g;
  }

  function renderWeek() {
    var week = state.plan.weeks[state.index];
    var detail = state.details[week.date];
    $("weekPanel").hidden = false;
    $("weekTitle").textContent = (state.index === 0 ? "השבוע, " : "") + "רביעי " + dm(week.date);
    $("weekNumbers").textContent = week.main.length + " מקבלים מתוך " + week.portions + " מנות · " +
      week.regulars_due + " קבועים שתורם הגיע · " + week.main_one_timers + " חד־פעמיים · " +
      week.reserve_list.length + " ברזרבה";
    var warn = $("warnings");
    clear(warn);
    week.warnings.forEach(function (text) { warn.appendChild(el("div", "warn", text)); });
    $("cMain").textContent = week.main.length + " / " + week.portions;
    $("cRes").textContent = String(week.reserve_list.length);

    var main = $("main"), res = $("res"), out = $("out");
    clear(main); clear(res); clear(out);
    if (!detail) {
      $("cOut").textContent = "";
      main.appendChild(el("p", "empty", "טוען את הרשימה…"));
      renderWhy(null);
      return;
    }
    var regs = detail.main.filter(function (e) { return e.kind === "regular"; });
    var ones = detail.main.filter(function (e) { return e.kind === "onetime"; });
    if (regs.length) { main.appendChild(group("קבועים", regs)); }
    if (ones.length) { main.appendChild(group("חד־פעמיים, לפי התור", ones)); }
    if (week.empty_portions > 0) {
      var g = el("div", "grp");
      var h = el("h4", null, "מנות בלי מקבל ");
      h.appendChild(el("b", null, String(week.empty_portions)));
      g.appendChild(h);
      var slots = el("div", "chips");
      for (var i = 0; i < Math.min(week.empty_portions, 60); i++) { slots.appendChild(el("span", "slot")); }
      g.appendChild(slots);
      main.appendChild(g);
    }
    if (!detail.main.length && week.empty_portions <= 0) { main.appendChild(el("p", "empty", "אין מקבלים בשבוע הזה.")); }

    if (detail.reserve_list.length) {
      var chips = el("div", "chips");
      detail.reserve_list.forEach(function (e) { chips.appendChild(chip(e)); });
      res.appendChild(chips);
    } else {
      res.appendChild(el("p", "empty", "אין רזרבה בשבוע הזה."));
    }

    $("cOut").textContent = String(detail.out.length);
    OUT_GROUPS.forEach(function (pair) {
      var list = detail.out.filter(function (e) { return e.group === pair[0]; });
      if (list.length) { out.appendChild(group(pair[1], list)); }
    });
    if (!detail.out.length) { out.appendChild(el("p", "empty", "כל מי שמשתתף ברשימות נמצא בשבוע הזה.")); }
    if (state.people && state.people.others.length) {
      out.appendChild(el("p", "others", "ועוד " + state.people.others.length +
        " כרטיסים שלא נכנסים לרשימות אוטומטית (בלי תדירות, בלי עדיפות ראשונה או שנייה, או מושהים). אפשר למצוא אותם בחיפוש."));
    }
    renderWhy(detail);
  }

  function findEntry(detail, guid) {
    var lists = [detail.main, detail.reserve_list, detail.out];
    for (var i = 0; i < lists.length; i++) {
      for (var j = 0; j < lists[i].length; j++) {
        if (lists[i][j].guid === guid) { return lists[i][j]; }
      }
    }
    return null;
  }

  function renderWhy(detail) {
    var box = $("why");
    clear(box);
    box.className = "why";
    if (!state.who) {
      box.appendChild(el("b", null, "לחצו על שם, או חפשו אותו למעלה"));
      box.appendChild(document.createTextNode("ותראו במשפט אחד למה הוא נמצא איפה שהוא, ובאילו שבועות הוא מקבל."));
      return;
    }
    var week = state.plan.weeks[state.index];
    var entry = detail ? findEntry(detail, state.who) : null;
    if (entry) {
      box.appendChild(el("b", null, entry.name + " · רביעי " + dm(week.date) + ": " + ROLE_TEXT[entry.role]));
      box.appendChild(document.createTextNode(entry.why));
    } else {
      var other = state.people && state.people.others.filter(function (p) { return p.guid === state.who; })[0];
      var known = state.people && state.people.participants.filter(function (p) { return p.guid === state.who; })[0];
      if (other) {
        box.appendChild(el("b", null, other.name + ": לא משתתף ברשימות"));
        box.appendChild(document.createTextNode(other.why));
        return;
      }
      box.appendChild(el("b", null, (known ? known.name : "המקבל שנבחר") + " · רביעי " + dm(week.date)));
      box.appendChild(document.createTextNode(detail ? "לא נמצא ברשימות של השבוע הזה." : "טוען…"));
    }
    var gets = [], waits = [];
    state.plan.weeks.forEach(function (w) {
      if (w.main.indexOf(state.who) >= 0) { gets.push(dm(w.date)); }
      else if (w.reserve_list.indexOf(state.who) >= 0) { waits.push(dm(w.date)); }
    });
    var n = state.plan.weeks.length;
    var when = gets.length ? "ב־" + n + " השבועות שמוצגים הוא מקבל ב: " + gets.join(", ") + "."
                           : "ב־" + n + " השבועות שמוצגים הוא לא מקבל.";
    if (waits.length) { when += " ברזרבה ב: " + waits.join(", ") + "."; }
    box.appendChild(el("div", "when", when));
  }

  // ── search ─────────────────────────────────────────────────────────────────
  function norm(s) { return String(s || "").replace(/["'׳״\-־]/g, "").replace(/\s+/g, " ").trim().toLowerCase(); }

  function showHits() {
    var q = norm($("q").value);
    var box = $("hits");
    clear(box);
    if (!q || !state.people) { box.hidden = true; return; }
    var words = q.split(" ");
    function match(p) { var n = norm(p.name); return words.every(function (w) { return n.indexOf(w) >= 0; }); }
    var found = state.people.participants.filter(match).map(function (p) { return { p: p, part: true }; })
      .concat(state.people.others.filter(match).map(function (p) { return { p: p, part: false }; }));
    found.slice(0, 12).forEach(function (hit) {
      var li = el("li");
      var b = el("button");
      b.type = "button";
      if (hit.part) { b.appendChild(el("i", "sw t-" + typeOf(hit.p.kind, hit.p.freq))); }
      b.appendChild(el("span", null, hit.p.name));
      b.appendChild(el("small", null, hit.part ? (hit.p.kind === "onetime" ? "חד־פעמי" : (hit.p.freq || "קבוע")) : "לא משתתף"));
      b.addEventListener("click", function () {
        state.who = hit.p.guid;
        $("q").value = "";
        box.hidden = true;
        render();
        renderWeek();
        $("why").scrollIntoView({ block: "nearest" });
      });
      li.appendChild(b);
      box.appendChild(li);
    });
    if (!found.length) { box.appendChild(el("li", "none", "לא נמצא שם כזה")); }
    else if (found.length > 12) { box.appendChild(el("li", "none", "ועוד " + (found.length - 12) + ". הקלידו עוד אותיות.")); }
    box.hidden = false;
  }

  $("q").addEventListener("input", showHits);
  $("q").addEventListener("keydown", function (e) { if (e.key === "Escape") { $("q").value = ""; showHits(); } });
  document.addEventListener("click", function (e) { if (!e.target.closest(".search")) { $("hits").hidden = true; } });

  loadPeople().then(function () { return load(); });
}());
