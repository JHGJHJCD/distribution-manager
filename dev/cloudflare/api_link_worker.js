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
//   • POST /push   (מוגן בסוד) → התוכנה דוחפת את רשימת הזכאים של השבוע
//                    body: {dist_date:"YYYY-MM-DD", phones:[{phone,name}]}
//   • GET  /answers (מוגן בסוד) → התוכנה קוראת מי אישר (?dist_date=... אופציונלי)
//
// חיווט בקו (הכרעת המשתמש 9/9/2026 — אותו קו, בלי DID ייעודי):
//   • שלוחה /76: type=api + api_link=<הכתובת>  (התוכנה בודקת/מתקנת אותה, v3.34)
//   • Did_Go_To.ini בשורש: 048691834=/76  ⇒ כל מי שמחייג ל-04 עובר קודם דרך השרת
//   • השורש: check_did_and_go_to_folder_one_time=yes ⇒ החזרה ל-/ לא נכנסת שוב ל-76
//
// כלל ההתנהגות (9/9/2026): כל מתקשר ל-04 מגיע לכאן. מי שלא ברשימת השבוע, או שכבר
// ענה השבוע — ממשיך **בשקט** לתפריט הראשי (go_to_folder=/), בלי שום הודעה.
// רק זכאי שטרם ענה שומע את השאלה "מגיע? 1 / 2 / 3", פעם אחת.
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
const QUESTION = 'read=t-שלום, יש לך חלוקה השבוע, אם תגיע הקישו 1, אם לא תגיע הקישו 2, אם אינך יודע הקישו 3=Digits,,1,1,7,No,yes,no';

async function ensureTables(env) {
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS week_list (
      phone TEXT PRIMARY KEY, name TEXT, dist_date TEXT)`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS answers (
      phone TEXT, dist_date TEXT, answer TEXT,
      at TEXT DEFAULT (datetime('now')),
      PRIMARY KEY (phone, dist_date))`),
  ]);
}

// ── דלתות התוכנה (מוגנות בסוד) ──
async function appApi(request, env, url) {
  if (url.searchParams.get('secret') !== env.APP_SECRET)
    return new Response('forbidden', { status: 403 });

  if (url.pathname === '/push') {
    const body = await request.json(); // {dist_date, phones:[{phone,name}]}
    await env.DB.prepare('DELETE FROM week_list').run();
    const rows = (body.phones || []).filter(e => norm(e.phone));
    if (rows.length) {
      await env.DB.batch(rows.map(e =>
        env.DB.prepare('INSERT OR REPLACE INTO week_list (phone,name,dist_date) VALUES (?,?,?)')
          .bind(norm(e.phone), e.name || '', body.dist_date || '')));
    }
    return Response.json({ ok: true, count: rows.length });
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

  const row = await env.DB.prepare('SELECT name,dist_date FROM week_list WHERE phone=?')
    .bind(phone).first();
  // מספר בדיקה (סוד TEST_PHONE ב"סודות (env)") נחשב זכאי גם בלי שורה ברשימה,
  // ונשאל בכל שיחה (בלי "פעם אחת") — לבדיקות בלבד; בלי הסוד הקוד הזה רדום.
  const isTest = !!env.TEST_PHONE && phone === norm(env.TEST_PHONE);
  if (!row && !isTest) return reply(TO_MENU);   // לא זכאי השבוע — בשקט לתפריט
  const distDate = row ? row.dist_date : 'test';

  if (!isTest) {
    const done = await env.DB.prepare('SELECT 1 FROM answers WHERE phone=? AND dist_date=?')
      .bind(phone, distDate).first();
    if (done) return reply(TO_MENU);            // כבר ענה השבוע — פעם אחת בלבד
  }

  if (digits === null || digits === undefined || digits === '') return reply(QUESTION);
  const d = String(digits);
  if (!['1', '2', '3'].includes(d)) return reply(QUESTION);   // הקשה לא מוכרת — שואלים שוב

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
