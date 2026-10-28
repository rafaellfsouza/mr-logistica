#!/usr/bin/env bash
# Gera o bundle do MR Logística no macOS (dist/MRLogistica.app).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
python3 -m PyInstaller mrlogistica.spec --noconfirm --clean
echo
echo "Pronto! Aplicativo em: $(pwd)/dist/MRLogistica.app"
