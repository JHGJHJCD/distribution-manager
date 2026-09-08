// בדיקת ה-Worker בלי ענן: node dev/cloudflare/test_worker.mjs  (D1 מדומה בזיכרון; yemot.mjs = stub של התבנית של פתרונאי)
import worker from './api_link_worker.js';

// ── D1 מדומה (v3.36): week_lists (phone+dist_date, active_from) + answers ──
// מבין רק את המשפטים שה-Worker כותב; משפט לא מוכר = חריגה (כדי לתפוס SQL חדש בלי בדיקה).
const NOW = () => new Date().toISOString().slice(0, 19).replace('T', ' ');
function makeDB() {
  const lists = new Map();    // 'phone|dist_date' → {phone, dist_date, name, active_from}
  const answers = new Map();  // 'phone|dist_date' → {phone, dist_date, answer, at}
  const stmt = (sql) => {
    let args = [];
    const s = {
      bind(...a) { args = a; return s; },
      async first() {
        if (sql.includes('FROM answers')) return answers.has(args[0] + '|' + args[1]) ? { 1: 1 } : null;
        throw new Error('first? ' + sql);
      },
      async run() {
        if (sql.startsWith('CREATE') || sql.startsWith('DROP')) return;
        if (sql.includes('DELETE FROM week_lists WHERE dist_date=?')) {
          for (const [k, r] of lists) if (r.dist_date === args[0]) lists.delete(k);
          return;
        }
        if (sql.includes("dist_date<date('now'")) {
          const days = parseInt(args[0], 10);            // '-45 days'
          const cut = new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);
          for (const [k, r] of lists) if (r.dist_date && r.dist_date < cut) lists.delete(k);
          return;
        }
        if (sql.includes('INTO week_lists')) { lists.set(args[0] + '|' + args[1], { phone: args[0], dist_date: args[1], name: args[2], active_from: args[3] }); return; }
        if (sql.includes('INTO answers')) { answers.set(args[0] + '|' + args[1], { phone: args[0], dist_date: args[1], answer: args[2], at: NOW() }); return; }
        if (sql.includes('CRASH')) throw new Error('boom');
        throw new Error('run? ' + sql);
      },
      async all() {
        if (sql.includes('FROM week_lists')) {
          const now = NOW();
          return { results: [...lists.values()]
            .filter(r => r.phone === args[0] && (r.active_from === null || r.active_from <= now))
            .sort((a, b) => (a.dist_date < b.dist_date ? 1 : -1)) };
        }
        if (sql.includes('FROM answers')) return { results: [...answers.values()].filter(r => !args.length || r.dist_date === args[0]) };
        throw new Error('all? ' + sql);
      },
    };
    return s;
  };
  return { prepare: stmt, batch: async (l) => { for (const x of l) await x.run(); }, _lists: lists, _answers: answers };
}
const env = { DB: makeDB(), APP_SECRET: 's3cret' };
const call = async (q, opts) => (await worker.fetch(new Request('https://w.test/' + (q || ''), opts), env));
const text = async (q, opts) => (await call(q, opts)).text();
const push = (body) => call('push?secret=s3cret', { method: 'POST', body: JSON.stringify(body) });
let fails = 0;
const ok = (name, c) => { console.log((c ? 'PASS ' : 'FAIL ') + name); if (!c) fails++; };
const isQ = (t) => t.startsWith('read=t-') && t.includes('=Digits,');

// 1. רשימה ריקה: כל מתקשר → בשקט לתפריט, בלי הודעה
let t = await text('?ApiPhone=0501111111&ApiCallId=1');
ok('רשימה ריקה = go_to_folder=/ בשקט', t === 'go_to_folder=/');
ok('מספר חסוי = בשקט', (await text('?ApiCallId=1')) === 'go_to_folder=/');
// 2. push
let r = await push({ dist_date: '2026-09-16', phones: [{ phone: '050-111-1111', name: 'א' }, { phone: '+972521234567', name: 'ב' }] });
ok('push מחזיר count=2', (await r.json()).count === 2);
ok('push בסוד שגוי = 403', (await call('push?secret=x', { method: 'POST', body: '{}' })).status === 403);
// 3. זכאי → שאלה; הקשה לא מוכרת → שואלים שוב; 1 → תודה + לתפריט
t = await text('?ApiPhone=972501111111');
ok('זכאי (972) שומע את השאלה', isQ(t));
t = await text('?ApiPhone=0501111111&Digits=9');
ok('הקשה 9 = שואלים שוב', isQ(t));
t = await text('?ApiPhone=0501111111&Digits=1');
ok('הקשה 1 = תודה ולתפריט', t.includes('רשמנו שתגיע') && t.endsWith('&go_to_folder=/'));
// 4. פעם אחת: חזרה שנייה → בשקט
t = await text('?ApiPhone=0501111111');
ok('כבר ענה = בשקט לתפריט', t === 'go_to_folder=/');
// 5. answers
let a = await (await call('answers?secret=s3cret&dist_date=2026-09-16')).json();
ok('answers מחזיר את התשובה', a.answers.length === 1 && a.answers[0].phone === '0501111111' && a.answers[0].answer === '1');
// 6. POST מהקו (api_url_post) + ניתוק
t = await text('', { method: 'POST', body: 'ApiPhone=0521234567&Digits=2' });
ok('POST + הקשה 2', t.includes('רשמנו שלא תגיע'));
ok('ניתוק = ok', (await text('?ApiPhone=0521234567&hangup=yes')) === 'ok');

// ── v3.36: רשימה לכל חלוקה + active_from ──
// 7. push של חלוקה אחרת לא מוחק את הרשימה של השבוע
await push({ dist_date: '2026-09-23', phones: [{ phone: '0531111111', name: 'ג' }] });
ok('push של תאריך אחר שומר את רשימת 09-16', env.DB._lists.has('0501111111|2026-09-16') && env.DB._lists.has('0531111111|2026-09-23'));
// 8. push חוזר לאותו תאריך מחליף רק אותו
await push({ dist_date: '2026-09-16', phones: [{ phone: '0541111111', name: 'ד' }] });
ok('push חוזר מחליף רק את רשימת 09-16', !env.DB._lists.has('0501111111|2026-09-16') && env.DB._lists.has('0541111111|2026-09-16') && env.DB._lists.has('0531111111|2026-09-23'));
// 9. רשימה ריקה = מחיקה של התאריך (ביטול תזמון)
await push({ dist_date: '2026-09-23', phones: [] });
ok('push ריק מוחק את רשימת התאריך', !env.DB._lists.has('0531111111|2026-09-23'));
ok('מי שנמחק = בשקט', (await text('?ApiPhone=0531111111')) === 'go_to_folder=/');
// 10. active_from עתידי = עוד לא נשאל (תזמון להמשך היום); עבר = נשאל
const future = new Date(Date.now() + 3600e3).toISOString();
const past = new Date(Date.now() - 3600e3).toISOString();
await push({ dist_date: '2026-09-30', active_from: future, phones: [{ phone: '0551111111', name: 'ה' }, { phone: '0561111111', name: 'ו', active_from: past }] });
ok('active_from עתידי (כללי) = בשקט', (await text('?ApiPhone=0551111111')) === 'go_to_folder=/');
ok('active_from אישי שעבר גובר על הכללי = נשאל', isQ(await text('?ApiPhone=0561111111')));
ok('active_from נשמר כ-UTC בפורמט SQLite', /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(env.DB._lists.get('0551111111|2026-09-30').active_from));
ok('בלי active_from = null (פעיל מיד)', env.DB._lists.get('0541111111|2026-09-16').active_from === null);
// 11. שתי חלוקות פעילות: נשאל על החדשה שטרם ענה לה, ואחריה על הישנה
await push({ dist_date: '2026-10-07', phones: [{ phone: '0571111111', name: 'ז' }] });
await push({ dist_date: '2026-10-01', phones: [{ phone: '0571111111', name: 'ז' }] });
ok('שתי חלוקות = נשאל', isQ(await text('?ApiPhone=0571111111')));
await text('?ApiPhone=0571111111&Digits=1');
a = await (await call('answers?secret=s3cret&dist_date=2026-10-07')).json();
ok('התשובה נרשמת על החלוקה החדשה ביותר', a.answers.length === 1 && a.answers[0].phone === '0571111111');
ok('אחרי שענה על החדשה — נשאל על הישנה', isQ(await text('?ApiPhone=0571111111')));
await text('?ApiPhone=0571111111&Digits=2');
ok('ענה על שתיהן = בשקט', (await text('?ApiPhone=0571111111')) === 'go_to_folder=/');
// 12. רשימות ישנות מתנקות בדחיפה הבאה
env.DB._lists.set('0581111111|2020-01-01', { phone: '0581111111', dist_date: '2020-01-01', name: 'ישן', active_from: null });
await push({ dist_date: '2026-10-14', phones: [] });
ok('רשימה מלפני 45+ יום נמחקת', !env.DB._lists.has('0581111111|2020-01-01'));
// 13. TEST_PHONE: זכאי תמיד, גם אחרי תשובה
env.TEST_PHONE = '0556752642';
ok('מספר בדיקה שומע שאלה', isQ(await text('?ApiPhone=0556752642')));
await text('?ApiPhone=0556752642&Digits=3');
ok('מספר בדיקה נשאל שוב גם אחרי תשובה', isQ(await text('?ApiPhone=0556752642')));
delete env.TEST_PHONE;
// 14. תקלה במסד = בשקט לתפריט (לא "אין מענה")
env.DB.prepare = () => { throw new Error('D1 down'); };
ok('תקלת שרת = go_to_folder=/', (await text('?ApiPhone=0541111111')) === 'go_to_folder=/');
console.log(fails ? `\n${fails} FAILED` : '\nALL PASS');
process.exit(fails ? 1 : 0);
