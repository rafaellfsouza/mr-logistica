"""
Impressão: recibo **não fiscal** (bobina 80 mm ou A4), etiquetas e relatórios.

Como o sistema não usa spooler de terceiros, a impressão funciona assim:

1. o documento é gerado em **PDF** (arquivo temporário na pasta de dados);
2. no Windows, se houver impressora padrão configurada, o arquivo é enviado
   direto para ela (``ShellExecute "print"``);
3. em qualquer sistema, o arquivo também é aberto no visualizador padrão, de onde
   o usuário pode imprimir, salvar ou enviar por e-mail.

Ou seja: **sempre** sai alguma coisa — nunca um botão que não faz nada.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .banco import Banco
from .caminhos import pasta_temporaria
from .utils import formatar_data, formatar_dinheiro, formatar_quantidade, hoje, limitar

LARGURA_80MM = 226.77  # pontos (80 mm)
LARGURA_58MM = 164.41  # pontos (58 mm, impressora térmica compacta)


class ErroImpressao(Exception):
    """Falha ao gerar ou enviar para impressão."""


# --------------------------------------------------------------------------------------
# Recibo não fiscal
# --------------------------------------------------------------------------------------


def gerar_recibo_pdf(banco: Banco, venda_id: int, destino=None, largura: str = "80mm") -> str:
    """Gera o PDF do recibo não fiscal de uma venda e devolve o caminho do arquivo."""
    from . import vendas as vendas_mod

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover
        raise ErroImpressao("Biblioteca reportlab não instalada. Reinstale o aplicativo.") from exc

    dados = vendas_mod.dados_para_recibo(banco, venda_id)
    if destino is None:
        destino = pasta_temporaria() / f"recibo-{dados['numero']:06d}.pdf"
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    termica = str(largura).lower() in ("80mm", "58mm", "termica")
    largura_pagina = LARGURA_58MM if str(largura).lower() == "58mm" else (LARGURA_80MM if termica else A4[0])
    altura_pagina = 100000  # será recalculada; usamos uma página alta e depois "cortamos"
    margem = 10 if termica else 40
    fonte = "Helvetica"
    fonte_negrito = "Helvetica-Bold"
    corpo = 7.5 if termica else 10
    entrelinha = corpo + 3.2
    largura_texto = largura_pagina - 2 * margem
    chars = max(20, int(largura_texto / (corpo * 0.52)))

    # ---------------------------------------------------------------- montagem do texto
    blocos: list[tuple[str, dict]] = []

    def linha(texto="", estilo=None):
        blocos.append((str(texto), estilo or {}))

    def separador(char="-", espaco_antes=2, espaco_depois=2):
        blocos.append((char * chars, {"antes": espaco_antes, "depois": espaco_depois, "cinza": True}))

    empresa = dados["empresa"]
    linha(empresa.get("nome") or "MR Logística", {"negrito": True, "tamanho": corpo + (2 if termica else 3), "centralizar": True})
    if empresa.get("documento"):
        linha(f"CNPJ/CPF: {empresa['documento']}", {"centralizar": True})
    if empresa.get("endereco"):
        for parte in _quebrar(empresa["endereco"], chars):
            linha(parte, {"centralizar": True})
    contatos = " | ".join(x for x in [empresa.get("telefone"), empresa.get("email")] if x)
    if contatos:
        linha(contatos, {"centralizar": True})
    separador("=")
    linha("COMPROVANTE NÃO FISCAL DE VENDA", {"negrito": True, "centralizar": True})
    linha(f"Cupom nº {dados['numero']:06d}", {"negrito": True, "centralizar": True})
    linha(f"Data: {formatar_data(dados['data'], com_hora=True)}", {"centralizar": True})
    if dados.get("vendedor"):
        linha(f"Vendedor: {dados['vendedor']}", {"centralizar": True})
    separador()
    linha(f"Cliente: {dados['cliente']['nome']}", {"negrito": True})
    if dados["cliente"].get("documento"):
        linha(f"CPF/CNPJ: {dados['cliente']['documento']}")
    if dados["cliente"].get("telefone"):
        linha(f"Telefone: {dados['cliente']['telefone']}")
    if dados["cliente"].get("endereco"):
        for parte in _quebrar(dados["cliente"]["endereco"], chars):
            linha(parte)
    separador()

    # Itens
    linha(_alinhar_colunas(["CÓD", "ITEM", "QTD", "UNIT", "TOTAL"], [10, chars - 34, 7, 8, 9]), {"negrito": True, "monoespacado": True})
    separador(".", 0, 1)
    for item in dados["itens"]:
        nome = limitar(item["nome"], max(12, chars - 34))
        qtd = formatar_quantidade(item["quantidade"])
        unit = _dinheiro_curto(item["preco"])
        total = _dinheiro_curto(item["total"])
        linha(
            _alinhar_colunas(
                [limitar(item["codigo"], 10), nome, qtd, unit, total],
                [10, max(8, chars - 34), 7, 8, 9],
                alinhamentos=("e", "e", "d", "d", "d"),
            ),
            {"monoespacado": True},
        )
        if item.get("desconto"):
            linha(f"{'':>10}desconto do item: -{formatar_dinheiro(item['desconto'])}", {"cinza": True, "monoespacado": True})
        if item.get("devolvido"):
            linha(
                f"{'':>10}(devolvido: {formatar_quantidade(item['devolvido'])})",
                {"cinza": True, "monoespacado": True},
            )
    separador(".", 1, 2)

    def linha_valor(rotulo: str, valor: str, estilo=None):
        linha(_alinhar_colunas([rotulo, valor], [max(10, chars - 16), 16], ("e", "d")), estilo or {"monoespacado": True})

    linha_valor("SUBTOTAL", formatar_dinheiro(dados["subtotal"]))
    if dados["desconto"]:
        linha_valor("DESCONTO", "-" + formatar_dinheiro(dados["desconto"]))
    if dados["acrescimo"]:
        linha_valor("ACRÉSCIMO", formatar_dinheiro(dados["acrescimo"]))
    linha_valor("TOTAL", formatar_dinheiro(dados["total"]), {"negrito": True, "tamanho": corpo + 1.5, "monoespacado": True})
    separador()

    # Pagamentos
    linha("PAGAMENTO", {"negrito": True})
    for pg in dados["pagamentos"]:
        texto = f"{pg['forma']}: {formatar_dinheiro(pg['valor'])}"
        if pg["forma"] == "Dinheiro":
            texto = f"Dinheiro: {formatar_dinheiro(pg['valor'])} (recebido {formatar_dinheiro(pg['recebido'])})"
        if pg.get("parcelas") and pg["parcelas"] > 1:
            texto += f" em {pg['parcelas']}x de {formatar_dinheiro(int(round(int(pg['valor']) / pg['parcelas'])))}"
        if pg.get("operadora"):
            texto += f" — {pg['operadora']}"
        linha(texto, {"monoespacado": True})
    if dados["troco"]:
        linha(f"TROCO: {formatar_dinheiro(dados['troco'])}", {"negrito": True, "monoespacado": True})
    if dados["fiado"]:
        linha(f"FIADO (conta a receber): {formatar_dinheiro(dados['fiado'])}", {"negrito": True})
    if dados.get("observacao"):
        separador()
        for parte in _quebrar(f"Obs.: {dados['observacao']}", chars):
            linha(parte, {"cinza": True})
    if dados.get("devolucoes"):
        separador()
        linha("DEVOLUÇÕES", {"negrito": True})
        for d in dados["devolucoes"]:
            linha(f"{formatar_data(d['data'], True)} — {formatar_dinheiro(d['valor'])} ({d['tipo']})", {"cinza": True})
            if d.get("motivo"):
                for parte in _quebrar(f"motivo: {d['motivo']}", chars):
                    linha("  " + parte, {"cinza": True})
    if dados.get("cancelamento"):
        separador("=")
        linha("*** VENDA CANCELADA ***", {"negrito": True, "centralizar": True})
        c = dados["cancelamento"]
        linha(f"Motivo: {c['motivo']}", {"centralizar": True})
        linha(f"Em: {formatar_data(c['data'], True)}", {"centralizar": True})
        separador("=")

    separador("-")
    if dados.get("mensagem"):
        for parte in _quebrar(dados["mensagem"], chars):
            linha(parte, {"centralizar": True})
    linha(f"{dados['itens_count']} item(ns) — {formatar_data(dados['emitido_em'], True)}", {"centralizar": True, "cinza": True})
    linha("Documento não fiscal — uso interno / controle de garantia.", {"centralizar": True, "cinza": True})
    linha("MR Logística — sistema de gestão local e offline.", {"centralizar": True, "cinza": True})

    # ---------------------------------------------------------------- renderização
    altura_total = sum(entrelinha + float(e.get("antes", 0)) + float(e.get("depois", 0)) for _, e in blocos) + 20
    if not termica:
        # Em A4 usa página padrão e quebra em várias páginas se necessário.
        altura_pagina = A4[1]
        altura_total = altura_pagina
    else:
        altura_pagina = max(altura_total + 20, 200)

    try:
        c = canvas.Canvas(str(destino), pagesize=(largura_pagina, altura_pagina))
    except Exception as exc:  # pragma: no cover
        raise ErroImpressao(f"Não foi possível criar o PDF: {exc}") from exc
    c.setTitle(f"Recibo não fiscal — cupom {dados['numero']:06d}")
    c.setAuthor("MR Logística")

    y = altura_pagina - margem
    for texto, estilo in blocos:
        y -= float(estilo.get("antes", 0))
        tamanho = float(estilo.get("tamanho", corpo))
        nome_fonte = fonte_negrito if estilo.get("negrito") else fonte
        if estilo.get("monoespacado") and not termica:
            nome_fonte = "Courier-Bold" if estilo.get("negrito") else "Courier"
            tamanho = corpo - 1
        c.setFont(nome_fonte, tamanho)
        if estilo.get("cinza"):
            c.setFillColorRGB(0.35, 0.35, 0.35)
        else:
            c.setFillColorRGB(0, 0, 0)
        x = margem
        if estilo.get("centralizar"):
            try:
                largura_real = c.stringWidth(texto, nome_fonte, tamanho)
            except Exception:
                largura_real = len(texto) * tamanho * 0.5
            x = margem + max(0, (largura_texto - largura_real) / 2)
        for parte in _quebrar(texto, chars if not estilo.get("monoespacado") else chars + 6) or [""]:
            c.drawString(x, y, parte)
            y -= entrelinha
            if not termica and y < margem:
                c.showPage()
                y = altura_pagina - margem
                c.setFont(nome_fonte, tamanho)
        y -= float(estilo.get("depois", 0))
    c.showPage()
    c.save()
    return str(destino)


def _dinheiro_curto(centavos: int) -> str:
    """Formato compacto para caber na coluna: ``1.234,56``."""
    return formatar_dinheiro(centavos, simbolo=False)


def _quebrar(texto: str, chars: int) -> list[str]:
    """Quebra um texto em linhas de no máximo ``chars`` caracteres (sem cortar palavras)."""
    texto = str(texto or "")
    if not texto:
        return [""]
    if chars <= 5:
        return [texto[i : i + chars] for i in range(0, len(texto), chars)] or [""]
    linhas, atual = [], ""
    for palavra in texto.split():
        candidato = f"{atual} {palavra}".strip()
        if len(candidato) <= chars:
            atual = candidato
        else:
            if atual:
                linhas.append(atual)
            while len(palavra) > chars:
                linhas.append(palavra[:chars])
                palavra = palavra[chars:]
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas or [""]


def _alinhar_colunas(valores: list[str], larguras: list[int], alinhamentos=None) -> str:
    """Monta uma linha de texto com colunas fixas (visual de cupom)."""
    alinhamentos = list(alinhamentos or ["e"] * len(valores))
    partes = []
    for valor, largura, alin in zip(valores, larguras, alinhamentos):
        texto = limitar(valor, max(1, largura))
        if alin == "d":
            partes.append(texto.rjust(max(1, largura)))
        elif alin == "c":
            partes.append(texto.center(max(1, largura)))
        else:
            partes.append(texto.ljust(max(1, largura)))
    return "".join(partes).rstrip()


# --------------------------------------------------------------------------------------
# Impressão / abertura de arquivos
# --------------------------------------------------------------------------------------


def imprimir_arquivo(caminho: str | Path, silencioso: bool = False) -> tuple[bool, str]:
    """Manda um PDF para a impressora padrão.

    Devolve ``(sucesso, mensagem)``. Se não conseguir imprimir direto, abre o
    arquivo no visualizador padrão (que sempre permite imprimir).
    """
    arquivo = Path(caminho)
    if not arquivo.exists():
        return False, f"Arquivo não encontrado: {arquivo}"
    sistema = sys.platform
    try:
        if sistema.startswith("win"):
            if not silencioso:
                os.startfile(str(arquivo), "print")  # type: ignore[attr-defined]
                return True, "Enviado para a impressora padrão."
            os.startfile(str(arquivo))  # type: ignore[attr-defined]
            return True, "Documento aberto para impressão."
        if sistema == "darwin":
            subprocess.Popen(["open", str(arquivo)])
            return True, "Documento aberto no visualizador (use Imprimir)."
        comandos = ["xdg-open", "gio", "gvfs-open"]
        for comando in comandos:
            if _existe_comando(comando):
                subprocess.Popen([comando, str(arquivo)])
                return True, f"Documento aberto com {comando} (use Imprimir)."
        return False, (
            "Não foi encontrado um visualizador de PDF no sistema. "
            f"O arquivo está salvo em: {arquivo}"
        )
    except Exception as exc:  # pragma: no cover - depende do sistema do usuário
        return False, f"Falha ao abrir/imprimir: {exc}. Arquivo salvo em {arquivo}"


def _existe_comando(nome: str) -> bool:
    from shutil import which

    return which(nome) is not None


def abrir_pasta(caminho: str | Path) -> tuple[bool, str]:
    """Abre o gerenciador de arquivos na pasta indicada (usado em backup/relatórios)."""
    pasta = Path(caminho)
    if pasta.is_file():
        pasta = pasta.parent
    if not pasta.exists():
        return False, "Pasta não encontrada."
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(pasta))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(pasta)])
        else:
            subprocess.Popen(["xdg-open", str(pasta)])
        return True, "Pasta aberta."
    except Exception as exc:
        return False, f"Não foi possível abrir a pasta: {exc}"


def listar_impressoras() -> list[str]:
    """Lista as impressoras instaladas (somente Windows; nos demais retorna vazio)."""
    if not sys.platform.startswith("win"):
        return []
    try:  # pragma: no cover - só no Windows
        import win32print  # type: ignore

        return [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)]
    except Exception:
        return []


def impressora_padrao() -> str:
    if not sys.platform.startswith("win"):
        return ""
    try:  # pragma: no cover
        import win32print  # type: ignore

        return win32print.GetDefaultPrinter()
    except Exception:
        return ""


# --------------------------------------------------------------------------------------
# Outros documentos
# --------------------------------------------------------------------------------------


def gerar_etiquetas_pdf(banco: Banco, itens: list[dict], destino=None, colunas: int = 2, linhas_por_pagina: int = 7,
                        largura_mm: float = 101.6 / 2, altura_mm: float = 33.9) -> str:
    """Gera a folha de etiquetas em PDF — delega para :mod:`mrlog.etiquetas`."""
    from . import etiquetas

    ids = [int(i["produto_id"]) if isinstance(i, dict) else int(i) for i in itens]
    return etiquetas.gerar_pdf(
        banco, ids, destino, colunas=colunas, linhas_por_pagina=linhas_por_pagina,
        largura_mm=largura_mm, altura_mm=altura_mm,
        quantidades=[int(i.get("quantidade", 1)) if isinstance(i, dict) else 1 for i in itens],
    )


def gerar_ficha_produto_pdf(banco: Banco, produto_id: int, destino=None) -> str:
    """Ficha completa do produto em PDF (cadastro + estoque + últimas movimentações)."""
    from . import estoque as estoque_mod
    from . import produtos as produtos_mod

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise ErroImpressao("Biblioteca reportlab não instalada.") from exc

    ficha = estoque_mod.ficha_produto(banco, produto_id)
    produto = ficha["produto"]
    destino = Path(destino) if destino else pasta_temporaria() / f"ficha-{produto['codigo']}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=14, textColor=colors.HexColor("#1F4E79"))
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontSize=9, leading=12)

    dados_gerais = [
        ["Código", str(produto["codigo"]), "Código de barras", str(produto["codigo_barras"] or "—")],
        ["Nome", str(produto["nome"]), "Marca", str(produto["marca"] or "—")],
        ["Categoria", str(produto["categoria_nome"] or "—"), "Fornecedor", str(produto["fornecedor_nome"] or "—")],
        ["Unidade de estoque", str(produto["unidade_base"]), "Unidade de venda", f"{produto['unidade_venda']} (fator {formatar_quantidade(produto['fator_venda'])})"],
        ["Preço de custo", formatar_dinheiro(produto["preco_custo"]), "Preço de venda", formatar_dinheiro(produto["preco_venda"])],
        ["Margem", f"{float(produto['margem_pct'] or 0):.2f}%".replace(".", ","), "Estoque atual", f"{formatar_quantidade(ficha['saldo'])} {produto['unidade_base']}"],
        ["Estoque mínimo", formatar_quantidade(produto["estoque_minimo"]), "Estoque máximo", formatar_quantidade(produto["estoque_maximo"]) or "—"],
        ["Localização", str(produto["localizacao"] or "—"), "Controla lote", "Sim" if produto["controla_lote"] else "Não"],
    ]
    historia: list[Any] = [
        Paragraph("Ficha do produto", titulo),
        Paragraph(f"Gerada em {formatar_data(hoje(), True)} — MR Logística", normal),
        Spacer(1, 8),
    ]
    tabela = Table(dados_gerais, colWidths=[38 * mm, 52 * mm, 38 * mm, 52 * mm])
    tabela.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3E0")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F6FA")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F2F6FA")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    historia.append(tabela)

    if ficha["lotes"]:
        historia += [Spacer(1, 10), Paragraph("<b>Lotes em estoque</b>", normal), Spacer(1, 4)]
        dados_lotes = [["Lote", "Validade", "Saldo", "Qtd inicial", "Custo unit."]]
        for l in ficha["lotes"]:
            dados_lotes.append(
                [
                    str(l["numero"] or "s/nº"),
                    formatar_data(l["validade"]) or "—",
                    formatar_quantidade(l["quantidade_atual"]),
                    formatar_quantidade(l["quantidade_inicial"]),
                    formatar_dinheiro(l["custo_unitario"]),
                ]
            )
        t = Table(dados_lotes, colWidths=[35 * mm, 30 * mm, 30 * mm, 35 * mm, 40 * mm])
        t.setStyle(_estilo_tabela_simples())
        historia.append(t)

    if ficha["movimentacoes"]:
        historia += [Spacer(1, 10), Paragraph(f"<b>Últimas movimentações ({ficha['periodo_dias']} dias)</b>", normal), Spacer(1, 4)]
        dados_mov = [["Data/Hora", "Tipo", "Motivo", "Qtd", "Saldo após", "Usuário"]]
        for m in ficha["movimentacoes"][:40]:
            dados_mov.append(
                [
                    formatar_data(m["criado_em"], True),
                    str(m["tipo"]),
                    str(m["motivo"]),
                    formatar_quantidade(m["quantidade"]),
                    formatar_quantidade(m["saldo_apos"]),
                    str(m["usuario_nome"] or ""),
                ]
            )
        t = Table(dados_mov, colWidths=[32 * mm, 18 * mm, 34 * mm, 20 * mm, 24 * mm, 42 * mm])
        t.setStyle(_estilo_tabela_simples())
        historia.append(t)

    try:
        doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=12 * mm, bottomMargin=14 * mm, title=f"Ficha {produto['codigo']}")
        doc.build(historia)
    except Exception as exc:
        raise ErroImpressao(f"Falha ao gerar a ficha: {exc}") from exc
    return str(destino)


def gerar_fechamento_caixa_pdf(banco: Banco, caixa_id: int, destino=None) -> str:
    """Relatório de fechamento de caixa em PDF (conferência de gaveta).

    Mostra abertura, entradas e saídas por categoria, totais por forma de
    pagamento, valor esperado pelo sistema, valor contado e a diferença.
    """
    from . import caixa as caixa_mod
    from . import configuracoes as config_mod

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise ErroImpressao("Biblioteca reportlab não instalada.") from exc

    caixa = caixa_mod.pegar(banco, caixa_id)
    if not caixa:
        raise ErroImpressao("Caixa não encontrado.")
    posicao = caixa_mod.posicao(banco, caixa_id)
    empresa = config_mod.empresa(banco)

    destino = Path(destino) if destino else pasta_temporaria() / f"fechamento-caixa-{caixa['data']}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=14, textColor=colors.HexColor("#1F4E79"))
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontSize=9, leading=12)

    historia: list[Any] = [
        Paragraph(str(empresa.get("nome") or "MR Logística"), titulo),
        Paragraph(f"Fechamento de caixa — {formatar_data(caixa['data'])}", normal),
        Paragraph(
            f"Operador: {caixa['usuario_nome'] or '—'} • "
            f"Abertura: {formatar_data(caixa['abertura_em'], True) if caixa['abertura_em'] else '—'} • "
            f"Status: {str(caixa['status']).capitalize()}",
            normal,
        ),
        Spacer(1, 8),
    ]

    resumo = [
        ["Abertura (fundo de troco)", formatar_dinheiro(posicao["abertura"])],
        ["Vendas (quantidade)", str(posicao["qtd_vendas"])],
        ["Vendas (total bruto)", formatar_dinheiro(posicao["total_vendas"])],
        ["Lucro das vendas", formatar_dinheiro(posicao["lucro_vendas"])],
        ["Total recebido", formatar_dinheiro(posicao["total_recebido"])],
        ["Total pago (saídas)", formatar_dinheiro(posicao["total_pago"])],
    ]
    if caixa["status"] == "fechado":
        resumo += [
            ["Valor esperado na gaveta (sistema)", formatar_dinheiro(posicao["valor_sistema"])],
            ["Valor contado", formatar_dinheiro(int(caixa["valor_fechamento"] or 0))],
            ["Diferença (quebra de caixa)", formatar_dinheiro(posicao["diferenca"])],
            ["Fechamento em", formatar_data(caixa["fechamento_em"], True) if caixa["fechamento_em"] else "—"],
        ]
    else:
        resumo.append(["Valor esperado na gaveta (parcial)", formatar_dinheiro(posicao["valor_sistema"])])
    tabela_resumo = Table(resumo, colWidths=[95 * mm, 55 * mm], hAlign="LEFT")
    tabela_resumo.setStyle(_estilo_tabela_simples())
    historia.append(tabela_resumo)

    if posicao["formas"]:
        historia += [Spacer(1, 10), Paragraph("<b>Totais por forma de pagamento</b>", normal), Spacer(1, 4)]
        dados = [["Forma", "Entradas", "Saídas", "Saldo"]]
        for forma, valores in sorted(posicao["formas"].items()):
            dados.append([forma, formatar_dinheiro(valores["entradas"]), formatar_dinheiro(valores["saidas"]),
                          formatar_dinheiro(valores["saldo"])])
        tabela = Table(dados, colWidths=[55 * mm, 35 * mm, 35 * mm, 35 * mm], hAlign="LEFT")
        tabela.setStyle(_estilo_tabela_simples())
        historia.append(tabela)

    if posicao["categorias"]:
        historia += [Spacer(1, 10), Paragraph("<b>Movimentações por categoria</b>", normal), Spacer(1, 4)]
        dados = [["Categoria", "Tipo", "Qtd", "Total"]]
        for item in posicao["categorias"]:
            dados.append([item["categoria"], "Entrada" if item["tipo"] == "entrada" else "Saída",
                          str(item["quantidade"]), formatar_dinheiro(item["total"])])
        tabela = Table(dados, colWidths=[60 * mm, 30 * mm, 20 * mm, 40 * mm], hAlign="LEFT")
        tabela.setStyle(_estilo_tabela_simples())
        historia.append(tabela)

    movimentos = caixa_mod.movimentos(banco, caixa_id)
    if movimentos:
        historia += [Spacer(1, 10), Paragraph(f"<b>Lançamentos ({len(movimentos)})</b>", normal), Spacer(1, 4)]
        dados = [["Hora", "Categoria", "Descrição", "Forma", "Valor"]]
        for movimento in movimentos:
            sinal = "" if movimento["tipo"] == "entrada" else "-"
            dados.append([
                formatar_data(movimento["criado_em"], True)[11:16],
                movimento["categoria"],
                limitar(movimento["descricao"] or "", 48),
                movimento["forma"] or "",
                f"{sinal}{formatar_dinheiro(int(movimento['valor'] or 0))}",
            ])
        tabela = Table(dados, colWidths=[16 * mm, 32 * mm, 62 * mm, 26 * mm, 26 * mm], hAlign="LEFT", repeatRows=1)
        tabela.setStyle(_estilo_tabela_simples())
        historia.append(tabela)

    if caixa["observacao"]:
        historia += [Spacer(1, 10), Paragraph(f"<b>Observação:</b> {caixa['observacao']}", normal)]
    historia += [Spacer(1, 14), Paragraph(f"Documento gerado em {formatar_data(hoje(), True)} pelo MR Logística "
                                          "(relatório gerencial — não fiscal).", normal)]

    try:
        doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=12 * mm, bottomMargin=14 * mm,
                                title=f"Fechamento de caixa {caixa['data']}")
        doc.build(historia)
    except Exception as exc:
        raise ErroImpressao(f"Falha ao gerar o fechamento: {exc}") from exc
    return str(destino)


def _estilo_tabela_simples():
    from reportlab.lib import colors as _c
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.25, _c.HexColor("#C9D3E0")),
            ("BACKGROUND", (0, 0), (-1, 0), _c.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), _c.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_c.white, _c.HexColor("#F7FAFD")]),
        ]
    )


# --------------------------------------------------------------------------------------
# Comprovantes financeiros (contas a receber / contas a pagar)
# --------------------------------------------------------------------------------------


def _cabecalho_documento(empresa: dict, titulo: str, subtitulo: str = "") -> tuple[list, Any]:
    """Cabeçalho padrão dos documentos gerenciais (nome da empresa + título)."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph

    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=14,
                                   textColor=colors.HexColor("#1F4E79"))
    estilo_normal = ParagraphStyle("n", parent=estilos["Normal"], fontSize=9, leading=12)
    historia = [
        Paragraph(str(empresa.get("nome") or "MR Logística"), estilo_titulo),
        Paragraph(titulo, estilo_normal),
    ]
    if subtitulo:
        historia.append(Paragraph(subtitulo, estilo_normal))
    return historia, estilo_normal


def gerar_comprovante_recebimento_pdf(banco: Banco, conta_id: int, destino=None) -> str:
    """Comprovante (não fiscal) de recebimento de um título do fiado.

    Lista o título, todos os recebimentos já feitos e o saldo remanescente.
    """
    from . import configuracoes as config_mod
    from . import contas_receber as cr_mod

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    except ImportError as exc:  # pragma: no cover
        raise ErroImpressao("Biblioteca reportlab não instalada.") from exc

    try:
        dados = cr_mod.titulo_para_impressao(banco, conta_id)
    except cr_mod.ErroContaReceber as exc:
        raise ErroImpressao(str(exc)) from exc
    empresa = config_mod.empresa(banco)

    destino = Path(destino) if destino else pasta_temporaria() / f"recebimento-{conta_id}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)

    historia, normal = _cabecalho_documento(
        empresa, f"Comprovante de recebimento nº {dados['numero']:06d}",
        f"Emitido em {formatar_data(hoje(), True)}",
    )
    historia += [Spacer(1, 8)]

    resumo = [
        ["Cliente", str(dados["cliente"] or "—")],
        ["Descrição do título", str(dados["descricao"] or "—")],
        ["Vencimento", formatar_data(dados["vencimento"])],
        ["Situação", str(dados["status"]).capitalize()],
        ["Valor do título", formatar_dinheiro(dados["valor"])],
        ["Total recebido", formatar_dinheiro(dados["pago"])],
        ["Desconto concedido", formatar_dinheiro(dados["desconto"])],
        ["Saldo devedor", formatar_dinheiro(dados["saldo"])],
    ]
    tabela = Table(resumo, colWidths=[55 * mm, 95 * mm], hAlign="LEFT")
    tabela.setStyle(_estilo_tabela_simples())
    historia.append(tabela)

    if dados["recebimentos"]:
        historia += [Spacer(1, 10), Paragraph("<b>Histórico de recebimentos</b>", normal), Spacer(1, 4)]
        linhas = [["Data / hora", "Forma", "Valor", "Recebido por"]]
        for recebimento in dados["recebimentos"]:
            linhas.append([
                formatar_data(recebimento["data"], True),
                str(recebimento["forma"] or "—"),
                formatar_dinheiro(recebimento["valor"]),
                str(recebimento["usuario"] or "—"),
            ])
        tabela = Table(linhas, colWidths=[42 * mm, 34 * mm, 32 * mm, 42 * mm], hAlign="LEFT", repeatRows=1)
        tabela.setStyle(_estilo_tabela_simples())
        historia.append(tabela)
    else:
        historia += [Spacer(1, 8), Paragraph("Nenhum recebimento registrado para este título.", normal)]

    endereco = empresa.get("endereco") or ""
    contato = " • ".join(p for p in (empresa.get("telefone") or "", empresa.get("email") or "") if p)
    historia += [Spacer(1, 14)]
    if endereco:
        historia.append(Paragraph(str(endereco), normal))
    if contato:
        historia.append(Paragraph(contato, normal))
    historia.append(Paragraph(
        "Documento gerencial (não fiscal) emitido pelo MR Logística. "
        "Não é comprovante fiscal e não substitui a nota fiscal.", normal))

    try:
        doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=12 * mm, bottomMargin=14 * mm,
                                title=f"Recebimento {dados['numero']:06d}")
        doc.build(historia)
    except Exception as exc:
        raise ErroImpressao(f"Falha ao gerar o comprovante: {exc}") from exc
    return str(destino)


def gerar_comprovante_pagamento_pdf(banco: Banco, conta_id: int, destino=None) -> str:
    """Comprovante (não fiscal) de pagamento de uma conta a pagar."""
    from . import configuracoes as config_mod
    from . import contas_pagar as cp_mod

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    except ImportError as exc:  # pragma: no cover
        raise ErroImpressao("Biblioteca reportlab não instalada.") from exc

    conta = cp_mod.pegar(banco, conta_id)
    if not conta:
        raise ErroImpressao("Conta não encontrada.")
    pagamentos = cp_mod.pagamentos(banco, conta_id)
    empresa = config_mod.empresa(banco)

    destino = Path(destino) if destino else pasta_temporaria() / f"pagamento-{conta_id}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)

    historia, normal = _cabecalho_documento(
        empresa, f"Comprovante de pagamento nº {int(conta_id):06d}",
        f"Emitido em {formatar_data(hoje(), True)}",
    )
    historia += [Spacer(1, 8)]

    resumo = [
        ["Fornecedor", str(conta["fornecedor_nome"] or "—")],
        ["Descrição", str(conta["descricao"] or "—")],
        ["Categoria", str(conta["categoria"] or "Outros")],
        ["Vencimento", formatar_data(conta["vencimento"])],
        ["Situação", str(conta["status"]).capitalize()],
        ["Valor da conta", formatar_dinheiro(int(conta["valor"] or 0))],
        ["Total pago", formatar_dinheiro(int(conta["valor_pago"] or 0))],
        ["Saldo", formatar_dinheiro(int(conta["saldo"] or 0))],
    ]
    tabela = Table(resumo, colWidths=[55 * mm, 95 * mm], hAlign="LEFT")
    tabela.setStyle(_estilo_tabela_simples())
    historia.append(tabela)

    if pagamentos:
        historia += [Spacer(1, 10), Paragraph("<b>Histórico de pagamentos</b>", normal), Spacer(1, 4)]
        linhas = [["Data / hora", "Forma", "Valor", "Pago por"]]
        for pagamento in pagamentos:
            linhas.append([
                formatar_data(pagamento["criado_em"], True),
                str(pagamento["forma"] or "—"),
                formatar_dinheiro(int(pagamento["valor"] or 0)),
                str(pagamento["usuario_nome"] or "—"),
            ])
        tabela = Table(linhas, colWidths=[42 * mm, 34 * mm, 32 * mm, 42 * mm], hAlign="LEFT", repeatRows=1)
        tabela.setStyle(_estilo_tabela_simples())
        historia.append(tabela)
    else:
        historia += [Spacer(1, 8), Paragraph("Nenhum pagamento registrado para esta conta.", normal)]

    if conta["observacao"]:
        historia += [Spacer(1, 10), Paragraph(f"<b>Observação:</b> {conta['observacao']}", normal)]
    historia += [Spacer(1, 14), Paragraph(
        "Documento gerencial (não fiscal) emitido pelo MR Logística.", normal)]

    try:
        doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=12 * mm, bottomMargin=14 * mm,
                                title=f"Pagamento {int(conta_id):06d}")
        doc.build(historia)
    except Exception as exc:
        raise ErroImpressao(f"Falha ao gerar o comprovante: {exc}") from exc
    return str(destino)
