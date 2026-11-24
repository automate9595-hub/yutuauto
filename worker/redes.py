"""Publicar el mismo video (con el mismo título y descripción) también en Facebook (Página, como Reel) y en TikTok.
Se hace como una persona: en el Chrome del worker, en una pestaña aparte que se cierra al terminar, con la sesión que ya iniciaste ahí.
- Facebook: facebook.com -> «Foto/vídeo» -> subir el mismo archivo -> título y descripción -> «Publicar».
- TikTok: TikTok Studio (tiktok.com/tiktokstudio/upload).
Si algo falla NO se toca la publicación de YouTube: queda el motivo en el video y diagnostico-redes.txt/.png en la carpeta del worker.
"""
import json, pathlib, re, time

import cdp

ROOT = pathlib.Path(__file__).parent
DEST = ROOT / "destinos.json"
DIAG_TXT, DIAG_PNG = ROOT / "diagnostico-redes.txt", ROOT / "diagnostico-redes.png"


class RedError(Exception): pass


# ------------------------------------------------------------------ dónde publicar
def leer_destinos():
    try: d = json.loads(DEST.read_text("utf-8"))
    except Exception: d = {}
    return {"fb": bool(d.get("fb")), "tt": bool(d.get("tt")), "fb_page": str(d.get("fb_page") or "").strip()[:200]}


def guardar_destinos(d):
    cur = {"fb": bool(d.get("fb")), "tt": bool(d.get("tt")), "fb_page": str(d.get("fb_page") or "").strip()[:200]}
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


def _dialogo_fb(tab): return tab.visible("div[role=dialog]")


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
        paso = "tocar «Foto/vídeo»"; fin = time.time() + 40; abierto = False
        while time.time() < fin and not abierto:
            chk()
            if _dialogo_fb(tab): abierto = True; break
            _clic(tab, r"^(foto/v[ií]deo|photo/video)$", habilitado=False)
            time.sleep(3)
            abierto = _dialogo_fb(tab)
        if not abierto: raise RedError("No pude abrir «Foto/vídeo» en facebook.com (cambió la pantalla o no hay cuadro para publicar).")
        time.sleep(1.5)
        paso = "subir el archivo"; ok = False; fin = time.time() + 60
        while time.time() < fin and not ok:
            chk()
            if tab.existe("div[role=dialog] input[type=file]"): tab.archivos("div[role=dialog] input[type=file]", [str(ruta)]); ok = True; break
            ok = _subir_archivo(tab, ruta, r"a[ñn]adir fotos?/v[ií]deos?|agregar fotos?/v[ií]deos?|add photos?/videos?|foto/v[ií]deo")
            if not ok: time.sleep(2)
        if not ok: raise RedError("No encontré dónde subir el video en el cuadro de Facebook.")
        paso = "escribir el título y la descripción y publicar"; escrito = False; click_pub = False; fin = time.time() + 20 * 60
        while time.time() < fin:
            chk(); time.sleep(2)
            _clic(tab, r"^(aceptar|entendido|got it|ok)$")                                   # aviso 'los videos se comparten como reels'
            if not escrito and tab.visible("div[role=dialog] div[role=textbox][contenteditable=true]"):
                tab.escribir("div[role=dialog] div[role=textbox][contenteditable=true]", texto, 0); escrito = True; time.sleep(1.5); continue
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
        print(f"  Publicando también en {NOMBRES[k]}…")
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
