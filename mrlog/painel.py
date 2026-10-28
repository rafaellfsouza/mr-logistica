"""
Painel de indicadores (tela inicial).

Reúne, em uma única chamada, tudo que o gestor quer ver ao abrir o sistema:

* vendas de hoje, do mês e ticket médio;
* lucro do dia/mês e margem;
* caixa aberto e saldo na gaveta;
* contas a receber (total e vencido) e contas a pagar;
* estoque: valor a custo, itens abaixo do mínimo, lotes vencendo/vencidos;
* série de vendas dos últimos dias (para o gráfico);
* alertas (estoque baixo, validade, contas vencidas, caixa fechado).
"""

from __future__ import annotations

from datetime import date, timedelta

from . import caixa as caixa_mod
from . import clientes as clientes_mod
from . import contas_pagar
from . import contas_receber
from . import estoque as estoque_mod
from . import fornecedores as fornecedores_mod
from . import produtos as produtos_mod
from . import vendas as vendas_mod
from .banco import Banco
from .utils import formatar_dinheiro, formatar_quantidade, hoje, primeiro_dia_mes, somar_dias


def indicadores(banco: Banco, dias_grafico: int = 14) -> dict:
    """Monta o dicionário completo do painel."""
    dia = hoje()
    mes_inicio = primeiro_dia_mes(dia)

    vendas_hoje = vendas_mod.resumo_dia(banco, dia)
    vendas_mes = banco.consultar_uma(
        """SELECT COUNT(*) AS qtd, COALESCE(SUM(total_liquido),0) AS total, COALESCE(SUM(lucro_liquido),0) AS lucro,
                  COALESCE(AVG(total_liquido),0) AS ticket
             FROM vw_vendas_resumo
            WHERE status<>'cancelada' AND data_venda BETWEEN ? AND ?""",
        (mes_inicio, dia),
    )
    ontem = somar_dias(dia, -1)
    vendas_ontem = vendas_mod.resumo_dia(banco, ontem)

    resumo_caixa = caixa_mod.resumo_dia(banco, dia)
    caixa_atual = caixa_mod.caixa_aberto(banco)
    saldo_gaveta = caixa_mod.valor_sistema(banco, int(caixa_atual["id"])) if caixa_atual else 0

    receber = contas_receber.resumo(banco)
    pagar = contas_pagar.resumo(banco)
    estoque = produtos_mod.resumo(banco)
    valor_estoque = estoque_mod.valor_estoque(banco)
    clientes = clientes_mod.resumo(banco)
    fornecedores = fornecedores_mod.resumo(banco)

    serie = _serie_vendas(banco, dias_grafico)
    top_produtos = _top_produtos(banco, dias=30, limite=5)
    ultimas_vendas = vendas_mod.listar(banco, data_inicial=somar_dias(dia, -7), limite=8)

    alertas = _alertas(banco, estoque, receber, pagar, resumo_caixa, caixa_atual)

    variacao = 0.0
    if int(vendas_ontem["total"] or 0) > 0:
        variacao = round((int(vendas_hoje["total"]) - int(vendas_ontem["total"])) * 100.0 / int(vendas_ontem["total"]), 1)

    return {
        "data": dia,
        "hoje": {
            "vendas": int(vendas_hoje["quantidade"]),
            "total": int(vendas_hoje["total"]),
            "lucro": int(vendas_hoje["lucro"]),
            "ticket_medio": int(vendas_hoje["ticket_medio"]),
            "itens": int(vendas_hoje["itens"]),
            "canceladas": int(vendas_hoje["canceladas"]),
        },
        "ontem": {"total": int(vendas_ontem["total"]), "vendas": int(vendas_ontem["quantidade"])},
        "variacao_hoje_pct": variacao,
        "mes": {
            "vendas": int(vendas_mes["qtd"] or 0),
            "total": int(vendas_mes["total"] or 0),
            "lucro": int(vendas_mes["lucro"] or 0),
            "ticket_medio": int(round(float(vendas_mes["ticket"] or 0))),
        },
        "caixa": {
            "aberto": bool(caixa_atual),
            "caixa_id": int(caixa_atual["id"]) if caixa_atual else None,
            "saldo_gaveta": saldo_gaveta,
            "operador": (caixa_atual["usuario_nome"] if caixa_atual else "") or "",
            "abertura": int(caixa_atual["valor_abertura"] or 0) if caixa_atual else 0,
        },
        "receber": receber,
        "pagar": pagar,
        "estoque": {
            **estoque,
            "valor_custo": valor_estoque["custo"],
            "valor_venda": valor_estoque["venda"],
            "margem_potencial": valor_estoque["margem_potencial"],
        },
        "clientes": clientes,
        "fornecedores": fornecedores,
        "serie_vendas": serie,
        "top_produtos": top_produtos,
        "ultimas_vendas": [
            {
                "id": v["id"],
                "numero": int(v["numero"]),
                "cliente": v["cliente_nome"] or "Consumidor final",
                "total": int(v["total"] or 0),
                "hora": str(v["criada_em"] or "")[11:16],
                "status": v["status"],
                "formas": v["formas"] or "",
            }
            for v in ultimas_vendas
        ],
        "alertas": alertas,
    }


def _serie_vendas(banco: Banco, dias: int) -> list[dict]:
    """Total vendido por dia nos últimos ``dias`` (base do gráfico do painel)."""
    dias = max(1, min(120, int(dias)))
    inicio = somar_dias(hoje(), -(dias - 1))
    linhas = banco.consultar(
        """SELECT data_venda AS dia, COUNT(*) AS qtd, COALESCE(SUM(total_liquido),0) AS total,
                  COALESCE(SUM(lucro_liquido),0) AS lucro
             FROM vw_vendas_resumo
            WHERE status<>'cancelada' AND data_venda BETWEEN ? AND ?
            GROUP BY data_venda""",
        (inicio, hoje()),
    )
    por_dia = {str(l["dia"]): l for l in linhas}
    serie = []
    base = date.fromisoformat(inicio)
    for i in range(dias):
        dia = (base + timedelta(days=i)).isoformat()
        linha = por_dia.get(dia)
        serie.append(
            {
                "dia": dia,
                "rotulo": dia[8:10] + "/" + dia[5:7],
                "quantidade": int(linha["qtd"]) if linha else 0,
                "total": int(linha["total"]) if linha else 0,
                "lucro": int(linha["lucro"]) if linha else 0,
            }
        )
    return serie


def _top_produtos(banco: Banco, dias: int = 30, limite: int = 5) -> list[dict]:
    inicio = somar_dias(hoje(), -max(0, dias - 1))
    # venda_itens não tem a coluna unidade_base: usamos a do produto (fallback p/ unidade vendida)
    linhas = banco.consultar(
        """SELECT vi.nome, SUM(vi.quantidade_base) AS quantidade,
                  COALESCE(p.unidade_base, vi.unidade) AS unidade,
                  SUM(vi.total_liquido) AS total, SUM(vi.lucro) AS lucro
             FROM venda_itens vi
             JOIN vendas v ON v.id = vi.venda_id
             LEFT JOIN produtos p ON p.id = vi.produto_id
            WHERE v.status IN ('concluida','parcialmente_devolvida') AND v.data_venda BETWEEN ? AND ?
            GROUP BY vi.produto_id, vi.nome, unidade
            ORDER BY total DESC LIMIT ?""",
        (inicio, hoje(), int(limite)),
    )
    return [
        {
            "nome": l["nome"],
            "quantidade": float(l["quantidade"] or 0),
            "unidade": l["unidade"] or "",
            "total": int(l["total"] or 0),
            "lucro": int(l["lucro"] or 0),
        }
        for l in linhas
    ]


def _alertas(banco: Banco, estoque: dict, receber: dict, pagar: dict, resumo_caixa: dict, caixa_atual) -> list[dict]:
    """Lista de alertas priorizados para o painel (cada um vira um card clicável)."""
    alertas: list[dict] = []

    if not caixa_atual:
        alertas.append(
            {
                "nivel": "atencao",
                "titulo": "Caixa fechado",
                "texto": "Abra o caixa para registrar as vendas do dia.",
                "tela": "caixa",
                "quantidade": 0,
            }
        )
    if estoque.get("estoque_baixo"):
        alertas.append(
            {
                "nivel": "critico",
                "titulo": "Estoque baixo",
                "texto": f"{estoque['estoque_baixo']} produto(s) no mínimo ou abaixo dele.",
                "tela": "estoque_baixo",
                "quantidade": int(estoque["estoque_baixo"]),
            }
        )
    if estoque.get("lotes_vencidos"):
        alertas.append(
            {
                "nivel": "critico",
                "titulo": "Lotes vencidos",
                "texto": f"{estoque['lotes_vencidos']} lote(s) com validade vencida em estoque.",
                "tela": "lotes",
                "quantidade": int(estoque["lotes_vencidos"]),
            }
        )
    if estoque.get("lotes_a_vencer"):
        alertas.append(
            {
                "nivel": "atencao",
                "titulo": "Validade próxima",
                "texto": f"{estoque['lotes_a_vencer']} lote(s) vencem nos próximos 30 dias.",
                "tela": "lotes",
                "quantidade": int(estoque["lotes_a_vencer"]),
            }
        )
    if receber.get("qtd_vencidas"):
        alertas.append(
            {
                "nivel": "critico",
                "titulo": "Fiado vencido",
                "texto": f"{receber['qtd_vencidas']} conta(s) vencida(s) somando {formatar_dinheiro(receber['vencido'])}.",
                "tela": "contas_receber",
                "quantidade": int(receber["qtd_vencidas"]),
            }
        )
    if pagar.get("qtd_vencidas"):
        alertas.append(
            {
                "nivel": "atencao",
                "titulo": "Contas a pagar vencidas",
                "texto": f"{pagar['qtd_vencidas']} conta(s) vencida(s) somando {formatar_dinheiro(pagar['vencido'])}.",
                "tela": "contas_pagar",
                "quantidade": int(pagar["qtd_vencidas"]),
            }
        )
    if estoque.get("sem_barras"):
        alertas.append(
            {
                "nivel": "info",
                "titulo": "Produtos sem código de barras",
                "texto": f"{estoque['sem_barras']} produto(s) não têm código — gere etiquetas para bipar mais rápido.",
                "tela": "etiquetas",
                "quantidade": int(estoque["sem_barras"]),
            }
        )
    divergencias = estoque_mod.verificar_saldos(banco)
    if divergencias:
        alertas.append(
            {
                "nivel": "atencao",
                "titulo": "Saldos divergentes",
                "texto": f"{len(divergencias)} produto(s) com saldo diferente do histórico. Recalcule em Estoque > Manutenção.",
                "tela": "estoque_manutencao",
                "quantidade": len(divergencias),
            }
        )
    return alertas


def texto_resumo(banco: Banco) -> list[str]:
    """Frases prontas (para a barra de status e o cabeçalho do painel)."""
    dados = indicadores(banco)
    return [
        f"Hoje: {dados['hoje']['vendas']} venda(s) — {formatar_dinheiro(dados['hoje']['total'])}",
        f"Lucro hoje: {formatar_dinheiro(dados['hoje']['lucro'])}",
        f"Mês: {formatar_dinheiro(dados['mes']['total'])} em {dados['mes']['vendas']} venda(s)",
        f"Caixa: {formatar_dinheiro(dados['caixa']['saldo_gaveta'])} ({'aberto' if dados['caixa']['aberto'] else 'fechado'})",
        f"A receber: {formatar_dinheiro(dados['receber']['a_receber'])}",
        f"A pagar: {formatar_dinheiro(dados['pagar']['a_pagar'])}",
        f"Estoque a custo: {formatar_dinheiro(dados['estoque']['valor_custo'])}",
    ]


def cartoes(banco: Banco) -> list[dict]:
    """Cartões prontos para desenhar no painel (título, valor, detalhe e cor)."""
    d = indicadores(banco)
    return [
        {
            "titulo": "Vendas hoje",
            "valor": formatar_dinheiro(d["hoje"]["total"]),
            "detalhe": f"{d['hoje']['vendas']} venda(s) • ticket {formatar_dinheiro(d['hoje']['ticket_medio'])}",
            "cor": "sucesso" if d["hoje"]["total"] > 0 else "neutro",
            "tela": "vendas",
        },
        {
            "titulo": "Lucro hoje",
            "valor": formatar_dinheiro(d["hoje"]["lucro"]),
            "detalhe": (
                f"ontem: {formatar_dinheiro(d['ontem']['total'])} "
                f"({d['variacao_hoje_pct']:+.1f}%)".replace(".", ",")
            ),
            "cor": "sucesso" if d["hoje"]["lucro"] >= 0 else "perigo",
            "tela": "relatorios",
        },
        {
            "titulo": "Vendas do mês",
            "valor": formatar_dinheiro(d["mes"]["total"]),
            "detalhe": f"{d['mes']['vendas']} venda(s) • lucro {formatar_dinheiro(d['mes']['lucro'])}",
            "cor": "info",
            "tela": "relatorios",
        },
        {
            "titulo": "Caixa (gaveta)",
            "valor": formatar_dinheiro(d["caixa"]["saldo_gaveta"]),
            "detalhe": ("Aberto por " + d["caixa"]["operador"]) if d["caixa"]["aberto"] else "Caixa fechado",
            "cor": "sucesso" if d["caixa"]["aberto"] else "atencao",
            "tela": "caixa",
        },
        {
            "titulo": "A receber (fiado)",
            "valor": formatar_dinheiro(d["receber"]["a_receber"]),
            "detalhe": f"{d['receber']['qtd_abertas']} título(s) • vencido {formatar_dinheiro(d['receber']['vencido'])}",
            "cor": "perigo" if d["receber"]["vencido"] else "info",
            "tela": "contas_receber",
        },
        {
            "titulo": "A pagar",
            "valor": formatar_dinheiro(d["pagar"]["a_pagar"]),
            "detalhe": f"{d['pagar']['qtd_abertas']} conta(s) • vence em 7 dias {formatar_dinheiro(d['pagar']['vencendo_7_dias'])}",
            "cor": "atencao" if d["pagar"]["a_pagar"] else "neutro",
            "tela": "contas_pagar",
        },
        {
            "titulo": "Estoque (custo)",
            "valor": formatar_dinheiro(d["estoque"]["valor_custo"]),
            "detalhe": f"{d['estoque']['ativos']} produto(s) ativo(s) • venda {formatar_dinheiro(d['estoque']['valor_venda'])}",
            "cor": "info",
            "tela": "produtos",
        },
        {
            "titulo": "Alertas de estoque",
            "valor": str(d["estoque"]["estoque_baixo"]),
            "detalhe": f"vencidos: {d['estoque']['lotes_vencidos']} • a vencer: {d['estoque']['lotes_a_vencer']}",
            "cor": "perigo" if d["estoque"]["estoque_baixo"] else "sucesso",
            "tela": "estoque_baixo",
        },
    ]


def top_produtos_texto(banco: Banco, dias: int = 30, limite: int = 5) -> list[str]:
    return [
        f"{i}. {p['nome']} — {formatar_quantidade(p['quantidade'])} {p['unidade']} ({formatar_dinheiro(p['total'])})"
        for i, p in enumerate(_top_produtos(banco, dias, limite), start=1)
    ]
