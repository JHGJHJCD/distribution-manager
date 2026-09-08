// stub של העזר שהתבנית של פתרונאי מספקת ל-Worker (readYemotParams/isHangup/reply) — לבדיקות מקומיות בלבד
export async function readYemotParams(request) {
  const u = new URL(request.url);
  if (request.method === 'POST') return new URLSearchParams(await request.text());
  return u.searchParams;
}
export const isHangup = (p) => p.get('hangup') === 'yes';
export const reply = (t) => new Response(t, { headers: { 'content-type': 'text/plain' } });
