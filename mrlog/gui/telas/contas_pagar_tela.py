"""
Tela de **Contas a pagar** — despesas, fornecedores e fluxo de saída do caixa.

Cobre o ciclo completo: lançamento (com fornecedor, categoria e vencimento),
edição enquanto não houver pagamento, pagamento total ou parcial (que sai do caixa
do dia), quitação, cancelamento, exclusão, comprovante em PDF e resumo por
categoria/fornecedor.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import contas_pagar as cp_mod
from ... import fornecedores as fornecedores_mod
from ... import formas_pagamento
from ... import impressao as impressao_mod
from ...esquema import CATEGORIAS_DESPESA
from ...utils import (
    converter_data_br,
    formatar_data,
    formatar_dinheiro,
    hoje,
    somar_dias,
)
from .. import dialogs
from ..widgets import Tabela
from . import TelaLista, imprimir_documento
from .contas_receber_tela import OPCOES_STATUS, ROTULOS_STATUS, texto_vencimento

MOTIVOS_CANCELAMENTO = (
    "Lançamento duplicado", "Conta cancelada pelo fornecedor", "Erro de valor/categoria",
    "Despesa não autorizada", "Renegociada em outro título",
)


class DialogoResumoDespesas(dialogs.Modal):
    """Despesas por categoria e por fornecedor (regime de caixa e competência)."""

    def __init__(self, mestre, tema, caixa: list[dict], competencia: list[dict], por_fornecedor: list[dict],
                resumo: dict):
        super().__init__(mestre, tema, "Contas a pagar — resumo por categoria e fornecedor",
                         largura=900, altura=620)
        cabecalho = ttk.Frame(self.corpo, style="TFrame")
        cabecalho.pack(fill="x", pady=(0, 8))
        cartoes = [
            ("A pagar", formatar_dinheiro(resumo["a_pagar"]), tema.cor("perigo")),
            ("Vencido", formatar_dinheiro(resumo["vencido"]), tema.cor("alerta")),
            ("Vence em 7 dias", formatar_dinheiro(resumo["vencendo_7_dias"]), tema.cor("info")),
            ("Pago no mês", formatar_dinheiro(resumo["pago_mes"]), tema.cor("sucesso")),
            ("Pago (total)", formatar_dinheiro(resumo["pago_total"]), tema.cor("fg")),
        ]
        for indice, (rotulo, valor, cor) in enumerate(cartoes):
            cartao = tk.Frame(cabecalho, background=tema.cor("bg_alt"),
                              highlightbackground=tema.cor("borda"), highlightthickness=1)
            cartao.grid(row=0, column=indice, sticky="nsew", padx=(0, 8))
            cabecalho.columnconfigure(indice, weight=1)
            tk.Label(cartao, text=rotulo, background=tema.cor("bg_alt"), foreground=tema.cor("fg_suave"),
                     font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(6, 0))
            tk.Label(cartao, text=valor, background=tema.cor("bg_alt"), foreground=cor,
                     font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=10, pady=(0, 6))

        abas = ttk.Notebook(self.corpo, style="TNotebook")
        abas.pack(fill="both", expand=True)

        colunas_categoria = [
            {"chave": "categoria", "rotulo": "Categoria", "largura": 230},
            {"chave": "quantidade", "rotulo": "Qtd", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "total", "rotulo": "Total pago", "largura": 130, "tipo": "dinheiro"},
            {"chave": "participacao_texto", "rotulo": "% do total", "largura": 110, "alinhamento": "centro"},
        ]
        for titulo, dados in (("Por categoria (pagamentos)", caixa), ("Por categoria (vencimento)", competencia)):
            pagina = ttk.Frame(abas, style="TFrame")
            abas.add(pagina, text=titulo)
            tabela = Tabela(pagina, tema, colunas_categoria, mostrar_busca=False, altura=12)
            tabela.pack(fill="both", expand=True, padx=6, pady=6)
            total_geral = sum(int(d["total"] or 0) for d in dados)
            linhas = []
            for item in dados:
                linha = dict(item)
                linha["participacao_texto"] = (f"{int(item['total'] or 0) / total_geral * 100:.1f}%"
                                               if total_geral else "0,0%")
                linhas.append(linha)
            tabela.carregar(linhas, resumo=f"Total: {formatar_dinheiro(total_geral)}")

        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Por fornecedor ({len(por_fornecedor)})")
        colunas_fornecedor = [
            {"chave": "fornecedor_nome", "rotulo": "Fornecedor", "largura": 280},
            {"chave": "quantidade", "rotulo": "Contas", "largura": 80, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "total", "rotulo": "Valor lançado", "largura": 140, "tipo": "dinheiro"},
            {"chave": "saldo", "rotulo": "Saldo em aberto", "largura": 140, "tipo": "dinheiro"},
        ]
        tabela = Tabela(pagina, tema, colunas_fornecedor, mostrar_busca=True, altura=12)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        tabela.carregar([dict(item) for item in por_fornecedor])

        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))


class ContasPagarTela(TelaLista):
    titulo = "Contas a pagar"
    descricao = "Despesas e fornecedores: lance, pague (total ou parcial), cancele e acompanhe os vencimentos."
    permissao_editar = "contas_pagar"
    permissao_excluir = "contas_pagar"

    def __init__(self, mestre, ctx):
        self._status = tk.StringVar(value=OPCOES_STATUS[0][1])
        self._vencimento_ate = tk.StringVar(value="")
        self._categoria = tk.StringVar(value="(todas)")
        self._fornecedor = tk.StringVar(value="")
        self._fornecedor_id: int | None = None
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "id", "rotulo": "Nº", "largura": 65, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "descricao", "rotulo": "Descrição", "largura": 240},
                {"chave": "fornecedor_nome", "rotulo": "Fornecedor", "largura": 190},
                {"chave": "categoria", "rotulo": "Categoria", "largura": 160},
                {"chave": "vencimento_texto", "rotulo": "Vencimento", "largura": 100, "alinhamento": "centro"},
                {"chave": "situacao_vencimento", "rotulo": "Prazo", "largura": 155},
                {"chave": "valor", "rotulo": "Valor", "largura": 110, "tipo": "dinheiro"},
                {"chave": "valor_pago", "rotulo": "Pago", "largura": 110, "tipo": "dinheiro"},
                {"chave": "saldo", "rotulo": "Saldo", "largura": 110, "tipo": "dinheiro"},
                {"chave": "status_texto", "rotulo": "Situação", "largura": 95, "alinhamento": "centro"},
                {"chave": "qtd_pagamentos", "rotulo": "Pagam.", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
            ],
            carregar_dados=self._dados,
            resumo=self._resumo,
            novo=self.nova_conta,
            editar=self._editar,
            excluir=self._excluir,
            ao_duplo_clique=lambda linha: self.pagar(linha),
            detalhes=self._detalhes,
            acoes=(
                ("💳 Pagar", self.pagar, "Primario.TButton", "F2"),
                ("✔ Quitar", self.quitar, "TButton", "F3"),
                ("🖨 Comprovante", self.imprimir_comprovante, "TButton", "F4"),
                ("✖ Cancelar conta", self.cancelar, "TButton", "F5"),
                ("📊 Resumo por categoria", self.ver_resumo, "TButton", "F6"),
                ("🚚 Fornecedores", self.ver_fornecedores, "TButton", "F7"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Contas a pagar",
            altura_tabela=20,
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        ttk.Label(pai, text="Situação:", style="TLabel").grid(row=0, column=0, sticky="w")
        self.combo_status = ttk.Combobox(pai, textvariable=self._status, width=26, state="readonly",
                                         values=[rotulo for _v, rotulo in OPCOES_STATUS])
        self.combo_status.grid(row=0, column=1, sticky="w", padx=(4, 14))
        self.combo_status.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Vencendo até:", style="TLabel").grid(row=0, column=2, sticky="w")
        entrada = ttk.Entry(pai, textvariable=self._vencimento_ate, width=12)
        entrada.grid(row=0, column=3, sticky="w", padx=(4, 6))
        entrada.bind("<Return>", lambda e: self.carregar())
        ttk.Button(pai, text="Hoje", command=lambda: self._vencendo(0)).grid(row=0, column=4, sticky="w")
        ttk.Button(pai, text="+7 dias", command=lambda: self._vencendo(7)).grid(row=0, column=5, sticky="w", padx=(4, 0))
        ttk.Button(pai, text="+30 dias", command=lambda: self._vencendo(30)).grid(row=0, column=6, sticky="w",
                                                                                  padx=(4, 14))

        ttk.Label(pai, text="Categoria:", style="TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.combo_categoria = ttk.Combobox(pai, textvariable=self._categoria, width=26, state="readonly",
                                            values=["(todas)"] + list(CATEGORIAS_DESPESA))
        self.combo_categoria.grid(row=1, column=1, sticky="w", padx=(4, 14), pady=(6, 0))
        self.combo_categoria.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Fornecedor:", style="TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))
        entrada_fornecedor = ttk.Entry(pai, textvariable=self._fornecedor, width=28)
        entrada_fornecedor.grid(row=1, column=3, columnspan=2, sticky="ew", padx=(4, 6), pady=(6, 0))
        entrada_fornecedor.bind("<Return>", lambda e: self.carregar())
        ttk.Button(pai, text="Selecionar...", command=self._escolher_fornecedor).grid(row=1, column=5, sticky="w",
                                                                                       pady=(6, 0))
        ttk.Button(pai, text="Limpar filtros", command=self.limpar_filtros).grid(row=1, column=6, sticky="w",
                                                                                 padx=(4, 0), pady=(6, 0))
        pai.columnconfigure(3, weight=1)

    def _vencendo(self, dias: int):
        self._vencimento_ate.set(formatar_data(somar_dias(hoje(), dias)))
        self.carregar()

    def limpar_filtros(self):
        self._status.set(OPCOES_STATUS[0][1])
        self._vencimento_ate.set("")
        self._categoria.set("(todas)")
        self._fornecedor.set("")
        self._fornecedor_id = None
        self.carregar()

    def _escolher_fornecedor(self):
        colunas = [
            {"chave": "nome", "rotulo": "Fornecedor", "largura": 240},
            {"chave": "documento_texto", "rotulo": "CNPJ/CPF", "largura": 150},
            {"chave": "saldo_aberto", "rotulo": "Saldo a pagar", "largura": 130, "tipo": "dinheiro"},
            {"chave": "prazo_dias", "rotulo": "Prazo (dias)", "largura": 100, "tipo": "inteiro",
             "alinhamento": "centro"},
        ]

        def buscar(termo: str):
            from ...utils import formatar_cpf_cnpj

            linhas = []
            for fornecedor in fornecedores_mod.listar(self.banco, filtro=termo, incluir_inativos=True):
                linha = dict(fornecedor)
                linha["documento_texto"] = formatar_cpf_cnpj(fornecedor["cnpj_cpf"] or "")
                linhas.append(linha)
            return linhas

        linha = dialogs.selecionar_registro(self.ctx.janela, self.tema, "Filtrar por fornecedor", colunas,
                                            buscar(""), ao_buscar=buscar, largura=760)
        if linha:
            self._fornecedor_id = int(linha["id"])
            self._fornecedor.set(linha["nome"])
            self.carregar()

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.pagar, "F3": self.quitar, "F4": self.imprimir_comprovante, "F5": self.cancelar,
                 "F6": self.ver_resumo, "F7": self.ver_fornecedores}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    # ------------------------------------------------------------------ dados
    def _status_selecionado(self) -> tuple[str, bool]:
        rotulo = self._status.get()
        for valor, texto in OPCOES_STATUS:
            if texto == rotulo:
                return ("", True) if valor == "todas" else (valor, False)
        return ("pendentes", False)

    def _dados(self) -> list[dict]:
        status, incluir_quitadas = self._status_selecionado()

        def consultar(status_filtro: str):
            return cp_mod.listar(
                self.banco,
                status=status_filtro,
                fornecedor_id=self._fornecedor_id,
                categoria=("" if self._categoria.get() == "(todas)" else self._categoria.get()),
                vencimento_ate=converter_data_br(self._vencimento_ate.get()) or "",
                texto=self._fornecedor.get().strip() if not self._fornecedor_id else "",
                limite=3000,
            )

        if incluir_quitadas:
            # "Tudo (inclusive canceladas)": junta as contas normais com as canceladas
            contas = list(consultar("")) + list(consultar("cancelada"))
            contas.sort(key=lambda c: (str(c["status"]) == "paga", str(c["vencimento"] or ""), int(c["id"])))
        else:
            contas = consultar(status)
        linhas = []
        for conta in contas:
            linha = dict(conta)
            status_conta = str(conta["status"] or "")
            linha["status_texto"] = ROTULOS_STATUS.get(status_conta, status_conta)
            linha["vencimento_texto"] = formatar_data(conta["vencimento"])
            linha["situacao_vencimento"] = texto_vencimento(conta["vencimento"], status_conta)
            linha["fornecedor_nome"] = conta["fornecedor_nome"] or "(sem fornecedor)"
            linha["valor"] = int(conta["valor"] or 0)
            linha["valor_pago"] = int(conta["valor_pago"] or 0)
            linha["saldo"] = int(conta["saldo"] or 0)
            if status_conta == "vencida":
                linha["_tag"] = "perigo"
            elif status_conta == "parcial":
                linha["_tag"] = "alerta"
            elif status_conta == "paga":
                linha["_tag"] = "sucesso"
            elif status_conta == "cancelada":
                linha["_tag"] = "neutro"
            linhas.append(linha)
        return linhas

    def _tag_linha(self, linha: dict) -> str:
        return str(linha.get("_tag") or "")

    def _resumo(self, dados) -> str:
        pendentes = [d for d in dados if d["status"] in ("aberta", "parcial", "vencida")]
        vencidas = [d for d in pendentes if d["status"] == "vencida"]
        return (f"{len(dados)} conta(s) • {len(pendentes)} em aberto "
                f"({formatar_dinheiro(sum(d['saldo'] for d in pendentes))}) • "
                f"{len(vencidas)} vencida(s) ({formatar_dinheiro(sum(d['saldo'] for d in vencidas))}) • "
                f"pago {formatar_dinheiro(sum(d['valor_pago'] for d in dados))}")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        conta = cp_mod.pegar(self.banco, linha["id"])
        if not conta:
            return []
        pagamentos = cp_mod.pagamentos(self.banco, int(conta["id"]))
        texto_pagamentos = "; ".join(
            f"{formatar_data(p['criado_em'], True)} {formatar_dinheiro(int(p['valor'] or 0))} ({p['forma']})"
            for p in pagamentos[-4:]
        )
        fornecedor = fornecedores_mod.pegar(self.banco, conta["fornecedor_id"]) if conta["fornecedor_id"] else None
        return [
            ("Conta nº", f"{int(conta['id']):06d}"),
            ("Descrição", conta["descricao"]),
            ("Categoria", conta["categoria"]),
            ("Fornecedor", conta["fornecedor_nome"] or "(sem fornecedor)"),
            ("Contato do fornecedor", (fornecedor["telefone"] or fornecedor["celular"] or "—") if fornecedor else "—"),
            ("Vencimento", formatar_data(conta["vencimento"])),
            ("Situação", linha["status_texto"] + f" — {linha['situacao_vencimento']}"),
            ("Valor", formatar_dinheiro(int(conta["valor"] or 0))),
            ("Pago", formatar_dinheiro(int(conta["valor_pago"] or 0))),
            ("Saldo", formatar_dinheiro(int(conta["saldo"] or 0))),
            ("Pagamentos", texto_pagamentos or "nenhum"),
            ("Criado em", formatar_data(conta["criado_em"], com_hora=True)),
            ("Observação", conta["observacao"]),
        ]

    # ------------------------------------------------------------------ ações
    def _conta_selecionada(self) -> dict | None:
        linha = self.exigir_selecao()
        if not linha:
            return None
        conta = cp_mod.pegar(self.banco, linha["id"])
        if not conta:
            dialogs.erro(self, self.tema, "Conta não encontrada (pode ter sido excluída).")
            self.carregar()
            return None
        return dict(conta)

    def pagar(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cp_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_pagar", "pagar contas"):
            return
        if conta["status"] == "cancelada":
            dialogs.alerta(self, self.tema, "Esta conta está cancelada.")
            return
        if conta["status"] == "paga":
            dialogs.alerta(self, self.tema, "Esta conta já está quitada.")
            return
        saldo = int(conta["saldo"] or 0)
        caixa_aberto = self.ctx.caixa_aberto
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Pagar conta nº {int(conta['id']):06d}",
            [
                {"chave": "valor", "rotulo": "Valor do pagamento", "tipo": "dinheiro", "largura": 14,
                 "obrigatorio": True, "dica": f"Saldo da conta: {formatar_dinheiro(saldo)}"},
                {"chave": "forma", "rotulo": "Forma de pagamento", "tipo": "lista", "largura": 22,
                 "opcoes": [(f, f) for f in formas_pagamento.PARA_RECEBIMENTOS]},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
                {"chave": "lancar_caixa", "rotulo": "Lançar no caixa do dia"
                 + ("" if caixa_aberto else " (nenhum caixa aberto)"), "tipo": "marcar",
                 "dica": "Pagamento em dinheiro só é permitido se houver saldo na gaveta."},
            ],
            {"valor": saldo, "forma": "Dinheiro", "lancar_caixa": bool(caixa_aberto)},
            largura=560,
            texto=f"{conta['descricao']} — {conta['categoria']}\n"
                  f"Fornecedor: {conta['fornecedor_nome'] or '(sem fornecedor)'}\n"
                  f"Vencimento: {formatar_data(conta['vencimento'])} "
                  f"({texto_vencimento(conta['vencimento'], conta['status'])})",
        )
        if not dados:
            return
        try:
            resultado = cp_mod.pagar(
                self.banco, int(conta["id"]), int(dados["valor"] or 0),
                forma=dados.get("forma") or "Dinheiro",
                observacao=(dados.get("observacao") or "").strip(), autor=self.usuario,
                lancar_no_caixa=bool(dados.get("lancar_caixa")),
            )
        except cp_mod.ErroContaPagar as exc:
            dialogs.erro(self, self.tema, str(exc), "Pagamento não lançado")
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(conta["id"]))
        self.ctx.app.atualizar_caixa()
        if resultado["saldo"] <= 0:
            dialogs.sucesso(self, self.tema,
                            f"Conta quitada!\n\nPago: {formatar_dinheiro(resultado['pago'])}\n"
                            f"{conta['descricao']}")
        else:
            dialogs.info(self, self.tema,
                         f"Pagamento parcial lançado.\n\nPago: {formatar_dinheiro(resultado['pago'])}\n"
                         f"Saldo da conta: {formatar_dinheiro(resultado['saldo'])}")

    def quitar(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cp_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_pagar", "quitar contas"):
            return
        if conta["status"] in ("paga", "cancelada"):
            dialogs.alerta(self, self.tema, "Esta conta já está quitada ou cancelada.")
            return
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Quitar conta nº {int(conta['id']):06d}",
            [
                {"chave": "forma", "rotulo": "Forma de pagamento", "tipo": "lista", "largura": 22,
                 "opcoes": [(f, f) for f in formas_pagamento.PARA_RECEBIMENTOS]},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            {"forma": "Dinheiro"}, largura=520,
            texto=f"{conta['descricao']}\nSaldo a quitar: {formatar_dinheiro(int(conta['saldo'] or 0))}",
        )
        if not dados:
            return
        try:
            resultado = cp_mod.quitar(self.banco, int(conta["id"]), forma=dados.get("forma") or "Dinheiro",
                                      observacao=(dados.get("observacao") or "").strip(), autor=self.usuario)
        except cp_mod.ErroContaPagar as exc:
            dialogs.erro(self, self.tema, str(exc), "Quitação não lançada")
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(conta["id"]))
        self.ctx.app.atualizar_caixa()
        dialogs.sucesso(self, self.tema, f"Conta quitada.\n\nPago: {formatar_dinheiro(resultado['pago'])}")

    def nova_conta(self, _tela=None):
        if not self.exigir("contas_pagar", "lançar contas a pagar"):
            return
        self._formulario(None)

    def _editar(self, _tela=None, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        if not self.exigir("contas_pagar", "editar contas a pagar"):
            return
        conta = cp_mod.pegar(self.banco, linha["id"])
        if not conta:
            dialogs.erro(self, self.tema, "Conta não encontrada.")
            self.carregar()
            return
        if int(conta["valor_pago"] or 0) > 0:
            dialogs.alerta(self, self.tema,
                           "Esta conta já tem pagamentos registrados e não pode ser editada.\n\n"
                           "Cancele-a e lance uma nova com os valores corretos.")
            return
        self._formulario(dict(conta))

    def _formulario(self, conta):
        editando = conta is not None
        opcoes_fornecedor = [(None, "(sem fornecedor)")] + list(fornecedores_mod.opcoes(self.banco))
        valores = {}
        if editando:
            valores = {
                "descricao": conta["descricao"], "categoria": conta["categoria"],
                "fornecedor_id": conta["fornecedor_id"], "valor": int(conta["valor"] or 0),
                "vencimento": conta["vencimento"], "observacao": conta["observacao"] or "",
            }
        else:
            valores = {"categoria": "Fornecedores", "vencimento": somar_dias(hoje(), 30)}
            if self._fornecedor_id:
                valores["fornecedor_id"] = self._fornecedor_id
        dados = dialogs.formulario(
            self.ctx.janela, self.tema,
            "Editar conta a pagar" if editando else "Nova conta a pagar",
            [
                {"chave": "descricao", "rotulo": "Descrição", "tipo": "texto", "largura": 34, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "categoria", "rotulo": "Categoria", "tipo": "lista", "largura": 24,
                 "opcoes": [(c, c) for c in CATEGORIAS_DESPESA]},
                {"chave": "fornecedor_id", "rotulo": "Fornecedor", "tipo": "lista", "largura": 26,
                 "opcoes": opcoes_fornecedor},
                {"chave": "valor", "rotulo": "Valor", "tipo": "dinheiro", "largura": 14, "obrigatorio": True},
                {"chave": "vencimento", "rotulo": "Vencimento", "tipo": "data", "largura": 12, "obrigatorio": True},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            valores, largura=620,
        )
        if not dados:
            return
        try:
            if editando:
                conta_id = cp_mod.atualizar(self.banco, int(conta["id"]), {
                    "descricao": dados["descricao"], "categoria": dados.get("categoria") or "Outros",
                    "fornecedor_id": dados.get("fornecedor_id"), "valor": int(dados["valor"] or 0),
                    "vencimento": dados.get("vencimento") or "", "observacao": dados.get("observacao") or "",
                }, autor=self.usuario)
                dialogs.sucesso(self, self.tema, "Conta atualizada.")
            else:
                conta_id = cp_mod.criar(
                    self.banco, dados["descricao"], int(dados["valor"] or 0),
                    vencimento=dados.get("vencimento") or "", fornecedor_id=dados.get("fornecedor_id"),
                    categoria=dados.get("categoria") or "Outros",
                    observacao=dados.get("observacao") or "", autor=self.usuario,
                )
                dialogs.sucesso(self, self.tema,
                                f"Conta nº {conta_id:06d} lançada.\n"
                                f"Valor: {formatar_dinheiro(int(dados['valor'] or 0))}\n"
                                f"Vencimento: {formatar_data(dados.get('vencimento') or '')}")
        except cp_mod.ErroContaPagar as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", conta_id)

    def imprimir_comprovante(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cp_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        try:
            caminho = impressao_mod.gerar_comprovante_pagamento_pdf(self.banco, int(conta["id"]))
        except impressao_mod.ErroImpressao as exc:
            dialogs.erro(self, self.tema, str(exc), "Comprovante")
            return
        imprimir_documento(self, self.tema, caminho, f"Comprovante de pagamento nº {int(conta['id']):06d}")

    def cancelar(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cp_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_pagar", "cancelar contas"):
            return
        if conta["status"] == "cancelada":
            dialogs.alerta(self, self.tema, "Esta conta já está cancelada.")
            return
        motivo = dialogs.pedir_motivo(
            self, self.tema, "Cancelar conta a pagar",
            f"Conta nº {int(conta['id']):06d} — {conta['descricao']}\n"
            f"Valor: {formatar_dinheiro(int(conta['valor'] or 0))}\n\n"
            "Descreva o motivo do cancelamento.",
            opcoes=MOTIVOS_CANCELAMENTO,
        )
        if not motivo:
            return
        try:
            cp_mod.cancelar(self.banco, int(conta["id"]), motivo=motivo, autor=self.usuario)
        except cp_mod.ErroContaPagar as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.info(self, self.tema, f"Conta nº {int(conta['id']):06d} cancelada.")

    def _excluir(self, _tela, linha: dict):
        if not self.exigir("contas_pagar", "excluir contas"):
            return None
        if not dialogs.confirmar(self, self.tema,
                                 f"Excluir definitivamente a conta nº {int(linha['id']):06d}?\n\n"
                                 f"{linha['descricao']} — {formatar_dinheiro(int(linha['valor'] or 0))}",
                                 "Excluir conta", "Excluir", "Cancelar"):
            return None
        try:
            cp_mod.excluir(self.banco, int(linha["id"]), autor=self.usuario)
        except cp_mod.ErroContaPagar as exc:
            dialogs.alerta(self, self.tema, str(exc), "Exclusão bloqueada")
            return None
        self.carregar()
        dialogs.sucesso(self, self.tema, "Conta excluída.")
        return True

    def ver_resumo(self):
        inicio = somar_dias(hoje(), -90)
        DialogoResumoDespesas(
            self.ctx.janela, self.tema,
            cp_mod.por_categoria(self.banco, inicio, hoje()),
            cp_mod.por_categoria_regime_competencia(self.banco, inicio, hoje()),
            cp_mod.por_fornecedor(self.banco),
            cp_mod.resumo(self.banco),
        ).abrir()

    def ver_fornecedores(self):
        self.ctx.navegar("fornecedores", {"apenas_com_saldo": True})

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("fornecedor_id"):
            fornecedor = fornecedores_mod.pegar(self.banco, int(parametros["fornecedor_id"]))
            self._fornecedor_id = int(parametros["fornecedor_id"])
            self._fornecedor.set(fornecedor["nome"] if fornecedor else "")
            self.carregar()
        if parametros.get("categoria"):
            self._categoria.set(str(parametros["categoria"]))
            self.carregar()
        if parametros.get("status"):
            for valor, rotulo in OPCOES_STATUS:
                if valor == str(parametros["status"]):
                    self._status.set(rotulo)
                    break
            self.carregar()
        if parametros.get("vencendo_ate"):
            self._vencimento_ate.set(formatar_data(str(parametros["vencendo_ate"])))
            self.carregar()
        if parametros.get("conta_id"):
            self.tabela.selecionar_por("id", int(parametros["conta_id"]))
