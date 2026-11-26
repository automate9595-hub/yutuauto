const $=id=>document.getElementById(id),K="yutu-v2",C="yutu-cfg-v3",C_OLD="yutu-cfg-v2",STEP_K="yutu-step";
const load=(k,d)=>{try{const v=JSON.parse(localStorage.getItem(k));return v===null||v===undefined?d:v}catch{return d}};
let q=load(K,[]);if(!Array.isArray(q))q=[];
const DEF={sn:3,st:"09:00,14:00,20:00",vn:2,vt:"12:00,18:00",publish:"now",
sub:true,lang:"es-latino",stt:"auto",model:"small",sub_pos:"bottom",sub_size:"m",sub_color:"white",sub_words:"",sub_caps:false,
cut_mode:"auto",cut_start:0,short_len:60,frame:"crop",vid_trim:false,vid_start:0,vid_len:0,
fx_list:[],fx_mode:"seq",fx_dur:3,fx_gap:0,fx_blend:0.6,fx_power:1,fx_start:0,fx_repeat:true,
vivid:false,vignette:false,fade:false,loudnorm:false,
ia_mode:"alternar",ia_cut:true,ia_fx:true,ia_zoom:true,lista_cada:0,ia_sub:true,ia_text:true,hashtags_base:"#MobileLegends #mlbb #shorts #gameplay #fyp",hashtags_titulo:true,
split_n:1,split_gap:6,split_mode:"auto",auto_reanudar:true};
let saved=load(C,null);if(saved===null){saved=load(C_OLD,{});delete saved.publish}   /* migra la config anterior; la publicación vuelve a "inmediata" */
let cfg=Object.assign({},DEF,saved);if(String(cfg.ia_mode).includes("grok"))cfg.ia_mode=String(cfg.ia_mode).replace("grok","groq");
if(+cfg.short_len===58)cfg.short_len=60;
const fmtDur=sec=>{sec=+sec||0;if(sec<60)return sec+" s";const m=+(sec/60).toFixed(2);return m+" min"};
const saveCfg=()=>{try{localStorage.setItem(C,JSON.stringify(cfg))}catch{}};

function parse(raw){try{const u=new URL(raw.trim()),h=u.hostname.replace(/^www\./,"").toLowerCase();
if(!["youtube.com","m.youtube.com","music.youtube.com","youtu.be"].includes(h))return null;
const l=u.searchParams.get("list");let v=null;
if(h==="youtu.be")v=u.pathname.split("/")[1];else if(u.pathname==="/watch")v=u.searchParams.get("v");else if(/^\/(shorts|embed|live)\//.test(u.pathname))v=u.pathname.split("/")[2];
const short=u.pathname.startsWith("/shorts/");
if(v&&/^[\w-]{11}$/.test(v))return{type:"video",id:v,url:"https://www.youtube.com/watch?v="+v,kind:short?"short":"video"};
if(l)return{type:"playlist",id:l,url:"https://www.youtube.com/playlist?list="+encodeURIComponent(l),kind:"video"};return null}catch{return null}}
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const times=s=>String(s).split(",").map(x=>x.trim()).filter(x=>/^\d{1,2}:\d{2}$/.test(x)).sort();
function slots(count,n,t){const out=[],ts=times(t).slice(0,n||0);if(!ts.length)return out;
const now=new Date();for(let d=0;out.length<count&&d<400;d++)for(const h of ts){const [H,M]=h.split(":").map(Number);const x=new Date(now.getFullYear(),now.getMonth(),now.getDate()+d,H,M);if(x>now&&out.length<count)out.push(x)}return out}
function save(){try{localStorage.setItem(K,JSON.stringify(q))}catch{}render()}

/* ---------- pasos desplegables ---------- */
const steps=[...document.querySelectorAll(".stp")];
function openStep(n,scroll){steps.forEach(s=>{const o=+s.dataset.n===n;s.classList.toggle("open",o);s.querySelector(".stp-h").setAttribute("aria-expanded",String(o))});
try{localStorage.setItem(STEP_K,String(n))}catch{}
if(scroll){const s=steps.find(x=>+x.dataset.n===n);if(s)setTimeout(()=>s.scrollIntoView({behavior:"smooth",block:"start"}),30)}}
steps.forEach(s=>s.querySelector(".stp-h").onclick=()=>{const n=+s.dataset.n;if(s.classList.contains("open")){s.classList.remove("open");s.querySelector(".stp-h").setAttribute("aria-expanded","false")}else openStep(n,true)});
document.querySelectorAll("[data-go]").forEach(b=>b.onclick=()=>openStep(+b.dataset.go,true));
document.querySelectorAll(".grp-h").forEach(h=>h.onclick=()=>h.parentElement.classList.toggle("open"));
openStep(Math.min(8,Math.max(1,+load(STEP_K,1)||1)),false);

/* ---------- resúmenes de cada paso ---------- */
const L={lang:{"es-latino":"Español latino",es:"Español",en:"Inglés",auto:"Detectar idioma"},
stt:{auto:"Automático (Groq large-v3 → PC)",groq_v3:"Groq large-v3",groq_turbo:"Groq large-v3-turbo",local:"En tu PC",vosk:"Vosk"},
ia:{alternar:"alternando",groq_primero:"Groq primero",gemini_primero:"Gemini primero",claude_primero:"Claude primero",solo_gemini:"solo Gemini",solo_groq:"solo Groq",solo_claude:"solo Claude",apagado:"apagada"}};
var DSTP="yt";
let W={worker:false,yt:false,running:false,items:[]};
function sums(){const sh=q.filter(x=>x.kind==="short").length;
const set=(n,t,ok)=>{$("sum-"+n).textContent=t;const s=steps.find(x=>+x.dataset.n===n);if(s)s.classList.toggle("done",!!ok)};
const sY=DSTP==="yt",oD=({fb:"Facebook",tt:"TikTok"})[DSTP]||"";
set(1,W.worker?(sY?(W.yt?"Worker y canal conectados":"Worker conectado · falta conectar el canal"):"Worker conectado · subís a "+oD+" (no hace falta YouTube)"):"Worker apagado: ejecutá 2-INSTALAR-Y-EJECUTAR.bat",W.worker&&(!sY||W.yt));
set(2,q.length?`${q.length} en cola · ${sh} Shorts · ${q.length-sh} videos`:"Pegá los links",q.length>0);
$("g-split").textContent=(+cfg.split_n||1)>1?cfg.split_n+" por video":"";
set(3,`${(+cfg.split_n||1)>1?cfg.split_n+' Shorts por video (1 cada '+(cfg.split_gap||0)+' h) · ':''}Short ${fmtDur(cfg.short_len||60)} · ${({auto:"tramo automático",inicio:"desde el inicio",manual:"desde "+fmtDur(cfg.cut_start)})[cfg.cut_mode]}${cfg.vid_trim?" · videos recortados":""}`,true);
const ac=["vivid","vignette","fade","loudnorm"].filter(k=>cfg[k]).length;
set(4,`${cfg.fx_list.length?cfg.fx_list.length+" efectos":"Sin efectos"}${ac?" · "+ac+" de acabado":""}`,true);
const tareas=["ia_text","ia_cut","ia_fx","ia_zoom"].filter(k=>cfg[k]).length;
set(5,cfg.ia_mode==="apagado"?"IA apagada":`IA ${L.ia[cfg.ia_mode]||cfg.ia_mode} · ${tareas} tareas`,true);
set(6,cfg.publish==="now"?"Publicar de inmediato":`Programar · ${cfg.sn} Shorts y ${cfg.vn} videos por día`,true);
$("sch-box").style.display=cfg.publish==="schedule"?"":"none"}

const nOf=x=>Math.max(1,Math.min(30,+(x.n||cfg.split_n)||1));
function render(){
const sh=q.filter(x=>x.kind==="short"),vd=q.filter(x=>x.kind!=="short");
$("s-total").textContent=q.length;$("s-short").textContent=sh.length;$("s-video").textContent=vd.length;
$("qcount").textContent=q.length+(q.length===1?" elemento":" elementos");
$("list").innerHTML=q.length?q.map(x=>`<div class="item"><div class="ic">${x.type==="playlist"?"▤":"▶"}</div><div><div class="url">${esc(x.url)}</div><div class="sub">${x.type==="playlist"?"Playlist (se expande al procesar)":"Video individual"}</div></div>${x.kind==="short"&&x.type==="video"?`<label class="nn" title="Cuántos Shorts sacar de este video"><input type="number" min="1" max="30" value="${nOf(x)}" data-n="${esc(x.key)}" aria-label="Cantidad de Shorts"><span>×</span></label>`:""}<div class="tog"><button class="${x.kind==="short"?"on":""}" data-k="${esc(x.key)}" data-v="short">Short</button><button class="${x.kind!=="short"?"on":""}" data-k="${esc(x.key)}" data-v="video">Video</button></div><button class="x" data-r="${esc(x.key)}" aria-label="Quitar">×</button></div>`).join(""):'<div class="empty"><b>Tu cola está vacía</b>Pegá links arriba para comenzar.</div>';
const base=slots(Math.min(sh.length,8),cfg.sn,cfg.st),a=[];
sh.forEach((x,i)=>{const n=x.type==="video"?nOf(x):1,t0=base[i];if(!t0)return;for(let k=0;k<n&&a.length<14;k++)a.push([new Date(t0.getTime()+k*(+cfg.split_gap||0)*36e5),n>1?`Short ${k+1}/${n}`:"Short"])});
const b=slots(Math.min(vd.length,8),cfg.vn,cfg.vt).map(d=>[d,"Video"]);
const all=[...a,...b].sort((x,y)=>x[0]-y[0]);
$("sched").innerHTML=all.length?all.map(([d,t])=>`<div class="sl"><span>${d.toLocaleDateString("es",{weekday:"short",day:"numeric",month:"short"})} · ${d.toLocaleTimeString("es",{hour:"2-digit",minute:"2-digit"})}</span><b class="tg ${t==="Video"?"v":""}">${t}</b></div>`).join(""):'<div class="empty">Agregá elementos a la cola para ver el calendario.</div>';
sums()}
$("list").oninput=e=>{const t=e.target;if(t.dataset.n){const x=q.find(y=>y.key===t.dataset.n);if(x){x.n=Math.max(1,Math.min(30,+t.value||1));try{localStorage.setItem(K,JSON.stringify(q))}catch{}sums()}}};
$("list").onclick=e=>{const t=e.target;if(t.dataset.n)return;if(t.dataset.r){q=q.filter(x=>x.key!==t.dataset.r);save()}if(t.dataset.k){q.find(x=>x.key===t.dataset.k).kind=t.dataset.v;save()}};
$("add").onclick=()=>{const L=$("links").value.split(/\n|,|;/).map(s=>s.trim()).filter(Boolean),m=$("msg");
if(!L.length){m.textContent="Pegá al menos un enlace.";m.className="msg err";return}
let a=0,d=0,i=0;for(const l of L){const p=parse(l);if(!p){i++;continue}const key=p.type+":"+p.id;if(q.some(x=>x.key===key)){d++;continue}q.push({...p,key,status:"pending",nuevo:true});a++}
save();m.textContent=`Agregados ${a} · repetidos ${d} · no reconocidos ${i}`;m.className="msg"+(a||d?"":" err");if(a)$("links").value=""};
$("clr").onclick=()=>{$("links").value="";$("msg").textContent=""};
$("empty").onclick=()=>{if(q.length&&confirm("¿Vaciar la cola?")){q=[];save()}};
$("all-short").onclick=()=>{q.forEach(x=>x.kind="short");save()};$("all-video").onclick=()=>{q.forEach(x=>x.kind="video");save()};

/* ---------- efectos ---------- */
const FX={zoomin:"Zoom de acercamiento",zoomout:"Zoom de alejamiento",pulse:"Pulso al ritmo",shake:"Temblor de cámara",pan:"Paneo lateral",tilt:"Inclinación suave",flash:"Destello blanco",glitch:"Glitch RGB",chroma:"Aberración cromática",blur:"Desenfoque",pop:"Color intenso",bw:"Blanco y negro dramático",sepia:"Vintage sepia",cine:"Cine teal y naranja",vignette:"Viñeta pulsante",strobe:"Estrobo negativo",mirror:"Espejo",grain:"Grano de película",bars:"Barras cinemáticas",trail:"Estela de movimiento",hue:"Cambio de tono"};
const PRE={dyn:{l:["zoomin","pulse","flash","shake","pop","glitch"],m:"seq",d:2.5},cine:{l:["zoomout","cine","bars","vignette","grain"],m:"overlap",d:4},retro:{l:["sepia","grain","vignette","trail"],m:"overlap",d:4},all:{l:Object.keys(FX),m:"seq",d:2},none:{l:[]}};
function fxRender(){if(!Array.isArray(cfg.fx_list))cfg.fx_list=[];cfg.fx_list=cfg.fx_list.filter(k=>FX[k]);
$("fxchips").innerHTML=Object.keys(FX).map(k=>{const i=cfg.fx_list.indexOf(k);return `<label class="fxc${i>=0?" on":""}"><input type="checkbox" data-fx="${k}" ${i>=0?"checked":""}><span>${FX[k]}</span>${i>=0?`<b>${i+1}</b>`:""}</label>`}).join("");
$("fx-count").textContent=cfg.fx_list.length?cfg.fx_list.length+" elegidos":"ninguno"}
$("fxchips").onchange=e=>{const k=e.target.dataset.fx;if(!k)return;cfg.fx_list=cfg.fx_list.filter(x=>x!==k);if(e.target.checked)cfg.fx_list.push(k);saveCfg();fxRender();sums()};
document.querySelectorAll("[data-fxp]").forEach(b=>b.onclick=()=>{const p=PRE[b.dataset.fxp];cfg.fx_list=p.l.slice();if(p.m){cfg.fx_mode=p.m;cfg.fx_dur=p.d;$("c-fx_mode").value=p.m;$("c-fx_dur").value=p.d}saveCfg();fxRender();sums()});
for(const k in DEF){const el=$("c-"+k);if(!el)continue;
if(el.type==="checkbox"){el.checked=!!cfg[k];el.onchange=()=>{cfg[k]=el.checked;saveCfg();sums()}}
else{el.value=cfg[k];if(el.tagName==="SELECT"&&el.value!==String(cfg[k])){cfg[k]=DEF[k];el.value=DEF[k]}
el.oninput=()=>{cfg[k]=el.type==="number"?(el.value===""?"":Math.max(0,+el.value||0)):el.value;saveCfg();render()}}}
fxRender();
$("export").onclick=()=>{const b=new Blob([JSON.stringify({config:cfg,items:q},null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="yutu-studio-cola.json";a.click();URL.revokeObjectURL(a.href)};
render();

/* ---------- ventana emergente ---------- */
document.addEventListener("click",e=>{const b=e.target.closest(".btn");if(!b)return;const r=b.getBoundingClientRect(),s=document.createElement("span");s.className="rp";const d=Math.max(r.width,r.height);s.style.cssText=`width:${d}px;height:${d}px;left:${e.clientX-r.left-d/2}px;top:${e.clientY-r.top-d/2}px`;b.appendChild(s);setTimeout(()=>s.remove(),600)});
function openWin(t,html){$("win-title").textContent=t;$("win-body").innerHTML=html;$("win").classList.add("open");$("win").setAttribute("aria-hidden","false")}
function closeWin(){$("win").classList.remove("open");$("win").setAttribute("aria-hidden","true");const v=$("win-body").querySelector("video");if(v)v.pause()}
$("win").onclick=e=>{if(e.target===$("win")||e.target.dataset.close!==undefined)closeWin()};addEventListener("keydown",e=>{if(e.key==="Escape")closeWin()});
$("list").addEventListener("click",e=>{if(e.target.closest("button,label,input"))return;const it=e.target.closest(".item");if(!it)return;const x=q.find(y=>y.key===it.querySelector("[data-r]").dataset.r);if(!x)return;
openWin(x.type==="playlist"?"Playlist":"Vista previa",(x.type==="video"?`<img src="https://i.ytimg.com/vi/${esc(x.id)}/hqdefault.jpg" alt="Miniatura" onerror="this.remove()">`:"")+`<p><b>Salida:</b> ${x.kind==="short"?"Short vertical 9:16":"Video completo"}</p><p class="sub" style="word-break:break-all">${esc(x.url)}</p>`)});
$("open-guide").onclick=()=>openWin("Guía de activación",`<ol><li>Ejecutá <code>worker\\2-INSTALAR-Y-EJECUTAR.bat</code>; queda en segundo plano con un icono junto al wifi.</li><li>Tocá <b>Conectar con mi canal de YouTube</b> e iniciá sesión en el Chrome que se abre (solo una vez).</li><li>Recorré los pasos, y en el último tocá <b>Procesar y publicar todo</b>.</li></ol><p class="sub">Esa sesión de Chrome es el permiso para publicar en tu canal.</p>`);

/* ---------- worker local ---------- */
const API="http://127.0.0.1:8765";
async function call(path,body,ms=12000){const c=new AbortController(),t=setTimeout(()=>c.abort(),ms);
try{const r=await fetch(API+path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:c.signal}:{signal:c.signal});return await r.json()}catch{return null}finally{clearTimeout(t)}}
const setPill=(id,s,t)=>{const e=$(id);e.className="pill "+s;e.lastChild.textContent=t};
const GO_TXT="Procesar y publicar todo ⚡";
function setBusy(b){["start","start-up","dock-go"].forEach(i=>$(i).disabled=b);$("start-up").textContent=b?"Procesando…":GO_TXT;$("dock-go").textContent=b?"Procesando…":GO_TXT;$("start").textContent=b?"Procesando…":"Solo editar (sin subir) ▶";
$("sum-7").textContent=b?"En marcha: no hace falta tocar nada":"Todo automático"}
/* Cuenta regresiva grande hasta el próximo Short de cada piloto (se cuenta desde que termina la subida) */
const CD={list:[],off:0,t:null};
function cdFmt(s){s=Math.max(0,Math.round(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60,p=n=>String(n).padStart(2,"0");return (h?h+":"+p(m):p(m))+":"+p(x)}
function cdSet(l,ahora){CD.list=l||[];CD.off=ahora?(Date.now()/1000-ahora):0;cdDraw();if(!CD.t)CD.t=setInterval(cdDraw,1000)}
function cdDraw(){const w=$("cdwrap");if(!w)return;const now=Date.now()/1000-CD.off;
w.innerHTML=CD.list.map(p=>{let big,sub,cl="cd";
if(p.cupo){big="✔";sub="Cupo de hoy completo ("+p.hecho+"/"+p.tope+")";cl+=" done"}
else if(p.enCurso){big="⏳";sub="Procesando y subiendo… el intervalo empieza al terminar";cl+=" busy"}
else if(p.turno&&(!p.proximo||p.proximo<=now)){big="⏸";sub="Esperando su turno: otro piloto está subiendo";cl+=" busy"}
else if(!p.proximo){big="00:00";sub="Buscando el próximo video…"}
else{const f=p.proximo-now;if(f<=0){big="00:00";sub="Buscando el próximo video…"}else{big=cdFmt(f);sub="Próximo Short · cada "+fmtDur(p.gap)+" · "+p.hecho+"/"+p.tope+" hoy"}}
return `<div class="${cl}"><small>${p.nombre}</small><strong>${big}</strong><span>${sub}</span></div>`}).join("")}
async function poll(){
if(!document.hidden){const s=await call("/status");
if(!s){W.fallos=(W.fallos||0)+1;if(W.fallos<3){setTimeout(poll,2500);return}W.worker=false;W.yt=false;W.running=false;setPill("p-worker","","Worker apagado");setPill("p-yt","","Canal sin conectar");setBusy(false);$("dock-msg").textContent="Worker apagado: ejecutá 2-INSTALAR-Y-EJECUTAR.bat"}
else{W.fallos=0;W.worker=true;W.yt=!!s.youtube;W.running=s.running;setPill("p-worker","ok","Worker conectado");
setPill("p-yt",s.youtube?"ok":"",s.youtube?"Canal conectado":"Canal sin conectar");$("p-yt").style.display=DSTP==="yt"?"":"none";
$("yt-detail").textContent=(s.youtube||DSTP!=="yt")?"":(s.detail||"");pubRender(s.items||[]);cdSet(s.proximos||[],s.ahora);if(s.ia)iaTxt(s.ia);$("log").textContent=s.log.length?s.log.join("\n"):"Sin actividad todavía.";$("log").scrollTop=1e9;setBusy(s.running);
const act=(s.items||[]).find(i=>["processing","uploading"].includes(i.status));
$("dock-msg").textContent=s.running?(act?`${act.stage||"Procesando"} · ${Math.round(act.pct||0)} %${act.title?" · "+act.title:""}`:"Procesando…"):((s.youtube||DSTP!=="yt")?"Listo para procesar":"Falta conectar el canal (paso 1)")}
sums()}
setTimeout(poll,W.running?1500:6000)}
const note=(t,err)=>{const m=$("ctl-msg");m.textContent=t;m.className="msg"+(err?" err":"")};
$("connect").onclick=async()=>{const r=await call("/connect",{});if(!r)return note("No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.",1),$("yt-detail").textContent="No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";
$("yt-detail").textContent=r.message||"Iniciá sesión en YouTube en el Chrome que se abrió.";poll()};
const go=async upload=>{if(!q.length){openStep(2,true);return note("La cola está vacía: agregá links primero.",1)}
const r=await call("/start",{config:cfg,items:q,upload,mode:cfg.publish==="schedule"?"schedule":"now",reedit:$("reedit").checked});if(!r)return note("No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.",1);
note(r.message,!r.ok);if(r.ok){q.forEach(x=>delete x.nuevo);try{localStorage.setItem(K,JSON.stringify(q))}catch{}openStep(7,true)}poll()};
$("start").onclick=()=>go(false);$("start-up").onclick=()=>go(true);$("dock-go").onclick=()=>go(true);
poll();

const ST={pending:"En espera",processing:"En proceso",ready:"Editado, listo para subir",uploading:"Subiendo a YouTube",scheduled:"Programado en YouTube",published:"Publicado",error:"Error",cancelled:"Cancelado"};
const BUSY=["pending","processing","uploading"];
function quitarCancelados(items){const c=new Set(items.filter(x=>x.status==="cancelled").map(x=>String(x.key||"").split("#")[0]));
if(!c.size)return;const n=q.length;q=q.filter(x=>!c.has(x.key));if(q.length!==n)save()}
function extrasTxt(x){const e=x.extras;if(!e)return"";const n={fb:"Facebook",tt:"TikTok"};
return Object.keys(e).map(k=>`<small class="${e[k].ok?"pgt":"err"}">${e[k].ok?"✓":"⚠"} ${n[k]||k}: ${esc(e[k].msg||"")}</small>`).join("")}
function pubRender(items){W.items=items;quitarCancelados(items);const el=$("pub");$("s-pub").textContent=items.filter(x=>x.status==="published"||x.status==="scheduled").length;
const nb=items.filter(x=>BUSY.includes(x.status)).length,nd=items.filter(x=>x.status==="published").length;
$("sum-8").textContent=items.length?`${items.length} videos · ${nd} publicados${nb?" · "+nb+" en curso":""}`:"Estado de cada video";
if(!items.length){el.innerHTML='<div class="empty">Todavía no hay videos procesados.</div>';return}
el.innerHTML=items.map(x=>{const st=x.status||"",pct=["ready","scheduled","published"].includes(st)?100:Math.max(0,Math.min(100,Math.round(x.pct||0)));
const label=(x.stage&&BUSY.includes(st)?x.stage:ST[st]||st)+" · "+(x.est?"~":"")+pct+" %";
const k=esc(x.key||"");
const acts=[x.hasfile?`<button class="btn ghost sm" data-act="prev" data-k="${k}">▶ Ver</button>`:"",
st==="ready"?`<button class="btn pri sm" data-act="now" data-k="${k}">Subir ahora ⚡</button><button class="btn ghost sm" data-act="sched" data-k="${k}">Programar</button>`:"",
BUSY.includes(st)?`<button class="btn ghost sm danger" data-act="cancel" data-k="${k}">Cancelar</button>`:"",
x.error?`<button class="btn ghost sm" data-act="diag" data-k="${k}">Ver diagnóstico</button>`:""].join("");
const link=x.yt_url?`<a class="yl" href="${esc(x.yt_url)}" target="_blank" rel="noopener">Ver en YouTube ↗</a>`:"";
return `<div class="pc">${x.type==="video"&&(x.thumb||(x.origen!=="tiktok"&&x.origen!=="facebook"))?`<img loading="lazy" src="${esc(x.thumb||"https://i.ytimg.com/vi/"+(x.id||"")+"/mqdefault.jpg")}" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">`:""}<div><b>${esc(x.ia_title||x.title||x.url||"")}</b><span class="st ${esc(st)}">${ST[st]||esc(st)}</span><small>${x.kind==="short"?"Short":"Video"}${x.parts>1?" · Parte "+x.part+"/"+x.parts:""}${x.reanudar&&x.status==="ready"?" · se reanuda sola":""}${x.publishAt?" · "+new Date(x.publishAt).toLocaleString("es",{dateStyle:"medium",timeStyle:"short"}):""}</small>
<div style="height:10px;border-radius:99px;background:var(--bd);overflow:hidden;margin:10px 0 4px"><span style="display:block;height:100%;width:${pct}%;min-width:${pct?4:0}px;border-radius:99px;background:${["error","cancelled"].includes(st)?"#8a5a66":BUSY.includes(st)?"#5b86ff":"#45c79b"}"></span></div><small class="pgt">${label}</small>${x.ia?`<small class="pgt">Ayuda IA: ${esc(x.ia)}</small>`:""}${link}${extrasTxt(x)}${x.aviso?`<small class="err">⚠ ${esc(x.aviso)}</small>`:""}${x.error?`<small class="err">${esc(x.error)}</small>`:""}${acts?`<div class="acts">${acts}</div>`:""}</div></div>`}).join("")}
$("pub").onclick=async e=>{const b=e.target.closest("[data-act]");if(!b)return;const k=b.dataset.k,a=b.dataset.act;
if(a==="prev"){const it=W.items.find(y=>y.key===k)||{},id=it.fid||k.split(":")[1].split("#")[0];openWin("Vista previa del video editado",`<video controls autoplay playsinline style="width:100%;max-height:70vh;border-radius:10px;background:#000" src="${API}/media/${encodeURIComponent(id)}_final.mp4"></video><p class="sub">Es el archivo ya editado, tal como se va a subir.</p>`);return}
if(a==="diag"){verDiag();return}
if(a==="cancel"){q=q.filter(x=>x.key!==k.split("#")[0]);save();const r=await call("/cancel",{key:k});note(r?r.message:"No encuentro el worker.",!r);poll();return}
const r=await call("/upload",{key:k,mode:a==="now"?"now":"schedule",config:cfg});note(r?r.message:"No encuentro el worker.",!r||!r.ok);poll()};

/* ---------- IA ---------- */
const iaTxt=s=>{["gemini","groq","claude"].forEach(p=>{$("ia-"+p).textContent=s[p]?(p==="gemini"&&s.gemini_n>1?s.gemini_n+" claves ✓ ("+s.gemini_libres+" con cuota)":"clave guardada ✓"):"sin clave"});
if(s.modelo_gemini!==undefined&&document.activeElement!==$("k-modelo"))$("k-modelo").value=s.modelo_gemini||"";
const m=s.modelo_usado||{};if(m.gemini)$("ia-gemini").textContent="clave guardada ✓ · modelo "+m.gemini;
$("ia-est").textContent=(s.gemini||s.groq||s.claude)?(s.ultimo?"Última ayuda: "+s.ultimo+".":"Listas."):"Todavía no hay claves."};
document.querySelectorAll("[data-ia]").forEach(b=>b.onclick=async()=>{const p=b.dataset.ia,a=b.dataset.a,m=$("ia-msg");m.className="msg";m.textContent="";
if(a==="save"){const v=$("k-"+p).value.trim();if(!v){m.textContent="Pegá la clave primero.";return}const r=await call("/ia",{[p]:v});$("k-"+p).value="";m.textContent=r?r.message:"No encuentro el worker.";if(r&&r.ia)iaTxt(r.ia)}
if(a==="model"){const r=await call("/ia",{modelo_gemini:$("k-modelo").value.trim()});m.textContent=r?(r.ok===false?r.message:"Modelo guardado."):"No encuentro el worker.";if(r&&r.ia)iaTxt(r.ia)}
if(a==="del"){const r=await call("/ia",{borrar:p});m.textContent=r?"Clave borrada.":"No encuentro el worker.";if(r&&r.ia)iaTxt(r.ia)}
if(a==="test"){m.textContent="Probando…";const r=await call("/ia-test",{proveedor:p},90000);m.textContent=r?r.message:"No encuentro el worker.";m.className="msg"+(r&&r.ok?"":" err")}});
$("cancel-all").onclick=async()=>{if(!confirm("¿Cancelar todo lo que está en proceso?"))return;const busy=W.items.filter(x=>BUSY.includes(x.status)).map(x=>String(x.key||"").split("#")[0]);q=q.filter(x=>!busy.includes(x.key));save();const r=await call("/cancel",{all:true});note(r?r.message:"No encuentro el worker.",!r);poll()};
document.querySelectorAll(".js-upall").forEach(b=>b.onclick=async()=>{const r=await call("/upload",{key:"ALL",mode:"now",config:cfg});note(r?r.message:"No encuentro el worker.",!r||!r.ok);poll()});
$("force").onclick=async()=>{const r=await call("/forzar",{});$("yt-detail").textContent=r?r.message:"No encuentro el worker.";poll()};

async function verDiag(){const r=await call("/diagnostico");
if(!r)return openWin("Diagnóstico",'<p>No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.</p>');
openWin("Diagnóstico de la última subida",`<p class="sub">Carpeta: <code>${esc(r.carpeta||"")}</code></p><div class="row"><button class="btn pri sm" id="diag-copy" type="button">Copiar todo</button></div><pre class="log" id="diag-txt" style="height:240px;margin-top:10px">${esc(r.text||"")}</pre>${r.png?`<img src="${API}/diag.png?t=${Date.now()}" alt="Captura del error" style="margin-top:12px">`:""}`);
const c=$("diag-copy");if(c)c.onclick=async()=>{const t=$("diag-txt").textContent;try{await navigator.clipboard.writeText(t)}catch{const a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();document.execCommand("copy");a.remove()}c.textContent="¡Copiado!"}}
$("diag-btn").onclick=verDiag;

/* ---------- piloto automático ---------- */
const PL_K="yutu-piloto",pl=Object.assign({tema:"",shorts:10,videos:3,dias:30,cada:0},load(PL_K,{}));
const plIds={tema:"pl-tema",shorts:"pl-shorts",videos:"pl-videos",dias:"pl-dias"};
for(const k in plIds){const el=$(plIds[k]);el.value=pl[k];el.oninput=()=>{pl[k]=el.type==="number"?Math.max(0,+el.value||0):el.value;try{localStorage.setItem(PL_K,JSON.stringify(pl))}catch{}}}
const plSend=async activo=>{const m=$("pl-msg");if(activo&&!pl.tema.trim()){m.textContent="Escribí un tema central.";m.className="msg err";return}
const r=await call("/piloto",{...pl,activo,config:cfg},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";plPoll()};
$("pl-on").onclick=()=>plSend(true);$("pl-off").onclick=()=>plSend(false);
async function plPoll(){if(document.hidden)return;const s=await call("/status");if(!s||!s.piloto)return;const p=s.piloto;
$("pl-estado").textContent=(p.activo?"🟢 Activo · ":"⏸ En pausa · ")+(p.estado||"Esperando el primer ciclo (hasta 1 min).")+(p.hist&&p.hist.length?" · Último: "+p.hist[p.hist.length-1].t.slice(0,60):"")}
setInterval(plPoll,8000);plPoll();

/* ---------- piloto TikTok ---------- */
const TT_K="yutu-tiktok",tt=Object.assign({cuenta:"",orden:"seguidilla",por_dia:5,dias:30,verificar:true},load(TT_K,{}));
const ttIds={cuenta:"tt-cuenta",orden:"tt-orden",por_dia:"tt-dia",dias:"tt-dias"};
for(const k in ttIds){const el=$(ttIds[k]);el.value=tt[k];el.oninput=()=>{tt[k]=el.type==="number"?Math.max(0,+el.value||0):el.value;try{localStorage.setItem(TT_K,JSON.stringify(tt))}catch{}}}
$("tt-ver").checked=!!tt.verificar;$("tt-ver").onchange=e=>{tt.verificar=e.target.checked;try{localStorage.setItem(TT_K,JSON.stringify(tt))}catch{}};
const ttSend=async activo=>{const m=$("tt-msg");if(activo&&!tt.cuenta.trim()){m.textContent="Escribí la cuenta de TikTok.";m.className="msg err";return}
const r=await call("/piloto-tiktok",{...tt,activo,config:cfg},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";ttPoll()};
$("tt-on").onclick=()=>ttSend(true);$("tt-off").onclick=()=>ttSend(false);
async function ttPoll(){if(document.hidden)return;const s=await call("/status");if(!s||!s.tiktok||!s.tiktok.cuenta)return;const p=s.tiktok;
$("tt-estado").textContent=(p.activo?"🟢 Activo · ":"⏸ En pausa · ")+p.cuenta+" · "+(p.estado||"Esperando el primer ciclo (hasta 1 min).")}
setInterval(ttPoll,8000);ttPoll();

/* ---------- piloto TikTok por tema ---------- */
const TM_K="yutu-tema-tt",tm=Object.assign({tema:"",shorts:10,videos:3,dias:30},load(TM_K,{}));
const tmIds={tema:"tm-tema",shorts:"tm-shorts",videos:"tm-videos",dias:"tm-dias"};
for(const k in tmIds){const el=$(tmIds[k]);el.value=tm[k];el.oninput=()=>{tm[k]=el.type==="number"?Math.max(0,+el.value||0):el.value;try{localStorage.setItem(TM_K,JSON.stringify(tm))}catch{}}}
const tmSend=async activo=>{const m=$("tm-msg");if(activo&&!tm.tema.trim()){m.textContent="Escribí el tema central.";m.className="msg err";return}
const r=await call("/piloto-tema-tiktok",{...tm,activo,config:cfg},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";tmPoll()};
$("tm-on").onclick=()=>tmSend(true);$("tm-off").onclick=()=>tmSend(false);
async function tmPoll(){if(document.hidden)return;const s=await call("/status");if(!s||!s.tema_tt||!s.tema_tt.tema)return;const p=s.tema_tt;
$("tm-estado").textContent=(p.activo?"🟢 Activo · ":"⏸ En pausa · ")+(p.estado||"Esperando el primer ciclo (hasta 1 min).")+(p.fuentes?" · "+p.fuentes.length+" fuentes encontradas":"")}
setInterval(tmPoll,8000);tmPoll();


/* ---------- aprendizaje de títulos ---------- */
async function apLoad(){const r=await call("/aprender",{accion:"listar"},8000);if(!r||!r.ok)return;const l=r.lecciones||[];$("ap-n").textContent=l.length?"· "+l.length+" lección"+(l.length>1?"es":"")+" tuya"+(l.length>1?"s":""):"";
$("ap-list").innerHTML=l.map(x=>`<div class="apit"><span>${esc(x.t).replace(/\n/g,"<br>")}<small>${esc(x.f||"")}</small></span><button type="button" class="btn ghost sm" data-ap="${x.i}" title="Olvidar esta lección">✕</button></div>`).join("")}
$("ap-add").onclick=async()=>{const m=$("ap-msg"),t=$("ap-txt").value.trim();if(!t){m.textContent="Escribí algo para enseñarle.";m.className="msg err";return}
const r=await call("/aprender",{accion:"agregar",texto:t},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?(r.ok?"Aprendido ✓ Ya lo aplica en los próximos títulos.":r.message):"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";if(r&&r.ok){$("ap-txt").value="";apLoad()}};
$("ap-list").onclick=async e=>{const b=e.target.closest("[data-ap]");if(!b)return;await call("/aprender",{accion:"borrar",i:+b.dataset.ap},8000);apLoad()};
$("ap-ev").onclick=async()=>{const t=$("ap-test").value.trim(),o=$("ap-res");if(!t)return;const r=await call("/aprender",{accion:"evaluar",titulo:t},8000);
o.textContent=r&&r.ok?`${r.aprobado?"✅":"⚠"} ${r.puntaje}/100 `+(r.problemas.length?"· "+r.problemas.join("; "):"· claro, específico y con gancho"):"No encuentro el worker."};
apLoad();

/* ---------- dónde se publican los videos ---------- */
const DST={plataforma:"yt",fb_page:""};let dstOk=false;const DST_N={yt:"YouTube",fb:"Facebook",tt:"TikTok"};
function dstDraw(){["yt","fb","tt"].forEach(k=>{$("dest-"+k).checked=DST.plataforma===k;$("dd-"+k).classList.toggle("on",DST.plataforma===k)});
$("dfb-login").parentElement.style.display=DST.plataforma==="fb"?"":"none";$("dtt-login").parentElement.style.display=DST.plataforma==="tt"?"":"none";
const sm=$("sum-6");if(sm)sm.dataset.d=DST_N[DST.plataforma];
DSTP=DST.plataforma;const yb=$("yt-block"),sk=$("yt-skip"),pe=$("p-yt"),yes=DST.plataforma==="yt";if(yb)yb.style.display=yes?"":"none";if(sk){sk.style.display=yes?"none":"";$("yt-skip-n").textContent=DST_N[DST.plataforma]}if(pe)pe.style.display=yes?"":"none";const yn=$("yt-need");if(yn)yn.style.display=yes?"":"none";sums()}
async function dstSave(){const m=$("dest-msg");const r=await call("/destinos",DST,8000);m.className="sub"+(r&&r.ok?"":" err");m.textContent=r?(r.ok?"Guardado: todos los videos se subirán solo a "+DST_N[DST.plataforma]+".":r.message):"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat."}
["yt","fb","tt"].forEach(k=>{$("dest-"+k).onchange=e=>{if(e.target.checked){DST.plataforma=k;dstDraw();dstSave()}}});
async function dstLoad(){if(dstOk)return;const s=await call("/status");if(s&&s.destinos){Object.assign(DST,s.destinos);dstOk=true;dstDraw()}}
dstDraw();dstLoad();setInterval(dstLoad,5000);

/* ---------- piloto Facebook (reels) ---------- */
const FB_K="yutu-piloto-fb",fbo=Object.assign({modo:"tema",tema:"",cuenta:"",shorts:10,videos:0,dias:30},load(FB_K,{}));
const fbSave=()=>{try{localStorage.setItem(FB_K,JSON.stringify(fbo))}catch{}};
const fbFuente=()=>{const c=fbo.modo==="cuenta";$("fb-fuente").value=c?fbo.cuenta:fbo.tema;$("fb-fuente").placeholder=c?"Pegá el enlace de la página de Facebook · ej: https://www.facebook.com/nombrepagina":"Tema central · ej: Mobile Legends"};
$("fb-modo").value=fbo.modo;fbFuente();
$("fb-modo").onchange=()=>{fbo.modo=$("fb-modo").value;fbSave();fbFuente()};
$("fb-fuente").oninput=e=>{fbo[fbo.modo==="cuenta"?"cuenta":"tema"]=e.target.value;fbSave()};
for(const k of["shorts","videos","dias"]){const el=$("fb-"+k);el.value=fbo[k];el.oninput=()=>{fbo[k]=Math.max(0,+el.value||0);fbSave()}}
const fbSend=async activo=>{const m=$("fb-msg"),c=fbo.modo==="cuenta";if(activo&&!(c?fbo.cuenta:fbo.tema).trim()){m.textContent=c?"Pegá el enlace de la página de Facebook.":"Escribí el tema central.";m.className="msg err";return}
const r=await call("/piloto-facebook",{...fbo,activo,config:cfg},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";fbPoll()};
$("fb-on").onclick=()=>fbSend(true);$("fb-off").onclick=()=>fbSend(false);
async function fbPoll(){if(document.hidden)return;const s=await call("/status");if(!s||!s.facebook||!(s.facebook.tema||s.facebook.cuenta))return;const p=s.facebook;
$("fb-estado").textContent=(p.activo?"🟢 Activo · ":"⏸ En pausa · ")+(p.estado||"Esperando el primer ciclo (hasta 1 min).")}
setInterval(fbPoll,8000);fbPoll();

/* ---------- piloto creador IA ---------- */
const PI_K="yutu-piloto-ia",IDI={"es-MX":"Español latino (México)","es-AR":"Español latino (Argentina)","es-CO":"Español latino (Colombia)","es-US":"Español latino (EE. UU.)","es-ES":"Español (España)","en-US":"Inglés","pt-BR":"Portugués (Brasil)","fr-FR":"Francés","de-DE":"Alemán","it-IT":"Italiano"};
const pi=Object.assign({tema:"",shorts:5,dias:30,duracion:45,voz:"alternar",estilo:"",idiomas:["es-MX"]},load(PI_K,{}));if(!Array.isArray(pi.idiomas)||!pi.idiomas.length)pi.idiomas=["es-MX"];
const piSave=()=>{try{localStorage.setItem(PI_K,JSON.stringify(pi))}catch{}};
const piIds={tema:"pi-tema",shorts:"pi-shorts",dias:"pi-dias",voz:"pi-voz",estilo:"pi-estilo"};
for(const k in piIds){const el=$(piIds[k]);el.value=pi[k];el.oninput=()=>{pi[k]=el.type==="number"?Math.max(0,+el.value||0):el.value;piSave()}}
function piChips(){$("pi-idiomas").innerHTML=Object.keys(IDI).map(k=>`<label class="fxc${pi.idiomas.includes(k)?" on":""}"><input type="checkbox" data-pi="${k}" ${pi.idiomas.includes(k)?"checked":""}><span>${IDI[k]}</span></label>`).join("")}
$("pi-idiomas").onchange=e=>{const k=e.target.dataset.pi;if(!k)return;pi.idiomas=pi.idiomas.filter(x=>x!==k);if(e.target.checked)pi.idiomas.push(k);if(!pi.idiomas.length)pi.idiomas=["es-MX"];piSave();piChips()};piChips();
const piSend=async activo=>{const m=$("pi-msg");if(activo&&!pi.tema.trim()){m.textContent="Escribí el tema central.";m.className="msg err";return}
const r=await call("/piloto-ia",{...pi,activo,config:cfg},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";piPoll()};
$("pi-on").onclick=()=>piSend(true);$("pi-off").onclick=()=>piSend(false);
async function piPoll(){if(document.hidden)return;const s=await call("/status");if(!s||!s.piloto_ia||!s.piloto_ia.tema)return;const p=s.piloto_ia;
$("pi-estado").textContent=(p.activo?"🟢 Activo · ":"⏸ En pausa · ")+(p.estado||"Esperando el primer ciclo (hasta 1 min).")}
setInterval(piPoll,8000);piPoll();


/* ---------- piloto de Shorts de YouTube ---------- */
const YS_K="yutu-piloto-yts",ys=Object.assign({tema:"",por_dia:5,dias:30,cada:0},load(YS_K,{}));
const ysSave=()=>{try{localStorage.setItem(YS_K,JSON.stringify(ys))}catch{}};
const ysIds={tema:"ys-tema",por_dia:"ys-dia",dias:"ys-dias"};
for(const k in ysIds){const el=$(ysIds[k]);el.value=ys[k];el.oninput=()=>{ys[k]=el.type==="number"?Math.max(0,+el.value||0):el.value;ysSave()}}
const ysSend=async activo=>{const m=$("ys-msg");if(activo&&!ys.tema.trim()){m.textContent="Escribí el tema central.";m.className="msg err";return}
const r=await call("/piloto-yts",{...ys,activo,config:cfg},8000);m.className="msg"+(r&&r.ok?"":" err");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";tabsPoll()};
$("ys-on").onclick=()=>ysSend(true);$("ys-off").onclick=()=>ysSend(false);

/* ---------- "cada cuánto" en TODOS los pilotos (0 = automático: reparte el cupo del día) ---------- */
function cadaCtl(secId,obj,saveFn){const cfgDiv=document.querySelector("#"+secId+" .cfg");if(!cfgDiv)return;
const min=+obj.cada||0,hrs=min>=60&&min%60===0;
const lab=document.createElement("label");lab.className="wide";lab.innerHTML='Subir uno nuevo cada<span class="two"><input type="number" min="0" step="1" placeholder="Auto"><select><option value="m">minutos</option><option value="h">horas</option></select></span>';
cfgDiv.appendChild(lab);const n=lab.querySelector("input"),u=lab.querySelector("select");u.value=hrs?"h":"m";n.value=min?(hrs?min/60:min):"";
const upd=()=>{const v=Math.max(0,+n.value||0);obj.cada=Math.round(v*(u.value==="h"?60:1));saveFn()};n.oninput=upd;u.onchange=upd}
cadaCtl("yts",ys,ysSave);cadaCtl("piloto",pl,()=>{try{localStorage.setItem(PL_K,JSON.stringify(pl))}catch{}});
cadaCtl("tiktok",tt,()=>{try{localStorage.setItem(TT_K,JSON.stringify(tt))}catch{}});
cadaCtl("tema-tt",tm,()=>{try{localStorage.setItem(TM_K,JSON.stringify(tm))}catch{}});
cadaCtl("pia",pi,piSave);cadaCtl("fb",fbo,fbSave);
/* elegir por popularidad: más vistas / likes / comentarios / compartidos / recientes */
function rankCtl(secId,obj,saveFn){const cfgDiv=document.querySelector("#"+secId+" .cfg");if(!cfgDiv)return;
const lab=document.createElement("label");lab.className="wide";
lab.innerHTML='Elegir los videos por<select><option value="mejores">⭐ Los mejores (relevancia, comentarios y visitas)</option><option value="auto">Automático (variados)</option><option value="vistas">👁 Más vistas</option><option value="likes">👍 Más likes</option><option value="comentarios">💬 Más comentarios</option><option value="compartidos">🔁 Más compartidos</option><option value="recientes">🆕 Más recientes</option></select><small class="sub">Toma siempre el mejor que todavía no se usó. Para likes, comentarios y compartidos consulta los datos de los mejores candidatos (tarda unos segundos más).</small>';
cfgDiv.appendChild(lab);const sel=lab.querySelector("select");sel.value=obj.ranking||(secId==="yts"?"mejores":"auto");sel.onchange=()=>{obj.ranking=sel.value;saveFn()}}
rankCtl("yts",ys,ysSave);rankCtl("tiktok",tt,()=>{try{localStorage.setItem(TT_K,JSON.stringify(tt))}catch{}});rankCtl("tema-tt",tm,()=>{try{localStorage.setItem(TM_K,JSON.stringify(tm))}catch{}});rankCtl("fb",fbo,fbSave);

/* ---------- pestañas ---------- */
const PT=["yts","piloto","tiktok","tema-tt","fb","pia"];let ptSel=load("yutu-ptab","yts");
function showTab(p){ptSel=PT.includes(p)?p:"yts";try{localStorage.setItem("yutu-ptab",JSON.stringify(ptSel))}catch{}
PT.forEach(k=>{$(k).classList.toggle("phid",k!==ptSel)});document.querySelectorAll("#ptabs button").forEach(b=>b.classList.toggle("on",b.dataset.p===ptSel))}
document.querySelectorAll("#ptabs button").forEach(b=>b.onclick=()=>showTab(b.dataset.p));showTab(ptSel);
async function tabsPoll(){const s=await call("/status");if(!s)return;
const on={yts:s.piloto_yts,piloto:s.piloto,tiktok:s.tiktok,"tema-tt":s.tema_tt,fb:s.facebook,pia:s.piloto_ia};
PT.forEach(k=>{const d=$("d-"+k);if(d)d.classList.toggle("act",!!(on[k]&&on[k].activo))});
const e=s.piloto_yts;if(e&&e.tema)$("ys-estado").textContent=(e.activo?"🟢 Activo · ":"⏸ En pausa · ")+(e.estado||"Buscando el primer Short…")}
setInterval(()=>{if(!document.hidden)tabsPoll()},8000);tabsPoll();


/* ---------- duraciones: se escriben en MINUTOS (se puede cambiar a segundos). Se guardan en segundos ---------- */
const unitGet=id=>{try{return localStorage.getItem("yutu-u-"+id)||"m"}catch{return"m"}};
const unitSet=(id,u)=>{try{localStorage.setItem("yutu-u-"+id,u)}catch{}};
const secShow=(sec,u)=>{sec=+sec||0;return sec?String(+(u==="m"?sec/60:sec).toFixed(2)):""};
const secRead=(v,u)=>{const n=Math.max(0,parseFloat(String(v).replace(",","."))||0);return Math.round(n*(u==="m"?60:1))};
function unitCtl(id,getSec,setSec,maxSec){const el=$("u-"+id),us=$("us-"+id);if(!el||!us)return;
us.value=unitGet(id);el.value=secShow(getSec(),us.value);
el.oninput=()=>{let v=secRead(el.value,us.value);if(maxSec&&v>maxSec){v=maxSec;el.value=secShow(v,us.value)}setSec(v)};
us.onchange=()=>{unitSet(id,us.value);el.value=secShow(getSec(),us.value)}}
unitCtl("short_len",()=>cfg.short_len,v=>{cfg.short_len=v||60;saveCfg();render()},180);
unitCtl("vid_start",()=>cfg.vid_start,v=>{cfg.vid_start=v;saveCfg();render()},86400);
unitCtl("cut_start",()=>cfg.cut_start,v=>{cfg.cut_start=v;saveCfg();render()},86400);
unitCtl("pi-dur",()=>pi.duracion,v=>{pi.duracion=Math.max(20,v||45);piSave()},180);

/* ---------- límite de duración (mínimo / máximo) de los videos que busca cada piloto ---------- */
function rangoCtl(secId,obj,saveFn){const cfgDiv=document.querySelector("#"+secId+" .cfg");if(!cfgDiv)return;
const box=document.createElement("div");box.className="durbox";
box.innerHTML='<div class="dh"><b>⏱ Duración de los videos que busca</b><span class="seg"><button type="button" data-u="m">Minutos</button><button type="button" data-u="s">Segundos</button></span></div>'+
'<label>Mínimo<span class="fin"><input type="number" min="0" step="any" placeholder="sin límite" data-r="dmin"><em></em></span></label>'+
'<label>Máximo<span class="fin"><input type="number" min="0" step="any" placeholder="sin límite" data-r="dmax"><em></em></span></label>'+
'<p class="sumr"></p>';
cfgDiv.appendChild(box);let u=obj.dunit==="s"?"s":"m";const ins=[...box.querySelectorAll("input")],ems=[...box.querySelectorAll("em")],sum=box.querySelector(".sumr");
const fm=sec=>sec>=60?+(sec/60).toFixed(2)+" min":sec+" s";
const paint=()=>{ins.forEach(el=>el.value=secShow(obj[el.dataset.r],u));ems.forEach(e=>e.textContent=u==="m"?"min":"seg");
box.querySelectorAll(".seg button").forEach(b=>b.classList.toggle("on",b.dataset.u===u));
const lo=+obj.dmin||0,hi=+obj.dmax||0;sum.textContent=lo&&hi?`Buscará videos de ${fm(lo)} a ${fm(hi)}.`:lo?`Buscará videos de al menos ${fm(lo)} (sin máximo).`:hi?`Buscará videos de hasta ${fm(hi)} (sin mínimo).`:"Sin límite de duración. Ej.: 1 a 10 minutos (admite decimales: 0,5 = 30 s)."};
paint();
ins.forEach(el=>el.oninput=()=>{obj[el.dataset.r]=secRead(el.value,u);saveFn();sum.textContent="";paintSum()});
const paintSum=()=>{const lo=+obj.dmin||0,hi=+obj.dmax||0;sum.textContent=lo&&hi?`Buscará videos de ${fm(lo)} a ${fm(hi)}.`:lo?`Buscará videos de al menos ${fm(lo)} (sin máximo).`:hi?`Buscará videos de hasta ${fm(hi)} (sin mínimo).`:"Sin límite de duración."};
box.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{u=b.dataset.u;obj.dunit=u;saveFn();paint()})}
rangoCtl("yts",ys,ysSave);rangoCtl("piloto",pl,()=>{try{localStorage.setItem(PL_K,JSON.stringify(pl))}catch{}});
rangoCtl("tiktok",tt,()=>{try{localStorage.setItem(TT_K,JSON.stringify(tt))}catch{}});rangoCtl("tema-tt",tm,()=>{try{localStorage.setItem(TM_K,JSON.stringify(tm))}catch{}});rangoCtl("fb",fbo,fbSave);

/* ---------- sesión de TikTok (en el Chrome del worker) ---------- */
function ttLogin(pre,ep="/tiktok-login",red="TikTok"){const m=$(pre+"-lmsg");if(!m)return;
$(pre+"-login").onclick=async()=>{m.textContent="Abriendo "+red+"…";const r=await call(ep,{accion:"abrir"},15000);m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat."};
$(pre+"-chk").onclick=async()=>{m.textContent="Comprobando…";const r=await call(ep,{accion:"comprobar"},40000);m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat."}}
ttLogin("tt");ttLogin("tm");ttLogin("fb","/facebook-login","Facebook");ttLogin("dfb","/facebook-login","Facebook");ttLogin("dtt","/tiktok-login","TikTok");


/* ---------- vaciar rastros ---------- */
$("clean").onclick=()=>{openWin("🧹 Vaciar rastros",`<p class="sub">Elegí qué borrar. Lo que está en proceso no se toca, y tu sesión de YouTube/TikTok se conserva.</p>
<div class="cfg" style="margin-top:12px">
<label class="chk"><input type="checkbox" data-e="cancelled" checked> Publicaciones canceladas</label>
<label class="chk"><input type="checkbox" data-e="error" checked> Publicaciones con error</label>
<label class="chk"><input type="checkbox" data-e="published,scheduled" checked> Ya publicadas o programadas (siguen en YouTube; solo se quitan de esta lista)</label>
<label class="chk"><input type="checkbox" data-e="pending"> En espera</label>
<label class="chk"><input type="checkbox" data-e="ready"> Editadas y listas para subir (se pierde el video editado)</label>
<hr style="border:0;border-top:1px solid var(--line);width:100%">
<label class="chk"><input id="cl-arch" type="checkbox" checked> Borrar los videos descargados y archivos temporales de esta PC</label>
<label class="chk"><input id="cl-rast" type="checkbox" checked> Borrar registros, diagnósticos y la caché del navegador oculto de TikTok</label>
<label class="chk"><input id="cl-pil" type="checkbox"> Borrar la memoria de los pilotos (lo ya usado y rechazado): podrían volver a elegir videos repetidos</label>
<label class="chk"><input id="cl-web" type="checkbox"> Vaciar también la lista de enlaces del paso 2</label>
<div class="row"><button class="btn pri" id="cl-go" type="button">🧹 Vaciar ahora</button><span id="cl-msg" class="msg"></span></div></div>`);
$("cl-go").onclick=async()=>{if(!confirm("¿Vaciar lo elegido? No se puede deshacer."))return;const m=$("cl-msg");m.className="msg";m.textContent="Vaciando…";
const est=[...document.querySelectorAll("#win-body [data-e]")].filter(x=>x.checked).flatMap(x=>x.dataset.e.split(","));
const r=await call("/limpiar",{estados:est,archivos:$("cl-arch").checked,rastros:$("cl-rast").checked,pilotos:$("cl-pil").checked},60000);
if($("cl-web").checked){q=[];save();render()}
m.className="msg"+(!r||!r.ok?" err":"");m.textContent=r?r.message:"No encuentro el worker. Ejecutá 2-INSTALAR-Y-EJECUTAR.bat.";poll()}};
