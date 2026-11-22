YUTU WORKER
1) Ejecuta 2-INSTALAR-Y-EJECUTAR.bat. Instala todo con pip, se cierra solo y deja el worker
   en segundo plano con un icono "Y" junto al wifi/bateria (verde = activo, azul = procesando).
   Clic derecho en el icono: abrir panel, ver registro, abrir carpeta de videos, salir.
2) En la web: configura la edicion (subtitulos, recorte, 21 efectos con duracion y mezcla).
3) "Conectar con mi canal de YouTube" e inicia sesion (una sola vez).
4) "Comenzar proceso" (solo edita) o "Comenzar proceso, automatizar y subir ahora" (edita y sube).
5) En Publicaciones: porcentaje de cada video, "Ver" (previsualizar), "Subir ahora", "Programar" y "Cancelar".
IA (opcional): pega tus claves de Gemini, Groq y Claude en la web (seccion Edicion). Vienen precargadas en claves-ia.json, que NO se sube a GitHub (GitHub lo bloquea).
Si una subida falla: worker\error-subida.png y worker\diagnostico-subida.txt muestran donde se quedo.
Registro: worker.log. Videos terminados: carpeta media.
Nota: YouTube Studio debe estar en ingles para que los campos de fecha/hora coincidan.
