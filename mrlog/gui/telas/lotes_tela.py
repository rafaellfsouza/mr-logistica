"""
Tela de **Lotes e validade** — controle FEFO (vence primeiro, sai primeiro).

Mostra todos os lotes com saldo, a data de validade, quantos dias faltam e o valor
imobilizado. Permite lançar entrada com lote, dar baixa em lote vencido e abrir a
ficha de estoque do produto.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import estoque as estoque_mod
from ... import produtos as produtos_mod
from ...utils import formatar_data, formatar_dinheiro, formatar_quantidade, hoje
from .. import dialogs
from . import TelaLista
from .estoque_tela import DialogoFichaProduto, DialogoMovimentacao
from .produtos_tela import selecionar_produto

SQL_LOTES = """
    SELECT l.*,
           p.codigo            AS produto_codigo,
           p.nome              AS produto_nome,
           p.unidade_base      AS unidade,
           p.estoque_atual     AS saldo_produto,
           p.controla_lote     AS controla_lote,
           p.preco_custo       AS custo_produto,
           f.nome              AS fornecedor_nome,
           CAST(julianday(COALESCE(NULLIF(l.validade,''), '9999-12-31'))
                - julianday('now','localtime') AS INTEGER) AS dias_para_vencer
      FROM lotes l
      JOIN produtos p ON p.id = l.produto_id
 LEFT JOIN fornecedores f ON f.id = l.fornecedor_id
"""

OPCOES_VALIDADE = [
    ("todos", "Todos os lotes"),
    ("vencidos", "Somente vencidos"),
    ("30", "Até 30 dias (inclui vencidos)"),
    ("60", "Até 60 dias (inclui vencidos)"),
    ("90", "Até 90 dias (inclui vencidos)"),
]


class LotesTela(TelaLista):
    titulo = "Lotes e validade"
    descricao = "Controle de lotes, datas de validade e baixas por vencimento (FEFO)."
    permissao_editar = "estoque_movimentar"

    def __init__(self, mestre, ctx):
        self._validade = tk.StringVar(value=OPCOES_VALIDADE[0][1])
        self._produto = tk.StringVar(value="")
        self._somente_com_saldo = tk.BooleanVar(value=True)
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "produto_codigo", "rotulo": "Código", "largura": 90},
                {"chave": "produto_nome", "rotulo": "Produto", "largura": 250},
                {"chave": "numero_texto", "rotulo": "Lote", "largura": 120},
                {"chave": "validade_texto", "rotulo": "Validade", "largura": 100, "alinhamento": "centro"},
                {"chave": "situacao", "rotulo": "Situação", "largura": 175},
                {"chave": "quantidade_atual", "rotulo": "Saldo do lote", "largura": 110, "tipo": "quantidade"},
                {"chave": "quantidade_inicial", "rotulo": "Qtd. inicial", "largura": 105, "tipo": "quantidade"},
                {"chave": "unidade", "rotulo": "Un.", "largura": 50, "alinhamento": "centro"},
                {"chave": "custo_unitario", "rotulo": "Custo un.", "largura": 95, "tipo": "dinheiro"},
                {"chave": "valor_lote", "rotulo": "Valor do lote", "largura": 115, "tipo": "dinheiro"},
                {"chave": "saldo_produto", "rotulo": "Saldo do produto", "largura": 120, "tipo": "quantidade"},
                {"chave": "fornecedor_texto", "rotulo": "Fornecedor", "largura": 170},
                {"chave": "documento", "rotulo": "Documento", "largura": 110},
            ],
            carregar_dados=self._dados,
            resumo=self._resumo,
            ao_duplo_clique=lambda linha: self.abrir_ficha(linha),
            detalhes=self._detalhes,
            acoes=(
                ("⬆ Entrada com lote", self.nova_entrada, "Primario.TButton", "F2"),
                ("🗑 Baixa por vencimento", self.baixar_vencido, "TButton", "F3"),
                ("➕ Lote de inventário inicial", self.novo_lote, "TButton", "F4"),
                ("📦 Ficha do produto", self.abrir_ficha, "TButton", "F5"),
                ("🚨 Vencidos / próximos", self.ver_alertas, "TButton", "F6"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Lotes e validade",
            altura_tabela=20,
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        ttk.Label(pai, text="Validade:", style="TLabel").grid(row=0, column=0, sticky="w")
        self.combo_validade = ttk.Combobox(pai, textvariable=self._validade, width=24, state="readonly",
                                           values=[rotulo for _v, rotulo in OPCOES_VALIDADE])
        self.combo_validade.grid(row=0, column=1, sticky="w", padx=(4, 14))
        self.combo_validade.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Produto:", style="TLabel").grid(row=0, column=2, sticky="w")
        entrada = ttk.Entry(pai, textvariable=self._produto, width=30)
        entrada.grid(row=0, column=3, sticky="ew", padx=(4, 8))
        entrada.bind("<Return>", lambda e: self.carregar())
        ttk.Button(pai, text="Selecionar...", command=self._escolher_produto).grid(row=0, column=4, sticky="w")
        ttk.Button(pai, text="Limpar", command=self._limpar_produto).grid(row=0, column=5, sticky="w", padx=(6, 0))

        tk.Checkbutton(
            pai, text="Somente lotes com saldo", variable=self._somente_com_saldo, command=self.carregar,
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
            activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
            selectcolor=self.tema.cor("bg_input"), highlightthickness=0,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        pai.columnconfigure(3, weight=1)

    def atualizar_tema(self):
        super().atualizar_tema()
        for filho in getattr(self, "quadro_filtros", ()).winfo_children():
            if isinstance(filho, tk.Checkbutton):
                filho.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                                selectcolor=self.tema.cor("bg_input"))

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.nova_entrada, "F3": self.baixar_vencido, "F4": self.novo_lote,
                 "F5": self.abrir_ficha, "F6": self.ver_alertas}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    def _escolher_produto(self):
        produto = selecionar_produto(self.ctx, "Filtrar lotes por produto")
        if produto:
            self._produto.set(produto["nome"])
            self.carregar()

    def _limpar_produto(self):
        self._produto.set("")
        self.carregar()

    # ------------------------------------------------------------------ dados
    def _filtro_validade(self) -> str:
        rotulo = self._validade.get()
        for valor, texto in OPCOES_VALIDADE:
            if texto == rotulo:
                return valor
        return "todos"

    def _dados(self) -> list[dict]:
        condicoes, params = [], []
        if self._somente_com_saldo.get():
            condicoes.append("l.quantidade_atual > 0")
        filtro = self._filtro_validade()
        if filtro == "vencidos":
            condicoes.append("l.validade IS NOT NULL AND l.validade <> '' AND date(l.validade) < date(?)")
            params.append(hoje())
        elif filtro in ("30", "60", "90"):
            condicoes.append("l.validade IS NOT NULL AND l.validade <> '' "
                             "AND date(l.validade) <= date(?, ?)")
            params += [hoje(), f"+{filtro} days"]
        termo = self._produto.get().strip()
        if termo:
            condicoes.append("(p.nome LIKE ? OR p.codigo LIKE ? OR COALESCE(l.numero,'') LIKE ?)")
            params += [f"%{termo}%"] * 3
        sql = SQL_LOTES
        if condicoes:
            sql += " WHERE " + " AND ".join(condicoes)
        sql += (" ORDER BY (l.validade IS NULL OR l.validade=''), l.validade, p.nome, l.id"
                " LIMIT 3000")
        linhas = []
        for lote in self.banco.consultar(sql, params):
            linha = dict(lote)
            dias = lote["dias_para_vencer"]
            tem_validade = bool((lote["validade"] or "").strip())
            linha["numero_texto"] = lote["numero"] or "s/nº"
            linha["validade_texto"] = formatar_data(lote["validade"]) if tem_validade else "sem validade"
            linha["valor_lote"] = int(round(float(lote["quantidade_atual"] or 0) * int(lote["custo_unitario"] or 0)))
            linha["fornecedor_texto"] = lote["fornecedor_nome"] or "—"
            linha["documento"] = lote["documento"] or ""
            if not tem_validade:
                linha["situacao"] = "Sem validade cadastrada"
            elif dias is None:
                linha["situacao"] = "—"
            elif dias < 0:
                linha["situacao"] = f"VENCIDO há {abs(int(dias))} dia(s)"
                linha["_tag"] = "perigo"
            elif dias == 0:
                linha["situacao"] = "Vence hoje"
                linha["_tag"] = "perigo"
            elif dias <= 30:
                linha["situacao"] = f"Vence em {int(dias)} dia(s)"
                linha["_tag"] = "alerta"
            elif dias <= 90:
                linha["situacao"] = f"Vence em {int(dias)} dia(s)"
            else:
                linha["situacao"] = f"Vence em {int(dias)} dia(s)"
            if float(lote["quantidade_atual"] or 0) <= 0:
                linha["_tag"] = "neutro"
            linhas.append(linha)
        return linhas

    def _tag_linha(self, linha: dict) -> str:
        return str(linha.get("_tag") or "")

    def _resumo(self, dados) -> str:
        vencidos = sum(1 for d in dados if str(d["situacao"]).startswith("VENCIDO") or d["situacao"] == "Vence hoje")
        proximos = sum(1 for d in dados if d.get("_tag") == "alerta")
        valor = sum(int(d["valor_lote"] or 0) for d in dados)
        return (f"{len(dados)} lote(s) • {vencidos} vencido(s)/vence hoje • {proximos} vencendo em 30 dias • "
                f"valor em lotes {formatar_dinheiro(valor)}")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        return [
            ("Lote", linha.get("numero_texto")),
            ("Produto", f"{linha.get('produto_codigo')} — {linha.get('produto_nome')}"),
            ("Validade", linha.get("validade_texto")),
            ("Situação", linha.get("situacao")),
            ("Saldo do lote", f"{formatar_quantidade(linha.get('quantidade_atual'))} {linha.get('unidade')}"),
            ("Quantidade inicial", formatar_quantidade(linha.get("quantidade_inicial"))),
            ("Saldo total do produto", formatar_quantidade(linha.get("saldo_produto"))),
            ("Custo unitário", formatar_dinheiro(int(linha.get("custo_unitario") or 0))),
            ("Valor do lote", formatar_dinheiro(int(linha.get("valor_lote") or 0))),
            ("Fornecedor", linha.get("fornecedor_texto")),
            ("Documento", linha.get("documento") or "—"),
            ("Criado em", formatar_data(linha.get("criado_em"), com_hora=True)),
            ("Observação", linha.get("observacao")),
        ]

    # ------------------------------------------------------------------ ações
    def nova_entrada(self, linha: dict | None = None):
        if not self.exigir("estoque_movimentar", "lançar entradas de estoque"):
            return
        produto = None
        if linha:
            produto = produtos_mod.pegar(self.banco, int(linha["produto_id"]))
        resultado = DialogoMovimentacao(self.ctx, "entrada", produto, motivo_padrao="compra").abrir()
        if resultado:
            self.carregar()
            dialogs.sucesso(self, self.tema,
                            f"Entrada lançada: {formatar_quantidade(resultado['quantidade'])} "
                            f"{resultado['unidade']} de {resultado['produto_nome']}.")
            self.ctx.app.atualizar_caixa()

    def novo_lote(self, linha: dict | None = None):
        """Cria um lote de inventário inicial (implantação / saldo existente sem lote)."""
        if not self.exigir("estoque_movimentar", "criar lotes de inventário"):
            return
        from ... import fornecedores as fornecedores_mod

        produto = produtos_mod.pegar(self.banco, int(linha["produto_id"])) if linha else None
        if not produto:
            produto = selecionar_produto(self.ctx, "Produto do lote de inventário")
        if not produto:
            return
        if not int(produto["controla_lote"] or 0):
            if not dialogs.confirmar(
                    self, self.tema,
                    f"O produto “{produto['nome']}” não controla lote e validade.\n\n"
                    "Ativar o controle de lote agora? As próximas entradas passarão a exigir lote/validade.",
                    "Controle de lote", "Ativar", "Cancelar"):
                return
            try:
                produtos_mod.atualizar(self.banco, int(produto["id"]), {"controla_lote": 1}, autor=self.usuario)
            except produtos_mod.ErroProduto as exc:
                dialogs.erro(self, self.tema, str(exc), "Não foi possível ativar o controle de lote")
                return
            produto = produtos_mod.pegar(self.banco, int(produto["id"]))
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Lote de inventário — {produto['nome']}",
            [
                {"chave": "numero", "rotulo": "Número do lote", "tipo": "texto", "largura": 18},
                {"chave": "validade", "rotulo": "Validade", "tipo": "data", "largura": 12},
                {"chave": "quantidade", "rotulo": f"Quantidade ({produto['unidade_base'] or 'un'})",
                 "tipo": "quantidade", "largura": 12, "obrigatorio": True, "decimais": 4},
                {"chave": "custo_unitario", "rotulo": "Custo unitário", "tipo": "dinheiro", "largura": 14},
                {"chave": "fornecedor_id", "rotulo": "Fornecedor", "tipo": "lista", "largura": 26,
                 "vazio": "(sem fornecedor)", "opcoes": fornecedores_mod.opcoes(self.banco)},
                {"chave": "documento", "rotulo": "Documento / nota", "tipo": "texto", "largura": 16},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 40, "colunas": 2},
            ],
            {"custo_unitario": int(produto["preco_custo"] or 0)},
            largura=620,
            texto="Registra o lote e a quantidade já existente em estoque (não gera nova movimentação).\n"
                  "Use para implantar o controle de lotes sem alterar o saldo do produto.",
        )
        if not dados:
            return
        try:
            lote_id = estoque_mod.criar_ou_atualizar_lote(
                self.banco, int(produto["id"]), float(dados["quantidade"] or 0),
                numero=(dados.get("numero") or "").strip(), validade=dados.get("validade") or "",
                custo_unitario=int(dados.get("custo_unitario") or 0),
                fornecedor_id=dados.get("fornecedor_id"), documento=(dados.get("documento") or "").strip(),
                observacao=(dados.get("observacao") or "").strip(),
            )
        except estoque_mod.ErroEstoque as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        if not lote_id:
            dialogs.alerta(self, self.tema, "Informe uma quantidade maior que zero para criar o lote.")
            return
        self.carregar()
        self.tabela.selecionar_por("id", lote_id)
        dialogs.sucesso(self, self.tema,
                        f"Lote criado para “{produto['nome']}” com "
                        f"{formatar_quantidade(float(dados['quantidade'] or 0))} {produto['unidade_base']}.")

    def baixar_vencido(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        if not self.exigir("estoque_movimentar", "dar baixa em lotes vencidos"):
            return
        if float(linha["quantidade_atual"] or 0) <= 0:
            dialogs.alerta(self, self.tema, "Este lote não tem saldo para baixar.")
            return
        disponivel = float(linha["quantidade_atual"])
        if linha["dias_para_vencer"] is not None and int(linha["dias_para_vencer"]) >= 0:
            if not dialogs.confirmar(
                    self, self.tema,
                    f"O lote “{linha['numero_texto']}” de {linha['produto_nome']} vence em "
                    f"{formatar_data(linha['validade']) if linha['validade'] else '—'} "
                    f"({linha['situacao']}).\n\nDar baixa mesmo assim?",
                    "Lote ainda válido", "Dar baixa", "Cancelar"):
                return
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Baixa por vencimento — {linha['produto_nome']}",
            [
                {"chave": "quantidade", "rotulo": "Quantidade a baixar", "tipo": "quantidade", "largura": 12,
                 "obrigatorio": True, "decimais": 4, "dica": f"Saldo do lote: {formatar_quantidade(disponivel)}"},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 40, "colunas": 2},
            ],
            {"quantidade": disponivel}, largura=520,
            texto="A baixa gera uma saída de estoque com o motivo “Baixa por vencimento”.",
        )
        if not dados:
            return
        quantidade = float(dados.get("quantidade") or 0)
        if quantidade <= 0:
            dialogs.alerta(self, self.tema, "A quantidade da baixa deve ser maior que zero.")
            return
        if quantidade > disponivel + 1e-9:
            dialogs.alerta(self, self.tema,
                            f"O lote tem apenas {formatar_quantidade(disponivel)} em saldo.\n"
                            f"Você informou {formatar_quantidade(quantidade)}.")
            return
        try:
            estoque_mod.baixa_por_vencimento(self.banco, int(linha["id"]), quantidade,
                                             observacao=(dados.get("observacao") or "").strip(), autor=self.usuario)
        except estoque_mod.ErroEstoque as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Baixa lançada: {formatar_quantidade(quantidade)} {linha['unidade']} do lote "
                        f"“{linha['numero_texto']}” ({linha['produto_nome']}).")
        self.ctx.app.atualizar_caixa()

    def abrir_ficha(self, linha: dict | None = None):
        linha = linha or self.selecionado()
        if not linha:
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

    def ver_alertas(self):
        vencidos = estoque_mod.lotes_vencidos(self.banco)
        proximos = estoque_mod.lotes_vencendo(self.banco, 30)
        if not vencidos and not proximos:
            dialogs.sucesso(self, self.tema,
                            "Nenhum lote vencido e nenhum lote vencendo nos próximos 30 dias.")
            return
        texto = []
        if vencidos:
            valor = sum(int(round(float(v["quantidade_atual"] or 0) * int(v["custo_unitario"] or 0))) for v in vencidos)
            texto.append(f"🔴 {len(vencidos)} lote(s) VENCIDO(s) — valor {formatar_dinheiro(valor)}")
            for lote in vencidos[:8]:
                texto.append(f"    • {lote['produto_nome']} — lote {lote['numero'] or 's/nº'} "
                             f"(val. {formatar_data(lote['validade'])}, saldo {formatar_quantidade(lote['quantidade_atual'])})")
            if len(vencidos) > 8:
                texto.append(f"    ... e mais {len(vencidos) - 8} lote(s)")
        if proximos:
            apenas_proximos = [l for l in proximos if int(l["dias_para_vencer"]) >= 0]
            if apenas_proximos:
                texto.append(f"\n🟠 {len(apenas_proximos)} lote(s) vencendo em até 30 dias")
                for lote in apenas_proximos[:8]:
                    texto.append(f"    • {lote['produto_nome']} — lote {lote['numero'] or 's/nº'} "
                                 f"(val. {formatar_data(lote['validade'])}, faltam {int(lote['dias_para_vencer'])} dia(s))")
        resposta = dialogs.mensagem(
            self, self.tema, "Alerta de validade",
            "\n".join(texto) + "\n\nFiltrar a grade para mostrar apenas os lotes vencidos?",
            "pergunta", ("Filtrar vencidos", "Fechar"),
        )
        if resposta == "Filtrar vencidos":
            self._validade.set(OPCOES_VALIDADE[1][1])
            self.carregar()

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("produto_id"):
            produto = produtos_mod.pegar_simples(self.banco, int(parametros["produto_id"]))
            self._produto.set(produto["nome"] if produto else "")
            self.carregar()
        if parametros.get("vencidos"):
            self._validade.set(OPCOES_VALIDADE[1][1])
            self.carregar()
        if parametros.get("lote_id"):
            self.tabela.selecionar_por("id", int(parametros["lote_id"]))
