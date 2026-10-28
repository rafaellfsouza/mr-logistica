"""
Tela de **Vendas** — histórico completo dos cupons com detalhes, reimpressão do
recibo, cancelamento e devolução (total ou parcial, com reembolso em dinheiro,
crédito no fiado ou sem reembolso).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import formas_pagamento
from ... import impressao as impressao_mod
from ... import usuarios as usuarios_mod
from ... import vendas as vendas_mod
from ...utils import formatar_data, formatar_dinheiro, formatar_quantidade, hoje, intervalo_padrao, somar_dias
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO
from ..widgets import Tabela
from . import TelaLista, imprimir_documento

ROTULOS_STATUS = {
    "concluida": "Concluída",
    "parcialmente_devolvida": "Devolução parcial",
    "devolvida": "Devolvida",
    "cancelada": "Cancelada",
}

TAGS_STATUS = {
    "concluida": "sucesso",
    "parcialmente_devolvida": "info",
    "devolvida": "alerta",
    "cancelada": "perigo",
}

MOTIVOS_CANCELAMENTO = ("Cliente desistiu da compra", "Erro de digitação/lançamento", "Produto com defeito",
                        "Pagamento não confirmado", "Troca por outro produto", "Outro motivo")
MOTIVOS_DEVOLUCAO = ("Produto com defeito", "Cliente não gostou", "Produto errado (troca)",
                     "Desistência da compra", "Vencido/danificado", "Outro motivo")


class VendasTela(TelaLista):
    titulo = "Vendas"
    descricao = "Histórico de vendas, reimpressão de recibo, cancelamento e devolução."
    permissao_editar = "vendas"

    def __init__(self, mestre, ctx):
        self._data_inicial = tk.StringVar(value=intervalo_padrao(30)[0])
        self._data_final = tk.StringVar(value=hoje())
        self._status = tk.StringVar(value="Todas (exceto canceladas)")
        self._vendedor = tk.StringVar(value="(todos)")
        self._forma = tk.StringVar(value="(todas)")
        self._texto = tk.StringVar(value="")
        self._numero = tk.StringVar(value="")
        self._incluir_canceladas = tk.BooleanVar(value=False)
        super().__init__(
            mestre, ctx,
            colunas=self._colunas(),
            carregar_dados=self._dados,
            resumo=self._resumo,
            ao_duplo_clique=lambda linha: self.ver_detalhes(linha),
            detalhes=self._detalhes,
            acoes=(
                ("🔍 Ver detalhes", lambda: self.ver_detalhes(), "Primario.TButton", "Enter"),
                ("🖨️ Recibo", self.imprimir_recibo, "TButton", "Ctrl+P"),
                ("↩ Devolução", self.devolucao, "TButton", ""),
                ("✖ Cancelar venda", self.cancelar, "Perigo.TButton", ""),
                ("🗓 Hoje", self.filtrar_hoje, "TButton", ""),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Vendas",
            altura_tabela=15,
        )

    @staticmethod
    def _colunas() -> list[dict]:
        return [
            {"chave": "numero", "rotulo": "Cupom", "largura": 78, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "data_hora", "rotulo": "Data/Hora", "largura": 130, "tipo": "texto", "alinhamento": "centro"},
            {"chave": "cliente_nome", "rotulo": "Cliente", "largura": 200},
            {"chave": "vendedor_nome", "rotulo": "Vendedor", "largura": 140},
            {"chave": "formas", "rotulo": "Pagamento", "largura": 170},
            {"chave": "qtd_itens", "rotulo": "Itens", "largura": 60, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "subtotal", "rotulo": "Subtotal", "largura": 100, "tipo": "dinheiro"},
            {"chave": "desconto", "rotulo": "Desconto", "largura": 90, "tipo": "dinheiro"},
            {"chave": "total", "rotulo": "Total", "largura": 105, "tipo": "dinheiro"},
            {"chave": "valor_devolvido", "rotulo": "Devolvido", "largura": 100, "tipo": "dinheiro"},
            {"chave": "total_liquido", "rotulo": "Líquido", "largura": 105, "tipo": "dinheiro"},
            {"chave": "lucro_liquido", "rotulo": "Lucro", "largura": 100, "tipo": "dinheiro"},
            {"chave": "status_texto", "rotulo": "Situação", "largura": 130, "alinhamento": "centro"},
        ]

    # ------------------------------------------------------------------ filtros
    def _montar_filtros(self, pai: tk.Widget):
        def br(valor: tk.StringVar):
            return f"{valor.get()[8:10]}/{valor.get()[5:7]}/{valor.get()[:4]}" if len(valor.get()) == 10 else valor.get()

        ttk.Label(pai, text="De:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 2))
        e1 = ttk.Entry(pai, textvariable=self._data_inicial, width=11)
        e1.grid(row=0, column=1, sticky="w")
        ttk.Label(pai, text="Até:", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(6, 2))
        e2 = ttk.Entry(pai, textvariable=self._data_final, width=11)
        e2.grid(row=0, column=3, sticky="w")
        for entrada in (e1, e2):
            entrada.bind("<Return>", lambda e: self.carregar())
            entrada.bind("<FocusOut>", lambda e: self.carregar())

        ttk.Label(pai, text="Situação:", style="Card.TLabel").grid(row=0, column=4, sticky="w", padx=(10, 2))
        combo_status = ttk.Combobox(pai, textvariable=self._status, width=22, state="readonly",
                                    values=("Todas (exceto canceladas)", "Concluída", "Devolução parcial",
                                            "Devolvida", "Cancelada", "Todas (inclusive canceladas)"))
        combo_status.grid(row=0, column=5, sticky="w")
        combo_status.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Vendedor:", style="Card.TLabel").grid(row=0, column=6, sticky="w", padx=(10, 2))
        self.combo_vendedor = ttk.Combobox(pai, textvariable=self._vendedor, width=20, state="readonly",
                                           values=["(todos)"] + [u["nome"] for u in usuarios_mod.vendedores(self.banco)])
        self.combo_vendedor.grid(row=0, column=7, sticky="w")
        self.combo_vendedor.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Pagamento:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.combo_forma = ttk.Combobox(pai, textvariable=self._forma, width=16, state="readonly",
                                        values=["(todas)"] + formas_pagamento.TODAS)
        self.combo_forma.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))
        self.combo_forma.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Cupom nº:", style="Card.TLabel").grid(row=1, column=3, sticky="e", pady=(8, 0))
        entrada_numero = ttk.Entry(pai, textvariable=self._numero, width=10)
        entrada_numero.grid(row=1, column=4, sticky="w", padx=(4, 0), pady=(8, 0))
        entrada_numero.bind("<Return>", lambda e: self.carregar())

        ttk.Label(pai, text="Cliente/vendedor/obs.:", style="Card.TLabel").grid(row=1, column=5, sticky="e", pady=(8, 0))
        entrada_texto = ttk.Entry(pai, textvariable=self._texto, width=26)
        entrada_texto.grid(row=1, column=6, columnspan=2, sticky="ew", pady=(8, 0))
        entrada_texto.bind("<KeyRelease>", lambda e: self.carregar())
        ttk.Button(pai, text="Aplicar", command=self.carregar).grid(row=1, column=8, sticky="w", padx=(8, 0), pady=(8, 0))
        pai.columnconfigure(7, weight=1)
        self._entrada_texto = entrada_texto

    def focar_busca(self):
        if getattr(self, "_entrada_texto", None) is not None:
            self._entrada_texto.focus_set()

    def filtrar_hoje(self):
        self._data_inicial.set(hoje())
        self._data_final.set(hoje())
        self.carregar()

    # ------------------------------------------------------------------ dados
    def _status_filtro(self) -> tuple[str, bool]:
        mapa = {
            "Concluída": ("concluida", False),
            "Devolução parcial": ("parcialmente_devolvida", False),
            "Devolvida": ("devolvida", False),
            "Cancelada": ("cancelada", True),
            "Todas (inclusive canceladas)": ("", True),
        }
        return mapa.get(self._status.get(), ("", False))

    def _vendedor_id(self) -> int | None:
        nome = self._vendedor.get().strip()
        if nome in ("", "(todos)"):
            return None
        for usuario in usuarios_mod.vendedores(self.banco):
            if usuario["nome"] == nome:
                return int(usuario["id"])
        return None

    def _dados(self) -> list[dict]:
        from ...utils import converter_data_br

        status, incluir_canceladas = self._status_filtro()
        numero = None
        if self._numero.get().strip().isdigit():
            numero = int(self._numero.get().strip())
        vendas = vendas_mod.listar(
            self.banco,
            data_inicial=converter_data_br(self._data_inicial.get()) or "",
            data_final=converter_data_br(self._data_final.get()) or "",
            status=status,
            vendedor_id=self._vendedor_id(),
            texto=self._texto.get().strip(),
            forma_pagamento=("" if self._forma.get() in ("", "(todas)") else self._forma.get()),
            numero=numero,
            incluir_canceladas=incluir_canceladas,
            limite=2000,
        )
        linhas = []
        for venda in vendas:
            linha = dict(venda)
            linha["status_texto"] = ROTULOS_STATUS.get(venda["status"], venda["status"])
            linha["_tag"] = TAGS_STATUS.get(venda["status"], "")
            linha["data_hora"] = formatar_data(venda["criada_em"] or venda["data_venda"], com_hora=True)[:16]
            linhas.append(linha)
        return linhas

    def _resumo(self, dados) -> str:
        total = sum(int(d["total_liquido"] or 0) for d in dados if d["status"] != "cancelada")
        lucro = sum(int(d["lucro_liquido"] or 0) for d in dados if d["status"] != "cancelada")
        canceladas = sum(1 for d in dados if d["status"] == "cancelada")
        texto = (f"{len(dados)} venda(s) • Faturamento líquido: {formatar_dinheiro(total)} • "
                 f"Lucro: {formatar_dinheiro(lucro)}")
        if canceladas:
            texto += f" • {canceladas} cancelada(s)"
        return texto

    def _tag_linha(self, linha: dict) -> str:
        return TAGS_STATUS.get(str(linha.get("status")), "")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        venda = vendas_mod.pegar(self.banco, linha["id"])
        if not venda:
            return []
        pares = [
            ("Cupom", f"{int(venda['numero']):06d}"),
            ("Data", formatar_data(venda["criada_em"], com_hora=True)),
            ("Cliente", venda["cliente_nome"] or "Consumidor final"),
            ("Vendedor", venda["vendedor_nome"] or "—"),
            ("Pagamentos", ", ".join(f"{p['forma']} {formatar_dinheiro(int(p['valor']))}"
                                     + (f" ({int(p['parcelas'])}x)" if int(p["parcelas"] or 1) > 1 else "")
                                     for p in vendas_mod.pagamentos(self.banco, venda["id"]))),
            ("Troco", formatar_dinheiro(int(venda["troco"] or 0)) if int(venda["troco"] or 0) else ""),
            ("Fiado", formatar_dinheiro(int(venda["valor_fiado"] or 0)) if int(venda["valor_fiado"] or 0) else ""),
            ("Acréscimo", formatar_dinheiro(int(venda["acrescimo"] or 0)) if int(venda["acrescimo"] or 0) else ""),
            ("Devolvido", formatar_dinheiro(int(venda["valor_devolvido"] or 0)) if int(venda["valor_devolvido"] or 0) else ""),
            ("Situação", ROTULOS_STATUS.get(venda["status"], venda["status"])),
            ("Observação", venda["observacao"]),
        ]
        return [(r, v) for r, v in pares if v]

    # ------------------------------------------------------------------ ações
    def _venda_selecionada(self):
        linha = self.exigir_selecao()
        if not linha:
            return None
        venda = vendas_mod.pegar(self.banco, linha["id"])
        if not venda:
            dialogs.erro(self, self.tema, "Venda não encontrada (pode ter sido removida).")
            self.carregar()
        return venda

    def ver_detalhes(self, linha: dict | None = None):
        venda = self._venda_selecionada() if linha is None else vendas_mod.pegar(self.banco, linha["id"])
        if not venda:
            return
        mostrar_detalhes_venda(self, self.ctx, venda)

    def imprimir_recibo(self, linha: dict | None = None, silencioso: bool = False):
        venda = self._venda_selecionada() if linha is None else vendas_mod.pegar(self.banco, linha["id"])
        if not venda:
            return None
        if venda["status"] == "cancelada":
            if not dialogs.confirmar(self, self.tema,
                                     "Esta venda está cancelada. Imprimir mesmo assim (com a marca de cancelamento)?",
                                     "Venda cancelada", "Imprimir", "Cancelar"):
                return None
        try:
            caminho = impressao_mod.gerar_recibo_pdf(
                self.banco, int(venda["id"]),
                largura=str(self.banco.config_pegar("recibo_largura", "80mm") or "80mm"),
            )
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Não foi possível gerar o recibo.")
            return None
        if not silencioso:
            imprimir_documento(self, self.tema, caminho, f"Recibo do cupom {int(venda['numero']):06d}")
        return caminho

    def cancelar(self):
        if not self.exigir("vendas_cancelar", "cancelar vendas"):
            return
        venda = self._venda_selecionada()
        if not venda:
            return
        ok, mensagem = vendas_mod.pode_cancelar(venda, self.usuario)
        if not ok:
            dialogs.alerta(self, self.tema, mensagem, "Cancelamento não permitido")
            return
        motivo = dialogs.pedir_motivo(
            self, self.tema, "Cancelar venda",
            f"Cupom nº {int(venda['numero']):06d} — {formatar_dinheiro(int(venda['total']))}\n"
            "O cancelamento devolve os produtos ao estoque, estorna os valores no caixa "
            "e cancela o fiado gerado.\n\nInforme o motivo (fica registrado):",
            opcoes=MOTIVOS_CANCELAMENTO,
        )
        if not motivo:
            return
        try:
            resultado = vendas_mod.cancelar(self.banco, int(venda["id"]), motivo=motivo, autor=self.usuario)
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc), "Não foi possível cancelar")
            return
        self.carregar()
        self.ctx.app.atualizar_caixa()
        texto = [f"Cupom nº {resultado['numero']:06d} cancelado."]
        if resultado["total_reembolso"]:
            texto.append(f"Estorno no caixa: {formatar_dinheiro(resultado['total_reembolso'])}.")
        if resultado["restaurou_estoque"]:
            texto.append("Os produtos voltaram ao estoque.")
        dialogs.sucesso(self, self.tema, "\n".join(texto))

    def devolucao(self):
        if not self.exigir("vendas_devolver", "registrar devoluções"):
            return
        venda = self._venda_selecionada()
        if not venda:
            return
        ok, mensagem = vendas_mod.pode_devolver(venda, self.usuario)
        if not ok:
            dialogs.alerta(self, self.tema, mensagem, "Devolução não permitida")
            return
        resultado = registrar_devolucao(self.ctx, int(venda["id"]))
        if resultado:
            self.carregar()
            self.ctx.app.atualizar_caixa()

    # ------------------------------------------------------------------ teclas / tema
    def ao_tecla(self, tecla: str) -> bool:
        return False

    def receber_parametros(self, parametros: dict):
        """Recebe o foco vindo de outras telas (usuários, clientes, painel...)."""
        parametros = parametros or {}
        if parametros.get("venda_id"):
            self._numero.set("")
            self.carregar()
            self.tabela.selecionar_por("id", int(parametros["venda_id"]))
            self.ver_detalhes()
            return
        alterou = False
        if parametros.get("data"):
            self._data_inicial.set(str(parametros["data"]))
            self._data_final.set(str(parametros["data"]))
            alterou = True
        if parametros.get("data_inicial"):
            self._data_inicial.set(str(parametros["data_inicial"]))
            alterou = True
        if parametros.get("data_final"):
            self._data_final.set(str(parametros["data_final"]))
            alterou = True
        if parametros.get("vendedor_nome"):
            self._vendedor.set(str(parametros["vendedor_nome"]))
            alterou = True
        if parametros.get("cliente_nome"):
            self._texto.set(str(parametros["cliente_nome"]))
            alterou = True
        if parametros.get("forma_pagamento"):
            self._forma.set(str(parametros["forma_pagamento"]))
            alterou = True
        if alterou:
            self.carregar()

    def carregar(self):
        super().carregar()
        try:
            self.combo_vendedor.configure(values=["(todos)"] + [u["nome"] for u in usuarios_mod.vendedores(self.banco)])
        except tk.TclError:
            pass


# --------------------------------------------------------------------------------------
# Detalhes da venda
# --------------------------------------------------------------------------------------


def mostrar_detalhes_venda(tela, ctx, venda) -> None:
    """Janela com abas: itens, pagamentos, devoluções e resumo do cupom."""
    venda_id = int(venda["id"])
    dialogo = dialogs.Modal(tela, ctx.tema, f"Cupom nº {int(venda['numero']):06d}", largura=900, altura=620)
    tema = ctx.tema

    cabecalho = ttk.Frame(dialogo.corpo, style="Card.TFrame", padding=10)
    cabecalho.pack(fill="x")
    linhas = [
        f"Cliente: {venda['cliente_nome'] or 'Consumidor final'}     "
        f"Vendedor: {venda['vendedor_nome'] or '—'}",
        f"Data: {formatar_data(venda['criada_em'], com_hora=True)}     "
        f"Situação: {ROTULOS_STATUS.get(venda['status'], venda['status'])}",
        f"Subtotal: {formatar_dinheiro(int(venda['subtotal'] or 0))}     "
        f"Desconto: {formatar_dinheiro(int(venda['desconto'] or 0))}     "
        f"Acréscimo: {formatar_dinheiro(int(venda['acrescimo'] or 0))}     "
        f"TOTAL: {formatar_dinheiro(int(venda['total'] or 0))}",
        f"Lucro: {formatar_dinheiro(int(venda['lucro'] or 0))}     "
        f"Devolvido: {formatar_dinheiro(int(venda['valor_devolvido'] or 0))}     "
        f"Líquido: {formatar_dinheiro(int(venda['total_liquido'] or 0))}",
    ]
    if venda["observacao"]:
        linhas.append(f"Observação: {venda['observacao']}")
    ttk.Label(cabecalho, text="\n".join(linhas), style="Card.TLabel", justify="left",
              wraplength=860, font=FONTE_PEQUENA).pack(anchor="w")

    abas = ttk.Notebook(dialogo.corpo)
    abas.pack(fill="both", expand=True, pady=(10, 0))

    # --- itens
    quadro_itens = ttk.Frame(abas, style="TFrame", padding=6)
    abas.add(quadro_itens, text="Itens")
    tabela_itens = Tabela(
        quadro_itens, tema,
        [{"chave": "ordem", "rotulo": "#", "largura": 44, "tipo": "inteiro", "alinhamento": "centro"},
         {"chave": "codigo", "rotulo": "Código", "largura": 90},
         {"chave": "nome", "rotulo": "Produto", "largura": 300},
         {"chave": "quantidade_texto", "rotulo": "Quantidade", "largura": 120, "alinhamento": "centro"},
         {"chave": "preco_unitario", "rotulo": "Preço unit.", "largura": 100, "tipo": "dinheiro"},
         {"chave": "desconto", "rotulo": "Desconto", "largura": 90, "tipo": "dinheiro"},
         {"chave": "total_liquido", "rotulo": "Total", "largura": 110, "tipo": "dinheiro"},
         {"chave": "lucro", "rotulo": "Lucro", "largura": 100, "tipo": "dinheiro"},
         {"chave": "devolvido_texto", "rotulo": "Devolvido", "largura": 110, "alinhamento": "centro"}],
        mostrar_busca=False, altura=10,
    )
    tabela_itens.pack(fill="both", expand=True)
    itens = []
    for item in vendas_mod.itens_venda_dict(ctx.banco, venda_id):
        linha = dict(item)
        linha["quantidade_texto"] = f"{formatar_quantidade(item['quantidade'])} {item['unidade']}"
        devolvido = float(item.get("quantidade_devolvida") or 0)
        linha["devolvido_texto"] = (f"{formatar_quantidade(devolvido)} {item.get('unidade_base') or item['unidade']}"
                                    if devolvido else "—")
        itens.append(linha)
    tabela_itens.carregar(itens)

    # --- pagamentos
    quadro_pagamentos = ttk.Frame(abas, style="TFrame", padding=6)
    abas.add(quadro_pagamentos, text="Pagamentos")
    tabela_pagamentos = Tabela(
        quadro_pagamentos, tema,
        [{"chave": "forma", "rotulo": "Forma", "largura": 180},
         {"chave": "valor", "rotulo": "Valor", "largura": 120, "tipo": "dinheiro"},
         {"chave": "parcelas", "rotulo": "Parcelas", "largura": 90, "tipo": "inteiro", "alinhamento": "centro"},
         {"chave": "recebido", "rotulo": "Recebido", "largura": 120, "tipo": "dinheiro"},
         {"chave": "operadora", "rotulo": "Operadora/autorização", "largura": 200}],
        mostrar_busca=False, altura=8,
    )
    tabela_pagamentos.pack(fill="both", expand=True)
    pagamentos = [dict(p) for p in vendas_mod.pagamentos_dict(ctx.banco, venda_id)]
    tabela_pagamentos.carregar(pagamentos)
    if int(venda["troco"] or 0) > 0:
        ttk.Label(quadro_pagamentos, text=f"Troco devolvido ao cliente: {formatar_dinheiro(int(venda['troco']))}",
                  style="TLabel", font=FONTE_SUBTITULO).pack(anchor="w", pady=(6, 0))
    if int(venda["valor_fiado"] or 0) > 0:
        ttk.Label(quadro_pagamentos,
                  text=f"Valor lançado no fiado: {formatar_dinheiro(int(venda['valor_fiado']))} (gera conta a receber)",
                  style="TLabel").pack(anchor="w", pady=(2, 0))

    # --- devoluções
    quadro_devolucoes = ttk.Frame(abas, style="TFrame", padding=6)
    abas.add(quadro_devolucoes, text="Devoluções")
    tabela_devolucoes = Tabela(
        quadro_devolucoes, tema,
        [{"chave": "data_texto", "rotulo": "Data", "largura": 130, "alinhamento": "centro"},
         {"chave": "produto", "rotulo": "Produto", "largura": 260},
         {"chave": "quantidade_texto", "rotulo": "Quantidade", "largura": 120, "alinhamento": "centro"},
         {"chave": "valor", "rotulo": "Valor", "largura": 110, "tipo": "dinheiro"},
         {"chave": "reembolso", "rotulo": "Reembolso", "largura": 110, "alinhamento": "centro"},
         {"chave": "motivo", "rotulo": "Motivo", "largura": 240}],
        mostrar_busca=False, altura=8,
    )
    tabela_devolucoes.pack(fill="both", expand=True)
    devolucoes = []
    for devolucao in vendas_mod.devolucoes_da_venda(ctx.banco, venda_id):
        itens_devolvidos = ctx.banco.consultar(
            """SELECT di.*, vi.nome, vi.unidade_base, vi.unidade
                 FROM devolucao_itens di JOIN venda_itens vi ON vi.id = di.venda_item_id
                WHERE di.devolucao_id=?""",
            (devolucao["id"],),
        )
        for item in itens_devolvidos:
            devolucoes.append({
                "data_texto": formatar_data(devolucao["criado_em"] or hoje(), com_hora=True)[:16],
                "produto": item["nome"],
                "quantidade_texto": f"{formatar_quantidade(item['quantidade_base'])} {item['unidade_base'] or item['unidade']}",
                "valor": int(item["valor"] or 0),
                "reembolso": str(devolucao["tipo_reembolso"] or "").capitalize(),
                "motivo": devolucao["motivo"] or "",
            })
    tabela_devolucoes.carregar(devolucoes, resumo="" if devolucoes else "Nenhuma devolução registrada neste cupom.")

    # --- botões
    def recibo():
        tela.imprimir_recibo({"id": venda_id})

    def devolver():
        dialogo.cancelar()
        if ctx.pode("vendas_devolver"):
            registrar_devolucao(ctx, venda_id)
            tela.carregar()

    def cancelar_venda():
        dialogo.cancelar()
        tela.cancelar()

    botoes = [("Fechar", dialogo.confirmar, "TButton"), ("🖨️ Recibo", recibo, "TButton")]
    if ctx.pode("vendas_devolver") and venda["status"] not in ("cancelada", "devolvida"):
        botoes.append(("↩ Devolver itens", devolver, "TButton"))
    if ctx.pode("vendas_cancelar") and venda["status"] != "cancelada":
        botoes.append(("✖ Cancelar cupom", cancelar_venda, "Perigo.TButton"))
    dialogo.barra_botoes(tuple(botoes))
    dialogo.abrir()


# --------------------------------------------------------------------------------------
# Devolução
# --------------------------------------------------------------------------------------


def registrar_devolucao(ctx, venda_id: int) -> dict | None:
    """Diálogo de devolução: escolher itens, quantidades e forma de reembolso."""
    banco = ctx.banco
    itens = vendas_mod.itens_devoluveis(banco, venda_id)
    if not itens:
        dialogs.info(ctx.janela, ctx.tema, "Todos os itens deste cupom já foram devolvidos.")
        return None
    venda = vendas_mod.pegar(banco, venda_id)

    dialogo = dialogs.Modal(ctx.janela, ctx.tema, f"Devolução — cupom {int(venda['numero']):06d}", largura=880, altura=600)
    ttk.Label(
        dialogo.corpo,
        text="Marque os itens devolvidos, informe a quantidade e escolha como o valor será reembolsado.\n"
             "A mercadoria volta ao estoque e o valor sai do caixa (ou vira crédito no fiado do cliente).",
        style="Suave.TLabel", wraplength=840, justify="left",
    ).pack(anchor="w")

    quadro = ttk.Frame(dialogo.corpo, style="TFrame")
    quadro.pack(fill="both", expand=True, pady=(8, 0))
    colunas = ("sel", "codigo", "nome", "qtd_vendida", "qtd_devolver", "unidade", "valor")
    tabela = ttk.Treeview(quadro, columns=colunas, show="headings", height=8, selectmode="browse")
    cabecalhos = {"sel": ("Dev.", 50, "center"), "codigo": ("Código", 90, "w"), "nome": ("Produto", 300, "w"),
                  "qtd_vendida": ("Qtd vendida", 100, "e"), "qtd_devolver": ("Qtd a devolver", 120, "e"),
                  "unidade": ("Unidade", 70, "center"), "valor": ("Valor", 110, "e")}
    for coluna in colunas:
        rotulo, largura, ancora = cabecalhos[coluna]
        tabela.heading(coluna, text=rotulo, anchor=ancora)
        tabela.column(coluna, width=largura, anchor=ancora)
    tabela.grid(row=0, column=0, sticky="nsew")
    barra = ttk.Scrollbar(quadro, orient="vertical", command=tabela.yview)
    tabela.configure(yscrollcommand=barra.set)
    barra.grid(row=0, column=1, sticky="ns")
    quadro.rowconfigure(0, weight=1)
    quadro.columnconfigure(0, weight=1)

    marcados = {item["venda_item_id"]: False for item in itens}
    quantidades = {item["venda_item_id"]: item["quantidade_disponivel"] for item in itens}

    def desenhar():
        tabela.delete(*tabela.get_children())
        for item in itens:
            identificador = item["venda_item_id"]
            marcado = "✔" if marcados[identificador] else ""
            quantidade = quantidades[identificador] if marcados[identificador] else 0
            valor = int(round(quantidade * item["valor_por_unidade_base"])) if marcados[identificador] else 0
            tabela.insert("", "end", iid=str(identificador), values=(
                marcado, item["codigo"], item["nome"],
                f"{formatar_quantidade(item['quantidade_vendida'])} {item['unidade']}",
                formatar_quantidade(quantidade) if marcados[identificador] else "—",
                item["unidade_base"], formatar_dinheiro(valor),
            ))
        atualizar_total()

    rotulo_total = ttk.Label(dialogo.corpo, text="", style="TLabel", font=FONTE_TITULO)

    def atualizar_total():
        total = 0
        for item in itens:
            if marcados[item["venda_item_id"]]:
                total += int(round(quantidades[item["venda_item_id"]] * item["valor_por_unidade_base"]))
        rotulo_total.configure(text=f"Valor a reembolsar: {formatar_dinheiro(total)}")

    def ao_clicar(evento):
        identificadores = tabela.identify_row(evento.y)
        if not identificadores:
            return
        identificador = int(identificadores)
        marcados[identificador] = not marcados[identificador]
        desenhar()

    tabela.bind("<Button-1>", ao_clicar)
    tabela.bind("<space>", lambda e: _alternar_selecao())

    def _alternar_selecao():
        selecao = tabela.selection()
        if not selecao:
            return
        identificador = int(selecao[0])
        marcados[identificador] = not marcados[identificador]
        desenhar()
        return "break"

    botoes_quadro = ttk.Frame(dialogo.corpo, style="TFrame")
    botoes_quadro.pack(fill="x", pady=(8, 0))

    def marcar_tudo():
        for chave in marcados:
            marcados[chave] = True
        desenhar()

    def desmarcar_tudo():
        for chave in marcados:
            marcados[chave] = False
        desenhar()

    def alterar_quantidade():
        selecao = tabela.selection()
        if not selecao:
            dialogs.alerta(dialogo, ctx.tema, "Selecione o item na tabela para alterar a quantidade.")
            return
        identificador = int(selecao[0])
        item = next(i for i in itens if i["venda_item_id"] == identificador)
        marcados[identificador] = True
        valor = dialogs.pedir_valor(
            dialogo, ctx.tema, f"Quantidade a devolver — {item['nome']}",
            f"Quantidade ({item['unidade_base']})", quantidades[identificador], tipo="quantidade",
            dica=f"Máximo disponível para devolução: {formatar_quantidade(item['quantidade_disponivel'])} "
                 f"{item['unidade_base']}",
        )
        if valor is None:
            return
        if float(valor) <= 0 or float(valor) > item["quantidade_disponivel"] + 1e-9:
            dialogs.alerta(dialogo, ctx.tema,
                           f"A quantidade deve estar entre 0 e {formatar_quantidade(item['quantidade_disponivel'])}.")
            return
        quantidades[identificador] = float(valor)
        desenhar()

    ttk.Button(botoes_quadro, text="Marcar todos", command=marcar_tudo).pack(side="left")
    ttk.Button(botoes_quadro, text="Desmarcar todos", command=desmarcar_tudo).pack(side="left", padx=6)
    ttk.Button(botoes_quadro, text="Alterar quantidade (Enter)", command=alterar_quantidade).pack(side="left")
    tabela.bind("<Return>", lambda e: alterar_quantidade())
    rotulo_total.pack(anchor="w", pady=(8, 0))

    ttk.Label(dialogo.corpo, text="Forma de reembolso:", style="TLabel").pack(anchor="w", pady=(8, 0))
    reembolso = tk.StringVar(value="dinheiro")
    quadro_reembolso = ttk.Frame(dialogo.corpo, style="TFrame")
    quadro_reembolso.pack(anchor="w")
    for valor, rotulo, dica in (
        ("dinheiro", "Dinheiro (saida do caixa)", "O valor sai do caixa e volta ao cliente"),
        ("credito", "Crédito no fiado", "Abate na conta a receber do cliente (ou fica de crédito)"),
        ("nenhum", "Sem reembolso (troca/cortesia)", "Apenas a mercadoria volta ao estoque"),
    ):
        ttk.Radiobutton(quadro_reembolso, text=f"{rotulo} — {dica}", value=valor, variable=reembolso).pack(anchor="w")

    ttk.Label(dialogo.corpo, text="Motivo da devolução *:", style="TLabel").pack(anchor="w", pady=(10, 0))
    entrada_motivo = ttk.Entry(dialogo.corpo, width=70)
    entrada_motivo.pack(anchor="w", fill="x")
    quadro_motivos = ttk.Frame(dialogo.corpo, style="TFrame")
    quadro_motivos.pack(anchor="w", fill="x", pady=(4, 0))
    for indice, motivo in enumerate(MOTIVOS_DEVOLUCAO):
        ttk.Button(quadro_motivos, text=motivo,
                   command=lambda m=motivo: (entrada_motivo.delete(0, "end"), entrada_motivo.insert(0, m))).grid(
            row=indice // 3, column=indice % 3, sticky="w", padx=2, pady=2)

    restaurar = tk.BooleanVar(value=True)
    ttk.Checkbutton(dialogo.corpo, text="Devolver a mercadoria ao estoque", variable=restaurar).pack(anchor="w", pady=(8, 0))

    def confirmar():
        selecionados = [
            {"venda_item_id": item["venda_item_id"], "quantidade_base": quantidades[item["venda_item_id"]]}
            for item in itens if marcados[item["venda_item_id"]] and quantidades[item["venda_item_id"]] > 0
        ]
        if not selecionados:
            dialogs.alerta(dialogo, ctx.tema, "Marque ao menos um item para devolver.")
            return
        motivo = entrada_motivo.get().strip()
        if not motivo:
            dialogs.alerta(dialogo, ctx.tema, "Informe o motivo da devolução.")
            return
        try:
            resultado = vendas_mod.devolver(banco, venda_id, selecionados, motivo=motivo,
                                            tipo_reembolso=reembolso.get(), autor=ctx.usuario,
                                            restaurar_estoque=bool(restaurar.get()))
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(dialogo, ctx.tema, str(exc), "Devolução não registrada")
            return
        dialogo.confirmar(resultado)

    dialogo.barra_botoes((("Confirmar devolução", confirmar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
    desenhar()
    resultado = dialogo.abrir()
    if resultado:
        texto = [f"Devolução registrada no cupom nº {int(resultado['numero']):06d}.",
                 f"Valor devolvido: {formatar_dinheiro(int(resultado.get('valor', 0) or 0))}."]
        tipo = str(resultado.get("tipo_reembolso", ""))
        if tipo == "dinheiro":
            texto.append("O valor foi lançado como saída no caixa (dinheiro).")
        elif tipo == "credito":
            texto.append("O valor ficou como crédito/abate no fiado do cliente.")
        else:
            texto.append("Nenhum reembolso financeiro (apenas retorno da mercadoria).")
        texto.append(f"Nova situação do cupom: {ROTULOS_STATUS.get(resultado.get('status', ''), resultado.get('status', ''))}.")
        dialogs.sucesso(ctx.janela, ctx.tema, "\n".join(texto), "Devolução concluída")
    return resultado
