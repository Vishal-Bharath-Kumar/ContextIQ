# Markdown Validation Script (PowerShell)
# Mirrors scripts/validate-markdown.sh for Windows/PowerShell shells.
# Checks markdown files for common formatting issues.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$File
)

$ErrorActionPreference = 'Stop'

# Reject path traversal
if ($File -match '\.\.') {
    Write-Host "Error: Path traversal not allowed in file path" -ForegroundColor Red
    exit 1
}

# Whitelist safe path characters (letters, digits, dash, underscore, dot, slash, backslash, colon, space)
if ($File -match '[^a-zA-Z0-9_./:\\ -]') {
    Write-Host "Error: File path contains invalid characters" -ForegroundColor Red
    exit 1
}

if ($File -notmatch '\.md$') {
    Write-Host "Error: File must have a .md extension" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
    Write-Host "Error: File not found: $File" -ForegroundColor Red
    exit 1
}

$errors = 0
$warnings = 0

Write-Host "Validating: $File"
Write-Host "----------------------------------------"

$content = Get-Content -LiteralPath $File -Raw
$lines = Get-Content -LiteralPath $File

# 1. File ends with newline
if ($content.Length -gt 0 -and $content[-1] -ne "`n") {
    Write-Host "WARNING: File does not end with newline" -ForegroundColor Yellow
    $warnings++
}

# 2. Trailing whitespace
$trailingLines = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match ' $') { $trailingLines += ($i + 1) }
}
if ($trailingLines.Count -gt 0) {
    Write-Host "WARNING: Trailing whitespace on lines: $($trailingLines -join ' ')" -ForegroundColor Yellow
    $warnings++
}

# 3. Tabs
$tabLines = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "`t") { $tabLines += ($i + 1) }
}
if ($tabLines.Count -gt 0) {
    Write-Host "WARNING: Tabs found on lines: $($tabLines -join ' ')" -ForegroundColor Yellow
    $warnings++
}

# 4. Code blocks without language identifier
$bareFence = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^```$') { $bareFence += ($i + 1) }
}
if ($bareFence.Count -gt 0) {
    Write-Host "WARNING: Code blocks without language identifier on lines: $($bareFence -join ' ')" -ForegroundColor Yellow
    $warnings++
}

# 5. Multiple consecutive blank lines
if ($content -match "`n`n`n+") {
    Write-Host "WARNING: Multiple consecutive blank lines found" -ForegroundColor Yellow
    $warnings++
}

# 6. Mixed list markers
$asterisk = ($lines | Where-Object { $_ -match '^\* ' }).Count
$plus     = ($lines | Where-Object { $_ -match '^\+ ' }).Count
$dash     = ($lines | Where-Object { $_ -match '^- ' }).Count
if ($asterisk -gt 0 -and $dash -gt 0) {
    Write-Host "WARNING: Mixed list markers (* and -) found. * markers: $asterisk, - markers: $dash" -ForegroundColor Yellow
    $warnings++
}
if ($plus -gt 0) {
    Write-Host "WARNING: Plus (+) list markers found (prefer -). + markers: $plus" -ForegroundColor Yellow
    $warnings++
}

# 7. Bad link text
if ($content -match '(?i)\[click here\]') {
    Write-Host "WARNING: 'Click here' links found (use descriptive text)" -ForegroundColor Yellow
    $warnings++
}
if ($content -match '(?i)\[here\]') {
    Write-Host "WARNING: 'Here' links found (use descriptive text)" -ForegroundColor Yellow
    $warnings++
}

# 8. Images without alt text
$noAlt = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '!\[\]\(') { $noAlt += ($i + 1) }
}
if ($noAlt.Count -gt 0) {
    Write-Host "WARNING: Images without alt text on lines: $($noAlt -join ' ')" -ForegroundColor Yellow
    $warnings++
}

# 9. Emphasis with underscores
if ($content -match '__[^_]*__') {
    Write-Host "WARNING: Bold with __ found (prefer **)" -ForegroundColor Yellow
    $warnings++
}
$nonUrl = ($lines | Where-Object { $_ -notmatch 'http' }) -join "`n"
if ($nonUrl -match '_[^_]*_') {
    Write-Host "WARNING: Italic with _ found (prefer *)" -ForegroundColor Yellow
    $warnings++
}

Write-Host "----------------------------------------"
Write-Host ("Errors: {0}" -f $errors) -ForegroundColor Red
Write-Host ("Warnings: {0}" -f $warnings) -ForegroundColor Yellow

if ($errors -eq 0 -and $warnings -eq 0) {
    Write-Host "OK - No issues found!" -ForegroundColor Green
    exit 0
} elseif ($errors -eq 0) {
    Write-Host "Validation completed with warnings" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "Validation failed" -ForegroundColor Red
    exit 1
}
