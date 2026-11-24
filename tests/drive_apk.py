"""The Android app (CM Remote) as build-apk.ps1 makes it: dist/ChannelMirror-Remote.apk checked with the Android SDK's own
tools - apksigner verify (v2/v3 signed; by this PC's release key when that's here) and aapt2 dump badging (package,
versionCode = its .json, min SDK 26, the target SDK, ONLY the INTERNET and REQUEST_INSTALL_PACKAGES permissions) - and
its contents (the code, the icon, the web app's files under assets/web/ named by their hashes, nothing else).
SKIPPED (exit 0, says so) where the Android SDK or a JDK isn't installed, or no APK has been built: other PCs aren't
broken by it. It never builds or signs anything itself.
Usage: python -u drive_apk.py <repo>"""
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(REPO))
APK = REPO / "dist" / "ChannelMirror-Remote.apk"
PKG = "io.github.jorah0.cmremote"


def skip(why):
    print(f"SKIPPED: {why}")
    sys.exit(0)


def newest(d):
    def ver(p):
        return [int(x) for x in re.findall(r"\d+", p.name)]
    return max((p for p in d.iterdir() if p.is_dir() and re.match(r"^(android-)?\d", p.name)), key=ver, default=None) \
        if d.is_dir() else None


sdk = next((Path(p) for p in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                               Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk")
            if p and (Path(p) / "build-tools").is_dir()), None)
jdk = next((p for p in [os.environ.get("JAVA_HOME")] + [str(q) for base in (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft", Path(os.environ.get("ProgramFiles", "")) /
    "Microsoft") if base.is_dir() for q in sorted(base.glob("jdk*"), reverse=True)] if p and (
    Path(p) / "bin" / "java.exe").is_file()), None)
if not sdk or not newest(sdk / "build-tools") or not newest(sdk / "platforms"):
    skip("the Android SDK isn't installed here (README: Android app) - the APK isn't checked")
if not jdk:
    skip("no JDK here (README: Android app) - the APK isn't checked")
if not APK.is_file():
    skip(f"no {APK.relative_to(REPO)} - run .\\build-apk.ps1 to build it, then this checks it")
bt = newest(sdk / "build-tools")
env = {**os.environ, "JAVA_HOME": jdk, "PATH": str(Path(jdk) / "bin") + os.pathsep + os.environ.get("PATH", "")}


def tool(*cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, (cmd[0], r.returncode, r.stdout[-2000:], r.stderr[-2000:])
    return r.stdout


# signed: v2 / v3 (Android 7+), one signer; by this PC's release key when it's here
out = tool(bt / "apksigner.bat", "verify", "--verbose", "--print-certs", APK)
print(out.strip())
assert out.startswith("Verifies") and "(APK Signature Scheme v2): true" in out and "(APK Signature Scheme v3): true" in out
assert "Number of signers: 1" in out
cert = re.search(r"certificate SHA-256 digest: ([0-9a-f]{64})", out)[1]
keys = Path(os.environ.get("LOCALAPPDATA", "")) / "ChannelMirror" / "android"
if (keys / "release.p12").is_file():
    from cmlib.core import secret_read
    pw = secret_read((keys / "release-password.txt").read_text())
    assert pw, "the release key's password can't be read here"
    env["CM_KS_PASS"] = pw  # (to keytool by its environment, never on a command line)
    try:
        listed = tool(Path(jdk) / "bin" / "keytool.exe", "-list", "-v", "-keystore", keys / "release.p12",
                      "-storetype", "PKCS12", "-storepass:env", "CM_KS_PASS")
    finally:
        env.pop("CM_KS_PASS")
    fp = re.search(r"SHA256: ([0-9A-F:]{95})", listed)[1].replace(":", "").lower()
    assert fp == cert, (fp, cert)
    print("signed by this PC's release key")
else:
    print("this PC has no release key: the signer isn't compared")

# the manifest as Android reads it
badging = tool(bt / "aapt2.exe", "dump", "badging", APK)
print(badging.strip())
info = json.loads(APK.with_name(APK.name + ".json").read_text())
m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
assert m and m[1] == PKG and int(m[2]) == info["code"] and m[3] == info["name"], (m and m.groups(), info)
from cmlib.remote import remote_apk_name, remote_web  # noqa: E402 (after the skips: needs nothing installed)
assert remote_apk_name(info["code"]) == info["name"]
assert info.get("cert") == cert, (info.get("cert"), cert)  # the key the PC page tells the user to compare
assert "minSdkVersion:'26'" in badging
target = int(re.search(r"targetSdkVersion:'(\d+)'", badging)[1])
assert target >= 35, target  # Google Play's floor; build-apk.ps1 targets the newest platform installed
perms = set(re.findall(r"uses-permission: name='([^']+)'", badging))
assert perms == {"android.permission.INTERNET", "android.permission.REQUEST_INSTALL_PACKAGES"}, perms
assert f"launchable-activity: name='{PKG}.MainActivity'" in badging

# its contents: the code, the icon, the web app (each file named by its hash, as listed) - nothing else
with zipfile.ZipFile(APK) as z:
    names = z.namelist()
    raw = [i.orig_filename for i in z.infolist()]  # (as stored: zipfile shows "\" as "/" on Windows)
    assert all("\\" not in n for n in raw), [n for n in raw if "\\" in n]  # Android reads "/" only
    web = json.loads(z.read("assets/web/manifest.json"))
    for p, f in web["files"].items():
        assert hashlib.sha256(z.read(f"assets/web/{f['sha256']}")).hexdigest() == f["sha256"], p
    expect = {"AndroidManifest.xml", "classes.dex", "resources.arsc", "assets/web/manifest.json",
              *(f"assets/web/{f['sha256']}" for f in web["files"].values())}
    extra = {n for n in names if n not in expect and not n.startswith(("META-INF/", "res/mipmap-"))}
    assert not extra and expect <= set(names), (extra, expect - set(names))
assert set(web["files"]) == set(remote_web()["files"]) and web["version"] == info["web"]
now = remote_web()["version"]
print(f"screens bundled: {web['version']}" + ("" if web["version"] == now else
      f" (the PC's are {now} now: phones get those over the link; rebuild to bundle them)"))
print(f"apk ok: {PKG} {info['name']} (code {info['code']}), min SDK 26, target {target}, INTERNET + "
      f"REQUEST_INSTALL_PACKAGES only, {APK.stat().st_size // 1024} KB")
