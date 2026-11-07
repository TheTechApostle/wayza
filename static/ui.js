"use strict";
/* WAYZA UI layer: service worker, install prompt, offline banner, ripple feedback. */
(function(){
  if("serviceWorker"in navigator&&(location.protocol==="https:"||location.hostname==="localhost"||location.hostname==="127.0.0.1")){
    window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}));
  }
  const bar=document.getElementById("offlineBar"),sync=()=>{if(bar)bar.hidden=navigator.onLine};
  addEventListener("online",sync);addEventListener("offline",sync);sync();
  let deferred=null;const btn=document.getElementById("installBtn");
  addEventListener("beforeinstallprompt",e=>{e.preventDefault();deferred=e;if(btn)btn.hidden=false});
  if(btn)btn.onclick=async()=>{if(!deferred)return;deferred.prompt();await deferred.userChoice.catch(()=>{});deferred=null;btn.hidden=true};
  addEventListener("appinstalled",()=>{if(btn)btn.hidden=true});
  document.addEventListener("pointerdown",e=>{
    if(matchMedia("(prefers-reduced-motion:reduce)").matches)return;
    const t=e.target.closest(".btn,.side-link,.mobile-nav a,.icon-btn,.account-btn");if(!t||t.disabled)return;
    const r=t.getBoundingClientRect(),d=Math.max(r.width,r.height),s=document.createElement("span");
    s.className="ripple";s.style.cssText=`width:${d}px;height:${d}px;left:${e.clientX-r.left-d/2}px;top:${e.clientY-r.top-d/2}px`;
    t.appendChild(s);setTimeout(()=>s.remove(),600);
  },{passive:true});
})();
