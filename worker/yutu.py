"""Yutu worker: descarga -> recorte -> efectos -> subtitulos -> subida a YouTube Studio (sin Google Cloud)."""
import json, math, os, re, shutil, subprocess, sys, time, pathlib, datetime as dt
import efectos, ia, voz, cdp
ROOT = pathlib.Path(__file__).parent
MEDIA = ROOT / "media"; MEDIA.mkdir(exist_ok=True)
QF = ROOT / "queue.json"; CF = ROOT / "cancel.json"
NO_UPLOAD = "--sin-subir" in sys.argv

class Cancelled(Exception): pass

D = None            # cola en memoria (para guardar el progreso)
PLAN = {}           # peso de cada etapa en el porcentaje total
_last = [0.0, -1]

def cancel_requested(it):
    try: c = json.loads(CF.read_text("utf-8"))
    except Exception: return False
    return bool(c.get("all") or it.get("key") in c.get("keys", []))

def check_cancel(it):
    if cancel_requested(it): raise Cancelled()

def ia_activa(cfg):
    return cfg.get("ia_mode", "alternar") != "apagado" and any(ia.estado()[k] for k in ("gemini", "groq", "claude"))

def make_plan(cfg, upload):
    w = {"dl": .20, "ia": .08 if (ia_activa(cfg) and cfg.get("ia_cut")) else 0,
         "sub": .20 if cfg.get("sub", True) else 0, "edit": .40, "up": .20 if upload else 0}
    tot = sum(w.values()); acc = 0; plan = {}
    for k in ("dl", "ia", "sub", "edit", "up"):
        plan[k] = (acc / tot, w[k] / tot); acc += w[k]
    return plan

LABEL = {"dl": "Descargando", "ia": "Analizando con IA", "sub": "Subtitulos", "edit": "Editando", "up": "Subiendo"}
def set_prog(it, stage, frac, force=False):
    off, wt = PLAN.get(stage, (0, 1))
    pct = int(round(100 * (off + wt * max(0.0, min(1.0, frac)))))
    it["stage"] = LABEL[stage]; it["pct"] = pct
    now = time.time()
    if force or pct != _last[1] and now - _last[0] > 0.7:
        _last[0], _last[1] = now, pct
        if D is not None: save(D)

def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if p: return p
    c = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin" / "ffmpeg.exe"
    return str(c) if c.exists() else None
FFMPEG = find_ffmpeg()

def run(*a, **k): return subprocess.run([str(x) for x in a], check=True, **k)
def ytdlp(*a, **k): return run(sys.executable, "-m", "yt_dlp", *a, **k)
def load(): return json.loads(QF.read_text("utf-8"))
def save(d):
    tmp = QF.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), "utf-8"); os.replace(tmp, QF)

def expand(d):
    out = []
    for it in d["items"]:
        if it["type"] != "playlist": out.append(it); continue
        r = ytdlp("--flat-playlist", "--print", "%(id)s", it["url"], capture_output=True, text=True)
        for vid in r.stdout.split():
            out.append({"type": "video", "id": vid, "key": "video:" + vid, "kind": it["kind"],
                        "url": "https://www.youtube.com/watch?v=" + vid, "status": "pending"})
    seen, res = set(), []
    for it in out:
        if it["key"] not in seen: seen.add(it["key"]); res.append(it)
    d["items"] = res

def download(it, src):
    cmd = [sys.executable, "-m", "yt_dlp", "--newline", "--progress-template", "download:[DL] %(progress._percent_str)s",
           "--ffmpeg-location", FFMPEG, "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
           "--merge-output-format", "mp4", "--no-playlist", "-o", str(MEDIA / f"{it['id']}.%(ext)s"), it["url"]]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    idx, last, tail = 0, 0.0, []
    for line in p.stdout:
        if cancel_requested(it): p.terminate(); raise Cancelled()
        m = re.search(r"\[DL\]\s*([\d.]+)%", line)
        if m:
            v = float(m.group(1))
            if v < last - 20: idx = 1                      # empezo el segundo flujo (audio)
            last = v
            set_prog(it, "dl", (0.85 * v / 100) if idx == 0 else 0.85 + 0.15 * v / 100)
        else: tail.append(line.strip())
    if p.wait() != 0: raise RuntimeError("yt-dlp fallo: " + " ".join(tail[-3:])[:200])
    set_prog(it, "dl", 1.0, True)

def srt_time(s):
    h, m, sec = int(s // 3600), int(s % 3600 // 60), s % 60
    return f"{h:02}:{m:02}:{sec:06.3f}".replace(".", ",")

def subtitles(it, src, start, length, cfg, short):
    """Transcribe solo el tramo elegido y arma subtitulos cortos (estilo Shorts)."""
    words = voz.palabras(FFMPEG, src, start, length, cfg.get("lang", "es"), cfg.get("model", "small"),
                         lambda f: set_prog(it, "sub", f), lambda: check_cancel(it),
                         motor=cfg.get("stt", "auto"), titulo=it.get("title", ""))
    set_prog(it, "sub", 1.0, True)
    maxw = int(cfg.get("sub_words") or (4 if short else 8))
    caps, cur = [], []
    def flush():
        if cur: caps.append((cur[0].start, cur[-1].end, "".join(w.word for w in cur).strip())); cur.clear()
    for w in words:
        if cur and (len(cur) >= maxw or w.start - cur[-1].end > 0.7 or w.end - cur[0].start > 3.5): flush()
        cur.append(w)
        if w.word.strip()[-1:] in ".?!": flush()
    flush()
    if not caps: return None
    if ia_activa(cfg) and cfg.get("ia_sub"):
        txt = [c[2] for c in caps]; mejor = txt[:]; prov = None
        for i in range(0, min(len(txt), 600), 120):                  # lotes: asi se turnan las IAs
            check_cancel(it)
            r = ia.corregir_subs(cfg.get("ia_mode", "alternar"), it.get("title", ""), txt[i:i + 120])
            if r: mejor[i:i + 120] = r["lineas"]; prov = r["prov"]
        if prov:
            caps = [(a, b, mejor[k]) for k, (a, b, _) in enumerate(caps)]; it["_sub_ia"] = prov
            print(f"  [IA {prov}] Subtitulos corregidos.")
    srt = MEDIA / (src.stem + ".srt")
    with open(srt, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(caps, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(max(b, a + 0.3))}\n{t.upper() if cfg.get('sub_caps') else t}\n\n")
    return srt

def transcribe_full(it, src, cfg, dur):
    """Transcripcion de todo el video, solo para que la IA elija el mejor tramo."""
    words = voz.palabras(FFMPEG, src, 0, dur, cfg.get("lang", "es"), "base",
                         lambda f: set_prog(it, "ia", f), lambda: check_cancel(it), motor="rapido", titulo=it.get("title", ""))
    return voz.frases(words)

def srt_text(srt):
    if not srt: return ""
    try: return " ".join(l.strip() for l in pathlib.Path(srt).read_text("utf-8").splitlines() if l.strip() and not l.strip().isdigit() and "-->" not in l)
    except Exception: return ""

def window(it, cfg, dur, ai_start=None):
    """Tramo del video original que se conserva: (inicio, duracion)."""
    f = lambda k, d=0: float(cfg.get(k) or d)
    if it["kind"] == "short":
        L = min(f("short_len", 58), 60, dur)
        mode = cfg.get("cut_mode", "auto")
        if mode == "inicio" or dur <= L: start = 0
        elif mode == "manual": start = min(f("cut_start"), dur - L)
        elif ai_start is not None: start = min(max(ai_start, 0), dur - L)
        else: start = min(dur * 0.1, dur - L)
    else:
        start = min(max(f("vid_start"), 0), max(dur - 1, 0)) if cfg.get("vid_trim") else 0
        if ai_start is not None and cfg.get("vid_trim") and f("vid_start") == 0: start = min(max(ai_start, 0), max(dur - 1, 0))
        L = dur - start
        if cfg.get("vid_trim") and f("vid_len") > 0: L = min(L, f("vid_len") * 60)
    return max(start, 0), max(L, 1)

def build_vf(cfg, short, L, srt):
    W, H = (1080, 1920) if short else (1920, 1080)
    fx = "on" if cfg.get("fx_list") else "none"; vf = []
    if short:
        if cfg.get("frame", "crop") == "blur":
            vf.append(f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:5[bg];"
                      f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        else:
            vf.append(f"crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale={W}:{H}")
    elif fx != "none":
        vf.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
    vf.append("setsar=1")
    vf += efectos.build(cfg, W, H, L)
    if cfg.get("vivid"): vf.append("eq=contrast=1.06:saturation=1.25:brightness=0.01,unsharp=5:5:0.6")
    if cfg.get("vignette"): vf.append("vignette=PI/5")
    if cfg.get("fade"): vf.append(f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(L - 0.5, 0):.2f}:d=0.5")
    if srt is not None:
        size = {"s": (12, 14), "m": (16, 20), "l": (20, 26)}[cfg.get("sub_size", "m") if cfg.get("sub_size", "m") in "sml" else "m"][0 if short else 1]
        col = {"white": "&H00FFFFFF", "yellow": "&H0000FFFF", "green": "&H0080FF80"}.get(cfg.get("sub_color", "white"), "&H00FFFFFF")
        pos = cfg.get("sub_pos", "bottom")
        al, mv = {"bottom": (2, 70 if short else 20), "middle": (10, 0), "top": (6, 40 if short else 15)}.get(pos, (2, 20))
        style = f"FontName=Arial,Alignment={al},FontSize={size},Bold=1,Outline=3,Shadow=0,PrimaryColour={col},OutlineColour=&H00000000,MarginV={mv}"
        vf.append(f"subtitles={srt.name}:force_style='{style}'")
    return ",".join(vf)

def build_af(cfg, L):
    af = []
    if cfg.get("loudnorm"): af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if cfg.get("fade"): af += ["afade=t=in:st=0:d=0.5", f"afade=t=out:st={max(L - 0.5, 0):.2f}:d=0.5"]
    return ",".join(af)

def encode(it, src, start, L, vf, af, final):
    args = [str(FFMPEG), "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", "-ss", str(start), "-t", str(L), "-i", src.name, "-vf", vf]
    if af: args += ["-af", af]
    args += ["-c:v", "libx264", "-preset", "fast", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", final.name]
    p = subprocess.Popen(args, cwd=MEDIA, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    errs = []
    for line in p.stdout:
        if cancel_requested(it):
            p.terminate(); p.wait(); final.unlink(missing_ok=True); raise Cancelled()
        m = re.match(r"out_time_(?:us|ms)=(\d+)", line)
        if m: set_prog(it, "edit", int(m.group(1)) / 1e6 / max(L, 1))
        elif "=" not in line: errs.append(line.strip())
    if p.wait() != 0: raise subprocess.CalledProcessError(p.returncode, "ffmpeg", output=" ".join(errs[-3:]))
    set_prog(it, "edit", 1.0, True)

def process(it, cfg):
    if not FFMPEG: raise RuntimeError("No encuentro FFmpeg. Cierra el worker y ejecuta 2-INSTALAR-Y-EJECUTAR.bat de nuevo.")
    vid = it["id"]; src = MEDIA / f"{vid}.mp4"; short = it["kind"] == "short"
    it["pct"] = 0; it["stage"] = "Preparando"; it.pop("est", None); save(D)
    check_cancel(it)
    info = json.loads(ytdlp("-j", "--no-playlist", it["url"], capture_output=True, text=True).stdout)
    it["title"] = info["title"][:90]; dur = info.get("duration") or 60
    if not src.exists():
        print("  [1/3] Descargando...")
        download(it, src)
    else: set_prog(it, "dl", 1.0, True)
    check_cancel(it)
    start, L = window(it, cfg, dur)
    modo, ayuda = cfg.get("ia_mode", "alternar"), []
    if ia_activa(cfg) and cfg.get("ia_cut") and dur > L + 2 and dur <= 1800 and not it.get("_noia"):
        elegible = (short and cfg.get("cut_mode", "auto") == "auto") or (not short and cfg.get("vid_trim") and float(cfg.get("vid_len") or 0) > 0 and not float(cfg.get("vid_start") or 0))
        if elegible:
            print("  [IA] Buscando el mejor tramo...")
            try:
                segs = transcribe_full(it, src, cfg, dur)
                r = ia.momento(modo, it["title"], segs, dur, L) if segs else None
                if r:
                    start, L = window(it, cfg, dur, r["inicio"]); ayuda.append("corte " + r["prov"])
                    print(f"  [IA {r['prov']}] Tramo elegido desde {start:.0f}s. {r['motivo']}")
                else: print("  [IA] Sin sugerencia útil: uso el corte normal.")
            except Cancelled: raise
            except Exception as e: print("  [IA] No se pudo analizar:", str(e)[:150])
        set_prog(it, "ia", 1.0, True)
    print(f"  Tramo: {start:.0f}s -> {start + L:.0f}s ({L:.0f}s de {dur:.0f}s)")
    srt = None
    if cfg.get("sub", True):
        print("  [2/3] Subtitulos...")
        try: srt = subtitles(it, src, start, L, cfg, short)
        except Cancelled: raise
        except Exception as e: print("  Sin subtitulos:", str(e)[:200])
    texto = srt_text(srt)
    if it.get("_sub_ia"): ayuda.append("subtítulos " + it.pop("_sub_ia"))
    ecfg = cfg
    if ia_activa(cfg) and cfg.get("ia_fx"):
        permitidos = [k for k in (cfg.get("fx_list") or []) if k in efectos.EFECTOS] or list(efectos.EFECTOS)
        r = ia.efecto_plan(modo, it["title"], texto, it["kind"], L, permitidos)
        if r:
            ecfg = dict(cfg, fx_list=r["fx_list"], fx_mode=r["fx_mode"], fx_dur=r["fx_dur"], fx_power=r["fx_power"])
            ayuda.append("efectos " + r["prov"]); print(f"  [IA {r['prov']}] Efectos: {', '.join(r['fx_list'])} ({r['fx_mode']}). {r['motivo']}")
        else: print("  [IA] Sin sugerencia de efectos: uso los tuyos.")
    final = MEDIA / f"{vid}_final.mp4"
    print("  [3/3] Editando video...")
    vf, af = build_vf(ecfg, short, L, srt), build_af(ecfg, L)
    if not short and not vf.replace("setsar=1", "").strip(",") and not af and start == 0 and L >= dur - 1:
        shutil.copy(src, final); set_prog(it, "edit", 1.0, True)   # completo y sin efectos: no se recodifica
    else:
        try: encode(it, src, start, L, vf, af, final)
        except subprocess.CalledProcessError as e:
            if srt is None: raise RuntimeError("FFmpeg: " + str(e.output)[:200])
            print("  FFmpeg no pudo quemar subtitulos; reintento sin ellos.")
            encode(it, src, start, L, build_vf(ecfg, short, L, None), af, final)
    if ia_activa(cfg) and cfg.get("ia_text"):
        r = ia.textos(modo, it["title"], texto, it["kind"])
        if r: it["ia_title"], it["ia_desc"] = r["titulo"], r["descripcion"]; ayuda.append("título " + r["prov"]); print(f"  [IA {r['prov']}] Título: {r['titulo']}")
    it["ia"] = " · ".join(ayuda)
    it["file"] = str(final); it["status"] = "ready"
    if not PLAN.get("up", (0, 0))[1]: it["pct"] = 100; it["stage"] = "Listo"
    save(D)

def next_slot(d, kind):
    c = d["config"]; n, t = (c["sn"], c["st"]) if kind == "short" else (c["vn"], c["vt"])
    times = sorted(x.strip() for x in t.split(",") if x.strip())[:n]
    taken = {i.get("publishAt") for i in d["items"]}
    now = dt.datetime.now().astimezone(); day = now.date()
    for off in range(400):
        for hm in times:
            h, m = map(int, hm.split(":"))
            s = dt.datetime.combine(day + dt.timedelta(days=off), dt.time(h, m)).astimezone()
            iso = s.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if s > now + dt.timedelta(minutes=15) and iso not in taken: return iso
    raise RuntimeError("Sin horarios configurados")

def local(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()

def write_plan(items):
    lines = []
    for it in items:
        when = local(it["publishAt"]).strftime("%Y-%m-%d %H:%M") if it.get("publishAt") else "-"
        lines.append(f"{when} | {it['kind']:5} | {it.get('title','')} | {it.get('file','')}")
    (ROOT / "plan-publicacion.txt").write_text("\n".join(lines), "utf-8")

STEP = [""]
def paso(msg): STEP[0] = msg; print("  Subida:", msg)

def up_progress(tab, it, t0, size_mb):
    """Porcentaje de subida: lo lee de Studio si puede; si no, lo estima (marcado con ~)."""
    frac = None
    try:
        txt = tab.texto("ytcp-video-upload-progress")
        m = re.search(r"(\d{1,3})\s*%", txt)
        if m: frac = min(int(m.group(1)), 100) / 100; it["est"] = False
        elif re.search(r"upload complete|checks complete|finished|completad|finaliz|terminad", txt, re.I): frac = 1.0; it["est"] = False
    except Exception: pass
    if frac is None:
        tau = max(8.0, size_mb / 2.0)               # ~2 MB/s
        frac = min(0.95, 1 - math.exp(-(time.time() - t0) / tau)); it["est"] = True
    set_prog(it, "up", frac)

MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"]
MESES_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
def fmt_fecha(actual, w):
    """Escribe la fecha igual que la muestra tu Studio (español o inglés)."""
    m = re.match(r"^\s*(\d{1,2})\s+([^\s\d,.]+)\.?\s+(\d{4})\s*$", actual)
    if m:
        es = m.group(2).lower() in [x.lower() for x in MESES_ES] + ["sep", "sept"]
        return f"{w.day} {(MESES_ES if es else MESES_EN)[w.month - 1]} {w.year}"
    if re.match(r"^\s*[A-Za-z]{3,4}\.?\s+\d{1,2},\s+\d{4}\s*$", actual): return f"{MESES_EN[w.month - 1]} {w.day}, {w.year}"
    raise RuntimeError("No reconozco el formato de fecha de Studio: " + actual[:30])

def fmt_hora(actual, w):
    m = re.search(r"([ap])\.?\s?m\.?", actual, re.I)
    if not m: return f"{w.hour}:{w.minute:02d}"
    h = w.hour % 12 or 12; am = w.hour < 12
    if "." in actual: return f"{h}:{w.minute:02d} {'a. m.' if am else 'p. m.'}"
    return f"{h}:{w.minute:02d} {'AM' if am else 'PM'}"

def campo_valor(tab, sel):
    return tab.eval(f"(function(){{var e=window.__D({json.dumps(sel)});return e?e.value||'':''}})()") or ""

ARCHIVO = "input[type=file]"
def abrir_dialogo(tab, cid, chk):
    """Abre el cuadro 'Subir videos' de Studio probando varias formas (Studio cambia seguido)."""
    paso("abriendo la subida: enlace directo")
    tab.ir(f"https://studio.youtube.com/channel/{cid}/videos/upload?d=ud")
    if tab.esperar(ARCHIVO, 20, chk): return
    tab.ir(f"https://studio.youtube.com/channel/{cid}"); time.sleep(2)
    paso("abriendo la subida: botón de subir del panel")
    for sel in ("#upload-icon", "#upload-button", "ytcp-icon-button#upload-icon", "ytcp-button#upload-button",
                "[aria-label='Subir vídeos']", "[aria-label='Subir videos']", "[aria-label='Upload videos']",
                "[aria-label*='ubir v' i]", "[aria-label*='pload v' i]"):
        chk()
        try:
            if tab.existe(sel):
                tab.clic(sel)
                if tab.esperar(ARCHIVO, 8, chk): return
        except Cancelled: raise
        except Exception: pass
    paso("abriendo la subida: menú Crear")
    for sel in ("#create-icon", "ytcp-button#create-icon", "[aria-label='Crear']", "[aria-label='Create']"):
        chk()
        try:
            if tab.existe(sel):
                tab.clic(sel); time.sleep(1.2)
                if not tab.clic_texto(r"^(subir v[ií]deos?|upload videos?)$") and tab.existe("#text-item-0"): tab.clic("#text-item-0")
                if tab.esperar(ARCHIVO, 10, chk): return
        except Cancelled: raise
        except Exception: pass
    try:
        if tab.clic_texto(r"^(crear|create)$"):
            time.sleep(1.2)
            if not tab.clic_texto(r"^(subir v[ií]deos?|upload videos?)$") and tab.existe("#text-item-0"): tab.clic("#text-item-0")
            if tab.esperar(ARCHIVO, 10, chk): return
    except Cancelled: raise
    except Exception: pass
    raise RuntimeError("Studio no abrió el cuadro de subida (probé enlace directo, botón de subir y menú Crear)")

def _clic_primero(tab, selectores, idx=0, espera=0):
    """Prueba varios selectores y hace clic en el primero que exista."""
    for sel in selectores:
        try:
            if espera and not tab.esperar(sel, espera): continue
            if tab.existe(sel): tab.clic(sel, idx); return True
        except Exception: pass
    return False

JS_NO_NINOS = r"""(function(){
var re=/\bno\b[\s,]+(no\s+)?(es|est[aá]|son|fue)\b[^]*ni\S{1,3}os|not\s+made\s+for\s+kids|NOT_MADE_FOR_KIDS/i;
var a=window.__A("tp-yt-paper-radio-button,[role=radio],input[type=radio],ytkc-made-for-kids-select label,ytkc-made-for-kids-select *");
var best=null;
for(var i=0;i<a.length;i++){var e=a[i];
 var t=((e.innerText||e.textContent||'')+' '+(e.getAttribute('name')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.id||'')).trim();
 if(!re.test(t))continue;
 var r=e.getBoundingClientRect();
 var esRadio=/radio/i.test(e.tagName+(e.getAttribute('role')||''));
 var score=(r.width>0?0:1000)+(esRadio?0:50)+t.length;
 if(!best||score<best.score)best={e:e,score:score};}
if(!best)return null;
best.e.scrollIntoView({block:'center'});
var r=best.e.getBoundingClientRect();
var on=best.e.getAttribute('aria-checked')==='true'||best.e.checked===true||best.e.hasAttribute('checked');
return {x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height,on:on};})()"""
JS_NO_NINOS_CLICK = JS_NO_NINOS.replace("var r=best.e.getBoundingClientRect();\nvar on", "best.e.click();var r=best.e.getBoundingClientRect();\nvar on")

def marcar_no_ninos(tab, chk):
    """Marca 'No, no es contenido para niños' en español o ingles, con o sin el atributo name de Studio."""
    for intento in range(6):
        chk()
        try:
            c = tab.eval(JS_NO_NINOS)
            if c and c.get("on"): return True
            if c and c["w"] > 0 and c["h"] > 0:
                for t in ("mousePressed", "mouseReleased"):
                    tab.call("Input.dispatchMouseEvent", {"type": t, "x": c["x"], "y": c["y"], "button": "left", "clickCount": 1})
                time.sleep(0.6)
                c2 = tab.eval(JS_NO_NINOS)
                if c2 and c2.get("on"): return True
                tab.eval(JS_NO_NINOS_CLICK)
                time.sleep(0.5)
                c3 = tab.eval(JS_NO_NINOS)
                if c3 and c3.get("on"): return True
                return True        # se hizo clic; algunas versiones de Studio no exponen el estado marcado
        except Exception as e:
            if type(e).__name__ == "Cancelled": raise
        time.sleep(1.5)
    return False

def textos_para_subir(it, cfg):
    """Titulo/descripcion de IA. Si ya se generaron al editar se usan; si no, se intenta ahora.
    Devuelve (titulo o None, descripcion o ''). None = dejar el titulo que pone Studio (nombre del archivo)."""
    t, desc = (it.get("ia_title") or "").strip(), (it.get("ia_desc") or "").strip()
    if not t and cfg and ia_activa(cfg) and cfg.get("ia_text", True):
        try:
            paso("pidiendo título y descripción a la IA")
            srt = MEDIA / f"{it.get('id', '')}.srt"
            r = ia.textos(cfg.get("ia_mode", "alternar"), it.get("title", ""), srt_text(srt if srt.exists() else None), it.get("kind", "video"))
            if r: t, desc = r["titulo"].strip(), r["descripcion"].strip(); it["ia_title"], it["ia_desc"] = t, desc; print(f"  [IA {r['prov']}] Título: {t}")
        except Exception as e: print("  [IA] No pude generar el título:", str(e)[:120])
    return (t[:100] if t else None), desc

def studio_upload_one(tab, cid, it, cfg=None):
    titulo, desc = textos_para_subir(it, cfg)
    cuerpo = (desc + "\n\n" if desc else "") + (f"#Shorts\n" if it["kind"] == "short" and "#shorts" not in desc.lower() else "") + f"Fuente: {it['url']}"
    now_mode = not it.get("publishAt")
    when = None if now_mode else local(it["publishAt"])
    size_mb = os.path.getsize(it["file"]) / 1048576
    chk = lambda: check_cancel(it)
    it["status"] = "uploading"; it.pop("error", None); it.pop("yt_url", None); set_prog(it, "up", 0.0, True)
    abrir_dialogo(tab, cid, chk)
    paso("enviando el archivo de video")
    tab.archivos("input[type=file]", [it["file"]]); t0 = time.time()
    paso("esperando el formulario de detalles")
    end = time.time() + 120
    while tab.cuantos("#textbox") < 2:
        chk()
        if time.time() > end: raise RuntimeError("Studio no mostró el formulario de título y descripción")
        time.sleep(1)
    time.sleep(1.5); up_progress(tab, it, t0, size_mb)
    if titulo:
        paso("escribiendo el título (IA)")
        tab.escribir("#textbox", titulo, 0); time.sleep(0.5)
    else:
        paso("sin título de IA: dejo el nombre del archivo")
    paso("escribiendo la descripción")
    tab.escribir("#textbox", cuerpo, 1); time.sleep(0.5)
    paso("marcando 'no es para niños'")
    if not marcar_no_ninos(tab, chk):
        print("  Aviso: no encontré la opción 'No es para niños'; sigo y dejo diagnóstico por si Studio la pide.")
        tab.captura(ROOT / "aviso-ninos.png"); tab.diagnostico(ROOT / "diagnostico-ninos.txt", "No encontré la opcion de 'para niños'")
    time.sleep(0.6)
    # Siguiente hasta llegar a Visibilidad (Detalles -> Elementos del video -> Comprobaciones -> Visibilidad)
    for n in range(1, 8):
        chk(); up_progress(tab, it, t0, size_mb)
        if tab.visible("tp-yt-paper-radio-button[name='PUBLIC']"): break
        paso(f"tocando 'Siguiente' ({n})")
        fin = time.time() + 90
        while not tab.habilitado("#next-button"):
            chk()
            if time.time() > fin: raise RuntimeError("El botón 'Siguiente' no se habilitó")
            time.sleep(1)
        tab.clic("#next-button"); time.sleep(2)
    else:
        raise RuntimeError("Llegué al final de las etapas sin ver la pantalla de Visibilidad")
    if now_mode:
        paso("eligiendo Público (publicar ahora)")
        tab.clic("tp-yt-paper-radio-button[name='PUBLIC']", 0, 20); time.sleep(0.8)
    else:
        paso("programando la fecha")
        tab.clic("#second-container-expand-button", 0, 20); time.sleep(1)
        tab.escribir("ytcp-date-picker input", fmt_fecha(campo_valor(tab, "ytcp-date-picker input"), when)); tab.tecla("Enter", 13); time.sleep(0.6)
        tab.escribir("#time-of-day-container input", fmt_hora(campo_valor(tab, "#time-of-day-container input"), when)); tab.tecla("Enter", 13); time.sleep(0.6)
    paso("esperando a que termine la subida")
    end = time.time() + 1500
    while True:
        chk(); up_progress(tab, it, t0, size_mb)
        if tab.habilitado("#done-button"): break
        if time.time() > end: raise RuntimeError("La subida tardó más de 25 minutos")
        time.sleep(1.5)
    paso("publicando" if now_mode else "programando")
    tab.clic("#done-button")
    fin = time.time() + 120
    while tab.visible("#done-button"):                        # cuando Studio cierra el formulario, ya se publicó
        chk()
        if time.time() > fin: raise RuntimeError("Studio no confirmó la publicación (el botón final sigue ahí)")
        time.sleep(1)
    time.sleep(2)
    try:
        link = tab.eval("(function(){var a=window.__A(\"a[href*='youtu.be/'],a[href*='youtube.com/shorts/'],a[href*='youtube.com/watch']\");"
                        "for(var i=0;i<a.length;i++){var r=a[i].getBoundingClientRect();if(r.width>0)return a[i].href}return ''})()")
        if link: it["yt_url"] = link
    except Exception: pass
    _clic_primero(tab, ["#close-button", "ytcp-button#close-button"])
    it["status"] = "published" if now_mode else "scheduled"; it["pct"] = 100
    it["stage"] = "Publicado" if now_mode else "Programado"; it.pop("est", None)

def marcar_fallo(d, items, msg):
    for it in items:
        if it["status"] in ("ready", "uploading"):
            it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"; it["error"] = msg[:260]
    save(d)

def studio_upload(d, only=None, mode=None):
    pending = [i for i in d["items"] if i["status"] == "ready" and (only is None or i["key"] in only)]
    if not pending: print("No hay videos listos para subir."); return
    now_mode = (mode or d.get("config", {}).get("publish")) == "now"
    for it in pending:
        it.pop("publishAt", None) if now_mode else it.__setitem__("publishAt", next_slot(d, it["kind"]))
    write_plan(pending); save(d)
    tab = cid = None
    try:
        print("Conectando con el Chrome del worker...")
        tab = cdp.Tab.existente("https://studio.youtube.com") or cdp.Tab.abrir("https://studio.youtube.com")
        print("Si no iniciaste sesion en YouTube, hacelo en la ventana de Chrome (espero hasta 5 min)...")
        end = time.time() + 300
        while time.time() < end:
            try:
                m = re.search(r"studio\.youtube\.com/channel/([\w-]+)", tab.url())
                if m: cid = m.group(1); break
            except Exception: pass
            time.sleep(1)
        if not cid: raise RuntimeError("No detecte tu canal en YouTube Studio. Abri Studio en el Chrome del worker e inicia sesion.")
    except Exception as e:
        print("No pude preparar la subida:", e); marcar_fallo(d, pending, "No pude preparar la subida: " + str(e)); return
    for it in pending:
        try:
            check_cancel(it)
            studio_upload_one(tab, cid, it, d.get("config")); print("Subido:", it["title"], it.get("publishAt") or "publicado ahora")
        except Cancelled:
            it["status"] = "cancelled"; it["stage"] = "Cancelado"; it.pop("publishAt", None)
            print("Cancelado:", it.get("title")); save(d)
            try: tab.ir(f"https://studio.youtube.com/channel/{cid}")
            except Exception: pass
        except Exception as e:
            tab.captura(ROOT / "error-subida.png"); tab.diagnostico(ROOT / "diagnostico-subida.txt", f"Paso: {STEP[0]}\nError: {e}")
            it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"
            it["error"] = f"No se pudo subir (paso: {STEP[0]}): {str(e)[:150]}. Detalle en worker\\diagnostico-subida.txt"
            print("No se pudo subir automaticamente:", it["title"], "->", STEP[0], "->", e)
            try: tab.ir(f"https://studio.youtube.com/channel/{cid}")        # sale del formulario a medias
            except Exception: pass
        save(d)
    try: tab.cerrar()
    except Exception: pass

def main():
    global D, PLAN
    if "--subir" in sys.argv: return upload_only()
    d = load(); d.setdefault("config", {}); D = d; expand(d); save(d)
    PLAN = make_plan(d["config"], not NO_UPLOAD)
    for it in d["items"]:
        if it["status"] not in ("pending", "processing"): continue
        try:
            check_cancel(it)
            it["status"] = "processing"; it.pop("error", None); save(d)
            print("Procesando", it["url"]); process(it, d["config"])
        except Cancelled:
            it["status"] = "cancelled"; it["stage"] = "Cancelado"; print("Cancelado:", it.get("title") or it["url"])
        except Exception as e:
            it["status"] = "error"; it["stage"] = "Error"; it["error"] = str(e)[:300]; print("ERROR:", e)
        save(d)
    if NO_UPLOAD:
        write_plan([i for i in d["items"] if i["status"] == "ready"])
    else:
        try: studio_upload(d, mode=(sys.argv[sys.argv.index("--modo") + 1] if "--modo" in sys.argv else None))
        except Exception as e: print("Fallo la subida automatica:", e); marcar_fallo(d, d["items"], "Falló la subida: " + str(e))
    print("Listo. Videos terminados en la carpeta media. Plan: plan-publicacion.txt")

def upload_only():
    """Sube videos ya editados: --subir CLAVE|ALL --modo now|schedule"""
    global D, PLAN
    d = load(); D = d; PLAN = {"up": (0.0, 1.0)}
    key = sys.argv[sys.argv.index("--subir") + 1]
    mode = sys.argv[sys.argv.index("--modo") + 1] if "--modo" in sys.argv else None
    try: studio_upload(d, None if key == "ALL" else {key}, mode)
    except Exception as e: print("Fallo la subida:", e); marcar_fallo(d, d["items"], "Falló la subida: " + str(e))
    print("Listo.")

if __name__ == "__main__":
    main()
