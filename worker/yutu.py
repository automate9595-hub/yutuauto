"""Yutu worker: descarga -> recorte -> subtitulos -> subida programada a YouTube."""
import json, subprocess, sys, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
MEDIA = ROOT / "media"; MEDIA.mkdir(exist_ok=True)
QF = ROOT / "queue.json"
NO_UPLOAD = "--sin-subir" in sys.argv

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
    vid = it["id"]; src = MEDIA / f"{vid}.mp4"
    info = json.loads(run("yt-dlp", "-j", "--no-playlist", it["url"], capture_output=True, text=True).stdout)
    it["title"] = info["title"][:90]; dur = info.get("duration") or 60
    if not src.exists():
        run("yt-dlp", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
            "--no-playlist", "-o", MEDIA / f"{vid}.%(ext)s", it["url"])
    short = it["kind"] == "short"; clip = MEDIA / f"{vid}_clip.mp4"
    if short:
        start = 0 if dur <= 58 else dur * 0.1
        run("ffmpeg", "-y", "-ss", start, "-t", 58, "-i", src,
            "-vf", "crop=ih*9/16:ih,scale=1080:1920", "-c:v", "libx264", "-preset", "fast", "-crf", 21,
            "-c:a", "aac", clip)
    else:
        clip = src
    final = MEDIA / f"{vid}_final.mp4"
    if cfg.get("sub", True):
        srt = subtitles(clip, cfg.get("lang", "es"), short)
        style = "Alignment=2,FontSize=%d,Outline=2,Bold=1,MarginV=%d" % ((16, 90) if short else (20, 30))
        run("ffmpeg", "-y", "-i", clip.name, "-vf", f"subtitles={srt.name}:force_style='{style}'",
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

def youtube():
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]; tf = ROOT / "token.json"
    creds = Credentials.from_authorized_user_file(tf, scopes) if tf.exists() else None
    if not creds or not creds.valid:
        if creds and creds.refresh_token: creds.refresh(Request())
        else: creds = InstalledAppFlow.from_client_secrets_file(ROOT / "client_secret.json", scopes).run_local_server(port=0)
        tf.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload(yt, it, d):
    from googleapiclient.http import MediaFileUpload
    short = it["kind"] == "short"; it["publishAt"] = next_slot(d, it["kind"])
    title = it["title"] + (" #Shorts" if short else "")
    body = {"snippet": {"title": title[:100], "description": f"{title}\n\nFuente: {it['url']}", "categoryId": "22"},
            "status": {"privacyStatus": "private", "publishAt": it["publishAt"], "selfDeclaredMadeForKids": False}}
    r = yt.videos().insert(part="snippet,status", body=body,
                           media_body=MediaFileUpload(it["file"], chunksize=-1, resumable=True)).execute()
    it["youtubeId"] = r["id"]; it["status"] = "scheduled"

def main():
    d = load(); d.setdefault("config", {}); expand(d); save(d)
    yt = None
    for it in d["items"]:
        try:
            if it["status"] == "pending": print("Procesando", it["url"]); process(it, d["config"]); save(d)
            if it["status"] == "ready" and not NO_UPLOAD:
                yt = yt or youtube(); upload(yt, it, d); print("Programado:", it["title"], it["publishAt"]); save(d)
        except Exception as e:
            it["status"] = "error"; it["error"] = str(e)[:300]; save(d); print("ERROR:", e)
    print("Listo.")

if __name__ == "__main__": main()
