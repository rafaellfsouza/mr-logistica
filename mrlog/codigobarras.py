"""
Códigos de barras: validação, geração e desenho.

Tudo é implementado aqui **sem bibliotecas externas** — só a biblioteca padrão e o
Pillow (que já é usado para as fotos dos produtos). Isso mantém o executável leve
e evita dependência de internet.

Suporta:

* **EAN-13** e **EAN-8** — padrões do varejo (cálculo do dígito verificador);
* **CODE128-B** — aceita letras, números e símbolos; é o formato usado para gerar
  códigos internos de produtos que ainda não têm código de barras.

O desenho é feito módulo a módulo (as barras pretas/brancas) e pode ser exportado
como imagem PNG (Pillow) ou como imagem nativa do Tkinter (``PhotoImage``) para
mostrar na tela e imprimir nas etiquetas.
"""

from __future__ import annotations

import io
import random
import time

from .utils import apenas_digitos

# --------------------------------------------------------------------------------------
# Tabelas de codificação
# --------------------------------------------------------------------------------------

#: Cada dígito de um EAN vira um padrão de 7 módulos (0 = branco, 1 = preto).
_EAN_L = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")
_EAN_G = ("0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111")
_EAN_R = ("1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100")
_EAN_PRIMEIRA = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")

_GUARDA = "101"
_CENTRO = "01010"

#: CODE128 — cada valor (0..106) vira 6 números: larguras de barra/espaco alternadas.
_CODE128_VALORES = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
)
_CODE128_INICIO_B = 104
_CODE128_FIM = 106


class ErroCodigoBarras(Exception):
    """Código inválido (tamanho errado, caracteres não suportados etc.)."""


# --------------------------------------------------------------------------------------
# EAN-13 / EAN-8
# --------------------------------------------------------------------------------------


def digito_verificador_ean(digitos: str) -> int:
    """Calcula o dígito verificador de um EAN-13/EAN-8 a partir dos dígitos anteriores.

    >>> digito_verificador_ean('789100031550')
    7
    """
    d = apenas_digitos(digitos)
    if not d:
        raise ErroCodigoBarras("Não há dígitos para calcular o verificador.")
    soma = 0
    # Peso 1/3 alternado, começando pela direita.
    for i, ch in enumerate(reversed(d)):
        soma += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - (soma % 10)) % 10


def ean_valido(codigo: str) -> bool:
    """Verifica tamanho e dígito verificador de um EAN-13 ou EAN-8."""
    d = apenas_digitos(codigo)
    if len(d) not in (8, 13):
        return False
    return digito_verificador_ean(d[:-1]) == int(d[-1])


def gerar_ean13(base: int | str = "", prefixo: str = "200") -> str:
    """Gera um EAN-13 válido para uso **interno** (etiqueta própria da loja).

    Se ``base`` for informado, usa seus dígitos como sequência; caso contrário cria
    uma sequência a partir do horário atual. O prefixo ``2xx`` é a faixa reservada
    para uso interno do estabelecimento.

    >>> len(gerar_ean13('123456789'))
    13
    """
    prefixo = apenas_digitos(prefixo) or "200"
    sequencia = apenas_digitos(base)
    if not sequencia:
        # Horário + sorteio: duas chamadas no mesmo segundo (ex.: geração de
        # códigos em lote para vários produtos) precisam receber candidatos
        # diferentes, senão a verificação de "código livre" reprova todos.
        sequencia = f"{int(time.time()) % 1_000_000}{random.randrange(0, 1000):03d}"
        sequencia = sequencia.zfill(9)[-9:]
    corpo = (prefixo + sequencia)[:12].ljust(12, "0")
    return corpo + str(digito_verificador_ean(corpo))


def completar_ean(codigo: str) -> str:
    """Se o código tiver 12 dígitos, calcula e acrescenta o verificador (vira EAN-13)."""
    d = apenas_digitos(codigo)
    if len(d) == 12:
        return d + str(digito_verificador_ean(d))
    if len(d) == 7:
        return d + str(digito_verificador_ean(d))
    return d


def ean_para_modulos(codigo: str) -> str:
    """Transforma um EAN-13/EAN-8 na sequência de módulos (``'1011...'``)."""
    d = apenas_digitos(codigo)
    if not ean_valido(d):
        raise ErroCodigoBarras(f"Código EAN inválido: '{codigo}'.")
    if len(d) == 13:
        padrao = _EAN_PRIMEIRA[int(d[0])]
        modulos = _GUARDA
        for i, ch in enumerate(d[1:7]):
            modulos += _EAN_L[int(ch)] if padrao[i] == "L" else _EAN_G[int(ch)]
        modulos += _CENTRO
        for ch in d[7:]:
            modulos += _EAN_R[int(ch)]
        return modulos + _GUARDA
    # EAN-8
    modulos = _GUARDA
    for ch in d[:4]:
        modulos += _EAN_L[int(ch)]
    modulos += _CENTRO
    for ch in d[4:]:
        modulos += _EAN_R[int(ch)]
    return modulos + _GUARDA


# --------------------------------------------------------------------------------------
# CODE128 (subconjunto B — caracteres ASCII 32..126)
# --------------------------------------------------------------------------------------


def code128_valido(texto: str) -> bool:
    """Confere se todos os caracteres podem ser codificados em CODE128-B."""
    return bool(texto) and all(32 <= ord(c) <= 126 for c in str(texto))


def gerar_codigo_interno(prefixo: str = "MR", sequencia: int | str = "") -> str:
    """Gera um código interno legível para produtos sem código de barras.

    >>> gerar_codigo_interno('MR', 7)
    'MR00000007'
    """
    if not sequencia:
        sequencia = int(time.time()) % 100_000_000
    return f"{prefixo}{int(sequencia):08d}"


def code128_para_modulos(texto: str) -> str:
    """Codifica um texto em CODE128-B e devolve a sequência de módulos."""
    texto = str(texto)
    if not texto:
        raise ErroCodigoBarras("Texto vazio não pode virar código de barras.")
    if not code128_valido(texto):
        raise ErroCodigoBarras(
            "O texto contém caracteres não suportados pelo CODE128 "
            "(use letras sem acento, números e símbolos comuns)."
        )
    valores = [_CODE128_INICIO_B] + [(ord(c) - 32) for c in texto]
    soma = valores[0]
    for i, v in enumerate(valores[1:], start=1):
        soma += i * v
    valores.append(soma % 103)
    valores.append(_CODE128_FIM)
    modulos = ""
    for v in valores:
        padrao = _CODE128_VALORES[v]
        for i, ch in enumerate(padrao):
            modulos += (ch * ("1" if i % 2 == 0 else "0"))
    return modulos


def para_modulos(codigo: str, formato: str = "auto") -> str:
    """Devolve os módulos de um código, escolhendo EAN ou CODE128 automaticamente."""
    codigo = str(codigo or "").strip()
    if not codigo:
        raise ErroCodigoBarras("Código vazio.")
    f = (formato or "auto").lower()
    if f in ("auto", "ean"):
        d = apenas_digitos(codigo)
        if len(d) in (8, 13) and d == codigo:
            if ean_valido(d):
                return ean_para_modulos(d)
            if f == "ean":
                raise ErroCodigoBarras(f"Dígito verificador inválido para '{codigo}'.")
        elif f == "ean":
            raise ErroCodigoBarras(f"'{codigo}' não é um EAN-8/EAN-13 válido.")
    if f == "ean":
        raise ErroCodigoBarras(f"'{codigo}' não é um EAN válido.")
    return code128_para_modulos(codigo)


def detectar_formato(codigo: str) -> str:
    """Informa se o código é ``EAN-13``, ``EAN-8``, ``CODE128`` ou ``INVÁLIDO``."""
    d = apenas_digitos(codigo)
    if d == str(codigo).strip() and len(d) == 13 and ean_valido(d):
        return "EAN-13"
    if d == str(codigo).strip() and len(d) == 8 and ean_valido(d):
        return "EAN-8"
    if code128_valido(codigo):
        return "CODE128"
    return "INVÁLIDO"


# --------------------------------------------------------------------------------------
# Desenho (imagem)
# --------------------------------------------------------------------------------------


def _desenhar(modulos: str, largura_modulo: int, altura: int, margem: int, mostrar_texto: bool, texto: str):
    """Cria a imagem PNG do código de barras e devolve os bytes."""
    from PIL import Image, ImageDraw, ImageFont

    n = len(modules)
    largura = n * largura_modulo + 2 * margem
    altura_texto = int(altura * 0.22) if mostrar_texto else 0
    altura_total = altura + altura_texto + 2 * margem
    img = Image.new("RGB", (max(1, largura), max(1, altura_total)), "white")
    d = ImageDraw.Draw(img)
    x = margem
    preto = (0, 0, 0)
    i = 0
    while i < n:
        if modulos[i] == "1":
            j = i
            while j < n and modulos[j] == "1":
                j += 1
            d.rectangle([x, margem, x + (j - i) * largura_modulo - 1, margem + altura - 1], fill=preto)
            i = j
            x = margem + i * largura_modulo
        else:
            i += 1
            x = margem + i * largura_modulo
    if mostrar_texto and texto:
        fonte = None
        for nome in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttf"):
            try:
                fonte = ImageFont.truetype(nome, max(10, int(altura_texto * 0.8)))
                break
            except OSError:
                continue
        if fonte is None:
            fonte = ImageFont.load_default()
        try:
            caixa = d.textbbox((0, 0), texto, font=fonte)
            largura_texto = caixa[2] - caixa[0]
        except AttributeError:  # Pillow antigo
            largura_texto = d.textsize(texto, font=fonte)[0]
        d.text(((largura - largura_texto) // 2, margem + altura + 2), texto, fill=preto, font=fonte)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def imagem_png(
    codigo: str,
    formato: str = "auto",
    largura_modulo: int = 2,
    altura: int = 70,
    margem: int = 12,
    mostrar_texto: bool = True,
) -> bytes:
    """Gera o PNG do código de barras (bytes) — usado nas etiquetas e na impressão."""
    modulos = para_modulos(codigo, formato)
    texto = apenas_digitos(codigo) if apenas_digitos(codigo) == str(codigo).strip() else str(codigo)
    return _desenhar(modulos, largura_modulo, altura, margem, mostrar_texto, texto if mostrar_texto else "")


def salvar_png(caminho, codigo: str, **kwargs) -> str:
    """Salva o código de barras num arquivo PNG e devolve o caminho."""
    dados = imagem_png(codigo, **kwargs)
    with open(caminho, "wb") as arq:
        arq.write(dados)
    return str(caminho)


def photo_image(codigo: str, widget=None, **kwargs):
    """Devolve um ``tkinter.PhotoImage`` com o código de barras para exibir na tela.

    Importante: guarde a referência retornada (ex.: ``self._img = ...``), senão o
    Python libera a imagem e ela some da tela.
    """
    import base64
    import tkinter as tk

    dados = imagem_png(codigo, **kwargs)
    b64 = base64.b64encode(dados).decode("ascii")
    return tk.PhotoImage(data=b64, master=widget)


def normalizar_codigo_digitado(codigo: str) -> str:
    """Trata o que vem do bipador/digitação: remove espaços, quebras de linha e TAB."""
    return str(codigo or "").replace("\r", "").replace("\n", "").replace("\t", "").strip()


def tamanho_imagem(codigo: str, largura_modulo: int = 2, altura: int = 70, margem: int = 12, mostrar_texto: bool = True) -> tuple[int, int]:
    """Dimensões (largura, altura) que a imagem do código terá — útil para layout."""
    modulos = para_modulos(codigo)
    largura = len(modulos) * largura_modulo + 2 * margem
    altura_texto = int(altura * 0.22) if mostrar_texto else 0
    return largura, altura + altura_texto + 2 * margem
