$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
# Solo instala Python si falta. FFmpeg y el resto se instalan con pip desde el .bat.
$tmp=Join-Path $env:TEMP 'yutu-tools'; New-Item -ItemType Directory -Force $tmp|Out-Null
$py="$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if(-not (Test-Path $py)){
  Write-Host 'Instalando Python...'
  $f="$tmp\python.exe"; Invoke-WebRequest https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe -OutFile $f -UseBasicParsing
  Start-Process $f -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0' -Wait
}
Write-Host 'Python listo.'
