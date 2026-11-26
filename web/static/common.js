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

  window.Haluka = { $: $, el: el, clear: clear, dm: dm, getJSON: getJSON, postJSON: postJSON, notice: notice };
}());
