"""Yutu Worker en segundo plano: servidor local + icono en la bandeja del sistema (junto al wifi/bateria)."""
import os, sys, socket, threading, time, webbrowser, pathlib
ROOT = pathlib.Path(__file__).parent
os.chdir(ROOT)
URL = "https://automate9595-hub.github.io/yutuauto/"

if sys.stdout is None or sys.executable.lower().endswith("pythonw.exe"):   # sin consola: todo al archivo
    _f = open(ROOT / "worker.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _f
else:
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

def busy():
    s = socket.socket(); s.settimeout(1)
    try: return s.connect_ex(("127.0.0.1", 8765)) == 0
    finally: s.close()

if busy():                       # ya esta corriendo: solo abre el panel
    webbrowser.open(URL); sys.exit(0)

import servidor
threading.Thread(target=servidor.serve, daemon=True).start()
print(time.strftime("%Y-%m-%d %H:%M:%S"), "Worker iniciado")
webbrowser.open(URL)

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception as e:
    print("Sin icono de bandeja (", e, "): el worker sigue activo en segundo plano.")
    while True: time.sleep(3600)

def icono(color):
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 2, 62, 62), 16, fill=color)
    d.line((18, 16, 32, 36), fill="white", width=8); d.line((46, 16, 32, 36), fill="white", width=8); d.line((32, 36, 32, 52), fill="white", width=8)
    return im

VERDE, AZUL = (47, 191, 143, 255), (68, 104, 255, 255)
def abrir_panel(*_): webbrowser.open(URL)
def abrir_log(*_):
    try: os.startfile(str(ROOT / "worker.log"))
    except Exception: pass
def abrir_media(*_):
    try: os.startfile(str(ROOT / "media"))
    except Exception: pass
def salir(icon, *_):
    servidor.stop_all(); icon.stop(); os._exit(0)

icon = pystray.Icon("yutu", icono(VERDE), "Yutu Worker - activo", pystray.Menu(
    pystray.MenuItem("Abrir panel", abrir_panel, default=True),
    pystray.MenuItem("Ver registro", abrir_log),
    pystray.MenuItem("Abrir carpeta de videos", abrir_media),
    pystray.MenuItem("Salir del worker", salir)))

def notificar(titulo, msg):
    try: icon.notify(msg, titulo)
    except Exception: pass
servidor.NOTIFY = notificar

def vigilar():
    ultimo = None
    while True:
        st = servidor.state
        ahora = "run" if st["running"] else "idle"
        if ahora != ultimo:
            icon.icon = icono(AZUL if st["running"] else VERDE); ultimo = ahora
        icon.title = "Yutu Worker - " + ("procesando videos..." if st["running"] else "activo") + (" | canal conectado" if st["youtube"] else "")
        time.sleep(2)
def listo(ic):
    ic.visible = True
    threading.Thread(target=vigilar, daemon=True).start()
    notificar("Yutu Worker", "Activo en segundo plano.")
icon.run(setup=listo)
