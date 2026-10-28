"""
Etiquetas com código de barras.

Atende ao pedido "gerar e imprimir etiquetas com código de barras para produtos
que não tenham":

* :func:`gerar_codigo_para_produto` cria um **EAN-13 interno** (faixa 200–299,
  reservada para uso do próprio estabelecimento) e grava no produto;
* :func:`salvar_png` gera a imagem de **uma** etiqueta;
* :func:`gerar_pdf` monta uma **folha A4** com várias etiquetas (padrão
  Pimaco/14 por folha, mas com medidas configuráveis);
* :func:`imprimir` envia a folha para a impressora padrão.

Também é possível imprimir etiquetas de produtos que **já têm** código de barras
(com preço, marca, validade etc.).
"""

from __future__ import annotations

from pathlib import Path

from . import codigobarras, impressao, produtos
from .banco import Banco
from .caminhos import pasta_temporaria
from .utils import formatar_dinheiro, formatar_quantidade, hoje, limitar


class ErroEtiqueta(Exception):
    """Falha na geração de etiquetas."""


#: Modelos de folha prontos (colunas, linhas, largura e altura da etiqueta em mm).
MODELOS = {
    "14 por folha (Pimaco 6180)": {"colunas": 2, "linhas": 7, "largura_mm": 50.8, "altura_mm": 33.9},
    "10 por folha (6182)": {"colunas": 2, "linhas": 5, "largura_mm": 50.8, "altura_mm": 47.6},
    "24 por folha (6183)": {"colunas": 3, "linhas": 8, "largura_mm": 63.5, "altura_mm": 33.9},
    "40 por folha (6080)": {"colunas": 2, "linhas": 20, "largura_mm": 45.7, "altura_mm": 12.7},
    "Rolo térmico 40x30 mm": {"colunas": 1, "linhas": 1, "largura_mm": 40.0, "altura_mm": 30.0},
    "Rolo térmico 60x40 mm": {"colunas": 1, "linhas": 1, "largura_mm": 60.0, "altura_mm": 40.0},
}

MODELO_PADRAO = "14 por folha (Pimaco 6180)"


def modelos() -> list[str]:
    return list(MODELOS.keys())


def aplicar_modelo(nome: str) -> dict:
    if nome not in MODELOS:
        raise ErroEtiqueta(f"Modelo de etiqueta desconhecido: '{nome}'.")
    return dict(MODELOS[nome])


# --------------------------------------------------------------------------------------
# Código de barras do produto
# --------------------------------------------------------------------------------------


def gerar_codigo_para_produto(banco: Banco, produto_id: int, prefixo: str = "200", autor=None) -> str:
    """Gera e grava um EAN-13 interno para um produto sem código de barras."""
    produto = produtos.pegar(banco, produto_id)
    if not produto:
        raise ErroEtiqueta("Produto não encontrado.")
    codigo = produtos.gerar_codigo_barras(banco, produto_id, prefixo=prefixo)
    return produtos.definir_codigo_barras(banco, produto_id, codigo, autor=autor)


def produtos_sem_codigo(banco: Banco) -> list:
    """Produtos ativos sem código de barras (alvo do botão "Gerar etiquetas")."""
    return produtos.listar(banco, apenas_sem_barras=True)


# --------------------------------------------------------------------------------------
# Imagem de uma etiqueta
# --------------------------------------------------------------------------------------


def imagem_etiqueta(
    produto,
    largura_px: int = 380,
    altura_px: int = 250,
    mostrar_preco: bool = True,
    mostrar_codigo_interno: bool = True,
    mostrar_marca: bool = False,
    mostrar_validade: bool = False,
    texto_extra: str = "",
):
    """Gera a imagem **PIL** de uma etiqueta (usada no PNG e no PDF)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover
        raise ErroEtiqueta("Biblioteca Pillow não instalada. Reinstale o aplicativo.") from exc

    codigo = str(produto["codigo_barras"] or produto["codigo"] or "")
    if not codigo:
        raise ErroEtiqueta(f"O produto '{produto['nome']}' não tem código de barras nem código interno.")

    img = Image.new("RGB", (largura_px, altura_px), "white")
    desenho = ImageDraw.Draw(img)

    def fonte(tamanho: int):
        for nome in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttf", "LiberationSans-Regular.ttf"):
            try:
                return ImageFont.truetype(nome, tamanho)
            except OSError:
                continue
        return ImageFont.load_default()

    def fonte_negrito(tamanho: int):
        for nome in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
            try:
                return ImageFont.truetype(nome, tamanho)
            except OSError:
                continue
        return fonte(tamanho)

    margem = max(6, int(largura_px * 0.03))
    y = margem

    # Nome do produto
    nome_fonte = fonte_negrito(max(10, int(altura_px * 0.085)))
    nome = str(produto["nome"] or "").upper()
    for linha_texto in _quebrar_texto(desenho, nome, nome_fonte, largura_px - 2 * margem, max_linhas=2):
        desenho.text((margem, y), linha_texto, font=nome_fonte, fill="black")
        y += _altura_linha(desenho, linha_texto, nome_fonte)

    # Preço / informações
    if mostrar_preco or mostrar_codigo_interno or mostrar_marca or mostrar_validade or texto_extra:
        info_fonte = fonte(max(9, int(altura_px * 0.07)))
        partes = []
        if mostrar_preco:
            partes.append(formatar_dinheiro(int(produto["preco_venda"] or 0)))
            unidade = produto["unidade_venda"] or produto["unidade_base"] or "un"
            if unidade and unidade != "un":
                partes[-1] += f"/{unidade}"
        if mostrar_codigo_interno:
            partes.append(f"Cód. {produto['codigo']}")
        if mostrar_marca and produto["marca"]:
            partes.append(str(produto["marca"]))
        if mostrar_validade and produto["validade"]:
            partes.append(f"Val. {produto['validade']}")
        if texto_extra:
            partes.append(texto_extra)
        texto = "  •  ".join(p for p in partes if p)
        for linha_texto in _quebrar_texto(desenho, texto, info_fonte, largura_px - 2 * margem, max_linhas=1):
            desenho.text((margem, y), linha_texto, font=info_fonte, fill="black")
            y += _altura_linha(desenho, linha_texto, info_fonte)

    # Código de barras ocupa o restante da etiqueta
    altura_disponivel = max(30, altura_px - y - margem)
    try:
        modulos = codigobarras.para_modulos(codigo)
    except codigobarras.ErroCodigoBarras as exc:
        raise ErroEtiqueta(str(exc)) from exc
    largura_barra = max(1, (largura_px - 2 * margem) // len(modulos))
    altura_barras = max(20, altura_disponivel - int(altura_disponivel * 0.24))
    x = margem + ((largura_px - 2 * margem) - largura_barra * len(modulos)) // 2
    for i, modulo in enumerate(modulos):
        if modulo == "1":
            desenho.rectangle([x + i * largura_barra, y, x + (i + 1) * largura_barra - 1, y + altura_barras - 1], fill="black")
    texto_fonte = fonte(max(9, int(altura_px * 0.075)))
    texto_codigo = codigo
    largura_texto = _largura_texto(desenho, texto_codigo, texto_fonte)
    desenho.text(
        (max(margem, (largura_px - largura_texto) // 2), y + altura_barras + 1),
        texto_codigo, font=texto_fonte, fill="black",
    )
    return img


def _altura_linha(desenho, texto: str, fonte) -> int:
    try:
        caixa = desenho.textbbox((0, 0), texto, font=fonte)
        return int(caixa[3] - caixa[1]) + 3
    except AttributeError:  # Pillow antigo
        return int(fonte.size * 1.25)


def _largura_texto(desenho, texto: str, fonte) -> int:
    try:
        caixa = desenho.textbbox((0, 0), texto, font=fonte)
        return int(caixa[2] - caixa[0])
    except AttributeError:  # pragma: no cover
        return int(len(texto) * fonte.size * 0.6)


def _quebrar_texto(desenho, texto: str, fonte, largura_max: int, max_linhas: int = 2) -> list[str]:
    """Quebra o texto respeitando a largura disponível (medida real em pixels)."""
    palavras = str(texto or "").split()
    if not palavras:
        return [""]
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        candidato = f"{atual} {palavra}".strip()
        if _largura_texto(desenho, candidato, fonte) <= largura_max:
            atual = candidato
        else:
            if atual:
                linhas.append(atual)
                if len(linhas) >= max_linhas:
                    atual = ""
                    break
            atual = palavra
    if atual and len(linhas) < max_linhas:
        linhas.append(atual)
    if not linhas:
        linhas = [limitar(texto, 40)]
    return linhas


def salvar_png(banco: Banco, produto_id: int, destino=None, **kwargs) -> str:
    """Salva a etiqueta de um produto como PNG."""
    produto = produtos.pegar(banco, produto_id)
    if not produto:
        raise ErroEtiqueta("Produto não encontrado.")
    destino = Path(destino) if destino else pasta_temporaria() / f"etiqueta-{produto['codigo']}.png"
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagem_etiqueta(produto, **kwargs).save(str(destino))
    return str(destino)


# --------------------------------------------------------------------------------------
# Folha A4 com várias etiquetas
# --------------------------------------------------------------------------------------


def gerar_pdf(
    banco: Banco,
    produto_ids,
    destino=None,
    colunas: int = 2,
    linhas_por_pagina: int = 7,
    largura_mm: float = 50.8,
    altura_mm: float = 33.9,
    quantidades=None,
    mostrar_preco: bool = True,
    mostrar_codigo_interno: bool = True,
    mostrar_marca: bool = False,
    margem_mm: float = 6.0,
    espacamento_mm: float = 2.0,
) -> str:
    """Monta a folha de etiquetas em PDF (A4) e devolve o caminho do arquivo."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas as pdf_canvas
    except ImportError as exc:  # pragma: no cover
        raise ErroEtiqueta("Biblioteca reportlab não instalada.") from exc
    import io

    ids = [int(i) for i in produto_ids or [] if i]
    if not ids:
        raise ErroEtiqueta("Selecione ao menos um produto para gerar etiquetas.")
    quantidades = list(quantidades or [1] * len(ids))
    if len(quantidades) < len(ids):
        quantidades += [1] * (len(ids) - len(quantidades))

    destino = Path(destino) if destino else pasta_temporaria() / f"etiquetas-{hoje()}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Expande as quantidades: quantidade 3 gera 3 etiquetas iguais
    repetidos: list[int] = []
    for produto_id, quantidade in zip(ids, quantidades):
        repetidos.extend([produto_id] * max(1, int(quantidade or 1)))

    largura_pagina, altura_pagina = A4
    mm = 72.0 / 25.4
    etiqueta_largura = largura_mm * mm
    etiqueta_altura = altura_mm * mm
    margem = margem_mm * mm
    espaco = espacamento_mm * mm

    colunas = max(1, int(colunas))
    linhas = max(1, int(linhas_por_pagina))
    por_pagina = colunas * linhas
    if por_pagina > len(repetidos):
        # se cabem mais etiquetas do que o necessário, mantém o modelo escolhido
        pass

    c = pdf_canvas.Canvas(str(destino), pagesize=A4)
    c.setTitle("Etiquetas — MR Logística")
    c.setAuthor("MR Logística")

    posicao = 0
    memoria: dict[int, object] = {}
    for indice, produto_id in enumerate(repetidos):
        if indice % por_pagina == 0 and indice > 0:
            c.showPage()
        slot = indice % por_pagina
        coluna = slot % colunas
        linha = slot // colunas
        x = margem + coluna * (etiqueta_largura + espaco)
        y = altura_pagina - margem - (linha + 1) * etiqueta_altura - linha * espaco

        if produto_id not in memoria:
            produto = produtos.pegar(banco, produto_id)
            if not produto:
                raise ErroEtiqueta(f"Produto {produto_id} não encontrado.")
            if not produto["codigo_barras"] and not produto["codigo"]:
                raise ErroEtiqueta(f"O produto '{produto['nome']}' não tem código para imprimir.")
            pixels_largura = max(260, int(etiqueta_largura * 4))
            pixels_altura = max(150, int(etiqueta_altura * 4))
            memoria[produto_id] = ImageReader(
                io.BytesIO(_png_bytes(imagem_etiqueta(
                    produto, largura_px=pixels_largura, altura_px=pixels_altura,
                    mostrar_preco=mostrar_preco, mostrar_codigo_interno=mostrar_codigo_interno,
                    mostrar_marca=mostrar_marca,
                )))
            )
        c.drawImage(
            memoria[produto_id], x, y, width=etiqueta_largura, height=etiqueta_altura,
            preserveAspectRatio=False, mask="auto",
        )
        # linha de corte suave (some na impressão em papel adesivo)
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.25)
        c.rect(x, y, etiqueta_largura, etiqueta_altura)
        posicao += 1

    c.showPage()
    c.save()
    if posicao == 0:
        raise ErroEtiqueta("Nenhuma etiqueta foi gerada.")
    return str(destino)


def _png_bytes(imagem) -> bytes:
    import io

    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


def imprimir(banco: Banco, produto_ids, modelo: str = MODELO_PADRAO, quantidades=None, **kwargs) -> tuple[bool, str, str]:
    """Gera a folha de etiquetas e manda imprimir. Devolve ``(ok, mensagem, caminho)``."""
    configuracao = aplicar_modelo(modelo)
    caminho = gerar_pdf(
        banco,
        produto_ids,
        colunas=configuracao["colunas"],
        linhas_por_pagina=configuracao["linhas"],
        largura_mm=configuracao["largura_mm"],
        altura_mm=configuracao["altura_mm"],
        quantidades=quantidades,
        **kwargs,
    )
    ok, mensagem = impressao.imprimir_arquivo(caminho)
    return ok, mensagem, caminho


def etiquetas_para_produtos_selecionados(banco: Banco, filtros: dict) -> list[int]:
    """Converte os filtros da tela de produtos em lista de ids para etiquetar."""
    linhas = produtos.listar(
        banco,
        filtro=str(filtros.get("texto") or ""),
        categoria_id=filtros.get("categoria_id") or None,
        fornecedor_id=filtros.get("fornecedor_id") or None,
        apenas_sem_barras=bool(filtros.get("apenas_sem_barras")),
        incluir_inativos=bool(filtros.get("incluir_inativos")),
    )
    return [int(l["id"]) for l in linhas]
