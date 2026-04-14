# window.ps1 - Window activation + key sending + paste
param(
    [string]$Action,
    [string]$ProcessName,
    [string]$Keys,
    [string]$Text,
    [string]$AppTitle
)

$ErrorActionPreference = "SilentlyContinue"

function Do-Activate {
    param([string]$ProcName, [string]$Title)
    $out = @{}
    $proc = $null
    if ($ProcName) {
        $p2 = $ProcName -replace '\.exe$',''
        $proc = Get-Process -Name $p2 -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($proc) {
        [Microsoft.VisualBasic.Interaction]::AppActivate($proc.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 100
        $out.success = $true
        $out.method = "process"
        $out.target = $proc.Name
    } elseif ($Title) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win32 {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int count);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
}
"@
        $found = $false
        $script:counter = 0
        $cb = [Win32+EnumProc]{
            param($h,$p)
            if ([Win32]::IsWindowVisible($h)) {
                $sb = New-Object System.Text.StringBuilder 256
                [Win32]::GetWindowText($h, $sb, 256) | Out-Null
                if ($sb.ToString() -like "*$Title*") {
                    [Microsoft.VisualBasic.Interaction]::AppActivate($h) | Out-Null
                    $script:counter++
                }
            }
            return $true
        }
        [Win32]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
        if ($script:counter -gt 0) {
            $out.success = $true
            $out.method = "title"
            $out.target = $Title
        } else {
            $out.success = $false
            $out.error = "Window not found"
        }
    } else {
        $out.success = $false
        $out.error = "No process or title specified"
    }
    $out | ConvertTo-Json -Compress
}

function Do-SendKeys {
    param([string]$K)
    $wshell = New-Object -ComObject WScript.Shell
    $wshell.SendKeys($K)
    @{"success"=$true;"keys"=$K} | ConvertTo-Json -Compress
}

function Do-Paste {
    param([string]$T)
    Set-Clipboard -Value $T -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 80
    $wshell = New-Object -ComObject WScript.Shell
    $wshell.SendKeys("^v")
    @{"success"=$true;"textLength"=$T.Length} | ConvertTo-Json -Compress
}

switch ($Action) {
    "activate" { Do-Activate -ProcName $ProcessName -Title $AppTitle }
    "sendkeys" { Do-SendKeys -K $Keys }
    "paste"    { Do-Paste -T $Text }
    default    { @{"error"="Unknown action: $Action"} | ConvertTo-Json -Compress }
}
