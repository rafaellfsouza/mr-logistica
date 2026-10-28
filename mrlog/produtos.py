"""
Cadastro de produtos — o coração do sistema.

Cada produto tem:

* **código interno** (SKU) e **código de barras** (lido pelo bipador);
* nome, descrição, categoria, marca e fornecedor;
* **unidade base** (como o estoque é controlado) e **unidade de venda** com fator
  de conversão (como é vendido);
* preço de custo, preço de venda e **margem de lucro** (calculada automaticamente
  nos dois sentidos);
* estoque atual, mínimo e máximo;
* controle opcional de **lote e validade**;
* foto opcional (copiada para a pasta de dados do sistema);
* peso, volume e dimensões (usados nas etiquetas e no cálculo de frete interno).

Regras importantes:

* O estoque **nunca** é digitado direto depois da implantação: qualquer alteração
  gera uma *movimentação* (entrada, saída ou ajuste), mantendo o histórico completo.
* Código interno e código de barras são **únicos** — o sistema bloqueia duplicados.
* O preço de custo é **média ponderada**: cada entrada de mercadoria recalcula o
  custo médio, como fazem Protheus e SAP B1.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import codigobarras, unidades
from .banco import Banco, ErroBanco
from .caminhos import pasta_fotos
from .utils import agora_iso, apenas_digitos, contem_sem_acento, normalizar, para_centavos


class ErroProduto(Exception):
    """Produto inválido, duplicado ou com operação bloqueada."""


# --------------------------------------------------------------------------------------
# Campos
# --------------------------------------------------------------------------------------

CAMPOS_TEXTO = (
    "codigo", "codigo_barras", "nome", "descricao", "marca", "localizacao", "observacao",
)
CAMPOS_NUMERICOS = (
    "preco_custo", "preco_venda", "estoque_minimo", "estoque_maximo",
    "peso_gramas", "volume_ml", "comprimento_mm", "largura_mm", "altura_mm",
)
CAMPOS_INTEIROS = ("categoria_id", "fornecedor_id", "validade_dias", "decimais")
CAMPOS_BOOLEANOS = ("permite_fracionar", "controla_lote", "ativo")

EXTENSOES_FOTO = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")


# --------------------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------------------

SQL_BASE = "SELECT * FROM vw_produtos_completo"


def listar(
    banco: Banco,
    filtro: str = "",
    categoria_id: int | None = None,
    fornecedor_id: int | None = None,
    incluir_inativos: bool = False,
    apenas_estoque_baixo: bool = False,
    apenas_sem_barras: bool = False,
    ordenar_por: str = "nome",
    descendente: bool = False,
    limite: int | None = None,
) -> list:
    """Lista produtos com busca e filtros combinados.

    ``filtro`` procura em código, código de barras, nome, descrição e marca —
    ignorando acentos e maiúsculas (a busca da tela aplica :func:`filtrar_local`).
    """
    colunas = {
        "nome": "nome COLLATE NOCASE",
        "codigo": "codigo COLLATE NOCASE",
        "estoque": "COALESCE(estoque_atual,0)",
        "preco": "preco_venda",
        "custo": "preco_custo",
        "margem": "margem_pct",
        "categoria": "categoria_nome COLLATE NOCASE",
        "fornecedor": "fornecedor_nome COLLATE NOCASE",
        "ultima_venda": "COALESCE(ultima_venda_em,'0')",
    }
    ordem = colunas.get(str(ordenar_por or "nome"), colunas["nome"])
    sql = SQL_BASE
    condicoes, params = [], []
    if not incluir_inativos:
        condicoes.append("ativo = 1")
    if categoria_id:
        condicoes.append("categoria_id = ?")
        params.append(int(categoria_id))
    if fornecedor_id:
        condicoes.append("fornecedor_id = ?")
        params.append(int(fornecedor_id))
    if apenas_estoque_baixo:
        condicoes.append("estoque_minimo > 0 AND COALESCE(estoque_atual,0) <= estoque_minimo")
    if apenas_sem_barras:
        condicoes.append("(codigo_barras IS NULL OR codigo_barras = '')")
    if filtro:
        f = f"%{filtro.strip()}%"
        condicoes.append("(codigo LIKE ? OR codigo_barras LIKE ? OR nome LIKE ? OR descricao LIKE ? OR marca LIKE ?)")
        params += [f] * 5
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += f" ORDER BY {ordem} {'DESC' if descendente else 'ASC'}"
    if limite:
        sql += " LIMIT ?"
        params.append(int(limite))
    return banco.consultar(sql, params)


def filtrar_local(produtos, filtro: str) -> list:
    """Filtro complementar em Python que ignora acentos e caixa alta/baixa."""
    if not filtro:
        return list(produtos)
    termo = normalizar(filtro)
    resultado = []
    for p in produtos:
        alvo = " ".join(
            normalizar(p[chave]) for chave in ("codigo", "codigo_barras", "nome", "descricao", "marca", "categoria_nome")
        )
        if termo in alvo:
            resultado.append(p)
    return resultado


def pegar(banco: Banco, produto_id):
    """Busca pela chave primária (com os campos calculados da visão)."""
    if not produto_id:
        return None
    return banco.consultar_uma(SQL_BASE + " WHERE id=?", (produto_id,))


def pegar_simples(banco: Banco, produto_id):
    return banco.consultar_uma("SELECT * FROM produtos WHERE id=?", (produto_id,))


def por_codigo(banco: Banco, codigo: str):
    """Busca exata pelo código interno."""
    c = str(codigo or "").strip()
    if not c:
        return None
    return banco.consultar_uma(SQL_BASE + " WHERE codigo = ? COLLATE NOCASE", (c,))


def por_codigo_barras(banco: Banco, codigo: str):
    """Busca exata pelo código de barras (é o que o bipador envia).

    Além da comparação direta, tenta variações comuns de leitura:
    sem caracteres não numéricos e sem zeros à esquerda (alguns bipadores e
    balanças enviam o código preenchido com zeros).
    """
    c = str(codigo or "").strip()
    if not c:
        return None
    linha = banco.consultar_uma(SQL_BASE + " WHERE codigo_barras = ?", (c,))
    if linha:
        return linha
    d = apenas_digitos(c)
    if d and d != c:
        linha = banco.consultar_uma(SQL_BASE + " WHERE codigo_barras = ?", (d,))
        if linha:
            return linha
    sem_zeros = d.lstrip("0")
    if sem_zeros and sem_zeros != d:
        linha = banco.consultar_uma(SQL_BASE + " WHERE codigo_barras = ?", (sem_zeros,))
        if linha:
            return linha
    return None


def resolver_bipagem(banco: Banco, codigo: str) -> tuple[Any | None, str]:
    """Interpreta o que o bipador (ou a digitação) enviou.

    Devolve ``(produto, tipo)`` onde ``tipo`` é:

    * ``'barras'`` — achou pelo código de barras;
    * ``'codigo'`` — achou pelo código interno;
    * ``'nome'``   — achou **um único** produto pelo nome (busca exata);
    * ``'nada'``   — não achou (a tela de venda abre o cadastro rápido).
    """
    bruto = codigobarras.normalizar_codigo_digitado(codigo)
    if not bruto:
        return None, "nada"
    produto = por_codigo_barras(banco, bruto)
    if produto:
        return produto, "barras"
    produto = por_codigo(banco, bruto)
    if produto:
        return produto, "codigo"
    alvo = normalizar(bruto)
    candidatos = banco.consultar(SQL_BASE + " WHERE ativo=1")
    unicos = [p for p in candidatos if normalizar(p["nome"]) == alvo]
    if len(unicos) == 1:
        return unicos[0], "nome"
    return None, "nada"


def buscar(banco: Banco, texto: str, limite: int = 50) -> list:
    """Busca aproximada usada na tela de venda (por nome, código ou barras)."""
    t = str(texto or "").strip()
    if not t:
        return []
    exato = por_codigo_barras(banco, t) or por_codigo(banco, t)
    if exato:
        return [exato]
    return [p for p in filtrar_local(listar(banco, limite=500), t)[:limite]]


def opcoes(banco: Banco) -> list[tuple[int, str]]:
    return [(l["id"], f"{l['codigo']} — {l['nome']}") for l in listar(banco)]


# --------------------------------------------------------------------------------------
# Código e código de barras
# --------------------------------------------------------------------------------------


def proximo_codigo(banco: Banco, prefixo: str = "") -> str:
    """Sugere o próximo código interno sequencial (ex.: ``P0001``, ``P0002``...)."""
    maior = 0
    for linha in banco.consultar("SELECT codigo FROM produtos"):
        c = str(linha["codigo"] or "")
        if prefixo and not c.upper().startswith(prefixo.upper()):
            continue
        digitos = apenas_digitos(c)
        if digitos:
            try:
                maior = max(maior, int(digitos))
            except ValueError:
                continue
    return f"{prefixo}{maior + 1:05d}"


def codigo_livre(banco: Banco, codigo: str) -> bool:
    return por_codigo(banco, codigo) is None


def codigo_barras_livre(banco: Banco, codigo: str, produto_id: int | None = None) -> bool:
    d = str(codigo or "").strip()
    if not d:
        return True
    linha = banco.consultar_uma(
        "SELECT id FROM produtos WHERE codigo_barras=? AND (? IS NULL OR id<>?)",
        (d, produto_id, produto_id),
    )
    return linha is None


def gerar_codigo_barras(banco: Banco, produto_id: int | None = None, prefixo: str = "200") -> str:
    """Gera um EAN-13 interno (faixa 2xx) que ainda não esteja em uso."""
    for _ in range(500):
        candidato = codigobarras.gerar_ean13(prefixo=prefixo)
        if codigo_barras_livre(banco, candidato, produto_id):
            return candidato
    raise ErroProduto("Não foi possível gerar um código de barras livre. Tente novamente.")


def definir_codigo_barras(banco: Banco, produto_id: int, codigo: str, autor=None) -> str:
    """Grava (ou corrige) o código de barras de um produto, validando o formato."""
    produto = pegar(banco, produto_id)
    if not produto:
        raise ErroProduto("Produto não encontrado.")
    c = str(codigo or "").strip()
    if not c:
        raise ErroProduto("Informe o código de barras ou clique em 'Gerar código interno'.")
    d = apenas_digitos(c)
    if d == c and len(d) in (8, 13):
        if not codigobarras.ean_valido(d):
            # corrige o dígito verificador quando o usuário digitou o número errado
            corrigido = codigobarras.completar_ean(d[:-1])
            raise ErroProduto(
                f"O dígito verificador de '{d}' está incorreto. O código válido seria '{corrigido}'."
            )
        c = d
    if not codigo_barras_livre(banco, c, produto_id):
        outro = por_codigo_barras(banco, c)
        raise ErroProduto(f"Este código de barras já pertence ao produto '{outro['nome'] if outro else c}'.")
    banco.atualizar("produtos", produto_id, {"codigo_barras": c, "atualizado_em": agora_iso()})
    banco.registrar_log("produto_barras", f"{produto['codigo']}: {c}", autor and autor["id"], autor and autor["nome"] or "")
    return c


def remover_codigo_barras(banco: Banco, produto_id: int, autor=None) -> None:
    produto = pegar(banco, produto_id)
    if not produto:
        raise ErroProduto("Produto não encontrado.")
    banco.atualizar("produtos", produto_id, {"codigo_barras": None, "atualizado_em": agora_iso()})
    banco.registrar_log("produto_barras_removido", produto["codigo"], autor and autor["id"], autor and autor["nome"] or "")


# --------------------------------------------------------------------------------------
# Preço / margem
# --------------------------------------------------------------------------------------


def preco_por_unidade_base(produto) -> int:
    """Preço de venda de **1 unidade base**, em centavos.

    O preço de venda é cadastrado por *unidade de venda*; para vender em outra
    unidade (ou fracionado) o sistema precisa do valor unitário da base.

    >>> preco_por_unidade_base({'preco_venda': 800, 'fator_venda': 6})
    133
    """
    try:
        preco = int(produto["preco_venda"] or 0)
        fator = float(produto["fator_venda"] or 1) or 1.0
    except (KeyError, IndexError, TypeError, ValueError):
        return 0
    if fator <= 0:
        return preco
    return int(round(preco / fator))


def custo_por_unidade_base(produto) -> int:
    """Custo médio de **1 unidade base**, em centavos (o custo já é gravado por base)."""
    try:
        return int(produto["preco_custo"] or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def calcular_margem(preco_custo_centavos: int, preco_venda_centavos: int) -> float:
    """Margem de lucro sobre o preço de venda, em %.

    >>> calcular_margem(1000, 1500)
    33.33
    """
    custo = int(preco_custo_centavos or 0)
    venda = int(preco_venda_centavos or 0)
    if venda <= 0:
        return 0.0
    return round((venda - custo) * 100.0 / venda, 2)


def preco_por_margem(preco_custo_centavos: int, margem_pct: float) -> int:
    """Preço de venda que produz a margem desejada sobre a venda.

    ``venda = custo / (1 - margem/100)``

    >>> preco_por_margem(1000, 50)
    2000
    """
    custo = int(preco_custo_centavos or 0)
    m = float(margem_pct or 0)
    if m >= 100:
        raise ErroProduto("A margem precisa ser menor que 100%.")
    if m <= -100:
        raise ErroProduto("Margem inválida.")
    if custo <= 0:
        return 0
    return int(round(custo / (1 - m / 100.0)))


def markup(preco_custo_centavos: int, preco_venda_centavos: int) -> float:
    """Markup sobre o custo (``venda/custo - 1``), em %."""
    custo = int(preco_custo_centavos or 0)
    if custo <= 0:
        return 0.0
    return round((int(preco_venda_centavos or 0) - custo) * 100.0 / custo, 2)


def aplicar_reajuste(banco: Banco, percentual: float, categoria_id: int | None = None, autor=None) -> int:
    """Reajusta o preço de venda de vários produtos de uma vez (ex.: +10%)."""
    if percentual == 0:
        raise ErroProduto("Informe um percentual diferente de zero.")
    if abs(percentual) > 900:
        raise ErroProduto("Percentual muito alto (máximo 900%).")
    condicao, params = "ativo=1", []
    if categoria_id:
        condicao += " AND categoria_id=?"
        params.append(int(categoria_id))
    linhas = banco.consultar(f"SELECT id, preco_venda FROM produtos WHERE {condicao}", params)
    fator = 1 + float(percentual) / 100.0
    with banco.transacao():
        for l in linhas:
            novo = int(round(float(l["preco_venda"] or 0) * fator))
            banco.atualizar("produtos", l["id"], {"preco_venda": max(0, novo), "atualizado_em": agora_iso()})
    banco.registrar_log(
        "reajuste_precos", f"{percentual:+.2f}% em {len(linhas)} produto(s)" + (f" (categoria {categoria_id})" if categoria_id else ""),
        autor and autor["id"], autor and autor["nome"] or "",
    )
    return len(linhas)


def aplicar_margem_padrao(banco: Banco, margem_pct: float, categoria_id: int | None = None, autor=None) -> int:
    """Recalcula o preço de venda a partir do custo médio e de uma margem alvo."""
    if margem_pct >= 100:
        raise ErroProduto("A margem precisa ser menor que 100%.")
    condicao, params = "ativo=1 AND preco_custo>0", []
    if categoria_id:
        condicao += " AND categoria_id=?"
        params.append(int(categoria_id))
    linhas = banco.consultar(f"SELECT id, preco_custo FROM produtos WHERE {condicao}", params)
    with banco.transacao():
        for l in linhas:
            banco.atualizar(
                "produtos",
                l["id"],
                {"preco_venda": preco_por_margem(int(l["preco_custo"] or 0), margem_pct), "atualizado_em": agora_iso()},
            )
    banco.registrar_log("margem_aplicada", f"{margem_pct:.2f}% em {len(linhas)} produto(s)", autor and autor["id"], autor and autor["nome"] or "")
    return len(linhas)


# --------------------------------------------------------------------------------------
# Validação e gravação
# --------------------------------------------------------------------------------------


def _numero(valor, campo: str, minimo: float = 0.0, casas: int = 4):
    if valor in (None, ""):
        return 0.0 if casas else 0
    try:
        v = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ErroProduto(f"Valor inválido no campo {campo}: '{valor}'.") from None
    if v < minimo:
        raise ErroProduto(f"{campo} não pode ser menor que {minimo}.")
    return round(v, casas) if casas else int(round(v))


def _validar(banco: Banco, dados: dict, produto_id: int | None = None) -> dict:
    registro: dict[str, Any] = {}

    nome = str(dados.get("nome") or "").strip()
    if not nome:
        raise ErroProduto("Informe o nome do produto.")
    if len(nome) < 2:
        raise ErroProduto("Nome do produto muito curto.")
    if len(nome) > 120:
        raise ErroProduto("Nome muito longo (máximo 120 caracteres).")
    registro["nome"] = nome

    codigo = str(dados.get("codigo") or "").strip()
    if not codigo:
        codigo = proximo_codigo(banco, str(dados.get("prefixo_codigo") or ""))
    if len(codigo) > 40:
        raise ErroProduto("Código interno muito longo (máximo 40 caracteres).")
    existente = por_codigo(banco, codigo)
    if existente and (produto_id is None or int(existente["id"]) != int(produto_id)):
        raise ErroProduto(f"O código interno '{codigo}' já está em uso pelo produto '{existente['nome']}'.")
    registro["codigo"] = codigo

    barras = str(dados.get("codigo_barras") or "").strip()
    if barras:
        d = apenas_digitos(barras)
        if d == barras and len(d) in (8, 13):
            if not codigobarras.ean_valido(d):
                corrigido = codigobarras.completar_ean(d[:-1])
                raise ErroProduto(
                    f"Código de barras '{d}' com dígito verificador incorreto. O valor válido seria '{corrigido}'."
                )
            barras = d
        if len(barras) > 48:
            raise ErroProduto("Código de barras muito longo.")
        if not codigo_barras_livre(banco, barras, produto_id):
            outro = por_codigo_barras(banco, barras)
            raise ErroProduto(
                f"O código de barras '{barras}' já está cadastrado no produto "
                f"'{outro['codigo']} — {outro['nome']}'."
            )
    registro["codigo_barras"] = barras or None

    for campo in ("descricao", "marca", "localizacao", "observacao"):
        registro[campo] = str(dados.get(campo) or "").strip()

    # Vínculos
    for campo in ("categoria_id", "fornecedor_id"):
        valor = dados.get(campo)
        if valor in (None, "", 0, "0"):
            registro[campo] = None
        else:
            try:
                registro[campo] = int(valor)
            except (TypeError, ValueError):
                raise ErroProduto(f"Valor inválido para {campo}.") from None
    if registro["categoria_id"]:
        if not banco.consultar_valor("SELECT id FROM categorias WHERE id=?", (registro["categoria_id"],)):
            raise ErroProduto("Categoria não encontrada.")
    if registro["fornecedor_id"]:
        if not banco.consultar_valor("SELECT id FROM fornecedores WHERE id=?", (registro["fornecedor_id"],)):
            raise ErroProduto("Fornecedor não encontrado.")

    # Unidades
    unidade_base = str(dados.get("unidade_base") or "un").strip().lower()
    unidade_venda = str(dados.get("unidade_venda") or unidade_base).strip().lower()
    if not unidades.existe(unidade_base, banco):
        raise ErroProduto(f"Unidade de estoque desconhecida: '{unidade_base}'.")
    if not unidades.existe(unidade_venda, banco):
        raise ErroProduto(f"Unidade de venda desconhecida: '{unidade_venda}'.")
    if unidade_base != unidade_venda and not unidades.mesma_familia(unidade_base, unidade_venda, banco):
        raise ErroProduto(
            f"A unidade de venda '{unidade_venda}' e a unidade de estoque '{unidade_base}' "
            f"precisam pertencer à mesma família (quantidade, peso, volume ou comprimento)."
        )
    registro["unidade_base"] = unidade_base
    registro["unidade_venda"] = unidade_venda

    fator = _numero(dados.get("fator_venda", 1), "Fator da unidade de venda", minimo=0.0, casas=6)
    if fator <= 0:
        fator = 1.0
    if unidade_base == unidade_venda and abs(fator - 1.0) > 1e-9:
        # mesma unidade => fator sempre 1 (evita conversões sem sentido)
        fator = 1.0
    if unidade_venda in ("dz", "par") and unidades.familia_de(unidade_base, banco) == unidades.FAMILIA_QUANTIDADE:
        # dúzia/par têm fator universal
        fator = unidades.FATORES_UNIVERSAIS.get(unidade_venda, fator)
    if unidade_venda in unidades.FATORES_POR_PRODUTO and fator == 1.0 and unidade_base != unidade_venda:
        raise ErroProduto(
            f"Informe quantas '{unidade_base}' existem em 1 '{unidade_venda}' (campo Fator da unidade de venda)."
        )
    registro["fator_venda"] = fator

    registro["permite_fracionar"] = 1 if dados.get("permite_fracionar", 1) else 0
    registro["decimais"] = int(_numero(dados.get("decimais", 0), "Casas decimais", minimo=0, casas=0) or 0)
    if not 0 <= registro["decimais"] <= 4:
        raise ErroProduto("As casas decimais devem estar entre 0 e 4.")
    if not registro["permite_fracionar"] and registro["decimais"] > 0:
        registro["decimais"] = 0

    # Preços
    custo = para_centavos(dados.get("preco_custo", 0))
    venda = para_centavos(dados.get("preco_venda", 0))
    if custo < 0 or venda < 0:
        raise ErroProduto("Preços não podem ser negativos.")
    if venda == 0 and custo > 0 and dados.get("margem_desejada") not in (None, "", 0, "0"):
        try:
            venda = preco_por_margem(custo, float(str(dados.get("margem_desejada")).replace(",", ".")))
        except (TypeError, ValueError):
            raise ErroProduto("Margem desejada inválida.") from None
    if venda == 0 and custo > 0:
        raise ErroProduto(
            "O preço de venda não pode ser zero quando há preço de custo. "
            "Informe o preço ou a margem desejada (produtos de cortesia devem ter custo zero)."
        )
    # Observação: vender abaixo do custo é permitido (liquidação, queima de estoque),
    # mas fica registrado no log para o gestor acompanhar.
    if venda > 0 and venda < custo:
        dados.setdefault("_aviso_abaixo_custo", True)
    registro["preco_custo"] = custo
    registro["preco_venda"] = venda

    # Estoques
    registro["estoque_minimo"] = _numero(dados.get("estoque_minimo", 0), "Estoque mínimo", minimo=0.0)
    registro["estoque_maximo"] = _numero(dados.get("estoque_maximo", 0), "Estoque máximo", minimo=0.0)
    if registro["estoque_maximo"] and registro["estoque_minimo"] > registro["estoque_maximo"]:
        raise ErroProduto("O estoque mínimo não pode ser maior que o estoque máximo.")

    # Medidas físicas
    registro["peso_gramas"] = _numero(dados.get("peso_gramas", 0), "Peso", minimo=0.0) or None
    registro["volume_ml"] = _numero(dados.get("volume_ml", 0), "Volume", minimo=0.0) or None
    registro["comprimento_mm"] = _numero(dados.get("comprimento_mm", 0), "Comprimento", minimo=0.0) or None
    registro["largura_mm"] = _numero(dados.get("largura_mm", 0), "Largura", minimo=0.0) or None
    registro["altura_mm"] = _numero(dados.get("altura_mm", 0), "Altura", minimo=0.0) or None

    # Lote / validade
    registro["controla_lote"] = 1 if dados.get("controla_lote", 0) else 0
    validade_dias = dados.get("validade_dias")
    if validade_dias in (None, ""):
        registro["validade_dias"] = None
    else:
        try:
            registro["validade_dias"] = int(validade_dias)
        except (TypeError, ValueError):
            raise ErroProduto("Validade padrão deve ser um número de dias.") from None
        if registro["validade_dias"] < 0:
            raise ErroProduto("Validade padrão não pode ser negativa.")
    # A validade padrão é opcional: pode ser informada lote a lote na entrada.

    registro["ativo"] = 1 if dados.get("ativo", 1) else 0
    return registro


def criar(banco: Banco, dados: dict, estoque_inicial: float = 0.0, foto=None, autor=None) -> int:
    """Cadastra o produto. ``estoque_inicial`` gera uma movimentação de inventário inicial."""
    registro = _validar(banco, dados)
    registro["estoque_atual"] = 0.0
    registro["criado_em"] = agora_iso()
    registro["atualizado_em"] = agora_iso()
    with banco.transacao():
        produto_id = banco.inserir("produtos", registro)
        if foto:
            gravar_foto(banco, produto_id, foto, registro["codigo"])
        qtd = float(estoque_inicial or 0)
        if abs(qtd) > 1e-9:
            from . import estoque as estoque_mod

            if qtd > 0:
                estoque_mod.entrada(
                    banco,
                    produto_id,
                    qtd,
                    motivo="inventario_inicial",
                    custo_unitario=int(registro["preco_custo"] or 0),
                    observacao="Saldo inicial informado no cadastro",
                    autor=autor,
                )
            else:
                estoque_mod.ajuste(
                    banco,
                    produto_id,
                    qtd,
                    motivo="inventario_inicial",
                    observacao="Saldo inicial negativo informado no cadastro",
                    autor=autor,
                )
    banco.registrar_log(
        "produto_criado", f"{registro['codigo']} — {registro['nome']}",
        autor and autor["id"], autor and autor["nome"] or "",
    )
    return produto_id


def atualizar(banco: Banco, produto_id: int, dados: dict, foto=None, autor=None) -> int:
    """Altera o produto. O estoque **não** é alterado aqui — use as movimentações."""
    atual = pegar(banco, produto_id)
    if not atual:
        raise ErroProduto("Produto não encontrado.")
    base = {c: atual[c] for c in atual.keys()}
    mesclado = {**base, **{k: v for k, v in dados.items() if k not in ("estoque_atual", "id")}}
    mesclado["ativo"] = dados.get("ativo", atual["ativo"])
    registro = _validar(banco, mesclado, produto_id)

    # Bloqueios de integridade quando o produto já tem histórico
    if registro["unidade_base"] != atual["unidade_base"]:
        movs = banco.consultar_valor("SELECT COUNT(*) FROM movimentacoes WHERE produto_id=?", (produto_id,)) or 0
        vendas = banco.consultar_valor("SELECT COUNT(*) FROM venda_itens WHERE produto_id=?", (produto_id,)) or 0
        if movs or vendas:
            raise ErroProduto(
                "Não é possível trocar a unidade de estoque de um produto que já tem "
                "movimentações ou vendas: os saldos ficariam incoerentes. "
                "Desative este produto e cadastre um novo com a unidade correta."
            )
    if registro["controla_lote"] and not atual["controla_lote"]:
        saldo = float(atual["estoque_atual"] or 0)
        if saldo > 1e-9:
            raise ErroProduto(
                "Para ativar o controle de lote com saldo em estoque, primeiro zere o estoque "
                "(ajuste de inventário) e depois informe os lotes na entrada."
            )
    registro["atualizado_em"] = agora_iso()
    with banco.transacao():
        banco.atualizar("produtos", produto_id, registro)
        if foto:
            gravar_foto(banco, produto_id, foto, registro["codigo"])
        elif "foto" in dados and not dados.get("foto"):
            remover_foto(banco, produto_id)
    banco.registrar_log("produto_alterado", f"{registro['codigo']} — {registro['nome']}", autor and autor["id"], autor and autor["nome"] or "")
    return produto_id


def desativar(banco: Banco, produto_id: int, autor=None) -> None:
    produto = pegar(banco, produto_id)
    if not produto:
        raise ErroProduto("Produto não encontrado.")
    banco.atualizar("produtos", produto_id, {"ativo": 0, "atualizado_em": agora_iso()})
    banco.registrar_log("produto_desativado", produto["codigo"], autor and autor["id"], autor and autor["nome"] or "")


def reativar(banco: Banco, produto_id: int, autor=None) -> None:
    produto = pegar(banco, produto_id)
    if not produto:
        raise ErroProduto("Produto não encontrado.")
    banco.atualizar("produtos", produto_id, {"ativo": 1, "atualizado_em": agora_iso()})
    banco.registrar_log("produto_reativado", produto["codigo"], autor and autor["id"], autor and autor["nome"] or "")


def excluir(banco: Banco, produto_id: int, autor=None) -> None:
    """Exclusão definitiva — só permitida sem histórico (vendas/movimentações/contas)."""
    produto = pegar(banco, produto_id)
    if not produto:
        raise ErroProduto("Produto não encontrado.")
    vendas = banco.consultar_valor("SELECT COUNT(*) FROM venda_itens WHERE produto_id=?", (produto_id,)) or 0
    if vendas:
        raise ErroProduto(
            f"Este produto já foi vendido {vendas} vez(es). Para preservar o histórico das vendas, "
            "use 'Desativar' em vez de excluir."
        )
    with banco.transacao():
        banco.executar("DELETE FROM devolucao_itens WHERE produto_id=?", (produto_id,))
        banco.executar("DELETE FROM lotes WHERE produto_id=?", (produto_id,))
        banco.executar("DELETE FROM movimentacoes WHERE produto_id=?", (produto_id,))
        remover_foto(banco, produto_id)
        banco.excluir("produtos", produto_id)
    banco.registrar_log("produto_excluido", f"{produto['codigo']} — {produto['nome']}", autor and autor["id"], autor and autor["nome"] or "")


# --------------------------------------------------------------------------------------
# Foto
# --------------------------------------------------------------------------------------


def gravar_foto(banco: Banco, produto_id: int, origem, codigo: str = "") -> str | None:
    """Copia a imagem (caminho ou bytes) para a pasta de dados e grava o nome no produto.

    Aceita ``str``/``Path`` (arquivo existente) ou ``bytes`` (imagem já em memória,
    ex.: capturada da webcam ou colada da área de transferência).
    """
    destino_dir = pasta_fotos()
    sufixo = str(produto_id).zfill(6)
    caminho_final: Path | None = None
    try:
        if isinstance(origem, (bytes, bytearray)):
            caminho_final = destino_dir / f"produto_{sufixo}.png"
            with open(caminho_final, "wb") as arq:
                arq.write(bytes(origem))
        else:
            origem_path = Path(str(origem)).expanduser()
            if not origem_path.exists():
                raise ErroProduto(f"Arquivo de imagem não encontrado: {origem}")
            ext = origem_path.suffix.lower()
            if ext not in EXTENSOES_FOTO:
                raise ErroProduto(
                    f"Formato de imagem não suportado: '{ext}'. Use JPG, PNG, GIF, BMP ou WEBP."
                )
            if origem_path.stat().st_size > 8 * 1024 * 1024:
                raise ErroProduto("A imagem é muito grande (máximo 8 MB).")
            caminho_final = destino_dir / f"produto_{sufixo}{ext}"
            if origem_path.resolve() != caminho_final.resolve():
                shutil.copyfile(origem_path, caminho_final)
    except OSError as exc:
        raise ErroProduto(f"Não foi possível salvar a foto: {exc}") from exc

    # Remove a foto anterior, se existia com outra extensão
    for ext in EXTENSOES_FOTO:
        antigo = destino_dir / f"produto_{sufixo}{ext}"
        if antigo.exists() and caminho_final and antigo.resolve() != caminho_final.resolve():
            try:
                antigo.unlink()
            except OSError:
                pass
    nome_arquivo = caminho_final.name if caminho_final else None
    banco.atualizar("produtos", produto_id, {"foto": nome_arquivo, "atualizado_em": agora_iso()})
    return nome_arquivo


def remover_foto(banco: Banco, produto_id: int) -> None:
    sufixo = str(produto_id).zfill(6)
    for ext in EXTENSOES_FOTO:
        arquivo = pasta_fotos() / f"produto_{sufixo}{ext}"
        if arquivo.exists():
            try:
                arquivo.unlink()
            except OSError:
                pass
    banco.atualizar("produtos", produto_id, {"foto": None})


def caminho_foto(produto) -> Path | None:
    """Caminho absoluto da foto do produto (ou ``None``)."""
    if not produto or not produto["foto"]:
        return None
    p = pasta_fotos() / str(produto["foto"])
    return p if p.exists() else None


# --------------------------------------------------------------------------------------
# Custo médio
# --------------------------------------------------------------------------------------


def recalcular_custo_medio(
    banco: Banco,
    produto_id: int,
    qtd_entrada: float,
    custo_entrada_centavos: int,
    saldo_antes: float | None = None,
    custo_antes: int | None = None,
) -> int:
    """Atualiza o custo médio ponderado após uma entrada de mercadoria.

    ``novo_custo = (saldo_antes * custo_antes + qtd * custo_entrada) / (saldo_antes + qtd)``

    .. important::
       ``saldo_antes``/``custo_antes`` devem ser os valores **anteriores** à entrada.
       Se omitidos, o saldo é lido do banco — o que só é correto quando a função é
       chamada *antes* de a movimentação ser gravada.
    """
    produto = pegar_simples(banco, produto_id)
    if not produto:
        raise ErroProduto("Produto não encontrado.")
    saldo_atual = float(produto["estoque_atual"] or 0) if saldo_antes is None else float(saldo_antes)
    custo_atual = int(produto["preco_custo"] or 0) if custo_antes is None else int(custo_antes)
    qtd = float(qtd_entrada or 0)
    if qtd <= 0:
        return custo_atual
    novo_saldo = saldo_atual + qtd
    if novo_saldo <= 0:
        return int(custo_entrada_centavos or 0)
    novo_custo = int(round((saldo_atual * custo_atual + qtd * int(custo_entrada_centavos or 0)) / novo_saldo))
    banco.atualizar("produtos", produto_id, {"preco_custo": max(0, novo_custo), "atualizado_em": agora_iso()})
    return max(0, novo_custo)


# --------------------------------------------------------------------------------------
# Indicadores
# --------------------------------------------------------------------------------------


def estoque_baixo(banco: Banco, limite: int = 100) -> list:
    """Produtos ativos com saldo igual ou abaixo do estoque mínimo."""
    return banco.consultar("SELECT * FROM vw_estoque_baixo ORDER BY nome LIMIT ?", (int(limite),))


def sem_movimento(banco: Banco, dias: int = 60, limite: int = 100) -> list:
    """Produtos com estoque parado (sem venda) há mais de ``dias`` dias."""
    from .utils import somar_dias, hoje

    corte = somar_dias(hoje(), -abs(int(dias)))
    return banco.consultar(
        """SELECT * FROM vw_produtos_completo
            WHERE ativo = 1 AND COALESCE(estoque_atual,0) > 0
              AND (ultima_venda_em IS NULL OR ultima_venda_em < ?)
            ORDER BY ultima_venda_em IS NOT NULL, ultima_venda_em LIMIT ?""",
        (corte, int(limite)),
    )


def resumo(banco: Banco) -> dict:
    """Totais usados no painel de indicadores."""
    linha = banco.consultar_uma(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN ativo=1 THEN 1 ELSE 0 END),0) AS ativos,
                  COALESCE(SUM(CASE WHEN ativo=1 THEN estoque_custo ELSE 0 END),0) AS valor_custo,
                  COALESCE(SUM(CASE WHEN ativo=1 THEN estoque_venda ELSE 0 END),0) AS valor_venda,
                  (SELECT COUNT(*) FROM vw_estoque_baixo) AS estoque_baixo,
                  (SELECT COUNT(*) FROM produtos WHERE ativo=1 AND (codigo_barras IS NULL OR codigo_barras='')) AS sem_barras,
                  (SELECT COUNT(*) FROM vw_lotes_validade WHERE dias_para_vencer <= 0) AS vencidos,
                  (SELECT COUNT(*) FROM vw_lotes_validade WHERE dias_para_vencer BETWEEN 1 AND 30) AS a_vencer
             FROM vw_produtos_completo"""
    )
    return {
        "total": int(linha["total"] or 0),
        "ativos": int(linha["ativos"] or 0),
        "valor_custo": int(linha["valor_custo"] or 0),
        "valor_venda": int(linha["valor_venda"] or 0),
        "estoque_baixo": int(linha["estoque_baixo"] or 0),
        "sem_barras": int(linha["sem_barras"] or 0),
        "lotes_vencidos": int(linha["vencidos"] or 0),
        "lotes_a_vencer": int(linha["a_vencer"] or 0),
    }


def categorias_em_uso(banco: Banco) -> list:
    return banco.consultar(
        """SELECT c.id, c.nome, COUNT(p.id) AS qtd
             FROM categorias c LEFT JOIN produtos p ON p.categoria_id=c.id AND p.ativo=1
            WHERE c.ativo=1 GROUP BY c.id ORDER BY c.nome"""
    )


def duplicados_por_nome(banco: Banco) -> list:
    """Aponta produtos com o mesmo nome — útil para limpar cadastros duplicados."""
    return banco.consultar(
        """SELECT LOWER(nome) AS nome_norm, COUNT(*) AS qtd, GROUP_CONCAT(codigo, ' | ') AS codigos
             FROM produtos WHERE ativo=1 GROUP BY LOWER(nome) HAVING COUNT(*) > 1 ORDER BY qtd DESC"""
    )


def validar_integridade(banco: Banco) -> list[str]:
    """Verificações rápidas de consistência do cadastro (usadas na tela de Configurações)."""
    problemas: list[str] = []
    for prod in banco.consultar("SELECT * FROM produtos"):
        if not prod["codigo"]:
            problemas.append(f"Produto #{prod['id']} sem código interno.")
        if not prod["nome"]:
            problemas.append(f"Produto #{prod['id']} sem nome.")
        try:
            unidades.pegar(prod["unidade_base"], banco)
        except unidades.ErroUnidade:
            problemas.append(f"Produto '{prod['nome']}': unidade de estoque inválida ('{prod['unidade_base']}').")
        try:
            if prod["unidade_venda"]:
                unidades.fator_para_base_produto(prod, prod["unidade_venda"], banco)
        except unidades.ErroUnidade as exc:
            problemas.append(f"Produto '{prod['nome']}': {exc}")
        if int(prod["preco_venda"] or 0) < 0 or int(prod["preco_custo"] or 0) < 0:
            problemas.append(f"Produto '{prod['nome']}': preço negativo.")
        if float(prod["estoque_minimo"] or 0) < 0:
            problemas.append(f"Produto '{prod['nome']}': estoque mínimo negativo.")
    vistos_codigo, vistos_barras = {}, {}
    for prod in banco.consultar("SELECT codigo, codigo_barras, nome FROM produtos"):
        c = normalizar(prod["codigo"])
        if c and c in vistos_codigo:
            problemas.append(f"Código interno duplicado: '{prod['codigo']}' ({vistos_codigo[c]} / {prod['nome']}).")
        vistos_codigo[c] = prod["nome"]
        b = str(prod["codigo_barras"] or "").strip()
        if b:
            if b in vistos_barras:
                problemas.append(f"Código de barras duplicado: '{b}' ({vistos_barras[b]} / {prod['nome']}).")
            vistos_barras[b] = prod["nome"]
            if len(apenas_digitos(b)) in (8, 13) and apenas_digitos(b) == b and not codigobarras.ean_valido(b):
                problemas.append(f"Código de barras com dígito verificador inválido: '{b}' ({prod['nome']}).")
    return problemas


def preco_abaixo_do_custo(produto) -> bool:
    """Indica se o preço de venda está abaixo do custo médio (alerta na tela)."""
    try:
        return 0 < int(produto["preco_venda"] or 0) < int(produto["preco_custo"] or 0)
    except (TypeError, ValueError, KeyError, IndexError):
        return False


def texto_busca(produto) -> str:
    """Concatena os campos pesquisáveis de um produto (usado no filtro sem acento)."""
    return " ".join(
        normalizar(produto[chave] if chave in produto.keys() else "")
        for chave in ("codigo", "codigo_barras", "nome", "descricao", "marca")
    )


def contem_acento(texto: str, produto) -> bool:
    """Auxiliar de busca sem acento exposto para as telas."""
    return contem_sem_acento(produto["nome"], texto)
