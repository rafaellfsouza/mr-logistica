"""
Contas a receber — o "fiado" (crediário próprio da loja).

Quando uma venda é finalizada com parte ou todo o valor em **Fiado**, o sistema:

1. exige um cliente identificado;
2. valida o limite de crédito cadastrado;
3. cria automaticamente um título em ``contas_receber`` com vencimento.

Depois o título pode ser **recebido** (total ou em parcelas), ter **desconto**
concedido, ser **cancelado** ou entrar em **atraso** (status ``vencida``, atualizado
automaticamente a cada consulta). Todo recebimento em dinheiro entra no caixa do dia.
"""

from __future__ import annotations

from . import caixa as caixa_mod
from . import clientes as clientes_mod
from .banco import Banco
from .utils import agora_iso, converter_data_br, dias_entre, formatar_dinheiro, hoje, para_centavos, somar_dias


class ErroContaReceber(Exception):
    """Operação inválida em contas a receber."""


SQL_BASE = """
    SELECT cr.*,
           (cr.valor - cr.valor_pago - cr.desconto) AS saldo,
           CAST(julianday('now','localtime') - julianday(cr.vencimento) AS INTEGER) AS dias_atraso,
           (SELECT COALESCE(SUM(r.valor),0) FROM recebimentos r WHERE r.conta_id = cr.id) AS soma_recebimentos,
           (SELECT COUNT(*) FROM recebimentos r WHERE r.conta_id = cr.id) AS qtd_recebimentos
      FROM contas_receber cr
"""


def _autor(autor) -> tuple[int | None, str]:
    if not autor:
        return None, ""
    try:
        return int(autor["id"]), str(autor["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, str(autor)


# --------------------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------------------


def atualizar_vencidas(banco: Banco) -> int:
    """Marca como ``vencida`` toda conta em aberto com vencimento anterior a hoje."""
    cur = banco.executar(
        """UPDATE contas_receber SET status='vencida', atualizado_em=?
            WHERE status IN ('aberta','parcial') AND date(vencimento) < date(?)""",
        (agora_iso(), hoje()),
    )
    return int(cur.rowcount or 0)


def recalcular_status(banco: Banco, conta_id: int) -> str:
    """Recalcula o status de um título a partir dos valores pagos/descontados."""
    conta = banco.consultar_uma("SELECT * FROM contas_receber WHERE id=?", (conta_id,))
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    if conta["status"] == "cancelada":
        return "cancelada"
    saldo = int(conta["valor"] or 0) - int(conta["valor_pago"] or 0) - int(conta["desconto"] or 0)
    if saldo <= 0:
        novo = "paga"
    elif int(conta["valor_pago"] or 0) > 0:
        novo = "parcial"
    elif dias_entre(conta["vencimento"]) < 0:
        novo = "vencida"
    else:
        novo = "aberta"
    if novo != conta["status"]:
        banco.atualizar("contas_receber", conta_id, {"status": novo, "atualizado_em": agora_iso()})
    return novo


# --------------------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------------------


def listar(
    banco: Banco,
    status: str = "",
    cliente_id: int | None = None,
    data_inicial: str = "",
    data_final: str = "",
    vencimento_ate: str = "",
    texto: str = "",
    incluir_quitadas: bool = False,
    limite: int = 1000,
) -> list:
    """Lista títulos com filtros combináveis (usado na tela e nos relatórios)."""
    atualizar_vencidas(banco)
    condicoes, params = [], []
    if status:
        if status == "pendentes":
            condicoes.append("cr.status IN ('aberta','parcial','vencida')")
        elif status == "atrasadas":
            condicoes.append("cr.status IN ('aberta','parcial','vencida') AND date(cr.vencimento) < date(?)")
            params.append(hoje())
        else:
            condicoes.append("cr.status = ?")
            params.append(status)
    elif not incluir_quitadas:
        condicoes.append("cr.status <> 'cancelada'")
    if cliente_id:
        condicoes.append("cr.cliente_id = ?")
        params.append(int(cliente_id))
    if data_inicial:
        condicoes.append("date(cr.criado_em) >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("date(cr.criado_em) <= date(?)")
        params.append(str(data_final)[:10])
    if vencimento_ate:
        condicoes.append("date(cr.vencimento) <= date(?)")
        params.append(str(vencimento_ate)[:10])
    if texto:
        condicoes.append("(cr.descricao LIKE ? OR cr.cliente_nome LIKE ?)")
        params += [f"%{texto}%"] * 2
    sql = SQL_BASE
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY (cr.status='paga'), cr.vencimento, cr.id LIMIT ?"
    params.append(int(limite))
    return banco.consultar(sql, params)


def pegar(banco: Banco, conta_id: int):
    return banco.consultar_uma(SQL_BASE + " WHERE cr.id=?", (conta_id,))


def recebimentos(banco: Banco, conta_id: int) -> list:
    return banco.consultar("SELECT * FROM recebimentos WHERE conta_id=? ORDER BY id", (conta_id,))


def resumo(banco: Banco) -> dict:
    """Totais para o painel: a receber, vencido, recebido no mês."""
    atualizar_vencidas(banco)
    linha = banco.consultar_uma(
        """SELECT
             COALESCE(SUM(CASE WHEN status IN ('aberta','parcial','vencida') THEN valor - valor_pago - desconto ELSE 0 END),0) AS a_receber,
             COALESCE(SUM(CASE WHEN status='vencida' THEN valor - valor_pago - desconto ELSE 0 END),0) AS vencido,
             COALESCE(SUM(CASE WHEN status IN ('aberta','parcial','vencida') THEN 1 ELSE 0 END),0) AS qtd_abertas,
             COALESCE(SUM(CASE WHEN status='vencida' THEN 1 ELSE 0 END),0) AS qtd_vencidas,
             COALESCE(SUM(valor_pago),0) AS recebido_total
           FROM contas_receber"""
    )
    mes = banco.consultar_valor(
        "SELECT COALESCE(SUM(valor),0) FROM recebimentos WHERE strftime('%Y-%m', criado_em) = strftime('%Y-%m','now','localtime')"
    )
    return {
        "a_receber": int(linha["a_receber"] or 0),
        "vencido": int(linha["vencido"] or 0),
        "qtd_abertas": int(linha["qtd_abertas"] or 0),
        "qtd_vencidas": int(linha["qtd_vencidas"] or 0),
        "recebido_total": int(linha["recebido_total"] or 0),
        "recebido_mes": int(mes or 0),
    }


def envelhecimento(banco: Banco) -> list[dict]:
    """Aging de contas a receber: agrupa os saldos em faixas de atraso.

    ``atraso`` é positivo quando o título está vencido e negativo quando ainda vai vencer.
    """
    atualizar_vencidas(banco)
    faixas = [
        ("A vencer", None, -1),
        ("Vence hoje", 0, 0),
        ("1 a 7 dias", 1, 7),
        ("8 a 15 dias", 8, 15),
        ("16 a 30 dias", 16, 30),
        ("31 a 60 dias", 31, 60),
        ("Acima de 60 dias", 61, None),
    ]
    contas = listar(banco, status="pendentes", limite=100000)
    atrasos = [(-dias_entre(c["vencimento"]), int(c["saldo"] or 0)) for c in contas]
    resultado = []
    for rotulo, minimo, maximo in faixas:
        selecionadas = [
            valor for atraso, valor in atrasos
            if (minimo is None or atraso >= minimo) and (maximo is None or atraso <= maximo)
        ]
        resultado.append(
            {
                "faixa": rotulo,
                "quantidade": len(selecionadas),
                "valor": sum(selecionadas),
            }
        )
    return resultado


# --------------------------------------------------------------------------------------
# Lançamentos
# --------------------------------------------------------------------------------------


def criar_manual(
    banco: Banco,
    cliente_id: int,
    descricao: str,
    valor,
    vencimento: str = "",
    venda_id: int | None = None,
    autor=None,
) -> int:
    """Lança uma conta a receber avulsa (sem origem em venda)."""
    cliente = clientes_mod.pegar(banco, cliente_id)
    if not cliente:
        raise ErroContaReceber("Cliente não encontrado.")
    if not int(cliente["ativo"] or 0):
        raise ErroContaReceber("Cliente desativado — reative-o para lançar contas.")
    descricao = str(descricao or "").strip()
    if not descricao:
        raise ErroContaReceber("Descreva a conta a receber.")
    centavos = para_centavos(valor)
    if centavos <= 0:
        raise ErroContaReceber("O valor deve ser maior que zero.")
    data_venc = converter_data_br(vencimento) or somar_dias(hoje(), 30)
    with banco.transacao():
        conta_id = banco.inserir(
            "contas_receber",
            {
                "cliente_id": int(cliente_id),
                "cliente_nome": cliente["nome"],
                "venda_id": int(venda_id) if venda_id else None,
                "descricao": descricao,
                "valor": centavos,
                "valor_pago": 0,
                "desconto": 0,
                "vencimento": data_venc,
                "status": "aberta",
                "criado_em": agora_iso(),
                "atualizado_em": agora_iso(),
            },
        )
    banco.registrar_log("conta_receber_criada", f"{cliente['nome']}: {formatar_dinheiro(centavos)}", *_autor(autor))
    return conta_id


def criar_de_venda(banco: Banco, venda_id: int, cliente_id: int, cliente_nome: str, valor_centavos: int,
                   vencimento: str = "", numero_venda: int = 0, autor=None) -> int | None:
    """Cria o título do fiado gerado por uma venda (chamado por :mod:`mrlog.vendas`)."""
    valor = int(valor_centavos or 0)
    if valor <= 0:
        return None
    data_venc = converter_data_br(vencimento) or hoje()
    descricao = f"Venda nº {numero_venda:06d}" if numero_venda else f"Venda nº {venda_id}"
    conta_id = banco.inserir(
        "contas_receber",
        {
            "cliente_id": int(cliente_id),
            "cliente_nome": cliente_nome,
            "venda_id": int(venda_id),
            "descricao": descricao,
            "valor": valor,
            "valor_pago": 0,
            "desconto": 0,
            "vencimento": data_venc,
            "status": "aberta",
            "criado_em": agora_iso(),
            "atualizado_em": agora_iso(),
        },
    )
    banco.registrar_log("fiado_gerado", f"{descricao} — {cliente_nome} — {formatar_dinheiro(valor)}", *_autor(autor))
    return conta_id


def receber(
    banco: Banco,
    conta_id: int,
    valor,
    forma: str = "Dinheiro",
    desconto=0,
    observacao: str = "",
    autor=None,
    lancar_no_caixa: bool = True,
) -> dict:
    """Recebe (total ou parcialmente) um título. Desconta do saldo e entra no caixa.

    Devolve ``{'recebido': centavos, 'saldo': centavos, 'status': str}``.
    """
    from . import formas_pagamento

    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    if conta["status"] == "cancelada":
        raise ErroContaReceber("Esta conta foi cancelada.")
    if conta["status"] == "paga":
        raise ErroContaReceber("Esta conta já está quitada.")
    forma_ok = formas_pagamento.normalizar(forma)
    if forma_ok not in formas_pagamento.PARA_RECEBIMENTOS:
        raise ErroContaReceber(f"Forma de recebimento inválida: '{forma}'.")
    saldo_atual = int(conta["saldo"] or 0)
    desc = para_centavos(desconto)
    if desc < 0:
        raise ErroContaReceber("O desconto não pode ser negativo.")
    if desc > saldo_atual:
        raise ErroContaReceber("O desconto não pode ser maior que o saldo devedor.")
    recebido = para_centavos(valor)
    if recebido < 0:
        raise ErroContaReceber("Valor recebido inválido.")
    if recebido + desc <= 0:
        raise ErroContaReceber("Informe o valor recebido ou um desconto.")
    if recebido > saldo_atual - desc:
        raise ErroContaReceber(
            f"O valor recebido ({formatar_dinheiro(recebido)}) é maior que o saldo devedor "
            f"({formatar_dinheiro(saldo_atual - desc)})."
        )
    usuario_id, usuario_nome = _autor(autor)
    with banco.transacao():
        banco.atualizar(
            "contas_receber",
            conta_id,
            {
                "valor_pago": int(conta["valor_pago"] or 0) + recebido,
                "desconto": int(conta["desconto"] or 0) + desc,
                "atualizado_em": agora_iso(),
            },
        )
        if recebido > 0:
            banco.inserir(
                "recebimentos",
                {
                    "conta_id": conta_id,
                    "valor": recebido,
                    "forma": forma_ok,
                    "caixa_id": None,
                    "usuario_id": usuario_id,
                    "usuario_nome": usuario_nome,
                    "observacao": str(observacao or ""),
                    "criado_em": agora_iso(),
                },
            )
            caixa_atual = caixa_mod.caixa_aberto(banco)
            if lancar_no_caixa and caixa_atual:
                caixa_mod.registrar_entrada(
                    banco, "Recebimento fiado",
                    f"Recebimento — {conta['cliente_nome']} ({conta['descricao']})",
                    recebido, forma_ok, referencia=str(conta_id), autor=autor,
                    caixa_id=int(caixa_atual["id"]),
                )
                banco.executar(
                    "UPDATE recebimentos SET caixa_id=? WHERE id=(SELECT MAX(id) FROM recebimentos WHERE conta_id=?)",
                    (caixa_atual["id"], conta_id),
                )
        novo_status = recalcular_status(banco, conta_id)
    banco.registrar_log(
        "conta_recebida",
        f"{conta['cliente_nome']} — {formatar_dinheiro(recebido)}" + (f" (desconto {formatar_dinheiro(desc)})" if desc else ""),
        usuario_id, usuario_nome,
    )
    conta_nova = pegar(banco, conta_id)
    return {"recebido": recebido, "desconto": desc, "saldo": int(conta_nova["saldo"] or 0), "status": novo_status}


def quitar(banco: Banco, conta_id: int, forma: str = "Dinheiro", desconto=0, observacao: str = "", autor=None) -> dict:
    """Atalho: quita o saldo integral do título."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    desc = para_centavos(desconto)
    saldo = int(conta["saldo"] or 0) - desc
    if saldo < 0:
        raise ErroContaReceber("Desconto maior que o saldo devedor.")
    return receber(banco, conta_id, saldo, forma, desconto=desc, observacao=observacao, autor=autor)


def alterar_vencimento(banco: Banco, conta_id: int, novo_vencimento: str, autor=None) -> str:
    """Prorroga a data de vencimento (renegociação)."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    if conta["status"] in ("paga", "cancelada"):
        raise ErroContaReceber("Não é possível alterar o vencimento de uma conta quitada ou cancelada.")
    data = converter_data_br(novo_vencimento)
    if not data:
        raise ErroContaReceber("Data de vencimento inválida. Use DD/MM/AAAA.")
    with banco.transacao():
        banco.atualizar("contas_receber", conta_id, {"vencimento": data, "atualizado_em": agora_iso()})
        recalcular_status(banco, conta_id)
    banco.registrar_log("conta_vencimento_alterado", f"{conta['descricao']} -> {data}", *_autor(autor))
    return data


def cancelar(banco: Banco, conta_id: int, motivo: str = "", autor=None) -> None:
    """Cancela o título (venda cancelada, erro de lançamento ou acordo)."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    if conta["status"] == "cancelada":
        raise ErroContaReceber("Esta conta já está cancelada.")
    if int(conta["valor_pago"] or 0) > 0 and not motivo:
        raise ErroContaReceber(
            "Esta conta já tem recebimentos. Informe um motivo para o cancelamento "
            "(os valores recebidos continuam no histórico do caixa)."
        )
    with banco.transacao():
        banco.atualizar(
            "contas_receber",
            conta_id,
            {"status": "cancelada", "atualizado_em": agora_iso(), "descricao": (conta["descricao"] + (f" [CANCELADA: {motivo}]" if motivo else " [CANCELADA]"))},
        )
    banco.registrar_log("conta_cancelada", f"{conta['cliente_nome']} — {conta['descricao']}", *_autor(autor))


def reabrir(banco: Banco, conta_id: int, autor=None) -> None:
    """Reabre um título cancelado por engano."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    if conta["status"] != "cancelada":
        raise ErroContaReceber("Somente contas canceladas podem ser reabertas.")
    with banco.transacao():
        banco.atualizar("contas_receber", conta_id, {"status": "aberta", "atualizado_em": agora_iso()})
        recalcular_status(banco, conta_id)
    banco.registrar_log("conta_reaberta", conta["descricao"], *_autor(autor))


def excluir(banco: Banco, conta_id: int, autor=None) -> None:
    """Exclusão definitiva — apenas para títulos sem recebimento e não vinculados a venda."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    if int(conta["qtd_recebimentos"] or 0) > 0:
        raise ErroContaReceber("Esta conta tem recebimentos registrados. Use 'Cancelar' em vez de excluir.")
    if conta["venda_id"]:
        raise ErroContaReceber("Esta conta veio de uma venda. Cancele a venda para removê-la.")
    with banco.transacao():
        banco.excluir("contas_receber", conta_id)
    banco.registrar_log("conta_excluida", conta["descricao"], *_autor(autor))


# --------------------------------------------------------------------------------------
# Extrato do cliente
# --------------------------------------------------------------------------------------


def extrato_cliente(banco: Banco, cliente_id: int) -> dict:
    """Extrato de fiado: dados do cliente, títulos abertos, quitados e totais."""
    cliente = clientes_mod.pegar(banco, cliente_id)
    if not cliente:
        raise ErroContaReceber("Cliente não encontrado.")
    abertas = listar(banco, cliente_id=cliente_id, status="pendentes")
    quitadas = banco.consultar(
        SQL_BASE + " WHERE cr.cliente_id=? AND cr.status IN ('paga','cancelada') ORDER BY cr.atualizado_em DESC LIMIT 200",
        (cliente_id,),
    )
    total_aberto = sum(int(c["saldo"] or 0) for c in abertas)
    total_vencido = sum(int(c["saldo"] or 0) for c in abertas if dias_entre(c["vencimento"]) < 0)
    return {
        "cliente": cliente,
        "abertas": abertas,
        "quitadas": quitadas,
        "total_aberto": total_aberto,
        "total_vencido": total_vencido,
        "limite": int(cliente["limite_credito"] or 0),
        "credito_disponivel": clientes_mod.credito_disponivel(cliente),
    }


def por_cliente(banco: Banco) -> list[dict]:
    """Ranking de devedores (usado no relatório de contas a receber)."""
    atualizar_vencidas(banco)
    linhas = banco.consultar(
        """SELECT cr.cliente_id, cr.cliente_nome,
                  COUNT(*) AS qtd,
                  SUM(cr.valor) AS total,
                  SUM(cr.valor - cr.valor_pago - cr.desconto) AS saldo,
                  MIN(cr.vencimento) AS vencimento_mais_antigo
             FROM contas_receber cr
            WHERE cr.status IN ('aberta','parcial','vencida')
            GROUP BY cr.cliente_id, cr.cliente_nome
            ORDER BY saldo DESC"""
    )
    return [
        {
            "cliente_id": l["cliente_id"],
            "cliente_nome": l["cliente_nome"],
            "quantidade": int(l["qtd"] or 0),
            "total": int(l["total"] or 0),
            "saldo": int(l["saldo"] or 0),
            "vencimento_mais_antigo": l["vencimento_mais_antigo"],
            "dias_atraso": max(0, -dias_entre(l["vencimento_mais_antigo"])) if l["vencimento_mais_antigo"] else 0,
        }
        for l in linhas
    ]


def titulo_para_impressao(banco: Banco, conta_id: int) -> dict:
    """Dados formatados para imprimir o comprovante de recebimento."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaReceber("Conta não encontrada.")
    return {
        "numero": conta_id,
        "cliente": conta["cliente_nome"],
        "descricao": conta["descricao"],
        "valor": int(conta["valor"] or 0),
        "pago": int(conta["valor_pago"] or 0),
        "desconto": int(conta["desconto"] or 0),
        "saldo": int(conta["saldo"] or 0),
        "vencimento": conta["vencimento"],
        "status": conta["status"],
        "recebimentos": [
            {"data": r["criado_em"], "valor": int(r["valor"] or 0), "forma": r["forma"], "usuario": r["usuario_nome"]}
            for r in recebimentos(banco, conta_id)
        ],
    }
