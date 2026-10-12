"""Build release artifacts for the current platform.

    uv run python scripts/build.py                 # PyInstaller build + portable archive
    uv run python scripts/build.py --installer     # Windows: also the Inno Setup installer
    uv run python scripts/build.py --appimage      # Linux: also the AppImage

Artifacts are written to ``release/``:

* Windows: ``KCDModManager-<ver>-windows-x64-portable.zip`` and ``...-setup.exe``
* Linux:   ``KCDModManager-<ver>-linux-x86_64.tar.gz`` and ``...-x86_64.AppImage``
* ``SHA256SUMS-<platform>.txt``
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
RELEASE = ROOT / "release"
APP_DIR = DIST / "KCDModManager"
SPEC = ROOT / "packaging" / "pyinstaller" / "kcd_mod_manager.spec"
LINUX = ROOT / "packaging" / "linux"
IS_WINDOWS = sys.platform == "win32"


def version() -> str:
    text = (ROOT / "src" / "kcd_mod_manager" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    if not match:
        raise SystemExit("version not found")
    return match.group(1)


def run(cmd: list[str], **kwargs: object) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kwargs)  # type: ignore[call-overload]


def pyinstaller() -> None:
    shutil.rmtree(APP_DIR, ignore_errors=True)
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "pyinstaller"),
            str(SPEC),
        ]
    )


def executable() -> Path:
    return APP_DIR / ("KCDModManager.exe" if IS_WINDOWS else "KCDModManager")


def self_test() -> None:
    report = BUILD / "self-test.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [str(executable()), "--self-test", "--self-test-report", str(report)],
        env=env,
        timeout=180,
        check=False,
    )
    print(report.read_text(encoding="utf-8") if report.exists() else "(no self-test report)")
    if result.returncode != 0:
        raise SystemExit(f"Self-test of the frozen build failed (exit code {result.returncode}).")


def portable_zip(ver: str) -> Path:
    target = RELEASE / f"KCDModManager-{ver}-windows-x64-portable.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, Path("KCDModManager") / path.relative_to(APP_DIR))
    return target


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    name = Path(info.name).name
    if info.isdir() or name in ("KCDModManager", "install-desktop-entry.sh") or name.endswith(".so"):
        info.mode = 0o755
    elif info.isfile():
        info.mode = 0o644
    return info


def linux_tarball(ver: str) -> Path:
    target = RELEASE / f"KCDModManager-{ver}-linux-x86_64.tar.gz"
    target.unlink(missing_ok=True)
    for extra in ("kcd-mod-manager.desktop", "kcd-mod-manager.png", "install-desktop-entry.sh"):
        shutil.copy2(LINUX / extra, APP_DIR / extra)
    with tarfile.open(target, "w:gz") as tar:
        tar.add(APP_DIR, arcname=f"KCDModManager-{ver}", filter=_tar_filter)
    return target


def inno_compiler() -> str:
    candidates = [
        shutil.which("iscc"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
        os.path.expandvars(r"%ProgramFiles%\Inno Setup 6\ISCC.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise SystemExit("Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isinfo.php")


def windows_installer(ver: str) -> Path:
    run(
        [
            inno_compiler(),
            "/Q",
            f"/DAppVersion={ver}",
            f"/DSourceDir={APP_DIR}",
            f"/DOutputDir={RELEASE}",
            str(ROOT / "packaging" / "windows" / "installer.iss"),
        ]
    )
    return RELEASE / f"KCDModManager-{ver}-windows-x64-setup.exe"


def appimage(ver: str) -> Path:
    tool = os.environ.get("APPIMAGETOOL") or shutil.which("appimagetool")
    if not tool:
        raise SystemExit("appimagetool not found (set APPIMAGETOOL or put it on PATH).")
    appdir = BUILD / "AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(APP_DIR, appdir / "usr" / "lib" / "kcd-mod-manager", symlinks=True)
    shutil.copy2(LINUX / "AppRun", appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)
    shutil.copy2(LINUX / "kcd-mod-manager.desktop", appdir / "kcd-mod-manager.desktop")
    shutil.copy2(LINUX / "kcd-mod-manager.png", appdir / "kcd-mod-manager.png")
    icons = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icons.mkdir(parents=True)
    shutil.copy2(LINUX / "kcd-mod-manager.png", icons / "kcd-mod-manager.png")
    exe = appdir / "usr" / "lib" / "kcd-mod-manager" / "KCDModManager"
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    target = RELEASE / f"KCDModManager-{ver}-x86_64.AppImage"
    target.unlink(missing_ok=True)
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    run([tool, "--no-appstream", str(appdir), str(target)], env=env)
    return target


def checksums(files: list[Path], label: str) -> Path:
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    target = RELEASE / f"SHA256SUMS-{label}.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--installer", action="store_true", help="Windows: build the Inno Setup installer")
    parser.add_argument("--appimage", action="store_true", help="Linux: build the AppImage")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="reuse dist/KCDModManager")
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args()

    ver = version()
    RELEASE.mkdir(exist_ok=True)
    if not args.skip_pyinstaller:
        pyinstaller()
    if not executable().is_file():
        raise SystemExit(f"Build output missing: {executable()}")
    if not args.skip_self_test:
        self_test()

    artifacts: list[Path] = []
    if IS_WINDOWS:
        artifacts.append(portable_zip(ver))
        if args.installer:
            artifacts.append(windows_installer(ver))
        label = "windows"
    else:
        artifacts.append(linux_tarball(ver))
        if args.appimage:
            artifacts.append(appimage(ver))
        label = f"linux-{platform.machine()}"
    artifacts.append(checksums(artifacts, label))
    for artifact in artifacts:
        print(f"{artifact.relative_to(ROOT)}  ({artifact.stat().st_size / 1_048_576:.1f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
