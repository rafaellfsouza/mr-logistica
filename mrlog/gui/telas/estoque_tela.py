"""
Tela de **Movimentações de estoque** — entradas, saídas e histórico completo.

Além da grade com filtros (período, tipo, motivo, produto, usuário), a tela
oferece:
- lançamento de **entrada** (compra, devolução de cliente, produção...) com custo,
  lote, validade e fornecedor;
- lançamento de **saída** (perda, devolução a fornecedor, consumo interno...);
- **ficha do produto** com saldo, lotes e últimas movimentações;
- **auditoria de saldos** (compara o saldo gravado com o recalculado pelo histórico);
- atalho para o ajuste de inventário.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import estoque as estoque_mod
from ... import fornecedores as fornecedores_mod
from ... import produtos as produtos_mod
from ... import unidades as unidades_mod
from ... import usuarios as usuarios_mod
from ...esquema import MOTIVOS_ENTRADA, MOTIVOS_SAIDA
from ...utils import (
    converter_data_br,
    formatar_data,
    formatar_dinheiro,
    formatar_quantidade,
    hoje,
    intervalo_padrao,
)
from .. import dialogs
from ..widgets import (
    CampoData,
    CampoDinheiro,
    CampoLista,
    CampoQuantidade,
    CampoTexto,
    QuadroRolavel,
    Tabela,
)
from . import TelaLista
from .produtos_tela import selecionar_produto

#: Todos os motivos conhecidos (entrada + saída + ajuste), com a descrição amigável.
MOTIVOS = estoque_mod.MOTIVOS

#: Motivos que merecem destaque vermelho na grade (perda de mercadoria).
MOTIVOS_CRITICOS = {"perda", "vencimento"}

OPCOES_TIPO = [("", "Todos os tipos"), ("entrada", "Somente entradas"),
               ("saida", "Somente saídas"), ("ajuste", "Somente ajustes")]


# --------------------------------------------------------------------------------------
# Lançamento de entrada / saída
# --------------------------------------------------------------------------------------


class DialogoMovimentacao(dialogs.Modal):
    """Formulário de entrada ou saída de mercadoria.

    O campo de código de barras mantém o foco para o operador **bipar** a mercadoria
    (o leitor USB funciona como teclado). Depois do bip, o foco vai para a quantidade.
    """

    def __init__(self, ctx, tipo: str = "entrada", produto=None, motivo_padrao: str = ""):
        self.ctx = ctx
        self.banco = ctx.banco
        self.tipo = "saida" if str(tipo).lower() == "saida" else "entrada"
        titulo = "Entrada de mercadoria" if self.tipo == "entrada" else "Saída de mercadoria"
        super().__init__(ctx.janela, ctx.tema, titulo, largura=760, altura=660)
        self.produto = produto
        self._motivo_padrao = motivo_padrao

        rolavel = QuadroRolavel(self.corpo, self.tema)
        rolavel.pack(fill="both", expand=True)
        quadro = rolavel.quadro
        quadro.columnconfigure(1, weight=1)

        # --- produto (com bipador) --------------------------------------------------
        ttk.Label(quadro, text="Produto", style="TLabel", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        linha_produto = ttk.Frame(quadro, style="TFrame")
        linha_produto.grid(row=1, column=0, columnspan=3, sticky="ew")
        linha_produto.columnconfigure(1, weight=1)
        ttk.Label(linha_produto, text="Bipe ou digite o código:", style="TLabel").grid(row=0, column=0, sticky="w")
        self.entrada_codigo = ttk.Entry(linha_produto, width=22)
        self.entrada_codigo.grid(row=0, column=1, sticky="ew", padx=6)
        self.entrada_codigo.bind("<Return>", lambda e: self._resolver_codigo())
        ttk.Button(linha_produto, text="Buscar (F2)", command=self.buscar_produto).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(linha_produto, text="Cadastrar", command=self._cadastrar_produto).grid(row=0, column=3)

        self.rotulo_produto = tk.Label(
            quadro, text="Nenhum produto selecionado.", anchor="w", justify="left", wraplength=680,
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg_suave"), font=("Segoe UI", 10),
        )
        self.rotulo_produto.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 10))

        # --- quantidade / unidade / motivo ------------------------------------------
        motivos = MOTIVOS_ENTRADA if self.tipo == "entrada" else MOTIVOS_SAIDA
        self.campo_quantidade = CampoQuantidade(quadro, self.tema, "Quantidade", obrigatorio=True, largura=12,
                                                decimais=4, ao_alterar=lambda _v: self._atualizar_resumo())
        self.campo_quantidade.grid(row=3, column=0, sticky="nw", padx=(0, 12), pady=4)
        self.campo_unidade = CampoLista(quadro, self.tema, "Unidade", largura=18,
                                        ao_alterar=lambda _v: self._atualizar_resumo())
        self.campo_unidade.grid(row=3, column=1, sticky="nw", padx=(0, 12), pady=4)
        self.campo_motivo = CampoLista(quadro, self.tema, "Motivo", obrigatorio=True, largura=30,
                                       opcoes=[(chave, texto) for chave, texto in motivos.items()])
        self.campo_motivo.grid(row=3, column=2, sticky="nw", pady=4)
        if self._motivo_padrao in motivos:
            self.campo_motivo.definir(self._motivo_padrao)

        # --- custo / lote / fornecedor ----------------------------------------------
        linha = 4
        if self.tipo == "entrada":
            self.campo_custo = CampoDinheiro(quadro, self.tema, "Custo unitário", largura=14,
                                             dica="Por unidade de estoque; alimenta o custo médio",
                                             ao_alterar=lambda _v: self._atualizar_resumo())
            self.campo_custo.grid(row=linha, column=0, sticky="nw", padx=(0, 12), pady=4)
            self.campo_fornecedor = CampoLista(quadro, self.tema, "Fornecedor", largura=28, vazio="(sem fornecedor)",
                                               opcoes=fornecedores_mod.opcoes(self.banco))
            self.campo_fornecedor.grid(row=linha, column=1, sticky="nw", padx=(0, 12), pady=4)
            self.campo_documento = CampoTexto(quadro, self.tema, "Nº do documento / nota", largura=18)
            self.campo_documento.grid(row=linha, column=2, sticky="nw", pady=4)
            linha += 1
        else:
            self.campo_custo = None
            self.campo_fornecedor = None
            self.campo_documento = None

        self.quadro_lote = ttk.Frame(quadro, style="TFrame")
        self.quadro_lote.grid(row=linha, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.campo_lote = CampoTexto(self.quadro_lote, self.tema, "Número do lote", largura=18)
        self.campo_lote.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.campo_validade = CampoData(self.quadro_lote, self.tema, "Validade", largura=12)
        self.campo_validade.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.rotulo_lote = ttk.Label(self.quadro_lote, text="", style="Suave.TLabel", wraplength=380, justify="left")
        self.rotulo_lote.grid(row=1, column=0, columnspan=3, sticky="w")

        self.campo_observacao = CampoTexto(quadro, self.tema, "Observação", largura=60, multilinea=True, altura=3)
        self.campo_observacao.grid(row=linha + 1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        # --- resumo ------------------------------------------------------------------
        self.rotulo_resumo = tk.Label(
            quadro, text="", anchor="w", justify="left", wraplength=680,
            background=self.tema.cor("bg_alt"), foreground=self.tema.cor("fg"), font=("Segoe UI", 9),
        )
        self.rotulo_resumo.grid(row=linha + 2, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        rotulo_botao = "Confirmar entrada" if self.tipo == "entrada" else "Confirmar saída"
        self.barra_botoes(((rotulo_botao, self.salvar, "Primario.TButton"), ("Cancelar", self.cancelar, "TButton")))
        self.bind("<F2>", lambda e: self.buscar_produto())
        self.definir_produto(self.produto, focar_quantidade=bool(produto))

    # ------------------------------------------------------------------ produto
    def buscar_produto(self):
        produto = selecionar_produto(self.ctx, "Selecionar produto para movimentação")
        if produto:
            self.definir_produto(produto, focar_quantidade=True)

    def _cadastrar_produto(self):
        from .produtos_tela import cadastro_rapido

        produto = cadastro_rapido(self.ctx, self.entrada_codigo.get().strip())
        if produto:
            self.definir_produto(produto, focar_quantidade=True)

    def _resolver_codigo(self):
        codigo = self.entrada_codigo.get().strip()
        if not codigo:
            return
        produto, tipo = produtos_mod.resolver_bipagem(self.banco, codigo)
        if not produto:
            if dialogs.confirmar(self, self.tema,
                                 f"Nenhum produto cadastrado com o código “{codigo}”.\n\n"
                                 "Deseja cadastrá-lo agora?", "Código não encontrado", "Cadastrar", "Cancelar"):
                self._cadastrar_produto()
            return
        self.definir_produto(produto, focar_quantidade=True)

    def definir_produto(self, produto, focar_quantidade: bool = False):
        self.produto = produto
        self.entrada_codigo.delete(0, "end")
        if not produto:
            self.rotulo_produto.configure(text="Nenhum produto selecionado.", foreground=self.tema.cor("fg_suave"))
            self.campo_unidade.definir_opcoes([])
            self.quadro_lote.grid_remove()
            self._atualizar_resumo()
            return
        saldo = estoque_mod.saldo(self.banco, int(produto["id"]))
        self.rotulo_produto.configure(
            text=f"{produto['codigo']} — {produto['nome']}\n"
                 f"Saldo atual: {unidades_mod.formatar(saldo, produto['unidade_base'] or 'un')}   •   "
                 f"Custo médio: {formatar_dinheiro(int(produto['preco_custo'] or 0))}   •   "
                 f"Venda: {formatar_dinheiro(int(produto['preco_venda'] or 0))}",
            foreground=self.tema.cor("fg"),
        )
        permitidas = unidades_mod.unidades_permitidas(produto, self.banco)
        if not permitidas:
            sigla = produto["unidade_base"] or "un"
            self.campo_unidade.definir_opcoes([(sigla, sigla)])
        else:
            self.campo_unidade.definir_opcoes([(u.sigla, u.rotulo) for u in permitidas])
        self.campo_unidade.definir(produto["unidade_base"] or (permitidas[0].sigla if permitidas else "un"))
        if self.campo_custo is not None and not self.campo_custo.valor():
            self.campo_custo.definir(int(produto["preco_custo"] or 0))
        # lote/validade só para produtos que controlam lote
        if int(produto["controla_lote"] or 0):
            self.quadro_lote.grid()
            lotes = estoque_mod.lotes_do_produto(self.banco, int(produto["id"]), apenas_com_saldo=True)
            if lotes:
                resumo = ", ".join(
                    f"{l['numero'] or 's/nº'} ({formatar_quantidade(l['quantidade_atual'])}"
                    + (f", val. {formatar_data(l['validade'])}" if l["validade"] else "") + ")"
                    for l in lotes[:4]
                )
                self.rotulo_lote.configure(text=f"Lotes com saldo: {resumo}")
            else:
                self.rotulo_lote.configure(text="Nenhum lote com saldo para este produto.")
            if produto["validade_dias"] and not self.campo_validade.valor():
                from ...utils import somar_dias

                self.campo_validade.definir(somar_dias(hoje(), int(produto["validade_dias"])))
        else:
            self.quadro_lote.grid_remove()
        self._atualizar_resumo()
        if focar_quantidade:
            self.campo_quantidade.focar()
        else:
            self.entrada_codigo.focus_set()

    def _atualizar_resumo(self):
        if not self.produto:
            self.rotulo_resumo.configure(text="Selecione o produto para ver o resumo da movimentação.")
            return
        quantidade = self.campo_quantidade.valor() or 0.0
        unidade = self.campo_unidade.valor() or self.produto["unidade_base"] or "un"
        saldo = estoque_mod.saldo(self.banco, int(self.produto["id"]))
        try:
            convertida = unidades_mod.converter_para_base(self.produto, quantidade, unidade, self.banco)
        except Exception:
            convertida = quantidade
        sinal = "+" if self.tipo == "entrada" else "−"
        novo_saldo = saldo + convertida if self.tipo == "entrada" else saldo - convertida
        custo = int(self.campo_custo.valor() or 0) if self.campo_custo is not None else int(self.produto["preco_custo"] or 0)
        linhas = [
            f"Movimento: {sinal}{formatar_quantidade(quantidade)} {unidade}"
            f"  →  {sinal}{formatar_quantidade(convertida)} {self.produto['unidade_base']}",
            f"Saldo atual: {formatar_quantidade(saldo)}   •   Saldo após o lançamento: {formatar_quantidade(novo_saldo)}",
            f"Valor total do movimento: {formatar_dinheiro(int(round(convertida * custo)))}",
        ]
        minimo = float(self.produto["estoque_minimo"] or 0)
        if minimo > 0:
            if novo_saldo <= minimo:
                linhas.append(f"⚠ O saldo ficará abaixo do estoque mínimo ({formatar_quantidade(minimo)}).")
            else:
                linhas.append(f"Estoque mínimo: {formatar_quantidade(minimo)} — situação normal após o lançamento.")
        if self.tipo == "saida" and novo_saldo < -1e-9:
            linhas.append("⚠ Saída maior que o saldo atual: o estoque ficará negativo.")
        self.rotulo_resumo.configure(text="\n".join(linhas))

    # ------------------------------------------------------------------ salvar
    def salvar(self, _evento=None):
        if not self.produto:
            dialogs.alerta(self, self.tema,
                           "Selecione o produto antes de confirmar.\n\n"
                           "Bipe o código de barras, digite o código e tecle Enter, ou use “Buscar (F2)”.")
            return
        for campo in (self.campo_quantidade, self.campo_motivo, self.campo_validade):
            ok, mensagem_erro = campo.validar()
            if not ok:
                campo.mostrar_erro(mensagem_erro)
                campo.focar()
                return
            campo.limpar_erro()
        quantidade = float(self.campo_quantidade.valor() or 0)
        if quantidade <= 0:
            dialogs.alerta(self, self.tema, "A quantidade deve ser maior que zero.")
            return
        motivo = self.campo_motivo.valor() or ("compra" if self.tipo == "entrada" else "outros")
        unidade = self.campo_unidade.valor() or None
        observacao = (self.campo_observacao.valor() or "").strip()
        lote_numero = (self.campo_lote.valor() or "").strip() if int(self.produto["controla_lote"] or 0) else ""
        validade = self.campo_validade.valor() if int(self.produto["controla_lote"] or 0) else ""
        try:
            if self.tipo == "entrada":
                movimento_id = estoque_mod.entrada(
                    self.banco, int(self.produto["id"]), quantidade, motivo=motivo,
                    custo_unitario=int(self.campo_custo.valor() or 0), unidade=unidade,
                    lote_numero=lote_numero, validade=validade,
                    fornecedor_id=self.campo_fornecedor.valor(),
                    documento=(self.campo_documento.valor() or "").strip(),
                    observacao=observacao, autor=self.ctx.usuario,
                )
            else:
                movimento_id = estoque_mod.saida(
                    self.banco, int(self.produto["id"]), quantidade, motivo=motivo, unidade=unidade,
                    observacao=observacao, autor=self.ctx.usuario,
                )
        except estoque_mod.ErroEstoque as exc:
            dialogs.erro(self, self.tema, str(exc), "Movimentação não lançada")
            return
        except unidades_mod.ErroUnidade as exc:
            dialogs.erro(self, self.tema, str(exc), "Unidade inválida")
            return
        self.confirmar({"movimento_id": movimento_id, "produto_id": int(self.produto["id"]),
                        "produto_nome": self.produto["nome"], "tipo": self.tipo, "motivo": motivo,
                        "quantidade": quantidade, "unidade": unidade or self.produto["unidade_base"]})

    def focar_codigo(self):
        self.entrada_codigo.focus_set()


# --------------------------------------------------------------------------------------
# Ficha do produto (saldo, lotes e histórico)
# --------------------------------------------------------------------------------------


class DialogoFichaProduto(dialogs.Modal):
    """Ficha de estoque de um produto: indicadores, lotes e últimas movimentações."""

    def __init__(self, ctx, produto_id: int, dias: int = 90):
        self.ctx = ctx
        ficha = estoque_mod.ficha_produto(ctx.banco, produto_id, dias=dias)
        produto = ficha["produto"]
        super().__init__(ctx.janela, ctx.tema, f"Ficha de estoque — {produto['nome']}", largura=940, altura=660)
        self.ficha = ficha

        valor_custo = int(round(ficha["saldo"] * float(produto["preco_custo"] or 0)))
        minimo = float(produto["estoque_minimo"] or 0)
        situacao = "Abaixo do mínimo" if (minimo > 0 and ficha["saldo"] <= minimo) else "Normal"
        cartoes = [
            ("Saldo atual", unidades_mod.formatar(ficha["saldo"], produto["unidade_base"] or "un"), ctx.tema.cor("fg")),
            ("Valor em estoque", formatar_dinheiro(valor_custo), ctx.tema.cor("info")),
            ("Estoque mínimo", formatar_quantidade(minimo), ctx.tema.cor("fg_suave")),
            ("Situação", situacao, ctx.tema.cor("perigo") if situacao != "Normal" else ctx.tema.cor("sucesso")),
            (f"Entradas ({dias} dias)", formatar_quantidade(ficha["entradas_periodo"]), ctx.tema.cor("sucesso")),
            (f"Saídas ({dias} dias)", formatar_quantidade(ficha["saidas_periodo"]), ctx.tema.cor("alerta")),
        ]
        quadro = ttk.Frame(self.corpo, style="TFrame")
        quadro.pack(fill="x", pady=(0, 8))
        for indice, (rotulo, valor, cor) in enumerate(cartoes):
            cartao = tk.Frame(quadro, background=ctx.tema.cor("bg_alt"),
                              highlightbackground=ctx.tema.cor("borda"), highlightthickness=1)
            cartao.grid(row=0, column=indice, sticky="nsew", padx=(0, 6))
            quadro.columnconfigure(indice, weight=1)
            tk.Label(cartao, text=rotulo, background=ctx.tema.cor("bg_alt"), foreground=ctx.tema.cor("fg_suave"),
                     font=("Segoe UI", 8), wraplength=130, justify="left").pack(anchor="w", padx=8, pady=(6, 0))
            tk.Label(cartao, text=valor, background=ctx.tema.cor("bg_alt"), foreground=cor,
                     font=("Segoe UI", 12, "bold"), wraplength=130, justify="left").pack(anchor="w", padx=8,
                                                                                          pady=(0, 6))

        abas = ttk.Notebook(self.corpo, style="TNotebook")
        abas.pack(fill="both", expand=True)

        lotes = ficha["lotes"]
        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Lotes ({len(lotes)})")
        colunas_lotes = [
            {"chave": "numero", "rotulo": "Lote", "largura": 120},
            {"chave": "validade_texto", "rotulo": "Validade", "largura": 100, "alinhamento": "centro"},
            {"chave": "dias_texto", "rotulo": "Situação", "largura": 130},
            {"chave": "quantidade_atual", "rotulo": "Saldo", "largura": 90, "tipo": "quantidade"},
            {"chave": "quantidade_inicial", "rotulo": "Inicial", "largura": 90, "tipo": "quantidade"},
            {"chave": "custo_unitario", "rotulo": "Custo un.", "largura": 100, "tipo": "dinheiro"},
            {"chave": "documento", "rotulo": "Documento", "largura": 120},
        ]
        tabela = Tabela(pagina, ctx.tema, colunas_lotes, mostrar_busca=False, altura=11)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        linhas = []
        for lote in lotes:
            linha = dict(lote)
            dias = lote["dias_para_vencer"]
            linha["validade_texto"] = formatar_data(lote["validade"]) if lote["validade"] else "sem validade"
            if dias is None:
                linha["dias_texto"] = "—"
            elif dias < 0:
                linha["dias_texto"] = f"Vencido há {abs(int(dias))} dia(s)"
                linha["_tag"] = "perigo"
            elif dias <= 30:
                linha["dias_texto"] = f"Vence em {int(dias)} dia(s)"
                linha["_tag"] = "alerta"
            else:
                linha["dias_texto"] = f"{int(dias)} dia(s) restantes"
            linhas.append(linha)
        tabela.carregar(linhas)

        movimentos = ficha["movimentacoes"]
        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Últimas movimentações ({len(movimentos)})")
        tabela = Tabela(pagina, ctx.tema, colunas_movimentacoes(), mostrar_busca=True, altura=11)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        tabela.carregar([linha_para_grade(m) for m in movimentos])

        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))


# --------------------------------------------------------------------------------------
# Grade de movimentações
# --------------------------------------------------------------------------------------


def colunas_movimentacoes() -> list[dict]:
    return [
        {"chave": "id", "rotulo": "Nº", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
        {"chave": "data_texto", "rotulo": "Data / hora", "largura": 145},
        {"chave": "tipo_texto", "rotulo": "Tipo", "largura": 85, "alinhamento": "centro"},
        {"chave": "motivo_texto", "rotulo": "Motivo", "largura": 190},
        {"chave": "produto_codigo", "rotulo": "Código", "largura": 90},
        {"chave": "produto_nome", "rotulo": "Produto", "largura": 240},
        {"chave": "quantidade_texto", "rotulo": "Quantidade", "largura": 120, "alinhamento": "centro"},
        {"chave": "custo_unitario", "rotulo": "Custo un.", "largura": 95, "tipo": "dinheiro"},
        {"chave": "valor_total", "rotulo": "Valor total", "largura": 105, "tipo": "dinheiro"},
        {"chave": "saldo_apos", "rotulo": "Saldo após", "largura": 95, "tipo": "quantidade"},
        {"chave": "lote_texto", "rotulo": "Lote", "largura": 110},
        {"chave": "usuario_nome", "rotulo": "Usuário", "largura": 150},
        {"chave": "observacao", "rotulo": "Observação", "largura": 260},
    ]


def linha_para_grade(movimento) -> dict:
    """Converte uma movimentação do banco na linha exibida na grade."""
    linha = dict(movimento)
    tipo = str(linha.get("tipo") or "")
    quantidade = float(linha.get("quantidade") or 0)
    unidade = linha.get("unidade") or "un"
    sinal = {"entrada": "+", "saida": "−"}.get(tipo, "")
    linha["data_texto"] = formatar_data(linha.get("criado_em"), com_hora=True)
    linha["tipo_texto"] = {"entrada": "Entrada", "saida": "Saída", "ajuste": "Ajuste"}.get(tipo, tipo)
    linha["motivo_texto"] = estoque_mod.motivo_descricao(linha.get("motivo") or "")
    linha["quantidade_texto"] = f"{sinal}{formatar_quantidade(quantidade)} {unidade}".strip()
    lote = linha.get("lote_numero_atual") or linha.get("lote_numero") or ""
    linha["lote_texto"] = lote or "—"
    if not linha.get("observacao"):
        linha["observacao"] = ""
    if linha.get("motivo") in MOTIVOS_CRITICOS:
        linha["_tag"] = "perigo"
    elif tipo == "ajuste":
        linha["_tag"] = "info"
    return linha


class EstoqueTela(TelaLista):
    titulo = "Movimentações de estoque"
    descricao = "Entradas, saídas, ajustes e histórico completo de cada produto."
    permissao_editar = "estoque_movimentar"

    def __init__(self, mestre, ctx):
        inicial, final = intervalo_padrao(30)
        self._data_inicial = tk.StringVar(value=inicial)
        self._data_final = tk.StringVar(value=final)
        self._tipo = tk.StringVar(value=OPCOES_TIPO[0][1])
        self._motivo = tk.StringVar(value="")
        self._produto_id: int | None = None
        self._produto_texto = tk.StringVar(value="")
        self._usuario = tk.StringVar(value="(todos)")
        super().__init__(
            mestre, ctx,
            colunas=colunas_movimentacoes(),
            carregar_dados=self._dados,
            resumo=self._resumo,
            ao_duplo_clique=lambda linha: self.abrir_ficha(linha),
            detalhes=self._detalhes,
            acoes=(
                ("⬆ Entrada", self.nova_entrada, "Primario.TButton", "F2"),
                ("⬇ Saída", self.nova_saida, "TButton", "F3"),
                ("📝 Ajuste de inventário", self.ir_para_ajuste, "TButton", "F4"),
                ("📦 Ficha do produto", self.abrir_ficha, "TButton", "F5"),
                ("🔎 Auditoria de saldos", self.auditar_saldos, "TButton", "F6"),
                ("🧮 Recalcular saldos", self.recalcular_saldos, "TButton", "F7"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Movimentacoes de estoque",
            altura_tabela=20,
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        ttk.Label(pai, text="De:", style="TLabel").grid(row=0, column=0, sticky="w", padx=(0, 4))
        ttk.Entry(pai, textvariable=self._data_inicial, width=11).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(pai, text="Até:", style="TLabel").grid(row=0, column=2, sticky="w", padx=(0, 4))
        ttk.Entry(pai, textvariable=self._data_final, width=11).grid(row=0, column=3, padx=(0, 10))

        ttk.Label(pai, text="Tipo:", style="TLabel").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self._combo_tipo = ttk.Combobox(pai, textvariable=self._tipo, width=17, state="readonly",
                                        values=[rotulo for _valor, rotulo in OPCOES_TIPO])
        self._combo_tipo.grid(row=0, column=5, padx=(0, 10))
        self._combo_tipo.set(self._tipo.get() or OPCOES_TIPO[0][1])
        self._combo_tipo.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Motivo:", style="TLabel").grid(row=0, column=6, sticky="w", padx=(0, 4))
        opcoes_motivo = ["(todos)"] + [f"{texto}" for texto in MOTIVOS.values()]
        self.combo_motivo = ttk.Combobox(pai, textvariable=self._motivo, width=26, state="readonly",
                                         values=opcoes_motivo)
        self.combo_motivo.grid(row=0, column=7, padx=(0, 10))
        self.combo_motivo.set("(todos)")
        self.combo_motivo.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Produto:", style="TLabel").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(6, 0))
        entrada_produto = ttk.Entry(pai, textvariable=self._produto_texto, width=26)
        entrada_produto.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 10), pady=(6, 0))
        entrada_produto.bind("<Return>", lambda e: self.carregar())
        ttk.Button(pai, text="Selecionar...", command=self._escolher_produto).grid(row=1, column=4, sticky="w",
                                                                                    pady=(6, 0))
        ttk.Button(pai, text="Limpar produto", command=self._limpar_produto).grid(row=1, column=5, sticky="w",
                                                                                   padx=(6, 0), pady=(6, 0))

        ttk.Label(pai, text="Usuário:", style="TLabel").grid(row=1, column=6, sticky="w", padx=(0, 4), pady=(6, 0))
        self.combo_usuario = ttk.Combobox(pai, textvariable=self._usuario, width=26, state="readonly",
                                          values=["(todos)"] + [u["nome"] for u in usuarios_mod.listar(self.banco)])
        self.combo_usuario.grid(row=1, column=7, sticky="w", pady=(6, 0))
        self.combo_usuario.set("(todos)")
        self.combo_usuario.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Button(pai, text="🔍 Filtrar", command=self.carregar).grid(row=2, column=0, columnspan=2, sticky="w",
                                                                       pady=(8, 0))
        ttk.Button(pai, text="↺ Limpar filtros", command=self.limpar_filtros).grid(row=2, column=2, columnspan=2,
                                                                                    sticky="w", pady=(8, 0))
        ttk.Button(pai, text="📅 Hoje", command=self.filtrar_hoje).grid(row=2, column=4, columnspan=2, sticky="w",
                                                                        pady=(8, 0))
        pai.columnconfigure(1, weight=1)
        pai.columnconfigure(3, weight=1)

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.nova_entrada, "F3": self.nova_saida, "F4": self.ir_para_ajuste,
                 "F5": self.abrir_ficha, "F6": self.auditar_saldos, "F7": self.recalcular_saldos}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    def filtrar_hoje(self):
        self._data_inicial.set(hoje())
        self._data_final.set(hoje())
        self.carregar()

    def limpar_filtros(self):
        inicial, final = intervalo_padrao(30)
        self._data_inicial.set(inicial)
        self._data_final.set(final)
        self._tipo.set(OPCOES_TIPO[0][1])
        self._motivo.set("(todos)")
        self._produto_id = None
        self._produto_texto.set("")
        self._usuario.set("(todos)")
        self.carregar()

    def definir_tipo(self, valor: str) -> None:
        """Define o filtro de tipo a partir do valor interno (``entrada``/``saida``/``ajuste``)."""
        for valor_opcao, rotulo in OPCOES_TIPO:
            if valor_opcao == valor:
                self._tipo.set(rotulo)
                return
        self._tipo.set(OPCOES_TIPO[0][1])

    def _escolher_produto(self):
        produto = selecionar_produto(self.ctx, "Filtrar movimentações por produto")
        if produto:
            self._produto_id = int(produto["id"])
            self._produto_texto.set(f"{produto['codigo']} — {produto['nome']}")
            self.carregar()

    def _limpar_produto(self):
        self._produto_id = None
        self._produto_texto.set("")
        self.carregar()

    # ------------------------------------------------------------------ dados
    def _tipo_selecionado(self) -> str:
        """Converte o rótulo do combo no valor usado pela consulta."""
        texto = self._tipo.get().strip()
        for valor, rotulo in OPCOES_TIPO:
            if rotulo == texto:
                return valor
        return texto if texto in ("entrada", "saida", "ajuste") else ""

    def _motivo_selecionado(self) -> str:
        texto = self._motivo.get().strip()
        if texto in ("", "(todos)"):
            return ""
        for chave, rotulo in MOTIVOS.items():
            if rotulo == texto:
                return chave
        return texto

    def _usuario_selecionado(self) -> int | None:
        nome = self._usuario.get().strip()
        if nome in ("", "(todos)"):
            return None
        for usuario in usuarios_mod.listar(self.banco):
            if usuario["nome"] == nome:
                return int(usuario["id"])
        return None

    def _dados(self) -> list[dict]:
        movimentos = estoque_mod.historico(
            self.banco,
            produto_id=self._produto_id,
            data_inicial=converter_data_br(self._data_inicial.get()) or "",
            data_final=converter_data_br(self._data_final.get()) or "",
            motivo=self._motivo_selecionado(),
            tipo=self._tipo_selecionado(),
            usuario_id=self._usuario_selecionado(),
            texto=self._produto_texto.get().strip() if not self._produto_id else "",
            limite=2000,
        )
        return [linha_para_grade(m) for m in movimentos]

    def _tag_linha(self, linha: dict) -> str:
        return str(linha.get("_tag") or "")

    def _resumo(self, dados) -> str:
        entradas = sum(int(d["valor_total"] or 0) for d in dados if d["tipo"] == "entrada")
        saidas = sum(int(d["valor_total"] or 0) for d in dados if d["tipo"] == "saida")
        qtd_entrada = sum(float(d["quantidade"] or 0) for d in dados if d["tipo"] == "entrada")
        qtd_saida = sum(float(d["quantidade"] or 0) for d in dados if d["tipo"] == "saida")
        return (f"{len(dados)} movimentação(ões) • entradas {formatar_quantidade(qtd_entrada)} "
                f"({formatar_dinheiro(entradas)}) • saídas {formatar_quantidade(qtd_saida)} "
                f"({formatar_dinheiro(saidas)})")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        return [
            ("Movimentação nº", linha.get("id")),
            ("Data", linha.get("data_texto")),
            ("Tipo", linha.get("tipo_texto")),
            ("Motivo", linha.get("motivo_texto")),
            ("Produto", f"{linha.get('produto_codigo')} — {linha.get('produto_nome')}"),
            ("Categoria", linha.get("categoria_nome")),
            ("Quantidade", linha.get("quantidade_texto")),
            ("Custo unitário", formatar_dinheiro(int(linha.get("custo_unitario") or 0))),
            ("Valor total", formatar_dinheiro(int(linha.get("valor_total") or 0))),
            ("Saldo após", formatar_quantidade(linha.get("saldo_apos"))),
            ("Lote", linha.get("lote_texto")),
            ("Validade", formatar_data(linha.get("validade")) if linha.get("validade") else "—"),
            ("Documento", linha.get("documento_id")),
            ("Usuário", linha.get("usuario_nome")),
            ("Observação", linha.get("observacao")),
        ]

    # ------------------------------------------------------------------ ações
    def _pode_movimentar(self) -> bool:
        return self.exigir("estoque_movimentar", "lançar movimentações de estoque")

    def nova_entrada(self, produto=None):
        if not self._pode_movimentar():
            return
        resultado = DialogoMovimentacao(self.ctx, "entrada", produto).abrir()
        self._pos_movimentacao(resultado, "Entrada")

    def nova_saida(self, produto=None):
        if not self._pode_movimentar():
            return
        resultado = DialogoMovimentacao(self.ctx, "saida", produto).abrir()
        self._pos_movimentacao(resultado, "Saída")

    def _pos_movimentacao(self, resultado, rotulo: str):
        if not resultado:
            return
        self.carregar()
        self.tabela.selecionar_por("id", resultado["movimento_id"])
        dialogs.sucesso(
            self, self.tema,
            f"{rotulo} lançada com sucesso.\n\n"
            f"Produto: {resultado['produto_nome']}\n"
            f"Quantidade: {formatar_quantidade(resultado['quantidade'])} {resultado['unidade']}\n"
            f"Motivo: {estoque_mod.motivo_descricao(resultado['motivo'])}\n"
            f"Saldo atual: {self._saldo_formatado(resultado['produto_id'])}",
        )
        self.ctx.app.atualizar_caixa()

    def _saldo_formatado(self, produto_id: int) -> str:
        produto = produtos_mod.pegar_simples(self.banco, produto_id)
        if not produto:
            return formatar_quantidade(estoque_mod.saldo(self.banco, produto_id))
        return estoque_mod.saldo_formatado(self.banco, produto)

    def ir_para_ajuste(self):
        self.ctx.navegar("ajuste")

    def abrir_ficha(self, linha: dict | None = None):
        if linha is None:
            linha = self.selecionado()
        if not linha:
            if self._produto_id:
                produto_id = self._produto_id
            else:
                produto = selecionar_produto(self.ctx, "Ficha de estoque do produto")
                if not produto:
                    return
                produto_id = int(produto["id"])
        else:
            produto_id = int(linha["produto_id"])
        try:
            DialogoFichaProduto(self.ctx, produto_id).abrir()
        except estoque_mod.ErroEstoque as exc:
            dialogs.erro(self, self.tema, str(exc))

    def auditar_saldos(self):
        divergencias = estoque_mod.verificar_saldos(self.banco)
        if not divergencias:
            dialogs.sucesso(self, self.tema,
                            "Auditoria concluída: o saldo gravado de todos os produtos confere com o "
                            "histórico de movimentações.")
            return
        colunas = [
            {"chave": "codigo", "rotulo": "Código", "largura": 100},
            {"chave": "nome", "rotulo": "Produto", "largura": 280},
            {"chave": "gravado", "rotulo": "Saldo gravado", "largura": 120, "tipo": "quantidade"},
            {"chave": "calculado", "rotulo": "Saldo pelo histórico", "largura": 150, "tipo": "quantidade"},
            {"chave": "diferenca", "rotulo": "Diferença", "largura": 110, "tipo": "quantidade"},
        ]
        linhas = []
        for item in divergencias:
            linha = dict(item)
            linha["diferenca"] = round(float(linha["calculado"] or 0) - float(linha["gravado"] or 0), 4)
            linha["_tag"] = "perigo"
            linhas.append(linha)
        if dialogs.confirmar(
                self, self.tema,
                f"Foram encontradas {len(divergencias)} divergência(s) entre o saldo gravado e o histórico.\n\n"
                "Deseja recalcular os saldos agora a partir das movimentações?",
                "Auditoria de saldos", "Recalcular", "Só ver a lista"):
            self.recalcular_saldos(silencioso=False)
            return
        DialogoListaSimples(self.ctx.janela, self.tema, "Divergências de saldo", colunas, linhas).abrir()

    def recalcular_saldos(self, silencioso: bool = False):
        if not self.pode("estoque_movimentar"):
            self.exigir("estoque_movimentar", "recalcular os saldos de estoque")
            return
        if not silencioso and not dialogs.confirmar(
                self, self.tema,
                "Recalcular o estoque atual de todos os produtos a partir do histórico de movimentações?\n\n"
                "Use esta opção apenas se os saldos estiverem divergentes.",
                "Recalcular saldos", "Recalcular", "Cancelar"):
            return
        total = estoque_mod.recalcular_saldos(self.banco)
        self.carregar()
        dialogs.sucesso(self, self.tema, f"Saldos recalculados para {total} produto(s).")

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("produto_id"):
            produto = produtos_mod.pegar_simples(self.banco, int(parametros["produto_id"]))
            self._produto_id = int(parametros["produto_id"])
            self._produto_texto.set(f"{produto['codigo']} — {produto['nome']}" if produto else "")
            self.carregar()
        if parametros.get("tipo") in ("entrada", "saida", "ajuste"):
            self.definir_tipo(str(parametros["tipo"]))
            self.carregar()
        if parametros.get("abrir_entrada") and self._produto_id:
            self.nova_entrada(produtos_mod.pegar(self.banco, self._produto_id))
        if parametros.get("abrir_saida") and self._produto_id:
            self.nova_saida(produtos_mod.pegar(self.banco, self._produto_id))


class DialogoListaSimples(dialogs.Modal):
    """Grade genérica em janela modal (usada pela auditoria de saldos)."""

    def __init__(self, mestre, tema, titulo: str, colunas: list[dict], linhas: list[dict]):
        super().__init__(mestre, tema, titulo, largura=820, altura=520)
        tabela = Tabela(self.corpo, tema, colunas, mostrar_busca=False, altura=16)
        tabela.pack(fill="both", expand=True)
        tabela.carregar(linhas)
        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))
