YUTU WORKER (v13)
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
