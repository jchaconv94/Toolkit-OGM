param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$versionFile = Join-Path $repoRoot "VERSION"
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content -LiteralPath $versionFile -Raw).Trim()
}
$issFile = Join-Path $repoRoot "packaging\windows\ToolkitOGM.iss"
$appDirectory = Join-Path $repoRoot "dist\ToolkitOGM"
$isccCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

if (-not $iscc) {
    throw "No se encontro Inno Setup para ejecutar la prueba real del instalador."
}
if (-not (Test-Path -LiteralPath (Join-Path $appDirectory "ToolkitOGM.exe"))) {
    throw "Primero debe generarse dist\ToolkitOGM con build_windows.ps1."
}

$base = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "ToolkitOGM-Installer-Regression"))
$testId = [Guid]::NewGuid().ToString("N")
$testRoot = [System.IO.Path]::GetFullPath((Join-Path $base $testId))
$installDirectory = Join-Path $testRoot "installed\ToolKit SISMED"
$fallbackDirectory = Join-Path $testRoot "fallback\ToolKit SISMED"
$installerDirectory = Join-Path $testRoot "installer"
$appId = "ToolkitOGM-Installer-Regression-$testId"
$appName = "ToolKit SISMED Regression $testId"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Setup {
    param(
        [string]$Installer,
        [string[]]$Arguments
    )

    $process = Start-Process `
        -FilePath $Installer `
        -ArgumentList $Arguments `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        throw "El instalador de prueba termino con codigo $($process.ExitCode)."
    }
}

try {
    Assert-True `
        ($testRoot.StartsWith($base + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) `
        "La carpeta temporal calculada no es segura."

    New-Item -ItemType Directory -Path $installerDirectory -Force | Out-Null

    & $iscc `
        "/DMyAppVersion=$Version" `
        "/DRepoRoot=$repoRoot" `
        "/DMyAppId=$appId" `
        "/DMyAppName=$appName" `
        "/DMyInstallerDir=$installerDirectory" `
        "/DMyDefaultDirName=$fallbackDirectory" `
        $issFile | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo compilar el instalador aislado."
    }

    $installer = Join-Path $installerDirectory "ToolkitOGM-Setup-$Version.exe"
    Assert-True (Test-Path -LiteralPath $installer) "No se genero el instalador aislado."

    $firstLog = Join-Path $testRoot "first-install.log"
    Invoke-Setup -Installer $installer -Arguments @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CURRENTUSER",
        "/AUTOUPDATE",
        "/SAFEUPDATE",
        "/DIR=`"$installDirectory`"",
        "/LOG=`"$firstLog`""
    )

    $installedExe = Join-Path $installDirectory "ToolkitOGM.exe"
    Assert-True (Test-Path -LiteralPath $installedExe) "La primera instalacion no dejo el ejecutable."
    Assert-True (Test-Path -LiteralPath (Join-Path $installDirectory "ToolkitUpdateHost.exe")) "La primera instalacion no incluyo el auxiliar seguro."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $installDirectory "ToolkitUpdater.exe"))) "La instalacion arrastro el auxiliar antiguo."

    $installedVersion = (Get-Item -LiteralPath $installedExe).VersionInfo.ProductVersion
    Assert-True ($installedVersion.StartsWith($Version)) "La version instalada no coincide: $installedVersion"

    $marker = Join-Path $installDirectory "preserve-update-test.txt"
    Set-Content -LiteralPath $marker -Value "conservar" -Encoding ASCII

    $secondLog = Join-Path $testRoot "second-install.log"
    Invoke-Setup -Installer $installer -Arguments @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CURRENTUSER",
        "/AUTOUPDATE",
        "/SAFEUPDATE",
        "/LOG=`"$secondLog`""
    )

    Assert-True (Test-Path -LiteralPath $installedExe) "La actualizacion elimino el ejecutable."
    Assert-True (Test-Path -LiteralPath $marker) "La actualizacion no conservo los archivos existentes."
    Assert-True (-not (Test-Path -LiteralPath $fallbackDirectory)) "La actualizacion cambio la carpeta registrada."

    Write-Host "Prueba real del instalador y conservacion de ruta: OK" -ForegroundColor Green
}
finally {
    $uninstaller = Join-Path $installDirectory "unins000.exe"
    if (Test-Path -LiteralPath $uninstaller) {
        try {
            Start-Process `
                -FilePath $uninstaller `
                -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
                -WindowStyle Hidden `
                -Wait | Out-Null
        }
        catch {
        }
    }

    if (Test-Path -LiteralPath $testRoot) {
        $resolved = [System.IO.Path]::GetFullPath($testRoot)
        if ($resolved.StartsWith($base + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
