# PyInstaller spec for KCD Mod Manager (one-folder build; used for the portable ZIP, the
# Windows installer, the Linux tarball and the AppImage).
#
#   uv run pyinstaller --noconfirm --clean packaging/pyinstaller/kcd_mod_manager.spec

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH).resolve()  # noqa: F821 - provided by PyInstaller
ROOT = HERE.parents[1]
SRC = ROOT / "src"
PKG = SRC / "kcd_mod_manager"
RES = PKG / "resources"

VERSION = re.search(r'__version__ = "([^"]+)"', (PKG / "__init__.py").read_text(encoding="utf-8")).group(1)
IS_WINDOWS = sys.platform == "win32"

version_file = None
if IS_WINDOWS:
    parts = [int(p) for p in re.findall(r"\d+", VERSION)[:4]]
    parts += [0] * (4 - len(parts))
    numbers = ", ".join(str(p) for p in parts)
    version_file = Path(workpath) / "version_info.txt"  # noqa: F821 - provided by PyInstaller
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numbers}), prodvers=({numbers}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'KCD Mod Manager contributors'),
      StringStruct('FileDescription', 'KCD Mod Manager'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'KCDModManager'),
      StringStruct('LegalCopyright', 'GPL-3.0-only'),
      StringStruct('OriginalFilename', 'KCDModManager.exe'),
      StringStruct('ProductName', 'KCD Mod Manager'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )

datas = [
    (str(RES / "i18n"), "kcd_mod_manager/resources/i18n"),
    (str(RES / "images"), "kcd_mod_manager/resources/images"),
    (str(RES / "icons"), "kcd_mod_manager/resources/icons"),
    (str(ROOT / "LICENSE"), "."),
]

hiddenimports = [
    *collect_submodules("keyring.backends"),
    *collect_submodules("kcd_mod_manager"),
]

excludes = [
    "tkinter",
    "unittest",
    "pydoc",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
]

a = Analysis(  # noqa: F821
    [str(HERE / "entry.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KCDModManager",
    console=False,
    icon=str(RES / "images" / "logo.ico") if IS_WINDOWS else None,
    version=str(version_file) if version_file else None,
    upx=False,
    strip=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="KCDModManager",
    upx=False,
    strip=False,
)
