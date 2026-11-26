"""Reels de Facebook en SEGUNDO PLANO.
- La lista de reels (por tema o por cuenta) se lee con el Chrome OCULTO del worker (el mismo de TikTok: puerto 9333, sin ventanas, sin imágenes).
- La sesión de Facebook se inicia UNA vez en el Chrome visible del worker; sus cookies se copian solas al Chrome oculto y a yt-dlp.
- La descarga la hace yt-dlp con esas cookies (el mismo camino que usan los demás pilotos).
"""
import json, os, pathlib, re, time, urllib.parse

import tiktok

ROOT = pathlib.Path(__file__).parent
COOK = tiktok.FBCOOK
DIAG_TXT, DIAG_PNG = ROOT / "diagnostico-facebook.txt", ROOT / "diagnostico-facebook.png"
MOTIVO = {"m": ""}          # login | captcha | noexiste | vacio | sin_chrome
SESION = ("c_user", "xs")
_SYNC = {"t": 0}


def sesion_en(cookies):
    nom = {c.get("name") for c in cookies or [] if "facebook" in str(c.get("domain", "")) and c.get("value")}
    return all(k in nom for k in SESION)


def guardar_cookies(cookies):
    """Cookies de Facebook -> archivo Netscape para yt-dlp. No pisa una sesión buena con cookies anónimas."""
    lin = ["# Netscape HTTP Cookie File"]
    for c in cookies or []:
        dom, nom, val = str(c.get("domain", "")), str(c.get("name", "")), str(c.get("value", ""))
        if "facebook" not in dom or not nom or re.search(r"[\t\r\n]", nom + val): continue
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


def sincronizar_sesion(forzar=False):
    """Copia la sesión del Chrome visible del worker (si está abierto) al archivo de cookies. Máx. una vez cada 5 minutos."""
    if not forzar and time.time() - _SYNC["t"] < 300 and sesion_guardada(): return
    _SYNC["t"] = time.time()
    cs = tiktok._cookies_principal()
    if cs: guardar_cookies(cs)


def sesion_iniciada():
    """¿Hay una sesión de Facebook abierta? Mira el Chrome visible del worker y copia sus cookies para el Chrome oculto."""
    cs = tiktok._cookies_principal()
    if cs is None: return sesion_guardada()
    if sesion_en(cs): guardar_cookies(cs); return True
    return False


# ------------------------------------------------------------------ direcciones
_RESERVADOS = {"reel", "reels", "watch", "videos", "groups", "share", "pages", "people", "p", "profile.php", "hashtag", "search", "photo", "story.php", "permalink.php"}

def _base_cuenta(cuenta):
    """Entiende lo que pegue el usuario: enlace de la página (con o sin /reels, /videos, ?mibextid...), /people/Nombre/ID, /p/Nombre-ID,
    profile.php?id=ID, enlace /share/..., @nombre o solo el nombre. Devuelve ('id', ID) | ('nombre', x) | ('url', enlace) | ('', '')."""
    c = str(cuenta or "").strip()
    if not c: return "", ""
    m = re.search(r"profile\.php\?id=(\d+)", c)
    if m: return "id", m.group(1)
    m = re.search(r"facebook\.com/(?:people|pages)/[^/?#]+/(\d{6,})", c)
    if m: return "id", m.group(1)
    m = re.search(r"facebook\.com/p/[^/?#]*?(\d{8,})", c)
    if m: return "id", m.group(1)
    if re.search(r"(?:facebook|fb)\.com/(?:share|groups)/", c):
        u = c if c.startswith("http") else "https://" + c.lstrip("/")
        return "url", u.split("#")[0]
    m = re.search(r"(?:facebook|fb)\.com/([\w.\-]+)", c)
    n = re.sub(r"[^\w.\-]", "", m.group(1) if m else c.lstrip("@/ ").split("/")[0].split("?")[0])
    if re.fullmatch(r"\d{8,}", n): return "id", n                                       # facebook.com/61576731622656/
    return ("nombre", n) if n and n.lower() not in _RESERVADOS else ("", "")

def urls_cuenta(cuenta):
    """Direcciones a probar, en orden: pestaña de Reels y pestaña de Videos de esa página/cuenta."""
    k, v = _base_cuenta(cuenta)
    if k == "id": return [f"https://www.facebook.com/profile.php?id={v}&sk=reels_tab", f"https://www.facebook.com/profile.php?id={v}&sk=videos"]
    if k == "nombre": return [f"https://www.facebook.com/{v}/reels/", f"https://www.facebook.com/{v}/videos/"]
    if k == "url": return [v]
    return []

def url_cuenta(cuenta):
    u = urls_cuenta(cuenta); return u[0] if u else ""


def nombre_cuenta(cuenta):
    """Nombre corto para mostrar en los mensajes."""
    k, v = _base_cuenta(cuenta)
    if k == "id": return "id" + v
    if k == "url": return re.sub(r"^https?://(www\.)?", "", v)[:40]
    return v or str(cuenta or "").strip()[:40]


def resolver(url, log=print):
    """Enlace /share/...: lo abre en el Chrome oculto, espera la redirección y devuelve la dirección real de la página ('' si no se pudo)."""
    tab = None
    try:
        tab = _tab(url); fin = time.time() + 25; u = ""
        while time.time() < fin:
            time.sleep(1.5)
            try: u = json.loads(tab.eval(JS_ESTADO) or "{}").get("u") or ""
            except Exception: u = ""
            if u and "/share/" not in u and "about:blank" not in u: break
        if not u or "/share/" in u or "/login" in u or "checkpoint" in u: return ""
        return u.split("#")[0]
    except Exception as e: log("Facebook: no pude resolver el enlace: " + str(e)[:80]); return ""
    finally:
        try: tab and tab.cerrar()
        except Exception: pass


def url_fuente(f):
    """Fuente de tema: «?texto» = búsqueda de videos, «#x» = hashtag, otra cosa = cuenta."""
    if f.startswith("?"): return "https://www.facebook.com/search/videos/?q=" + urllib.parse.quote(f[1:])
    if f.startswith("#"): return "https://www.facebook.com/hashtag/" + urllib.parse.quote(f[1:])
    return url_cuenta(f)


def id_de_url(u):
    for rx in (r"/reel/(\d{8,})", r"/videos/(\d{8,})", r"[?&]v=(\d{8,})", r"/watch/?\?.*?v=(\d{8,})", r"/share/r/([\w\-]+)"):
        m = re.search(rx, str(u or ""))
        if m: return m.group(1)
    return ""


# ------------------------------------------------------------------ Chrome oculto
def _tab(url="about:blank"):
    """Pestaña OCULTA (mismo Chrome en segundo plano que usa TikTok). Si no arranca, una pestaña del Chrome del worker sin traerla al frente."""
    import cdp
    try:
        v = tiktok.bg_asegurar(); tiktok.BG_USO.write_text(str(time.time()))
        tab = cdp.Tab.abrir("about:blank", port=tiktok.BG_PORT, traer=False)
        try:
            tab.call("Network.enable")
            tab.call("Network.setUserAgentOverride", {"userAgent": tiktok._ua(v), "acceptLanguage": "es-ES,es;q=0.9,en;q=0.8", "platform": "Win32"})
            try: tab.call("Network.setBlockedURLs", {"urls": tiktok.BLOQUEAR})
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
            if url != "about:blank": tab.call("Page.navigate", {"url": url})
            return tab
        except Exception:
            try: tab.cerrar()
            except Exception: pass
            raise
    except Exception as e1:
        try: return cdp.Tab.abrir(url, port=9222, traer=False)
        except Exception:
            MOTIVO["m"] = "sin_chrome"; raise tiktok.ErrorWeb("no pude abrir un navegador en segundo plano (" + str(e1)[:70] + ")")


JS_ESTADO = r"""(function(){var t=((document.body&&document.body.innerText)||'').slice(0,1800).toLowerCase();return JSON.stringify({u:location.href,t:t})})()"""
JS_LISTA = r"""(function(){var o=[],seen={};document.querySelectorAll('a[href*="/reel/"],a[href*="/videos/"],a[href*="/watch/?v="],a[href*="/watch?v="]').forEach(function(a){
var h=a.href;var m=h.match(/\/reel\/(\d{8,})/)||h.match(/\/videos\/(\d{8,})/)||h.match(/[?&]v=(\d{8,})/);if(!m||seen[m[1]])return;seen[m[1]]=1;
var t=a.getAttribute('aria-label')||a.title||'';var im=a.querySelector('img');if(!t&&im)t=im.alt||'';
if(!t){var n=a,k=0;while(n&&k<5&&!t){n=n.parentElement;k++;if(n&&n.innerText&&n.innerText.length>12&&n.innerText.length<500){
var ls=n.innerText.split('\n').filter(function(x){return x.trim().length>12});if(ls.length)t=ls[0]}}}
var vw='';var c=a;for(var k=0;k<5&&c&&!vw;k++){c=c.parentElement;if(!c||!c.innerText||c.innerText.length>400)break;
var ls=c.innerText.split('\n');for(var j=0;j<ls.length;j++){if(/^\s*[\d][\d.,]*\s*(k|m|b|mil|mill\.?)?\s*$/i.test(ls[j])){vw=ls[j].trim();break}}}
o.push({i:m[1],t:t||'',vw:vw})});return JSON.stringify(o)})()"""


def _motivo_de(tx):
    if re.search(r"checkpoint|captcha|confirm.*you.*human|verifica que eres|security check|comprobaci[oó]n de seguridad", tx): return "captcha"
    if re.search(r"este contenido no est[aá] disponible|this content isn.t available|page isn.t available|p[aá]gina no est[aá] disponible|no encontramos", tx): return "noexiste"
    if re.search(r"iniciar sesi[oó]n|inicia sesi[oó]n|log in|log into|crear cuenta nueva|create new account|you must log in", tx): return "login"
    return ""


def _diagnostico(tab, url, que):
    try:
        st = json.loads(tab.eval(JS_ESTADO) or "{}")
        DIAG_TXT.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\nPedido: {url}\nResultado: {que} (motivo: {MOTIVO['m'] or '-'})\nURL final: {st.get('u')}\n\nTexto de la página:\n{st.get('t')}\n", "utf-8")
        import base64
        r = tab.call("Page.captureScreenshot", {"format": "png"}, timeout=15)
        DIAG_PNG.write_bytes(base64.b64decode(r.get("data", "")))
    except Exception: pass


def listar(url, log=print, scrolls=8, espera=35):
    """Abre la página en el Chrome OCULTO, baja con scroll y devuelve [{id, t, dur, v, url}] de reels.
    Si no hay ninguno, MOTIVO['m'] dice por qué (login, captcha, no existe...) y queda diagnostico-facebook.txt/.png."""
    MOTIVO["m"] = ""; tab = None; vistos = {}
    def leer():
        try: items = json.loads(tab.eval(JS_LISTA) or "[]")
        except Exception: return
        for it in items:
            i = it.get("i")
            if i and i not in vistos:
                vistos[i] = {"id": i, "t": re.sub(r"\s+", " ", it.get("t", "")).strip()[:300], "dur": 0, "v": tiktok.num_corto(it.get("vw")), "url": f"https://www.facebook.com/reel/{i}"}
    try:
        tab = _tab(url); time.sleep(3)
        fin = time.time() + espera
        while time.time() < fin:
            leer()
            if vistos: break
            try: st = json.loads(tab.eval(JS_ESTADO) or "{}")
            except Exception: st = {}
            mot = _motivo_de((st.get("t") or "")) if st else ""
            if "/login" in (st.get("u") or "") or "checkpoint" in (st.get("u") or ""): mot = "login" if "/login" in (st.get("u") or "") else "captcha"
            if mot in ("noexiste",): MOTIVO["m"] = mot; break
            if mot: MOTIVO["m"] = mot
            time.sleep(1.5)
        if vistos:
            MOTIVO["m"] = ""
            for _ in range(scrolls):
                try: tab.eval("window.scrollBy(0, 2600)")
                except Exception: pass
                time.sleep(1.6); leer()
        elif not MOTIVO["m"]: MOTIVO["m"] = "vacio"
        try: guardar_cookies(tiktok._cookies(tab))
        except Exception: pass
        if not vistos: _diagnostico(tab, url, "sin reels")
        return list(vistos.values())
    except tiktok.ErrorWeb as e: log("Facebook: " + str(e)); return []
    except Exception as e: log("No pude leer Facebook en segundo plano: " + str(e)[:100]); return []
    finally:
        try: tab and tab.cerrar()
        except Exception: pass
