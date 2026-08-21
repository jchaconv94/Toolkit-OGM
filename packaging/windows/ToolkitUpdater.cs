using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

internal static class ToolkitUpdater
{
    private const int ParentWaitMilliseconds = 20000;
    private const string InstallerArguments =
        "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART " +
        "/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /AUTOUPDATE";

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length < 3)
        {
            return 10;
        }

        string installerPath = Path.GetFullPath(args[0]);
        string logPath = Path.GetFullPath(args[2]);
        int parentProcessId;

        if (!int.TryParse(args[1], out parentProcessId))
        {
            WriteLog(logPath, "No se recibio un identificador valido para ToolKit SISMED.");
            return 11;
        }

        if (!File.Exists(installerPath))
        {
            WriteLog(logPath, "No se encontro el instalador descargado: " + installerPath);
            return 12;
        }

        WriteLog(logPath, "Auxiliar iniciado. Esperando el cierre de ToolKit SISMED (PID=" + parentProcessId + ").");
        WaitForParent(logPath, parentProcessId);
        Thread.Sleep(750);

        try
        {
            WriteLog(logPath, "Solicitando a Windows permiso para instalar la actualizacion.");
            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = installerPath;
            startInfo.Arguments = InstallerArguments;
            startInfo.WorkingDirectory = Path.GetDirectoryName(installerPath);
            startInfo.UseShellExecute = true;
            startInfo.Verb = "runas";
            startInfo.WindowStyle = ProcessWindowStyle.Normal;
            Process.Start(startInfo);
            WriteLog(logPath, "La solicitud de instalacion fue enviada correctamente a Windows.");
            return 0;
        }
        catch (Win32Exception exception)
        {
            WriteLog(logPath, "Windows no permitio abrir el instalador: " + exception.Message);
            return 20;
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo abrir el instalador: " + exception.Message);
            return 21;
        }
    }

    private static void WaitForParent(string logPath, int parentProcessId)
    {
        try
        {
            Process parent = Process.GetProcessById(parentProcessId);
            if (parent.HasExited || parent.WaitForExit(ParentWaitMilliseconds))
            {
                WriteLog(logPath, "ToolKit SISMED se cerro correctamente.");
                return;
            }

            WriteLog(
                logPath,
                "ToolKit SISMED sigue activo despues de 20 segundos. " +
                "El instalador intentara cerrarlo de forma segura."
            );
        }
        catch (ArgumentException)
        {
            WriteLog(logPath, "ToolKit SISMED ya estaba cerrado.");
        }
        catch (Exception exception)
        {
            WriteLog(logPath, "No se pudo comprobar el cierre de ToolKit SISMED: " + exception.Message);
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
}
