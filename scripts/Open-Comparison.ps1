$ErrorActionPreference = 'Stop'
$report = Get-Content -LiteralPath 'D:\Artifacts\MimoTTS\latest-report.json' -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $report.path)) { throw 'Comparison report does not exist' }
$chrome = Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'
if (-not (Test-Path -LiteralPath $chrome)) { throw 'Google Chrome is unavailable at its installed path' }
Start-Process -FilePath $chrome -ArgumentList ([Uri]::new($report.path).AbsoluteUri)
Write-Output $report.path
