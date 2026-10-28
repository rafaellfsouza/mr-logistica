"""
Estoque: entradas, saídas, ajustes de inventário, histórico, lotes e validade.

Princípios:

1. **Toda alteração de saldo gera uma movimentação.** O campo
   ``produtos.estoque_atual`` é mantido por *triggers* do próprio banco, somando
   entradas e subtraindo saídas — assim ele nunca fica diferente do histórico.
2. **Custo médio ponderado.** Cada entrada recalcula o preço de custo do produto.
3. **Lotes e validade** são opcionais por produto. Quando o produto controla lote,
   a saída consome automaticamente pelo critério **PVPS/FEFO** (o que vence primeiro
   sai primeiro), e a devolução de cliente devolve a mercadoria ao lote de origem.
4. Nada é apagado: o histórico completo fica na tabela ``movimentacoes`` e pode ser
   filtrado por produto, período, motivo, lote e usuário.
"""

from __future__ import annotations

from typing import Any

from . import produtos as produtos_mod
from . import unidades
from .banco import Banco
from .esquema import MOTIVOS_AJUSTE, MOTIVOS_ENTRADA, MOTIVOS_SAIDA
from .utils import agora_iso, dias_entre, formatar_data, hoje, somar_dias


class ErroEstoque(Exception):
    """Operação de estoque inválida (saldo insuficiente, unidade errada etc.)."""


MOTIVOS = {**MOTIVOS_ENTRADA, **MOTIVOS_SAIDA, **MOTIVOS_AJUSTE}

#: Motivos que aumentam o estoque.
MOTIVOS_ENTRAM = {"compra", "devolucao_cliente", "transferencia_entrada", "producao", "ajuste_positivo",
                  "inventario_inicial", "ajuste_inventario", "correcao", "outros"}

LIMITE_MOVIMENTACAO = 1_000_000.0


# --------------------------------------------------------------------------------------
# Consultas básicas
# --------------------------------------------------------------------------------------


def saldo(banco: Banco, produto_id: int) -> float:
    """Estoque atual do produto, na unidade base."""
    valor = banco.consultar_valor("SELECT estoque_atual FROM produtos WHERE id=?", (produto_id,))
    return float(valor or 0.0)


def saldo_formatado(banco: Banco, produto) -> str:
    """Saldo com a unidade: ``12 kg`` / ``3 un``."""
    return unidades.formatar(saldo(banco, produto["id"]), produto["unidade_base"] or "un")


def motivo_descricao(motivo: str) -> str:
    return MOTIVOS.get(str(motivo or ""), str(motivo or ""))


def _tipo_do_motivo(motivo: str) -> str:
    if motivo in MOTIVOS_ENTRADA:
        return "entrada"
    if motivo in MOTIVOS_SAIDA:
        return "saida"
    if motivo in MOTIVOS_AJUSTE:
        return "ajuste"
    raise ErroEstoque(f"Motivo de movimentação desconhecido: '{motivo}'.")


def _autor(autor) -> tuple[int | None, str]:
    if not autor:
        return None, ""
    try:
        return int(autor["id"]), str(autor["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, str(autor)


def _validar_produto(banco: Banco, produto_id: int):
    produto = produtos_mod.pegar(banco, produto_id)
    if not produto:
        raise ErroEstoque(f"Produto não encontrado (id {produto_id}).")
    return produto


def _quantidade_valida(produto, quantidade: float, unidade: str | None, banco: Banco) -> tuple[float, str]:
    """Converte a quantidade informada para a unidade base e valida os limites."""
    unidade_base = str(produto["unidade_base"] or "un")
    unidade_usada = str(unidade or unidade_base).strip().lower() or unidade_base
    try:
        qtd = float(quantidade)
    except (TypeError, ValueError):
        raise ErroEstoque("Quantidade inválida.") from None
    if qtd != qtd or qtd in (float("inf"), float("-inf")):
        raise ErroEstoque("Quantidade inválida.")
    if abs(qtd) > LIMITE_MOVIMENTACAO:
        raise ErroEstoque("Quantidade muito alta (máximo 1.000.000).")
    if unidade_usada != unidade_base:
        qtd = unidades.converter_para_base(produto, qtd, unidade_usada, banco)
    qtd = unidades.arredondar(qtd)
    return qtd, unidade_usada


# --------------------------------------------------------------------------------------
# Movimentação (núcleo)
# --------------------------------------------------------------------------------------


def registrar_movimento(
    banco: Banco,
    produto_id: int,
    quantidade_base: float,
    motivo: str,
    tipo: str | None = None,
    unidade: str | None = None,
    custo_unitario: int = 0,
    lote_id: int | None = None,
    lote_numero: str = "",
    validade: str = "",
    documento_id: int | None = None,
    observacao: str = "",
    autor=None,
    lote_ref: int | None = None,
) -> int:
    """Grava uma movimentação e devolve o ``id``.

    * ``quantidade_base`` é sempre **positiva** e já convertida para a unidade de
      estoque; o sinal é definido pelo ``tipo`` (entrada/saida/ajuste).
    * Quando ``lote_id`` é informado, o saldo do lote é atualizado automaticamente
      pelo *trigger* ``trg_lote_mov_ins``.
    * ``lote_ref`` é apenas uma referência informativa (não altera saldo do lote).
    """
    produto = _validar_produto(banco, produto_id)
    tipo_final = (tipo or _tipo_do_motivo(motivo)).lower()
    if tipo_final not in ("entrada", "saida", "ajuste"):
        raise ErroEstoque(f"Tipo de movimentação inválido: '{tipo}'.")
    qtd = abs(float(quantidade_base))
    if qtd <= 1e-9:
        raise ErroEstoque("A quantidade da movimentação deve ser maior que zero.")
    usuario_id, usuario_nome = _autor(autor)
    custo = int(custo_unitario or 0)
    movimento_id = banco.inserir(
        "movimentacoes",
        {
            "produto_id": int(produto_id),
            "lote_id": int(lote_id) if lote_id else None,
            "tipo": tipo_final,
            "motivo": str(motivo),
            "quantidade": qtd,
            "unidade": str(produto["unidade_base"] or "un"),
            "custo_unitario": custo,
            "valor_total": int(round(qtd * custo)),
            "saldo_apos": None,  # preenchido logo abaixo
            "documento_id": int(documento_id) if documento_id else None,
            "lote_numero": str(lote_numero or ""),
            "lote_ref": int(lote_ref) if lote_ref else None,
            "validade": str(validade or ""),
            "usuario_id": usuario_id,
            "usuario_nome": usuario_nome,
            "observacao": str(observacao or ""),
            "criado_em": agora_iso(),
        },
    )
    banco.atualizar("movimentacoes", movimento_id, {"saldo_apos": saldo(banco, produto_id)})
    return movimento_id


# --------------------------------------------------------------------------------------
# Lotes
# --------------------------------------------------------------------------------------


def criar_ou_atualizar_lote(
    banco: Banco,
    produto_id: int,
    quantidade: float,
    numero: str = "",
    validade: str = "",
    custo_unitario: int = 0,
    fornecedor_id=None,
    documento: str = "",
    observacao: str = "",
    forcar_inicial: float = 0.0,
) -> int | None:
    """Cria o lote (ou soma a quantidade num lote já existente com o mesmo nº/validade).

    Use ``quantidade=0`` com ``forcar_inicial`` quando o saldo do lote for ser
    lançado pela própria movimentação (via trigger) — assim não há dupla contagem.
    """
    if quantidade <= 0 and forcar_inicial <= 0:
        return None
    numero = str(numero or "").strip()
    validade = str(validade or "").strip() or None
    existente = banco.consultar_uma(
        """SELECT * FROM lotes
            WHERE produto_id=?
              AND COALESCE(numero,'') = COALESCE(?, '')
              AND COALESCE(validade,'') = COALESCE(?, '')""",
        (produto_id, numero, validade),
    )
    if existente:
        banco.atualizar(
            "lotes",
            existente["id"],
            {
                "quantidade_inicial": float(existente["quantidade_inicial"] or 0) + float(quantidade),
                "quantidade_atual": float(existente["quantidade_atual"] or 0) + float(quantidade),
                "custo_unitario": int(custo_unitario or existente["custo_unitario"] or 0),
                "fornecedor_id": fornecedor_id or existente["fornecedor_id"],
                "documento": str(documento or existente["documento"] or ""),
                "atualizado_em": agora_iso(),
            },
        )
        return int(existente["id"])
    return banco.inserir(
        "lotes",
        {
            "produto_id": int(produto_id),
            "numero": numero or None,
            "validade": validade,
            "quantidade_inicial": max(float(quantidade), float(forcar_inicial or 0)),
            "quantidade_atual": float(max(0.0, quantidade)),
            "custo_unitario": int(custo_unitario or 0),
            "fornecedor_id": int(fornecedor_id) if fornecedor_id else None,
            "documento": str(documento or ""),
            "observacao": str(observacao or ""),
            "criado_em": agora_iso(),
            "atualizado_em": agora_iso(),
        },
    )


def lotes_do_produto(banco: Banco, produto_id: int, apenas_com_saldo: bool = True, incluir_vencidos: bool = True) -> list:
    """Lotes de um produto, ordenados pelo que vence primeiro (FEFO)."""
    sql = """SELECT l.*,
                    CAST(julianday(COALESCE(NULLIF(l.validade,''), '9999-12-31')) - julianday('now','localtime') AS INTEGER) AS dias_para_vencer
               FROM lotes l
              WHERE l.produto_id=?"""
    if apenas_com_saldo:
        sql += " AND l.quantidade_atual > 0"
    if not incluir_vencidos:
        sql += " AND (l.validade IS NULL OR l.validade = '' OR l.validade >= ?)"
    sql += " ORDER BY (l.validade IS NULL OR l.validade=''), l.validade, l.id"
    params: list[Any] = [produto_id]
    if not incluir_vencidos:
        params.append(hoje())
    return banco.consultar(sql, params)


def lote_por_numero(banco: Banco, produto_id: int, numero: str, validade: str = ""):
    return banco.consultar_uma(
        """SELECT * FROM lotes WHERE produto_id=? AND COALESCE(numero,'')=COALESCE(?,'')
              AND COALESCE(validade,'')=COALESCE(?,'') LIMIT 1""",
        (produto_id, str(numero or "").strip(), str(validade or "").strip() or None),
    )


def _consumir_lotes(banco: Banco, produto_id: int, quantidade: float, motivo: str, lote_id: int | None,
                    custo_unitario: int, documento_id: int | None, observacao: str, autor,
                    proibir_vencido: bool = False) -> tuple[float, int]:
    """Consome a quantidade dos lotes (FEFO) gravando um movimento por lote.

    Devolve ``(quantidade consumida, id da última movimentação)``.
    """
    if lote_id:
        lote = banco.consultar_uma("SELECT * FROM lotes WHERE id=? AND produto_id=?", (lote_id, produto_id))
        if not lote:
            raise ErroEstoque("Lote não encontrado para este produto.")
        disponivel = float(lote["quantidade_atual"] or 0)
        if disponivel + 1e-9 < quantidade:
            from .utils import formatar_quantidade

            raise ErroEstoque(
                f"O lote '{lote['numero'] or 's/nº'}' tem apenas {formatar_quantidade(disponivel)} em saldo."
            )
        if proibir_vencido and lote["validade"] and dias_entre(lote["validade"]) < 0:
            raise ErroEstoque(
                f"O lote '{lote['numero'] or 's/nº'}' está vencido desde {formatar_data(lote['validade'])}. "
                "Dê baixa por vencimento ou use outro lote."
            )
        movimento_id = registrar_movimento(
            banco, produto_id, quantidade, motivo=motivo, tipo="saida",
            custo_unitario=int(lote["custo_unitario"] or custo_unitario or 0),
            lote_id=int(lote["id"]), lote_numero=lote["numero"] or "", validade=lote["validade"] or "",
            documento_id=documento_id, observacao=observacao, autor=autor,
        )
        return quantidade, movimento_id

    total = 0.0
    restante = quantidade
    ultimo = 0
    for lote in lotes_do_produto(banco, produto_id):
        if restante <= 1e-9:
            break
        disponivel = float(lote["quantidade_atual"] or 0)
        if disponivel <= 1e-9:
            continue
        if proibir_vencido and lote["validade"] and dias_entre(lote["validade"]) < 0:
            continue
        usar = min(disponivel, restante)
        ultimo = registrar_movimento(
            banco, produto_id, usar, motivo=motivo, tipo="saida",
            custo_unitario=int(lote["custo_unitario"] or custo_unitario or 0),
            lote_id=int(lote["id"]), lote_numero=lote["numero"] or "", validade=lote["validade"] or "",
            documento_id=documento_id, observacao=observacao, autor=autor,
        )
        restante = unidades.arredondar(restante - usar)
        total += usar
    return total, ultimo


def _devolver_ao_lote(banco: Banco, produto_id: int, quantidade: float, motivo: str,
                      lote_origem_id: int | None, validade_sugerida: str, custo_unitario: int,
                      documento_id: int | None, observacao: str, autor) -> None:
    """Devolve mercadoria ao lote de origem (ou cria um lote equivalente)."""
    lote = None
    if lote_origem_id:
        lote = banco.consultar_uma("SELECT * FROM lotes WHERE id=?", (lote_origem_id,))
    if lote:
        # A movimentação com lote_id atualiza o saldo do lote pelo trigger; em seguida
        # limitamos o saldo à quantidade inicial do lote (a devolução nunca cria sobra).
        registrar_movimento(
            banco, produto_id, quantidade, motivo=motivo, tipo="entrada",
            custo_unitario=int(lote["custo_unitario"] or custo_unitario or 0),
            lote_id=int(lote["id"]), lote_numero=lote["numero"] or "", validade=lote["validade"] or "",
            documento_id=documento_id, observacao=observacao, autor=autor,
        )
        limite = float(lote["quantidade_inicial"] or 0)
        novo_saldo = float(banco.consultar_valor("SELECT quantidade_atual FROM lotes WHERE id=?", (lote["id"],)) or 0)
        if limite > 0 and novo_saldo > limite:
            banco.atualizar("lotes", lote["id"], {"quantidade_atual": limite, "atualizado_em": agora_iso()})
        return
    lote_id = criar_ou_atualizar_lote(
        banco, produto_id, 0, numero="", validade=validade_sugerida or "",
        custo_unitario=custo_unitario, documento="", observacao=observacao, forcar_inicial=quantidade,
    )
    registrar_movimento(
        banco, produto_id, quantidade, motivo=motivo, tipo="entrada",
        custo_unitario=int(custo_unitario or 0), lote_id=lote_id, lote_numero="",
        validade=validade_sugerida or "", documento_id=documento_id, observacao=observacao, autor=autor,
    )


# --------------------------------------------------------------------------------------
# Operações de alto nível
# --------------------------------------------------------------------------------------


def entrada(
    banco: Banco,
    produto_id: int,
    quantidade,
    motivo: str = "compra",
    custo_unitario: int = 0,
    unidade: str | None = None,
    lote_numero: str = "",
    validade: str = "",
    fornecedor_id=None,
    documento: str = "",
    observacao: str = "",
    autor=None,
    atualizar_custo: bool = True,
) -> int:
    """Entrada de mercadoria (compra, produção, transferência recebida, ajuste +).

    * atualiza o **custo médio ponderado** do produto;
    * cria/alimenta o **lote** quando o produto controla lote (validade obrigatória
      se o produto tiver validade padrão configurada).
    """
    produto = _validar_produto(banco, produto_id)
    qtd, unidade_usada = _quantidade_valida(produto, quantidade, unidade, banco)
    if qtd <= 0:
        raise ErroEstoque("A quantidade de entrada deve ser maior que zero.")
    if motivo not in MOTIVOS_ENTRADA and motivo not in MOTIVOS_AJUSTE:
        raise ErroEstoque(f"Motivo de entrada inválido: '{motivo}'.")
    custo = int(custo_unitario or 0)
    if custo < 0:
        raise ErroEstoque("Custo unitário não pode ser negativo.")

    validade_final = str(validade or "").strip()
    if int(produto["controla_lote"] or 0) and not validade_final and produto["validade_dias"]:
        validade_final = somar_dias(hoje(), int(produto["validade_dias"]))

    # Estado ANTES da entrada (necessário para o custo médio ponderado correto).
    saldo_antes = float(produto["estoque_atual"] or 0)
    custo_antes = int(produto["preco_custo"] or 0)

    observacao_final = _com_doc(observacao, documento)
    with banco.transacao():
        if int(produto["controla_lote"] or 0):
            # O lote é criado (ou localizado) e o saldo dele é lançado pela própria
            # movimentação, via trigger — evitando contagem dupla.
            lote_id = criar_ou_atualizar_lote(
                banco, produto_id, 0, numero=lote_numero, validade=validade_final,
                custo_unitario=custo or int(produto["preco_custo"] or 0),
                fornecedor_id=fornecedor_id, documento=documento, observacao=observacao,
                forcar_inicial=qtd,
            )
            movimento_id = registrar_movimento(
                banco, produto_id, qtd, motivo=motivo, tipo="entrada", unidade=unidade_usada,
                custo_unitario=custo, lote_id=lote_id, lote_numero=lote_numero,
                validade=validade_final, documento_id=None, observacao=observacao_final, autor=autor,
            )
        else:
            movimento_id = registrar_movimento(
                banco, produto_id, qtd, motivo=motivo, tipo="entrada", unidade=unidade_usada,
                custo_unitario=custo, lote_numero=lote_numero, validade=validade_final,
                observacao=observacao_final, autor=autor,
            )
        if atualizar_custo:
            produtos_mod.recalcular_custo_medio(
                banco, produto_id, qtd, custo, saldo_antes=saldo_antes, custo_antes=custo_antes
            )
    usuario_id, usuario_nome = _autor(autor)
    banco.registrar_log(
        "estoque_entrada",
        f"{produto['codigo']} +{qtd} {produto['unidade_base']} ({motivo_descricao(motivo)})",
        usuario_id, usuario_nome,
    )
    return movimento_id


def _com_doc(observacao: str, documento: str) -> str:
    doc = f"Documento: {documento}"
    if not observacao:
        return doc
    if doc in observacao:
        return observacao
    return f"{observacao} | {doc}"


def saida(
    banco: Banco,
    produto_id: int,
    quantidade,
    motivo: str = "venda",
    unidade: str | None = None,
    lote_id: int | None = None,
    custo_unitario: int | None = None,
    documento_id: int | None = None,
    observacao: str = "",
    autor=None,
    permitir_negativo: bool = False,
    bloquear_vencido: bool = True,
) -> int:
    """Saída de mercadoria (venda, perda, devolução a fornecedor, ajuste −).

    Consome os lotes pelo critério FEFO quando o produto controla lote.
    """
    produto = _validar_produto(banco, produto_id)
    qtd, unidade_usada = _quantidade_valida(produto, quantidade, unidade, banco)
    if qtd <= 0:
        raise ErroEstoque("A quantidade de saída deve ser maior que zero.")
    if motivo not in MOTIVOS_SAIDA and motivo not in MOTIVOS_AJUSTE:
        raise ErroEstoque(f"Motivo de saída inválido: '{motivo}'.")
    saldo_atual = saldo(banco, produto_id)
    if saldo_atual + 1e-9 < qtd and not permitir_negativo:
        from .utils import formatar_quantidade

        raise ErroEstoque(
            f"Estoque insuficiente de '{produto['nome']}': disponível {formatar_quantidade(saldo_atual)} "
            f"{produto['unidade_base']}, solicitado {formatar_quantidade(qtd)}."
        )
    custo = int(produto["preco_custo"] or 0) if custo_unitario is None else int(custo_unitario or 0)

    ultimo_id = 0
    with banco.transacao():
        if int(produto["controla_lote"] or 0):
            consumido, ultimo_id = _consumir_lotes(
                banco, produto_id, qtd, motivo, lote_id, custo, documento_id, observacao, autor,
                proibir_vencido=bloquear_vencido,
            )
            falta = unidades.arredondar(qtd - consumido)
            if falta > 1e-9:
                # Sem lote disponível suficiente: completa com movimento sem lote
                # (mantém o saldo coerente; o gestor regulariza os lotes depois).
                if not permitir_negativo:
                    raise ErroEstoque(
                        f"Não há lotes com saldo suficiente para '{produto['nome']}' "
                        f"(faltam {falta} {produto['unidade_base']})."
                    )
                ultimo = registrar_movimento(
                    banco, produto_id, falta, motivo=motivo, tipo="saida", unidade=unidade_usada,
                    custo_unitario=custo, documento_id=documento_id,
                    observacao=(observacao + " | " if observacao else "") + "Saída sem lote vinculado",
                    autor=autor,
                )
                return ultimo
            return ultimo_id or 0
        return registrar_movimento(
            banco, produto_id, qtd, motivo=motivo, tipo="saida", unidade=unidade_usada,
            custo_unitario=custo, documento_id=documento_id, observacao=observacao, autor=autor,
        )


def ajuste(
    banco: Banco,
    produto_id: int,
    quantidade_contada,
    motivo: str = "ajuste_inventario",
    unidade: str | None = None,
    lote_numero: str = "",
    validade: str = "",
    observacao: str = "",
    autor=None,
) -> dict:
    """Ajuste de inventário: informa o saldo **contado** e o sistema calcula a diferença.

    Devolve ``{'diferenca': float, 'tipo': 'entrada'|'saida'|'ajuste', 'movimentos': [ids]}``.
    """
    produto = _validar_produto(banco, produto_id)
    contado, unidade_usada = _quantidade_valida(produto, quantidade_contada, unidade, banco)
    if contado < 0:
        raise ErroEstoque("O saldo contado não pode ser negativo.")
    if motivo not in MOTIVOS_AJUSTE and motivo not in MOTIVOS_ENTRADA and motivo not in MOTIVOS_SAIDA:
        raise ErroEstoque(f"Motivo de ajuste inválido: '{motivo}'.")
    atual = saldo(banco, produto_id)
    diferenca = unidades.arredondar(contado - atual)
    resultado = {"anterior": atual, "contado": contado, "diferenca": diferenca, "tipo": "ajuste", "movimentos": []}
    if abs(diferenca) <= 1e-9:
        banco.registrar_log(
            "estoque_ajuste", f"{produto['codigo']}: conferido, sem diferença",
            *_autor(autor),
        )
        return resultado
    custo = int(produto["preco_custo"] or 0)
    if diferenca > 0:
        resultado["tipo"] = "entrada"
        resultado["movimentos"].append(
            entrada(
                banco, produto_id, diferenca, motivo=motivo if motivo in MOTIVOS_ENTRADA else "ajuste_positivo",
                custo_unitario=custo, unidade=produto["unidade_base"], lote_numero=lote_numero, validade=validade,
                observacao=observacao or f"Ajuste de inventário: {atual} -> {contado}", autor=autor,
                atualizar_custo=False,
            )
        )
    else:
        resultado["tipo"] = "saida"
        resultado["movimentos"].append(
            saida(
                banco, produto_id, abs(diferenca), motivo=motivo if motivo in MOTIVOS_SAIDA else "ajuste_negativo",
                unidade=produto["unidade_base"], custo_unitario=custo,
                observacao=observacao or f"Ajuste de inventário: {atual} -> {contado}", autor=autor,
                permitir_negativo=False, bloquear_vencido=False,
            )
        )
    usuario_id, usuario_nome = _autor(autor)
    banco.registrar_log(
        "estoque_ajuste",
        f"{produto['codigo']}: {atual} -> {contado} ({'+' if diferenca > 0 else ''}{diferenca})",
        usuario_id, usuario_nome,
    )
    return resultado


def baixa_por_vencimento(banco: Banco, lote_id: int, quantidade: float | None = None, observacao: str = "", autor=None) -> int:
    """Dá baixa num lote vencido (parcial ou total)."""
    lote = banco.consultar_uma("SELECT * FROM lotes WHERE id=?", (lote_id,))
    if not lote:
        raise ErroEstoque("Lote não encontrado.")
    disponivel = float(lote["quantidade_atual"] or 0)
    qtd = disponivel if quantidade in (None, "", 0) else float(quantidade)
    if qtd <= 0:
        raise ErroEstoque("Quantidade para baixa deve ser maior que zero.")
    if qtd > disponivel + 1e-9:
        raise ErroEstoque(f"O lote tem apenas {disponivel} em saldo.")
    texto = observacao or f"Baixa por vencimento do lote '{lote['numero'] or 's/nº'}' (validade {formatar_data(lote['validade'])})"
    movimento_id = saida(
        banco, lote["produto_id"], qtd, motivo="vencimento", lote_id=lote_id,
        custo_unitario=int(lote["custo_unitario"] or 0), observacao=texto, autor=autor,
        bloquear_vencido=False,
    )
    usuario_id, usuario_nome = _autor(autor)
    banco.registrar_log("estoque_vencimento", texto, usuario_id, usuario_nome)
    return movimento_id


def devolver_ao_estoque(banco: Banco, produto_id: int, quantidade_base: float, motivo: str = "devolucao_cliente",
                        lote_origem_id: int | None = None, validade_sugerida: str = "",
                        custo_unitario: int = 0, documento_id: int | None = None,
                        observacao: str = "", autor=None) -> int:
    """Entrada usada em devoluções/cancelamentos: preserva o lote de origem."""
    produto = _validar_produto(banco, produto_id)
    qtd = abs(float(quantidade_base))
    if qtd <= 1e-9:
        return 0
    with banco.transacao():
        if int(produto["controla_lote"] or 0):
            _devolver_ao_lote(
                banco, produto_id, qtd, motivo, lote_origem_id, validade_sugerida,
                custo_unitario or int(produto["preco_custo"] or 0), documento_id, observacao, autor,
            )
        else:
            registrar_movimento(
                banco, produto_id, qtd, motivo=motivo, tipo="entrada",
                custo_unitario=int(custo_unitario or produto["preco_custo"] or 0),
                documento_id=documento_id, observacao=observacao, autor=autor,
            )
    usuario_id, usuario_nome = _autor(autor)
    banco.registrar_log(
        "estoque_devolucao", f"{produto['codigo']} +{qtd} {produto['unidade_base']}",
        usuario_id, usuario_nome,
    )
    return 1


# --------------------------------------------------------------------------------------
# Histórico e indicadores
# --------------------------------------------------------------------------------------


def historico(
    banco: Banco,
    produto_id: int | None = None,
    data_inicial: str | None = None,
    data_final: str | None = None,
    motivo: str = "",
    tipo: str = "",
    lote_id: int | None = None,
    usuario_id: int | None = None,
    texto: str = "",
    limite: int = 1000,
) -> list:
    """Histórico de movimentações com filtros combináveis."""
    sql = """SELECT m.*, p.codigo AS produto_codigo, p.nome AS produto_nome,
                    p.unidade_base, c.nome AS categoria_nome, l.numero AS lote_numero_atual
               FROM movimentacoes m
               JOIN produtos p ON p.id = m.produto_id
               LEFT JOIN categorias c ON c.id = p.categoria_id
               LEFT JOIN lotes l ON l.id = m.lote_id"""
    condicoes, params = _condicoes_filtro(produto_id, data_inicial, data_final, motivo, tipo, lote_id, usuario_id, texto)
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(int(limite))
    return banco.consultar(sql, params)


def _condicoes_filtro(produto_id, data_inicial, data_final, motivo, tipo, lote_id, usuario_id, texto):
    condicoes, params = [], []
    if produto_id:
        condicoes.append("m.produto_id = ?")
        params.append(int(produto_id))
    if data_inicial:
        condicoes.append("date(m.criado_em) >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("date(m.criado_em) <= date(?)")
        params.append(str(data_final)[:10])
    if motivo:
        condicoes.append("m.motivo = ?")
        params.append(str(motivo))
    if tipo:
        condicoes.append("m.tipo = ?")
        params.append(str(tipo))
    if lote_id:
        condicoes.append("m.lote_id = ?")
        params.append(int(lote_id))
    if usuario_id:
        condicoes.append("m.usuario_id = ?")
        params.append(int(usuario_id))
    if texto:
        condicoes.append("(p.nome LIKE ? OR p.codigo LIKE ? OR m.observacao LIKE ? OR m.usuario_nome LIKE ?)")
        params += [f"%{texto}%"] * 4
    return condicoes, params


def movimentacoes_de_documento(banco: Banco, documento_id: int, motivo: str = "venda") -> list:
    return banco.consultar(
        "SELECT * FROM movimentacoes WHERE documento_id=? AND motivo=? ORDER BY id", (documento_id, motivo)
    )


def resumo_periodo(banco: Banco, data_inicial: str, data_final: str) -> dict:
    """Totais de entradas e saídas do período (para o relatório de movimentações)."""
    linha = banco.consultar_uma(
        """SELECT COALESCE(SUM(CASE WHEN tipo='entrada' THEN quantidade ELSE 0 END),0) AS qtd_entrada,
                  COALESCE(SUM(CASE WHEN tipo='saida'   THEN quantidade ELSE 0 END),0) AS qtd_saida,
                  COALESCE(SUM(CASE WHEN tipo='entrada' THEN valor_total ELSE 0 END),0) AS valor_entrada,
                  COALESCE(SUM(CASE WHEN tipo='saida'   THEN valor_total ELSE 0 END),0) AS valor_saida,
                  COUNT(*) AS total_mov
             FROM movimentacoes
            WHERE date(criado_em) BETWEEN date(?) AND date(?)""",
        (data_inicial, data_final),
    )
    return {
        "quantidade_entrada": float(linha["qtd_entrada"] or 0),
        "quantidade_saida": float(linha["qtd_saida"] or 0),
        "valor_entrada": int(linha["valor_entrada"] or 0),
        "valor_saida": int(linha["valor_saida"] or 0),
        "total_movimentacoes": int(linha["total_mov"] or 0),
    }


def estoque_baixo(banco: Banco, limite: int = 200) -> list:
    """Produtos com saldo igual ou abaixo do estoque mínimo (com o quanto falta)."""
    linhas = banco.consultar("SELECT * FROM vw_estoque_baixo ORDER BY nome LIMIT ?", (int(limite),))
    resultado = []
    for l in linhas:
        resultado.append(
            {
                **{k: l[k] for k in l.keys()},
                "faltam": round(float(l["estoque_minimo"] or 0) - float(l["estoque_atual"] or 0), 4),
            }
        )
    return resultado


def sugestao_compra(banco: Banco, limite: int = 200) -> list:
    """Lista de compras sugerida: repor até o estoque máximo (ou 2x o mínimo)."""
    sugestoes = []
    for p in estoque_baixo(banco, limite):
        minimo = float(p["estoque_minimo"] or 0)
        maximo = float(p["estoque_maximo"] or 0)
        alvo = maximo if maximo > minimo else minimo * 2
        falta = round(max(0.0, alvo - float(p["estoque_atual"] or 0)), 4)
        if falta > 0:
            sugestoes.append(
                {
                    "produto_id": p["id"],
                    "codigo": p["codigo"],
                    "nome": p["nome"],
                    "unidade": p["unidade_base"],
                    "estoque_atual": float(p["estoque_atual"] or 0),
                    "estoque_minimo": minimo,
                    "sugerido": falta,
                    "fornecedor": p["fornecedor_nome"] or "",
                    "custo_unitario": int(p["preco_custo"] or 0),
                    "custo_total": int(round(falta * float(p["preco_custo"] or 0))),
                }
            )
    return sugestoes


def lotes_vencendo(banco: Banco, dias: int = 30) -> list:
    """Lotes com saldo que vencem em até ``dias`` dias (ou já vencidos)."""
    return banco.consultar(
        """SELECT v.*, p.fornecedor_id FROM vw_lotes_validade v
             JOIN produtos p ON p.id = v.produto_id
            WHERE v.dias_para_vencer <= ?
            ORDER BY v.dias_para_vencer, v.produto_nome""",
        (int(dias),),
    )


def lotes_vencidos(banco: Banco) -> list:
    return lotes_vencendo(banco, -1)


def valor_estoque(banco: Banco) -> dict:
    linha = banco.consultar_uma(
        """SELECT COALESCE(SUM(estoque_custo),0) AS custo, COALESCE(SUM(estoque_venda),0) AS venda,
                  COALESCE(SUM(estoque_atual),0) AS itens
             FROM vw_produtos_completo WHERE ativo=1"""
    )
    return {
        "custo": int(linha["custo"] or 0),
        "venda": int(linha["venda"] or 0),
        "quantidade": float(linha["itens"] or 0),
        "margem_potencial": int(linha["venda"] or 0) - int(linha["custo"] or 0),
    }


def recalcular_saldos(banco: Banco) -> int:
    """Reconstrói ``estoque_atual`` a partir das movimentações (manutenção)."""
    with banco.transacao():
        banco.executar(
            """UPDATE produtos SET estoque_atual =
                 (SELECT COALESCE(SUM(CASE tipo WHEN 'entrada' THEN quantidade
                                                WHEN 'saida' THEN -quantidade
                                                ELSE quantidade END), 0)
                    FROM movimentacoes WHERE produto_id = produtos.id)"""
        )
        banco.executar(
            """UPDATE lotes SET quantidade_atual =
                 (SELECT COALESCE(SUM(CASE m.tipo WHEN 'saida' THEN -m.quantidade ELSE m.quantidade END), 0)
                    FROM movimentacoes m WHERE m.lote_id = lotes.id)"""
        )
    return banco.consultar_valor("SELECT COUNT(*) FROM produtos") or 0


def verificar_saldos(banco: Banco) -> list:
    """Compara o saldo gravado com o saldo calculado pelo histórico (auditoria)."""
    return banco.consultar(
        """SELECT p.id, p.codigo, p.nome, p.estoque_atual AS gravado,
                  (SELECT COALESCE(SUM(CASE m.tipo WHEN 'entrada' THEN m.quantidade
                                                   WHEN 'saida' THEN -m.quantidade
                                                   ELSE m.quantidade END),0)
                     FROM movimentacoes m WHERE m.produto_id=p.id) AS calculado
             FROM produtos p
            WHERE ABS(COALESCE(p.estoque_atual,0) -
                      (SELECT COALESCE(SUM(CASE m.tipo WHEN 'entrada' THEN m.quantidade
                                                       WHEN 'saida' THEN -m.quantidade
                                                       ELSE m.quantidade END),0)
                         FROM movimentacoes m WHERE m.produto_id=p.id)) > 0.0001"""
    )


def ficha_produto(banco: Banco, produto_id: int, dias: int = 90) -> dict:
    """Resumo completo de um produto: cadastro, saldo, lotes e últimas movimentações."""
    produto = produtos_mod.pegar(banco, produto_id)
    if not produto:
        raise ErroEstoque("Produto não encontrado.")
    corte = somar_dias(hoje(), -abs(int(dias)))
    movimentacoes = historico(banco, produto_id=produto_id, data_inicial=corte, data_final=hoje(), limite=50)
    entrada = sum(float(m["quantidade"]) for m in movimentacoes if m["tipo"] == "entrada")
    saida_q = sum(float(m["quantidade"]) for m in movimentacoes if m["tipo"] == "saida")
    return {
        "produto": produto,
        "saldo": saldo(banco, produto_id),
        "lotes": lotes_do_produto(banco, produto_id),
        "movimentacoes": movimentacoes,
        "entradas_periodo": round(entrada, 4),
        "saidas_periodo": round(saida_q, 4),
        "periodo_dias": dias,
    }
