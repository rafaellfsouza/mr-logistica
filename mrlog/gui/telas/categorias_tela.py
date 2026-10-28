"""
Tela de **Categorias** — agrupamento de produtos usado nos filtros e relatórios.

Categorias nunca são apagadas quando possuem produtos vinculados: a exclusão
definitiva só é liberada para categorias vazias; caso contrário o usuário é
orientado a **desativar** (exclusão lógica, mantém o histórico).
"""

from __future__ import annotations

import tkinter as tk

from ... import categorias as categorias_mod
from .. import dialogs
from . import TelaLista, abrir_formulario

CAMPOS = [
    {"chave": "nome", "rotulo": "Nome da categoria", "tipo": "texto", "obrigatorio": True, "largura": 32},
    {"chave": "descricao", "rotulo": "Descrição (opcional)", "tipo": "texto", "largura": 44, "colunas": 2},
]


class CategoriasTela(TelaLista):
    titulo = "Categorias"
    descricao = "Grupos de produtos usados nos filtros, relatórios e reajustes de preço."
    permissao_editar = "categorias"
    permissao_excluir = "categorias"

    def __init__(self, mestre, ctx):
        self._incluir_inativas = tk.BooleanVar(value=False)
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "nome", "rotulo": "Categoria", "largura": 250},
                {"chave": "descricao", "rotulo": "Descrição", "largura": 330},
                {"chave": "qtd_produtos", "rotulo": "Produtos", "largura": 90, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "qtd_inativos", "rotulo": "Inativos", "largura": 80, "tipo": "inteiro", "alinhamento": "centro"},
                {"chave": "estoque_valor", "rotulo": "Estoque (custo)", "largura": 130, "tipo": "dinheiro"},
                {"chave": "status_texto", "rotulo": "Situação", "largura": 90, "alinhamento": "centro"},
            ],
            carregar_dados=self._dados,
            resumo=self._resumo,
            novo=self._novo,
            editar=self._editar,
            excluir=self._excluir,
            ao_duplo_clique=lambda linha: self.editar(linha=linha),
            detalhes=self._detalhes,
            acoes=(
                ("📦 Produtos da categoria", self.ver_produtos, "TButton", "F2"),
                ("⏻ Desativar / Reativar", self.alternar_status, "TButton", "F3"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Categorias",
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        tk.Checkbutton(
            pai, text="Mostrar categorias inativas", variable=self._incluir_inativas, command=self.carregar,
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
            activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
            selectcolor=self.tema.cor("bg_input"), highlightthickness=0, anchor="w",
        ).pack(side="left")

    def ao_tecla(self, tecla: str) -> bool:
        if tecla == "F2":
            self.ver_produtos()
            return True
        if tecla == "F3":
            self.alternar_status()
            return True
        return False

    # ------------------------------------------------------------------ dados
    def _dados(self) -> list[dict]:
        categorias = categorias_mod.listar(self.banco, incluir_inativas=bool(self._incluir_inativas.get()))
        # Um único agrupamento evita consultar produto por produto.
        agregados = {
            int(linha["categoria_id"]): dict(linha)
            for linha in self.banco.consultar(
                """SELECT categoria_id,
                          COUNT(*) AS qtd_total,
                          SUM(CASE WHEN ativo = 1 THEN 1 ELSE 0 END) AS qtd_ativos,
                          COALESCE(SUM(preco_custo * estoque_atual), 0) AS valor_custo
                     FROM produtos
                    WHERE categoria_id IS NOT NULL
                 GROUP BY categoria_id"""
            )
        }
        linhas = []
        for categoria in categorias:
            linha = dict(categoria)
            extra = agregados.get(int(categoria["id"])) or {}
            linha["qtd_produtos"] = int(extra.get("qtd_ativos") or linha.get("qtd_produtos") or 0)
            linha["qtd_inativos"] = max(0, int(extra.get("qtd_total") or 0) - linha["qtd_produtos"])
            linha["estoque_valor"] = int(extra.get("valor_custo") or 0)
            ativo = int(categoria["ativo"] or 0)
            linha["status_texto"] = "Ativa" if ativo else "Inativa"
            linha["_tag"] = "" if ativo else "neutro"
            linhas.append(linha)
        return linhas

    def _resumo(self, dados) -> str:
        ativas = sum(1 for d in dados if d["status_texto"] == "Ativa")
        produtos = sum(d["qtd_produtos"] for d in dados)
        return f"{len(dados)} categoria(s) • {ativas} ativa(s) • {produtos} produto(s) ativo(s) vinculado(s)"

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        from ...utils import formatar_dinheiro, formatar_quantidade

        criadas = str(linha.get("criado_em") or "").replace("T", " ")[:19]
        return [
            ("Código", linha.get("id")),
            ("Situação", linha.get("status_texto")),
            ("Produtos ativos", linha.get("qtd_produtos")),
            ("Produtos inativos", linha.get("qtd_inativos")),
            ("Valor em estoque (custo)", formatar_dinheiro(linha.get("estoque_valor"))),
            ("Criada em", criadas),
            ("Descrição", linha.get("descricao")),
        ]

    # ------------------------------------------------------------------ CRUD
    def _novo(self, _tela=None):
        dados = abrir_formulario(self, "Nova categoria", CAMPOS, largura=540)
        if not dados:
            return
        try:
            categorias_mod.criar(self.banco, dados["nome"], dados.get("descricao", ""), autor=self.usuario)
        except categorias_mod.ErroCategoria as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, f"Categoria “{dados['nome'].strip()}” criada.")

    def _editar(self, _tela=None, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        dados = abrir_formulario(
            self, f"Editar categoria “{linha['nome']}”", CAMPOS,
            {"nome": linha["nome"], "descricao": linha["descricao"] or ""}, largura=540,
        )
        if not dados:
            return
        try:
            categorias_mod.atualizar(self.banco, int(linha["id"]), dados["nome"], dados.get("descricao", ""),
                                     autor=self.usuario)
        except categorias_mod.ErroCategoria as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, "Categoria atualizada.")

    def _excluir(self, _tela, linha: dict):
        if int(linha.get("qtd_produtos") or 0) + int(linha.get("qtd_inativos") or 0) > 0:
            dialogs.alerta(
                self, self.tema,
                f"A categoria “{linha['nome']}” ainda tem produtos vinculados.\n\n"
                "Para preservarmos o histórico das vendas e do estoque, ela não pode ser excluída.\n"
                "Use o botão **Desativar / Reativar** para escondê-la das listas.",
                "Exclusão bloqueada",
            )
            return None
        if not dialogs.confirmar(self, self.tema, f"Excluir definitivamente a categoria “{linha['nome']}”?",
                                 "Excluir categoria", "Excluir", "Cancelar"):
            return None
        try:
            categorias_mod.excluir(self.banco, int(linha["id"]), autor=self.usuario)
        except categorias_mod.ErroCategoria as exc:
            dialogs.alerta(self, self.tema, str(exc), "Exclusão bloqueada")
            return None
        self.carregar()
        dialogs.sucesso(self, self.tema, "Categoria excluída.")
        return True

    # ------------------------------------------------------------------ ações
    def alternar_status(self):
        linha = self.exigir_selecao()
        if not linha:
            return
        ativo = int(linha["ativo"] or 0)
        try:
            if ativo:
                if not dialogs.confirmar(self, self.tema,
                                         f"Desativar a categoria “{linha['nome']}”?\n\n"
                                         "Ela deixará de aparecer nas listas e combos, mas os produtos "
                                         "permanecem vinculados.",
                                         "Desativar categoria", "Desativar", "Cancelar"):
                    return
                categorias_mod.desativar(self.banco, int(linha["id"]), autor=self.usuario)
                dialogs.info(self, self.tema, "Categoria desativada.")
            else:
                categorias_mod.reativar(self.banco, int(linha["id"]), autor=self.usuario)
                dialogs.sucesso(self, self.tema, f"Categoria “{linha['nome']}” reativada.")
        except categorias_mod.ErroCategoria as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()

    def ver_produtos(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        # limpa o filtro de fornecedor para a navegação não herdar o estado anterior
        self.ctx.navegar("produtos", {"categoria": linha["nome"], "fornecedor": "(todos)", "termo": ""})
