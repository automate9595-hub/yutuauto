@echo off
if not "%~1"=="run" (start "Yutu Worker" cmd /k ""%~f0" run" & exit /b)
chcp 65001 >nul
title Yutu Worker - NO CERRAR
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-herramientas.ps1"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\ffmpeg\bin;%PATH%"
python -m pip install -q -U yt-dlp faster-whisper playwright imageio-ffmpeg
start "" https://automate9595-hub.github.io/yutuauto/
python servidor.py
echo.
echo El worker se detuvo. Puedes cerrar esta ventana.
