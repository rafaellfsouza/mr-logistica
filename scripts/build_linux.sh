#!/usr/bin/env bash
# Gera o binário único do MR Logística no Linux (dist/MRLogistica).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
# Tkinter é pacote do sistema no Linux
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "Instalando o Tkinter do sistema..."
    (sudo apt-get update && sudo apt-get install -y python3-tk) || true
fi
python3 -m PyInstaller mrlogistica.spec --noconfirm --clean
echo
echo "Pronto! Binário em: $(pwd)/dist/MRLogistica"
