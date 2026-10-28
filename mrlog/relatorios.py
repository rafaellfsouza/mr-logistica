"""
Relatórios do MR Logística.

Todos os relatórios devolvem **a mesma estrutura**, o que permite que a tela de
relatórios, a exportação para Excel/CSV/PDF e a impressão usem um único código:

.. code-block:: python

    {
        "chave": "vendas_por_dia",
        "titulo": "Vendas por dia",
        "periodo": "01/10/2026 a 28/10/2026",
        "colunas": [{"chave": "data", "rotulo": "Data", "tipo": "texto", "largura": 12}, ...],
        "linhas":  [ {...}, ... ],
        "totais":  {"total": 123456, "lucro": 23456},   # centavos
        "resumo":  ["Total vendido: R$ 1.234,56", ...], # frases prontas para o rodapé
        "filtros": "Período: 01/10/2026 a 28/10/2026",
    }

Tipos de coluna suportados: ``texto``, ``inteiro``, ``dinheiro`` (centavos),
``quantidade``, ``percentual`` e ``data``.
"""

from __future__ import annotations

from typing import Any, Callable

from . import caixa as caixa_mod
from . import clientes as clientes_mod
from . import contas_pagar
from . import contas_receber
from . import estoque as estoque_mod
from . import fornecedores as fornecedores_mod
from . import produtos as produtos_mod
from . import usuarios
from .banco import Banco
from .utils import (
    formatar_data,
    formatar_dinheiro,
    formatar_quantidade,
    hoje,
    intervalo_padrao,
    para_reais,
    primeiro_dia_mes,
)

STATUS_VALIDOS = ("concluida", "parcialmente_devolvida")
_PLACEHOLDERS_STATUS = ",".join("?" * len(STATUS_VALIDOS))


class ErroRelatorio(Exception):
    """Relatório inexistente ou parâmetro inválido."""


# --------------------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------------------


def _periodo(parametros: dict, dias: int = 30) -> tuple[str, str]:
    """Resolve o período do relatório (início, fim) a partir dos parâmetros."""
    ini = str(parametros.get("data_inicial") or "")[:10]
    fim = str(parametros.get("data_final") or "")[:10]
    if not ini or not fim:
        padrao_ini, padrao_fim = intervalo_padrao(dias)
        ini = ini or padrao_ini
        fim = fim or padrao_fim
    return ini, fim


def _texto_periodo(ini: str, fim: str) -> str:
    return f"{formatar_data(ini)} a {formatar_data(fim)}"


def _coluna(chave: str, rotulo: str, tipo: str = "texto", largura: int = 0, alinhamento: str = "") -> dict:
    return {
        "chave": chave,
        "rotulo": rotulo,
        "tipo": tipo,
        "largura": largura or max(len(rotulo) + 2, 10),
        "alinhamento": alinhamento or ("esquerda" if tipo == "texto" else "direita"),
    }


def _linhas(cursor) -> list[dict]:
    return [dict(l) for l in cursor]


def _formata_valor(coluna: dict, valor) -> str:
    tipo = coluna.get("tipo")
    if valor is None:
        return ""
    if tipo == "dinheiro":
        return formatar_dinheiro(int(valor or 0))
    if tipo == "quantidade":
        return formatar_quantidade(valor)
    if tipo == "percentual":
        return f"{float(valor or 0):.2f}%".replace(".", ",")
    if tipo == "inteiro":
        return str(int(valor or 0))
    if tipo == "data":
        return formatar_data(valor)
    return str(valor)


# --------------------------------------------------------------------------------------
# Vendas
# --------------------------------------------------------------------------------------


def vendas_por_dia(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    linhas = _linhas(
        banco.consultar(
            f"""SELECT v.data_venda AS data,
                       COUNT(*) AS vendas,
                       SUM(v.qtd_itens) AS itens,
                       SUM(v.total_liquido) AS total,
                       SUM(v.desconto) AS desconto,
                       SUM(v.custo_total) AS custo,
                       SUM(v.lucro_liquido) AS lucro,
                       ROUND(AVG(v.total_liquido),0) AS ticket,
                       ROUND(SUM(v.lucro_liquido) * 100.0 / NULLIF(SUM(v.total_liquido),0), 2) AS margem
                  FROM vw_vendas_resumo v
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY v.data_venda ORDER BY v.data_venda""",
            (*STATUS_VALIDOS, ini, fim),
        )
    )
    total = sum(int(l["total"] or 0) for l in linhas)
    lucro = sum(int(l["lucro"] or 0) for l in linhas)
    return {
        "chave": "vendas_por_dia",
        "titulo": "Vendas por dia",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("data", "Data", "data", 12),
            _coluna("vendas", "Vendas", "inteiro", 8),
            _coluna("itens", "Itens", "inteiro", 8),
            _coluna("total", "Total vendido", "dinheiro", 14),
            _coluna("desconto", "Descontos", "dinheiro", 12),
            _coluna("custo", "Custo (CMV)", "dinheiro", 14),
            _coluna("lucro", "Lucro", "dinheiro", 14),
            _coluna("ticket", "Ticket médio", "dinheiro", 13),
            _coluna("margem", "Margem", "percentual", 9),
        ],
        "linhas": linhas,
        "totais": {"total": total, "lucro": lucro, "vendas": sum(int(l["vendas"] or 0) for l in linhas)},
        "resumo": [
            f"Vendas: {sum(int(l['vendas'] or 0) for l in linhas)}",
            f"Total vendido: {formatar_dinheiro(total)}",
            f"Lucro: {formatar_dinheiro(lucro)}",
            f"Margem média: {(lucro * 100.0 / total if total else 0):.2f}%".replace(".", ","),
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def vendas_por_produto(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    linhas = _linhas(
        banco.consultar(
            f"""SELECT vi.codigo, vi.nome, vi.unidade,
                       SUM(vi.quantidade) AS quantidade,
                       SUM(vi.quantidade_base) AS quantidade_base,
                       COUNT(DISTINCT vi.venda_id) AS vendas,
                       SUM(vi.total_bruto) AS bruto,
                       SUM(vi.desconto) AS desconto,
                       SUM(vi.total_liquido) AS total,
                       SUM(vi.custo_total) AS custo,
                       SUM(vi.lucro) AS lucro,
                       ROUND(SUM(vi.lucro) * 100.0 / NULLIF(SUM(vi.total_liquido),0), 2) AS margem
                  FROM venda_itens vi
                  JOIN vendas v ON v.id = vi.venda_id
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY vi.produto_id, vi.codigo, vi.nome, vi.unidade
                 ORDER BY total DESC""",
            (*STATUS_VALIDOS, ini, fim),
        )
    )
    total = sum(int(l["total"] or 0) for l in linhas)
    lucro = sum(int(l["lucro"] or 0) for l in linhas)
    return {
        "chave": "vendas_por_produto",
        "titulo": "Vendas por produto",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("codigo", "Código", "texto", 12),
            _coluna("nome", "Produto", "texto", 34),
            _coluna("quantidade", "Qtd", "quantidade", 9),
            _coluna("unidade", "Un", "texto", 6),
            _coluna("vendas", "Vendas", "inteiro", 8),
            _coluna("bruto", "Bruto", "dinheiro", 13),
            _coluna("desconto", "Desconto", "dinheiro", 11),
            _coluna("total", "Total líquido", "dinheiro", 14),
            _coluna("custo", "Custo", "dinheiro", 13),
            _coluna("lucro", "Lucro", "dinheiro", 13),
            _coluna("margem", "Margem", "percentual", 9),
        ],
        "linhas": linhas,
        "totais": {"total": total, "lucro": lucro, "quantidade_itens": len(linhas)},
        "resumo": [
            f"Produtos vendidos: {len(linhas)}",
            f"Total vendido: {formatar_dinheiro(total)}",
            f"Lucro: {formatar_dinheiro(lucro)}",
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def vendas_por_forma_pagamento(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    linhas = _linhas(
        banco.consultar(
            f"""SELECT vp.forma, COUNT(DISTINCT vp.venda_id) AS vendas,
                       SUM(vp.valor) AS total, SUM(vp.parcelas) AS parcelas,
                       ROUND(SUM(vp.valor) * 100.0 / NULLIF((SELECT SUM(v.total) FROM vendas v
                            WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?),0), 2) AS participacao
                  FROM venda_pagamentos vp
                  JOIN vendas v ON v.id = vp.venda_id
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY vp.forma ORDER BY total DESC""",
            (*STATUS_VALIDOS, ini, fim, *STATUS_VALIDOS, ini, fim),
        )
    )
    total = sum(int(l["total"] or 0) for l in linhas)
    return {
        "chave": "vendas_por_forma_pagamento",
        "titulo": "Vendas por forma de pagamento",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("forma", "Forma de pagamento", "texto", 22),
            _coluna("vendas", "Vendas", "inteiro", 9),
            _coluna("total", "Valor", "dinheiro", 15),
            _coluna("parcelas", "Parcelas somadas", "inteiro", 16),
            _coluna("participacao", "% do total", "percentual", 11),
        ],
        "linhas": linhas,
        "totais": {"total": total},
        "resumo": [f"Total recebido: {formatar_dinheiro(total)}"] + [
            f"{l['forma']}: {formatar_dinheiro(l['total'])} ({float(l['participacao'] or 0):.1f}%)".replace(".", ",")
            for l in linhas
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def vendas_por_vendedor(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    linhas = _linhas(
        banco.consultar(
            f"""SELECT COALESCE(v.vendedor_nome,'(sem vendedor)') AS vendedor,
                       COUNT(*) AS vendas,
                       SUM(v.qtd_itens) AS itens,
                       SUM(v.total_liquido) AS total,
                       SUM(v.lucro_liquido) AS lucro,
                       SUM(v.desconto) AS desconto,
                       ROUND(AVG(v.total_liquido),0) AS ticket,
                       ROUND(SUM(v.lucro_liquido)*100.0/NULLIF(SUM(v.total_liquido),0),2) AS margem,
                       SUM(v.troco) AS troco,
                       SUM(v.valor_fiado) AS fiado
                  FROM vw_vendas_resumo v
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY COALESCE(v.vendedor_nome,'(sem vendedor)') ORDER BY total DESC""",
            (*STATUS_VALIDOS, ini, fim),
        )
    )
    total = sum(int(l["total"] or 0) for l in linhas)
    lucro = sum(int(l["lucro"] or 0) for l in linhas)
    return {
        "chave": "vendas_por_vendedor",
        "titulo": "Vendas por vendedor",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("vendedor", "Vendedor", "texto", 26),
            _coluna("vendas", "Vendas", "inteiro", 8),
            _coluna("itens", "Itens", "inteiro", 8),
            _coluna("total", "Total vendido", "dinheiro", 14),
            _coluna("ticket", "Ticket médio", "dinheiro", 13),
            _coluna("desconto", "Descontos", "dinheiro", 12),
            _coluna("lucro", "Lucro", "dinheiro", 13),
            _coluna("margem", "Margem", "percentual", 9),
            _coluna("fiado", "Fiado", "dinheiro", 12),
        ],
        "linhas": linhas,
        "totais": {"total": total, "lucro": lucro},
        "resumo": [f"Vendedores: {len(linhas)}", f"Total vendido: {formatar_dinheiro(total)}", f"Lucro: {formatar_dinheiro(lucro)}"],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def produtos_mais_vendidos(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    limite = int(parametros.get("limite") or 20)
    ranking = int(parametros.get("por") == "quantidade")
    ordem = "quantidade_base DESC" if ranking else "total DESC"
    linhas = _linhas(
        banco.consultar(
            f"""SELECT vi.codigo, vi.nome, COALESCE(p.unidade_base, vi.unidade) AS unidade,
                       SUM(vi.quantidade_base) AS quantidade_base,
                       SUM(vi.total_liquido) AS total,
                       SUM(vi.lucro) AS lucro,
                       COUNT(DISTINCT vi.venda_id) AS vendas,
                       COALESCE(p.estoque_atual, 0) AS estoque
                  FROM venda_itens vi
                  JOIN vendas v ON v.id = vi.venda_id
                  LEFT JOIN produtos p ON p.id = vi.produto_id
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY vi.produto_id, vi.codigo, vi.nome, unidade
                 ORDER BY {ordem} LIMIT ?""",
            (*STATUS_VALIDOS, ini, fim, limite),
        )
    )
    return {
        "chave": "produtos_mais_vendidos",
        "titulo": f"Produtos mais vendidos (top {limite} por {'quantidade' if ranking else 'valor'})",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("posicao", "#", "inteiro", 5),
            _coluna("codigo", "Código", "texto", 12),
            _coluna("nome", "Produto", "texto", 36),
            _coluna("quantidade_base", "Qtd vendida", "quantidade", 12),
            _coluna("unidade", "Un", "texto", 6),
            _coluna("vendas", "Vendas", "inteiro", 8),
            _coluna("total", "Faturamento", "dinheiro", 14),
            _coluna("lucro", "Lucro", "dinheiro", 13),
            _coluna("estoque", "Estoque atual", "quantidade", 13),
        ],
        "linhas": [{**l, "posicao": i} for i, l in enumerate(linhas, start=1)],
        "totais": {"total": sum(int(l["total"] or 0) for l in linhas)},
        "resumo": [f"Itens no ranking: {len(linhas)}", f"Faturamento do ranking: {formatar_dinheiro(sum(int(l['total'] or 0) for l in linhas))}"],
        "filtros": f"Período: {_texto_periodo(ini, fim)} | Top {limite} por {'quantidade' if ranking else 'valor'}",
    }


def lucro(banco: Banco, parametros: dict) -> dict:
    """Lucro por mês: receita líquida, CMV, despesas pagas e resultado."""
    ini, fim = _periodo(parametros, dias=365)
    linhas = _linhas(
        banco.consultar(
            f"""SELECT strftime('%Y-%m', v.data_venda) AS mes,
                       COUNT(*) AS vendas,
                       SUM(v.total_liquido) AS receita,
                       SUM(v.custo_total) - SUM(v.custo_devolvido) AS cmv,
                       SUM(v.lucro_liquido) AS lucro_bruto,
                       SUM(v.desconto) AS descontos
                  FROM vw_vendas_resumo v
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY mes ORDER BY mes""",
            (*STATUS_VALIDOS, ini, fim),
        )
    )
    despesas = {
        str(l["mes"]): int(l["total"] or 0)
        for l in banco.consultar(
            """SELECT strftime('%Y-%m', criado_em) AS mes, SUM(valor) AS total
                 FROM pagamentos_conta GROUP BY mes"""
        )
    }
    for l in linhas:
        l["despesas"] = despesas.get(str(l["mes"]), 0)
        l["lucro_liquido_final"] = int(l["lucro_bruto"] or 0) - int(l["despesas"] or 0)
        receita = int(l["receita"] or 0)
        l["margem_bruta"] = round(int(l["lucro_bruto"] or 0) * 100.0 / receita, 2) if receita else 0.0
        l["margem_liquida"] = round(int(l["lucro_liquido_final"]) * 100.0 / receita, 2) if receita else 0.0
    receita_total = sum(int(l["receita"] or 0) for l in linhas)
    lucro_total = sum(int(l["lucro_liquido_final"] or 0) for l in linhas)
    return {
        "chave": "lucro",
        "titulo": "Lucro (resultado por mês)",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("mes", "Mês", "texto", 10),
            _coluna("vendas", "Vendas", "inteiro", 8),
            _coluna("receita", "Receita líquida", "dinheiro", 15),
            _coluna("cmv", "CMV (custo)", "dinheiro", 14),
            _coluna("lucro_bruto", "Lucro bruto", "dinheiro", 14),
            _coluna("margem_bruta", "Margem bruta", "percentual", 13),
            _coluna("despesas", "Despesas pagas", "dinheiro", 15),
            _coluna("lucro_liquido_final", "Lucro líquido", "dinheiro", 14),
            _coluna("margem_liquida", "Margem líquida", "percentual", 14),
            _coluna("descontos", "Descontos concedidos", "dinheiro", 18),
        ],
        "linhas": linhas,
        "totais": {"receita": receita_total, "lucro": lucro_total},
        "resumo": [
            f"Receita líquida: {formatar_dinheiro(receita_total)}",
            f"Lucro líquido: {formatar_dinheiro(lucro_total)}",
            f"Margem líquida: {(lucro_total * 100.0 / receita_total if receita_total else 0):.2f}%".replace(".", ","),
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def relatorio_vendas(banco: Banco, parametros: dict) -> dict:
    """Relação de vendas (cupom a cupom)."""
    ini, fim = _periodo(parametros)
    condicoes = [f"v.status IN ({_PLACEHOLDERS_STATUS})", "v.data_venda BETWEEN ? AND ?"]
    params: list[Any] = [*STATUS_VALIDOS, ini, fim]
    if parametros.get("cliente_id"):
        condicoes.append("v.cliente_id = ?")
        params.append(int(parametros["cliente_id"]))
    if parametros.get("vendedor_id"):
        condicoes.append("v.vendedor_id = ?")
        params.append(int(parametros["vendedor_id"]))
    if parametros.get("forma"):
        condicoes.append("EXISTS (SELECT 1 FROM venda_pagamentos vp WHERE vp.venda_id=v.id AND vp.forma=?)")
        params.append(str(parametros["forma"]))
    if parametros.get("incluir_canceladas"):
        condicoes = [c for c in condicoes if "status" not in c]
    linhas = _linhas(
        banco.consultar(
            f"""SELECT v.numero, v.criada_em, v.data_venda, v.cliente_nome, v.vendedor_nome,
                       v.qtd_itens, v.subtotal, v.desconto, v.total_liquido AS total, v.lucro_liquido AS lucro,
                       v.status, v.valor_fiado, v.troco,
                       (SELECT GROUP_CONCAT(vp.forma || ' ' || printf('%.2f', vp.valor/100.0), ' + ')
                          FROM venda_pagamentos vp WHERE vp.venda_id=v.id) AS pagamentos
                  FROM vw_vendas_resumo v
                 WHERE {' AND '.join(condicoes)}
                 ORDER BY v.id DESC LIMIT 5000""",
            params,
        )
    )
    total = sum(int(l["total"] or 0) for l in linhas)
    return {
        "chave": "vendas",
        "titulo": "Relação de vendas",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("numero", "Cupom", "inteiro", 9),
            _coluna("criada_em", "Data/Hora", "texto", 17),
            _coluna("cliente_nome", "Cliente", "texto", 24),
            _coluna("vendedor_nome", "Vendedor", "texto", 18),
            _coluna("qtd_itens", "Itens", "inteiro", 7),
            _coluna("subtotal", "Subtotal", "dinheiro", 12),
            _coluna("desconto", "Desconto", "dinheiro", 11),
            _coluna("total", "Total", "dinheiro", 12),
            _coluna("lucro", "Lucro", "dinheiro", 12),
            _coluna("pagamentos", "Pagamento", "texto", 26),
            _coluna("status", "Situação", "texto", 16),
        ],
        "linhas": linhas,
        "totais": {"total": total, "lucro": sum(int(l["lucro"] or 0) for l in linhas)},
        "resumo": [f"Vendas: {len(linhas)}", f"Total: {formatar_dinheiro(total)}"],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


# --------------------------------------------------------------------------------------
# Estoque
# --------------------------------------------------------------------------------------


def estoque_atual(banco: Banco, parametros: dict) -> dict:
    condicoes, params = [], []
    if not parametros.get("incluir_inativos"):
        condicoes.append("ativo = 1")
    if parametros.get("categoria_id"):
        condicoes.append("categoria_id = ?")
        params.append(int(parametros["categoria_id"]))
    if parametros.get("fornecedor_id"):
        condicoes.append("fornecedor_id = ?")
        params.append(int(parametros["fornecedor_id"]))
    if parametros.get("texto"):
        condicoes.append("(nome LIKE ? OR codigo LIKE ? OR codigo_barras LIKE ?)")
        params += [f"%{parametros['texto']}%"] * 3
    if parametros.get("apenas_baixo"):
        condicoes.append("estoque_minimo > 0 AND COALESCE(estoque_atual,0) <= estoque_minimo")
    sql = "SELECT * FROM vw_produtos_completo"
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY nome"
    linhas = _linhas(banco.consultar(sql, params))
    for l in linhas:
        l["situacao"] = (
            "ZERADO" if float(l["estoque_atual"] or 0) <= 0
            else "BAIXO" if float(l["estoque_minimo"] or 0) > 0 and float(l["estoque_atual"] or 0) <= float(l["estoque_minimo"] or 0)
            else "OK"
        )
    custo = sum(int(l["estoque_custo"] or 0) for l in linhas)
    venda = sum(int(l["estoque_venda"] or 0) for l in linhas)
    return {
        "chave": "estoque_atual",
        "titulo": "Estoque atual",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("codigo", "Código", "texto", 11),
            _coluna("codigo_barras", "Cód. barras", "texto", 14),
            _coluna("nome", "Produto", "texto", 34),
            _coluna("categoria_nome", "Categoria", "texto", 16),
            _coluna("fornecedor_nome", "Fornecedor", "texto", 18),
            _coluna("estoque_atual", "Saldo", "quantidade", 10),
            _coluna("unidade_base", "Un", "texto", 6),
            _coluna("estoque_minimo", "Mínimo", "quantidade", 9),
            _coluna("preco_custo", "Custo unit.", "dinheiro", 12),
            _coluna("preco_venda", "Preço venda", "dinheiro", 12),
            _coluna("margem_pct", "Margem", "percentual", 9),
            _coluna("estoque_custo", "Estoque a custo", "dinheiro", 16),
            _coluna("estoque_venda", "Estoque a venda", "dinheiro", 16),
            _coluna("situacao", "Situação", "texto", 10),
        ],
        "linhas": linhas,
        "totais": {"custo": custo, "venda": venda, "produtos": len(linhas)},
        "resumo": [
            f"Produtos: {len(linhas)}",
            f"Estoque a custo: {formatar_dinheiro(custo)}",
            f"Estoque a preço de venda: {formatar_dinheiro(venda)}",
            f"Margem potencial: {formatar_dinheiro(venda - custo)}",
        ],
        "filtros": "Somente ativos" if not parametros.get("incluir_inativos") else "Inclui inativos",
    }


def estoque_baixo(banco: Banco, parametros: dict) -> dict:
    linhas = [dict(l) for l in estoque_mod.estoque_baixo(banco, limite=5000)]
    for l in linhas:
        l["sugerido"] = round(max(0.0, float(l["estoque_minimo"] or 0) * 2 - float(l["estoque_atual"] or 0)), 4)
        l["custo_reposicao"] = int(round(float(l["sugerido"]) * float(l["preco_custo"] or 0)))
    return {
        "chave": "estoque_baixo",
        "titulo": "Alerta de estoque baixo (e sugestão de compra)",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("codigo", "Código", "texto", 11),
            _coluna("nome", "Produto", "texto", 34),
            _coluna("categoria_nome", "Categoria", "texto", 16),
            _coluna("fornecedor_nome", "Fornecedor", "texto", 20),
            _coluna("estoque_atual", "Saldo", "quantidade", 10),
            _coluna("unidade_base", "Un", "texto", 6),
            _coluna("estoque_minimo", "Mínimo", "quantidade", 9),
            _coluna("faltam", "Faltam", "quantidade", 9),
            _coluna("sugerido", "Sugestão de compra", "quantidade", 18),
            _coluna("preco_custo", "Custo unit.", "dinheiro", 12),
            _coluna("custo_reposicao", "Custo da reposição", "dinheiro", 18),
        ],
        "linhas": linhas,
        "totais": {"custo": sum(int(l["custo_reposicao"] or 0) for l in linhas), "produtos": len(linhas)},
        "resumo": [
            f"Produtos abaixo do mínimo: {len(linhas)}",
            f"Custo estimado da reposição: {formatar_dinheiro(sum(int(l['custo_reposicao'] or 0) for l in linhas))}",
        ],
        "filtros": "Produtos ativos com saldo <= estoque mínimo",
    }


def movimentacoes_estoque(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    linhas = _linhas(
        banco.consultar(
            """SELECT m.criado_em, m.tipo, m.motivo, p.codigo, p.nome, p.unidade_base AS unidade,
                      m.quantidade, m.custo_unitario, m.valor_total, m.saldo_apos,
                      m.lote_numero, m.validade, m.usuario_nome, m.observacao, m.documento_id
                 FROM movimentacoes m JOIN produtos p ON p.id=m.produto_id
                WHERE date(m.criado_em) BETWEEN ? AND ?"""
            + (" AND m.produto_id=?" if parametros.get("produto_id") else "")
            + (" AND m.tipo=?" if parametros.get("tipo") else "")
            + (" AND m.motivo=?" if parametros.get("motivo") else "")
            + " ORDER BY m.id DESC LIMIT 20000",
            [
                ini, fim,
                *([int(parametros["produto_id"])] if parametros.get("produto_id") else []),
                *([str(parametros["tipo"])] if parametros.get("tipo") else []),
                *([str(parametros["motivo"])] if parametros.get("motivo") else []),
            ],
        )
    )
    for l in linhas:
        l["sinal"] = "-" if l["tipo"] == "saida" else ("+" if l["tipo"] == "entrada" else "+/-")
    resumo = estoque_mod.resumo_periodo(banco, ini, fim)
    return {
        "chave": "movimentacoes_estoque",
        "titulo": "Movimentações de estoque",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("criado_em", "Data/Hora", "texto", 17),
            _coluna("sinal", "+/-", "texto", 5),
            _coluna("tipo", "Tipo", "texto", 9),
            _coluna("motivo", "Motivo", "texto", 16),
            _coluna("codigo", "Código", "texto", 11),
            _coluna("nome", "Produto", "texto", 30),
            _coluna("quantidade", "Qtd", "quantidade", 9),
            _coluna("unidade", "Un", "texto", 6),
            _coluna("custo_unitario", "Custo unit.", "dinheiro", 12),
            _coluna("valor_total", "Valor", "dinheiro", 12),
            _coluna("saldo_apos", "Saldo após", "quantidade", 11),
            _coluna("lote_numero", "Lote", "texto", 10),
            _coluna("validade", "Validade", "data", 11),
            _coluna("usuario_nome", "Usuário", "texto", 16),
        ],
        "linhas": linhas,
        "totais": {"entradas": resumo["valor_entrada"], "saidas": resumo["valor_saida"], "movimentos": resumo["total_movimentacoes"]},
        "resumo": [
            f"Movimentações: {resumo['total_movimentacoes']}",
            f"Entradas: {formatar_quantidade(resumo['quantidade_entrada'])} ({formatar_dinheiro(resumo['valor_entrada'])})",
            f"Saídas: {formatar_quantidade(resumo['quantidade_saida'])} ({formatar_dinheiro(resumo['valor_saida'])})",
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def lotes_validade(banco: Banco, parametros: dict) -> dict:
    dias = int(parametros.get("dias") or banco.config_pegar_int("alerta_validade_dias", 30))
    linhas = _linhas(
        banco.consultar(
            """SELECT l.numero, l.validade, l.dias_para_vencer, l.quantidade_inicial, l.quantidade_atual,
                      l.produto_codigo AS codigo, l.produto_nome AS nome, l.unidade_base AS unidade,
                      l.custo_unitario, (l.quantidade_atual * l.custo_unitario) AS valor, l.documento
                 FROM vw_lotes_validade l
                WHERE l.dias_para_vencer <= ?
                ORDER BY l.dias_para_vencer""",
            (dias,),
        )
    )
    for l in linhas:
        d = int(l["dias_para_vencer"] or 0)
        l["situacao"] = "VENCIDO" if d < 0 else ("CRÍTICO" if d <= 7 else "ATENÇÃO")
    vencidos = [l for l in linhas if int(l["dias_para_vencer"] or 0) < 0]
    return {
        "chave": "lotes_validade",
        "titulo": f"Lotes e validade (próximos {dias} dias)",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("codigo", "Código", "texto", 11),
            _coluna("nome", "Produto", "texto", 32),
            _coluna("numero", "Lote", "texto", 12),
            _coluna("validade", "Validade", "data", 11),
            _coluna("dias_para_vencer", "Dias", "inteiro", 7),
            _coluna("situacao", "Situação", "texto", 10),
            _coluna("quantidade_atual", "Saldo", "quantidade", 10),
            _coluna("unidade", "Un", "texto", 6),
            _coluna("quantidade_inicial", "Qtd inicial", "quantidade", 12),
            _coluna("custo_unitario", "Custo unit.", "dinheiro", 12),
            _coluna("valor", "Valor em estoque", "dinheiro", 17),
        ],
        "linhas": linhas,
        "totais": {"valor": sum(int(l["valor"] or 0) for l in linhas), "lotes": len(linhas)},
        "resumo": [
            f"Lotes listados: {len(linhas)}",
            f"Lotes vencidos: {len(vencidos)} ({formatar_dinheiro(sum(int(l['valor'] or 0) for l in vencidos))})",
            f"Valor total em lotes: {formatar_dinheiro(sum(int(l['valor'] or 0) for l in linhas))}",
        ],
        "filtros": f"Lotes com saldo e validade em até {dias} dias (ou vencidos)",
    }


def curva_abc(banco: Banco, parametros: dict) -> dict:
    """Curva ABC de faturamento por produto (gestão de estoque)."""
    ini, fim = _periodo(parametros, dias=90)
    linhas = _linhas(
        banco.consultar(
            f"""SELECT vi.codigo, vi.nome, SUM(vi.total_liquido) AS total, SUM(vi.lucro) AS lucro,
                       SUM(vi.quantidade_base) AS quantidade, COALESCE(p.unidade_base, vi.unidade) AS unidade
                  FROM venda_itens vi
                  JOIN vendas v ON v.id=vi.venda_id
                  LEFT JOIN produtos p ON p.id=vi.produto_id
                 WHERE v.status IN ({_PLACEHOLDERS_STATUS}) AND v.data_venda BETWEEN ? AND ?
                 GROUP BY vi.produto_id, vi.codigo, vi.nome, unidade
                 ORDER BY total DESC""",
            (*STATUS_VALIDOS, ini, fim),
        )
    )
    total_geral = sum(int(l["total"] or 0) for l in linhas) or 1
    acumulado = 0
    for l in linhas:
        acumulado += int(l["total"] or 0)
        l["participacao"] = round(int(l["total"] or 0) * 100.0 / total_geral, 2)
        l["acumulado"] = round(acumulado * 100.0 / total_geral, 2)
        l["classe"] = "A" if l["acumulado"] <= 80 else ("B" if l["acumulado"] <= 95 else "C")
    return {
        "chave": "curva_abc",
        "titulo": "Curva ABC de produtos (por faturamento)",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("classe", "Classe", "texto", 8),
            _coluna("codigo", "Código", "texto", 11),
            _coluna("nome", "Produto", "texto", 34),
            _coluna("quantidade", "Qtd", "quantidade", 10),
            _coluna("unidade", "Un", "texto", 6),
            _coluna("total", "Faturamento", "dinheiro", 14),
            _coluna("lucro", "Lucro", "dinheiro", 13),
            _coluna("participacao", "% do total", "percentual", 11),
            _coluna("acumulado", "% acumulado", "percentual", 12),
        ],
        "linhas": linhas,
        "totais": {"total": sum(int(l["total"] or 0) for l in linhas)},
        "resumo": [
            "Classe A: até 80% do faturamento | Classe B: até 95% | Classe C: restante",
            f"Produtos: {len(linhas)} | Faturamento: {formatar_dinheiro(total_geral)}",
            f"A: {sum(1 for l in linhas if l['classe'] == 'A')} | B: {sum(1 for l in linhas if l['classe'] == 'B')} | C: {sum(1 for l in linhas if l['classe'] == 'C')}",
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


# --------------------------------------------------------------------------------------
# Financeiro
# --------------------------------------------------------------------------------------


def contas_a_receber(banco: Banco, parametros: dict) -> dict:
    contas_receber.atualizar_vencidas(banco)
    status = str(parametros.get("status") or "pendentes")
    linhas = [dict(l) for l in contas_receber.listar(
        banco,
        status="" if status == "todas" else status,
        cliente_id=parametros.get("cliente_id") or None,
        texto=str(parametros.get("texto") or ""),
        incluir_quitadas=status == "todas",
        limite=100000,
    )]
    total = sum(int(l["valor"] or 0) for l in linhas)
    saldo = sum(int(l["saldo"] or 0) for l in linhas)
    return {
        "chave": "contas_receber",
        "titulo": f"Contas a receber ({'todas' if status == 'todas' else status})",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("id", "Nº", "inteiro", 7),
            _coluna("cliente_nome", "Cliente", "texto", 28),
            _coluna("descricao", "Descrição", "texto", 26),
            _coluna("vencimento", "Vencimento", "data", 12),
            _coluna("dias_atraso", "Dias atraso", "inteiro", 11),
            _coluna("valor", "Valor", "dinheiro", 13),
            _coluna("valor_pago", "Recebido", "dinheiro", 13),
            _coluna("desconto", "Desconto", "dinheiro", 11),
            _coluna("saldo", "Saldo", "dinheiro", 13),
            _coluna("status", "Situação", "texto", 12),
        ],
        "linhas": linhas,
        "totais": {"total": total, "saldo": saldo},
        "resumo": [
            f"Títulos: {len(linhas)}",
            f"Valor lançado: {formatar_dinheiro(total)}",
            f"Saldo a receber: {formatar_dinheiro(saldo)}",
        ],
        "filtros": f"Situação: {status}",
    }


def contas_a_pagar(banco: Banco, parametros: dict) -> dict:
    contas_pagar.atualizar_vencidas(banco)
    status = str(parametros.get("status") or "pendentes")
    linhas = [dict(l) for l in contas_pagar.listar(
        banco, status="" if status == "todas" else status,
        categoria=str(parametros.get("categoria") or ""),
        texto=str(parametros.get("texto") or ""), limite=100000,
    )]
    return {
        "chave": "contas_pagar",
        "titulo": f"Contas a pagar ({'todas' if status == 'todas' else status})",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("id", "Nº", "inteiro", 7),
            _coluna("fornecedor_nome", "Fornecedor", "texto", 24),
            _coluna("descricao", "Descrição", "texto", 30),
            _coluna("categoria", "Categoria", "texto", 18),
            _coluna("vencimento", "Vencimento", "data", 12),
            _coluna("dias_atraso", "Dias atraso", "inteiro", 11),
            _coluna("valor", "Valor", "dinheiro", 13),
            _coluna("valor_pago", "Pago", "dinheiro", 13),
            _coluna("saldo", "Saldo", "dinheiro", 13),
            _coluna("status", "Situação", "texto", 12),
        ],
        "linhas": linhas,
        "totais": {
            "total": sum(int(l["valor"] or 0) for l in linhas),
            "saldo": sum(int(l["saldo"] or 0) for l in linhas),
        },
        "resumo": [
            f"Títulos: {len(linhas)}",
            f"Valor lançado: {formatar_dinheiro(sum(int(l['valor'] or 0) for l in linhas))}",
            f"Saldo a pagar: {formatar_dinheiro(sum(int(l['saldo'] or 0) for l in linhas))}",
        ],
        "filtros": f"Situação: {status}",
    }


def fluxo_caixa(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros)
    linhas = _linhas(
        banco.consultar(
            """SELECT m.criado_em, c.data AS data_caixa, m.categoria, m.tipo, m.forma, m.descricao,
                      m.valor, m.referencia, m.usuario_nome
                 FROM caixa_movimentos m JOIN caixa_diario c ON c.id=m.caixa_id
                WHERE c.data BETWEEN ? AND ?
                ORDER BY m.id DESC LIMIT 20000""",
            (ini, fim),
        )
    )
    entradas = sum(int(l["valor"] or 0) for l in linhas if l["tipo"] == "entrada")
    saidas = sum(int(l["valor"] or 0) for l in linhas if l["tipo"] == "saida")
    por_categoria = _linhas(
        banco.consultar(
            """SELECT m.categoria, m.tipo, SUM(m.valor) AS total, COUNT(*) AS qtd
                 FROM caixa_movimentos m JOIN caixa_diario c ON c.id=m.caixa_id
                WHERE c.data BETWEEN ? AND ? GROUP BY m.categoria, m.tipo ORDER BY total DESC""",
            (ini, fim),
        )
    )
    return {
        "chave": "fluxo_caixa",
        "titulo": "Fluxo de caixa",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("criado_em", "Data/Hora", "texto", 17),
            _coluna("categoria", "Categoria", "texto", 18),
            _coluna("tipo", "Tipo", "texto", 9),
            _coluna("forma", "Forma", "texto", 15),
            _coluna("descricao", "Descrição", "texto", 34),
            _coluna("valor", "Valor", "dinheiro", 13),
            _coluna("referencia", "Referência", "texto", 11),
            _coluna("usuario_nome", "Usuário", "texto", 16),
        ],
        "linhas": linhas,
        "totais": {"entradas": entradas, "saidas": saidas, "saldo": entradas - saidas},
        "resumo": [
            f"Entradas: {formatar_dinheiro(entradas)}",
            f"Saídas: {formatar_dinheiro(saidas)}",
            f"Saldo do período: {formatar_dinheiro(entradas - saidas)}",
        ] + [f"{l['categoria']} ({l['tipo']}): {formatar_dinheiro(l['total'])}" for l in por_categoria[:6]],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def fechamentos_caixa(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros, dias=90)
    caixas = caixa_mod.listar(banco, data_inicial=ini, data_final=fim, limite=10000)
    linhas = []
    for c in caixas:
        posicao = caixa_mod.posicao(banco, int(c["id"]))
        linhas.append(
            {
                "id": c["id"],
                "data": c["data"],
                "usuario_nome": c["usuario_nome"] or "",
                "status": "Aberto" if c["status"] == "aberto" else "Fechado",
                "abertura": int(c["valor_abertura"] or 0),
                "qtd_vendas": int(c["qtd_vendas"] or 0),
                "total_vendas": int(c["total_vendas"] or 0),
                "dinheiro": posicao["formas"].get("Dinheiro", {}).get("saldo", 0),
                "pix": posicao["formas"].get("Pix", {}).get("saldo", 0),
                "debito": posicao["formas"].get("Cartão de débito", {}).get("saldo", 0),
                "credito": posicao["formas"].get("Cartão de crédito", {}).get("saldo", 0),
                "sistema": posicao["valor_sistema"],
                "contado": int(c["valor_fechamento"] or 0),
                "diferenca": int(c["diferenca"] or 0),
            }
        )
    return {
        "chave": "fechamentos_caixa",
        "titulo": "Fechamentos de caixa",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("data", "Data", "data", 11),
            _coluna("usuario_nome", "Operador", "texto", 18),
            _coluna("status", "Situação", "texto", 10),
            _coluna("abertura", "Abertura", "dinheiro", 12),
            _coluna("qtd_vendas", "Vendas", "inteiro", 8),
            _coluna("total_vendas", "Total vendido", "dinheiro", 14),
            _coluna("dinheiro", "Dinheiro", "dinheiro", 12),
            _coluna("pix", "Pix", "dinheiro", 12),
            _coluna("debito", "Débito", "dinheiro", 12),
            _coluna("credito", "Crédito", "dinheiro", 12),
            _coluna("sistema", "Valor sistema", "dinheiro", 14),
            _coluna("contado", "Contado", "dinheiro", 12),
            _coluna("diferenca", "Diferença", "dinheiro", 12),
        ],
        "linhas": linhas,
        "totais": {
            "total": sum(int(l["total_vendas"] or 0) for l in linhas),
            "diferenca": sum(int(l["diferenca"] or 0) for l in linhas),
        },
        "resumo": [
            f"Caixas: {len(linhas)}",
            f"Total vendido: {formatar_dinheiro(sum(int(l['total_vendas'] or 0) for l in linhas))}",
            f"Diferença acumulada (quebra de caixa): {formatar_dinheiro(sum(int(l['diferenca'] or 0) for l in linhas))}",
        ],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


def despesas(banco: Banco, parametros: dict) -> dict:
    ini, fim = _periodo(parametros, dias=90)
    linhas = contas_pagar.por_categoria(banco, ini, fim)
    total = sum(int(l["total"] or 0) for l in linhas)
    for l in linhas:
        l["participacao"] = round(int(l["total"] or 0) * 100.0 / total, 2) if total else 0.0
    return {
        "chave": "despesas",
        "titulo": "Despesas por categoria",
        "periodo": _texto_periodo(ini, fim),
        "colunas": [
            _coluna("categoria", "Categoria", "texto", 26),
            _coluna("quantidade", "Lançamentos", "inteiro", 12),
            _coluna("total", "Valor", "dinheiro", 14),
            _coluna("pago", "Pago", "dinheiro", 14),
            _coluna("participacao", "% do total", "percentual", 11),
        ],
        "linhas": linhas,
        "totais": {"total": total},
        "resumo": [f"Total de despesas: {formatar_dinheiro(total)}"],
        "filtros": f"Período: {_texto_periodo(ini, fim)}",
    }


# --------------------------------------------------------------------------------------
# Cadastros
# --------------------------------------------------------------------------------------


def clientes_relatorio(banco: Banco, parametros: dict) -> dict:
    linhas = [
        dict(l)
        for l in clientes_mod.listar(
            banco,
            incluir_inativos=bool(parametros.get("incluir_inativos")),
            filtro=str(parametros.get("texto") or ""),
        )
    ]
    return {
        "chave": "clientes",
        "titulo": "Clientes",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("id", "Cód.", "inteiro", 7),
            _coluna("nome", "Nome", "texto", 30),
            _coluna("cpf_cnpj", "CPF/CNPJ", "texto", 16),
            _coluna("telefone", "Telefone", "texto", 15),
            _coluna("celular", "Celular", "texto", 15),
            _coluna("email", "E-mail", "texto", 24),
            _coluna("cidade", "Cidade", "texto", 16),
            _coluna("uf", "UF", "texto", 5),
            _coluna("qtd_compras", "Compras", "inteiro", 9),
            _coluna("total_compras", "Total comprado", "dinheiro", 15),
            _coluna("saldo_devedor", "Saldo fiado", "dinheiro", 13),
            _coluna("limite_credito", "Limite", "dinheiro", 12),
            _coluna("ultima_compra", "Última compra", "texto", 17),
        ],
        "linhas": linhas,
        "totais": {
            "total": sum(int(l["total_compras"] or 0) for l in linhas),
            "saldo": sum(int(l["saldo_devedor"] or 0) for l in linhas),
        },
        "resumo": [
            f"Clientes: {len(linhas)}",
            f"Total comprado: {formatar_dinheiro(sum(int(l['total_compras'] or 0) for l in linhas))}",
            f"Saldo em fiado: {formatar_dinheiro(sum(int(l['saldo_devedor'] or 0) for l in linhas))}",
        ],
        "filtros": "Inclui inativos" if parametros.get("incluir_inativos") else "Somente ativos",
    }


def fornecedores_relatorio(banco: Banco, parametros: dict) -> dict:
    linhas = [dict(l) for l in fornecedores_mod.listar(
        banco, incluir_inativos=bool(parametros.get("incluir_inativos")), filtro=str(parametros.get("texto") or "")
    )]
    return {
        "chave": "fornecedores",
        "titulo": "Fornecedores",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("id", "Cód.", "inteiro", 7),
            _coluna("nome", "Nome", "texto", 30),
            _coluna("cnpj_cpf", "CNPJ/CPF", "texto", 16),
            _coluna("contato", "Contato", "texto", 18),
            _coluna("telefone", "Telefone", "texto", 15),
            _coluna("email", "E-mail", "texto", 24),
            _coluna("cidade", "Cidade", "texto", 16),
            _coluna("uf", "UF", "texto", 5),
            _coluna("prazo_dias", "Prazo (dias)", "inteiro", 12),
            _coluna("qtd_produtos", "Produtos", "inteiro", 10),
            _coluna("saldo_aberto", "Saldo a pagar", "dinheiro", 14),
            _coluna("total_pago", "Total pago", "dinheiro", 13),
        ],
        "linhas": linhas,
        "totais": {"saldo": sum(int(l["saldo_aberto"] or 0) for l in linhas)},
        "resumo": [
            f"Fornecedores: {len(linhas)}",
            f"Saldo a pagar: {formatar_dinheiro(sum(int(l['saldo_aberto'] or 0) for l in linhas))}",
        ],
        "filtros": "Inclui inativos" if parametros.get("incluir_inativos") else "Somente ativos",
    }


def produtos_relatorio(banco: Banco, parametros: dict) -> dict:
    """Cadastro completo de produtos (ficha cadastral)."""
    linhas = [dict(l) for l in produtos_mod.listar(
        banco,
        filtro=str(parametros.get("texto") or ""),
        categoria_id=parametros.get("categoria_id") or None,
        fornecedor_id=parametros.get("fornecedor_id") or None,
        incluir_inativos=bool(parametros.get("incluir_inativos")),
    )]
    for l in linhas:
        l["markup"] = produtos_mod.markup(int(l["preco_custo"] or 0), int(l["preco_venda"] or 0))
    return {
        "chave": "produtos",
        "titulo": "Cadastro de produtos",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("codigo", "Código", "texto", 11),
            _coluna("codigo_barras", "Cód. barras", "texto", 14),
            _coluna("nome", "Produto", "texto", 34),
            _coluna("categoria_nome", "Categoria", "texto", 16),
            _coluna("marca", "Marca", "texto", 14),
            _coluna("fornecedor_nome", "Fornecedor", "texto", 18),
            _coluna("unidade_base", "Un. estoque", "texto", 11),
            _coluna("unidade_venda", "Un. venda", "texto", 10),
            _coluna("fator_venda", "Fator", "quantidade", 8),
            _coluna("preco_custo", "Custo", "dinheiro", 11),
            _coluna("preco_venda", "Preço", "dinheiro", 11),
            _coluna("margem_pct", "Margem", "percentual", 9),
            _coluna("markup", "Markup", "percentual", 9),
            _coluna("estoque_atual", "Estoque", "quantidade", 10),
            _coluna("estoque_minimo", "Mínimo", "quantidade", 9),
        ],
        "linhas": linhas,
        "totais": {"produtos": len(linhas)},
        "resumo": [f"Produtos: {len(linhas)}"],
        "filtros": "Inclui inativos" if parametros.get("incluir_inativos") else "Somente ativos",
    }


def usuarios_relatorio(banco: Banco, parametros: dict) -> dict:
    linhas = [dict(l) for l in usuarios.listar(banco)]
    for l in linhas:
        l["perfil_rotulo"] = usuarios.ROTULOS_PERFIS.get(l["perfil"], l["perfil"])
        l["situacao"] = "Ativo" if int(l["ativo"] or 0) else "Inativo"
    return {
        "chave": "usuarios",
        "titulo": "Usuários e permissões",
        "periodo": f"Posição em {formatar_data(hoje())}",
        "colunas": [
            _coluna("id", "Cód.", "inteiro", 7),
            _coluna("nome", "Nome", "texto", 28),
            _coluna("login", "Login", "texto", 16),
            _coluna("perfil_rotulo", "Perfil", "texto", 16),
            _coluna("email", "E-mail", "texto", 26),
            _coluna("telefone", "Telefone", "texto", 15),
            _coluna("situacao", "Situação", "texto", 10),
            _coluna("ultimo_login", "Último login", "texto", 20),
        ],
        "linhas": linhas,
        "totais": {"usuarios": len(linhas)},
        "resumo": [f"Usuários: {len(linhas)}"] + [
            f"{usuarios.ROTULOS_PERFIS[p]}: {n}" for p, n in usuarios.contagem_por_perfil(banco).items()
        ],
        "filtros": "",
    }


# --------------------------------------------------------------------------------------
# Registro dos relatórios
# --------------------------------------------------------------------------------------

#: chave -> (título, grupo, função, parâmetros aceitos)
RELATORIOS: dict[str, dict[str, Any]] = {
    "vendas_por_dia": {"titulo": "Vendas por dia", "grupo": "Vendas", "funcao": vendas_por_dia,
                       "parametros": ["data_inicial", "data_final"]},
    "vendas_por_produto": {"titulo": "Vendas por produto", "grupo": "Vendas", "funcao": vendas_por_produto,
                           "parametros": ["data_inicial", "data_final"]},
    "vendas_por_forma_pagamento": {"titulo": "Vendas por forma de pagamento", "grupo": "Vendas",
                                   "funcao": vendas_por_forma_pagamento, "parametros": ["data_inicial", "data_final"]},
    "vendas_por_vendedor": {"titulo": "Vendas por vendedor", "grupo": "Vendas", "funcao": vendas_por_vendedor,
                            "parametros": ["data_inicial", "data_final"]},
    "produtos_mais_vendidos": {"titulo": "Produtos mais vendidos", "grupo": "Vendas",
                               "funcao": produtos_mais_vendidos, "parametros": ["data_inicial", "data_final", "limite", "por"]},
    "vendas": {"titulo": "Relação de vendas (cupom a cupom)", "grupo": "Vendas", "funcao": relatorio_vendas,
               "parametros": ["data_inicial", "data_final", "cliente_id", "vendedor_id", "forma"]},
    "lucro": {"titulo": "Lucro e resultado por mês", "grupo": "Financeiro", "funcao": lucro,
              "parametros": ["data_inicial", "data_final"]},
    "contas_receber": {"titulo": "Contas a receber (fiado)", "grupo": "Financeiro", "funcao": contas_a_receber,
                       "parametros": ["status", "cliente_id", "texto"]},
    "contas_pagar": {"titulo": "Contas a pagar", "grupo": "Financeiro", "funcao": contas_a_pagar,
                     "parametros": ["status", "categoria", "texto"]},
    "fluxo_caixa": {"titulo": "Fluxo de caixa", "grupo": "Financeiro", "funcao": fluxo_caixa,
                    "parametros": ["data_inicial", "data_final"]},
    "fechamentos_caixa": {"titulo": "Fechamentos de caixa", "grupo": "Financeiro", "funcao": fechamentos_caixa,
                          "parametros": ["data_inicial", "data_final"]},
    "despesas": {"titulo": "Despesas por categoria", "grupo": "Financeiro", "funcao": despesas,
                 "parametros": ["data_inicial", "data_final"]},
    "estoque_atual": {"titulo": "Estoque atual", "grupo": "Estoque", "funcao": estoque_atual,
                      "parametros": ["categoria_id", "fornecedor_id", "texto", "apenas_baixo", "incluir_inativos"]},
    "estoque_baixo": {"titulo": "Estoque baixo / sugestão de compra", "grupo": "Estoque", "funcao": estoque_baixo,
                      "parametros": []},
    "movimentacoes_estoque": {"titulo": "Movimentações de estoque", "grupo": "Estoque", "funcao": movimentacoes_estoque,
                              "parametros": ["data_inicial", "data_final", "produto_id", "tipo", "motivo"]},
    "lotes_validade": {"titulo": "Lotes e validade", "grupo": "Estoque", "funcao": lotes_validade, "parametros": ["dias"]},
    "curva_abc": {"titulo": "Curva ABC de produtos", "grupo": "Estoque", "funcao": curva_abc,
                  "parametros": ["data_inicial", "data_final"]},
    "clientes": {"titulo": "Clientes", "grupo": "Cadastros", "funcao": clientes_relatorio,
                 "parametros": ["texto", "incluir_inativos"]},
    "fornecedores": {"titulo": "Fornecedores", "grupo": "Cadastros", "funcao": fornecedores_relatorio,
                     "parametros": ["texto", "incluir_inativos"]},
    "produtos": {"titulo": "Cadastro de produtos", "grupo": "Cadastros", "funcao": produtos_relatorio,
                 "parametros": ["texto", "categoria_id", "fornecedor_id", "incluir_inativos"]},
    "usuarios": {"titulo": "Usuários e permissões", "grupo": "Cadastros", "funcao": usuarios_relatorio, "parametros": []},
}


def disponiveis() -> list[str]:
    """Chaves de todos os relatórios disponíveis (ordem de cadastro)."""
    return list(RELATORIOS.keys())


def info(chave: str) -> dict:
    if chave not in RELATORIOS:
        raise ErroRelatorio(f"Relatório inexistente: '{chave}'.")
    return RELATORIOS[chave]


def meta() -> dict:
    """Metadados para montar a tela de relatórios: ``{grupo: [ {chave, titulo, parametros} ]}``."""
    resultado: dict[str, list[dict]] = {}
    for chave, dados in RELATORIOS.items():
        resultado.setdefault(dados["grupo"], []).append(
            {"chave": chave, "titulo": dados["titulo"], "parametros": dados["parametros"]}
        )
    return resultado


def gerar(banco: Banco, chave: str, parametros: dict | None = None) -> dict:
    """Gera um relatório e devolve a estrutura padrão (ver módulo docstring)."""
    dados = info(chave)
    resultado = dados["funcao"](banco, dict(parametros or {}))
    resultado.setdefault("chave", chave)
    resultado.setdefault("titulo", dados["titulo"])
    resultado.setdefault("colunas", [])
    resultado.setdefault("linhas", [])
    resultado.setdefault("totais", {})
    resultado.setdefault("resumo", [])
    resultado.setdefault("periodo", "")
    resultado.setdefault("filtros", "")
    resultado["gerado_em"] = hoje()
    return resultado


def gerar_todos(banco: Banco, parametros: dict | None = None) -> dict[str, dict]:
    """Gera todos os relatórios de uma vez (usado no teste de fumaça)."""
    return {chave: gerar(banco, chave, parametros) for chave in RELATORIOS}


def formatar_linha(relatorio: dict, linha: dict) -> list[str]:
    """Converte uma linha em lista de textos já formatados (usado nas tabelas)."""
    return [_formata_valor(c, linha.get(c["chave"])) for c in relatorio["colunas"]]


def linhas_formatadas(relatorio: dict) -> list[list[str]]:
    return [formatar_linha(relatorio, l) for l in relatorio["linhas"]]


def valores_para_exportacao(relatorio: dict) -> list[list[Any]]:
    """Valores "crus" (números como números) para Excel/CSV."""
    resultado = []
    for linha in relatorio["linhas"]:
        valores = []
        for coluna in relatorio["colunas"]:
            v = linha.get(coluna["chave"])
            tipo = coluna["tipo"]
            if v is None:
                valores.append("")
            elif tipo == "dinheiro":
                valores.append(para_reais(v))
            elif tipo == "quantidade":
                valores.append(float(v))
            elif tipo in ("inteiro",):
                valores.append(int(v))
            elif tipo == "percentual":
                valores.append(float(v))
            elif tipo == "data":
                valores.append(formatar_data(v))
            else:
                valores.append(str(v))
        resultado.append(valores)
    return resultado
