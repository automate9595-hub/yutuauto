"""TikTok a prueba de bloqueos y en SEGUNDO PLANO.
- yt-dlp con varias variantes (Chrome simulado + cookies, solo cookies, sin nada) y el error REAL a la vista.
- Si yt-dlp no puede, se lee y se descarga con un Chrome OCULTO (headless, puerto 9333, perfil propio "chrome-bg"): no abre ventanas,
  no roba el foco, no carga imágenes ni video y se cierra solo cuando deja de usarse.
- La sesión de TikTok se inicia UNA vez en el Chrome visible del worker; sus cookies se copian solas al Chrome oculto.
"""
import json, os, pathlib, re, subprocess, sys, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
COOK = ROOT / "tiktok-cookies.txt"
BG_PORT = 9333
BG_DIR = ROOT / "chrome-bg"
BG_USO = ROOT / "bg-uso.txt"
DIAG_TXT, DIAG_PNG = ROOT / "diagnostico-tiktok.txt", ROOT / "diagnostico-tiktok.png"
MOTIVO = {"m": ""}          # por qué la última lectura no devolvió videos: login | captcha | privada | noexiste | vacio | sin_chrome
SESION = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")
_MEJOR = {}                 # variante de yt-dlp que funcionó la última vez
_FALLO = {"t": 0}           # cuándo fallaron todas las variantes (para no insistir)
_SYNC = {"t": 0}


class ErrorWeb(Exception): pass


# ------------------------------------------------------------------ cookies
def guardar_cookies(cookies):
    """Cookies de TikTok -> archivo Netscape (solo líneas válidas) para yt-dlp. No pisa una sesión buena con cookies anónimas."""
    lin = ["# Netscape HTTP Cookie File"]
    for c in cookies or []:
        dom, nom, val = str(c.get("domain", "")), str(c.get("name", "")), str(c.get("value", ""))
        if "tiktok" not in dom or not nom or re.search(r"[\t\r\n]", nom + val): continue
        exp = c.get("expires", -1)
        try: exp = int(exp) if exp and exp > 0 else 0
        except Exception: exp = 0
        lin.append("\t".join([("#HttpOnly_" if c.get("httpOnly") else "") + dom, "TRUE" if dom.startswith(".") else "FALSE", c.get("path") or "/",
                              "TRUE" if c.get("secure") else "FALSE", str(exp), nom, val]))
    if len(lin) < 2: return False
    if not sesion_en(cookies) and sesion_guardada(): return False
    try:
        tmp = COOK.with_suffix(".tmp"); tmp.write_text("\n".join(lin) + "\n", "utf-8"); os.replace(tmp, COOK); return True
    except Exception: return False


def leer_cookies_archivo():
    out = []
    try: txt = COOK.read_text("utf-8", "replace")
    except Exception: return out
    for l in txt.splitlines():
        ho = l.startswith("#HttpOnly_"); l2 = l[10:] if ho else l
        if not l2.strip() or l2.startswith("#"): continue
        f = l2.split("\t")
        if len(f) != 7: continue
        c = {"name": f[5], "value": f[6], "domain": f[0], "path": f[2], "secure": f[3] == "TRUE", "httpOnly": ho}
        if f[4].strip().isdigit() and int(f[4]) > 0: c["expires"] = int(f[4])
        out.append(c)
    return out


def sesion_guardada(): return sesion_en(leer_cookies_archivo())


def cookies_validas():
    """Revisa el archivo de cookies; las líneas rotas se quitan (una sola línea mala hace fallar a yt-dlp entero)."""
    try: txt = COOK.read_text("utf-8", "replace")
    except Exception: return False
    buenas, cambio, n = ["# Netscape HTTP Cookie File"], False, 0
    for l in txt.splitlines():
        if not l.strip() or (l.startswith("#") and not l.startswith("#HttpOnly_")): continue
        f = l.split("\t")
        if len(f) == 7 and f[0].strip() and f[5].strip() and re.fullmatch(r"-?\d+", f[4].strip() or "x"): buenas.append(l); n += 1
        else: cambio = True
    if cambio and n:
        try: COOK.write_text("\n".join(buenas) + "\n", "utf-8")
        except Exception: pass
    return n > 0


def sesion_en(cookies):
    return any("tiktok" in str(c.get("domain", "")) and c.get("name") in SESION and c.get("value") for c in cookies or [])


# ------------------------------------------------------------------ yt-dlp con variantes
def _curl_ok():
    try: import curl_cffi; return True
    except Exception: return False


def variantes(url):
    """Formas de llamar a yt-dlp, de la más completa a la más simple (la que funcionó la última vez va primero)."""
    tt = "tiktok.com" in str(url)
    imp = ["--impersonate", "chrome"] if _curl_ok() else []
    ck = ["--cookies", str(COOK)] if tt and cookies_validas() else []
    out = []
    for a in (imp + ck, imp, ck, []):
        if a not in out: out.append(a)
    m = _MEJOR.get(tt)
    if m in out: out.remove(m); out.insert(0, m)
    return out


def recordar(url, var):
    _MEJOR["tiktok.com" in str(url)] = var; _FALLO["t"] = 0


def limpiar_error(texto):
    """Última línea útil de lo que dijo yt-dlp (ERROR: ...), sin rutas ni ruido."""
    lin = [l.strip() for l in str(texto or "").splitlines() if l.strip()]
    err = [l for l in lin if l.startswith("ERROR")] or lin
    return re.sub(r"\s+", " ", err[-1])[:260] if err else "yt-dlp terminó sin decir por qué"


def ytdlp_texto(args, url, timeout=90, rapido=False):
    """Corre yt-dlp probando cada variante. Devuelve su salida; si todas fallan, el error REAL (no solo 'returned non-zero').
    rapido=True: si hace poco fallaron todas, no insiste (ahorra CPU)."""
    if rapido and time.time() - _FALLO["t"] < 600 and "tiktok.com" in str(url): raise RuntimeError("yt-dlp no puede con TikTok ahora mismo")
    ultimo = ""
    for var in variantes(url):
        try:
            r = subprocess.run([sys.executable, "-m", "yt_dlp", *var, *args, url], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired: ultimo = "yt-dlp tardó demasiado"; continue
        except Exception as e: ultimo = str(e)[:200]; continue
        if r.returncode == 0 and r.stdout.strip(): recordar(url, var); return r.stdout
        ultimo = limpiar_error(r.stderr or r.stdout)
    if "tiktok.com" in str(url): _FALLO["t"] = time.time()
    raise RuntimeError(ultimo or "yt-dlp no devolvió nada")


def info(url, web=True):
    """Datos del video (título, duración...). TikTok: yt-dlp y, si no puede, la propia página abierta en el Chrome oculto."""
    try: return json.loads(ytdlp_texto(["-j", "--no-playlist"], url).strip().splitlines()[-1])
    except Exception as e:
        causa = str(e)
        if "tiktok.com" in str(url) and web:
            try: return info_web(url)
            except Exception as e2: causa += " | navegador: " + str(e2)[:160]
        raise RuntimeError(causa[:380])


def duracion(url):
    """Duración en segundos sin gastar de más: yt-dlp rápido y, si no, la página en el Chrome oculto. 0 = no se pudo saber."""
    try: return int(float(ytdlp_texto(["--no-playlist", "--no-warnings", "--print", "duration"], url, timeout=40, rapido=True).strip().splitlines()[-1]))
    except Exception: pass
    if "tiktok.com" in str(url):
        try: return int(float(info_web(url, espera=15).get("duration") or 0))
        except Exception: return 0
    return 0


# ------------------------------------------------------------------ Chrome oculto (segundo plano)
def chrome_path():
    pf, pf86, la = (os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"))
    for p in (pf + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Google\Chrome\Application\chrome.exe",
              la + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Microsoft\Edge\Application\msedge.exe",
              pf + r"\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(p): return p
    return os.environ.get("YUTU_CHROME")


def _version(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r: return json.loads(r.read())
    except Exception: return None


def bg_asegurar():
    """Levanta el Chrome oculto si no está. Devuelve su /json/version."""
    v = _version(BG_PORT)
    if v: return v
    exe = chrome_path()
    if not exe: raise ErrorWeb("no encontré Chrome ni Edge")
    BG_DIR.mkdir(exist_ok=True)
    fl = sum(getattr(subprocess, n, 0) for n in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"))
    for modo in ("--headless=new", "--headless"):                # Chrome viejo (Windows 7/8.1) solo entiende --headless
        try:
            subprocess.Popen([exe, modo, f"--remote-debugging-port={BG_PORT}", f"--user-data-dir={BG_DIR}", "--no-first-run", "--no-default-browser-check",
                              "--disable-gpu", "--mute-audio", "--disable-extensions", "--disable-background-networking", "--window-size=1280,900",
                              "--blink-settings=imagesEnabled=false", "--autoplay-policy=user-gesture-required", "--no-sandbox" if os.name != "nt" else "--disable-features=Translate", "about:blank"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=fl, start_new_session=(os.name != "nt"))
        except Exception as e: raise ErrorWeb("no pude abrir el Chrome oculto: " + str(e)[:80])
        for _ in range(30):
            v = _version(BG_PORT)
            if v: return v
            time.sleep(0.5)
    raise ErrorWeb("el Chrome oculto no respondió")


def bg_cerrar():
    """Cierra el Chrome oculto (libera RAM y CPU)."""
    v = _version(BG_PORT)
    if not v: return False
    try:
        import cdp
        ws = cdp.WS(v["webSocketDebuggerUrl"]); ws.send(json.dumps({"id": 1, "method": "Browser.close"})); time.sleep(0.5); ws.close(); return True
    except Exception: return False


def bg_reposo(seg=180):
    """Lo llama el vigilante cada minuto: si hace más de `seg` segundos que nadie lo usa, cierra el Chrome oculto."""
    try:
        if _version(BG_PORT) and time.time() - float(BG_USO.read_text() or 0) > seg: return bg_cerrar()
    except Exception:
        try:
            if _version(BG_PORT): return bg_cerrar()
        except Exception: pass
    return False


def _ua(v):
    m = re.search(r"/(\d+[\d.]*)", (v or {}).get("Browser", ""))
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{m.group(1) if m else '131.0.0.0'} Safari/537.36"


BLOQUEAR = ["*.mp4*", "*.m3u8*", "*.mp3*", "*.webm*", "*.woff*", "*.ttf*", "*.png*", "*.jpg*", "*.jpeg*", "*.webp*", "*.gif*", "*.svg*", "*.avif*", "*.ico*",
            "*/video/tos/*", "*mime_type=video*"]


def sincronizar_sesion(forzar=False):
    """Copia la sesión del Chrome visible del worker (si está abierto) al archivo de cookies. Máx. una vez cada 5 minutos."""
    if not forzar and time.time() - _SYNC["t"] < 300 and sesion_guardada(): return
    _SYNC["t"] = time.time()
    cs = _cookies_principal()
    if cs: guardar_cookies(cs)


def _preparar(tab, v):
    """Pestaña oculta: sin imágenes ni video, navegador 'normal' y con la sesión de TikTok."""
    tab.call("Network.enable")
    tab.call("Network.setUserAgentOverride", {"userAgent": _ua(v), "acceptLanguage": "es-ES,es;q=0.9,en;q=0.8", "platform": "Win32"})
    try: tab.call("Network.setBlockedURLs", {"urls": BLOQUEAR})
    except Exception: pass
    try: tab.call("Page.addScriptToEvaluateOnNewDocument", {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})
    except Exception: pass
    try: tab.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
    except Exception: pass
    sincronizar_sesion()
    cs = leer_cookies_archivo()
    if cs:
        try: tab.call("Network.setCookies", {"cookies": cs})
        except Exception: pass


def _tab(url="about:blank"):
    """Pestaña OCULTA para trabajar en segundo plano. Si el Chrome oculto no arranca, usa una pestaña del Chrome del worker sin traerla al frente."""
    import cdp
    try:
        v = bg_asegurar(); BG_USO.write_text(str(time.time()))
        tab = cdp.Tab.abrir("about:blank", port=BG_PORT, traer=False)
        try:
            _preparar(tab, v)
            if url != "about:blank": tab.call("Page.navigate", {"url": url})
            return tab
        except Exception:
            try: tab.cerrar()
            except Exception: pass
            raise
    except Exception as e1:
        try: return cdp.Tab.abrir(url, port=9222, traer=False)
        except Exception as e2:
            MOTIVO["m"] = "sin_chrome"; raise ErrorWeb("no pude abrir un navegador en segundo plano (" + str(e1)[:70] + ")")


def _cookies(tab):
    try: return tab.call("Network.getAllCookies").get("cookies", [])
    except Exception: return []


def _cookies_principal():
    """Cookies del Chrome visible del worker, o None si no está abierto. No abre pestañas ni toma el foco."""
    import cdp
    try:
        pags = [t for t in cdp.Tab.listar(9222) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    except Exception: return None
    if not pags: return None
    tab = None
    try:
        tab = cdp.Tab(pags[0], propia=False, port=9222, traer=False)
        return _cookies(tab)
    except Exception: return None
    finally:
        try: tab and tab.cerrar()
        except Exception: pass


def sesion_iniciada():
    """¿Hay una sesión de TikTok abierta? Mira el Chrome visible del worker y copia sus cookies para el Chrome oculto."""
    cs = _cookies_principal()
    if cs is None: return sesion_guardada()
    if sesion_en(cs): guardar_cookies(cs); return True
    return False


JS_ESTADO = r"""(function(){var t=((document.body&&document.body.innerText)||'').slice(0,1800).toLowerCase();return JSON.stringify({u:location.href,t:t})})()"""
JS_LISTA = r"""(function(){var o=[],seen={};document.querySelectorAll('a[href*="/video/"]').forEach(function(a){
var h=a.href.split('?')[0];if(seen[h])return;seen[h]=1;var t=a.getAttribute('aria-label')||a.title||'';var im=a.querySelector('img');
if(!t&&im)t=im.alt||'';if(!t){var n=a,k=0;while(n&&k<4&&!t){n=n.parentElement;k++;
if(n&&n.querySelectorAll('a[href*="/video/"]').length===1&&n.innerText&&n.innerText.length<400)t=n.innerText}}
o.push({h:h,t:t||''})});return JSON.stringify(o)})()"""
JS_VIDEO = r"""(function(){var ua=navigator.userAgent;try{var s=document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
var j=s?JSON.parse(s.textContent):null;var d=j&&j['__DEFAULT_SCOPE__']&&j['__DEFAULT_SCOPE__']['webapp.video-detail'];
var it=d&&d.itemInfo&&d.itemInfo.itemStruct;if(it){var v=it.video||{};var u=[];
if(v.playAddr)u.push(v.playAddr);if(v.downloadAddr)u.push(v.downloadAddr);
(v.bitrateInfo||[]).forEach(function(b){((b.PlayAddr&&b.PlayAddr.UrlList)||[]).forEach(function(x){u.push(x)})});
return JSON.stringify({ok:1,id:it.id||'',desc:it.desc||'',dur:v.duration||0,urls:u,ua:ua,st:d.statusCode||0,thumb:v.cover||''})}
if(d&&d.statusCode)return JSON.stringify({ok:0,st:d.statusCode,ua:ua,urls:[]})}catch(e){}
var vv=document.querySelector('video');var src=vv?(vv.currentSrc||vv.src||''):'';
return JSON.stringify({ok:src&&src.indexOf('blob:')!==0?1:0,id:'',desc:document.title||'',dur:vv&&vv.duration||0,urls:src&&src.indexOf('blob:')!==0?[src]:[],ua:ua,st:0})})()"""


def _motivo_de(tx):
    if re.search(r"captcha|verifica|arrastra|drag the|puzzle|slide to|verify to continue", tx): return "captcha"
    if re.search(r"esta cuenta es privada|this account is private", tx): return "privada"
    if re.search(r"no se pudo encontrar|couldn.t find this account|no encontramos|page not available|p[aá]gina no disponible", tx): return "noexiste"
    if re.search(r"iniciar sesi[oó]n|inicia sesi[oó]n|log in|sign up|reg[ií]strate|continuar con|continue with", tx): return "login"
    return ""


def _diagnostico(tab, url, que):
    """Deja en la carpeta del worker qué vio el navegador (texto y captura), para saber por qué TikTok no devolvió nada."""
    try:
        st = json.loads(tab.eval(JS_ESTADO) or "{}")
        DIAG_TXT.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\nPedido: {url}\nResultado: {que} (motivo: {MOTIVO['m'] or '-'})\nURL final: {st.get('u')}\n\nTexto de la página:\n{st.get('t')}\n", "utf-8")
        import base64
        r = tab.call("Page.captureScreenshot", {"format": "png"}, timeout=15)
        DIAG_PNG.write_bytes(base64.b64decode(r.get("data", "")))
    except Exception: pass


def listar(url, log=print, scrolls=8, espera=35):
    """Abre la página en el Chrome OCULTO, espera a que carguen los videos, baja con scroll y devuelve [{id, t, dur, v, url}].
    Si no hay videos, MOTIVO['m'] dice por qué (login, captcha, privada...) y se guarda diagnostico-tiktok.txt/.png."""
    MOTIVO["m"] = ""; tab = None; vistos = {}
    def leer():
        try: items = json.loads(tab.eval(JS_LISTA) or "[]")
        except Exception: return
        for it in items:
            m = re.search(r"/video/(\d{15,})", it.get("h", ""))
            if m and m.group(1) not in vistos:
                vistos[m.group(1)] = {"id": m.group(1), "t": re.sub(r"\s+", " ", it.get("t", "")).strip()[:300], "dur": 0, "v": 0, "url": it["h"]}
    try:
        tab = _tab(url); time.sleep(3)
        fin = time.time() + espera; avisado = False
        while time.time() < fin:
            leer()
            if vistos: break
            try: st = json.loads(tab.eval(JS_ESTADO) or "{}")
            except Exception: st = {}
            mot = _motivo_de((st.get("t") or "") + " " + (st.get("u") or "")) if st else ""
            if "/login" in (st.get("u") or ""): mot = "login"
            if mot in ("privada", "noexiste"): MOTIVO["m"] = mot; break
            if mot == "captcha" and not avisado:
                avisado = True; log("TikTok pidió verificación humana (captcha) en el navegador oculto.")
            if mot: MOTIVO["m"] = mot
            time.sleep(1.5)
        if vistos:
            MOTIVO["m"] = ""
            for _ in range(scrolls):
                try: tab.eval("window.scrollBy(0, 2400)")
                except Exception: pass
                time.sleep(1.5); leer()
        elif not MOTIVO["m"]: MOTIVO["m"] = "vacio"
        guardar_cookies(_cookies(tab))
        if not vistos: _diagnostico(tab, url, "sin videos")
        return list(vistos.values())
    except ErrorWeb as e: log("TikTok: " + str(e)); return []
    except Exception as e: log("No pude leer TikTok en segundo plano: " + str(e)[:100]); return []
    finally:
        try: tab and tab.cerrar()
        except Exception: pass


def info_web(url, espera=30):
    """Abre el video en el Chrome oculto y saca de la propia página sus datos y los enlaces directos del archivo."""
    tab = None
    try:
        tab = _tab(url); time.sleep(2); fin = time.time() + espera; d = {}
        while time.time() < fin:
            try: d = json.loads(tab.eval(JS_VIDEO) or "{}")
            except Exception: d = {}
            if d.get("urls") or d.get("st"): break
            time.sleep(1.2)
        cs = _cookies(tab); guardar_cookies(cs)
        if not d.get("urls"):
            MOTIVO["m"] = "vacio"; _diagnostico(tab, url, "video sin enlaces")
            raise ErrorWeb("TikTok no mostró el video (código %s)%s" % (d.get("st") or "?", "; probá iniciar sesión en TikTok" if not (sesion_en(cs) or sesion_guardada()) else ""))
        m = re.search(r"/video/(\d{15,})", url)
        return {"id": d.get("id") or (m.group(1) if m else ""), "title": (d.get("desc") or "").strip() or ("TikTok " + (m.group(1) if m else "")),
                "duration": d.get("dur") or 0, "thumbnail": d.get("thumb") or "", "webpage_url": url,
                "_urls": d["urls"], "_ua": d.get("ua") or _ua(None),
                "_cookie": "; ".join(f"{c['name']}={c['value']}" for c in cs if "tiktok" in str(c.get("domain", "")))}
    finally:
        try: tab and tab.cerrar()
        except Exception: pass


def _bajar(u, destino, hdrs, cb, chequear):
    req = urllib.request.Request(u, headers=hdrs); tmp = pathlib.Path(str(destino) + ".part"); hecho = 0
    with urllib.request.urlopen(req, timeout=40) as r:
        ct = (r.headers.get("Content-Type") or "").lower()
        if ct and not any(x in ct for x in ("video", "octet", "mp4", "binary")): raise ErrorWeb("la respuesta no es un video (" + ct[:40] + ")")
        total = int((r.headers.get("Content-Range") or "").split("/")[-1] or 0) if r.headers.get("Content-Range") else int(r.headers.get("Content-Length") or 0)
        with open(tmp, "wb") as f:
            while True:
                chequear()
                b = r.read(262144)
                if not b: break
                f.write(b); hecho += len(b)
                if total: cb(min(hecho / total, 0.99))
    if hecho < 20000:
        tmp.unlink(missing_ok=True); raise ErrorWeb("archivo demasiado chico (%d bytes)" % hecho)
    os.replace(tmp, destino); cb(1.0)


def descargar_web(url, destino, cb=lambda f: None, chequear=lambda: None):
    """Respaldo cuando yt-dlp no puede: baja el archivo con las mismas cookies y el mismo navegador que TikTok ve."""
    i = info_web(url); hdrs = {"User-Agent": i["_ua"], "Referer": "https://www.tiktok.com/", "Accept": "*/*", "Range": "bytes=0-",
                               "Cookie": i["_cookie"], "Origin": "https://www.tiktok.com"}
    ultimo = "sin enlaces"
    for u in dict.fromkeys(i["_urls"]):
        try: _bajar(u, pathlib.Path(destino), hdrs, cb, chequear); return i
        except (ErrorWeb, OSError, ValueError) as e: ultimo = str(e)[:140]
    raise ErrorWeb("no pude bajar el archivo: " + ultimo)
