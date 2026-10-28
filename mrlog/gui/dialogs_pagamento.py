"""
Diálogo de **pagamento da venda** usado pelo PDV.

Permite pagamento misto (várias formas na mesma venda), calcula troco em tempo real
e trata o fiado (exige cliente e respeita o limite de crédito). Devolve um
dicionário com ``pagamentos``, ``troco``, ``observacao`` e ``vencimento_fiado``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from .. import clientes as clientes_mod
from .. import contas_receber
from .. import formas_pagamento
from .. import vendas as vendas_mod
from ..utils import formatar_dinheiro, hoje, para_centavos, somar_dias
from .dialogs import Modal, alerta, selecionar_registro
from .tema import FONTE_BASE, FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO, FONTE_VALOR, Tema


class DialogoPagamento(Modal):
    """Modal de fechamento da venda (dinheiro, Pix, débito, crédito, fiado e misto)."""

    def __init__(self, mestre, tema: Tema, ctx, total: int, cliente=None, quantidade_itens: int = 0):
        super().__init__(mestre, tema, "Pagamento da venda", largura=820, altura=640)
        self.ctx = ctx
        self.banco = ctx.banco
        self.total = int(total or 0)
        self.cliente = cliente
        self.pagamentos: list[dict] = []
        self.quantidade_itens = quantidade_itens
        self._montar()
        self._atualizar()

    # ------------------------------------------------------------------ interface
    def _montar(self):
        corpo = self.corpo
        corpo.columnconfigure(0, weight=3)
        corpo.columnconfigure(1, weight=2)

        # ---- coluna esquerda: formas de pagamento
        esquerda = ttk.Frame(corpo, style="TFrame")
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        esquerda.rowconfigure(3, weight=1)
        esquerda.columnconfigure(0, weight=1)

        ttk.Label(esquerda, text="Formas de pagamento", style="TLabel", font=FONTE_SUBTITULO).grid(
            row=0, column=0, sticky="w")
        ttk.Label(
            esquerda,
            text="Clique em uma forma para lançar (você pode combinar várias — pagamento misto).",
            style="Suave.TLabel", wraplength=420, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        quadro_formas = ttk.Frame(esquerda, style="TFrame")
        quadro_formas.grid(row=2, column=0, sticky="ew")
        self.botoes_forma: dict[str, ttk.Button] = {}
        for indice, forma in enumerate(formas_pagamento.TODAS):
            atalho = formas_pagamento.ATALHOS.get(forma, "")
            rotulo = f"{forma}  ({atalho})" if atalho else forma
            botao = ttk.Button(quadro_formas, text=rotulo, style="Primario.TButton",
                               command=lambda f=forma: self.adicionar_forma(f))
            botao.grid(row=indice // 3, column=indice % 3, sticky="ew", padx=3, pady=3)
            quadro_formas.columnconfigure(indice % 3, weight=1)
            self.botoes_forma[forma] = botao

        # ---- lançamentos
        ttk.Label(esquerda, text="Lançamentos", style="TLabel", font=FONTE_SUBTITULO).grid(
            row=3, column=0, sticky="nw", pady=(10, 2))
        self.tabela = ttk.Treeview(
            esquerda, columns=("forma", "detalhe", "valor"), show="headings", height=6, selectmode="browse"
        )
        self.tabela.heading("forma", text="Forma", anchor="w")
        self.tabela.heading("detalhe", text="Detalhes", anchor="w")
        self.tabela.heading("valor", text="Valor", anchor="e")
        self.tabela.column("forma", width=140, anchor="w")
        self.tabela.column("detalhe", width=210, anchor="w")
        self.tabela.column("valor", width=110, anchor="e")
        self.tabela.grid(row=4, column=0, sticky="nsew")
        self.tabela.bind("<Delete>", lambda e: self.remover_selecionado())
        esquerda.rowconfigure(4, weight=1)

        botoes_lista = ttk.Frame(esquerda, style="TFrame")
        botoes_lista.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(botoes_lista, text="Remover selecionado (Del)", command=self.remover_selecionado).pack(side="left")
        ttk.Button(botoes_lista, text="Limpar tudo", command=self.limpar).pack(side="left", padx=6)
        ttk.Button(botoes_lista, text="Dinheiro exato", command=self.dinheiro_exato).pack(side="left")

        # ---- coluna direita: resumo
        direita = ttk.Frame(corpo, style="Card.TFrame", padding=12)
        direita.grid(row=0, column=1, sticky="nsew")
        direita.columnconfigure(0, weight=1)

        ttk.Label(direita, text="TOTAL DA VENDA", style="Card.Suave.TLabel").grid(row=0, column=0, sticky="w")
        self.rotulo_total = tk.Label(direita, text=formatar_dinheiro(self.total), font=FONTE_VALOR,
                                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"))
        self.rotulo_total.grid(row=1, column=0, sticky="w", pady=(0, 6))
        cliente_texto = f"Cliente: {self.cliente['nome']}" if self.cliente else "Consumidor final"
        ttk.Label(direita, text=f"{self.quantidade_itens} item(ns) • {cliente_texto}",
                  style="Card.Suave.TLabel", wraplength=280, justify="left").grid(row=2, column=0, sticky="w")

        self.rotulo_pago = tk.Label(direita, text="Pago: R$ 0,00", font=FONTE_SUBTITULO,
                                    background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"))
        self.rotulo_pago.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.rotulo_falta = tk.Label(direita, text="", font=FONTE_SUBTITULO,
                                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("perigo"))
        self.rotulo_falta.grid(row=4, column=0, sticky="w")
        self.rotulo_troco = tk.Label(direita, text="", font=FONTE_TITULO,
                                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("sucesso"))
        self.rotulo_troco.grid(row=5, column=0, sticky="w", pady=(4, 0))

        ttk.Label(direita, text="Observação (opcional):", style="Card.TLabel").grid(row=6, column=0, sticky="w", pady=(14, 2))
        self.entrada_observacao = ttk.Entry(direita, width=32)
        self.entrada_observacao.grid(row=7, column=0, sticky="ew")

        ttk.Label(direita, text="Atalhos: F4 Dinheiro • F5 Pix • F6 Débito • F7 Crédito • F8 Fiado\n"
                                "Enter conclui a venda • Esc cancela",
                  style="Card.Suave.TLabel", justify="left", wraplength=280).grid(row=8, column=0, sticky="w", pady=(14, 0))

        self.barra_botoes((("✔ Concluir venda (Enter)", self.concluir, "Sucesso.TButton"),
                           ("Cancelar (Esc)", self.cancelar, "TButton")))

        # atalhos internos
        for forma, atalho in formas_pagamento.ATALHOS.items():
            self.bind(f"<{atalho}>", lambda e, f=forma: self.adicionar_forma(f))
        self.bind("<Return>", lambda e: self.concluir())

    # ------------------------------------------------------------------ lançamentos
    def adicionados(self) -> int:
        return sum(int(p["valor"]) for p in self.pagamentos)

    def restante(self) -> int:
        return max(0, self.total - self.adicionados())

    def adicionar_forma(self, forma: str):
        forma = formas_pagamento.normalizar(forma)
        restante = self.restante()
        if restante <= 0:
            alerta(self, self.tema, "O total da venda já foi coberto pelos lançamentos.\n"
                                    "Remova um lançamento se quiser alterar os valores.")
            return
        if forma == formas_pagamento.FIADO:
            dados = self._lancar_fiado(restante)
        elif forma == "Dinheiro":
            dados = self._lancar_dinheiro(restante)
        elif forma == "Cartão de crédito":
            dados = self._lancar_cartao(forma, restante)
        else:
            dados = {"forma": forma, "valor": restante, "recebido": restante, "parcelas": 1,
                     "operadora": "", "documento": "", "detalhe": "Valor restante"}
        if not dados:
            return
        self.pagamentos.append(dados)
        self._atualizar()

    def _lancar_dinheiro(self, restante: int) -> dict | None:
        """Recebe em dinheiro e calcula o troco na hora."""
        dialogo = Modal(self, self.tema, "Pagamento em dinheiro", largura=460, altura=330)
        ttk.Label(dialogo.corpo, text=f"Total da venda: {formatar_dinheiro(self.total)}", style="TLabel").pack(anchor="w")
        ttk.Label(dialogo.corpo, text=f"Falta pagar: {formatar_dinheiro(restante)}", style="TLabel",
                  font=FONTE_SUBTITULO).pack(anchor="w", pady=(2, 8))
        ttk.Label(dialogo.corpo, text="Valor recebido do cliente:", style="TLabel").pack(anchor="w")
        entrada = ttk.Entry(dialogo.corpo, width=18, justify="right", font=FONTE_SUBTITULO)
        entrada.pack(anchor="w", pady=(2, 6))
        entrada.insert(0, f"{restante / 100:.2f}".replace(".", ","))
        entrada.select_range(0, "end")
        entrada.focus_set()
        rotulo_troco = ttk.Label(dialogo.corpo, text="", style="TLabel", font=FONTE_SUBTITULO)
        rotulo_troco.pack(anchor="w")

        quadro = ttk.Frame(dialogo.corpo, style="TFrame")
        quadro.pack(fill="x", pady=(10, 0))

        def recebido_atual() -> int:
            try:
                return int(para_centavos(entrada.get()))
            except Exception:
                return 0

        def calcular(_evento=None) -> int:
            recebido = recebido_atual()
            troco = recebido - restante
            if recebido <= 0:
                rotulo_troco.configure(text="Informe o valor recebido.")
            elif troco < 0:
                rotulo_troco.configure(text=f"Faltam {formatar_dinheiro(-troco)} — complete com outra forma.")
            else:
                rotulo_troco.configure(text=f"Troco: {formatar_dinheiro(troco)}")
            return recebido

        def definir(valor: int):
            entrada.delete(0, "end")
            entrada.insert(0, f"{valor / 100:.2f}".replace(".", ","))
            calcular()

        for valor in (2000, 5000, 10000, 20000):
            ttk.Button(quadro, text=formatar_dinheiro(valor), command=lambda v=valor: definir(v)).pack(side="left", padx=2)
        ttk.Button(quadro, text="Exato", command=lambda: definir(restante)).pack(side="left", padx=2)
        entrada.bind("<KeyRelease>", calcular)
        calcular()

        def confirmar(_evento=None):
            recebido = recebido_atual()
            if recebido <= 0:
                alerta(dialogo, self.tema, "Informe um valor recebido válido.")
                return
            if recebido < restante:
                falta = restante - recebido
                if not self.cliente:
                    alerta(dialogo, self.tema,
                           f"Faltam {formatar_dinheiro(falta)} para concluir a venda.\n\n"
                           "Complete em dinheiro/outra forma ou identifique o cliente (F7) para lançar a "
                           "diferença no fiado.")
                    return
                ok, mensagem = clientes_mod.pode_fiar(clientes_mod.pegar(self.banco, self.cliente["id"]), falta)
                if not ok:
                    alerta(dialogo, self.tema, mensagem)
                    return
                self.pagamentos.append({"forma": formas_pagamento.FIADO, "valor": falta, "recebido": 0,
                                        "parcelas": 1, "operadora": "", "documento": "",
                                        "detalhe": f"Diferença lançada no fiado ({self.cliente['nome']})"})
                dialogo.confirmar({"forma": "Dinheiro", "valor": recebido, "recebido": recebido, "parcelas": 1,
                                   "operadora": "", "documento": "",
                                   "detalhe": f"Recebido {formatar_dinheiro(recebido)}"})
                return
            troco = recebido - restante
            dialogo.confirmar({
                "forma": "Dinheiro", "valor": restante, "recebido": recebido, "parcelas": 1,
                "operadora": "", "documento": "",
                "detalhe": (f"Recebido {formatar_dinheiro(recebido)} • troco {formatar_dinheiro(troco)}"
                            if troco else f"Recebido {formatar_dinheiro(recebido)}"),
            })

        entrada.bind("<Return>", confirmar)
        dialogo.barra_botoes((("Confirmar", confirmar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
        return dialogo.abrir()

    def _lancar_cartao(self, forma: str, restante: int) -> dict | None:
        dialogo = Modal(self, self.tema, f"Pagamento em {forma.lower()}", largura=440, altura=340)
        ttk.Label(dialogo.corpo, text=f"Valor a pagar: {formatar_dinheiro(restante)}", style="TLabel",
                  font=FONTE_SUBTITULO).pack(anchor="w")
        ttk.Label(dialogo.corpo, text="Valor neste cartão:", style="TLabel").pack(anchor="w", pady=(8, 0))
        entrada_valor = ttk.Entry(dialogo.corpo, width=16, justify="right")
        entrada_valor.pack(anchor="w")
        entrada_valor.insert(0, f"{restante / 100:.2f}".replace(".", ","))
        entrada_valor.select_range(0, "end")
        ttk.Label(dialogo.corpo, text="Parcelas:", style="TLabel").pack(anchor="w", pady=(8, 0))
        combo = ttk.Combobox(dialogo.corpo, values=[f"{i}x" for i in range(1, 13)], width=6, state="readonly")
        combo.set("1x")
        combo.pack(anchor="w")
        ttk.Label(dialogo.corpo, text="Operadora / autorização (opcional):", style="TLabel").pack(anchor="w", pady=(8, 0))
        entrada_operadora = ttk.Entry(dialogo.corpo, width=28)
        entrada_operadora.pack(anchor="w")
        entrada_valor.focus_set()

        def confirmar(_evento=None):
            try:
                valor = int(para_centavos(entrada_valor.get()))
            except Exception:
                valor = 0
            if valor <= 0:
                alerta(dialogo, self.tema, "Informe um valor válido.")
                return
            if valor > restante:
                alerta(dialogo, self.tema,
                       f"O valor ({formatar_dinheiro(valor)}) é maior que o restante da venda "
                       f"({formatar_dinheiro(restante)}).")
                return
            parcelas = int(str(combo.get()).replace("x", "") or 1)
            dialogo.confirmar({
                "forma": forma, "valor": valor, "recebido": valor, "parcelas": parcelas,
                "operadora": entrada_operadora.get().strip(), "documento": "",
                "detalhe": f"{parcelas}x de {formatar_dinheiro(int(valor / parcelas))}"
                           + (f" • {entrada_operadora.get().strip()}" if entrada_operadora.get().strip() else ""),
            })

        entrada_valor.bind("<Return>", confirmar)
        dialogo.barra_botoes((("Confirmar", confirmar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
        return dialogo.abrir()

    def _lancar_fiado(self, restante: int) -> dict | None:
        if not self.cliente:
            alerta(self, self.tema,
                   "Para vender no fiado é preciso identificar o cliente.\n\n"
                   "Use o botão 'Cliente (F7)' na tela do PDV e repita o lançamento.")
            return None
        cliente = clientes_mod.pegar(self.banco, self.cliente["id"])
        ok, mensagem = clientes_mod.pode_fiar(cliente, restante)
        if not ok:
            alerta(self, self.tema, mensagem)
            return None
        dialogo = Modal(self, self.tema, "Venda no fiado", largura=470, altura=330)
        informacoes = [
            f"Cliente: {cliente['nome']}",
            f"Valor a fiar: {formatar_dinheiro(restante)}",
        ]
        if clientes_mod.tem_limite(cliente):
            informacoes.append(f"Limite de crédito: {formatar_dinheiro(int(cliente['limite_credito'] or 0))}")
            informacoes.append(f"Crédito disponível: {formatar_dinheiro(clientes_mod.credito_disponivel(cliente))}")
        informacoes.append(f"Saldo devedor atual: {formatar_dinheiro(int(cliente['saldo_devedor'] or 0))}")
        resumo = contas_receber.resumo(self.banco)
        if resumo["vencido"]:
            informacoes.append(f"⚠ Há títulos vencidos do cliente totalizando {formatar_dinheiro(resumo['vencido'])} "
                               "(verifique antes de fiar).")
        ttk.Label(dialogo.corpo, text="\n".join(informacoes), style="TLabel", justify="left",
                  wraplength=420).pack(anchor="w")
        ttk.Label(dialogo.corpo, text="Vencimento:", style="TLabel").pack(anchor="w", pady=(10, 0))
        entrada_vencimento = ttk.Entry(dialogo.corpo, width=14)
        entrada_vencimento.pack(anchor="w")
        padrao = somar_dias(hoje(), 30)
        entrada_vencimento.insert(0, f"{padrao[8:10]}/{padrao[5:7]}/{padrao[:4]}")
        ttk.Label(dialogo.corpo, text="Formato DD/MM/AAAA (padrão: 30 dias).", style="Suave.TLabel").pack(anchor="w")

        def confirmar():
            from ..utils import converter_data_br

            vencimento = converter_data_br(entrada_vencimento.get())
            if not vencimento:
                alerta(dialogo, self.tema, "Data de vencimento inválida. Use o formato DD/MM/AAAA.")
                return
            dialogo.confirmar({"forma": formas_pagamento.FIADO, "valor": restante, "recebido": 0,
                               "parcelas": 1, "operadora": "", "documento": "",
                               "vencimento": vencimento,
                               "detalhe": f"Fiado — vence em {vencimento[8:10]}/{vencimento[5:7]}/{vencimento[:4]}"})

        dialogo.barra_botoes((("Lançar no fiado", confirmar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
        resultado = dialogo.abrir()
        return resultado

    # ------------------------------------------------------------------ gestão
    def remover_selecionado(self):
        selecao = self.tabela.selection()
        if not selecao:
            return
        indice = self.tabela.index(selecao[0])
        if 0 <= indice < len(self.pagamentos):
            self.pagamentos.pop(indice)
            self._atualizar()

    def limpar(self):
        self.pagamentos.clear()
        self._atualizar()

    def dinheiro_exato(self):
        restante = self.restante()
        if restante <= 0:
            return
        self.pagamentos.append({"forma": "Dinheiro", "valor": restante, "recebido": restante, "parcelas": 1,
                                "operadora": "", "documento": "", "detalhe": "Dinheiro exato"})
        self._atualizar()

    # ------------------------------------------------------------------ resumo
    def _atualizar(self):
        self.tabela.delete(*self.tabela.get_children())
        for pagamento in self.pagamentos:
            self.tabela.insert("", "end", values=(
                pagamento["forma"], pagamento.get("detalhe", ""), formatar_dinheiro(int(pagamento["valor"])),
            ))
        pago = self.adicionados()
        falta = max(0, self.total - pago)
        troco = 0
        dinheiro_pago = sum(int(p["valor"]) for p in self.pagamentos if p["forma"] == "Dinheiro")
        dinheiro_recebido = sum(int(p.get("recebido", 0)) for p in self.pagamentos if p["forma"] == "Dinheiro")
        if dinheiro_pago:
            troco = max(0, dinheiro_recebido - dinheiro_pago)
        self.rotulo_pago.configure(text=f"Pagamento lançado: {formatar_dinheiro(pago)}")
        self.rotulo_falta.configure(text=(f"Falta: {formatar_dinheiro(falta)}" if falta else "✔ Valor completo"))
        self.rotulo_troco.configure(text=(f"Troco: {formatar_dinheiro(troco)}" if troco else ""))
        self.rotulo_total.configure(text=formatar_dinheiro(self.total))

    # ------------------------------------------------------------------ conclusão
    def concluir(self, _evento=None):
        if not self.pagamentos:
            alerta(self, self.tema, "Informe ao menos uma forma de pagamento.")
            return
        try:
            resultado = vendas_mod.validar_pagamento(self.total, self.pagamentos, permitir_fiado=bool(self.cliente))
        except vendas_mod.ErroVenda as exc:
            alerta(self, self.tema, str(exc))
            return
        if resultado.falta > 0:
            alerta(self, self.tema,
                   f"Faltam {formatar_dinheiro(resultado.falta)} para concluir a venda.\n"
                   "Complete o pagamento (ou lance no fiado, identificando o cliente).")
            return
        if not resultado.pagamentos:
            alerta(self, self.tema, "Nenhum valor lançado.")
            return
        vencimento = next((p.get("vencimento", "") for p in self.pagamentos
                           if p["forma"] == formas_pagamento.FIADO), "")
        self.confirmar({
            "pagamentos": [p for p in self.pagamentos],
            "troco": resultado.troco,
            "observacao": self.entrada_observacao.get().strip(),
            "vencimento_fiado": vencimento,
            "fiado": resultado.fiado,
        })
