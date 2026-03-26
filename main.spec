# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[
        *numpy_binaries,
    ],
    datas=[
        ('lpptemplate', 'lpptemplate'),
        ('love_runtime', 'love_runtime'),
        ('config.json', '.'),
        ('controls.lua', '.'),
        ('raycast3d.lua', '.'),
        *collect_data_files('PIL'),
        *numpy_datas,
    ],
    hiddenimports=[
        *numpy_hiddenimports,
        # ── PySide6 ──
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtMultimedia',
        'shiboken6',
        # ── PIL / numpy ──
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFilter',
        'numpy',
        'numpy._core',
        'numpy._core._multiarray_umath',
        'numpy._core._exceptions',
        'numpy._core.multiarray',
        'numpy._core.umath',
        'numpy.lib.format',
        # ── Your modules ──
        'resource_path',
        'appearance_customizer',
        'behavior_node_graph',
        'level_editor',
        'lpp_exporter',
        'models',
        'project_explorer',
        'sfx',
        'spritesheet_tool',
        'tab_3d_maps',
        'tab_animation_graph',
        'tab_editor',
        'tab_gamedata',
        'tab_objects',
        'tab_paperdoll',
        'tab_scene_options',
        'tab_sfx',
        'theme_customizer',
        'theme_manager',
        'theme_utils',
        'tileset_manager',
        'tile_palette',
        'windows_exporter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages you do NOT need
        'torch', 'torchaudio', 'torchvision',
        'tensorflow', 'tensorboard',
        'transformers', 'diffusers', 'accelerate',
        'spacy', 'nltk', 'sklearn', 'scikit-learn',
        'matplotlib', 'pandas', 'scipy',
        'gradio', 'flask', 'fastapi', 'uvicorn',
        'selenium', 'kivy', 'buildozer', 'pygame',
        'IPython', 'jupyter',
        'cv2', 'opencv-python',
        'PyQt5', 'PyQt6',
    ],
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
    name='VitaAdventureCreator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # No terminal window
    icon='favicon.ico',
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
    upx=False,
    upx_exclude=[],
    name='VitaAdventureCreator',
)
