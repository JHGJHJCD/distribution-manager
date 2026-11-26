/* מנהל חלוקה — מסך ההגדרות: המספרים הרגילים של שבוע, משקלי הניקוד, הקהילות, וגיבוי ושחזור (שלב 5).
   לפני שמירה הדף שואל את השרת "מה ישתנה?" ומציג את התשובה; שום דבר לא נשמר עד שלוחצים "שמור".
   הדף לא מחשב שום כלל בעצמו. כל טקסט שמגיע מהנתונים נכנס עם textContent בלבד. */
(function () {
  "use strict";

  var H = window.Haluka;                // web/static/common.js
  var $ = H.$, el = H.el, clear = H.clear, getJSON = H.getJSON, postJSON = H.postJSON, notice = H.notice;
  var SHOWN = 4;                        // how many lists "what would change" spells out
  var WAIT = 350;                       // ms of quiet before asking "what would change"
  var state = { view: null, busy: false, timers: {}, asked: {} };

  function fail(e, lead) { notice((lead || "") + (e.message || ""), true); }
  function tidy(n) { return String(Math.round(n * 10) / 10); }
  function count(n, one, many) { return n === 1 ? one : n + " " + many; }
  function setBusy(on) {
    state.busy = on;
    document.body.classList.toggle("busy", on);
  }

  // ── what the two forms say ─────────────────────────────────────────────────
  function numberInput(id, max, step) {
    var input = el("input");
    input.id = id;
    input.type = "number";
    input.min = "0";
    input.max = String(max);
    input.step = step;
    input.inputMode = step === "1" ? "numeric" : "decimal";
    return input;
  }

  // The numbers as they are typed, or null when one of them cannot be saved.
  function readNumbers() {
    var out = {}, ok = true;
    state.view.number_fields.forEach(function (f) {
      var s = $("n_" + f.name).value.trim();
      if (!/^\d{1,4}$/.test(s) || Number(s) > f.max) { ok = false; return; }
      out[f.name] = Number(s);
    });
    return ok ? out : null;
  }
  // {weights, sum, bad}: bad = a box that is not a number between 0 and 100 with one decimal at most
  function readWeights() {
    var out = {}, sum = 0, bad = false;
    state.view.weights.forEach(function (w) {
      var s = $("w_" + w.key).value.trim();
      if (!/^\d{1,3}(\.\d)?$/.test(s) || Number(s) > 100) { bad = true; return; }
      out[w.key] = Number(s);
      sum += Number(s);
    });
    return { weights: out, sum: Math.round(sum * 10) / 10, bad: bad };
  }
  // {percents, sum, bad, all}: bad = a box that is not a number between 0 and 100 with one decimal at most;
  // all = every community has a percentage of its own
  function readCommunities() {
    var out = {}, sum = 0, bad = false, fixed = 0;
    state.view.communities.forEach(function (c, i) {
      var s = $("c_" + i).value.trim();
      if (s === "") { s = "0"; }
      if (!/^\d{1,3}(\.\d)?$/.test(s) || Number(s) > 100) { bad = true; return; }
      out[c.name] = Number(s);
      sum += Number(s);
      if (Number(s) > 0) { fixed += 1; }
    });
    return { percents: out, sum: Math.round(sum * 10) / 10, bad: bad,
             all: state.view.communities.length > 0 && fixed === state.view.communities.length };
  }
  function sameCommunities(p) {
    return state.view.communities.every(function (c) { return p[c.name] === c.percent; });
  }
  function sameNumbers(n) {
    return !!n && state.view.number_fields.every(function (f) { return n[f.name] === state.view.numbers[f.name]; });
  }
  function sameWeights(w) {
    return state.view.weights.every(function (x) { return w[x.key] === x.value; });
  }

  // ── "what would change?" ───────────────────────────────────────────────────
  // One line for each list that would differ (the first few), in words.
  function showEffect(box, p) {
    clear(box);
    if (p.same) {
      box.appendChild(el("b", null, "אם תשמור: שום רשימה ב־" + p.weeks + " השבועות הקרובים לא תשתנה."));
      return;
    }
    box.appendChild(el("b", null, "אם תשמור, " + count(p.changed.length, "רשימה אחת תשתנה", "רשימות ישתנו") +
                       " ב־" + p.weeks + " השבועות הקרובים:"));
    p.changed.slice(0, SHOWN).forEach(function (c) {
      var bits = [];
      if (c.enter && c.enter === c.leave) { bits.push(count(c.enter, "שם אחד מתחלף", "שמות מתחלפים")); }
      else {
        if (c.enter) { bits.push(count(c.enter, "נכנס שם אחד", "שמות נכנסים")); }
        if (c.leave) { bits.push(count(c.leave, "יוצא שם אחד", "שמות יוצאים")); }
      }
      if (c.reserve_before !== c.reserve_after) { bits.push("ברזרבה " + c.reserve_after + " במקום " + c.reserve_before); }
      box.appendChild(el("span", null, (c.kind === "event" ? c.name : "שבוע " + H.dm(c.date)) + ": " + bits.join(", ")));
    });
    var more = p.changed.length - SHOWN;
    if (more > 0) { box.appendChild(el("span", null, "וכך גם בעוד " + count(more, "רשימה אחת", "רשימות") + ".")); }
  }

  // Ask the server what the typed settings would change — a little after the typing stops,
  // and only the latest question is answered on the screen.
  function ask(which, body) {
    var box = $(which + "Effect");
    window.clearTimeout(state.timers[which]);
    if (!body) { box.hidden = true; state.asked[which] = 0; return; }
    var mine = state.asked[which] = (state.asked[which] || 0) + 1;
    state.timers[which] = window.setTimeout(function () {
      postJSON("/api/settings/preview", body).then(function (p) {
        if (state.asked[which] !== mine) { return; }
        showEffect(box, p);
        box.hidden = false;
      }).catch(function () { if (state.asked[which] === mine) { box.hidden = true; } });
    }, WAIT);
  }

  // ── the screen follows what is typed ───────────────────────────────────────
  function numbersTyped() {
    var n = readNumbers();
    var changed = !sameNumbers(n);
    $("numSave").disabled = !n || !changed;
    $("numUndo").hidden = !!n && !changed;
    ask("num", n && changed ? { numbers: n } : null);
  }
  function weightsTyped() {
    var r = readWeights();
    var sum = $("wSum");
    var right = !r.bad && r.sum === 100;
    sum.className = "sum " + (right ? "ok" : "bad");
    sum.textContent = r.bad ? "בכל תיבה צריך מספר בין 0 ל־100 (עד ספרה אחת אחרי הנקודה)"
      : right ? "סך הכול 100 ✓"
      : r.sum < 100 ? "סך הכול " + tidy(r.sum) + " · חסרים " + tidy(100 - r.sum) + " כדי להגיע ל־100"
                    : "סך הכול " + tidy(r.sum) + " · " + tidy(r.sum - 100) + " יותר מדי";
    var changed = r.bad || !sameWeights(r.weights);
    $("wSave").disabled = !right || !changed;
    $("wSave").title = right ? "" : "אפשר לשמור רק כשהמשקלים מסתכמים ב־100";
    $("wUndo").hidden = !changed;
    ask("w", right && changed ? { weights: r.weights } : null);
  }

  function communitiesTyped() {
    var r = readCommunities();
    var sum = $("cSum");
    var over = r.sum > 100, short = r.all && r.sum !== 100;
    var right = !r.bad && !over && !short;
    sum.hidden = !state.view.communities.length;
    sum.className = "sum " + (right ? "ok" : "bad");
    sum.textContent = r.bad ? "בכל תיבה צריך מספר בין 0 ל־100 (עד ספרה אחת אחרי הנקודה)"
      : over ? "סך הכול " + tidy(r.sum) + "% · " + tidy(r.sum - 100) + " יותר מדי"
      : short ? "לכל הקהילות נקבע אחוז, ולכן הסכום צריך להיות 100 בדיוק (עכשיו " + tidy(r.sum) + ")"
      : r.sum === 0 ? "לא נקבע אחוז לאף קהילה: כולן מתחלקות לפי הגודל שלהן"
      : r.sum === 100 ? "סך הכול 100% ✓"
                      : "סך הכול " + tidy(r.sum) + "% · השאר מתחלק בין שאר הקהילות לפי הגודל שלהן";
    var changed = r.bad || !sameCommunities(r.percents);
    $("cSave").disabled = !right || !changed;
    $("cSave").title = right ? "" : "אי אפשר לשמור: האחוזים לא מסתדרים";
    $("cUndo").hidden = !changed;
    ask("c", right && changed ? { communities: r.percents } : null);
  }

  function fill() {
    var v = state.view;
    v.number_fields.forEach(function (f) { $("n_" + f.name).value = v.numbers[f.name]; });
    v.weights.forEach(function (w) { $("w_" + w.key).value = w.value; });
    v.communities.forEach(function (c, i) { $("c_" + i).value = c.percent; });
    numbersTyped();
    weightsTyped();
    communitiesTyped();
  }

  function build() {
    var v = state.view;
    var rows = $("numRows");
    clear(rows);
    v.number_fields.forEach(function (f) {
      var row = el("div", "wrow");
      var label = el("label", null, f.name === "cooldown_weeks" ? "כמה שבועות חד־פעמי מחכה אחרי שקיבל " : f.label);
      label.htmlFor = "n_" + f.name;
      if (f.name === "cooldown_weeks") { label.appendChild(el("small", null, "0 = בלי הפסקה")); }
      row.appendChild(label);
      var input = numberInput("n_" + f.name, f.max, "1");
      input.addEventListener("input", numbersTyped);
      row.appendChild(input);
      rows.appendChild(row);
    });
    rows = $("wRows");
    clear(rows);
    v.weights.forEach(function (w) {
      var row = el("div", "wrow");
      var label = el("label", null, w.label);
      label.htmlFor = "w_" + w.key;
      row.appendChild(label);
      var pct = el("span", "pct");
      var input = numberInput("w_" + w.key, 100, "0.1");
      input.addEventListener("input", weightsTyped);
      pct.appendChild(input);
      pct.appendChild(document.createTextNode("%"));
      row.appendChild(pct);
      rows.appendChild(row);
    });
    rows = $("cRows");
    clear(rows);
    v.communities.forEach(function (c, i) {
      var row = el("div", "wrow");
      var label = el("label", null, c.name + " ");
      label.htmlFor = "c_" + i;
      label.appendChild(el("small", null, c.size === 1 ? "מקבל פעיל אחד" : c.size + " מקבלים פעילים"));
      row.appendChild(label);
      var pct = el("span", "pct");
      var input = numberInput("c_" + i, 100, "0.1");
      input.addEventListener("input", communitiesTyped);
      pct.appendChild(input);
      pct.appendChild(document.createTextNode("%"));
      row.appendChild(pct);
      rows.appendChild(row);
    });
    $("cNone").hidden = v.communities.length > 0;
    $("cSave").hidden = !v.communities.length;
    $("cNoCommunity").hidden = !v.no_community;
    $("cNoCommunity").textContent = v.no_community === 1
      ? "יש מקבל פעיל אחד בלי קהילה. הוא מקבל חלק כמו קהילה קטנה (\"" + v.no_community_label + "\")."
      : "יש " + v.no_community + " מקבלים פעילים בלי קהילה. יחד הם מקבלים חלק לפי מספרם, כמו קהילה (\"" + v.no_community_label + "\").";
    $("wDefaults").textContent = "חזרה לברירת המחדל (" + v.weights.filter(function (w) { return w["default"] > 0; })
      .map(function (w) { return w["default"]; }).join(", ") + ")";
    $("queueNote").textContent = "התור של החד־פעמיים לא מושפע מהמשקלים. יש לו נוסחה קבועה: " +
      v.one_time_queue.map(function (q) { return q.value + "% " + q.label.replace(/ \(.*\)$/, ""); }).join(", ") + ".";
  }

  function load() {
    return getJSON("/api/settings").then(function (v) {
      var first = !state.view;
      // the list of communities itself may have changed (a card was edited in another tab): build it again
      var same = !first && JSON.stringify(state.view.communities.map(function (c) { return c.name; })) ===
                           JSON.stringify(v.communities.map(function (c) { return c.name; }));
      state.view = v;
      if (first || !same) { build(); }
      fill();
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את ההגדרות מהשרת. " + (e.message || ""), true);
    });
  }

  function save(url, body) {
    if (state.busy) { return; }
    setBusy(true);
    postJSON(url, body).then(function () {
      notice("נשמר. כל הרשימות הבאות חושבו מחדש.");
      return load();
    }).catch(function (e) { fail(e, "לא נשמר. "); }).then(function () { setBusy(false); });
  }

  $("numSave").addEventListener("click", function () {
    var n = readNumbers();
    if (n) { save("/api/settings/numbers", n); }
  });
  $("wSave").addEventListener("click", function () {
    var r = readWeights();
    if (!r.bad && r.sum === 100) { save("/api/settings/weights", { weights: r.weights }); }
  });
  $("numUndo").addEventListener("click", function () {
    state.view.number_fields.forEach(function (f) { $("n_" + f.name).value = state.view.numbers[f.name]; });
    numbersTyped();
  });
  $("wUndo").addEventListener("click", function () {
    state.view.weights.forEach(function (w) { $("w_" + w.key).value = w.value; });
    weightsTyped();
  });
  $("cSave").addEventListener("click", function () {
    var r = readCommunities();
    if (!r.bad && r.sum <= 100 && !(r.all && r.sum !== 100)) { save("/api/settings/communities", { percents: r.percents }); }
  });
  $("cUndo").addEventListener("click", function () {
    state.view.communities.forEach(function (c, i) { $("c_" + i).value = c.percent; });
    communitiesTyped();
  });
  $("wDefaults").addEventListener("click", function () {
    state.view.weights.forEach(function (w) { $("w_" + w.key).value = w["default"]; });
    weightsTyped();
  });

  // ── backup and restore (stage 5) ───────────────────────────────────────────
  // The page shows the list of backups (when, why, how big). Before a restore it asks the
  // server how much the backup holds beside how much the site holds now, shows the two side
  // by side, and restores only after "yes". A backup's content never reaches the page.
  var BK_SHOWN = 8;                     // how many backups the list shows before "show all"
  var bk = { list: [], all: false, asked: null, fresh: "" };
  var BK_ROWS = [["cards", "כרטיסים"], ["active", "מהם פעילים"], ["history_rows", "רישומים בהיסטוריה"],
                 ["rounds", "חלוקות בהיסטוריה"], ["last_week", "ההיסטוריה מגיעה עד"], ["events_ahead", "חלוקות חג שלפנינו"]];

  function when(text) {                 // "2026-11-26 08:12" -> "26/11/2026 בשעה 08:12"
    var p = String(text || "").split(" ");
    return /^\d{4}-\d{2}-\d{2}$/.test(p[0]) ? H.longDate(p[0]) + (p[1] ? " בשעה " + p[1] : "") : String(text || "");
  }
  function bkSay(text, isError) {
    var n = $("bkSay");
    n.textContent = text || "";
    n.className = "notice" + (isError ? " error" : "");
    n.hidden = !text;
  }
  function closeAsk() {
    bk.asked = null;
    $("bkAsk").hidden = true;
  }

  function showBackups(v) {
    bk.list = v.backups;
    var last = v.backups[0];
    $("bkLast").textContent = last ? H.dm(last.taken_at.split(" ")[0]) + " · " + last.taken_at.split(" ")[1] : "אין";
    $("bkLastWhy").textContent = last ? "הגיבוי האחרון · " + last.reason_text : "הגיבוי האחרון";
    $("bkCount").textContent = String(v.total);
    var mb = v.total_kb >= 1024;
    $("bkSize").textContent = mb ? tidy(v.total_kb / 1024) : String(v.total_kb);
    $("bkSizeUnit").textContent = mb ? "מ\"ב יחד" : "ק\"ב יחד";
    $("bkMissing").hidden = v.auto_today;
    $("bkFolder").textContent = v.folder;
    $("bkWhere").hidden = !v.folder;
    var rows = $("bkRows");
    clear(rows);
    var shown = bk.all ? v.backups : v.backups.slice(0, BK_SHOWN);
    shown.forEach(function (b) {
      var row = el("div", "bkrow" + (b.name === bk.fresh ? " fresh" : ""));
      row.appendChild(el("span", "d", H.longDate(b.taken_at.split(" ")[0])));
      row.appendChild(el("span", "t", b.taken_at.split(" ")[1]));
      row.appendChild(el("span", "why-taken", b.reason_text));
      row.appendChild(el("span", "size", b.size_kb >= 1024 ? tidy(b.size_kb / 1024) + " מ\"ב" : b.size_kb + " ק\"ב"));
      var go = el("button", "btn small quiet go", "שחזר למצב הזה");
      go.type = "button";
      go.addEventListener("click", function () { askRestore(b); });
      row.appendChild(go);
      rows.appendChild(row);
    });
    $("bkNone").hidden = v.backups.length > 0;
    var more = v.backups.length - BK_SHOWN;
    $("bkMore").hidden = bk.all || more <= 0;
    $("bkMore").textContent = "הצג את כל " + v.backups.length + " הגיבויים";
  }
  // On the server: does a copy of the backup leave it, and when did the last one leave.
  function showOffsite(v) {
    var late = $("osLate"), line = $("osLine");
    late.hidden = true;
    line.hidden = true;
    if (!v.show) { return; }                              // on this computer: nothing to say
    if (!v.on) {
      late.textContent = "עוד לא יוצא גיבוי מחוץ לשרת. עד שמחברים, הגיבויים נמצאים רק בשרת עצמו.";
      late.hidden = false;
    } else if (v.late) {
      late.textContent = (v.last_ok ? "הגיבוי האחרון שיצא מהשרת הוא מ־" + H.stamp(v.last_ok) + "." : "עוד לא יצא אף גיבוי מהשרת.") +
        " הוא אמור לצאת לבד פעם ביום. צריך לומר ליהודה.";
      late.hidden = false;
    } else {
      line.textContent = "עותק של הנתונים יוצא מהשרת לבד פעם ביום. האחרון יצא ב־" + H.stamp(v.last_ok) + ".";
      line.hidden = false;
    }
  }
  // Google Drive: connect, the recovery key (shown once), disconnect.
  var DRIVE_SAID = { "drive-ok": "Google Drive חובר. מעכשיו יוצא אליו עותק מוצפן פעם ביום.",
                     "drive-again": "החיבור ל-Google Drive לא הושלם. אפשר לנסות שוב.",
                     "drive-no_permission": "החיבור לא הושלם: צריך לסמן אצל Google את האישור לשמור קבצים ב-Drive.",
                     "drive-off": "חיבור ל-Google Drive לא מוגדר בשרת." };
  function showDrive(v) {
    $("drBox").hidden = !v.available;
    if (!v.available) { return; }
    $("drLine").textContent = v.connected
      ? "מחובר מאז " + H.stamp(v.since) + ". כל עותק מוצפן לפני שהוא יוצא, והאתר רואה ב-Drive רק את הקבצים שהוא עצמו שם שם."
      : "לא מחובר. אחרי החיבור יוצא ל-Drive עותק מוצפן של הנתונים פעם ביום. האתר יראה ב-Drive רק את הקבצים שהוא עצמו שם שם.";
    $("drConnect").hidden = v.connected;
    $("drOff").hidden = !v.connected;
    $("drKeyBox").hidden = !v.key;
    $("drKey").textContent = v.key || "";
  }
  function loadDrive() {
    return getJSON("/api/drive").then(showDrive).catch(function () { /* the rest of the screen still works */ });
  }
  $("drKept").addEventListener("click", function () { postJSON("/api/drive/key-kept", {}).then(showDrive); });
  $("drOff").addEventListener("click", function () {
    postJSON("/api/drive/disconnect", {}).then(function (v) {
      showDrive(v);
      bkSay("Google Drive נותק. הגיבויים שכבר שם נשארים, והמפתח שלהם לא השתנה.");
      getJSON("/api/offsite").then(showOffsite);
    });
  });
  if (DRIVE_SAID[location.hash.slice(1)]) {
    bkSay(DRIVE_SAID[location.hash.slice(1)], location.hash !== "#drive-ok");
    history.replaceState(null, "", "/settings");
    $("bkPanel").scrollIntoView();
  }
  function loadBackups() {
    loadDrive();
    getJSON("/api/offsite").then(showOffsite).catch(function () { /* the list below still loads */ });
    return getJSON("/api/backups").then(showBackups).catch(function (e) {
      if (e.status !== 503) { bkSay("לא הצלחתי לקבל את רשימת הגיבויים. " + (e.message || ""), true); }
    });
  }

  // The backup beside the site as it is now, and what a restore would do — then "yes" or "cancel".
  function askRestore(b) {
    if (state.busy) { return; }
    setBusy(true);
    bkSay("");
    getJSON("/api/backup?name=" + encodeURIComponent(b.name)).then(function (v) {
      bk.asked = v;
      $("bkAskTitle").textContent = "לשחזר את האתר למצב של " + when(v.taken_at) + "? (" + v.reason_text + ")";
      var cmp = $("bkCmp");
      clear(cmp);
      cmp.appendChild(el("div", "cmp-head", ""));
      cmp.appendChild(el("div", "cmp-head", "בגיבוי"));
      cmp.appendChild(el("div", "cmp-head", "עכשיו"));
      var same = true;
      BK_ROWS.forEach(function (r) {
        var a = v.backup[r[0]], n = v.now[r[0]];
        var differs = a !== n;
        if (differs) { same = false; }
        var text = function (x) { return r[0] === "last_week" ? (x ? H.longDate(x) : "אין") : String(x); };
        cmp.appendChild(el("div", "cmp-label", r[1]));
        cmp.appendChild(el("div", "num" + (differs ? " cmp-diff" : ""), text(a)));
        cmp.appendChild(el("div", "num" + (differs ? " cmp-diff" : ""), text(n)));
      });
      var notes = $("bkAskNotes");
      clear(notes);
      if (same) { notes.appendChild(el("p", null, "לפי המספרים האלה הגיבוי זהה למה שיש באתר עכשיו. ייתכן שיש הבדל בפרטים של כרטיסים, בהגדרות או במה שנקבע ביד.")); }
      notes.appendChild(el("p", null, "כל מה שנעשה באתר אחרי הגיבוי הזה (כרטיסים, שינויים ביד, הגדרות) יחזור למצב שבגיבוי."));
      if (v.weeks_to_redo > 0) {
        notes.appendChild(el("p", null, (v.weeks_to_redo === 1 ? "מאז הגיבוי נכנס להיסטוריה שבוע אחד. אחרי השחזור האתר יכתוב אותו שוב"
          : "מאז הגיבוי נכנסו להיסטוריה " + v.weeks_to_redo + " שבועות. אחרי השחזור האתר יכתוב אותם שוב") +
          ", כפי שהוא מחשב ממה שיש בגיבוי."));
      }
      notes.appendChild(el("p", null, "לפני השחזור נשמר גיבוי של המצב של עכשיו, כך שאפשר להתחרט ולחזור אליו."));
      $("bkAsk").hidden = false;
      $("bkAsk").focus();
      $("bkAsk").scrollIntoView({ block: "nearest" });
    }).catch(function (e) { closeAsk(); bkSay("אי אפשר לשחזר מהגיבוי הזה. " + (e.message || ""), true); })
      .then(function () { setBusy(false); });
  }

  $("bkNo").addEventListener("click", closeAsk);
  $("bkYes").addEventListener("click", function () {
    var v = bk.asked;
    if (!v || state.busy) { return; }
    setBusy(true);
    postJSON("/api/backup/restore", { name: v.name }).then(function (done) {
      closeAsk();
      bk.fresh = done.safety;
      bkSay("האתר חזר למצב של " + when(v.taken_at) + ". המצב שהיה לפני השחזור שמור בגיבוי \"לפני שחזור\" (מסומן ברשימה), ואפשר לחזור אליו.");
      return load().then(loadBackups);
    }).catch(function (e) { bkSay("לא שוחזר. " + (e.message || ""), true); return loadBackups(); })
      .then(function () { setBusy(false); });
  });
  $("bkMake").addEventListener("click", function () {
    if (state.busy) { return; }
    setBusy(true);
    closeAsk();
    postJSON("/api/backup/make", {}).then(function (done) {
      bk.fresh = done.name;
      bkSay("נשמר גיבוי של המצב של עכשיו.");
      return loadBackups();
    }).catch(function (e) { bkSay("הגיבוי לא נשמר. " + (e.message || ""), true); })
      .then(function () { setBusy(false); });
  });
  $("bkMore").addEventListener("click", function () {
    bk.all = true;
    loadBackups();
  });

  load().then(loadBackups);
}());
