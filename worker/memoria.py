"""Cuida la RAM (pensado para PCs de 2 GB): libera lo que no se usa mientras el worker trabaja."""
import ctypes, gc, os, time

class _MS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

def _estado():
    """(total_mb, libre_mb) o (None, None)."""
    try:
        if os.name == "nt":
            m = _MS(); m.dwLength = ctypes.sizeof(_MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys / 1048576), int(m.ullAvailPhys / 1048576)
        t = l = None
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemTotal"): t = int(ln.split()[1]) // 1024
            elif ln.startswith("MemAvailable"): l = int(ln.split()[1]) // 1024
        return t, l
    except Exception: return None, None

def total_mb(): return _estado()[0]
def libre_mb(): return _estado()[1]

def poca_ram(): 
    t = total_mb(); return bool(t and t <= 3072)

def recortar():
    """Windows: devuelve al sistema la RAM que este proceso ya no usa."""
    if os.name != "nt": return
    try:
        k = ctypes.windll.kernel32; k.SetProcessWorkingSetSize(k.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception: pass

def liberar(modelos=True):
    """Descarga los modelos de voz (cientos de MB), recoge la basura de Python y recorta la RAM del proceso."""
    if modelos:
        try:
            import voz; voz.descargar()
        except Exception: pass
    gc.collect(); recortar()

def esperar(minimo_mb=300, tope_s=40, log=print):
    """Antes de un paso pesado (FFmpeg): si queda muy poca RAM libre, libera y espera un poco a que se desocupe."""
    l = libre_mb()
    if l is None or l >= minimo_mb: return
    liberar(); t0 = time.time()
    while time.time() - t0 < tope_s:
        l = libre_mb()
        if l is None or l >= minimo_mb: break
        time.sleep(2)
    log(f"  (RAM libre: {libre_mb()} MB)")
