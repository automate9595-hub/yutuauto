YUTU WORKER (v28)

NOVEDADES v28
- Los pilotos de Shorts de YouTube, Facebook (tema y cuenta), TikTok cuenta y TikTok tema tienen ahora «Elegir los videos por»: Automático (variados), Más vistas, Más likes, Más comentarios, Más compartidos o Más recientes. Toma siempre el mejor que todavía no se usó (nunca repite).
  Vistas: sale de la propia lista cuando el sitio las muestra; likes/comentarios/compartidos/fecha se consultan con yt-dlp a los 10 mejores candidatos (tarda unos segundos más) y se recuerdan.
  En el estado del piloto se ve el dato del video elegido, por ejemplo «(más likes: 12.345)». Facebook puede no mostrar likes/comentarios si la sesión no está iniciada: en ese caso queda ordenado por lo que haya.

NOVEDADES v27
- 🧠 Aprendizaje de títulos (paso 6 · Inteligencia artificial): Yutu parte de tu lección (un buen título es CLARO, ESPECÍFICO y despierta CURIOSIDAD, con los ejemplos malos/buenos) y aprende de lo que le enseñes: pegá consejos o ejemplos y se le entregan a la IA en CADA título (todos los pilotos y el Creador IA). Podés borrar lecciones y probar un título para ver su puntaje.
- Control de calidad: cada título se puntúa (0-100: longitud, número/dato concreto, gancho, nada genérico tipo «Mi experiencia...»). Si sale flojo (menos de 60) se pide uno mejor, con el motivo, hasta 2 veces antes de subir. Sigue sin repetirse nunca.
- Las lecciones quedan en aprendizaje.json (carpeta del worker).

NOVEDADES v26
- NUEVO panel «📤 Dónde se publican los videos» (paso 7 · Publicación): YouTube siempre, y si querés también tu Página de Facebook (Reel) y TikTok, con el MISMO título y descripción.
  Funciona con los pilotos y con la cola manual. Se publica en Facebook/TikTok apenas termina la subida a YouTube (no usan la programación).
  Se hace en el Chrome del worker (misma sesión que ya iniciaste), en una pestaña aparte que se cierra sola: Facebook por Meta Business Suite, TikTok por TikTok Studio.
  Si Facebook/TikTok pide iniciar sesión o cambió su pantalla, el video de YouTube NO se toca ni se repite: en la tarjeta del video queda «⚠ TikTok: motivo», y en la carpeta del worker se guardan diagnostico-redes.txt / .png.
  Cada red se publica una sola vez por video (no se duplica aunque se reintente).
  La Página de Facebook: opcional, ID numérico; vacío = la que tengas seleccionada en Meta Business Suite.

NOVEDADES v25
- NUEVO piloto «📘 Facebook · reels»: busca reels por TEMA o por CUENTA/PÁGINA, en segundo plano (Chrome oculto, sin ventanas) y los descarga con yt-dlp. Funciona igual que los demás: cupo diario, intervalo, duración mín/máx, cuenta regresiva. Nunca repite el reel, el título ni el fragmento.
  Facebook casi siempre exige sesión: tocá «Iniciar sesión en Facebook», entrá en la ventana de Chrome y «Ya inicié sesión: comprobar» (una sola vez).
- Los pilotos trabajan SIEMPRE DE A UNO: mientras un video se descarga, edita o sube no se elige otro; al terminar de subir sigue el piloto que más tiempo lleva sin publicar. En la cuenta regresiva aparece «Esperando su turno».
- Claves de Gemini nuevas agregadas a la rotación (ahora 7; pasa sola a la siguiente cuando una se queda sin cuota).

NOVEDADES v24
- Cuenta regresiva grande en la web hasta el próximo Short de cada piloto. El intervalo (ej. 30 min) se cuenta desde que TERMINA la subida y se repite en cada ciclo.
- Al aparecer "Se ha publicado el vídeo" toca Cerrar y MINIMIZA Chrome, para que quede a la vista la web de Yutu con la cuenta regresiva. Al subir el siguiente, Chrome se restaura solo.
- Mientras un video del piloto se descarga/edita/sube, el piloto no elige otro.
- Corregido el falso "Se cortó la subida / No pude abrir el selector de Visibilidad": si el archivo ya llegó a YouTube (o pasó el 90 %), se da por subido y no se repite el proceso ni se duplica; sigue con el siguiente programado.

NOVEDADES v23
- YA NO SE ABREN VENTANAS DE TU CANAL A CADA RATO: antes el worker abría una pestaña nueva de YouTube Studio cada vez que revisaba los pilotos
  (cada minuto), y eso llenaba la RAM. Ahora Chrome se abre SOLO al tocar "Conectar con mi canal" / "Iniciar sesión en TikTok" y cuando un video ya
  está editado y listo para subir. Si había pestañas de Studio repetidas, el worker deja una y cierra las demás. La sesión se conserva siempre
  (perfil chrome-perfil).
- BUCLE "Analizando con IA" (volvía el % atrás y empezaba de nuevo): si la nube (Groq) fallaba, la IA transcribía TODO el video en tu PC, algo
  muy lento y pesado. Ahora, en videos de más de 5 min, solo usa la nube; si no puede, usa el corte normal. La barra de progreso nunca retrocede
  y, si el proceso se corta dos veces en el mismo video, se marca con error y la causa (p. ej. MemoryError) en vez de repetir sin fin.
- TIKTOK EN SEGUNDO PLANO: las búsquedas y lecturas de TikTok usan un Chrome OCULTO (sin ventana, sin imágenes ni video, perfil chrome-bg) que se
  cierra solo a los 3 min sin uso. Tu sesión de TikTok se copia sola desde el Chrome visible. Si TikTok no devuelve videos, se guarda
  diagnostico-tiktok.txt y .png con lo que vio el navegador.
- Los pilotos de TikTok leen como máximo 3 páginas por ciclo y el estado dice qué pasó (buscando..., fuera de duración, no era del tema).
- INTERVALOS DE DURACIÓN rediseñados: bloque grande con Mínimo / Máximo, selector Minutos | Segundos y una frase que resume el rango.
- BOTÓN "🧹 Vaciar rastros…" en Publicaciones: quita canceladas, con error, publicadas..., borra videos descargados/temporales, registros,
  diagnósticos y caché, y (opcional) la memoria de los pilotos y la lista de enlaces. No toca lo que está en proceso ni tus sesiones.

YUTU WORKER (v22)

NOVEDADES v22
- DURACIONES EN MINUTOS: el límite de duración de los videos que buscan los pilotos, la duración del Short, el inicio del recorte y la duración
  del Short del Creador IA se escriben en MINUTOS (admite decimales: 0,5 = 30 s) y hay un selector para pasar a segundos. Los Shorts pueden
  durar hasta 3 minutos (YouTube ya lo permite).
- TIKTOK NO DESCARGABA ("Command ... returned non-zero exit status"): ahora la descarga prueba varias formas (Chrome simulado + cookies, solo
  cookies, simple) y, si TikTok sigue bloqueando a yt-dlp, baja el video con el Chrome del worker. Si falla, la tarjeta muestra la causa REAL.
- TIKTOK POR TEMA: busca el tema directo en TikTok (buscador) además de los hashtags/cuentas que propone la IA; si TikTok pide login o captcha
  ya no descarta las fuentes, avisa qué hacer.
- TIKTOK POR CUENTA: la cuenta se lee primero con el Chrome del worker (espera a que carguen los videos y baja con scroll) y después con yt-dlp.
- BOTONES NUEVOS "Iniciar sesión en TikTok" y "Ya inicié sesión: comprobar" (pestañas TikTok · cuenta y TikTok · tema). Se inicia sesión UNA vez
  en la ventana de Chrome del worker; las cookies se guardan solas y se usan para leer y descargar.
- El límite de duración también se vuelve a comprobar al descargar (cuando la lista de TikTok no trae la duración).
- Para que yt-dlp y curl_cffi sean compatibles, volvé a ejecutar 2-INSTALAR-Y-EJECUTAR.bat.

YUTU WORKER (v18)

NOVEDADES v21
- Ventana final "Se está procesando el vídeo": solo cuando el pie dice "Comprobaciones completadas" toca "Cerrar" (mientras sube/comprueba, espera).
- Límite de duración (mínimo y máximo, en segundos) para los videos que buscan los pilotos de YouTube, Shorts de YouTube y los dos de TikTok.

NOVEDADES v19
- WORKER ESTABLE: ahora corre bajo un supervisor (si se cae, se levanta solo), el trabajo pesado va con menos prioridad (el panel ya no
  parece "apagado" mientras se edita), el proceso de edición sobrevive a un reinicio y se retoma donde quedó, y nada queda "procesando" para siempre.
- CANCELADOS: lo que cancelás ya no se vuelve a cargar al tocar "Comenzar".
- SUBIDA: leía el panel flotante de OTRAS subidas ("Subiéndose 19 %") y se quedaba esperando para siempre. Ahora mira solo el cuadro de
  la subida actual: cuando dice "Comprobaciones completadas" toca Siguiente hasta Publicar (y "Publicar de todas formas").
- TODOS LOS PILOTOS: "Subir uno nuevo cada [minutos/horas]" (vacío = reparte el cupo del día), 1 Short por video fuente (siempre videos
  distintos), nunca el mismo tramo/segundos de un video (segmentos-usados.json), descripciones sin repetir (descripciones-usadas.json).
- PILOTO NUEVO "Shorts de YouTube": un Short distinto del tema cada X tiempo.
- TIKTOK: si yt-dlp no puede leer la cuenta/etiqueta, se lee con el Chrome del worker (y se guardan sus cookies para descargar).
- PLAYLISTS: paso 7 -> "publicar uno cada X minutos".
- GEMINI: podés pegar VARIAS claves; cuando una se queda sin cuota pasa sola a la siguiente.
- Web ordenada: pilotos en pestañas con un punto verde si están activos.

NOVEDADES v18
- PILOTOS TIKTOK ARREGLADOS: la IA les devolvia un formato incompatible y los dos se quedaban sin hacer nada. Ahora leen TikTok
  haciéndose pasar por Chrome (curl_cffi) y, si TikTok bloquea, el piloto por tema sigue con Shorts de YouTube del mismo tema.
- MAS RAPIDO: el siguiente video se descarga mientras se edita el actual; cada video se SUBE apenas queda listo (antes se editaba
  todo y recién después se subía); no se vuelve a transcribir lo que ya se transcribió; subtitulos corregidos por la IA en paralelo;
  el título se piensa mientras FFmpeg codifica; FFmpeg en modo veryfast; descarga con 4 fragmentos a la vez.
- IA: zooms y efectos en los momentos exactos que decide la IA (paso 6, casilla nueva). Sin IA usa el ritmo del discurso.
- PILOTO CREADOR IA (arriba en la web): tema + Shorts por dia + idiomas (incluye español latino México/Argentina/Colombia/EE.UU.).
  Gemini escribe la idea, Groq el guion y Claude el título; si una falla, la siguiente sigue. Voz neuronal (edge-tts), imagenes
  por IA (Pollinations), subtitulos sincronizados y publicación automática.
- SUBIDA: no toca "Siguiente" hasta que Studio termina de subir y COMPROBAR (100 %, "Comprobaciones completadas"); después pasa
  por todas las etapas verificando que la pantalla cambie, y publica ("Publicar de todas formas" si pregunta).
- TITULOS UNICOS: nunca se usa el título del video copiado, el original ni uno ya usado (registro en titulos-usados.json).

1) Ejecuta 2-INSTALAR-Y-EJECUTAR.bat. Instala todo con pip, se cierra solo y deja el worker
   en segundo plano con un icono "Y" junto al wifi/bateria (verde = activo, azul = procesando).
2) En la web hay 9 pasos desplegables: Conectar, Videos, Subtitulos, Recorte, Efectos, IA, Publicacion,
   Ejecutar y Publicaciones. Abri cada uno, elegi lo que quieras y toca "Siguiente".
3) En el paso 1 conecta tu canal de YouTube (una sola vez).
4) Boton "Procesar y publicar todo": descarga, edita, sube a tu canal, toca "Siguiente" en cada etapa de Studio
   y publica. El video queda visible en tu canal sin que toques nada.

SUBTITULOS: motor "Automatico" = Whisper large-v3 en Groq (usa tu clave de Groq) -> large-v3-turbo -> faster-whisper en tu PC -> Vosk.
Idiomas: Español latino, Español, Ingles, Detectar. El titulo del video se usa como pista para escribir bien los nombres.
Modelos locales: tiny, base, small, medium, large-v3-turbo, large-v3 (los grandes piden mas RAM y se descargan una vez).

IA: claves en worker\claves-ia.json (solo en tu PC; no se suben a GitHub). Gemini usa el Flash Lite mas nuevo que acepte tu clave;
si falla prueba otros modelos. Podes fijar un modelo en el paso 6. Claude sin credito se salta solo durante 1 hora.
El titulo y la descripcion los escribe la IA; si ninguna responde, se sube con el nombre del archivo.

Si una subida falla: worker\error-subida.png y worker\diagnostico-subida.txt muestran donde se quedo.
Registro: worker.log. Videos terminados: carpeta media.

NOVEDADES v15
- CORRECCION: ya no se cierra el cuadro de subida ni se cambia de pagina mientras Studio muestre porcentaje o tiempo restante de subida; espera a que desaparezca. Si se corta, reanuda sola.
- PILOTO AUTOMATICO (arriba en la web): tema central + Shorts/Videos por dia + dias. La IA busca el video mas relevante que nunca se uso, lo descarga, edita y sube. Estado en worker\piloto.json.
- PILOTO TIKTOK: pasas una cuenta; toma sus videos (seguidilla, aleatorio o mas vistos), la IA verifica que sean de Mobile Legends, los edita y sube de a uno sin repetir. Estado en worker\piloto-tiktok.json.
- PILOTO TIKTOK POR TEMA: solo escribis el tema; la IA propone hashtags/cuentas de TikTok, toma videos al azar, verifica que sean del tema y los sube sin repetir. Estado en worker\piloto-tema-tiktok.json.

NOVEDADES v14
- SUBIDA QUE SE CORTA: si Studio muestra "La subida se ha interrumpido" (o el porcentaje no avanza 7 min, o se cae internet/Chrome),
  el worker busca solo la fila en Contenido del canal, toca "Reanudar subida", entrega el archivo de la carpeta media (sin abrir la
  ventana de Windows) y sigue hasta publicar. Hasta 5 intentos seguidos; si no alcanza, el vigilante lo reintenta cada pocos minutos
  (hasta 8 veces). Tambien revisa al empezar si quedo alguna subida cortada de antes. Se apaga en el paso 7 (casilla "reanudarla sola").
- VARIOS SHORTS DE UN VIDEO LARGO: en el paso 4 elegis cuantos Shorts sacar y cada cuantas horas sale uno (o ajustas la cantidad en cada
  video de la cola). La IA elige los mejores momentos distintos; sin IA se reparten parejo. Los archivos quedan como ID_p1_final.mp4, ID_p2_final.mp4...
