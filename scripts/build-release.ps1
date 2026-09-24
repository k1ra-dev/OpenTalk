$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectDir

if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Der Windows-Release-Build unterstützt nur Windows x86_64."
}
if (-not $env:WHISPER_CLI_BINARY -or -not (Test-Path $env:WHISPER_CLI_BINARY)) {
    throw "WHISPER_CLI_BINARY muss auf whisper-cli.exe zeigen."
}
if (-not $env:FFMPEG_BINARY -or -not (Test-Path $env:FFMPEG_BINARY)) {
    throw "FFMPEG_BINARY muss auf ffmpeg.exe zeigen."
}

Remove-Item -Recurse -Force build/OpenTalk, build/OpenTalk-binaries, dist/OpenTalk, artifacts `
    -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force build/OpenTalk-binaries, artifacts | Out-Null
Copy-Item $env:WHISPER_CLI_BINARY build/OpenTalk-binaries/whisper-cli.exe
Copy-Item $env:FFMPEG_BINARY build/OpenTalk-binaries/ffmpeg.exe
$env:WHISPER_CLI_BINARY = Join-Path $projectDir "build/OpenTalk-binaries/whisper-cli.exe"
$env:FFMPEG_BINARY = Join-Path $projectDir "build/OpenTalk-binaries/ffmpeg.exe"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $env:TEMP "opentalk-pyinstaller-cache"

python -m PyInstaller --clean --noconfirm packaging/OpenTalk.spec
Compress-Archive -Path dist/OpenTalk -DestinationPath artifacts/OpenTalk-Windows-x86_64.zip -Force
Get-Item artifacts/OpenTalk-Windows-x86_64.zip | Format-List Name, Length
