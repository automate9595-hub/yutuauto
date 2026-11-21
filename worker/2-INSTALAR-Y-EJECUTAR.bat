@echo off
if not "%~1"=="run" (start "Yutu Worker - preparando" cmd /c ""%~f0" run" & exit /b)
chcp 65001 >nul
title Yutu Worker - preparando
cd /d "%~dp0"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"

python --version >nul 2>&1
if errorlevel 1 (
  echo Instalando Python...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-herramientas.ps1"
)

echo Instalando componentes con pip (la primera vez puede tardar unos minutos)...
python -m pip install -q --disable-pip-version-check -U yt-dlp
python -m pip install -q --disable-pip-version-check faster-whisper playwright imageio-ffmpeg pystray pillow
if errorlevel 1 (
  echo.
  echo ERROR: pip no pudo instalar los componentes. Revisa tu conexion y ejecuta este archivo de nuevo.
  pause
  exit /b 1
)

echo Iniciando el worker en segundo plano...
start "" pythonw "%~dp0bandeja.pyw"
echo Listo. Busca el icono verde "Y" junto al wifi y la bateria (si no lo ves, toca la flecha ^ de la barra de tareas).
timeout /t 5 >nul
exit
