"""
Formas de pagamento usadas no PDV, nos recebimentos e nos pagamentos.

Centralizado aqui para que toda a interface use exatamente os mesmos rótulos —
assim os relatórios "por forma de pagamento" fecham sem ambiguidade.
"""

from __future__ import annotations

#: Ordem em que as formas aparecem nas telas.
TODAS = ["Dinheiro", "Pix", "Cartão de débito", "Cartão de crédito", "Fiado"]

#: Formas que representam recebimento imediato (não geram conta a receber).
IMEDIATAS = ["Dinheiro", "Pix", "Cartão de débito", "Cartão de crédito"]

#: Forma que gera conta a receber (o famoso "fiado" / crediário da casa).
FIADO = "Fiado"

#: Formas aceitas para receber uma conta em atraso / pagar uma despesa.
PARA_RECEBIMENTOS = ["Dinheiro", "Pix", "Cartão de débito", "Cartão de crédito"]

#: Ícones/atalhos exibidos nos botões do PDV.
ATALHOS = {
    "Dinheiro": "F4",
    "Pix": "F5",
    "Cartão de débito": "F6",
    "Cartão de crédito": "F7",
    "Fiado": "F8",
}

ROTULOS_CURTOS = {
    "Dinheiro": "Dinheiro",
    "Pix": "Pix",
    "Cartão de débito": "Débito",
    "Cartão de crédito": "Crédito",
    "Fiado": "Fiado",
}


def valida(forma: str) -> bool:
    return str(forma or "").strip() in TODAS


def normalizar(forma: str) -> str:
    """Aceita variações de digitação ("dinheiro", "PIX", "debito") e devolve o rótulo oficial."""
    alvo = str(forma or "").strip().lower()
    equivalencias = {
        "dinheiro": "Dinheiro",
        "cash": "Dinheiro",
        "pix": "Pix",
        "débito": "Cartão de débito",
        "debito": "Cartão de débito",
        "cartão de débito": "Cartão de débito",
        "cartao de debito": "Cartão de débito",
        "crédito": "Cartão de crédito",
        "credito": "Cartão de crédito",
        "cartão de crédito": "Cartão de crédito",
        "cartao de credito": "Cartão de crédito",
        "fiado": "Fiado",
        "crediario": "Fiado",
        "crediário": "Fiado",
        "conta": "Fiado",
    }
    return equivalencias.get(alvo, str(forma or "").strip())


def gera_conta_receber(forma: str) -> bool:
    return normalizar(forma) == FIADO


def entra_no_caixa_fisico(forma: str) -> bool:
    """Somente dinheiro fica na gaveta; Pix e cartão entram como recebimento eletrônico."""
    return normalizar(forma) == "Dinheiro"
