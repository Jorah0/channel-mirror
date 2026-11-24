# Builds dist\ChannelMirror-Remote.apk: the phone remote as an Android app (CM Remote, android\), no Gradle - javac, d8,
# aapt2, zipalign, apksigner from a JDK 17+ and the Android SDK. Run from this folder:  .\build-apk.ps1
# The release key is made once in %LOCALAPPDATA%\ChannelMirror\android\ (never in the repo), its password sealed for
# this Windows user (DPAPI). BACK THAT FOLDER UP: without the key, installed phones can't be updated.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
function Check($what) { if ($LASTEXITCODE) { throw "$what failed (exit code $LASTEXITCODE)" } }
function Newest($dir, $filter) { Get-ChildItem $dir -Directory -Filter $filter -ErrorAction SilentlyContinue |
    Sort-Object { [version](($_.Name -replace '^[^\d]*', '') -replace '[^\d.].*$', '') } | Select-Object -Last 1 }

# the tools: found, never installed or put on PATH here (only this run's own PATH)
$jdk = @($env:JAVA_HOME) + @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Microsoft", "$env:ProgramFiles\Microsoft",
    "$env:ProgramFiles\Java", "$env:ProgramFiles\Eclipse Adoptium" -Directory -Filter "jdk*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | ForEach-Object FullName) | Where-Object { $_ -and (Test-Path "$_\bin\javac.exe") } |
    Select-Object -First 1
$sdk = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, "$env:LOCALAPPDATA\Android\Sdk") |
    Where-Object { $_ -and (Test-Path "$_\build-tools") } | Select-Object -First 1
if (-not $jdk) { throw "No JDK 17+ found (winget install Microsoft.OpenJDK.17) - see README, Android app" }
if (-not $sdk) { throw "No Android SDK found in %LOCALAPPDATA%\Android\Sdk - see README, Android app" }
$plat = Get-ChildItem "$sdk\platforms" -Directory | Where-Object { $_.Name -match '^android-\d+(\.\d+)?$' -and (Test-Path "$($_.FullName)\android.jar") } |
    Sort-Object { [version](($_.Name -replace 'android-', '') + '.0' -replace '^(\d+\.\d+).*', '$1') } | Select-Object -Last 1
$bt = (Newest "$sdk\build-tools" "*").FullName
if (-not $plat -or -not $bt) { throw "The Android SDK needs a platform and build-tools (sdkmanager) - see README" }
$jar = "$($plat.FullName)\android.jar"
$target = [int](($plat.Name -replace 'android-', '') -replace '\..*', '')
$env:JAVA_HOME = $jdk
$env:Path = "$jdk\bin;$env:Path"

# the release key and its password (sealed with secret_keep, read with secret_read - cmlib\core.py)
$keys = "$env:LOCALAPPDATA\ChannelMirror\android"
$ks, $passFile, $buildFile = "$keys\release.p12", "$keys\release-password.txt", "$keys\build-number.txt"
New-Item -ItemType Directory -Force $keys | Out-Null
Push-Location $root
try {
    if (-not (Test-Path $ks)) {
        $env:CM_KS_PASS = python -c "import secrets, sys; from cmlib.core import secret_keep; p = secrets.token_urlsafe(32); open(sys.argv[1], 'w').write(secret_keep(p)); print(p)" $passFile
        if ($LASTEXITCODE -or -not $env:CM_KS_PASS) { throw "Couldn't make the key's password" }
        & keytool -genkeypair -keystore $ks -storetype PKCS12 -alias cmremote -keyalg RSA -keysize 3072 `
            -validity 10950 -dname "CN=Channel Mirror Remote" -storepass:env CM_KS_PASS -keypass:env CM_KS_PASS
        Check "keytool"
        Write-Host "NEW release key: $ks. Back up release.p12 AND its password (README: Android app > Backing up the key -" -ForegroundColor Yellow
        Write-Host "the sealed password file only opens for this Windows user on this PC). Without both, installed phones can't be updated." -ForegroundColor Yellow
    } else {
        $env:CM_KS_PASS = python -c "import sys; from cmlib.core import secret_read; p = secret_read(open(sys.argv[1]).read()); print(p or '')" $passFile
        if (-not $env:CM_KS_PASS -and $env:CM_RELEASE_PASSWORD) {  # a restored key: its backed-up password, sealed again here
            $env:CM_KS_PASS = $env:CM_RELEASE_PASSWORD
            python -c "import os, sys; from cmlib.core import secret_keep; open(sys.argv[1], 'w').write(secret_keep(os.environ['CM_KS_PASS']))" $passFile
            Check "sealing the password"
        }
        if (-not $env:CM_KS_PASS) { throw "Can't read the key's password in $passFile (restored from another PC or user? set CM_RELEASE_PASSWORD to its backed-up password once - README)" }
    }

    # the version: VERSION (cmlib\install.py) + a build number kept with the key
    $build = 1 + [int](Get-Content $buildFile -ErrorAction SilentlyContinue)
    $code, $name = (python -c "import sys; from cmlib.install import VERSION; from cmlib.remote import remote_apk_version; print(*remote_apk_version(VERSION, int(sys.argv[1])))" $build) -split ' '
    if ($LASTEXITCODE -or -not $name) { throw "Couldn't work out the version" }

    $b = "$root\android\build"
    if (Test-Path $b) { Remove-Item -Recurse -Force $b }
    New-Item -ItemType Directory -Force "$b\classes", "$b\dex", "$b\assets\web" | Out-Null
    # the web app's files, as the PC serves them now (named by their SHA-256, listed in manifest.json)
    $web = python -c "import sys; from cmlib.remote import remote_export_web; print(remote_export_web(sys.argv[1]))" "$b\assets\web"
    if ($LASTEXITCODE) { throw "Couldn't export the web app" }

    & "$bt\aapt2.exe" compile --dir "$root\android\res" -o "$b\res.zip"; Check "aapt2 compile"
    & "$bt\aapt2.exe" link -I $jar --manifest "$root\android\AndroidManifest.xml" -o "$b\unsigned.apk" `
        --min-sdk-version 26 --target-sdk-version $target --version-code $code --version-name $name "$b\res.zip"
    Check "aapt2 link"
    & javac --release 11 -encoding UTF-8 -Xlint:-options -cp $jar -d "$b\classes" `
        @((Get-ChildItem "$root\android\src" -Recurse -Filter *.java).FullName); Check "javac"
    & "$bt\d8.bat" --release --min-api 26 --lib $jar --output "$b\dex" `
        @((Get-ChildItem "$b\classes" -Recurse -Filter *.class).FullName); Check "d8"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::Open("$b\unsigned.apk", "Update")
    try {  # the code, and the web app as assets/web/... (added here: aapt2 -A stores "\" in names on Windows)
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, "$b\dex\classes.dex", "classes.dex")
        foreach ($f in Get-ChildItem "$b\assets\web" -File) {
            [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $f.FullName, "assets/web/$($f.Name)")
        }
    } finally { $z.Dispose() }
    & "$bt\zipalign.exe" -p -f 4 "$b\unsigned.apk" "$b\aligned.apk"; Check "zipalign"
    New-Item -ItemType Directory -Force "$root\dist" | Out-Null
    $apk = "$root\dist\ChannelMirror-Remote.apk"
    & "$bt\apksigner.bat" sign --ks $ks --ks-key-alias cmremote --ks-pass env:CM_KS_PASS --key-pass env:CM_KS_PASS `
        --out $apk "$b\aligned.apk"; Check "apksigner sign"
    $certs = & "$bt\apksigner.bat" verify --print-certs $apk; Check "apksigner verify"
    $cert = ([regex]::Match(($certs -join "`n"), 'certificate SHA-256 digest: ([0-9a-f]{64})')).Groups[1].Value
    # what the PC offers phones (cmlib\remote.py remote_apk): the version and signing key, next to the APK
    Set-Content "$apk.json" "{`"code`": $code, `"name`": `"$name`", `"web`": `"$web`", `"cert`": `"$cert`"}" -Encoding ASCII
    Set-Content $buildFile $build
    Remove-Item -Recurse -Force $b
    Write-Host "Built: $apk  ($name, code $code, $([math]::Round((Get-Item $apk).Length / 1KB)) KB, target SDK $target, screens $web)"
} finally {
    Remove-Item Env:CM_KS_PASS -ErrorAction SilentlyContinue
    Pop-Location
}
