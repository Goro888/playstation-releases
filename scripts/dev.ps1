<#
.SYNOPSIS
    Start the JARVIS bridge and the HUD on Windows.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -NoHud
#>
[CmdletBinding()]
param(
    [string]$BridgeHost = "127.0.0.1",
    [int]$BridgePort = 8770,
    [int]$HudPort = 5173,
    [switch]$NoHud
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "bridge -> http://${BridgeHost}:${BridgePort}" -ForegroundColor Cyan
$bridge = Start-Process -FilePath $py -ArgumentList "-m", "jarvis", "serve", "--host", $BridgeHost, "--port", $BridgePort -PassThru -WindowStyle Minimized

try {
    if (-not $NoHud) {
        if (-not (Test-Path (Join-Path $root "hud\node_modules"))) {
            Write-Host "installing HUD dependencies…" -ForegroundColor Yellow
            Push-Location (Join-Path $root "hud"); npm install; Pop-Location
        }
        Write-Host "hud    -> http://127.0.0.1:${HudPort}" -ForegroundColor Cyan
        Push-Location (Join-Path $root "hud")
        $env:JARVIS_BRIDGE = "http://127.0.0.1:$BridgePort"
        npm run dev -- --host 127.0.0.1 --port $HudPort
        Pop-Location
    } else {
        Write-Host "press Ctrl+C to stop the bridge" -ForegroundColor Yellow
        Wait-Process -Id $bridge.Id
    }
} finally {
    if (-not $bridge.HasExited) { Stop-Process -Id $bridge.Id -Force -ErrorAction SilentlyContinue }
}
