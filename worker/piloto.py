"""Piloto automático: tema central -> busca videos relevantes (sin repetir) -> los pone en la cola -> descarga, edita y sube solo."""
import json, pathlib, subprocess, sys, time, urllib.parse, datetime as dt
import ia, tiktok
ROOT = pathlib.Path(__file__).parent
def _imp():
    try: import curl_cffi; return ["--impersonate", "chrome"]
    except Exception: return []
PF = ROOT / "piloto.json"
VARIANTES = ["{t}", "{t} mejores momentos", "{t} compilación", "{t} gracioso", "{t} épico", "{t} viral", "{t} 2026", "{t} funny moments", "{t} best plays", "{t} clips"]

def leer():
    try: return json.loads(PF.read_text("utf-8"))
    except Exception: return {}

def guardar(p):
    tmp = PF.with_suffix(".tmp"); tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False), "utf-8"); tmp.replace(PF)

def configurar(d):
    p = leer(); hoy = dt.date.today().isoformat()
    p.update(activo=bool(d.get("activo")), tema=str(d.get("tema", p.get("tema", ""))).strip()[:120],
             shorts=max(0, min(int(d.get("shorts", 10)), 60)), videos=max(0, min(int(d.get("videos", 3)), 30)),
             dias=max(1, min(int(d.get("dias", 30)), 365)), por_video=1, cada=max(0, min(int(d.get("cada", 0) or 0), 1440)), **_rango(d))
    if d.get("activo") and not p.get("inicio"): p.update(inicio=hoy, usados=p.get("usados", []), hist=p.get("hist", []))
    if not d.get("activo") and d.get("reiniciar"): p.update(inicio=None, hoy={})
    p.setdefault("usados", []); p.setdefault("hist", []); guardar(p); return p

def _rango(d):
    """Límites de duración (segundos) elegidos en la web. 0 = sin límite."""
    f = lambda k: max(0, min(int(d.get(k, 0) or 0), 86400))
    return {"dmin": f("dmin"), "dmax": f("dmax")}

def _duracion(url):
    """Duración en segundos sin gastar de más (yt-dlp rápido y, si no, la página en el Chrome oculto). 0 = no se pudo saber."""
    return tiktok.duracion(url)

def limpiar_memoria():
    """Borra lo ya usado/rechazado, el historial y las fuentes de TODOS los pilotos. Conserva su configuración y el cupo de hoy."""
    n = 0
    for f, claves in ((PF, ("usados", "hist")), (TF, ("usados", "rechazados", "hist", "lista")), (PTF, ("usados", "rechazados", "hist", "fuentes", "muertas", "cache")),
                      (YF, ("usados", "hist")), (ROOT / "piloto-ia.json", ("ideas", "hist"))):
        try: d = json.loads(f.read_text("utf-8"))
        except Exception: continue
        for k in claves:
            if k in d: d[k] = {} if k == "cache" else []
        d["lista_t"] = 0; d["estado"] = "Memoria borrada: vuelvo a buscar desde cero."
        try: f.write_text(json.dumps(d, indent=2, ensure_ascii=False), "utf-8"); n += 1
        except Exception: pass
    return n

def en_rango(p, v):
    """¿La duración del video está entre el mínimo y el máximo del piloto? (si no se conoce, se consulta; si no se puede, pasa)"""
    lo, hi = int(p.get("dmin") or 0), int(p.get("dmax") or 0)
    if not lo and not hi: return True
    d = v.get("dur") or v.get("d") or 0
    if not d and v.get("url"): d = _duracion(v["url"]); v["dur"] = d
    if not d: return True
    return (not lo or d >= lo) and (not hi or d <= hi)

def _buscar(query, n=25):
    r = subprocess.run([sys.executable, "-m", "yt_dlp", f"ytsearch{n}:{query}", "--flat-playlist", "--dump-json", "--no-warnings"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    out = []
    for l in r.stdout.splitlines():
        try: j = json.loads(l)
        except Exception: continue
        if j.get("id"): out.append({"id": j["id"], "title": j.get("title") or "", "dur": j.get("duration") or 0, "views": j.get("view_count") or 0})
    return out

def elegir(p, kind, ya, modo="alternar"):
    """Devuelve el video más relevante que nunca se usó. Va rotando las búsquedas para no repetir."""
    tema = p["tema"]; v0 = p.get("variante", 0)
    for k in range(len(VARIANTES)):
        q = VARIANTES[(v0 + k) % len(VARIANTES)].format(t=tema)
        try: res = _buscar(q)
        except Exception: continue
        lo0, hi0 = (150, 1500) if kind == "video" else (90, 1800)
        lo, hi = (p.get("dmin") or lo0), (p.get("dmax") or hi0)                 # tu límite manda sobre el predeterminado
        ok = [r for r in res if r["id"] not in ya and r["id"] not in p["usados"] and lo <= r["dur"] <= hi]
        if not ok: continue
        top = ok[:6]; pick = top[0]
        try:                                     # la IA elige el más relevante de los primeros (si falla, queda el primero de la búsqueda)
            lista = "\n".join(f"{i}. {r['title']} ({r['dur']}s, {r['views']} vistas)" for i, r in enumerate(top))
            txt = ia.texto(f"Tema central: «{tema}». Elegí el video más relevante y atractivo para el tema. Respondé SOLO el número.\n{lista}", modo)
            import re; m = re.search(r"\d+", txt or "")
            if m and int(m.group(0)) < len(top): pick = top[int(m.group(0))]
        except Exception: pass
        p["variante"] = (v0 + k + 1) % len(VARIANTES)
        return pick
    return None

def contar_hoy(p):
    hoy = dt.date.today().isoformat(); h = p.get("hoy") or {}
    if h.get("fecha") != hoy: h = {"fecha": hoy, "short": 0, "video": 0, "ultimo": 0}
    p["hoy"] = h; return h

def tick(items_existentes, log=print):
    """Llamado por el vigilante. Devuelve una lista (0 o 1) de items nuevos para la cola, o [] si no toca."""
    p = leer()
    if not p.get("activo") or not p.get("tema"): return []
    hoy = dt.date.today(); ini = dt.date.fromisoformat(p.get("inicio") or hoy.isoformat())
    dia = (hoy - ini).days + 1
    if dia > p["dias"]:
        p["activo"] = False; p["estado"] = f"Terminado: se completaron los {p['dias']} días."; guardar(p); log(p["estado"]); return []
    h = contar_hoy(p); falta_s = p["shorts"] - h["short"]; falta_v = p["videos"] - h["video"]
    if falta_s <= 0 and falta_v <= 0: p["estado"] = f"Día {dia}/{p['dias']}: cupo de hoy completo."; guardar(p); return []
    total = p["shorts"] + p["videos"] or 1
    gap = p["cada"] * 60 if p.get("cada") else max(8 * 60, (15 * 3600) // total)      # tu intervalo, o reparte el cupo en ~15 horas
    if time.time() - h.get("ultimo", 0) < gap: p["estado"] = f"Día {dia}/{p['dias']}: Shorts {h['short']}/{p['shorts']} · Videos {h['video']}/{p['videos']}"; guardar(p); return []
    kind = "video" if (falta_v > 0 and (falta_s <= 0 or falta_v / max(p["videos"], 1) >= falta_s / max(p["shorts"], 1))) else "short"
    ya = {i.get("id") for i in items_existentes}
    r = elegir(p, kind, ya)
    if not r: p["estado"] = "No encontré videos nuevos para ese tema; pruebo otra búsqueda en el próximo ciclo."; guardar(p); log(p["estado"]); return []
    n = 1                                            # cada Short sale de un video DISTINTO
    p["usados"].append(r["id"]); p["usados"] = p["usados"][-3000:]
    h["ultimo"] = time.time(); h[kind] += 1
    p["hist"] = (p.get("hist", []) + [{"id": r["id"], "t": r["title"], "k": kind, "d": hoy.isoformat()}])[-200:]
    p["estado"] = f"Día {dia}/{p['dias']}: agregué «{r['title'][:50]}» ({kind}). Shorts {h['short']}/{p['shorts']} · Videos {h['video']}/{p['videos']}"
    guardar(p); log(p["estado"])
    return [{"type": "video", "id": r["id"], "key": "video:" + r["id"], "kind": kind, "url": "https://www.youtube.com/watch?v=" + r["id"],
             "status": "pending", "n": n, "auto": True, "dmin": p.get("dmin", 0), "dmax": p.get("dmax", 0)}]


# ======================= Piloto TikTok =======================
import random, re
TF = ROOT / "piloto-tiktok.json"
CLAVES_ML = re.compile(r"mobile\s*legends|\bmlbb\b|\bmlbb\w*|\bm[l1]\b|\bm[0-9]\s*world|\bmpl\b|savage|maniac|lord\b|turtle|tortuga|\bmythic|\bmitico|\bgloria\b|\bepic\b.*\b(ml|moonton)|moonton|alucard|layla|fanny|gusion|ling\b|hayabusa|kagura|lancelot|chou\b|miya|nana\b|tigreal|franco|eudora|saber\b|zilong|balmond|bruno|clint|granger|beatrix|brody|wanwan", re.I)

def leer_tt():
    try: return json.loads(TF.read_text("utf-8"))
    except Exception: return {}

def guardar_tt(p):
    tmp = TF.with_suffix(".tmp"); tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False), "utf-8"); tmp.replace(TF)

def configurar_tt(d):
    p = leer_tt(); cuenta = str(d.get("cuenta", p.get("cuenta", ""))).strip()
    m = re.search(r"tiktok\.com/(@[\w.\-]+)", cuenta); cuenta = m.group(1) if m else ("@" + cuenta.lstrip("@") if cuenta else "")
    if cuenta != p.get("cuenta"): p.update(cuenta=cuenta, lista=[], lista_t=0, rechazados=[], inicio=None, hoy={})
    if d.get("activo") and not p.get("lista"): p["lista_t"] = 0          # al activar, reintenta la lectura enseguida
    p.update(activo=bool(d.get("activo")), cuenta=cuenta, orden=d.get("orden") if d.get("orden") in ("seguidilla", "aleatorio", "relevantes") else "seguidilla",
             por_dia=max(1, min(int(d.get("por_dia", 5)), 60)), dias=max(1, min(int(d.get("dias", 30)), 365)), verificar=bool(d.get("verificar", True)), cada=max(0, min(int(d.get("cada", 0) or 0), 1440)), **_rango(d))
    if p["activo"] and not p.get("inicio"): p["inicio"] = dt.date.today().isoformat()
    for k in ("usados", "rechazados", "hist", "lista"): p.setdefault(k, [])
    guardar_tt(p); return p

def _flat(url, fin, log=print):
    """Lista de videos con yt-dlp (plan B: a TikTok le suele fallar la lectura de cuentas y etiquetas)."""
    try: txt = tiktok.ytdlp_texto(["--flat-playlist", "--dump-json", "--no-warnings", "--playlist-end", str(fin)], url, timeout=150)
    except Exception as e: log("TikTok: yt-dlp no pudo leer la lista (" + str(e)[:110] + ")"); return []
    out = []
    for l in txt.splitlines():
        try: j = json.loads(l)
        except Exception: continue
        vid = str(j.get("id") or "")
        if vid and vid.isdigit(): out.append({"id": vid, "t": (j.get("title") or j.get("description") or "")[:300], "v": j.get("view_count") or 0, "dur": j.get("duration") or 0,
                                              "url": j.get("webpage_url") or j.get("url") or ""})
    return out

def _listar_cuenta(cuenta, log=print):
    url = f"https://www.tiktok.com/{cuenta}"
    out = tiktok.listar(url, log, scrolls=10)                # primero el Chrome del worker (navegador real, con tu sesión)
    if not out and tiktok.MOTIVO.get("m") in ("", "vacio", "sin_chrome"): out = _flat(url, 80, log)
    for v in out:
        if not v.get("url"): v["url"] = f"https://www.tiktok.com/{cuenta}/video/{v['id']}"
    return out

MSG_TT = {"login": "TikTok pide iniciar sesión: tocá «Iniciar sesión en TikTok», entrá a tu cuenta en la ventana de Chrome y reintento solo.",
          "captcha": "TikTok pidió verificación humana: resolvela en la ventana de Chrome del worker y reintento solo.",
          "privada": "La cuenta es privada: no se pueden leer sus videos.",
          "noexiste": "TikTok no encuentra esa cuenta: revisá cómo está escrita.",
          "sin_chrome": "No pude abrir el Chrome del worker. Tocá «Conectar con mi canal» en el paso 1 y reintento solo."}

def es_mobile_legends(texto, cuenta, modo="alternar"):
    """Verifica con la IA que el video es de Mobile Legends (si la IA no responde, usa palabras clave)."""
    try:
        txt = ia.texto(f"Cuenta de TikTok: {cuenta}\nTexto/hashtags del video: «{texto or '(sin texto)'}»\n¿Este video es de Mobile Legends: Bang Bang (el juego)? "
                       "Si el texto está vacío, decidí por el nombre de la cuenta. Respondé SOLO SI o NO.", modo)
        if txt:
            t = txt.strip().upper()
            if t.startswith("SI") or t.startswith("SÍ") or t.startswith("YES"): return True
            if t.startswith("NO"): return False
    except Exception: pass
    return bool(CLAVES_ML.search(texto or "") or CLAVES_ML.search(cuenta or ""))

def tick_tt(items_existentes, log=print):
    p = leer_tt()
    if not p.get("activo") or not p.get("cuenta"): return []
    hoy = dt.date.today(); ini = dt.date.fromisoformat(p.get("inicio") or hoy.isoformat()); dia = (hoy - ini).days + 1
    if dia > p["dias"]:
        p["activo"] = False; p["estado"] = f"Terminado: se completaron los {p['dias']} días."; guardar_tt(p); log("TikTok: " + p["estado"]); return []
    h = p.get("hoy") or {}
    if h.get("fecha") != hoy.isoformat(): h = {"fecha": hoy.isoformat(), "n": 0, "ultimo": 0}
    p["hoy"] = h
    if h["n"] >= p["por_dia"]: p["estado"] = f"Día {dia}/{p['dias']}: cupo de hoy completo ({h['n']}/{p['por_dia']})."; guardar_tt(p); return []
    if time.time() - h["ultimo"] < (p["cada"] * 60 if p.get("cada") else max(8 * 60, (15 * 3600) // p["por_dia"])):
        p["estado"] = f"Día {dia}/{p['dias']}: {h['n']}/{p['por_dia']} publicados hoy."; guardar_tt(p); return []
    ya = {i.get("id") for i in items_existentes} | set(p["usados"]) | set(p["rechazados"])
    if not p.get("lista") and time.time() - p.get("lista_t", 0) < 600: return []      # no insistir cada minuto si TikTok no respondió
    if not p.get("lista") or time.time() - p.get("lista_t", 0) > 6 * 3600:
        try: p["lista"] = _listar_cuenta(p["cuenta"], log); p["lista_t"] = time.time()
        except Exception as e: p["estado"] = "No pude leer la cuenta de TikTok: " + str(e)[:80]; guardar_tt(p); log("TikTok: " + p["estado"]); return []
        if not p["lista"]:
            p["estado"] = MSG_TT.get(tiktok.MOTIVO.get("m"), "La cuenta no devolvió videos (¿mal escrita o TikTok la bloqueó?). Probá «Iniciar sesión en TikTok» y reintento en 10 min.")
            guardar_tt(p); log("TikTok: " + p["estado"]); return []
    libres = [v for v in p["lista"] if v["id"] not in ya]
    if not libres: p["estado"] = "Ya se usaron todos los videos válidos de la cuenta."; guardar_tt(p); log("TikTok: " + p["estado"]); return []
    if p["orden"] == "aleatorio": random.shuffle(libres)
    elif p["orden"] == "relevantes": libres.sort(key=lambda v: -(v.get("v") or 0))
    elegido = None
    for v in libres[:15]:
        if not en_rango(p, v): p["rechazados"].append(v["id"]); log(f"TikTok: descartado por duración ({v.get('dur')} s): {v['t'][:40]}"); continue
        if p.get("verificar", True) and not es_mobile_legends(v["t"], p["cuenta"]):
            p["rechazados"].append(v["id"]); log(f"TikTok: descartado (no es de Mobile Legends): {v['t'][:50]}"); continue
        elegido = v; break
    if not elegido: p["estado"] = "Los videos revisados no eran de Mobile Legends; sigo con otros en el próximo ciclo."; guardar_tt(p); return []
    p["usados"].append(elegido["id"]); h["n"] += 1; h["ultimo"] = time.time()
    p["hist"] = (p.get("hist", []) + [{"id": elegido["id"], "t": elegido["t"][:80], "d": hoy.isoformat()}])[-200:]
    p["estado"] = f"Día {dia}/{p['dias']}: tomé «{elegido['t'][:50]}». {h['n']}/{p['por_dia']} hoy."; guardar_tt(p); log("TikTok: " + p["estado"])
    return [{"type": "video", "id": elegido["id"], "key": "video:" + elegido["id"], "kind": "short", "url": elegido["url"], "status": "pending", "n": 1, "auto": True, "origen": "tiktok", "dmin": p.get("dmin", 0), "dmax": p.get("dmax", 0)}]


# ======================= Piloto TikTok por tema (fuentes que busca la IA) =======================
PTF = ROOT / "piloto-tema-tiktok.json"

def leer_tm():
    try: return json.loads(PTF.read_text("utf-8"))
    except Exception: return {}

def guardar_tm(p):
    tmp = PTF.with_suffix(".tmp"); tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False), "utf-8"); tmp.replace(PTF)

def configurar_tm(d):
    p = leer_tm(); tema = str(d.get("tema", p.get("tema", ""))).strip()[:120]
    if tema != p.get("tema"): p.update(tema=tema, fuentes=[], muertas=[], cache={}, rechazados=[], inicio=None, hoy={})
    p.update(activo=bool(d.get("activo")), tema=tema, shorts=max(0, min(int(d.get("shorts", 10)), 60)),
             videos=max(0, min(int(d.get("videos", 3)), 30)), dias=max(1, min(int(d.get("dias", 30)), 365)), cada=max(0, min(int(d.get("cada", 0) or 0), 1440)), **_rango(d))
    if p["activo"] and not p.get("inicio"): p["inicio"] = dt.date.today().isoformat()
    for k in ("usados", "rechazados", "hist", "fuentes", "muertas"): p.setdefault(k, [])
    p.setdefault("cache", {}); guardar_tm(p); return p

def _fuentes_ia(p, modo="alternar"):
    """Búsquedas del tema + hashtags y cuentas que propone la IA (las que no existan se descartan solas)."""
    sem = _semillas(p)
    usadas = ", ".join(p["fuentes"][-40:]) or "ninguna"
    txt = ia.texto(f"Tema central: «{p['tema']}». Proponé 12 FUENTES NUEVAS de TikTok para encontrar videos de ese tema: hashtags (con #) y cuentas conocidas (con @). "
                   f"Variá idioma (español e inglés) y subtemas. No repitas estas: {usadas}. Respondé en r una lista separada por comas.", modo) or ""
    nuevas = []
    for x in re.findall(r"[#@][\w.\-]{2,40}", txt):
        x = x.lower()
        if x not in p["fuentes"] and x not in p["muertas"] and x not in nuevas: nuevas.append(x)
    if not nuevas:                                         # sin IA: hashtags derivados del tema
        base = re.sub(r"[^\w]+", "", p["tema"].lower())
        nuevas = [h for h in ("#" + base, "#" + base + "es", "#" + base + "funny", "#" + base + "moments", "#" + base + "viral", "#" + base + "clips") if h not in p["fuentes"] and h not in p["muertas"]]
    p["fuentes"] += nuevas; return sem + nuevas

def _semillas(p):
    """Búsquedas directas del tema en TikTok (lo más fiable: no dependen de que la IA adivine hashtags o cuentas que existan)."""
    t = p["tema"].strip()
    nuevas = [s for s in ("?" + t, "?" + t + " viral", "?" + t + " momentos") if s not in p["fuentes"] and s not in p["muertas"]]
    p["fuentes"] += nuevas; return nuevas

def _listar_fuente(f, log=print):
    """Búsqueda (?tema), hashtag (#x) o cuenta (@x): primero con el Chrome del worker, después con yt-dlp."""
    if f.startswith("?"): url = "https://www.tiktok.com/search/video?q=" + urllib.parse.quote(f[1:])
    elif f.startswith("#"): url = f"https://www.tiktok.com/tag/{urllib.parse.quote(f[1:])}"
    else: url = f"https://www.tiktok.com/{f}"
    out = tiktok.listar(url, log, scrolls=6)
    if not out and not f.startswith("?") and tiktok.MOTIVO.get("m") in ("", "vacio", "sin_chrome"): out = _flat(url, 40, log)
    for v in out:
        if not v.get("url"): v["url"] = f"https://www.tiktok.com/video/{v['id']}"
    return out

def _respaldo_youtube(tema, n=30):
    """TikTok bloquea la lectura a veces: se buscan Shorts del tema en YouTube para no quedarse parado."""
    out = []
    for q in (f"{tema} shorts", f"{tema} tiktok compilation", f"{tema} funny moments"):
        try: res = _buscar(q, n)
        except Exception: continue
        out += [{"id": r["id"], "t": r["title"], "dur": r["dur"], "url": "https://www.youtube.com/watch?v=" + r["id"]} for r in res if 5 < (r["dur"] or 0) <= 1500]
    return out

def es_del_tema(texto, tema, modo="alternar"):
    try:
        txt = ia.texto(f"Tema central: «{tema}»\nTexto/hashtags del video de TikTok: «{texto or '(sin texto)'}»\n¿El video trata de ese tema? Respondé SOLO SI o NO.", modo)
        if txt:
            t = txt.strip().upper()
            if t[:2] in ("SI", "SÍ") or t.startswith("YES"): return True
            if t.startswith("NO"): return False
    except Exception: pass
    pal = [w for w in re.findall(r"\w{4,}", tema.lower())]
    return any(w in (texto or "").lower() for w in pal)

def tick_tm(items_existentes, log=print):
    p = leer_tm()
    if not p.get("activo") or not p.get("tema"): return []
    hoy = dt.date.today(); ini = dt.date.fromisoformat(p.get("inicio") or hoy.isoformat()); dia = (hoy - ini).days + 1
    if dia > p["dias"]:
        p["activo"] = False; p["estado"] = f"Terminado: se completaron los {p['dias']} días."; guardar_tm(p); log("TikTok tema: " + p["estado"]); return []
    h = p.get("hoy") or {}
    if h.get("fecha") != hoy.isoformat(): h = {"fecha": hoy.isoformat(), "short": 0, "video": 0, "ultimo": 0}
    p["hoy"] = h; fs, fv = p["shorts"] - h["short"], p["videos"] - h["video"]
    if fs <= 0 and fv <= 0: p["estado"] = f"Día {dia}/{p['dias']}: cupo de hoy completo."; guardar_tm(p); return []
    gap = p["cada"] * 60 if p.get("cada") else max(8 * 60, (15 * 3600) // max(p["shorts"] + p["videos"], 1))
    if time.time() - h["ultimo"] < gap: p["estado"] = f"Día {dia}/{p['dias']}: Shorts {h['short']}/{p['shorts']} · Videos {h['video']}/{p['videos']}"; guardar_tm(p); return []
    kind = "video" if (fv > 0 and (fs <= 0 or fv / max(p["videos"], 1) >= fs / max(p["shorts"], 1))) else "short"
    ya = {i.get("id") for i in items_existentes} | set(p["usados"]) | set(p["rechazados"])
    def vivas():
        return [f for f in p["fuentes"] if f not in p["muertas"] and (f not in p["cache"] or any(v["id"] not in ya for v in p["cache"][f]))]
    abiertas, cont = 0, {"dur": 0, "tema": 0}                # abiertas: páginas leídas en esta pasada (tope 3: cuida la PC)
    for _ in range(8):                                      # prueba hasta 8 fuentes distintas, al azar
        vs = vivas()
        if not vs:
            try: nuevas = _fuentes_ia(p)
            except Exception as e: nuevas = []; log("TikTok tema: error pidiendo fuentes: " + str(e)[:80])
            if not nuevas:
                if "youtube-respaldo" not in p["cache"]:
                    p["cache"]["youtube-respaldo"] = _respaldo_youtube(p["tema"]); p["fuentes"].append("youtube-respaldo")
                    log("TikTok tema: sin fuentes nuevas; uso Shorts de YouTube como respaldo.")
                    continue
                p["estado"] = "No encuentro fuentes nuevas para ese tema."; guardar_tm(p); log("TikTok tema: " + p["estado"]); return []
            log("TikTok tema: fuentes nuevas: " + ", ".join(nuevas[:8])); continue
        f = next((x for x in vs if x.startswith("?")), None) or random.choice(vs)       # primero las búsquedas del tema
        if f not in p["cache"]:
            if abiertas >= 3: p["estado"] = "Busqué en 3 fuentes sin encontrar un video válido; sigo en el próximo ciclo."; guardar_tm(p); return []
            abiertas += 1; p["estado"] = f"Buscando en TikTok (segundo plano): {f}"; guardar_tm(p)
            try: lst = _listar_fuente(f, log)
            except Exception as e: lst = []; log(f"TikTok tema: error leyendo {f}: {str(e)[:80]}")
            if not lst:
                mot = tiktok.MOTIVO.get("m")
                if mot in ("login", "captcha", "sin_chrome"):          # no es culpa de la fuente: no se descarta
                    p["estado"] = MSG_TT[mot]; guardar_tm(p); log("TikTok tema: " + p["estado"]); return []
                p["muertas"].append(f); log(f"TikTok tema: {f} no devolvió videos, la descarto"); continue
            p["cache"][f] = lst
        cand = [v for v in p["cache"][f] if v["id"] not in ya]
        if kind == "video": cand = [v for v in cand if not v["dur"] or v["dur"] >= 60] or cand
        random.shuffle(cand)
        for v in cand[:8]:
            if not en_rango(p, v): p["rechazados"].append(v["id"]); ya.add(v["id"]); cont["dur"] += 1; continue
            if v["t"] and not es_del_tema(v["t"], p["tema"]): p["rechazados"].append(v["id"]); ya.add(v["id"]); cont["tema"] += 1; continue      # sin texto: se acepta (la fuente ya es del tema)
            p["usados"].append(v["id"]); h[kind] += 1; h["ultimo"] = time.time()
            p["hist"] = (p.get("hist", []) + [{"id": v["id"], "t": v["t"][:80], "f": f, "k": kind, "d": hoy.isoformat()}])[-200:]
            p["estado"] = f"Día {dia}/{p['dias']}: {kind} de {f}. Shorts {h['short']}/{p['shorts']} · Videos {h['video']}/{p['videos']}"
            guardar_tm(p); log("TikTok tema: " + p["estado"])
            return [{"type": "video", "id": v["id"], "key": "video:" + v["id"], "kind": kind, "url": v["url"], "status": "pending", "n": 1, "auto": True, "origen": "tiktok", "dmin": p.get("dmin", 0), "dmax": p.get("dmax", 0)}]
        if not [v for v in p["cache"][f] if v["id"] not in ya] and f not in p["muertas"]: p["muertas"].append(f)
    p["estado"] = f"Revisé videos y ninguno sirvió (fuera de duración: {cont['dur']} · no eran del tema: {cont['tema']}); pruebo otras fuentes en el próximo ciclo."; guardar_tm(p); return []


# ======================= Piloto YouTube Shorts =======================
YF = ROOT / "piloto-yts.json"
VAR_YS = ["{t} #shorts", "{t} shorts", "{t} shorts viral", "{t} shorts épico", "{t} shorts gracioso", "{t} shorts mejores momentos", "{t} shorts 2026", "{t} short funny", "{t} shorts compilación"]

def leer_ys():
    try: return json.loads(YF.read_text("utf-8"))
    except Exception: return {}

def guardar_ys(p):
    tmp = YF.with_suffix(".tmp"); tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False), "utf-8"); tmp.replace(YF)

def configurar_ys(d):
    p = leer_ys(); hoy = dt.date.today().isoformat(); tema = str(d.get("tema", p.get("tema", ""))).strip()[:120]
    if tema != p.get("tema"): p.update(inicio=None, hoy={}, variante=0)
    p.update(activo=bool(d.get("activo")), tema=tema, por_dia=max(1, min(int(d.get("por_dia", 5)), 60)), dias=max(1, min(int(d.get("dias", 30)), 365)),
             cada=max(0, min(int(d.get("cada", 0) or 0), 1440)), **_rango(d))
    if p["activo"] and not p.get("inicio"): p["inicio"] = hoy
    for k in ("usados", "hist"): p.setdefault(k, [])
    guardar_ys(p); return p

def tick_ys(items_existentes, log=print):
    """Cada X minutos/horas: busca UN Short nuevo del tema en YouTube (nunca uno ya usado) y lo manda a descargar, editar y publicar."""
    p = leer_ys()
    if not p.get("activo") or not p.get("tema"): return []
    hoy = dt.date.today(); ini = dt.date.fromisoformat(p.get("inicio") or hoy.isoformat()); dia = (hoy - ini).days + 1
    if dia > p["dias"]: p["activo"] = False; p["estado"] = f"Terminado: se completaron los {p['dias']} días."; guardar_ys(p); log("Piloto YouTube Shorts: " + p["estado"]); return []
    h = p.get("hoy") or {}
    if h.get("fecha") != hoy.isoformat(): h = {"fecha": hoy.isoformat(), "n": 0, "ultimo": 0}
    p["hoy"] = h
    if h["n"] >= p["por_dia"]: p["estado"] = f"Día {dia}/{p['dias']}: cupo de hoy completo ({h['n']}/{p['por_dia']})."; guardar_ys(p); return []
    gap = p["cada"] * 60 if p.get("cada") else max(8 * 60, (15 * 3600) // p["por_dia"])
    falta = gap - (time.time() - h["ultimo"])
    if falta > 0: p["estado"] = f"Día {dia}/{p['dias']}: {h['n']}/{p['por_dia']} hoy · próximo en {int(falta // 60) + 1} min."; guardar_ys(p); return []
    ya = {i.get("id") for i in items_existentes}; tema = p["tema"]; v0 = p.get("variante", 0); pick = None
    for k in range(len(VAR_YS)):
        try: res = _buscar(VAR_YS[(v0 + k) % len(VAR_YS)].format(t=tema), 40)
        except Exception: continue
        ok = [r for r in res if r["id"] not in ya and r["id"] not in p["usados"] and (p.get("dmin") or 8) <= (r["dur"] or 0) <= (p.get("dmax") or 180)]
        if ok: pick = ok[0]; p["variante"] = (v0 + k + 1) % len(VAR_YS); break
    if not pick: p["estado"] = "No encontré Shorts nuevos de ese tema; pruebo otra búsqueda en el próximo ciclo."; guardar_ys(p); log("Piloto YouTube Shorts: " + p["estado"]); return []
    p["usados"] = (p["usados"] + [pick["id"]])[-3000:]; h["n"] += 1; h["ultimo"] = time.time()
    p["hist"] = (p.get("hist", []) + [{"id": pick["id"], "t": pick["title"][:80], "d": hoy.isoformat()}])[-200:]
    p["estado"] = f"Día {dia}/{p['dias']}: agregué «{pick['title'][:50]}» ({h['n']}/{p['por_dia']} hoy)."
    guardar_ys(p); log("Piloto YouTube Shorts: " + p["estado"])
    return [{"type": "video", "id": pick["id"], "key": "video:" + pick["id"], "kind": "short", "url": "https://www.youtube.com/watch?v=" + pick["id"],
             "status": "pending", "n": 1, "auto": True, "origen": "yt-shorts", "dmin": p.get("dmin", 0), "dmax": p.get("dmax", 0)}]
