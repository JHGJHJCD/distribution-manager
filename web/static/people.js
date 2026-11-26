/* מנהל חלוקה — מסך המקבלים (שלב 3): הרשימה, כרטיס אחד, הוספה ועריכה, השהיה, מחיקה
   עם ביטול, והצעות לכרטיסים שנראים כפולים. הדף לא מחליט שום דבר בעצמו: השרת בודק
   ושומר. כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד.
   הכתובת זוכרת איפה נמצאים: #card=<כרטיס> · #new · #dups (כך גם "אחורה" עובד). */
(function () {
  "use strict";

  var H = window.Haluka;
  var $ = H.$, el = H.el, clear = H.clear, dm = H.dm, getJSON = H.getJSON, postJSON = H.postJSON, notice = H.notice;

  var ACTIVE = "פעיל", PAUSED = "מושהה";
  var TYPE_CLASS = { w1: "w1", w2: "w2", w3: "w3", w4: "w4", one1: "one", one2: "one", other: "w1" };
  // the fields of a card: [field, label, kind, where]; "type" is the one choice of the kind of recipient
  var MAIN = [["last_name", "שם משפחה", "text"], ["first_name", "שם פרטי", "text"],
              ["phone1", "טלפון", "tel"], ["phone2", "טלפון 2", "tel"], ["phone3", "טלפון 3", "tel"],
              ["souls", "נפשות", "number"], ["type", "סוג", "type"]];
  var MORE = [["children_total", "מספר ילדים", "number"],
              ["address", "כתובת", "text"], ["id_number", "תעודת זהות", "text"],
              ["spouse_id_number", "תעודת זהות בן/בת זוג", "text"], ["email", "מייל", "text"],
              ["synagogue", "בית כנסת", "text"], ["representative", "נציג / קהילה", "text"],
              ["income", "הכנסה", "text"], ["per_soul", "פנוי לנפש", "text"],
              ["housing_expenses", "הוצאות דיור", "text"], ["medical_expenses", "הוצאות רפואיות", "text"]];
  var state = { types: [], card: null, busy: false, timer: null, token: 0, pair: null, lastDeleted: null,
                flash: null, flashUndo: false };

  function longDate(iso) { var p = iso.split("-"); return Number(p[2]) + "/" + Number(p[1]) + "/" + p[0]; }
  function setBusy(on) { state.busy = on; document.body.classList.toggle("busy", on); }
  function fail(e) { notice(e.message || "משהו לא הצליח", true); }
  function typeChip(row) {
    var cls = TYPE_CLASS[row.type];
    return el("span", "tag" + (cls ? " t-" + cls : " t-off"), row.type_label);
  }

  // One change: send it, and nothing else can be pressed until the server has answered.
  function send(url, body) {
    if (state.busy) { return Promise.reject(new Error("רגע, הפעולה הקודמת עוד לא הסתיימה")); }
    setBusy(true);
    return postJSON(url, body).then(function (r) { setBusy(false); return r; },
                                    function (e) { setBusy(false); throw e; });
  }

  // ── which view ─────────────────────────────────────────────────────────────
  function show(view) {
    ["listView", "cardView", "dupView"].forEach(function (id) { $(id).hidden = id !== view; });
    window.scrollTo(0, 0);
  }

  function route() {
    var hash = window.location.hash.replace(/^#/, "");
    // what the last action wants to say on the screen it leads to
    notice(state.flash || "");
    $("undo").hidden = !state.flashUndo;
    state.flash = null;
    state.flashUndo = false;
    if (hash === "new") { return openCard(""); }
    if (hash.indexOf("card=") === 0) { return openCard(decodeURIComponent(hash.slice(5))); }
    if (hash === "dups") { return openDups(); }
    show("listView");
    return loadList();
  }
  function go(hash) {
    if (window.location.hash.replace(/^#/, "") === hash) { route(); } else { window.location.hash = hash; }
  }

  // ── the list ───────────────────────────────────────────────────────────────
  function row(card, extra) {
    var b = el("button", "row" + (card.status === ACTIVE ? "" : " paused"));
    b.type = "button";
    b.appendChild(el("span", "row-name", card.name));
    b.appendChild(typeChip(card));
    b.appendChild(el("span", "row-num", [card.souls ? card.souls + " נפשות" : "",
                                         card.holiday ? "נתמך חגים" : ""].filter(Boolean).join(" · ")));
    b.appendChild(el("span", "row-last", card.last ? "קיבל לאחרונה " + longDate(card.last) : "עוד לא קיבל"));
    b.appendChild(el("span", "row-status" + (card.status === ACTIVE ? "" : " off"), card.status));
    if (extra) { b.appendChild(el("span", "row-last", extra)); }
    b.addEventListener("click", function () { go("card=" + encodeURIComponent(card.guid)); });
    return b;
  }

  function loadList() {
    var token = ++state.token;
    var url = "/api/cards?q=" + encodeURIComponent($("q").value.trim()) + "&show=" + $("show").value;
    return getJSON(url).then(function (data) {
      if (token !== state.token) { return; }
      state.types = data.types;
      $("counts").textContent = data.total + " כרטיסים · " + data.active + " פעילים";
      $("found").textContent = data.found === data.total ? "" : "נמצאו " + data.found + " מתוך " + data.total;
      var box = $("rows");
      clear(box);
      data.cards.forEach(function (c) { box.appendChild(row(c)); });
      if (!data.cards.length) { box.appendChild(el("p", "empty", data.total ? "לא נמצא כרטיס כזה" : "עוד אין כרטיסים")); }
      var strip = $("dupStrip");
      strip.hidden = !data.duplicates;
      strip.textContent = data.duplicates === 1 ? "יש הצעה אחת לכרטיסים שנראים כפולים · לבדוק"
        : "יש " + data.duplicates + " הצעות לכרטיסים שנראים כפולים · לבדוק";
      $("deletedBox").hidden = !data.deleted;
      $("deletedTitle").textContent = "כרטיסים שנמחקו (" + data.deleted + ")";
      if (data.deleted && $("deletedBox").open) { loadDeleted(); }
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את הרשימה מהשרת. " + (e.message || ""), true);
    });
  }

  function loadDeleted() {
    return getJSON("/api/cards/deleted").then(function (data) {
      var box = $("deletedRows");
      clear(box);
      data.cards.forEach(function (c) {
        var line = el("div", "row static");
        line.appendChild(el("span", "row-name", c.name));
        line.appendChild(el("span", "row-last", "נמחק ב-" + longDate(c.deleted_at)));
        var b = el("button", "btn small", "שחזר");
        b.type = "button";
        b.addEventListener("click", function () { restore(c.guid, c.name); });
        line.appendChild(b);
        box.appendChild(line);
      });
    }).catch(fail);
  }

  function restore(guid, name) {
    send("/api/card/restore", { guid: guid }).then(function () {
      state.flash = "הכרטיס של " + name + " חזר לרשימה.";
      go("");
    }).catch(fail);
  }

  // ── one card ───────────────────────────────────────────────────────────────
  function field(def, card) {
    var name = def[0], kind = def[2];
    var wrap = el("div", "field");
    var label = el("label", null, def[1]);
    label.htmlFor = "f_" + name;
    var input;
    if (kind === "type") {
      input = document.createElement("select");
      var known = false;
      state.types.forEach(function (t) {
        var o = el("option", null, t.label);
        o.value = t.key;
        if (t.key === card.type) { o.selected = true; known = true; }
        input.appendChild(o);
      });
      if (!known && card.type) {                      // an unusual kind that came from the import: kept as it is
        var o = el("option", null, card.type_label || "אחר");
        o.value = card.type;
        o.selected = true;
        input.appendChild(o);
      }
    } else {
      input = document.createElement("input");
      input.type = kind === "number" ? "number" : (kind === "tel" ? "tel" : "text");
      if (kind === "number") { input.min = "0"; input.max = "99"; input.inputMode = "numeric"; }
      if (kind === "tel") { input.dir = "ltr"; input.className = "ltr"; }
      var v = card[name];
      input.value = (v === null || v === undefined || (kind === "number" && !v)) ? "" : String(v);
    }
    input.id = "f_" + name;
    input.name = name;
    wrap.appendChild(label);
    wrap.appendChild(input);
    return wrap;
  }

  // The holiday mark: one tick for "receives in holiday distributions", and under it the
  // holidays themselves (none ticked = all of them). Ticks only, so nothing can be misread.
  function tick(id, text, checked) {
    var label = el("label", "tick");
    var box = document.createElement("input");
    box.type = "checkbox";
    box.id = id;
    box.checked = !!checked;
    label.appendChild(box);
    label.appendChild(el("span", null, text));
    return label;
  }

  function renderHoliday(card) {
    var box = $("holidayField");
    clear(box);
    box.appendChild(tick("f_holiday_support", "נתמך חגים · מקבל גם בחלוקות חג", card.holiday_support));
    var which = el("div", "ticks");
    which.id = "holidayWhich";
    which.appendChild(el("span", "sub", "באילו חגים? בלי סימון = כל החגים:"));
    (card.holiday_names || []).forEach(function (name, i) {
      var one = tick("f_holiday_" + i, name, (card.holidays || []).indexOf(name) >= 0);
      one.firstChild.value = name;
      which.appendChild(one);
    });
    box.appendChild(which);
    function sync() { which.hidden = !$("f_holiday_support").checked; }
    $("f_holiday_support").addEventListener("change", sync);
    sync();
  }

  function renderCard(card) {
    state.card = card;
    $("alikeBox").hidden = true;
    $("cardTitle").textContent = card.guid ? card.name : "מקבל חדש";
    [["mainFields", MAIN], ["moreFields", MORE]].forEach(function (pair) {
      var box = $(pair[0]);
      clear(box);
      pair[1].forEach(function (def) { box.appendChild(field(def, card)); });
    });
    $("moreBox").open = MORE.some(function (def) { return String(card[def[0]] || "").trim() && card[def[0]] !== 0; });
    renderHoliday(card);
    var notes = $("notesField");
    clear(notes);
    var label = el("label", null, "הערות");
    label.htmlFor = "f_notes";
    var area = document.createElement("textarea");
    area.id = "f_notes";
    area.name = "notes";
    area.rows = 3;
    area.value = card.notes || "";
    notes.appendChild(label);
    notes.appendChild(area);

    var isNew = !card.guid;
    $("saveBtn").textContent = isNew ? "הוסף" : "שמור";
    $("pauseBtn").hidden = isNew;
    $("pauseBtn").textContent = card.status === ACTIVE ? "השהה" : "החזר לפעיל";
    $("deleteBtn").hidden = isNew;
    $("deleteBtn").disabled = !card.can_delete;
    $("deleteWhy").hidden = isNew || card.can_delete;
    $("deleteWhy").textContent = "לכרטיס הזה יש היסטוריה של חלוקות, ולכן אי אפשר למחוק אותו. אפשר להשהות אותו.";
    $("side").hidden = isNew;
    if (!isNew) { renderSide(card); }
  }

  function renderSide(card) {
    var when = $("whenBox");
    clear(when);
    when.appendChild(el("b", null, "מתי יקבל"));
    if (card.why_out) {
      when.appendChild(el("span", null, card.why_out));
    } else if (card.coming.receives.length) {
      when.appendChild(el("span", null, "בשבועות הקרובים: " + card.coming.receives.slice(0, 6).map(dm).join(" · ") +
        (card.coming.receives.length > 6 ? " ועוד" : "")));
    } else {
      when.appendChild(el("span", null, "לא ברשימה ב-" + card.coming.weeks + " השבועות הקרובים"));
    }
    if (!card.why_out && card.coming.reserve.length) {
      when.appendChild(el("div", "when", "ברזרבה: " + card.coming.reserve.slice(0, 6).map(dm).join(" · ")));
    }
    var link = el("a", "link", "הצג במסך השבועות");
    link.href = "/?who=" + encodeURIComponent(card.guid);
    when.appendChild(el("div", "when")).appendChild(link);

    var hist = $("histBox");
    clear(hist);
    hist.appendChild(el("b", null, "מה היה עד היום"));
    var got = card.history.filter(function (h) { return h.received; });
    if (!card.history_count) {
      hist.appendChild(el("span", null, "עוד לא קיבל אף פעם"));
    } else {
      hist.appendChild(el("span", null, "רשום בהיסטוריה " + card.history_count + " פעמים" +
        (got.length ? " · לאחרונה: " + got.slice(0, 5).map(function (h) { return longDate(h.date); }).join(" · ") : "")));
      var all = el("a", "link", "כל ההיסטוריה שלו");
      all.href = "/history?who=" + encodeURIComponent(card.guid);
      hist.appendChild(el("div", "when")).appendChild(all);
    }
    hist.appendChild(el("div", "when", "סטטוס: " + card.status));
  }

  function openCard(guid) {
    show("cardView");
    clear($("mainFields"));
    $("cardTitle").textContent = "";
    var ready = state.types.length ? Promise.resolve() : getJSON("/api/cards?show=all").then(function (d) { state.types = d.types; });
    return ready.then(function () {
      return getJSON(guid ? "/api/card?guid=" + encodeURIComponent(guid) : "/api/card/new");
    }).then(renderCard).catch(function (e) {
      show("listView");
      fail(e);
      return loadList();
    });
  }

  function formData() {
    var data = { guid: state.card.guid, seen: state.card.seen };
    MAIN.concat(MORE).forEach(function (def) { data[def[0]] = $("f_" + def[0]).value; });
    data.notes = $("f_notes").value;
    data.holiday_support = $("f_holiday_support").checked;
    data.holidays = Array.prototype.filter.call($("holidayWhich").querySelectorAll("input"),
                                                function (c) { return c.checked; }).map(function (c) { return c.value; });
    return data;
  }

  function save(sure) {
    var data = formData();
    if (sure) { data.sure = true; }
    send("/api/card/save", data).then(function (r) {
      if (!r.ok && r.alike) { return askAlike(r.alike); }
      $("alikeBox").hidden = true;
      if (r["new"]) {
        state.flash = "הכרטיס נוסף. כל השבועות חושבו מחדש.";
        go("card=" + encodeURIComponent(r.guid));
      } else {
        notice("נשמר. כל השבועות חושבו מחדש.");
        return openCard(r.guid);
      }
    }).catch(fail);
  }

  function askAlike(alike) {
    var names = alike.some(function (a) { return a.same_name; });
    var phones = alike.some(function (a) { return a.same_phone; });
    $("alikeTitle").textContent = "כבר יש כרטיס עם " + (names && phones ? "אותו שם או אותו טלפון" : (names ? "אותו שם" : "אותו טלפון")) +
      ". האם זה אותו אדם?";
    var box = $("alikeRows");
    clear(box);
    alike.forEach(function (a) {
      var line = el("div", "row static");
      line.appendChild(el("span", "row-name", a.name));
      line.appendChild(el("span", "row-last", (a.same_name ? "אותו שם" : "") + (a.same_name && a.same_phone ? " · " : "") +
        (a.same_phone ? "אותו טלפון" : "")));
      line.appendChild(el("span", "row-last", a.last ? "קיבל לאחרונה " + longDate(a.last) : "עוד לא קיבל"));
      var b = el("button", "btn small", "פתח את הכרטיס הקיים");
      b.type = "button";
      b.addEventListener("click", function () { go("card=" + encodeURIComponent(a.guid)); });
      line.appendChild(b);
      box.appendChild(line);
    });
    $("alikeBox").hidden = false;
    $("alikeNew").focus();
  }

  function togglePause() {
    var card = state.card;
    var to = card.status === ACTIVE ? PAUSED : ACTIVE;
    send("/api/card/status", { guid: card.guid, status: to }).then(function () {
      return openCard(card.guid);
    }).then(function () {
      notice(to === PAUSED ? "הכרטיס הושהה. הוא לא ייכנס לרשימות עד שיחזור להיות פעיל." : "הכרטיס חזר להיות פעיל.");
    }).catch(fail);
  }

  function removeCard() {
    var card = state.card;
    if (!window.confirm("למחוק את הכרטיס של " + card.name + "?\nאפשר יהיה להחזיר אותו מ\"כרטיסים שנמחקו\".")) { return; }
    send("/api/card/delete", { guid: card.guid }).then(function () {
      state.lastDeleted = { guid: card.guid, name: card.name };
      $("undoText").textContent = "הכרטיס של " + card.name + " נמחק. ";
      state.flashUndo = true;
      go("");
    }).catch(fail);
  }

  // ── look-alikes ────────────────────────────────────────────────────────────
  function openDups() {
    show("dupView");
    $("compareBox").hidden = true;
    return getJSON("/api/duplicates").then(function (data) {
      var box = $("groups");
      clear(box);
      if (!data.groups.length) { box.appendChild(el("p", "empty", "אין הצעות. כל הכרטיסים נראים שונים זה מזה.")); }
      data.groups.forEach(function (g) { box.appendChild(groupBox(g)); });
    }).catch(fail);
  }

  function groupBox(g) {
    var box = el("div", "bk dup");
    box.appendChild(el("h3", null, g.title));
    var picked = [];
    var merge = el("button", "btn quiet", "השווה ומזג…");
    merge.type = "button";
    function sync() { merge.disabled = picked.length !== 2; }
    g.members.forEach(function (m) {
      var line = el("label", "row static");
      var tick = document.createElement("input");
      tick.type = "checkbox";
      tick.hidden = g.members.length === 2;                 // two cards: there is nothing to choose
      if (g.members.length === 2) { picked.push(m.guid); }
      tick.addEventListener("change", function () {
        if (tick.checked) { picked.push(m.guid); } else { picked.splice(picked.indexOf(m.guid), 1); }
        sync();
      });
      line.appendChild(tick);
      line.appendChild(el("span", "row-name", m.name));
      line.appendChild(typeChip(m));
      line.appendChild(el("span", "row-num", m.souls ? m.souls + " נפשות" : ""));
      line.appendChild(el("span", "row-last", m.history_count ? "קיבל " + m.history_count + " פעמים" : "עוד לא קיבל"));
      line.appendChild(el("span", "row-status" + (m.status === ACTIVE ? "" : " off"), m.status));
      var open = el("a", "link", "פתח כרטיס");
      open.href = "#card=" + encodeURIComponent(m.guid);
      line.appendChild(open);
      box.appendChild(line);
    });
    if (g.members.length > 2) { box.appendChild(el("p", "sub", "כדי למזג, סמנו שני כרטיסים.")); }
    var actions = el("div", "actions");
    var differ = el("button", "btn main", "אנשים שונים");
    differ.type = "button";
    differ.addEventListener("click", function () {
      send("/api/duplicates/different", { guids: g.members.map(function (m) { return m.guid; }) })
        .then(openDups).then(function () { notice("נרשם: אנשים שונים. ההצעה לא תופיע שוב."); }).catch(fail);
    });
    merge.addEventListener("click", function () { compare(picked[0], picked[1]); });
    actions.appendChild(differ);
    actions.appendChild(merge);
    box.appendChild(actions);
    sync();
    return box;
  }

  function compare(a, b) {
    getJSON("/api/duplicates/compare?a=" + encodeURIComponent(a) + "&b=" + encodeURIComponent(b)).then(function (c) {
      state.pair = c;
      $("compareTitle").textContent = "הכרטיס שנשאר: " + c.keep.name + " (יש לו יותר היסטוריה, או שהוא הוותיק יותר)";
      $("idWarn").hidden = !c.ids_differ;
      var table = $("compareTable");
      clear(table);
      [["", "הכרטיס שנשאר", "הכרטיס שמתמזג לתוכו"]].concat(c.differences.map(function (d) {
        return [d.label, d.keep, d.drop];
      })).forEach(function (cells, i) {
        cells.forEach(function (text, j) {
          table.appendChild(el("div", (i === 0 ? "cmp-head" : (j === 0 ? "cmp-label" : "")) +
            (i > 0 && j > 0 && cells[1] !== cells[2] ? " cmp-diff" : ""), text || (i > 0 && j > 0 ? "—" : "")));
        });
      });
      $("compareNote").textContent = "שום מספר טלפון לא נמחק: המספרים של הכרטיס השני מתווספים לכרטיס שנשאר, " +
        "וההיסטוריה של שניהם מתאחדת (" + c.keep.history_count + " + " + c.drop.history_count + " רישומים). " +
        "בשדה שבו שני הכרטיסים שונים נשאר מה שכתוב בכרטיס שנשאר." +
        (c.gains.length ? " יתווספו לו: " + c.gains.join(", ") + "." : "");
      $("compareBox").hidden = false;
      $("compareBox").scrollIntoView({ block: "nearest" });
      $("compareCancel").focus();
    }).catch(fail);
  }

  function doMerge() {
    var c = state.pair;
    if (!c) { return; }
    send("/api/duplicates/merge", { keep: c.keep.guid, drop: c.drop.guid }).then(function () {
      state.pair = null;
      return openDups();
    }).then(function () { notice("שני הכרטיסים מוזגו לכרטיס של " + c.keep.name + ". כל השבועות חושבו מחדש."); }).catch(fail);
  }

  // ── wiring ─────────────────────────────────────────────────────────────────
  $("addBtn").addEventListener("click", function () { go("new"); });
  $("backBtn").addEventListener("click", function () { go(""); });
  $("dupBack").addEventListener("click", function () { go(""); });
  $("dupStrip").addEventListener("click", function () { go("dups"); });
  $("show").addEventListener("change", loadList);
  $("q").addEventListener("input", function () {
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(loadList, 200);
  });
  $("deletedBox").addEventListener("toggle", function () { if ($("deletedBox").open) { loadDeleted(); } });
  $("cardForm").addEventListener("submit", function (e) { e.preventDefault(); save(false); });
  $("pauseBtn").addEventListener("click", togglePause);
  $("deleteBtn").addEventListener("click", removeCard);
  $("alikeNew").addEventListener("click", function () { save(true); });
  $("alikeCancel").addEventListener("click", function () { $("alikeBox").hidden = true; });
  $("compareCancel").addEventListener("click", function () { $("compareBox").hidden = true; state.pair = null; });
  $("compareMerge").addEventListener("click", doMerge);
  $("undoBtn").addEventListener("click", function () {
    if (state.lastDeleted) { restore(state.lastDeleted.guid, state.lastDeleted.name); }
  });
  window.addEventListener("hashchange", route);

  route();
}());
