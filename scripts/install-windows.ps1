$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT" -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Dieser Installer unterstützt Windows x86_64."
}
$projectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venv = Join-Path $projectDir ".venv"
python -c "import sys; raise SystemExit(sys.version_info < (3, 10) or sys.maxsize <= 2**32)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 oder neuer (x64) muss im PATH installiert sein." }
python -m venv $venv
if ($LASTEXITCODE -ne 0) { throw "Python-Umgebung konnte nicht erstellt werden." }
$python = Join-Path $venv "Scripts/python.exe"
& $python -m pip install -r (Join-Path $projectDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Python-Abhängigkeiten konnten nicht installiert werden." }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Programs")) "OpenTalk.lnk"))
$shortcut.TargetPath = Join-Path $env:SystemRoot "System32/WindowsPowerShell/v1.0/powershell.exe"
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $projectDir "scripts/gui.ps1") + '"'
$shortcut.WorkingDirectory = $projectDir
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Host "OpenTalk ist im Startmenü. Der Starter nutzt direkt diesen Checkout."
Write-Host "Für die lokale Erkennung: Git, CMake und Visual Studio C++ Build Tools installieren (README)."
Write-Host "Danach im Programm unter Einstellungen die Erkennung einrichten."
