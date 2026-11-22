"""Control de Chrome por DevTools (CDP) en Python puro: sin Playwright ni Node.js (funciona en Windows 8.1)."""
import base64, json, os, re, socket, struct, time, urllib.parse, urllib.request

class WS:
    def __init__(self, url):
        u = urllib.parse.urlparse(url); host, port = u.hostname, u.port or 80
        self.s = socket.create_connection((host, port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + ("?" + u.query if u.query else "")
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = self.s.recv(4096)
            if not c: raise ConnectionError("Chrome cerró la conexión")
            buf += c
        head, _, self.buf = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]: raise ConnectionError("Chrome rechazó la conexión: " + head[:80].decode("latin1"))

    def send(self, text, op=1):
        p = text.encode() if isinstance(text, str) else text
        n = len(p); mask = os.urandom(4)
        h = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(h + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))

    def _need(self, n, end):
        while len(self.buf) < n:
            self.s.settimeout(max(end - time.time(), 0.05))
            c = self.s.recv(65536)
            if not c: raise ConnectionError("Chrome cerró la conexión")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout):
        end = time.time() + timeout; msg = b""
        while True:
            b1, b2 = self._need(2, end); fin, op, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126: n = struct.unpack(">H", self._need(2, end))[0]
            elif n == 127: n = struct.unpack(">Q", self._need(8, end))[0]
            data = self._need(n, end)
            if op == 8: raise ConnectionError("Chrome cerró la conexión")
            if op == 9: self.send(data, 10); continue
            if op in (1, 2, 0): msg += data
            if fin and op in (0, 1, 2): return msg.decode("utf-8", "replace")

    def close(self):
        try: self.s.close()
        except Exception: pass

HELPERS = ("window.__D=window.__D||function(s,r){r=r||document;var x=r.querySelector(s);if(x)return x;"
           "var a=r.querySelectorAll('*');for(var i=0;i<a.length;i++){if(a[i].shadowRoot){x=window.__D(s,a[i].shadowRoot);if(x)return x}}return null};"
           "window.__A=window.__A||function(s,r,o){r=r||document;o=o||[];r.querySelectorAll(s).forEach(function(e){o.push(e)});"
           "var a=r.querySelectorAll('*');for(var i=0;i<a.length;i++){if(a[i].shadowRoot)window.__A(s,a[i].shadowRoot,o)}return o};")

class Tab:
    def __init__(self, info):
        self.id = info["id"]; self.ws = WS(info["webSocketDebuggerUrl"]); self.n = 0
        self.call("Page.enable"); self.call("Page.bringToFront")

    @staticmethod
    def abrir(url="about:blank", port=9222):
        q = f"http://127.0.0.1:{port}/json/new?" + urllib.parse.quote(url, safe=":/?&=#")
        for m in ("PUT", "GET"):
            try:
                with urllib.request.urlopen(urllib.request.Request(q, method=m), timeout=8) as r: return Tab(json.loads(r.read()))
            except Exception as e: err = e
        raise RuntimeError("No pude abrir una pestaña en Chrome: " + str(err)[:100])

    def call(self, method, params=None, timeout=30):
        self.n += 1; i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0: raise TimeoutError(method + " tardó demasiado")
            msg = json.loads(self.ws.recv(left))
            if msg.get("method") == "Page.javascriptDialogOpening":        # "¿Salir del sitio?": aceptar
                self.n += 1; self.ws.send(json.dumps({"id": self.n, "method": "Page.handleJavaScriptDialog", "params": {"accept": True}}))
            if msg.get("id") == i:
                if "error" in msg: raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def eval(self, js, objeto=False, espera=False):
        r = self.call("Runtime.evaluate", {"expression": HELPERS + js, "returnByValue": not objeto, "awaitPromise": espera})
        if r.get("exceptionDetails"): raise RuntimeError("JS: " + str(r["exceptionDetails"].get("exception", {}).get("description", ""))[:150])
        return r["result"] if objeto else r["result"].get("value")

    def url(self): return self.eval("location.href") or ""

    def ir(self, url, timeout=45):
        self.call("Page.navigate", {"url": url})
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.5)
            try:
                if self.eval("document.readyState") == "complete": return
            except Exception: pass

    def existe(self, sel): return bool(self.eval(f"!!window.__D({json.dumps(sel)})"))
    def cuantos(self, sel): return int(self.eval(f"window.__A({json.dumps(sel)}).length") or 0)

    def esperar(self, sel, timeout=30, chk=None):
        end = time.time() + timeout
        while time.time() < end:
            if chk: chk()
            if self.existe(sel): return True
            time.sleep(0.5)
        return False

    def texto(self, sel):
        return self.eval(f"(function(){{var e=window.__D({json.dumps(sel)});return e?(e.innerText||e.textContent||''):''}})()") or ""

    def _centro(self, sel, idx=0):
        return self.eval(f"(function(){{var e=window.__A({json.dumps(sel)})[{idx}];if(!e)return null;"
                         "e.scrollIntoView({block:'center'});var r=e.getBoundingClientRect();"
                         "return {x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height}}})()")

    def clic(self, sel, idx=0, esperar=0):
        if esperar: self.esperar(sel, esperar)
        c = self._centro(sel, idx)
        if not c: raise RuntimeError("No encuentro en la página: " + sel)
        if c["w"] > 0 and c["h"] > 0:
            for t in ("mousePressed", "mouseReleased"):
                self.call("Input.dispatchMouseEvent", {"type": t, "x": c["x"], "y": c["y"], "button": "left", "clickCount": 1})
        else:
            self.eval(f"window.__A({json.dumps(sel)})[{idx}].click()")

    def clic_texto(self, patron, tags="button, tp-yt-paper-item, ytcp-text-menu-item, *[role=menuitem], *[role=button]"):
        """Clic en el primer elemento visible cuyo texto coincide con la expresión regular."""
        ok = self.eval("(function(){var re=new RegExp(" + json.dumps(patron) + ",'i');var a=window.__A(" + json.dumps(tags) + ");"
                       "for(var i=0;i<a.length;i++){var t=(a[i].innerText||'').trim();var r=a[i].getBoundingClientRect();"
                       "if(t&&t.length<60&&re.test(t)&&r.width>0){a[i].scrollIntoView({block:'center'});r=a[i].getBoundingClientRect();"
                       "return {x:r.left+r.width/2,y:r.top+r.height/2}}}return null})()")
        if not ok: return False
        for t in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {"type": t, "x": ok["x"], "y": ok["y"], "button": "left", "clickCount": 1})
        return True

    def escribir(self, sel, texto, idx=0):
        """Reemplaza el contenido del campo (input o texto editable) y dispara los eventos reales de escritura."""
        self.clic(sel, idx)
        self.eval(f"(function(){{var e=window.__A({json.dumps(sel)})[{idx}];e.focus();"
                  "if(e.select&&e.tagName!=='DIV'){e.select()}else{document.execCommand('selectAll',false,null)}}})()")
        self.call("Input.insertText", {"text": texto})

    def tecla(self, key="Enter", code=13):
        for t in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": t, "key": key, "code": key, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code})

    def archivos(self, sel, rutas, idx=0):
        o = self.eval(f"window.__A({json.dumps(sel)})[{idx}]", objeto=True)
        if not o.get("objectId"): raise RuntimeError("No encuentro el selector de archivos")
        self.call("DOM.setFileInputFiles", {"objectId": o["objectId"], "files": [os.path.abspath(r) for r in rutas]})

    def captura(self, ruta):
        try:
            d = self.call("Page.captureScreenshot", {"format": "png"}, 20)["data"]
            with open(ruta, "wb") as f: f.write(base64.b64decode(d))
        except Exception: pass

    def cerrar(self):
        self.ws.close()
        try: urllib.request.urlopen(f"http://127.0.0.1:9222/json/close/{self.id}", timeout=3).read()
        except Exception: pass
