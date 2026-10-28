"""
Caixa diário: abertura, fechamento, sangria, suprimento, despesas e posição.

Fluxo (igual ao PDV do Protheus/SAP B1, só que simplificado):

1. **Abertura** — o operador informa o fundo de troco. Só pode existir **um caixa
   aberto** por vez.
2. **Movimentação** — cada venda, recebimento de fiado, despesa, sangria (retirada)
   ou suprimento (reforço de troco) grava uma linha em ``caixa_movimentos`` com a
   forma de pagamento.
3. **Fechamento** — o operador conta o dinheiro e informa o valor. O sistema
   compara com o valor esperado e registra a diferença (quebra de caixa).

O "valor do sistema" considera apenas **dinheiro físico**: abertura + vendas em
dinheiro (já descontado o troco) + recebimentos em dinheiro + suprimentos
− sangrias − despesas em dinheiro − devoluções em dinheiro. Pix e cartão aparecem
separados na posição do caixa, pois não ficam na gaveta.
"""

from __future__ import annotations

from typing import Any

from .banco import Banco
from .utils import agora_iso, converter_data_br, formatar_dinheiro, hoje, para_centavos

#: Forma de pagamento que entra fisicamente na gaveta.
FORMA_DINHEIRO = "Dinheiro"

CATEGORIAS_ENTRADA = ("Abertura", "Venda", "Recebimento fiado", "Suprimento", "Outras entradas")
CATEGORIAS_SAIDA = ("Sangria", "Despesa", "Pagamento conta", "Devolução", "Outras saídas")

CATEGORIAS_MOVIMENTO = CATEGORIAS_ENTRADA + CATEGORIAS_SAIDA


class ErroCaixa(Exception):
    """Operação de caixa inválida."""


def _autor(autor) -> tuple[int | None, str]:
    if not autor:
        return None, ""
    try:
        return int(autor["id"]), str(autor["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, str(autor)


# --------------------------------------------------------------------------------------
# Consulta
# --------------------------------------------------------------------------------------


def caixa_aberto(banco: Banco):
    """Retorna o caixa aberto (ou ``None``)."""
    return banco.consultar_uma("SELECT * FROM caixa_diario WHERE status='aberto' ORDER BY id DESC LIMIT 1")


def exigir_aberto(banco: Banco):
    """Devolve o caixa aberto ou dispara erro com orientação."""
    atual = caixa_aberto(banco)
    if not atual:
        raise ErroCaixa(
            "Nenhum caixa aberto. Abra o caixa (menu Financeiro > Caixa) para registrar as movimentações."
        )
    return atual


def pegar(banco: Banco, caixa_id: int):
    return banco.consultar_uma("SELECT * FROM caixa_diario WHERE id=?", (caixa_id,))


def listar(banco: Banco, data_inicial: str = "", data_final: str = "", apenas_abertos: bool = False, limite: int = 200) -> list:
    sql = """SELECT c.*,
                    (SELECT COUNT(*) FROM vendas v WHERE v.caixa_id=c.id AND v.status<>'cancelada') AS qtd_vendas,
                    (SELECT COALESCE(SUM(v.total),0) FROM vendas v WHERE v.caixa_id=c.id AND v.status<>'cancelada') AS total_vendas,
                    (SELECT COALESCE(SUM(CASE WHEN m.tipo='entrada' THEN m.valor ELSE -m.valor END),0)
                       FROM caixa_movimentos m WHERE m.caixa_id=c.id AND m.forma='Dinheiro') AS dinheiro_movimentado
               FROM caixa_diario c"""
    condicoes, params = [], []
    if data_inicial:
        condicoes.append("c.data >= ?")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("c.data <= ?")
        params.append(str(data_final)[:10])
    if apenas_abertos:
        condicoes.append("c.status='aberto'")
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY c.id DESC LIMIT ?"
    params.append(int(limite))
    return banco.consultar(sql, params)


def movimentos(banco: Banco, caixa_id: int, categoria: str = "", forma: str = "", tipo: str = "") -> list:
    sql = "SELECT * FROM caixa_movimentos WHERE caixa_id=?"
    params: list[Any] = [caixa_id]
    if categoria:
        sql += " AND categoria=?"
        params.append(categoria)
    if forma:
        sql += " AND forma=?"
        params.append(forma)
    if tipo:
        sql += " AND tipo=?"
        params.append(tipo)
    sql += " ORDER BY id"
    return banco.consultar(sql, params)


# --------------------------------------------------------------------------------------
# Abertura / fechamento
# --------------------------------------------------------------------------------------


def abrir(banco: Banco, valor_abertura=0, observacao: str = "", data: str = "", autor=None) -> int:
    """Abre o caixa do dia com o fundo de troco informado."""
    if caixa_aberto(banco):
        raise ErroCaixa("Já existe um caixa aberto. Feche-o antes de abrir outro.")
    valor = para_centavos(valor_abertura)
    if valor < 0:
        raise ErroCaixa("O valor de abertura não pode ser negativo.")
    dia = converter_data_br(data) or hoje()
    usuario_id, usuario_nome = _autor(autor)
    with banco.transacao():
        caixa_id = banco.inserir(
            "caixa_diario",
            {
                "data": dia,
                "usuario_id": usuario_id,
                "usuario_nome": usuario_nome,
                "valor_abertura": valor,
                "status": "aberto",
                "abertura_em": agora_iso(),
                "observacao": str(observacao or ""),
            },
        )
        if valor > 0:
            _registrar(banco, caixa_id, "entrada", "Abertura", "Fundo de troco / abertura de caixa", valor,
                       FORMA_DINHEIRO, referencia=str(caixa_id), autor=autor)
    banco.registrar_log("caixa_aberto", f"Abertura {formatar_dinheiro(valor)}", usuario_id, usuario_nome)
    return caixa_id


def fechar(banco: Banco, caixa_id: int, valor_contado, observacao: str = "", autor=None) -> dict:
    """Fecha o caixa comparando a contagem real com o valor esperado pelo sistema."""
    caixa = pegar(banco, caixa_id)
    if not caixa:
        raise ErroCaixa("Caixa não encontrado.")
    if caixa["status"] != "aberto":
        raise ErroCaixa("Este caixa já foi fechado.")
    contado = para_centavos(valor_contado)
    if contado < 0:
        raise ErroCaixa("O valor contado não pode ser negativo.")
    sistema = valor_sistema(banco, caixa_id)
    diferenca = contado - sistema
    usuario_id, usuario_nome = _autor(autor)
    with banco.transacao():
        banco.atualizar(
            "caixa_diario",
            caixa_id,
            {
                "valor_fechamento": contado,
                "valor_sistema": sistema,
                "diferenca": diferenca,
                "status": "fechado",
                "fechamento_em": agora_iso(),
                "observacao": str(observacao or caixa["observacao"] or ""),
            },
        )
    banco.registrar_log(
        "caixa_fechado",
        f"Sistema {formatar_dinheiro(sistema)} | Contado {formatar_dinheiro(contado)} | Diferença {formatar_dinheiro(diferenca)}",
        usuario_id, usuario_nome,
    )
    return {"valor_sistema": sistema, "valor_contado": contado, "diferenca": diferenca, "posicao": posicao(banco, caixa_id)}


def _registrar(banco: Banco, caixa_id: int, tipo: str, categoria: str, descricao: str, valor: int,
               forma: str = FORMA_DINHEIRO, referencia: str = "", autor=None) -> int:
    if tipo not in ("entrada", "saida"):
        raise ErroCaixa("Tipo de movimento inválido (use 'entrada' ou 'saida').")
    if categoria not in CATEGORIAS_MOVIMENTO:
        raise ErroCaixa(f"Categoria de caixa inválida: '{categoria}'.")
    valor = int(valor or 0)
    if valor < 0:
        raise ErroCaixa("Valor do movimento não pode ser negativo.")
    usuario_id, usuario_nome = _autor(autor)
    return banco.inserir(
        "caixa_movimentos",
        {
            "caixa_id": int(caixa_id),
            "tipo": tipo,
            "categoria": categoria,
            "descricao": str(descricao or categoria),
            "valor": valor,
            "forma": str(forma or FORMA_DINHEIRO),
            "referencia": str(referencia or ""),
            "usuario_id": usuario_id,
            "usuario_nome": usuario_nome,
            "criado_em": agora_iso(),
        },
    )


def _caixa_alvo(banco: Banco, caixa_id: int | None, exigir_caixa: bool) -> int | None:
    """Resolve em qual caixa lançar: o informado, o aberto, ou nenhum (com erro)."""
    if caixa_id:
        caixa = pegar(banco, int(caixa_id))
        if not caixa:
            raise ErroCaixa("Caixa não encontrado.")
        return int(caixa["id"])
    caixa = caixa_aberto(banco)
    if caixa:
        return int(caixa["id"])
    if exigir_caixa:
        exigir_aberto(banco)
    return None


def registrar_entrada(banco: Banco, categoria: str, descricao: str, valor_centavos: int, forma: str = FORMA_DINHEIRO,
                      referencia: str = "", autor=None, exigir_caixa: bool = True,
                      caixa_id: int | None = None) -> int | None:
    """Entrada genérica no caixa (usada por vendas, recebimentos e suprimentos).

    ``valor_centavos`` é inteiro em centavos. Valores <= 0 são ignorados.
    """
    centavos = int(valor_centavos or 0)
    if centavos <= 0:
        return None
    alvo = _caixa_alvo(banco, caixa_id, exigir_caixa)
    if not alvo:
        return None
    return _registrar(banco, alvo, "entrada", categoria, descricao, centavos, forma, referencia, autor)


def registrar_saida(banco: Banco, categoria: str, descricao: str, valor_centavos: int, forma: str = FORMA_DINHEIRO,
                    referencia: str = "", autor=None, exigir_caixa: bool = True,
                    caixa_id: int | None = None) -> int | None:
    """Saída genérica do caixa (sangria, despesa, devolução, pagamento de conta)."""
    centavos = int(valor_centavos or 0)
    if centavos <= 0:
        return None
    alvo = _caixa_alvo(banco, caixa_id, exigir_caixa)
    if not alvo:
        return None
    return _registrar(banco, alvo, "saida", categoria, descricao, centavos, forma, referencia, autor)


def sangria(banco: Banco, valor, motivo: str = "", autor=None) -> int:
    """Retirada de dinheiro do caixa (ex.: depósito bancário, segurança)."""
    caixa = exigir_aberto(banco)
    centavos = para_centavos(valor)
    if centavos <= 0:
        raise ErroCaixa("Informe um valor maior que zero para a sangria.")
    disponivel = por_forma(banco, caixa["id"]).get(FORMA_DINHEIRO, {}).get("saldo", 0)
    if centavos > disponivel:
        raise ErroCaixa(
            f"Não há dinheiro suficiente na gaveta. Disponível: {formatar_dinheiro(disponivel)}."
        )
    movimento_id = _registrar(
        banco, caixa["id"], "saida", "Sangria", motivo or "Sangria (retirada de dinheiro)",
        centavos, FORMA_DINHEIRO, referencia="", autor=autor,
    )
    banco.registrar_log("caixa_sangria", formatar_dinheiro(centavos), *_autor(autor))
    return movimento_id


def suprimento(banco: Banco, valor, motivo: str = "", autor=None) -> int:
    """Reforço de troco: entrada de dinheiro que não vem de venda."""
    caixa = exigir_aberto(banco)
    centavos = para_centavos(valor)
    if centavos <= 0:
        raise ErroCaixa("Informe um valor maior que zero para o suprimento.")
    movimento_id = _registrar(
        banco, caixa["id"], "entrada", "Suprimento", motivo or "Suprimento (reforço de troco)",
        centavos, FORMA_DINHEIRO, referencia="", autor=autor,
    )
    banco.registrar_log("caixa_suprimento", formatar_dinheiro(centavos), *_autor(autor))
    return movimento_id


def lancar_despesa(banco: Banco, descricao: str, valor, categoria_despesa: str = "Outros",
                   forma: str = FORMA_DINHEIRO, autor=None) -> int:
    """Despesa paga na hora, saindo do caixa (não passa por contas a pagar)."""
    caixa = exigir_aberto(banco)
    centavos = para_centavos(valor)
    if centavos <= 0:
        raise ErroCaixa("Informe o valor da despesa.")
    if not str(descricao or "").strip():
        raise ErroCaixa("Descreva a despesa.")
    if forma == FORMA_DINHEIRO:
        disponivel = por_forma(banco, caixa["id"]).get(FORMA_DINHEIRO, {}).get("saldo", 0)
        if centavos > disponivel:
            raise ErroCaixa(
                f"Não há dinheiro suficiente na gaveta para esta despesa. Disponível: {formatar_dinheiro(disponivel)}."
            )
    movimento_id = _registrar(
        banco, caixa["id"], "saida", "Despesa", f"{categoria_despesa}: {descricao}".strip(": "),
        centavos, forma, referencia="", autor=autor,
    )
    banco.registrar_log("caixa_despesa", f"{descricao} — {formatar_dinheiro(centavos)}", *_autor(autor))
    return movimento_id


def registrar_venda_no_caixa(banco: Banco, caixa_id: int | None, venda_id: int, numero: int,
                              pagamentos: list[dict], troco: int, autor=None) -> None:
    """Grava no caixa cada forma de pagamento de uma venda (descontando o troco em dinheiro).

    O **fiado não entra no caixa**: ele vira conta a receber e só aparece aqui no dia
    em que for efetivamente recebido (categoria "Recebimento fiado").
    """
    if not caixa_id:
        return
    from .esquema import FORMA_FIADO

    for pg in pagamentos:
        valor = int(pg.get("valor") or 0)
        forma = str(pg.get("forma") or FORMA_DINHEIRO)
        if valor <= 0 or forma == FORMA_FIADO:
            continue
        if forma == FORMA_DINHEIRO and troco > 0:
            valor -= troco  # o troco volta para a gaveta
            troco = 0
        if valor <= 0:
            continue
        _registrar(
            banco, caixa_id, "entrada", "Venda", f"Venda nº {numero:06d}", valor, forma,
            referencia=str(venda_id), autor=autor,
        )


def registrar_devolucao_no_caixa(banco: Banco, caixa_id: int | None, venda_numero: int, valor: int,
                                 forma: str = FORMA_DINHEIRO, autor=None) -> None:
    """Estorno de uma devolução/cancelamento (saída do caixa)."""
    if not caixa_id or int(valor or 0) <= 0:
        return
    _registrar(
        banco, caixa_id, "saida", "Devolução", f"Devolução da venda nº {venda_numero:06d}", int(valor),
        forma, referencia="", autor=autor,
    )


# --------------------------------------------------------------------------------------
# Posição / fechamento
# --------------------------------------------------------------------------------------


def por_categoria(banco: Banco, caixa_id: int) -> list[dict]:
    linhas = banco.consultar(
        """SELECT categoria, tipo, COALESCE(SUM(valor),0) AS total, COUNT(*) AS qtd
             FROM caixa_movimentos WHERE caixa_id=? GROUP BY categoria, tipo ORDER BY tipo DESC, total DESC""",
        (caixa_id,),
    )
    return [
        {"categoria": l["categoria"], "tipo": l["tipo"], "total": int(l["total"] or 0), "quantidade": int(l["qtd"] or 0)}
        for l in linhas
    ]


def por_forma(banco: Banco, caixa_id: int) -> dict[str, dict]:
    """Totais por forma de pagamento (dinheiro, Pix, débito, crédito)."""
    linhas = banco.consultar(
        """SELECT forma, COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor ELSE -valor END),0) AS saldo,
                  COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor ELSE 0 END),0) AS entradas,
                  COALESCE(SUM(CASE WHEN tipo='saida' THEN valor ELSE 0 END),0) AS saidas
             FROM caixa_movimentos WHERE caixa_id=? GROUP BY forma""",
        (caixa_id,),
    )
    return {
        str(l["forma"] or FORMA_DINHEIRO): {
            "saldo": int(l["saldo"] or 0),
            "entradas": int(l["entradas"] or 0),
            "saidas": int(l["saidas"] or 0),
        }
        for l in linhas
    }


def valor_sistema(banco: Banco, caixa_id: int) -> int:
    """Saldo esperado **na gaveta** (apenas dinheiro físico)."""
    valor = banco.consultar_valor(
        """SELECT COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor ELSE -valor END),0)
             FROM caixa_movimentos WHERE caixa_id=? AND forma=?""",
        (caixa_id, FORMA_DINHEIRO),
    )
    return int(valor or 0)


def posicao(banco: Banco, caixa_id: int) -> dict:
    """Resumo completo do caixa: valores por forma, por categoria e total do sistema."""
    caixa = pegar(banco, caixa_id)
    if not caixa:
        raise ErroCaixa("Caixa não encontrado.")
    formas = por_forma(banco, caixa_id)
    categorias = por_categoria(banco, caixa_id)
    vendas = banco.consultar_uma(
        """SELECT COUNT(*) AS qtd, COALESCE(SUM(total),0) AS total, COALESCE(SUM(lucro),0) AS lucro
             FROM vendas WHERE caixa_id=? AND status<>'cancelada'""",
        (caixa_id,),
    )
    return {
        "caixa": caixa,
        "abertura": int(caixa["valor_abertura"] or 0),
        "formas": formas,
        "categorias": categorias,
        "valor_sistema": valor_sistema(banco, caixa_id),
        "total_recebido": sum(f["entradas"] for f in formas.values()),
        "total_pago": sum(f["saidas"] for f in formas.values()),
        "qtd_vendas": int(vendas["qtd"] or 0),
        "total_vendas": int(vendas["total"] or 0),
        "lucro_vendas": int(vendas["lucro"] or 0),
        "status": caixa["status"],
        "fechamento": int(caixa["valor_fechamento"] or 0),
        "diferenca": int(caixa["diferenca"] or 0),
    }


def resumo_dia(banco: Banco, data: str | None = None) -> dict:
    """Indicadores do dia (usados no painel e na tela de caixa)."""
    dia = converter_data_br(data) if data else hoje()
    caixa = banco.consultar_uma("SELECT * FROM caixa_diario WHERE data=? ORDER BY id DESC LIMIT 1", (dia,))
    vendas = banco.consultar_uma(
        """SELECT COUNT(*) AS qtd, COALESCE(SUM(total),0) AS total, COALESCE(SUM(lucro),0) AS lucro,
                  COALESCE(AVG(total),0) AS ticket
             FROM vendas WHERE data_venda=? AND status<>'cancelada'""",
        (dia,),
    )
    return {
        "data": dia,
        "caixa_aberto": bool(caixa and caixa["status"] == "aberto"),
        "caixa_id": int(caixa["id"]) if caixa else None,
        "qtd_vendas": int(vendas["qtd"] or 0),
        "total_vendas": int(vendas["total"] or 0),
        "lucro": int(vendas["lucro"] or 0),
        "ticket_medio": int(round(float(vendas["ticket"] or 0))),
        "valor_sistema": valor_sistema(banco, caixa["id"]) if caixa else 0,
    }


def cancelar_movimento(banco: Banco, movimento_id: int, autor=None) -> None:
    """Estorna um lançamento do caixa (erro de digitação, por exemplo)."""
    movimento = banco.consultar_uma("SELECT * FROM caixa_movimentos WHERE id=?", (movimento_id,))
    if not movimento:
        raise ErroCaixa("Movimento não encontrado.")
    caixa = pegar(banco, movimento["caixa_id"])
    if caixa and caixa["status"] == "fechado":
        raise ErroCaixa("Não é possível alterar um movimento de caixa já fechado.")
    if movimento["categoria"] in ("Venda", "Abertura"):
        raise ErroCaixa(
            "Movimentos de venda e abertura são gerados automaticamente. "
            "Cancele/devolva a venda pela tela de Vendas."
        )
    with banco.transacao():
        banco.excluir("caixa_movimentos", movimento_id)
    banco.registrar_log(
        "caixa_movimento_cancelado",
        f"{movimento['categoria']} {formatar_dinheiro(movimento['valor'])}",
        *_autor(autor),
    )
