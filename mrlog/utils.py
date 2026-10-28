"""
Funções utilitárias usadas por todo o sistema: dinheiro, datas, textos e arredondamento.

**Regra de ouro do dinheiro:** todos os valores monetários são armazenados e
calculados em **centavos (número inteiro)**. Isso elimina os erros de vírgula
flutuante (o clássico ``0.1 + 0.2 != 0.3``) que fazem o caixa "perder" centavos.
A conversão para reais acontece somente na hora de mostrar na tela ou exportar.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# --------------------------------------------------------------------------------------
# Dinheiro (centavos <-> reais)
# --------------------------------------------------------------------------------------


def para_centavos(valor) -> int:
    """Converte um valor em **centavos inteiros**.

    Aceita texto no padrão brasileiro (``'1.234,56'``, ``'12,34'``), número em reais
    (``12.34``), ``Decimal`` e ``int``.

    .. warning::
       ``int`` é interpretado **diretamente como centavos** (não como reais), porque
       todo o núcleo do sistema trafega dinheiro em centavos. Para converter um número
       inteiro de reais use ``para_centavos(str(valor))`` ou multiplique por 100.

    >>> para_centavos('12,34')
    1234
    >>> para_centavos('1.234,56')
    123456
    >>> para_centavos(0.1)
    10
    >>> para_centavos(1234)
    1234
    >>> para_centavos(None)
    0
    """
    if valor is None or valor == "":
        return 0
    if isinstance(valor, int) and not isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, str):
        v = valor.strip().replace("R$", "").replace(" ", "")
        v = v.replace(".", "").replace(",", ".") if ("," in v and v.count(".") >= 1) else v.replace(",", ".")
        if v in ("", "-", "."):
            return 0
        valor = v
    return int((Decimal(str(valor)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def para_reais(centavos) -> float:
    """Converte centavos inteiros em reais (float, apenas para exibição/exportação)."""
    if centavos is None:
        return 0.0
    return round(int(centavos) / 100.0, 2)


def formatar_dinheiro(centavos, simbolo: bool = True) -> str:
    """Formata centavos no padrão brasileiro: ``123456`` -> ``R$ 1.234,56``."""
    valor = para_reais(centavos or 0)
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}" if simbolo else texto


def formatar_quantidade(qtd) -> str:
    """Formata quantidade sem zeros à direita desnecessários: ``2.0`` -> ``2`` | ``0.25`` -> ``0,25``."""
    try:
        v = float(qtd or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v))}"
    texto = f"{v:.4f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def arredondar_qtd(valor, casas: int = 4) -> float:
    """Arredonda quantidade para o número de casas decimais usado no estoque."""
    return float(Decimal(str(valor)).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP))


def total_linha_centavos(qtd, preco_unit_centavos) -> int:
    """Total de uma linha em centavos, com arredondamento comercial (meio para cima)."""
    d = Decimal(str(qtd)) * Decimal(int(preco_unit_centavos))
    return int(d.to_integral_value(rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------------------
# Datas
# --------------------------------------------------------------------------------------

FORMATO_DATA = "%Y-%m-%d"
FORMATO_DATA_HORA = "%Y-%m-%d %H:%M:%S"


def agora() -> str:
    """Data e hora atuais no formato gravado no banco (``YYYY-MM-DD HH:MM:SS``)."""
    return datetime.now().strftime(FORMATO_DATA_HORA)


def hoje() -> str:
    """Data de hoje no formato gravado no banco (``YYYY-MM-DD``)."""
    return date.today().strftime(FORMATO_DATA)


def agora_iso() -> str:
    """Data/hora com segundos fracionários — usada para ordenação precisa de eventos."""
    return datetime.now().isoformat(sep=" ", timespec="milliseconds")


def formatar_data(data_bruta, com_hora: bool = False) -> str:
    """Converte ``2026-10-28`` (ou com hora) para ``28/10/2026`` (ou ``28/10/2026 14:05``).

    >>> formatar_data('2026-10-28')
    '28/10/2026'
    >>> formatar_data('2026-10-28 14:05:30', True)
    '28/10/2026 14:05:30'
    """
    if data_bruta is None or data_bruta == "":
        return ""
    texto = str(data_bruta).strip()
    formatos = (FORMATO_DATA_HORA, "%Y-%m-%d %H:%M", FORMATO_DATA)
    if len(texto) == 16:  # "2026-10-28 14:05" -> completa os segundos
        texto += ":00"
    for fmt in formatos:
        try:
            dt = datetime.strptime(texto, fmt)
            break
        except ValueError:
            continue
    else:
        try:
            dt = datetime.fromisoformat(texto)
        except ValueError:
            return str(data_bruta)
    if com_hora:
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    if fmt == FORMATO_DATA:
        return dt.strftime("%d/%m/%Y")
    return dt.strftime("%d/%m/%Y %H:%M")


def converter_data_br(texto: str) -> str | None:
    """Converte data digitada pelo usuário (``28/10/2026``, ``28102026``, ``28-10-26``) para ISO.

    Retorna ``None`` se a data for inválida.
    """
    if not texto:
        return None
    t = texto.strip()
    if not t:
        return None
    candidatos = []
    if "/" in t or "-" in t or "." in t:
        partes = re.split(r"[/\-.]", t)
        if len(partes) == 3:
            d, m, a = partes
            if len(a) == 2:
                a = "20" + a if int(a) <= 69 else "19" + a
            candidatos.append(f"{int(a):04d}-{int(m):02d}-{int(d):02d}")
    elif t.isdigit():
        if len(t) == 8:
            candidatos.append(f"{t[4:]}-{t[2:4]}-{t[:2]}")
        elif len(t) == 6:
            candidatos.append(f"20{t[4:]}-{t[2:4]}-{t[:2]}")
    else:
        try:
            return datetime.fromisoformat(t).date().strftime(FORMATO_DATA)
        except ValueError:
            return None
    for c in candidatos:
        try:
            return datetime.strptime(c, FORMATO_DATA).strftime(FORMATO_DATA)
        except ValueError:
            continue
    return None


def somar_dias(data_iso: str, dias: int) -> str:
    """Soma dias a uma data ISO e devolve outra data ISO."""
    dt = datetime.strptime(data_iso[:10], FORMATO_DATA) + timedelta(days=dias)
    return dt.strftime(FORMATO_DATA)


def dias_entre(data_iso: str, referencia: str | None = None) -> int:
    """Quantos dias faltam (ou passaram) entre ``data_iso`` e hoje/referência."""
    base = datetime.strptime((referencia or hoje())[:10], FORMATO_DATA)
    alvo = datetime.strptime(str(data_iso)[:10], FORMATO_DATA)
    return (alvo - base).days


def primeiro_dia_mes(data_iso: str | None = None) -> str:
    d = datetime.strptime((data_iso or hoje())[:10], FORMATO_DATA)
    return d.replace(day=1).strftime(FORMATO_DATA)


def intervalo_padrao(dias: int = 30) -> tuple[str, str]:
    """Intervalo ``inicial, final`` cobrindo os últimos ``dias`` dias (padrão dos relatórios)."""
    fim = date.today()
    ini = fim - timedelta(days=max(0, dias - 1))
    return ini.strftime(FORMATO_DATA), fim.strftime(FORMATO_DATA)


# --------------------------------------------------------------------------------------
# Textos
# --------------------------------------------------------------------------------------


def normalizar(texto) -> str:
    """Remove acentos e joga em minúsculas — usado nas buscas ("café" encontra "CAFE")."""
    if texto is None:
        return ""
    t = unicodedata.normalize("NFD", str(texto))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower().strip()


def contem_sem_acento(haystack, needle) -> bool:
    """Verifica se ``needle`` está dentro de ``haystack`` ignorando acentos e caixa."""
    n = normalizar(needle)
    return bool(n) and n in normalizar(haystack)


def apenas_digitos(texto) -> str:
    """Mantém só números — usado em CPF/CNPJ/telefone/código de barras."""
    return re.sub(r"\D", "", str(texto or ""))


def formatar_cpf_cnpj(valor) -> str:
    """Mascara CPF (``123.456.789-09``) ou CNPJ (``12.345.678/0001-90``)."""
    d = apenas_digitos(valor)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return str(valor or "")


def formatar_telefone(valor) -> str:
    """Mascara telefone brasileiro: ``(31) 98888-7777``."""
    d = apenas_digitos(valor)
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return str(valor or "")


def limitar(texto, tamanho: int = 60) -> str:
    """Corta um texto longo adicionando reticências (usado em tabelas)."""
    t = str(texto or "")
    return t if len(t) <= tamanho else t[: tamanho - 1] + "…"


def slug(texto) -> str:
    """Gera um nome de arquivo seguro a partir de um texto."""
    t = normalizar(texto)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "arquivo"
