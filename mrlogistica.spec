# -*- mode: python ; coding: utf-8 -*-
"""
Spec do PyInstaller — gera o executável de ARQUIVO ÚNICO do MR Logística.

Uso local:
    pip install -r requirements-dev.txt
    pyinstaller mrlogistica.spec --noconfirm --clean

Resultado:
    Windows : dist/MRLogistica.exe      (dois cliques e pronto, sem instalação)
    Linux   : dist/MRLogistica          (binário único)
    macOS   : dist/MRLogistica.app      (bundle) + dist/MRLogistica (binário)

O GitHub Actions usa este mesmo spec para publicar os executáveis nas Releases.
"""

import sys

from PyInstaller.utils.hooks import collect_submodules

# O reportlab e o openpyxl importam módulos dinamicamente (fontes, formatos de
# planilha); coletar os submódulos evita "ModuleNotFoundError" no executável.
hiddenimports = (
    collect_submodules("reportlab")
    + collect_submodules("openpyxl")
    + collect_submodules("PIL")
    + ["PIL._tkinter_finder"]
)

# O ícone muda conforme o sistema de build (o .ico não existe no macOS e vice-versa).
if sys.platform.startswith("win"):
    ICONE = "assets/icone.ico"
elif sys.platform == "darwin":
    ICONE = "assets/icone.icns"
else:
    ICONE = "assets/icone.png"

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    # os assets vão para a pasta "assets" dentro do bundle (sys._MEIPASS/assets)
    datas=[
        ("assets/icone.png", "assets"),
        ("assets/icone.ico", "assets"),
        ("assets/icone.icns", "assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # nada de bibliotecas científicas pesadas dentro do executável
    excludes=["numpy", "pandas", "scipy", "matplotlib", "pytest", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # no macOS o formato natural é o .app (que também embute tudo em um arquivo)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="MRLogistica",
        debug=False,
        strip=False,
        upx=False,
        console=False,  # sem janela de console
        icon=ICONE,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="MRLogistica",
    )
    app = BUNDLE(
        coll,
        name="MRLogistica.app",
        icon=ICONE,
        bundle_identifier="app.mrlogistica.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
            "NSHumanReadableCopyright": "MR Logística",
        },
    )
else:
    # arquivo único (onefile): tudo dentro de um .exe / binário
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="MRLogistica",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # True mostraria um console preto junto (não queremos)
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICONE,
    )
