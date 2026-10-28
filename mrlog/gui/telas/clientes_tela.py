"""
Tela de **Clientes** — cadastro completo + visão financeira (fiado, limite, compras).

Recursos:
- busca por nome, CPF/CNPJ, telefone, cidade e e-mail (campo de busca da grade);
- filtros rápidos: somente devedores / incluir inativos;
- ficha do cliente com extrato de fiado e histórico de compras;
- atalho para abrir uma venda no PDV já com o cliente identificado;
- lançamento manual de conta a receber (fiado avulso).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ... import clientes as clientes_mod
from ... import contas_receber as cr_mod
from ...utils import (
    dias_entre,
    formatar_cpf_cnpj,
    formatar_data,
    formatar_dinheiro,
    formatar_telefone,
    hoje,
    somar_dias,
)
from .. import dialogs
from ..widgets import Tabela
from . import TelaLista


class DialogoExtrato(dialogs.Modal):
    """Ficha financeira do cliente: títulos em aberto, quitados e últimas compras."""

    def __init__(self, mestre, tema, extrato: dict, compras: list):
        cliente = extrato["cliente"]
        super().__init__(mestre, tema, f"Ficha do cliente — {cliente['nome']}", largura=900, altura=640)
        self.extrato = extrato

        resumo = ttk.Frame(self.corpo, style="TFrame")
        resumo.pack(fill="x", pady=(0, 6))
        cartoes = [
            ("Saldo devedor", formatar_dinheiro(extrato["total_aberto"]), tema.cor("perigo")),
            ("Em atraso", formatar_dinheiro(extrato["total_vencido"]), tema.cor("alerta")),
            ("Limite de crédito", formatar_dinheiro(extrato["limite"]) if extrato["limite"] else "Sem limite",
             tema.cor("info")),
            ("Crédito disponível", formatar_dinheiro(extrato["credito_disponivel"]) if extrato["limite"] else "—",
             tema.cor("sucesso")),
        ]
        for indice, (rotulo, valor, cor) in enumerate(cartoes):
            quadro = tk.Frame(resumo, background=tema.cor("bg_alt"), highlightbackground=tema.cor("borda"),
                              highlightthickness=1)
            quadro.grid(row=0, column=indice, sticky="nsew", padx=(0, 8))
            resumo.columnconfigure(indice, weight=1)
            tk.Label(quadro, text=rotulo, background=tema.cor("bg_alt"), foreground=tema.cor("fg_suave"),
                     font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(6, 0))
            tk.Label(quadro, text=valor, background=tema.cor("bg_alt"), foreground=cor,
                     font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=10, pady=(0, 6))

        abas = ttk.Notebook(self.corpo, style="TNotebook")
        abas.pack(fill="both", expand=True)

        colunas_contas = [
            {"chave": "descricao", "rotulo": "Descrição", "largura": 260},
            {"chave": "vencimento", "rotulo": "Vencimento", "largura": 100, "alinhamento": "centro"},
            {"chave": "valor", "rotulo": "Valor", "largura": 110, "tipo": "dinheiro"},
            {"chave": "valor_pago", "rotulo": "Pago", "largura": 100, "tipo": "dinheiro"},
            {"chave": "saldo", "rotulo": "Saldo", "largura": 110, "tipo": "dinheiro"},
            {"chave": "status", "rotulo": "Situação", "largura": 90, "alinhamento": "centro"},
            {"chave": "atraso_texto", "rotulo": "Atraso", "largura": 90, "alinhamento": "centro"},
        ]
        for titulo, dados in (("Títulos em aberto", extrato["abertas"]), ("Títulos quitados/cancelados", extrato["quitadas"])):
            pagina = ttk.Frame(abas, style="TFrame")
            abas.add(pagina, text=f"{titulo} ({len(dados)})")
            tabela = Tabela(pagina, tema, colunas_contas, mostrar_busca=False, altura=10)
            tabela.pack(fill="both", expand=True, padx=6, pady=6)
            linhas = []
            for conta in dados:
                linha = dict(conta)
                atraso = dias_entre(linha.get("vencimento")) if linha.get("vencimento") else 0
                linha["atraso_texto"] = f"{abs(atraso)} dia(s)" if atraso < 0 else "em dia"
                if linha.get("status") in ("vencida",) or atraso < 0:
                    linha["_tag"] = "perigo"
                elif linha.get("status") == "paga":
                    linha["_tag"] = "sucesso"
                elif linha.get("status") == "cancelada":
                    linha["_tag"] = "neutro"
                linhas.append(linha)
            tabela.carregar(linhas)

        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Últimas compras ({len(compras)})")
        colunas_compras = [
            {"chave": "numero", "rotulo": "Cupom", "largura": 80, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "data_texto", "rotulo": "Data", "largura": 150},
            {"chave": "vendedor_nome", "rotulo": "Vendedor", "largura": 180},
            {"chave": "itens", "rotulo": "Itens", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "total", "rotulo": "Total", "largura": 120, "tipo": "dinheiro"},
            {"chave": "status", "rotulo": "Situação", "largura": 150},
        ]
        tabela = Tabela(pagina, tema, colunas_compras, mostrar_busca=False, altura=10)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        linhas = []
        for venda in compras:
            linha = dict(venda)
            linha["data_texto"] = formatar_data(linha.get("criada_em"), com_hora=True)
            if linha.get("status") == "cancelada":
                linha["_tag"] = "neutro"
            elif linha.get("status") == "devolvida":
                linha["_tag"] = "alerta"
            linhas.append(linha)
        tabela.carregar(linhas)

        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))


class ClientesTela(TelaLista):
    titulo = "Clientes"
    descricao = "Cadastro de clientes, limite de crédito (fiado) e histórico de compras."
    permissao_editar = "clientes"
    permissao_excluir = "clientes"

    def __init__(self, mestre, ctx):
        self._apenas_devedores = tk.BooleanVar(value=False)
        self._incluir_inativos = tk.BooleanVar(value=False)
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "nome", "rotulo": "Nome", "largura": 250},
                {"chave": "tipo", "rotulo": "Tipo", "largura": 80, "alinhamento": "centro"},
                {"chave": "documento_texto", "rotulo": "CPF/CNPJ", "largura": 150},
                {"chave": "telefone_texto", "rotulo": "Contato", "largura": 130},
                {"chave": "cidade_texto", "rotulo": "Cidade/UF", "largura": 150},
                {"chave": "limite_credito", "rotulo": "Limite", "largura": 100, "tipo": "dinheiro"},
                {"chave": "saldo_devedor", "rotulo": "Saldo devedor", "largura": 110, "tipo": "dinheiro"},
                {"chave": "contas_abertas", "rotulo": "Títulos", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "total_compras", "rotulo": "Total comprado", "largura": 120, "tipo": "dinheiro"},
                {"chave": "qtd_compras", "rotulo": "Compras", "largura": 80, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "ultima_compra_texto", "rotulo": "Última compra", "largura": 110, "alinhamento": "centro"},
                {"chave": "situacao", "rotulo": "Situação", "largura": 90, "alinhamento": "centro"},
            ],
            carregar_dados=self._dados,
            resumo=self._resumo,
            novo=self._novo,
            editar=self._editar,
            excluir=self._excluir,
            ao_duplo_clique=lambda linha: self.editar(linha=linha),
            detalhes=self._detalhes,
            acoes=(
                ("🛒 Nova venda", self.nova_venda, "Primario.TButton", "F2"),
                ("💰 Lançar fiado", self.lancar_fiado, "TButton", "F3"),
                ("📒 Ficha / extrato", self.abrir_extrato, "TButton", "F4"),
                ("⏻ Desativar / Reativar", self.alternar_status, "TButton", "F5"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Clientes",
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        for texto, variavel in (("Somente devedores", self._apenas_devedores),
                                ("Incluir inativos", self._incluir_inativos)):
            tk.Checkbutton(
                pai, text=texto, variable=variavel, command=self.carregar,
                background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                selectcolor=self.tema.cor("bg_input"), highlightthickness=0,
            ).pack(side="left", padx=(0, 16))
        ttk.Label(pai, text="Dica: duplo clique abre a ficha de edição.", style="Suave.TLabel").pack(side="right")

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.nova_venda, "F3": self.lancar_fiado, "F4": self.abrir_extrato,
                 "F5": self.alternar_status}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    def atualizar_tema(self):
        super().atualizar_tema()
        self._reestilizar_filtros()

    def _reestilizar_filtros(self):
        for filho in self.quadro_filtros.winfo_children():
            if isinstance(filho, tk.Checkbutton):
                filho.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                                selectcolor=self.tema.cor("bg_input"))

    # ------------------------------------------------------------------ dados
    def _dados(self) -> list[dict]:
        clientes = clientes_mod.listar(
            self.banco,
            incluir_inativos=bool(self._incluir_inativos.get()),
            apenas_devedores=bool(self._apenas_devedores.get()),
        )
        linhas = []
        for cliente in clientes:
            linha = dict(cliente)
            linha["documento_texto"] = formatar_cpf_cnpj(cliente["cpf_cnpj"] or "")
            linha["telefone_texto"] = formatar_telefone(cliente["celular"] or cliente["telefone"] or "")
            linha["cidade_texto"] = " / ".join(p for p in (cliente["cidade"] or "", cliente["uf"] or "") if p)
            linha["ultima_compra_texto"] = formatar_data(cliente["ultima_compra"]) if cliente["ultima_compra"] else "—"
            linha["saldo_devedor"] = int(cliente["saldo_devedor"] or 0)
            linha["limite_credito"] = int(cliente["limite_credito"] or 0)
            linha["total_compras"] = int(cliente["total_compras"] or 0)
            ativo = int(cliente["ativo"] or 0)
            linha["situacao"] = "Ativo" if ativo else "Inativo"
            linhas.append(linha)
        return linhas

    def _tag_linha(self, linha: dict) -> str:
        if not int(linha.get("ativo") or 0):
            return "neutro"
        saldo = int(linha.get("saldo_devedor") or 0)
        limite = int(linha.get("limite_credito") or 0)
        if saldo > 0 and limite > 0 and saldo >= limite:
            return "perigo"          # estourou o limite de crédito
        if saldo > 0:
            return "alerta"          # tem fiado em aberto
        return ""

    def _resumo(self, dados) -> str:
        devedores = sum(1 for d in dados if int(d["saldo_devedor"] or 0) > 0)
        saldo = sum(int(d["saldo_devedor"] or 0) for d in dados)
        return (f"{len(dados)} cliente(s) • {devedores} com saldo em aberto • "
                f"total a receber {formatar_dinheiro(saldo)}")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        cliente = clientes_mod.pegar(self.banco, linha["id"])
        if not cliente:
            return []
        credito = clientes_mod.credito_disponivel(cliente)
        return [
            ("Código", cliente["id"]),
            ("Tipo", cliente["tipo"]),
            ("CPF/CNPJ", formatar_cpf_cnpj(cliente["cpf_cnpj"] or "") or "—"),
            ("RG/Inscrição", cliente["rg_inscricao"]),
            ("Contato", cliente["contato"]),
            ("Telefone", formatar_telefone(cliente["telefone"] or "") or "—"),
            ("Celular", formatar_telefone(cliente["celular"] or "") or "—"),
            ("E-mail", cliente["email"]),
            ("Endereço", clientes_mod.endereco_completo(cliente) or "—"),
            ("Nascimento", formatar_data(cliente["nascimento"]) if cliente["nascimento"] else "—"),
            ("Limite de crédito", formatar_dinheiro(cliente["limite_credito"]) if cliente["limite_credito"] else "Sem limite"),
            ("Crédito disponível", formatar_dinheiro(credito) if cliente["limite_credito"] else "—"),
            ("Saldo devedor", formatar_dinheiro(cliente["saldo_devedor"])),
            ("Observação", cliente["observacao"]),
        ]

    # ------------------------------------------------------------------ formulário
    def _formulario(self, cliente):
        editando = cliente is not None
        valores: dict[str, Any] = {}
        if editando:
            valores = {chave: (cliente[chave] if cliente[chave] is not None else "") for chave in (
                "nome", "tipo", "cpf_cnpj", "rg_inscricao", "contato", "telefone", "celular", "email",
                "endereco", "numero", "bairro", "cidade", "uf", "cep", "observacao")}
            valores["nascimento"] = formatar_data(cliente["nascimento"]) if cliente["nascimento"] else ""
            valores["limite_credito"] = int(cliente["limite_credito"] or 0)
            valores["ativo"] = int(cliente["ativo"] or 0)
        else:
            valores = {"tipo": "Física", "ativo": 1, "uf": ""}

        secoes = [
            ("Identificação", [
                {"chave": "nome", "rotulo": "Nome / Razão social", "tipo": "texto", "largura": 34, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "tipo", "rotulo": "Tipo de pessoa", "tipo": "lista", "largura": 18,
                 "opcoes": [("Física", "Física (CPF)"), ("Jurídica", "Jurídica (CNPJ)")]},
                {"chave": "cpf_cnpj", "rotulo": "CPF / CNPJ", "tipo": "texto", "largura": 20, "mascara": "documento",
                 "dica": "11 dígitos (CPF) ou 14 (CNPJ)"},
                {"chave": "rg_inscricao", "rotulo": "RG / Inscrição estadual", "tipo": "texto", "largura": 20},
                {"chave": "contato", "rotulo": "Pessoa de contato", "tipo": "texto", "largura": 26},
            ]),
            ("Contato", [
                {"chave": "telefone", "rotulo": "Telefone", "tipo": "texto", "largura": 18, "mascara": "telefone"},
                {"chave": "celular", "rotulo": "Celular / WhatsApp", "tipo": "texto", "largura": 18,
                 "mascara": "telefone"},
                {"chave": "email", "rotulo": "E-mail", "tipo": "texto", "largura": 30},
            ]),
            ("Endereço", [
                {"chave": "endereco", "rotulo": "Logradouro", "tipo": "texto", "largura": 34, "colunas": 2},
                {"chave": "numero", "rotulo": "Número", "tipo": "texto", "largura": 10},
                {"chave": "bairro", "rotulo": "Bairro", "tipo": "texto", "largura": 22},
                {"chave": "cidade", "rotulo": "Cidade", "tipo": "texto", "largura": 22},
                {"chave": "uf", "rotulo": "UF", "tipo": "texto", "largura": 6, "maiusculas": True},
                {"chave": "cep", "rotulo": "CEP", "tipo": "texto", "largura": 12},
            ]),
            ("Crédito e outros", [
                {"chave": "limite_credito", "rotulo": "Limite de crédito (fiado)", "tipo": "dinheiro", "largura": 14,
                 "dica": "0 = sem limite definido"},
                {"chave": "nascimento", "rotulo": "Data de nascimento", "tipo": "texto", "largura": 14,
                 "dica": "DD/MM/AAAA"},
                {"chave": "ativo", "rotulo": "Cliente ativo", "tipo": "marcar"},
                {"chave": "observacao", "rotulo": "Observações", "tipo": "texto", "largura": 34, "multilinea": True,
                 "altura": 3, "colunas": 3},
            ]),
        ]

        dialogo = dialogs.DialogoFormulario(
            self.ctx.janela, self.tema,
            "Editar cliente" if editando else "Novo cliente",
            secoes, valores, largura=780, altura=640,
            validar=self._validar_formulario,
        )
        resultado = dialogo.abrir()
        if resultado is None:
            return
        self._salvar(cliente, resultado)

    @staticmethod
    def _validar_formulario(dados: dict) -> str:
        nome = str(dados.get("nome") or "").strip()
        if len(nome) < 2:
            return "Informe o nome do cliente (mínimo 2 letras)."
        if dados.get("email") and "@" not in str(dados["email"]):
            return "E-mail inválido."
        return ""

    def _novos_dados(self, dados: dict) -> dict:
        return {
            "nome": dados.get("nome") or "",
            "tipo": dados.get("tipo") or "Física",
            "cpf_cnpj": dados.get("cpf_cnpj") or "",
            "rg_inscricao": dados.get("rg_inscricao") or "",
            "contato": dados.get("contato") or "",
            "telefone": dados.get("telefone") or "",
            "celular": dados.get("celular") or "",
            "email": dados.get("email") or "",
            "endereco": dados.get("endereco") or "",
            "numero": dados.get("numero") or "",
            "bairro": dados.get("bairro") or "",
            "cidade": dados.get("cidade") or "",
            "uf": dados.get("uf") or "",
            "cep": dados.get("cep") or "",
            "nascimento": dados.get("nascimento") or "",
            "limite_credito": int(dados.get("limite_credito") or 0),
            "observacao": dados.get("observacao") or "",
            "ativo": int(bool(dados.get("ativo", 1))),
        }

    def _salvar(self, cliente, dados: dict):
        registro = self._novos_dados(dados)
        try:
            if cliente is None:
                similares = clientes_mod.nomes_similares(self.banco, registro["nome"])
                if similares and dialogs.confirmar(
                        self, self.tema,
                        "Já existem clientes com nome parecido:\n\n" + "\n".join(f"• {n}" for n in similares) +
                        "\n\nCadastrar mesmo assim?", "Possível duplicado", "Cadastrar", "Cancelar"):
                    pass
                elif similares:
                    return
                cliente_id = clientes_mod.criar(self.banco, registro, autor=self.usuario)
                dialogs.sucesso(self, self.tema, f"Cliente “{registro['nome']}” cadastrado.")
            else:
                cliente_id = clientes_mod.atualizar(self.banco, int(cliente["id"]), registro, autor=self.usuario)
                dialogs.sucesso(self, self.tema, "Cliente atualizado.")
        except clientes_mod.ErroCliente as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", cliente_id)
        return cliente_id

    def _novo(self, _tela=None):
        self._formulario(None)

    def _editar(self, _tela=None, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        cliente = clientes_mod.pegar(self.banco, linha["id"])
        if not cliente:
            dialogs.erro(self, self.tema, "Cliente não encontrado (pode ter sido excluído).")
            self.carregar()
            return
        self._formulario(cliente)

    def _excluir(self, _tela, linha: dict):
        """Exclusão definitiva só para clientes sem histórico; caso contrário, desativa."""
        tem_historico = (int(linha.get("qtd_compras") or 0) > 0 or int(linha.get("contas_abertas") or 0) > 0
                         or int(linha.get("total_compras") or 0) > 0)
        if tem_historico:
            dialogs.alerta(
                self, self.tema,
                f"O cliente “{linha['nome']}” possui compras e/ou títulos no fiado.\n\n"
                "Para manter o histórico e os relatórios corretos ele não pode ser excluído.\n"
                "Use **Desativar / Reativar** (F5) para escondê-lo das listas.",
                "Exclusão bloqueada",
            )
            return None
        if not dialogs.confirmar(self, self.tema, f"Excluir definitivamente o cliente “{linha['nome']}”?",
                                 "Excluir cliente", "Excluir", "Cancelar"):
            return None
        try:
            clientes_mod.excluir(self.banco, int(linha["id"]), autor=self.usuario)
        except clientes_mod.ErroCliente as exc:
            dialogs.alerta(self, self.tema, str(exc), "Exclusão bloqueada")
            return None
        self.carregar()
        dialogs.sucesso(self, self.tema, "Cliente excluído.")
        return True

    # ------------------------------------------------------------------ ações
    def alternar_status(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        ativo = int(linha["ativo"] or 0)
        try:
            if ativo:
                if int(linha.get("saldo_devedor") or 0) > 0:
                    dialogs.alerta(
                        self, self.tema,
                        f"“{linha['nome']}” ainda deve {formatar_dinheiro(int(linha['saldo_devedor']))} "
                        f"em {int(linha.get('contas_abertas') or 0)} título(s).\n\n"
                        "Receba ou cancele as pendências em **Contas a receber** antes de desativar.",
                        "Desativação bloqueada",
                    )
                    return
                if not dialogs.confirmar(self, self.tema,
                                         f"Desativar o cliente “{linha['nome']}”?\n\n"
                                         "Ele deixará de aparecer nas vendas e cadastros, mas o histórico é mantido.",
                                         "Desativar cliente", "Desativar", "Cancelar"):
                    return
                clientes_mod.desativar(self.banco, int(linha["id"]), autor=self.usuario)
                dialogs.info(self, self.tema, "Cliente desativado — não aparece mais nas listas de venda.")
            else:
                clientes_mod.reativar(self.banco, int(linha["id"]), autor=self.usuario)
                dialogs.sucesso(self, self.tema, f"Cliente “{linha['nome']}” reativado.")
        except clientes_mod.ErroCliente as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()

    def nova_venda(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        if not int(linha["ativo"] or 0):
            dialogs.alerta(self, self.tema, "Cliente desativado — reative-o antes de vender.")
            return
        self.ctx.navegar("pdv", {"cliente_id": int(linha["id"])})

    def lancar_fiado(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        if not int(linha["ativo"] or 0):
            dialogs.alerta(self, self.tema, "Cliente desativado — reative-o antes de lançar contas.")
            return
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Lançar fiado — {linha['nome']}",
            [
                {"chave": "descricao", "rotulo": "Descrição", "tipo": "texto", "largura": 34, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "valor", "rotulo": "Valor", "tipo": "dinheiro", "largura": 14, "obrigatorio": True},
                {"chave": "vencimento", "rotulo": "Vencimento", "tipo": "texto", "largura": 12,
                 "dica": "DD/MM/AAAA"},
            ],
            {"vencimento": formatar_data(somar_dias(hoje(), 30))},
            largura=520,
            texto="Lançamento avulso de conta a receber (não altera o estoque nem o caixa).",
        )
        if not dados:
            return
        try:
            conta_id = cr_mod.criar_manual(self.banco, int(linha["id"]), dados["descricao"], dados["valor"],
                                           dados.get("vencimento") or "", autor=self.usuario)
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Conta a receber lançada (nº {conta_id}).\n"
                        f"Cliente: {linha['nome']}\nValor: {formatar_dinheiro(int(dados['valor']))}")
        self.tabela.selecionar_por("id", int(linha["id"]))

    def abrir_extrato(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        try:
            cr_mod.atualizar_vencidas(self.banco)
            extrato = cr_mod.extrato_cliente(self.banco, int(linha["id"]))
        except cr_mod.ErroContaReceber as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        compras = clientes_mod.compras_do_cliente(self.banco, int(linha["id"]), limite=100)
        DialogoExtrato(self.ctx.janela, self.tema, extrato, compras).abrir()

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("apenas_devedores") is not None:
            self._apenas_devedores.set(bool(parametros["apenas_devedores"]))
            self.carregar()
        if parametros.get("cliente_id"):
            self.tabela.selecionar_por("id", int(parametros["cliente_id"]))


# --------------------------------------------------------------------------------------
# Helper reutilizável (contas a receber, PDV, vendas...)
# --------------------------------------------------------------------------------------


def selecionar_cliente(ctx, titulo: str = "Selecionar cliente", texto: str = "",
                       incluir_inativos: bool = False):
    """Abre a busca de clientes e devolve a linha completa (ou ``None``)."""
    colunas = [
        {"chave": "nome", "rotulo": "Cliente", "largura": 250},
        {"chave": "documento_texto", "rotulo": "CPF/CNPJ", "largura": 150},
        {"chave": "telefone_texto", "rotulo": "Telefone", "largura": 130},
        {"chave": "cidade_texto", "rotulo": "Cidade", "largura": 130},
        {"chave": "saldo_devedor", "rotulo": "Saldo devedor", "largura": 120, "tipo": "dinheiro"},
        {"chave": "limite_credito", "rotulo": "Limite", "largura": 110, "tipo": "dinheiro"},
    ]

    def buscar(termo: str):
        linhas = []
        for cliente in clientes_mod.listar(ctx.banco, incluir_inativos=incluir_inativos, filtro=termo):
            linha = dict(cliente)
            linha["documento_texto"] = formatar_cpf_cnpj(cliente["cpf_cnpj"] or "")
            linha["telefone_texto"] = formatar_telefone(cliente["celular"] or cliente["telefone"] or "")
            linha["cidade_texto"] = cliente["cidade"] or ""
            linhas.append(linha)
        return linhas

    linha = dialogs.selecionar_registro(
        ctx.janela, ctx.tema, titulo, colunas, buscar(""), ao_buscar=buscar, largura=860,
        texto=texto or "Digite o nome, CPF/CNPJ ou telefone e clique duas vezes para selecionar.",
    )
    if not linha:
        return None
    return clientes_mod.pegar(ctx.banco, linha["id"])
