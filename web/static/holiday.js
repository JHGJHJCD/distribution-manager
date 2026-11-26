/* מנהל חלוקה — מסך חלוקת החג (שלב 4): החלוקות שלפנינו, חלוקה אחת במלואה, הקמה ושינוי,
   שינויים ביד, הדפסה ואקסל, ומחיקה שאפשר לבטל.
   הדף לא מחשב שום כלל בעצמו: הוא מבקש מהשרת את הרשימות ומציג אותן, ושולח לשרת את מה
   שהמנהל קבע. כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד.
   הכתובת: /holiday = כל החלוקות · /holiday?event=<מזהה> = חלוקה אחת. */
(function () {
  "use strict";

  var MAX_NUMBER = 2000;                // התקרה של מנות / רזרבה (כמו בשרת)
  var NEW = "new";                      // a distribution that is being set up and is not stored yet
  var ROLE_TEXT = { main: "מקבל", reserve: "ברזרבה", out: "לא בחלוקה הזו" };
  var ACTIONS = {
    main: [["העבר לרזרבה", "reserve"], ["הסר מהחלוקה", "remove"]],
    reserve: [["הכנס לרשימה", "add"], ["הסר מהחלוקה", "remove"]],
    out: [["הוסף לחלוקה הזו", "add"], ["שים ברזרבה", "reserve"]]
  };
  // the groups of "not in this distribution", in the order the server sends them
  var OUT_GROUPS = [
    ["removed", "הוסרו ביד", ""],
    ["ev_missing", "חסר להם נתון בכרטיס, ולכן לא נכנסו", "amber"],
    ["ev_cut", "מתאימים, ולא נשאר להם מקום", ""],
    ["no_portions", "אין מנות בחלוקה הזו", ""],
    ["ev_filter", "לא עוברים את הסינון", ""],
    ["ev_other", "מסומנים רק לחגים אחרים", ""]
  ];

  var H = window.Haluka;                // web/static/common.js
  var $ = H.$, el = H.el, clear = H.clear, getJSON = H.getJSON, postJSON = H.postJSON, notice = H.notice;
  var state = { ov: null, cur: null, detail: null, who: null, people: null, busy: false, again: false,
                undo: null, token: 0, built: false };

  function setBusy(on) {
    state.busy = on;
    document.body.classList.toggle("busy", on);
  }
  function dayDate(e) { return e.day + " " + H.longDate(e.date); }
  function fail(e, lead) { notice((lead || "") + (e.message || ""), true); }

  // ── the address: which distribution is open ────────────────────────────────
  function asked() {
    var guid = new URLSearchParams(window.location.search).get("event") || "";
    return /^[0-9A-Za-z_-]{1,64}$/.test(guid) ? guid : null;
  }
  function go(guid) {
    var url = guid ? "/holiday?event=" + encodeURIComponent(guid) : "/holiday";
    if (window.location.pathname + window.location.search !== url) { window.history.pushState({}, "", url); }
  }

  // ── loading ────────────────────────────────────────────────────────────────
  function loadOverview() {
    return getJSON("/api/events").then(function (ov) {
      state.ov = ov;
      if (!state.built) { buildForm(ov); state.built = true; }
      return ov;
    });
  }
  function loadPeople() {
    return getJSON("/api/people").then(function (p) { state.people = p; }).catch(function () { state.people = null; });
  }
  function loadDetail(guid) {
    var token = ++state.token;
    return getJSON("/api/event?guid=" + encodeURIComponent(guid)).then(function (d) {
      if (token !== state.token) { return null; }
      state.detail = d;
      return d;
    });
  }

  // Show what the address asks for: one distribution, or all of them.
  function show() {
    var guid = asked();
    return loadOverview().then(function () {
      if (!guid) { showList(); return null; }
      return loadDetail(guid).then(function (d) {
        if (!d) { return; }
        state.cur = guid;
        fillForm(d);
        renderEvent();
      }).catch(function (e) {
        go(null);
        showList();
        fail(e);
      });
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את חלוקות החג מהשרת. " + (e.message || ""), true);
    });
  }

  // After a change: everything is asked again (the server computes all the lists anew).
  function refresh() {
    var guid = state.cur;
    return loadOverview().then(function () {
      if (!guid || guid === NEW) { return null; }
      return loadDetail(guid).then(function (d) { if (d) { renderEvent(); } });
    });
  }

  // One change: send it, then ask for everything again. A refusal comes back as a sentence
  // in Hebrew and is shown as it is. A change that was made while another one was on its way
  // is sent right after it (see formChanged).
  function change(url, body) {
    if (state.busy) { return Promise.resolve(false); }
    setBusy(true);
    return postJSON(url, body).then(function () {
      notice("");
      return refresh().then(function () { return true; });
    }).catch(function (e) {
      fail(e, "השינוי לא נשמר. ");
      if (state.detail && state.cur !== NEW) { fillForm(state.detail); }      // the form shows what is saved
      return false;
    }).then(function (ok) {
      setBusy(false);
      if (state.again) { state.again = false; formChanged(); }
      return ok;
    });
  }

  // ── all the distributions ──────────────────────────────────────────────────
  function arrow() {
    var a = el("span", "end", "←");
    a.setAttribute("aria-hidden", "true");
    return a;
  }

  function showList() {
    state.cur = null;
    state.detail = null;
    state.who = null;
    $("holEvent").hidden = true;
    $("holList").hidden = false;
    var ov = state.ov;
    var box = $("holRows");
    clear(box);
    ov.open.forEach(function (ev) {
      var row = el("button", "hrow");
      row.type = "button";
      row.appendChild(el("span", "row-name", ev.name));
      row.appendChild(el("span", "n", dayDate(ev) + " · " + ev.portions + " מנות · " + ev.main_count + " מקבלים · " +
                         ev.reserve_count + " ברזרבה"));
      var marks = [];
      if (ev.manual_count > 0) { marks.push("✋"); }
      if (ev.warnings.length || (ev.print && ev.print.changed)) { marks.push("⚠"); }
      if (marks.length) {
        var m = el("span", "mark", marks.join(" "));
        m.title = ev.warnings.concat(ev.print && ev.print.changed ? ["השתנה מאז ההדפסה"] : [])
          .concat(ev.manual_count > 0 ? ["יש שינויים ביד"] : []).join(" · ");
        row.appendChild(m);
      }
      row.appendChild(arrow());
      row.addEventListener("click", function () { open(ev.guid); });
      box.appendChild(row);
    });
    if (!ov.open.length) { box.appendChild(el("p", "empty", "אין חלוקת חג שנקבעה. לחצו על \"+ חלוקת חג חדשה\".")); }

    var past = $("holPastRows");
    clear(past);
    ov.past.forEach(function (ev) {
      var row = el("button", "hrow");
      row.type = "button";
      row.appendChild(el("span", "row-name", ev.name));
      row.appendChild(el("span", "n", dayDate(ev) + " · קיבלו " + ev.main_count));
      row.appendChild(arrow());
      row.addEventListener("click", function () { open(ev.guid); });
      past.appendChild(row);
    });
    $("holPast").hidden = !ov.past.length;
    $("holPastTitle").textContent = "חלוקות חג שעברו (" + ov.past.length + ")";

    var gone = $("holDeletedRows");
    clear(gone);
    ov.deleted.forEach(function (ev) {
      var row = el("div", "hrow plain");
      row.appendChild(el("span", "row-name", ev.name));
      row.appendChild(el("span", "n", dayDate(ev) + " · " + ev.portions + " מנות"));
      var b = el("button", "btn small push", "החזר");
      b.type = "button";
      b.addEventListener("click", function () { restore(ev.guid); });
      row.appendChild(b);
      gone.appendChild(row);
    });
    $("holDeleted").hidden = !ov.deleted.length;
    $("holDeletedTitle").textContent = "חלוקות שנמחקו (" + ov.deleted.length + ")";

    var undo = state.undo && ov.deleted.some(function (e) { return e.guid === state.undo.guid; }) ? state.undo : null;
    $("holUndo").hidden = !undo;
    if (undo) { $("holUndoText").textContent = undo.text; }
  }

  function open(guid) {
    state.undo = null;
    notice("");
    go(guid);
    show().then(function () { window.scrollTo(0, 0); });
  }
  function back() {
    notice("");
    go(null);
    loadOverview().then(showList).catch(function (e) { fail(e); });
    window.scrollTo(0, 0);
  }

  function restore(guid) {
    if (state.busy) { return; }
    setBusy(true);
    postJSON("/api/event/restore", { event: guid }).then(function () {
      state.undo = null;
      notice("החלוקה חזרה, עם כל מה שנקבע בה.");
      return loadOverview().then(showList);
    }).catch(function (e) {
      fail(e, "החלוקה לא חזרה. ");
      return loadOverview().then(showList).catch(function () {});
    }).then(function () { setBusy(false); });
  }

  // ── the form: day, holiday, numbers, filter ────────────────────────────────
  function numberInput(id, label) {
    var input = el("input");
    input.id = id;
    input.type = "number";
    input.step = "any";
    input.inputMode = "decimal";
    input.setAttribute("aria-label", label);
    return input;
  }
  function buildForm(ov) {
    var sel = $("evHol");
    clear(sel);
    ov.holidays.forEach(function (h) {
      var o = el("option", null, h.label);
      o.value = h.code;
      sel.appendChild(o);
    });
    var grid = $("evFilter");
    clear(grid);
    ov.filter.forEach(function (f) {
      grid.appendChild(el("span", "f-name", f.label));
      var pairs = el("span", "f-pairs");
      [["min", "מ־"], ["max", "עד־"]].forEach(function (side) {
        var id = "f_" + f.field + "_" + side[0];
        var pair = el("span", "pair");
        var label = el("label", null, side[1]);
        label.htmlFor = id;
        pair.appendChild(label);
        pair.appendChild(numberInput(id, f.label + ", " + side[1]));
        pairs.appendChild(pair);
      });
      grid.appendChild(pairs);
    });
    Array.prototype.forEach.call($("evForm").querySelectorAll("input, select"), function (input) {
      input.addEventListener("change", formChanged);
    });
  }

  function shown(value) { return value === null || value === undefined ? "" : String(value); }
  function fillForm(ev) {
    $("evDate").min = state.ov.first_day;
    $("evDate").value = ev.date || "";
    $("evHol").value = ev.holiday;
    $("evPortions").value = shown(ev.portions);
    $("evReserve").value = shown(ev.reserve);
    state.ov.filter.forEach(function (f) {
      var b = (ev.criteria || {})[f.field] || {};
      $("f_" + f.field + "_min").value = shown(b.min);
      $("f_" + f.field + "_max").value = shown(b.max);
    });
  }

  function whole(text, emptyIs) {
    var s = String(text).trim();
    if (s === "") { return emptyIs; }
    if (!/^\d{1,4}$/.test(s)) { return undefined; }
    var n = Number(s);
    return n <= MAX_NUMBER ? n : undefined;
  }
  function bound(input) {
    var s = input.value.trim();
    if (s === "") { return input.validity && input.validity.badInput ? undefined : null; }
    var n = Number(s);
    return isFinite(n) && Math.abs(n) <= 1e9 ? n : undefined;
  }
  // What the form says, or the sentence that explains what is wrong in it.
  function readForm() {
    var date = $("evDate").value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { return { error: "צריך לבחור תאריך לחלוקה." }; }
    var portions = whole($("evPortions").value, undefined), reserve = whole($("evReserve").value, 0);
    if (portions === undefined) { return { error: "מנות: צריך מספר שלם בין 0 ל־" + MAX_NUMBER + "." }; }
    if (reserve === undefined) { return { error: "רזרבה: צריך מספר שלם בין 0 ל־" + MAX_NUMBER + "." }; }
    var criteria = {}, error = "";
    state.ov.filter.forEach(function (f) {
      var lo = bound($("f_" + f.field + "_min")), hi = bound($("f_" + f.field + "_max"));
      if (lo === undefined || hi === undefined) { error = error || f.label + ": צריך מספר."; return; }
      if (lo !== null && hi !== null && lo > hi) { error = error || f.label + ": המספר ב\"מ־\" גדול מהמספר ב\"עד־\"."; return; }
      if (lo !== null || hi !== null) { criteria[f.field] = { min: lo, max: hi }; }
    });
    if (error) { return { error: error }; }
    return { data: { date: date, holiday: $("evHol").value, portions: portions, reserve: reserve, criteria: criteria } };
  }
  function sameAsSaved(data, ev) {
    if (data.date !== ev.date || data.holiday !== ev.holiday || data.portions !== ev.portions || data.reserve !== ev.reserve) { return false; }
    return state.ov.filter.every(function (f) {
      var a = data.criteria[f.field] || {}, b = (ev.criteria || {})[f.field] || {};
      return shown(a.min) === shown(b.min) && shown(a.max) === shown(b.max);
    });
  }

  // A distribution that exists is saved as soon as a field is changed (there is no "save"
  // button to forget); a new one is stored only by "צור את החלוקה".
  function formChanged() {
    if (state.cur === NEW || !state.detail || state.detail.closed) { return; }
    if (state.busy) { state.again = true; return; }
    var f = readForm();
    if (f.error) { notice("השינוי לא נשמר. " + f.error, true); return; }
    if (sameAsSaved(f.data, state.detail)) { notice(""); return; }
    f.data.guid = state.cur;
    change("/api/event/save", f.data);
  }

  function startNew() {
    state.undo = null;
    state.cur = NEW;
    state.detail = null;
    state.who = null;
    notice("");
    fillForm({ date: "", holiday: state.ov.holidays[0].code, portions: null, reserve: state.ov.defaults.reserve, criteria: {} });
    renderEvent();
    window.scrollTo(0, 0);
    $("evDate").focus();
  }
  function create() {
    if (state.busy || state.cur !== NEW) { return; }
    var f = readForm();
    if (f.error) { notice(f.error, true); return; }
    setBusy(true);
    postJSON("/api/event/save", f.data).then(function (r) {
      notice("");
      go(r.guid);
      return show();
    }).catch(function (e) { fail(e, "החלוקה לא נוצרה. "); }).then(function () { setBusy(false); });
  }

  function remove() {
    var d = state.detail;
    if (!d || d.closed || state.busy) { return; }
    setBusy(true);
    postJSON("/api/event/delete", { event: d.guid }).then(function () {
      state.undo = { guid: d.guid, text: d.name + " של " + dayDate(d) + " נמחקה." };
      notice("");
      go(null);
      return loadOverview().then(showList);
    }).catch(function (e) { fail(e, "החלוקה לא נמחקה. "); }).then(function () { setBusy(false); window.scrollTo(0, 0); });
  }

  // ── one distribution ───────────────────────────────────────────────────────
  function chip(entry) {
    return H.chip(entry, entry.guid === state.who, function () {
      state.who = entry.guid;
      renderEvent();
      if (!whySeen) { $("evWhy").scrollIntoView({ block: "nearest" }); }
    });
  }
  function group(title, entries, cls) { return H.group(title, entries, chip, cls); }
  function chips(entries) {
    var box = el("div", "chips");
    entries.forEach(function (e) { box.appendChild(chip(e)); });
    return box;
  }

  function renderEvent() {
    var isNew = state.cur === NEW, d = state.detail;
    var closed = !isNew && !!d.closed;
    $("holList").hidden = true;
    $("holEvent").hidden = false;
    $("evTitle").textContent = isNew ? "חלוקת חג חדשה" : d.name + " · " + dayDate(d);
    $("evClosedNote").hidden = !closed;
    $("evForm").hidden = closed;
    $("evCreate").hidden = !isNew;
    $("evActions").hidden = isNew || closed;
    $("evBody").hidden = isNew;
    if (isNew) { return; }

    $("evStats").hidden = closed;
    $("evSearch").hidden = closed;
    $("outBucket").hidden = closed;
    $("evInfo").hidden = closed;
    var filtered = Object.keys(d.criteria || {}).length > 0;
    if (!closed) {
      $("stMarked").textContent = d.marked;
      $("stPass").textContent = d.eligible;
      $("stPassLabel").textContent = filtered ? "עוברים את הסינון" : "בתור לחלוקה";
      $("stMain").textContent = d.main_count;
      $("stRes").textContent = d.reserve_count;
      $("stNoRoom").textContent = d.left_out;
      $("stMissing").textContent = d.missing;
      $("stMissingTile").className = "stat" + (d.missing > 0 ? " amber" : "");
    }
    $("mainSub").textContent = closed ? "מי שקיבל בחלוקה הזו, כמו שנרשם."
      : filtered ? "מי שמסומן לחג ועובר את הסינון. מי שמחכה הכי הרבה זמן, ראשון."
                 : "מי שמסומן לחג. מי שמחכה הכי הרבה זמן, ראשון.";

    var warn = $("evWarnings");
    clear(warn);
    (d.warnings || []).forEach(function (text) { warn.appendChild(el("div", "warn", text)); });
    var note = closed ? null : H.printNote(d.print);
    if (note) { warn.appendChild(note); }

    var main = $("evMain"), res = $("evRes"), out = $("evOut");
    clear(main); clear(res); clear(out);
    $("cMain").textContent = d.main.length + " / " + d.portions;
    $("cRes").textContent = String(d.reserve_list.length);
    $("cOut").textContent = String(d.out.length);

    var byHand = d.main.filter(function (e) { return e.manual; });
    var inLine = d.main.filter(function (e) { return !e.manual; });
    if (byHand.length) {
      main.appendChild(group("נוספו ביד", byHand));
      if (inLine.length) { main.appendChild(group("לפי זמן ההמתנה", inLine)); }
    } else if (inLine.length) {
      main.appendChild(chips(inLine));
    }
    var empty = closed ? 0 : d.empty_portions;
    if (empty > 0 && d.portions > 0) {
      var g = el("div", "grp");
      var h = el("h4", null, "מנות בלי מקבל ");
      h.appendChild(el("b", null, String(empty)));
      g.appendChild(h);
      var slots = el("div", "chips");
      for (var i = 0; i < Math.min(empty, 60); i++) { slots.appendChild(el("span", "slot")); }
      g.appendChild(slots);
      main.appendChild(g);
    }
    if (!d.main.length && !(empty > 0 && d.portions > 0)) { main.appendChild(el("p", "empty", "אין מקבלים בחלוקה הזו.")); }

    if (d.reserve_list.length) { res.appendChild(chips(d.reserve_list)); }
    else { res.appendChild(el("p", "empty", "אין רזרבה בחלוקה הזו.")); }

    if (!closed) {
      OUT_GROUPS.forEach(function (g3) {
        var list = d.out.filter(function (e) { return e.group === g3[0]; });
        if (list.length) { out.appendChild(group(g3[1], list, g3[2])); }
      });
      if (!d.out.length) { out.appendChild(el("p", "empty", "כל מי שמסומן לחג הזה נמצא ברשימה או ברזרבה.")); }
      if (d.unmarked > 0) {
        out.appendChild(el("p", "others", "ועוד " + d.unmarked + " כרטיסים פעילים שלא מסומנים \"נתמך חגים\"." +
          " אפשר להוסיף מישהו מהם ביד דרך החיפוש."));
      }
    }
    renderWhy(d, closed);
    pin();
  }

  function findEntry(d, guid) {
    var lists = [d.main, d.reserve_list, d.out];
    for (var i = 0; i < lists.length; i++) {
      for (var j = 0; j < lists[i].length; j++) {
        if (lists[i][j].guid === guid) { return lists[i][j]; }
      }
    }
    return null;
  }
  function known(guid) {
    var p = state.people;
    if (!p) { return null; }
    var hit = p.participants.filter(function (x) { return x.guid === guid; })[0];
    if (hit) { return { name: hit.name, active: true, why: "" }; }
    hit = p.others.filter(function (x) { return x.guid === guid; })[0];
    return hit ? { name: hit.name, active: !!hit.active, why: hit.why || "" } : null;
  }

  function actionButtons(box, guid, list) {
    var row = el("div", "actions");
    list.forEach(function (pair) {
      var b = el("button", "btn small", pair[0]);
      b.type = "button";
      b.setAttribute("data-action", pair[1]);
      b.addEventListener("click", function () {
        change("/api/event/manual", { event: state.cur, guid: guid, action: pair[1] });
      });
      row.appendChild(b);
    });
    box.appendChild(row);
  }

  function renderWhy(d, closed) {
    var box = $("evWhy");
    clear(box);
    if (!state.who) {
      box.appendChild(document.createTextNode(closed ? "לחצו על שם ותראו למה הוא היה ברשימה."
        : "לחצו על שם ותראו במשפט אחד למה הוא נמצא איפה שהוא, ומה אפשר לשנות ביד."));
      return;
    }
    var entry = findEntry(d, state.who);
    if (entry) {
      box.appendChild(el("b", null, (entry.manual ? "✋ " : "") + entry.name + " · " + ROLE_TEXT[entry.role]));
      box.appendChild(document.createTextNode(entry.why));
      if (!closed) {
        actionButtons(box, entry.guid, (ACTIONS[entry.role] || []).concat(entry.manual ? [["בטל את השינוי ביד", "clear"]] : []));
      }
      return;
    }
    var who = known(state.who);
    if (!who) {
      box.appendChild(el("b", null, "המקבל שנבחר"));
      box.appendChild(document.createTextNode("לא נמצא ברשימות של החלוקה הזו."));
      return;
    }
    box.appendChild(el("b", null, who.name + " · " + ROLE_TEXT.out));
    if (closed) {
      box.appendChild(document.createTextNode("לא היה ברשימה של החלוקה הזו."));
    } else if (who.active) {
      box.appendChild(document.createTextNode("לא מסומן בכרטיס כנתמך חגים, ולכן לא נכנס לבד. אפשר להוסיף אותו ביד."));
      actionButtons(box, state.who, ACTIONS.out);
    } else {
      box.appendChild(document.createTextNode("הכרטיס מושהה, ואי אפשר להכניס אותו לרשימה."));
    }
  }

  // The explanation stays pinned over the long lists (style.css: .why.pinned) and casts a
  // shadow while it is; a name that is pressed while the box is out of sight brings it back.
  var whySeen = true, pinAsked = false;
  function pin() {
    pinAsked = false;
    $("evWhy").classList.toggle("stuck", !$("holEvent").hidden && !$("evBody").hidden &&
                                $("whyMark").getBoundingClientRect().top < 8);
  }
  window.addEventListener("scroll", function () {
    if (!pinAsked) { pinAsked = true; window.requestAnimationFrame(pin); }
  }, { passive: true });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) { whySeen = entries[entries.length - 1].isIntersecting; }).observe($("evWhy"));
  }

  // ── print and Excel ────────────────────────────────────────────────────────
  // First the server notes the list as it is now (only for the reminder "changed since it
  // was printed"), then the paper page or the file opens.
  function produce(how) {
    var d = state.detail;
    if (!d || d.closed || state.busy) { return; }
    var query = "?event=" + encodeURIComponent(d.guid);
    var tab = how === "print" ? window.open("", "_blank") : null;      // right on the click (a later tab is blocked)
    setBusy(true);
    postJSON("/api/printed", { event: d.guid, how: how }).then(function () {
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
      fail(e, how === "print" ? "ההדפסה לא נפתחה. " : "קובץ האקסל לא ירד. ");
    }).then(function () { setBusy(false); });
  }

  // ── search: any card, to see where it stands or to add it by hand ──────────
  function showHits() {
    var q = H.norm($("evQ").value);
    var box = $("evHits");
    clear(box);
    if (!q || !state.people) { box.hidden = true; return; }
    var words = q.split(" ");
    function match(p) { var n = H.norm(p.name); return words.every(function (w) { return n.indexOf(w) >= 0; }); }
    var found = state.people.participants.filter(match).concat(state.people.others.filter(match));
    found.slice(0, 12).forEach(function (p) {
      var li = el("li");
      var b = el("button");
      b.type = "button";
      var entry = state.detail ? findEntry(state.detail, p.guid) : null;
      b.appendChild(el("i", "sw t-" + H.typeOf(p.kind || "other", p.freq)));
      b.appendChild(el("span", null, p.name));
      b.appendChild(el("small", null, entry ? ROLE_TEXT[entry.role] : p.active === false ? "מושהה" : "לא מסומן לחגים"));
      b.addEventListener("click", function () {
        state.who = p.guid;
        $("evQ").value = "";
        box.hidden = true;
        renderEvent();
        $("evWhy").scrollIntoView({ block: "nearest" });
      });
      li.appendChild(b);
      box.appendChild(li);
    });
    if (!found.length) { box.appendChild(el("li", "none", "לא נמצא שם כזה")); }
    else if (found.length > 12) { box.appendChild(el("li", "none", "ועוד " + (found.length - 12) + ". הקלידו עוד אותיות.")); }
    box.hidden = false;
  }

  // ── wiring ─────────────────────────────────────────────────────────────────
  $("holNew").addEventListener("click", startNew);
  $("holUndoBtn").addEventListener("click", function () { if (state.undo) { restore(state.undo.guid); } });
  $("evBack").addEventListener("click", back);
  $("evCancel").addEventListener("click", back);
  $("evCreateBtn").addEventListener("click", create);
  $("evDelete").addEventListener("click", remove);
  $("evPrint").addEventListener("click", function () { produce("print"); });
  $("evExcel").addEventListener("click", function () { produce("excel"); });
  $("evQ").addEventListener("input", showHits);
  $("evQ").addEventListener("keydown", function (e) { if (e.key === "Escape") { $("evQ").value = ""; showHits(); } });
  document.addEventListener("click", function (e) { if (!e.target.closest(".search")) { $("evHits").hidden = true; } });
  window.addEventListener("popstate", function () { notice(""); show(); });

  // a link from elsewhere may name a person to explain: /holiday?event=<id>&who=<card>
  var who = new URLSearchParams(window.location.search).get("who");
  if (who) { state.who = who; }

  loadPeople().then(show);
}());
