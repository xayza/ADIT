# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ADIT (Windows build).

Build ON WINDOWS (this cannot be built on a Linux VM):
    scripts\\build_windows.bat
which runs:  pyinstaller --clean --noconfirm adit.spec

One-folder mode (not one-file): the output is dist/ADIT/ADIT.exe plus
its support files. The exe runs the same server.py entry point as
`python server.py` — there is no separate packaged code path. The
server detects a frozen run (sys.frozen) and uses the exe folder as
its root, so static/ (collected below) and projects/ live next to
the exe. FFmpeg is NOT bundled: it must be in PATH or placed as
ffmpeg.exe next to ADIT.exe (see README, section "Chay nhu app").
"""
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ["server.py"],
    pathex=[],
    binaries=[],
    # Static web UI and helper scripts ship as data files, collected
    # into dist/ADIT/static/ and dist/ADIT/scripts/ respectively.
    datas=[
        ("static", "static"),
        ("scripts", "scripts"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ADIT",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Console window ON on purpose: the server prints its address and
    # stop instructions there, and closing the window stops the app.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ADIT",
)
