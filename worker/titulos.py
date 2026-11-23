"""Registro de titulos: nunca se publica el titulo del video copiado, el titulo original ni uno ya usado antes."""
import json, os, pathlib, re, threading, unicodedata, difflib
ROOT = pathlib.Path(__file__).parent
TF = ROOT / "titulos-usados.json"
_L = threading.Lock()

def norm(t):
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t).split() and " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split()) or ""

def _cargar():
    try: return json.loads(TF.read_text("utf-8")).get("usados", [])
    except Exception: return []

def usados(extra=()):
    return _cargar() + [str(x) for x in extra if x]

def parecido(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb: return False
    if na == nb: return True
    if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.82: return True
    sa, sb = set(na.split()), set(nb.split())
    return len(sa) >= 3 and len(sb) >= 3 and len(sa & sb) / min(len(sa), len(sb)) >= 0.85

def repetido(titulo, prohibidos):
    return any(parecido(titulo, x) for x in prohibidos)

def registrar(titulo):
    with _L:
        u = _cargar()
        if not any(norm(x) == norm(titulo) for x in u):
            u = (u + [titulo])[-1500:]
            tmp = TF.with_suffix(".tmp"); tmp.write_text(json.dumps({"usados": u}, ensure_ascii=False, indent=1), "utf-8"); os.replace(tmp, TF)

def sembrar(items):
    """Al arrancar: los titulos de lo que ya esta en la cola cuentan como usados."""
    for i in items:
        t = i.get("final_title") or i.get("ia_title")
        if t and i.get("status") in ("published", "scheduled", "uploading", "ready"): registrar(t)

def fallback(texto, tema, prohibidos, n=1):
    """Ultimo recurso sin IA: arma un titulo a partir de lo que se dice en el clip (no del titulo copiado)."""
    base = re.sub(r"\s+", " ", str(texto or "")).strip()
    frase = re.split(r"(?<=[.!?])\s+", base)[0][:62].strip(" ,;:-") if base else ""
    cand = [f"{frase.capitalize()}… 😱" if frase else "", f"{tema or 'Momento'}: lo que nadie esperaba", f"{tema or 'Momento'} que se volvió viral", f"No vas a creer este momento de {tema or 'este clip'}"]
    for c in [x for x in cand if x]:
        if not repetido(c, prohibidos): return c[:95]
    k = n
    while True:
        c = f"{(cand[1] if len(cand) > 1 else 'Clip')} #{k}"
        if not repetido(c, prohibidos): return c[:95]
        k += 1
