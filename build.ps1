# Builds dist\ChannelMirror.exe (single file, no console). Run from this folder:  .\build.ps1
python -m pip install --quiet pyinstaller numpy
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ChannelMirror `
    --icon icon.ico --add-data "icon.ico;." --add-data "icon.png;." --exclude-module cv2 channel_mirror.py  # cv2: only the selftest's optional QR read-back
if ($LASTEXITCODE -eq 0) { Write-Host "Built: $PWD\dist\ChannelMirror.exe" }
