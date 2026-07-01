# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# ── qt_material data ──────────────────────────────────────────────────────────
try:
    import qt_material
    qt_material_dir = os.path.dirname(qt_material.__file__)
    qt_material_data = [(qt_material_dir, 'qt_material')]
except ImportError:
    qt_material_data = []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('fonts', 'fonts'),
        *qt_material_data,
    ],
    hiddenimports=[
        # ── theme ────────────────────────────────────────────────────────────
        'qt_material',
        # ── excel ────────────────────────────────────────────────────────────
        'openpyxl',
        'openpyxl.cell._writer',
        'openpyxl.styles.stylesheet',
        'openpyxl.reader.excel',
        'openpyxl.writer.excel',
        'openpyxl.utils',
        'openpyxl.utils.dataframe',
        'et_xmlfile',
        # ── app modules ──────────────────────────────────────────────────────
        'database',
        'styles',
        'widgets',
        'version',
        'tabs.recipients',
        'tabs.group_update',
        'tabs.one_time',
        'tabs.tracking',
        'tabs.search',
        'tabs.review',
        'tabs.settings',
        'tabs.summary',
        'utils.excel_utils',
        'utils.backup',
        'utils.print_view',
        'utils.ui',
        'utils.updater',
        # ── networking (in-app updater) ──────────────────────────────────────
        'urllib.request',
        'json',
        'ssl',
        # ── PyQt6 submodules sometimes missed ────────────────────────────────
        'PyQt6.QtPrintSupport',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        # ── stdlib ───────────────────────────────────────────────────────────
        'sqlite3',
        'pathlib',
        'threading',
        'hashlib',
        'secrets',
        'collections',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PySide2', 'PyQt5', 'tkinter', 'unittest', 'pydoc',
              'numpy', 'pandas', 'matplotlib', 'scipy'],
    noarchive=False,
    optimize=0,   # 0 = safe; optimize=2 stripped library asserts and caused crashes
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='מנהל_חלוקה',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
