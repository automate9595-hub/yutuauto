"""Yutu worker: descarga -> recorte -> subtitulos -> subida a YouTube Studio (sin Google Cloud)."""
import json, os, shutil, subprocess, sys, time, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
MEDIA = ROOT / "media"; MEDIA.mkdir(exist_ok=True)
QF = ROOT / "queue.json"
NO_UPLOAD = "--sin-subir" in sys.argv

def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p: return p
    c = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin" / "ffmpeg.exe"
    if c.exists(): return str(c)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
FFMPEG = find_ffmpeg()

def run(*a, **k): return subprocess.run([str(x) for x in a], check=True, **k)
def load(): return json.loads(QF.read_text("utf-8"))
def save(d): QF.write_text(json.dumps(d, indent=2, ensure_ascii=False), "utf-8")

def expand(d):
    out = []
    for it in d["items"]:
        if it["type"] != "playlist": out.append(it); continue
        r = run("yt-dlp", "--flat-playlist", "--print", "%(id)s", it["url"], capture_output=True, text=True)
        for vid in r.stdout.split():
            out.append({"type": "video", "id": vid, "key": "video:" + vid, "kind": it["kind"],
                        "url": "https://www.youtube.com/watch?v=" + vid, "status": "pending"})
    seen, res = set(), []
    for it in out:
        if it["key"] not in seen: seen.add(it["key"]); res.append(it)
    d["items"] = res

def srt_time(s):
    h, m, sec = int(s // 3600), int(s % 3600 // 60), s % 60
    return f"{h:02}:{m:02}:{sec:06.3f}".replace(".", ",")

def subtitles(clip, lang, short):
    from faster_whisper import WhisperModel
    model = WhisperModel("small", compute_type="int8")
    segs, _ = model.transcribe(str(clip), language=None if lang == "auto" else lang, vad_filter=True)
    srt = clip.with_suffix(".srt")
    with open(srt, "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{srt_time(s.start)} --> {srt_time(s.end)}\n{s.text.strip()}\n\n")
    return srt

def process(it, cfg):
    if not FFMPEG: raise RuntimeError("No encuentro FFmpeg. Cierra el worker y ejecuta 2-INSTALAR-Y-EJECUTAR.bat de nuevo.")
    vid = it["id"]; src = MEDIA / f"{vid}.mp4"
    info = json.loads(run("yt-dlp", "-j", "--no-playlist", it["url"], capture_output=True, text=True).stdout)
    it["title"] = info["title"][:90]; dur = info.get("duration") or 60
    if not src.exists():
        run("yt-dlp", "--no-progress", "--ffmpeg-location", FFMPEG,
            "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
            "--no-playlist", "-o", MEDIA / f"{vid}.%(ext)s", it["url"])
    short = it["kind"] == "short"; clip = MEDIA / f"{vid}_clip.mp4"
    if short:
        start = 0 if dur <= 58 else dur * 0.1
        run(FFMPEG, "-loglevel", "error", "-y", "-ss", start, "-t", 58, "-i", src,
            "-vf", "crop=ih*9/16:ih,scale=1080:1920", "-c:v", "libx264", "-preset", "fast", "-crf", 21,
            "-c:a", "aac", clip)
    else:
        clip = src
    final = MEDIA / f"{vid}_final.mp4"
    if cfg.get("sub", True):
        srt = subtitles(clip, cfg.get("lang", "es"), short)
        style = "Alignment=2,FontSize=%d,Outline=2,Bold=1,MarginV=%d" % ((16, 90) if short else (20, 30))
        run(FFMPEG, "-loglevel", "error", "-y", "-i", clip.name, "-vf", f"subtitles={srt.name}:force_style='{style}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", 21, "-c:a", "copy", final.name, cwd=MEDIA)
    else:
        clip.replace(final)
    it["file"] = str(final); it["status"] = "ready"

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

def studio_upload_one(page, it):
    title = it["title"] + (" #Shorts" if it["kind"] == "short" else "")
    when = local(it["publishAt"])
    page.goto("https://studio.youtube.com", wait_until="domcontentloaded")
    page.click("#create-icon"); page.click("#text-item-0")
    page.wait_for_selector("input[type=file]", state="attached", timeout=60000)
    page.set_input_files("input[type=file]", it["file"])
    page.wait_for_selector("#textbox", timeout=120000)
    box = page.locator("#textbox")
    box.nth(0).click(); page.keyboard.press("Control+A"); page.keyboard.type(title[:100])
    box.nth(1).click(); page.keyboard.type(f"{title}\n\nFuente: {it['url']}")
    page.locator("[name='VIDEO_MADE_FOR_KIDS_NOT_MADE_FOR_KIDS']").click()
    for _ in range(3):
        page.click("#next-button"); page.wait_for_timeout(1500)
    page.click("#second-container-expand-button")
    page.locator("ytcp-date-picker input").first.fill(when.strftime("%b %d, %Y")); page.keyboard.press("Enter")
    page.locator("#time-of-day-container input").first.fill(when.strftime("%I:%M %p").lstrip("0")); page.keyboard.press("Enter")
    page.locator("#done-button").click(timeout=1200000)
    page.wait_for_timeout(4000)
    it["status"] = "scheduled"

def studio_upload(d):
    from playwright.sync_api import sync_playwright
    pending = [i for i in d["items"] if i["status"] == "ready"]
    if not pending: return
    for it in pending: it["publishAt"] = next_slot(d, it["kind"])
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
                studio_upload_one(page, it); print("Programado:", it["title"], it["publishAt"])
            except Exception as e:
                it["status"] = "ready"; it["error"] = "Subir a mano (ver plan-publicacion.txt): " + str(e)[:200]
                print("No se pudo subir automaticamente:", it["title"], "->", e)
            save(d)

def main():
    d = load(); d.setdefault("config", {}); expand(d); save(d)
    for it in d["items"]:
        try:
            if it["status"] in ("pending", "processing"):
                it["status"] = "processing"; it.pop("error", None); save(d)
                print("Procesando", it["url"]); process(it, d["config"]); save(d)
        except Exception as e:
            it["status"] = "error"; it["error"] = str(e)[:300]; save(d); print("ERROR:", e)
    if NO_UPLOAD:
        write_plan([i for i in d["items"] if i["status"] == "ready"])
    else:
        try: studio_upload(d)
        except Exception as e: print("Fallo la subida automatica:", e)
    print("Listo. Videos terminados en la carpeta media. Plan: plan-publicacion.txt")

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
