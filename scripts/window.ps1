# window.ps1 - Window activation + app launch + key sending + paste
param(
    [string]$Action,
    [string]$ProcessName,
    [string]$Keys,
    [string]$Text,
    [string]$AppTitle
)

$ErrorActionPreference = "SilentlyContinue"

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

# 预定义 app name -> exe 路径映射
$AppPaths = @{
    "cursor"  = "$env:LOCALAPPDATA\Cursor\Cursor.exe"
    "vscode"  = "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe"
    "claude"  = "$env:APPDATA\Claude\Claude.exe"
    "browser" = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    "edge"    = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    "chrome"  = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    "firefox" = "C:\Program Files\Mozilla Firefox\firefox.exe"
}

function Do-Launch {
    param([string]$AppName)
    $path = $null
    if ($AppPaths.ContainsKey($AppName)) {
        $path = $AppPaths[$AppName]
    }
    if (-not $path -or -not (Test-Path $path)) {
        $found = Get-Command "$AppName.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $path = $found.Source }
    }
    if ($path -and (Test-Path $path)) {
        Start-Process $path
        @{success=$true; method="launch"; target=$path} | ConvertTo-Json -Compress
    } else {
        @{success=$false; error="App not found: $AppName"} | ConvertTo-Json -Compress
    }
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

function Do-GotoChat {
    param([string]$T)
    # 1. 激活目标窗口
    Do-Activate -Title $T | Out-Null
    # 2. 按 Tab 若干次定位到聊天输入框（通常在顶部 Tab 之后第一个输入区）
    Start-Sleep -Milliseconds 150
    $wshell = New-Object -ComObject WScript.Shell
    # QClaw webchat: Tab x5 通常能定位到消息输入框
    $wshell.SendKeys("{TAB}{TAB}{TAB}{TAB}{TAB}")
    Start-Sleep -Milliseconds 100
    @{"success"=$true;"method"="goto-chat";"target"=$T} | ConvertTo-Json -Compress
}

function Do-GotoChatPaste {
    param([string]$T, [string]$Text)
    # 1. 激活目标窗口
    Do-Activate -Title $T | Out-Null
    Start-Sleep -Milliseconds 150
    # 2. Tab 定位到输入框
    $wshell = New-Object -ComObject WScript.Shell
    $wshell.SendKeys("{TAB}{TAB}{TAB}{TAB}{TAB}")
    Start-Sleep -Milliseconds 100
    # 3. 粘贴语音内容
    Set-Clipboard -Value $Text -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 80
    $wshell.SendKeys("^v")
    @{"success"=$true;"method"="goto-chat-paste";"target"=$T;"textLength"=$Text.Length} | ConvertTo-Json -Compress
}

switch ($Action) {
    "activate"      { Do-Activate -ProcName $ProcessName -Title $AppTitle }
    "launch"        { Do-Launch -AppName $ProcessName }
    "sendkeys"      { Do-SendKeys -K $Keys }
    "paste"         { Do-Paste -T $Text }
    "goto-chat"     { Do-GotoChat -T $AppTitle }
    "goto-chat-paste" { Do-GotoChatPaste -T $AppTitle -Text $Text }
    default         { @{"error"="Unknown action: $Action"} | ConvertTo-Json -Compress }
}
