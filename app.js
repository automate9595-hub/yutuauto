const $=id=>document.getElementById(id),K="yutu-v2",C="yutu-cfg-v2";
const load=(k,d)=>{try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}};
let q=load(K,[]);if(!Array.isArray(q))q=[];
let cfg=Object.assign({sn:3,st:"09:00,14:00,20:00",vn:2,vt:"12:00,18:00",lang:"es",sub:true},load(C,{}));
function parse(raw){try{const u=new URL(raw.trim()),h=u.hostname.replace(/^www\./,"").toLowerCase();
if(!["youtube.com","m.youtube.com","music.youtube.com","youtu.be"].includes(h))return null;
const l=u.searchParams.get("list");let v=null;
if(h==="youtu.be")v=u.pathname.split("/")[1];else if(u.pathname==="/watch")v=u.searchParams.get("v");else if(/^\/(shorts|embed|live)\//.test(u.pathname))v=u.pathname.split("/")[2];
const short=u.pathname.startsWith("/shorts/");
if(v&&/^[\w-]{11}$/.test(v))return{type:"video",id:v,url:"https://www.youtube.com/watch?v="+v,kind:short?"short":"video"};
if(l)return{type:"playlist",id:l,url:"https://www.youtube.com/playlist?list="+encodeURIComponent(l),kind:"video"};return null}catch{return null}}
const esc=s=>s.replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const times=s=>s.split(",").map(x=>x.trim()).filter(x=>/^\d{1,2}:\d{2}$/.test(x)).sort();
function slots(kind,count,n,t){const out=[],ts=times(t).slice(0,n||0);if(!ts.length)return out;
const now=new Date();for(let d=0;out.length<count&&d<400;d++)for(const h of ts){const [H,M]=h.split(":").map(Number);const x=new Date(now.getFullYear(),now.getMonth(),now.getDate()+d,H,M);if(x>now&&out.length<count)out.push(x)}return out}
function save(){localStorage.setItem(K,JSON.stringify(q));render()}
function render(){
const sh=q.filter(x=>x.kind==="short"),vd=q.filter(x=>x.kind!=="short");
$("s-total").textContent=q.length;$("s-short").textContent=sh.length;$("s-video").textContent=vd.length;
const dS=cfg.sn?Math.ceil(sh.length/cfg.sn):0,dV=cfg.vn?Math.ceil(vd.length/cfg.vn):0;$("s-days").textContent=Math.max(dS,dV);
$("qcount").textContent=q.length+(q.length===1?" elemento":" elementos");
$("list").innerHTML=q.length?q.map(x=>`<div class="item"><div class="ic">${x.type==="playlist"?"▤":"▶"}</div><div><div class="url">${esc(x.url)}</div><div class="sub">${x.type==="playlist"?"Playlist (se expande al procesar)":"Video individual"}</div></div><div class="tog"><button class="${x.kind==="short"?"on":""}" data-k="${x.key}" data-v="short">Short</button><button class="${x.kind!=="short"?"on":""}" data-k="${x.key}" data-v="video">Video</button></div><button class="x" data-r="${x.key}" aria-label="Quitar">×</button></div>`).join(""):'<div class="empty"><b>Tu cola está vacía</b>Pegá links arriba para comenzar.</div>';
const a=slots("short",Math.min(sh.length,8),cfg.sn,cfg.st).map(d=>[d,"Short"]),b=slots("video",Math.min(vd.length,8),cfg.vn,cfg.vt).map(d=>[d,"Video"]);
const all=[...a,...b].sort((x,y)=>x[0]-y[0]);
$("sched").innerHTML=all.length?all.map(([d,t])=>`<div class="sl"><span>${d.toLocaleDateString("es",{weekday:"short",day:"numeric",month:"short"})} · ${d.toLocaleTimeString("es",{hour:"2-digit",minute:"2-digit"})}</span><b class="tg ${t==="Video"?"v":""}">${t}</b></div>`).join(""):'<div class="empty">Agregá elementos a la cola para ver el calendario.</div>'}
$("list").onclick=e=>{const t=e.target;if(t.dataset.r){q=q.filter(x=>x.key!==t.dataset.r);save()}if(t.dataset.k){q.find(x=>x.key===t.dataset.k).kind=t.dataset.v;save()}};
$("add").onclick=()=>{const L=$("links").value.split(/\n|,|;/).map(s=>s.trim()).filter(Boolean),m=$("msg");
if(!L.length){m.textContent="Pegá al menos un enlace.";m.className="msg err";return}
let a=0,d=0,i=0;for(const l of L){const p=parse(l);if(!p){i++;continue}const key=p.type+":"+p.id;if(q.some(x=>x.key===key)){d++;continue}q.push({...p,key,status:"pending"});a++}
save();m.textContent=`Agregados ${a} · repetidos ${d} · no reconocidos ${i}`;m.className="msg"+(a||d?"":" err");if(a)$("links").value=""};
$("clr").onclick=()=>{$("links").value="";$("msg").textContent=""};
$("empty").onclick=()=>{if(q.length&&confirm("¿Vaciar la cola?")){q=[];save()}};
$("all-short").onclick=()=>{q.forEach(x=>x.kind="short");save()};$("all-video").onclick=()=>{q.forEach(x=>x.kind="video");save()};
const F={sn:"c-sn",st:"c-st",vn:"c-vn",vt:"c-vt",lang:"c-lang"};
for(const k in F){const el=$(F[k]);el.value=cfg[k];el.oninput=()=>{cfg[k]=el.type==="number"?Math.max(0,+el.value||0):el.value;localStorage.setItem(C,JSON.stringify(cfg));render()}}
$("c-sub").checked=cfg.sub;$("c-sub").onchange=e=>{cfg.sub=e.target.checked;localStorage.setItem(C,JSON.stringify(cfg))};
$("export").onclick=()=>{const b=new Blob([JSON.stringify({config:cfg,items:q},null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="yutu-studio-cola.json";a.click();URL.revokeObjectURL(a.href)};
render();

/* efectos */
addEventListener("load",()=>setTimeout(()=>$("splash").classList.add("out"),1300));
document.querySelectorAll(".head,.card:not(.stat),.stat,.steps>*").forEach((e,i)=>{e.classList.add("rv");e.style.transitionDelay=(i%4)*70+"ms"});
const io=new IntersectionObserver(es=>es.forEach(x=>{if(x.isIntersecting){x.target.classList.add("in");io.unobserve(x.target)}}),{threshold:.12});
document.querySelectorAll(".rv").forEach(e=>io.observe(e));
addEventListener("pointermove",e=>{const s=$("spot");s.style.left=e.clientX+"px";s.style.top=e.clientY+"px"});
document.addEventListener("click",e=>{const b=e.target.closest(".btn");if(!b)return;const r=b.getBoundingClientRect(),s=document.createElement("span");s.className="rp";const d=Math.max(r.width,r.height);s.style.cssText=`width:${d}px;height:${d}px;left:${e.clientX-r.left-d/2}px;top:${e.clientY-r.top-d/2}px`;b.appendChild(s);setTimeout(()=>s.remove(),600)});
function openWin(t,html){$("win-title").textContent=t;$("win-body").innerHTML=html;$("win").classList.add("open");$("win").setAttribute("aria-hidden","false")}
function closeWin(){$("win").classList.remove("open");$("win").setAttribute("aria-hidden","true")}
$("win").onclick=e=>{if(e.target===$("win")||e.target.dataset.close!==undefined)closeWin()};addEventListener("keydown",e=>{if(e.key==="Escape")closeWin()});
$("list").addEventListener("click",e=>{if(e.target.closest("button"))return;const it=e.target.closest(".item");if(!it)return;const x=q.find(y=>y.key===it.querySelector("[data-r]").dataset.r);
openWin(x.type==="playlist"?"Playlist":"Vista previa",(x.type==="video"?`<img src="https://i.ytimg.com/vi/${x.id}/hqdefault.jpg" alt="Miniatura" onerror="this.remove()">`:"")+`<p><b>Salida:</b> ${x.kind==="short"?"Short vertical 9:16":"Video completo"}</p><p class="sub" style="word-break:break-all">${esc(x.url)}</p>`)});
$("open-guide").onclick=()=>openWin("Guía de activación",`<ol><li>Exportá la cola con el botón verde.</li><li>Poné <code>client_secret.json</code> (OAuth de escritorio, YouTube Data API v3) en la carpeta <code>worker</code>.</li><li>Ejecutá <code>2-INSTALAR-Y-EJECUTAR.bat</code>.</li><li>Dejá la PC encendida: cada video queda programado en su horario.</li></ol>`);
