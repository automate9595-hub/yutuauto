"""TikTok a prueba de bloqueos.
- yt-dlp con varias variantes (Chrome simulado + cookies, solo cookies, sin nada) y el error REAL a la vista.
- Si yt-dlp no puede, se lee y se descarga con el Chrome del worker (navegador real, con tu sesión de TikTok).
- Lectura de cuentas, hashtags y búsquedas por tema con ese mismo Chrome.
"""
import json, os, pathlib, re, subprocess, sys, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
COOK = ROOT / "tiktok-cookies.txt"
MOTIVO = {"m": ""}          # por qué la última lectura no devolvió videos: login | captcha | privada | noexiste | vacio | sin_chrome
SESION = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")


class ErrorWeb(Exception): pass


# ------------------------------------------------------------------ cookies
def guardar_cookies(cookies):
    """Cookies de TikTok del Chrome del worker -> archivo Netscape (solo líneas válidas) para yt-dlp. True si guardó alguna."""
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
    try:
        tmp = COOK.with_suffix(".tmp"); tmp.write_text("\n".join(lin) + "\n", "utf-8"); os.replace(tmp, COOK); return True
    except Exception: return False


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
    """Formas de llamar a yt-dlp, de la más completa a la más simple. Si una falla (p. ej. curl_cffi incompatible), la siguiente sigue."""
    tt = "tiktok.com" in str(url)
    imp = ["--impersonate", "chrome"] if _curl_ok() else []
    ck = ["--cookies", str(COOK)] if tt and cookies_validas() else []
    out = []
    for a in (imp + ck, imp, ck, []):
        if a not in out: out.append(a)
    return out


def limpiar_error(texto):
    """Última línea útil de lo que dijo yt-dlp (ERROR: ...), sin rutas ni ruido."""
    lin = [l.strip() for l in str(texto or "").splitlines() if l.strip()]
    err = [l for l in lin if l.startswith("ERROR")] or lin
    return re.sub(r"\s+", " ", err[-1])[:260] if err else "yt-dlp terminó sin decir por qué"


def ytdlp_texto(args, url, timeout=90):
    """Corre yt-dlp probando cada variante. Devuelve su salida; si todas fallan, el error REAL (no solo 'returned non-zero')."""
    ultimo = ""
    for var in variantes(url):
        try:
            r = subprocess.run([sys.executable, "-m", "yt_dlp", *var, *args, url], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired: ultimo = "yt-dlp tardó demasiado"; continue
        except Exception as e: ultimo = str(e)[:200]; continue
        if r.returncode == 0 and r.stdout.strip(): return r.stdout
        ultimo = limpiar_error(r.stderr or r.stdout)
    raise RuntimeError(ultimo or "yt-dlp no devolvió nada")


def info(url, web=True):
    """Datos del video (título, duración...). TikTok: yt-dlp y, si no puede, la propia página abierta en el Chrome del worker."""
    try: return json.loads(ytdlp_texto(["-j", "--no-playlist"], url).strip().splitlines()[-1])
    except Exception as e:
        causa = str(e)
        if "tiktok.com" in str(url) and web:
            try: return info_web(url)
            except Exception as e2: causa += " | Chrome del worker: " + str(e2)[:160]
        raise RuntimeError(causa[:380])


# ------------------------------------------------------------------ Chrome del worker (CDP)
def _tab(url="about:blank"):
    import cdp
    try: return cdp.Tab.abrir(url)
    except Exception as e: MOTIVO["m"] = "sin_chrome"; raise ErrorWeb("el Chrome del worker no está abierto (" + str(e)[:80] + ")")


def _cookies(tab):
    try: return tab.call("Network.getAllCookies").get("cookies", [])
    except Exception: return []


def sesion_iniciada():
    """¿Hay una sesión de TikTok abierta en el Chrome del worker? Si la hay, guarda sus cookies para yt-dlp."""
    tab = None
    try:
        tab = _tab(); cs = _cookies(tab)
        if sesion_en(cs): guardar_cookies(cs); return True
        return False
    except Exception: return False
    finally:
        try: tab and tab.cerrar()
        except Exception: pass


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


def listar(url, log=print, scrolls=8, espera=35):
    """Abre la página en el Chrome del worker (navegador real), espera a que carguen los videos, baja con scroll y devuelve
    [{id, t, dur, v, url}]. Si no hay videos, MOTIVO['m'] dice por qué (login, captcha, privada...)."""
    MOTIVO["m"] = ""; tab = None; vistos = {}
    def leer():
        try: items = json.loads(tab.eval(JS_LISTA) or "[]")
        except Exception: return
        for it in items:
            m = re.search(r"/video/(\d{15,})", it.get("h", ""))
            if m and m.group(1) not in vistos:
                vistos[m.group(1)] = {"id": m.group(1), "t": re.sub(r"\s+", " ", it.get("t", "")).strip()[:300], "dur": 0, "v": 0, "url": it["h"]}
    try:
        tab = _tab(url); time.sleep(4)
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
                avisado = True; fin = max(fin, time.time() + 90); log("TikTok pide verificación humana: resolvela en la ventana de Chrome del worker (te espero 90 s).")
            if mot: MOTIVO["m"] = mot
            time.sleep(1.5)
        if vistos:
            MOTIVO["m"] = ""
            for _ in range(scrolls):
                try: tab.eval("window.scrollBy(0, 2400)")
                except Exception: pass
                time.sleep(1.8); leer()
        guardar_cookies(_cookies(tab))
        if not vistos and not MOTIVO["m"]: MOTIVO["m"] = "vacio"
        return list(vistos.values())
    except ErrorWeb as e: log("TikTok: " + str(e)); return []
    except Exception as e: log("No pude leer TikTok con el Chrome del worker: " + str(e)[:100]); return []
    finally:
        try: tab and tab.cerrar()
        except Exception: pass


def info_web(url, espera=30):
    """Abre el video en el Chrome del worker y saca de la propia página sus datos y los enlaces directos del archivo."""
    tab = None
    try:
        tab = _tab(url); time.sleep(3); fin = time.time() + espera; d = {}
        while time.time() < fin:
            try: d = json.loads(tab.eval(JS_VIDEO) or "{}")
            except Exception: d = {}
            if d.get("urls"): break
            if d.get("st"): break
            time.sleep(1.5)
        cs = _cookies(tab); guardar_cookies(cs)
        if not d.get("urls"):
            raise ErrorWeb("TikTok no mostró el video (código %s)%s" % (d.get("st") or "?", "; probá iniciar sesión en TikTok" if not sesion_en(cs) else ""))
        m = re.search(r"/video/(\d{15,})", url)
        return {"id": d.get("id") or (m.group(1) if m else ""), "title": (d.get("desc") or "").strip() or ("TikTok " + (m.group(1) if m else "")),
                "duration": d.get("dur") or 0, "thumbnail": d.get("thumb") or "", "webpage_url": url,
                "_urls": d["urls"], "_ua": d.get("ua") or "Mozilla/5.0",
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
