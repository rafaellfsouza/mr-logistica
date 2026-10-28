"""
Cadastro de fornecedores: dados de contato, endereço, prazo de pagamento e
resumo financeiro (total comprado e saldo em aberto em contas a pagar).
"""

from __future__ import annotations

from .banco import Banco
from .utils import agora_iso, apenas_digitos, normalizar


class ErroFornecedor(Exception):
    """Fornecedor inválido ou duplicado."""


CAMPOS_TEXTO = (
    "nome", "razao_social", "cnpj_cpf", "inscricao", "contato", "telefone", "celular",
    "email", "endereco", "numero", "bairro", "cidade", "uf", "cep", "observacao",
)

SQL_BASE = """
    SELECT f.*,
           (SELECT COUNT(*) FROM produtos p WHERE p.fornecedor_id = f.id AND p.ativo = 1) AS qtd_produtos,
           (SELECT COALESCE(SUM(cp.valor - cp.valor_pago), 0)
              FROM contas_pagar cp
             WHERE cp.fornecedor_id = f.id AND cp.status IN ('aberta','parcial','vencida')) AS saldo_aberto,
           (SELECT COALESCE(SUM(cp.valor_pago), 0)
              FROM contas_pagar cp WHERE cp.fornecedor_id = f.id) AS total_pago,
           (SELECT COALESCE(SUM(m.valor_total), 0)
              FROM movimentacoes m
              JOIN lotes l ON l.id = m.lote_id
             WHERE l.fornecedor_id = f.id AND m.tipo = 'entrada') AS total_comprado
      FROM fornecedores f
"""


def listar(banco: Banco, incluir_inativos: bool = False, filtro: str = "", apenas_com_saldo: bool = False) -> list:
    """Lista fornecedores com busca por nome, documento, cidade, contato ou e-mail."""
    condicoes, params = [], []
    if not incluir_inativos:
        condicoes.append("f.ativo = 1")
    if filtro:
        condicoes.append(
            "(f.nome LIKE ? OR f.razao_social LIKE ? OR f.cnpj_cpf LIKE ? OR f.cidade LIKE ? "
            "OR f.contato LIKE ? OR f.email LIKE ? OR f.telefone LIKE ? OR f.celular LIKE ?)"
        )
        params += [f"%{filtro}%"] * 8
    if apenas_com_saldo:
        condicoes.append(
            "(SELECT COALESCE(SUM(cp.valor - cp.valor_pago),0) FROM contas_pagar cp "
            " WHERE cp.fornecedor_id=f.id AND cp.status IN ('aberta','parcial','vencida')) > 0"
        )
    sql = SQL_BASE
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY f.nome"
    return banco.consultar(sql, params)


def pegar(banco: Banco, fornecedor_id):
    if not fornecedor_id:
        return None
    return banco.consultar_uma(SQL_BASE + " WHERE f.id=?", (fornecedor_id,))


def opcoes(banco: Banco) -> list[tuple[int, str]]:
    """``[(id, nome), ...]`` para combos (somente ativos)."""
    return [(l["id"], l["nome"]) for l in listar(banco)]


def _limpar(dados: dict) -> dict:
    registro = {c: str(dados.get(c) or "").strip() for c in CAMPOS_TEXTO}
    if not registro["nome"]:
        raise ErroFornecedor("Informe o nome (ou razão social) do fornecedor.")
    if len(registro["nome"]) < 2:
        raise ErroFornecedor("Nome do fornecedor muito curto.")
    registro["uf"] = registro["uf"].upper()[:2]
    doc = apenas_digitos(registro["cnpj_cpf"])
    if doc and len(doc) not in (11, 14):
        raise ErroFornecedor("CPF/CNPJ inválido: devem ser 11 (CPF) ou 14 (CNPJ) dígitos.")
    try:
        registro["prazo_dias"] = max(0, int(dados.get("prazo_dias") or 0))
    except (TypeError, ValueError):
        raise ErroFornecedor("Prazo de pagamento deve ser um número de dias.") from None
    registro["ativo"] = 1 if dados.get("ativo", 1) else 0
    return registro


def documento_duplicado(banco: Banco, documento: str, fornecedor_id: int | None = None):
    doc = apenas_digitos(documento)
    if not doc:
        return None
    return banco.consultar_uma(
        "SELECT * FROM fornecedores WHERE REPLACE(REPLACE(REPLACE(cnpj_cpf,'.',''),'-',''),'/','')=? AND (? IS NULL OR id<>?)",
        (doc, fornecedor_id, fornecedor_id),
    )


def criar(banco: Banco, dados: dict, autor=None) -> int:
    registro = _limpar(dados)
    duplicado = documento_duplicado(banco, registro["cnpj_cpf"])
    if duplicado:
        raise ErroFornecedor(f"Já existe o fornecedor '{duplicado['nome']}' com este CPF/CNPJ.")
    registro["criado_em"] = agora_iso()
    registro["atualizado_em"] = agora_iso()
    novo_id = banco.inserir("fornecedores", registro)
    banco.registrar_log("fornecedor_criado", registro["nome"], autor and autor["id"], autor and autor["nome"] or "")
    return novo_id


def atualizar(banco: Banco, fornecedor_id: int, dados: dict, autor=None) -> int:
    atual = pegar(banco, fornecedor_id)
    if not atual:
        raise ErroFornecedor("Fornecedor não encontrado.")
    registro = _limpar({**{c: atual[c] for c in CAMPOS_TEXTO}, **dados, "prazo_dias": dados.get("prazo_dias", atual["prazo_dias"]), "ativo": dados.get("ativo", atual["ativo"])})
    duplicado = documento_duplicado(banco, registro["cnpj_cpf"], fornecedor_id)
    if duplicado:
        raise ErroFornecedor(f"Já existe o fornecedor '{duplicado['nome']}' com este CPF/CNPJ.")
    registro["atualizado_em"] = agora_iso()
    banco.atualizar("fornecedores", fornecedor_id, registro)
    banco.registrar_log("fornecedor_alterado", registro["nome"], autor and autor["id"], autor and autor["nome"] or "")
    return fornecedor_id


def desativar(banco: Banco, fornecedor_id: int, autor=None) -> None:
    atual = pegar(banco, fornecedor_id)
    if not atual:
        raise ErroFornecedor("Fornecedor não encontrado.")
    banco.atualizar("fornecedores", fornecedor_id, {"ativo": 0, "atualizado_em": agora_iso()})
    banco.registrar_log("fornecedor_desativado", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def reativar(banco: Banco, fornecedor_id: int, autor=None) -> None:
    atual = pegar(banco, fornecedor_id)
    if not atual:
        raise ErroFornecedor("Fornecedor não encontrado.")
    banco.atualizar("fornecedores", fornecedor_id, {"ativo": 1, "atualizado_em": agora_iso()})
    banco.registrar_log("fornecedor_reativado", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def excluir(banco: Banco, fornecedor_id: int, autor=None) -> None:
    """Exclusão definitiva — bloqueada quando há produtos, compras ou contas vinculadas."""
    atual = pegar(banco, fornecedor_id)
    if not atual:
        raise ErroFornecedor("Fornecedor não encontrado.")
    produtos = banco.consultar_valor("SELECT COUNT(*) FROM produtos WHERE fornecedor_id=?", (fornecedor_id,)) or 0
    contas = banco.consultar_valor("SELECT COUNT(*) FROM contas_pagar WHERE fornecedor_id=?", (fornecedor_id,)) or 0
    lotes = banco.consultar_valor("SELECT COUNT(*) FROM lotes WHERE fornecedor_id=?", (fornecedor_id,)) or 0
    if produtos or contas or lotes:
        raise ErroFornecedor(
            "Não é possível excluir: existem "
            f"{produtos} produto(s), {contas} conta(s) a pagar e {lotes} lote(s) vinculados. "
            "Use 'Desativar' para tirá-lo das listas."
        )
    banco.excluir("fornecedores", fornecedor_id)
    banco.registrar_log("fornecedor_excluido", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def produtos_do_fornecedor(banco: Banco, fornecedor_id: int) -> list:
    return banco.consultar(
        "SELECT p.codigo, p.codigo_barras, p.nome, p.unidade_base, p.estoque_atual, p.preco_custo, p.preco_venda, p.ativo "
        "FROM produtos p WHERE p.fornecedor_id=? ORDER BY p.nome",
        (fornecedor_id,),
    )


def resumo(banco: Banco) -> dict:
    """Totais usados no painel: quantidade de fornecedores e saldo a pagar."""
    linha = banco.consultar_uma(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN ativo=1 THEN 1 ELSE 0 END),0) AS ativos,
                  (SELECT COALESCE(SUM(valor - valor_pago),0) FROM contas_pagar WHERE status IN ('aberta','parcial','vencida')) AS saldo
             FROM fornecedores"""
    )
    return {"total": int(linha["total"] or 0), "ativos": int(linha["ativos"] or 0), "saldo_aberto": int(linha["saldo"] or 0)}


def endereco_completo(fornecedor) -> str:
    partes = [
        " ".join(x for x in [fornecedor["endereco"] or "", fornecedor["numero"] or ""] if x),
        fornecedor["bairro"] or "",
        " - ".join(x for x in [fornecedor["cidade"] or "", fornecedor["uf"] or ""] if x),
        fornecedor["cep"] or "",
    ]
    return ", ".join(p for p in partes if p.strip())


def sugestao_pelo_documento(banco: Banco, texto: str):
    """Busca aproximada pelo documento digitado sem máscara."""
    doc = apenas_digitos(texto)
    if not doc:
        return None
    for linha in banco.consultar("SELECT * FROM fornecedores WHERE cnpj_cpf IS NOT NULL AND cnpj_cpf <> ''"):
        if apenas_digitos(linha["cnpj_cpf"]) == doc:
            return linha
    return None


def nomes_similares(banco: Banco, nome: str, limite: int = 5) -> list:
    """Ajuda a evitar cadastros duplicados: procura nomes parecidos."""
    alvo = normalizar(nome)
    if not alvo:
        return []
    resultado = []
    for linha in banco.consultar("SELECT id, nome FROM fornecedores WHERE ativo=1 ORDER BY nome"):
        n = normalizar(linha["nome"])
        if alvo in n or n in alvo or _similaridade(alvo, n) > 0.8:
            resultado.append(linha["nome"])
        if len(resultado) >= limite:
            break
    return resultado


def _similaridade(a: str, b: str) -> float:
    """Semelhança simples entre duas strings (usada só para sugerir duplicados)."""
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()
