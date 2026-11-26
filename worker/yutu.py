"""Yutu worker: descarga -> recorte -> efectos -> subtitulos -> subida a YouTube Studio (sin Google Cloud)."""
import json, math, os, re, shutil, subprocess, sys, time, pathlib, urllib.request, datetime as dt
import threading, concurrent.futures as cf
import efectos, ia, voz, cdp, titulos, tiktok, redes, aprendizaje, atomico
ROOT = pathlib.Path(__file__).parent
MEDIA = ROOT / "media"; MEDIA.mkdir(exist_ok=True)
QF = ROOT / "queue.json"; CF = ROOT / "cancel.json"
NO_UPLOAD = "--sin-subir" in sys.argv

class Cancelled(Exception): pass
class SubidaInterrumpida(Exception): pass

MAX_INTENTOS = 5      # reintentos dentro de una misma subida (reanuda sola)
MAX_AUTO = 8          # reintentos automáticos posteriores (los lanza el vigilante del servidor)
MAX_SHORT = 180       # YouTube Shorts admite hasta 3 minutos
STALL_S = 420         # si el % no avanza en 7 min, se considera cortada

def fid(it):
    """Nombre base de los archivos del item: el id del video, más _pN si es la parte N de un video largo."""
    return it["id"] + (f"_p{it['part']}" if (it.get("parts") or 1) > 1 else "")

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
         "sub": .10 if cfg.get("ia_mode", "alternar") != "apagado" else 0, "edit": .40, "up": .20 if upload else 0}
    tot = sum(w.values()); acc = 0; plan = {}
    for k in ("dl", "ia", "sub", "edit", "up"):
        plan[k] = (acc / tot, w[k] / tot); acc += w[k]
    return plan

_PASADA = str(os.getpid()) + "-" + str(int(time.time()))      # cada ejecución del proceso es una pasada nueva
LABEL = {"dl": "Descargando", "ia": "Analizando con IA", "sub": "Leyendo el clip", "edit": "Editando", "up": "Subiendo"}
def set_prog(it, stage, frac, force=False):
    off, wt = PLAN.get(stage, (0, 1))
    pct = int(round(100 * (off + wt * max(0.0, min(1.0, frac)))))
    if pct < int(it.get("pct") or 0) and it.get("_pasada") == _PASADA: pct = int(it.get("pct") or 0)        # un motor que reintenta no hace "volver atrás" la barra
    it["_pasada"] = _PASADA; it["stage"] = LABEL[stage]; it["pct"] = pct
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
_SL = threading.Lock()
def save(d):
    with _SL:                                   # editar y subir ahora corren a la vez: un solo guardado por vez
        atomico.escribir(QF, json.dumps(d, indent=2, ensure_ascii=False))

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

def download(it, src, cb=None, h264=False):
    """Descarga con yt-dlp probando varias variantes (Chrome simulado / cookies / simple). Si es TikTok y ninguna sirve,
    baja el archivo con el Chrome del worker. El error que se muestra es el REAL, no un 'returned non-zero'."""
    cb = cb or (lambda f: set_prog(it, "dl", f))
    url = it.get("url") or ""; ultimo = ""
    for var in tiktok.variantes(url):
        cmd = [sys.executable, "-m", "yt_dlp", "--newline", "-N", "4", "--retries", "5", "--fragment-retries", "5", "--no-mtime"] + var + ["--progress-template", "download:[DL] %(progress._percent_str)s",
               "--ffmpeg-location", FFMPEG, "-f", ("bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][vcodec^=avc]+ba/" if h264 else "") + "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
               "--merge-output-format", "mp4", "--no-playlist"] + (["--force-overwrites"] if h264 else []) + ["-o", str(MEDIA / f"{it['id']}.%(ext)s"), url]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        idx, last, tail = 0, 0.0, []
        for line in p.stdout:
            if cancel_requested(it): p.terminate(); raise Cancelled()
            m = re.search(r"\[DL\]\s*([\d.]+)%", line)
            if m:
                v = float(m.group(1))
                if v < last - 20: idx = 1                      # empezo el segundo flujo (audio)
                last = v
                cb((0.85 * v / 100) if idx == 0 else 0.85 + 0.15 * v / 100)
            else: tail.append(line.strip())
        if p.wait() == 0 and src.exists(): cb(1.0); return
        if p.returncode == 0: ultimo = "yt-dlp terminó pero no dejó el archivo"
        else: ultimo = tiktok.limpiar_error("\n".join(tail))
        print("  yt-dlp:", ultimo[:160])
    if "tiktok.com" in url:
        print("  yt-dlp no pudo con TikTok: pruebo con el Chrome del worker...")
        try: tiktok.descargar_web(url, src, cb, lambda: check_cancel(it)); return
        except Cancelled: raise
        except Exception as e: ultimo += " | Chrome del worker: " + str(e)[:150]
    raise RuntimeError("No se pudo descargar: " + ultimo[:300])

PRE_INFO, DLP, PRE_PEND = {}, {}, set()
import memoria
PRE_SEM = threading.Semaphore(1 if memoria.poca_ram() else 2)        # PC con poca RAM: 1 descarga por adelantado; si no, 2
_REL = set()

def info_video(it):
    return tiktok.info(it["url"])

def prefetch(items):
    """Descarga (y lee los datos de) los siguientes videos mientras el actual se edita: la red y la CPU trabajan a la vez."""
    lista, vistos = [], set()
    for it in items:
        if it.get("type") == "video" and it.get("status") == "pending" and it["id"] not in vistos: vistos.add(it["id"]); lista.append(it)
    PRE_PEND.update(i["id"] for i in lista)
    def job():
        for it in lista:
            PRE_SEM.acquire()
            vid = it["id"]
            try:
                if cancel_requested(it): continue
                PRE_INFO[vid] = info_video(it)
                src = MEDIA / f"{vid}.mp4"
                if not src.exists(): download(it, src, lambda f, v=vid: DLP.__setitem__(v, f))
            except Exception as e: print("  (descarga anticipada falló, se reintenta al procesar):", str(e)[:100])
            finally: PRE_PEND.discard(vid)
    if lista: threading.Thread(target=job, daemon=True).start()

def esperar_pre(it):
    """Si el video se está bajando por adelantado, espera mostrando su progreso. Devuelve los datos del video o None."""
    vid = it["id"]
    while vid in PRE_PEND:
        check_cancel(it); set_prog(it, "dl", DLP.get(vid, 0.0)); time.sleep(0.4)
    return PRE_INFO.get(vid)

SEGF = ROOT / "segmentos-usados.json"; _SGL = threading.Lock()

def seg_leer():
    try: return json.loads(SEGF.read_text("utf-8"))
    except Exception: return {}

def seg_libre(vid, mia, a, L, dur, margen=0.5):
    """Inicio (cerca de 'a') de un tramo de L s que NO pise ningún segundo ya usado de este video en otro Short. None si no queda ninguno."""
    usados = [r for f, r in seg_leer().get(vid, {}).items() if f != mia]
    choca = lambda s: any(s < r[1] + margen and s + L > r[0] - margen for r in usados)
    if not choca(a): return a
    for d in range(1, int(dur) + 1):
        for s in (a - d, a + d):
            if 0 <= s <= dur - L and not choca(s): return float(s)
    return None

def seg_registrar(vid, mia, a, L):
    with _SGL:
        d = seg_leer(); d.setdefault(vid, {})[mia] = [round(a, 2), round(a + L, 2)]
        atomico.escribir(SEGF, json.dumps(d))

def srt_time(s):
    h, m, sec = int(s // 3600), int(s % 3600 // 60), s % 60
    return f"{h:02}:{m:02}:{sec:06.3f}".replace(".", ",")

def subtitles(it, src, start, length, cfg, short):
    """Transcribe solo el tramo elegido y arma subtitulos cortos (estilo Shorts)."""
    full = it.pop("_full_words", None)
    if full:                                    # ya se transcribió todo en la nube para elegir el tramo: se reutiliza (ahorra minutos)
        words = [voz.Palabra(w.start - start, w.end - start, w.word) for w in full if start - 0.05 <= w.start < start + length]
        for w in words: w.word = w.word if w.word.startswith(" ") else " " + w.word
        print("  Subtítulos: reutilizo la transcripción del análisis (sin repetir el trabajo).")
    else: words = voz.palabras(FFMPEG, src, start, length, cfg.get("lang", "es"), cfg.get("model", "small"),
                         lambda f: set_prog(it, "sub", f), lambda: check_cancel(it),
                         motor=cfg.get("stt", "auto"), titulo=it.get("title", ""), solo_nube=True)       # nunca el modelo local (pesa mucho en 2 GB)
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
    srt = MEDIA / f"{fid(it)}.srt"
    with open(srt, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(caps, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(max(b, a + 0.3))}\n{t.upper() if cfg.get('sub_caps') else t}\n\n")
    return srt

def transcribe_full(it, src, cfg, dur):
    """Transcripcion de todo el video, solo para que la IA elija el mejor tramo (si fue en la nube se reutiliza en los subtitulos)."""
    words = voz.palabras(FFMPEG, src, 0, dur, cfg.get("lang", "es"), "base",
                         lambda f: set_prog(it, "ia", f), lambda: check_cancel(it), motor="rapido", titulo=it.get("title", ""),
                         solo_nube=True)            # solo en la nube: nunca el modelo local
    if str(getattr(voz, "ULTIMO", "")).startswith("groq") and cfg.get("stt", "auto") in ("auto", "groq_turbo", "groq_v3"): it["_full_words"] = words
    return voz.frases(words)

def srt_frases(srt):
    """(inicio, fin, texto) de cada subtitulo del .srt."""
    out = []
    try:
        for bl in pathlib.Path(srt).read_text("utf-8").strip().split("\n\n"):
            ln = bl.strip().splitlines()
            m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)", ln[1]) if len(ln) >= 3 else None
            if m:
                g = [int(x) for x in m.groups()]; out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, " ".join(ln[2:])))
    except Exception: pass
    return out

def eventos_respaldo(frases, L, permitidos):
    """Sin IA: zoom/efecto en el arranque y en las frases con énfasis (!, ?), alternando efectos."""
    ciclo = [k for k in ("zoomin", "flash", "pulse", "zoomin", "shake", "glitch") if k in permitidos] or ["zoomin"]
    ev, ult, k = [{"t": 0.3, "dur": 1.8, "fx": ciclo[0]}], 0.3, 1
    for a, b, t in frases:
        if a - ult >= 3.2 and a < L - 1 and (t.strip()[-1:] in "!?" or a - ult >= 5.5):
            ev.append({"t": round(a, 2), "dur": 1.5, "fx": ciclo[k % len(ciclo)]}); ult = a; k += 1
    return ev[:14]

def srt_text(srt):
    if not srt: return ""
    try: return " ".join(l.strip() for l in pathlib.Path(srt).read_text("utf-8").splitlines() if l.strip() and not l.strip().isdigit() and "-->" not in l)
    except Exception: return ""

def window(it, cfg, dur, ai_start=None):
    """Tramo del video original que se conserva: (inicio, duracion)."""
    f = lambda k, d=0: float(cfg.get(k) or d)
    if it["kind"] == "short":
        L = min(f("short_len", 58), MAX_SHORT, dur)
        mode = cfg.get("cut_mode", "auto")
        if it.get("split_start") is not None: start = min(max(float(it["split_start"]), 0), max(dur - L, 0))
        elif mode == "inicio" or dur <= L: start = 0
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
    fx = "on" if (cfg.get("fx_list") or cfg.get("fx_events")) else "none"; vf = []
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
    vf += efectos.build_eventos(cfg.get("fx_events"), W, H, L, cfg.get("fx_power", 1))
    if cfg.get("vivid"): vf.append("eq=contrast=1.06:saturation=1.25:brightness=0.01,unsharp=5:5:0.6")
    if cfg.get("vignette"): vf.append("vignette=PI/5")
    if cfg.get("fade"): vf.append(f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(L - 0.5, 0):.2f}:d=0.5")
    # los subtítulos NUNCA se queman en el video
    return ",".join(vf)

def build_af(cfg, L):
    af = []
    if cfg.get("loudnorm"): af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if cfg.get("fade"): af += ["afade=t=in:st=0:d=0.5", f"afade=t=out:st={max(L - 0.5, 0):.2f}:d=0.5"]
    return ",".join(af)

def encode(it, src, start, L, vf, af, final, tolerante=False, audio=None):
    """audio: None = el del video; Path = audio rescatado aparte; "" = sin audio."""
    memoria.esperar(300, 40)
    hilos = str(min(os.cpu_count() or 2, 2))                                   # pocos hilos = menos RAM (PC de 2 GB)
    args = [str(FFMPEG), "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", "-ss", str(start), "-t", str(L)]
    if tolerante: args += ["-err_detect", "ignore_err", "-fflags", "+discardcorrupt+genpts"]        # sigue aunque haya cuadros o audio dañados
    args += ["-i", src.name]
    if isinstance(audio, pathlib.Path): args += ["-i", audio.name]
    args += ["-vf", vf]
    if tolerante: args += ["-max_error_rate", "1.0"]
    if isinstance(audio, pathlib.Path): args += ["-map", "0:v:0", "-map", "1:a:0"]
    if audio == "": args += ["-an"]
    elif af: args += ["-af", af]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-threads", hilos, "-crf", "22", "-pix_fmt", "yuv420p"]
    if audio != "": args += ["-c:a", "aac", "-b:a", "160k"]
    args += ["-movflags", "+faststart", final.name]
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

def _falla_de_archivo(e):
    """True si FFmpeg falló por el archivo (audio AAC / cuadros dañados, descarga cortada...). False si fue por subtítulos, filtros o disco."""
    return not re.search(r"subtitle|libass|fontconfig|filtergraph|no such filter|no such file|permission denied|no space left", str(e.output or ""), re.I)

def _audio_rescate(src, start, L):
    """Saca el audio aparte ignorando lo dañado. Devuelve el .wav o None."""
    wav = MEDIA / (src.stem + "_rescate.wav")
    try:
        subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", "-err_detect", "ignore_err", "-ss", str(start), "-t", str(L), "-i", src.name,
                        "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", wav.name], cwd=MEDIA, capture_output=True, timeout=600)
    except Exception: pass
    return wav if wav.exists() and wav.stat().st_size > 4096 else None

def _encode_resiliente(it, src, start, L, vf, af, final):
    """El video SIEMPRE termina de editarse: si FFmpeg tropieza con el archivo (error de decodificación, audio AAC dañado...) escala solo:
    1) edita saltando lo dañado, 2) baja el video de nuevo limpio, 3) rescata el audio aparte, 4) como último recurso, sin audio."""
    try: return encode(it, src, start, L, vf, af, final)
    except subprocess.CalledProcessError as e:
        if not _falla_de_archivo(e): raise
    print("  FFmpeg tropezó con el archivo: lo edito saltando lo dañado…")
    try: return encode(it, src, start, L, vf, af, final, True)
    except subprocess.CalledProcessError as e:
        if not _falla_de_archivo(e): raise
    print("  Sigue fallando: bajo el video de nuevo, limpio (H.264)…")
    bak = src.with_suffix(".bak")
    try: src.replace(bak)
    except Exception: bak = None
    try:
        download(it, src, None, True)
        if bak: bak.unlink(missing_ok=True)
    except Cancelled: raise
    except Exception as e:
        print("  No pude bajarlo de nuevo:", str(e)[:120])
        if bak and bak.exists(): bak.replace(src)
    try: return encode(it, src, start, L, vf, af, final, True)
    except subprocess.CalledProcessError as e:
        if not _falla_de_archivo(e): raise
    print("  Rescato el audio por separado…")
    wav = _audio_rescate(src, start, L)
    try: return encode(it, src, start, L, vf, af, final, True, wav if wav else "")
    finally:
        if wav: wav.unlink(missing_ok=True)

def reparto_parejo(dur, L, n):
    """n inicios repartidos parejo a lo largo del video, cada tramo centrado en su porción (sin solaparse si cabe)."""
    slot = dur / n
    return [max(0.0, min(dur - L, i * slot + max(0.0, (slot - L) / 2))) for i in range(n)]

def planificar_partes(it, cfg, src, dur, L):
    """Decide de una vez el inicio de TODOS los Shorts que salen de este video largo (IA o reparto parejo)."""
    hermanos = sorted([x for x in D["items"] if x.get("id") == it["id"] and x.get("parts") == it.get("parts") and x.get("kind") == "short"],
                      key=lambda x: x.get("part", 0)) if D else [it]
    n = len(hermanos); starts = None; prov = ""
    if cfg.get("split_mode", "auto") == "auto" and ia_activa(cfg) and dur <= 3600 and not it.get("_noia"):
        print(f"  [IA] Buscando los {n} mejores momentos para {n} Shorts...")
        try:
            segs = transcribe_full(it, src, cfg, dur)
            r = ia.momentos(cfg.get("ia_mode", "alternar"), it.get("title", ""), segs, dur, L, n) if segs else None
            if r: starts, prov = r["inicios"], r["prov"]; print(f"  [IA {prov}] Momentos elegidos: " + ", ".join(f"{x:.0f}s" for x in starts) + ". " + r["motivo"])
        except Cancelled: raise
        except Exception as e: print("  [IA] No se pudo analizar:", str(e)[:150])
        set_prog(it, "ia", 1.0, True)
    if not starts or len(starts) < n:
        starts = reparto_parejo(dur, L, n); print(f"  Reparto parejo de {n} Shorts: " + ", ".join(f"{x:.0f}s" for x in starts))
    for x, st in zip(hermanos, starts): x["split_start"] = round(st, 1)
    save(D)

def split_items(d):
    """Un Short con 'n' > 1 (o split_n de la config) se convierte en n items independientes: video:ID#1 ... video:ID#n."""
    cfg = d.get("config", {}); out = []
    for it in d["items"]:
        n = min(int(it.get("n") or cfg.get("split_n") or 1), 30)
        if it.get("kind") != "short" or it.get("type") != "video" or it.get("parts") or "#" in it["key"] or it.get("status") != "pending" or n <= 1:
            out.append(it); continue
        L = min(float(cfg.get("short_len") or 58), MAX_SHORT)
        try: dur = info_video(it).get("duration")
        except Exception as e: dur = None; print("  No pude leer la duración para dividir:", str(e)[:100])
        if dur and int(dur // L) < n:
            n = max(1, int(dur // L)); print(f"  El video dura {dur:.0f}s: solo caben {n} Shorts de {L:.0f}s sin repetir partes.")
        if n <= 1: out.append(it); continue
        for p in range(1, n + 1):
            c = dict(it); c.update(key=f"{it['key']}#{p}", part=p, parts=n, status="pending"); out.append(c)
        print(f"  {it['url']} -> {n} Shorts (uno cada {cfg.get('split_gap') or 0} h)")
    d["items"] = out

def process_gen(it, cfg):
    """Video creado 100 % por IA (piloto creador): guion + voz + imagenes + subtitulos."""
    import generador
    it["pct"] = 0; it["stage"] = "Creando con IA"; save(D)
    def prog(f, etapa=None):
        it["pct"] = int(round(100 * f)); it["stage"] = etapa or "Creando con IA"
        if time.time() - _last[0] > 0.7: _last[0] = time.time(); save(D)
    try: r = generador.crear(it, cfg, MEDIA, FFMPEG, prog, lambda: check_cancel(it), titulos.usados([i.get("final_title") or i.get("ia_title") for i in D["items"]]))
    except Exception: generador.reembolsar(it); raise
    it["title"] = r["titulo"][:90]; it["ia_title"], it["ia_desc"] = r["titulo"], r["descripcion"]; it["ia"] = r["ayuda"]
    it["file"] = str(MEDIA / f"{fid(it)}_final.mp4"); it["status"] = "ready"
    if not PLAN.get("up", (0, 0))[1]: it["pct"] = 100; it["stage"] = "Listo"
    save(D)

def process(it, cfg):
    if not FFMPEG: raise RuntimeError("No encuentro FFmpeg. Cierra el worker y ejecuta 2-INSTALAR-Y-EJECUTAR.bat de nuevo.")
    if it.get("type") == "gen": return process_gen(it, cfg)
    vid = it["id"]; src = MEDIA / f"{vid}.mp4"; short = it["kind"] == "short"
    it["pct"] = 0; it["stage"] = "Preparando"; it.pop("est", None); save(D)
    check_cancel(it)
    info = esperar_pre(it) or info_video(it)
    it["title"] = (info.get("title") or it.get("title") or it["url"])[:90]; dur = info.get("duration") or 60
    if info.get("thumbnail"): it["thumb"] = info["thumbnail"]
    lo, hi = int(it.get("dmin") or 0), int(it.get("dmax") or 0)           # límite de duración elegido en el piloto
    if (lo or hi) and info.get("duration"):
        d0 = float(info["duration"]); fm = lambda x: f"{x / 60:.1f} min".replace(".0 ", " ")
        if (lo and d0 < lo) or (hi and d0 > hi):
            raise RuntimeError(f"Descartado: dura {fm(d0)} y tu límite es {fm(lo) if lo else 'sin mínimo'} a {fm(hi) if hi else 'sin máximo'}.")
    if not src.exists():
        print("  [1/3] Descargando...")
        download(it, src)
    else: set_prog(it, "dl", 1.0, True)
    check_cancel(it)
    if short and it.get("parts") and it.get("split_start") is None:
        planificar_partes(it, cfg, src, dur, min(float(cfg.get("short_len") or 58), MAX_SHORT, dur))
    start, L = window(it, cfg, dur)
    modo, ayuda = cfg.get("ia_mode", "alternar"), []
    if ia_activa(cfg) and cfg.get("ia_cut") and dur > L + 2 and dur <= 1800 and not it.get("_noia") and not it.get("parts"):
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
    if short:                                  # nunca la misma parte (ni los mismos segundos) de un video en dos Shorts
        ns = seg_libre(vid, fid(it), start, L, dur)
        if ns is None: raise RuntimeError("Ya se usaron todas las partes de este video: no queda un tramo distinto para otro Short.")
        if abs(ns - start) > 0.01: print(f"  Ese tramo ya se usó en otro Short; tomo otro distinto desde {ns:.0f}s."); start = ns
    print(f"  Tramo: {start:.0f}s -> {start + L:.0f}s ({L:.0f}s de {dur:.0f}s)")
    srt = None
    if ia_activa(cfg):                                     # solo se LEE lo que se dice (nube), para que la IA escriba bien título y descripción; no se agrega ningún subtítulo
        print("  [2/3] Leyendo lo que se dice en el clip (no se agregan subtítulos)...")
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
    if cfg.get("ia_zoom", True) and (short or L <= 240) and not ecfg.get("fx_events"):
        permitidos = [k for k in (cfg.get("fx_list") or []) if k in efectos.EFECTOS] or list(efectos.EFECTOS)
        fr = srt_frases(srt) if srt else []
        r = ia.eventos(modo, it["title"], fr, it["kind"], L, permitidos) if ia_activa(cfg) else None
        if r: ecfg = dict(ecfg, fx_events=r["eventos"]); ayuda.append("zooms " + r["prov"]); print(f"  [IA {r['prov']}] {len(r['eventos'])} zooms/efectos en momentos clave. {r['motivo']}")
        else:
            ecfg = dict(ecfg, fx_events=eventos_respaldo(fr, L, permitidos)); print("  Zooms automáticos por ritmo del discurso (sin IA disponible).")
    th_txt = None
    if ia_activa(cfg) and cfg.get("ia_text"):                       # el título se piensa mientras FFmpeg codifica
        res_txt = {}
        def _txt():
            try: res_txt["r"] = ia.textos(modo, it["title"], texto, it["kind"], titulos.usados([i.get("final_title") or i.get("ia_title") for i in D["items"]]) + [it["title"]], cfg.get("idioma_titulo", ""))
            except Exception as e: res_txt["e"] = e
        th_txt = threading.Thread(target=_txt, daemon=True); th_txt.start()
    final = MEDIA / f"{fid(it)}_final.mp4"
    print("  [3/3] Editando video...")
    vf, af = build_vf(ecfg, short, L, srt), build_af(ecfg, L)
    if not short and not vf.replace("setsar=1", "").strip(",") and not af and start == 0 and L >= dur - 1:
        shutil.copy(src, final); set_prog(it, "edit", 1.0, True)   # completo y sin efectos: no se recodifica
    else:
        try: _encode_resiliente(it, src, start, L, vf, af, final)
        except subprocess.CalledProcessError as e: raise RuntimeError("FFmpeg: " + str(e.output)[:200])
    if th_txt:
        th_txt.join(120); r = res_txt.get("r")
        if r: it["ia_title"], it["ia_desc"] = r["titulo"], r["descripcion"]; ayuda.append("título " + r["prov"]); print(f"  [IA {r['prov']}] Título: {r['titulo']}")
    it["ia"] = " · ".join(ayuda)
    if short: seg_registrar(vid, fid(it), start, L)
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

# (up_progress está más abajo, junto con la subida con reanudado automático)

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
var re=/\bno\b[\s,]+(no\s+)?(es|est[aá]|son|fue)[^]*ni\S{1,3}os|not\s+made\s+for\s+kids|NOT_MADE_FOR_KIDS/i;
var a=window.__A("tp-yt-paper-radio-button,[role=radio],input[type=radio],ytkc-made-for-kids-select label,ytkc-made-for-kids-select *");
var best=null;
for(var i=0;i<a.length;i++){var e=a[i];
 var t=((e.innerText||e.textContent||'')+' '+(e.getAttribute('name')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.id||'')).trim();
 if(!re.test(t))continue;
 var r=e.getBoundingClientRect();
 var esRadio=/radio/i.test(e.tagName+(e.getAttribute('role')||''));
 var score=(r.width>0?0:1000)+(esRadio?0:50)+t.length;
 if(!best||score<best.score)best={e:e,score:score};}
if(!best){var c=[];for(var j=0;j<a.length;j++){var q=a[j],rr=q.getBoundingClientRect();if(rr.width<=0||rr.height<=0)continue;
 if(!/radio/i.test(q.tagName+(q.getAttribute('role')||'')))continue;
 if(/ni[ñn]os|kids|children/i.test(q.innerText||''))c.push(q)}
 if(c.length===2)best={e:c[1],score:0}}
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

JS_PUBLICO = r"""(function(){var a=window.__A("tp-yt-paper-radio-button[name='PUBLIC'],tp-yt-paper-radio-button,[role=radio]");
var res=null;for(var i=0;i<a.length;i++){var e=a[i],r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)continue;
var t=((e.getAttribute('name')||'')+' '+(e.innerText||'')).trim();
if(/^PUBLIC\b/.test(e.getAttribute('name')||'')||/^\s*(p[uú]blico|public)\b/i.test(e.innerText||'')){
 res={on:e.getAttribute('aria-checked')==='true'||e.hasAttribute('checked'),x:r.left+r.width/2,y:r.top+r.height/2};break}}
return res})()"""

def publico_marcado(tab):
    try:
        r = tab.eval(JS_PUBLICO); return bool(r and r.get("on"))
    except Exception: return False

def elegir_publico(tab):
    """Marca 'Publico' en Visibilidad (por name o por texto, español/ingles) y comprueba que quedo marcado."""
    for _ in range(4):
        r = tab.eval(JS_PUBLICO)
        if not r: time.sleep(1); continue
        if r["on"]: return True
        for t in ("mousePressed", "mouseReleased"):
            tab.call("Input.dispatchMouseEvent", {"type": t, "x": r["x"], "y": r["y"], "button": "left", "clickCount": 1})
        time.sleep(0.7)
    r = tab.eval(JS_PUBLICO)
    return bool(r)          # si se vio y se hizo clic, seguimos: algunas versiones no exponen el estado marcado

def estado_botones(tab):
    try:
        return tab.eval("window.__A('#next-button,#done-button').map(function(e){var r=e.getBoundingClientRect();"
                        "return e.id+' visible='+(r.width>0&&r.height>0)+' disabled='+(e.hasAttribute('disabled')||e.getAttribute('aria-disabled')==='true')}).join(' ; ')")
    except Exception as e: return str(e)[:60]

RE_PIE_SUBE = re.compile(r"subi[eé]ndose|subiendo|uploading", re.I)
RE_PIE_COMP = re.compile(r"comprobando|checking", re.I)
RE_PIE_PROC = re.compile(r"procesando|processing", re.I)
RE_PIE_OK = re.compile(r"comprobaciones completadas|checks complete|no se han encontrado problemas|no issues found|se han encontrado|found (?:an? )?(?:issue|copyright)|infracci|may restrict|podr[ií]a", re.I)

JS_PIE = r"""(function(){var d=window.__D('ytcp-uploads-dialog');if(!d)return '';var e=window.__A('ytcp-video-upload-progress',d)[0]||window.__D('.left-button-area',d)||window.__D('#footer',d);return e?(e.innerText||''):''})()"""
JS_OKDLG = r"""(function(){var d=window.__D('ytcp-uploads-dialog');if(!d)return false;return /comprobaciones completadas|no se han encontrado problemas|checks complete|no issues found/i.test(d.innerText||'')})()"""

def texto_pie(tab):
    """SOLO el pie del cuadro de subida actual (no el panel flotante, que muestra OTRAS subidas, p. ej. 'Subiéndose 19 %')."""
    try: return (tab.eval(JS_PIE) or "").replace("\n", " ")
    except Exception: return ""

def estado_pie(tab):
    """Que dice Studio abajo a la izquierda del cuadro de subida: 'subiendo' -> 'procesando'/'comprobando' -> 'listo'."""
    try:
        if tab.eval(JS_OKDLG): return "listo", "Comprobaciones completadas"
    except Exception: pass
    t = texto_pie(tab)
    if RE_PIE_SUBE.search(t): return "subiendo", t
    if RE_PIE_COMP.search(t): return "comprobando", t
    if RE_PIE_PROC.search(t): return "procesando", t
    if RE_PIE_OK.search(t): return "listo", t
    return "?", t

def esperar_comprobaciones(tab, it, t0, size_mb, chk, limite=None):
    """NO avanza con 'Siguiente' mientras Studio esté subiendo o comprobando: espera a que la comprobación llegue a 100 %
    (el pie pasa de 'Subiéndose…' a 'Comprobando…' y termina en 'Comprobaciones completadas')."""
    limite = limite or max(1800, int(size_mb * 25) + 1200); fin = time.time() + limite; vacio = 0; ult = None; ini = time.time()
    while time.time() < fin:
        chk(); up_progress(tab, it, t0, size_mb)
        e, t = estado_pie(tab)
        if e != ult: print(f"  Studio: {e} · {t[:90]}"); ult = e
        paso(f"esperando a Studio ({e}): {t[:70]}")
        if e == "listo": print(f"  Comprobaciones terminadas ({int(time.time() - ini)} s). Sigo con 'Siguiente'."); return True
        vacio = vacio + 1 if e == "?" else 0
        if vacio >= 8: return False                  # el pie no muestra nada: no hay nada que esperar
        time.sleep(1.5)
    print("  Studio tardó demasiado en comprobar; sigo igual (si pregunta, 'Publicar de todas formas').")
    return False

JS_FIRMA = r"""(function(){var d=window.__D('ytcp-uploads-dialog');if(!d)return '';var c=window.__D('#scrollable-content',d)||d;
return (c.innerText||'').replace(/\s+/g,' ').slice(0,200)+'|'+window.__A('#textbox',d).length+'|'+window.__A('tp-yt-paper-radio-button',d).filter(function(e){return e.getBoundingClientRect().width>0}).length})()"""
def firma(tab):
    try: return tab.eval(JS_FIRMA) or ""
    except Exception: return ""

def avanzar_hasta_visibilidad(tab, it, t0, size_mb, chk, limite=300):
    """1) espera a que Studio termine de subir y COMPROBAR (100 %). 2) toca 'Siguiente' en cada etapa y verifica que la pantalla cambió.
    Si el botón no responde, escala: forzar clic, 'no es para niños', saltar por el indice de etapas, y deja diagnostico."""
    esperar_comprobaciones(tab, it, t0, size_mb, chk)
    inicio = time.time(); n = 0; trabado = None; fallos = 0; diag = False
    while time.time() - inicio < limite:
        chk(); up_progress(tab, it, t0, size_mb)
        if tab.eval(JS_PUBLICO): return
        if tab.habilitado("#next-button"):
            f0 = firma(tab); n += 1; trabado = None; paso(f"tocando 'Siguiente' ({n})")
            tab.clic_visible("#next-button", True, fallos >= 1)
            cambio = False
            for _ in range(10):
                time.sleep(0.5); chk()
                if firma(tab) != f0 or tab.eval(JS_PUBLICO): cambio = True; break
            if cambio: fallos = 0; time.sleep(0.6); continue
            fallos += 1; print(f"  'Siguiente' no cambió la pantalla (intento {fallos}); pruebo otra forma.")
            if fallos == 2: marcar_no_ninos(tab, chk)
            elif fallos == 3: tab.clic_texto(r"^(visibilidad|visibility)$", "ytcp-stepper-step, ytcp-stepper-step *, [role=tab], #step-badge-3, .step-badge, button"); time.sleep(1.5)
            elif fallos >= 4 and not diag:
                diag = True; guardar_diagnostico(tab, RuntimeError("'Siguiente' no avanza"))
            continue
        trabado = trabado or time.time(); t = time.time() - trabado
        STEP[0] = f"esperando que 'Siguiente' se habilite ({int(t)} s) - {estado_botones(tab)}"
        if t > 6 and int(t) % 10 == 6: marcar_no_ninos(tab, chk)
        if t > 40 and int(t) % 10 == 0: tab.clic_visible("#next-button", False, True); time.sleep(2)
        time.sleep(1)
    raise RuntimeError("No pude pasar a la pantalla de Visibilidad: " + estado_botones(tab))

PATRON_FORZAR = r"^(publicar de todas formas|publicar igualmente|publish anyway)$"
TAGS_BOTON = "ytcp-button, button, tp-yt-paper-button, [role=button], a"

def publicar_de_todas_formas(tab):
    """Si Studio muestra 'Aún estamos comprobando tu contenido', toca 'Publicar de todas formas' (nunca 'Entendido')."""
    try: return bool(tab.clic_texto(PATRON_FORZAR, TAGS_BOTON))
    except Exception: return False

def id_de_url(u):
    m = re.search(r"(?:youtu\.be/|shorts/|[?&]v=)([\w-]{11})", u or ""); return m.group(1) if m else None

def verificar_publicado(tab, cid, it, chk):
    """Mira la lista de contenido de Studio y comprueba que el video figure como Público. Devuelve 'publico', 'privado' o None (no se pudo ver)."""
    vid = id_de_url(it.get("yt_url"))
    if not vid: return None
    try:
        tab.ir(f"https://studio.youtube.com/channel/{cid}/videos/{'short' if it.get('kind') == 'short' else 'upload'}")
        js = ("(function(){var a=window.__A(\"a[href*='/video/" + vid + "/']\");if(!a.length)return null;var e=a[0],t='';"
              "for(var i=0;i<10&&e;i++){e=e.parentElement;if(e&&e.tagName&&/ROW/i.test(e.tagName)){t=e.innerText;break}}"
              "if(!t){e=a[0];for(var j=0;j<6&&e.parentElement;j++)e=e.parentElement;t=e.innerText}return t})()")
        fin = time.time() + 75; txt = None
        while time.time() < fin:
            chk()
            try: txt = tab.eval(js)
            except Exception: txt = None
            if txt: break
            time.sleep(2)
        if not txt: return None
        t = txt.lower()
        if re.search(r"\bp[uú]blico\b|\bpublic\b", t) and not re.search(r"privado|private|no listado|unlisted|programado|scheduled", t): return "publico"
        if re.search(r"privado|private", t): return "privado"
    except Cancelled: raise
    except Exception as e: print("  No pude verificar la visibilidad:", str(e)[:80])
    return None

def textos_para_subir(it, cfg):
    """Titulo y descripcion finales. GARANTIA: nunca es igual (ni parecido) al titulo del video copiado, al original ni a uno ya usado.
    Devuelve (titulo, descripcion): el titulo siempre existe."""
    if it.get("final_title") and it.get("ia_desc"):
        tg = titulos.etiquetas((cfg or {}).get("hashtags_base"))
        return titulos.ajustar(titulos.sin_video(titulos.formatear(it["final_title"], 100), tg), 100), titulos.sin_video(titulos.formatear_desc(it["ia_desc"], it["final_title"]), tg)      # reintento/reanudación: ya tiene su título único
    original = it.get("title", "") if it.get("type") != "gen" else ""
    orig_ia = titulos.limpiar_original(orig_ia) or "(sin título)"       # sin hashtags ni "video"
    tags = titulos.etiquetas((cfg or {}).get("hashtags_base")); uso_fallback = False
    prohibidos = titulos.usados([i.get("final_title") or i.get("ia_title") for i in (D["items"] if D else []) if i is not it]) + ([original] if original else [])
    t, desc = (it.get("ia_title") or "").strip(), (it.get("ia_desc") or "").strip()
    srt = MEDIA / f"{fid(it) if it.get('id') else ''}.srt"
    texto = srt_text(srt if srt.exists() else None)
    modo = (cfg or {}).get("ia_mode", "alternar"); activa = bool(cfg) and ia_activa(cfg) and cfg.get("ia_text", True)
    for intento in range(4):
        if t and not titulos.repetido(t, prohibidos): break
        if t: print(f"  Título repetido o igual al original, pido otro: {t[:60]}"); prohibidos = prohibidos + [t]; t = ""
        if activa:
            try:
                paso("pidiendo título y descripción nuevos a la IA")
                r = ia.textos(modo, orig_ia, texto, it.get("kind", "video"), prohibidos, (cfg or {}).get("idioma_titulo", ""))
                if r: t, desc = r["titulo"].strip(), r["descripcion"].strip(); print(f"  [IA {r['prov']}] Título: {t}")
            except Exception as e: print("  [IA] No pude generar el título:", str(e)[:120])
    if not t or titulos.repetido(t, prohibidos):
        tema = (cfg or {}).get("tema_titulo", "") or ("Mobile Legends" if "mobile legends" in (original + " " + texto).lower() else "")
        t = titulos.fallback(texto, tema, prohibidos, len(titulos.usados()) + 1); uso_fallback = True
        print("  Título propio (sin IA disponible):", t)
    if activa and t:                           # control de calidad: claro, específico y con razón para hacer clic (lo que Yutu aprendió); si es flojo se pide uno mejor
        sc, probs = aprendizaje.evaluar(t)
        for _ in range(2):
            if sc >= aprendizaje.MIN: break
            print(f"  Título flojo ({sc}/100: {'; '.join(probs)[:110]}): pido uno mejor.")
            try:
                r = ia.textos(modo, orig_ia, texto, it.get("kind", "video"), prohibidos + [t], (cfg or {}).get("idioma_titulo", ""), (), "; ".join(probs))
            except Exception: r = None
            if not r or titulos.repetido(r["titulo"], prohibidos + [t]): continue
            sc2, pr2 = aprendizaje.evaluar(r["titulo"])
            if sc2 > sc: t, desc, sc, probs = r["titulo"].strip(), r["descripcion"].strip(), sc2, pr2; print(f"  [IA {r['prov']}] Título mejorado ({sc}/100): {t}")
    otras = titulos.descripciones_usadas() + [i.get("ia_desc") for i in (D["items"] if D else []) if i is not it and i.get("ia_desc") and i.get("final_title")]
    for _ in range(3):                         # la descripcion tampoco puede ser igual a la de otro video
        if desc and not titulos.desc_repetida(desc, otras): break
        if desc: print("  Descripción repetida, pido otra."); otras = otras + [desc]; desc = ""
        if activa:
            try:
                r = ia.textos(modo, orig_ia, texto, it.get("kind", "video"), prohibidos + [t], (cfg or {}).get("idioma_titulo", ""), otras)
                if r and not titulos.repetido(r["titulo"], prohibidos + [t]) : desc = r["descripcion"].strip()
                elif r: desc = r["descripcion"].strip()
            except Exception: pass
    if not desc or titulos.desc_repetida(desc, otras):
        desc = titulos.desc_fallback(t, texto, (cfg or {}).get("tema_titulo", ""), otras, len(otras) + 1, tags); print("  Descripción propia (única).")
    t, desc = titulos.formatear(t, 95), titulos.formatear_desc(desc, t)                  # SIEMPRE en MAYÚSCULAS y con emojis
    if uso_fallback:                                                                     # sin IA: los hashtags por defecto van en la descripción y (si está activado) al final del título
        if not all(h.lower() in desc.lower() for h in tags.split()): desc = desc.rstrip() + "\n\n" + tags
        if (cfg or {}).get("hashtags_titulo", True): t = titulos.con_etiquetas(t, tags, 100)
    t, desc = titulos.ajustar(titulos.sin_video(t, tags), 100), titulos.sin_video(desc, tags)       # NUNCA queda la palabra «video»: va el set de hashtags
    it["ia_title"], it["ia_desc"], it["final_title"] = t, desc, t[:100]
    titulos.registrar(t[:100]); titulos.registrar_desc(desc)      # quedan guardados ya: ningun otro video podra repetirlos
    return t[:100], desc

# ======================= subida con reanudado automático =======================
RE_CORTE = re.compile(r"interrumpid|interrupted|subida\s+(?:cancelada|fallida)|upload\s+(?:failed|cancel)|no se pudo (?:subir|cargar)|couldn.?t upload|reanudar subida|resume upload", re.I)
SEL_PROGRESO = "ytcp-video-upload-progress, ytcp-multi-progress-monitor"
_PROG = {"pct": None, "t": 0.0}

def texto_progreso(tab):
    """Texto de los paneles de progreso de Studio (el del cuadro de subida y el flotante 'Subiendo 1 de 1')."""
    try:
        t = tab.eval("window.__A(%s).map(function(e){return e.innerText||''}).join(' | ')" % json.dumps(SEL_PROGRESO)) or ""
        if t.strip(" |\n"): return t
        return tab.eval("(function(){var ex={};window.__A('ytcp-video-row').forEach(function(r){(r.innerText||'').split('\\n').forEach(function(l){ex[l.trim()]=1})});"
                        "return (document.body.innerText||'').split('\\n').filter(function(l){l=l.trim();return l&&!ex[l]&&/subiendo|% subido|uploading|subida|upload/i.test(l)}).slice(0,8).join(' | ')})()") or ""
    except Exception: return ""

def vigilar_subida(tab, real):
    """Lanza SubidaInterrumpida si Studio avisa que se cortó o si el porcentaje lleva demasiado sin avanzar."""
    try: malo = bool(RE_ARCHIVO_INCORRECTO.search(tab.eval(JS_DIALOGO_TXT) or ""))
    except Exception: malo = False
    if malo:
        try: cerrar_archivo_incorrecto(tab)
        except Exception: pass
        raise SubidaInterrumpida("Studio mostró «Archivo incorrecto»")
    m = RE_CORTE.search(texto_progreso(tab))
    if m: raise SubidaInterrumpida("Studio avisó: " + m.group(0))
    if real is not None and real < 100:
        if _PROG["pct"] != real: _PROG["pct"], _PROG["t"] = real, time.time()
        elif time.time() - _PROG["t"] > STALL_S: raise SubidaInterrumpida(f"la subida no avanza hace {STALL_S // 60} min (quedó en {real} %)")

RE_SUBIENDO = re.compile(r"subi[eé]ndose|se est[aá] subiendo|subiendo|uploading|\d{1,3}\s*%\s*(?:subid|uploaded)|tiempo restante|time remaining|quedan?\s+\d|\d+\s*(?:minutos?|segundos?|minutes?|seconds?)\s+(?:restantes?|left|remaining)", re.I)
RE_YA_SUBIDO = re.compile(r"procesando|processing|comprobaci|checks|subida completada|upload complete|v[ií]deo publicado|video published", re.I)

def texto_subida(tab):
    """Todo el texto visible que indique que la subida sigue (diálogo 'Se está subiendo el vídeo', panel flotante, cuadro de subida)."""
    try:
        return tab.eval("(function(){var o=[];window.__A('ytcp-uploads-dialog,ytcp-dialog,tp-yt-paper-dialog,ytcp-multi-progress-monitor,ytcp-video-upload-progress,ytcp-uploads-still-processing-dialog').forEach(function(e){var r=e.getBoundingClientRect();if(r.width>0)o.push(e.innerText||'')});"
                        "if(!o.length){(document.body.innerText||'').split('\\n').forEach(function(l){if(/subi[eé]ndose|subiendo|uploading|restante|remaining/i.test(l))o.push(l)})}return o.join(' | ')})()") or ""
    except Exception: return ""

def subida_en_curso(tab):
    """True mientras Studio siga mostrando que el archivo se está subiendo (porcentaje o tiempo restante)."""
    t = texto_subida(tab)
    if not t.strip(): return False
    if RE_SUBIENDO.search(t) and not re.search(r"subi[eé]ndose|subiendo|uploading", t, re.I) and RE_YA_SUBIDO.search(t): return False   # solo 'procesando ... quedan X min': ya está en YouTube
    return bool(RE_SUBIENDO.search(t))

def esperar_subida_terminada(tab, it, t0, size_mb, chk, limite=None):
    """NO deja cerrar ni navegar hasta que desaparezca el porcentaje / tiempo restante de la subida (si no, YouTube la corta)."""
    limite = limite or max(1800, int(size_mb * 20) + 900); fin = time.time() + limite; libres = 0
    paso("esperando a que termine de subirse (no cierro hasta que no quede tiempo restante)")
    while time.time() < fin:
        chk()
        try: up_progress(tab, it, t0, size_mb)          # avisa si se corta o se estanca
        except SubidaInterrumpida: raise
        except Exception: pass
        if subida_en_curso(tab): libres = 0
        else: libres += 1
        if libres >= 6: return                            # ~9 s seguidos sin nada de subida
        time.sleep(1.5)
    raise SubidaInterrumpida(f"La subida seguía en curso después de {limite // 60} min")

def up_progress(tab, it, t0, size_mb):
    """Porcentaje de subida: lo lee de Studio si puede; si no, lo estima (marcado con ~). Si la subida se corta, avisa."""
    frac = real = None
    try:
        txt = texto_pie(tab) or texto_progreso(tab)
        m = re.search(r"(\d{1,3})\s*%", txt)
        if m: real = min(int(m.group(1)), 100); frac = real / 100; it["est"] = False
        elif re.search(r"upload complete|checks complete|finished|completad|finaliz|terminad", txt, re.I): frac = 1.0; it["est"] = False
    except Exception: pass
    vigilar_subida(tab, real)
    if frac is None:
        tau = max(8.0, size_mb / 2.0)               # ~2 MB/s
        frac = min(0.95, 1 - math.exp(-(time.time() - t0) / tau)); it["est"] = True
    set_prog(it, "up", frac)

def hay_internet():
    try: urllib.request.urlopen("https://www.youtube.com/generate_204", timeout=6).read(); return True
    except urllib.error.HTTPError: return True
    except Exception: return False

def esperar_internet(chk, maxs=900):
    if hay_internet(): return True
    paso("sin internet: espero a que vuelva"); fin = time.time() + maxs
    while time.time() < fin:
        chk()
        if hay_internet(): print("  Internet volvió."); time.sleep(3); return True
        time.sleep(5)
    return False

def espera(seg, chk):
    for _ in range(int(seg)): chk(); time.sleep(1)

def asegurar_tab(tab, chk):
    """Si Chrome o la pestaña se cerraron/colgaron, se reconecta (o reabre Chrome con tu sesión)."""
    try: tab.url(); return
    except Exception: pass
    for _ in range(6):
        chk()
        try: tab.reconectar(); tab.url(); return
        except Exception: pass
        try:
            import servidor; servidor.launch_chrome()
        except Exception: pass
        time.sleep(5)
    raise RuntimeError("Chrome no responde: no pude reconectar con la pestaña de Studio")

JS_FILAS_CORTADAS = r"""(function(){var o=[];window.__A("ytcp-video-row").forEach(function(r){var t=r.innerText||'';
if(/interrumpid|interrupted|reanudar subida|resume upload/i.test(t)){var a=window.__D("a[href*='/video/']",r);
o.push({t:t.slice(0,700),vid:a?((a.href.match(/\/video\/([\w-]{11})/)||[])[1]||''):''})}});return o})()"""

JS_CLIC_REANUDAR = r"""(function(nombre){var rows=window.__A("ytcp-video-row"),row=null,n=(nombre||'').toLowerCase();
for(var i=0;i<rows.length&&!row;i++){if((rows[i].innerText||'').toLowerCase().indexOf(n)>=0)row=rows[i]}
for(var k=0;k<rows.length&&!row;k++){if(/reanudar subida|resume upload/i.test(rows[k].innerText||''))row=rows[k]}
if(!row)return null;var a=window.__A("ytcp-button,button,tp-yt-paper-button,a,[role=button],span,div",row),best=null;
for(var j=0;j<a.length;j++){var e=a[j],t=(e.innerText||'').trim();if(!/^(reanudar subida|resume upload)$/i.test(t))continue;
var r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)continue;var s=/^(ytcp-button|button|tp-yt-paper-button|a)$/i.test(e.tagName)?0:1;if(!best||s<best.s)best={s:s,e:e}}
if(!best)return null;best.e.scrollIntoView({block:'center'});var q=best.e.getBoundingClientRect();return {x:q.left+q.width/2,y:q.top+q.height/2}})(%s)"""

def filas_cortadas(tab, espera_s=25, chk=None):
    """Filas de la lista de contenido que dicen 'La subida se ha interrumpido' (con su archivo y el id del borrador)."""
    fin = time.time() + espera_s
    while time.time() < fin:
        if chk: chk()
        try:
            if tab.cuantos("ytcp-video-row") > 0: time.sleep(1.5); return tab.eval(JS_FILAS_CORTADAS) or []
        except Exception: pass
        time.sleep(1)
    return []

def nombre_en_fila(txt):
    m = re.search(r"(?:selecciona|select)\s+(\S+?\.\w{2,4})(?=\s|\.|$)", txt, re.I)
    return m.group(1).lower() if m else None

def buscar_cortada(tab, cid, it, chk, esperar=25):
    """Va a la lista de Studio y devuelve la fila de subida interrumpida que corresponde a este archivo (o None)."""
    nombre = pathlib.Path(it["file"]).name.lower()
    for ruta in ("upload", "short"):
        tab.ir(f"https://studio.youtube.com/channel/{cid}/videos/{ruta}")
        for f in filas_cortadas(tab, esperar, chk):
            if nombre_en_fila(f["t"]) == nombre or nombre in f["t"].lower(): return f
    return None

def revisar_cortadas(tab, cid, pending, chk):
    """Antes de subir nada: ¿quedó alguna subida cortada de estos mismos archivos? (por ejemplo, de una corrida anterior)."""
    nombres = {pathlib.Path(i["file"]).name.lower() for i in pending if i.get("file")}; hallados = set()
    try:
        paso("revisando si quedó alguna subida cortada en Studio")
        for ruta, esp in (("upload", 25), ("short", 12)):
            tab.ir(f"https://studio.youtube.com/channel/{cid}/videos/{ruta}")
            for f in filas_cortadas(tab, esp, chk):
                n = nombre_en_fila(f["t"])
                if n in nombres: hallados.add(n)
                else:
                    for x in nombres:
                        if x in f["t"].lower(): hallados.add(x)
    except Cancelled: raise
    except Exception as e: print("  No pude revisar subidas cortadas:", str(e)[:100])
    if hallados: print("  Subidas cortadas encontradas (las reanudo solas):", ", ".join(sorted(hallados)))
    return hallados

# ======================= subidas cortadas: se ELIMINAN y se vuelve a subir (cada paso se verifica; si uno falla, NO se avanza) =======================
RE_ARCHIVO_INCORRECTO = re.compile(r"archivo incorrecto|wrong file|incorrect file", re.I)
RE_CONFIRMA_BORRAR = re.compile(r"eliminar|delete|permanente|permanent", re.I)
RE_BOTON_BORRAR = r"^(eliminar definitivamente|delete forever|eliminar|delete)$"

_ENDLG = "function enDlg(e){while(e){if(e.nodeType===1&&(/dialog/i.test(e.tagName)||e.getAttribute('role')==='dialog'))return true;e=e.parentNode||e.host}return false}"
JS_DIALOGO_TXT = r"""(function(){var o=[];window.__A('ytcp-confirmation-dialog,ytcp-dialog,tp-yt-paper-dialog,[role=dialog]').forEach(function(e){var r=e.getBoundingClientRect();if(r.width>0&&r.height>0){var t=(e.innerText||'').trim();if(t)o.push(t)}});return o.join(' || ')})()"""
_JS_FILA = r"""var rows=window.__A('ytcp-video-row'),n=(nombre||'').toLowerCase(),row=null;
for(var i=0;i<rows.length&&!row;i++){var t=(rows[i].innerText||'').toLowerCase();if(/interrumpid|interrupted|reanudar subida|resume upload/.test(t)&&(!n||t.indexOf(n)>=0))row=rows[i]}
if(!row)return null;row.scrollIntoView({block:'center'});var rr=row.getBoundingClientRect();"""
JS_ELIMINAR_FILA = "(function(nombre){" + _JS_FILA + r"""
var a=window.__A('ytcp-button,button,tp-yt-paper-button,a,[role=button],span,div',row),best=null;
for(var j=0;j<a.length;j++){var e=a[j],t2=(e.innerText||'').trim();if(!/^(eliminar|delete)$/i.test(t2))continue;
var r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)continue;var s=/^(ytcp-button|button|tp-yt-paper-button|a)$/i.test(e.tagName)?0:1;if(!best||s<best.s)best={s:s,x:r.left+r.width/2,y:r.top+r.height/2}}
return {fila:{x:rr.left+rr.width/2,y:rr.top+rr.height/2},btn:best?{x:best.x,y:best.y}:null}})(%s)"""
JS_OPCIONES_FILA = "(function(nombre){" + _JS_FILA + r"""
var a=window.__A('ytcp-icon-button,button,[role=button]',row);
for(var j=0;j<a.length;j++){var e=a[j],l=(e.getAttribute('aria-label')||e.innerText||'').trim();if(!/^(opciones|options|m[aá]s opciones|more options|acciones)/i.test(l))continue;
var r=e.getBoundingClientRect();if(r.width>0&&r.height>0)return {x:r.left+r.width/2,y:r.top+r.height/2}}return null})(%s)"""
JS_CASILLAS = "(function(){" + _ENDLG + r"""
var a=window.__A('ytcp-checkbox-lit,tp-yt-paper-checkbox,[role=checkbox],input[type=checkbox]'),m=[],o=[];
function dentro(x,y){while(x){if(x===y)return true;x=x.parentNode||x.host}return false}
for(var i=0;i<a.length;i++){var e=a[i];if(!enDlg(e))continue;var r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)continue;m.push(e)}
for(var i=0;i<m.length;i++){var e=m[i],anidada=false;for(var j=0;j<m.length;j++){if(j!==i&&dentro(e,m[j])){anidada=true;break}}if(anidada)continue;
var r=e.getBoundingClientRect(),c=e.getAttribute('aria-checked')==='true'||e.hasAttribute('checked')||e.checked===true;
o.push({x:r.left+Math.min(18,r.width/2),y:r.top+r.height/2,c:c,t:String(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,100)})}
return o})()"""
JS_BOTON_DLG = "(function(re){" + _ENDLG + r"""var rx=new RegExp(re,'i'),a=window.__A('ytcp-button,button,tp-yt-paper-button,[role=button],a');
for(var i=0;i<a.length;i++){var e=a[i];if(!enDlg(e))continue;var r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)continue;
var t=(e.innerText||e.getAttribute('aria-label')||'').trim();if(!t||t.length>60||!rx.test(t))continue;
return {x:r.left+r.width/2,y:r.top+r.height/2,dis:e.hasAttribute('disabled')||e.getAttribute('aria-disabled')==='true',t:t}}return null})(%s)"""

def _clic_xy(tab, x, y):
    tab.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    for t in ("mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})

def _hasta(cond, timeout, chk=None, cada=0.5):
    """Repite 'cond' hasta que devuelva algo verdadero o se acabe el tiempo (None). Un error de la página (está navegando) cuenta como 'todavía no'."""
    fin = time.time() + timeout
    while time.time() < fin:
        if chk: chk()
        try:
            r = cond()
            if r: return r
        except Cancelled: raise
        except Exception: pass
        time.sleep(cada)
    return None

def _dialogo_borrar(tab):
    txt = tab.eval(JS_DIALOGO_TXT) or ""
    return txt if (txt and RE_CONFIRMA_BORRAR.search(txt) and not RE_ARCHIVO_INCORRECTO.search(txt)) else ""

def _boton_dialogo(tab, patron):
    return tab.eval(JS_BOTON_DLG % json.dumps(patron))

def _cancelar_dialogo(tab):
    try:
        b = _boton_dialogo(tab, r"^(cancelar|cancel)$")
        if b: _clic_xy(tab, b["x"], b["y"])
        else: tab.tecla("Escape", 27)
        time.sleep(0.8)
    except Exception: pass

def cerrar_archivo_incorrecto(tab, chk=None):
    """Si Studio muestra 'Archivo incorrecto' (pide el archivo original para reanudar), lo cierra con Cancelar. True si estaba abierto."""
    try: txt = tab.eval(JS_DIALOGO_TXT) or ""
    except Exception: return False
    if not RE_ARCHIVO_INCORRECTO.search(txt): return False
    paso("Studio mostró 'Archivo incorrecto': toco Cancelar")
    _cancelar_dialogo(tab)
    if not _hasta(lambda: not RE_ARCHIVO_INCORRECTO.search(tab.eval(JS_DIALOGO_TXT) or ""), 10, chk): raise RuntimeError("No pude cerrar el cuadro 'Archivo incorrecto'")
    return True

def _tocar_eliminar(tab, nombre, chk):
    """Paso 1: toca 'Eliminar' en la fila de la subida cortada y confirma que se abrió el cuadro de confirmación."""
    r = tab.eval(JS_ELIMINAR_FILA % json.dumps(nombre))
    if not r: return False
    try: tab.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": r["fila"]["x"], "y": r["fila"]["y"]})     # los botones de la fila a veces aparecen al pasar el mouse
    except Exception: pass
    time.sleep(0.4); r = tab.eval(JS_ELIMINAR_FILA % json.dumps(nombre)) or r
    if r.get("btn"): _clic_xy(tab, r["btn"]["x"], r["btn"]["y"])
    else:                                                                    # sin botón visible: menú de opciones (⋮) de la fila
        o = tab.eval(JS_OPCIONES_FILA % json.dumps(nombre))
        if not o: return False
        _clic_xy(tab, o["x"], o["y"]); time.sleep(1)
        if not tab.clic_texto(RE_BOTON_BORRAR, "tp-yt-paper-item, ytcp-text-menu-item, [role=menuitem], [role=option]"): return False
    return bool(_hasta(lambda: _dialogo_borrar(tab), 15, chk))

def _tildar_conciencia(tab, chk):
    """Paso 2: tilda 'Soy consciente...' y confirma que el botón 'Eliminar definitivamente' quedó habilitado."""
    fin = time.time() + 20; clics = 0
    while time.time() < fin:
        chk()
        cs = tab.eval(JS_CASILLAS) or []
        b = _boton_dialogo(tab, RE_BOTON_BORRAR)
        pend = [c for c in cs if not c["c"]]
        habilitado = bool(b and not b["dis"])
        if pend and clics < 2 and not (habilitado and clics >= 1):
            _clic_xy(tab, pend[0]["x"], pend[0]["y"]); clics += 1; time.sleep(0.8); continue
        if habilitado: return True
        time.sleep(0.5)
    return False

def _confirmar_borrado(tab, chk):
    """Paso 3: toca 'Eliminar definitivamente' y confirma que el cuadro se cerró."""
    b = _boton_dialogo(tab, RE_BOTON_BORRAR)
    if not b or b["dis"]: return False
    _clic_xy(tab, b["x"], b["y"])
    return bool(_hasta(lambda: not _dialogo_borrar(tab), 30, chk))

def eliminar_subida_cortada(tab, cid, ruta, fila, filas, chk):
    """Eliminar -> tildar 'soy consciente' -> Eliminar definitivamente -> comprobar en la lista. No pasa al siguiente paso si el anterior no se completó."""
    url = f"https://studio.youtube.com/channel/{cid}/videos/{ruta}"
    nombre = nombre_en_fila(fila["t"]) or ""
    clave = lambda f: nombre_en_fila(f["t"]) or f.get("vid") or f["t"][:80]
    k = clave(fila); antes = sum(1 for f in filas if clave(f) == k); et = nombre or "subida cortada"; ultimo = "sin detalle"
    for intento in range(1, 4):
        chk()
        try:
            cerrar_archivo_incorrecto(tab, chk)
            paso(f"{et}: 1/4 tocando 'Eliminar' (intento {intento}/3)")
            if not _tocar_eliminar(tab, nombre, chk): raise RuntimeError("no se abrió el cuadro de confirmación al tocar 'Eliminar'")
            paso(f"{et}: 2/4 tildando 'Soy consciente...'")
            if not _tildar_conciencia(tab, chk): raise RuntimeError("no pude tildar la casilla «soy consciente» (el botón de eliminar sigue bloqueado)")
            paso(f"{et}: 3/4 tocando 'Eliminar definitivamente'")
            if not _confirmar_borrado(tab, chk): raise RuntimeError("Studio no cerró el cuadro después de 'Eliminar definitivamente'")
            paso(f"{et}: 4/4 verificando que desapareció de la lista")
            for _ in range(3):
                chk(); time.sleep(3); tab.ir(url)
                if sum(1 for f in filas_cortadas(tab, 25, chk) if clave(f) == k) < antes:
                    print(f"  Subida cortada eliminada: {et}."); return True
            raise RuntimeError("la subida cortada sigue en la lista después de eliminarla")
        except Cancelled: raise
        except Exception as e:
            ultimo = str(e)[:120]; print(f"  Eliminar subida cortada: intento {intento}/3 falló en «{STEP[0]}»: {ultimo}")
            try: guardar_diagnostico(tab, e)
            except Exception: pass
            _cancelar_dialogo(tab)
            try:
                tab.ir(url)
                if sum(1 for f in filas_cortadas(tab, 25, chk) if clave(f) == k) < antes: print(f"  Subida cortada eliminada: {et}."); return True
            except Cancelled: raise
            except Exception: pass
    raise RuntimeError(f"No pude eliminar la subida cortada ({et}): {ultimo}. No sigo para no repetir el corte.")

def _es_de_este_worker(f, nombres):
    t = f["t"].lower(); n = nombre_en_fila(f["t"])
    if n and n in nombres: return True
    if any(x in t for x in nombres): return True
    return bool(n) and n.endswith("_final.mp4") and not (MEDIA / n).exists()     # huérfana: el archivo ya no existe, no se podría reanudar nunca

def limpiar_cortadas(tab, cid, nombres, chk):
    """Antes de subir: elimina de Studio TODA subida cortada de estos archivos (y las huérfanas _final.mp4). Devuelve cuántas borró.
    Si no logra eliminar una, lanza RuntimeError: no se sube encima de una cortada (eso era lo que provocaba el ciclo cortar-reiniciar-cortar)."""
    nombres = {n.lower() for n in nombres}; borradas = 0
    paso("revisando si quedó alguna subida cortada en Studio")
    for ruta, esp in (("upload", 25), ("short", 12)):
        for _ in range(15):
            chk(); tab.ir(f"https://studio.youtube.com/channel/{cid}/videos/{ruta}")
            filas = filas_cortadas(tab, esp, chk)
            mias = [f for f in filas if _es_de_este_worker(f, nombres)]
            if not mias: break
            print(f"  Hay {len(mias)} subida(s) cortada(s) en «{ruta}»: las elimino antes de subir.")
            eliminar_subida_cortada(tab, cid, ruta, mias[0], filas, chk); borradas += 1
        else: raise RuntimeError("Siguen apareciendo subidas cortadas después de eliminar 15: no sigo")
    if borradas: print(f"  Subidas cortadas eliminadas: {borradas}. Ahora creo la subida nueva.")
    return borradas

def capturar_id(tab, it):
    if it.get("_draft"): return
    try:
        l = tab.eval("(function(){var a=window.__A(\"a[href*='youtu.be/'],a[href*='youtube.com/shorts/']\");for(var i=0;i<a.length;i++){var r=a[i].getBoundingClientRect();if(r.width>0)return a[i].href}return ''})()")
        v = id_de_url(l)
        if v: it["_draft"] = v
    except Exception: pass

def fijar_visibilidad(tab, now_mode, when, chk):
    if now_mode:
        paso("eligiendo Público (publicar ahora)")
        if not elegir_publico(tab): raise RuntimeError("No encontré la opción 'Público' en la pantalla de Visibilidad")
        time.sleep(0.8)
    else:
        paso("programando la fecha")
        tab.clic_visible("#second-container-expand-button") or tab.clic("#second-container-expand-button", 0, 20); time.sleep(1)
        tab.escribir("ytcp-date-picker input", fmt_fecha(campo_valor(tab, "ytcp-date-picker input"), when)); tab.tecla("Enter", 13); time.sleep(0.6)
        tab.escribir("#time-of-day-container input", fmt_hora(campo_valor(tab, "#time-of-day-container input"), when)); tab.tecla("Enter", 13); time.sleep(0.6)

def _finalizar(tab, cid, it, chk, now_mode):
    it.pop("aviso", None)
    if now_mode:
        paso("verificando que quedó Público")
        v = verificar_publicado(tab, cid, it, chk)
        if v == "publico": print("  Verificado: el video figura como Público.")
        elif v == "privado":
            it["aviso"] = "YouTube lo dejó en Privado (probablemente por la comprobación de derechos). Revisalo en Studio."; print("  AVISO:", it["aviso"])
        else: print("  No pude confirmar la visibilidad en la lista de Studio (el video sí se envió a publicar).")
    it["status"] = "published" if now_mode else "scheduled"; it["pct"] = 100
    it["stage"] = "Publicado" if now_mode else "Programado"; it.pop("est", None)

def _detalles(tab, it, titulo, cuerpo, chk):
    if titulo:
        paso("escribiendo el título único"); tab.escribir("#textbox", titulo, 0); time.sleep(0.5)
    paso("escribiendo la descripción"); tab.escribir("#textbox", cuerpo, 1); time.sleep(0.5)
    paso("marcando 'no es para niños'")
    if not marcar_no_ninos(tab, chk):
        print("  Aviso: no encontré la opción 'No es para niños'; sigo y dejo diagnóstico por si Studio la pide.")
        tab.captura(ROOT / "aviso-ninos.png"); tab.diagnostico(ROOT / "diagnostico-ninos.txt", "No encontré la opcion de 'para niños'")
    time.sleep(0.6)

JS_DLG_TXT = r"""(function(){var vis=function(e){var r=e.getBoundingClientRect();return r.width>0&&r.height>0};
var inDlg=function(e){for(var n=e,i=0;n&&i<14;i++){var g=(n.tagName||'').toLowerCase();if(g.indexOf('dialog')>=0||(n.getAttribute&&n.getAttribute('role')==='dialog'))return n;n=n.parentElement||(n.getRootNode&&n.getRootNode().host)||null}return null};
var a=window.__A('[role=dialog],ytcp-video-share-dialog,ytcp-uploads-dialog,ytcp-uploads-still-processing-dialog,tp-yt-paper-dialog,ytcp-dialog');
for(var i=0;i<a.length;i++){if(vis(a[i])){var t=a[i].innerText||'';if(t.trim())return t}}
var b=window.__A('button,ytcp-button,tp-yt-paper-button,[role=button]');
for(var j=0;j<b.length;j++){var x=(b[j].innerText||b[j].getAttribute('aria-label')||'').trim();
if(vis(b[j])&&/^(cerrar|close)$/i.test(x)){var d=inDlg(b[j]);if(d){var t2=d.innerText||'';if(t2.trim())return t2}}}
return ''})()"""
RE_VENTANA_FINAL = re.compile(r"se est[aá] procesando|v[ií]deo publicado|se ha publicado|video published|processing|procesamiento|enlace del v", re.I)

JS_CERRAR_DLG = r"""(function(){var vis=function(e){var r=e.getBoundingClientRect();return r.width>0&&r.height>0};
var inDlg=function(e){for(var n=e,i=0;n&&i<14;i++){var g=(n.tagName||'').toLowerCase();if(g.indexOf('dialog')>=0||(n.getAttribute&&n.getAttribute('role')==='dialog'))return n;n=n.parentElement||(n.getRootNode&&n.getRootNode().host)||null}return null};
var d=window.__A('[role=dialog],ytcp-video-share-dialog,ytcp-uploads-dialog,ytcp-uploads-still-processing-dialog,tp-yt-paper-dialog,ytcp-dialog');
for(var i=0;i<d.length;i++){if(!vis(d[i]))continue;
var b=d[i].querySelectorAll('#close-button,ytcp-button#close-button,button,ytcp-button,tp-yt-paper-button,[role=button]');
for(var j=0;j<b.length;j++){var t=(b[j].innerText||b[j].getAttribute('aria-label')||'').trim();
if(vis(b[j])&&(b[j].id==='close-button'||/^(cerrar|close)$/i.test(t))){b[j].click();return 1}}}
var c=window.__A('button,ytcp-button,tp-yt-paper-button,[role=button]');
for(var k=0;k<c.length;k++){var u=(c[k].innerText||c[k].getAttribute('aria-label')||'').trim();
if(vis(c[k])&&/^(cerrar|close)$/i.test(u)&&inDlg(c[k])){c[k].click();return 1}}
return 0})()"""

def _cerrar_ventana_final(tab, intento):
    """Cierra 'Se ha publicado el vídeo'. Cada intento usa un método distinto: clic por texto, .click() por JS dentro del cuadro, tecla Esc, botón #close-button."""
    m = intento % 4
    try:
        if m == 0: return bool(tab.clic_texto(r"^(cerrar|close)$", TAGS_BOTON)) or _clic_primero(tab, ["ytcp-video-share-dialog #close-button", "#close-button"])
        if m == 1: return bool(tab.eval(JS_CERRAR_DLG))
        if m == 2: tab.tecla("Escape", 27); return True
        return tab.clic_visible("#close-button", False, True)
    except Exception: return False

def cerrar_cuando_completo(tab, it, t0, size_mb, chk, limite=1200):
    """Ventana final ('Se está procesando el vídeo' / 'Vídeo publicado'): SOLO cuando el pie dice 'Comprobaciones completadas' toca 'Cerrar'.
    Mientras dice 'Subiéndose' o 'Comprobando' espera (si se cierra antes, YouTube corta la subida)."""
    fin = time.time() + limite; sin_ventana = 0; ult = None; intentos = 0
    while time.time() < fin:
        chk()
        try: up_progress(tab, it, t0, size_mb)
        except SubidaInterrumpida: raise
        except Exception: pass
        txt = ""
        try: txt = tab.eval(JS_DLG_TXT) or ""
        except Exception: pass
        if not txt.strip():
            sin_ventana += 1
            if sin_ventana >= 6: return True                  # no hay ventana: ya se cerró sola
            time.sleep(1); continue
        sin_ventana = 0
        if re.search(r"comprobaciones completadas|checks complete|no se han encontrado problemas|no issues found|se ha publicado el v[ií]deo|video published", txt, re.I):      # SOLO con 'Comprobaciones completadas'
            try:
                link = tab.eval("(function(){var a=window.__A(\"a[href*='youtu.be/'],a[href*='youtube.com/shorts/'],a[href*='youtube.com/watch']\");for(var i=0;i<a.length;i++){var r=a[i].getBoundingClientRect();if(r.width>0)return a[i].href}return ''})()")
                if link: it["yt_url"] = link
            except Exception: pass
            print("  Comprobaciones completadas en la ventana final: toco 'Cerrar'.")
            paso("comprobaciones completadas: cerrando la ventana")
            _cerrar_ventana_final(tab, intentos); intentos += 1      # si no se cierra, el siguiente giro prueba OTRO método (clic, JS, Esc...)
            time.sleep(1.5)
            if intentos >= 6:                                         # no hay forma de cerrarla: el video YA está publicado; se minimiza Chrome y se sigue
                print("  La ventana final no se cerró: minimizo Chrome y paso al siguiente video.")
                _minimizar(tab); return True
            continue                                          # si la ventana ya no está, el siguiente giro devuelve True
        if txt != ult: print("  Ventana final: esperando a que Studio termine de comprobar…"); ult = txt
        paso("ventana final abierta: espero 'Comprobaciones completadas' para cerrar")
        time.sleep(1.5)
    return False

def _cierre_dialogo(tab, cid, it, chk, t0, size_mb, now_mode, when):
    """Desde 'Siguiente' hasta publicar, dentro del cuadro de subida (Detalles -> Elementos -> Comprobaciones -> Visibilidad)."""
    avanzar_hasta_visibilidad(tab, it, t0, size_mb, chk); capturar_id(tab, it)
    fijar_visibilidad(tab, now_mode, when, chk)
    paso("esperando a que termine la subida")
    limite = max(1500, int(size_mb * 30) + 900); end = time.time() + limite        # proporcional al tamaño: un video grande no se da por cortado a los 25 min mientras sigue subiendo
    while True:
        chk(); up_progress(tab, it, t0, size_mb); capturar_id(tab, it)
        if tab.habilitado("#done-button"): break
        if now_mode and int(time.time() - t0) % 20 == 0 and not publico_marcado(tab): elegir_publico(tab)   # por si no quedo marcado
        if time.time() > end: raise SubidaInterrumpida(f"La subida tardó más de {limite // 60} minutos")
        time.sleep(1.5)
    it["_subida_ok"] = True
    if D is not None: save(D)
    paso("publicando" if now_mode else "programando")
    if not tab.clic_visible("#done-button", True, True): raise RuntimeError("No encontré el botón final de publicar")
    fin = time.time() + 180; forzado = 0
    while True:                                   # cuando Studio cierra el formulario (o muestra "Video publicado"), ya se publicó
        chk()
        if publicar_de_todas_formas(tab):         # aviso "Aún estamos comprobando tu contenido"
            forzado += 1; paso("Studio avisó que sigue comprobando: 'Publicar de todas formas'"); time.sleep(2); continue
        if tab.visible("ytcp-video-share-dialog") or not tab.visible("#done-button"): break
        if time.time() > fin: raise RuntimeError("Studio no confirmó la publicación (el botón final sigue ahí)")
        if forzado == 0 and int(time.time() - fin) % 25 == 0 and tab.habilitado("#done-button"): tab.clic_visible("#done-button", True, True)   # el clic no se registro: reintento
        time.sleep(1)
    time.sleep(2)
    if cerrar_cuando_completo(tab, it, t0, size_mb, chk):    # espera "Comprobaciones completadas" y toca Cerrar
        _finalizar(tab, cid, it, chk, now_mode); return
    esperar_subida_terminada(tab, it, t0, size_mb, chk)      # respaldo: antes de cerrar el diálogo o abrir otra página
    try:
        link = tab.eval("(function(){var a=window.__A(\"a[href*='youtu.be/'],a[href*='youtube.com/shorts/'],a[href*='youtube.com/watch']\");"
                        "for(var i=0;i<a.length;i++){var r=a[i].getBoundingClientRect();if(r.width>0)return a[i].href}return ''})()")
        if link: it["yt_url"] = link
    except Exception: pass
    _clic_primero(tab, ["#close-button", "ytcp-button#close-button"])
    _finalizar(tab, cid, it, chk, now_mode)

def esperar_fin_subida(tab, it, t0, size_mb, chk, limite=1800):
    """En la página de edición / lista: espera a que desaparezca el panel 'Subiendo...' y su tiempo restante."""
    esperar_subida_terminada(tab, it, t0, size_mb, chk, max(limite, int(size_mb * 20) + 900))

def abrir_visibilidad_edicion(tab, chk):
    """En la página de edición: abre el selector de Visibilidad (Borrador/Privado ▾)."""
    pats = r"^(borrador|privado|no listado|programado|p[uú]blico|draft|private|unlisted|scheduled|public)$"
    for _ in range(4):
        chk()
        if tab.eval(JS_PUBLICO): return True
        for sel in ("ytcp-video-metadata-visibility #select-button", "ytcp-video-metadata-visibility ytcp-icon-button", "ytcp-video-metadata-visibility", "#visibility-text"):
            try:
                if tab.visible(sel) and tab.clic_visible(sel):
                    time.sleep(1.5)
                    if tab.eval(JS_PUBLICO): return True
            except Exception: pass
        if tab.clic_texto(pats, "ytcp-text-dropdown-trigger, ytcp-text-dropdown-trigger *, ytcp-video-metadata-visibility *, #select-button, [role=button], button"):
            time.sleep(1.5)
            if tab.eval(JS_PUBLICO): return True
        time.sleep(1.5)
    return False

def _cierre_edicion(tab, cid, it, chk, now_mode, when, t0=None, size_mb=0, esperar=True):
    """Publica un borrador ya subido desde su página de edición (Visibilidad -> Público/Programar -> Guardar)."""
    t0 = t0 or time.time()
    if esperar: esperar_fin_subida(tab, it, t0, size_mb, chk)
    it["_subida_ok"] = True
    if D is not None: save(D)
    if not abrir_visibilidad_edicion(tab, chk): raise RuntimeError("No pude abrir el selector de Visibilidad en la página de edición")
    fijar_visibilidad(tab, now_mode, when, chk)
    paso("guardando la visibilidad")
    if not (tab.clic_texto(r"^(guardar|listo|save|done)$", TAGS_BOTON) or _clic_primero(tab, ["ytcp-video-visibility-select-dialog #save-button", "#save-button", "#done-button"])):
        raise RuntimeError("No encontré el botón para confirmar la visibilidad")
    time.sleep(2)
    fin = time.time() + 60
    while time.time() < fin:                      # botón 'Guardar' de arriba (si Studio dejó cambios pendientes)
        chk()
        if publicar_de_todas_formas(tab): time.sleep(2); continue
        if tab.habilitado("#save"): tab.clic_visible("#save", True, True); time.sleep(3); break
        if not tab.eval(JS_PUBLICO): break
        time.sleep(1)
    vid = it.get("_draft") or id_de_url(tab.url()) or (re.search(r"/video/([\w-]{11})", tab.url()) or [None, None])[1]
    if vid: it["_draft"] = vid; it["yt_url"] = f"https://youtu.be/{vid}"
    _finalizar(tab, cid, it, chk, now_mode)

def _terminar_borrador(tab, cid, it, chk, now_mode, when):
    vid = it.get("_draft")
    if not vid: raise RuntimeError("Subí el video pero no guardé su id: no puedo terminar de publicarlo solo")
    paso("abriendo el video ya subido para publicarlo")
    tab.ir(f"https://studio.youtube.com/video/{vid}/edit")
    if not tab.esperar("ytcp-video-metadata-editor, #textbox", 40, chk): raise RuntimeError("No cargó la página de edición del video")
    _cierre_edicion(tab, cid, it, chk, now_mode, when, esperar=False)

def _subir_nuevo(tab, cid, it, chk, titulo, cuerpo, now_mode, when, size_mb):
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
    _detalles(tab, it, titulo, cuerpo, chk)
    _cierre_dialogo(tab, cid, it, chk, t0, size_mb, now_mode, when)

def _reanudar(tab, cid, it, chk, titulo, cuerpo, now_mode, when, size_mb):
    """Hace lo mismo que harías a mano: Contenido del canal -> 'Reanudar subida' -> elegir el archivo en la carpeta media."""
    nombre = pathlib.Path(it["file"]).name
    paso("buscando la subida interrumpida en la lista de Studio")
    f = buscar_cortada(tab, cid, it, chk)
    if not f: raise RuntimeError("Studio ya no muestra como interrumpida la subida de " + nombre)
    if f.get("vid"): it["_draft"] = f["vid"]
    paso("tocando 'Reanudar subida' y entregando el archivo " + nombre)
    c = tab.eval(JS_CLIC_REANUDAR % json.dumps(nombre))
    if not c: raise RuntimeError("No encontré el botón 'Reanudar subida' en la fila de " + nombre)
    if not tab.subir_con_selector(c["x"], c["y"], [it["file"]]): raise RuntimeError("Studio no abrió el selector de archivos al tocar 'Reanudar subida'")
    print(f"  Reanudar subida: archivo entregado a Studio automáticamente ({nombre}).")
    t0 = time.time(); _PROG.update(pct=None, t=t0); paso("Studio retomó la subida; esperando su pantalla")
    fin = time.time() + 90; modo = None; con_prog = None
    while time.time() < fin:
        chk()
        try:
            u = tab.url()
            if tab.visible("ytcp-uploads-dialog") and tab.cuantos("#textbox") >= 2: modo = "dialogo"; break
            m = re.search(r"/video/([\w-]{11})/edit", u)
            if m: it["_draft"] = m.group(1); modo = "edicion"; break
            if re.search(r"\d{1,3}\s*%", texto_progreso(tab)): con_prog = con_prog or time.time()
            if con_prog and time.time() - con_prog > 10: modo = "lista"; break
        except Cancelled: raise
        except Exception: pass
        time.sleep(1)
    if modo is None: raise RuntimeError("Después de elegir el archivo, Studio no retomó la subida")
    print("  Studio retomó la subida (" + modo + ").")
    if modo == "dialogo":
        capturar_id(tab, it); up_progress(tab, it, t0, size_mb)
        if not (tab.eval("(function(){var e=window.__A('#textbox')[0];return e?(e.innerText||'').trim():''})()") or "").strip() and titulo: _detalles(tab, it, titulo, cuerpo, chk)
        _cierre_dialogo(tab, cid, it, chk, t0, size_mb, now_mode, when)
    elif modo == "edicion": _cierre_edicion(tab, cid, it, chk, now_mode, when, t0, size_mb)
    else:
        esperar_fin_subida(tab, it, t0, size_mb, chk); it["_subida_ok"] = True
        _terminar_borrador(tab, cid, it, chk, now_mode, when)

def video_publico(vid):
    """True/False si YouTube muestra el video públicamente (oEmbed: sin abrir el navegador); None si no se pudo saber (sin internet, etc.)."""
    if not vid: return None
    try:
        urllib.request.urlopen(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=12).read(); return True
    except urllib.error.HTTPError as e: return False if e.code in (401, 403, 404) else None
    except Exception: return None

def _minimizar(tab):
    """Terminada la subida: Chrome se minimiza y queda a la vista la web de Yutu con la cuenta regresiva."""
    try:
        if tab.ventana("minimized"): print("  Subida terminada: minimicé la ventana de Chrome.")
    except Exception: pass

def _fin_piloto(it):
    """Avisa al piloto dueño del video que la subida terminó: desde ahora corre su cuenta regresiva."""
    try:
        if it.get("piloto"):
            import piloto; piloto.marcar_fin({it["piloto"]: time.time()})
    except Exception: pass

def _dar_por_subido(it, now_mode, confirmado):
    """La subida ya terminó (o el video ya está en YouTube): se cierra como hecha y NO se repite."""
    vid = it.get("_draft")
    if vid: it["yt_url"] = f"https://youtu.be/{vid}"
    for k in ("reanudar", "reintentos", "reanudar_en", "_subida_ok", "_draft", "error"): it.pop(k, None)
    it["status"] = "published" if now_mode else "scheduled"; it["pct"] = 100; it["stage"] = "Publicado" if now_mode else "Programado"; it.pop("est", None)
    if confirmado or not now_mode: it.pop("aviso", None)
    else: it["aviso"] = "Subido a YouTube; no pude confirmar su visibilidad (si no figura público, revisalo en Studio)."
    it["fin_t"] = time.time(); _fin_piloto(it)
    if D is not None: save(D)

def studio_upload_one(tab, cid, it, cfg=None, cortadas=None):
    titulo, desc = textos_para_subir(it, cfg)
    cuerpo = (desc + "\n\n" if desc else "") + ("#Shorts" if it["kind"] == "short" and "#shorts" not in desc.lower() else "")
    cuerpo = cuerpo.strip()
    now_mode = not it.get("publishAt")
    when = None if now_mode else local(it["publishAt"])
    size_mb = os.path.getsize(it["file"]) / 1048576
    chk = lambda: check_cancel(it)
    auto = (cfg or {}).get("auto_reanudar", True)
    maxi = MAX_INTENTOS if auto else 1
    if it.get("_draft") and video_publico(it["_draft"]) is True:                  # ya se había subido en un intento anterior: no se repite
        print("  Ese video ya está público en YouTube: no lo subo otra vez."); _dar_por_subido(it, now_mode, True); _minimizar(tab); return
    try: tab.ventana("normal")                                                   # si quedó minimizada de la subida anterior
    except Exception: pass
    it["status"] = "uploading"; it.pop("error", None); it.pop("yt_url", None); set_prog(it, "up", 0.0, True)
    nombre = pathlib.Path(it["file"]).name.lower()
    if size_mb < 0.01: raise RuntimeError("El archivo final está vacío o incompleto: " + nombre)
    if it.get("_subida_ok") and it.get("_draft"): modo = "borrador"
    else:
        modo = "nuevo"; it.pop("_draft", None); it.pop("_subida_ok", None)
        asegurar_tab(tab, chk); limpiar_cortadas(tab, cid, {nombre}, chk)          # si hay una cortada y no se puede eliminar, NO se sigue
    ultimo = None
    for intento in range(1, maxi + 1):
        _PROG.update(pct=None, t=time.time())
        try:
            asegurar_tab(tab, chk)
            if modo == "reanudar": _reanudar(tab, cid, it, chk, titulo, cuerpo, now_mode, when, size_mb)
            elif modo == "borrador": _terminar_borrador(tab, cid, it, chk, now_mode, when)
            else: _subir_nuevo(tab, cid, it, chk, titulo, cuerpo, now_mode, when, size_mb)
            for k in ("reanudar", "reintentos", "reanudar_en", "_subida_ok", "_draft"): it.pop(k, None)
            it["fin_t"] = time.time(); _fin_piloto(it); _minimizar(tab)
            return
        except Cancelled: raise
        except Exception as e:
            ultimo = e
            vid = it.get("_draft"); pub = video_publico(vid) if vid else None
            subido = bool(it.get("_subida_ok")) or (int(_PROG.get("pct") or 0) >= 90 and bool(vid) and not isinstance(e, SubidaInterrumpida))
            if pub is True or (subido and (pub is None or not now_mode)):          # el archivo ya está en YouTube: lo que falló es solo el cierre
                print(f"  El video ya está subido ({'público' if pub else 'sin confirmar'}); falló solo «{STEP[0]}». Lo doy por terminado y no lo repito.")
                _dar_por_subido(it, now_mode, pub is True); _minimizar(tab); return
            print(f"  Intento {intento}/{maxi} falló en «{STEP[0]}»: {str(e)[:140]}")
            if intento >= maxi:
                if subido:                                                         # último intento: el archivo ya está en YouTube, no se repite todo el proceso
                    print("  El archivo ya está en YouTube; no pude confirmar la visibilidad. Lo cierro sin repetir."); guardar_diagnostico(tab, e); _dar_por_subido(it, now_mode, False); _minimizar(tab); return
                break
            guardar_diagnostico(tab, e)
            it["aviso"] = f"Se cortó la subida ({str(e)[:80]}). La reanudo sola (intento {intento + 1}/{maxi})..."
            if D is not None: save(D)
            esperar_internet(chk, 900); espera(min(20 * intento, 90), chk)
            try: asegurar_tab(tab, chk)
            except Cancelled: raise
            except Exception: pass
            if it.get("_subida_ok") and it.get("_draft"): modo = "borrador"
            else:
                it.pop("_draft", None); it.pop("_subida_ok", None)
                limpiar_cortadas(tab, cid, {nombre}, chk)                          # eliminar la cortada (no reanudar: Studio exige el archivo idéntico y daba 'Archivo incorrecto')
                modo = "nuevo"
            print("  Sigo con:", {"reanudar": "reanudar la subida cortada", "borrador": "publicar el video ya subido", "nuevo": "subirlo de nuevo"}[modo])
    raise ultimo

def marcar_fallo(d, items, msg):
    auto = d.get("config", {}).get("auto_reanudar", True)
    for it in items:
        if it["status"] in ("ready", "uploading"):
            it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"; it["error"] = msg[:260]
            if auto: it["reintentos"] = it.get("reintentos", 0) + 1; it["reanudar"] = True; it["reanudar_en"] = time.time() + min(300 * it["reintentos"], 1800)
    save(d)

def guardar_diagnostico(tab, e):
    """Deja el diagnostico (texto + captura) en la carpeta del worker; el servidor lo entrega a la web (boton 'Ver diagnóstico')."""
    txt = ROOT / "diagnostico-subida.txt"
    try: txt.write_text(f"Paso: {STEP[0]}\nError: {e}\n", "utf-8")             # lo minimo, por si lo demas falla
    except Exception as x: print("  No pude escribir el diagnóstico:", x)
    try: tab.captura(ROOT / "error-subida.png")
    except Exception: pass
    try: tab.diagnostico(txt, f"Paso: {STEP[0]}\nError: {e}\nBotones: {estado_botones(tab)}")
    except Exception as x: print("  No pude leer la página para el diagnóstico:", x)
    print(f"  Diagnóstico guardado en: {txt}")

def plan_horario(d, it, ahora_mode):
    """Cuándo sale cada item. Shorts de un mismo video largo: el 1.º ya (o en el próximo horario) y cada siguiente +split_gap horas."""
    cfg = d.get("config", {}); now = dt.datetime.now().astimezone(); lim = now + dt.timedelta(minutes=15)
    iso = lambda t: t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not it.get("parts") and (cfg.get("lista_cada") or 0) and not it.get("auto"):
        # videos de una lista de reproducción / cola manual: uno cada X minutos (el primero ya, los demás programados en YouTube)
        cada = dt.timedelta(minutes=float(cfg["lista_cada"])); prev = d.get("ult_pub")
        t = now if not prev else max(now, local(prev) + cada)
        d["ult_pub"] = iso(t)
        return None if t <= lim else iso(t)
    if not it.get("parts"):
        if ahora_mode: return None
        if it.get("publishAt") and local(it["publishAt"]) > lim: return it["publishAt"]
        return next_slot(d, it["kind"])
    sib = [x for x in d["items"] if x.get("id") == it["id"] and x.get("parts")]
    base = next((x["split_base"] for x in sib if x.get("split_base")), None)
    if not base: base = iso(now) if ahora_mode else next_slot(d, it["kind"])
    for x in sib: x["split_base"] = base
    t = local(base) + dt.timedelta(hours=float(cfg.get("split_gap") or 0) * (it.get("part", 1) - 1))
    if t > lim: return iso(t)
    return None if ahora_mode else next_slot(d, it["kind"])

def _conectar_studio():
    """-> (tab, cid). Usa la pestaña de Studio ya abierta del Chrome del worker (no toca las conexiones existentes)."""
    print("Conectando con el Chrome del worker...")
    tab = cdp.Tab.existente("https://studio.youtube.com")
    if not tab:                                              # Chrome se abre SOLO ahora, cuando ya hay un video editado para subir
        try:
            import servidor; servidor.launch_chrome()
        except Exception: pass
        for _ in range(24):
            tab = cdp.Tab.existente("https://studio.youtube.com")
            if tab: break
            time.sleep(0.5)
        tab = tab or cdp.Tab.abrir("https://studio.youtube.com")
    print("Si no iniciaste sesion en YouTube, hacelo en la ventana de Chrome (espero hasta 5 min)...")
    end = time.time() + 300; cid = None
    while time.time() < end:
        try:
            m = re.search(r"studio\.youtube\.com/channel/([\w-]+)", tab.url())
            if m: cid = m.group(1); break
        except Exception: pass
        time.sleep(1)
    if not cid: raise RuntimeError("No detecte tu canal en YouTube Studio. Abri Studio en el Chrome del worker e inicia sesion.")
    return tab, cid

def _extras(d, it):
    """Después de YouTube: el mismo video con el mismo título y descripción en Facebook / TikTok (si los elegiste en el panel «Dónde publicar»).
    Un fallo acá NUNCA reabre ni repite la subida de YouTube."""
    if it.get("status") not in ("published", "scheduled"): return
    return                                                    # una sola plataforma por corrida: ya no se publica "además" en otra red
    dest = redes.leer_destinos()
    if not (dest["fb"] or dest["tt"]): return
    listo = it.get("stage") or "Publicado"
    try: redes.publicar_extras(it, it.get("final_title") or it.get("title"), it.get("ia_desc") or "", lambda: check_cancel(it), print, lambda: save(d))
    except Cancelled: print("  Publicación en redes cancelada.")
    except Exception as e: print("  Redes: error inesperado:", str(e)[:150])
    it["stage"] = listo; it["fin_t"] = time.time(); _fin_piloto(it); save(d)

def _subir_item(d, tab, cid, it, cortadas, auto):
    try:
        check_cancel(it)
        studio_upload_one(tab, cid, it, d.get("config"), cortadas); print("Subido:", it.get("final_title") or it.get("title"), it.get("publishAt") or "publicado ahora")
        _extras(d, it)
        _minimizar(tab)                                           # todo publicado (YouTube + redes): Chrome minimizado y se sigue con el próximo video
    except Cancelled:
        it["status"] = "cancelled"; it["stage"] = "Cancelado"; it.pop("publishAt", None)
        print("Cancelado:", it.get("title")); save(d)
        try: tab.ir(f"https://studio.youtube.com/channel/{cid}")
        except Exception: pass
    except Exception as e:
        guardar_diagnostico(tab, e)
        it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"
        it["error"] = f"No se pudo subir (paso: {STEP[0]}): {str(e)[:150]}"
        if auto:
            n = it.get("reintentos", 0) + 1; it["reintentos"] = n; it["reanudar"] = True; it["reanudar_en"] = time.time() + min(300 * n, 1800)
            it["error"] += f" · Lo reintento solo en unos minutos (intento automático {n}/{MAX_AUTO})."
        print("No se pudo subir automaticamente:", it.get("title"), "->", STEP[0], "->", e)
        try: tab.ir(f"https://studio.youtube.com/channel/{cid}")        # sale del formulario a medias
        except Exception: pass
    save(d)

def _publicar_solo_en(d, it, plat):
    """La plataforma elegida NO es YouTube: el video se sube SOLO a esa plataforma (Facebook o TikTok), sin tocar YouTube."""
    nombre = redes.NOMBRES[plat]
    try:
        check_cancel(it)
        it.pop("publishAt", None); it.pop("error", None); it["status"] = "uploading"; it["pct"] = 100; it["stage"] = f"Armando título y descripción…"; save(d)
        titulo, desc = textos_para_subir(it, d.get("config"))                      # título y descripción PROPIOS (antes acá salía el título copiado del reel)
        it["stage"] = f"Publicando en {nombre}…"; save(d)
        redes.publicar_extras(it, titulo, desc, lambda: check_cancel(it), print, lambda: save(d))
        r = (it.get("extras") or {}).get(plat) or {}
        if r.get("ok"):
            it["status"] = "published"; it["pct"] = 100; it["stage"] = f"Publicado en {nombre}"; it["fin_t"] = time.time(); it.pop("est", None); _fin_piloto(it)
            print("Publicado en", nombre + ":", it.get("final_title") or it.get("title"))
        else:
            it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"; it["error"] = f"No se pudo publicar en {nombre}: {r.get('msg') or 'sin detalle'}"[:220]; it["fin_t"] = time.time(); _fin_piloto(it)
            print("No se pudo publicar en", nombre + ":", it.get("title"), "->", r.get("msg"))
    except Cancelled:
        it["status"] = "cancelled"; it["stage"] = "Cancelado"; print("Cancelado:", it.get("title"))
    except Exception as e:
        it["status"] = "ready"; it["pct"] = 100; it["stage"] = "Listo"; it["error"] = f"No se pudo publicar en {nombre}: {str(e)[:150]}"; it["fin_t"] = time.time(); _fin_piloto(it)
        print("No se pudo publicar en", nombre + ":", it.get("title"), "->", e)
    save(d)

def studio_upload(d, only=None, mode=None):
    pending = [i for i in d["items"] if i["status"] in ("ready", "uploading") and i.get("file") and (only is None or i["key"] in only)]
    if not pending: print("No hay videos listos para subir."); return
    plat = redes.leer_destinos()["plataforma"]
    if plat != "yt":                                          # plataforma elegida: Facebook o TikTok (YouTube no se toca)
        for it in pending: _publicar_solo_en(d, it, plat)
        write_plan([i for i in d["items"] if i.get("file") and i["status"] in ("ready", "scheduled", "published")]); return
    now_mode = (mode or d.get("config", {}).get("publish")) == "now"
    for it in pending:
        pa = plan_horario(d, it, now_mode)
        if pa: it["publishAt"] = pa
        else: it.pop("publishAt", None)
    write_plan(pending); save(d)
    try: tab, cid = _conectar_studio()
    except Exception as e:
        print("No pude preparar la subida:", e); marcar_fallo(d, pending, "No pude preparar la subida: " + str(e)); return
    cortadas = set()                                          # las subidas cortadas se eliminan video por video (limpiar_cortadas), no se reanudan
    auto = d.get("config", {}).get("auto_reanudar", True)
    for it in pending: _subir_item(d, tab, cid, it, cortadas, auto)
    try: tab.cerrar()
    except Exception: pass

def subir_en_vivo(d, hilo, mode):
    """Sube cada video EN CUANTO queda editado, mientras el siguiente se descarga y edita (antes se editaba todo y recién después se subía)."""
    cfg = d.get("config", {}); now_mode = (mode or cfg.get("publish")) == "now"; auto = cfg.get("auto_reanudar", True)
    previos = [i for i in d["items"] if i["status"] == "ready" and i.get("file")]       # editados en corridas anteriores
    tab = cid = None; cortadas = set(); hechos = set(); falla_conexion = False
    plat = redes.leer_destinos()["plataforma"]                                             # una sola plataforma para todos los videos
    while True:
        vivo = hilo.is_alive()                                                            # se mira ANTES de listar (evita carreras)
        listos = [i for i in d["items"] if i["status"] == "ready" and i.get("file") and i["key"] not in hechos]
        if not listos:
            if not vivo: break
            time.sleep(1.5); continue
        if plat == "yt" and tab is None and not falla_conexion:
            try:
                tab, cid = _conectar_studio()
            except Exception as e:
                falla_conexion = True; print("No pude preparar la subida:", e)
        it = listos[0]; hechos.add(it["key"])
        if plat != "yt": save(d); _publicar_solo_en(d, it, plat); continue                 # Facebook o TikTok: se sube SOLO ahí
        if falla_conexion: marcar_fallo(d, [it], "No pude preparar la subida"); continue
        pa = plan_horario(d, it, now_mode)
        if pa: it["publishAt"] = pa
        else: it.pop("publishAt", None)
        save(d); _subir_item(d, tab, cid, it, cortadas, auto)
    write_plan([i for i in d["items"] if i.get("file") and i["status"] in ("ready", "scheduled", "published")])
    try: tab and tab.cerrar()
    except Exception: pass

def main():
    global D, PLAN
    if "--reanudar" in sys.argv: return reanudar_only()
    if "--subir" in sys.argv: return upload_only()
    d = load(); d.setdefault("config", {}); D = d; expand(d); split_items(d); save(d)
    try: titulos.sembrar(d["items"])
    except Exception: pass
    PLAN = make_plan(d["config"], not NO_UPLOAD)
    prefetch([i for i in d["items"] if i["status"] in ("pending", "processing")])
    def productor():
        for it in d["items"]:
            if it["status"] not in ("pending", "processing"): continue
            try:
                check_cancel(it)
                it["status"] = "processing"; it.pop("error", None); it["pct"] = 0; save(d)
                print("Procesando", it.get("url") or it.get("tema") or it.get("key")); process(it, d["config"])
            except Cancelled:
                it["status"] = "cancelled"; it["stage"] = "Cancelado"; print("Cancelado:", it.get("title") or it.get("url"))
            except Exception as e:
                it["status"] = "error"; it["stage"] = "Error"; it["error"] = str(e)[:400]; print("ERROR:", e)
            if it.get("id") and it["id"] not in _REL: _REL.add(it["id"]); PRE_SEM.release()
            save(d)
            PRE_INFO.pop(it.get("id"), None); DLP.pop(it.get("id"), None); memoria.liberar(True)      # suelta RAM entre video y video
    hilo = threading.Thread(target=productor, daemon=True); hilo.start()
    if NO_UPLOAD:
        hilo.join(); write_plan([i for i in d["items"] if i["status"] == "ready"])
    else:
        try: subir_en_vivo(d, hilo, (sys.argv[sys.argv.index("--modo") + 1] if "--modo" in sys.argv else None))
        except Exception as e: print("Fallo la subida automatica:", e); marcar_fallo(d, d["items"], "Falló la subida: " + str(e))
        hilo.join()
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

def reanudar_only():
    """Lo lanza el vigilante del servidor: retoma las subidas que quedaron cortadas (marcadas 'reanudar')."""
    global D, PLAN
    d = load(); D = d; PLAN = {"up": (0.0, 1.0)}
    keys = {i["key"] for i in d["items"] if i.get("reanudar") and i.get("status") == "ready"}
    if not keys: print("Nada para reanudar."); return
    print("Reanudando subidas cortadas:", len(keys))
    mode = "schedule" if d.get("config", {}).get("publish") == "schedule" else "now"
    try: studio_upload(d, keys, mode)
    except Exception as e: print("Fallo al reanudar:", e); marcar_fallo(d, [i for i in d["items"] if i["key"] in keys], "Falló al reanudar: " + str(e))
    print("Listo.")

RUNF = ROOT / "running.json"; _FIN = threading.Event()

def _latido():
    """Avisa al worker cada 4 s que este proceso sigue vivo (si el worker se reinicia, puede seguirlo o retomarlo)."""
    args = sys.argv[1:]
    while not _FIN.is_set():
        try: RUNF.write_text(json.dumps({"pid": os.getpid(), "t": time.time(), "args": args}), "utf-8")
        except Exception: pass
        _FIN.wait(4)

if __name__ == "__main__":
    import traceback
    threading.Thread(target=_latido, daemon=True).start()
    try:
        main(); _FIN.set(); time.sleep(0.2); RUNF.unlink(missing_ok=True)       # terminó bien: no hay nada que retomar
    except BaseException:
        _FIN.set(); traceback.print_exc()                                     # se cortó: el latido se detiene y el worker lo retoma
        sys.exit(1)
