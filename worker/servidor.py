"""Servidor local: conecta la web con el worker (solo 127.0.0.1)."""
import ia, json, os, pathlib, socket, subprocess, sys, threading, time, urllib.request
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
def queue_items():
    global _LAST_ITEMS
    try:
        d = json.loads((ROOT / "queue.json").read_text("utf-8"))
        _LAST_ITEMS = [dict({k: i.get(k) for k in ("id", "key", "type", "kind", "title", "status", "publishAt", "error", "url", "pct", "stage", "est", "ia", "ia_title", "yt_url")},
                            hasfile=bool(i.get("id") and (MEDIA / f"{i['id']}_final.mp4").exists())) for i in d.get("items", [])]
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
    items = [old[i["key"]] if i.get("key") in old and old[i["key"]].get("status") in keep else i for i in data["items"]]
    write_queue({"config": data.get("config", {}), "items": items})

def run_job(extra):
    global PROC
    state["running"] = True; log("== Comenzando proceso ==")
    try:
        PROC = subprocess.Popen([py_exe(), "-u", "yutu.py"] + extra, cwd=ROOT, env=ENV,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                creationflags=NOWIN)
        for line in PROC.stdout: log(line)
        PROC.wait()
    except Exception as e:
        log(f"ERROR: {e}")
    state["running"] = False; log("== Proceso terminado ==")
    try: (ROOT / "cancel.json").unlink()
    except Exception: pass
    try: NOTIFY("Yutu Worker", "Proceso terminado. Revisa el panel.")
    except Exception: pass

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
        m = _re.fullmatch(r"/media/([\w-]{11})_final\.mp4", self.path.split("?")[0])
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
        self._send({"ok": True, **state, "log": LOG[-40:], "items": queue_items(), "ia": ia.estado()})
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
        if self.path == "/cancel":
            request_cancel(data.get("key"), bool(data.get("all")))
            return self._send({"ok": True, "message": "Cancelando..." if state["running"] else "Cancelado."})
        if self.path == "/upload":
            if state["running"]: return self._send({"ok": False, "message": "Ya hay un proceso en marcha. Esperá a que termine o cancelalo."})
            d = read_queue(); key = data.get("key") or "ALL"
            ready = [i for i in (d or {}).get("items", []) if i.get("status") == "ready" and (key == "ALL" or i.get("key") == key)]
            if not ready: return self._send({"ok": False, "message": "No hay videos editados listos para subir."})
            if data.get("config"): d["config"] = data["config"]; write_queue(d)
            if not launch_chrome(): return self._send({"ok": False, "message": "No pude abrir Chrome/Edge para subir."})
            try: (ROOT / "cancel.json").unlink()
            except Exception: pass
            mode = "now" if data.get("mode") == "now" else "schedule"
            threading.Thread(target=run_job, args=(["--subir", key, "--modo", mode],), daemon=True).start()
            return self._send({"ok": True, "message": f"Subiendo {len(ready)} video(s) " + ("ahora." if mode == "now" else "con programación.")})
        self._send({"ok": False}, 404)

def serve():
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()

if __name__ == "__main__":
    print("Worker listo en http://127.0.0.1:8765 - vuelve a la web y usa los botones.")
    print("No cierres esta ventana.")
    serve()
