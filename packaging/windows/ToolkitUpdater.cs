using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;

internal static class ToolkitUpdateHost
{
    private const int ParentWaitMilliseconds = 90000;
    private const long SafetyMarginBytes = 256L * 1024L * 1024L;
    private const string ApplicationExeName = "ToolkitOGM.exe";

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 && string.Equals(args[0], "--restore", StringComparison.OrdinalIgnoreCase))
        {
            return RunElevatedRestore(args);
        }

        if (args.Length < 5)
        {
            return 10;
        }

        string installerPath;
        string logPath;
        string installDirectory;
        string expectedVersion = (args[4] ?? string.Empty).Trim();
        int parentProcessId;

        try
        {
            installerPath = Path.GetFullPath(args[0]);
            logPath = Path.GetFullPath(args[2]);
            installDirectory = Path.GetFullPath(args[3]).TrimEnd(Path.DirectorySeparatorChar);
        }
        catch (Exception)
        {
            return 11;
        }

        if (!int.TryParse(args[1], out parentProcessId))
        {
            WriteLog(logPath, "No se recibio un identificador valido para ToolKit SISMED.");
            return 12;
        }

        string applicationPath = Path.Combine(installDirectory, ApplicationExeName);
        string updateDirectory = Path.GetDirectoryName(installerPath);
        if (!File.Exists(installerPath) || !IsSafeInstallationDirectory(installDirectory))
        {
            WriteLog(logPath, "Se cancelo la actualizacion porque sus rutas no son validas.");
            return 13;
        }
        if (!File.Exists(applicationPath))
        {
            WriteLog(logPath, "Se cancelo la actualizacion: no existe " + applicationPath);
            return 14;
        }
        if (IsPathInside(updateDirectory, installDirectory))
        {
            WriteLog(
                logPath,
                "Se cancelo la actualizacion porque sus archivos temporales estan dentro de la instalacion."
            );
            return 17;
        }

        Version parsedExpectedVersion;
        if (!TryParseVersion(expectedVersion, out parsedExpectedVersion))
        {
            WriteLog(logPath, "Se cancelo la actualizacion: la version esperada no es valida.");
            return 15;
        }

        WriteLog(
            logPath,
            "Auxiliar seguro iniciado. Carpeta que se conservara: " + installDirectory
        );
        if (!WaitForParent(logPath, parentProcessId))
        {
            WriteLog(logPath, "La aplicacion no termino de cerrarse. No se modifico la instalacion.");
            return 16;
        }

        string backupDirectory = Path.Combine(
            updateDirectory,
            "ToolkitOGM-Recovery-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")
        );

        try
        {
            CreateVerifiedBackup(installDirectory, backupDirectory, logPath);
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo crear la copia de recuperacion: " + exception.Message);
            StartApplication(applicationPath, "--update-failed", logPath);
            ShowFailure(
                "La actualizacion fue cancelada antes de modificar ToolKit SISMED porque no se pudo crear una copia de seguridad.\n\n" +
                "La instalacion anterior se conserva. Puede abrir la aplicacion e intentarlo nuevamente."
            );
            return 20;
        }

        int installerExitCode;
        try
        {
            installerExitCode = RunInstaller(
                installerPath,
                installDirectory,
                expectedVersion,
                logPath
            );
        }
        catch (Win32Exception exception)
        {
            WriteLog(logPath, "Windows no permitio ejecutar el instalador: " + exception.Message);
            DeleteDirectoryQuietly(backupDirectory, logPath);
            StartApplication(applicationPath, "--update-failed", logPath);
            return 21;
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo ejecutar el instalador: " + exception.Message);
            return RecoverPreviousInstallation(
                backupDirectory,
                installDirectory,
                applicationPath,
                logPath,
                "El instalador no pudo iniciarse."
            );
        }

        if (installerExitCode == 0 && HasExpectedVersion(applicationPath, expectedVersion, logPath))
        {
            WriteLog(logPath, "Actualizacion verificada correctamente. Version instalada: " + expectedVersion);
            DeleteDirectoryQuietly(backupDirectory, logPath);
            StartApplication(applicationPath, "--install-success", logPath);
            return 0;
        }

        WriteLog(
            logPath,
            "La instalacion no quedo verificada (codigo=" + installerExitCode + "). Se restaurara la version anterior."
        );
        StopApplicationAtPath(applicationPath, logPath);
        return RecoverPreviousInstallation(
            backupDirectory,
            installDirectory,
            applicationPath,
            logPath,
            "Windows no completo correctamente la actualizacion."
        );
    }

    private static int RunElevatedRestore(string[] args)
    {
        if (args.Length < 4)
        {
            return 40;
        }

        string backupDirectory;
        string installDirectory;
        string logPath;
        try
        {
            backupDirectory = Path.GetFullPath(args[1]);
            installDirectory = Path.GetFullPath(args[2]).TrimEnd(Path.DirectorySeparatorChar);
            logPath = Path.GetFullPath(args[3]);
        }
        catch (Exception)
        {
            return 41;
        }

        try
        {
            RestoreBackup(backupDirectory, installDirectory, logPath);
            WriteLog(logPath, "La recuperacion con permisos de administrador termino correctamente.");
            return 0;
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "La recuperacion con permisos de administrador fallo: " + exception.Message);
            return 42;
        }
    }

    private static bool WaitForParent(string logPath, int parentProcessId)
    {
        try
        {
            using (Process parent = Process.GetProcessById(parentProcessId))
            {
                if (parent.HasExited || parent.WaitForExit(ParentWaitMilliseconds))
                {
                    WriteLog(logPath, "ToolKit SISMED se cerro correctamente.");
                    return true;
                }
            }

            return false;
        }
        catch (ArgumentException)
        {
            WriteLog(logPath, "ToolKit SISMED ya estaba cerrado.");
            return true;
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo comprobar el cierre: " + exception.Message);
            return false;
        }
    }

    private static int RunInstaller(
        string installerPath,
        string installDirectory,
        string expectedVersion,
        string logPath
    )
    {
        string setupLog = Path.Combine(
            Path.GetDirectoryName(installerPath),
            "setup-" + expectedVersion + ".log"
        );
        string installMode = IsPerUserInstallation(installDirectory) ? "/CURRENTUSER" : "/ALLUSERS";
        string arguments =
            "/SP- /SILENT /NORESTART /NORESTARTAPPLICATIONS " +
            "/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /AUTOUPDATE /SAFEUPDATE " +
            installMode + " " +
            "/DIR=" + Quote(installDirectory) + " " +
            "/LOG=" + Quote(setupLog) + " /LOGCLOSEAPPLICATIONS";

        WriteLog(logPath, "Abriendo el instalador para actualizar exactamente la carpeta actual.");
        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = installerPath;
        startInfo.Arguments = arguments;
        startInfo.WorkingDirectory = Path.GetDirectoryName(installerPath);
        startInfo.UseShellExecute = true;
        startInfo.WindowStyle = ProcessWindowStyle.Normal;

        using (Process installer = Process.Start(startInfo))
        {
            if (installer == null)
            {
                throw new InvalidOperationException("Windows no devolvio el proceso del instalador.");
            }

            installer.WaitForExit();
            WriteLog(logPath, "El instalador termino con codigo " + installer.ExitCode + ".");
            return installer.ExitCode;
        }
    }

    private static void CreateVerifiedBackup(
        string installDirectory,
        string backupDirectory,
        string logPath
    )
    {
        if (Directory.Exists(backupDirectory))
        {
            throw new IOException("La carpeta de recuperacion ya existe.");
        }
        if (IsPathInside(backupDirectory, installDirectory))
        {
            throw new IOException("La copia de recuperacion no puede guardarse dentro de la instalacion.");
        }

        DirectorySnapshot source = MeasureDirectory(installDirectory);
        if (source.FileCount == 0 || source.TotalBytes <= 0)
        {
            throw new IOException("La instalacion actual no contiene archivos para respaldar.");
        }

        DriveInfo backupDrive = new DriveInfo(Path.GetPathRoot(backupDirectory));
        long requiredBytes = source.TotalBytes + SafetyMarginBytes;
        if (backupDrive.AvailableFreeSpace < requiredBytes)
        {
            throw new IOException(
                "No hay espacio suficiente para proteger la instalacion antes de actualizar. " +
                "Se requieren aproximadamente " + FormatBytes(requiredBytes) + "."
            );
        }

        WriteLog(
            logPath,
            "Creando copia de recuperacion (" + source.FileCount + " archivos, " + FormatBytes(source.TotalBytes) + ")."
        );
        CopyDirectory(installDirectory, backupDirectory);

        DirectorySnapshot backup = MeasureDirectory(backupDirectory);
        string backupExe = Path.Combine(backupDirectory, ApplicationExeName);
        if (
            backup.FileCount != source.FileCount ||
            backup.TotalBytes != source.TotalBytes ||
            !File.Exists(backupExe) ||
            !FilesHaveSameHash(Path.Combine(installDirectory, ApplicationExeName), backupExe)
        )
        {
            DeleteDirectoryQuietly(backupDirectory, logPath);
            throw new IOException("La copia de recuperacion no supero la verificacion de integridad.");
        }

        WriteLog(logPath, "Copia de recuperacion verificada correctamente.");
    }

    private static int RecoverPreviousInstallation(
        string backupDirectory,
        string installDirectory,
        string applicationPath,
        string logPath,
        string reason
    )
    {
        bool restored = false;
        try
        {
            if (IsPerUserInstallation(installDirectory))
            {
                RestoreBackup(backupDirectory, installDirectory, logPath);
                restored = true;
            }
            else
            {
                restored = RunElevatedRecovery(backupDirectory, installDirectory, logPath);
            }
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo restaurar directamente: " + exception.Message);
            restored = RunElevatedRecovery(backupDirectory, installDirectory, logPath);
        }

        if (restored && File.Exists(applicationPath))
        {
            DeleteDirectoryQuietly(backupDirectory, logPath);
            WriteLog(logPath, "La instalacion anterior fue restaurada correctamente.");
            StartApplication(applicationPath, "--update-failed", logPath);
            return 30;
        }

        WriteLog(logPath, "ALERTA: no se pudo restaurar automaticamente. Copia conservada en " + backupDirectory);
        ShowFailure(
            reason + "\n\n" +
            "No fue posible restaurar automaticamente la instalacion. No elimine esta copia de recuperacion:\n" +
            backupDirectory + "\n\n" +
            "Comuniquese con soporte antes de volver a instalar."
        );
        return 31;
    }

    private static bool RunElevatedRecovery(
        string backupDirectory,
        string installDirectory,
        string logPath
    )
    {
        try
        {
            string helperPath = Process.GetCurrentProcess().MainModule.FileName;
            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = helperPath;
            startInfo.Arguments =
                "--restore " + Quote(backupDirectory) + " " + Quote(installDirectory) + " " + Quote(logPath);
            startInfo.UseShellExecute = true;
            startInfo.Verb = "runas";
            startInfo.WindowStyle = ProcessWindowStyle.Normal;

            WriteLog(logPath, "Solicitando permiso de administrador para restaurar la instalacion anterior.");
            using (Process recovery = Process.Start(startInfo))
            {
                if (recovery == null)
                {
                    return false;
                }
                recovery.WaitForExit();
                return recovery.ExitCode == 0;
            }
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "Windows no permitio ejecutar la recuperacion: " + exception.Message);
            return false;
        }
    }

    private static void RestoreBackup(
        string backupDirectory,
        string installDirectory,
        string logPath
    )
    {
        if (!Directory.Exists(backupDirectory) || !File.Exists(Path.Combine(backupDirectory, ApplicationExeName)))
        {
            throw new DirectoryNotFoundException("No se encontro una copia de recuperacion valida.");
        }
        if (!IsSafeInstallationDirectory(installDirectory))
        {
            throw new IOException("La carpeta de instalacion no es segura para restaurar.");
        }

        string quarantineDirectory = installDirectory + ".failed-" + Guid.NewGuid().ToString("N");
        bool movedCurrent = false;
        try
        {
            if (Directory.Exists(installDirectory))
            {
                Directory.Move(installDirectory, quarantineDirectory);
                movedCurrent = true;
            }

            CopyDirectory(backupDirectory, installDirectory);
            DirectorySnapshot source = MeasureDirectory(backupDirectory);
            DirectorySnapshot restored = MeasureDirectory(installDirectory);
            if (
                source.FileCount != restored.FileCount ||
                source.TotalBytes != restored.TotalBytes ||
                !File.Exists(Path.Combine(installDirectory, ApplicationExeName)) ||
                !FilesHaveSameHash(
                    Path.Combine(backupDirectory, ApplicationExeName),
                    Path.Combine(installDirectory, ApplicationExeName)
                )
            )
            {
                throw new IOException("La instalacion restaurada no coincide con la copia protegida.");
            }

            if (movedCurrent)
            {
                DeleteDirectoryQuietly(quarantineDirectory, logPath);
            }
        }
        catch
        {
            try
            {
                if (Directory.Exists(installDirectory))
                {
                    Directory.Delete(installDirectory, true);
                }
                if (movedCurrent && Directory.Exists(quarantineDirectory))
                {
                    Directory.Move(quarantineDirectory, installDirectory);
                }
            }
            catch (Exception rollbackException)
            {
                WriteLog(logPath, "Tambien fallo el retorno de emergencia: " + rollbackException.Message);
            }
            throw;
        }
    }

    private static void CopyDirectory(string sourceDirectory, string destinationDirectory)
    {
        Directory.CreateDirectory(destinationDirectory);
        foreach (string file in Directory.GetFiles(sourceDirectory))
        {
            string destination = Path.Combine(destinationDirectory, Path.GetFileName(file));
            File.Copy(file, destination, true);
            File.SetLastWriteTimeUtc(destination, File.GetLastWriteTimeUtc(file));
        }

        foreach (string directory in Directory.GetDirectories(sourceDirectory))
        {
            FileAttributes attributes = File.GetAttributes(directory);
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new IOException("La instalacion contiene un enlace de carpeta no compatible: " + directory);
            }
            CopyDirectory(directory, Path.Combine(destinationDirectory, Path.GetFileName(directory)));
        }
    }

    private static DirectorySnapshot MeasureDirectory(string directory)
    {
        DirectorySnapshot result = new DirectorySnapshot();
        MeasureDirectory(directory, result);
        return result;
    }

    private static void MeasureDirectory(string directory, DirectorySnapshot result)
    {
        foreach (string file in Directory.GetFiles(directory))
        {
            FileInfo info = new FileInfo(file);
            result.FileCount++;
            result.TotalBytes += info.Length;
        }

        foreach (string child in Directory.GetDirectories(directory))
        {
            FileAttributes attributes = File.GetAttributes(child);
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new IOException("La instalacion contiene un enlace de carpeta no compatible: " + child);
            }
            MeasureDirectory(child, result);
        }
    }

    private static bool HasExpectedVersion(string applicationPath, string expected, string logPath)
    {
        try
        {
            string actual = FileVersionInfo.GetVersionInfo(applicationPath).ProductVersion;
            Version expectedVersion;
            Version actualVersion;
            if (!TryParseVersion(expected, out expectedVersion) || !TryParseVersion(actual, out actualVersion))
            {
                WriteLog(logPath, "No se pudo interpretar la version instalada: " + (actual ?? "sin version"));
                return false;
            }

            bool matches = NormalizeVersion(expectedVersion).Equals(NormalizeVersion(actualVersion));
            if (!matches)
            {
                WriteLog(logPath, "Version esperada=" + expected + "; version encontrada=" + actual);
            }
            return matches;
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo verificar la version del ejecutable: " + exception.Message);
            return false;
        }
    }

    private static bool TryParseVersion(string value, out Version version)
    {
        version = null;
        string clean = (value ?? string.Empty).Trim();
        int separator = clean.IndexOfAny(new char[] { ' ', '+', '-' });
        if (separator > 0)
        {
            clean = clean.Substring(0, separator);
        }
        return Version.TryParse(clean, out version);
    }

    private static Version NormalizeVersion(Version version)
    {
        return new Version(
            Math.Max(version.Major, 0),
            Math.Max(version.Minor, 0),
            Math.Max(version.Build, 0),
            Math.Max(version.Revision, 0)
        );
    }

    private static bool FilesHaveSameHash(string first, string second)
    {
        return string.Equals(FileSha256(first), FileSha256(second), StringComparison.OrdinalIgnoreCase);
    }

    private static string FileSha256(string path)
    {
        using (SHA256 sha = SHA256.Create())
        using (FileStream stream = File.OpenRead(path))
        {
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", string.Empty);
        }
    }

    private static bool IsPerUserInstallation(string installDirectory)
    {
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return IsPathInside(installDirectory, local);
    }

    private static bool IsSafeInstallationDirectory(string installDirectory)
    {
        try
        {
            string full = Path.GetFullPath(installDirectory).TrimEnd(Path.DirectorySeparatorChar);
            string root = Path.GetPathRoot(full).TrimEnd(Path.DirectorySeparatorChar);
            return full.Length > root.Length + 3 && !string.Equals(full, root, StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static bool IsPathInside(string candidate, string parent)
    {
        string fullCandidate = Path.GetFullPath(candidate).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string fullParent = Path.GetFullPath(parent).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        return fullCandidate.StartsWith(fullParent, StringComparison.OrdinalIgnoreCase);
    }

    private static void StopApplicationAtPath(string applicationPath, string logPath)
    {
        foreach (Process process in Process.GetProcessesByName("ToolkitOGM"))
        {
            try
            {
                string runningPath = process.MainModule.FileName;
                if (!string.Equals(Path.GetFullPath(runningPath), Path.GetFullPath(applicationPath), StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                process.CloseMainWindow();
                if (!process.WaitForExit(10000))
                {
                    process.Kill();
                    process.WaitForExit(5000);
                }
                WriteLog(logPath, "Se cerro la instancia iniciada por una instalacion incompleta.");
            }
            catch (Exception exception)
            {
                WriteLog(logPath, "No se pudo cerrar una instancia incompleta: " + exception.Message);
            }
            finally
            {
                process.Dispose();
            }
        }
    }

    private static void StartApplication(string applicationPath, string arguments, string logPath)
    {
        try
        {
            if (!File.Exists(applicationPath))
            {
                return;
            }
            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = applicationPath;
            startInfo.Arguments = arguments;
            startInfo.WorkingDirectory = Path.GetDirectoryName(applicationPath);
            startInfo.UseShellExecute = true;
            Process.Start(startInfo);
            WriteLog(logPath, "Se abrio ToolKit SISMED despues de finalizar el proceso de actualizacion.");
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo volver a abrir ToolKit SISMED: " + exception.Message);
        }
    }

    private static void DeleteDirectoryQuietly(string directory, string logPath)
    {
        try
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, true);
            }
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo limpiar una carpeta temporal: " + exception.Message);
        }
    }

    private static string Quote(string value)
    {
        return "\"" + (value ?? string.Empty).Replace("\"", "\\\"") + "\"";
    }

    private static string FormatBytes(long bytes)
    {
        return (bytes / (1024.0 * 1024.0)).ToString("0") + " MB";
    }

    private static void ShowFailure(string message)
    {
        try
        {
            MessageBox.Show(
                message,
                "Actualizacion de ToolKit SISMED",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
        catch
        {
        }
    }

    private static void WriteLog(string logPath, string message)
    {
        try
        {
            string directory = Path.GetDirectoryName(logPath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            string line = "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] " + message + Environment.NewLine;
            File.AppendAllText(logPath, line, new UTF8Encoding(false));
        }
        catch
        {
        }
    }

    private sealed class DirectorySnapshot
    {
        public long FileCount;
        public long TotalBytes;
    }
}
