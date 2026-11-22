"""Ayuda de IA opcional: Gemini y Grok se turnan como un interruptor.

Regla de oro: la IA SOLO sugiere. Todo se valida y, si una IA falla, tarda o responde mal,
se prueba con la otra y, si tampoco, la edicion sigue con tu configuracion normal.
Las claves viven solo en claves-ia.json (esta carpeta). No se suben a GitHub ni salen en la web.
"""
import json, os, pathlib, re, urllib.error, urllib.request
import efectos

ROOT = pathlib.Path(__file__).parent
KF = ROOT / "claves-ia.json"
TIMEOUT = 40
NOMBRE = {"gemini": "Gemini", "grok": "Grok", "claude": "Claude"}
CICLO = ["gemini", "grok", "claude"]
_grok_model = [None]

# ---------- claves (nunca se devuelven a la web)
def cargar():
    try: return json.loads(KF.read_text("utf-8"))
    except Exception: return {}

def guardar(d):
    tmp = KF.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=2), "utf-8"); os.replace(tmp, KF)

def estado():
    d = cargar()
    return {"gemini": bool(d.get("gemini")), "grok": bool(d.get("grok")), "claude": bool(d.get("claude")), "ultimo": NOMBRE.get(d.get("ultimo"), "")}

def set_claves(data):
    d = cargar()
    for p in CICLO:
        v = str(data.get(p) or "").strip()
        if v:
            if len(v) > 300 or re.search(r"\s", v): raise ValueError("La clave no parece válida (tiene espacios).")
            d[p] = v
    if data.get("borrar") in CICLO: d.pop(data["borrar"], None)
    guardar(d)

# ---------- HTTP
def _http(url, body=None, headers=None):
    h = {"Content-Type": "application/json"}; h.update(headers or {})
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=h,
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r: return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.read().decode('utf-8', 'replace')[:160]}")

def _gemini(prompt, d):
    model = d.get("modelo_gemini") or "gemini-flash-latest"
    cuerpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}}
    try:
        r = _http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", cuerpo, {"x-goog-api-key": d["gemini"]})
    except RuntimeError as e1:
        if d["gemini"].startswith("AIza"): raise                      # clave normal de AI Studio: el error es real
        try:                                                          # claves "AQ." = Vertex AI (modo express)
            r = _http("https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash:generateContent",
                      cuerpo, {"x-goog-api-key": d["gemini"]})
        except RuntimeError as e2:
            raise RuntimeError(f"AI Studio: {str(e1)[:70]} | Vertex: {str(e2)[:70]}")
    return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])

def _elegir_grok(d):
    if d.get("modelo_grok"): return d["modelo_grok"]
    if _grok_model[0]: return _grok_model[0]
    r = _http("https://api.x.ai/v1/models", None, {"Authorization": "Bearer " + d["grok"]})
    ids = [m["id"] for m in r.get("data", []) if str(m.get("id", "")).startswith("grok")
           and not re.search(r"image|imagine|video|embed|vision", m["id"])]
    if not ids: raise RuntimeError("Tu clave de Grok no lista modelos de texto.")
    ids.sort(key=lambda i: (("fast" in i or "mini" in i), i), reverse=True)   # prefiere los rapidos
    _grok_model[0] = ids[0]; return ids[0]

def _grok(prompt, d):
    r = _http("https://api.x.ai/v1/chat/completions",
              {"model": _elegir_grok(d), "temperature": 0.4,
               "messages": [{"role": "system", "content": "Respondes SOLO con JSON válido, sin texto extra."},
                            {"role": "user", "content": prompt}]},
              {"Authorization": "Bearer " + d["grok"]})
    return r["choices"][0]["message"]["content"]

def _claude(prompt, d):
    r = _http("https://api.anthropic.com/v1/messages",
              {"model": d.get("modelo_claude") or "claude-haiku-5-5", "max_tokens": 2500,
               "system": "Respondes SOLO con JSON válido, sin texto extra.",
               "messages": [{"role": "user", "content": prompt}]},
              {"x-api-key": d["claude"], "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")

def _json(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    a, b = txt.find("{"), txt.rfind("}")
    return json.loads(txt[a:b + 1])

# ---------- el interruptor
def _orden(modo, d):
    tiene = [p for p in CICLO if d.get(p)]
    if modo == "apagado" or not tiene: return []
    if modo.startswith("solo_"): return [p for p in tiene if p == modo[5:]]
    if modo.endswith("_primero"):
        p0 = modo[:-8]; base = [p0] + [p for p in CICLO if p != p0]       # el elegido y luego los demas de respaldo
    else:                                                                  # alternar: sigue el turno, los demas de respaldo
        ult = d.get("ultimo"); i = (CICLO.index(ult) + 1) % len(CICLO) if ult in CICLO else 0
        base = CICLO[i:] + CICLO[:i]
    return [p for p in base if p in tiene]

def pedir(prompt, modo="alternar"):
    """-> (dict, proveedor) o (None, None). Nunca lanza excepciones."""
    d = cargar()
    for p in _orden(modo, d):
        try:
            data = _json(globals()["_" + p](prompt, d))
            if isinstance(data, dict):
                d = cargar(); d["ultimo"] = p; guardar(d)
                return data, p
        except Exception as e:
            print(f"  IA {NOMBRE[p]} no respondió bien ({str(e)[:140]}). Pruebo con la otra o sigo sin IA.")
    return None, None

def probar(p):
    d = cargar()
    if not d.get(p): return False, f"Falta la clave de {NOMBRE[p]}."
    try:
        r = _json(globals()["_" + p]('Responde exactamente este JSON: {"ok": true}', d))
        return bool(r.get("ok")), f"{NOMBRE[p]} funciona." if r.get("ok") else f"{NOMBRE[p]} respondió algo inesperado."
    except Exception as e:
        return False, f"{NOMBRE[p]} falló: {str(e)[:140]}"

# ---------- tareas (todas devuelven None si no hay ayuda utilizable)
def momento(modo, titulo, segs, dur, L):
    texto = "\n".join(f"[{int(a)}s] {t}" for a, b, t in segs)[:14000]
    if not texto.strip(): return None
    data, p = pedir(f'''Eres editor de video. Elige el tramo CONTINUO de {L:.0f} segundos más atractivo del video: gancho fuerte al inicio, idea completa, sin cortar frases.
Video: "{titulo}" ({dur:.0f} s). Transcripción con marcas de tiempo:
{texto}
Responde SOLO este JSON: {{"inicio": <segundo de inicio>, "motivo": "<una frase>"}}''', modo)
    try:
        s = float(data["inicio"])
        if not (0 <= s <= dur - L): return None
        cerca = min(segs, key=lambda x: abs(x[0] - s))          # pega el inicio al comienzo de una frase
        if abs(cerca[0] - s) <= 4 and cerca[0] <= dur - L: s = cerca[0]
        return {"inicio": s, "prov": NOMBRE[p], "motivo": str(data.get("motivo", ""))[:120]}
    except Exception: return None

def efecto_plan(modo, titulo, texto, kind, L, permitidos):
    cat = "\n".join(f"- {k}: {efectos.EFECTOS[k]}" for k in permitidos if k in efectos.EFECTOS)
    data, p = pedir(f'''Eres editor de video. Para un {"Short vertical" if kind == "short" else "video"} de {L:.0f} s titulado "{titulo}" elige entre 3 y 7 efectos de ESTA lista (solo estos ids) y cómo combinarlos para que el video se sienta dinámico sin saturar.
Contenido (extracto): {texto[:1500] or "(sin texto)"}
Efectos permitidos:
{cat}
Modos: "seq" (uno tras otro), "overlap" (entrelazados), "random", "stack" (todos a la vez).
Responde SOLO este JSON: {{"fx_list": ["id", ...], "fx_mode": "seq|overlap|random|stack", "fx_dur": <segundos 1.5 a 6>, "fx_power": <0.5 a 1.2>, "motivo": "<una frase>"}}''', modo)
    try:
        ids = [i for i in data["fx_list"] if i in permitidos and i in efectos.EFECTOS]
        ids = list(dict.fromkeys(ids))[:8]
        if not ids: return None
        mode = data.get("fx_mode") if data.get("fx_mode") in ("seq", "overlap", "random", "stack") else "seq"
        return {"fx_list": ids, "fx_mode": mode, "fx_dur": min(6, max(1.5, float(data.get("fx_dur", 3)))),
                "fx_power": min(1.2, max(0.5, float(data.get("fx_power", 1)))), "prov": NOMBRE[p],
                "motivo": str(data.get("motivo", ""))[:120]}
    except Exception: return None

def textos(modo, titulo, texto, kind):
    data, p = pedir(f'''Eres editor de YouTube. Escribe un título y una descripción para este {"Short" if kind == "short" else "video"}.
Título original: "{titulo}". Contenido (extracto): {texto[:1500] or "(sin texto)"}
Reglas: mismo idioma del contenido, título atractivo de máximo 90 caracteres, sin mentiras ni promesas falsas, sin inventar datos; descripción de 2 a 3 frases y 3 a 5 hashtags al final.
Responde SOLO este JSON: {{"titulo": "...", "descripcion": "..."}}''', modo)
    try:
        t, desc = str(data["titulo"]).strip(), str(data["descripcion"]).strip()
        if not t or not desc: return None
        return {"titulo": t[:95], "descripcion": desc[:1500], "prov": NOMBRE[p]}
    except Exception: return None

def corregir_subs(modo, titulo, lineas):
    """Corrige ortografia y palabras mal transcritas SIN cambiar cuantas lineas hay ni su significado."""
    data, p = pedir(f'''Eres corrector de subtítulos de video titulado "{titulo}". Corrige ortografía, tildes, puntuación y palabras mal transcritas.
No cambies el significado, no agregues ni quites líneas, no traduzcas. Mantén cada línea corta.
Líneas (JSON): {json.dumps(lineas, ensure_ascii=False)}
Responde SOLO este JSON: {{"lineas": [... exactamente {len(lineas)} textos ...]}}''', modo)
    try:
        out = data["lineas"]
        if not isinstance(out, list) or len(out) != len(lineas): return None
        res = []
        for a, b in zip(lineas, out):
            b = str(b).strip()
            res.append(b if b and 0.5 <= len(b) / max(len(a), 1) <= 1.7 else a)   # descarta cambios raros
        return {"lineas": res, "prov": NOMBRE[p]}
    except Exception: return None
