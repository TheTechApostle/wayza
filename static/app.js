"use strict";
const $=s=>document.querySelector(s), esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const R=Math.PI/180, ngn=n=>"₦"+Number(n).toLocaleString();
const dist=(a,b,c,d)=>{const x=(d-b)*R*Math.cos((a+c)/2*R),y=(c-a)*R;return Math.hypot(x,y)*6371000};
const fm=m=>m<1000?Math.round(m/10)*10+" m":(m/1000).toFixed(1)+" km";
let T=localStorage.getItem("tk"),U=null,STOPS=[],ROUTES=[],trip=null,me=null,wid=null,sim=null,vOn=true,lastKey="",lastT=0,ws=null,chatWith=null,nearMe=null;

async function api(p,o={}){
  if(!navigator.onLine)throw new Error("You're offline. Check your connection and try again.");
  const ctl=new AbortController(),tm=setTimeout(()=>ctl.abort(),o.timeout||20000);
  let r;
  try{r=await fetch("/api"+p,{method:o.method||"GET",signal:ctl.signal,headers:{...(o.body?{"Content-Type":"application/json"}:{}),...(T?{Authorization:"Bearer "+T}:{})},body:o.body?JSON.stringify(o.body):undefined})}
  catch(e){throw new Error(e.name==="AbortError"?"That took too long. Please try again.":"Can't reach the server. Please try again.")}
  finally{clearTimeout(tm)}
  if(r.status===204)return null;
  const j=await r.json().catch(()=>({}));
  if(!r.ok){
    if(r.status===401&&T&&!p.startsWith("/auth"))logout(false);
    const d=j.detail,msg=typeof d==="string"?d:(d&&d[0]&&d[0].msg);
    throw new Error(msg||(r.status===429?"Too many attempts. Please wait a moment.":r.status>=500?"Something went wrong on our side. Please try again.":"Something went wrong"));
  }
  return j;
}
function toast(msg,bad){const d=document.createElement("div");d.className="toast align-items-center border-0 text-bg-"+(bad?"danger":"success");d.setAttribute("role",bad?"alert":"status");d.setAttribute("aria-live",bad?"assertive":"polite");d.innerHTML=`<div class="d-flex"><div class="toast-body">${esc(msg)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Dismiss"></button></div>`;$("#toasts").append(d);const t=new bootstrap.Toast(d,{delay:bad?6000:4000});t.show();d.addEventListener("hidden.bs.toast",()=>d.remove())}
const guard=fn=>async(...a)=>{try{return await fn(...a)}catch(e){toast(e.message,true)}};
window.G=guard;

// ---------- navigation / theme ----------
const PAGES={ride:"Find a ride",routes:"Bus routes",market:"Local marketplace",msgs:"Messages",account:"Account"};
let curPg=null;
function show(pg){
  if(!PAGES[pg])pg="ride";
  const first=curPg===null,changed=pg!==curPg;curPg=pg;
  document.querySelectorAll(".pg").forEach(s=>s.classList.toggle("d-none",s.id!=="pg-"+pg));
  document.querySelectorAll("[data-pg]").forEach(a=>{const on=a.dataset.pg===pg;a.classList.toggle("active",on);on?a.setAttribute("aria-current","page"):a.removeAttribute("aria-current")});
  $("#mapWrap").classList.toggle("d-none",!["ride","routes"].includes(pg));setTimeout(()=>map.invalidateSize(),50);
  document.title=PAGES[pg]+" · WAYZA";
  if(pg==="market")loadMarket();if(pg==="msgs")loadThreads();if(pg==="account")renderAccount();
  if(changed&&!first){window.scrollTo({top:0});const m=$("#main");if(m)m.focus({preventScroll:true});const sr=$("#sr");if(sr)sr.textContent=PAGES[pg]+" page"}
}
function go(pg){if(!PAGES[pg])pg="ride";if(location.hash.slice(1)===pg)show(pg);else location.hash=pg}
window.addEventListener("hashchange",()=>show(location.hash.slice(1)));
window.go=go;
document.querySelectorAll("[data-pg]").forEach(a=>a.onclick=e=>{e.preventDefault();go(a.dataset.pg)});
function applyTheme(t){document.documentElement.setAttribute("data-bs-theme",t);$("#themeBtn").setAttribute("aria-pressed",t==="dark");const m=document.querySelector('meta[name=theme-color]');if(m)m.content=t==="dark"?"#101a14":"#0c5138"}
$("#themeBtn").onclick=()=>{const d=document.documentElement.getAttribute("data-bs-theme")==="dark",t=d?"light":"dark";applyTheme(t);try{localStorage.setItem("theme",t)}catch(e){}};
applyTheme(localStorage.getItem("theme")||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light"));

// ---------- map ----------
const map=L.map("map").setView([6.53,3.37],11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"© OpenStreetMap contributors"}).addTo(map);
const stopsL=L.layerGroup().addTo(map),routeL=L.layerGroup().addTo(map);let meM=null;
function drawStops(){stopsL.clearLayers();STOPS.forEach(s=>L.circleMarker([s.lat,s.lon],{radius:4,color:"#0a8f4f",weight:1,fillOpacity:.6}).bindPopup(`<b>${esc(s.name)}</b><br>${esc(s.zone)}<br><a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}&travelmode=transit">Directions</a>`).addTo(stopsL))}
function showRoute(r){routeL.clearLayers();const pts=r.stops.map(s=>[s.lat,s.lon]);L.polyline(pts,{color:"#0a8f4f",weight:5,opacity:.8}).addTo(routeL);
  r.stops.forEach((s,i)=>L.marker([s.lat,s.lon],{icon:L.divIcon({className:"",html:`<div style="background:#0a8f4f;color:#fff;border-radius:50%;width:20px;height:20px;text-align:center;font:11px/20px sans-serif">${i+1}</div>`,iconSize:[20,20]})}).bindTooltip(s.name).addTo(routeL));
  map.fitBounds(pts,{padding:[30,30]})}

// ---------- free browser voice guide ----------
const HAS="speechSynthesis" in window;
let availableVoices=[];
let selectedVoice=null;
const voicePreferenceKey="wayza_voice_preference";
function getVoicePreference(){
  try{return localStorage.getItem(voicePreferenceKey)||"female-ng"}catch(e){return "female-ng"}
}
function femaleName(v){
  return /female|woman|zira|susan|victoria|samantha|karen|moira|tessa|hazel|aria|jenny|sonia|libby|natasha/i.test(v.name||"");
}
function chooseVoice(){
  if(!HAS)return;
  availableVoices=speechSynthesis.getVoices()||[];
  const pref=getVoicePreference();
  const ng=availableVoices.filter(v=>/en-ng|nigeria|nigerian/i.test((v.lang||"")+" "+(v.name||"")));
  const english=availableVoices.filter(v=>/^en(-|_)/i.test(v.lang||""));
  const femaleEnglish=english.filter(femaleName);
  if(pref==="female-ng"){
    selectedVoice=ng.find(femaleName)||ng[0]||femaleEnglish.find(v=>/en-gb/i.test(v.lang))||femaleEnglish[0]||english.find(v=>/en-gb/i.test(v.lang))||english[0]||availableVoices[0]||null;
  }else if(pref==="female"){
    selectedVoice=femaleEnglish.find(v=>/en-gb/i.test(v.lang))||femaleEnglish[0]||english.find(v=>/en-gb/i.test(v.lang))||english[0]||availableVoices[0]||null;
  }else if(pref==="nigeria"){
    selectedVoice=ng[0]||english.find(v=>/en-gb/i.test(v.lang))||english[0]||availableVoices[0]||null;
  }else if(pref==="british"){
    selectedVoice=availableVoices.find(v=>/en-gb/i.test(v.lang)&&femaleName(v))||availableVoices.find(v=>/en-gb/i.test(v.lang))||english[0]||null;
  }else if(pref==="american"){
    selectedVoice=availableVoices.find(v=>/en-us/i.test(v.lang)&&femaleName(v))||availableVoices.find(v=>/en-us/i.test(v.lang))||english[0]||null;
  }else{
    selectedVoice=availableVoices.find(v=>v.default)||availableVoices[0]||null;
  }
  const status=$("#voiceStatus");
  if(status){
    status.textContent=selectedVoice
      ? "Using "+selectedVoice.name+" ("+selectedVoice.lang+"). Voice options depend on your device."
      : "No browser voice is available on this device.";
  }
}
if(HAS){
  chooseVoice();
  speechSynthesis.onvoiceschanged=chooseVoice;
}
const voiceSelect=$("#voiceSelect");
if(voiceSelect){
  voiceSelect.value=getVoicePreference();
  voiceSelect.onchange=()=>{
    try{localStorage.setItem(voicePreferenceKey,voiceSelect.value)}catch(e){}
    chooseVoice();
    if(vOn)say("Your voice guide is ready.");
  };
}
function say(t,force){
  if(!HAS||(!vOn&&!force))return;
  try{
    speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(t);
    if(selectedVoice)u.voice=selectedVoice;
    u.lang=selectedVoice?.lang||"en-GB";
    u.rate=.91;
    u.pitch=getVoicePreference()==="female-ng"||getVoicePreference()==="female"?1.08:1;
    u.volume=1;
    speechSynthesis.speak(u);
  }catch(e){}
}
$("#vt").onclick=()=>{if(!HAS){$("#vt").textContent="Voice unavailable";return}vOn=!vOn;$("#vt").textContent="Voice: "+(vOn?"On":"Off");if(!vOn)speechSynthesis.cancel();else say("Voice guide on.")};
let info=null;
$("#sayNow").onclick=()=>say(info?info.say:"I don’t have your location yet. Tap Start tracking first.",true);
function announce(key,text,buzz){const t=Date.now();if(key===lastKey||t-lastT<4000)return;lastKey=key;lastT=t;say(text);if(buzz&&navigator.vibrate)navigator.vibrate([300,150,300])}

// ---------- GPS tracking (ported from the original app, now route-aware) ----------
function update(p){
  me=p;const ds=STOPS.map(s=>({s,d:dist(p.a,p.o,s.lat,s.lon)})).sort((x,y)=>x.d-y.d),n=ds[0];
  if(meM)meM.setLatLng([p.a,p.o]);else meM=L.circleMarker([p.a,p.o],{radius:8,color:"#fff",weight:3,fillColor:"#2563eb",fillOpacity:1}).addTo(map);
  if(!n||n.d>15000){$("#st").textContent="Outside Lagos coverage";$("#cur").textContent="No Lagos stop nearby";$("#det").textContent="Try Demo ride to see it work.";return}
  const at=n.d<120,near=n.d<400;
  $("#st").textContent=at?"You are at":near?"Approaching / just passed":"Nearest stop";$("#cur").textContent=n.s.name;
  $("#det").textContent=`${n.s.zone} · ${fm(n.d)} away`+(p.acc?` · GPS ±${Math.round(p.acc)} m`:"");
  info={say:at?`You are at ${n.s.name} bus stop.`:`Your nearest bus stop is ${n.s.name}, ${fm(n.d)} away.`};
  $("#nearby").innerHTML=ds.slice(0,5).map(x=>`<div class="li"><div>${esc(x.s.name)}<br><small class="text-muted">${esc(x.s.zone)} · ${fm(x.d)}</small></div><a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&origin=${p.a},${p.o}&destination=${x.s.lat},${x.s.lon}&travelmode=walking">Walk</a></div>`).join("");
  if(trip){
    const st=trip.route.stops,dest=st[trip.di],dd=dist(p.a,p.o,dest.lat,dest.lon);
    let bi=0,bd=1e12;st.forEach((s,i)=>{const d=dist(p.a,p.o,s.lat,s.lon);if(d<bd){bd=d;bi=i}});
    const left=Math.abs(trip.di-bi),between=Math.max(left-1,0);
    let msg,key,buzz=false;
    if(dd<150){msg=`You are at your bus stop, ${dest.name}. Time to get down.`;key="arr";buzz=true;$("#st").textContent="🔔 Get down here"}
    else if(dd<600){msg=`Get ready. ${dest.name} is your next stop, ${fm(dd)} ahead.`;key="near";buzz=true;$("#st").textContent="🔔 Almost there"}
    else{msg=between?`${between} more stop${between>1?"s":""} before ${dest.name}.`:`${dest.name} is your next stop.`;key="c"+between}
    $("#tripInfo").innerHTML=`<b>${esc(msg)}</b> · ${fm(dd)} to go`;announce(key,msg,buzz);info.say=msg;
  }else announce(n.s.name+(at?"a":near?"n":"f"),info.say);
}
function stopTracking(){try{speechSynthesis.cancel()}catch(e){}if(wid!==null)navigator.geolocation.clearWatch(wid);wid=null;if(sim)clearInterval(sim);sim=null;$("#go").textContent="Start tracking";$("#demo").textContent="Demo ride"}
$("#go").onclick=()=>{
  if(wid!==null||sim)return stopTracking();
  if(!navigator.geolocation){$("#det").textContent="This browser has no GPS support.";return}
  lastKey="";say("Voice guide on. Finding your location.");$("#st").textContent="Finding you…";$("#go").textContent="Stop tracking";
  wid=navigator.geolocation.watchPosition(e=>update({a:e.coords.latitude,o:e.coords.longitude,acc:e.coords.accuracy}),
    ()=>{$("#st").textContent="Location blocked";$("#det").textContent="Allow location for this page in your browser settings, then tap Start again.";stopTracking()},{enableHighAccuracy:true,maximumAge:2000,timeout:20000});
  try{navigator.wakeLock&&navigator.wakeLock.request("screen").catch(()=>{})}catch(e){}
};
$("#demo").onclick=()=>{
  if(sim||wid!==null)return stopTracking();
  if(!trip){toast("Pick a route and destination first, then tap Demo ride",true);return}
  const st=trip.route.stops,pts=[];lastKey="";
  const from=Math.abs(trip.di-0)>=Math.abs(trip.di-(st.length-1))?st.length-1:0,step=trip.di>=from?1:-1;
  for(let i=from;i!==trip.di;i+=step){const a=st[i],b=st[i+step];for(let k=0;k<8;k++)pts.push({a:a.lat+(b.lat-a.lat)*k/8,o:a.lon+(b.lon-a.lon)*k/8})}
  pts.push({a:st[trip.di].lat,o:st[trip.di].lon});
  let i=0;$("#demo").textContent="Stop demo";say("Starting demo ride.");
  sim=setInterval(()=>{update(pts[i++]);if(i>=pts.length)stopTracking()},900);
};
$("#rsel").onchange=()=>{const r=ROUTES.find(x=>x.id==$("#rsel").value);$("#dsel").innerHTML='<option value="">Where are you getting down?</option>'+(r?r.stops.map((s,i)=>`<option value="${i}">${esc(s.name)}</option>`).join(""):"");if(r)showRoute(r)};
$("#setTrip").onclick=()=>{const r=ROUTES.find(x=>x.id==$("#rsel").value),di=$("#dsel").value;if(!r||di==="")return toast("Choose a route and your destination stop",true);
  trip={route:r,di:+di};lastKey="";const t=`Trip set to ${r.stops[+di].name} on ${r.name}.`;$("#tripInfo").textContent=t;say(t);if(me)update(me)};
$("#clrTrip").onclick=()=>{trip=null;$("#tripInfo").textContent="";routeL.clearLayers()};
$("#addStop").onclick=guard(async()=>{if(!me)return toast("Start tracking first so we know where you are",true);if(!U)return toast("Sign in to suggest a stop",true);const n=prompt("Name of this bus stop?");if(!n)return;
  await api("/stops",{method:"POST",body:{name:n.trim(),lat:me.a,lon:me.o,zone:"Added by rider"}});toast("Thanks! An admin will review your stop.")});

// ---------- routes ----------
function renderRoutes(){
  const q=($("#rq")?.value||"").trim().toLowerCase();
  const filtered=ROUTES.filter(r=>{
    const hay=[r.code,r.name,...(r.stops||[]).map(s=>s.name),...(r.stops||[]).map(s=>s.zone||"")].join(" ").toLowerCase();
    return !q||hay.includes(q);
  });
  const count=$("#routeCount"); if(count) count.textContent=filtered.length;
  $("#routeList").innerHTML=filtered.map(r=>{
    const opts=r.stops.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join("");
    const stopPreview=r.stops.slice(0,5).map((s,i)=>`<span class="route-stop-chip">${esc(s.name)}</span>`).join('<span class="route-stop-arrow">›</span>');
    const more=r.stops.length>5?`<span class="route-stop-chip more-chip">+${r.stops.length-5} stops</span>`:"";
    return `<article class="card route-result-card">
      <div class="card-body">
        <div class="route-card-head"><div><span class="route-code">${esc(r.code)}</span><h3>${esc(r.name)}</h3><p>${r.stop_count} stops <span>·</span> estimated fare from ${ngn(r.base_fare+r.per_stop_fare)}</p></div>
        <div class="route-card-actions"><button class="btn btn-success btn-sm" onclick="useRoute(${r.id})">Choose route</button><button class="btn btn-outline-success btn-sm" onclick="viewRoute(${r.id})" aria-label="Show route map">Map</button></div></div>
        <div class="route-stop-preview">${stopPreview}${more}</div>
        <details class="route-details"><summary>View all stops &amp; calculate fare</summary>
          <ol class="small mt-3">${r.stops.map(s=>`<li>${esc(s.name)}</li>`).join("")}</ol>
          <div class="row g-2 mt-2"><div class="col"><label class="small text-muted">From</label><select id="ff${r.id}" class="form-select form-select-sm">${opts}</select></div><div class="col"><label class="small text-muted">To</label><select id="ft${r.id}" class="form-select form-select-sm">${opts}</select></div><div class="col-auto align-self-end"><button class="btn btn-sm btn-outline-success" onclick="calcFare(${r.id})">Estimate fare</button></div></div><div id="fr${r.id}" class="small mt-2"></div>
        </details>
      </div></article>`;
  }).join("")||"<div class='empty-state'>No routes match that search. Try a different stop or neighbourhood.</div>";
}
window.viewRoute=id=>showRoute(ROUTES.find(r=>r.id===id));
window.useRoute=id=>{$("#rsel").value=id;$("#rsel").onchange();go("ride");toast("Now choose where you’re getting down")};
window.calcFare=guard(async id=>{const f=await api(`/routes/${id}/fare?from_stop=${$("#ff"+id).value}&to_stop=${$("#ft"+id).value}`);$("#fr"+id).textContent=`${f.stops_between} stop(s) in between · estimated fare ${ngn(f.estimated_fare)} (estimate only)`});
$("#rq").oninput=renderRoutes;

// ---------- marketplace ----------
const stars=n=>n?"★".repeat(Math.round(n))+"☆".repeat(5-Math.round(n))+` ${n}`:"No ratings yet";
const SKEL='<div class="col-12 col-md-6 col-xl-4"><div class="skel-card" aria-hidden="true"><div class="skel skel-img"></div><div class="skel skel-line w60"></div><div class="skel skel-line"></div></div></div>'.repeat(6);
const loadMarket=guard(async()=>{
  $("#mlist").setAttribute("aria-busy","true");$("#mlist").innerHTML=SKEL;
  const p=new URLSearchParams();[["q","#mq"],["category","#mcat"],["stop_id","#mstop"]].forEach(([k,s])=>{if($(s).value)p.set(k,$(s).value)});
  if(nearMe){p.set("lat",nearMe.a);p.set("lon",nearMe.o);p.set("radius_km",5)}
  const l=await api("/businesses?"+p);
  $("#mlist").innerHTML=l.map(b=>{
    const cover=(b.media||[]).find(m=>m.media_type!=="document" && m.file_url);
    const product=(b.products_preview||[]).find(x=>x.image_url) || (b.products_preview||[])[0];
    const coverHtml=cover?`<img class="market-cover-img" src="${esc(cover.file_url)}" alt="${esc(cover.caption||b.name)}" loading="lazy">`:`<div class="market-cover-placeholder"><i class="fa-solid fa-store"></i><span>Local business</span></div>`;
    return `<div class="col-12 col-md-6 col-xl-4"><article class="market-business-card h-100">
      <button class="market-cover" type="button" onclick="openBiz(${b.id})" aria-label="View ${esc(b.name)}">${coverHtml}
        <span class="market-cover-shade"></span><span class="market-cover-badges">${b.promoted?'<span class="market-badge promoted"><i class="fa-solid fa-bolt"></i> Featured</span>':""}${b.verified?'<span class="market-badge verified"><i class="fa-solid fa-circle-check"></i> Verified</span>':""}</span>
        <span class="market-photo-count"><i class="fa-regular fa-images"></i> ${(b.media||[]).filter(m=>m.media_type!=="document").length} photos</span>
      </button>
      <div class="market-business-content">
        <div class="market-business-top"><div><span class="market-category">${esc(b.category||"Local business")}</span><h4>${esc(b.name)}</h4></div><span class="market-rating"><i class="fa-solid fa-star"></i> ${b.rating?Number(b.rating).toFixed(1):"New"}</span></div>
        <div class="market-location"><i class="fa-solid fa-location-dot"></i> ${b.stop?esc(b.stop.name):"Lagos"}${b.distance_km!=null?` <span>· ${Number(b.distance_km).toFixed(1)} km away</span>`:""}</div>
        <p class="market-description">${esc((b.description||"Discover this local business on WAYZA.").slice(0,118))}${(b.description||"").length>118?"…":""}</p>
        ${product?`<div class="market-product-peek">${product.image_url?`<img src="${esc(product.image_url)}" alt="${esc(product.name)}" loading="lazy">`:""}<div><small>POPULAR PRODUCT</small><strong>${esc(product.name)}</strong></div><b>${ngn(product.price)}</b></div>`:""}
        <div class="market-card-bottom"><span class="market-review-count"><i class="fa-regular fa-star"></i> ${b.review_count||0} reviews</span><button class="btn market-view-btn" onclick="openBiz(${b.id})">Explore shop <i class="fa-solid fa-arrow-right"></i></button></div>
      </div>
    </article></div>`;
  }).join("")||`<div class="col-12"><div class="market-empty"><i class="fa-solid fa-store-slash"></i><h4>No businesses found</h4><p>Try another search or choose a different bus stop.</p><button class="btn btn-outline-success" onclick="document.querySelector('#mq').value='';document.querySelector('#mcat').value='';document.querySelector('#mstop').value='';loadMarket()">Clear filters</button></div></div>`;
  $("#mlist").removeAttribute("aria-busy");
  const cats=await api("/categories");const cur=$("#mcat").value;$("#mcat").innerHTML='<option value="">All categories</option>'+cats.map(c=>`<option ${c===cur?"selected":""}>${esc(c)}</option>`).join("")});
["#mq"].forEach(s=>$(s).oninput=()=>{clearTimeout(window._t);window._t=setTimeout(loadMarket,300)});["#mcat","#mstop"].forEach(s=>$(s).onchange=loadMarket);
$("#mnear").onclick=()=>{if(nearMe){nearMe=null;$("#mnear").textContent="Near me";return loadMarket()}navigator.geolocation.getCurrentPosition(e=>{nearMe={a:e.coords.latitude,o:e.coords.longitude};$("#mnear").textContent="Near me ✓";loadMarket()},()=>toast("Allow location to search nearby",true))};
let curBiz=null;
window.openBiz=guard(async id=>{const b=curBiz=await api("/businesses/"+id);let fav=false;if(U)fav=(await api("/favourites")).some(x=>x.id===id);
  $("#bizBody").innerHTML=`<div class="d-flex justify-content-between"><h5>${esc(b.name)} ${b.verified?'<span class="badge text-bg-success">✓</span>':""}</h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="small text-muted mb-2">${esc(b.category)}${b.stop?" · 🚏 "+esc(b.stop.name):""} · ${stars(b.rating)}</div><p>${esc(b.description)}</p>
  <div class="d-flex gap-2 mb-3 flex-wrap">${b.phone?`<a class="btn btn-sm btn-outline-success" href="tel:${esc(b.phone)}">📞 Call</a>`:""}<button class="btn btn-sm btn-success" onclick="msgBiz()">💬 Message</button><button class="btn btn-sm btn-outline-danger" onclick="toggleFav(${id},${fav})">${fav?"♥ Saved":"♡ Save"}</button></div>
  <div class="biz-gallery-heading"><h6><i class="fa-regular fa-images"></i> Business photos & flyers</h6><span>${(b.media||[]).filter(m=>m.media_type!=="document").length} photos</span></div><div class="biz-gallery mb-3">${(b.media||[]).map(m=>m.media_type==="document"?`<a class="biz-document" href="${esc(m.file_url)}" target="_blank" rel="noopener"><i class="fa-solid fa-file-pdf"></i><span>${esc(m.caption||m.file_name)}</span><i class="fa-solid fa-arrow-up-right-from-square"></i></a>`:`<a class="biz-gallery-photo" href="${esc(m.file_url)}" target="_blank" rel="noopener"><img src="${esc(m.file_url)}" alt="${esc(m.caption||b.name)}" loading="lazy"><span>${esc(m.caption||"View photo")}</span></a>`).join("")||"<div class='biz-no-photos'><i class='fa-regular fa-image'></i> This business has not uploaded photos yet.</div>"}</div>
  <h6>Products</h6>${b.products.map(p=>`<div class="li"><div class="d-flex gap-2">${p.image_url?`<img src="${esc(p.image_url)}" alt="" width="48" height="48" style="object-fit:cover;border-radius:8px">`:""}<div>${esc(p.name)}<br><small class="text-muted">${esc(p.description)}</small></div></div><b>${ngn(p.price)}</b></div>`).join("")||"<p class='small text-muted'>No products listed yet.</p>"}
  <h6 class="mt-3">Reviews</h6>${b.reviews.map(r=>`<div class="li"><div><span class="text-warning">${"★".repeat(r.rating)}</span> <b class="small">${esc(r.user)}</b><br><small>${esc(r.comment)}</small></div></div>`).join("")||"<p class='small text-muted'>No reviews yet.</p>"}
  ${U&&U.id!==b.owner_id?`<div class="row g-2 mt-2"><div class="col-4"><select id="rv" class="form-select form-select-sm">${[5,4,3,2,1].map(n=>`<option value="${n}">${"★".repeat(n)}</option>`).join("")}</select></div><div class="col"><input id="rc" class="form-control form-control-sm" placeholder="Your review" maxlength="500"></div><div class="col-auto"><button class="btn btn-sm btn-success" onclick="postReview(${id})">Post</button></div></div>`:""}`;
  bootstrap.Modal.getOrCreateInstance($("#bizModal")).show()});
window.toggleFav=guard(async(id,on)=>{if(!U)return toast("Sign in to save favourites",true);await api("/favourites/"+id,{method:on?"DELETE":"POST"});openBiz(id)});
window.postReview=guard(async id=>{await api(`/businesses/${id}/reviews`,{method:"POST",body:{rating:+$("#rv").value,comment:$("#rc").value}});toast("Thanks for your review!");openBiz(id);loadMarket()});
window.msgBiz=()=>{if(!U)return toast("Sign in to message sellers",true);bootstrap.Modal.getInstance($("#bizModal")).hide();go("msgs");openChat(curBiz.owner_id,curBiz.name,curBiz.id)};

// ---------- messaging (WebSocket + REST) ----------
function connectWS(){if(!T||ws)return;ws=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+"/ws?token="+T);
  ws.onmessage=e=>{const d=JSON.parse(e.data);if(d.type==="message"){if(chatWith&&chatWith.id===d.message.sender_id){appendBubble(d.message);api("/messages/"+chatWith.id)}else toast("💬 "+d.from_name+": "+d.message.body)}else if(d.type==="notification"){toast("🔔 "+d.text);loadNotes()}};
  ws.onclose=()=>{ws=null;if(T)setTimeout(connectWS,4000)}}
const appendBubble=m=>{const c=$("#chatBox");if(!c)return;c.insertAdjacentHTML("beforeend",`<div class="bub ${m.sender_id===U.id?"me":""}">${esc(m.body)}</div>`);c.scrollTop=c.scrollHeight};
const loadThreads=guard(async()=>{if(!U){$("#msgs").innerHTML="<p class='text-muted'>Sign in to see your messages.</p>";return}
  const t=await api("/messages/threads");$("#msgs").innerHTML=`<div id="thr">${t.map(x=>`<div class="li" role="button" onclick="openChat(${x.user_id},'${esc(x.name).replace(/'/g,"")}')"><div><b>${esc(x.name)}</b><br><small class="text-muted">${esc(x.last)}</small></div>${x.unread?`<span class="badge text-bg-success align-self-center">${x.unread}</span>`:""}</div>`).join("")||"<p class='text-muted'>No conversations yet. Message a seller from the Market tab.</p>"}</div><div id="chatPane"></div>`;
  if(chatWith)openChat(chatWith.id,chatWith.name)});
window.openChat=guard(async(id,name,bid)=>{chatWith={id,name,bid};if(!$("#chatPane"))await loadThreads();const m=await api("/messages/"+id);
  $("#chatPane").innerHTML=`<h6 class="mt-3">${esc(name)}</h6><div class="chat" id="chatBox"></div><div class="input-group mt-2"><input id="cm" class="form-control" placeholder="Type a message" maxlength="2000"><button class="btn btn-success" onclick="sendMsg()">Send</button></div>`;
  m.forEach(appendBubble);$("#cm").onkeydown=e=>{if(e.key==="Enter")sendMsg()}});
window.sendMsg=guard(async()=>{const b=$("#cm").value.trim();if(!b)return;const m=await api("/messages",{method:"POST",body:{to_user_id:chatWith.id,body:b,business_id:chatWith.bid||null}});$("#cm").value="";appendBubble(m)});

// ---------- account ----------
async function loadMe(){if(!T)return;try{U=await api("/me");$("#acctBtn").textContent=U.name.split(" ")[0];connectWS();loadNotes()}catch(e){}}
function logout(render=true){T=null;U=null;localStorage.removeItem("tk");if(ws){ws.close();ws=null}$("#acctBtn").textContent="Sign in";if(render)renderAccount()}
window.logout=logout;
const authDone=r=>{T=r.token;U=r.user;localStorage.setItem("tk",T);$("#acctBtn").textContent=U.name.split(" ")[0];connectWS();renderAccount()};
window.doLogin=guard(async()=>authDone(await api("/auth/login",{method:"POST",body:{email:$("#le").value,password:$("#lp").value}})));
window.doReg=guard(async()=>authDone(await api("/auth/register",{method:"POST",body:{name:$("#rn").value,email:$("#re").value,phone:$("#rph").value,password:$("#rp").value,role:$("#rr").value}})));
let notes=[];const loadNotes=async()=>{try{notes=await api("/notifications");const u=notes.filter(n=>!n.read).length;$("#acctBtn").innerHTML=esc(U.name.split(" ")[0])+(u?` <span class="badge text-bg-light">${u}</span>`:"")}catch(e){}};
async function renderAccount(){
  if(!U){$("#acct").innerHTML=`<div class="row g-3"><div class="col-md-6"><div class="card card-body"><h6>Sign in</h6><input id="le" class="form-control mb-2" type="email" placeholder="Email" autocomplete="username"><input id="lp" class="form-control mb-2" type="password" placeholder="Password" autocomplete="current-password"><button class="btn btn-success" onclick="doLogin()">Sign in</button></div></div>
  <div class="col-md-6"><div class="card card-body"><h6>Create account</h6><input id="rn" class="form-control mb-2" placeholder="Full name"><input id="re" class="form-control mb-2" type="email" placeholder="Email"><input id="rph" class="form-control mb-2" placeholder="Phone (optional)"><input id="rp" class="form-control mb-2" type="password" placeholder="Password (8+ characters)" autocomplete="new-password">
  <select id="rr" class="form-select mb-2"><option value="passenger">I’m a passenger</option><option value="business">I own a business</option></select><button class="btn btn-outline-success" onclick="doReg()">Register</button></div></div></div>`;return}
  let h=`<div class="d-flex justify-content-between align-items-center mb-3"><div><h5 class="mb-0">${esc(U.name)}</h5><small class="text-muted">${esc(U.email)} · ${U.role}</small></div><button class="btn btn-sm btn-outline-secondary" onclick="logout()">Sign out</button></div>
  <div class="card card-body mb-3"><h6>Notifications</h6>${notes.map(n=>`<div class="li small"><span>${n.read?"":"● "}${esc(n.text)}</span><small class="text-muted">${esc(n.at.slice(0,10))}</small></div>`).join("")||"<small class='text-muted'>Nothing yet.</small>"}${notes.some(n=>!n.read)?`<button class="btn btn-sm btn-link p-0 mt-1" onclick="markRead()">Mark all read</button>`:""}</div>
  <div class="card card-body mb-3"><h6>Profile</h6><div class="row g-2"><div class="col-md"><input id="pn" class="form-control" value="${esc(U.name)}"></div><div class="col-md"><input id="pp" class="form-control" value="${esc(U.phone)}" placeholder="Phone"></div><div class="col-md-auto"><button class="btn btn-success" onclick="saveProfile()">Save</button></div></div></div>`;
  $("#acct").innerHTML=h+'<div id="role"></div>';
  if(U.role==="passenger")roleFavs();else if(U.role==="business")roleBiz();else roleAdmin("stats")}
window.markRead=guard(async()=>{await api("/notifications/read",{method:"POST"});await loadNotes();renderAccount()});
window.saveProfile=guard(async()=>{U=await api("/me",{method:"PATCH",body:{name:$("#pn").value,phone:$("#pp").value}});toast("Profile saved");loadNotes()});
const roleFavs=guard(async()=>{const f=await api("/favourites");$("#role").innerHTML=`<div class="card card-body"><h6>Saved shops</h6>${f.map(b=>`<div class="li"><span>${esc(b.name)} <small class="text-muted">${esc(b.category)}</small></span><button class="btn btn-sm btn-outline-success" onclick="openBiz(${b.id})">View</button></div>`).join("")||"<small class='text-muted'>Tap ♡ on a shop to save it.</small>"}</div>`});

const roleBiz=guard(async()=>{
  const [bs,plans,pays]=await Promise.all([api("/my/businesses"),api("/plans"),api("/my/payments")]);
  const so=STOPS.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join("");
  $("#role").innerHTML=`<h6>My businesses</h6>${bs.map(b=>`<div class="card card-body mb-3"><div class="d-flex justify-content-between"><b>${esc(b.name)}</b><span>${b.verified?'<span class="badge text-bg-success">Verified</span> ':'<span class="badge text-bg-secondary">Unverified</span> '}${b.subscribed?`<span class="badge text-bg-success">Live until ${esc(b.subscription_expires.slice(0,10))}</span>`:'<span class="badge text-bg-danger">Not visible – subscribe</span>'}${b.suspended?' <span class="badge text-bg-danger">Suspended</span>':""}</span></div>
  <div class="d-flex gap-2 flex-wrap my-2">${plans.map(p=>`<button class="btn btn-sm btn-outline-success" onclick="subscribe(${b.id},'${p.id}')">${esc(p.name)} – ${ngn(p.price_ngn)}/${p.days}d</button>`).join("")}</div>
  <div class="small fw-bold mt-2">Business gallery, posters & flyers</div>
  <div class="d-flex flex-wrap gap-2 my-2">${(b.media||[]).map(m=>m.media_type==="document"?`<a class="btn btn-sm btn-outline-success" href="${esc(m.file_url)}" target="_blank">📄 ${esc(m.caption||m.file_name)}</a>`:`<a href="${esc(m.file_url)}" target="_blank"><img src="${esc(m.file_url)}" alt="${esc(m.caption||"Business image")}" style="width:72px;height:72px;object-fit:cover;border-radius:10px"></a>`).join("")||"<small class='text-muted'>No images or flyers uploaded yet.</small>"}</div>
  <div class="row g-2 mb-2"><div class="col-12"><input type="file" id="media${b.id}" class="form-control form-control-sm" accept="image/jpeg,image/png,image/webp,application/pdf"></div><div class="col"><input id="caption${b.id}" class="form-control form-control-sm" placeholder="Caption (optional)"></div><div class="col-auto"><button class="btn btn-sm btn-outline-success" onclick="uploadBizMedia(${b.id})">Upload</button></div></div>
  <div class="small fw-bold">Products</div>${b.products.map(p=>`<div class="li small"><span>${esc(p.name)} – ${ngn(p.price)}</span><button class="btn btn-sm btn-link text-danger p-0" onclick="delProd(${p.id})">Remove</button></div>`).join("")||"<small class='text-muted'>None yet.</small>"}
  <div class="row g-2 mt-1"><div class="col"><input id="pn${b.id}" class="form-control form-control-sm" placeholder="Product name"></div><div class="col-3"><input id="pr${b.id}" type="number" min="0" class="form-control form-control-sm" placeholder="₦ price"></div><div class="col-12"><input id="pi${b.id}" class="form-control form-control-sm" placeholder="Image URL (optional, https://…)"></div><div class="col-12"><button class="btn btn-sm btn-success" onclick="addProd(${b.id})">Add product</button></div></div></div>`).join("")||"<p class='text-muted small'>Create your first business below.</p>"}
  <div class="card card-body mb-3"><h6>New business</h6><input id="bn" class="form-control mb-2" placeholder="Business name"><input id="bd" class="form-control mb-2" placeholder="Description"><div class="row g-2 mb-2"><div class="col"><input id="bc" class="form-control" placeholder="Category (e.g. Food, Fashion)"></div><div class="col"><input id="bp" class="form-control" placeholder="Phone"></div></div>
  <select id="bs" class="form-select mb-2"><option value="">Nearest bus stop…</option>${so}</select><button class="btn btn-success" onclick="newBiz()">Create</button></div>
  <div class="card card-body"><h6>Payments</h6>${pays.map(p=>`<div class="li small"><span>${esc(p.plan)} · ${ngn(p.amount_ngn)}</span><span>${esc(p.status)} · ${esc(p.at.slice(0,10))}</span></div>`).join("")||"<small class='text-muted'>No payments yet.</small>"}</div>`});
window.uploadBizMedia=guard(async id=>{
  const input=$("#media"+id),file=input.files?.[0];if(!file)return toast("Choose an image or PDF first",true);
  const fd=new FormData();fd.append("file",file);fd.append("caption",$("#caption"+id).value||"");
  const r=await fetch(`/api/businesses/${id}/media`,{method:"POST",headers:T?{Authorization:"Bearer "+T}:{},body:fd});
  const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Upload failed");
  toast("Media uploaded");roleBiz();
});
window.newBiz=guard(async()=>{await api("/businesses",{method:"POST",body:{name:$("#bn").value,description:$("#bd").value,category:$("#bc").value||"General",phone:$("#bp").value,stop_id:$("#bs").value?+$("#bs").value:null}});toast("Business created – subscribe to go live");roleBiz()});
window.addProd=guard(async id=>{await api(`/businesses/${id}/products`,{method:"POST",body:{name:$("#pn"+id).value,price:+$("#pr"+id).value||0,image_url:$("#pi"+id).value}});roleBiz()});
window.delProd=guard(async id=>{await api("/products/"+id,{method:"DELETE"});roleBiz()});
window.subscribe=guard(async(bid,plan)=>{const r=await api("/payments/initialize",{method:"POST",body:{business_id:bid,plan}});location.href=r.authorization_url});

// ---------- admin ----------
window.roleAdmin=guard(async v=>{
  const tabs=["stats","users","businesses","plans","payments","stops","routes"],nav=`<div class="btn-group mb-3 flex-wrap">${tabs.map(t=>`<button class="btn btn-sm btn-${t===v?"success":"outline-success"}" onclick="roleAdmin('${t}')">${t}</button>`).join("")}</div>`;let b="";
  if(v==="stats"){const s=await api("/admin/stats");b=`<div class="row g-2">${Object.entries(s).map(([k,x])=>`<div class="col-6 col-md-3"><div class="card card-body text-center"><div class="fs-4 fw-bold">${k==="revenue_ngn"?ngn(x):x}</div><small class="text-muted">${esc(k.replace(/_/g," "))}</small></div></div>`).join("")}</div>`}
  if(v==="users"){const u=await api("/admin/users");b=`<div class="card card-body mb-3"><h6>Create account</h6><div class="row g-2"><div class="col-md-4"><input id="auName" class="form-control" placeholder="Full name"></div><div class="col-md-4"><input id="auEmail" type="email" class="form-control" placeholder="Email"></div><div class="col-md-4"><input id="auPhone" class="form-control" placeholder="Phone"></div><div class="col-md-4"><input id="auPass" type="password" class="form-control" placeholder="Temporary password (8+ chars)"></div><div class="col-md-4"><select id="auRole" class="form-select"><option value="passenger">Passenger</option><option value="business">Business</option><option value="admin">Admin</option></select></div><div class="col-md-4"><button class="btn btn-success w-100" onclick="adminAddUser()">Create account</button></div></div></div>`+u.map(x=>`<div class="li small"><span>${esc(x.name)} <small class="text-muted">${esc(x.email)} · ${x.role}</small></span><span class="d-flex gap-1"><button class="btn btn-sm btn-outline-${x.is_active?"danger":"success"}" onclick="setUser(${x.id},${!x.is_active})">${x.is_active?"Suspend":"Reactivate"}</button><button class="btn btn-sm btn-outline-danger" onclick="adminDeleteUser(${x.id})">Remove</button></span></div>`).join("")}
  if(v==="businesses"){const [l,plans,users]=await Promise.all([api("/admin/businesses"),api("/admin/plans"),api("/admin/users")]);b=`<div class="card card-body mb-3"><h6>Add business listing</h6><div class="row g-2"><div class="col-md-4"><input id="abOwner" type="number" class="form-control" placeholder="Owner user ID"></div><div class="col-md-4"><input id="abName" class="form-control" placeholder="Business name"></div><div class="col-md-4"><input id="abCategory" class="form-control" placeholder="Category"></div><div class="col-md-6"><input id="abPhone" class="form-control" placeholder="Phone"></div><div class="col-md-6"><input id="abDesc" class="form-control" placeholder="Description"></div><div class="col-12"><button class="btn btn-success" onclick="adminAddBusiness()">Create business</button></div></div><small class="text-muted">Owner IDs: ${users.map(x=>`${x.id} ${esc(x.name)}`).join(" · ")}</small></div>`+l.map(x=>`<div class="card card-body mb-2"><div class="d-flex justify-content-between flex-wrap gap-2"><div><b>${esc(x.name)}</b><div class="small text-muted">${esc(x.category)} · owner #${x.owner_id} · ${x.subscribed?"subscribed":"not subscribed"}</div></div><div class="d-flex gap-1 flex-wrap"><button class="btn btn-sm btn-outline-success" onclick="setBiz(${x.id},'verified',${!x.verified})">${x.verified?"Unverify":"Verify"}</button><button class="btn btn-sm btn-outline-danger" onclick="setBiz(${x.id},'suspended',${!x.suspended})">${x.suspended?"Unsuspend":"Suspend"}</button><button class="btn btn-sm btn-danger" onclick="adminDeleteBusiness(${x.id})">Remove</button></div></div><div class="row g-2 mt-2"><div class="col"><select id="plan${x.id}" class="form-select form-select-sm">${plans.map(p=>`<option value="${p.code}">${esc(p.name)} · ₦${p.price_ngn.toLocaleString()} / ${p.duration_days} days</option>`).join("")}</select></div><div class="col-auto"><button class="btn btn-sm btn-success" onclick="adminAssignPlan(${x.id})">Assign subscription</button></div></div></div>`).join("")}
  if(v==="plans"){const ps=await api("/admin/plans");b=`<div class="card card-body mb-3"><h6>Create subscription plan</h6><div class="row g-2"><div class="col-md-2"><input id="pc" class="form-control" placeholder="code e.g. gold"></div><div class="col-md-3"><input id="pname" class="form-control" placeholder="Plan name"></div><div class="col-md-3"><input id="pdesc" class="form-control" placeholder="Description"></div><div class="col-md-2"><input id="pprice" type="number" min="0" class="form-control" placeholder="Price ₦"></div><div class="col-md-1"><input id="pduration" type="number" min="1" value="30" class="form-control" title="Duration days"></div><div class="col-md-1"><input id="ppromo" type="number" min="0" value="0" class="form-control" title="Promotion days"></div><div class="col-12"><button class="btn btn-success" onclick="adminCreatePlan()">Create plan</button></div></div></div>`+ps.map(p=>`<div class="card card-body mb-2"><div class="d-flex justify-content-between"><b>${esc(p.name)} (${esc(p.code)})</b><span>${p.is_active?"Active":"Inactive"}</span></div><small>${esc(p.description)} · ₦${p.price_ngn.toLocaleString()} · ${p.duration_days} days · ${p.promo_days} promo days</small><div class="d-flex gap-2 mt-2"><button class="btn btn-sm btn-outline-primary" onclick='adminEditPlan(${JSON.stringify(p).replace(/'/g,"&#39;")})'>Edit</button><button class="btn btn-sm btn-outline-danger" onclick="adminDeletePlan(${p.id})">Remove / deactivate</button></div></div>`).join("")}
  if(v==="payments"){const l=await api("/admin/payments");b=l.map(x=>`<div class="li small"><span>${esc(x.reference)} · ${esc(x.plan)}</span><span>${ngn(x.amount_ngn)} · ${esc(x.status)}</span></div>`).join("")||"No payments."}
  if(v==="stops"){const l=await api("/admin/stops/pending");b=l.map(x=>`<div class="li small"><span>${esc(x.name)} <small class="text-muted">${x.lat.toFixed(4)}, ${x.lon.toFixed(4)}</small></span><span class="d-flex gap-1"><button class="btn btn-sm btn-success" onclick="appr(${x.id},true)">Approve</button><button class="btn btn-sm btn-outline-danger" onclick="appr(${x.id},false)">Reject</button></span></div>`).join("")||"No stops waiting for review."}
  if(v==="routes"){b=ROUTES.map(r=>`<div class="li small"><span>${esc(r.code)} · ${esc(r.name)}</span><button class="btn btn-sm btn-outline-danger" onclick="delRoute(${r.id})">Delete</button></div>`).join("")+`<div class="card card-body mt-3"><h6>New route</h6><div class="row g-2"><div class="col-4"><input id="nc" class="form-control" placeholder="Code"></div><div class="col"><input id="nn" class="form-control" placeholder="Route name"></div><div class="col-12"><input id="ns" class="form-control" placeholder="Stop names in order, comma separated (must exist)"></div><div class="col-6"><input id="nb" type="number" class="form-control" placeholder="Base fare ₦" value="150"></div><div class="col-6"><input id="np" type="number" class="form-control" placeholder="Per stop ₦" value="40"></div><div class="col-12"><button class="btn btn-success" onclick="newRoute()">Create route</button></div></div></div>`}
  $("#role").innerHTML=nav+b});
window.adminAddUser=guard(async()=>{await api("/admin/users",{method:"POST",body:{name:$("#auName").value,email:$("#auEmail").value,phone:$("#auPhone").value,password:$("#auPass").value,role:$("#auRole").value}});toast("Account created");roleAdmin("users")});
window.adminDeleteUser=guard(async id=>{if(!confirm("Permanently remove this account and its owned business listings?"))return;await api("/admin/users/"+id,{method:"DELETE"});roleAdmin("users")});
window.adminAddBusiness=guard(async()=>{await api("/admin/businesses",{method:"POST",body:{owner_id:+$("#abOwner").value,name:$("#abName").value,category:$("#abCategory").value||"General",phone:$("#abPhone").value,description:$("#abDesc").value}});toast("Business listing created");roleAdmin("businesses")});
window.adminDeleteBusiness=guard(async id=>{if(!confirm("Permanently remove this business listing?"))return;await api("/admin/businesses/"+id,{method:"DELETE"});roleAdmin("businesses")});
window.adminAssignPlan=guard(async id=>{const fd=new FormData();fd.append("plan_code",$("#plan"+id).value);const r=await fetch(`/api/admin/businesses/${id}/subscription`,{method:"POST",headers:T?{Authorization:"Bearer "+T}:{},body:fd});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||"Could not assign plan");toast("Subscription activated");roleAdmin("businesses")});
window.adminCreatePlan=guard(async()=>{await api("/admin/plans",{method:"POST",body:{code:$("#pc").value,name:$("#pname").value,description:$("#pdesc").value,price_ngn:+$("#pprice").value,duration_days:+$("#pduration").value,promo_days:+$("#ppromo").value,is_active:true}});toast("Plan created");roleAdmin("plans")});
window.adminEditPlan=guard(async p=>{const name=prompt("Plan name",p.name);if(name===null)return;const price=prompt("Price in NGN",p.price_ngn);if(price===null)return;const days=prompt("Duration in days",p.duration_days);if(days===null)return;const desc=prompt("Description",p.description);if(desc===null)return;await api("/admin/plans/"+p.id,{method:"PATCH",body:{code:p.code,name,description:desc,price_ngn:+price,duration_days:+days,promo_days:p.promo_days,is_active:p.is_active}});roleAdmin("plans")});
window.adminDeletePlan=guard(async id=>{if(!confirm("Remove this plan? Plans already used in payments will be deactivated."))return;await api("/admin/plans/"+id,{method:"DELETE"});roleAdmin("plans")});
window.setUser=guard(async(id,on)=>{await api("/admin/users/"+id,{method:"PATCH",body:{is_active:on}});roleAdmin("users")});
window.setBiz=guard(async(id,k,v)=>{await api(`/admin/businesses/${id}?${k}=${v}`,{method:"POST"});roleAdmin("businesses")});
window.appr=guard(async(id,a)=>{await api(`/admin/stops/${id}/approve?approve=${a}`,{method:"POST"});await loadBase();roleAdmin("stops")});
window.delRoute=guard(async id=>{if(!confirm("Delete this route?"))return;await api("/admin/routes/"+id,{method:"DELETE"});await loadBase();roleAdmin("routes")});
window.newRoute=guard(async()=>{await api("/admin/routes",{method:"POST",body:{code:$("#nc").value,name:$("#nn").value,stop_names:$("#ns").value.split(",").map(s=>s.trim()).filter(Boolean),base_fare:+$("#nb").value||0,per_stop_fare:+$("#np").value||0}});await loadBase();toast("Route created");roleAdmin("routes")});

// ---------- boot ----------
async function loadBase(){[STOPS,ROUTES]=await Promise.all([api("/stops"),api("/routes")]);drawStops();
  $("#rsel").innerHTML='<option value="">Choose a route…</option>'+ROUTES.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join("");
  $("#mstop").innerHTML='<option value="">Any bus stop</option>'+STOPS.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join("");renderRoutes()}
(async()=>{
  await guard(loadBase)();await loadMe();
  const ref=new URLSearchParams(location.search).get("pay_ref");
  if(ref&&U){history.replaceState({},"","/");try{const r=await api("/payments/verify/"+encodeURIComponent(ref));toast(r.status==="success"?"Payment confirmed – your shop is live!":"Payment status: "+r.status,r.status!=="success")}catch(e){toast(e.message,true)}go("account")}
  else go(["ride","routes","market","msgs","account"].includes(location.hash.slice(1))?location.hash.slice(1):"ride");
})();
