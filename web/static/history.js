/* מנהל חלוקה — מסך ההיסטוריה (שלב 4): כל חלוקה שעברה ומי היה בה, רישומים ישנים בלי רשימת
   חלוקה, ו"מתי פלוני קיבל". קריאה בלבד: הדף לא שולח לשרת שום שינוי.
   הדף רק מציג את מה שהשרת מחזיר; כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד.
   הכתובת: /history · /history?who=<מזהה כרטיס> פותח ישר את ההיסטוריה של אדם אחד. */
(function () {
  "use strict";

  var PAGE = 30;                        // how many rounds are asked for at a time
  var FIRST_ROWS = 10;                  // how many of a person's rows are shown before "show all"
  var H = window.Haluka;                // web/static/common.js
  var $ = H.$, el = H.el, clear = H.clear, getJSON = H.getJSON, notice = H.notice;
  var state = { rounds: [], total: 0, more: false, people: null, person: null, all: false };

  function fail(e, lead) { notice((lead || "") + (e.message || ""), true); }
  function timesText(n) {
    return n === 0 ? "עוד לא קיבל אף פעם" : n === 1 ? "קיבל פעם אחת" : n === 2 ? "קיבל פעמיים" : "קיבל " + n + " פעמים";
  }
  function count(n, one, many) { return n === 1 ? one : n + " " + many; }
  // a date as it is shown; a row whose date is not a date shows the text that was written
  function dateText(r) { return r.date ? H.longDate(r.date) : (r.raw_date || r.key || "בלי תאריך"); }

  // what kind of round a row belongs to: a regular one, a holiday, a bonus
  function roundTag(r) {
    if (r.kind === "holiday") { return el("span", "tag t-one", r.label || "חלוקת חג"); }
    if (r.kind === "bonus") { return el("span", "tag t-w4", "חלוקת בונוס"); }
    return el("span", "tag t-w1", "חלוקה רגילה");
  }

  // The name a round was given, when it says more than the row already does: a week the site
  // closed, or a name that is only the kind and the date again, adds nothing.
  function givenName(r) {
    if (!r.name || r.from_site) { return ""; }
    var p = (r.date || "").split("-");
    var bare = r.name;
    if (p.length === 3) { bare = bare.replace(p[2] + "/" + p[1] + "/" + p[0], "").replace(Number(p[2]) + "/" + Number(p[1]) + "/" + p[0], ""); }
    bare = bare.trim();
    return bare === "" || bare === "חלוקת רביעי" || bare === r.label ? "" : r.name;
  }

  // ── one person ─────────────────────────────────────────────────────────────
  function setAddress(guid) {
    var url = guid ? "/history?who=" + encodeURIComponent(guid) : "/history";
    if (window.location.pathname + window.location.search !== url) { window.history.replaceState({}, "", url); }
  }

  function showPerson(guid, scroll) {
    return getJSON("/api/history/person?guid=" + encodeURIComponent(guid)).then(function (p) {
      state.person = p;
      state.all = false;
      notice("");
      setAddress(p.guid);
      renderPerson();
      if (scroll) { $("hPerson").scrollIntoView({ block: "center" }); }
    }).catch(function (e) { fail(e); });
  }

  function link(text, href) {
    var a = el("a", "link", text);
    a.href = href;
    return a;
  }

  function renderPerson() {
    var box = $("hPerson"), p = state.person;
    clear(box);
    box.hidden = !p;
    if (!p) { return; }
    var head = el("div", "person-head");
    head.appendChild(el("h3", null, p.name + ": " + timesText(p.received)));
    var kind = H.typeOf(p.kind, p.freq);
    head.appendChild(el("span", "tag t-" + kind, p.kind === "onetime" ? "חד־פעמי" : p.kind === "other" ? "כרטיס בלבד" : (p.freq || "קבוע")));
    if (!p.active) { head.appendChild(el("span", "row-status off", p.status || "מושהה")); }
    box.appendChild(head);

    var facts = [];
    if (p.received > 0 && p.extra > 0) {
      facts.push(count(p.regular, "פעם אחת בחלוקה רגילה", "פעמים בחלוקות רגילות") + " · " +
                 count(p.extra, "פעם אחת בחלוקת חג או בונוס", "פעמים בחלוקות חג או בונוס"));
    }
    if (p.absent > 0) { facts.push("נרשם שלא הגיע: " + count(p.absent, "פעם אחת", "פעמים")); }
    if (p.last) { facts.push("לאחרונה: " + H.longDate(p.last)); }
    if (facts.length) { box.appendChild(el("p", "sub", facts.join(" · "))); }

    var links = el("div", "actions links");
    links.appendChild(link("פתח את הכרטיס", "/people#card=" + encodeURIComponent(p.guid)));
    links.appendChild(link("מתי יקבל (מסך השבועות)", "/?who=" + encodeURIComponent(p.guid)));
    box.appendChild(links);

    var rows = el("div", "rows");
    (state.all ? p.rows : p.rows.slice(0, FIRST_ROWS)).forEach(function (r) {
      var line = el("div", "hrow" + (r.received ? "" : " plain"));
      line.appendChild(el("span", "d", dateText(r)));
      if (r.day) { line.appendChild(el("span", "n", r.day)); }
      line.appendChild(r.received ? roundTag(r) : el("span", "tag t-off", "נרשם שלא הגיע"));
      if (givenName(r)) { line.appendChild(el("span", "n", givenName(r))); }
      rows.appendChild(line);
    });
    box.appendChild(rows);
    if (p.rows.length > FIRST_ROWS) {
      var acts = el("div", "actions");
      var b = el("button", "btn small quiet", state.all ? "הצג רק את " + FIRST_ROWS + " האחרונות" : "הצג את כל " + p.rows.length + " השורות");
      b.type = "button";
      b.addEventListener("click", function () { state.all = !state.all; renderPerson(); });
      acts.appendChild(b);
      box.appendChild(acts);
    }
  }

  // a name in a list of the past: pressing it shows that person's own history
  function nameChip(p) {
    if (!p.guid) {                                  // the card is gone: a name, nothing to open
      return el("span", "chip t-other", p.name);
    }
    return H.chip(p, !!state.person && state.person.guid === p.guid, function () { showPerson(p.guid, true); });
  }
  function chipsOf(people, cls) {
    var box = el("div", "chips" + (cls ? " " + cls : ""));
    people.forEach(function (p) { box.appendChild(nameChip(p)); });
    return box;
  }

  // ── the rounds that passed ─────────────────────────────────────────────────
  // A row that opens to the names of everybody in it; the names are asked for on the first opening.
  function openingRow(build, load) {
    var names = el("div", "opened");
    names.hidden = true;
    var loaded = false;
    var row = el("button", "hrow");
    row.type = "button";
    row.setAttribute("aria-expanded", "false");
    build(row);
    var mark = el("span", "end", "▾");
    mark.setAttribute("aria-hidden", "true");
    row.appendChild(mark);
    row.addEventListener("click", function () {
      names.hidden = !names.hidden;
      row.setAttribute("aria-expanded", names.hidden ? "false" : "true");
      mark.textContent = names.hidden ? "▾" : "▴";
      if (names.hidden || loaded) { return; }
      loaded = true;
      names.appendChild(el("p", "empty", "טוען את השמות…"));
      load().then(function (d) {
        clear(names);
        if (d.people.length) { names.appendChild(chipsOf(d.people)); }
        else { names.appendChild(el("p", "empty", "אין רישום של מי שקיבל.")); }
        if (d.absent_people.length) {
          names.appendChild(el("p", "sub", "נרשם שלא הגיעו:"));
          names.appendChild(chipsOf(d.absent_people, "dim"));
        }
        if (d.reserve && d.reserve.length) {
          names.appendChild(el("p", "sub", "היו ברזרבה (לא קיבלו):"));
          names.appendChild(chipsOf(d.reserve, "dim"));
        }
      }).catch(function (e) {
        loaded = false;
        clear(names);
        names.appendChild(el("p", "empty", "לא הצלחתי לקבל את השמות. " + (e.message || "")));
      });
    });
    return [row, names];
  }

  function numbers(r) {
    return count(r.received, "מקבל אחד", "מקבלים") + (r.absent > 0 ? " · " + count(r.absent, "אחד לא הגיע", "לא הגיעו") : "");
  }

  function renderRounds() {
    var box = $("hRounds");
    clear(box);
    state.rounds.forEach(function (r) {
      openingRow(function (row) {
        row.appendChild(el("span", "d", dateText(r)));
        if (r.day) { row.appendChild(el("span", "n", r.day)); }
        row.appendChild(roundTag(r));
        if (givenName(r)) { row.appendChild(el("span", "n", givenName(r))); }
        row.appendChild(el("span", "n", numbers(r)));
      }, function () {
        return getJSON("/api/history/round?batch=" + encodeURIComponent(r.batch));
      }).forEach(function (node) { box.appendChild(node); });
    });
    if (!state.rounds.length) { box.appendChild(el("p", "empty", "עוד אין חלוקות בהיסטוריה.")); }
    $("hCount").textContent = !state.total ? "" : state.more
      ? "מוצגות " + state.rounds.length + " האחרונות מתוך " + state.total + " · לחיצה על שורה מראה מי קיבל"
      : count(state.total, "חלוקה אחת", "חלוקות") + " · לחיצה על שורה מראה מי קיבל";
    $("hMore").hidden = !state.more;
  }

  function renderOld(old, rows) {
    $("hOld").hidden = !old.length;
    $("hOldTitle").textContent = "רישומים ישנים, מלפני שהיו רשימות חלוקה (" + rows + ")";
    var box = $("hOldRows");
    clear(box);
    old.forEach(function (o) {
      openingRow(function (row) {
        row.className += " plain";
        row.appendChild(el("span", "d", dateText(o)));
        if (o.day) { row.appendChild(el("span", "n", o.day)); }
        row.appendChild(el("span", "n", numbers(o)));
      }, function () {
        return getJSON("/api/history/old?date=" + encodeURIComponent(o.key));
      }).forEach(function (node) { box.appendChild(node); });
    });
  }

  function loadRounds() {
    return getJSON("/api/history?offset=" + state.rounds.length + "&limit=" + PAGE).then(function (d) {
      var first = state.rounds.length === 0;
      state.rounds = state.rounds.concat(d.rounds);
      state.total = d.total;
      state.more = d.more;
      renderRounds();
      if (first) { renderOld(d.old, d.old_rows); }
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את ההיסטוריה מהשרת. " + (e.message || ""), true);
    });
  }

  // ── search ─────────────────────────────────────────────────────────────────
  function showHits() {
    var q = H.norm($("hQ").value);
    var box = $("hHits");
    clear(box);
    if (!q || !state.people) { box.hidden = true; return; }
    var words = q.split(" ");
    function match(p) { var n = H.norm(p.name); return words.every(function (w) { return n.indexOf(w) >= 0; }); }
    var found = state.people.participants.filter(match).concat(state.people.others.filter(match));
    found.slice(0, 12).forEach(function (p) {
      var li = el("li");
      var b = el("button");
      b.type = "button";
      b.appendChild(el("i", "sw t-" + H.typeOf(p.kind || "other", p.freq)));
      b.appendChild(el("span", null, p.name));
      b.appendChild(el("small", null, p.kind === "onetime" ? "חד־פעמי" : p.kind ? (p.freq || "קבוע") : p.active === false ? "מושהה" : "כרטיס בלבד"));
      b.addEventListener("click", function () {
        $("hQ").value = "";
        box.hidden = true;
        showPerson(p.guid, false);
      });
      li.appendChild(b);
      box.appendChild(li);
    });
    if (!found.length) { box.appendChild(el("li", "none", "לא נמצא שם כזה")); }
    else if (found.length > 12) { box.appendChild(el("li", "none", "ועוד " + (found.length - 12) + ". הקלידו עוד אותיות.")); }
    box.hidden = false;
  }

  $("hQ").addEventListener("input", showHits);
  $("hQ").addEventListener("keydown", function (e) { if (e.key === "Escape") { $("hQ").value = ""; showHits(); } });
  document.addEventListener("click", function (e) { if (!e.target.closest(".search")) { $("hHits").hidden = true; } });
  $("hMore").addEventListener("click", loadRounds);

  getJSON("/api/people").then(function (p) { state.people = p; }).catch(function () { state.people = null; });
  loadRounds().then(function () {
    var who = new URLSearchParams(window.location.search).get("who") || "";
    if (/^[0-9A-Za-z_-]{1,64}$/.test(who)) { showPerson(who, false); }
  });
}());
