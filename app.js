const $=id=>document.getElementById(id),K="yutu-v2",C="yutu-cfg-v2";
const load=(k,d)=>{try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}};
let q=load(K,[]);if(!Array.isArray(q))q=[];
const DEF={sn:3,st:"09:00,14:00,20:00",vn:2,vt:"12:00,18:00",publish:"schedule",
sub:true,lang:"es",model:"small",sub_pos:"bottom",sub_size:"m",sub_color:"white",sub_words:"",sub_caps:false,
cut_mode:"auto",cut_start:0,short_len:58,frame:"crop",vid_trim:false,vid_start:0,vid_len:0,
fx:"none",vivid:false,vignette:false,fade:false,loudnorm:false};
let cfg=Object.assign({},DEF,load(C,{}));
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
for(const k in DEF){const el=$("c-"+k);if(!el)continue;
if(el.type==="checkbox"){el.checked=!!cfg[k];el.onchange=()=>{cfg[k]=el.checked;localStorage.setItem(C,JSON.stringify(cfg))}}
else{el.value=cfg[k];el.oninput=()=>{cfg[k]=el.type==="number"?(el.value===""?"":Math.max(0,+el.value||0)):el.value;localStorage.setItem(C,JSON.stringify(cfg));render()}}}
$("export").onclick=()=>{const b=new Blob([JSON.stringify({config:cfg,items:q},null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="yutu-studio-cola.json";a.click();URL.revokeObjectURL(a.href)};
render();

/* efectos */
addEventListener("load",()=>setTimeout(()=>$("splash").classList.add("out"),1300));
document.querySelectorAll(".head,.card:not(.stat),.stat,.steps>*").forEach((e,i)=>{e.classList.add("rv");e.style.transitionDelay=(i%4)*70+"ms"});
const io=new IntersectionObserver(es=>es.forEach(x=>{if(x.isIntersecting){x.target.classList.add("in");io.unobserve(x.target)}}),{threshold:.12});
document.querySelectorAll(".rv").forEach(e=>io.observe(e));
document.addEventListener("click",e=>{const b=e.target.closest(".btn");if(!b)return;const r=b.getBoundingClientRect(),s=document.createElement("span");s.className="rp";const d=Math.max(r.width,r.height);s.style.cssText=`width:${d}px;height:${d}px;left:${e.clientX-r.left-d/2}px;top:${e.clientY-r.top-d/2}px`;b.appendChild(s);setTimeout(()=>s.remove(),600)});
function openWin(t,html){$("win-title").textContent=t;$("win-body").innerHTML=html;$("win").classList.add("open");$("win").setAttribute("aria-hidden","false")}
function closeWin(){$("win").classList.remove("open");$("win").setAttribute("aria-hidden","true")}
$("win").onclick=e=>{if(e.target===$("win")||e.target.dataset.close!==undefined)closeWin()};addEventListener("keydown",e=>{if(e.key==="Escape")closeWin()});
$("list").addEventListener("click",e=>{if(e.target.closest("button"))return;const it=e.target.closest(".item");if(!it)return;const x=q.find(y=>y.key===it.querySelector("[data-r]").dataset.r);
openWin(x.type==="playlist"?"Playlist":"Vista previa",(x.type==="video"?`<img src="https://i.ytimg.com/vi/${x.id}/hqdefault.jpg" alt="Miniatura" onerror="this.remove()">`:"")+`<p><b>Salida:</b> ${x.kind==="short"?"Short vertical 9:16":"Video completo"}</p><p class="sub" style="word-break:break-all">${esc(x.url)}</p>`)});
$("open-guide").onclick=()=>openWin("Guía de activación",`<ol><li>Ejecutá <code>worker\\2-INSTALAR-Y-EJECUTAR.bat</code>; queda en segundo plano con un icono junto al wifi.</li><li>Tocá <b>Conectar con mi canal de YouTube</b> e iniciá sesión en el Chrome que se abre (solo una vez).</li><li>Configurá la edición y tocá <b>Comenzar proceso</b> (solo edita) o <b>Comenzar proceso, automatizar y subir ahora</b>.</li></ol><p class="sub">Esa sesión de Chrome es el permiso para publicar en tu canal.</p>`);

/* worker local */
const API="http://127.0.0.1:8765";
async function call(path,body){const c=new AbortController(),t=setTimeout(()=>c.abort(),4000);
try{const r=await fetch(API+path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:c.signal}:{signal:c.signal});return await r.json()}catch{return null}finally{clearTimeout(t)}}
const setPill=(id,s,t)=>{const e=$(id);e.className="pill "+s;e.lastChild.textContent=t};
let running=false;
async function poll(){
if(!document.hidden){const s=await call("/status");
if(!s){setPill("p-worker","","Worker apagado");setPill("p-yt","","Canal sin conectar");running=false;$("start").disabled=$("start-up").disabled=false}
else{running=s.running;setPill("p-worker","ok","Worker conectado");
setPill("p-yt",s.youtube?"ok":"",s.youtube?"Canal conectado":"Canal sin conectar");
$("yt-detail").textContent=s.youtube?"":(s.detail||"");pubRender(s.items||[]);$("log").textContent=s.log.length?s.log.join("\n"):"Sin actividad todavía.";$("log").scrollTop=1e9;$("start").disabled=$("start-up").disabled=s.running;
$("start").textContent=s.running?"Procesando…":"Comenzar proceso (solo editar) ▶";$("start-up").textContent=s.running?"Procesando…":"Comenzar proceso, automatizar y subir ahora ⚡"}}
setTimeout(poll,running?2500:7000)}
const note=(t,err)=>{const m=$("ctl-msg");m.textContent=t;m.className="msg"+(err?" err":"")};
$("connect").onclick=async()=>{const r=await call("/connect",{});if(!r)return note("No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.",1);
note(r.message||"Iniciá sesión en YouTube en el Chrome que se abrió.");poll()};
const go=async upload=>{if(!q.length)return note("La cola está vacía: agregá links primero.",1);
const r=await call("/start",{config:cfg,items:q,upload,reedit:$("reedit").checked});if(!r)return note("No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.",1);
note(r.message,!r.ok);poll()};
$("start").onclick=()=>go(false);$("start-up").onclick=()=>go(true);
poll();

const ST={pending:"En espera",processing:"Editando…",ready:"Listo (editado)",scheduled:"Programado en YouTube",published:"Publicado",error:"Error"};
function pubRender(items){const el=$("pub");if(!items.length){el.innerHTML='<div class="empty">Todavía no hay videos procesados.</div>';return}
el.innerHTML=items.map(x=>`<div class="pc">${x.type==="video"?`<img loading="lazy" src="https://i.ytimg.com/vi/${esc(x.id||"")}/mqdefault.jpg" alt="" onerror="this.style.visibility='hidden'">`:""}<div><b>${esc(x.title||x.url||"")}</b><span class="st ${esc(x.status||"")}">${ST[x.status]||esc(x.status||"")}</span><small>${x.kind==="short"?"Short":"Video"}${x.publishAt?" · "+new Date(x.publishAt).toLocaleString("es",{dateStyle:"medium",timeStyle:"short"}):""}</small>${x.error?`<small>${esc(x.error)}</small>`:""}</div></div>`).join("")}
$("force").onclick=async()=>{const r=await call("/forzar",{});note(r?r.message:"No encuentro el worker.",!r);poll()};
