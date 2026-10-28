"""Permite iniciar o sistema com ``python -m mrlog``."""

from __future__ import annotations

import sys
from pathlib import Path

# garante que o pacote seja encontrado quando executado a partir da pasta do projeto
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from mrlog.gui.app import executar

    return executar()


if __name__ == "__main__":
    sys.exit(main())
