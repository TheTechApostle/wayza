/* WAYZA service worker: app-shell caching. API, uploads and WebSockets are never cached. */
const V="wayza-v2",SHELL=["/","/static/style.css","/static/standards.css","/static/app.js","/static/ui.js","/static/manifest.webmanifest","/static/icon.svg"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(V).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()))});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==V).map(x=>caches.delete(x)))).then(()=>self.clients.claim()))});
self.addEventListener("fetch",e=>{
  const r=e.request,u=new URL(r.url);
  if(r.method!=="GET"||u.origin!==location.origin||u.pathname.startsWith("/api")||u.pathname.startsWith("/uploads")||u.pathname==="/ws"||u.pathname.startsWith("/admin"))return;
  if(r.mode==="navigate"){e.respondWith(fetch(r).catch(()=>caches.match("/")));return}
  e.respondWith(caches.match(r).then(hit=>{const net=fetch(r).then(res=>{if(res.ok)caches.open(V).then(c=>c.put(r,res.clone()));return res}).catch(()=>hit);return hit||net}));
});
