$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$configFile = Join-Path $projectDir "config.local.ps1"
if (Test-Path $configFile) { . $configFile }
$python = $env:OPENTALK_PYTHON
if (-not $python) { $python = Join-Path $projectDir ".venv/Scripts/pythonw.exe" }
if (-not (Test-Path $python)) {
    throw "Python-Umgebung fehlt. Zuerst scripts/install-windows.ps1 ausführen."
}
& $python (Join-Path $projectDir "opentalk_gui.py")
