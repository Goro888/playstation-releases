<#
.SYNOPSIS
    One-shot Windows installer for JARVIS.

.DESCRIPTION
    Installs the layered JARVIS stack on Windows:
      1. Python 3.11 virtual environment + core requirements
      2. Ollama (local inference) + a Qwen model
      3. whisper.cpp (speech-to-text) + a ggml Whisper model
      4. Piper (neural text-to-speech) + a voice
      5. openWakeWord (the "Hey JARVIS" wake word) + PortAudio capture
      6. A starter config at ~/.jarvis/config.yaml

    Every stage is independent: if one download fails the rest still install,
    and `python -m jarvis doctor` tells you exactly what is still missing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1 -Model qwen3.5:9b -WhisperModel small -SkipModels
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Model = "qwen3.5:4b",
    [string]$VisionModel = "qwen2.5vl:7b",
    [string]$WhisperModel = "base",
    [string]$PiperVoice = "en_US-lessac-medium",
    [switch]$SkipModels,
    [switch]$NoVoice
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$JarvisHome = if ($env:JARVIS_HOME) { $env:JARVIS_HOME } else { Join-Path $HOME ".jarvis" }
$ModelsDir  = Join-Path $JarvisHome "models"
$BinDir     = Join-Path $JarvisHome "bin"
$RepoRoot   = Split-Path -Parent $PSScriptRoot

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [--]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [!!]  $msg" -ForegroundColor Red }

function Ensure-Dir($path) {
    if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
}

function Get-LatestReleaseAsset($repo, $pattern) {
    try {
        $release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'jarvis-installer' }
        $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
        if (-not $asset) { return $null }
        return @{ Url = $asset.browser_download_url; Name = $asset.name; Tag = $release.tag_name }
    } catch {
        Write-Warn "could not query GitHub releases for $repo ($_)"
        return $null
    }
}

function Install-ZipAsset($repo, $pattern, $destName) {
    $asset = Get-LatestReleaseAsset $repo $pattern
    if (-not $asset) { return $false }
    $dest = Join-Path $BinDir $destName
    Ensure-Dir $dest
    $zip = Join-Path $env:TEMP $asset.Name
    Write-Host "  downloading $($asset.Name) ($($asset.Tag))"
    try {
        Invoke-WebRequest -Uri $asset.Url -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        Write-Err "download/extract failed: $_"
        return $false
    }
}

Write-Host @"

      #####    #    ######  #     #  #####  #####
         #    # #   #     # #     # #     # #
         #   #   #  #     # #     # #       #####
      #  #  #####  ######   #   #   #  ####      #
      #  #  #   #  #   #     # #    #     #      #
       ##   #   #  #    #     #      #####  #####

      local-first AI operating assistant — Windows installer
"@ -ForegroundColor Cyan

Ensure-Dir $JarvisHome
Ensure-Dir $ModelsDir
Ensure-Dir $BinDir

# ---------------------------------------------------------------------------
Write-Step "1/6  Python environment"
# ---------------------------------------------------------------------------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Err "Python not found. Install Python 3.11 from https://www.python.org/downloads/windows/ (tick 'Add to PATH') and re-run."
    exit 1
}
$pyVersion = & $python.Source -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $pyVersion at $($python.Source)"
if ([version]$pyVersion -lt [version]"3.10" -or [version]$pyVersion -gt [version]"3.13") {
    Write-Warn "OpenJarvis/JARVIS target Python 3.10-3.13; you have $pyVersion."
}

Set-Location $RepoRoot
$venv = Join-Path $RepoRoot ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "  creating virtualenv at $venv"
    & $python.Source -m venv $venv
}
$pip = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $pip)) { $pip = $python.Source }
& $pip -m pip install --upgrade pip --quiet
& $pip -m pip install -r (Join-Path $RepoRoot "requirements.txt")
if ($LASTEXITCODE -eq 0) { Write-Ok "core requirements installed" } else { Write-Err "pip install failed" }

# ---------------------------------------------------------------------------
Write-Step "2/6  Ollama (local brain)"
# ---------------------------------------------------------------------------
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "  Ollama not found — trying winget…"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    } else {
        Write-Warn "winget unavailable — install Ollama manually from https://ollama.com/download/windows"
    }
}
if ($ollama) {
    Write-Ok "ollama at $($ollama.Source)"
    if (-not $SkipModels) {
        $svc = Get-Process ollama -ErrorAction SilentlyContinue
        if (-not $svc) { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep -Seconds 4 }
        Write-Host "  pulling $Model (this is the big download ~1.5 GB)…"
        & ollama pull $Model
        Write-Host "  pulling $VisionModel (multimodal, for screen understanding)…"
        & ollama pull $VisionModel
    }
} else {
    Write-Warn "Ollama missing — JARVIS will run on the offline brain until you install it."
}

# ---------------------------------------------------------------------------
Write-Step "3/6  whisper.cpp (speech-to-text)"
# ---------------------------------------------------------------------------
if ($NoVoice) {
    Write-Warn "skipped (-NoVoice)"
} else {
    & $pip -m pip install openwakeword sounddevice numpy --quiet
    $whisperDir = Join-Path $BinDir "whisper.cpp"
    if (-not (Test-Path $whisperDir)) {
        Install-ZipAsset "ggml-org/whisper.cpp" "*win-x64*.zip" "whisper.cpp" | Out-Null
    }
    $cli = Get-ChildItem -Path $BinDir -Recurse -Filter "whisper-cli.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cli) { $cli = Get-ChildItem -Path $BinDir -Recurse -Filter "main.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if ($cli) {
        Write-Ok "whisper.cpp binary: $($cli.FullName)"
        $ggml = Join-Path $ModelsDir "ggml-$WhisperModel.bin"
        if (-not (Test-Path $ggml) -and -not $SkipModels) {
            Write-Host "  downloading ggml-$WhisperModel.bin"
            try {
                Invoke-WebRequest "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$WhisperModel.bin" -OutFile $ggml -UseBasicParsing
                Write-Ok "whisper model saved to $ggml"
            } catch { Write-Err "model download failed: $_" }
        }
    } else {
        Write-Warn "whisper.cpp exe not found — try: winget install Gyan.FFmpeg ; or download from https://github.com/ggml-org/whisper.cpp/releases"
    }
}

# ---------------------------------------------------------------------------
Write-Step "4/6  Piper (text-to-speech)"
# ---------------------------------------------------------------------------
if ($NoVoice) {
    Write-Warn "skipped (-NoVoice)"
} else {
    $piperDir = Join-Path $BinDir "piper"
    if (-not (Test-Path (Join-Path $piperDir "piper.exe"))) {
        Install-ZipAsset "OHF-voice/piper1-gpl" "*windows_amd64*.zip" "piper" | Out-Null
    }
    $piperExe = Get-ChildItem -Path $BinDir -Recurse -Filter "piper.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($piperExe) {
        Write-Ok "piper at $($piperExe.FullName)"
        Ensure-Dir (Join-Path $ModelsDir "piper")
        if (-not $SkipModels) {
            $onnx = Join-Path $ModelsDir "piper\$PiperVoice.onnx"
            if (-not (Test-Path $onnx)) {
                Write-Host "  downloading voice $PiperVoice"
                try {
                    Invoke-WebRequest "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$PiperVoice.onnx" -OutFile $onnx -UseBasicParsing
                    Invoke-WebRequest "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$PiperVoice.onnx.json" -OutFile "$onnx.json" -UseBasicParsing
                    Write-Ok "voice saved to $onnx"
                } catch { Write-Err "voice download failed: $_ (pick another at https://rhasspy.github.io/piper-samples/)" }
            }
        }
    } else {
        Write-Warn "piper.exe not found — download it from https://github.com/OHF-voice/piper1-gpl/releases and drop it in $BinDir"
    }
}

# ---------------------------------------------------------------------------
Write-Step "5/6  Optional: Windows UI Automation"
# ---------------------------------------------------------------------------
& $pip -m pip install uiautomation --quiet
if ($LASTEXITCODE -eq 0) { Write-Ok "uiautomation installed (click buttons by name)" }

# ---------------------------------------------------------------------------
Write-Step "6/6  Configuration"
# ---------------------------------------------------------------------------
$configDir = Join-Path $JarvisHome
Ensure-Dir $configDir
$configPath = Join-Path $JarvisHome "config.yaml"
if (-not (Test-Path $configPath)) {
    Copy-Item (Join-Path $RepoRoot "config\jarvis.example.yaml") $configPath
    Write-Ok "created $configPath"
} else {
    Write-Ok "kept existing $configPath"
}

# Point the config at whatever we actually installed
$cfgText = Get-Content $configPath -Raw
$cfgText = $cfgText -replace 'model: qwen3.5:4b', "model: $Model"
$cfgText = $cfgText -replace 'stt_model: base', "stt_model: $WhisperModel"
$cfgText = $cfgText -replace 'tts_voice: en_US-lessac-medium', "tts_voice: $PiperVoice"
if ($piperExe) { $cfgText = $cfgText -replace 'piper_binary: piper', "piper_binary: $($piperExe.FullName.Replace('\','\\'))" }
if ($cli)      { $cfgText = $cfgText -replace 'stt_binary: whisper-cli', "stt_binary: $($cli.FullName.Replace('\','\\'))" }
Set-Content -Path $configPath -Value $cfgText -Encoding UTF8

Set-Location $RepoRoot
& $pip -m jarvis doctor

Write-Host @"

-----------------------------------------------------------------------------
  Next steps

    .venv\Scripts\python -m jarvis serve        # start the bridge (port 8770)
    cd hud ; npm install ; npm run dev          # start the HUD (port 5173)
    .venv\Scripts\python -m jarvis chat --voice # or run it from the terminal

  Then say:  "Hey JARVIS"  …  "open chrome"
-----------------------------------------------------------------------------
"@ -ForegroundColor Cyan
