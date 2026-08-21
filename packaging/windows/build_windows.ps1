param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\.."))
$toolkitDir = Join-Path $repoRoot "toolskit"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$versionFile = Join-Path $repoRoot "VERSION"
$iconPng = Join-Path $toolkitDir "assets\icon.png"
$iconIco = Join-Path $scriptDir "ToolkitOGM.ico"
$versionInfoFile = Join-Path $scriptDir "ToolkitOGM.version.txt"
$specFile = Join-Path $scriptDir "ToolkitOGM.spec"
$issFile = Join-Path $scriptDir "ToolkitOGM.iss"
$updaterSource = Join-Path $scriptDir "ToolkitUpdater.cs"
$distDir = Join-Path $repoRoot "dist"
$buildDir = Join-Path $repoRoot "build\pyinstaller"
$appDistDir = Join-Path $distDir "ToolkitOGM"

function Assert-LastExitCode {
    param(
        [string]$Message
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Message (exit code $LASTEXITCODE)"
    }
}

function Remove-DirectoryWithRetries {
    param(
        [string]$Path,
        [int]$Attempts = 5,
        [int]$DelaySeconds = 2
    )

    if (-not (Test-Path $Path)) {
        return
    }

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Remove-Item $Path -Recurse -Force
            return
        }
        catch {
            if ($attempt -eq $Attempts) {
                throw "No se pudo limpiar $Path. Cierra cualquier instancia de ToolkitOGM que este usando ese directorio y vuelve a intentar."
            }

            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    if (-not (Test-Path $versionFile)) {
        throw "No se encontro el archivo VERSION en la raiz del repositorio."
    }

    $Version = (Get-Content $versionFile -Raw).Trim()
}

if ($Version -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') {
    throw "La version '$Version' no es valida. Usa formato semantico como 1.0.1 o 1.0.1.0"
}

$versionParts = $Version.Split('.')
while ($versionParts.Count -lt 4) {
    $versionParts += '0'
}

$versionTuple = $versionParts[0..3] -join ', '

if (-not (Test-Path $pythonExe)) {
    throw "No se encontro el interprete esperado en .venv\Scripts\python.exe"
}

Write-Host "==> Instalando dependencias de runtime..." -ForegroundColor Cyan
& $pythonExe -m pip install -r (Join-Path $toolkitDir "requirements.txt")
Assert-LastExitCode "Fallo la instalacion de dependencias de runtime"

Write-Host "==> Instalando PyInstaller..." -ForegroundColor Cyan
& $pythonExe -m pip install pyinstaller
Assert-LastExitCode "Fallo la instalacion de PyInstaller"

if (-not (Test-Path $iconPng)) {
    throw "No se encontro el icono base en $iconPng"
}

Write-Host "==> Usando version $Version" -ForegroundColor Cyan

Write-Host "==> Generando metadata de version..." -ForegroundColor Cyan
$versionInfo = @"
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=($versionTuple),
        prodvers=($versionTuple),
        mask=0x3f,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0)
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040904B0',
                [
                    StringStruct('CompanyName', 'Jordan Chacon Villacis'),
                    StringStruct('FileDescription', 'ToolKit SISMED'),
                    StringStruct('FileVersion', '$Version'),
                    StringStruct('InternalName', 'ToolkitOGM'),
                    StringStruct('OriginalFilename', 'ToolkitOGM.exe'),
                    StringStruct('ProductName', 'ToolKit SISMED'),
                    StringStruct('ProductVersion', '$Version')
                ]
            )
        ]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])
    ]
)
"@
Set-Content -Path $versionInfoFile -Value $versionInfo -Encoding UTF8

Write-Host "==> Generando icono .ico..." -ForegroundColor Cyan
$iconScript = @"
from PIL import Image
img = Image.open(r'$iconPng')
img.save(r'$iconIco', format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
"@
& $pythonExe -c $iconScript
Assert-LastExitCode "Fallo la generacion del icono .ico"

if (Test-Path $buildDir) {
    Remove-Item $buildDir -Recurse -Force
}

Remove-DirectoryWithRetries -Path $appDistDir

Write-Host "==> Empaquetando ejecutable con PyInstaller..." -ForegroundColor Cyan
& $pythonExe -m PyInstaller --noconfirm --clean --distpath $distDir --workpath $buildDir $specFile
Assert-LastExitCode "Fallo el empaquetado con PyInstaller"

Write-Host "==> Generando auxiliar nativo de actualizacion..." -ForegroundColor Cyan
$cscCandidates = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$cscPath = $cscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $cscPath) {
    throw "No se encontro el compilador C# de Windows necesario para ToolkitUpdater.exe"
}
if (-not (Test-Path -LiteralPath $updaterSource)) {
    throw "No se encontro el codigo fuente del auxiliar: $updaterSource"
}

$updaterExe = Join-Path $appDistDir "ToolkitUpdater.exe"
& $cscPath /nologo /target:winexe /optimize+ "/out:$updaterExe" $updaterSource
Assert-LastExitCode "Fallo la compilacion de ToolkitUpdater.exe"
if (-not (Test-Path -LiteralPath $updaterExe)) {
    throw "No se genero el auxiliar esperado: $updaterExe"
}

$possibleIscc = @()

$isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($isccCommand) {
    $possibleIscc += $isccCommand.Source
}

$possibleIscc += @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)

$isccPath = $possibleIscc | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $isccPath) {
    Write-Warning "No se encontro Inno Setup. El ejecutable ya fue generado en dist\ToolkitOGM, pero el instalador no pudo compilarse."
    exit 0
}

Write-Host "==> Generando instalador con Inno Setup..." -ForegroundColor Cyan
& $isccPath "/DMyAppVersion=$Version" "/DRepoRoot=$repoRoot" $issFile
Assert-LastExitCode "Fallo la compilacion del instalador con Inno Setup"

$installerPath = Join-Path $distDir "installer\ToolkitOGM-Setup-$Version.exe"
if (-not (Test-Path $installerPath)) {
    throw "Inno Setup termino, pero no se encontro el instalador esperado en $installerPath"
}

Write-Host "==> Generando huella SHA-256 para la actualizacion automatica..." -ForegroundColor Cyan
$installerHash = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$installerPath.sha256"
"$installerHash  $(Split-Path -Leaf $installerPath)" | Set-Content -Path $checksumPath -Encoding Ascii

Write-Host "==> Proceso completado." -ForegroundColor Green
Write-Host "    Instalador: $installerPath" -ForegroundColor Green
Write-Host "    SHA-256:    $checksumPath" -ForegroundColor Green
