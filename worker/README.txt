YUTU WORKER (v18)

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
