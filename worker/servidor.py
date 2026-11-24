"""Servidor local: conecta la web con el worker (solo 127.0.0.1)."""
import ia, piloto, generador, tiktok, json, os, pathlib, socket, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).parent
MEDIA = ROOT / "media"
ALLOWED = {"https://automate9595-hub.github.io", "http://localhost", "http://127.0.0.1"}
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_PROGRESS_BARS="1")
state = {"youtube": False, "running": False, "detail": ""}
LOG = []
PROC = None
NOTIFY = lambda title, msg: None      # la bandeja lo reemplaza para mostrar avisos
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def log(s):
    LOG.append(str(s).rstrip()[:300]); del LOG[:-200]
    try: print(str(s).rstrip()[:300], flush=True)
    except Exception: pass

def py_exe():
    """python.exe (no pythonw) para que los procesos hijos tengan stdout."""
    p = pathlib.Path(sys.executable)
    q = p.with_name("python.exe")
    return str(q) if p.name.lower() == "pythonw.exe" and q.exists() else sys.executable

def stop_all():
    try:
        if PROC and PROC.poll() is None: PROC.terminate()
        RUNF.unlink(missing_ok=True)                         # salida voluntaria: no se retoma sola
    except Exception: pass

def chrome_path():
    pf, pf86, la = (os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"))
    for p in (pf + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Google\Chrome\Application\chrome.exe",
              la + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Microsoft\Edge\Application\msedge.exe",
              pf + r"\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(p): return p

def tabs():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2) as r: return json.loads(r.read())
    except Exception:
        return None

def port_open(): return tabs() is not None

def open_tab(url):
    try: urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:9222/json/new?" + url, method="PUT"), timeout=3).read()
    except Exception: pass

def launch_chrome():
    if port_open():
        open_tab("https://studio.youtube.com"); return True
    p = chrome_path()
    if not p: return False
    subprocess.Popen([p, "--remote-debugging-port=9222", f"--user-data-dir={ROOT / 'chrome-perfil'}", "--no-first-run",
                      "--no-default-browser-check", "https://studio.youtube.com"])
    for _ in range(30):
        if port_open(): return True
        time.sleep(0.5)
    return False

def refresh_login():
    t = tabs()
    if t is None:
        state["youtube"] = False; state["detail"] = "El Chrome del worker no esta abierto. Toca 'Conectar con mi canal'."; return
    pages = [x for x in t if x.get("type") == "page"]
    for x in pages:
        u, title = x.get("url", ""), x.get("title", "")
        if u.startswith("https://studio.youtube.com/") and ("/channel/" in u or "Studio" in title):
            state["youtube"] = True; state["detail"] = "Sesion de YouTube Studio detectada."; return
    if not state["youtube"]:
        hosts = ", ".join(sorted({x.get("url", "").split("/")[2] for x in pages if x.get("url", "").count("/") >= 2})) or "ninguna"
        state["detail"] = "Chrome abierto, pero no veo YouTube Studio con tu canal. Pestanas: " + hosts

_LAST_ITEMS = []
def _fid(i): return i.get("id", "") + (f"_p{i['part']}" if (i.get("parts") or 1) > 1 else "")
def queue_items():
    global _LAST_ITEMS
    try:
        d = json.loads((ROOT / "queue.json").read_text("utf-8"))
        _LAST_ITEMS = [dict({k: i.get(k) for k in ("id", "key", "type", "kind", "title", "status", "publishAt", "error", "url", "pct", "stage", "est", "ia", "ia_title", "yt_url", "aviso", "part", "parts", "reanudar", "reintentos", "final_title", "origen")},
                            fid=_fid(i), hasfile=bool(i.get("id") and (MEDIA / f"{_fid(i)}_final.mp4").exists())) for i in d.get("items", [])]
    except Exception:
        pass
    return _LAST_ITEMS

def write_queue(d):
    qf = ROOT / "queue.json"; tmp = qf.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), "utf-8"); os.replace(tmp, qf)

def read_queue():
    try: return json.loads((ROOT / "queue.json").read_text("utf-8"))
    except Exception: return None

def request_cancel(key=None, all_=False):
    """Pide cancelar. Si hay proceso en marcha lo ve el worker; si no, se marca directamente."""
    cf = ROOT / "cancel.json"
    try: c = json.loads(cf.read_text("utf-8"))
    except Exception: c = {}
    if all_: c["all"] = True
    elif key and key not in c.setdefault("keys", []): c["keys"].append(key)
    cf.write_text(json.dumps(c), "utf-8")
    if not state["running"]:
        d = read_queue()
        if d:
            for i in d.get("items", []):
                if i.get("status") in ("pending", "processing", "uploading") and (all_ or i.get("key") == key):
                    i["status"] = "cancelled"; i["stage"] = "Cancelado"
            write_queue(d)
        try: cf.unlink()
        except Exception: pass

def merge_queue(data, reedit=False):
    qf = ROOT / "queue.json"; old = {}
    if qf.exists():
        try: old = {i["key"]: i for i in json.loads(qf.read_text("utf-8")).get("items", [])}
        except Exception: pass
    keep = ("scheduled", "published") if reedit else ("ready", "scheduled", "published")
    items = []
    for i in data["items"]:
        partes = [old[k] for k in old if k.startswith(i.get("key", "\0") + "#")]        # Shorts sacados del mismo video largo
        if partes and any(p.get("status") in keep for p in partes):
            for p in sorted(partes, key=lambda x: x.get("part", 0)):
                if p.get("status") in keep: items.append(p)
                else:                                                                       # esa parte se vuelve a procesar desde cero
                    items.append(dict({k: p[k] for k in ("type", "id", "key", "kind", "url", "part", "parts", "split_start", "split_base") if k in p}, status="pending"))
        else:
            o = old.get(i.get("key"))
            if o and o.get("status") == "cancelled" and not i.get("nuevo"): items.append(o)              # lo cancelado NO se vuelve a cargar solo
            else:
                if o and o.get("status") in keep: items.append(o)
                else: items.append({k: v for k, v in i.items() if k != "nuevo"})
    web = {str(i.get("key", "")).split("#")[0] for i in data["items"]}
    for k, o in old.items():                                  # lo que ya estaba en la cola del worker (pilotos, ya publicados) no se pierde
        if k.split("#")[0] not in web and (o.get("status") in ("ready", "scheduled", "published") or (o.get("auto") and o.get("status") in ("pending", "processing"))):
            items.append(o)
    write_queue({"config": data.get("config", {}), "items": items})

RUNF = ROOT / "running.json"; JOBLOG = ROOT / "job.log"; CRASHF = ROOT / "crash.json"
BAJA = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)        # el trabajo pesado va con menos prioridad: el panel siempre responde

def job_vivo():
    """True si el proceso de edición está vivo (latido reciente), aunque este servidor se haya reiniciado."""
    try: return time.time() - json.loads(RUNF.read_text("utf-8")).get("t", 0) < 25
    except Exception: return False

def _seguir(pos, proc=None):
    """Lee job.log mientras el proceso viva. El proceso escribe a un ARCHIVO (no a una tubería), así sobrevive a un reinicio del worker."""
    t_fin = None
    while True:
        try:
            with open(JOBLOG, "r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                for line in f: log(line)
                pos = f.tell()
        except Exception: pass
        vivo = (proc.poll() is None) if proc is not None else job_vivo()
        if not vivo:
            t_fin = t_fin or time.time()
            if time.time() - t_fin > 1.5: break
        time.sleep(0.6)

def _fin_job():
    state["running"] = False; log("== Proceso terminado ==")
    try: (ROOT / "cancel.json").unlink()
    except Exception: pass
    try: NOTIFY("Yutu Worker", "Proceso terminado. Revisa el panel.")
    except Exception: pass

def run_job(extra):
    global PROC
    state["running"] = True; log("== Comenzando proceso ==")
    try:
        if JOBLOG.exists() and JOBLOG.stat().st_size > 5_000_000: JOBLOG.unlink()
        pos = JOBLOG.stat().st_size if JOBLOG.exists() else 0
        fh = open(JOBLOG, "a", encoding="utf-8", buffering=1)
        PROC = subprocess.Popen([py_exe(), "-u", "yutu.py"] + extra, cwd=ROOT, env=ENV, stdout=fh, stderr=subprocess.STDOUT,
                                creationflags=NOWIN | BAJA)
        _seguir(pos, PROC)
        fh.close()
    except Exception as e:
        log(f"ERROR: {e}")
    _fin_job()

def _crashes_recientes():
    try: c = [t for t in json.loads(CRASHF.read_text("utf-8")) if time.time() - t < 900]
    except Exception: c = []
    return c

def recuperar():
    """Al arrancar el worker: si había un proceso a medias, lo retoma (o lo sigue mirando si sigue vivo) y arregla los videos que quedaron colgados."""
    try: info = json.loads(RUNF.read_text("utf-8"))
    except Exception: return
    if job_vivo():
        state["running"] = True; log("Había un proceso en marcha: lo sigo mirando.")
        pos = JOBLOG.stat().st_size if JOBLOG.exists() else 0
        threading.Thread(target=lambda: (_seguir(pos), _fin_job()), daemon=True).start(); return
    c = _crashes_recientes()
    d = read_queue()
    if d:                                                       # nada queda "procesando" para siempre
        for i in d.get("items", []):
            if i.get("status") == "processing": i["status"] = "pending"
            elif i.get("status") == "uploading" and i.get("file"): i["status"] = "ready"; i["reanudar"] = True; i["reanudar_en"] = 0
        write_queue(d)
    try: RUNF.unlink()
    except Exception: pass
    if len(c) >= 3: log("El proceso se cortó 3 veces en 15 min: no lo relanzo solo. Revisá job.log."); return
    c.append(time.time()); CRASHF.write_text(json.dumps(c), "utf-8")
    args = info.get("args") or ["--modo", "now"]
    log("El proceso se había cortado: lo retomo solo donde quedó.")
    threading.Thread(target=run_job, args=(args,), daemon=True).start()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode(); self.send_response(code)
        o = self.headers.get("Origin", "")
        if o in ALLOWED: self.send_header("Access-Control-Allow-Origin", o)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS"); self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin"); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self._send({})
    def _bad_origin(self):
        o = self.headers.get("Origin", ""); return bool(o) and o not in ALLOWED
    def _media(self):
        import re as _re
        m = _re.fullmatch(r"/media/([\w-]{11}(?:_p\d{1,2})?)_final\.mp4", self.path.split("?")[0])
        ref = self.headers.get("Referer", "")
        if not m or (ref and not any(ref.startswith(o) for o in ALLOWED)): return self._send({"ok": False}, 404)
        f = MEDIA / f"{m.group(1)}_final.mp4"
        if not f.exists(): return self._send({"ok": False}, 404)
        size = f.stat().st_size; a, b = 0, size - 1
        rg = _re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rg:
            if rg.group(1): a = int(rg.group(1))
            if rg.group(2): b = min(int(rg.group(2)), size - 1)
            if not rg.group(1) and rg.group(2): a, b = max(size - int(rg.group(2)), 0), size - 1
        self.send_response(206 if rg else 200)
        self.send_header("Content-Type", "video/mp4"); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        if rg: self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.end_headers()
        try:
            with open(f, "rb") as fh:
                fh.seek(a); left = b - a + 1
                while left > 0:
                    chunk = fh.read(min(65536, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
        except Exception: pass
    def _diag_png(self):
        f = ROOT / "error-subida.png"; ref = self.headers.get("Referer", "")
        if not f.exists() or (ref and not any(ref.startswith(o) for o in ALLOWED)): return self._send({"ok": False}, 404)
        b = f.read_bytes(); self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/media/"): return self._media()
        if self.path.startswith("/diag.png"): return self._diag_png()
        if self._bad_origin(): return self._send({"ok": False}, 403)
        if self.path.startswith("/diagnostico"):
            partes = []
            for n in ("diagnostico-subida.txt", "diagnostico-ninos.txt"):
                f = ROOT / n
                if f.exists(): partes.append(f"===== {n} =====\n" + f.read_text("utf-8", "replace"))
            return self._send({"ok": bool(partes), "carpeta": str(ROOT), "png": (ROOT / "error-subida.png").exists(),
                               "text": "\n\n".join(partes) or "Todavía no hay diagnóstico guardado (no hubo errores de subida)."})
        refresh_login()
        self._send({"ok": True, **state, "log": LOG[-40:], "items": queue_items(), "ia": ia.estado(), "piloto": {k: v for k, v in piloto.leer().items() if k not in ("usados", "config")},
                               "tiktok": {k: v for k, v in piloto.leer_tt().items() if k not in ("usados", "rechazados", "lista")},
                               "tema_tt": {k: v for k, v in piloto.leer_tm().items() if k not in ("usados", "rechazados", "cache", "muertas", "hist")},
                               "piloto_ia": {k: v for k, v in generador.leer().items() if k not in ("ideas", "hist")},
                               "piloto_yts": {k: v for k, v in piloto.leer_ys().items() if k not in ("usados", "hist")}})
    def do_POST(self):
        if self._bad_origin(): return self._send({"ok": False}, 403)
        n = int(self.headers.get("Content-Length") or 0); data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/connect":
            if not launch_chrome(): return self._send({"ok": False, "message": "No encontre Chrome ni Edge."})
            return self._send({"ok": True, "message": "Inicia sesion en YouTube en la pestana de Studio que se abrio."})
        if self.path == "/forzar":
            state["youtube"] = True; state["detail"] = "Marcado como conectado manualmente."
            return self._send({"ok": True, "message": "Marcado como conectado."})
        if self.path == "/start":
            if state["running"]: return self._send({"ok": False, "message": "Ya hay un proceso en marcha."})
            if not data.get("items"): return self._send({"ok": False, "message": "La cola esta vacia."})
            try: (ROOT / "cancel.json").unlink()
            except Exception: pass
            merge_queue(data, bool(data.get("reedit")))
            want_up = bool(data.get("upload"))
            no_up = (not want_up) or (not launch_chrome())
            if want_up and no_up: log("Sin Chrome/Edge: solo preparo los videos.")
            extra = ["--sin-subir"] if no_up else (["--modo", "now" if data.get("mode") != "schedule" else "schedule"])
            threading.Thread(target=run_job, args=(extra,), daemon=True).start()
            return self._send({"ok": True, "message": "Editando y subiendo..." if not no_up else "Editando (sin subir)..."})
        if self.path == "/ia":                       # guarda las claves SOLO en esta PC (claves-ia.json)
            try: ia.set_claves(data)
            except Exception as e: return self._send({"ok": False, "message": str(e)})
            return self._send({"ok": True, "message": "Guardado en tu PC.", "ia": ia.estado()})
        if self.path == "/ia-test":
            ok, msg = ia.probar(data.get("proveedor", ""))
            return self._send({"ok": ok, "message": msg})
        if self.path == "/tiktok-login":             # sesión de TikTok en el Chrome del worker (mejora lectura de cuentas, búsquedas y descargas)
            if data.get("accion") == "abrir":
                if not launch_chrome(): return self._send({"ok": False, "message": "No encontré Chrome ni Edge."})
                open_tab("https://www.tiktok.com/login")
                return self._send({"ok": True, "message": "Abrí TikTok en la ventana de Chrome del worker. Iniciá sesión ahí y después tocá «Ya inicié sesión»."})
            if not port_open(): return self._send({"ok": False, "message": "El Chrome del worker no está abierto. Tocá primero «Iniciar sesión en TikTok»."})
            ok = tiktok.sesion_iniciada()
            return self._send({"ok": ok, "login": ok, "message": "Sesión de TikTok detectada y guardada ✓" if ok else "Todavía no veo la sesión de TikTok. Iniciá sesión en la ventana de Chrome y probá de nuevo."})
        if self.path == "/piloto":                   # piloto automático: tema + cupo diario + días
            try:
                p = piloto.configurar(data)
                if data.get("config"): p["config"] = data["config"]; piloto.guardar(p)
            except Exception as e: return self._send({"ok": False, "message": "Datos inválidos: " + str(e)})
            log("Piloto automático " + ("ACTIVADO" if p["activo"] else "pausado") + f": «{p['tema']}» · {p['shorts']} Shorts + {p['videos']} Videos al día · {p['dias']} días")
            if p["activo"]: kick()
            return self._send({"ok": True, "message": "Piloto activado." if p["activo"] else "Piloto en pausa.", "piloto": {k: v for k, v in p.items() if k not in ("usados", "config")}})
        if self.path == "/piloto-tiktok":
            try:
                p = piloto.configurar_tt(data)
                if p["activo"] and not p["cuenta"]: p["activo"] = False; piloto.guardar_tt(p); return self._send({"ok": False, "message": "Escribí la cuenta de TikTok."})
                if data.get("config"): p["config"] = data["config"]; piloto.guardar_tt(p)
            except Exception as e: return self._send({"ok": False, "message": "Datos inválidos: " + str(e)})
            log("Piloto TikTok " + ("ACTIVADO" if p["activo"] else "pausado") + f": {p['cuenta']} · {p['por_dia']}/día · {p['orden']} · {p['dias']} días")
            if p["activo"]: kick()
            return self._send({"ok": True, "message": "Piloto TikTok activado." if p["activo"] else "Piloto TikTok en pausa."})
        if self.path == "/piloto-tema-tiktok":
            try:
                p = piloto.configurar_tm(data)
                if p["activo"] and not p["tema"]: p["activo"] = False; piloto.guardar_tm(p); return self._send({"ok": False, "message": "Escribí el tema central."})
                if data.get("config"): p["config"] = data["config"]; piloto.guardar_tm(p)
            except Exception as e: return self._send({"ok": False, "message": "Datos inválidos: " + str(e)})
            log("Piloto TikTok por tema " + ("ACTIVADO" if p["activo"] else "pausado") + f": «{p['tema']}» · {p['shorts']} Shorts + {p['videos']} Videos/día · {p['dias']} días")
            if p["activo"]: kick()
            return self._send({"ok": True, "message": "Piloto activado." if p["activo"] else "Piloto en pausa."})
        if self.path == "/piloto-yts":              # piloto de Shorts de YouTube
            try:
                p = piloto.configurar_ys(data)
                if p["activo"] and not p["tema"]: p["activo"] = False; piloto.guardar_ys(p); return self._send({"ok": False, "message": "Escribí el tema central."})
                if data.get("config"): p["config"] = data["config"]; piloto.guardar_ys(p)
            except Exception as e: return self._send({"ok": False, "message": "Datos inválidos: " + str(e)})
            log("Piloto YouTube Shorts " + ("ACTIVADO" if p["activo"] else "pausado") + f": «{p['tema']}» · {p['por_dia']} por día · cada {p['cada'] or 'auto'} min")
            if p["activo"]: kick()
            return self._send({"ok": True, "message": "Piloto de Shorts activado: busca el primero ahora." if p["activo"] else "Piloto de Shorts en pausa."})
        if self.path == "/piloto-ia":               # piloto creador: IA crea los Shorts desde cero
            try:
                p = generador.configurar(data)
                if p["activo"] and not p["tema"]: p["activo"] = False; generador.guardar(p); return self._send({"ok": False, "message": "Escribí el tema central."})
                if data.get("config"): p["config"] = data["config"]; generador.guardar(p)
            except Exception as e: return self._send({"ok": False, "message": "Datos inválidos: " + str(e)})
            log("Piloto IA creador " + ("ACTIVADO" if p["activo"] else "pausado") + f": «{p['tema']}» · {p['shorts']} Shorts/día · {', '.join(p['idiomas'])} · {p['dias']} días")
            if p["activo"]: kick()
            return self._send({"ok": True, "message": "Piloto creador activado." if p["activo"] else "Piloto creador en pausa."})
        if self.path == "/cancel":
            request_cancel(data.get("key"), bool(data.get("all")))
            return self._send({"ok": True, "message": "Cancelando..." if state["running"] else "Cancelado."})
        if self.path == "/upload":
            if state["running"]: return self._send({"ok": False, "message": "Ya hay un proceso en marcha. Esperá a que termine o cancelalo."})
            d = read_queue(); key = data.get("key") or "ALL"
            ready = [i for i in (d or {}).get("items", []) if i.get("status") == "ready" and (key == "ALL" or i.get("key") == key)]
            if not ready: return self._send({"ok": False, "message": "No hay videos editados listos para subir."})
            if data.get("config"): d["config"] = data["config"]
            for i in ready: i.pop("reintentos", None); i.pop("reanudar_en", None)
            write_queue(d)
            if not launch_chrome(): return self._send({"ok": False, "message": "No pude abrir Chrome/Edge para subir."})
            try: (ROOT / "cancel.json").unlink()
            except Exception: pass
            mode = "now" if data.get("mode") == "now" else "schedule"
            threading.Thread(target=run_job, args=(["--subir", key, "--modo", mode],), daemon=True).start()
            return self._send({"ok": True, "message": f"Subiendo {len(ready)} video(s) " + ("ahora." if mode == "now" else "con programación.")})
        self._send({"ok": False}, 404)

MAX_AUTO = 8
def _piloto_tick():
    """Si algún piloto (búsqueda o TikTok) está activo y toca el siguiente video del día: lo agrega a la cola y lanza todo el proceso."""
    pa, pt, pm, pg, py = piloto.leer(), piloto.leer_tt(), piloto.leer_tm(), generador.leer(), piloto.leer_ys()
    if not (pa.get("activo") or pt.get("activo") or pm.get("activo") or pg.get("activo") or py.get("activo")): return
    if (pt.get("activo") or pm.get("activo")): launch_chrome()          # TikTok se lee con el Chrome del worker
    d = read_queue() or {"config": pa.get("config") or pt.get("config") or pm.get("config") or pg.get("config") or {}, "items": []}
    nuevos = []
    for act, fn, nom in ((pa.get("activo"), piloto.tick, "Piloto"), (pt.get("activo"), piloto.tick_tt, "Piloto TikTok"), (pm.get("activo"), piloto.tick_tm, "Piloto TikTok tema"), (py.get("activo"), piloto.tick_ys, "Piloto YouTube Shorts")):
        if act:
            try: nuevos += fn(d.get("items", []) + nuevos, log)
            except Exception as e: log(f"{nom}: error {str(e)[:100]} (sigo con los demás)")
    if pg.get("activo"):
        try: nuevos += generador.tick(d.get("items", []) + nuevos, log)
        except Exception as e: log("Piloto IA: " + str(e)[:100])
    if not nuevos: return
    d.setdefault("config", pa.get("config") or pt.get("config") or pm.get("config") or pg.get("config") or {}); d["config"]["publish"] = "now"
    d["items"] = d.get("items", []) + nuevos; write_queue(d)
    if not launch_chrome(): log("Piloto: no pude abrir Chrome; lo dejo en la cola."); return
    try: (ROOT / "cancel.json").unlink()
    except Exception: pass
    threading.Thread(target=run_job, args=(["--modo", "now"],), daemon=True).start()

_KL = threading.Lock()
def kick():
    """Al activar un piloto: busca el primer video YA, sin esperar el siguiente minuto del vigilante."""
    def _t():
        if state["running"] or not _KL.acquire(False): return
        try: _piloto_tick()
        except Exception as e: log(f"Piloto: {str(e)[:100]}")
        finally: _KL.release()
    threading.Thread(target=_t, daemon=True).start()

def vigilante():
    """Cada minuto: si una subida quedó cortada (marcada 'reanudar') y no hay nada en marcha, la retoma sola, sin que toques nada."""
    while True:
        time.sleep(60)
        try:
            if not state["running"]: _piloto_tick()
            d = read_queue()
            if not d or state["running"] or not d.get("config", {}).get("auto_reanudar", True): continue
            ahora = time.time()
            pend = [i for i in d.get("items", []) if i.get("reanudar") and i.get("status") == "ready"
                    and i.get("reintentos", 0) <= MAX_AUTO and ahora >= i.get("reanudar_en", 0) and i.get("id") and (MEDIA / f"{_fid(i)}_final.mp4").exists()]
            if not pend: continue
            if not launch_chrome(): log("Vigilante: no pude abrir Chrome para reanudar; lo intento de nuevo en un rato."); continue
            try: (ROOT / "cancel.json").unlink()
            except Exception: pass
            log(f"Vigilante: reanudando {len(pend)} subida(s) cortada(s) automáticamente.")
            threading.Thread(target=run_job, args=(["--reanudar"],), daemon=True).start()
        except Exception as e: log(f"Vigilante: {e}")

def serve():
    """Servidor a prueba de caidas: si algo lo tumba, se levanta de nuevo solo (y el vigilante igual)."""
    try: recuperar()
    except Exception as e: log(f"recuperar: {e}")
    def vig():
        while True:
            try: vigilante()
            except Exception as e: log(f"Vigilante reiniciado ({str(e)[:80]})"); time.sleep(5)
    threading.Thread(target=vig, daemon=True).start()
    while True:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", 8765), H); srv.daemon_threads = True; srv.serve_forever()
        except Exception as e:
            log(f"Servidor reiniciado ({str(e)[:80]})"); time.sleep(2)

if __name__ == "__main__":
    print("Worker listo en http://127.0.0.1:8765 - vuelve a la web y usa los botones.")
    print("No cierres esta ventana.")
    serve()
