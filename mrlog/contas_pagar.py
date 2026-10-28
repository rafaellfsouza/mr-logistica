"""
Contas a pagar — despesas e compras a prazo dos fornecedores.

Complementa o contas a receber: aqui ficam aluguel, energia, salários, fretes e as
compras de mercadoria com prazo. O pagamento sai do caixa do dia (ou fica registrado
sem caixa, quando o caixa está fechado) e o histórico completo é preservado.
"""

from __future__ import annotations

from . import caixa as caixa_mod
from . import fornecedores as fornecedores_mod
from .banco import Banco
from .esquema import CATEGORIAS_DESPESA
from .utils import agora_iso, converter_data_br, dias_entre, formatar_dinheiro, hoje, para_centavos, somar_dias


class ErroContaPagar(Exception):
    """Operação inválida em contas a pagar."""


SQL_BASE = """
    SELECT cp.*,
           (cp.valor - cp.valor_pago) AS saldo,
           CAST(julianday('now','localtime') - julianday(cp.vencimento) AS INTEGER) AS dias_atraso,
           (SELECT COUNT(*) FROM pagamentos_conta pg WHERE pg.conta_id = cp.id) AS qtd_pagamentos
      FROM contas_pagar cp
"""


def _autor(autor) -> tuple[int | None, str]:
    if not autor:
        return None, ""
    try:
        return int(autor["id"]), str(autor["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, str(autor)


def atualizar_vencidas(banco: Banco) -> int:
    cur = banco.executar(
        """UPDATE contas_pagar SET status='vencida', atualizado_em=?
            WHERE status IN ('aberta','parcial') AND date(vencimento) < date(?)""",
        (agora_iso(), hoje()),
    )
    return int(cur.rowcount or 0)


def recalcular_status(banco: Banco, conta_id: int) -> str:
    conta = banco.consultar_uma("SELECT * FROM contas_pagar WHERE id=?", (conta_id,))
    if not conta:
        raise ErroContaPagar("Conta não encontrada.")
    if conta["status"] == "cancelada":
        return "cancelada"
    saldo = int(conta["valor"] or 0) - int(conta["valor_pago"] or 0)
    if saldo <= 0:
        novo = "paga"
    elif int(conta["valor_pago"] or 0) > 0:
        novo = "parcial"
    elif dias_entre(conta["vencimento"]) < 0:
        novo = "vencida"
    else:
        novo = "aberta"
    if novo != conta["status"]:
        banco.atualizar("contas_pagar", conta_id, {"status": novo, "atualizado_em": agora_iso()})
    return novo


def listar(
    banco: Banco,
    status: str = "",
    fornecedor_id: int | None = None,
    categoria: str = "",
    data_inicial: str = "",
    data_final: str = "",
    vencimento_ate: str = "",
    texto: str = "",
    limite: int = 1000,
) -> list:
    atualizar_vencidas(banco)
    condicoes, params = [], []
    if status:
        if status == "pendentes":
            condicoes.append("cp.status IN ('aberta','parcial','vencida')")
        elif status == "atrasadas":
            condicoes.append("cp.status IN ('aberta','parcial','vencida') AND date(cp.vencimento) < date(?)")
            params.append(hoje())
        else:
            condicoes.append("cp.status = ?")
            params.append(status)
    else:
        condicoes.append("cp.status <> 'cancelada'")
    if fornecedor_id:
        condicoes.append("cp.fornecedor_id = ?")
        params.append(int(fornecedor_id))
    if categoria:
        condicoes.append("cp.categoria = ?")
        params.append(categoria)
    if data_inicial:
        condicoes.append("date(cp.criado_em) >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("date(cp.criado_em) <= date(?)")
        params.append(str(data_final)[:10])
    if vencimento_ate:
        condicoes.append("date(cp.vencimento) <= date(?)")
        params.append(str(vencimento_ate)[:10])
    if texto:
        condicoes.append("(cp.descricao LIKE ? OR cp.fornecedor_nome LIKE ? OR cp.observacao LIKE ?)")
        params += [f"%{texto}%"] * 3
    sql = SQL_BASE
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY (cp.status='paga'), cp.vencimento, cp.id LIMIT ?"
    params.append(int(limite))
    return banco.consultar(sql, params)


def pegar(banco: Banco, conta_id: int):
    return banco.consultar_uma(SQL_BASE + " WHERE cp.id=?", (conta_id,))


def pagamentos(banco: Banco, conta_id: int) -> list:
    return banco.consultar("SELECT * FROM pagamentos_conta WHERE conta_id=? ORDER BY id", (conta_id,))


def criar(
    banco: Banco,
    descricao: str,
    valor,
    vencimento: str = "",
    fornecedor_id: int | None = None,
    categoria: str = "Outros",
    observacao: str = "",
    autor=None,
) -> int:
    """Lança uma conta a pagar."""
    descricao = str(descricao or "").strip()
    if not descricao:
        raise ErroContaPagar("Descreva a conta.")
    centavos = para_centavos(valor)
    if centavos <= 0:
        raise ErroContaPagar("O valor deve ser maior que zero.")
    data_venc = converter_data_br(vencimento) or somar_dias(hoje(), 30)
    fornecedor_nome = ""
    if fornecedor_id:
        fornecedor = fornecedores_mod.pegar(banco, fornecedor_id)
        if not fornecedor:
            raise ErroContaPagar("Fornecedor não encontrado.")
        fornecedor_nome = fornecedor["nome"]
    categoria_final = str(categoria or "Outros").strip()
    if categoria_final not in CATEGORIAS_DESPESA:
        categoria_final = "Outros"
    conta_id = banco.inserir(
        "contas_pagar",
        {
            "fornecedor_id": int(fornecedor_id) if fornecedor_id else None,
            "fornecedor_nome": fornecedor_nome,
            "descricao": descricao,
            "categoria": categoria_final,
            "valor": centavos,
            "valor_pago": 0,
            "vencimento": data_venc,
            "status": "aberta",
            "observacao": str(observacao or ""),
            "criado_em": agora_iso(),
            "atualizado_em": agora_iso(),
        },
    )
    banco.registrar_log("conta_pagar_criada", f"{descricao}: {formatar_dinheiro(centavos)}", *_autor(autor))
    return conta_id


def atualizar(banco: Banco, conta_id: int, dados: dict, autor=None) -> int:
    """Edita uma conta ainda não paga."""
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaPagar("Conta não encontrada.")
    if int(conta["valor_pago"] or 0) > 0:
        raise ErroContaPagar("Conta com pagamentos registrados não pode ser editada. Cancele-a e lance uma nova.")
    registro: dict = {}
    if "descricao" in dados:
        descricao = str(dados["descricao"] or "").strip()
        if not descricao:
            raise ErroContaPagar("Descreva a conta.")
        registro["descricao"] = descricao
    if "valor" in dados:
        centavos = para_centavos(dados["valor"])
        if centavos <= 0:
            raise ErroContaPagar("O valor deve ser maior que zero.")
        registro["valor"] = centavos
    if "vencimento" in dados:
        data = converter_data_br(str(dados["vencimento"] or ""))
        if not data:
            raise ErroContaPagar("Vencimento inválido. Use DD/MM/AAAA.")
        registro["vencimento"] = data
    if "categoria" in dados:
        categoria = str(dados["categoria"] or "Outros").strip()
        registro["categoria"] = categoria if categoria in CATEGORIAS_DESPESA else "Outros"
    if "observacao" in dados:
        registro["observacao"] = str(dados["observacao"] or "").strip()
    if "fornecedor_id" in dados:
        fornecedor_id = dados["fornecedor_id"]
        if fornecedor_id in (None, "", 0, "0"):
            registro["fornecedor_id"] = None
            registro["fornecedor_nome"] = ""
        else:
            fornecedor = fornecedores_mod.pegar(banco, fornecedor_id)
            if not fornecedor:
                raise ErroContaPagar("Fornecedor não encontrado.")
            registro["fornecedor_id"] = int(fornecedor_id)
            registro["fornecedor_nome"] = fornecedor["nome"]
    if not registro:
        return conta_id
    registro["atualizado_em"] = agora_iso()
    with banco.transacao():
        banco.atualizar("contas_pagar", conta_id, registro)
        recalcular_status(banco, conta_id)
    banco.registrar_log("conta_pagar_alterada", registro.get("descricao", conta["descricao"]), *_autor(autor))
    return conta_id


def pagar(
    banco: Banco,
    conta_id: int,
    valor,
    forma: str = "Dinheiro",
    observacao: str = "",
    autor=None,
    lancar_no_caixa: bool = True,
) -> dict:
    """Paga (total ou parcialmente) uma conta. O valor sai do caixa do dia."""
    from . import formas_pagamento

    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaPagar("Conta não encontrada.")
    if conta["status"] == "cancelada":
        raise ErroContaPagar("Esta conta foi cancelada.")
    if conta["status"] == "paga":
        raise ErroContaPagar("Esta conta já está quitada.")
    forma_ok = formas_pagamento.normalizar(forma)
    if forma_ok == formas_pagamento.FIADO:
        raise ErroContaPagar("Não é possível pagar uma conta 'no fiado'.")
    saldo = int(conta["saldo"] or 0)
    pago = para_centavos(valor)
    if pago <= 0:
        raise ErroContaPagar("Informe o valor do pagamento.")
    if pago > saldo:
        raise ErroContaPagar(
            f"O valor informado ({formatar_dinheiro(pago)}) é maior que o saldo da conta "
            f"({formatar_dinheiro(saldo)})."
        )
    usuario_id, usuario_nome = _autor(autor)
    caixa_atual = caixa_mod.caixa_aberto(banco)
    # Pagamento em dinheiro só sai se houver dinheiro na gaveta (evita caixa negativo).
    if caixa_atual and lancar_no_caixa and forma_ok == caixa_mod.FORMA_DINHEIRO:
        disponivel = caixa_mod.por_forma(banco, int(caixa_atual["id"])).get(caixa_mod.FORMA_DINHEIRO, {}).get("saldo", 0)
        if pago > disponivel:
            raise ErroContaPagar(
                f"Não há dinheiro suficiente na gaveta para este pagamento "
                f"(disponível: {formatar_dinheiro(disponivel)}). "
                "Faça um suprimento, pague em outra forma (Pix/cartão) ou feche o caixa."
            )
    with banco.transacao():
        banco.atualizar(
            "contas_pagar",
            conta_id,
            {"valor_pago": int(conta["valor_pago"] or 0) + pago, "atualizado_em": agora_iso()},
        )
        banco.inserir(
            "pagamentos_conta",
            {
                "conta_id": conta_id,
                "valor": pago,
                "forma": forma_ok,
                "caixa_id": int(caixa_atual["id"]) if (caixa_atual and lancar_no_caixa) else None,
                "usuario_id": usuario_id,
                "usuario_nome": usuario_nome,
                "observacao": str(observacao or ""),
                "criado_em": agora_iso(),
            },
        )
        if lancar_no_caixa:
            caixa_mod.registrar_saida(
                banco, "Pagamento conta", f"{conta['categoria']}: {conta['descricao']}",
                pago, forma_ok, referencia=str(conta_id), autor=autor, exigir_caixa=False,
            )
        novo_status = recalcular_status(banco, conta_id)
    banco.registrar_log("conta_pagar_paga", f"{conta['descricao']} — {formatar_dinheiro(pago)}", usuario_id, usuario_nome)
    conta_nova = pegar(banco, conta_id)
    return {"pago": pago, "saldo": int(conta_nova["saldo"] or 0), "status": novo_status}


def quitar(banco: Banco, conta_id: int, forma: str = "Dinheiro", observacao: str = "", autor=None) -> dict:
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaPagar("Conta não encontrada.")
    return pagar(banco, conta_id, int(conta["saldo"] or 0), forma, observacao, autor)


def cancelar(banco: Banco, conta_id: int, motivo: str = "", autor=None) -> None:
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaPagar("Conta não encontrada.")
    if conta["status"] == "cancelada":
        raise ErroContaPagar("Esta conta já está cancelada.")
    if int(conta["valor_pago"] or 0) > 0:
        raise ErroContaPagar(
            "Esta conta tem pagamentos registrados. Estorne os pagamentos ou ajuste o valor."
        )
    with banco.transacao():
        banco.atualizar(
            "contas_pagar",
            conta_id,
            {
                "status": "cancelada",
                "atualizado_em": agora_iso(),
                "observacao": (str(conta["observacao"] or "") + (f" | Cancelada: {motivo}" if motivo else " | Cancelada")).strip(" |"),
            },
        )
    banco.registrar_log("conta_pagar_cancelada", conta["descricao"], *_autor(autor))


def excluir(banco: Banco, conta_id: int, autor=None) -> None:
    conta = pegar(banco, conta_id)
    if not conta:
        raise ErroContaPagar("Conta não encontrada.")
    if int(conta["qtd_pagamentos"] or 0) > 0:
        raise ErroContaPagar("Esta conta tem pagamentos registrados. Use 'Cancelar' em vez de excluir.")
    with banco.transacao():
        banco.excluir("contas_pagar", conta_id)
    banco.registrar_log("conta_pagar_excluida", conta["descricao"], *_autor(autor))


def resumo(banco: Banco) -> dict:
    atualizar_vencidas(banco)
    linha = banco.consultar_uma(
        """SELECT
             COALESCE(SUM(CASE WHEN status IN ('aberta','parcial','vencida') THEN valor - valor_pago ELSE 0 END),0) AS a_pagar,
             COALESCE(SUM(CASE WHEN status='vencida' THEN valor - valor_pago ELSE 0 END),0) AS vencido,
             COALESCE(SUM(CASE WHEN status IN ('aberta','parcial','vencida') THEN 1 ELSE 0 END),0) AS qtd_abertas,
             COALESCE(SUM(CASE WHEN status='vencida' THEN 1 ELSE 0 END),0) AS qtd_vencidas,
             COALESCE(SUM(valor_pago),0) AS pago_total
           FROM contas_pagar"""
    )
    mes = banco.consultar_valor(
        "SELECT COALESCE(SUM(valor),0) FROM pagamentos_conta WHERE strftime('%Y-%m', criado_em) = strftime('%Y-%m','now','localtime')"
    )
    vencendo = banco.consultar_valor(
        """SELECT COALESCE(SUM(valor - valor_pago),0) FROM contas_pagar
            WHERE status IN ('aberta','parcial') AND date(vencimento) BETWEEN date(?) AND date(?)""",
        (hoje(), somar_dias(hoje(), 7)),
    )
    return {
        "a_pagar": int(linha["a_pagar"] or 0),
        "vencido": int(linha["vencido"] or 0),
        "qtd_abertas": int(linha["qtd_abertas"] or 0),
        "qtd_vencidas": int(linha["qtd_vencidas"] or 0),
        "pago_total": int(linha["pago_total"] or 0),
        "pago_mes": int(mes or 0),
        "vencendo_7_dias": int(vencendo or 0),
    }


def por_categoria(banco: Banco, data_inicial: str = "", data_final: str = "") -> list[dict]:
    """Despesas agrupadas por categoria, em **regime de caixa** (pela data do pagamento).

    É o número que fecha com o fluxo de caixa e com o resultado do período.
    """
    condicoes, params = ["cp.status <> 'cancelada'"], []
    if data_inicial:
        condicoes.append("date(pg.criado_em) >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("date(pg.criado_em) <= date(?)")
        params.append(str(data_final)[:10])
    linhas = banco.consultar(
        f"""SELECT cp.categoria,
                   COUNT(pg.id) AS qtd,
                   COALESCE(SUM(pg.valor),0) AS total,
                   COALESCE(SUM(pg.valor),0) AS pago
              FROM pagamentos_conta pg
              JOIN contas_pagar cp ON cp.id = pg.conta_id
             WHERE {' AND '.join(condicoes)}
             GROUP BY cp.categoria ORDER BY total DESC""",
        params,
    )
    return [
        {"categoria": l["categoria"], "quantidade": int(l["qtd"] or 0), "total": int(l["total"] or 0), "pago": int(l["pago"] or 0)}
        for l in linhas
    ]


def por_categoria_regime_competencia(banco: Banco, data_inicial: str = "", data_final: str = "") -> list[dict]:
    """Mesma visão, mas pelo **vencimento** (o que foi lançado no período)."""
    condicoes, params = ["cp.status <> 'cancelada'"], []
    if data_inicial:
        condicoes.append("date(cp.vencimento) >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("date(cp.vencimento) <= date(?)")
        params.append(str(data_final)[:10])
    linhas = banco.consultar(
        f"""SELECT cp.categoria, COUNT(*) AS qtd, SUM(cp.valor) AS total, SUM(cp.valor_pago) AS pago
              FROM contas_pagar cp WHERE {' AND '.join(condicoes)}
             GROUP BY cp.categoria ORDER BY total DESC""",
        params,
    )
    return [
        {"categoria": l["categoria"], "quantidade": int(l["qtd"] or 0), "total": int(l["total"] or 0), "pago": int(l["pago"] or 0)}
        for l in linhas
    ]


def por_fornecedor(banco: Banco) -> list[dict]:
    linhas = banco.consultar(
        """SELECT cp.fornecedor_id, cp.fornecedor_nome, COUNT(*) AS qtd,
                  SUM(cp.valor) AS total, SUM(cp.valor - cp.valor_pago) AS saldo
             FROM contas_pagar cp
            WHERE cp.status IN ('aberta','parcial','vencida')
            GROUP BY cp.fornecedor_id, cp.fornecedor_nome ORDER BY saldo DESC"""
    )
    return [
        {
            "fornecedor_id": l["fornecedor_id"],
            "fornecedor_nome": l["fornecedor_nome"] or "(sem fornecedor)",
            "quantidade": int(l["qtd"] or 0),
            "total": int(l["total"] or 0),
            "saldo": int(l["saldo"] or 0),
        }
        for l in linhas
    ]
