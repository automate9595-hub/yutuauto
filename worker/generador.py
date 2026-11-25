"""Piloto IA creador: tema central -> N Shorts al dia hechos 100 % por IA.

Mezcla TODAS las IAs sin cortar el proceso: la idea la empieza Gemini, el guion Groq y los textos de YouTube Claude;
si alguna falla (clave, cuota, saturada) la siguiente toma su lugar automaticamente (ia.pedir ya hace ese respaldo).
Voz: edge-tts (gratis, voces neuronales con español latino) -> si no, voz de Windows. Imagenes: Pollinations (gratis, sin clave)
-> si falla, fondo degradado. Montaje: FFmpeg con movimiento de camara + subtitulos sincronizados con la voz.
"""
import asyncio, hashlib, json, os, pathlib, random, re, subprocess, sys, time, urllib.parse, urllib.request, datetime as dt
import ia, titulos, aprendizaje

ROOT = pathlib.Path(__file__).parent
GF = ROOT / "piloto-ia.json"

# codigo -> nombre, voces (hombre, mujer) de edge-tts, descripcion del habla para la IA
IDIOMAS = {
    "es-MX": ("Español latino (México)", ("es-MX-JorgeNeural", "es-MX-DaliaNeural"), "español latinoamericano neutro, natural y cercano (México), sin giros de España"),
    "es-AR": ("Español latino (Argentina)", ("es-AR-TomasNeural", "es-AR-ElenaNeural"), "español rioplatense (Argentina), coloquial, con voseo"),
    "es-CO": ("Español latino (Colombia)", ("es-CO-GonzaloNeural", "es-CO-SalomeNeural"), "español latinoamericano (Colombia), cercano y claro"),
    "es-US": ("Español latino (EE. UU.)", ("es-US-AlonsoNeural", "es-US-PalomaNeural"), "español latinoamericano neutro"),
    "es-ES": ("Español (España)", ("es-ES-AlvaroNeural", "es-ES-ElviraNeural"), "español de España"),
    "en-US": ("Inglés", ("en-US-GuyNeural", "en-US-JennyNeural"), "English, energetic and casual"),
    "pt-BR": ("Portugués (Brasil)", ("pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"), "português do Brasil, informal"),
    "fr-FR": ("Francés", ("fr-FR-HenriNeural", "fr-FR-DeniseNeural"), "français naturel"),
    "de-DE": ("Alemán", ("de-DE-ConradNeural", "de-DE-KatjaNeural"), "Deutsch, locker"),
    "it-IT": ("Italiano", ("it-IT-DiegoNeural", "it-IT-ElsaNeural"), "italiano naturale"),
}
POLL = "https://image.pollinations.ai/prompt/{p}?width=1080&height=1920&nologo=true&seed={s}&model=flux"

# ------------------------------------------------------------------ estado / configuracion
def leer():
    try: return json.loads(GF.read_text("utf-8"))
    except Exception: return {}

def guardar(p):
    tmp = GF.with_suffix(".tmp"); tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False), "utf-8"); os.replace(tmp, GF)

def configurar(d):
    p = leer(); hoy = dt.date.today().isoformat()
    idiomas = [x for x in (d.get("idiomas") or p.get("idiomas") or ["es-MX"]) if x in IDIOMAS] or ["es-MX"]
    tema = str(d.get("tema", p.get("tema", ""))).strip()[:140]
    if tema != p.get("tema"): p.update(ideas=[], inicio=None, hoy={})
    p.update(activo=bool(d.get("activo")), tema=tema, shorts=max(1, min(int(d.get("shorts", 5)), 40)), dias=max(1, min(int(d.get("dias", 30)), 365)),
             idiomas=idiomas, cada=max(0, min(int(d.get("cada", 0) or 0), 1440)), duracion=max(20, min(int(d.get("duracion", 45)), 180)),
             voz=d.get("voz") if d.get("voz") in ("hombre", "mujer", "alternar") else "alternar", estilo=str(d.get("estilo", p.get("estilo", "")))[:160])
    if p["activo"] and not p.get("inicio"): p["inicio"] = hoy
    for k in ("ideas", "hist"): p.setdefault(k, [])
    guardar(p); return p

def reembolsar(it):
    """Si un video creado fallo, no cuenta para el cupo del dia."""
    p = leer(); h = p.get("hoy") or {}
    if h.get("n", 0) > 0 and h.get("fecha") == dt.date.today().isoformat(): h["n"] -= 1; h["ultimo"] = 0; p["hoy"] = h; guardar(p)

def tick(items_existentes, log=print):
    p = leer()
    if not p.get("activo") or not p.get("tema"): return []
    hoy = dt.date.today(); ini = dt.date.fromisoformat(p.get("inicio") or hoy.isoformat()); dia = (hoy - ini).days + 1
    if dia > p["dias"]: p["activo"] = False; p["estado"] = f"Terminado: se completaron los {p['dias']} días."; guardar(p); log("Piloto IA: " + p["estado"]); return []
    h = p.get("hoy") or {}
    if h.get("fecha") != hoy.isoformat(): h = {"fecha": hoy.isoformat(), "n": 0, "ultimo": 0}
    p["hoy"] = h
    if h["n"] >= p["shorts"]: p["estado"] = f"Día {dia}/{p['dias']}: cupo de hoy completo ({h['n']}/{p['shorts']})."; guardar(p); return []
    if sum(1 for i in items_existentes if i.get("type") == "gen" and i.get("status") in ("pending", "processing")) >= 2: return []     # no acumular trabajo
    gap = p["cada"] * 60 if p.get("cada") else max(4 * 60, (15 * 3600) // p["shorts"])
    if time.time() - h["ultimo"] < gap: p["estado"] = f"Día {dia}/{p['dias']}: {h['n']}/{p['shorts']} creados hoy."; guardar(p); return []
    idi = p["idiomas"][len(p.get("hist", [])) % len(p["idiomas"])]
    vid = hashlib.sha1(f"{time.time()}{random.random()}".encode()).hexdigest()[:11]
    h["n"] += 1; h["ultimo"] = time.time()
    p["estado"] = f"Día {dia}/{p['dias']}: creando un Short con IA en {IDIOMAS[idi][0]} ({h['n']}/{p['shorts']} hoy)."
    p["hist"] = (p.get("hist", []) + [{"id": vid, "i": idi, "d": hoy.isoformat()}])[-200:]
    guardar(p); log("Piloto IA: " + p["estado"])
    return [{"type": "gen", "id": vid, "key": "gen:" + vid, "kind": "short", "status": "pending", "auto": True, "origen": "ia", "piloto": "ia",
             "tema": p["tema"], "idioma": idi, "voz": p["voz"], "duracion": p["duracion"], "estilo": p.get("estilo", ""), "url": "IA: " + p["tema"], "title": "Creando con IA…"}]

# ------------------------------------------------------------------ pasos de la creacion
def _ia(modo, prompt):
    data, prov = ia.pedir(prompt, modo)
    if not isinstance(data, dict): raise RuntimeError("Ninguna IA respondió (revisa las claves en el paso 6 o la conexión).")
    return data, ia.NOMBRE[prov]

def _limpio(t):
    t = re.sub(r"https?://\S+|[#@*_`~<>\[\]{}|]|[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]", "", str(t or ""))
    return re.sub(r"\s+", " ", t).strip()

def idear_y_escribir(it, p_ideas):
    """Devuelve (escenas, meta, ayuda). Tres pasos, cada uno empieza con una IA distinta (las demas respaldan)."""
    cod = it["idioma"]; nom, _, habla = IDIOMAS[cod]; tema = it["tema"]; dur = int(it.get("duracion") or 45)
    palabras = int(dur * 2.5); n = 6 if dur <= 40 else 7 if dur <= 70 else min(16, round(dur / 9))
    usadas = "\n".join("- " + x for x in p_ideas[-50:]) or "(ninguna)"
    estilo = (it.get("estilo") or "").strip()
    d1, a1 = _ia("gemini_primero", f'''Eres guionista de Shorts virales. Tema central: «{tema}». {("Estilo: " + estilo + ".") if estilo else ""}
Propón UNA idea nueva, concreta y atractiva para un Short de {dur} s, distinta de todas estas ya hechas:
{usadas}
Idioma del video: {nom}. Responde SOLO este JSON: {{"idea": "<una frase>", "gancho": "<primera frase que engancha en 2 s>"}}''')
    idea, gancho = _limpio(d1.get("idea")), _limpio(d1.get("gancho"))
    if not idea: raise RuntimeError("La IA no propuso ninguna idea.")
    d2, a2 = _ia("groq_primero", f'''Escribe el guion de un Short vertical de {dur} s (unas {palabras} palabras en total) sobre: «{idea}» (tema central: {tema}).
Empieza con este gancho: «{gancho}». Cierra con una frase que invite a seguir o comentar. Sin mentiras ni datos inventados.
Idioma: {habla}. Divide en {n} escenas; "texto" es lo que se NARRA (sin emojis ni hashtags) y "imagen" es una descripción VISUAL en INGLÉS (sin texto escrito, sin logos ni personas reales famosas, ilustración/cinemático) para generar la imagen vertical de esa escena.
Responde SOLO este JSON: {{"escenas": [{{"texto": "...", "imagen": "..."}}]}}''')
    esc = [{"texto": _limpio(e.get("texto")), "imagen": _limpio(e.get("imagen")) or tema} for e in (d2.get("escenas") or []) if isinstance(e, dict) and _limpio(e.get("texto"))]
    if len(esc) < 3: raise RuntimeError("El guion salió incompleto.")
    esc = esc[:max(9, n + 2)]
    prohib = titulos.usados([i for i in it.get("_prohibidos", [])])
    d3, a3 = _ia("gemini_primero", f'''Eres un editor de YouTube experto en títulos virales. Para este Short ({idea}) con guion: «{" ".join(e["texto"] for e in esc)[:900]}»
escribe título y descripción en {nom}. {aprendizaje.guia()}
{ia.PROMPT_ESTILO}
Título de máximo 85 caracteres (con los emojis), claro, específico y MUY atractivo, claramente DISTINTO de estos ya usados:
{chr(10).join("- " + x[:90] for x in prohib[-40:]) or "(ninguno)"}
Descripción atractiva de 2 a 3 frases con emojis y 3 a 5 hashtags al final. Responde SOLO este JSON: {{"titulo": "...", "descripcion": "..."}}''')
    titulo, desc = titulos.formatear(_limpio(d3.get("titulo")) or idea[:85], 95), titulos.formatear_desc(str(d3.get("descripcion") or idea).strip(), str(d3.get("titulo") or idea))
    return esc, {"titulo": titulo[:95], "descripcion": desc[:1500], "idea": idea}, f"idea {a1} · guion {a2} · textos {a3}"

def _dur(ffmpeg, f):
    r = subprocess.run([str(ffmpeg), "-i", str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0

async def _edge(texto, voz, ruta, rate):
    import edge_tts
    try: com = edge_tts.Communicate(texto, voz, rate=rate, boundary="WordBoundary")
    except TypeError: com = edge_tts.Communicate(texto, voz, rate=rate)
    ev = []
    with open(ruta, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio": f.write(ch["data"])
            elif ch["type"] == "WordBoundary": ev.append((ch["offset"] / 1e7, ch["duration"] / 1e7, ch["text"]))
    return ev

def _sapi(texto, cod, ruta):
    """Voz de Windows (sin internet) si edge-tts no esta disponible."""
    tf = pathlib.Path(str(ruta) + ".txt"); tf.write_text(texto, "utf-8")
    ps = ("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          f"try{{$s.SelectVoiceByHints('NotSet',[Globalization.CultureInfo]'{cod}')}}catch{{}};$s.SetOutputToWaveFile('{ruta}');"
          f"$s.Speak([IO.File]::ReadAllText('{tf}',[Text.Encoding]::UTF8));$s.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    tf.unlink(missing_ok=True)
    if r.returncode != 0 or not pathlib.Path(ruta).exists(): raise RuntimeError("La voz de Windows no funcionó: " + r.stderr[:100])

def voz_escena(texto, cod, voz_nombre, tmp, i, ffmpeg):
    """-> (wav, duracion, [(inicio, fin, palabra)]) de una escena."""
    mp3 = tmp / f"v{i}.mp3"; wav = tmp / f"v{i}.wav"; ev = []; motor = "edge-tts"
    try:
        ev = asyncio.run(_edge(texto, voz_nombre, str(mp3), "+4%")); src = mp3
        if not mp3.exists() or mp3.stat().st_size < 500: raise RuntimeError("audio vacío")
    except Exception as e:
        print("  Voz: edge-tts no disponible (" + str(e)[:70] + "), uso la voz de Windows.")
        src = tmp / f"v{i}_s.wav"; _sapi(texto, cod, src); ev = []; motor = "windows"
    subprocess.run([str(ffmpeg), "-loglevel", "error", "-y", "-i", str(src), "-af", "apad=pad_dur=0.25", "-ar", "44100", "-ac", "1", str(wav)], check=True)
    d = _dur(ffmpeg, wav); voz_d = max(d - 0.25, 0.5); pal = texto.split()
    ev = [x for x in ev if x[2].strip()]
    if len(ev) < max(1, len(pal) // 2):                         # sin tiempos por palabra: se reparten por largo de cada palabra
        tot = sum(len(w) + 1 for w in pal) or 1; t = 0.0; ev = []
        for w in pal: dd = voz_d * (len(w) + 1) / tot; ev.append((t, dd, w)); t += dd
    return wav, d, [(a, a + b, w) for a, b, w in ev]

def imagen_escena(prompt, estilo, tmp, i, seed):
    """Imagen vertical por IA (Pollinations). Si falla, degradado: el video nunca se corta."""
    dest = tmp / f"i{i}.jpg"
    q = urllib.parse.quote(f"{prompt}, {estilo or 'cinematic digital illustration, vibrant colors, dramatic lighting'}, vertical, no text, no watermark")
    for intento in range(3):
        try:
            req = urllib.request.Request(POLL.format(p=q, s=seed + i * 7 + intento), headers={"User-Agent": "Mozilla/5.0 Yutu-Worker"})
            with urllib.request.urlopen(req, timeout=90) as r: b = r.read()
            if b[:3] == b"\xff\xd8\xff" or b[:4] == b"\x89PNG":
                dest.write_bytes(b); _ajustar(dest); return True
        except Exception: pass
        time.sleep(3 * (intento + 1))
    _degradado(dest, seed + i); return False

def _ajustar(f):
    from PIL import Image
    im = Image.open(f).convert("RGB"); w, h = im.size; k = max(1080 / w, 1920 / h)
    im = im.resize((int(w * k) + 1, int(h * k) + 1)); w, h = im.size; x, y = (w - 1080) // 2, (h - 1920) // 2
    im.crop((x, y, x + 1080, y + 1920)).save(f, "JPEG", quality=92)

def _degradado(f, seed):
    from PIL import Image
    rnd = random.Random(seed); c1 = tuple(rnd.randint(20, 120) for _ in range(3)); c2 = tuple(rnd.randint(80, 220) for _ in range(3))
    im = Image.new("RGB", (1080, 1920)); px = im.load()
    for y in range(1920):
        t = y / 1919; row = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        for x in range(0, 1080): px[x, y] = row
    im.save(f, "JPEG", quality=90)

def _ass_time(s): return f"{int(s // 3600):02}:{int(s % 3600 // 60):02}:{s % 60:06.3f}".replace(".", ",")

def crear(it, cfg, MEDIA, FFMPEG, prog, chk, prohibidos=()):
    """Crea MEDIA/<id>_final.mp4. Devuelve {titulo, descripcion, ayuda}."""
    import shutil, tempfile
    vid = it["id"]; cod = it["idioma"]; nom, voces, _ = IDIOMAS[cod]
    st = leer(); it["_prohibidos"] = list(prohibidos)
    prog(0.03, "IA: idea y guion"); chk()
    esc, meta, ayuda = idear_y_escribir(it, st.get("ideas", []))
    it.pop("_prohibidos", None)
    st = leer(); st["ideas"] = (st.get("ideas", []) + [meta["idea"]])[-120:]; guardar(st)
    print(f"  [IA] {ayuda}. Idea: {meta['idea'][:80]}")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yutu-gen-"))
    try:
        vzn = it.get("voz", "alternar"); voz_n = voces[0] if vzn == "hombre" else voces[1] if vzn == "mujer" else random.choice(voces)
        wavs, durs, palabras, t0 = [], [], [], 0.0
        for i, e in enumerate(esc):
            chk(); prog(0.15 + 0.25 * i / len(esc), "Voz de la narración")
            w, d, ev = voz_escena(e["texto"], cod, voz_n, tmp, i, FFMPEG)
            wavs.append(w); durs.append(d); palabras += [(t0 + a, t0 + b, x) for a, b, x in ev]; t0 += d
        seed = random.randint(1, 10 ** 6); fallos = 0
        for i, e in enumerate(esc):
            chk(); prog(0.40 + 0.30 * i / len(esc), "Imágenes con IA")
            if not imagen_escena(e["imagen"], it.get("estilo", ""), tmp, i, seed): fallos += 1
        if fallos: print(f"  Imágenes: {fallos} escena(s) con fondo degradado (el servicio de imágenes no respondió).")
        clips = []
        for i, d in enumerate(durs):
            chk(); prog(0.70 + 0.12 * i / len(durs), "Montando escenas")
            z = f"1+0.14*t/{d:.3f}" if i % 2 == 0 else f"1.14-0.14*t/{d:.3f}"
            out = tmp / f"c{i}.mp4"
            subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", "-loop", "1", "-framerate", "30", "-t", f"{d:.3f}", "-i", str(tmp / f"i{i}.jpg"),
                            "-vf", f"scale=w='1080*({z})':h='1920*({z})':eval=frame,crop=1080:1920,setsar=1,format=yuv420p", "-r", "30",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-an", str(out)], check=True)
            clips.append(out)
        (tmp / "v.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), "utf-8"); (tmp / "a.txt").write_text("".join(f"file '{w.name}'\n" for w in wavs), "utf-8")
        subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "v.txt", "-c", "copy", "base.mp4"], cwd=tmp, check=True)
        subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "a.txt", "-c", "copy", "voz.wav"], cwd=tmp, check=True)
        # subtitulos sincronizados con la voz (grupos de 3-4 palabras)
        maxw = int(cfg.get("sub_words") or 3); caps, cur = [], []
        for a, b, w in palabras:
            if cur and (len(cur) >= maxw or a - cur[-1][1] > 0.6): caps.append(cur); cur = []
            cur.append((a, b, w))
            if w[-1:] in ".?!¿¡": caps.append(cur); cur = []
        if cur: caps.append(cur)
        srt = MEDIA / f"{vid}.srt"
        with open(srt, "w", encoding="utf-8") as f:
            for k, c in enumerate(caps, 1):
                txt = " ".join(x[2] for x in c); txt = txt.upper() if cfg.get("sub_caps", True) else txt
                f.write(f"{k}\n{_ass_time(c[0][0])} --> {_ass_time(max(c[-1][1], c[0][0] + 0.3))}\n{txt}\n\n")
        shutil.copy(srt, tmp / "s.srt")
        col = {"white": "&H00FFFFFF", "yellow": "&H0000FFFF", "green": "&H0080FF80"}.get(cfg.get("sub_color", "yellow"), "&H0000FFFF")
        size = {"s": 14, "m": 18, "l": 22}.get(cfg.get("sub_size", "m"), 18); al, mv = {"bottom": (2, 140), "middle": (10, 0), "top": (6, 80)}.get(cfg.get("sub_pos", "middle"), (10, 0))
        style = f"FontName=Arial,Alignment={al},FontSize={size},Bold=1,Outline=3,Shadow=0,PrimaryColour={col},OutlineColour=&H00000000,MarginV={mv}"
        prog(0.86, "Subtítulos y exportación"); chk()
        final = MEDIA / f"{vid}_final.mp4"
        cmd = lambda vf: [str(FFMPEG), "-loglevel", "error", "-y", "-i", "base.mp4", "-i", "voz.wav"] + (["-vf", vf] if vf else ["-c:v", "copy"]) + \
              (["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"] if vf else []) + ["-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(final)]
        try: subprocess.run(cmd(f"subtitles=s.srt:force_style='{style}'"), cwd=tmp, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print("  FFmpeg no pudo quemar subtítulos; exporto sin ellos."); subprocess.run(cmd(""), cwd=tmp, check=True)
        prog(1.0, "Listo")
        return {"titulo": meta["titulo"], "descripcion": meta["descripcion"], "ayuda": ayuda + (" · voz " + voz_n)}
    finally: shutil.rmtree(tmp, ignore_errors=True)
