/* מנהל חלוקה — מסך הכניסה (רק כשהאתר בשרת). עומד בפני עצמו: בלי common.js, כי בלי כניסה
   השרת לא מגיש שום קובץ אחר. */
(function () {
  "use strict";
  var form = document.getElementById("loginForm");
  var note = document.getElementById("notice");
  var go = document.getElementById("loginGo");

  function say(text) { note.textContent = text || ""; note.hidden = !text; }

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
