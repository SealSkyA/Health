Get-ChildItem -Path $env:APPDATA, $env:LOCALAPPDATA, $env:USERPROFILE -Directory -Name -ErrorAction SilentlyContinue |
  Where-Object { $_ -match 'monkey|minis' } | ForEach-Object { Write-Output $_ }
Write-Output '---PROC---'
try {
  $p = Get-Process -Name 'monkeycode-desktop' -ErrorAction Stop
  Write-Output $p.Path
} catch { Write-Output 'proc not found' }