"""
Cadastro de categorias de produtos (usado para organizar e filtrar o estoque/relatórios).
"""

from __future__ import annotations

from .banco import Banco
from .utils import agora_iso, normalizar


class ErroCategoria(Exception):
    """Categoria inválida ou duplicada."""


def listar(banco: Banco, incluir_inativas: bool = False, filtro: str = "") -> list:
    """Lista categorias (com a quantidade de produtos ativos de cada uma)."""
    sql = """
        SELECT c.*,
               (SELECT COUNT(*) FROM produtos p WHERE p.categoria_id = c.id AND p.ativo = 1) AS qtd_produtos
          FROM categorias c
    """
    condicoes, params = [], []
    if not incluir_inativas:
        condicoes.append("c.ativo = 1")
    if filtro:
        condicoes.append("c.nome LIKE ?")
        params.append(f"%{filtro}%")
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY c.nome"
    return banco.consultar(sql, params)


def opcoes(banco: Banco) -> list[tuple[int, str]]:
    """``[(id, nome), ...]`` para preencher combos, ordenado por nome."""
    return [(l["id"], l["nome"]) for l in listar(banco)]


def pegar(banco: Banco, categoria_id):
    if not categoria_id:
        return None
    return banco.consultar_uma("SELECT * FROM categorias WHERE id=?", (categoria_id,))


def pegar_por_nome(banco: Banco, nome: str):
    alvo = normalizar(nome)
    for linha in banco.consultar("SELECT * FROM categorias"):
        if normalizar(linha["nome"]) == alvo:
            return linha
    return None


def criar(banco: Banco, nome: str, descricao: str = "", autor=None) -> int:
    nome = str(nome or "").strip()
    if not nome:
        raise ErroCategoria("Informe o nome da categoria.")
    if len(nome) < 2:
        raise ErroCategoria("Nome da categoria muito curto.")
    existente = pegar_por_nome(banco, nome)
    if existente:
        if int(existente["ativo"]):
            raise ErroCategoria(f"A categoria '{existente['nome']}' já existe.")
        # A categoria existia mas estava desativada: reativa em vez de duplicar.
        banco.atualizar("categorias", existente["id"], {"ativo": 1, "descricao": descricao or ""})
        return int(existente["id"])
    novo_id = banco.inserir("categorias", {"nome": nome, "descricao": descricao or "", "ativo": 1, "criado_em": agora_iso()})
    banco.registrar_log("categoria_criada", nome, autor and autor["id"], autor and autor["nome"] or "")
    return novo_id


def atualizar(banco: Banco, categoria_id: int, nome: str, descricao: str = "", autor=None) -> int:
    nome = str(nome or "").strip()
    if not nome:
        raise ErroCategoria("Informe o nome da categoria.")
    atual = pegar(banco, categoria_id)
    if not atual:
        raise ErroCategoria("Categoria não encontrada.")
    outra = pegar_por_nome(banco, nome)
    if outra and int(outra["id"]) != int(categoria_id):
        raise ErroCategoria(f"Já existe outra categoria chamada '{outra['nome']}'.")
    banco.atualizar("categorias", categoria_id, {"nome": nome, "descricao": descricao or ""})
    banco.registrar_log("categoria_alterada", nome, autor and autor["id"], autor and autor["nome"] or "")
    return categoria_id


def desativar(banco: Banco, categoria_id: int, autor=None) -> None:
    """Desativa (exclusão lógica). Os produtos mantêm o vínculo histórico."""
    atual = pegar(banco, categoria_id)
    if not atual:
        raise ErroCategoria("Categoria não encontrada.")
    banco.atualizar("categorias", categoria_id, {"ativo": 0})
    banco.registrar_log("categoria_desativada", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def reativar(banco: Banco, categoria_id: int, autor=None) -> None:
    atual = pegar(banco, categoria_id)
    if not atual:
        raise ErroCategoria("Categoria não encontrada.")
    banco.atualizar("categorias", categoria_id, {"ativo": 1})
    banco.registrar_log("categoria_reativada", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def excluir(banco: Banco, categoria_id: int, autor=None) -> None:
    """Exclusão definitiva — só é permitida quando não há produtos vinculados."""
    atual = pegar(banco, categoria_id)
    if not atual:
        raise ErroCategoria("Categoria não encontrada.")
    usados = banco.consultar_valor("SELECT COUNT(*) FROM produtos WHERE categoria_id=?", (categoria_id,)) or 0
    if usados:
        raise ErroCategoria(
            f"Não é possível excluir: {usados} produto(s) ainda usam esta categoria. "
            f"Use 'Desativar' para escondê-la das listas."
        )
    banco.excluir("categorias", categoria_id)
    banco.registrar_log("categoria_excluida", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")
