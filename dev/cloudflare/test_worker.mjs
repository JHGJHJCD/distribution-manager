// בדיקת ה-Worker בלי ענן: node dev/cloudflare/test_worker.mjs  (D1 מדומה בזיכרון; yemot.mjs = stub של התבנית של פתרונאי)
import worker from './api_link_worker.js';
// ── D1 מדומה: week_list + answers בזיכרון ──
function makeDB() {
  const week = new Map(), answers = new Map();
  const stmt = (sql) => {
    let args = [];
    const s = { bind(...a) { args = a; return s; },
      async first() {
        if (sql.includes('FROM week_list')) { const r = week.get(args[0]); return r ? { name: r.name, dist_date: r.dist_date } : null; }
        if (sql.includes('FROM answers')) return answers.has(args[0] + '|' + args[1]) ? { 1: 1 } : null;
        throw new Error('first? ' + sql);
      },
      async run() {
        if (sql.startsWith('CREATE')) return;
        if (sql.includes('DELETE FROM week_list')) { week.clear(); return; }
        if (sql.includes('INTO week_list')) { week.set(args[0], { name: args[1], dist_date: args[2] }); return; }
        if (sql.includes('INTO answers')) { answers.set(args[0] + '|' + args[1], { phone: args[0], dist_date: args[1], answer: args[2], at: 'now' }); return; }
        if (sql.includes('CRASH')) throw new Error('boom');
        throw new Error('run? ' + sql);
      },
      async all() { return { results: [...answers.values()].filter(r => !args.length || r.dist_date === args[0]) }; },
    };
    return s;
  };
  return { prepare: stmt, batch: async (l) => { for (const x of l) await x.run(); }, _week: week, _answers: answers };
}
const env = { DB: makeDB(), APP_SECRET: 's3cret' };
const call = async (q, opts) => (await worker.fetch(new Request('https://w.test/' + (q || ''), opts), env));
const text = async (q, opts) => (await call(q, opts)).text();
let fails = 0;
const ok = (name, c) => { console.log((c ? 'PASS ' : 'FAIL ') + name); if (!c) fails++; };

// 1. רשימה ריקה: כל מתקשר → בשקט לתפריט, בלי הודעה
let t = await text('?ApiPhone=0501111111&ApiCallId=1');
ok('רשימה ריקה = go_to_folder=/ בשקט', t === 'go_to_folder=/');
ok('מספר חסוי = בשקט', (await text('?ApiCallId=1')) === 'go_to_folder=/');
// 2. push
const r = await call('push?secret=s3cret', { method: 'POST', body: JSON.stringify({ dist_date: '2026-09-16', phones: [{ phone: '050-111-1111', name: 'א' }, { phone: '+972521234567', name: 'ב' }] }) });
ok('push מחזיר count=2', (await r.json()).count === 2);
ok('push בסוד שגוי = 403', (await call('push?secret=x', { method: 'POST', body: '{}' })).status === 403);
// 3. זכאי → שאלה; הקשה לא מוכרת → שואלים שוב; 1 → תודה + לתפריט
t = await text('?ApiPhone=972501111111');
ok('זכאי (972) שומע את השאלה', t.startsWith('read=t-') && t.includes('=Digits,'));
t = await text('?ApiPhone=0501111111&Digits=9');
ok('הקשה 9 = שואלים שוב', t.startsWith('read=t-'));
t = await text('?ApiPhone=0501111111&Digits=1');
ok('הקשה 1 = תודה ולתפריט', t.includes('רשמנו שתגיע') && t.endsWith('&go_to_folder=/'));
// 4. פעם אחת: חזרה שנייה → בשקט
t = await text('?ApiPhone=0501111111');
ok('כבר ענה = בשקט לתפריט', t === 'go_to_folder=/');
// 5. answers
const a = await (await call('answers?secret=s3cret&dist_date=2026-09-16')).json();
ok('answers מחזיר את התשובה', a.answers.length === 1 && a.answers[0].phone === '0501111111' && a.answers[0].answer === '1');
// 6. POST מהקו (api_url_post) + ניתוק
t = await text('', { method: 'POST', body: 'ApiPhone=0521234567&Digits=2' });
ok('POST + הקשה 2', t.includes('רשמנו שלא תגיע'));
ok('ניתוק = ok', (await text('?ApiPhone=0521234567&hangup=yes')) === 'ok');
// 7. TEST_PHONE: זכאי תמיד, גם אחרי תשובה
env.TEST_PHONE = '0556752642';
ok('מספר בדיקה שומע שאלה', (await text('?ApiPhone=0556752642')).startsWith('read='));
await text('?ApiPhone=0556752642&Digits=3');
ok('מספר בדיקה נשאל שוב גם אחרי תשובה', (await text('?ApiPhone=0556752642')).startsWith('read='));
// 8. תקלה במסד = בשקט לתפריט (לא "אין מענה")
env.DB.prepare = () => { throw new Error('D1 down'); };
ok('תקלת שרת = go_to_folder=/', (await text('?ApiPhone=0501111111')) === 'go_to_folder=/');
console.log(fails ? `\n${fails} FAILED` : '\nALL PASS');
process.exit(fails ? 1 : 0);
