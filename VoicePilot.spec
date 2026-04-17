# -*- mode: python ; coding: utf-8 -*-
import os, sys

# Get paths
SKILL = os.path.dirname(os.path.abspath(SPECPATH))
TK_DLL = os.path.join(sys.prefix, 'DLLs', 'tk86t.dll').replace('\\', '\\\\')
TCL_DLL = os.path.join(sys.prefix, 'DLLs', 'tcl86t.dll').replace('\\', '\\\\')
TK_LIB = os.path.join(sys.prefix, 'tcl').replace('\\', '\\\\')

a = Analysis(
    [os.path.join(SKILL, 'scripts', 'voice-gui.py')],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(SKILL, 'config.json'), '.'),
        (os.path.join(SKILL, 'scripts', 'window.ps1'), 'scripts'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'customtkinter',
        'webrtcvad',
        'sounddevice',
        'scipy.signal',
    ],
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
    name='VoicePilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoicePilot',
)
