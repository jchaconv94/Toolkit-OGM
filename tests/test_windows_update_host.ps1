param()

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$source = Join-Path $repoRoot "packaging\windows\ToolkitUpdater.cs"
$cscCandidates = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$csc = $cscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $csc) {
    throw "No se encontro csc.exe para probar el auxiliar de actualizacion."
}

$base = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "ToolkitOGM-Updater-Regression"))
$testRoot = [System.IO.Path]::GetFullPath((Join-Path $base ([Guid]::NewGuid().ToString("N"))))
if (-not $testRoot.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "La carpeta temporal calculada no es segura."
}

function Invoke-CSharpCompiler {
    param(
        [string]$Output,
        [string]$Source,
        [string[]]$References = @()
    )

    $arguments = @("/nologo", "/target:winexe", "/optimize+", "/out:$Output")
    foreach ($reference in $References) {
        $arguments += "/reference:$reference"
    }
    $arguments += $Source
    & $csc @arguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Output)) {
        throw "No se pudo compilar $Output"
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $hostExe = Join-Path $testRoot "ToolkitUpdateHost.exe"
    Invoke-CSharpCompiler -Output $hostExe -Source $source -References @("System.Windows.Forms.dll")

    $oldSource = Join-Path $testRoot "old-app.cs"
    $newSource = Join-Path $testRoot "new-app.cs"
    $installerSource = Join-Path $testRoot "fake-installer.cs"

    @'
using System.Reflection;
[assembly: AssemblyVersion("2.1.4.0")]
[assembly: AssemblyFileVersion("2.1.4.0")]
[assembly: AssemblyInformationalVersion("2.1.4")]
internal static class Program { private static void Main() { } }
'@ | Set-Content -LiteralPath $oldSource -Encoding UTF8

    @'
using System.Reflection;
[assembly: AssemblyVersion("2.1.5.0")]
[assembly: AssemblyFileVersion("2.1.5.0")]
[assembly: AssemblyInformationalVersion("2.1.5")]
internal static class Program { private static void Main() { } }
'@ | Set-Content -LiteralPath $newSource -Encoding UTF8

    @'
using System;
using System.IO;

internal static class FakeInstaller
{
    private static int Main(string[] args)
    {
        string installDirectory = null;
        foreach (string argument in args)
        {
            if (argument.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase))
            {
                installDirectory = argument.Substring(5).Trim('"');
            }
        }
        if (string.IsNullOrEmpty(installDirectory)) return 90;

        string ownDirectory = AppDomain.CurrentDomain.BaseDirectory;
        if (File.Exists(Path.Combine(ownDirectory, "mode-fail.txt")))
        {
            Directory.Delete(installDirectory, true);
            Directory.CreateDirectory(installDirectory);
            File.WriteAllText(Path.Combine(installDirectory, "partial-update.txt"), "incompleta");
            return 5;
        }

        File.Copy(
            Path.Combine(ownDirectory, "new-app.exe"),
            Path.Combine(installDirectory, "ToolkitOGM.exe"),
            true
        );
        File.WriteAllText(Path.Combine(installDirectory, "updated.txt"), "ok");
        return 0;
    }
}
'@ | Set-Content -LiteralPath $installerSource -Encoding UTF8

    $oldExe = Join-Path $testRoot "old-app.exe"
    $newExe = Join-Path $testRoot "new-app.exe"
    Invoke-CSharpCompiler -Output $oldExe -Source $oldSource
    Invoke-CSharpCompiler -Output $newExe -Source $newSource

    foreach ($mode in @("success", "failure")) {
        $caseRoot = Join-Path $testRoot $mode
        $installDirectory = Join-Path $caseRoot "installed"
        $updateDirectory = Join-Path $caseRoot "updates"
        New-Item -ItemType Directory -Path $installDirectory, $updateDirectory -Force | Out-Null
        Copy-Item -LiteralPath $oldExe -Destination (Join-Path $installDirectory "ToolkitOGM.exe")
        Set-Content -LiteralPath (Join-Path $installDirectory "old-data.txt") -Value "datos-protegidos" -Encoding ASCII
        Copy-Item -LiteralPath $newExe -Destination (Join-Path $updateDirectory "new-app.exe")

        $installer = Join-Path $updateDirectory "ToolkitOGM-Setup-2.1.5.exe"
        Invoke-CSharpCompiler -Output $installer -Source $installerSource
        if ($mode -eq "failure") {
            Set-Content -LiteralPath (Join-Path $updateDirectory "mode-fail.txt") -Value "1" -Encoding ASCII
        }

        $log = Join-Path $updateDirectory "launcher.log"
        $hostProcess = Start-Process -FilePath $hostExe -ArgumentList @(
            $installer,
            "999999",
            $log,
            $installDirectory,
            "2.1.5"
        ) -Wait -PassThru
        $exitCode = $hostProcess.ExitCode

        if ($mode -eq "success") {
            Assert-True ($exitCode -eq 0) "El caso exitoso termino con codigo $exitCode."
            $actualVersion = (Get-Item (Join-Path $installDirectory "ToolkitOGM.exe")).VersionInfo.ProductVersion
            Assert-True ($actualVersion.StartsWith("2.1.5")) "No se verifico la version nueva: $actualVersion"
            Assert-True (Test-Path (Join-Path $installDirectory "old-data.txt")) "Se perdio un archivo de la instalacion durante el caso exitoso."
        }
        else {
            Assert-True ($exitCode -eq 30) "El caso fallido no activo la recuperacion (codigo $exitCode)."
            $actualVersion = (Get-Item (Join-Path $installDirectory "ToolkitOGM.exe")).VersionInfo.ProductVersion
            Assert-True ($actualVersion.StartsWith("2.1.4")) "No se restauro la version anterior: $actualVersion"
            Assert-True ((Get-Content (Join-Path $installDirectory "old-data.txt") -Raw).Trim() -eq "datos-protegidos") "No se restauro el archivo protegido."
            Assert-True (-not (Test-Path (Join-Path $installDirectory "partial-update.txt"))) "Quedaron archivos de una actualizacion incompleta."
            Assert-True ((Get-Content -LiteralPath $log -Raw) -like "*instalacion anterior fue restaurada correctamente*") "El registro no confirmo la recuperacion automatica."
        }

        $recoveries = @(Get-ChildItem -LiteralPath $updateDirectory -Directory -Filter "ToolkitOGM-Recovery-*" -ErrorAction SilentlyContinue)
        Assert-True ($recoveries.Count -eq 0) "La copia temporal no se limpio despues del caso $mode."
    }

    Write-Host "Pruebas del auxiliar de actualizacion: OK" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        $resolved = [System.IO.Path]::GetFullPath($testRoot)
        if ($resolved.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
