"""
Tela de **Contas a receber** — o fiado/crediário da loja.

Cobre todo o ciclo do título: lançamento manual ou automático (venda no fiado),
recebimento total ou parcial com desconto, prorrogação de vencimento,
cancelamento, reabertura, exclusão, comprovante em PDF e aging de devedores.

Recebimentos em dinheiro entram automaticamente no caixa do dia (quando há caixa
aberto) — a mesma regra usada pelo PDV.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import clientes as clientes_mod
from ... import contas_receber as cr_mod
from ... import formas_pagamento
from ... import impressao as impressao_mod
from ...utils import (
    converter_data_br,
    dias_entre,
    formatar_data,
    formatar_dinheiro,
    formatar_telefone,
    hoje,
    somar_dias,
)
from .. import dialogs
from ..widgets import Tabela
from . import TelaLista, imprimir_documento
from .clientes_tela import selecionar_cliente

OPCOES_STATUS = [
    ("pendentes", "Pendentes (em aberto)"),
    ("atrasadas", "Somente atrasadas"),
    ("aberta", "Em aberto (a vencer)"),
    ("parcial", "Parcialmente recebidas"),
    ("vencida", "Vencidas"),
    ("paga", "Quitadas"),
    ("cancelada", "Canceladas"),
    ("", "Todas (exceto canceladas)"),
    ("todas", "Tudo (inclusive canceladas)"),
]

MOTIVOS_CANCELAMENTO = (
    "Cliente pagou em outra conta", "Venda cancelada", "Erro de lançamento",
    "Acordo/desconto integral", "Cliente inativo sem débito",
)

ROTULOS_STATUS = {
    "aberta": "Em aberto", "parcial": "Parcial", "vencida": "Vencida",
    "paga": "Quitada", "cancelada": "Cancelada",
}


def texto_vencimento(vencimento: str, status: str) -> str:
    """Texto amigável da situação do vencimento (“vence hoje”, “atrasada 3 dias”...)."""
    if not vencimento:
        return "—"
    if status in ("paga", "cancelada"):
        return formatar_data(vencimento)
    dias = dias_entre(vencimento)
    if dias < 0:
        return f"Atrasada há {abs(dias)} dia(s)"
    if dias == 0:
        return "Vence hoje"
    if dias == 1:
        return "Vence amanhã"
    return f"Vence em {dias} dia(s)"


class DialogoAging(dialogs.Modal):
    """Aging (faixas de atraso) e ranking de devedores."""

    def __init__(self, mestre, tema, faixas: list[dict], devedores: list[dict]):
        super().__init__(mestre, tema, "Contas a receber — aging e devedores", largura=880, altura=600)
        total = sum(int(f["valor"] or 0) for f in faixas)
        ttk.Label(self.corpo, text=f"Saldo total em aberto: {formatar_dinheiro(total)}",
                  style="TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))

        abas = ttk.Notebook(self.corpo, style="TNotebook")
        abas.pack(fill="both", expand=True)

        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text="Faixas de atraso")
        colunas = [
            {"chave": "faixa", "rotulo": "Faixa", "largura": 200},
            {"chave": "quantidade", "rotulo": "Títulos", "largura": 100, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "valor", "rotulo": "Valor", "largura": 140, "tipo": "dinheiro"},
            {"chave": "participacao_texto", "rotulo": "% do total", "largura": 110, "alinhamento": "centro"},
        ]
        tabela = Tabela(pagina, tema, colunas, mostrar_busca=False, altura=12)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        linhas = []
        for faixa in faixas:
            linha = dict(faixa)
            linha["participacao_texto"] = f"{(int(faixa['valor'] or 0) / total * 100):.1f}%" if total else "0,0%"
            if faixa["faixa"] not in ("A vencer", "Vence hoje"):
                linha["_tag"] = "perigo" if "60" in faixa["faixa"] else "alerta"
            linhas.append(linha)
        tabela.carregar(linhas, resumo=f"{sum(f['quantidade'] for f in faixas)} título(s) em aberto")

        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Maiores devedores ({len(devedores)})")
        colunas = [
            {"chave": "cliente_nome", "rotulo": "Cliente", "largura": 250},
            {"chave": "quantidade", "rotulo": "Títulos", "largura": 80, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "total", "rotulo": "Valor total", "largura": 130, "tipo": "dinheiro"},
            {"chave": "saldo", "rotulo": "Saldo devedor", "largura": 130, "tipo": "dinheiro"},
            {"chave": "vencimento_texto", "rotulo": "Vencimento mais antigo", "largura": 160, "alinhamento": "centro"},
            {"chave": "dias_atraso", "rotulo": "Dias de atraso", "largura": 110, "tipo": "inteiro", "alinhamento": "centro"},
        ]
        tabela = Tabela(pagina, tema, colunas, mostrar_busca=False, altura=12)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        linhas = []
        for devedor in devedores:
            linha = dict(devedor)
            linha["vencimento_texto"] = formatar_data(devedor["vencimento_mais_antigo"])
            if int(devedor["dias_atraso"] or 0) > 30:
                linha["_tag"] = "perigo"
            elif int(devedor["dias_atraso"] or 0) > 0:
                linha["_tag"] = "alerta"
            linhas.append(linha)
        tabela.carregar(linhas)

        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))


class ContasReceberTela(TelaLista):
    titulo = "Contas a receber"
    descricao = "Fiado e crediário: receba títulos, conceda descontos, prorrogue vencimentos e acompanhe atrasos."
    permissao_editar = "contas_receber"
    permissao_excluir = "contas_receber"

    def __init__(self, mestre, ctx):
        self._status = tk.StringVar(value=OPCOES_STATUS[0][1])
        self._vencimento_ate = tk.StringVar(value="")
        self._cliente = tk.StringVar(value="")
        self._cliente_id: int | None = None
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "id", "rotulo": "Nº", "largura": 65, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "cliente_nome", "rotulo": "Cliente", "largura": 220},
                {"chave": "descricao", "rotulo": "Descrição", "largura": 250},
                {"chave": "origem", "rotulo": "Origem", "largura": 110, "alinhamento": "centro"},
                {"chave": "vencimento_texto", "rotulo": "Vencimento", "largura": 100, "alinhamento": "centro"},
                {"chave": "situacao_vencimento", "rotulo": "Prazo", "largura": 155},
                {"chave": "valor", "rotulo": "Valor", "largura": 110, "tipo": "dinheiro"},
                {"chave": "valor_pago", "rotulo": "Recebido", "largura": 110, "tipo": "dinheiro"},
                {"chave": "desconto", "rotulo": "Desconto", "largura": 100, "tipo": "dinheiro"},
                {"chave": "saldo", "rotulo": "Saldo", "largura": 110, "tipo": "dinheiro"},
                {"chave": "status_texto", "rotulo": "Situação", "largura": 95, "alinhamento": "centro"},
                {"chave": "qtd_recebimentos", "rotulo": "Receb.", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
            ],
            carregar_dados=self._dados,
            resumo=self._resumo,
            novo=self.novo_titulo,
            excluir=self._excluir,
            ao_duplo_clique=lambda linha: self.receber(linha),
            detalhes=self._detalhes,
            acoes=(
                ("💰 Receber", self.receber, "Primario.TButton", "F2"),
                ("✔ Quitar", self.quitar, "TButton", "F3"),
                ("📅 Prorrogar", self.prorrogar, "TButton", "F4"),
                ("🖨 Comprovante", self.imprimir_comprovante, "TButton", "F5"),
                ("✖ Cancelar título", self.cancelar, "TButton", "F6"),
                ("↩ Reabrir", self.reabrir, "TButton", "F7"),
                ("📊 Aging / devedores", self.ver_aging, "TButton", "F8"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Contas a receber",
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
        ttk.Button(pai, text="Hoje", command=self._vencendo_hoje).grid(row=0, column=4, sticky="w")
        ttk.Button(pai, text="+30 dias", command=self._vencendo_30).grid(row=0, column=5, sticky="w", padx=(4, 14))

        ttk.Label(pai, text="Cliente:", style="TLabel").grid(row=0, column=6, sticky="w")
        entrada_cliente = ttk.Entry(pai, textvariable=self._cliente, width=28)
        entrada_cliente.grid(row=0, column=7, sticky="ew", padx=(4, 6))
        entrada_cliente.bind("<Return>", lambda e: self.carregar())
        ttk.Button(pai, text="Selecionar...", command=self._escolher_cliente).grid(row=0, column=8, sticky="w")
        ttk.Button(pai, text="Limpar", command=self._limpar_cliente).grid(row=0, column=9, sticky="w", padx=(4, 0))
        pai.columnconfigure(7, weight=1)

    def _vencendo_hoje(self):
        self._vencimento_ate.set(formatar_data(hoje()))
        self.carregar()

    def _vencendo_30(self):
        self._vencimento_ate.set(formatar_data(somar_dias(hoje(), 30)))
        self.carregar()

    def _escolher_cliente(self):
        cliente = selecionar_cliente(self.ctx, "Filtrar títulos por cliente", incluir_inativos=True)
        if cliente:
            self._cliente_id = int(cliente["id"])
            self._cliente.set(cliente["nome"])
            self.carregar()

    def _limpar_cliente(self):
        self._cliente_id = None
        self._cliente.set("")
        self.carregar()

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.receber, "F3": self.quitar, "F4": self.prorrogar, "F5": self.imprimir_comprovante,
                 "F6": self.cancelar, "F7": self.reabrir, "F8": self.ver_aging}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    def atualizar_tema(self):
        super().atualizar_tema()

    # ------------------------------------------------------------------ dados
    def _status_selecionado(self) -> tuple[str, bool]:
        rotulo = self._status.get()
        for valor, texto in OPCOES_STATUS:
            if texto == rotulo:
                # "todas" inclui as canceladas (incluir_quitadas=True remove o filtro de status)
                return ("", True) if valor == "todas" else (valor, False)
        return ("pendentes", False)

    def _dados(self) -> list[dict]:
        status, incluir_quitadas = self._status_selecionado()
        contas = cr_mod.listar(
            self.banco,
            status=status,
            cliente_id=self._cliente_id,
            vencimento_ate=converter_data_br(self._vencimento_ate.get()) or "",
            texto=self._cliente.get().strip() if not self._cliente_id else "",
            incluir_quitadas=incluir_quitadas,
            limite=3000,
        )
        linhas = []
        for conta in contas:
            linha = dict(conta)
            status_conta = str(conta["status"] or "")
            linha["status_texto"] = ROTULOS_STATUS.get(status_conta, status_conta)
            linha["vencimento_texto"] = formatar_data(conta["vencimento"])
            linha["situacao_vencimento"] = texto_vencimento(conta["vencimento"], status_conta)
            linha["origem"] = f"Venda nº {int(conta['venda_id']):06d}" if conta["venda_id"] else "Manual"
            linha["valor"] = int(conta["valor"] or 0)
            linha["valor_pago"] = int(conta["valor_pago"] or 0)
            linha["desconto"] = int(conta["desconto"] or 0)
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
        return (f"{len(dados)} título(s) • {len(pendentes)} em aberto "
                f"({formatar_dinheiro(sum(d['saldo'] for d in pendentes))}) • "
                f"{len(vencidas)} vencido(s) ({formatar_dinheiro(sum(d['saldo'] for d in vencidas))}) • "
                f"recebido {formatar_dinheiro(sum(d['valor_pago'] for d in dados))}")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        conta = cr_mod.pegar(self.banco, linha["id"])
        if not conta:
            return []
        cliente = clientes_mod.pegar(self.banco, conta["cliente_id"]) if conta["cliente_id"] else None
        recebimentos = cr_mod.recebimentos(self.banco, int(conta["id"]))
        texto_recebimentos = "; ".join(
            f"{formatar_data(r['criado_em'], True)} {formatar_dinheiro(int(r['valor'] or 0))} ({r['forma']})"
            for r in recebimentos[-4:]
        )
        return [
            ("Título nº", f"{int(conta['id']):06d}"),
            ("Cliente", conta["cliente_nome"]),
            ("Telefone", formatar_telefone((cliente["celular"] or cliente["telefone"] or "")) if cliente else "—"),
            ("Saldo devedor do cliente", formatar_dinheiro(int(cliente["saldo_devedor"] or 0)) if cliente else "—"),
            ("Descrição", conta["descricao"]),
            ("Origem", linha["origem"]),
            ("Vencimento", formatar_data(conta["vencimento"])),
            ("Situação", linha["status_texto"] + f" — {linha['situacao_vencimento']}"),
            ("Valor", formatar_dinheiro(int(conta["valor"] or 0))),
            ("Recebido", formatar_dinheiro(int(conta["valor_pago"] or 0))),
            ("Desconto", formatar_dinheiro(int(conta["desconto"] or 0))),
            ("Saldo devedor", formatar_dinheiro(int(conta["saldo"] or 0))),
            ("Recebimentos", texto_recebimentos or "nenhum"),
            ("Criado em", formatar_data(conta["criado_em"], com_hora=True)),
            ("Atualizado em", formatar_data(conta["atualizado_em"], com_hora=True) if conta["atualizado_em"] else "—"),
        ]

    # ------------------------------------------------------------------ ações
    def _conta_selecionada(self) -> dict | None:
        linha = self.exigir_selecao()
        if not linha:
            return None
        conta = cr_mod.pegar(self.banco, linha["id"])
        if not conta:
            dialogs.erro(self, self.tema, "Título não encontrado (pode ter sido excluído).")
            self.carregar()
            return None
        return dict(conta)

    def receber(self, linha: dict | None = None):
        if linha is None:
            conta = self._conta_selecionada()
        else:
            conta = cr_mod.pegar(self.banco, linha["id"])
            conta = dict(conta) if conta else None
        if not conta:
            return
        if not self.exigir("contas_receber", "receber títulos"):
            return
        if conta["status"] == "cancelada":
            dialogs.alerta(self, self.tema, "Este título está cancelado. Reabra-o antes de receber.")
            return
        if conta["status"] == "paga":
            dialogs.alerta(self, self.tema, "Este título já está quitado.")
            return
        saldo = int(conta["saldo"] or 0)
        caixa_aberto = self.ctx.caixa_aberto
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Receber título nº {int(conta['id']):06d}",
            [
                {"chave": "valor", "rotulo": "Valor recebido", "tipo": "dinheiro", "largura": 14, "obrigatorio": True,
                 "dica": f"Saldo devedor: {formatar_dinheiro(saldo)}"},
                {"chave": "forma", "rotulo": "Forma de recebimento", "tipo": "lista", "largura": 22,
                 "opcoes": [(f, f) for f in formas_pagamento.PARA_RECEBIMENTOS]},
                {"chave": "desconto", "rotulo": "Desconto concedido", "tipo": "dinheiro", "largura": 14},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
                {"chave": "lancar_caixa", "rotulo": "Lançar no caixa do dia"
                 + ("" if caixa_aberto else " (nenhum caixa aberto)"), "tipo": "marcar",
                 "dica": "Somente dinheiro entra na gaveta; Pix e cartão entram como recebimento eletrônico."},
            ],
            {"valor": saldo, "forma": "Dinheiro", "desconto": 0, "lancar_caixa": bool(caixa_aberto)},
            largura=560,
            texto=f"{conta['cliente_nome']} — {conta['descricao']}\n"
                  f"Vencimento: {formatar_data(conta['vencimento'])} ({texto_vencimento(conta['vencimento'], conta['status'])})",
        )
        if not dados:
            return
        try:
            resultado = cr_mod.receber(
                self.banco, int(conta["id"]), int(dados["valor"] or 0),
                forma=dados.get("forma") or "Dinheiro", desconto=int(dados.get("desconto") or 0),
                observacao=(dados.get("observacao") or "").strip(), autor=self.usuario,
                lancar_no_caixa=bool(dados.get("lancar_caixa")),
            )
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc), "Recebimento não lançado")
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(conta["id"]))
        self.ctx.app.atualizar_caixa()
        if resultado["saldo"] <= 0:
            dialogs.sucesso(self, self.tema,
                            f"Título quitado!\n\nRecebido: {formatar_dinheiro(resultado['recebido'])}\n"
                            f"Desconto: {formatar_dinheiro(resultado['desconto'])}\n"
                            f"Cliente: {conta['cliente_nome']}")
        else:
            dialogs.info(self, self.tema,
                         f"Recebimento parcial lançado.\n\nRecebido: {formatar_dinheiro(resultado['recebido'])}\n"
                         f"Saldo devedor: {formatar_dinheiro(resultado['saldo'])}")

    def quitar(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cr_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_receber", "quitar títulos"):
            return
        if conta["status"] in ("paga", "cancelada"):
            dialogs.alerta(self, self.tema, "Este título já está quitado ou cancelado.")
            return
        saldo = int(conta["saldo"] or 0)
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Quitar título nº {int(conta['id']):06d}",
            [
                {"chave": "forma", "rotulo": "Forma de recebimento", "tipo": "lista", "largura": 22,
                 "opcoes": [(f, f) for f in formas_pagamento.PARA_RECEBIMENTOS]},
                {"chave": "desconto", "rotulo": "Desconto para quitação", "tipo": "dinheiro", "largura": 14},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
            ],
            {"forma": "Dinheiro", "desconto": 0}, largura=520,
            texto=f"{conta['cliente_nome']} — {conta['descricao']}\n"
                  f"Saldo devedor: {formatar_dinheiro(saldo)}",
        )
        if not dados:
            return
        try:
            resultado = cr_mod.quitar(self.banco, int(conta["id"]), forma=dados.get("forma") or "Dinheiro",
                                      desconto=int(dados.get("desconto") or 0),
                                      observacao=(dados.get("observacao") or "").strip(), autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc), "Quitação não lançada")
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(conta["id"]))
        self.ctx.app.atualizar_caixa()
        dialogs.sucesso(self, self.tema,
                        f"Título quitado.\n\nRecebido: {formatar_dinheiro(resultado['recebido'])}\n"
                        f"Desconto: {formatar_dinheiro(resultado['desconto'])}")

    def novo_titulo(self, _tela=None):
        if not self.exigir("contas_receber", "lançar contas a receber"):
            return
        cliente = selecionar_cliente(self.ctx, "Cliente do título")
        if not cliente:
            return
        if not int(cliente["ativo"] or 0):
            dialogs.alerta(self, self.tema, "Cliente desativado — reative-o antes de lançar títulos.")
            return
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Nova conta a receber — {cliente['nome']}",
            [
                {"chave": "descricao", "rotulo": "Descrição", "tipo": "texto", "largura": 34, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "valor", "rotulo": "Valor", "tipo": "dinheiro", "largura": 14, "obrigatorio": True},
                {"chave": "vencimento", "rotulo": "Vencimento", "tipo": "data", "largura": 12},
            ],
            {"vencimento": somar_dias(hoje(), 30)}, largura=520,
            texto=("Limite de crédito: "
                   + (formatar_dinheiro(int(cliente["limite_credito"] or 0)) if int(cliente["limite_credito"] or 0)
                      else "sem limite definido")
                   + f"\nSaldo devedor atual: {formatar_dinheiro(int(cliente['saldo_devedor'] or 0))}"),
        )
        if not dados:
            return
        try:
            conta_id = cr_mod.criar_manual(self.banco, int(cliente["id"]), dados["descricao"],
                                           int(dados["valor"] or 0), dados.get("vencimento") or "",
                                           autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", conta_id)
        dialogs.sucesso(self, self.tema,
                        f"Título nº {conta_id:06d} lançado para {cliente['nome']}.\n"
                        f"Valor: {formatar_dinheiro(int(dados['valor'] or 0))}")

    def prorrogar(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cr_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_receber", "prorrogar vencimentos"):
            return
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Prorrogar vencimento — {conta['cliente_nome']}",
            [{"chave": "vencimento", "rotulo": "Novo vencimento", "tipo": "data", "largura": 12, "obrigatorio": True}],
            {"vencimento": somar_dias(conta["vencimento"] or hoje(), 15)}, largura=420,
            texto=f"Título nº {int(conta['id']):06d} — {conta['descricao']}\n"
                  f"Vencimento atual: {formatar_data(conta['vencimento'])}\n"
                  f"Saldo devedor: {formatar_dinheiro(int(conta['saldo'] or 0))}",
        )
        if not dados:
            return
        try:
            nova_data = cr_mod.alterar_vencimento(self.banco, int(conta["id"]), dados["vencimento"],
                                                  autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(conta["id"]))
        dialogs.sucesso(self, self.tema, f"Vencimento prorrogado para {formatar_data(nova_data)}.")

    def imprimir_comprovante(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cr_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        try:
            caminho = impressao_mod.gerar_comprovante_recebimento_pdf(self.banco, int(conta["id"]))
        except impressao_mod.ErroImpressao as exc:
            dialogs.erro(self, self.tema, str(exc), "Comprovante")
            return
        imprimir_documento(self, self.tema, caminho,
                           f"Comprovante de recebimento nº {int(conta['id']):06d}")

    def cancelar(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cr_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_receber", "cancelar títulos"):
            return
        if conta["status"] == "cancelada":
            dialogs.alerta(self, self.tema, "Este título já está cancelado.")
            return
        motivo = dialogs.pedir_motivo(
            self, self.tema, "Cancelar título",
            f"Título nº {int(conta['id']):06d} — {conta['cliente_nome']}\n"
            f"Valor: {formatar_dinheiro(int(conta['valor'] or 0))} • Saldo: {formatar_dinheiro(int(conta['saldo'] or 0))}\n\n"
            "Descreva o motivo do cancelamento.",
            opcoes=MOTIVOS_CANCELAMENTO,
        )
        if not motivo:
            return
        try:
            cr_mod.cancelar(self.banco, int(conta["id"]), motivo=motivo, autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.info(self, self.tema, f"Título nº {int(conta['id']):06d} cancelado.")

    def reabrir(self, linha: dict | None = None):
        conta = self._conta_selecionada() if linha is None else dict(cr_mod.pegar(self.banco, linha["id"]) or {})
        if not conta:
            return
        if not self.exigir("contas_receber", "reabrir títulos"):
            return
        if conta["status"] != "cancelada":
            dialogs.alerta(self, self.tema, "Somente títulos cancelados podem ser reabertos.")
            return
        if not dialogs.confirmar(self, self.tema,
                                 f"Reabrir o título nº {int(conta['id']):06d} de {conta['cliente_nome']}?",
                                 "Reabrir título", "Reabrir", "Cancelar"):
            return
        try:
            cr_mod.reabrir(self.banco, int(conta["id"]), autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(conta["id"]))
        dialogs.sucesso(self, self.tema, "Título reaberto.")

    def _excluir(self, _tela, linha: dict):
        if not self.exigir("contas_receber", "excluir títulos"):
            return None
        if not dialogs.confirmar(self, self.tema,
                                 f"Excluir definitivamente o título nº {int(linha['id']):06d}?\n\n"
                                 f"{linha['cliente_nome']} — {formatar_dinheiro(int(linha['valor'] or 0))}",
                                 "Excluir título", "Excluir", "Cancelar"):
            return None
        try:
            cr_mod.excluir(self.banco, int(linha["id"]), autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.alerta(self, self.tema, str(exc), "Exclusão bloqueada")
            return None
        self.carregar()
        dialogs.sucesso(self, self.tema, "Título excluído.")
        return True

    def ver_aging(self):
        faixas = cr_mod.envelhecimento(self.banco)
        devedores = cr_mod.por_cliente(self.banco)
        DialogoAging(self.ctx.janela, self.tema, faixas, devedores).abrir()

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("cliente_id"):
            cliente = clientes_mod.pegar(self.banco, int(parametros["cliente_id"]))
            self._cliente_id = int(parametros["cliente_id"])
            self._cliente.set(cliente["nome"] if cliente else "")
            self.carregar()
        if parametros.get("status"):
            for valor, rotulo in OPCOES_STATUS:
                if valor == str(parametros["status"]):
                    self._status.set(rotulo)
                    break
            self.carregar()
        if parametros.get("conta_id"):
            self.tabela.selecionar_por("id", int(parametros["conta_id"]))
