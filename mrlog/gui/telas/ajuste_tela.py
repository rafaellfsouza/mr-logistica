"""
Tela de **Ajuste de inventário** — contagem física e acerto do saldo do sistema.

Fluxo de trabalho:
1. monte a folha de contagem (adicione produtos individualmente, carregue os
   produtos com estoque baixo ou todos os produtos);
2. informe a quantidade **contada** de cada item (duplo clique ou F3) — o sistema
   calcula a diferença para o saldo atual;
3. aplique os ajustes (F4): cada diferença gera uma movimentação de
   ``ajuste_inventario`` (entrada quando sobra mercadoria, saída quando falta).

Nada é gravado antes de “Aplicar ajustes”, então a contagem pode ser feita com
calma — inclusive exportada para conferência em papel ou Excel.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import estoque as estoque_mod
from ... import produtos as produtos_mod
from ... import unidades as unidades_mod
from ...esquema import MOTIVOS_AJUSTE
from ...utils import formatar_dinheiro, formatar_quantidade, hoje
from .. import dialogs
from ..widgets import Tabela
from . import Tela, exportar_dados
from .produtos_tela import selecionar_produto

COLUNAS = [
    {"chave": "codigo", "rotulo": "Código", "largura": 90},
    {"chave": "nome", "rotulo": "Produto", "largura": 260},
    {"chave": "unidade", "rotulo": "Un.", "largura": 55, "alinhamento": "centro"},
    {"chave": "saldo_sistema", "rotulo": "Saldo no sistema", "largura": 120, "tipo": "quantidade"},
    {"chave": "contado_texto", "rotulo": "Contagem física", "largura": 120, "tipo": "quantidade", "alinhamento": "centro"},
    {"chave": "diferenca_texto", "rotulo": "Diferença", "largura": 110, "alinhamento": "centro"},
    {"chave": "valor_diferenca", "rotulo": "Valor da diferença", "largura": 130, "tipo": "dinheiro"},
    {"chave": "estoque_minimo", "rotulo": "Mínimo", "largura": 80, "tipo": "quantidade"},
    {"chave": "situacao", "rotulo": "Situação", "largura": 170},
]


class AjusteTela(Tela):
    titulo = "Ajuste de inventário"
    descricao = "Contagem física do estoque: informe o que foi contado e o sistema acerta as diferenças."

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        #: ``{produto_id: {"produto": linha, "contado": float | None}}``
        self._itens: dict[int, dict] = {}
        self._motivo = tk.StringVar(value="Ajuste de inventário")
        self._observacao = tk.StringVar(value="")
        self._somente_diferenca = tk.BooleanVar(value=False)

        self._montar_barra(
            [
                ("＋ Adicionar produto", self.adicionar_produto, "Primario.TButton", "F2"),
                ("✎ Informar contagem", self.informar_contagem, "TButton", "F3"),
                ("✔ Aplicar ajustes", self.aplicar_ajustes, "TButton", "F4"),
                ("🗑 Remover item", self.remover_item, "TButton", "Del"),
                ("📥 Estoque baixo", self.carregar_estoque_baixo, "TButton", ""),
                ("📥 Todos os produtos", self.carregar_todos, "TButton", ""),
                ("🧹 Limpar contagem", self.limpar, "TButton", ""),
                ("⟳ Atualizar saldos", self.carregar, "TButton", "Ctrl+R"),
            ],
            [("⭳ Exportar contagem", self.exportar, "TButton")],
        )
        self._montar_opcoes()
        self._montar_tabela()
        self._montar_rodape()
        self._registrar_teclas()
        self.carregar()

    # ------------------------------------------------------------------ interface
    def _montar_opcoes(self):
        quadro = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
        quadro.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(quadro, text="Motivo do ajuste:", style="TLabel").grid(row=0, column=0, sticky="w")
        self.combo_motivo = ttk.Combobox(quadro, textvariable=self._motivo, width=32, state="readonly",
                                         values=[texto for texto in MOTIVOS_AJUSTE.values()])
        self.combo_motivo.grid(row=0, column=1, sticky="w", padx=(6, 16))
        ttk.Label(quadro, text="Observação:", style="TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(quadro, textvariable=self._observacao, width=44).grid(row=0, column=3, sticky="ew", padx=(6, 16))
        tk.Checkbutton(
            quadro, text="Mostrar somente itens com diferença", variable=self._somente_diferenca,
            command=self._redesenhar, background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
            activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
            selectcolor=self.tema.cor("bg_input"), highlightthickness=0,
        ).grid(row=0, column=4, sticky="w")
        quadro.columnconfigure(3, weight=1)
        self.quadro_opcoes = quadro

    def _montar_tabela(self):
        self.tabela = Tabela(
            self, self.tema, COLUNAS,
            ao_selecionar=self._ao_selecionar,
            ao_duplo_clique=lambda linha: self.informar_contagem(linha),
            mostrar_busca=True, altura=18,
        )
        self.tabela.grid(row=3, column=0, sticky="nsew")
        # a linha 2 (``self.corpo`` da classe base) fica só com as opções do ajuste
        self.corpo.grid_remove()
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=1)

    def _montar_rodape(self):
        self.painel_resumo = ttk.Frame(self, style="Card.TFrame", padding=10)
        self.painel_resumo.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.painel_resumo.columnconfigure(0, weight=1)
        self.rotulo_orientacao = tk.Label(
            self.painel_resumo, justify="left", anchor="w", wraplength=980, font=("Segoe UI", 9),
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg_suave"),
            text="1) Adicione os produtos à folha de contagem (ou bipe o código de barras no campo abaixo).\n"
                 "2) Dê duplo clique no item e informe a quantidade contada.\n"
                 "3) Clique em “Aplicar ajustes” para gravar as diferenças como movimentação de inventário.",
        )
        self.rotulo_orientacao.grid(row=0, column=0, sticky="ew")

        quadro_bip = ttk.Frame(self.painel_resumo, style="TFrame")
        quadro_bip.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(quadro_bip, text="Bipe o código do produto:", style="TLabel").pack(side="left")
        self.entrada_codigo = ttk.Entry(quadro_bip, width=24)
        self.entrada_codigo.pack(side="left", padx=6)
        self.entrada_codigo.bind("<Return>", lambda e: self._ao_bipar())
        ttk.Button(quadro_bip, text="Adicionar à contagem", command=self._ao_bipar).pack(side="left")
        self.rotulo_totais = tk.Label(
            quadro_bip, text="", anchor="e", justify="right", font=("Segoe UI", 10, "bold"),
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
        )
        self.rotulo_totais.pack(side="right")

    def _registrar_teclas(self):
        for sequencia, comando in (("<F2>", self.adicionar_produto), ("<F3>", self.informar_contagem),
                                   ("<F4>", self.aplicar_ajustes), ("<Delete>", self.remover_item)):
            self.bind(sequencia, lambda e, c=comando: (c(), "break")[1])

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.adicionar_produto, "F3": self.informar_contagem, "F4": self.aplicar_ajustes,
                 "Del": self.remover_item}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    def focar_busca(self):
        self.tabela.focar_busca()

    def focar_principal(self):
        self.entrada_codigo.focus_set()

    def atualizar_tema(self):
        self.tabela.atualizar_tema()
        for rotulo in (self.rotulo_orientacao, self.rotulo_totais):
            rotulo.configure(background=self.tema.cor("bg_card"))
        self.rotulo_orientacao.configure(foreground=self.tema.cor("fg_suave"))
        self.rotulo_totais.configure(foreground=self.tema.cor("fg"))
        for filho in self.quadro_opcoes.winfo_children():
            if isinstance(filho, tk.Checkbutton):
                filho.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                                selectcolor=self.tema.cor("bg_input"))

    # ------------------------------------------------------------------ dados
    def carregar(self):
        """Recarrega os saldos do banco para os itens da folha de contagem."""
        for produto_id, item in list(self._itens.items()):
            produto = produtos_mod.pegar(self.banco, produto_id)
            if not produto:
                self._itens.pop(produto_id, None)
                continue
            item["produto"] = produto
        self._redesenhar()

    def _linhas(self) -> list[dict]:
        linhas = []
        for produto_id, item in self._itens.items():
            produto = item["produto"]
            contado = item["contado"]
            saldo = estoque_mod.saldo(self.banco, produto_id)
            custo = int(produto["preco_custo"] or 0)
            linha = {
                "id": produto_id,
                "codigo": produto["codigo"],
                "nome": produto["nome"],
                "unidade": produto["unidade_base"] or "un",
                "saldo_sistema": saldo,
                "contado": contado,
                "contado_texto": float(contado) if contado is not None else "",
                "estoque_minimo": float(produto["estoque_minimo"] or 0),
                "custo": custo,
            }
            if contado is None:
                linha["diferenca"] = None
                linha["diferenca_texto"] = "não contado"
                linha["valor_diferenca"] = 0
                linha["situacao"] = "Aguardando contagem"
            else:
                diferenca = unidades_mod.arredondar(float(contado) - saldo)
                linha["diferenca"] = diferenca
                linha["diferenca_texto"] = (f"+{formatar_quantidade(diferenca)}" if diferenca > 0
                                            else formatar_quantidade(diferenca))
                linha["valor_diferenca"] = int(round(diferenca * custo))
                if abs(diferenca) <= 1e-9:
                    linha["situacao"] = "Conferido — sem diferença"
                    linha["_tag"] = "sucesso"
                elif diferenca > 0:
                    linha["situacao"] = "Sobra de mercadoria (entrada)"
                    linha["_tag"] = "info"
                else:
                    linha["situacao"] = "Falta de mercadoria (saída)"
                    linha["_tag"] = "perigo"
            if self._somente_diferenca.get() and (linha.get("diferenca") is None
                                                  or abs(linha["diferenca"]) <= 1e-9):
                continue
            linhas.append(linha)
        return sorted(linhas, key=lambda l: (l["codigo"] or "").lower())

    def registros(self) -> list[dict]:
        """Linhas exibidas na folha de contagem (mesma API das telas de lista)."""
        return self.tabela.registros()

    def selecionado(self) -> dict | None:
        return self.tabela.linha_selecionada()

    def _redesenhar(self):
        linhas = self._linhas()
        contados = [l for l in linhas if l["contado"] is not None]
        com_diferenca = [l for l in contados if abs(l["diferenca"] or 0) > 1e-9]
        valor = sum(int(l["valor_diferenca"] or 0) for l in com_diferenca)
        resumo = (f"{len(linhas)} item(ns) na contagem • {len(contados)} contado(s) • "
                  f"{len(com_diferenca)} com diferença")
        self.tabela.carregar(linhas, resumo=resumo)
        self.rotulo_totais.configure(
            text=f"Itens: {len(linhas)}    Com diferença: {len(com_diferenca)}    "
                 f"Valor líquido: {formatar_dinheiro(valor)}"
        )
        self.status(f"Ajuste de inventário: {resumo}.")

    def _ao_selecionar(self, linha: dict | None):
        if not linha:
            return
        self.status(f"{linha['codigo']} — {linha['nome']}: saldo {formatar_quantidade(linha['saldo_sistema'])} "
                    f"{linha['unidade']}")

    # ------------------------------------------------------------------ ações
    def _motivo_chave(self) -> str:
        texto = self._motivo.get()
        for chave, rotulo in MOTIVOS_AJUSTE.items():
            if rotulo == texto:
                return chave
        return "ajuste_inventario"

    def incluir(self, produto) -> bool:
        """Coloca o produto na folha de contagem (mantendo uma contagem já informada)."""
        if not produto:
            return False
        produto_id = int(produto["id"])
        anterior = self._itens.get(produto_id, {}).get("contado")
        self._itens[produto_id] = {"produto": produto, "contado": anterior}
        self._redesenhar()
        self.tabela.selecionar_por("id", produto_id)
        return True

    def adicionar_produto(self):
        if not self.exigir("estoque_movimentar", "fazer ajustes de inventário"):
            return
        produto = selecionar_produto(self.ctx, "Adicionar produto à contagem")
        if produto:
            self.incluir(produto)
            self.informar_contagem()

    def _ao_bipar(self):
        codigo = self.entrada_codigo.get().strip()
        if not codigo:
            return
        produto, tipo = produtos_mod.resolver_bipagem(self.banco, codigo)
        self.entrada_codigo.delete(0, "end")
        if not produto:
            if dialogs.confirmar(self, self.tema,
                                 f"Nenhum produto com o código “{codigo}”.\n\nCadastrar agora?",
                                 "Código não encontrado", "Cadastrar", "Cancelar"):
                from .produtos_tela import cadastro_rapido

                novo = cadastro_rapido(self.ctx, codigo)
                if novo:
                    self.incluir(novo)
            else:
                self.entrada_codigo.focus_set()
            return
        if self.incluir(produto):
            self.status(f"{produto['nome']} adicionado à contagem ({tipo}).")
            self.informar_contagem()

    def informar_contagem(self, linha: dict | None = None):
        if not self.exigir("estoque_movimentar", "fazer ajustes de inventário"):
            return
        linha = linha or self.tabela.linha_selecionada()
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione o item da contagem (ou adicione um produto).")
            return
        produto_id = int(linha["id"])
        item = self._itens.get(produto_id)
        if not item:
            return
        produto = item["produto"]
        saldo = estoque_mod.saldo(self.banco, produto_id)
        valor = dialogs.pedir_valor(
            self.ctx.janela, self.tema, f"Contagem — {produto['nome']}",
            rotulo=f"Quantidade contada ({produto['unidade_base'] or 'un'})",
            valor=(item["contado"] if item["contado"] is not None else saldo),
            tipo="quantidade", minimo=0.0,
            dica=f"Saldo no sistema: {formatar_quantidade(saldo)} {produto['unidade_base'] or 'un'}. "
                 f"Você pode informar em outra unidade no campo de observação do ajuste.",
        )
        if valor is None:
            return
        item["contado"] = float(valor)
        self._redesenhar()
        self.tabela.selecionar_por("id", produto_id)
        diferenca = float(valor) - saldo
        self.status(f"{produto['codigo']}: contado {formatar_quantidade(float(valor))} • "
                    f"diferença {'+' if diferenca > 0 else ''}{formatar_quantidade(diferenca)}")

    def remover_item(self):
        linha = self.tabela.linha_selecionada()
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione o item que deseja remover da contagem.")
            return
        self._itens.pop(int(linha["id"]), None)
        self._redesenhar()

    def carregar_estoque_baixo(self):
        if not self.exigir("estoque_movimentar", "fazer ajustes de inventário"):
            return
        adicionados = 0
        for item in estoque_mod.estoque_baixo(self.banco, limite=500):
            produto = produtos_mod.pegar(self.banco, item["id"])
            if produto and self.incluir(produto):
                adicionados += 1
        self._redesenhar()
        if adicionados:
            dialogs.info(self, self.tema, f"{adicionados} produto(s) com estoque baixo adicionados à contagem.")
        else:
            dialogs.info(self, self.tema, "Nenhum produto está abaixo do estoque mínimo.")

    def carregar_todos(self):
        if not self.exigir("estoque_movimentar", "fazer ajustes de inventário"):
            return
        produtos = produtos_mod.listar(self.banco, incluir_inativos=False)
        if len(produtos) > 300 and not dialogs.confirmar(
                self, self.tema,
                f"Serão adicionados {len(produtos)} produtos à folha de contagem.\n\nContinuar?",
                "Carregar todos", "Carregar", "Cancelar"):
            return
        for produto in produtos:
            self.incluir(produto)
        self._redesenhar()
        dialogs.info(self, self.tema, f"{len(produtos)} produto(s) adicionados à contagem.")

    def limpar(self):
        if not self._itens:
            dialogs.info(self, self.tema, "A folha de contagem já está vazia.")
            return
        if not dialogs.confirmar(self, self.tema,
                                 f"Limpar a folha de contagem ({len(self._itens)} item(ns))?\n\n"
                                 "Nenhuma movimentação gravada será desfeita.",
                                 "Limpar contagem", "Limpar", "Cancelar"):
            return
        self._itens.clear()
        self._redesenhar()

    def aplicar_ajustes(self):
        if not self.exigir("estoque_movimentar", "fazer ajustes de inventário"):
            return
        pendentes = [(produto_id, item) for produto_id, item in self._itens.items() if item["contado"] is not None]
        if not pendentes:
            dialogs.alerta(self, self.tema,
                           "Nenhum item com contagem informada.\n\n"
                           "Adicione produtos à folha e informe a quantidade contada (duplo clique ou F3).")
            return
        diferencas = []
        for produto_id, item in pendentes:
            saldo = estoque_mod.saldo(self.banco, produto_id)
            diferenca = float(item["contado"]) - saldo
            if abs(diferenca) > 1e-9:
                diferencas.append((produto_id, item, diferenca))
        if not diferencas:
            dialogs.sucesso(self, self.tema,
                            f"Todos os {len(pendentes)} item(ns) contado(s) conferem com o saldo do sistema.\n"
                            "Nenhum ajuste é necessário.")
            return
        valor_total = sum(
            int(round(diferenca * int(item["produto"]["preco_custo"] or 0)))
            for _produto_id, item, diferenca in diferencas
        )
        sobras = sum(1 for _p, _i, d in diferencas if d > 0)
        faltas = len(diferencas) - sobras
        if not dialogs.confirmar(
                self, self.tema,
                f"Aplicar {len(diferencas)} ajuste(s) de inventário?\n\n"
                f"• {sobras} sobra(s) → entrada de mercadoria\n"
                f"• {faltas} falta(s) → saída de mercadoria\n"
                f"• Valor líquido: {formatar_dinheiro(valor_total)}\n\n"
                f"Motivo: {self._motivo.get()}",
                "Aplicar ajustes", "Aplicar", "Cancelar"):
            return
        motivo = self._motivo_chave()
        observacao = self._observacao.get().strip()
        ok, falhas = 0, []
        for produto_id, item, diferenca in diferencas:
            try:
                estoque_mod.ajuste(self.banco, produto_id, float(item["contado"]), motivo=motivo,
                                   observacao=observacao, autor=self.usuario)
                ok += 1
            except estoque_mod.ErroEstoque as exc:
                falhas.append(f"{item['produto']['codigo']} — {item['produto']['nome']}: {exc}")
            except unidades_mod.ErroUnidade as exc:
                falhas.append(f"{item['produto']['codigo']}: {exc}")
        # marca os itens ajustados como conferidos (mantém a folha para auditoria)
        for produto_id, _item, _diferenca in diferencas:
            if produto_id in self._itens:
                self._itens[produto_id]["contado"] = None
        self.carregar()
        texto = f"{ok} ajuste(s) aplicado(s) com sucesso.\nValor líquido: {formatar_dinheiro(valor_total)}"
        if falhas:
            texto += "\n\nNão foi possível ajustar:\n" + "\n".join(f"• {f}" for f in falhas[:10])
            dialogs.alerta(self, self.tema, texto, "Ajustes aplicados com ressalvas")
        else:
            dialogs.sucesso(self, self.tema, texto, "Inventário atualizado")
        self.ctx.app.atualizar_caixa()

    def exportar(self):
        linhas = self._linhas()
        if not linhas:
            dialogs.alerta(self, self.tema, "A folha de contagem está vazia — adicione produtos antes de exportar.")
            return None
        return exportar_dados(
            self, self.tema, "Contagem de inventario", COLUNAS, linhas,
            periodo=f"Contagem de {hoje()}",
            filtros=f"motivo={self._motivo.get()}",
        )

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("produto_id"):
            produto = produtos_mod.pegar(self.banco, int(parametros["produto_id"]))
            if produto and self.incluir(produto):
                self.informar_contagem()
        if parametros.get("estoque_baixo"):
            self.carregar_estoque_baixo()

    def ao_sair(self):
        if not self._itens:
            return True
        resposta = dialogs.mensagem(
            self, self.tema, "Contagem em andamento",
            f"A folha de contagem tem {len(self._itens)} item(ns).\n\n"
            "O que deseja fazer antes de sair?",
            "pergunta", ("Descartar contagem", "Manter a folha aberta"),
        )
        if resposta == "Descartar contagem":
            self._itens.clear()
            self._redesenhar()
            return True
        return False
