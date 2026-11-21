$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$tmp=Join-Path $env:TEMP 'yutu-tools'; New-Item -ItemType Directory -Force $tmp|Out-Null
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$hasPy=$false; try{ & python --version 2>$null|Out-Null; $hasPy=($LASTEXITCODE -eq 0) }catch{}
if(-not $hasPy -and -not (Test-Path $py)){
  Write-Host 'Instalando Python...'
  $f="$tmp\python.exe"; Invoke-WebRequest https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe -OutFile $f -UseBasicParsing
  Start-Process $f -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0' -Wait
}
try{
if(-not((Get-Command ffmpeg -ErrorAction SilentlyContinue) -or (Test-Path "$env:LOCALAPPDATA\ffmpeg\bin\ffmpeg.exe"))){
  Write-Host 'Instalando FFmpeg...'
  $f="$tmp\ffmpeg.zip"; Invoke-WebRequest https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile $f -UseBasicParsing
  $x="$tmp\ff"; Remove-Item $x -Recurse -Force -ErrorAction SilentlyContinue; Expand-Archive $f $x -Force
  $d=Get-ChildItem $x -Directory|Select-Object -First 1
  Remove-Item "$env:LOCALAPPDATA\ffmpeg" -Recurse -Force -ErrorAction SilentlyContinue
  Move-Item $d.FullName "$env:LOCALAPPDATA\ffmpeg"
}
}catch{ Write-Host 'No pude bajar FFmpeg directo; uso la alternativa por pip.' }
Write-Host 'Herramientas listas.'
