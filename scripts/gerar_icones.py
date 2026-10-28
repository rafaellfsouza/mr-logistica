"""Gera os ícones do aplicativo (icone.ico / icone.icns / icone.png) a partir de um PNG.

Uso:  python scripts/gerar_icones.py [arquivo-origem.png]
Sem argumento usa assets/icone.png (512x512) como base.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent
ASSETS = BASE / "assets"
TAMANHOS_ICO = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
TAMANHOS_ICNS = [(16, 16), (32, 32), (48, 48), (128, 128), (256, 256), (512, 512)]


def main(origem: Path) -> int:
    imagem = Image.open(origem).convert("RGBA")
    lado = min(imagem.size)
    esquerda = (imagem.width - lado) // 2
    topo = (imagem.height - lado) // 2
    quadrada = imagem.crop((esquerda, topo, esquerda + lado, topo + lado))

    ASSETS.mkdir(parents=True, exist_ok=True)
    quadrada.resize((512, 512), Image.LANCZOS).save(ASSETS / "icone.png", format="PNG", optimize=True)
    quadrada.save(ASSETS / "icone.ico", format="ICO", sizes=TAMANHOS_ICO)
    try:
        quadrada.save(ASSETS / "icone.icns", format="ICNS", sizes=TAMANHOS_ICNS)
    except Exception as exc:  # .icns só é obrigatório no build de macOS
        print(f"aviso: não foi possível gerar o .icns ({exc})")
    print(f"Ícones gerados em {ASSETS}: icone.png, icone.ico"
          + (", icone.icns" if (ASSETS / "icone.icns").exists() else ""))
    return 0


if __name__ == "__main__":
    argumento = sys.argv[1] if len(sys.argv) > 1 else str(ASSETS / "icone.png")
    sys.exit(main(Path(argumento)))
