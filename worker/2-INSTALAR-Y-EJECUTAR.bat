@echo off
chcp 65001 >nul
title Yutu Worker
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-herramientas.ps1"
if errorlevel 1 (echo No se pudieron instalar las herramientas. & pause & exit /b 1)
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\ffmpeg\bin;%PATH%"
python -m pip install -q -U yt-dlp faster-whisper google-api-python-client google-auth-oauthlib
if exist "%USERPROFILE%\Downloads\yutu-studio-cola.json" copy /y "%USERPROFILE%\Downloads\yutu-studio-cola.json" "%~dp0queue.json" >nul
if not exist queue.json (echo Falta la cola: exportala desde la web primero. & pause & exit /b 1)
if not exist client_secret.json echo AVISO: sin client_secret.json solo se prepara el video, no se sube.
if exist client_secret.json (python yutu.py) else (python yutu.py --sin-subir)
pause
