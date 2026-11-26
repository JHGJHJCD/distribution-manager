/* מנהל חלוקה — מסך ההגדרות (שלב 4): המספרים הרגילים של שבוע ומשקלי הניקוד.
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

  load();
}());
