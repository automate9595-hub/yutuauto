@echo off
chcp 65001 >nul
title Yutu Studio - Subir a GitHub
set "REPO=https://github.com/automate9595-hub/yutuauto.git"
set "SLUG=automate9595-hub/yutuauto"
set "SRC=%~dp0"
set "WORK=%TEMP%\yutu-upload"
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%ProgramFiles%\GitHub CLI;%LOCALAPPDATA%\Programs\Git\cmd;%LOCALAPPDATA%\gh\bin"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-herramientas.ps1"
if errorlevel 1 (echo No se pudieron instalar las herramientas. Revisa tu conexion. & pause & exit /b 1)

gh auth status -h github.com >nul 2>&1
if errorlevel 1 goto login
git ls-remote "%REPO%" >nul 2>&1
if errorlevel 1 goto login
goto logged

:login
echo.
echo ============================================================
echo  Se va a mostrar un CODIGO. Ya queda copiado al portapapeles.
echo  Se abre github.com/login/device: pega el codigo y autoriza.
echo ============================================================
cmdkey /delete:git:https://github.com >nul 2>&1
gh auth logout -h github.com >nul 2>&1
echo.| gh auth login -h github.com -p https -w -c -s repo,workflow
if errorlevel 1 (echo No se pudo iniciar sesion. & pause & exit /b 1)

:logged
gh auth setup-git -h github.com
for /f "delims=" %%i in ('gh api user --jq .login') do set "GHUSER=%%i"
git config --global user.name "%GHUSER%"
git config --global user.email "%GHUSER%@users.noreply.github.com"

rmdir /s /q "%WORK%" 2>nul
git clone "%REPO%" "%WORK%"
if errorlevel 1 (echo No se pudo clonar el repositorio. & pause & exit /b 1)
cd /d "%WORK%"
git checkout -B main >nul 2>&1
git rm -r -q --ignore-unmatch . >nul 2>&1
robocopy "%SRC%." "%WORK%" /E /XD .git /XF "1-SUBIR-A-GITHUB.bat" "instalar-herramientas.ps1" /NFL /NDL /NJH /NJS /NP >nul
git add -A
git diff --cached --quiet
if not errorlevel 1 (echo No hay cambios para subir. & pause & exit /b 0)
git commit -q -m "Yutu Studio v2.0"
git push -u origin main
if errorlevel 1 (echo Fallo el push. & pause & exit /b 1)

gh api -X POST repos/%SLUG%/pages -f build_type=workflow >nul 2>&1
gh api -X PUT repos/%SLUG%/pages -f build_type=workflow >nul 2>&1
echo.
echo LISTO. Tu web: https://automate9595-hub.github.io/yutuauto/
pause
