/* מנהל חלוקה — מה שמשותף לכל הדפים: בניית רכיבים, ובקשות לשרת.
   כל טקסט שמגיע מהנתונים נכנס לדף עם textContent בלבד. */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  function dm(iso) { var p = iso.split("-"); return Number(p[2]) + "/" + Number(p[1]); }
  function answer(r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      if (r.status === 401 && body.login && location.pathname !== "/login") {
        location.href = "/login";                        // the session ended: back to the login page
      }
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

  // ── lists of people, as chips (the weeks screen and the holiday screen) ─────
  var TYPE = { "שבועי": "w1", "דו-שבועי": "w2", "תלת-שבועי": "w3", "חודשי": "w4" };
  var NAMES_SHOWN = 6;                  // how many names at most in "changed since it was printed"

  // the colour of a person: by frequency for a regular, one colour for one-timers, and a
  // plain chip for a card that takes no part in the weekly lists (holiday lists only)
  function typeOf(kind, freq) {
    if (kind === "onetime") { return "one"; }
    return kind === "other" ? "other" : (TYPE[freq] || "w1");
  }
  function chip(entry, selected, onPick) {
    var b = el("button", "chip t-" + typeOf(entry.kind, entry.freq) + (entry.manual ? " manual" : "") +
               (selected ? " sel" : ""), entry.name);
    b.type = "button";
    if (entry.manual) { b.title = "נקבע ביד"; }
    b.addEventListener("click", function () { onPick(entry); });
    return b;
  }
  function group(title, entries, makeChip, cls) {
    var g = el("div", "grp" + (cls ? " " + cls : ""));
    var h = el("h4", null, title + " ");
    h.appendChild(el("b", null, String(entries.length)));
    g.appendChild(h);
    var chips = el("div", "chips");
    entries.forEach(function (e) { chips.appendChild(makeChip(e)); });
    g.appendChild(chips);
    return g;
  }

  // "2026-11-25 20:30" -> "25/11 בשעה 20:30"
  function stamp(text) {
    var parts = String(text || "").split(" ");
    return /^\d{4}-\d{2}-\d{2}$/.test(parts[0]) ? dm(parts[0]) + (parts[1] ? " בשעה " + parts[1] : "") : String(text || "");
  }
  function nameList(names, count) {
    if (!names) { return String(count); }                // only how many is known
    var shown = names.slice(0, NAMES_SHOWN).join(", ");
    return names.length > NAMES_SHOWN ? shown + " ועוד " + (names.length - NAMES_SHOWN) : shown;
  }
  // The reminder "changed since it was printed" (it never holds anything in place), or a
  // quiet line when the list is still the one on the paper. null when it was never printed.
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
  function norm(s) { return String(s || "").replace(/["'׳״\-־]/g, "").replace(/\s+/g, " ").trim().toLowerCase(); }
  function longDate(iso) { var p = iso.split("-"); return Number(p[2]) + "/" + Number(p[1]) + "/" + p[0]; }

  // On the server (login is on) the row of screens ends with who entered and "יציאה".
  // On this computer the answer is "no login" and the page stays as it is.
  function showWhoEntered() {
    var nav = document.querySelector("nav.nav");
    if (!nav) { return; }
    getJSON("/api/me").then(function (me) {
      if (!me.login) { return; }
      var box = el("span", "who");
      box.appendChild(el("span", null, me.name));
      var out = el("button", "btn quiet", "יציאה");
      out.type = "button";
      out.addEventListener("click", function () {
        postJSON("/api/logout", {}).then(function () { location.href = "/login"; }, function () { location.href = "/login"; });
      });
      box.appendChild(out);
      nav.appendChild(box);
    }).catch(function () { /* the page works without it */ });
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", showWhoEntered); }
  else { showWhoEntered(); }

  window.Haluka = { $: $, el: el, clear: clear, dm: dm, getJSON: getJSON, postJSON: postJSON, notice: notice,
                    typeOf: typeOf, chip: chip, group: group, stamp: stamp, printNote: printNote, norm: norm,
                    longDate: longDate };
}());
