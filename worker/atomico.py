"""Guardado de archivos a prueba de Windows.

[WinError 32] 'El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso' aparece cuando el
servidor, el antivirus o el navegador tienen abierto queue.json justo en el instante de reemplazarlo. Acá se reintenta
unos segundos con espera creciente, y cada proceso/hilo escribe en su PROPIO archivo temporal (antes todos usaban queue.tmp y se pisaban).
"""
import os, pathlib, threading, time

def reemplazar(tmp, destino, intentos=40):
    ult = None
    for i in range(intentos):
        try: os.replace(tmp, destino); return
        except PermissionError as e: ult = e                                   # Windows: archivo abierto por otro proceso
        except OSError as e:
            if getattr(e, "winerror", None) not in (5, 32, 33): raise
            ult = e
        time.sleep(min(0.05 * (i + 1), 0.5))
    try:                                                                        # último recurso: escribir directo (no atómico, pero no se pierde el guardado)
        pathlib.Path(destino).write_bytes(pathlib.Path(tmp).read_bytes())
    except Exception:
        raise ult
    finally:
        try: os.unlink(tmp)
        except Exception: pass

def escribir(destino, texto):
    destino = pathlib.Path(destino)
    tmp = destino.with_name(f"{destino.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(texto, "utf-8")
    reemplazar(tmp, destino)
