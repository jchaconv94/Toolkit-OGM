param(
    [int]$Days = 14
)

$ErrorActionPreference = "Continue"
$since = (Get-Date).AddDays(-[Math]::Abs($Days))

Write-Host "== ToolKit SISMED: diagnostico de eliminacion ==" -ForegroundColor Cyan
Write-Host "Desde: $since"
Write-Host ""

$paths = @(
    "$env:ProgramFiles\ToolKit SISMED\ToolkitOGM.exe",
    "${env:ProgramFiles(x86)}\ToolKit SISMED\ToolkitOGM.exe",
    "$env:LOCALAPPDATA\Programs\ToolKit SISMED\ToolkitOGM.exe"
)

Write-Host "== Rutas conocidas ==" -ForegroundColor Cyan
foreach ($path in $paths) {
    if (Test-Path $path) {
        $item = Get-Item $path
        Write-Host "OK  $path  ($($item.Length) bytes, modificado $($item.LastWriteTime))" -ForegroundColor Green
    }
    else {
        Write-Host "NO  $path" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "== Registro de desinstalacion ==" -ForegroundColor Cyan
$uninstallRoots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
Get-ItemProperty $uninstallRoots -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "*ToolKit SISMED*" } |
    Select-Object DisplayName, DisplayVersion, InstallLocation, UninstallString |
    Format-List

Write-Host ""
Write-Host "== Detecciones de Microsoft Defender ==" -ForegroundColor Cyan
try {
    Get-MpThreatDetection -ErrorAction Stop |
        Where-Object {
            $_.InitialDetectionTime -ge $since -and
            ($_.Resources -match "ToolkitOGM|ToolKit SISMED|Toolkit-OGM")
        } |
        Select-Object InitialDetectionTime, ThreatName, ActionSuccess, Resources |
        Format-List
}
catch {
    Write-Host "No se pudo consultar Get-MpThreatDetection: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== Eventos recientes de Defender ==" -ForegroundColor Cyan
try {
    Get-WinEvent -FilterHashtable @{
        LogName = "Microsoft-Windows-Windows Defender/Operational"
        StartTime = $since
    } -ErrorAction Stop |
        Where-Object {
            $_.Message -match "ToolkitOGM|ToolKit SISMED|Toolkit-OGM|quarantine|cuarentena"
        } |
        Select-Object TimeCreated, Id, ProviderName, Message |
        Format-List
}
catch {
    Write-Host "No se pudo consultar el log de Defender: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== Autoarranque Toolkit ==" -ForegroundColor Cyan
# Desde la 2.3.19 el arranque es un acceso directo que deja el instalador en la carpeta Inicio.
$startupLinks = @(
    (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\StartUp\ToolKit SISMED.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\ToolKit SISMED.lnk")
)
foreach ($link in $startupLinks) {
    Write-Host ("{0}: {1}" -f $link, (Test-Path -LiteralPath $link))
}
# Las versiones anteriores se registraban solas (tarea o clave Run) y Defender las borraba por eso.
try {
    schtasks /Query /TN "ToolkitOGM_Autorun" /V /FO LIST 2>$null
}
catch {
    Write-Host "No se pudo consultar la tarea programada." -ForegroundColor Yellow
}
Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "ToolkitOGM_Sync" -ErrorAction SilentlyContinue |
    Select-Object ToolkitOGM_Sync | Format-List

Write-Host ""
Write-Host "Diagnostico terminado."
