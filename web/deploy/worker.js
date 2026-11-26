// The fixed front address of the site, on Cloudflare Workers (free, *.workers.dev).
//
// The server reaches the internet through a "quick" cloudflared tunnel whose address changes
// every time it starts. This Worker has an address that never changes; it remembers where the
// tunnel is now and passes every request on to it, adding a secret that the site insists on —
// so the tunnel's own address is of no use to anyone who finds it.
//
// Needs (Worker settings):  a KV namespace bound as  HALUKA_KV,
//                           a secret  HALUKA_PROXY_SECRET   (the same text as in web.env),
//                           a secret  HALUKA_REGISTER_KEY   (only the server knows it).
// The server tells the Worker where the tunnel is (deploy/haluka-tunnel.sh):
//     POST /__tunnel   header  X-Register-Key: <HALUKA_REGISTER_KEY>   body: https://xxxx.trycloudflare.com
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/__tunnel") {
      if (request.method !== "POST" || request.headers.get("X-Register-Key") !== env.HALUKA_REGISTER_KEY) {
        return new Response("not found", { status: 404 });
      }
      const target = (await request.text()).trim();
      if (!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(target)) {
        return new Response("not a tunnel address", { status: 400 });
      }
      await env.HALUKA_KV.put("tunnel", target);
      return new Response("ok");
    }

    const target = await env.HALUKA_KV.get("tunnel");
    if (!target) {
      return new Response("האתר עוד לא מחובר. אפשר לנסות שוב בעוד רגע.", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    const headers = new Headers(request.headers);
    headers.set("X-Haluka-Proxy", env.HALUKA_PROXY_SECRET);
    try {
      // redirect: "manual" — the browser, not the Worker, follows the site's redirects (the login depends on it)
      return await fetch(target + url.pathname + url.search, {
        method: request.method, headers, redirect: "manual",
        body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      });
    } catch (e) {
      return new Response("האתר לא זמין כרגע. אפשר לנסות שוב בעוד רגע.", { status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
  },
};
