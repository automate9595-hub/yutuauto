"""Catalogo de efectos de camara/imagen para FFmpeg.

Cada efecto se activa en ventanas de tiempo (duracion, pausa, suavizado) y se reparte entre
los efectos elegidos: en secuencia, solapados, aleatorio o todos juntos.
Todo es una cadena de filtros de tamano fijo (sirve igual para 30 s que para 2 horas).
"""
import random

# id -> nombre (la web usa la misma lista)
EFECTOS = {
    "zoomin": "Zoom de acercamiento", "zoomout": "Zoom de alejamiento", "pulse": "Pulso al ritmo",
    "shake": "Temblor de cámara", "pan": "Paneo lateral", "tilt": "Inclinación suave",
    "flash": "Destello blanco", "glitch": "Glitch RGB", "chroma": "Aberración cromática",
    "blur": "Desenfoque", "pop": "Color intenso", "bw": "Blanco y negro dramático",
    "sepia": "Vintage sepia", "cine": "Cine teal y naranja", "vignette": "Viñeta pulsante",
    "strobe": "Estrobo negativo", "mirror": "Espejo", "grain": "Grano de película",
    "bars": "Barras cinemáticas", "trail": "Estela de movimiento", "hue": "Cambio de tono",
}

def _zc(W, H, z, x="(iw-ow)/2", y="(ih-oh)/2"):
    return [f"scale=w='{W}*({z})':h='{H}*({z})':eval=frame", f"crop={W}:{H}:x='{x}':y='{y}'"]

def _filters(eid, E, A, PH, U, W, H, p):
    """E = intensidad 0..1 (con subida/bajada suave), A = ventana activa (0/1),
    PH = avance dentro de la ventana 0..1, U = segundos desde que empezo la ventana."""
    if eid == "zoomin":   return _zc(W, H, f"1+0.22*{p}*{E}*{PH}+0.0*{A}")
    if eid == "zoomout":  return _zc(W, H, f"1+0.22*{p}*{E}*(1-{PH})")
    if eid == "pulse":    return _zc(W, H, f"1+0.07*{p}*{E}*abs(sin(t*6))")
    if eid == "shake":
        z = f"1+0.07*{p}*{E}"
        return _zc(W, H, z, f"(iw-ow)/2*(1+{E}*sin(t*23))", f"(ih-oh)/2*(1+{E}*cos(t*29))")
    if eid == "pan":      return _zc(W, H, f"1+0.14*{p}*{E}", f"(iw-ow)*{PH}")
    if eid == "tilt":
        return [f"rotate=a='0.05*{p}*{E}*sin(t*2)':ow={W}:oh={H}:c=black"] + _zc(W, H, f"1+0.10*{p}*{E}")
    if eid == "flash":    return [f"eq=brightness='0.8*{p}*{A}*max(0,1-{U}/0.3)':eval=frame"]
    if eid == "glitch":
        return [f"chromashift=crh=-18:cbh=18:crv=6:cbv=-6:enable='{A}'", f"noise=alls=26:allf=t:enable='{A}'"]
    if eid == "chroma":   return [f"chromashift=crh=-7:cbh=7:enable='{A}'"]
    if eid == "blur":     return [f"gblur=sigma={max(1, round(7 * p))}:enable='{A}'"]
    if eid == "pop":      return [f"eq=saturation='1+0.9*{p}*{E}':contrast='1+0.12*{p}*{E}':eval=frame"]
    if eid == "bw":       return [f"eq=saturation='1-{E}':contrast='1+0.15*{E}':eval=frame"]
    if eid == "sepia":
        return [f"colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:enable='{A}'"]
    if eid == "cine":     return [f"colorbalance=rs=.12:gs=0:bs=-.12:rh=.10:bh=-.10:rm=.08:bm=-.08:enable='{A}'"]
    if eid == "vignette": return [f"vignette=angle='PI/2.5-PI/3.2*min(1,{p}*{E})':eval=frame:enable='{A}'"]
    if eid == "strobe":   return [f"negate=enable='{A}*lt(mod(t,0.3),0.09)'"]
    if eid == "mirror":   return [f"hflip=enable='{A}'"]
    if eid == "grain":    return [f"noise=alls={max(5, round(16 * p))}:allf=t+u:enable='{A}'"]
    if eid == "bars":
        h = f"ih*0.13*{E}"
        return [f"drawbox=x=0:y=0:w=iw:h='{h}':color=black:t=fill:enable='{A}'",
                f"drawbox=x=0:y='ih-({h})':w=iw:h='{h}':color=black:t=fill:enable='{A}'"]
    if eid == "trail":    return [f"tmix=frames=5:enable='{A}'"]
    if eid == "hue":      return [f"hue=h='120*{p}*{E}*sin(t*3)'"]
    return []

def build(cfg, W, H, L):
    """Devuelve la lista de filtros de efectos para un clip de L segundos."""
    ids = [e for e in (cfg.get("fx_list") or []) if e in EFECTOS]
    if not ids: return []
    f = lambda k, d: float(cfg.get(k) if cfg.get(k) not in (None, "") else d)
    D = max(0.5, f("fx_dur", 3)); gap = max(0.0, f("fx_gap", 0)); blend = max(0.1, f("fx_blend", 0.6))
    S = max(0.0, f("fx_start", 0)); power = min(1.5, max(0.2, f("fx_power", 1)))
    mode = cfg.get("fx_mode", "seq"); repeat = bool(cfg.get("fx_repeat", True))
    if mode == "random": random.Random(7).shuffle(ids)
    n = len(ids)
    p = round(power, 2)
    out = []
    for j, eid in enumerate(ids):
        if mode == "stack":
            R = min(blend, 1.5)
            E = f"max(0,min(1,(t-{S})/{R}))*gte(t,{S})"
            A = f"gte(t,{S})"
            PH = f"max(0,min(1,(t-{S})/{max(L - S, 1):.2f}))"
            U = f"max(0,t-{S})"
        else:
            if mode == "overlap": P = D; Wd = D + blend; R = blend
            else:                 P = D + gap; Wd = D; R = min(blend, D / 2)
            T = n * P; off = j * P
            u = f"mod(t-{S}+{T * 1000:.3f}-{off:.3f},{T:.3f})"
            gate = f"gte(t,{S})" + ("" if repeat else f"*lt(t-{S},{T:.3f})")
            A = f"({gate}*lt({u},{Wd:.3f}))"
            E = f"({A}*max(0,min(1,min({u},{Wd:.3f}-{u})/{R:.3f})))"
            PH = f"min(1,{u}/{Wd:.3f})"
            U = u
        out += _filters(eid, E, A, PH, U, W, H, p)
    return out


ZOOMS = ("zoomin", "zoomout", "pulse", "shake")

def build_eventos(eventos, W, H, L, power=1.0):
    """Efectos en momentos EXACTOS (los decide la IA o el respaldo por subtitulos).
    eventos = [{"t": seg, "dur": seg, "fx": id}]. Todos los zooms se funden en UN solo filtro (rapido)."""
    ev = [e for e in (eventos or []) if e.get("fx") in EFECTOS][:16]
    if not ev: return []
    p = round(min(1.5, max(0.2, float(power))), 2); out = []
    zsum, ssum = [], []
    for e in ev:
        a = max(0.0, float(e["t"])); d = max(0.5, float(e.get("dur", 1.5))); b = a + d; R = min(0.35, d / 2)
        A = f"between(t,{a:.2f},{b:.2f})"
        E = f"({A}*min(1,min(t-{a:.2f},{b:.2f}-t)/{R:.2f}))"
        PH = f"min(1,max(0,(t-{a:.2f})/{d:.2f}))"
        U = f"max(0,t-{a:.2f})"
        if e["fx"] == "zoomin": zsum.append(f"0.20*{p}*{E}*{PH}")
        elif e["fx"] == "zoomout": zsum.append(f"0.20*{p}*{E}*(1-{PH})")
        elif e["fx"] == "pulse": zsum.append(f"0.08*{p}*{E}*abs(sin(t*6))")
        elif e["fx"] == "shake": zsum.append(f"0.06*{p}*{E}"); ssum.append(E)
        else: out += _filters(e["fx"], E, A, PH, U, W, H, p)
    if zsum:
        z = "1+" + "+".join(zsum)
        sh = "min(1," + "+".join(ssum) + ")" if ssum else "0"
        x = f"(iw-ow)/2*(1+{sh}*sin(t*23))" if ssum else "(iw-ow)/2"
        y = f"(ih-oh)/2*(1+{sh}*cos(t*29))" if ssum else "(ih-oh)/2"
        out = _zc(W, H, z, x, y) + out
    return out
