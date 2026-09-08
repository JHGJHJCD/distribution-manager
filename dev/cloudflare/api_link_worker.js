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
// חיווט בקו (בסוף, דרך הכלי הבטוח של פתרונאי — לא בשורש!):
//   שלוחה  type=api  +  api_link=https://pai-dev-s-api-link.pai-ffff542b.workers.dev
//
// ⚠ טרם אומת חי מול הקו: ש-ApiPhone מגיע, שפורמט read/‏id_list_message מתקבל.

import { isHangup, readYemotParams, reply } from './yemot.mjs';

// נרמול מספר אחיד לשני הצדדים (ספרות בלבד, 972 → 0)
const norm = (p) => {
  let d = (p || '').replace(/\D/g, '');
  if (d.startsWith('972')) d = '0' + d.slice(3);
  return d;
};

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

export default {
  async fetch(request, env) {
    await ensureTables(env);
    const url = new URL(request.url);

    // ── דלתות התוכנה (מוגנות בסוד) ──
    if (url.pathname === '/push' || url.pathname === '/answers') {
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
    const params = await readYemotParams(request);
    if (isHangup(params)) return reply('ok');

    const phone = norm(params.get('ApiPhone'));
    const digits = params.get('Digits');

    const row = await env.DB.prepare('SELECT name,dist_date FROM week_list WHERE phone=?')
      .bind(phone).first();
    // מספר בדיקה (סוד TEST_PHONE ב"סודות (env)") נחשב זכאי גם בלי שורה ברשימה —
    // לבדיקות בלבד; למחוק את הסוד כשהתוכנה דוחפת רשימות אמיתיות.
    const isTest = !!env.TEST_PHONE && phone === norm(env.TEST_PHONE);

    if (!row && !isTest)
      return reply('id_list_message=t-שלום, לא רשומה עבורך חלוקה השבוע, תודה ולהתראות&go_to_folder=/');
    const distDate = row ? row.dist_date : 'test';

    if (digits === null)
      return reply('read=t-שלום, יש לך חלוקה השבוע, אם תגיע הקישו 1, אם לא תגיע הקישו 2, אם אינך יודע הקישו 3=Digits,,1,1,7,No,yes,no');

    await env.DB.prepare(
      `INSERT INTO answers (phone,dist_date,answer,at) VALUES (?,?,?,datetime('now'))
       ON CONFLICT(phone,dist_date) DO UPDATE SET answer=excluded.answer, at=excluded.at`)
      .bind(phone, distDate, String(digits)).run();

    const msg = digits === '1' ? 'תודה, רשמנו שתגיע'
              : digits === '2' ? 'רשמנו שלא תגיע, תודה'
              : 'רשמנו את תשובתך, תודה';
    return reply('id_list_message=t-' + msg + '&go_to_folder=/');
  },
};
