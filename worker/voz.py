"""Voz a texto que funciona tambien en Windows 8.1.

1) faster-whisper (mejor calidad). Si PyAV no carga (Windows 8.1) se evita: pasamos el audio ya decodificado.
2) Vosk (modelo ligero, se descarga una vez) si faster-whisper no se puede usar.
"""
import json, pathlib, subprocess, sys, types, urllib.request, zipfile

ROOT = pathlib.Path(__file__).parent
MODELOS = ROOT / "modelos"
VOSK = {"es": "vosk-model-small-es-0.42", "en": "vosk-model-small-en-us-0.15"}
_WM, _VM, _FALLO = {}, {}, set()

class Palabra:
    def __init__(self, a, b, w): self.start, self.end, self.word = float(a), float(b), " " + str(w).strip()

def pcm(ffmpeg, src, start, length):
    r = subprocess.run([str(ffmpeg), "-loglevel", "error", "-ss", str(start), "-t", str(length), "-i", str(src),
                        "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True)
    return r.stdout

def _whisper_model(nombre):
    if nombre in _WM: return _WM[nombre]
    try:
        from faster_whisper import WhisperModel
    except Exception:
        for k in [k for k in sys.modules if k.startswith("faster_whisper") or k == "av" or k.startswith("av.")]: del sys.modules[k]
        sys.modules["av"] = types.ModuleType("av")      # PyAV no hace falta: el audio ya viene decodificado
        from faster_whisper import WhisperModel
    _WM[nombre] = WhisperModel(nombre, compute_type="int8")
    return _WM[nombre]

def _con_whisper(data, lang, modelo, prog, chk):
    import numpy as np
    audio = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
    total = max(len(audio) / 16000, 1); m = _whisper_model(modelo); idioma = None if lang == "auto" else lang
    try: segs, _ = m.transcribe(audio, language=idioma, vad_filter=True, word_timestamps=True)
    except Exception: segs, _ = m.transcribe(audio, language=idioma, vad_filter=False, word_timestamps=True)
    out = []
    for s in segs:
        chk(); out += [Palabra(w.start, w.end, w.word) for w in (s.words or [])]; prog(s.end / total)
    return out

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

def palabras(ffmpeg, src, start, length, lang, modelo, prog, chk):
    """-> lista de Palabra con tiempos relativos al tramo. Lanza RuntimeError si ningun motor funciona."""
    data = pcm(ffmpeg, src, start, length); errs = []
    for motor in ("whisper", "vosk"):
        if motor in _FALLO: continue
        try:
            out = _con_whisper(data, lang, modelo, prog, chk) if motor == "whisper" else _con_vosk(data, lang, prog, chk)
            print("  Voz: " + ("faster-whisper" if motor == "whisper" else "Vosk (modelo ligero)"))
            return out
        except KeyboardInterrupt: raise
        except Exception as e:
            if type(e).__name__ == "Cancelled": raise
            _FALLO.add(motor); errs.append(f"{motor}: {str(e)[:110]}")
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
