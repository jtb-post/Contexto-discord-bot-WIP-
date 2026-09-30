# Creates the "Contexto Bot" desktop shortcut. Run by "Create Desktop Shortcut.bat".
#
# Uses the Unicode shell-link API (IShellLinkW) instead of WScript.Shell, which
# turns non-English characters in a path (e.g. a Cyrillic or Chinese username, or
# a translated OneDrive folder) into "?" and then fails with "file not found".
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$dir = $PSScriptRoot
$target = Join-Path $dir 'Start Contexto.bat'
$icon = Join-Path $dir 'assets\contexto.ico'

# Double-clicking inside a .zip runs a temporary copy with nothing next to it.
$temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if ($dir.StartsWith($temp.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host 'This is running from a temporary folder, probably inside a .zip.'
    Write-Host 'Right-click the .zip, choose Extract All, then run this from the extracted folder.'
    exit 1
}
foreach ($file in @($target, $icon)) {
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Host "Missing file: $file"
        Write-Host 'Download the project again and extract the whole .zip.'
        exit 1
    }
}

$desktop = [Environment]::GetFolderPath('Desktop')
if (-not $desktop -or -not (Test-Path -LiteralPath $desktop)) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }
$lnk = Join-Path $desktop 'Contexto Bot.lnk'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int cch, IntPtr findData, uint flags);
    void GetIDList(out IntPtr pidl);
    void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
    void GetHotkey(out short hotkey);
    void SetHotkey(short hotkey);
    void GetShowCmd(out int showCmd);
    void SetShowCmd(int showCmd);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int cch, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string rel, uint reserved);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
}

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
class ShellLink {}

public static class ContextoShortcut {
    public static void Create(string lnk, string target, string workDir, string icon, string description) {
        var link = (IShellLinkW)new ShellLink();
        link.SetPath(target);
        link.SetWorkingDirectory(workDir);
        link.SetIconLocation(icon, 0);
        link.SetDescription(description);
        ((IPersistFile)link).Save(lnk, true);
    }

    public static string[] Read(string lnk) {
        var link = (IShellLinkW)new ShellLink();
        ((IPersistFile)link).Load(lnk, 0);
        var target = new StringBuilder(1024);
        var icon = new StringBuilder(1024);
        int index;
        link.GetPath(target, target.Capacity, IntPtr.Zero, 0);
        link.GetIconLocation(icon, icon.Capacity, out index);
        return new[] { target.ToString(), icon.ToString() };
    }
}
'@

[ContextoShortcut]::Create($lnk, $target, $dir, $icon, 'Start the Contexto Discord bot')

# Read it back to be sure nothing was lost on the way.
$saved = [ContextoShortcut]::Read($lnk)
if ($saved[0] -ne $target -or $saved[1] -ne $icon) {
    Write-Host "The shortcut was saved with the wrong path: $($saved[0])"
    exit 1
}
Write-Host "Added ""Contexto Bot"" to $desktop. Double-click it to start the bot."
