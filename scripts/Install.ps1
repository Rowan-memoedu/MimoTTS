#Requires -Version 7.4
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$runtime = 'D:\AppData\MimoTTS'
$venv = Join-Path $runtime 'venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create runtime' }
}
& (Join-Path $venv 'Scripts\python.exe') -m pip install --cache-dir 'D:\Caches\pip' --no-deps -e $root
if ($LASTEXITCODE -ne 0) { throw 'Unable to install MiMo TTS' }
$bin = Join-Path $runtime 'bin'
New-Item -ItemType Directory -Path $bin -Force | Out-Null
$command = '@echo off' + "`r`n" + '"' + (Join-Path $venv 'Scripts\python.exe') + '" -X utf8 -m mimo_tts.cli %*' + "`r`n"
[IO.File]::WriteAllText((Join-Path $bin 'mimo-tts.cmd'), $command, [Text.UTF8Encoding]::new($false))
$userPath = [Environment]::GetEnvironmentVariable('Path','User')
if ($bin -notin ($userPath -split ';')) {
    [Environment]::SetEnvironmentVariable('Path',($userPath.TrimEnd(';') + ';' + $bin),'User')
}
$env:Path = "$bin;$env:Path"
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MimoEnvironmentBroadcast {
    [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, UIntPtr wParam, string lParam, uint flags, uint timeout, out UIntPtr result);
}
'@
$broadcastResult = [UIntPtr]::Zero
[MimoEnvironmentBroadcast]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$broadcastResult) | Out-Null
& (Join-Path $bin 'mimo-tts.cmd') --json doctor
if ($LASTEXITCODE -ne 0) { throw 'MiMo doctor requires a configured user environment key' }
Write-Output "INSTALLED $bin\mimo-tts.cmd"
