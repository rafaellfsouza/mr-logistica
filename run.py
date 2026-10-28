#!/usr/bin/env python3
"""
MR Logística — ponto de entrada.

Como executar:
    python run.py                (a partir da pasta do projeto)
    python -m mrlog              (equivalente)
    MRLogistica.exe              (executável gerado pelo PyInstaller — dois cliques)

O programa não precisa de internet, de servidor nem de instalação: todos os dados
ficam num banco SQLite dentro da pasta do usuário (veja ``mrlog/caminhos.py``).
"""

from __future__ import annotations

import sys
import traceback


def _instalar_tratador_de_erros() -> None:
    """Registra falhas inesperadas em arquivo e avisa o usuário antes de sair.

    Sem isso, um erro numa thread do Tkinter fecharia o programa "do nada" e o
    usuário não teria como nos contar o que aconteceu.
    """

    def hook(tipo, valor, tb):
        texto = "".join(traceback.format_exception(tipo, valor, tb))
        # 1) grava o erro na pasta de dados (junto do banco)
        try:
            from mrlog.caminhos import pasta_dados

            arquivo = pasta_dados() / "erro-ultimo.txt"
            arquivo.write_text(texto, encoding="utf-8")
        except Exception:
            pass
        # 2) imprime no console (útil durante o desenvolvimento)
        sys.__excepthook__(tipo, valor, tb)
        # 3) mostra uma janela simples, mesmo que o resto da interface já tenha morrido
        try:
            import tkinter as tk
            from tkinter import messagebox

            raiz = tk.Tk()
            raiz.withdraw()
            messagebox.showerror(
                "MR Logística — erro inesperado",
                "O sistema encontrou um erro e precisa ser fechado.\n\n"
                f"Detalhes (também gravados em erro-ultimo.txt):\n{texto[-1200:]}",
            )
            raiz.destroy()
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    _instalar_tratador_de_erros()
    try:
        from mrlog.gui.app import executar
    except ImportError as exc:  # falta de dependência (Pillow, openpyxl, reportlab...)
        print(f"Não foi possível iniciar o MR Logística: {exc}", file=sys.stderr)
        print("Instale as dependências com:  pip install -r requirements.txt", file=sys.stderr)
        return 2
    except Exception as exc:  # tkinter indisponível no sistema
        print(f"Não foi possível iniciar a interface gráfica: {exc}", file=sys.stderr)
        print("No Linux instale o Tkinter:  sudo apt install python3-tk", file=sys.stderr)
        return 3
    try:
        return executar()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
