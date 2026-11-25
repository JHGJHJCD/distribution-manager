/* מנהל חלוקה — מסך השבועות (שלב 2: גם שינויים ביד, מספר מנות לשבוע, הדפסה ואקסל).
   הדף לא מחשב שום כלל בעצמו: הוא מבקש מהשרת את הרשימות ומציג אותן, ושולח לשרת
   את מה שהמנהל קבע. כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד. */
(function () {
  "use strict";

  var STEP = 8;                         // כמה שבועות נוספים בכל לחיצה על "עוד שבועות"
  var MAX_NUMBER = 2000;                // התקרה של מנות / רזרבה (כמו בשרת)
  var NAMES_SHOWN = 6;                  // כמה שמות לכל היותר בהערה "השתנה מאז ההדפסה"
  var state = { weeks: STEP, plan: null, people: null, index: 0, who: null, details: {}, token: 0,
                busy: false, toolsFor: null };

  var TYPE = { "שבועי": "w1", "דו-שבועי": "w2", "תלת-שבועי": "w3", "חודשי": "w4" };
  var ROLE_TEXT = { main: "מקבל", reserve: "ברזרבה", out: "לא בשבוע הזה" };
  var OUT_GROUPS = [
    ["removed", "הוסרו ביד מהשבוע הזה"],
    ["reg_cut", "קבועים שתורם הגיע, ולא נשאר להם מקום"],
    ["no_portions", "אין מנות בשבוע הזה"],
    ["one_queue", "חד־פעמיים שמחכים בתור"],
    ["reg_wait", "קבועים שתורם עוד לא הגיע"],
    ["one_pause", "חד־פעמיים בהפסקה אחרי שקיבלו"]
  ];
  // מה אפשר לעשות ביד למי שנמצא ברשימה / ברזרבה / מחוץ לשבוע: [הכיתוב, הפעולה שנשלחת לשרת]
  var ACTIONS = {
    main: [["העבר לרזרבה", "reserve"], ["הסר מהשבוע", "remove"]],
    reserve: [["הכנס לרשימה", "add"], ["הסר מהשבוע", "remove"]],
    out: [["הוסף לשבוע הזה", "add"], ["שים ברזרבה", "reserve"]]
  };

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
  function currentWeek() { return state.plan ? state.plan.weeks[state.index] : null; }

  function answer(r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      if (!r.ok) {
        var text = body.message || (typeof body.detail === "string" ? body.detail : "") ||
          (r.status === 422 ? "הנתונים שנשלחו לא תקינים" : "שגיאה " + r.status);
        var err = new Error(text);
        err.status = r.status;
        throw err;
      }
      return body;
    });
  }
  function getJSON(url) {
    return fetch(url, { headers: { "Accept": "application/json" } }).then(answer);
  }
  // כל כתיבה נשלחת עם הכותרת X-Haluka: אתר אחר שפתוח בדפדפן לא יכול לשלוח אותה
  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json", "X-Haluka": "1" },
      body: JSON.stringify(body)
    }).then(answer);
  }

  function notice(text, isError) {
    var n = $("notice");
    n.textContent = text || "";
    n.className = "notice" + (isError ? " error" : "");
    n.hidden = !text;
  }

  function setBusy(on) {
    state.busy = on;
    document.body.classList.toggle("busy", on);
  }

  // ── loading ────────────────────────────────────────────────────────────────
  // The strip and the selected week arrive together and are drawn once, so the screen
  // does not blink after a change; the week and the person that were chosen stay chosen.
  function load(keepDate) {
    return getJSON("/api/plan?weeks=" + state.weeks).then(function (plan) {
      var index = state.index;
      if (keepDate) {
        var i = plan.weeks.findIndex(function (w) { return w.date === keepDate; });
        index = i >= 0 ? i : 0;
      } else if (index >= plan.weeks.length) {
        index = 0;
      }
      var date = plan.weeks[index].date;
      return getJSON("/api/week?date=" + date).catch(function () { return null; }).then(function (detail) {
        state.plan = plan;
        state.index = index;
        state.details = {};
        if (detail) { state.details[date] = detail; }
        if (plan.closed_now && plan.closed_now.length) {
          notice("השבוע של " + plan.closed_now.map(dm).join(", ") +
                 " עבר, והרשימה שלו נכנסה להיסטוריה כמו שהייתה.");
        }
        render();
        return loadDetail();
      });
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את הרשימות מהשרת. " + (e.message || ""), true);
    });
  }

  function loadDetail() {
    var week = currentWeek();
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

  function refresh() {
    var week = currentWeek();
    state.toolsFor = null;                               // the number boxes follow the server again
    return load(week ? week.date : null);
  }

  // One change by hand: send it, then ask for everything again (the server recomputes all
  // the weeks). A refusal comes back as a sentence in Hebrew and is shown as it is.
  function change(url, body) {
    if (state.busy) { return Promise.resolve(false); }
    setBusy(true);
    return postJSON(url, body).then(function () {
      notice("");
      return refresh().then(function () { return true; });
    }).catch(function (e) {
      notice("השינוי לא נשמר. " + (e.message || ""), true);
      return false;
    }).then(function (ok) { setBusy(false); return ok; });
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
      if (w.manual_count > 0) {
        var hand = el("span", "hand", "✋");
        hand.title = "יש בשבוע הזה שינויים ביד";
        b.appendChild(hand);
      }
      var bar = el("div", "bar");
      [["שבועי", "w1"], ["דו-שבועי", "w2"], ["תלת-שבועי", "w3"], ["חודשי", "w4"], ["חד-פעמי", "one"]].forEach(function (t) {
        var n = w.counts[t[0]] || 0;
        var col = el("i", "t-" + t[1]);
        col.style.height = Math.round(Math.min(1, n / Math.max(1, w.portions) * 1.6) * 36) + "px";
        col.title = t[0] + ": " + n;
        bar.appendChild(col);
      });
      b.appendChild(bar);
      var n = el("div", "n");
      n.appendChild(el("span", null, w.main_regulars + " קבועים"));
      n.appendChild(el("span", null, w.main_one_timers + " חד״פ"));
      b.appendChild(n);
      var changed = !!(w.print && w.print.changed);
      if (w.empty_portions > 0 || w.cut || changed) {
        var flag = el("span", "flag", "⚠");
        flag.title = w.warnings.concat(changed ? ["השתנה מאז ההדפסה"] : []).join(" · ");
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
      load(currentWeek().date).then(function () {
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
    var b = el("button", "chip t-" + typeOf(entry.kind, entry.freq) + (entry.manual ? " manual" : "") +
               (entry.guid === state.who ? " sel" : ""), entry.name);
    b.type = "button";
    if (entry.manual) { b.title = "נקבע ביד"; }
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

  // "2026-11-25 20:30" -> "25/11 בשעה 20:30"
  function stamp(text) {
    var parts = String(text || "").split(" ");
    return /^\d{4}-\d{2}-\d{2}$/.test(parts[0]) ? dm(parts[0]) + (parts[1] ? " בשעה " + parts[1] : "") : String(text || "");
  }
  function nameList(names, count) {
    if (!names) { return String(count); }                // the strip knows only how many
    var shown = names.slice(0, NAMES_SHOWN).join(", ");
    return names.length > NAMES_SHOWN ? shown + " ועוד " + (names.length - NAMES_SHOWN) : shown;
  }
  // The reminder "changed since it was printed" (it never holds anything in place), or a
  // quiet line when the list is still the one on the paper.
  function printNote(p) {
    if (!p) { return null; }
    var excel = p.how === "excel";
    if (!p.changed) {
      return el("div", "printed", (excel ? "הורד לאקסל ב־" : "הודפס ב־") + stamp(p.printed_at) +
                " · הרשימה לא השתנתה מאז");
    }
    var parts = [];
    if (p.added) { parts.push((p.added === 1 ? "נוסף " : "נוספו ") + nameList(p.added_names, p.added)); }
    if (p.removed) { parts.push((p.removed === 1 ? "יצא " : "יצאו ") + nameList(p.removed_names, p.removed)); }
    return el("div", "warn", (excel ? "השתנה מאז ההורדה לאקסל ב־" : "השתנה מאז ההדפסה ב־") +
              stamp(p.printed_at) + ": " + parts.join(" · "));
  }

  function renderTools(week) {
    var key = week.date + "|" + week.portions + "|" + week.reserve;
    if (state.toolsFor !== key) {                        // never over a number being typed
      state.toolsFor = key;
      $("nPortions").value = week.portions;
      $("nReserve").value = week.reserve;
    }
    $("resetNumbers").hidden = !week.numbers_set;
  }

  function renderWeek() {
    var week = currentWeek();
    var detail = state.details[week.date];
    $("weekPanel").hidden = false;
    $("weekTitle").textContent = (state.index === 0 ? "השבוע, " : "") + "רביעי " + dm(week.date);
    $("weekNumbers").textContent = week.main.length + " מקבלים מתוך " + week.portions + " מנות · " +
      week.regulars_due + " קבועים שתורם הגיע · " + week.main_one_timers + " חד־פעמיים · " +
      week.reserve_list.length + " ברזרבה" +
      (week.numbers_set ? " · המספרים נקבעו ביד לשבוע הזה" : "") +
      (week.manual_count === 1 ? " · שינוי אחד ביד" : week.manual_count > 1 ? " · " + week.manual_count + " שינויים ביד" : "");
    renderTools(week);
    var warn = $("warnings");
    clear(warn);
    week.warnings.forEach(function (text) { warn.appendChild(el("div", "warn", text)); });
    var note = printNote(detail ? detail.print : week.print);
    if (note) { warn.appendChild(note); }
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
        " כרטיסים שלא נכנסים לרשימות אוטומטית (בלי תדירות, בלי עדיפות ראשונה או שנייה, או מושהים)." +
        " אפשר למצוא אותם בחיפוש, ולהוסיף ביד לשבוע מי שפעיל."));
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

  // The buttons under the explanation: what can be set by hand for this person, this week.
  function actionButtons(box, guid, list) {
    var week = currentWeek();
    var row = el("div", "actions");
    list.forEach(function (pair) {
      var b = el("button", "btn small", pair[0]);
      b.type = "button";
      b.setAttribute("data-action", pair[1]);
      b.addEventListener("click", function () {
        change("/api/week/manual", { date: week.date, guid: guid, action: pair[1] });
      });
      row.appendChild(b);
    });
    box.appendChild(row);
  }

  function renderWhy(detail) {
    var box = $("why");
    clear(box);
    box.className = "why";
    if (!state.who) {
      box.appendChild(el("b", null, "לחצו על שם, או חפשו אותו למעלה"));
      box.appendChild(document.createTextNode("ותראו במשפט אחד למה הוא נמצא איפה שהוא, באילו שבועות הוא מקבל, ומה אפשר לשנות ביד."));
      return;
    }
    var week = currentWeek();
    var entry = detail ? findEntry(detail, state.who) : null;
    if (entry) {
      box.appendChild(el("b", null, (entry.manual ? "✋ " : "") + entry.name + " · רביעי " + dm(week.date) + ": " + ROLE_TEXT[entry.role]));
      box.appendChild(document.createTextNode(entry.why));
    } else {
      var other = state.people && state.people.others.filter(function (p) { return p.guid === state.who; })[0];
      var known = state.people && state.people.participants.filter(function (p) { return p.guid === state.who; })[0];
      if (other) {
        box.appendChild(el("b", null, other.name + ": לא משתתף ברשימות"));
        box.appendChild(document.createTextNode(other.why));
        if (other.active && detail) { actionButtons(box, other.guid, [["הוסף לשבוע הזה", "add"]]); }
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
    if (entry) {
      actionButtons(box, entry.guid, (ACTIONS[entry.role] || []).concat(entry.manual ? [["בטל את השינוי ביד", "clear"]] : []));
    }
  }

  // ── the week's tools: numbers, print, Excel ────────────────────────────────
  function whole(text) {
    var s = String(text).trim();
    if (!/^\d{1,4}$/.test(s)) { return null; }
    var n = Number(s);
    return n <= MAX_NUMBER ? n : null;
  }

  function saveNumbers() {
    var week = currentWeek();
    if (!week) { return; }
    var portions = whole($("nPortions").value), reserve = whole($("nReserve").value);
    if (portions === null || reserve === null) {
      notice("צריך מספר שלם בין 0 ל־" + MAX_NUMBER + ", גם במנות וגם ברזרבה.", true);
      return;
    }
    var d = state.plan.defaults;
    var ordinary = portions === d.portions && reserve === d.reserve;      // typed the ordinary numbers = nothing set by hand
    change("/api/week/numbers", { date: week.date, portions: ordinary ? null : portions, reserve: ordinary ? null : reserve });
  }

  function resetNumbers() {
    var week = currentWeek();
    if (week) { change("/api/week/numbers", { date: week.date, portions: null, reserve: null }); }
  }

  function rangeWeeks() {
    var box = $("nRange");
    var most = Number(box.max) || 104;
    var n = parseInt(box.value, 10);
    n = n >= 1 ? Math.min(n, most) : 1;
    box.value = n;
    return n;
  }

  // Printing / Excel: first the server notes the lists as they are now (only for the
  // reminder "changed since it was printed"), then the paper page or the file opens.
  function produce(how) {
    var week = currentWeek();
    if (!week || state.busy) { return; }
    var n = rangeWeeks();
    var query = "?from=" + week.date + "&weeks=" + n;
    // the new tab is opened right on the click (a browser blocks a tab opened later)
    var tab = how === "print" ? window.open("", "_blank") : null;
    setBusy(true);
    postJSON("/api/printed", { start: week.date, weeks: n, how: how }).then(function () {
      notice("");
      if (how === "print") {
        var page = window.location.origin + "/print" + query;
        if (tab) { tab.location.replace(page); } else { window.location.assign(page); }
      } else {
        var a = el("a");
        a.href = "/api/export.xlsx" + query;
        a.download = "";
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
      return refresh();
    }).catch(function (e) {
      if (tab) { tab.close(); }
      notice((how === "print" ? "ההדפסה לא נפתחה. " : "קובץ האקסל לא ירד. ") + (e.message || ""), true);
    }).then(function () { setBusy(false); });
  }

  $("saveNumbers").addEventListener("click", saveNumbers);
  $("resetNumbers").addEventListener("click", resetNumbers);
  ["nPortions", "nReserve"].forEach(function (id) {
    $(id).addEventListener("keydown", function (e) { if (e.key === "Enter") { saveNumbers(); } });
  });
  $("doPrint").addEventListener("click", function () { produce("print"); });
  $("doExcel").addEventListener("click", function () { produce("excel"); });

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
