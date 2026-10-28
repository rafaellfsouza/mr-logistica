"""
Vendas: carrinho do PDV, finalização com pagamento misto e troco, cancelamento e devolução.

**Ciclo de vida de uma venda**

``carrinho`` → ``finalizar`` → ``concluida`` → (``cancelar`` → ``cancelada``) ou
(``devolver`` → ``devolvida`` / ``parcialmente_devolvida``).

Ao finalizar, tudo acontece dentro de **uma única transação**:

1. grava o cupom (``vendas``) e os itens com custo e lucro por linha;
2. dá baixa no estoque (por lote, critério FEFO, quando o produto controla lote);
3. grava os pagamentos (dinheiro, Pix, débito, crédito e fiado) e o troco;
4. cria a conta a receber do fiado e valida o limite de crédito do cliente;
5. lança os valores no caixa aberto;
6. registra a venda na trilha de auditoria.

Se qualquer passo falhar, **nada** é gravado — não existe venda "pela metade".

**Receita líquida**: devoluções não geram "venda negativa". O valor devolvido é
descontado do cupom original (visão ``vw_vendas_resumo`` → ``total_liquido``), e a
mercadoria volta ao estoque como ``devolucao_cliente`` (que não conta como receita).
Assim o relatório de vendas, o de lucro e o caixa fecham iguais.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import caixa as caixa_mod
from . import clientes as clientes_mod
from . import contas_receber
from . import estoque as estoque_mod
from . import produtos as produtos_mod
from . import unidades
from . import usuarios as usuarios_mod
from .banco import Banco
from .esquema import FORMA_FIADO
from .formas_pagamento import TODAS as FORMAS_PAGAMENTO
from .utils import (
    agora,
    agora_iso,
    formatar_dinheiro,
    formatar_quantidade,
    hoje,
    para_centavos,
    para_reais,
    somar_dias,
    total_linha_centavos,
)


class ErroVenda(Exception):
    """Erro de regra de negócio na venda (estoque, pagamento, limite de crédito...)."""


# --------------------------------------------------------------------------------------
# Carrinho
# --------------------------------------------------------------------------------------


@dataclass
class ItemCarrinho:
    """Uma linha do carrinho do PDV."""

    produto_id: int
    codigo: str
    codigo_barras: str
    nome: str
    unidade: str
    unidade_base: str
    quantidade: float
    preco_unitario: int              # centavos, NA unidade vendida
    custo_unitario: int              # centavos, por unidade BASE
    fator: float                     # quantas unidades base valem 1 unidade vendida
    desconto: int = 0                # centavos (R$), específico da linha
    desconto_tipo: str = ""          # '' | '%' (só informativo, o valor já está em centavos)
    permite_fracionar: bool = True
    decimais: int = 0
    imagem: str = ""
    sequencia: int = 0

    # ---------------------------------------------------------------- totais
    @property
    def quantidade_base(self) -> float:
        return unidades.arredondar(self.quantidade * self.fator)

    @property
    def total_bruto(self) -> int:
        return total_linha_centavos(self.quantidade, self.preco_unitario)

    @property
    def total_liquido(self) -> int:
        return max(0, self.total_bruto - int(self.desconto or 0))

    @property
    def custo_total(self) -> int:
        return int(round(self.quantidade_base * self.custo_unitario))

    @property
    def lucro(self) -> int:
        return self.total_liquido - self.custo_total

    @property
    def margem_pct(self) -> float:
        return round(self.lucro * 100.0 / self.total_liquido, 2) if self.total_liquido > 0 else 0.0

    def descricao_quantidade(self) -> str:
        return f"{formatar_quantidade(self.quantidade)} {self.unidade}"

    def como_dict(self) -> dict:
        return {
            "produto_id": self.produto_id,
            "codigo": self.codigo,
            "codigo_barras": self.codigo_barras,
            "nome": self.nome,
            "unidade": self.unidade,
            "quantidade": self.quantidade,
            "quantidade_base": self.quantidade_base,
            "preco_unitario": self.preco_unitario,
            "desconto": self.desconto,
            "total_bruto": self.total_bruto,
            "total_liquido": self.total_liquido,
            "custo_unitario": self.custo_unitario,
            "custo_total": self.custo_total,
            "lucro": self.lucro,
            "sequencia": self.sequencia,
        }


@dataclass
class TotaisCarrinho:
    subtotal: int = 0
    desconto_itens: int = 0
    desconto_venda: int = 0
    acrescimo: int = 0
    total: int = 0
    custo: int = 0
    lucro: int = 0
    quantidade_itens: int = 0
    quantidade_produtos: float = 0.0
    margem_pct: float = 0.0
    ticket_medio: int = 0


class Carrinho:
    """Carrinho de venda com as mesmas regras usadas na finalização."""

    def __init__(self, banco: Banco, vendedor=None, config: dict | None = None):
        self.banco = banco
        self.vendedor = vendedor
        self.config = config if config is not None else {
            "venda_permite_preco_zero": banco.config_pegar_bool("venda_permite_preco_zero", False),
            "venda_permite_estoque_negativo": banco.config_pegar_bool("venda_permite_estoque_negativo", False),
            "venda_exige_caixa_aberto": banco.config_pegar_bool("venda_exige_caixa_aberto", True),
        }
        self.itens: list[ItemCarrinho] = []
        self.cliente = None
        self.desconto_valor: int = 0        # desconto global em centavos
        self.acrescimo: int = 0             # acréscimo global em centavos
        self.observacao: str = ""
        self._sequencia = 0

    # ------------------------------------------------------------------ itens
    def limpar(self) -> None:
        self.itens.clear()
        self.cliente = None
        self.desconto_valor = 0
        self.acrescimo = 0
        self.observacao = ""
        self._sequencia = 0

    def __len__(self) -> int:
        return len(self.itens)

    def __bool__(self) -> bool:
        return bool(self.itens)

    @property
    def quantidade_itens(self) -> int:
        return len(self.itens)

    def indice_do_item(self, produto_id: int, unidade: str, preco: int) -> int | None:
        """Procura uma linha igual (mesmo produto, unidade e preço) para somar quantidade."""
        for i, item in enumerate(self.itens):
            if item.produto_id == produto_id and item.unidade == unidade and item.preco_unitario == preco:
                return i
        return None

    def adicionar(
        self,
        produto,
        quantidade: float = 1.0,
        unidade: str | None = None,
        preco_unitario: int | None = None,
        sobrescrever: bool = False,
    ) -> ItemCarrinho:
        """Adiciona um produto ao carrinho.

        Se o mesmo produto/unidade/preço já estiver no carrinho, a quantidade é
        **somada** (comportamento esperado do bipador) — a não ser que
        ``sobrescrever=True``.
        """
        if produto is None:
            raise ErroVenda("Produto não encontrado.")
        if not int(produto["ativo"] or 0):
            raise ErroVenda(f"O produto '{produto['nome']}' está desativado e não pode ser vendido.")
        unidade_base = str(produto["unidade_base"] or "un")
        unidade_usada = str(unidade or produto["unidade_venda"] or unidade_base).strip().lower()
        try:
            unidades.validar_quantidade(produto, quantidade, unidade_usada)
        except unidades.ErroUnidade as exc:
            raise ErroVenda(str(exc)) from None
        try:
            fator = unidades.fator_para_base_produto(produto, unidade_usada, self.banco)
        except unidades.ErroUnidade as exc:
            raise ErroVenda(str(exc)) from None

        if preco_unitario is None:
            # O preço cadastrado vale para 1 unidade de VENDA. Para qualquer outra
            # unidade, converte pelo fator (1 cx = 6 un => 1 un = preço/6).
            preco_venda = int(produto["preco_venda"] or 0)
            fator_cadastrado = float(produto["fator_venda"] or 1) or 1.0
            preco_base = int(round(preco_venda / fator_cadastrado)) if fator_cadastrado else preco_venda
            preco = int(round(preco_base * fator))
        else:
            preco = int(para_centavos(preco_unitario))
        if preco < 0:
            raise ErroVenda("O preço não pode ser negativo.")
        if preco == 0 and not self.config.get("venda_permite_preco_zero"):
            raise ErroVenda(
                f"O produto '{produto['nome']}' está sem preço de venda. "
                "Cadastre o preço ou habilite 'permitir venda com preço zero' nas configurações."
            )

        quantidade = unidades.arredondar(float(quantidade))
        indice = None if sobrescrever else self.indice_do_item(int(produto["id"]), unidade_usada, preco)
        if indice is not None:
            item = self.itens[indice]
            item.quantidade = unidades.arredondar(item.quantidade + quantidade)
            self._checar_estoque(item, produto)
            return item

        self._sequencia += 1
        item = ItemCarrinho(
            produto_id=int(produto["id"]),
            codigo=str(produto["codigo"] or ""),
            codigo_barras=str(produto["codigo_barras"] or ""),
            nome=str(produto["nome"] or ""),
            unidade=unidade_usada,
            unidade_base=unidade_base,
            quantidade=quantidade,
            preco_unitario=preco,
            custo_unitario=int(produto["preco_custo"] or 0),
            fator=fator,
            permite_fracionar=bool(int(produto["permite_fracionar"] or 0)),
            decimais=int(produto["decimais"] or 0),
            imagem=str(produto["foto"] or ""),
            sequencia=self._sequencia,
        )
        self.itens.append(item)
        self._checar_estoque(item, produto)
        return item

    def _checar_estoque(self, item: ItemCarrinho, produto) -> None:
        """Avisa (com erro) quando a quantidade passa do saldo, se o sistema estiver configurado assim."""
        if self.config.get("venda_permite_estoque_negativo"):
            return
        saldo = estoque_mod.saldo(self.banco, item.produto_id)
        if item.quantidade_base > saldo + 1e-9:
            raise ErroVenda(
                f"Estoque insuficiente de '{item.nome}': disponível "
                f"{formatar_quantidade(saldo)} {item.unidade_base}, pedido "
                f"{formatar_quantidade(item.quantidade_base)} {item.unidade_base}."
            )

    def remover(self, indice: int) -> ItemCarrinho | None:
        if 0 <= indice < len(self.itens):
            return self.itens.pop(indice)
        return None

    def item(self, indice: int) -> ItemCarrinho | None:
        if 0 <= indice < len(self.itens):
            return self.itens[indice]
        return None

    def alterar_quantidade(self, indice: int, quantidade: float, unidade: str | None = None) -> ItemCarrinho:
        item = self.item(indice)
        if not item:
            raise ErroVenda("Item não encontrado no carrinho.")
        produto = produtos_mod.pegar(self.banco, item.produto_id)
        if produto is None:
            raise ErroVenda("Produto não encontrado.")
        if unidade and str(unidade).lower() != item.unidade:
            unidade_nova = str(unidade).strip().lower()
            try:
                fator = unidades.fator_para_base_produto(produto, unidade_nova, self.banco)
            except unidades.ErroUnidade as exc:
                raise ErroVenda(str(exc)) from None
            quantidade_base = item.quantidade_base  # preserva a quantidade real
            item.unidade = unidade_nova
            item.fator = fator
            item.quantidade = unidades.arredondar(quantidade_base / fator) if fator else quantidade_base
            fator_cadastrado = float(produto["fator_venda"] or 1) or 1.0
            preco_base = int(round(int(produto["preco_venda"] or 0) / fator_cadastrado)) if fator_cadastrado else 0
            if preco_base:
                item.preco_unitario = int(round(preco_base * fator))
            item.custo_unitario = int(produto["preco_custo"] or 0)
        try:
            unidades.validar_quantidade(produto, quantidade, item.unidade)
        except unidades.ErroUnidade as exc:
            raise ErroVenda(str(exc)) from None
        item.quantidade = unidades.arredondar(float(quantidade))
        self._checar_estoque(item, produto)
        return item

    def alterar_preco(self, indice: int, preco) -> ItemCarrinho:
        item = self.item(indice)
        if not item:
            raise ErroVenda("Item não encontrado no carrinho.")
        novo = int(para_centavos(preco))
        if novo < 0:
            raise ErroVenda("O preço não pode ser negativo.")
        if novo == 0 and not self.config.get("venda_permite_preco_zero"):
            raise ErroVenda("Preço zero não é permitido (habilite nas configurações).")
        item.preco_unitario = novo
        return item

    def desconto_no_item(self, indice: int, valor=None, percentual: float | None = None) -> ItemCarrinho:
        """Aplica desconto **em uma linha** (valor em R$ ou %)."""
        item = self.item(indice)
        if not item:
            raise ErroVenda("Item não encontrado no carrinho.")
        if percentual is not None:
            pct = float(percentual)
            if pct < 0 or pct > 100:
                raise ErroVenda("O desconto percentual deve estar entre 0 e 100%.")
            item.desconto = int(round(item.total_bruto * pct / 100.0))
            item.desconto_tipo = "%"
        else:
            centavos = int(para_centavos(valor))
            if centavos < 0:
                raise ErroVenda("Desconto não pode ser negativo.")
            if centavos > item.total_bruto:
                raise ErroVenda(
                    f"O desconto ({formatar_dinheiro(centavos)}) não pode ser maior que o total da linha "
                    f"({formatar_dinheiro(item.total_bruto)})."
                )
            item.desconto = centavos
            item.desconto_tipo = ""
        return item

    def definir_cliente(self, cliente) -> None:
        if cliente is None:
            self.cliente = None
            return
        if not int(cliente["ativo"] or 0):
            raise ErroVenda("Cliente desativado.")
        self.cliente = cliente

    def definir_desconto(self, valor=None, percentual: float | None = None, limite_pct: float = 100.0) -> int:
        """Desconto global da venda (em R$ ou %). Retorna o valor em centavos."""
        subtotal = self.totais().subtotal
        if percentual is not None:
            pct = float(percentual)
            if pct < 0 or pct > 100:
                raise ErroVenda("O desconto percentual deve estar entre 0 e 100%.")
            if pct > float(limite_pct or 0) + 1e-9:
                raise ErroVenda(
                    f"Seu perfil permite desconto máximo de {limite_pct:.0f}%. "
                    "Peça a liberação de um administrador."
                )
            self.desconto_valor = int(round(subtotal * pct / 100.0))
        else:
            centavos = int(para_centavos(valor))
            if centavos < 0:
                raise ErroVenda("Desconto não pode ser negativo.")
            pct_equivalente = (centavos * 100.0 / subtotal) if subtotal > 0 else 0.0
            if pct_equivalente > float(limite_pct or 0) + 1e-9:
                raise ErroVenda(
                    f"Desconto de {pct_equivalente:.1f}% acima do limite do seu perfil ({limite_pct:.0f}%)."
                )
            self.desconto_valor = centavos
        if self.desconto_valor > subtotal:
            raise ErroVenda(
                f"O desconto ({formatar_dinheiro(self.desconto_valor)}) não pode ser maior que o subtotal "
                f"({formatar_dinheiro(subtotal)})."
            )
        return self.desconto_valor

    def definir_acrescimo(self, valor) -> int:
        self.acrescimo = max(0, int(para_centavos(valor)))
        if self.acrescimo > 1_000_000_00:
            raise ErroVenda("Acréscimo muito alto.")
        return self.acrescimo

    # ------------------------------------------------------------------ totais
    def totais(self) -> TotaisCarrinho:
        subtotal = sum(i.total_bruto for i in self.itens)
        desconto_itens = sum(int(i.desconto or 0) for i in self.itens)
        desconto_venda = min(int(self.desconto_valor or 0), max(0, subtotal - desconto_itens))
        acrescimo = int(self.acrescimo or 0)
        custo = sum(i.custo_total for i in self.itens)
        total = max(0, subtotal - desconto_itens - desconto_venda + acrescimo)
        return TotaisCarrinho(
            subtotal=subtotal,
            desconto_itens=desconto_itens,
            desconto_venda=desconto_venda,
            acrescimo=acrescimo,
            total=total,
            custo=custo,
            lucro=total - custo,
            quantidade_itens=len(self.itens),
            quantidade_produtos=round(sum(i.quantidade_base for i in self.itens), 4),
            margem_pct=round((total - custo) * 100.0 / total, 2) if total > 0 else 0.0,
            ticket_medio=total,
        )

    def ratear_desconto(self) -> list[dict]:
        """Distribui o desconto global entre as linhas, proporcionalmente ao valor de cada uma.

        O rateio usa o método do *resto maior*: a soma das parcelas é sempre exatamente
        igual ao desconto total (nenhum centavo se perde).
        """
        totais = self.totais()
        desconto = totais.desconto_venda
        acrescimo = totais.acrescimo
        base = [i.total_liquido for i in self.itens]
        soma = sum(base)
        resultado = []
        for item, valor_base in zip(self.itens, base):
            if desconto <= 0 or soma <= 0:
                rateio_desconto = 0
            else:
                rateio_desconto = int(round(desconto * valor_base / soma))
            if acrescimo <= 0 or soma <= 0:
                rateio_acrescimo = 0
            else:
                rateio_acrescimo = int(round(acrescimo * valor_base / soma))
            resultado.append(
                {
                    "item": item,
                    "desconto_rateado": rateio_desconto,
                    "acrescimo_rateado": rateio_acrescimo,
                }
            )
        # Ajuste fino do arredondamento (lança a diferença na linha de maior valor)
        for campo, alvo in (("desconto_rateado", desconto), ("acrescimo_rateado", acrescimo)):
            if alvo <= 0 or not resultado:
                continue
            diferenca = alvo - sum(r[campo] for r in resultado)
            if diferenca:
                maior = max(resultado, key=lambda r: r["item"].total_liquido)
                maior[campo] = max(0, maior[campo] + diferenca)
        for r in resultado:
            item: ItemCarrinho = r["item"]
            r["desconto_total"] = int(item.desconto or 0) + r["desconto_rateado"]
            r["acrescimo_total"] = r["acrescimo_rateado"]
            r["total_liquido"] = max(0, item.total_bruto - r["desconto_total"] + r["acrescimo_total"])
            r["lucro"] = r["total_liquido"] - item.custo_total
        return resultado


# --------------------------------------------------------------------------------------
# Pagamentos
# --------------------------------------------------------------------------------------


@dataclass
class Pagamento:
    forma: str
    valor: int
    recebido: int = 0     # quanto foi entregue em dinheiro (para calcular o troco)
    parcelas: int = 1
    operadora: str = ""
    documento: str = ""

    def como_dict(self) -> dict:
        return {
            "forma": self.forma,
            "valor": self.valor,
            "recebido": self.recebido,
            "parcelas": self.parcelas,
            "operadora": self.operadora,
            "documento": self.documento,
        }


@dataclass
class ResultadoPagamento:
    total: int
    pago: int
    troco: int
    falta: int
    fiado: int
    pagamentos: list[Pagamento] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.falta <= 0


def normalizar_pagamentos(pagamentos: Iterable[Any]) -> list[Pagamento]:
    """Aceita ``Pagamento`` ou ``dict`` e devolve uma lista limpa e agrupada."""
    consolidado: dict[str, Pagamento] = {}
    for bruto in pagamentos or []:
        if isinstance(bruto, Pagamento):
            pg = bruto
        elif isinstance(bruto, dict):
            pg = Pagamento(
                forma=str(bruto.get("forma") or ""),
                valor=int(para_centavos(bruto.get("valor", 0))),
                recebido=int(para_centavos(bruto.get("recebido", 0))),
                parcelas=int(bruto.get("parcelas", 1) or 1),
                operadora=str(bruto.get("operadora") or ""),
                documento=str(bruto.get("documento") or ""),
            )
        else:
            raise ErroVenda("Pagamento em formato inválido.")
        from .formas_pagamento import normalizar

        forma = normalizar(pg.forma)
        if forma not in FORMAS_PAGAMENTO:
            raise ErroVenda(f"Forma de pagamento inválida: '{pg.forma}'.")
        if pg.valor < 0:
            raise ErroVenda("Valor de pagamento não pode ser negativo.")
        if pg.valor == 0:
            continue
        pg.forma = forma
        pg.parcelas = max(1, min(48, int(pg.parcelas or 1)))
        if forma != "Dinheiro":
            pg.recebido = pg.valor
        else:
            pg.recebido = max(pg.valor, pg.recebido or 0)
        existente = consolidado.get(forma)
        if existente:
            existente.valor += pg.valor
            existente.recebido += pg.recebido
            existente.parcelas = max(existente.parcelas, pg.parcelas)
            existente.operadora = existente.operadora or pg.operadora
            existente.documento = (existente.documento + " / " + pg.documento).strip(" /") if pg.documento else existente.documento
        else:
            consolidado[forma] = pg
    ordem = {forma: i for i, forma in enumerate(FORMAS_PAGAMENTO)}
    return sorted(consolidado.values(), key=lambda p: ordem.get(p.forma, 99))


def validar_pagamento(total: int, pagamentos: Iterable[Any], permitir_fiado: bool = True) -> ResultadoPagamento:
    """Confere se os pagamentos cobrem o total e calcula o troco.

    Regras:

    * o troco só pode existir quando há pagamento em **dinheiro** — e nunca pode
      ser maior que o valor entregue;
    * se faltar valor, ele precisa ir para o **fiado** (e aí exige cliente);
    * ``Fiado`` não gera troco.
    """
    lista = normalizar_pagamentos(pagamentos)
    if not lista:
        raise ErroVenda("Informe ao menos uma forma de pagamento.")
    pago = sum(p.valor for p in lista)
    fiado = sum(p.valor for p in lista if p.forma == FORMA_FIADO)
    dinheiro = [p for p in lista if p.forma == "Dinheiro"]
    recebido_dinheiro = sum(p.recebido for p in dinheiro)
    troco = 0
    if dinheiro:
        troco = recebido_dinheiro - sum(p.valor for p in dinheiro)
        if troco < 0:
            raise ErroVenda(
                f"Dinheiro recebido ({formatar_dinheiro(recebido_dinheiro)}) é menor que o valor em dinheiro da venda "
                f"({formatar_dinheiro(sum(p.valor for p in dinheiro))})."
            )
    falta = max(0, int(total) - pago)
    if falta > 0 and not permitir_fiado:
        raise ErroVenda(
            f"Faltam {formatar_dinheiro(falta)} para concluir a venda. Complete o pagamento ou lance no fiado."
        )
    if falta > 0:
        fiado += falta
    return ResultadoPagamento(
        total=int(total), pago=pago, troco=troco, falta=falta, fiado=fiado, pagamentos=lista
    )


# --------------------------------------------------------------------------------------
# Finalização
# --------------------------------------------------------------------------------------


def _id_de(registro) -> int | None:
    """Extrai o ``id`` de uma linha do banco ou de um dicionário comum."""
    if registro is None:
        return None
    try:
        return int(registro["id"])
    except (KeyError, IndexError, TypeError, ValueError):
        try:
            return int(getattr(registro, "id"))
        except (TypeError, ValueError):
            return None


def _devolver_por_lote(banco: Banco, produto_id: int, quantidade: float, movimentos: list,
                       custo_unitario: int, documento_id: int | None, observacao: str, autor) -> None:
    """Devolve a mercadoria aos lotes de origem, na ordem inversa em que saíram.

    Se a venda baixou de 3 lotes diferentes, a devolução repõe proporcionalmente em
    cada um — assim o saldo por lote continua fiel à realidade.
    """
    restante = unidades.arredondar(quantidade)
    if restante <= 0:
        return
    for movimento in movimentos or []:
        if restante <= 1e-9:
            break
        usar = min(float(movimento["quantidade"] or 0), restante)
        if usar <= 1e-9:
            continue
        estoque_mod.devolver_ao_estoque(
            banco, produto_id, usar, motivo="devolucao_cliente",
            lote_origem_id=movimento["lote_id"], validade_sugerida=movimento["validade"] or "",
            custo_unitario=int(movimento["custo_unitario"] or custo_unitario or 0),
            documento_id=documento_id, observacao=observacao, autor=autor,
        )
        restante = unidades.arredondar(restante - usar)
    if restante > 1e-9:
        estoque_mod.devolver_ao_estoque(
            banco, produto_id, restante, motivo="devolucao_cliente",
            lote_origem_id=None, validade_sugerida="",
            custo_unitario=int(custo_unitario or 0), documento_id=documento_id,
            observacao=observacao, autor=autor,
        )


def _usuario_info(usuario) -> tuple[int | None, str]:
    if not usuario:
        return None, ""
    try:
        return int(usuario["id"]), str(usuario["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, str(usuario)


def finalizar(
    banco: Banco,
    carrinho: Carrinho,
    pagamentos: Iterable[Any],
    cliente=None,
    vendedor=None,
    desconto_valor=None,
    acrescimo_valor=None,
    observacao: str = "",
    vencimento_fiado: str = "",
    troco_informado: int | None = None,
    exigir_caixa: bool | None = None,
    limite_desconto_pct: float | None = None,
) -> dict:
    """Grava a venda completa. Devolve ``{'venda_id', 'numero', 'total', 'troco', ...}``."""
    if not carrinho.itens:
        raise ErroVenda("O carrinho está vazio.")
    if desconto_valor is not None:
        carrinho.definir_desconto(valor=desconto_valor, limite_pct=limite_desconto_pct or 100.0)
    if acrescimo_valor is not None:
        carrinho.definir_acrescimo(acrescimo_valor)

    cliente = cliente if cliente is not None else carrinho.cliente
    vendedor = vendedor if vendedor is not None else carrinho.vendedor
    totais = carrinho.totais()
    if totais.total <= 0 and not carrinho.config.get("venda_permite_preco_zero"):
        raise ErroVenda("O total da venda não pode ser zero.")

    resultado = validar_pagamento(totais.total, pagamentos)
    if troco_informado is not None:
        resultado.troco = int(troco_informado)

    caixa_atual = caixa_mod.caixa_aberto(banco)
    exige_caixa = carrinho.config.get("venda_exige_caixa_aberto", True) if exigir_caixa is None else exigir_caixa
    if exige_caixa and not caixa_atual:
        raise ErroVenda(
            "Nenhum caixa aberto. Abra o caixa em Financeiro > Caixa para registrar a venda "
            "(ou desative a exigência em Configurações)."
        )
    caixa_id = int(caixa_atual["id"]) if caixa_atual else None

    # Fiado exige cliente e respeita o limite de crédito
    if resultado.fiado > 0:
        alvo = cliente if cliente is not None else carrinho.cliente
        if not alvo:
            raise ErroVenda("Para vender no fiado é obrigatório identificar o cliente.")
        cliente = clientes_mod.pegar(banco, _id_de(alvo)) or alvo
        ok, mensagem = clientes_mod.pode_fiar(cliente, resultado.fiado)
        if not ok:
            raise ErroVenda(mensagem)
    elif cliente is not None:
        cliente = clientes_mod.pegar(banco, _id_de(cliente)) or cliente


    usuario_id, usuario_nome = _usuario_info(vendedor)
    numero = banco.proximo_numero("vendas")
    data_venda = hoje()
    rateio = carrinho.ratear_desconto()

    with banco.transacao():
        venda_id = banco.inserir(
            "vendas",
            {
                "numero": numero,
                "cliente_id": int(cliente["id"]) if cliente else None,
                "cliente_nome": str(cliente["nome"]) if cliente else "Consumidor final",
                "vendedor_id": usuario_id,
                "vendedor_nome": usuario_nome,
                "subtotal": totais.subtotal,
                "desconto": totais.desconto_itens + totais.desconto_venda,
                "acrescimo": totais.acrescimo,
                "total": totais.total,
                "custo_total": totais.custo,
                "lucro": totais.lucro,
                "valor_pago": max(0, resultado.pago - resultado.fiado),
                "troco": resultado.troco,
                "valor_fiado": resultado.fiado,
                "status": "concluida",
                "caixa_id": caixa_id,
                "observacao": str(observacao or carrinho.observacao or ""),
                "criada_em": agora_iso(),
                "data_venda": data_venda,
            },
        )

        # ------------------------------------------------------------------ itens + estoque
        for ordem, linha in enumerate(rateio, start=1):
            item: ItemCarrinho = linha["item"]
            banco.inserir(
                "venda_itens",
                {
                    "venda_id": venda_id,
                    "produto_id": item.produto_id,
                    "codigo": item.codigo,
                    "codigo_barras": item.codigo_barras,
                    "nome": item.nome,
                    "unidade": item.unidade,
                    "quantidade": item.quantidade,
                    "quantidade_base": item.quantidade_base,
                    "preco_unitario": item.preco_unitario,
                    "desconto": linha["desconto_total"],
                    "acrescimo": linha["acrescimo_total"],
                    "total_bruto": item.total_bruto,
                    "total_liquido": linha["total_liquido"],
                    "custo_unitario": item.custo_unitario,
                    "custo_total": item.custo_total,
                    "lucro": linha["lucro"],
                    "ordem": ordem,
                },
            )
            estoque_mod.saida(
                banco,
                item.produto_id,
                item.quantidade_base,
                motivo="venda",
                unidade=item.unidade_base,
                custo_unitario=item.custo_unitario,
                documento_id=venda_id,
                observacao=f"Venda nº {numero:06d}",
                autor=vendedor,
                permitir_negativo=bool(carrinho.config.get("venda_permite_estoque_negativo")),
                bloquear_vencido=False,
            )

        # ------------------------------------------------------------------ pagamentos
        for pg in resultado.pagamentos:
            if pg.valor <= 0:
                continue
            banco.inserir(
                "venda_pagamentos",
                {
                    "venda_id": venda_id,
                    "forma": pg.forma,
                    "valor": pg.valor,
                    "parcelas": pg.parcelas,
                    "recebido": pg.recebido,
                    "operadora": pg.operadora,
                    "documento": pg.documento,
                    "criado_em": agora_iso(),
                },
            )

        # ------------------------------------------------------------------ caixa
        caixa_mod.registrar_venda_no_caixa(
            banco, caixa_id, venda_id, numero, [p.como_dict() for p in resultado.pagamentos],
            resultado.troco, autor=vendedor,
        )

        # ------------------------------------------------------------------ fiado
        conta_id = None
        if resultado.fiado > 0:
            vencimento = vencimento_fiado or hoje()
            from .utils import converter_data_br

            vencimento = converter_data_br(str(vencimento)) or hoje()
            conta_id = contas_receber.criar_de_venda(
                banco, venda_id, int(cliente["id"]), str(cliente["nome"]), resultado.fiado,
                vencimento=vencimento, numero_venda=numero, autor=vendedor,
            )

    carrinho.limpar()
    banco.registrar_log(
        "venda_finalizada",
        f"Cupom nº {numero:06d} — {formatar_dinheiro(totais.total)} — {len(rateio)} item(ns)",
        usuario_id, usuario_nome,
    )
    venda = pegar(banco, venda_id)
    return {
        "venda_id": venda_id,
        "numero": numero,
        "total": totais.total,
        "subtotal": totais.subtotal,
        "desconto": totais.desconto_itens + totais.desconto_venda,
        "acrescimo": totais.acrescimo,
        "troco": resultado.troco,
        "fiado": resultado.fiado,
        "pago": resultado.pago,
        "conta_receber_id": conta_id,
        "caixa_id": caixa_id,
        "cliente_nome": str(cliente["nome"]) if cliente else "Consumidor final",
        "venda": venda,
        "itens": [dict(i) for i in itens_venda_dict(banco, venda_id)],
    }


# --------------------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------------------


def pegar(banco: Banco, venda_id: int):
    return banco.consultar_uma("SELECT * FROM vw_vendas_resumo WHERE id=?", (venda_id,))


def por_numero(banco: Banco, numero: int):
    return banco.consultar_uma("SELECT * FROM vw_vendas_resumo WHERE numero=?", (numero,))


def itens(banco: Banco, venda_id: int) -> list:
    return banco.consultar(
        """SELECT vi.*, p.nome AS nome_atual, p.unidade_base, p.foto
             FROM venda_itens vi LEFT JOIN produtos p ON p.id = vi.produto_id
            WHERE vi.venda_id=? ORDER BY vi.ordem, vi.id""",
        (venda_id,),
    )


def itens_venda_dict(banco: Banco, venda_id: int) -> list[dict]:
    return [dict(l) for l in itens(banco, venda_id)]


def pagamentos(banco: Banco, venda_id: int) -> list:
    return banco.consultar("SELECT * FROM venda_pagamentos WHERE venda_id=? ORDER BY id", (venda_id,))


def pagamentos_dict(banco: Banco, venda_id: int) -> list[dict]:
    return [dict(l) for l in pagamentos(banco, venda_id)]


def listar(
    banco: Banco,
    data_inicial: str = "",
    data_final: str = "",
    status: str = "",
    cliente_id: int | None = None,
    vendedor_id: int | None = None,
    caixa_id: int | None = None,
    texto: str = "",
    forma_pagamento: str = "",
    numero: int | None = None,
    incluir_canceladas: bool = False,
    limite: int = 500,
) -> list:
    """Lista vendas com filtros combináveis (tela de Vendas e relatórios)."""
    condicoes, params = [], []
    if numero:
        condicoes.append("v.numero = ?")
        params.append(int(numero))
    if data_inicial:
        condicoes.append("v.data_venda >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("v.data_venda <= date(?)")
        params.append(str(data_final)[:10])
    if status:
        condicoes.append("v.status = ?")
        params.append(status)
    elif not incluir_canceladas:
        condicoes.append("v.status <> 'cancelada'")
    if cliente_id:
        condicoes.append("v.cliente_id = ?")
        params.append(int(cliente_id))
    if vendedor_id:
        condicoes.append("v.vendedor_id = ?")
        params.append(int(vendedor_id))
    if caixa_id:
        condicoes.append("v.caixa_id = ?")
        params.append(int(caixa_id))
    if forma_pagamento:
        condicoes.append("EXISTS (SELECT 1 FROM venda_pagamentos vp WHERE vp.venda_id=v.id AND vp.forma=?)")
        params.append(forma_pagamento)
    if texto:
        condicoes.append(
            "(v.cliente_nome LIKE ? OR v.vendedor_nome LIKE ? OR CAST(v.numero AS TEXT) LIKE ? OR v.observacao LIKE ?)"
        )
        params += [f"%{texto}%"] * 4
    # total_liquido/lucro_liquido seguem a mesma regra da visão vw_vendas_resumo
    sql = """SELECT v.*,
                    (SELECT COUNT(*) FROM venda_itens vi WHERE vi.venda_id=v.id) AS qtd_itens,
                    (SELECT COALESCE(SUM(vi2.quantidade_base),0) FROM venda_itens vi2 WHERE vi2.venda_id=v.id) AS qtd_produtos,
                    (SELECT GROUP_CONCAT(DISTINCT vp.forma) FROM venda_pagamentos vp WHERE vp.venda_id=v.id) AS formas,
                    COALESCE((SELECT SUM(d.valor) FROM devolucoes d WHERE d.venda_id=v.id),0) AS devolvido,
                    COALESCE((SELECT SUM(di.valor) FROM devolucoes d
                                JOIN devolucao_itens di ON di.devolucao_id=d.id
                               WHERE d.venda_id=v.id),0) AS custo_devolvido,
                    CASE WHEN v.status='cancelada' THEN 0
                         ELSE MAX(0, v.total - COALESCE((SELECT SUM(d.valor) FROM devolucoes d WHERE d.venda_id=v.id),0))
                    END AS total_liquido,
                    CASE WHEN v.status='cancelada' THEN 0
                         ELSE v.lucro - COALESCE((SELECT SUM(di.valor) FROM devolucoes d
                                                    JOIN devolucao_itens di ON di.devolucao_id=d.id
                                                   WHERE d.venda_id=v.id),0)
                    END AS lucro_liquido
               FROM vendas v"""
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY v.id DESC LIMIT ?"
    params.append(int(limite))
    return banco.consultar(sql, params)


def ultima_venda(banco: Banco):
    return banco.consultar_uma("SELECT * FROM vw_vendas_resumo ORDER BY id DESC LIMIT 1")


def resumo_dia(banco: Banco, data: str | None = None) -> dict:
    """Indicadores de vendas do dia (painel inicial)."""
    dia = str(data or hoje())[:10]
    linha = banco.consultar_uma(
        """SELECT COUNT(*) AS qtd,
                  COALESCE(SUM(total_liquido),0) AS total,
                  COALESCE(SUM(lucro_liquido),0) AS lucro,
                  COALESCE(AVG(total_liquido),0) AS ticket,
                  COALESCE(SUM(qtd_itens),0) AS itens
             FROM vw_vendas_resumo WHERE data_venda=? AND status<>'cancelada'""",
        (dia,),
    )
    canceladas = banco.consultar_valor(
        "SELECT COUNT(*) FROM vendas WHERE data_venda=? AND status='cancelada'", (dia,)
    )
    return {
        "data": dia,
        "quantidade": int(linha["qtd"] or 0),
        "total": int(linha["total"] or 0),
        "lucro": int(linha["lucro"] or 0),
        "ticket_medio": int(round(float(linha["ticket"] or 0))),
        "itens": int(linha["itens"] or 0),
        "canceladas": int(canceladas or 0),
    }


# --------------------------------------------------------------------------------------
# Cancelamento
# --------------------------------------------------------------------------------------


def pode_cancelar(venda, usuario=None, hoje_iso: str | None = None) -> tuple[bool, str]:
    """Regra de cancelamento: administrador pode sempre; os demais, só a própria venda do dia."""
    if venda is None:
        return False, "Venda não encontrada."
    if venda["status"] == "cancelada":
        return False, "Esta venda já foi cancelada."
    if venda["status"] in ("devolvida",):
        return False, "Venda totalmente devolvida não pode ser cancelada."
    if usuario and usuarios_mod.pode(usuario, "vendas_cancelar"):
        return True, ""
    dia = str(hoje_iso or hoje())[:10]
    if str(venda["data_venda"])[:10] != dia:
        return False, "Somente o administrador pode cancelar vendas de outros dias."
    if usuario and venda["vendedor_id"] and int(venda["vendedor_id"]) != int(usuario["id"]):
        return False, "Você só pode cancelar as suas próprias vendas."
    return True, ""


def cancelar(banco: Banco, venda_id: int, motivo: str = "", autor=None, restaurar_estoque: bool = True) -> dict:
    """Cancela a venda: estoca de volta, cancela o fiado e estorna o que foi pago."""
    venda = pegar(banco, venda_id)
    if not venda:
        raise ErroVenda("Venda não encontrada.")
    ok, mensagem = pode_cancelar(venda, autor)
    if not ok:
        raise ErroVenda(mensagem or "Cancelamento não permitido.")
    if not str(motivo or "").strip():
        raise ErroVenda("Informe o motivo do cancelamento.")
    usuario_id, usuario_nome = _usuario_info(autor)
    linhas = itens(banco, venda_id)
    lista_pagamentos = pagamentos(banco, venda_id)
    movimentos_por_item: dict[int, list] = {}
    for m in banco.consultar(
        "SELECT * FROM movimentacoes WHERE documento_id=? AND motivo='venda' ORDER BY id DESC", (venda_id,)
    ):
        movimentos_por_item.setdefault(int(m["produto_id"]), []).append(m)
    reembolsos: list[dict] = []
    caixa_atual = caixa_mod.caixa_aberto(banco)

    with banco.transacao():
        if restaurar_estoque:
            for linha in linhas:
                quantidade = float(linha["quantidade_base"] or 0) - float(linha["quantidade_devolvida"] or 0)
                if quantidade <= 1e-9:
                    continue
                _devolver_por_lote(
                    banco, int(linha["produto_id"]), quantidade,
                    movimentos_por_item.get(int(linha["produto_id"]), []),
                    custo_unitario=int(linha["custo_unitario"] or 0),
                    documento_id=venda_id,
                    observacao=f"Cancelamento da venda nº {venda['numero']:06d}",
                    autor=autor,
                )
        # Cancela a conta a receber do fiado
        contas = banco.consultar("SELECT * FROM contas_receber WHERE venda_id=?", (venda_id,))
        for conta in contas:
            if conta["status"] != "cancelada":
                contas_receber.cancelar(
                    banco, int(conta["id"]), motivo=f"Venda nº {venda['numero']:06d} cancelada", autor=autor
                )
        # Estorna o que foi pago (exceto fiado, tratado acima)
        caixa_id = int(venda["caixa_id"]) if venda["caixa_id"] else (int(caixa_atual["id"]) if caixa_atual else None)
        for pg in lista_pagamentos:
            if pg["forma"] == FORMA_FIADO or int(pg["valor"] or 0) <= 0:
                continue
            reembolsos.append({"forma": pg["forma"], "valor": int(pg["valor"])})
            if caixa_id:
                caixa_mod.registrar_saida(
                    banco, "Devolução", f"Estorno da venda nº {venda['numero']:06d}",
                    int(pg["valor"]), pg["forma"], referencia=str(venda_id), autor=autor,
                    exigir_caixa=False, caixa_id=caixa_id,
                )
        banco.atualizar(
            "vendas",
            venda_id,
            {
                "status": "cancelada",
                "cancelada_motivo": str(motivo).strip(),
                "cancelada_em": agora_iso(),
            },
        )
    banco.registrar_log(
        "venda_cancelada",
        f"Cupom nº {venda['numero']:06d} — {formatar_dinheiro(int(venda['total'] or 0))} — motivo: {motivo}",
        usuario_id, usuario_nome,
    )
    return {
        "venda_id": venda_id,
        "numero": int(venda["numero"]),
        "reembolsos": reembolsos,
        "total_reembolso": sum(r["valor"] for r in reembolsos),
        "restaurou_estoque": restaurar_estoque,
    }


# --------------------------------------------------------------------------------------
# Devolução
# --------------------------------------------------------------------------------------


def pode_devolver(venda, usuario=None) -> tuple[bool, str]:
    if venda is None:
        return False, "Venda não encontrada."
    if venda["status"] == "cancelada":
        return False, "Venda cancelada não pode ser devolvida."
    if venda["status"] == "devolvida":
        return False, "Esta venda já foi totalmente devolvida."
    if usuario and not usuarios_mod.pode(usuario, "vendas_devolver"):
        return False, "Seu perfil não permite registrar devoluções."
    return True, ""


def itens_devoluveis(banco: Banco, venda_id: int) -> list[dict]:
    """Itens da venda com o quanto ainda pode ser devolvido."""
    resultado = []
    for linha in itens(banco, venda_id):
        restante = float(linha["quantidade_base"] or 0) - float(linha["quantidade_devolvida"] or 0)
        if restante <= 1e-9:
            continue
        preco_por_base = (
            int(linha["total_liquido"] or 0) / float(linha["quantidade_base"]) if float(linha["quantidade_base"] or 0) else 0
        )
        resultado.append(
            {
                "venda_item_id": int(linha["id"]),
                "produto_id": linha["produto_id"],
                "codigo": linha["codigo"],
                "nome": linha["nome"],
                "unidade": linha["unidade"],
                "unidade_base": linha["unidade_base"] or linha["unidade"],
                "quantidade_vendida": float(linha["quantidade"] or 0),
                "quantidade_base": float(linha["quantidade_base"] or 0),
                "quantidade_devolvida": float(linha["quantidade_devolvida"] or 0),
                "quantidade_disponivel": round(restante, 6),
                "total_liquido": int(linha["total_liquido"] or 0),
                "custo_unitario": int(linha["custo_unitario"] or 0),
                "valor_por_unidade_base": int(round(preco_por_base)),
            }
        )
    return resultado


def devolver(
    banco: Banco,
    venda_id: int,
    itens_para_devolver: Iterable[dict],
    motivo: str = "",
    tipo_reembolso: str = "dinheiro",
    autor=None,
    restaurar_estoque: bool = True,
) -> dict:
    """Registra uma devolução (total ou parcial) de uma venda.

    ``itens_para_devolver`` é uma lista de ``{'venda_item_id': int, 'quantidade_base': float}``
    (a quantidade sempre na **unidade de estoque**).

    ``tipo_reembolso``:

    * ``dinheiro`` — o valor volta ao caixa como saída;
    * ``credito``  — abate na conta a receber do fiado (ou gera crédito para o cliente);
    * ``nenhum``   — apenas a mercadoria volta ao estoque (troca/cortesia).
    """
    venda = pegar(banco, venda_id)
    if not venda:
        raise ErroVenda("Venda não encontrada.")
    ok, mensagem = pode_devolver(venda, autor)
    if not ok:
        raise ErroVenda(mensagem)
    if not str(motivo or "").strip():
        raise ErroVenda("Informe o motivo da devolução.")
    tipo = str(tipo_reembolso or "dinheiro").lower()
    if tipo not in ("dinheiro", "credito", "nenhum"):
        raise ErroVenda("Tipo de reembolso inválido (dinheiro, crédito ou nenhum).")

    disponiveis = {i["venda_item_id"]: i for i in itens_devoluveis(banco, venda_id)}
    if not disponiveis:
        raise ErroVenda("Não há itens disponíveis para devolução nesta venda.")
    normalizados: list[tuple[dict, float]] = []
    for bruto in itens_para_devolver or []:
        if isinstance(bruto, dict):
            item_id = int(bruto.get("venda_item_id") or 0)
            quantidade = float(bruto.get("quantidade_base") or 0)
        else:
            item_id = int(getattr(bruto, "venda_item_id", 0))
            quantidade = float(getattr(bruto, "quantidade_base", 0))
        if item_id not in disponiveis:
            raise ErroVenda(f"Item {item_id} não faz parte desta venda (ou já foi devolvido).")
        info = disponiveis[item_id]
        if quantidade <= 1e-9:
            continue
        if quantidade > info["quantidade_disponivel"] + 1e-9:
            raise ErroVenda(
                f"Quantidade devolvida de '{info['nome']}' ({formatar_quantidade(quantidade)}) "
                f"é maior que a disponível ({formatar_quantidade(info['quantidade_disponivel'])})."
            )
        normalizados.append((info, unidades.arredondar(quantidade)))
    if not normalizados:
        raise ErroVenda("Informe ao menos um item para devolver.")

    movimentos_venda = banco.consultar(
        "SELECT * FROM movimentacoes WHERE documento_id=? AND motivo='venda' ORDER BY id", (venda_id,)
    )
    movimentos_por_item: dict[int, list] = {}
    for m in movimentos_venda:
        movimentos_por_item.setdefault(int(m["produto_id"]), []).append(m)

    usuario_id, usuario_nome = _usuario_info(autor)
    caixa_atual = caixa_mod.caixa_aberto(banco)
    caixa_id = int(venda["caixa_id"]) if venda["caixa_id"] else (int(caixa_atual["id"]) if caixa_atual else None)

    with banco.transacao():
        devolucao_id = banco.inserir(
            "devolucoes",
            {
                "venda_id": venda_id,
                "valor": 0,
                "motivo": str(motivo).strip(),
                "tipo_reembolso": tipo,
                "usuario_id": usuario_id,
                "usuario_nome": usuario_nome,
                "criado_em": agora_iso(),
            },
        )
        valor_total = 0
        custo_total = 0
        for info, quantidade in normalizados:
            if quantidade <= 1e-9:
                continue
            proporcao = quantidade / info["quantidade_base"] if info["quantidade_base"] else 0.0
            valor_item = int(round(info["total_liquido"] * proporcao))
            custo_item = int(round(info["custo_unitario"] * quantidade))
            banco.inserir(
                "devolucao_itens",
                {
                    "devolucao_id": devolucao_id,
                    "venda_item_id": info["venda_item_id"],
                    "produto_id": info["produto_id"],
                    "quantidade_base": quantidade,
                    "valor": valor_item,
                },
            )
            banco.executar(
                "UPDATE venda_itens SET quantidade_devolvida = COALESCE(quantidade_devolvida,0) + ? WHERE id=?",
                (quantidade, info["venda_item_id"]),
            )
            valor_total += valor_item
            custo_total += custo_item
            if restaurar_estoque and info["produto_id"]:
                _devolver_por_lote(
                    banco, int(info["produto_id"]), quantidade,
                    movimentos_por_item.get(int(info["produto_id"]), []),
                    custo_unitario=int(info["custo_unitario"] or 0),
                    documento_id=venda_id,
                    observacao=f"Devolução da venda nº {venda['numero']:06d}",
                    autor=autor,
                )
        banco.atualizar("devolucoes", devolucao_id, {"valor": valor_total})

        # ------------------------------------------------------------------ reembolso
        conta = banco.consultar_uma(
            "SELECT * FROM contas_receber WHERE venda_id=? AND status<>'cancelada' ORDER BY id LIMIT 1", (venda_id,)
        )
        if tipo == "credito":
            if conta:
                novo_valor = max(0, int(conta["valor"] or 0) - valor_total)
                banco.atualizar(
                    "contas_receber",
                    int(conta["id"]),
                    {
                        "valor": novo_valor,
                        "descricao": f"{conta['descricao']} (devolução de {formatar_dinheiro(valor_total)})",
                        "atualizado_em": agora_iso(),
                    },
                )
                contas_receber.recalcular_status(banco, int(conta["id"]))
            elif valor_total > 0:
                raise ErroVenda(
                    "Não há conta de fiado aberta nesta venda para abater o crédito. "
                    "Use o reembolso em dinheiro (sai do caixa) ou 'nenhum'."
                )
        elif tipo == "dinheiro" and valor_total > 0:
            if caixa_id:
                caixa_mod.registrar_saida(
                    banco, "Devolução", f"Devolução da venda nº {venda['numero']:06d}",
                    valor_total, "Dinheiro", referencia=str(venda_id), autor=autor,
                    exigir_caixa=False, caixa_id=caixa_id,
                )
        # Ajusta o fiado quando o reembolso foi em dinheiro e existe conta aberta
        if tipo == "dinheiro" and conta and valor_total > 0:
            novo_valor = max(0, int(conta["valor"] or 0) - valor_total)
            if novo_valor != int(conta["valor"] or 0):
                banco.atualizar("contas_receber", int(conta["id"]), {"valor": novo_valor, "atualizado_em": agora_iso()})
                contas_receber.recalcular_status(banco, int(conta["id"]))

        # ------------------------------------------------------------------ status da venda
        restantes = [i for i in itens(banco, venda_id) if float(i["quantidade_base"] or 0) - float(i["quantidade_devolvida"] or 0) > 1e-9]
        novo_status = "parcialmente_devolvida" if restantes else "devolvida"
        banco.atualizar("vendas", venda_id, {"status": novo_status})

    banco.registrar_log(
        "venda_devolucao",
        f"Cupom nº {venda['numero']:06d} — devolvido {formatar_dinheiro(valor_total)} ({novo_status})",
        usuario_id, usuario_nome,
    )
    return {
        "devolucao_id": devolucao_id,
        "venda_id": venda_id,
        "numero": int(venda["numero"]),
        "valor": valor_total,
        "custo": custo_total,
        "tipo_reembolso": tipo,
        "status": novo_status,
        "itens": [(i["nome"], q) for i, q in normalizados],
    }


def devolver_venda_toda(banco: Banco, venda_id: int, motivo: str, tipo_reembolso: str = "dinheiro", autor=None) -> dict:
    """Atalho: devolve 100% dos itens de uma venda."""
    lista = [
        {"venda_item_id": i["venda_item_id"], "quantidade_base": i["quantidade_disponivel"]}
        for i in itens_devoluveis(banco, venda_id)
    ]
    return devolver(banco, venda_id, lista, motivo=motivo, tipo_reembolso=tipo_reembolso, autor=autor)


def devolucoes_da_venda(banco: Banco, venda_id: int) -> list:
    return banco.consultar(
        """SELECT d.*, (SELECT COUNT(*) FROM devolucao_itens di WHERE di.devolucao_id=d.id) AS qtd_itens
             FROM devolucoes d WHERE d.venda_id=? ORDER BY d.id DESC""",
        (venda_id,),
    )


def historico_devolucoes(banco: Banco, data_inicial: str = "", data_final: str = "", limite: int = 300) -> list:
    condicoes, params = [], []
    if data_inicial:
        condicoes.append("date(d.criado_em) >= date(?)")
        params.append(str(data_inicial)[:10])
    if data_final:
        condicoes.append("date(d.criado_em) <= date(?)")
        params.append(str(data_final)[:10])
    sql = """SELECT d.*, v.numero AS venda_numero, v.cliente_nome,
                    (SELECT COUNT(*) FROM devolucao_itens di WHERE di.devolucao_id=d.id) AS qtd_itens
               FROM devolucoes d JOIN vendas v ON v.id=d.venda_id"""
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY d.id DESC LIMIT ?"
    params.append(int(limite))
    return banco.consultar(sql, params)


# --------------------------------------------------------------------------------------
# Impressão / comprovante
# --------------------------------------------------------------------------------------


def dados_para_recibo(banco: Banco, venda_id: int) -> dict:
    """Monta tudo que o recibo não fiscal precisa (usado por :mod:`mrlog.impressao`)."""
    venda = pegar(banco, venda_id)
    if not venda:
        raise ErroVenda("Venda não encontrada.")
    config = banco.config_todas()
    cliente = clientes_mod.pegar(banco, venda["cliente_id"]) if venda["cliente_id"] else None
    linhas = []
    for i in itens(banco, venda_id):
        linhas.append(
            {
                "codigo": i["codigo"],
                "nome": i["nome"],
                "quantidade": formatar_quantidade(i["quantidade"]),
                "unidade": i["unidade"],
                "preco": int(i["preco_unitario"] or 0),
                "desconto": int(i["desconto"] or 0),
                "total": int(i["total_liquido"] or 0),
                "devolvido": float(i["quantidade_devolvida"] or 0),
            }
        )
    return {
        "empresa": {
            "nome": config.get("recibo_titulo") or config.get("empresa_nome") or "MR Logística",
            "documento": config.get("empresa_documento", ""),
            "endereco": config.get("empresa_endereco", "") if config.get("recibo_mostrar_endereco", "1") == "1" else "",
            "telefone": config.get("empresa_telefone", ""),
            "email": config.get("empresa_email", ""),
        },
        "mensagem": config.get("recibo_mensagem", ""),
        "numero": int(venda["numero"]),
        "data": venda["criada_em"],
        "vendedor": venda["vendedor_nome"] or "",
        "cliente": {
            "nome": venda["cliente_nome"] or "Consumidor final",
            "documento": (cliente["cpf_cnpj"] if cliente else "") or "",
            "endereco": (clientes_mod.endereco_completo(cliente) if cliente else "") or "",
            "telefone": (cliente["celular"] or cliente["telefone"] if cliente else "") or "",
        },
        "itens": linhas,
        "subtotal": int(venda["subtotal"] or 0),
        "desconto": int(venda["desconto"] or 0),
        "acrescimo": int(venda["acrescimo"] or 0),
        "total": int(venda["total"] or 0),
        "pagamentos": [
            {
                "forma": p["forma"],
                "valor": int(p["valor"] or 0),
                "recebido": int(p["recebido"] or 0),
                "parcelas": int(p["parcelas"] or 1),
                "operadora": p["operadora"] or "",
            }
            for p in pagamentos(banco, venda_id)
        ],
        "troco": int(venda["troco"] or 0),
        "fiado": int(venda["valor_fiado"] or 0),
        "status": venda["status"],
        "observacao": venda["observacao"] or "",
        "devolucoes": [
            {"data": d["criado_em"], "valor": int(d["valor"] or 0), "motivo": d["motivo"] or "", "tipo": d["tipo_reembolso"]}
            for d in devolucoes_da_venda(banco, venda_id)
        ],
        "cancelamento": {
            "motivo": venda["cancelada_motivo"] or "",
            "data": venda["cancelada_em"] or "",
        }
        if venda["status"] == "cancelada"
        else None,
        "itens_count": len(linhas),
        "emitido_em": agora(),
    }
