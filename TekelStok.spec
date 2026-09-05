# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması.

Tek bir spec iki çıktı üretebilir; ``TEKEL_ONEFILE`` ortam değişkeni belirler:
  * onedir  (varsayılan, ÖNERİLEN) — ~1 sn açılır, virüs programları daha az
    yanlış alarm verir,
  * onefile — tek dosya, ama 5-10 sn açılır ve karantinaya alınabilir.
"""
import os
from pathlib import Path

ONEFILE = os.environ.get("TEKEL_ONEFILE") == "1"
PROJECT_ROOT = Path(os.environ.get("TEKEL_PROJECT_ROOT", os.getcwd()))

# Kullanılmayan Qt modülleri paketlenmez: çıktı küçülür, açılış hızlanır.
# İKİ İSTİSNA, ASLA ÇIKARILMAZ:
#   * shiboken6  — PySide6'nın çekirdek bağlayıcısı
#   * QtNetwork  — tek örnek koruması (QLocalServer) bunu kullanır
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtHelp",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtSpatialAudio",
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "pytest", "_pytest", "setuptools", "pip",
    "numpy", "matplotlib", "PIL", "pandas",
]

ikon = PROJECT_ROOT / "resources" / "icon.ico"
datas = []
if ikon.exists():
    datas.append((str(ikon), "resources"))

a = Analysis(
    [str(PROJECT_ROOT / "app" / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# upx=False: sıkıştırma virüs programlarında yanlış alarm sebebidir.
# console=False: kasada siyah konsol penceresi açılmamalıdır.
if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="TekelStok",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        console=False, disable_windowed_traceback=False,
        argv_emulation=False, target_arch=None, codesign_identity=None,
        entitlements_file=None,
        icon=str(ikon) if ikon.exists() else None,
        runtime_tmpdir=None,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="TekelStok",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        console=False, disable_windowed_traceback=False,
        argv_emulation=False, target_arch=None, codesign_identity=None,
        entitlements_file=None,
        icon=str(ikon) if ikon.exists() else None,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False, name="TekelStok",
    )
