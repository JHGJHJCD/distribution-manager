/* מנהל חלוקה — מסך הכניסה (רק כשהאתר בשרת). עומד בפני עצמו: בלי common.js, כי בלי כניסה
   השרת לא מגיש שום קובץ אחר. */
(function () {
  "use strict";
  var form = document.getElementById("loginForm");
  var note = document.getElementById("notice");
  var go = document.getElementById("loginGo");

  function say(text) { note.textContent = text || ""; note.hidden = !text; }

  // which ways in this server offers, and what the way back from Google said
  var ways = (document.body.getAttribute("data-ways") || "").split(" ");
  var google = ways.indexOf("google") >= 0, password = ways.indexOf("password") >= 0;
  document.getElementById("loginGoogle").hidden = !google;
  document.getElementById("loginHelp").hidden = !google;
  form.hidden = !password;
  document.getElementById("loginNone").hidden = google || password;
  var WHY = { "not_allowed": "החשבון הזה לא מורשה להיכנס לאתר. אפשר לנסות עם חשבון Google אחר.",
              "again": "הכניסה לא הושלמה. אפשר לנסות שוב.", "off": "כניסה עם Google לא מוגדרת באתר." };
  var why = WHY[location.hash.slice(1)];
  if (why) { say(why); history.replaceState(null, "", "/login"); }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    say("");
    go.disabled = true;
    fetch("/api/login", {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json", "X-Haluka": "1" },
      body: JSON.stringify({ name: document.getElementById("loginName").value,
                             password: document.getElementById("loginPass").value })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (r.ok) { location.href = "/"; return; }
        say(body.message || (r.status === 422 ? "צריך למלא שם וסיסמה" : "הכניסה לא הצליחה. אפשר לנסות שוב."));
        document.getElementById("loginPass").value = "";
        document.getElementById("loginPass").focus();
      });
    }).catch(function () { say("אין חיבור לאתר. אפשר לנסות שוב בעוד רגע."); })
      .then(function () { go.disabled = false; });
  });
}());
