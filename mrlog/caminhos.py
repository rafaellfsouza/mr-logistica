"""
Localização de arquivos e pastas do aplicativo.

O MR Logística roda de duas formas:

1. **Código-fonte** (``python run.py``) — os dados ficam em ``~/.mrlogistica``.
2. **Executável gerado pelo PyInstaller** (``MRLogistica.exe``) — o usuário só dá
   dois cliques, não instala nada. Os dados continuam em ``~/.mrlogistica`` para
   sobreviverem a atualizações do executável.

A pasta de dados pode ser forçada pela variável de ambiente ``MRLOG_DATA_DIR``
(útil para testes automáticos e para levar o banco num pendrive).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

NOME_APP = "MR Logística"
NOME_PASTA_DADOS = ".mrlogistica"
NOME_BANCO = "mrlogistica.db"

# Variáveis que o PyInstaller cria quando congela o programa em um arquivo único.
EM_EXECUTAVEL = bool(getattr(sys, "frozen", False))


def pasta_base() -> Path:
    """Pasta onde os arquivos do programa estão (código-fonte ou bundle congelado)."""
    if EM_EXECUTAVEL:
        # PyInstaller onefile: os arquivos são extraídos em sys._MEIPASS.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def pasta_dados() -> Path:
    """Pasta gravável onde ficam o banco de dados, as fotos e os backups."""
    forçada = os.environ.get("MRLOG_DATA_DIR")
    if forçada:
        pasta = Path(forçada).expanduser()
    else:
        pasta = Path.home() / NOME_PASTA_DADOS
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_banco() -> Path:
    """Caminho completo do banco SQLite."""
    return pasta_dados() / NOME_BANCO


def pasta_fotos() -> Path:
    """Fotos dos produtos (copiadas para cá no cadastro, para não depender do arquivo original)."""
    p = pasta_dados() / "fotos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pasta_backups() -> Path:
    """Backups gerados pelo próprio aplicativo."""
    p = pasta_dados() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pasta_temporaria() -> Path:
    """Arquivos temporários de impressão (recibos, etiquetas, relatórios em PDF)."""
    p = pasta_dados() / "temp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pasta_assets() -> Path:
    """Recursos embutidos no executável (ícone, imagens)."""
    return pasta_base() / "assets"


def caminho_icone() -> Path | None:
    """Ícone da janela (PNG — formato que o Tkinter desenha em qualquer sistema)."""
    caminho = pasta_assets() / "icone.png"
    return caminho if caminho.exists() else None


def caminho_icone_exe() -> Path | None:
    """Ícone nativo do Windows (``.ico``), usado na barra de tarefas e no executável."""
    caminho = pasta_assets() / "icone.ico"
    return caminho if caminho.exists() else None
