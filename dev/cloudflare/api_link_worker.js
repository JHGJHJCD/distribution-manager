// ── שרת המענה של "מנהל חלוקה" (Cloudflare Worker) ─────────────────────────
// מקור-אמת של הקוד שפרוס במרחב-הפיתוח של פתרונאי ("פיתוחים אישיים").
// נוצר מהתבנית "סקריפט לקו הטלפון (api_link)" והותאם לצינתוקים.
//
// כתובת חיה (deploy):  https://pai-dev-s-api-link.pai-ffff542b.workers.dev
// מסד נתונים:          D1, נגיש כ-env.DB (נוצר אוטומטית ע"י התבנית)
// סוד:                 env.APP_SECRET  (מוגדר ב"סודות (env)" בדפדפן, לא בקוד/לא ב-git)
//
// שלושה סוגי פניות על אותה כתובת:
//   • ברירת מחדל  → הקו של ימות (api_link): אם יש חלוקה למתקשר, אוסף אישור 1/2/3
//   • POST /push   (מוגן בסוד) → התוכנה דוחפת את רשימת הזכאים של חלוקה אחת
//                    body: {dist_date:"YYYY-MM-DD", active_from?:"ISO-UTC",
//                           mode?:"both"|"message", recording?:true|false,
//                           phones:[{phone,name,active_from?}]}
//                    v3.37: mode = מה המתקשר שומע — both: ההקלטה (f-msg בשלוחה 76,
//                    התוכנה מעתיקה אותה בכל העלאה) ואז השאלה 1/2/3; message: ההקלטה
//                    בלבד (פעם אחת, טבלת heard). recording=false ⇒ אין קובץ בשלוחה
//                    (אסור לנסות להשמיע — ימות היו משמיעים "אין מענה") ⇒ שאלה ב-TTS.
//                    v3.36: מחליפה **רק** את הרשימה של אותו dist_date (רשימות של
//                    חלוקות אחרות נשארות), ו-active_from = מאיזה רגע השורה "חיה"
//                    (תזמון: שעת השיגור; שיגור חכם: שעת הקבוצה של כל אחד) — לפני
//                    הרגע הזה המתקשר לא נשאל (עוד לא צולצל אליו). רשימה ריקה = מחיקה.
//   • GET  /answers (מוגן בסוד) → התוכנה קוראת מי אישר (?dist_date=... אופציונלי)
//
// חיווט בקו (הכרעת המשתמש 9/9/2026 — אותו קו, בלי DID ייעודי):
//   • שלוחה /76: type=api + api_link=<הכתובת>  (התוכנה בודקת/מתקנת אותה, v3.34)
//   • Did_Go_To.ini בשורש: 048691834=/76  ⇒ כל מי שמחייג ל-04 עובר קודם דרך השרת
//   • השורש: check_did_and_go_to_folder_one_time=yes ⇒ החזרה ל-/ לא נכנסת שוב ל-76
//
// כלל ההתנהגות (9/9/2026): כל מתקשר ל-04 מגיע לכאן. מי שלא ברשימה פעילה, או שכבר
// ענה לאותה חלוקה — ממשיך **בשקט** לתפריט הראשי (go_to_folder=/), בלי שום הודעה.
// רק זכאי שטרם ענה שומע את השאלה "מגיע? 1 / 2 / 3", פעם אחת לחלוקה.
// כשיש לו כמה חלוקות פעילות (השבוע + חלוקה מיוחדת) — נשאל על החדשה ביותר שטרם ענה לה.
//
// ⚠ שגיאה בשרת/בקוד = ימות משמיעים "אין מענה" ויוצאים לשורש — לכן כל נתיב
//   הקו עטוף ב-try/catch שמחזיר go_to_folder=/ (המתקשר לא ירגיש שיש שרת).

import { isHangup, readYemotParams, reply } from './yemot.mjs';

// נרמול מספר אחיד לשני הצדדים (ספרות בלבד, 972 → 0)
const norm = (p) => {
  let d = (p || '').replace(/\D/g, '');
  if (d.startsWith('972')) d = '0' + d.slice(3);
  return d;
};

const TO_MENU = 'go_to_folder=/';            // המשך שקט לתפריט הראשי
const REC = 'f-msg';                         // ivr2:/76/msg.wav — ההקלטה של הצינתוק
const ASK = 'אם תגיע הקישו 1, אם לא תגיע הקישו 2, אם אינך יודע הקישו 3';
const READ_ARGS = '=Digits,,1,1,7,No,yes,no';
const QUESTION = 'read=t-שלום, יש לך חלוקה השבוע, ' + ASK + READ_ARGS;   // בלי הקלטה
const QUESTION_REC = 'read=' + REC + '.t-' + ASK + READ_ARGS;            // הקלטה ואז השאלה
const ASK_AGAIN = 'read=t-' + ASK + READ_ARGS;                           // הקשה לא מוכרת
const KEEP_DAYS = 45;                        // רשימות ישנות מזה נמחקות בדחיפה הבאה

// 'YYYY-MM-DDTHH:MM:SS(.ffffff)(+00:00|Z)' → 'YYYY-MM-DD HH:MM:SS' (UTC, בר-השוואה
// ל-datetime('now') של SQLite). ריק/לא תקין → null (= פעיל מיד).
function toSqlUtc(v) {
  if (!v) return null;
  const d = new Date(String(v));
  if (isNaN(d.getTime())) return null;
  return d.toISOString().slice(0, 19).replace('T', ' ');
}

async function ensureTables(env) {
  await env.DB.batch([
    // v3.36: שורה לכל (מספר, חלוקה) + מאיזה רגע היא פעילה. הטבלה הישנה week_list
    // (מפתח = מספר בלבד) הוחלפה; מה שהיה בה נמחק בדחיפה הראשונה ממילא.
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS week_lists (
      phone TEXT, dist_date TEXT, name TEXT, active_from TEXT,
      PRIMARY KEY (phone, dist_date))`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS answers (
      phone TEXT, dist_date TEXT, answer TEXT,
      at TEXT DEFAULT (datetime('now')),
      PRIMARY KEY (phone, dist_date))`),
    // v3.37: מצב ההשמעה לכל חלוקה + האם ההקלטה קיימת בשלוחה; ומי כבר שמע (מצב message)
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS list_meta (
      dist_date TEXT PRIMARY KEY, mode TEXT, recording INTEGER)`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS heard (
      phone TEXT, dist_date TEXT, at TEXT DEFAULT (datetime('now')),
      PRIMARY KEY (phone, dist_date))`),
    env.DB.prepare('DROP TABLE IF EXISTS week_list'),
  ]);
}

// ── דלתות התוכנה (מוגנות בסוד) ──
async function appApi(request, env, url) {
  if (url.searchParams.get('secret') !== env.APP_SECRET)
    return new Response('forbidden', { status: 403 });

  if (url.pathname === '/push') {
    const body = await request.json();
    const distDate = body.dist_date || '';
    const defaultFrom = toSqlUtc(body.active_from);
    const rows = (body.phones || []).filter(e => norm(e.phone));
    const mode = body.mode === 'message' ? 'message' : 'both';
    const stmts = [
      env.DB.prepare('DELETE FROM week_lists WHERE dist_date=?').bind(distDate),
      env.DB.prepare('INSERT OR REPLACE INTO list_meta (dist_date,mode,recording) VALUES (?,?,?)')
        .bind(distDate, mode, body.recording ? 1 : 0),
      // ניקוי רשימות של חלוקות ישנות (dist_date תאריכי בלבד; רשימה עצמאית '' נשארת)
      env.DB.prepare(`DELETE FROM week_lists WHERE dist_date<>'' AND dist_date<date('now',?)`)
        .bind(`-${KEEP_DAYS} days`),
    ];
    for (const e of rows) {
      stmts.push(env.DB.prepare(
        'INSERT OR REPLACE INTO week_lists (phone,dist_date,name,active_from) VALUES (?,?,?,?)')
        .bind(norm(e.phone), distDate, e.name || '', toSqlUtc(e.active_from) || defaultFrom));
    }
    await env.DB.batch(stmts);
    return Response.json({ ok: true, count: rows.length, dist_date: distDate });
  }

  // /answers
  const dd = url.searchParams.get('dist_date');
  const q = dd
    ? env.DB.prepare('SELECT phone,answer,at,dist_date FROM answers WHERE dist_date=?').bind(dd)
    : env.DB.prepare('SELECT phone,answer,at,dist_date FROM answers');
  const { results } = await q.all();
  return Response.json({ answers: results });
}

// ── הקו של ימות ──
async function lineCall(request, env) {
  const params = await readYemotParams(request);
  if (isHangup(params)) return reply('ok');

  const phone = norm(params.get('ApiPhone'));
  const digits = params.get('Digits');
  if (!phone) return reply(TO_MENU);            // מספר חסוי — אין מה לשאול

  // הרשימות הפעילות של המתקשר, החדשה קודם; מדלגים על מה שכבר ענה לו.
  const { results: rows } = await env.DB.prepare(
    `SELECT dist_date FROM week_lists
      WHERE phone=? AND (active_from IS NULL OR active_from<=datetime('now'))
      ORDER BY dist_date DESC`).bind(phone).all();
  // מספר בדיקה (סוד TEST_PHONE ב"סודות (env)") נחשב זכאי גם בלי שורה ברשימה,
  // ונשאל בכל שיחה (בלי "פעם אחת") — לבדיקות בלבד; בלי הסוד הקוד הזה רדום.
  const isTest = !!env.TEST_PHONE && phone === norm(env.TEST_PHONE);
  let distDate = null, meta = { mode: 'both', recording: 0 };
  if (isTest) {
    distDate = 'test';
  } else {
    for (const r of rows || []) {
      const m = await env.DB.prepare('SELECT mode,recording FROM list_meta WHERE dist_date=?')
        .bind(r.dist_date).first() || { mode: 'both', recording: 0 };
      // מצב "הקלטה בלבד": מי שכבר שמע — הלאה; אחרת משמיעים פעם אחת וממשיכים לתפריט
      const doneTable = m.mode === 'message' ? 'heard' : 'answers';
      const done = await env.DB.prepare(`SELECT 1 FROM ${doneTable} WHERE phone=? AND dist_date=?`)
        .bind(phone, r.dist_date).first();
      if (!done) { distDate = r.dist_date; meta = m; break; }
    }
  }
  if (distDate === null) return reply(TO_MENU);   // לא זכאי / כבר ענה/שמע — בשקט לתפריט

  if (meta.mode === 'message') {
    await env.DB.prepare('INSERT OR REPLACE INTO heard (phone,dist_date,at) VALUES (?,?,datetime(\'now\'))')
      .bind(phone, distDate).run();
    // בלי הקלטה בשלוחה אין מה להשמיע — בשקט לתפריט (לא מנסים f-msg שלא קיים)
    return reply(meta.recording ? 'id_list_message=' + REC + '&' + TO_MENU : TO_MENU);
  }

  const first = meta.recording ? QUESTION_REC : QUESTION;
  if (digits === null || digits === undefined || digits === '') return reply(first);
  const d = String(digits);
  if (!['1', '2', '3'].includes(d)) return reply(ASK_AGAIN);   // הקשה לא מוכרת — שואלים שוב (בלי ההקלטה)

  await env.DB.prepare(
    `INSERT INTO answers (phone,dist_date,answer,at) VALUES (?,?,?,datetime('now'))
     ON CONFLICT(phone,dist_date) DO UPDATE SET answer=excluded.answer, at=excluded.at`)
    .bind(phone, distDate, d).run();

  const msg = d === '1' ? 'תודה, רשמנו שתגיע'
            : d === '2' ? 'רשמנו שלא תגיע, תודה'
            : 'רשמנו את תשובתך, תודה';
  return reply('id_list_message=t-' + msg + '&' + TO_MENU);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/push' || url.pathname === '/answers') {
      await ensureTables(env);
      return appApi(request, env, url);
    }
    try {
      await ensureTables(env);
      return await lineCall(request, env);
    } catch (e) {
      // כל תקלה = המתקשר ממשיך לתפריט כרגיל (לא "אין מענה" של ימות)
      return reply(TO_MENU);
    }
  },
};
