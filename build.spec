# -*- mode: python ; coding: utf-8 -*-
import sys ; sys.setrecursionlimit(sys.getrecursionlimit() * 5)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('c:\\hostedtoolcache\\windows\\python\\3.12.7\\x64\\lib\\site-packages\\sv_ttk', 'sv_ttk')],
    datas=[('images', 'images')],
    hiddenimports=['sv_ttk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

splash = Splash('images\\EDCM_Splash.png',
                binaries=a.binaries,
                datas=a.datas,
                text_pos=(150, 470),
                text_size=12,
                text_color='black')

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Elite Dangerous Carrier Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['images\\EDCM.ico'],
)
