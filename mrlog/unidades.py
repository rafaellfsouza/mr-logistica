"""
Unidades de medida e conversão automática.

O sistema trabalha com **quatro famílias**:

===========  ==================================================================  =====================
Família      Unidades                                                            Unidade padrão (base)
===========  ==================================================================  =====================
quantidade   unidade, caixa, pacote, dúzia, par, fardo, kit, peça, rolo, folha   unidade (``un``)
massa        miligrama, grama, quilograma, tonelada                              grama (``g``)
volume       mililitro, litro, metro cúbico                                      mililitro (``ml``)
comprimento  milímetro, centímetro, metro, quilômetro                            milímetro (``mm``)
===========  ==================================================================  =====================

**Conversão automática dentro da mesma família.** Para massa, volume e comprimento
a conversão é universal (1 kg = 1000 g, 1 m = 100 cm...). Para *quantidade* a
conversão depende de dois fatores:

* unidades com fator fixo universal — dúzia (12) e par (2);
* unidades definidas pelo cadastro do produto — caixa, pacote, fardo e kit usam o
  campo ``fator_venda`` do produto (ex.: 1 caixa = 24 unidades).

**Venda fracionada:** um produto controlado em quilograma pode ser vendido como
``0,250 kg`` (250 gramas). O estoque é sempre movimentado na *unidade base*, depois
da conversão — por isso ``250 g`` e ``0,25 kg`` baixam exatamente o mesmo saldo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .banco import Banco

FAMILIA_QUANTIDADE = "quantidade"
FAMILIA_MASSA = "massa"
FAMILIA_VOLUME = "volume"
FAMILIA_COMPRIMENTO = "comprimento"

FAMILIAS = (FAMILIA_QUANTIDADE, FAMILIA_MASSA, FAMILIA_VOLUME, FAMILIA_COMPRIMENTO)

NOMES_FAMILIAS = {
    FAMILIA_QUANTIDADE: "Quantidade",
    FAMILIA_MASSA: "Peso / massa",
    FAMILIA_VOLUME: "Volume",
    FAMILIA_COMPRIMENTO: "Comprimento",
}

#: Unidades cujo fator é universal, independente do cadastro do produto.
FATORES_UNIVERSAIS = {"dz": 12.0, "par": 2.0}

#: Unidades que dependem do fator informado no produto.
FATORES_POR_PRODUTO = {"cx", "pct", "fd", "kit"}

CASAS_QUANTIDADE = 6  # precisão interna das quantidades convertidas


class ErroUnidade(Exception):
    """Conversão impossível (famílias diferentes, unidade inexistente etc.)."""


@dataclass(frozen=True)
class Unidade:
    sigla: str
    nome: str
    familia: str
    fator_base: float
    ordem: int = 0

    @property
    def rotulo(self) -> str:
        """Texto exibido nos combos: ``kg — Quilograma``."""
        return f"{self.sigla} — {self.nome}"

    @classmethod
    def de_linha(cls, linha) -> "Unidade":
        return cls(
            sigla=str(linha["sigla"]),
            nome=str(linha["nome"]),
            familia=str(linha["familia"]),
            fator_base=float(linha["fator_base"] or 1.0),
            ordem=int(linha["ordem"] or 0),
        )


# --------------------------------------------------------------------------------------
# Leitura do cadastro de unidades
# --------------------------------------------------------------------------------------

_CACHE: dict[str, Unidade] = {}


def recarregar(banco: Banco) -> dict[str, Unidade]:
    """(Re)carrega o dicionário de sigla -> Unidade a partir do banco."""
    global _CACHE
    _CACHE = {
        str(l["sigla"]).lower(): Unidade.de_linha(l)
        for l in banco.consultar("SELECT * FROM unidades ORDER BY ordem, sigla")
    }
    return _CACHE


def todas(banco: Banco | None = None) -> list[Unidade]:
    """Lista todas as unidades cadastradas, ordenadas por família."""
    cache = _CACHE if _CACHE else (recarregar(banco) if banco else {})
    return sorted(cache.values(), key=lambda u: (u.familia, u.ordem, u.sigla))


def por_familia(familia: str, banco: Banco | None = None) -> list[Unidade]:
    return [u for u in todas(banco) if u.familia == familia]


def pegar(sigla, banco: Banco | None = None) -> Unidade:
    """Busca uma unidade pela sigla (sem distinguir maiúsculas)."""
    if not sigla:
        raise ErroUnidade("Unidade não informada.")
    s = str(sigla).strip().lower()
    cache = _CACHE if _CACHE else (recarregar(banco) if banco else {})
    if s not in cache:
        raise ErroUnidade(f"Unidade de medida desconhecida: '{sigla}'.")
    return cache[s]


def existe(sigla, banco: Banco | None = None) -> bool:
    try:
        pegar(sigla, banco)
        return True
    except ErroUnidade:
        return False


def familia_de(sigla, banco: Banco | None = None) -> str:
    return pegar(sigla, banco).familia


def mesma_familia(sigla_a, sigla_b, banco: Banco | None = None) -> bool:
    try:
        return familia_de(sigla_a, banco) == familia_de(sigla_b, banco)
    except ErroUnidade:
        return False


# --------------------------------------------------------------------------------------
# Fator de conversão
# --------------------------------------------------------------------------------------


def fator_para_base(
    unidade: str,
    unidade_base: str,
    fator_venda: float = 1.0,
    unidade_venda: str | None = None,
    banco: Banco | None = None,
) -> float:
    """Quantas **unidades base** valem ``1`` unidade informada.

    Regras (nesta ordem):

    1. mesma sigla                      -> 1
    2. mesma família massa/volume/compr.-> razão entre os fatores da família
    3. quantidade com fator universal   -> dúzia = 12, par = 2
    4. é a unidade de venda do produto  -> ``fator_venda`` do cadastro
    5. caixa/pacote/fardo/kit           -> ``fator_venda`` do cadastro (senão erro)
    6. famílias diferentes              -> erro
    """
    uni = pegar(unidade, banco)
    base = pegar(unidade_base, banco)
    if uni.sigla == base.sigla:
        return 1.0

    if uni.familia != base.familia:
        raise ErroUnidade(
            f"Não é possível converter '{uni.sigla}' ({NOMES_FAMILIAS.get(uni.familia, uni.familia)}) "
            f"para '{base.sigla}' ({NOMES_FAMILIAS.get(base.familia, base.familia)}): famílias diferentes."
        )

    if uni.familia != FAMILIA_QUANTIDADE:
        # Massa, volume e comprimento: conversão universal pela unidade padrão da família.
        return float(uni.fator_base) / float(base.fator_base or 1.0)

    # Família quantidade
    if uni.sigla in FATORES_UNIVERSAIS:
        if base.sigla in FATORES_UNIVERSAIS:
            return uni.fator_base / base.fator_base
        return uni.fator_base

    if unidade_venda and str(unidade_venda).strip().lower() == uni.sigla:
        if fator_venda and float(fator_venda) > 0:
            return float(fator_venda)
        return 1.0

    if uni.sigla in FATORES_POR_PRODUTO:
        if fator_venda and float(fator_venda) > 0:
            return float(fator_venda)
        raise ErroUnidade(
            f"A unidade '{uni.sigla}' só pode ser usada se o produto informar quantas "
            f"'{base.sigla}' existem em 1 '{uni.sigla}' (campo Fator da unidade de venda)."
        )

    return 1.0


def fator_para_base_produto(produto, unidade: str, banco: Banco | None = None) -> float:
    """Atalho de :func:`fator_para_base` recebendo a linha/dict do produto."""
    return fator_para_base(
        unidade=unidade,
        unidade_base=produto["unidade_base"] or "un",
        fator_venda=float(produto["fator_venda"] or 1.0),
        unidade_venda=produto["unidade_venda"],
        banco=banco,
    )


def unidades_permitidas(produto, banco: Banco | None = None) -> list[Unidade]:
    """Unidades que podem ser usadas para vender/movimentar este produto.

    Inclui a unidade de venda (mesmo que seja de outra família — ex.: vender
    "unidade" de um produto estocado em "kg"), a unidade base, todas as unidades
    da mesma família da base e dúzia/par quando a base é "un".
    """
    cache = _CACHE if _CACHE else (recarregar(banco) if banco else {})
    base = str(produto["unidade_base"] or "un").lower()
    venda = str(produto["unidade_venda"] or base).lower()
    permitidas: dict[str, Unidade] = {}

    for u in por_familia(familia_de(base, banco), banco):
        permitidas[u.sigla] = u
    if base in cache:
        permitidas[base] = cache[base]
    if venda in cache:
        permitidas[venda] = cache[venda]
    if base == "un":
        for extra in ("dz", "par"):
            if extra in cache:
                permitidas[extra] = cache[extra]

    familia_base = familia_de(base, banco)
    return sorted(
        permitidas.values(),
        key=lambda u: (u.familia != familia_base, u.familia, u.ordem, u.sigla),
    )


def siglas_permitidas(produto, banco: Banco | None = None) -> list[str]:
    return [u.sigla for u in unidades_permitidas(produto, banco)]


def converter(
    quantidade: float,
    unidade_origem: str,
    unidade_destino: str,
    fator_venda: float = 1.0,
    unidade_venda: str | None = None,
    banco: Banco | None = None,
) -> float:
    """Converte ``quantidade`` de uma unidade para outra **dentro da mesma família**.

    A conversão passa sempre pela unidade padrão da família (g, ml, mm ou un),
    o que garante coerência: ``250 g`` -> ``0,25 kg`` -> ``250000 mg``.

    >>> converter(1, 'kg', 'g')
    1000.0
    >>> converter(250, 'g', 'kg')
    0.25
    >>> converter(1, 'm', 'cm')
    100.0
    """
    if unidade_origem == unidade_destino:
        return arredondar(quantidade)
    base_familia = unidade_padrao(familia_de(unidade_origem, banco), banco)
    fator_origem = fator_para_base(unidade_origem, base_familia, fator_venda, unidade_venda, banco)
    fator_destino = fator_para_base(unidade_destino, base_familia, fator_venda, unidade_venda, banco)
    if not fator_destino:
        raise ErroUnidade("Fator de conversão inválido.")
    return arredondar(float(quantidade) * fator_origem / fator_destino)


def unidade_padrao(familia: str, banco: Banco | None = None) -> str:
    """Unidade padrão (base) de cada família: g, ml, mm e un."""
    return {
        FAMILIA_MASSA: "g",
        FAMILIA_VOLUME: "ml",
        FAMILIA_COMPRIMENTO: "mm",
        FAMILIA_QUANTIDADE: "un",
    }.get(familia, "un")


def converter_para_base(produto, quantidade: float, unidade: str, banco: Banco | None = None) -> float:
    """Converte a quantidade digitada na venda para a **unidade de estoque** do produto."""
    f = fator_para_base_produto(produto, unidade, banco)
    return arredondar(float(quantidade) * f)


def converter_da_base(produto, quantidade_base: float, unidade: str, banco: Banco | None = None) -> float:
    """Converte um saldo em unidade base para outra unidade (usado em telas e etiquetas)."""
    f = fator_para_base_produto(produto, unidade, banco)
    if not f:
        return 0.0
    return arredondar(float(quantidade_base) / f)


def arredondar(valor: float, casas: int = CASAS_QUANTIDADE) -> float:
    """Arredonda eliminando o ruído de ponto flutuante (``24 * 0.1`` -> ``2.4``)."""
    v = round(float(valor), casas)
    if abs(v - round(v)) < 1e-9:
        return float(round(v))
    return v


def validar_quantidade(produto, quantidade: float, unidade: str) -> None:
    """Garante que a quantidade é positiva e respeita a permissão de fracionamento."""
    try:
        q = float(quantidade)
    except (TypeError, ValueError):
        raise ErroUnidade("Quantidade inválida.") from None
    if math.isnan(q) or math.isinf(q):
        raise ErroUnidade("Quantidade inválida.")
    if q <= 0:
        raise ErroUnidade("A quantidade deve ser maior que zero.")
    if q > 1_000_000:
        raise ErroUnidade("Quantidade muito alta (máximo 1.000.000).")
    if not int(produto["permite_fracionar"] or 0) and abs(q - math.floor(q)) > 1e-9:
        raise ErroUnidade(
            f"O produto '{produto['nome']}' não permite quantidade fracionada "
            f"(use números inteiros ou libere o fracionamento no cadastro)."
        )


def formatar(quantidade: float, unidade: str, casas: int | None = None) -> str:
    """``250`` + ``g`` -> ``250 g`` | ``0.25`` + ``kg`` -> ``0,25 kg``."""
    from .utils import formatar_quantidade

    q = float(quantidade or 0)
    if casas is not None:
        q = round(q, casas)
    return f"{formatar_quantidade(q)} {unidade}".strip()


def resumo_conversao(produto, unidade: str, banco: Banco | None = None) -> str:
    """Frase explicativa usada na tela: ``1 cx = 24 un``."""
    try:
        f = fator_para_base_produto(produto, unidade, banco)
    except ErroUnidade:
        return ""
    base = produto["unidade_base"] or "un"
    if unidade == base:
        return ""
    from .utils import formatar_quantidade

    return f"1 {unidade} = {formatar_quantidade(f)} {base}"
