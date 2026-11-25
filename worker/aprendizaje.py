"""Lo que Yutu va aprendiendo de lo que le enseñás (títulos que funcionan).
- BASE: la lección de partida (título claro, específico y que despierte curiosidad, con ejemplos malos y buenos).
- Tus lecciones: lo que pegues en el panel «🧠 Aprendizaje de títulos» se guarda en aprendizaje.json y se le entrega a la IA en CADA título.
- evaluar(): puntúa un título (0-100) y dice qué le falta; si queda flojo, se le pide a la IA uno mejor antes de subir.
"""
import json, pathlib, re, time

ROOT = pathlib.Path(__file__).parent
AF = ROOT / "aprendizaje.json"
MIN = 60

BASE = """CÓMO ES UN BUEN TÍTULO (lección base):
Un buen título no necesita ser complicado, creativo ni misterioso: necesita ser CLARO, ESPECÍFICO y despertar CURIOSIDAD. El espectador debe entender enseguida de qué trata el video y qué va a encontrar si hace clic; debe tener una razón concreta para verlo (qué descubrirá, qué problema se resuelve o qué experiencia le espera).
Ejemplos:
MALO: «Mi experiencia jugando Minecraft» -> BUENO: «Sobreviví 100 Días en Minecraft Hardcore sin Morir»
MALO: «Conociendo Japón» -> BUENO: «10 Lugares de Japón que Debes Visitar en tu Primer Viaje»
MALO: «Mi rutina de ejercicio» -> BUENO: «Rutina de 30 Minutos para Fortalecer Todo el Cuerpo en Casa»
Los malos dicen más o menos de qué trata pero no dan una razón para verlo; los buenos tienen una propuesta clara: un número, un resultado, un reto o un beneficio concreto.
Siempre sin mentir: la promesa del título debe cumplirse en el video.
FORMATO DE LA CASA: los ejemplos de arriba muestran la idea, pero los títulos de Yutu se escriben SIEMPRE EN MAYÚSCULAS y con 2 a 4 emojis (ej: «SOBREVIVÍ 100 DÍAS EN MINECRAFT HARDCORE SIN MORIR 😱🔥»). Tienen que ser muy atractivos."""


def _cargar():
    try: d = json.loads(AF.read_text("utf-8"))
    except Exception: d = {}
    d.setdefault("lecciones", []); return d


def _guardar(d):
    tmp = AF.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8"); tmp.replace(AF)


def listar():
    return [{"i": i, "t": x["t"], "f": x.get("f", "")} for i, x in enumerate(_cargar()["lecciones"])]


def agregar(texto):
    t = re.sub(r"\n{3,}", "\n\n", str(texto or "").strip())[:2500]
    if len(t) < 12: raise ValueError("Escribí algo más largo (un consejo, un ejemplo bueno y uno malo...).")
    d = _cargar()
    if any(x["t"] == t for x in d["lecciones"]): return len(d["lecciones"])
    d["lecciones"] = (d["lecciones"] + [{"t": t, "f": time.strftime("%Y-%m-%d")}])[-40:]; _guardar(d); return len(d["lecciones"])


def borrar(i):
    d = _cargar()
    if 0 <= int(i) < len(d["lecciones"]): d["lecciones"].pop(int(i)); _guardar(d)


def guia():
    """Bloque para el prompt de la IA: lección base + lo que le enseñaste (lo más reciente primero, hasta ~3500 caracteres)."""
    ls, usado, out = _cargar()["lecciones"], 0, []
    for x in reversed(ls):
        if usado + len(x["t"]) > 3500: break
        out.append("- " + x["t"].replace("\n", " ")); usado += len(x["t"])
    extra = ("\nLO QUE EL USUARIO TE ENSEÑÓ (aplicalo; lo más reciente manda):\n" + "\n".join(out)) if out else ""
    return BASE + extra


GENERICO = re.compile(r"^(mi|mis|mí|un d[ií]a|conociendo|jugando|probando|video|short|clip|parte|momento|vlog|hola|hoy)\b|\b(mi experiencia|mi rutina|mi opini[oó]n|un d[ií]a en|sin t[ií]tulo)\b", re.I)
CURIOSIDAD = re.compile(r"\b(c[oó]mo|por qu[eé]|qu[eé] pasa|sin|nunca|jam[aá]s|secreto|error|truco|mejor|peor|incre[ií]ble|imposible|todo|nadie|s[oó]lo|solo|hasta|antes de|despu[eé]s|as[ií]|esto|lo que|razones|forma|manera|gu[ií]a|reto|logr[eé]|sobrevi|descubr)", re.I)


def evaluar(titulo):
    """(puntaje 0-100, [problemas]). Mide lo que el título tiene que lograr: claro, específico, con razón para hacer clic."""
    t = re.sub(r"\s+", " ", str(titulo or "")).strip(); pro = []; p = 50
    if not t: return 0, ["vacío"]
    n = len(re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\ufe0f]", "", t).strip())      # el largo se mide sin emojis
    if n < 22: p -= 18; pro.append("muy corto: no dice qué vas a encontrar")
    elif n <= 75: p += 12
    elif n <= 90: p += 2
    else: p -= 12; pro.append("muy largo (se corta en el celular)")
    if GENERICO.search(t): p -= 25; pro.append("genérico: no da una razón concreta para verlo")
    if re.search(r"\d", t): p += 14
    else: pro.append("sin número ni dato concreto")
    if CURIOSIDAD.search(t) or "?" in t or ":" in t: p += 12
    else: pro.append("no despierta curiosidad (falta un resultado, reto o beneficio)")
    if t.count("#") or len(re.findall(r"[\U0001F300-\U0001FAFF]", t)) > 5: p -= 8; pro.append("hashtags o demasiados emojis en el título")
    if len(t.split()) >= 6 and len(set(w.lower() for w in t.split())) < len(t.split()) - 2: p -= 6; pro.append("palabras repetidas")
    return max(0, min(100, p)), pro
