@echo off
title Yutu Worker - instalar y encender
cd /d "%~dp0"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"

python --version >nul 2>&1
if errorlevel 1 echo Instalando Python...
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-herramientas.ps1"
python --version >nul 2>&1
if errorlevel 1 goto sinpython

echo Instalando componentes con pip (la primera vez puede tardar unos minutos)...
python -m pip install -q --disable-pip-version-check -U "yt-dlp[default,curl-cffi]"
python -m pip install -q --disable-pip-version-check imageio-ffmpeg pystray pillow
python -m pip install -q --disable-pip-version-check edge-tts curl_cffi
if errorlevel 1 goto sinpip

echo Instalando voz para subtitulos (si alguno falla, el worker usa el otro)...
python -m pip install -q --disable-pip-version-check faster-whisper
python -m pip install -q --disable-pip-version-check vosk

echo Iniciando el worker en segundo plano...
start "" pythonw "%~dp0bandeja.pyw"
echo.
echo LISTO. Busca el icono verde "Y" junto al wifi y la bateria (si no lo ves, toca la flecha ^ de la barra de tareas).
goto fin

:sinpython
echo.
echo ERROR: no encuentro Python. Cierra esta ventana y ejecuta este archivo de nuevo (la instalacion de Python pudo haber terminado recien).
goto fin

:sinpip
echo.
echo ERROR: pip no pudo instalar los componentes. Revisa tu conexion y ejecuta este archivo de nuevo.

:fin
if /i "%~1"=="nopause" exit /b
echo.
pause
exit /b
