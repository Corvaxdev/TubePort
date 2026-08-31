# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 nanomicron

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve().parent
SOURCE = PROJECT_ROOT / "src" / "TubePort.pyw"
ICON = PROJECT_ROOT / "assets" / "tubeport.ico"
VERSION_INFO = PROJECT_ROOT / "packaging" / "version_info.txt"
MANIFEST = PROJECT_ROOT / "packaging" / "tubeport.manifest"

datas = [(str(ICON), "assets")]
datas += collect_data_files("sv_ttk")

a = Analysis(
    [str(SOURCE)],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TubePort",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(VERSION_INFO),
    icon=[str(ICON)],
    manifest=str(MANIFEST),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TubePort",
)
