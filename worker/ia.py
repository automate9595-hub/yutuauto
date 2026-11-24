"""Ayuda de IA opcional: Gemini y Grok se turnan como un interruptor.

Regla de oro: la IA SOLO sugiere. Todo se valida y, si una IA falla, tarda o responde mal,
se prueba con la otra y, si tampoco, la edicion sigue con tu configuracion normal.
Las claves viven solo en claves-ia.json (esta carpeta). No se suben a GitHub ni salen en la web.
"""
import json, os, pathlib, re, socket, threading, time, urllib.error, urllib.request
import efectos, aprendizaje

ROOT = pathlib.Path(__file__).parent
KF = ROOT / "claves-ia.json"
TIMEOUT = 30
PRESUPUESTO_IA = 60     # tope TOTAL por consulta a la IA: nunca dejar el worker esperando mas de ~1 min
PRESUPUESTO_PROV = 22   # tope por proveedor (Gemini/Groq/Claude): si uno se cuelga, pasa al siguiente
_TL = threading.local() # limite de tiempo propio de cada hilo (los subtitulos corren en paralelo)
NOMBRE = {"gemini": "Gemini", "groq": "Groq", "claude": "Claude"}
CICLO = ["gemini", "groq", "claude"]
PATRON = ["gemini", "groq", "gemini", "claude", "gemini"]
_TURNO = [0]
_groq_modelos = [None]
_gem_modelos = [None]
USADO = {}          # ultimo modelo que respondio, por proveedor (para mostrarlo en la web)
_HASTA = [None]       # limite de tiempo total para la prueba del boton 'Probar'

# ---------- claves (nunca se devuelven a la web)
def cargar():
    try: return json.loads(KF.read_text("utf-8"))
    except Exception: return {}

def guardar(d):
    tmp = KF.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=2), "utf-8"); os.replace(tmp, KF)

def estado():
    d = cargar()
    ks = _claves_gemini(d)
    return {"gemini_n": len(ks), "gemini_libres": sum(1 for k in ks if _GK.get(k, 0) < time.time()), "gemini": bool(d.get("gemini")), "groq": bool(d.get("groq")), "claude": bool(d.get("claude")), "ultimo": NOMBRE.get(d.get("ultimo"), ""),
            "modelo_gemini": d.get("modelo_gemini", ""), "modelo_usado": dict(USADO)}

def set_claves(data):
    d = cargar()
    gv = str(data.get("gemini") or "").strip()
    if gv:                                           # Gemini acepta VARIAS claves (una por línea): se van turnando cuando una se queda sin cuota
        nuevas = [k for k in re.split(r"[\s,;]+", gv) if k]
        if any(len(k) > 300 for k in nuevas): raise ValueError("Una clave no parece válida.")
        ks = _claves_gemini(d) + [k for k in nuevas if k not in _claves_gemini(d)]
        d["gemini"] = ks[0]; d["gemini_extra"] = ks[1:]
    for p in [x for x in CICLO if x != "gemini"]:
        v = str(data.get(p) or "").strip()
        if v:
            if len(v) > 300 or re.search(r"\s", v): raise ValueError("La clave no parece válida (tiene espacios).")
            d[p] = v
    if data.get("borrar") in CICLO:
        d.pop(data["borrar"], None)
        if data["borrar"] == "gemini": d.pop("gemini_extra", None)
    if "modelo_gemini" in data:                      # "" = automatico (el Flash Lite mas nuevo)
        m = str(data.get("modelo_gemini") or "").strip().removeprefix("models/")
        if m and not re.fullmatch(r"[\w.\-]{3,80}", m): raise ValueError("El nombre del modelo no parece válido (ej: gemini-flash-lite-latest).")
        if m: d["modelo_gemini"] = m
        else: d.pop("modelo_gemini", None)
        _gem_modelos[0] = None
    d.pop("caida", None) if any(str(data.get(p) or "").strip() for p in CICLO) else None   # clave nueva: vuelve a intentar
    guardar(d)

# ---------- HTTP
# Orden de preferencia: Flash Lite mas nuevo (se descubre solo con la clave) -> alias -> Flash.
RESPALDO_GEMINI = ["gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-2.5-flash"]

def _http(url, body=None, headers=None):
    h = {"Content-Type": "application/json", "User-Agent": "Yutu-Worker/1.0"}; h.update(headers or {})
    t = TIMEOUT
    if _HASTA[0]:
        t = min(TIMEOUT, _HASTA[0] - time.time())
        if t < 3: raise RuntimeError("Tiempo de espera agotado")
    dl = getattr(_TL, "hasta", None)
    if dl:
        t = min(t, dl - time.time())
        if t < 2: raise RuntimeError("Tiempo de espera agotado")
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=h,
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=t) as r: return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.read().decode('utf-8', 'replace')[:160]}")
    except (socket.timeout, TimeoutError):
        raise RuntimeError("Tiempo de espera agotado")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)): raise RuntimeError("Tiempo de espera agotado")
        raise RuntimeError("Sin conexión con el servicio: " + str(e.reason)[:80])

def _version(nombre):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", nombre)
    return float(m.group(1)) if m else 0.0

def _modelos_gemini(d):
    """Lista de modelos a probar, en orden. Si elegiste uno en la web, solo ese (y luego el respaldo)."""
    if d.get("modelo_gemini"): return [d["modelo_gemini"]] + [m for m in RESPALDO_GEMINI if m != d["modelo_gemini"]]
    if _gem_modelos[0]: return _gem_modelos[0]
    lista = []
    try:
        r = _http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", None, {"x-goog-api-key": d["gemini"]})
        ids = [m["name"].removeprefix("models/") for m in r.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        lite = [i for i in ids if re.search(r"flash-lite", i) and not re.search(r"preview-tts|tts|image|live|audio|embed|exp", i)]
        lite.sort(key=lambda i: (-_version(i), "preview" in i, len(i)))       # el numero mas alto primero; los estables antes que preview
        lista = lite[:3]
    except Exception as e:
        print("  IA Gemini: no pude listar modelos, uso los de respaldo (" + str(e)[:60] + ")")
    lista += [m for m in RESPALDO_GEMINI if m not in lista]
    _gem_modelos[0] = lista
    return lista

_GK = {}            # clave de Gemini -> hasta cuando descansa (sin cuota)
_GKI = [0]

def _claves_gemini(d):
    ks = [d.get("gemini")] + list(d.get("gemini_extra") or [])
    return [k for k in dict.fromkeys(ks) if k]

def _gemini(prompt, d):
    """Varias claves: se usan por turnos y, si una se queda sin cuota (o es inválida), pasa sola a la siguiente."""
    ks = _claves_gemini(d); ult = None
    libres = [k for k in ks if _GK.get(k, 0) < time.time()]
    if libres: n = _GKI[0] % len(libres); libres = libres[n:] + libres[:n]; _GKI[0] += 1
    for i, k in enumerate(libres):
        try: return _gemini_una(prompt, dict(d, gemini=k))
        except RuntimeError as e:
            m = str(e); ult = e
            if re.search(r"HTTP (429|403)|RESOURCE_EXHAUSTED|quota|exceeded", m, re.I):
                _GK[k] = time.time() + (6 * 3600 if re.search(r"per ?day|daily|PerDay", m, re.I) else 120)
                print(f"  IA Gemini: la clave {ks.index(k) + 1} de {len(ks)} se quedó sin cuota; paso a la siguiente.")
            elif re.search(r"HTTP (400|401)", m) and re.search(r"API key|key not valid|invalid", m, re.I):
                _GK[k] = time.time() + 24 * 3600; print(f"  IA Gemini: la clave {ks.index(k) + 1} no es válida; la salto.")
            else: raise
    raise ult or RuntimeError("HTTP 429 Todas las claves de Gemini están sin cuota por ahora.")

def _gemini_una(prompt, d):
    cuerpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}}
    hdr = {"x-goog-api-key": d["gemini"]}; ultimo = RuntimeError("Gemini no respondió"); t0 = time.time()
    def texto(r): return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
    for modelo in _modelos_gemini(d):
        for intento in range(2):
            if time.time() - t0 > 50: raise ultimo                                  # nunca bloquear la edicion mas de ~1 min
            try:
                out = texto(_http(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent", cuerpo, hdr))
                USADO["gemini"] = modelo; return out
            except RuntimeError as e:
                ultimo = e; m = str(e)
                if "Tiempo de espera" in m: break                                    # lento: probar otro modelo
                if re.search(r"HTTP (503|500|429)", m) and intento == 0: time.sleep(2); continue
                if re.search(r"HTTP (503|500|429|404)", m): break
                if re.search(r"HTTP 400", m) and re.search(r"model|not supported|thinking|mime", m, re.I): break   # este modelo no sirve: el siguiente
                if re.search(r"HTTP (400|401|403)", m) and not d["gemini"].startswith("AIza"):
                    try: return texto(_http("https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash:generateContent", cuerpo, hdr))
                    except RuntimeError as e2: raise RuntimeError(f"{m[:80]} | Vertex: {str(e2)[:80]}")
                raise
    raise ultimo

PREFERIDOS_GROQ = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]

def _modelos_groq(d):
    if d.get("modelo_groq"): return [d["modelo_groq"]]
    if _groq_modelos[0]: return _groq_modelos[0]
    r = _http("https://api.groq.com/openai/v1/models", None, {"Authorization": "Bearer " + d["groq"]})
    ids = [m["id"] for m in r.get("data", []) if not re.search(r"whisper|guard|tts|playai|orpheus|distil|embed|safeguard", str(m.get("id", "")), re.I)]
    if not ids: raise RuntimeError("Tu clave de Groq no lista modelos de texto.")
    ids.sort(key=lambda i: PREFERIDOS_GROQ.index(i) if i in PREFERIDOS_GROQ else 99)
    _groq_modelos[0] = ids[:3]; return _groq_modelos[0]

def _groq(prompt, d):
    ultimo = RuntimeError("Groq no respondió")
    for modelo in _modelos_groq(d):
        try:
            r = _http("https://api.groq.com/openai/v1/chat/completions",
                      {"model": modelo, "temperature": 0.4,
                       "messages": [{"role": "system", "content": "Respondes SOLO con JSON válido, sin texto extra."},
                                    {"role": "user", "content": prompt}]},
                      {"Authorization": "Bearer " + d["groq"]})
            USADO["groq"] = modelo
            return r["choices"][0]["message"]["content"]
        except RuntimeError as e:
            ultimo = e
            if re.search(r"decommission|not found|does not exist|HTTP 404|HTTP 400.*model", str(e), re.I): continue   # modelo retirado: siguiente
            raise
    raise ultimo

def _claude(prompt, d):
    r = _http("https://api.anthropic.com/v1/messages",
              {"model": d.get("modelo_claude") or "claude-haiku-5-5", "max_tokens": 2500,
               "system": "Respondes SOLO con JSON válido, sin texto extra.",
               "messages": [{"role": "user", "content": prompt}]},
              {"x-api-key": d["claude"], "anthropic-version": "2023-06-01"})
    USADO["claude"] = d.get("modelo_claude") or "claude-haiku-5-5"
    return "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")

def _json(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    a, b = txt.find("{"), txt.rfind("}")
    return json.loads(txt[a:b + 1])

# ---------- el interruptor
_CAIDAS = set()      # proveedores con clave invalida o sin credito: se saltan el resto de esta edicion

def _explicar(p, e):
    m, n = str(e), NOMBRE[p]
    if re.search(r"credit balance|billing", m, re.I):
        return f"{n}: la clave es válida pero la cuenta no tiene crédito de API. Carga saldo en console.anthropic.com > Plans & Billing (la suscripción de Claude.ai no incluye API)."
    if re.search(r"HTTP (503|500)|high demand|overloaded|unavailable", m, re.I):
        return f"{n}: el servicio está saturado ahora mismo (la clave parece válida). El worker reintenta y usa otro modelo; vuelve a probar en unos minutos."
    if re.search(r"Tiempo de espera|timed out|Sin conexi", m, re.I):
        return f"{n}: no respondió a tiempo (internet lento o servicio saturado). Revisa tu conexión y vuelve a probar."
    if re.search(r"HTTP 429|quota|rate", m, re.I):
        return f"{n}: se acabó la cuota gratuita o el límite por minuto. Prueba más tarde o con otra clave."
    if re.search(r"Incorrect API key|API_KEY_INVALID|invalid x-api-key|authentication|HTTP 401", m, re.I):
        extra = " Las claves de GroqCloud empiezan con gsk_ y se crean en console.groq.com." if p == "groq" else ""
        return f"{n}: la clave no es válida.{extra}"
    return f"{n}: {m[:140]}"

def _en_pausa(p, d):
    c = (d.get("caida") or {}).get(p)
    return bool(c) and time.time() < c

def _pausar(p):
    d = cargar(); d.setdefault("caida", {})[p] = time.time() + 3600; guardar(d)

def _muerta(e):
    m = str(e)
    return not re.search(r"HTTP (503|500|429)", m) and bool(re.search(r"credit balance|billing|Incorrect API key|API_KEY_INVALID|invalid x-api-key|authentication|HTTP 401", m, re.I))

def _orden(modo, d):
    modo = (modo or "alternar").replace("grok", "groq")      # nombres antiguos guardados en la web
    tiene = [p for p in CICLO if d.get(p)]
    if modo == "apagado" or not tiene: return []
    if modo.startswith("solo_"): return [p for p in tiene if p == modo[5:]]
    if modo.endswith("_primero"):
        p0 = modo[:-8]; base = [p0] + [p for p in CICLO if p != p0]       # el elegido y luego los demas de respaldo
    else:                                                                  # alternar: sigue el turno, los demas de respaldo
        # alternar CON PRIORIDAD A GEMINI: de cada 5 pedidos, 3 empiezan en Gemini, 1 en Groq y 1 en Claude (los demas siempre de respaldo)
        p0 = PATRON[_TURNO[0] % len(PATRON)]; _TURNO[0] += 1
        base = [p0] + [p for p in CICLO if p != p0]
    return [p for p in base if p in tiene]

def pedir(prompt, modo="alternar"):
    """-> (dict, proveedor) o (None, None). Nunca lanza excepciones ni espera mas de PRESUPUESTO_IA segundos."""
    d = cargar(); fin = time.time() + PRESUPUESTO_IA
    try:
        for p in [x for x in _orden(modo, d) if x not in _CAIDAS and not _en_pausa(x, d)]:
            if fin - time.time() < 4: print("  IA: se agotó el tiempo de espera; sigo sin IA."); break
            _TL.hasta = min(fin, time.time() + PRESUPUESTO_PROV)
            try:
                data = _json(globals()["_" + p](prompt, d))
                if isinstance(data, dict):
                    d = cargar(); d["ultimo"] = p; guardar(d)
                    return data, p
            except Exception as e:
                if _muerta(e): _CAIDAS.add(p); _pausar(p)
                print(f"  IA {_explicar(p, e)} Sigo con otra IA o sin IA.")
        return None, None
    finally:
        _TL.hasta = None

def texto(prompt, modo="alternar"):
    """Respuesta en texto plano (para los pilotos). Devuelve '' si ninguna IA responde. Nunca lanza excepciones."""
    data, p = pedir(prompt + '\nResponde SOLO este JSON: {"r": "<tu respuesta>"}', modo)
    try: return str(data.get("r", "")).strip() if data else ""
    except Exception: return ""

def probar(p):
    d = cargar()
    if not d.get(p): return False, f"Falta la clave de {NOMBRE[p]}."
    _HASTA[0] = time.time() + 55; _CAIDAS.discard(p)
    try:
        r = _json(globals()["_" + p]('Responde exactamente este JSON: {"ok": true}', d))
        dd = cargar(); (dd.get("caida") or {}).pop(p, None); guardar(dd)
        mod = f" (modelo {USADO[p]})" if USADO.get(p) else ""
        return bool(r.get("ok")), f"{NOMBRE[p]} funciona{mod}." if r.get("ok") else f"{NOMBRE[p]} respondió algo inesperado."
    except Exception as e:
        return False, _explicar(p, e)
    finally: _HASTA[0] = None

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

def momentos(modo, titulo, segs, dur, L, n):
    """Pide a la IA los n mejores tramos DISTINTOS (sin solaparse) para sacar n Shorts del mismo video largo."""
    texto = "\n".join(f"[{int(a)}s] {t}" for a, b, t in segs)[:14000]
    if not texto.strip() or n < 1: return None
    data, p = pedir(f'''Eres editor de video. Del video largo elige los {n} tramos CONTINUOS de {L:.0f} segundos más atractivos para {n} Shorts distintos:
cada uno con gancho fuerte al inicio, una idea completa, sin cortar frases y SIN solaparse entre sí (separados al menos {L:.0f} s).
Video: "{titulo}" ({dur:.0f} s). Transcripción con marcas de tiempo:
{texto}
Responde SOLO este JSON: {{"inicios": [<segundo de inicio de cada tramo>], "motivo": "<una frase>"}}''', modo)
    try:
        out = []
        for s in sorted(float(x) for x in data["inicios"]):
            if not (0 <= s <= dur - L): continue
            cerca = min(segs, key=lambda x: abs(x[0] - s))          # pega el inicio al comienzo de una frase
            if abs(cerca[0] - s) <= 4 and cerca[0] <= dur - L: s = cerca[0]
            if all(abs(s - o) >= L for o in out): out.append(s)
        if len(out) < n: return None                                # incompleto: el worker reparte parejo
        return {"inicios": out[:n], "prov": NOMBRE[p], "motivo": str(data.get("motivo", ""))[:120]}
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

def textos(modo, titulo, texto, kind, prohibidos=(), idioma="", descs=(), feedback=""):
    """Titulo y descripcion NUEVOS: nunca iguales al original ni a los ya usados (lista 'prohibidos')."""
    pro = "\n".join("- " + str(x)[:100] for x in list(prohibidos)[-40:]) or "(ninguno)"
    data, p = pedir(f'''Eres editor de YouTube. Escribe un título y una descripción para este {"Short" if kind == "short" else "video"}.
Título original (NO lo copies ni lo parafrasees de cerca): "{titulo}". Contenido (extracto): {texto[:1500] or "(sin texto)"}
Títulos que YA se usaron (el tuyo debe ser claramente distinto de todos, con otro gancho y otras palabras clave):
{pro}
Descripciones que YA se usaron (la tuya NO puede repetir sus frases ni su estructura; escribe otra distinta basada en este clip):
{chr(10).join("- " + str(x)[:120].replace(chr(10), " ") for x in list(descs)[-12:]) or "(ninguna)"}
{aprendizaje.guia()}
{("OJO, el título anterior salió flojo: " + feedback + " Escribí uno claramente mejor.") if feedback else ""}
Reglas: {("idioma: " + idioma + ".") if idioma else "mismo idioma del contenido."} Título atractivo de máximo 90 caracteres basado en lo que PASA en este clip, sin mentiras ni promesas falsas, sin inventar datos; descripción de 2 a 3 frases y 3 a 5 hashtags al final.
Responde SOLO este JSON: {{"titulo": "...", "descripcion": "..."}}''', modo)
    try:
        t, desc = str(data["titulo"]).strip(), str(data["descripcion"]).strip()
        if not t or not desc: return None
        return {"titulo": t[:95], "descripcion": desc[:1500], "prov": NOMBRE[p]}
    except Exception: return None

def eventos(modo, titulo, frases, kind, L, permitidos):
    """La IA decide CUANDO poner zooms y efectos: lista de {t, dur, fx} sobre el tramo (tiempos relativos al clip)."""
    txt = "\n".join(f"[{a:.1f}s] {t}" for a, b, t in frases)[:6000]
    cat = ", ".join(k for k in permitidos if k in efectos.EFECTOS)
    data, p = pedir(f'''Eres editor de video de {"Shorts" if kind == "short" else "YouTube"}. El clip dura {L:.0f} s y se titula "{titulo}".
Transcripción con tiempos (segundos desde el inicio del clip):
{txt or "(sin voz: reparte los efectos parejo)"}
Decide en qué momentos exactos poner zoom/efectos para dar ritmo: zoom de acercamiento en las frases clave o remates, destello o glitch en los cambios de idea, pulso o temblor en los momentos intensos. Entre 4 y {max(4, min(14, int(L // 4)))} eventos, separados al menos 2 s, el primero antes de los 2 s (gancho).
Solo puedes usar estos ids de efecto: {cat}.
Responde SOLO este JSON: {{"eventos": [{{"t": <segundo>, "dur": <1 a 3>, "fx": "<id>"}}, ...], "motivo": "<una frase>"}}''', modo)
    try:
        out = []
        for e in data["eventos"]:
            t, d, fx = float(e["t"]), min(3.0, max(0.8, float(e.get("dur", 1.5)))), str(e["fx"])
            if fx in permitidos and fx in efectos.EFECTOS and 0 <= t < L - 0.5 and all(abs(t - o["t"]) >= 1.5 for o in out):
                out.append({"t": round(t, 2), "dur": round(min(d, L - t), 2), "fx": fx})
        out.sort(key=lambda x: x["t"])
        return {"eventos": out[:16], "prov": NOMBRE[p], "motivo": str(data.get("motivo", ""))[:120]} if len(out) >= 2 else None
    except Exception: return None

def corregir_subs(modo, titulo, lineas):
    """Corrige ortografia y palabras mal transcritas SIN cambiar cuantas lineas hay ni su significado."""
    data, p = pedir(f'''Eres corrector de subtítulos de video titulado "{titulo}". Corrige ortografía, tildes, puntuación y palabras mal transcritas (si está en español, respeta el español latinoamericano y su jerga, sin españolizar ni "corregir" voseo, lunfardo ni regionalismos; si hay frases en inglés, déjalas en inglés).
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
