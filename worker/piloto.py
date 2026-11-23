"""Piloto automático: tema central -> busca videos relevantes (sin repetir) -> los pone en la cola -> descarga, edita y sube solo."""
import json, pathlib, subprocess, sys, time, datetime as dt
import ia
ROOT = pathlib.Path(__file__).parent
PF = ROOT / "piloto.json"
VARIANTES = ["{t}", "{t} mejores momentos", "{t} compilación", "{t} gracioso", "{t} épico", "{t} viral", "{t} 2026", "{t} funny moments", "{t} best plays", "{t} clips"]

def leer():
    try: return json.loads(PF.read_text("utf-8"))
    except Exception: return {}

def guardar(p):
    tmp = PF.with_suffix(".tmp"); tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False), "utf-8"); tmp.replace(PF)

def configurar(d):
    p = leer(); hoy = dt.date.today().isoformat()
    p.update(activo=bool(d.get("activo")), tema=str(d.get("tema", p.get("tema", ""))).strip()[:120],
             shorts=max(0, min(int(d.get("shorts", 10)), 60)), videos=max(0, min(int(d.get("videos", 3)), 30)),
             dias=max(1, min(int(d.get("dias", 30)), 365)), por_video=max(1, min(int(d.get("por_video", 3)), 10)))
    if d.get("activo") and not p.get("inicio"): p.update(inicio=hoy, usados=p.get("usados", []), hist=p.get("hist", []))
    if not d.get("activo") and d.get("reiniciar"): p.update(inicio=None, hoy={})
    p.setdefault("usados", []); p.setdefault("hist", []); guardar(p); return p

def _buscar(query, n=25):
    r = subprocess.run([sys.executable, "-m", "yt_dlp", f"ytsearch{n}:{query}", "--flat-playlist", "--dump-json", "--no-warnings"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    out = []
    for l in r.stdout.splitlines():
        try: j = json.loads(l)
        except Exception: continue
        if j.get("id"): out.append({"id": j["id"], "title": j.get("title") or "", "dur": j.get("duration") or 0, "views": j.get("view_count") or 0})
    return out

def elegir(p, kind, ya, modo="alternar"):
    """Devuelve el video más relevante que nunca se usó. Va rotando las búsquedas para no repetir."""
    tema = p["tema"]; v0 = p.get("variante", 0)
    for k in range(len(VARIANTES)):
        q = VARIANTES[(v0 + k) % len(VARIANTES)].format(t=tema)
        try: res = _buscar(q)
        except Exception: continue
        ok = [r for r in res if r["id"] not in ya and r["id"] not in p["usados"] and
              ((kind == "video" and 150 <= r["dur"] <= 1500) or (kind == "short" and 90 <= r["dur"] <= 1800))]
        if not ok: continue
        top = ok[:6]; pick = top[0]
        try:                                     # la IA elige el más relevante de los primeros (si falla, queda el primero de la búsqueda)
            lista = "\n".join(f"{i}. {r['title']} ({r['dur']}s, {r['views']} vistas)" for i, r in enumerate(top))
            txt = ia.pedir(f"Tema central: «{tema}». Elegí el video más relevante y atractivo para el tema. Respondé SOLO el número.\n{lista}", modo)
            import re; m = re.search(r"\d+", txt or "")
            if m and int(m.group(0)) < len(top): pick = top[int(m.group(0))]
        except Exception: pass
        p["variante"] = (v0 + k + 1) % len(VARIANTES)
        return pick
    return None

def contar_hoy(p):
    hoy = dt.date.today().isoformat(); h = p.get("hoy") or {}
    if h.get("fecha") != hoy: h = {"fecha": hoy, "short": 0, "video": 0, "ultimo": 0}
    p["hoy"] = h; return h

def tick(items_existentes, log=print):
    """Llamado por el vigilante. Devuelve una lista (0 o 1) de items nuevos para la cola, o [] si no toca."""
    p = leer()
    if not p.get("activo") or not p.get("tema"): return []
    hoy = dt.date.today(); ini = dt.date.fromisoformat(p.get("inicio") or hoy.isoformat())
    dia = (hoy - ini).days + 1
    if dia > p["dias"]:
        p["activo"] = False; p["estado"] = f"Terminado: se completaron los {p['dias']} días."; guardar(p); log(p["estado"]); return []
    h = contar_hoy(p); falta_s = p["shorts"] - h["short"]; falta_v = p["videos"] - h["video"]
    if falta_s <= 0 and falta_v <= 0: p["estado"] = f"Día {dia}/{p['dias']}: cupo de hoy completo."; guardar(p); return []
    total = p["shorts"] + p["videos"] or 1
    gap = max(8 * 60, (15 * 3600) // total)            # reparte el cupo en ~15 horas
    if time.time() - h.get("ultimo", 0) < gap: p["estado"] = f"Día {dia}/{p['dias']}: Shorts {h['short']}/{p['shorts']} · Videos {h['video']}/{p['videos']}"; guardar(p); return []
    kind = "video" if (falta_v > 0 and (falta_s <= 0 or falta_v / max(p["videos"], 1) >= falta_s / max(p["shorts"], 1))) else "short"
    ya = {i.get("id") for i in items_existentes}
    r = elegir(p, kind, ya)
    if not r: p["estado"] = "No encontré videos nuevos para ese tema; pruebo otra búsqueda en el próximo ciclo."; guardar(p); log(p["estado"]); return []
    n = min(p["por_video"], max(falta_s, 1)) if kind == "short" else 1
    p["usados"].append(r["id"]); p["usados"] = p["usados"][-3000:]
    h["ultimo"] = time.time(); h[kind] += n if kind == "short" else 1
    p["hist"] = (p.get("hist", []) + [{"id": r["id"], "t": r["title"], "k": kind, "d": hoy.isoformat()}])[-200:]
    p["estado"] = f"Día {dia}/{p['dias']}: agregué «{r['title'][:50]}» ({kind}). Shorts {h['short']}/{p['shorts']} · Videos {h['video']}/{p['videos']}"
    guardar(p); log(p["estado"])
    return [{"type": "video", "id": r["id"], "key": "video:" + r["id"], "kind": kind, "url": "https://www.youtube.com/watch?v=" + r["id"],
             "status": "pending", "n": n, "auto": True}]
