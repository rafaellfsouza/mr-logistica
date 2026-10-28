"""
Tela de **Fornecedores** — cadastro, produtos vinculados e saldo a pagar.

Recursos:
- busca por nome, razão social, CNPJ/CPF, cidade, contato, e-mail e telefones;
- filtros rápidos: somente com saldo em aberto / incluir inativos;
- ficha do fornecedor com produtos e contas a pagar;
- lançamento rápido de conta a pagar já vinculada ao fornecedor;
- atalho para a tela de Produtos filtrada pelo fornecedor.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ... import contas_pagar as cp_mod
from ... import fornecedores as fornecedores_mod
from ...esquema import CATEGORIAS_DESPESA
from ...utils import (
    formatar_cpf_cnpj,
    formatar_data,
    formatar_dinheiro,
    formatar_quantidade,
    formatar_telefone,
    hoje,
    somar_dias,
)
from .. import dialogs
from ..widgets import Tabela
from . import TelaLista


class DialogoFichaFornecedor(dialogs.Modal):
    """Ficha do fornecedor: indicadores, produtos vinculados e contas a pagar."""

    def __init__(self, mestre, tema, fornecedor, produtos: list, contas: list):
        super().__init__(mestre, tema, f"Ficha do fornecedor — {fornecedor['nome']}", largura=920, altura=640)

        saldo_aberto = int(fornecedor["saldo_aberto"] or 0)
        cartoes = [
            ("Saldo a pagar", formatar_dinheiro(saldo_aberto), tema.cor("perigo") if saldo_aberto else tema.cor("sucesso")),
            ("Total já pago", formatar_dinheiro(int(fornecedor["total_pago"] or 0)), tema.cor("info")),
            ("Total comprado (entradas)", formatar_dinheiro(int(fornecedor["total_comprado"] or 0)), tema.cor("primaria")),
            ("Prazo médio", f"{int(fornecedor['prazo_dias'] or 0)} dia(s)", tema.cor("fg")),
            ("Produtos vinculados", str(len(produtos)), tema.cor("fg")),
        ]
        quadro_cartoes = ttk.Frame(self.corpo, style="TFrame")
        quadro_cartoes.pack(fill="x", pady=(0, 8))
        for indice, (rotulo, valor, cor) in enumerate(cartoes):
            cartao = tk.Frame(quadro_cartoes, background=tema.cor("bg_alt"),
                              highlightbackground=tema.cor("borda"), highlightthickness=1)
            cartao.grid(row=0, column=indice, sticky="nsew", padx=(0, 8))
            quadro_cartoes.columnconfigure(indice, weight=1)
            tk.Label(cartao, text=rotulo, background=tema.cor("bg_alt"), foreground=tema.cor("fg_suave"),
                     font=("Segoe UI", 9), wraplength=150, justify="left").pack(anchor="w", padx=8, pady=(6, 0))
            tk.Label(cartao, text=valor, background=tema.cor("bg_alt"), foreground=cor,
                     font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=8, pady=(0, 6))

        abas = ttk.Notebook(self.corpo, style="TNotebook")
        abas.pack(fill="both", expand=True)

        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Produtos ({len(produtos)})")
        colunas_produtos = [
            {"chave": "codigo", "rotulo": "Código", "largura": 90},
            {"chave": "nome", "rotulo": "Produto", "largura": 260},
            {"chave": "codigo_barras", "rotulo": "Cód. barras", "largura": 130},
            {"chave": "estoque_atual", "rotulo": "Estoque", "largura": 90, "alinhamento": "centro"},
            {"chave": "unidade_base", "rotulo": "Un.", "largura": 50, "alinhamento": "centro"},
            {"chave": "preco_custo", "rotulo": "Custo", "largura": 100, "tipo": "dinheiro"},
            {"chave": "preco_venda", "rotulo": "Venda", "largura": 100, "tipo": "dinheiro"},
            {"chave": "margem_texto", "rotulo": "Margem", "largura": 80, "alinhamento": "centro"},
        ]
        tabela = Tabela(pagina, tema, colunas_produtos, mostrar_busca=True, altura=12)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        linhas = []
        for produto in produtos:
            linha = dict(produto)
            linha["estoque_atual"] = formatar_quantidade(produto["estoque_atual"])
            custo, venda = int(produto["preco_custo"] or 0), int(produto["preco_venda"] or 0)
            linha["margem_texto"] = f"{(venda - custo) / custo * 100:.1f}%" if custo > 0 else "—"
            if not int(produto["ativo"] or 0):
                linha["_tag"] = "neutro"
            linhas.append(linha)
        tabela.carregar(linhas)

        pagina = ttk.Frame(abas, style="TFrame")
        abas.add(pagina, text=f"Contas a pagar ({len(contas)})")
        colunas_contas = [
            {"chave": "descricao", "rotulo": "Descrição", "largura": 240},
            {"chave": "categoria", "rotulo": "Categoria", "largura": 140},
            {"chave": "vencimento", "rotulo": "Vencimento", "largura": 100, "alinhamento": "centro"},
            {"chave": "valor", "rotulo": "Valor", "largura": 110, "tipo": "dinheiro"},
            {"chave": "valor_pago", "rotulo": "Pago", "largura": 100, "tipo": "dinheiro"},
            {"chave": "saldo", "rotulo": "Saldo", "largura": 110, "tipo": "dinheiro"},
            {"chave": "status", "rotulo": "Situação", "largura": 90, "alinhamento": "centro"},
            {"chave": "atraso_texto", "rotulo": "Atraso", "largura": 90, "alinhamento": "centro"},
        ]
        tabela = Tabela(pagina, tema, colunas_contas, mostrar_busca=True, altura=12)
        tabela.pack(fill="both", expand=True, padx=6, pady=6)
        linhas = []
        for conta in contas:
            linha = dict(conta)
            atraso = int(conta["dias_atraso"] or 0)
            pendente = conta["status"] in ("aberta", "parcial", "vencida")
            linha["atraso_texto"] = (f"{atraso} dia(s)" if atraso > 0 else "em dia") if pendente else "—"
            if conta["status"] == "paga":
                linha["_tag"] = "sucesso"
            elif conta["status"] == "cancelada":
                linha["_tag"] = "neutro"
            elif atraso > 0:
                linha["_tag"] = "perigo"
            linhas.append(linha)
        tabela.carregar(linhas)

        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))


class FornecedoresTela(TelaLista):
    titulo = "Fornecedores"
    descricao = "Cadastro de fornecedores, produtos vinculados e contas a pagar."
    permissao_editar = "fornecedores"
    permissao_excluir = "fornecedores"

    def __init__(self, mestre, ctx):
        self._apenas_com_saldo = tk.BooleanVar(value=False)
        self._incluir_inativos = tk.BooleanVar(value=False)
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "nome", "rotulo": "Nome fantasia", "largura": 220},
                {"chave": "razao_social", "rotulo": "Razão social", "largura": 220},
                {"chave": "documento_texto", "rotulo": "CNPJ/CPF", "largura": 150},
                {"chave": "contato_texto", "rotulo": "Contato", "largura": 170},
                {"chave": "cidade_texto", "rotulo": "Cidade/UF", "largura": 140},
                {"chave": "prazo_dias", "rotulo": "Prazo (dias)", "largura": 95, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "qtd_produtos", "rotulo": "Produtos", "largura": 85, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "saldo_aberto", "rotulo": "A pagar", "largura": 110, "tipo": "dinheiro"},
                {"chave": "total_pago", "rotulo": "Já pago", "largura": 110, "tipo": "dinheiro"},
                {"chave": "total_comprado", "rotulo": "Total comprado", "largura": 120, "tipo": "dinheiro"},
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
                ("📦 Produtos", self.ver_produtos, "TButton", "F2"),
                ("💳 Lançar conta a pagar", self.lancar_conta, "TButton", "F3"),
                ("📒 Ficha do fornecedor", self.abrir_ficha, "TButton", "F4"),
                ("⏻ Desativar / Reativar", self.alternar_status, "TButton", "F5"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Fornecedores",
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        for texto, variavel in (("Somente com saldo a pagar", self._apenas_com_saldo),
                                ("Incluir inativos", self._incluir_inativos)):
            tk.Checkbutton(
                pai, text=texto, variable=variavel, command=self.carregar,
                background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                selectcolor=self.tema.cor("bg_input"), highlightthickness=0,
            ).pack(side="left", padx=(0, 16))

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.ver_produtos, "F3": self.lancar_conta, "F4": self.abrir_ficha,
                 "F5": self.alternar_status}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    def atualizar_tema(self):
        super().atualizar_tema()
        for filho in getattr(self, "quadro_filtros", ()).winfo_children():
            if isinstance(filho, tk.Checkbutton):
                filho.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                                selectcolor=self.tema.cor("bg_input"))

    # ------------------------------------------------------------------ dados
    def _dados(self) -> list[dict]:
        fornecedores = fornecedores_mod.listar(
            self.banco,
            incluir_inativos=bool(self._incluir_inativos.get()),
            apenas_com_saldo=bool(self._apenas_com_saldo.get()),
        )
        linhas = []
        for fornecedor in fornecedores:
            linha = dict(fornecedor)
            linha["documento_texto"] = formatar_cpf_cnpj(fornecedor["cnpj_cpf"] or "")
            contatos = [p for p in (fornecedor["contato"] or "",
                                    formatar_telefone(fornecedor["telefone"] or ""),
                                    formatar_telefone(fornecedor["celular"] or "")) if p]
            linha["contato_texto"] = " • ".join(contatos) if contatos else "—"
            linha["cidade_texto"] = " / ".join(p for p in (fornecedor["cidade"] or "", fornecedor["uf"] or "") if p)
            for chave in ("saldo_aberto", "total_pago", "total_comprado"):
                linha[chave] = int(fornecedor[chave] or 0)
            ativo = int(fornecedor["ativo"] or 0)
            linha["situacao"] = "Ativo" if ativo else "Inativo"
            linhas.append(linha)
        return linhas

    def _tag_linha(self, linha: dict) -> str:
        if not int(linha.get("ativo") or 0):
            return "neutro"
        if int(linha.get("saldo_aberto") or 0) > 0:
            return "alerta"
        return ""

    def _resumo(self, dados) -> str:
        total = sum(int(d["saldo_aberto"] or 0) for d in dados)
        com_saldo = sum(1 for d in dados if int(d["saldo_aberto"] or 0) > 0)
        return (f"{len(dados)} fornecedor(es) • {com_saldo} com saldo em aberto • "
                f"a pagar {formatar_dinheiro(total)}")

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        fornecedor = fornecedores_mod.pegar(self.banco, linha["id"])
        if not fornecedor:
            return []
        return [
            ("Código", fornecedor["id"]),
            ("Razão social", fornecedor["razao_social"]),
            ("CNPJ/CPF", formatar_cpf_cnpj(fornecedor["cnpj_cpf"] or "") or "—"),
            ("Inscrição", fornecedor["inscricao"]),
            ("Contato", fornecedor["contato"]),
            ("Telefone", formatar_telefone(fornecedor["telefone"] or "") or "—"),
            ("Celular", formatar_telefone(fornecedor["celular"] or "") or "—"),
            ("E-mail", fornecedor["email"]),
            ("Endereço", fornecedores_mod.endereco_completo(fornecedor) or "—"),
            ("Prazo de pagamento", f"{int(fornecedor['prazo_dias'] or 0)} dia(s)"),
            ("Produtos ativos", linha.get("qtd_produtos")),
            ("Saldo a pagar", formatar_dinheiro(int(fornecedor["saldo_aberto"] or 0))),
            ("Total pago", formatar_dinheiro(int(fornecedor["total_pago"] or 0))),
            ("Observação", fornecedor["observacao"]),
        ]

    # ------------------------------------------------------------------ formulário
    def _formulario(self, fornecedor):
        editando = fornecedor is not None
        chaves_texto = ("nome", "razao_social", "cnpj_cpf", "inscricao", "contato", "telefone", "celular",
                        "email", "endereco", "numero", "bairro", "cidade", "uf", "cep", "observacao")
        valores: dict[str, Any] = {}
        if editando:
            valores = {chave: (fornecedor[chave] or "") for chave in chaves_texto}
            valores["prazo_dias"] = int(fornecedor["prazo_dias"] or 0)
            valores["ativo"] = int(fornecedor["ativo"] or 0)
        else:
            valores = {"ativo": 1, "prazo_dias": 30}

        secoes = [
            ("Identificação", [
                {"chave": "nome", "rotulo": "Nome fantasia", "tipo": "texto", "largura": 30, "obrigatorio": True},
                {"chave": "razao_social", "rotulo": "Razão social", "tipo": "texto", "largura": 30, "colunas": 2},
                {"chave": "cnpj_cpf", "rotulo": "CNPJ / CPF", "tipo": "texto", "largura": 20, "mascara": "documento",
                 "dica": "11 dígitos (CPF) ou 14 (CNPJ)"},
                {"chave": "inscricao", "rotulo": "Inscrição estadual", "tipo": "texto", "largura": 18},
                {"chave": "contato", "rotulo": "Pessoa de contato", "tipo": "texto", "largura": 24},
                {"chave": "prazo_dias", "rotulo": "Prazo de pagamento (dias)", "tipo": "quantidade", "largura": 10,
                 "decimais": 0, "minimo": 0, "maximo": 3650,
                 "dica": "Usado como vencimento padrão das contas"},
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
            ("Outros", [
                {"chave": "ativo", "rotulo": "Fornecedor ativo", "tipo": "marcar"},
                {"chave": "observacao", "rotulo": "Observações", "tipo": "texto", "largura": 34, "multilinea": True,
                 "altura": 3, "colunas": 3},
            ]),
        ]

        dialogo = dialogs.DialogoFormulario(
            self.ctx.janela, self.tema,
            "Editar fornecedor" if editando else "Novo fornecedor",
            secoes, valores, largura=780, altura=640, validar=self._validar_formulario,
        )
        resultado = dialogo.abrir()
        if resultado is None:
            return
        self._salvar(fornecedor, resultado, chaves_texto)

    @staticmethod
    def _validar_formulario(dados: dict) -> str:
        if len(str(dados.get("nome") or "").strip()) < 2:
            return "Informe o nome do fornecedor (mínimo 2 letras)."
        if dados.get("email") and "@" not in str(dados["email"]):
            return "E-mail inválido."
        return ""

    def _salvar(self, fornecedor, dados: dict, chaves_texto):
        registro = {chave: (dados.get(chave) or "") for chave in chaves_texto}
        registro["prazo_dias"] = int(dados.get("prazo_dias") or 0)
        registro["ativo"] = int(bool(dados.get("ativo", 1)))
        try:
            if fornecedor is None:
                similares = fornecedores_mod.nomes_similares(self.banco, registro["nome"])
                if similares:
                    if not dialogs.confirmar(
                            self, self.tema,
                            "Já existem fornecedores com nome parecido:\n\n" + "\n".join(f"• {n}" for n in similares) +
                            "\n\nCadastrar mesmo assim?", "Possível duplicado", "Cadastrar", "Cancelar"):
                        return
                fornecedor_id = fornecedores_mod.criar(self.banco, registro, autor=self.usuario)
                dialogs.sucesso(self, self.tema, f"Fornecedor “{registro['nome']}” cadastrado.")
            else:
                fornecedor_id = fornecedores_mod.atualizar(self.banco, int(fornecedor["id"]), registro,
                                                           autor=self.usuario)
                dialogs.sucesso(self, self.tema, "Fornecedor atualizado.")
        except fornecedores_mod.ErroFornecedor as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", fornecedor_id)
        return fornecedor_id

    def _novo(self, _tela=None):
        self._formulario(None)

    def _editar(self, _tela=None, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        fornecedor = fornecedores_mod.pegar(self.banco, linha["id"])
        if not fornecedor:
            dialogs.erro(self, self.tema, "Fornecedor não encontrado (pode ter sido excluído).")
            self.carregar()
            return
        self._formulario(fornecedor)

    def _excluir(self, _tela, linha: dict):
        if not dialogs.confirmar(self, self.tema, f"Excluir definitivamente o fornecedor “{linha['nome']}”?",
                                 "Excluir fornecedor", "Excluir", "Cancelar"):
            return None
        try:
            fornecedores_mod.excluir(self.banco, int(linha["id"]), autor=self.usuario)
        except fornecedores_mod.ErroFornecedor as exc:
            dialogs.alerta(self, self.tema, str(exc), "Exclusão bloqueada")
            return None
        self.carregar()
        dialogs.sucesso(self, self.tema, "Fornecedor excluído.")
        return True

    # ------------------------------------------------------------------ ações
    def alternar_status(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        try:
            if int(linha["ativo"] or 0):
                if not dialogs.confirmar(self, self.tema,
                                         f"Desativar o fornecedor “{linha['nome']}”?\n\n"
                                         "Ele deixará de aparecer nos cadastros, mas produtos e contas "
                                         "permanecem vinculados.",
                                         "Desativar fornecedor", "Desativar", "Cancelar"):
                    return
                fornecedores_mod.desativar(self.banco, int(linha["id"]), autor=self.usuario)
                dialogs.info(self, self.tema, "Fornecedor desativado.")
            else:
                fornecedores_mod.reativar(self.banco, int(linha["id"]), autor=self.usuario)
                dialogs.sucesso(self, self.tema, f"Fornecedor “{linha['nome']}” reativado.")
        except fornecedores_mod.ErroFornecedor as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()

    def ver_produtos(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        # limpa os demais filtros para a navegação não herdar o estado anterior
        self.ctx.navegar("produtos", {"fornecedor": linha["nome"], "categoria": "(todas)", "termo": ""})

    def lancar_conta(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        prazo = int(linha.get("prazo_dias") or 30) or 30
        dados = dialogs.formulario(
            self.ctx.janela, self.tema, f"Lançar conta a pagar — {linha['nome']}",
            [
                {"chave": "descricao", "rotulo": "Descrição", "tipo": "texto", "largura": 32, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "categoria", "rotulo": "Categoria", "tipo": "lista", "largura": 22,
                 "opcoes": [(c, c) for c in CATEGORIAS_DESPESA]},
                {"chave": "valor", "rotulo": "Valor", "tipo": "dinheiro", "largura": 14, "obrigatorio": True},
                {"chave": "vencimento", "rotulo": "Vencimento", "tipo": "texto", "largura": 12,
                 "dica": "DD/MM/AAAA"},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 32, "colunas": 2},
            ],
            {"categoria": "Fornecedores", "vencimento": formatar_data(somar_dias(hoje(), prazo))},
            largura=560,
            texto=f"Vencimento sugerido pelo prazo do fornecedor: {prazo} dia(s).",
        )
        if not dados:
            return
        try:
            conta_id = cp_mod.criar(
                self.banco, dados["descricao"], dados["valor"], dados.get("vencimento") or "",
                fornecedor_id=int(linha["id"]), categoria=dados.get("categoria") or "Outros",
                observacao=dados.get("observacao") or "", autor=self.usuario,
            )
        except cp_mod.ErroContaPagar as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Conta a pagar lançada (nº {conta_id}).\n"
                        f"Fornecedor: {linha['nome']}\nValor: {formatar_dinheiro(int(dados['valor']))}\n"
                        f"Vencimento: {formatar_data(dados.get('vencimento') or '')}")

    def abrir_ficha(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        fornecedor = fornecedores_mod.pegar(self.banco, linha["id"])
        if not fornecedor:
            dialogs.erro(self, self.tema, "Fornecedor não encontrado.")
            self.carregar()
            return
        produtos = fornecedores_mod.produtos_do_fornecedor(self.banco, int(linha["id"]))
        contas = cp_mod.listar(self.banco, fornecedor_id=int(linha["id"]), limite=500)
        DialogoFichaFornecedor(self.ctx.janela, self.tema, fornecedor, produtos, contas).abrir()

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("apenas_com_saldo") is not None:
            self._apenas_com_saldo.set(bool(parametros["apenas_com_saldo"]))
            self.carregar()
        if parametros.get("fornecedor_id"):
            self.tabela.selecionar_por("id", int(parametros["fornecedor_id"]))
