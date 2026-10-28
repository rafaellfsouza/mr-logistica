"""
Cadastro de clientes: dados pessoais/empresa, limite de crédito para o "fiado",
saldo devedor, histórico de compras e última compra.
"""

from __future__ import annotations

from .banco import Banco
from .utils import agora_iso, apenas_digitos, converter_data_br, normalizar


class ErroCliente(Exception):
    """Cliente inválido ou duplicado."""


CAMPOS_TEXTO = (
    "nome", "tipo", "cpf_cnpj", "rg_inscricao", "contato", "telefone", "celular",
    "email", "endereco", "numero", "bairro", "cidade", "uf", "cep", "observacao",
)

SQL_BASE = """
    SELECT c.*,
           (SELECT COALESCE(SUM(cr.valor - cr.valor_pago - cr.desconto), 0)
              FROM contas_receber cr
             WHERE cr.cliente_id = c.id AND cr.status IN ('aberta','parcial','vencida')) AS saldo_devedor,
           (SELECT COUNT(*) FROM contas_receber cr
             WHERE cr.cliente_id = c.id AND cr.status IN ('aberta','parcial','vencida')) AS contas_abertas,
           (SELECT COALESCE(SUM(v.total), 0) FROM vendas v
             WHERE v.cliente_id = c.id AND v.status IN ('concluida','parcialmente_devolvida')) AS total_compras,
           (SELECT COUNT(*) FROM vendas v
             WHERE v.cliente_id = c.id AND v.status IN ('concluida','parcialmente_devolvida')) AS qtd_compras,
           (SELECT MAX(v.criada_em) FROM vendas v
             WHERE v.cliente_id = c.id AND v.status IN ('concluida','parcialmente_devolvida')) AS ultima_compra
      FROM clientes c
"""

STATUS_VENDA_OK = ("concluida", "parcialmente_devolvida")


def listar(banco: Banco, incluir_inativos: bool = False, filtro: str = "", apenas_devedores: bool = False) -> list:
    """Lista clientes com busca por nome, documento, telefone, cidade ou e-mail."""
    condicoes, params = [], []
    if not incluir_inativos:
        condicoes.append("c.ativo = 1")
    if filtro:
        condicoes.append(
            "(c.nome LIKE ? OR c.cpf_cnpj LIKE ? OR c.telefone LIKE ? OR c.celular LIKE ? "
            "OR c.email LIKE ? OR c.cidade LIKE ? OR c.contato LIKE ?)"
        )
        params += [f"%{filtro}%"] * 7
    if apenas_devedores:
        condicoes.append(
            "(SELECT COALESCE(SUM(cr.valor - cr.valor_pago - cr.desconto),0) FROM contas_receber cr "
            " WHERE cr.cliente_id = c.id AND cr.status IN ('aberta','parcial','vencida')) > 0"
        )
    sql = SQL_BASE
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY c.nome"
    return banco.consultar(sql, params)


def pegar(banco: Banco, cliente_id):
    if not cliente_id:
        return None
    return banco.consultar_uma(SQL_BASE + " WHERE c.id=?", (cliente_id,))


def opcoes(banco: Banco) -> list[tuple[int, str]]:
    """``[(id, nome), ...]`` — o primeiro item é sempre "Consumidor final"."""
    linhas = banco.consultar("SELECT id, nome FROM clientes WHERE ativo=1 ORDER BY nome")
    return [(l["id"], l["nome"]) for l in linhas]


def buscar_por_documento(banco: Banco, texto: str):
    doc = apenas_digitos(texto)
    if not doc:
        return None
    return banco.consultar_uma(
        "SELECT * FROM clientes WHERE REPLACE(REPLACE(REPLACE(cpf_cnpj,'.',''),'-',''),'/','')=? LIMIT 1",
        (doc,),
    )


def _limpar(dados: dict) -> dict:
    registro = {c: str(dados.get(c) or "").strip() for c in CAMPOS_TEXTO}
    if not registro["nome"]:
        raise ErroCliente("Informe o nome do cliente.")
    if len(registro["nome"]) < 2:
        raise ErroCliente("Nome do cliente muito curto.")
    if registro["tipo"] not in ("Física", "Jurídica"):
        registro["tipo"] = "Física"
    registro["uf"] = registro["uf"].upper()[:2]
    doc = apenas_digitos(registro["cpf_cnpj"])
    if doc and len(doc) not in (11, 14):
        raise ErroCliente("CPF/CNPJ inválido: devem ser 11 (CPF) ou 14 (CNPJ) dígitos.")
    nascimento = converter_data_br(str(dados.get("nascimento") or ""))
    if dados.get("nascimento") and not nascimento:
        raise ErroCliente("Data de nascimento inválida. Use o formato DD/MM/AAAA.")
    registro["nascimento"] = nascimento or ""
    try:
        from .utils import para_centavos

        registro["limite_credito"] = max(0, para_centavos(dados.get("limite_credito", 0)))
    except Exception as exc:  # valor não numérico
        raise ErroCliente(f"Limite de crédito inválido: {exc}") from None
    registro["ativo"] = 1 if dados.get("ativo", 1) else 0
    return registro


def documento_duplicado(banco: Banco, documento: str, cliente_id: int | None = None):
    doc = apenas_digitos(documento)
    if not doc:
        return None
    return banco.consultar_uma(
        "SELECT * FROM clientes WHERE REPLACE(REPLACE(REPLACE(cpf_cnpj,'.',''),'-',''),'/','')=? AND (? IS NULL OR id<>?)",
        (doc, cliente_id, cliente_id),
    )


def criar(banco: Banco, dados: dict, autor=None) -> int:
    registro = _limpar(dados)
    duplicado = documento_duplicado(banco, registro["cpf_cnpj"])
    if duplicado:
        raise ErroCliente(f"Já existe o cliente '{duplicado['nome']}' com este CPF/CNPJ.")
    registro["criado_em"] = agora_iso()
    registro["atualizado_em"] = agora_iso()
    novo_id = banco.inserir("clientes", registro)
    banco.registrar_log("cliente_criado", registro["nome"], autor and autor["id"], autor and autor["nome"] or "")
    return novo_id


def atualizar(banco: Banco, cliente_id: int, dados: dict, autor=None) -> int:
    atual = pegar(banco, cliente_id)
    if not atual:
        raise ErroCliente("Cliente não encontrado.")
    base = {c: atual[c] for c in CAMPOS_TEXTO}
    base["nascimento"] = atual["nascimento"]
    base["limite_credito"] = atual["limite_credito"]
    base["ativo"] = atual["ativo"]
    registro = _limpar({**base, **dados})
    duplicado = documento_duplicado(banco, registro["cpf_cnpj"], cliente_id)
    if duplicado:
        raise ErroCliente(f"Já existe o cliente '{duplicado['nome']}' com este CPF/CNPJ.")
    registro["atualizado_em"] = agora_iso()
    banco.atualizar("clientes", cliente_id, registro)
    banco.registrar_log("cliente_alterado", registro["nome"], autor and autor["id"], autor and autor["nome"] or "")
    return cliente_id


def desativar(banco: Banco, cliente_id: int, autor=None) -> None:
    atual = pegar(banco, cliente_id)
    if not atual:
        raise ErroCliente("Cliente não encontrado.")
    devedor = banco.consultar_valor(
        "SELECT COALESCE(SUM(valor - valor_pago - desconto),0) FROM contas_receber "
        "WHERE cliente_id=? AND status IN ('aberta','parcial','vencida')",
        (cliente_id,),
    ) or 0
    if devedor > 0:
        raise ErroCliente(
            "Este cliente tem contas em aberto. Quite ou cancele as pendências antes de desativar."
        )
    banco.atualizar("clientes", cliente_id, {"ativo": 0, "atualizado_em": agora_iso()})
    banco.registrar_log("cliente_desativado", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def reativar(banco: Banco, cliente_id: int, autor=None) -> None:
    atual = pegar(banco, cliente_id)
    if not atual:
        raise ErroCliente("Cliente não encontrado.")
    banco.atualizar("clientes", cliente_id, {"ativo": 1, "atualizado_em": agora_iso()})
    banco.registrar_log("cliente_reativado", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def excluir(banco: Banco, cliente_id: int, autor=None) -> None:
    """Exclusão definitiva — bloqueada quando há vendas ou contas ligadas ao cliente."""
    atual = pegar(banco, cliente_id)
    if not atual:
        raise ErroCliente("Cliente não encontrado.")
    vendas = banco.consultar_valor("SELECT COUNT(*) FROM vendas WHERE cliente_id=?", (cliente_id,)) or 0
    contas = banco.consultar_valor("SELECT COUNT(*) FROM contas_receber WHERE cliente_id=?", (cliente_id,)) or 0
    if vendas or contas:
        raise ErroCliente(
            f"Não é possível excluir: o cliente tem {vendas} venda(s) e {contas} conta(s) registradas. "
            "Use 'Desativar' para tirá-lo das listas."
        )
    banco.excluir("clientes", cliente_id)
    banco.registrar_log("cliente_excluido", atual["nome"], autor and autor["id"], autor and autor["nome"] or "")


def compras_do_cliente(banco: Banco, cliente_id: int, limite: int = 100) -> list:
    return banco.consultar(
        """SELECT v.id, v.numero, v.criada_em, v.data_venda, v.total, v.status, v.vendedor_nome,
                  (SELECT COUNT(*) FROM venda_itens vi WHERE vi.venda_id=v.id) AS itens
             FROM vendas v WHERE v.cliente_id=? ORDER BY v.id DESC LIMIT ?""",
        (cliente_id, limite),
    )


def credito_disponivel(cliente) -> int:
    """Quanto ainda pode comprar no fiado (centavos). ``0`` de limite = sem restrição."""
    limite = int(cliente["limite_credito"] or 0)
    if limite <= 0:
        return 0
    return max(0, limite - int(cliente["saldo_devedor"] or 0))


def tem_limite(cliente) -> bool:
    return int(cliente["limite_credito"] or 0) > 0


def pode_fiar(cliente, valor_centavos: int) -> tuple[bool, str]:
    """Valida se o cliente pode assumir mais esse valor no fiado."""
    if not cliente:
        return False, "Selecione um cliente para vender no fiado."
    if not int(cliente["ativo"] or 0):
        return False, "Cliente desativado."
    if not tem_limite(cliente):
        return True, ""
    disponivel = credito_disponivel(cliente)
    if valor_centavos > disponivel:
        from .utils import formatar_dinheiro

        return False, (
            f"Limite de crédito excedido. Disponível: {formatar_dinheiro(disponivel)}; "
            f"valor da compra no fiado: {formatar_dinheiro(valor_centavos)}."
        )
    return True, ""


def resumo(banco: Banco) -> dict:
    linha = banco.consultar_uma(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN ativo=1 THEN 1 ELSE 0 END),0) AS ativos,
                  (SELECT COUNT(DISTINCT cliente_id) FROM contas_receber WHERE status IN ('aberta','parcial','vencida')) AS devedores,
                  (SELECT COALESCE(SUM(valor - valor_pago - desconto),0) FROM contas_receber WHERE status IN ('aberta','parcial','vencida')) AS saldo
             FROM clientes"""
    )
    return {
        "total": int(linha["total"] or 0),
        "ativos": int(linha["ativos"] or 0),
        "devedores": int(linha["devedores"] or 0),
        "saldo_aberto": int(linha["saldo"] or 0),
    }


def endereco_completo(cliente) -> str:
    partes = [
        " ".join(x for x in [cliente["endereco"] or "", cliente["numero"] or ""] if x),
        cliente["bairro"] or "",
        " - ".join(x for x in [cliente["cidade"] or "", cliente["uf"] or ""] if x),
        cliente["cep"] or "",
    ]
    return ", ".join(p for p in partes if p.strip())


def nomes_similares(banco: Banco, nome: str, limite: int = 5) -> list:
    """Sugere cadastros parecidos para evitar clientes duplicados."""
    import difflib

    alvo = normalizar(nome)
    if len(alvo) < 3:
        return []
    resultado = []
    for linha in banco.consultar("SELECT nome FROM clientes WHERE ativo=1 ORDER BY nome"):
        n = normalizar(linha["nome"])
        if alvo in n or n in alvo or difflib.SequenceMatcher(None, alvo, n).ratio() > 0.85:
            resultado.append(linha["nome"])
        if len(resultado) >= limite:
            break
    return resultado
