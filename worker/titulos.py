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
        if t and i.get("status") in ("published", "scheduled", "uploading", "ready"):
            registrar(t)
            if i.get("ia_desc"): registrar_desc(i["ia_desc"])

# ---------------- formato de títulos y descripciones: MAYÚSCULAS + emojis ----------------
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2B1B\u2B1C\u2934\u2935\u2190-\u21FF\u2300-\u23FF\u25A0-\u25FF\u2705\u203C\u2049]\ufe0f?")
EMOJIS_TITULO = ["🔥", "😱", "🤯", "😂", "💥", "⚡", "👀", "🏆", "😮", "🚀", "💯", "🎮"]
EMOJIS_DESC = ["🔥", "👀", "😱", "💥", "👇", "🎮", "⚡", "😂"]
MAX_EMOJIS_TITULO = 4

def _elige(lista, semilla, n):
    h = sum(ord(c) for c in str(semilla)) or 1
    return [lista[(h + i * 5) % len(lista)] for i in range(n)]

def formatear(t, maximo=95):
    """Título SIEMPRE en MAYÚSCULAS y con emojis (2 a 4). Si no trae emojis se le agregan; si se pasa del largo, se recorta el texto y quedan los emojis."""
    t = re.sub(r"\s+", " ", str(t or "")).strip().strip("\"“”«»").strip()
    if not t: return t
    t = t.upper()
    ems = EMOJI.findall(t)
    sin = re.sub(r"\s+", " ", EMOJI.sub("", t)).strip(" ·-–—|\"“”«»")
    if len(ems) > MAX_EMOJIS_TITULO: ems = ems[:MAX_EMOJIS_TITULO]
    if not ems: ems = _elige(EMOJIS_TITULO, sin, 2)
    elif len(ems) == 1: ems = ems + [e for e in _elige(EMOJIS_TITULO, sin, 2) if e != ems[0]][:1]
    cola = "".join(ems)
    lim = maximo - len(cola) - 1
    if len(sin) > lim:
        corte = sin[:lim]; sin = (corte.rsplit(" ", 1)[0] if " " in corte[lim // 2:] else corte).rstrip(" ,;:-–—")
    return (sin + " " + cola).strip()

def formatear_desc(d, titulo=""):
    """Descripción con emojis: si no trae ninguno, se le pone uno al inicio y una invitación al final antes de los hashtags."""
    d = str(d or "").strip()
    if not d: return d
    sem = titulo or d
    if len(EMOJI.findall(d)) < 2:
        lineas = d.split("\n"); 
        if not EMOJI.search(lineas[0]): lineas[0] = _elige(EMOJIS_DESC, sem, 1)[0] + " " + lineas[0]
        d = "\n".join(lineas)
        if len(EMOJI.findall(d)) < 2:
            cuerpo, tags = (d.rsplit("\n", 1) + [""])[:2] if re.search(r"(^|\n)\s*#\w+[^\n]*$", d) else (d, "")
            d = (cuerpo.rstrip() + " " + _elige(EMOJIS_DESC, sem + "x", 2)[1] + ("\n" + tags if tags else "")).strip()
    return d

TAGS_DEF = "#MobileLegends #mlbb #shorts #gameplay #fyp"

def etiquetas(s=None):
    """Hashtags por defecto (cuando la IA no responde o está apagada). Acepta con o sin # y separados por espacios o comas."""
    t = [("#" + x.lstrip("#")) for x in re.split(r"[\s,;]+", str(s if s is not None and str(s).strip() else TAGS_DEF)) if x.strip("#")]
    return " ".join(dict.fromkeys(t))

def limpiar_original(t):
    """El título copiado sin hashtags, enlaces ni palabras vacías como 'video' o 'reel' (para dárselo a la IA o decidir si dice algo)."""
    t = re.sub(r"https?://\S+|#\w+", " ", str(t or ""))
    t = re.sub(r"\b(video|reel|reels|short|shorts)\b[\s,.:;-]*", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" ,.;:-")

def con_etiquetas(t, tags, maximo=100):
    """Agrega al final del título los hashtags que entren completos (sin cortar ninguno a la mitad)."""
    t = str(t or "").strip()
    for h in str(tags or "").split():
        if len(t) + 1 + len(h) <= maximo and h.lower() not in t.lower(): t += " " + h
    return t

_VIDEO = re.compile(r"(?<!\w)#?v[ií]deos?(?!\w)", re.I)

def sin_video(t, tags=None):
    """Nunca queda la palabra «video»: se reemplaza por los hashtags por defecto. Sin hashtags repetidos ni signos sueltos."""
    tags = etiquetas(tags)
    t = _VIDEO.sub(" " + tags + " ", str(t or ""))
    vistos = set()
    def uno(m):
        k = m.group(0).lower()
        if k in vistos: return ""
        vistos.add(k); return m.group(0)
    t = re.sub(r"#\w+", uno, t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"(^|\s)[,;:.\-–—]+(?=\s|$)", r"\1", t)
    t = re.sub(r"[ \t]+([,.;:!?])", r"\1", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    return t.strip(" ,;:-–—\t")

def ajustar(t, maximo=100):
    """Recorta en una palabra completa (nunca a mitad de un hashtag)."""
    t = str(t or "").strip()
    if len(t) <= maximo: return t
    corte = t[:maximo]
    return (corte.rsplit(" ", 1)[0] if " " in corte else corte).rstrip(" ,;:-–—")

def fallback(texto, tema, prohibidos, n=1):
    """Ultimo recurso sin IA: arma un titulo a partir de lo que se dice en el clip (no del titulo copiado)."""
    base = re.sub(r"\s+", " ", str(texto or "")).strip()
    frase = re.split(r"(?<=[.!?])\s+", base)[0][:62].strip(" ,;:-") if base else ""
    cand = [f"{frase.capitalize()}… 😱" if frase else "", f"{tema or 'Momento'}: lo que nadie esperaba", f"{tema or 'Momento'} que se volvió viral", f"No vas a creer este momento de {tema or 'este clip'}"]
    for c in [x for x in cand if x]:
        c = formatear(c)
        if not repetido(c, prohibidos): return c
    k = n
    while True:
        c = formatear(f"{(cand[1] if len(cand) > 1 else 'Clip')} {k}")
        if not repetido(c, prohibidos): return c
        k += 1


# ---------------- descripciones: tampoco se repiten ----------------
DF = ROOT / "descripciones-usadas.json"

def _sin_tags(t):
    return re.sub(r"#\w+", " ", str(t or ""))

def descripciones_usadas():
    try: return json.loads(DF.read_text("utf-8")).get("usadas", [])
    except Exception: return []

def desc_repetida(desc, otras):
    """Igual o muy parecida (sin contar hashtags) a otra ya usada."""
    return any(parecido(_sin_tags(desc), _sin_tags(x)) for x in otras if _sin_tags(x).strip()) if _sin_tags(desc).strip() else False

def registrar_desc(desc):
    with _L:
        u = descripciones_usadas()
        if not desc_repetida(desc, u):
            u = (u + [str(desc)[:600]])[-1500:]
            tmp = DF.with_suffix(".tmp"); tmp.write_text(json.dumps({"usadas": u}, ensure_ascii=False, indent=1), "utf-8"); os.replace(tmp, DF)

def desc_fallback(titulo, texto, tema, otras, k=1, tags=None):
    """Descripcion propia y unica armada con el titulo y lo que se dice en el clip."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", str(texto or ""))) if len(f.strip()) > 12]
    base = (" ".join(frases[:2])[:230] + "\n\n") if frases else ""
    tag = etiquetas(tags)
    cand = [f"🔥 {titulo}\n\n{base}👀 ¡Mirá hasta el final!\n\n{tag}", f"{base}😱 {titulo} · ¡no te lo pierdas! 👇\n\n{tag}"]
    for c in cand:
        c = formatear_desc(c, titulo)
        if not desc_repetida(c, otras): return c.strip()
    n = k
    while True:
        c = formatear_desc(f"🔥 {titulo}\n\n{base}Parte {n} 👀\n\n{tag}", titulo)
        if not desc_repetida(c, otras): return c.strip()
        n += 1
