$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$h=@{'User-Agent'='yutu'}
$tmp=Join-Path $env:TEMP 'yutu-tools'; New-Item -ItemType Directory -Force $tmp|Out-Null
function Has($p){Test-Path $p}
if(-not((Get-Command git -ErrorAction SilentlyContinue) -or (Has "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe") -or (Has "$env:ProgramFiles\Git\cmd\git.exe"))){
  Write-Host 'Instalando Git...'
  $r=Invoke-RestMethod https://api.github.com/repos/git-for-windows/git/releases/latest -Headers $h
  $a=$r.assets|Where-Object{$_.name -match '^Git-.*-64-bit\.exe$'}|Select-Object -First 1
  $f="$tmp\$($a.name)"; Invoke-WebRequest $a.browser_download_url -OutFile $f -UseBasicParsing
  Start-Process $f -ArgumentList '/VERYSILENT','/NORESTART','/CURRENTUSER','/SUPPRESSMSGBOXES' -Wait
}
if(-not((Get-Command gh -ErrorAction SilentlyContinue) -or (Has "$env:LOCALAPPDATA\gh\bin\gh.exe") -or (Has "$env:ProgramFiles\GitHub CLI\gh.exe"))){
  Write-Host 'Instalando GitHub CLI...'
  $r=Invoke-RestMethod https://api.github.com/repos/cli/cli/releases/latest -Headers $h
  $a=$r.assets|Where-Object{$_.name -match 'windows_amd64\.zip$'}|Select-Object -First 1
  $f="$tmp\gh.zip"; Invoke-WebRequest $a.browser_download_url -OutFile $f -UseBasicParsing
  Expand-Archive $f "$env:LOCALAPPDATA\gh" -Force
}
Write-Host 'Herramientas listas.'
