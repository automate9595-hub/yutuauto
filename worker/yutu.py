"""Yutu worker: descarga -> recorte -> efectos -> subtitulos -> subida a YouTube Studio (sin Google Cloud)."""
import json, math, os, re, shutil, subprocess, sys, time, pathlib, datetime as dt
import efectos
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

def make_plan(cfg, upload):
    w = {"dl": .20, "sub": .20 if cfg.get("sub", True) else 0, "edit": .40, "up": .20 if upload else 0}
    tot = sum(w.values()); acc = 0; plan = {}
    for k in ("dl", "sub", "edit", "up"):
        plan[k] = (acc / tot, w[k] / tot); acc += w[k]
    return plan

LABEL = {"dl": "Descargando", "sub": "Subtitulos", "edit": "Editando", "up": "Subiendo"}
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

_MODEL = {}
def whisper_model(name):
    if name not in _MODEL:
        from faster_whisper import WhisperModel
        _MODEL[name] = WhisperModel(name, compute_type="int8")
    return _MODEL[name]

def subtitles(it, src, start, length, cfg, short):
    """Transcribe solo el tramo elegido y arma subtitulos cortos (estilo Shorts)."""
    wav = MEDIA / (src.stem + "_audio.wav")
    run(FFMPEG, "-loglevel", "error", "-y", "-ss", start, "-t", length, "-i", src, "-vn", "-ac", 1, "-ar", 16000, wav)
    lang = cfg.get("lang", "es")
    segs, _ = whisper_model(cfg.get("model", "small")).transcribe(
        str(wav), language=None if lang == "auto" else lang, vad_filter=True, word_timestamps=True)
    words = []
    for sg in segs:
        check_cancel(it); words += list(sg.words or []); set_prog(it, "sub", sg.end / max(length, 1))
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
    wav.unlink(missing_ok=True)
    if not caps: return None
    srt = MEDIA / (src.stem + ".srt")
    with open(srt, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(caps, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(max(b, a + 0.3))}\n{t.upper() if cfg.get('sub_caps') else t}\n\n")
    return srt

def window(it, cfg, dur):
    """Tramo del video original que se conserva: (inicio, duracion)."""
    f = lambda k, d=0: float(cfg.get(k) or d)
    if it["kind"] == "short":
        L = min(f("short_len", 58), 60, dur)
        mode = cfg.get("cut_mode", "auto")
        if mode == "inicio" or dur <= L: start = 0
        elif mode == "manual": start = min(f("cut_start"), dur - L)
        else: start = min(dur * 0.1, dur - L)
    else:
        start = min(max(f("vid_start"), 0), max(dur - 1, 0)) if cfg.get("vid_trim") else 0
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
    print(f"  Tramo: {start:.0f}s -> {start + L:.0f}s ({L:.0f}s de {dur:.0f}s)")
    srt = None
    if cfg.get("sub", True):
        print("  [2/3] Subtitulos (Whisper)...")
        try: srt = subtitles(it, src, start, L, cfg, short)
        except Cancelled: raise
        except Exception as e: print("  Sin subtitulos:", str(e)[:200])
    final = MEDIA / f"{vid}_final.mp4"
    print("  [3/3] Editando video...")
    vf, af = build_vf(cfg, short, L, srt), build_af(cfg, L)
    if not short and not vf.replace("setsar=1", "").strip(",") and not af and start == 0 and L >= dur - 1:
        shutil.copy(src, final); set_prog(it, "edit", 1.0, True)   # completo y sin efectos: no se recodifica
    else:
        try: encode(it, src, start, L, vf, af, final)
        except subprocess.CalledProcessError as e:
            if srt is None: raise RuntimeError("FFmpeg: " + str(e.output)[:200])
            print("  FFmpeg no pudo quemar subtitulos; reintento sin ellos.")
            encode(it, src, start, L, build_vf(cfg, short, L, None), af, final)
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

def up_progress(page, it, t0, size_mb):
    """Porcentaje de subida: lo lee de Studio si puede; si no, lo estima (marcado con ~)."""
    frac = None
    try:
        txt = page.locator("ytcp-video-upload-progress").first.inner_text(timeout=400)
        m = re.search(r"(\d{1,3})\s*%", txt)
        if m: frac = min(int(m.group(1)), 100) / 100; it["est"] = False
        elif re.search(r"upload complete|checks complete|finished", txt, re.I): frac = 1.0; it["est"] = False
    except Exception: pass
    if frac is None:
        tau = max(8.0, size_mb / 2.0)               # ~2 MB/s
        frac = min(0.95, 1 - math.exp(-(time.time() - t0) / tau)); it["est"] = True
    set_prog(it, "up", frac)

def studio_upload_one(page, it):
    from playwright.sync_api import TimeoutError as PWTimeout
    title = it["title"] + (" #Shorts" if it["kind"] == "short" else "")
    now_mode = not it.get("publishAt")
    when = None if now_mode else local(it["publishAt"])
    size_mb = os.path.getsize(it["file"]) / 1048576; t0 = time.time()
    it["status"] = "uploading"; it.pop("error", None); set_prog(it, "up", 0.0, True)
    page.goto("https://studio.youtube.com", wait_until="domcontentloaded")
    page.click("#create-icon"); page.click("#text-item-0")
    page.wait_for_selector("input[type=file]", state="attached", timeout=60000)
    page.set_input_files("input[type=file]", it["file"])
    t0 = time.time(); check_cancel(it)
    page.wait_for_selector("#textbox", timeout=120000)
    up_progress(page, it, t0, size_mb)
    box = page.locator("#textbox")
    box.nth(0).click(); page.keyboard.press("Control+A"); page.keyboard.type(title[:100])
    box.nth(1).click(); page.keyboard.type(f"{title}\n\nFuente: {it['url']}")
    page.locator("[name='VIDEO_MADE_FOR_KIDS_NOT_MADE_FOR_KIDS']").click()
    for _ in range(3):
        check_cancel(it); up_progress(page, it, t0, size_mb)
        page.click("#next-button"); page.wait_for_timeout(1500)
    if now_mode:
        page.locator("tp-yt-paper-radio-button[name='PUBLIC']").click()
    else:
        page.click("#second-container-expand-button")
        page.locator("ytcp-date-picker input").first.fill(when.strftime("%b %d, %Y")); page.keyboard.press("Enter")
        page.locator("#time-of-day-container input").first.fill(when.strftime("%I:%M %p").lstrip("0")); page.keyboard.press("Enter")
    end = time.time() + 1200                       # espera a que termine la subida, mostrando el avance
    while True:
        check_cancel(it); up_progress(page, it, t0, size_mb)
        try: page.locator("#done-button").click(timeout=1500); break
        except PWTimeout:
            if time.time() > end: raise
    page.wait_for_timeout(4000)
    it["status"] = "published" if now_mode else "scheduled"; it["pct"] = 100; it["stage"] = "Publicado" if now_mode else "Programado"; it.pop("est", None)

def studio_upload(d, only=None, mode=None):
    from playwright.sync_api import sync_playwright
    pending = [i for i in d["items"] if i["status"] == "ready" and (only is None or i["key"] in only)]
    if not pending: print("No hay videos listos para subir."); return
    now_mode = (mode or d.get("config", {}).get("publish")) == "now"
    for it in pending:
        it.pop("publishAt", None) if now_mode else it.__setitem__("publishAt", next_slot(d, it["kind"]))
    write_plan(pending); save(d)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = browser.contexts[0].new_page()
        page.goto("https://studio.youtube.com", wait_until="domcontentloaded")
        print("Si no iniciaste sesion en YouTube, hacelo en la ventana de Chrome (espero hasta 5 min)...")
        if not wait_login(page, 300):
            raise RuntimeError("No detecte tu sesion en YouTube Studio (pagina actual: " + page.url + ")")
        for it in pending:
            try:
                check_cancel(it)
                studio_upload_one(page, it); print("Subido:", it["title"], it.get("publishAt") or "publicado ahora")
            except Cancelled:
                it["status"] = "cancelled"; it["stage"] = "Cancelado"; it.pop("publishAt", None)
                print("Cancelado:", it.get("title")); save(d)
                try: page.close(run_before_unload=False)
                except Exception: pass
                page = browser.contexts[0].new_page()
            except Exception as e:
                it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"
                it["error"] = "Subir a mano (ver plan-publicacion.txt): " + str(e)[:200]
                print("No se pudo subir automaticamente:", it["title"], "->", e)
            save(d)

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
        try: studio_upload(d)
        except Exception as e: print("Fallo la subida automatica:", e)
    print("Listo. Videos terminados en la carpeta media. Plan: plan-publicacion.txt")

def upload_only():
    """Sube videos ya editados: --subir CLAVE|ALL --modo now|schedule"""
    global D, PLAN
    d = load(); D = d; PLAN = {"up": (0.0, 1.0)}
    key = sys.argv[sys.argv.index("--subir") + 1]
    mode = sys.argv[sys.argv.index("--modo") + 1] if "--modo" in sys.argv else None
    try: studio_upload(d, None if key == "ALL" else {key}, mode)
    except Exception as e: print("Fallo la subida:", e)
    print("Listo.")

def logged_in(page):
    u = page.url
    if "studio.youtube.com/channel/" in u: return True
    return "studio.youtube.com" in u and page.locator("#create-icon, #upload-icon").count() > 0

def wait_login(page, secs):
    end = time.time() + secs
    while time.time() < end:
        try:
            if logged_in(page): return True
        except Exception: pass
        page.wait_for_timeout(1000)
    return False

def estado():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0]
            for pg in ctx.pages:
                if "studio.youtube.com/channel/" in pg.url: print("LOGIN_OK"); return
            page = ctx.new_page(); page.goto("https://studio.youtube.com", wait_until="domcontentloaded")
            ok = wait_login(page, 15); url = page.url; page.close()
            print("LOGIN_OK" if ok else "LOGIN_NO pagina=" + url[:120])
    except Exception as e:
        print("LOGIN_NO error=" + str(e)[:160])

if __name__ == "__main__":
    estado() if "--estado" in sys.argv else main()
