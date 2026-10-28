"""
Tela de **Caixa** — abertura, movimentações (sangria, suprimento, despesas,
pagamento de contas), posição por forma de pagamento, fechamento com contagem
de gaveta e impressão do relatório de fechamento.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import caixa as caixa_mod
from ... import contas_pagar as contas_pagar_mod
from ... import contas_receber as contas_receber_mod
from ... import formas_pagamento
from ... import impressao as impressao_mod
from ...esquema import CATEGORIAS_DESPESA
from ...utils import formatar_data, formatar_dinheiro, hoje
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO, FONTE_VALOR
from ..widgets import Cartao, Tabela
from . import Tela, abrir_formulario, exportar_dados, imprimir_documento

COLUNAS_MOVIMENTOS = [
    {"chave": "hora", "rotulo": "Hora", "largura": 60, "alinhamento": "centro"},
    {"chave": "tipo_texto", "rotulo": "Tipo", "largura": 80, "alinhamento": "centro"},
    {"chave": "categoria", "rotulo": "Categoria", "largura": 150},
    {"chave": "descricao", "rotulo": "Descrição", "largura": 330},
    {"chave": "forma", "rotulo": "Forma", "largura": 120},
    {"chave": "valor", "rotulo": "Valor", "largura": 110, "tipo": "dinheiro"},
    {"chave": "usuario_nome", "rotulo": "Usuário", "largura": 140},
    {"chave": "referencia", "rotulo": "Referência", "largura": 100, "alinhamento": "centro"},
]

COLUNAS_CAIXAS = [
    {"chave": "data_texto", "rotulo": "Data", "largura": 100, "alinhamento": "centro"},
    {"chave": "usuario_nome", "rotulo": "Operador", "largura": 170},
    {"chave": "status_texto", "rotulo": "Situação", "largura": 100, "alinhamento": "centro"},
    {"chave": "valor_abertura", "rotulo": "Abertura", "largura": 110, "tipo": "dinheiro"},
    {"chave": "qtd_vendas", "rotulo": "Vendas", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
    {"chave": "total_vendas", "rotulo": "Total vendas", "largura": 120, "tipo": "dinheiro"},
    {"chave": "valor_sistema", "rotulo": "Sistema", "largura": 110, "tipo": "dinheiro"},
    {"chave": "valor_fechamento", "rotulo": "Contado", "largura": 110, "tipo": "dinheiro"},
    {"chave": "diferenca", "rotulo": "Diferença", "largura": 110, "tipo": "dinheiro"},
]


class CaixaTela(Tela):
    titulo = "Caixa"
    descricao = "Abertura, movimentações do dia, contagem de gaveta e fechamento."

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self.caixa_selecionado: int | None = None
        self._cartoes: list[Cartao] = []
        self._montar_interface()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.corpo.rowconfigure(2, weight=1)
        self.corpo.columnconfigure(0, weight=1)

        # --- cartões de posição
        self.quadro_cartoes = tk.Frame(self.corpo, background=self.tema.cor("bg"))
        self.quadro_cartoes.grid(row=0, column=0, sticky="ew")

        # --- botões de operação
        self.quadro_botoes = ttk.Frame(self.corpo, style="Card.TFrame", padding=(10, 6))
        self.quadro_botoes.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.botoes: dict[str, ttk.Button] = {}
        especificacoes = [
            ("🔓 Abrir caixa", self.abrir_caixa, "Sucesso.TButton"),
            ("💰 Sangria (retirada)", self.sangria, "TButton"),
            ("➕ Suprimento (troco)", self.suprimento, "TButton"),
            ("🧾 Despesa do caixa", self.despesa, "TButton"),
            ("📥 Receber fiado", self.receber_fiado, "TButton"),
            ("📤 Pagar conta", self.pagar_conta, "TButton"),
            ("🔐 Fechar caixa", self.fechar_caixa, "Perigo.TButton"),
            ("🖨️ Relatório de fechamento", self.relatorio_fechamento, "TButton"),
            ("↺ Estornar lançamento", self.estornar_movimento, "TButton"),
            ("⟳ Atualizar", self.carregar, "TButton"),
            ("⭳ Exportar movimentos", self.exportar, "TButton"),
        ]
        for indice, (texto, comando, estilo) in enumerate(especificacoes):
            botao = ttk.Button(self.quadro_botoes, text=texto, command=comando, style=estilo)
            botao.grid(row=indice // 6, column=indice % 6, sticky="ew", padx=3, pady=3)
            self.quadro_botoes.columnconfigure(indice % 6, weight=1)
            self.botoes[texto] = botao

        # --- abas: movimentos e histórico de caixas
        self.abas = ttk.Notebook(self.corpo)
        self.abas.grid(row=2, column=0, sticky="nsew")

        quadro_movimentos = ttk.Frame(self.abas, style="TFrame", padding=6)
        self.abas.add(quadro_movimentos, text="Movimentações do caixa selecionado")
        filtro = ttk.Frame(quadro_movimentos, style="TFrame")
        filtro.pack(fill="x", pady=(0, 6))
        ttk.Label(filtro, text="Categoria:", style="TLabel").pack(side="left")
        self.combo_categoria = ttk.Combobox(filtro, width=20, state="readonly",
                                            values=["(todas)"] + list(caixa_mod.CATEGORIAS_MOVIMENTO))
        self.combo_categoria.set("(todas)")
        self.combo_categoria.pack(side="left", padx=(4, 10))
        self.combo_categoria.bind("<<ComboboxSelected>>", lambda e: self._carregar_movimentos())
        ttk.Label(filtro, text="Forma:", style="TLabel").pack(side="left")
        self.combo_forma = ttk.Combobox(filtro, width=18, state="readonly",
                                        values=["(todas)"] + list(formas_pagamento.TODAS))
        self.combo_forma.set("(todas)")
        self.combo_forma.pack(side="left", padx=(4, 10))
        self.combo_forma.bind("<<ComboboxSelected>>", lambda e: self._carregar_movimentos())
        ttk.Label(filtro, text="Tipo:", style="TLabel").pack(side="left")
        self.combo_tipo = ttk.Combobox(filtro, width=12, state="readonly",
                                       values=["(ambos)", "entrada", "saida"])
        self.combo_tipo.set("(ambos)")
        self.combo_tipo.pack(side="left", padx=(4, 10))
        self.combo_tipo.bind("<<ComboboxSelected>>", lambda e: self._carregar_movimentos())
        self.rotulo_caixa_atual = ttk.Label(filtro, text="", style="TLabel", font=FONTE_SUBTITULO)
        self.rotulo_caixa_atual.pack(side="left", padx=(10, 0))

        self.tabela_movimentos = Tabela(quadro_movimentos, self.tema, COLUNAS_MOVIMENTOS, altura=14)
        self.tabela_movimentos.pack(fill="both", expand=True)

        quadro_caixas = ttk.Frame(self.abas, style="TFrame", padding=6)
        self.abas.add(quadro_caixas, text="Histórico de caixas")
        self.tabela_caixas = Tabela(quadro_caixas, self.tema, COLUNAS_CAIXAS,
                                    ao_selecionar=self._ao_selecionar_caixa,
                                    ao_duplo_clique=self._abrir_caixa_selecionado, altura=14)
        self.tabela_caixas.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ dados
    def carregar(self):
        self._carregar_cartoes()
        self._carregar_caixas()
        self._carregar_movimentos()
        self._atualizar_botoes()

    def _caixa_foco(self):
        """Caixa que deve ser exibido: o selecionado no histórico ou o aberto."""
        if self.caixa_selecionado:
            return caixa_mod.pegar(self.banco, self.caixa_selecionado)
        return caixa_mod.caixa_aberto(self.banco)

    def _carregar_cartoes(self):
        for filho in self.quadro_cartoes.winfo_children():
            filho.destroy()
        self._cartoes.clear()
        caixa = self._caixa_foco()
        if caixa is None:
            cartao = Cartao(self.quadro_cartoes, self.tema, "Caixa", "Fechado",
                            "Nenhum caixa aberto. Clique em 'Abrir caixa' para começar o dia.", cor="alerta",
                            largura_minima=260, ao_clicar=self.abrir_caixa)
            cartao.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            self.quadro_cartoes.columnconfigure(0, weight=1)
            self._cartoes.append(cartao)
            return
        posicao = caixa_mod.posicao(self.banco, int(caixa["id"]))
        dinheiro = posicao["formas"].get("Dinheiro", {})
        fechado = caixa["status"] == "fechado"
        cartoes = [
            {"titulo": f"Caixa de {formatar_data(caixa['data'])}",
             "valor": "Fechado" if fechado else "Aberto",
             "detalhe": f"Operador: {caixa['usuario_nome'] or '—'}",
             "cor": "neutro" if fechado else "sucesso"},
            {"titulo": "Abertura", "valor": formatar_dinheiro(posicao["abertura"]),
             "detalhe": "Fundo de troco informado", "cor": "info"},
            {"titulo": "Vendas", "valor": formatar_dinheiro(posicao["total_vendas"]),
             "detalhe": f"{posicao['qtd_vendas']} cupom(ns) • lucro {formatar_dinheiro(posicao['lucro_vendas'])}",
             "cor": "info"},
            {"titulo": "Dinheiro na gaveta", "valor": formatar_dinheiro(int(dinheiro.get("saldo", 0) or 0)),
             "detalhe": f"entradas {formatar_dinheiro(int(dinheiro.get('entradas', 0) or 0))} • "
                        f"saídas {formatar_dinheiro(int(dinheiro.get('saidas', 0) or 0))}", "cor": "sucesso"},
            {"titulo": "Pix / cartões", "valor": formatar_dinheiro(
                posicao["total_recebido"] - int(dinheiro.get("entradas", 0) or 0)),
             "detalhe": "Valores que não passam pela gaveta", "cor": "info"},
            {"titulo": "Contado no fechamento" if fechado else "Esperado pelo sistema",
             "valor": formatar_dinheiro(int(caixa["valor_fechamento"] or 0) if fechado else posicao["valor_sistema"]),
             "detalhe": (f"Diferença: {formatar_dinheiro(posicao['diferenca'])}" if fechado
                         else "Conferir na hora de fechar"),
             "cor": ("perigo" if fechado and posicao["diferenca"] else ("sucesso" if fechado else "neutro"))},
        ]
        for indice, dados in enumerate(cartoes):
            cartao = Cartao(self.quadro_cartoes, self.tema, **dados, largura_minima=180)
            cartao.grid(row=indice // 6, column=indice % 6, sticky="nsew", padx=(0, 8), pady=(0, 6))
            self.quadro_cartoes.columnconfigure(indice % 6, weight=1)
            self._cartoes.append(cartao)

    def _carregar_caixas(self):
        caixas = caixa_mod.listar(self.banco, limite=300)
        linhas = []
        for caixa in caixas:
            linha = dict(caixa)
            linha["data_texto"] = formatar_data(caixa["data"])
            linha["status_texto"] = "Aberto" if caixa["status"] == "aberto" else "Fechado"
            linha["_tag"] = "sucesso" if caixa["status"] == "aberto" else (
                "perigo" if int(caixa["diferenca"] or 0) != 0 else "")
            linhas.append(linha)
        self.tabela_caixas.carregar(
            linhas,
            resumo=f"{len(linhas)} caixa(s) • {sum(1 for l in linhas if l['status'] == 'aberto')} aberto(s)",
        )

    def _carregar_movimentos(self):
        caixa = self._caixa_foco()
        if caixa is None:
            self.tabela_movimentos.carregar([], resumo="Nenhum caixa aberto ou selecionado.")
            self.rotulo_caixa_atual.configure(text="Nenhum caixa selecionado")
            return
        categoria = self.combo_categoria.get()
        forma = self.combo_forma.get()
        tipo = self.combo_tipo.get()
        movimentos = caixa_mod.movimentos(
            self.banco, int(caixa["id"]),
            categoria=("" if categoria == "(todas)" else categoria),
            forma=("" if forma == "(todas)" else forma),
            tipo=("" if tipo == "(ambos)" else tipo),
        )
        linhas = []
        total_entradas = total_saidas = 0
        for movimento in movimentos:
            linha = dict(movimento)
            linha["hora"] = formatar_data(movimento["criado_em"], com_hora=True)[11:16]
            linha["tipo_texto"] = "Entrada" if movimento["tipo"] == "entrada" else "Saída"
            linha["_tag"] = "sucesso" if movimento["tipo"] == "entrada" else "perigo"
            if movimento["tipo"] == "entrada":
                total_entradas += int(movimento["valor"] or 0)
            else:
                total_saidas += int(movimento["valor"] or 0)
            linhas.append(linha)
        self.rotulo_caixa_atual.configure(
            text=f"Caixa de {formatar_data(caixa['data'])} ({caixa['status']}) — {formatar_dinheiro(total_entradas)} em entradas "
                 f"e {formatar_dinheiro(total_saidas)} em saídas"
        )
        self.tabela_movimentos.carregar(
            linhas, resumo=f"{len(linhas)} lançamento(s) • entradas {formatar_dinheiro(total_entradas)} • "
                           f"saídas {formatar_dinheiro(total_saidas)}",
        )

    def _atualizar_botoes(self):
        caixa = caixa_mod.caixa_aberto(self.banco)
        aberto = caixa is not None
        pode_operar = self.pode("caixa")
        for texto, estado in (
            ("🔓 Abrir caixa", not aberto and pode_operar),
            ("💰 Sangria (retirada)", aberto and pode_operar),
            ("➕ Suprimento (troco)", aberto and pode_operar),
            ("🧾 Despesa do caixa", aberto and pode_operar),
            ("📥 Receber fiado", aberto and self.pode("contas_receber")),
            ("📤 Pagar conta", aberto and self.pode("contas_pagar")),
            ("🔐 Fechar caixa", aberto and pode_operar),
            ("↺ Estornar lançamento", aberto and pode_operar),
        ):
            self.botoes[texto].configure(state=("normal" if estado else "disabled"))
        self.ctx.caixa_aberto = caixa
        self.ctx.app.atualizar_caixa()

    def _ao_selecionar_caixa(self, linha: dict | None):
        if linha:
            self.caixa_selecionado = int(linha["id"])
            self._carregar_cartoes()
            self._carregar_movimentos()
            self._atualizar_botoes()
            self.abas.select(0)

    def _abrir_caixa_selecionado(self, linha: dict):
        self.caixa_selecionado = int(linha["id"])
        self.abas.select(0)
        self._carregar_cartoes()
        self._carregar_movimentos()

    # ------------------------------------------------------------------ operações
    def abrir_caixa(self):
        if not self.exigir("caixa", "abrir o caixa"):
            return
        if caixa_mod.caixa_aberto(self.banco):
            dialogs.alerta(self, self.tema, "Já existe um caixa aberto. Feche-o antes de abrir outro.")
            return
        dados = abrir_formulario(
            self, "Abertura de caixa",
            [
                {"chave": "valor", "rotulo": "Valor inicial em gaveta (troco)", "tipo": "dinheiro", "largura": 16},
                {"chave": "data", "rotulo": "Data", "tipo": "data", "padrao_hoje": True},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            {"valor": 0}, largura=520,
            texto="O valor inicial é o dinheiro físico que já está na gaveta (fundo de troco). "
                  "Ele entra como movimento de 'Abertura'.",
        )
        if not dados:
            return
        try:
            caixa_id = caixa_mod.abrir(self.banco, valor_abertura=int(dados["valor"] or 0),
                                       observacao=dados.get("observacao", ""), data=dados.get("data", ""),
                                       autor=self.usuario)
        except caixa_mod.ErroCaixa as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.caixa_selecionado = None
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Caixa aberto com {formatar_dinheiro(int(dados['valor'] or 0))} em gaveta.\n"
                        "Boas vendas!")

    def sangria(self):
        if not self.exigir("caixa", "fazer sangria"):
            return
        caixa = caixa_mod.exigir_aberto(self.banco)
        disponivel = caixa_mod.por_forma(self.banco, int(caixa["id"])).get("Dinheiro", {}).get("saldo", 0)
        dados = abrir_formulario(
            self, "Sangria (retirada de dinheiro)",
            [
                {"chave": "valor", "rotulo": "Valor retirado", "tipo": "dinheiro", "obrigatorio": True, "largura": 16},
                {"chave": "motivo", "rotulo": "Motivo", "tipo": "texto", "largura": 34, "colunas": 2,
                 "dica": "Ex.: depósito bancário, retirada do sócio"},
            ],
            {"valor": 0}, largura=500,
            texto=f"Dinheiro disponível na gaveta: {formatar_dinheiro(int(disponivel))}.",
        )
        if not dados:
            return
        try:
            caixa_mod.sangria(self.banco, int(dados["valor"]), motivo=dados.get("motivo", ""), autor=self.usuario)
        except caixa_mod.ErroCaixa as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, f"Sangria de {formatar_dinheiro(int(dados['valor']))} registrada.")

    def suprimento(self):
        if not self.exigir("caixa", "fazer suprimento"):
            return
        dados = abrir_formulario(
            self, "Suprimento (reforço de troco)",
            [
                {"chave": "valor", "rotulo": "Valor em dinheiro", "tipo": "dinheiro", "obrigatorio": True, "largura": 16},
                {"chave": "motivo", "rotulo": "Motivo", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            {"valor": 0}, largura=500,
            texto="Entrada de dinheiro que não vem de venda (ex.: troco trazido do cofre).",
        )
        if not dados:
            return
        try:
            caixa_mod.suprimento(self.banco, int(dados["valor"]), motivo=dados.get("motivo", ""), autor=self.usuario)
        except caixa_mod.ErroCaixa as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, f"Suprimento de {formatar_dinheiro(int(dados['valor']))} registrado.")

    def despesa(self):
        if not self.exigir("caixa", "lançar despesas no caixa"):
            return
        dados = abrir_formulario(
            self, "Despesa paga no caixa",
            [
                {"chave": "descricao", "rotulo": "Descrição", "tipo": "texto", "obrigatorio": True, "largura": 34,
                 "colunas": 2},
                {"chave": "valor", "rotulo": "Valor", "tipo": "dinheiro", "obrigatorio": True, "largura": 14},
                {"chave": "categoria", "rotulo": "Categoria", "tipo": "lista", "opcoes": CATEGORIAS_DESPESA, "largura": 24},
                {"chave": "forma", "rotulo": "Forma de pagamento", "tipo": "lista",
                 "opcoes": formas_pagamento.IMEDIATAS, "largura": 22},
            ],
            {"valor": 0, "categoria": "Outros", "forma": "Dinheiro"}, largura=560,
            texto="Despesa paga na hora, saindo do caixa. Para contas com vencimento use 'Contas a pagar'.",
        )
        if not dados:
            return
        try:
            caixa_mod.lancar_despesa(self.banco, dados["descricao"], int(dados["valor"]),
                                     categoria_despesa=dados.get("categoria", "Outros"),
                                     forma=dados.get("forma", "Dinheiro"), autor=self.usuario)
        except caixa_mod.ErroCaixa as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, f"Despesa de {formatar_dinheiro(int(dados['valor']))} lançada no caixa.")

    def receber_fiado(self):
        """Recebe um título em aberto direto do caixa."""
        if not self.exigir("contas_receber", "receber valores de clientes"):
            return
        contas = contas_receber_mod.listar(self.banco, status="pendentes")
        if not contas:
            dialogs.info(self, self.tema, "Nenhuma conta a receber em aberto.")
            return
        colunas = [
            {"chave": "cliente_nome", "rotulo": "Cliente", "largura": 240},
            {"chave": "descricao", "rotulo": "Descrição", "largura": 240},
            {"chave": "vencimento_texto", "rotulo": "Vencimento", "largura": 100, "alinhamento": "centro"},
            {"chave": "saldo", "rotulo": "Saldo", "largura": 110, "tipo": "dinheiro"},
        ]
        dados = [{**dict(c), "vencimento_texto": formatar_data(c["vencimento"])} for c in contas]
        linha = dialogs.selecionar_registro(self, self.tema, "Receber fiado (contas a receber)", colunas, dados,
                                            largura=780, texto="Selecione o título e o valor a receber.")
        if not linha:
            return
        conta = contas_receber_mod.pegar(self.banco, int(linha["id"]))
        valores = abrir_formulario(
            self, f"Recebimento — {conta['cliente_nome']}",
            [
                {"chave": "valor", "rotulo": "Valor recebido", "tipo": "dinheiro", "obrigatorio": True, "largura": 16},
                {"chave": "forma", "rotulo": "Forma", "tipo": "lista", "opcoes": formas_pagamento.PARA_RECEBIMENTOS,
                 "largura": 22},
                {"chave": "desconto", "rotulo": "Desconto concedido", "tipo": "dinheiro", "largura": 14},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            {"valor": int(conta["saldo"] or 0), "forma": "Dinheiro", "desconto": 0}, largura=520,
            texto=f"Saldo do título: {formatar_dinheiro(int(conta['saldo'] or 0))} (vence em "
                  f"{formatar_data(conta['vencimento'])}).",
        )
        if not valores:
            return
        try:
            resultado = contas_receber_mod.receber(self.banco, int(conta["id"]), int(valores["valor"]),
                                                   forma=valores.get("forma", "Dinheiro"),
                                                   desconto=int(valores.get("desconto") or 0),
                                                   observacao=valores.get("observacao", ""), autor=self.usuario)
        except contas_receber_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Recebido {formatar_dinheiro(resultado['recebido'])}.\n"
                        f"Saldo restante: {formatar_dinheiro(resultado['saldo'])} ({resultado['status']}).")

    def pagar_conta(self):
        """Paga uma conta a pagar usando o caixa do dia."""
        if not self.exigir("contas_pagar", "pagar contas"):
            return
        contas = contas_pagar_mod.listar(self.banco, status="pendentes")
        if not contas:
            dialogs.info(self, self.tema, "Nenhuma conta a pagar em aberto.")
            return
        colunas = [
            {"chave": "descricao", "rotulo": "Descrição", "largura": 260},
            {"chave": "fornecedor_nome", "rotulo": "Fornecedor", "largura": 200},
            {"chave": "categoria", "rotulo": "Categoria", "largura": 140},
            {"chave": "vencimento_texto", "rotulo": "Vencimento", "largura": 100, "alinhamento": "centro"},
            {"chave": "saldo", "rotulo": "Saldo", "largura": 110, "tipo": "dinheiro"},
        ]
        dados = [{**dict(c), "vencimento_texto": formatar_data(c["vencimento"])} for c in contas]
        linha = dialogs.selecionar_registro(self, self.tema, "Pagar conta (contas a pagar)", colunas, dados,
                                            largura=820, texto="Selecione a conta que será paga agora.")
        if not linha:
            return
        conta = contas_pagar_mod.pegar(self.banco, int(linha["id"]))
        valores = abrir_formulario(
            self, f"Pagamento — {conta['descricao']}",
            [
                {"chave": "valor", "rotulo": "Valor pago", "tipo": "dinheiro", "obrigatorio": True, "largura": 16},
                {"chave": "forma", "rotulo": "Forma", "tipo": "lista", "opcoes": formas_pagamento.IMEDIATAS,
                 "largura": 22},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            {"valor": int(conta["saldo"] or 0), "forma": "Dinheiro"}, largura=520,
            texto=f"Saldo da conta: {formatar_dinheiro(int(conta['saldo'] or 0))}.",
        )
        if not valores:
            return
        try:
            resultado = contas_pagar_mod.pagar(self.banco, int(conta["id"]), int(valores["valor"]),
                                               forma=valores.get("forma", "Dinheiro"),
                                               observacao=valores.get("observacao", ""), autor=self.usuario)
        except contas_pagar_mod.ErroContaPagar as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Pagamento de {formatar_dinheiro(resultado['pago'])} registrado.\n"
                        f"Saldo restante: {formatar_dinheiro(resultado['saldo'])}.")

    def estornar_movimento(self):
        if not self.exigir("caixa", "estornar lançamentos do caixa"):
            return
        movimento = self.tabela_movimentos.linha_selecionada()
        if not movimento:
            dialogs.alerta(self, self.tema, "Selecione o lançamento que deseja estornar.")
            return
        if movimento["categoria"] in ("Venda", "Abertura", "Devolução", "Recebimento fiado", "Pagamento conta"):
            dialogs.alerta(self, self.tema,
                           "Este lançamento foi gerado automaticamente por outra operação.\n"
                           "Para desfazer, cancele/devolva a venda pela tela de Vendas, ou estorne o "
                           "recebimento/pagamento na tela financeira correspondente.")
            return
        if not dialogs.confirmar(self, self.tema,
                                 f"Estornar o lançamento '{movimento['categoria']} — {movimento['descricao']}' "
                                 f"({formatar_dinheiro(int(movimento['valor']))})?\n\nO movimento será removido do caixa.",
                                 "Estornar lançamento", "Estornar", "Cancelar"):
            return
        try:
            caixa_mod.cancelar_movimento(self.banco, int(movimento["id"]), autor=self.usuario)
        except caixa_mod.ErroCaixa as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, "Lançamento estornado.")

    def fechar_caixa(self):
        if not self.exigir("caixa", "fechar o caixa"):
            return
        caixa = caixa_mod.caixa_aberto(self.banco)
        if not caixa:
            dialogs.alerta(self, self.tema, "Não há caixa aberto para fechar.")
            return
        posicao = caixa_mod.posicao(self.banco, int(caixa["id"]))
        dinheiro = posicao["formas"].get("Dinheiro", {})
        dialogo = dialogs.Modal(self, self.tema, "Fechamento de caixa", largura=560, altura=520)
        linhas_resumo = [
            f"Caixa de {formatar_data(caixa['data'])} — operador {caixa['usuario_nome'] or '—'}",
            f"Abertura: {formatar_dinheiro(posicao['abertura'])}",
            f"Vendas: {posicao['qtd_vendas']} cupom(ns), total {formatar_dinheiro(posicao['total_vendas'])}",
            f"Entradas: {formatar_dinheiro(posicao['total_recebido'])} • Saídas: {formatar_dinheiro(posicao['total_pago'])}",
            f"Dinheiro esperado na gaveta (sistema): {formatar_dinheiro(int(dinheiro.get('saldo', 0) or 0))}",
        ]
        for forma, valores in sorted(posicao["formas"].items()):
            if forma != "Dinheiro":
                linhas_resumo.append(f"    {forma}: {formatar_dinheiro(valores['saldo'])}")
        ttk.Label(dialogo.corpo, text="\n".join(linhas_resumo), style="TLabel", justify="left",
                  wraplength=520, font=FONTE_PEQUENA).pack(anchor="w")
        ttk.Label(dialogo.corpo, text="Valor contado na gaveta (apenas dinheiro):", style="TLabel").pack(
            anchor="w", pady=(12, 2))
        entrada = ttk.Entry(dialogo.corpo, width=18, justify="right", font=FONTE_SUBTITULO)
        entrada.pack(anchor="w")
        entrada.insert(0, f"{(dinheiro.get('saldo', 0) or 0) / 100:.2f}".replace(".", ","))
        entrada.select_range(0, "end")
        entrada.focus_set()
        rotulo_diferenca = ttk.Label(dialogo.corpo, text="", style="TLabel", font=FONTE_SUBTITULO)
        rotulo_diferenca.pack(anchor="w", pady=(6, 0))
        ttk.Label(dialogo.corpo, text="Observação do fechamento:", style="TLabel").pack(anchor="w", pady=(10, 2))
        entrada_obs = ttk.Entry(dialogo.corpo, width=56)
        entrada_obs.pack(anchor="w", fill="x")

        esperado = int(dinheiro.get("saldo", 0) or 0)

        def contar(_evento=None) -> int:
            from ...utils import para_centavos

            try:
                contado = int(para_centavos(entrada.get()))
            except Exception:
                contado = 0
            diferenca = contado - esperado
            if diferenca == 0:
                rotulo_diferenca.configure(text="Diferença: R$ 0,00 (caixa fecha certo ✔)",
                                           foreground=self.tema.cor("sucesso"))
            else:
                rotulo_diferenca.configure(
                    text=f"Diferença: {formatar_dinheiro(diferenca)} "
                         f"({'sobra' if diferenca > 0 else 'falta'})",
                    foreground=self.tema.cor("alerta" if diferenca > 0 else "perigo"),
                )
            return contado

        entrada.bind("<KeyRelease>", contar)
        contar()

        def confirmar():
            contado = contar()
            diferenca = contado - esperado
            if diferenca != 0:
                if not dialogs.confirmar(
                    dialogo, self.tema,
                    f"A contagem difere do sistema em {formatar_dinheiro(diferenca)} "
                    f"({'sobra' if diferenca > 0 else 'falta de dinheiro'}). \n\n"
                    "A diferença ficará registrada como quebra de caixa. Confirmar o fechamento?",
                    "Confirmar fechamento", "Fechar caixa", "Voltar",
                ):
                    return
            if not dialogs.confirmar(dialogo, self.tema,
                                     "Fechar o caixa?\nDepois de fechado, os lançamentos não podem mais ser alterados.",
                                     "Fechar caixa", "Fechar", "Cancelar"):
                return
            try:
                resultado = caixa_mod.fechar(self.banco, int(caixa["id"]), contado,
                                             observacao=entrada_obs.get().strip(), autor=self.usuario)
            except caixa_mod.ErroCaixa as exc:
                dialogs.erro(dialogo, self.tema, str(exc))
                return
            dialogo.confirmar(resultado)

        dialogo.barra_botoes((("Fechar caixa", confirmar, "Perigo.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
        resultado = dialogo.abrir()
        if not resultado:
            return
        self.caixa_selecionado = int(caixa["id"])
        self.carregar()
        self.abas.select(0)
        texto = [
            "Caixa fechado com sucesso.",
            f"Esperado pelo sistema: {formatar_dinheiro(resultado['valor_sistema'])}",
            f"Contado: {formatar_dinheiro(resultado['valor_contado'])}",
            f"Diferença: {formatar_dinheiro(resultado['diferenca'])}",
        ]
        if dialogs.confirmar(self, self.tema, "\n".join(texto) + "\n\nImprimir o relatório de fechamento?",
                             "Fechamento concluído", "Imprimir", "Fechar"):
            self.relatorio_fechamento(int(caixa["id"]))

    def relatorio_fechamento(self, caixa_id: int | None = None):
        caixa = caixa_mod.pegar(self.banco, caixa_id) if caixa_id else self._caixa_foco()
        if not caixa:
            dialogs.alerta(self, self.tema, "Selecione um caixa no histórico (ou abra o caixa do dia).")
            return
        try:
            caminho = impressao_mod.gerar_fechamento_caixa_pdf(self.banco, int(caixa["id"]))
        except impressao_mod.ErroImpressao as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        imprimir_documento(self, self.tema, caminho, f"Fechamento de caixa {formatar_data(caixa['data'])}")

    def exportar(self):
        linhas = self.tabela_movimentos.registros()
        if not linhas:
            dialogs.alerta(self, self.tema, "Não há movimentos para exportar.")
            return
        exportar_dados(self, self.tema, "Movimentações de caixa", COLUNAS_MOVIMENTOS, linhas,
                       periodo=f"Gerado em {hoje()}", filtros=self.rotulo_caixa_atual.cget("text"))

    # ------------------------------------------------------------------ diversos
    def focar_busca(self):
        self.tabela_movimentos.focar_busca()

    def atualizar_tema(self):
        for cartao in self._cartoes:
            cartao.atualizar_tema()
        self.tabela_movimentos.atualizar_tema()
        self.tabela_caixas.atualizar_tema()
        self.quadro_cartoes.configure(background=self.tema.cor("bg"))
        self.carregar()

    def ao_entrar(self):
        self.carregar()
