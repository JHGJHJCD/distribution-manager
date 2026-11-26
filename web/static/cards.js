/* מנהל חלוקה — מסך המקבלים (שלב 3): רשימה, חיפוש, כרטיס, הוספה, עריכה, השהיה.
   הדף לא מחליט שום כלל: השרת בודק את מה שנשלח ומחזיר משפט על כל שדה שגוי.
   כל טקסט שמגיע מהנתונים נכנס עם textContent / value בלבד. */
(function () {
  "use strict";

  var TYPE = { "שבועי": "w1", "דו-שבועי": "w2", "תלת-שבועי": "w3", "חודשי": "w4" };
  // the form: [group title, [[field, label, type, wide?]]]
  var GROUPS = [
    ["פרטים בסיסיים", [
      ["first_name", "שם פרטי *", "text"], ["last_name", "משפחה", "text"],
      ["phone1", "טלפון", "tel"], ["phone2", "טלפון נוסף", "tel"], ["phone3", "טלפון נוסף", "tel"],
      ["address", "כתובת", "text"], ["souls", "נפשות", "number"],
      ["status", "סטטוס", "status"], ["kind", "סוג", "kind"], ["schedule", "תדירות", "schedule"],
      ["holiday_support", "מקבל גם בחגים", "check"], ["notes", "הערות", "area", true]]],
    ["פרטים אישיים", [
      ["birth_date", "ת. לידה בעל", "date"], ["spouse_birth_date", "ת. לידה אשה", "date"],
      ["id_number", "ת.ז. בעל", "text"], ["spouse_id_number", "ת.ז. אשה", "text"],
      ["marital_status", "מצב אישי", "text"], ["email", "אימייל", "text"], ["synagogue", "בית כנסת", "text"],
      ["occupation", "עיסוק בעל", "text"], ["work_scope", "היקף משרה", "text"], ["parent_type", "סוג הורה", "text"]]],
    ["ילדים וכלכלה", [
      ["children_home", "ילדים בבית", "number"], ["children_married", "ילדים נשואים", "number"],
      ["children_total", "מספר ילדים", "number"], ["housing_expenses", "הוצאות דיור", "text"],
      ["medical_expenses", "הוצאות רפואיות", "text"], ["income", "הכנסות", "text"], ["per_soul", "פנוי לנפש", "text"]]],
    ["מידע מנהלי", [
      ["external_id", "מס' מזהה", "text"], ["source", "מקור", "text"], ["representative", "שם נציג", "text"]]]
  ];
  var state = { list: null, card: null, guid: null, busy: false };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  function dmy(iso) { var p = String(iso || "").split("-"); return p.length === 3 ? Number(p[2]) + "/" + Number(p[1]) + "/" + p[0] : ""; }
  function norm(s) { return String(s || "").replace(/["'׳״\-־()+]/g, "").replace(/\s+/g, " ").trim().toLowerCase(); }

  function answer(r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      if (!r.ok) {
        var err = new Error(body.message || (typeof body.detail === "string" ? body.detail : "") ||
          (r.status === 422 ? "הנתונים שנשלחו לא תקינים" : "שגיאה " + r.status));
        err.status = r.status;
        err.body = body;
        throw err;
      }
      return body;
    });
  }
  function getJSON(url) { return fetch(url, { headers: { "Accept": "application/json" } }).then(answer); }
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
  function setBusy(on) { state.busy = on; document.body.classList.toggle("busy", on); }

  // ── the list ───────────────────────────────────────────────────────────────
  function loadList() {
    return getJSON("/api/cards").then(function (list) {
      state.list = list;
      renderList();
      var b = $("showDups");
      b.hidden = !list.duplicates;
      b.textContent = list.duplicates === 1 ? "כרטיס שאולי כפול" : list.duplicates + " כרטיסים שאולי כפולים";
    }).catch(function (e) {
      notice(e.status === 503 ? e.message : "לא הצלחתי לקבל את רשימת המקבלים. " + (e.message || ""), true);
    });
  }

  function renderList() {
    var cards = state.list.cards;
    var active = cards.filter(function (c) { return c.status === "פעיל"; }).length;
    $("count").textContent = cards.length + " כרטיסים · " + active + " פעילים · " + (cards.length - active) + " מושהים";
    var words = norm($("q").value).split(" ").filter(Boolean);
    var status = $("fStatus").value;
    var digits = $("q").value.replace(/\D/g, "");
    var found = cards.filter(function (c) {
      if (status && c.status !== status) { return false; }
      if (!words.length) { return true; }
      var hay = norm(c.name);
      return words.every(function (w) { return hay.indexOf(w) >= 0; }) ||
        (digits.length >= 3 && c.phone.replace(/\D/g, "").indexOf(digits) >= 0);
    });
    var box = $("rows");
    clear(box);
    found.forEach(function (c) {
      var li = el("li");
      var b = el("button", c.status === "פעיל" ? null : "paused");
      b.type = "button";
      b.setAttribute("aria-current", c.guid === state.guid ? "true" : "false");
      var sw = el("i", "sw" + (c.kind === "regular" ? " t-" + (TYPE[c.kind_text] || "w1") : c.takes_part ? " t-one" : ""));
      b.appendChild(sw);
      b.appendChild(el("span", null, c.name));
      b.appendChild(c.status === "פעיל" ? el("span") : el("span", "tag", c.status));
      b.appendChild(el("small", null, c.kind_text + (c.phone ? " · " + c.phone : "") + (c.souls ? " · " + c.souls + " נפשות" : "")));
      b.addEventListener("click", function () { openCard(c.guid); });
      li.appendChild(b);
      box.appendChild(li);
    });
    if (!found.length) { box.appendChild(el("li", "none", "אין כרטיס שמתאים לחיפוש.")); }
  }

  // ── the card ───────────────────────────────────────────────────────────────
  function input(field, type) {
    var n;
    if (type === "area") { n = el("textarea"); }
    else if (type === "status" || type === "kind" || type === "schedule") {
      n = el("select");
      var options = type === "status" ? [["פעיל", "פעיל"], ["מושהה", "מושהה"]]
        : type === "kind" ? state.list.kinds.map(function (k) { return [k.value, k.label]; })
        : state.list.schedules.map(function (s) { return [s, s]; });
      options.forEach(function (o) { var opt = el("option", null, o[1]); opt.value = o[0]; n.appendChild(opt); });
    } else {
      n = el("input");
      n.type = type === "check" ? "checkbox" : type;
      if (type === "number") { n.min = "0"; n.inputMode = "numeric"; }
      if (type === "tel") { n.dir = "ltr"; }
    }
    n.id = "f_" + field;
    n.name = field;
    n.autocomplete = "off";
    return n;
  }

  function buildForm() {
    var box = $("groups");
    clear(box);
    GROUPS.forEach(function (g) {
      var set = el("fieldset");
      set.appendChild(el("legend", null, g[0]));
      g[1].forEach(function (f) {
        var wrap = el("div", "field" + (f[3] ? " wide" : "") + (f[2] === "check" ? " check" : ""));
        wrap.id = "w_" + f[0];
        var label = el("label", null, f[1]);
        label.htmlFor = "f_" + f[0];
        var control = input(f[0], f[2]);
        if (f[2] === "check") { wrap.appendChild(control); wrap.appendChild(label); }
        else { wrap.appendChild(label); wrap.appendChild(control); }
        set.appendChild(wrap);
      });
      box.appendChild(set);
    });
    $("f_kind").addEventListener("change", showSchedule);
  }
  function showSchedule() { $("w_schedule").hidden = $("f_kind").value !== "regular"; }

  function fill(card) {
    GROUPS.forEach(function (g) {
      g[1].forEach(function (f) {
        var n = $("f_" + f[0]);
        var v = card[f[0]];
        if (f[2] === "check") { n.checked = !!v; }
        else if (f[0] === "schedule") { n.value = v || state.list.schedules[0]; }
        else { n.value = v === undefined || v === null ? "" : v; }
      });
    });
    showSchedule();
  }

  function collect() {
    var out = {};
    GROUPS.forEach(function (g) {
      g[1].forEach(function (f) {
        var n = $("f_" + f[0]);
        out[f[0]] = f[2] === "check" ? n.checked : f[2] === "number" ? (n.value.trim() === "" ? 0 : Number(n.value)) : n.value;
      });
    });
    return out;
  }

  function fieldErrors(fields) {
    Array.prototype.forEach.call(document.querySelectorAll(".field .err"), function (n) { n.remove(); });
    Array.prototype.forEach.call(document.querySelectorAll(".field.bad"), function (n) { n.classList.remove("bad"); });
    var first = null;
    Object.keys(fields || {}).forEach(function (key) {
      var wrap = $("w_" + key);
      if (!wrap) { return; }
      wrap.classList.add("bad");
      wrap.appendChild(el("span", "err", fields[key]));
      first = first || $("f_" + key);
    });
    if (first) { first.focus(); }
  }

  function twinsBox(list, asking) {
    var box = $("twins");
    clear(box);
    if (!list || !list.length) { return; }
    var warn = el("div", "warn", asking ? "כבר יש כרטיס שנראה כמו אותו אדם. לא שמרתי עדיין. " : "שימו לב, יש כרטיס דומה: ");
    list.forEach(function (t, i) {
      if (i) { warn.appendChild(document.createTextNode(" · ")); }
      var b = el("button", "linkish", t.name);
      b.type = "button";
      b.addEventListener("click", function () { openCard(t.guid); });
      warn.appendChild(b);
      warn.appendChild(document.createTextNode(" (" + t.why + (t.status === "פעיל" ? "" : ", " + t.status) + ")"));
    });
    if (asking) {
      var row = el("div", "actions");
      var yes = el("button", "btn small", "אלה שני אנשים שונים, שמור כרטיס חדש");
      yes.type = "button";
      yes.id = "confirmNew";
      yes.addEventListener("click", function () { save(true); });
      row.appendChild(yes);
      warn.appendChild(row);
    }
    box.appendChild(warn);
  }

  function showCard(card) {
    state.card = card;
    state.guid = card ? card.guid : null;
    $("form").hidden = false;
    $("hint").hidden = true;
    fieldErrors({});
    $("cardTitle").textContent = card ? card.name : "מקבל חדש";
    var facts = [];
    if (card) {
      facts.push(card.received_count ? "קיבל " + card.received_count + " פעמים, לאחרונה ב־" + dmy(card.last_received) : "עוד לא קיבל אף פעם");
      if (card.created_at) { facts.push("הכרטיס נפתח ב־" + dmy(card.created_at)); }
    }
    $("facts").textContent = facts.join(" · ");
    fill(card || { status: "פעיל", kind: "regular", schedule: state.list.schedules[0], souls: "" });
    twinsBox(card ? card.lookalikes : [], false);
    var toggle = $("toggle");
    toggle.hidden = !card;
    if (card) { toggle.textContent = card.status === "פעיל" ? "השהה" : "החזר לפעיל"; }
    var changes = $("changes");
    clear(changes);
    (card ? card.changes : []).forEach(function (c) {
      changes.appendChild(el("li", null, dmy(c.at.slice(0, 10)) + " " + c.at.slice(11) + ": " +
        (c.field ? c.field + ": " + (c.old || "ריק") + " ← " + (c.new || "ריק") : c.new)));
    });
    $("changesBox").hidden = !card || !card.changes.length;
    if (state.list) { renderList(); }
  }

  function openCard(guid) {
    notice("");
    return getJSON("/api/card?guid=" + encodeURIComponent(guid)).then(showCard).catch(function (e) {
      notice("לא הצלחתי לפתוח את הכרטיס. " + (e.message || ""), true);
    });
  }

  // After a save the server has already recomputed every coming week; say when he receives.
  function whenReceives(card) {
    return getJSON("/api/plan?weeks=8").then(function (plan) {
      var gets = plan.weeks.filter(function (w) { return w.main.indexOf(card.guid) >= 0; })
        .map(function (w) { var p = w.date.split("-"); return Number(p[2]) + "/" + Number(p[1]); });
      return gets.length ? " בשמונת השבועות הקרובים מקבל ב: " + gets.join(", ") + "." : " בשמונת השבועות הקרובים לא נמצא ברשימות.";
    }).catch(function () { return ""; });
  }

  function save(confirmed, only) {
    if (state.busy) { return; }
    var adding = !state.card;
    var body = { guid: adding ? null : state.card.guid, updated_at: adding ? null : state.card.updated_at,
                 confirmed: !!confirmed, card: only || collect() };
    setBusy(true);
    postJSON("/api/card", body).then(function (card) {
      showCard(card);
      return Promise.all([loadList(), whenReceives(card)]).then(function (r) {
        notice((adding ? "הכרטיס נוסף." : card.changed ? "נשמר." : "לא היה מה לשמור, שום דבר לא השתנה.") +
               " כל השבועות חושבו מחדש." + r[1]);
      });
    }).catch(function (e) {
      var b = e.body || {};
      if (b.code === "duplicate") { twinsBox(b.duplicates, true); notice(""); $("twins").scrollIntoView({ block: "nearest" }); return; }
      if (b.code === "stale") { return openCard(state.card.guid).then(function () { notice(e.message, true); }); }
      fieldErrors(b.fields);
      notice("לא נשמר. " + (e.message || ""), true);
    }).then(function () { setBusy(false); });
  }

  // ── may be the same person twice ───────────────────────────────────────────
  function showDups() {
    var box = $("dups");
    if (!box.hidden) { box.hidden = true; return; }
    getJSON("/api/duplicates").then(function (d) {
      clear(box);
      box.appendChild(el("p", "sub", "כרטיסים עם אותו שם או אותו טלפון. לחיצה על שם פותחת את הכרטיס. מיזוג של שני כרטיסים עוד לא קיים באתר."));
      d.groups.forEach(function (g) {
        var row = el("div", "dup");
        row.appendChild(el("b", null, g.why + ": " + g.key));
        g.cards.forEach(function (c, i) {
          if (i) { row.appendChild(document.createTextNode(" · ")); }
          var b = el("button", "linkish", c.name + (c.status === "פעיל" ? "" : " (" + c.status + ")"));
          b.type = "button";
          b.addEventListener("click", function () { openCard(c.guid); });
          row.appendChild(b);
        });
        box.appendChild(row);
      });
      box.hidden = false;
    }).catch(function (e) { notice("לא הצלחתי לקבל את רשימת הכפולים. " + (e.message || ""), true); });
  }

  $("q").addEventListener("input", renderList);
  $("fStatus").addEventListener("change", renderList);
  $("newCard").addEventListener("click", function () { notice(""); showCard(null); $("f_first_name").focus(); });
  $("showDups").addEventListener("click", showDups);
  $("form").addEventListener("submit", function (e) { e.preventDefault(); save(false); });
  $("toggle").addEventListener("click", function () {
    if (state.card) { save(false, { status: state.card.status === "פעיל" ? "מושהה" : "פעיל" }); }
  });

  loadList().then(function () {
    if (!state.list) { return; }
    buildForm();
    var guid = new URLSearchParams(window.location.search).get("guid");
    if (guid) { openCard(guid); }
  });
}());
