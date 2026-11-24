"""Voz a texto con varios motores (si uno falla o es flojo, sigue el siguiente).

Motores, de mejor a mas liviano:
  groq_v3     Whisper large-v3 en la nube de Groq (el mas preciso; usa tu clave de Groq, gratis dentro de la cuota)
  groq_turbo  Whisper large-v3-turbo en Groq (casi igual de bueno y mas rapido)
  local       faster-whisper en tu PC, con el modelo que elijas (tiny ... large-v3)
  vosk        modelo ligero offline (ultimo recurso)

Idiomas: es (Español), es-latino (Español latinoamericano), en (Inglés), auto (detectar).
En todos se le da a Whisper una "pista" (idioma, puntuación y el título del video) que mejora tildes, nombres y jerga.
"""
import json, os, pathlib, re, subprocess, sys, tempfile, time, types, urllib.error, urllib.request, uuid, zipfile

ROOT = pathlib.Path(__file__).parent
MODELOS = ROOT / "modelos"
VOSK = {"es": "vosk-model-small-es-0.42", "en": "vosk-model-small-en-us-0.15"}
GROQ_MODELOS = {"groq_v3": "whisper-large-v3", "groq_turbo": "whisper-large-v3-turbo"}
LOCAL_ALIAS = {"turbo": "large-v3-turbo", "large": "large-v3"}
LOCAL_REPO = {"large-v3-turbo": ["large-v3-turbo", "deepdml/faster-whisper-large-v3-turbo-ct2"]}
_WM, _VM, _FALLO = {}, {}, set()
ULTIMO = ""
TROZO = 240         # segundos por envio a la nube (cada trozo pesa pocos MB)

class Palabra:
    def __init__(self, a, b, w): self.start, self.end, self.word = float(a), float(b), " " + str(w).strip()

# ---------- idioma y "pista" para Whisper
def idioma(lang, titulo=""):
    """-> (codigo de idioma o None, pista de texto)."""
    lang = (lang or "es").lower()
    base = {"es": "Transcripción en español, con tildes, signos ¿? ¡! y buena puntuación.",
            "es-latino": "Transcripción en español latinoamericano (Argentina, México, Colombia, Chile). Habla coloquial, con voseo y jerga; tildes, signos ¿? ¡! y buena puntuación.",
            "en": "Clear English transcript with correct punctuation.",
            "auto": ""}.get(lang, "")
    codigo = None if lang == "auto" else ("es" if lang.startswith("es") else lang[:2])
    t = re.sub(r"\s+", " ", str(titulo or "")).strip()[:120]
    pista = (base + (f" Tema del video: {t}." if t else "")).strip()
    return codigo, pista

def pcm(ffmpeg, src, start, length):
    r = subprocess.run([str(ffmpeg), "-loglevel", "error", "-ss", str(start), "-t", str(length), "-i", str(src),
                        "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True)
    return r.stdout

# ---------- Groq (nube)
def _clave_groq():
    try: return json.loads((ROOT / "claves-ia.json").read_text("utf-8")).get("groq") or ""
    except Exception: return ""

def _multipart(campos, nombre, datos, mime):
    b = uuid.uuid4().hex; out = []
    for k, v in campos:
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    out += [datos, f"\r\n--{b}--\r\n".encode()]
    return b"".join(out), "multipart/form-data; boundary=" + b

def _post_groq(modelo, datos, codigo, pista, clave, url="https://api.groq.com/openai/v1/audio/transcriptions"):
    campos = [("model", modelo), ("response_format", "verbose_json"), ("timestamp_granularities[]", "word"),
              ("timestamp_granularities[]", "segment"), ("temperature", "0")]
    if codigo: campos.append(("language", codigo))
    if pista: campos.append(("prompt", pista[:600]))
    cuerpo, ctype = _multipart(campos, "audio.flac", datos, "audio/flac")
    for intento in range(3):
        req = urllib.request.Request(url, data=cuerpo, method="POST", headers={
            "Authorization": "Bearer " + clave, "Content-Type": ctype, "User-Agent": "Yutu-Worker/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r: return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:200]
            if e.code in (429, 500, 502, 503) and intento < 2:
                try: espera = float(e.headers.get("retry-after") or 0)
                except Exception: espera = 0
                time.sleep(min(max(espera, 3 * (intento + 1)), 25)); continue
            raise RuntimeError(f"Groq {modelo}: HTTP {e.code} {msg}")
        except urllib.error.URLError as e:
            if intento < 2: time.sleep(2); continue
            raise RuntimeError("Groq sin conexión: " + str(e.reason)[:80])

def _flac(ffmpeg, src, a, dur, destino):
    subprocess.run([str(ffmpeg), "-loglevel", "error", "-y", "-ss", str(a), "-t", str(dur), "-i", str(src),
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(destino)], check=True)

def _norm(t): return re.sub(r"[\W_]+", "", str(t).lower())

def _palabras_groq(resp, offset):
    """Palabras con tiempo; descarta segmentos que son ruido/silencio (Whisper inventa 'Gracias por ver el video').
    La API entrega las palabras sin puntuacion: se la devolvemos desde el texto del segmento cuando coinciden."""
    segs = resp.get("segments", [])
    malos = [(s["start"], s["end"]) for s in segs if s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -0.8]
    crudas = [(float(w["start"]), float(w["end"]), str(w["word"]).strip()) for w in resp.get("words") or []]
    crudas = [w for w in crudas if not any(x <= (w[0] + w[1]) / 2 <= y for x, y in malos)]
    for s in segs:                                                    # puntuacion y mayusculas del texto del segmento
        if (s["start"], s["end"]) in malos: continue
        idx = [i for i, w in enumerate(crudas) if s["start"] - 0.05 <= (w[0] + w[1]) / 2 <= s["end"] + 0.05]
        toks = str(s.get("text", "")).split()
        if idx and len(toks) == len(idx) and all(_norm(t) == _norm(crudas[i][2]) for t, i in zip(toks, idx)):
            for t, i in zip(toks, idx): crudas[i] = (crudas[i][0], crudas[i][1], t)
    out = [Palabra(a + offset, b + offset, w) for a, b, w in crudas]
    if not out:                                                       # sin tiempos por palabra: se reparten dentro de cada segmento
        for s in segs:
            if (s["start"], s["end"]) in malos: continue
            ws = str(s.get("text", "")).split()
            if not ws: continue
            a, b = float(s["start"]), float(s["end"]); paso = (b - a) / len(ws)
            out += [Palabra(a + offset + i * paso, a + offset + (i + 1) * paso, w) for i, w in enumerate(ws)]
    return out

def _con_groq(motor, ffmpeg, src, start, length, lang, titulo, prog, chk):
    clave = _clave_groq()
    if not clave: raise RuntimeError("falta la clave de Groq")
    codigo, pista = idioma(lang, titulo); modelo = GROQ_MODELOS[motor]
    out, hecho = [], 0.0
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yutu-voz-"))
    try:
        while hecho < length - 0.05:
            chk(); dur = min(TROZO, length - hecho); f = tmp / "t.flac"
            _flac(ffmpeg, src, start + hecho, dur, f)
            datos = f.read_bytes()
            if len(datos) > 24 * 1048576: raise RuntimeError("trozo de audio demasiado grande para Groq")
            out += _palabras_groq(_post_groq(modelo, datos, codigo, pista, clave), hecho)
            hecho += dur; prog(min(hecho / max(length, 1), 1.0))
    finally:
        for x in tmp.glob("*"): x.unlink(missing_ok=True)
        try: tmp.rmdir()
        except Exception: pass
    return out

# ---------- faster-whisper (local)
def _whisper_model(nombre):
    if nombre in _WM: return _WM[nombre]
    try:
        from faster_whisper import WhisperModel
    except Exception:
        for k in [k for k in sys.modules if k.startswith("faster_whisper") or k == "av" or k.startswith("av.")]: del sys.modules[k]
        sys.modules["av"] = types.ModuleType("av")      # PyAV no hace falta: el audio ya viene decodificado
        from faster_whisper import WhisperModel
    ultimo = None
    for repo in LOCAL_REPO.get(nombre, [nombre]):
        try:
            _WM[nombre] = WhisperModel(repo, compute_type="int8"); return _WM[nombre]
        except Exception as e: ultimo = e
    raise ultimo

def _con_whisper(data, lang, modelo, titulo, prog, chk):
    import numpy as np
    modelo = LOCAL_ALIAS.get(modelo, modelo)
    audio = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
    total = max(len(audio) / 16000, 1); m = _whisper_model(modelo)
    codigo, pista = idioma(lang, titulo)
    base = dict(language=codigo, word_timestamps=True, beam_size=5, initial_prompt=pista or None,
                condition_on_previous_text=False)      # evita que un error se repita en todo el video
    def correr(vad):
        try: segs, _ = m.transcribe(audio, vad_filter=vad, **base)
        except Exception:
            if not vad: raise
            segs, _ = m.transcribe(audio, vad_filter=False, **base)
        out = []
        for s in segs:
            chk(); out += [Palabra(w.start, w.end, w.word) for w in (s.words or [])]; prog(s.end / total)
        return out
    out = correr(True)
    return out or correr(False)                         # musica/cantos: el filtro de voz a veces los borra

# ---------- Vosk (ligero)
def _modelo_vosk(lang):
    from vosk import Model
    code = "en" if lang == "en" else "es"
    if code in _VM: return _VM[code]
    d = MODELOS / VOSK[code]
    if not d.exists():
        MODELOS.mkdir(exist_ok=True); z = MODELOS / (VOSK[code] + ".zip")
        print(f"  Descargando modelo de voz ligero ({VOSK[code]}), solo la primera vez...")
        urllib.request.urlretrieve(f"https://alphacephei.com/vosk/models/{VOSK[code]}.zip", z)
        with zipfile.ZipFile(z) as f: f.extractall(MODELOS)
        z.unlink(missing_ok=True)
    _VM[code] = Model(str(d)); return _VM[code]

def _con_vosk(data, lang, prog, chk):
    from vosk import KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    rec = KaldiRecognizer(_modelo_vosk(lang), 16000); rec.SetWords(True)
    res, paso = [], 32000
    for i in range(0, len(data), paso):
        chk()
        if rec.AcceptWaveform(data[i:i + paso]): res += json.loads(rec.Result()).get("result", [])
        prog(i / max(len(data), 1))
    res += json.loads(rec.FinalResult()).get("result", [])
    return [Palabra(x["start"], x["end"], x["word"]) for x in res]

# ---------- orden de motores
NOMBRES = {"groq_v3": "Groq Whisper large-v3", "groq_turbo": "Groq Whisper large-v3-turbo", "local": "Whisper local", "vosk": "Vosk (modelo ligero)"}

def orden(motor):
    motor = (motor or "auto").lower()
    tiene_groq = bool(_clave_groq())
    if motor == "rapido": base = ["groq_turbo", "local", "vosk"]
    elif motor == "local": base = ["local", "groq_v3", "groq_turbo", "vosk"]
    elif motor == "vosk": base = ["vosk", "local"]
    elif motor in GROQ_MODELOS: base = [motor] + [m for m in ("groq_v3", "groq_turbo") if m != motor] + ["local", "vosk"]
    else: base = ["groq_v3", "groq_turbo", "local", "vosk"]            # auto: lo mejor primero
    return [m for m in base if tiene_groq or m not in GROQ_MODELOS]

def palabras(ffmpeg, src, start, length, lang, modelo, prog, chk, motor="auto", titulo="", solo_nube=False):
    """-> lista de Palabra con tiempos relativos al tramo. Lanza RuntimeError si ningun motor funciona."""
    errs, data = [], None
    ms = [m for m in orden(motor) if m in GROQ_MODELOS] if solo_nube else orden(motor)
    if solo_nube and not ms: raise RuntimeError("sin motor en la nube (Groq): no se analiza el video completo en la PC")
    for m in ms:
        if m in _FALLO: continue
        try:
            if m in GROQ_MODELOS: out = _con_groq(m, ffmpeg, src, start, length, lang, titulo, prog, chk)
            else:
                if data is None: data = pcm(ffmpeg, src, start, length)
                out = _con_whisper(data, lang, modelo, titulo, prog, chk) if m == "local" else _con_vosk(data, lang, prog, chk)
            if not out and m != "vosk": errs.append(f"{m}: sin palabras"); continue
            globals()["ULTIMO"] = m
            print("  Voz: " + NOMBRES[m] + (f" ({LOCAL_ALIAS.get(modelo, modelo)})" if m == "local" else ""))
            return out
        except KeyboardInterrupt: raise
        except Exception as e:
            if type(e).__name__ == "Cancelled": raise
            if not re.search(r"HTTP 429|HTTP 5\d\d|sin conexi", str(e)): _FALLO.add(m)     # cuota/red: se reintenta en el proximo video
            errs.append(f"{m}: {str(e)[:110]}"); print("  Voz: " + NOMBRES[m] + " no funcionó (" + str(e)[:90] + "), pruebo el siguiente.")
    raise RuntimeError(" | ".join(errs) or "sin motor de voz")

def frases(words, pausa=0.8, maxp=14):
    """Agrupa palabras en frases (inicio, fin, texto) para que la IA vea la transcripcion."""
    out, cur = [], []
    for w in words:
        if cur and (w.start - cur[-1].end > pausa or len(cur) >= maxp):
            out.append((cur[0].start, cur[-1].end, "".join(x.word for x in cur).strip())); cur = []
        cur.append(w)
    if cur: out.append((cur[0].start, cur[-1].end, "".join(x.word for x in cur).strip()))
    return out
