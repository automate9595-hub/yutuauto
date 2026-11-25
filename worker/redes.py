"""Publicar el mismo video (con el mismo título y descripción) también en Facebook (Página, como Reel) y en TikTok.
Se hace como una persona: en el Chrome del worker, en una pestaña aparte que se cierra al terminar, con la sesión que ya iniciaste ahí.
- Facebook: facebook.com -> «Foto/vídeo» -> subir el mismo archivo -> título y descripción -> «Publicar».
- TikTok: TikTok Studio (tiktok.com/tiktokstudio/upload).
Si algo falla NO se toca la publicación de YouTube: queda el motivo en el video y diagnostico-redes.txt/.png en la carpeta del worker.
"""
import json, os, pathlib, re, subprocess, time

import cdp

ROOT = pathlib.Path(__file__).parent
DEST = ROOT / "destinos.json"
DIAG_TXT, DIAG_PNG = ROOT / "diagnostico-redes.txt", ROOT / "diagnostico-redes.png"


class RedError(Exception): pass


# ------------------------------------------------------------------ dónde publicar
PLATAFORMAS = ("yt", "fb", "tt")


def _normalizar(d):
    pl = str(d.get("plataforma") or "yt").lower()
    if pl not in PLATAFORMAS: pl = "yt"
    return {"plataforma": pl, "fb": pl == "fb", "tt": pl == "tt", "fb_page": str(d.get("fb_page") or "").strip()[:200]}


def leer_destinos():
    """UNA sola plataforma para todos los videos: yt (YouTube), fb (Facebook) o tt (TikTok)."""
    try: d = json.loads(DEST.read_text("utf-8"))
    except Exception: d = {}
    return _normalizar(d)


def guardar_destinos(d):
    cur = _normalizar(d)
    tmp = DEST.with_suffix(".tmp"); tmp.write_text(json.dumps(cur, ensure_ascii=False), "utf-8"); tmp.replace(DEST)
    return cur


def texto_publicacion(titulo, desc, maximo):
    """Título + descripción (con sus hashtags) como una sola publicación, recortada al límite de la red."""
    t = (str(titulo or "").strip() + "\n\n" + str(desc or "").strip()).strip()
    if len(t) <= maximo: return t
    corte = t[:maximo]
    return (corte.rsplit("\n", 1)[0] if "\n" in corte[maximo // 2:] else corte.rsplit(" ", 1)[0]).strip()


# ------------------------------------------------------------------ utilidades de página
def _body(tab):
    try: return (tab.eval("((document.body&&document.body.innerText)||'').slice(0,4000)") or "").lower()
    except Exception: return ""


def _diag(tab, red, paso, err):
    try:
        DIAG_TXT.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\nRed: {red}\nPaso: {paso}\nError: {err}\nURL: {tab.url()}\n\nTexto visible:\n{_body(tab)}\n", "utf-8")
        tab.captura(DIAG_PNG)
        try: tab.diagnostico(ROOT / "diagnostico-redes-botones.txt", f"{red} · {paso} · {err}")
        except Exception: pass
    except Exception: pass


def _centro_texto(tab, patron, tags="button,[role=button],div[role=button],span[role=button]", habilitado=True):
    return tab.eval("(function(){var re=new RegExp(" + json.dumps(patron) + ",'i');var a=window.__A(" + json.dumps(tags) + ");"
                    "for(var i=0;i<a.length;i++){var e=a[i],t=(e.innerText||e.getAttribute('aria-label')||'').trim();var r=e.getBoundingClientRect();"
                    "if(!t||t.length>40||!re.test(t)||r.width<=0||r.height<=0)continue;"
                    + ("if(e.hasAttribute('disabled')||e.getAttribute('aria-disabled')==='true')continue;" if habilitado else "") +
                    "e.scrollIntoView({block:'center'});r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}}return null})()")


def _clic(tab, patron, **kw):
    c = _centro_texto(tab, patron, **kw)
    if not c: return False
    for t in ("mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent", {"type": t, "x": c["x"], "y": c["y"], "button": "left", "clickCount": 1})
    return True


def _subir_archivo(tab, ruta, patron_boton):
    """Entrega el archivo al selector de la página: directo al <input type=file> o tocando el botón de 'subir' e interceptando el cuadro de Windows."""
    if tab.existe("input[type=file]"): tab.archivos("input[type=file]", [str(ruta)]); return True
    c = _centro_texto(tab, patron_boton, habilitado=False)
    if c and tab.subir_con_selector(c["x"], c["y"], [str(ruta)]): return True
    if tab.existe("input[type=file]"): tab.archivos("input[type=file]", [str(ruta)]); return True
    return False


def _abrir(url):
    tab = cdp.Tab.abrir("about:blank", port=9222, traer=False)
    try: tab.call("Emulation.setFocusEmulationEnabled", {"enabled": True})       # que la página no se "duerma" aunque Chrome esté minimizado
    except Exception: pass
    tab.ir(url); time.sleep(2.5)
    return tab


RX_LOGIN = re.compile(r"iniciar sesi[oó]n|inicia sesi[oó]n|log in|log into|sign in|crear cuenta|create new account|continuar con|continue with", re.I)


# ------------------------------------------------------------------ Facebook (facebook.com -> Foto/vídeo -> Publicar)
RX_PUBLICAR = r"^(publicar|post|publish|compartir|share)$"
RX_FB_OK = re.compile(r"se est[aá] publicando|publicando|publicad[oa]|tu (reel|v[ií]deo|publicaci[oó]n) (se|est[aá]|ya)|your (reel|video|post) (is|has been|was)|posting|shared|published", re.I)


RX_FOTOVIDEO = r"^(foto/v[ií]deo|photo/video)$"
RX_ANADIR = r"a[ñn]adir fotos?/v[ií]deos?|agregar fotos?/v[ií]deos?|add photos?/videos?"
JS_VIDEO_ADJUNTO = r"""(function(){var a=window.__A('div[role=dialog]');
if(/\/(post|reel|reels|stories)\/create/i.test(location.pathname))a=[document.body];
for(var i=0;i<a.length;i++){var r=a[i].getBoundingClientRect();if(r.width<=0||r.height<=0)continue;
var t=a[i].innerText||'';
if(a[i].querySelector('video'))return 1;
if(/\.mp4|subiendo|uploading|procesando|processing|\b\d{1,2}:\d{2}\b/i.test(t))return 1;
if(a[i].querySelector('div[role=textbox]')&&!/a[ñn]adir fotos?\/v[ií]deos?|arrastr|drag and drop|add photos?\/videos?/i.test(t))return 1}
return 0})()"""


def _entregar(tab, ev, ruta):
    """Chrome avisó que Facebook quiso abrir el selector de archivos: se le entrega la ruta completa del video (sin ventana de Windows)."""
    if ev and ev.get("backendNodeId"):
        tab.call("DOM.setFileInputFiles", {"files": [os.path.abspath(str(ruta))], "backendNodeId": ev["backendNodeId"]}); return True
    return False


def _dialogo_windows(ruta):
    """Último recurso: si el selector de Windows ('Abrir') quedó abierto, escribe la ruta completa del video en «Nombre» y da Enter."""
    p = os.path.abspath(str(ruta))
    esc = "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in p).replace("'", "''")
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $w=New-Object -ComObject WScript.Shell; $ok=$false; "
          "foreach($t in 'Abrir','Open'){ if($w.AppActivate($t)){$ok=$true;break} }; if(-not $ok){exit 2}; Start-Sleep -Milliseconds 800; "
          "[System.Windows.Forms.SendKeys]::SendWait('" + esc + "'); Start-Sleep -Milliseconds 600; [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return r.returncode == 0
    except Exception: return False


RX_URL_CREAR = re.compile(r"/(post|reel|reels|stories)/create|/composer", re.I)


def _dialogo_fb(tab):
    """¿Está abierto el compositor de Facebook? Como cuadro (dialog) o como página completa «Crear reel» (facebook.com/post/create)."""
    try: u = tab.url() or ""
    except Exception: u = ""
    return bool(RX_URL_CREAR.search(u)) or bool(tab.visible("div[role=dialog]"))


def _caja_texto_fb(tab):
    for sel in ("div[role=dialog] div[role=textbox][contenteditable=true]", "div[role=textbox][contenteditable=true]"):
        if tab.visible(sel): return sel
    return None


def facebook(ruta, texto, page="", chk=lambda: None, log=print):
    """Publica desde facebook.com (NO Meta Business Suite): inicio -> 'Foto/vídeo' -> subir el MISMO archivo -> título+descripción -> 'Publicar'."""
    tab = _abrir("https://www.facebook.com/"); paso = "abrir facebook.com"
    try:
        for _ in range(25):
            chk(); b = _body(tab)
            if len(b) > 200: break
            time.sleep(1)
        if "/login" in tab.url() or (RX_LOGIN.search(_body(tab)) and not _centro_texto(tab, r"^(foto/v[ií]deo|photo/video)$", habilitado=False)):
            raise RedError("Facebook pide iniciar sesión: entrá a facebook.com en el Chrome del worker (botón «Iniciar sesión en Facebook») y reintento en la próxima publicación.")
        paso = "tocar «Foto/vídeo»"
        try: tab.call("DOM.enable")
        except Exception: pass
        tab.call("Page.setInterceptFileChooserDialog", {"enabled": True}); tab.eventos.clear()      # el selector de Windows no se muestra: se le entrega la ruta
        subido = False; fin = time.time() + 40
        while time.time() < fin and not subido and not _dialogo_fb(tab):
            chk()
            _clic(tab, RX_FOTOVIDEO, habilitado=False)
            subido = _entregar(tab, tab.esperar_evento("Page.fileChooserOpened", 4), ruta)         # a veces el propio botón ya abre el selector
            if not subido: time.sleep(1.5)
        if not subido and not _dialogo_fb(tab): raise RedError("No pude abrir «Foto/vídeo» en facebook.com (cambió la pantalla o no hay cuadro para publicar).")
        time.sleep(1.5)
        paso = "subir el archivo"; fin = time.time() + 60; intentos = 0
        while not subido and time.time() < fin:
            chk(); intentos += 1
            if _clic(tab, RX_ANADIR, habilitado=False):
                subido = _entregar(tab, tab.esperar_evento("Page.fileChooserOpened", 6), ruta)
                if not subido and _dialogo_windows(ruta): log("  Facebook: elegí el archivo en la ventana «Abrir» de Windows."); subido = True
            if not subido and tab.existe("div[role=dialog] input[type=file]"):
                tab.archivos("div[role=dialog] input[type=file]", [str(ruta)]); subido = True
            if not subido: time.sleep(2)
        if not subido: raise RedError("No encontré dónde subir el video en el cuadro de Facebook.")
        paso = "comprobar que el video se cargó"; fin = time.time() + 90; adj = False
        while time.time() < fin:
            chk()
            if tab.eval(JS_VIDEO_ADJUNTO): adj = True; break
            time.sleep(2)
        try: tab.call("Page.setInterceptFileChooserDialog", {"enabled": False})
        except Exception: pass
        if not adj: raise RedError("El video no llegó a cargarse en Facebook (el selector de archivos no recibió «" + pathlib.Path(str(ruta)).name + "»).")
        paso = "escribir el título y la descripción y publicar"; escrito = False; click_pub = False; fin = time.time() + 20 * 60
        while time.time() < fin:
            chk(); time.sleep(2)
            _clic(tab, r"^(aceptar|entendido|got it|ok)$")                                   # aviso 'los videos se comparten como reels'
            caja = None if escrito else _caja_texto_fb(tab)
            if caja:
                tab.escribir(caja, texto, 0); escrito = True; time.sleep(1.5); continue
            if escrito and _clic(tab, RX_PUBLICAR): click_pub = True; break                 # solo se habilita cuando el video terminó de subir
            if escrito: _clic(tab, r"^(siguiente|next|continuar|continue)$")
        if not click_pub: raise RedError("El video no quedó listo para «Publicar» en Facebook (tardó más de 20 minutos o cambió la pantalla).")
        paso = "confirmar la publicación"; fin = time.time() + 180
        while time.time() < fin:
            chk(); time.sleep(2); b = _body(tab)
            _clic(tab, r"^(publicar ahora|post now|share now|compartir ahora)$")
            if not _dialogo_fb(tab) or RX_FB_OK.search(b): time.sleep(4); return "ok"        # el cuadro se cerró: ya se publicó
        return "enviado"
    except Exception as e:
        _diag(tab, "Facebook", paso, e)
        raise
    finally:
        try: tab.ventana("minimized")                      # terminó: Chrome minimizado y se sigue con el próximo video
        except Exception: pass
        try: tab.cerrar()
        except Exception: pass


# ------------------------------------------------------------------ TikTok
def tiktok(ruta, texto, chk=lambda: None, log=print):
    tab = _abrir("https://www.tiktok.com/tiktokstudio/upload?from=upload"); paso = "abrir TikTok Studio"
    try:
        fin = time.time() + 45
        while time.time() < fin and not tab.existe("input[type=file]"):
            chk(); time.sleep(1)
        if not tab.existe("input[type=file]"):
            if "login" in tab.url() or RX_LOGIN.search(_body(tab)):
                raise RedError("TikTok pide iniciar sesión: entrá a TikTok en el Chrome del worker (botón «Iniciar sesión en TikTok») y reintento en la próxima publicación.")
            raise RedError("TikTok Studio no mostró el cuadro para subir el video.")
        paso = "subir el archivo"; tab.archivos("input[type=file]", [str(ruta)])
        paso = "esperar a que termine de subir"; fin = time.time() + 20 * 60; listo = False
        while time.time() < fin:
            chk(); time.sleep(2)
            if tab.habilitado('[data-e2e="post_video_button"]') or tab.habilitado("button[data-e2e=post_video_button]"): listo = True; break
            if _centro_texto(tab, r"^(publicar|post)$") and re.search(r"subido|uploaded|100%|cargado", _body(tab)): listo = True; break
        if not listo: raise RedError("TikTok no terminó de procesar el video (más de 20 minutos).")
        paso = "escribir el título y la descripción"
        for sel in ("div.public-DraftEditor-content[contenteditable=true]", "div[contenteditable=true]"):
            if tab.visible(sel): tab.escribir(sel, texto, 0); break
        else: log("  TikTok: no encontré el campo de descripción; publico sin texto.")
        time.sleep(2)
        paso = "publicar"; clic = False
        for _ in range(20):
            chk()
            if tab.clic_visible('[data-e2e="post_video_button"]', True, False) or _clic(tab, r"^(publicar|post)$"): clic = True; break
            time.sleep(1.5)
        if not clic: raise RedError("No pude tocar «Publicar» en TikTok.")
        paso = "confirmar la publicación"; fin = time.time() + 150
        while time.time() < fin:
            chk(); time.sleep(2); b = _body(tab)
            _clic(tab, r"^(publicar ahora|post now|publish now)$")
            if re.search(r"se ha subido|video (publicado|subido)|your video (has been )?(uploaded|published)|manage your posts|administrar publicaciones|upload another|subir otro", b) or "/tiktokstudio/content" in tab.url(): return "ok"
        return "enviado"
    except Exception as e:
        _diag(tab, "TikTok", paso, e)
        raise
    finally:
        try: tab.ventana("minimized")                      # terminó: Chrome minimizado y se sigue con el próximo video
        except Exception: pass
        try: tab.cerrar()
        except Exception: pass


# ------------------------------------------------------------------ todo junto
NOMBRES = {"fb": "Facebook", "tt": "TikTok"}


def publicar_extras(it, titulo, desc, chk=lambda: None, log=print, guardar=lambda: None):
    """Publica `it['file']` en los destinos elegidos que falten. Deja el resultado en it['extras'] = {fb: {ok, msg, t}}. Nunca lanza error."""
    dest = leer_destinos()
    ex = it.setdefault("extras", {})
    ruta = it.get("file")
    if not ruta or not pathlib.Path(ruta).exists(): return ex
    for k in ("fb", "tt"):
        if not dest.get(k) or (ex.get(k) or {}).get("ok"): continue                  # ya publicado: no se duplica
        it["stage"] = f"Publicando en {NOMBRES[k]}…"; guardar()
        print(f"  Publicando en {NOMBRES[k]}…")
        try:
            r = facebook(ruta, texto_publicacion(titulo, desc, 2000), dest["fb_page"], chk, log) if k == "fb" else tiktok(ruta, texto_publicacion(titulo, desc, 2000), chk, log)
            ex[k] = {"ok": True, "msg": "Publicado" if r == "ok" else "Enviado (la página no mostró confirmación: revisalo)", "t": time.time()}
            print(f"  {NOMBRES[k]}: {ex[k]['msg']}")
        except Exception as e:
            if type(e).__name__ == "Cancelled": raise
            ex[k] = {"ok": False, "msg": str(e)[:200], "t": time.time()}
            print(f"  {NOMBRES[k]}: NO se pudo publicar → {e}")
        guardar()
    return ex
