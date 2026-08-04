# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['autorb/cli.py'],
    pathex=[],
    binaries=[
        ('tools/forgetool', 'tools/'),
    ],
    datas=[
        ('autorb/export/data/template.con', 'autorb/export/data'),
        ('README.md', '.'),
        ('LICENSE', '.')
    ],
    hiddenimports=['whisperx', 'basic_pitch', 'demucs', 'torch', 'scipy', 'numpy', 'librosa', 'sklearn', 'pandas', 'matplotlib'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['output', 'tests', 'input', '.devcontainer', '.github', 'venv', 'stems'],
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
    name='autorb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    name='autorb',
)
