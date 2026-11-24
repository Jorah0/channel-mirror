# Builds dist\ChannelMirror.exe (single file, no console). Run from this folder:  .\build.ps1
# The Android app (dist\ChannelMirror-Remote.apk, from .\build-apk.ps1) goes inside when it's built, so the exe offers it.
python -m pip install --quiet pyinstaller numpy
$apk = @()
if ((Test-Path dist\ChannelMirror-Remote.apk) -and (Test-Path dist\ChannelMirror-Remote.apk.json)) {
    $apk = "--add-data", "dist\ChannelMirror-Remote.apk;.", "--add-data", "dist\ChannelMirror-Remote.apk.json;."
    Write-Host "Bundling the Android app: $((Get-Content dist\ChannelMirror-Remote.apk.json -Raw).Trim())"
} else { Write-Host "No Android app in dist\ (.\build-apk.ps1): the exe won't offer one" }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ChannelMirror `
    --icon icon.ico --add-data "icon.ico;." --add-data "icon.png;." @apk --exclude-module cv2 channel_mirror.py  # cv2: only the selftest's optional QR read-back
if ($LASTEXITCODE -eq 0) { Write-Host "Built: $PWD\dist\ChannelMirror.exe" }
