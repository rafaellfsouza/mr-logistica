"""
MR Logística — Sistema desktop de gestão comercial (PDV, estoque, financeiro e relatórios).

Pacote principal. A arquitetura é dividida em duas camadas:

* ``mrlog.*``      -> núcleo (banco de dados SQLite, regras de negócio, relatórios,
                      exportações, impressão). Não depende de interface gráfica e
                      por isso é 100% testável automaticamente.
* ``mrlog.gui.*``  -> interface gráfica em Tkinter/ttk (janelas, telas e widgets).

100% offline: nenhum dado sai do computador do usuário.
"""

__version__ = "1.0.0"
__author__ = "MR Logística"
NOME_APP = "MR Logística"
