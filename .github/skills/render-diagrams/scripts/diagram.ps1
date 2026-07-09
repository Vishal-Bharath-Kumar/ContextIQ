#!/usr/bin/env pwsh
# =============================================================================
# diagram.ps1 — IDE-agnostic local diagram renderer (PowerShell cross-platform)
# Works on: Windows PowerShell 5.1+, PowerShell 7+, macOS, Linux
# Works in: Windsurf, VS Code, Cursor, Rider, any terminal, CI/CD
#
# Usage:
#   .\bin\diagram.ps1 diagrams\auth.puml              render single file
#   .\bin\diagram.ps1 diagrams\er.mmd --Format svg    render as SVG
#   .\bin\diagram.ps1 --All                           render all in .\diagrams\
#   .\bin\diagram.ps1 --All --Dir src\                render all in custom folder
#   .\bin\diagram.ps1 --Watch                         auto-render on save
#   .\bin\diagram.ps1 --Server                        start PlantUML server
#   .\bin\diagram.ps1 --Server --Stop                 stop PlantUML server
#   .\bin\diagram.ps1 --Check                         verify dependencies
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Position=0)] [string]$File,
    [string]  $Format    = "png",
    [string]  $Dir       = $env:DIAGRAMS_DIR ?? "diagrams",
    [switch]  $All,
    [switch]  $Watch,
    [switch]  $Server,
    [switch]  $Stop,
    [switch]  $Check,
    [switch]  $Svg,
    [switch]  $Help
)

# ── Config ────────────────────────────────────────────────────────────────────
$PlantumlJar    = $env:PLANTUML_JAR ?? (Join-Path $HOME "plantuml.jar")
$PlantumlPort   = $env:PLANTUML_PORT ?? "8080"
$PlantumlServer = "http://localhost:$PlantumlPort"
$PidFile        = ".plantuml_server.pid"

if ($Svg) { $Format = "svg" }

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Ok($msg)   { Write-Host "  ✅ $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "  ❌ $msg" -ForegroundColor Red }
function Write-Warn($msg) { Write-Host "  ⚠️  $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "  ℹ️  $msg" -ForegroundColor Cyan }
function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Blue }

function Test-Server {
    try {
        $r = Invoke-WebRequest -Uri $PlantumlServer -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -lt 500
    } catch { return $false }
}

# ── PlantUML encoding ─────────────────────────────────────────────────────────
function Get-PumlEncoded([string]$text) {
    $chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $ms = New-Object System.IO.MemoryStream
    $deflate = New-Object System.IO.Compression.DeflateStream($ms, [System.IO.Compression.CompressionMode]::Compress)
    $deflate.Write($bytes, 0, $bytes.Length)
    $deflate.Close()
    $compressed = $ms.ToArray()
    $result = [System.Text.StringBuilder]::new()
    for ($i = 0; $i -lt $compressed.Length; $i += 3) {
        $b0 = $compressed[$i]
        $b1 = if ($i+1 -lt $compressed.Length) { $compressed[$i+1] } else { 0 }
        $b2 = if ($i+2 -lt $compressed.Length) { $compressed[$i+2] } else { 0 }
        $b  = ($b0 -shl 16) -bor ($b1 -shl 8) -bor $b2
        [void]$result.Append($chars[($b -shr 18) -band 63])
        [void]$result.Append($chars[($b -shr 12) -band 63])
        [void]$result.Append($(if ($i+1 -lt $compressed.Length) { $chars[($b -shr 6) -band 63] } else { "=" }))
        [void]$result.Append($(if ($i+2 -lt $compressed.Length) { $chars[$b -band 63] } else { "=" }))
    }
    return $result.ToString()
}

# ── Render single PlantUML file ───────────────────────────────────────────────
function Invoke-RenderPuml([string]$src, [string]$fmt) {
    $out = [System.IO.Path]::ChangeExtension($src, $fmt)
    $text = Get-Content $src -Raw

    # Try server first
    if (Test-Server) {
        try {
            $encoded = Get-PumlEncoded $text
            $url = "$PlantumlServer/plantuml/$fmt/$encoded"
            Invoke-WebRequest -Uri $url -OutFile $out -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
            Write-Ok "[server] $(Split-Path $src -Leaf) → $(Split-Path $out -Leaf)"
            return $true
        } catch {
            Write-Warn "Server render failed — falling back to jar"
        }
    }

    # Fallback: java -jar
    if (-not (Test-Path $PlantumlJar)) {
        Write-Err "plantuml.jar not found at: $PlantumlJar"
        return $false
    }
    $flag = if ($fmt -eq "svg") { "-tsvg" } else { "-tpng" }
    $result = & java -jar $PlantumlJar $flag $src 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "[jar]    $(Split-Path $src -Leaf) → $(Split-Path $out -Leaf)"
        return $true
    } else {
        Write-Err "PlantUML render failed: $src`n$result"
        return $false
    }
}

# ── Render single Mermaid file ────────────────────────────────────────────────
function Invoke-RenderMmd([string]$src, [string]$fmt) {
    $out = [System.IO.Path]::ChangeExtension($src, $fmt)
    if (-not (Get-Command mmdc -ErrorAction SilentlyContinue)) {
        Write-Err "mmdc not found. Run: npm install -g @mermaid-js/mermaid-cli"
        return $false
    }
    $result = & mmdc -i $src -o $out -b white --quiet 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "[mmdc]   $(Split-Path $src -Leaf) → $(Split-Path $out -Leaf)"
        return $true
    } else {
        Write-Err "Mermaid render failed: $src`n$result"
        return $false
    }
}

# ── Render dispatcher ─────────────────────────────────────────────────────────
function Invoke-Render([string]$src, [string]$fmt) {
    if (-not (Test-Path $src)) { Write-Err "File not found: $src"; return $false }
    $ext = [System.IO.Path]::GetExtension($src).ToLower()
    switch ($ext) {
        { $_ -in ".puml",".plantuml" } { return Invoke-RenderPuml $src $fmt }
        { $_ -in ".mmd",".mermaid"  } { return Invoke-RenderMmd  $src $fmt }
        default { Write-Warn "Skipping unsupported extension: $ext"; return $true }
    }
}

# ── Render all ────────────────────────────────────────────────────────────────
function Invoke-RenderAll([string]$dir, [string]$fmt) {
    if (-not (Test-Path $dir)) { Write-Err "Directory not found: $dir"; exit 1 }
    $files = Get-ChildItem -Path $dir -Recurse -Include "*.puml","*.plantuml","*.mmd","*.mermaid"
    if ($files.Count -eq 0) { Write-Warn "No diagram files found in: $dir"; return }

    Write-Step "Rendering $($files.Count) diagram(s) in $dir ..."
    Write-Host ""
    $ok = 0; $fail = 0
    foreach ($f in $files) {
        if (Invoke-Render $f.FullName $fmt) { $ok++ } else { $fail++ }
    }
    Write-Host ""
    Write-Host "─────────────────────────────────"
    Write-Ok "Done — $ok rendered"
    if ($fail -gt 0) { Write-Err "$fail failed" }
}

# ── Watch (FileSystemWatcher — event-driven, no polling) ──────────────────────
function Start-Watch([string]$dir, [string]$fmt) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $watcher = New-Object System.IO.FileSystemWatcher
    $watcher.Path = Resolve-Path $dir
    $watcher.IncludeSubdirectories = $true
    $watcher.EnableRaisingEvents = $true
    $watcher.Filter = "*.*"

    $action = {
        $path = $Event.SourceEventArgs.FullPath
        $ext  = [System.IO.Path]::GetExtension($path).ToLower()
        if ($ext -in @(".puml",".plantuml",".mmd",".mermaid")) {
            Start-Sleep -Milliseconds 300  # debounce
            Write-Host ""
            Write-Host "▶ Changed: $(Split-Path $path -Leaf)" -ForegroundColor Blue
            . $using:PSCommandPath -File $path -Format $using:fmt 2>$null
        }
    }

    Register-ObjectEvent $watcher "Changed" -Action $action | Out-Null
    Register-ObjectEvent $watcher "Created" -Action $action | Out-Null

    Write-Step "Watching: $(Resolve-Path $dir)"
    Write-Info "Format  : $($fmt.ToUpper())"
    Write-Info "Ctrl+C  : Stop watcher"
    Write-Host ""
    try { while ($true) { Start-Sleep -Seconds 1 } }
    finally { $watcher.Dispose(); Write-Host "`n🛑 Watcher stopped." }
}

# ── Server management ────────────────────────────────────────────────────────
function Start-PumlServer {
    if (Test-Server) { Write-Ok "PlantUML server already running at $PlantumlServer"; return }
    if (-not (Test-Path $PlantumlJar)) {
        Write-Err "plantuml.jar not found: $PlantumlJar"
        Write-Host "    Download: https://plantuml.com/download"
        exit 1
    }
    Write-Step "Starting PlantUML server on port $PlantumlPort ..."
    $proc = Start-Process -FilePath "java" -ArgumentList "-jar", $PlantumlJar, "-picoweb:$PlantumlPort" `
                          -WindowStyle Hidden -PassThru
    $proc.Id | Set-Content $PidFile
    for ($i = 0; $i -lt 16; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Server) {
            Write-Ok "Server ready at $PlantumlServer  (PID: $($proc.Id))"
            Write-Info "Stop with: .\bin\diagram.ps1 --Server --Stop"
            return
        }
        Write-Host "  Waiting... ($([math]::Round(($i+1)*0.5,1))s)" -NoNewline
        Write-Host "`r" -NoNewline
    }
    Write-Err "Server did not start. Check Java installation."
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    exit 1
}

function Stop-PumlServer {
    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        Write-Ok "PlantUML server stopped (PID: $pid)"
    } else { Write-Warn "No PID file found" }
}

# ── Dependency check ──────────────────────────────────────────────────────────
function Invoke-Check {
    Write-Host ""
    Write-Step "Checking dependencies ..."
    Write-Host ""
    if (Get-Command java -ErrorAction SilentlyContinue) {
        $v = & java -version 2>&1 | Select-Object -First 1
        Write-Ok "Java      : $v"
    } else { Write-Err "Java not found — install from https://adoptium.net" }

    if (Test-Path $PlantumlJar) { Write-Ok "plantuml  : $PlantumlJar" }
    else {
        Write-Err "plantuml.jar not found: $PlantumlJar"
        Write-Host "    Download: https://plantuml.com/download"
        Write-Host "    Or set:  `$env:PLANTUML_JAR = 'D:\tools\plantuml.jar'"
    }

    if (Test-Server) { Write-Ok "PU Server : running at $PlantumlServer" }
    else {
        Write-Warn "PU Server : not running (optional)"
        Write-Host "    Start:  .\bin\diagram.ps1 --Server"
    }

    if (Get-Command mmdc -ErrorAction SilentlyContinue) {
        $v = & mmdc --version 2>&1 | Select-Object -First 1
        Write-Ok "mmdc      : $v"
    } else {
        Write-Err "mmdc not found"
        Write-Host "    Install: npm install -g @mermaid-js/mermaid-cli"
    }
    Write-Host ""
}

# ── Help ──────────────────────────────────────────────────────────────────────
function Show-Help {
    Write-Host ""
    Write-Host "  diagram.ps1 — local diagram renderer (PlantUML + Mermaid)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Usage:"
    Write-Host "    .\bin\diagram.ps1 <file.puml>          render single PlantUML file"
    Write-Host "    .\bin\diagram.ps1 <file.mmd>           render single Mermaid file"
    Write-Host "    .\bin\diagram.ps1 <file> --Svg         render as SVG"
    Write-Host "    .\bin\diagram.ps1 --All                render all in .\diagrams\"
    Write-Host "    .\bin\diagram.ps1 --All --Svg          render all as SVG"
    Write-Host "    .\bin\diagram.ps1 --All --Dir src\     render all in custom folder"
    Write-Host "    .\bin\diagram.ps1 --Watch              auto-render on file save"
    Write-Host "    .\bin\diagram.ps1 --Watch --Dir src\   watch custom folder"
    Write-Host "    .\bin\diagram.ps1 --Server             start PlantUML HTTP server"
    Write-Host "    .\bin\diagram.ps1 --Server --Stop      stop PlantUML server"
    Write-Host "    .\bin\diagram.ps1 --Check              verify all dependencies"
    Write-Host ""
    Write-Host "  Environment variables:"
    Write-Host "    PLANTUML_JAR     path to plantuml.jar  (default: ~/plantuml.jar)"
    Write-Host "    PLANTUML_PORT    server port            (default: 8080)"
    Write-Host "    DIAGRAMS_DIR     default diagram folder (default: .\diagrams)"
    Write-Host ""
}

# ── Main dispatch ─────────────────────────────────────────────────────────────
if     ($Check)           { Invoke-Check }
elseif ($Server -and $Stop) { Stop-PumlServer }
elseif ($Server)          { Start-PumlServer }
elseif ($Watch)           { Start-Watch $Dir $Format }
elseif ($All)             { Invoke-RenderAll $Dir $Format }
elseif ($File)            { Invoke-Render $File $Format | Out-Null }
else                      { Show-Help }
