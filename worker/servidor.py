"""Servidor local: conecta la web con el worker (solo 127.0.0.1)."""
import json, os, pathlib, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).parent
ALLOWED = {"https://automate9595-hub.github.io", "http://localhost", "http://127.0.0.1"}
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_PROGRESS_BARS="1")
state = {"youtube": False, "running": False, "watching": False}
LOG = []

def log(s):
    LOG.append(str(s).rstrip()[:300]); del LOG[:-200]

def chrome_path():
    pf, pf86, la = (os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"))
    for p in (pf + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Google\Chrome\Application\chrome.exe",
              la + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Microsoft\Edge\Application\msedge.exe",
              pf + r"\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(p): return p

def port_open():
    with socket.socket() as s:
        s.settimeout(1); return s.connect_ex(("127.0.0.1", 9222)) == 0

def launch_chrome():
    if port_open(): return True
    p = chrome_path()
    if not p: return False
    subprocess.Popen([p, "--remote-debugging-port=9222", f"--user-data-dir={ROOT / 'chrome-perfil'}", "https://studio.youtube.com"])
    for _ in range(20):
        if port_open(): return True
        time.sleep(0.5)
    return False

def check_login():
    try:
        r = subprocess.run([sys.executable, "yutu.py", "--estado"], cwd=ROOT, capture_output=True, text=True, timeout=90, env=ENV)
        return "LOGIN_OK" in r.stdout
    except Exception:
        return False

def watch():
    state["watching"] = True; end = time.time() + 600
    while time.time() < end and not state["youtube"]:
        time.sleep(6); state["youtube"] = check_login()
    state["watching"] = False
    if state["youtube"]: log("Canal de YouTube conectado.")

def merge_queue(data):
    qf = ROOT / "queue.json"; old = {}
    if qf.exists():
        try: old = {i["key"]: i for i in json.loads(qf.read_text("utf-8")).get("items", [])}
        except Exception: pass
    items = [old[i["key"]] if i.get("key") in old and old[i["key"]].get("status") in ("ready", "scheduled") else i for i in data["items"]]
    qf.write_text(json.dumps({"config": data.get("config", {}), "items": items}, indent=2, ensure_ascii=False), "utf-8")

def run_job(no_upload):
    state["running"] = True; log("== Comenzando proceso ==")
    try:
        proc = subprocess.Popen([sys.executable, "-u", "yutu.py"] + (["--sin-subir"] if no_upload else []), cwd=ROOT, env=ENV,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout: log(line)
        proc.wait()
    except Exception as e:
        log(f"ERROR: {e}")
    state["running"] = False; log("== Proceso terminado ==")

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
    def do_GET(self):
        if self._bad_origin(): return self._send({"ok": False}, 403)
        self._send({"ok": True, **state, "log": LOG[-40:]})
    def do_POST(self):
        if self._bad_origin(): return self._send({"ok": False}, 403)
        n = int(self.headers.get("Content-Length") or 0); data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/connect":
            if not launch_chrome(): return self._send({"ok": False, "message": "No encontre Chrome ni Edge."})
            if not state["watching"]: threading.Thread(target=watch, daemon=True).start()
            return self._send({"ok": True, "message": "Inicia sesion en YouTube en el Chrome que se abrio."})
        if self.path == "/start":
            if state["running"]: return self._send({"ok": False, "message": "Ya hay un proceso en marcha."})
            if not data.get("items"): return self._send({"ok": False, "message": "La cola esta vacia."})
            merge_queue(data)
            no_up = not launch_chrome()
            if no_up: log("Sin Chrome/Edge: solo preparo los videos.")
            elif not state["youtube"]: log("Aun no hay sesion de YouTube: inicia sesion en el Chrome abierto (espero hasta 5 min).")
            threading.Thread(target=run_job, args=(no_up,), daemon=True).start()
            return self._send({"ok": True, "message": "Proceso iniciado."})
        self._send({"ok": False}, 404)

if __name__ == "__main__":
    print("Worker listo en http://127.0.0.1:8765 - vuelve a la web y usa los botones.")
    print("No cierres esta ventana.")
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
