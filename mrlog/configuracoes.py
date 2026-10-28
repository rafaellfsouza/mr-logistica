"""
Configurações do sistema (tela "Configurações").

Tudo fica na tabela ``config`` do próprio banco — nada de arquivos soltos, nada de
registro do Windows. As chaves são validadas aqui para que a interface nunca grave
um valor inválido.
"""

from __future__ import annotations

from . import backup as backup_mod
from . import estoque as estoque_mod
from . import produtos as produtos_mod
from .banco import Banco
from .caminhos import caminho_banco, pasta_backups, pasta_dados, pasta_fotos
from .utils import agora_iso

TEMAS = ("claro", "escuro")

#: chaves booleanas (0/1)
CHAVES_BOOL = (
    "alerta_estoque_ativo",
    "backup_automatico",
    "venda_exige_caixa_aberto",
    "venda_permite_preco_zero",
    "venda_permite_estoque_negativo",
    "recibo_mostrar_endereco",
    "pdv_bipador_ativo",
    "pdv_confirmar_quantidade",
)

#: chaves numéricas inteiras com mínimo/máximo
CHAVES_INT = {
    "alerta_validade_dias": (1, 365),
    "manter_backups": (1, 200),
    "etiquetas_por_pagina": (1, 120),
}

#: chaves de texto livre
CHAVES_TEXTO = (
    "empresa_nome",
    "empresa_documento",
    "empresa_endereco",
    "empresa_telefone",
    "empresa_email",
    "recibo_titulo",
    "recibo_mensagem",
    "recibo_largura",
    "tema",
    "ultimo_usuario",
)

CHAVES_CONHECIDAS = set(CHAVES_BOOL) | set(CHAVES_INT) | set(CHAVES_TEXTO)


class ErroConfiguracao(Exception):
    """Valor inválido para uma configuração."""


def carregar(banco: Banco) -> dict:
    """Devolve todas as configurações com os tipos já convertidos."""
    bruto = banco.config_todas()
    resultado: dict = {}
    # chaves que nascem desligadas; todas as outras começam ativadas
    padroes_falsos = {"venda_permite_preco_zero", "venda_permite_estoque_negativo", "pdv_confirmar_quantidade"}
    for chave in CHAVES_BOOL:
        padrao = chave not in padroes_falsos
        resultado[chave] = banco.config_pegar_bool(chave, padrao) if chave in bruto else padrao
    for chave, (minimo, maximo) in CHAVES_INT.items():
        valor = banco.config_pegar_int(chave, minimo)
        resultado[chave] = min(max(valor, minimo), maximo)
    for chave in CHAVES_TEXTO:
        resultado[chave] = banco.config_pegar(chave, "")
    resultado["tema"] = resultado["tema"] if resultado["tema"] in TEMAS else "claro"
    return resultado


def salvar(banco: Banco, valores: dict, autor=None) -> dict:
    """Grava um conjunto de configurações, validando cada chave."""
    salvos = {}
    for chave, valor in (valores or {}).items():
        if chave not in CHAVES_CONHECIDAS:
            raise ErroConfiguracao(f"Configuração desconhecida: '{chave}'.")
        if chave in CHAVES_BOOL:
            gravado = "1" if valor in (True, 1, "1", "true", "True", "sim", "on") else "0"
        elif chave in CHAVES_INT:
            minimo, maximo = CHAVES_INT[chave]
            try:
                inteiro = int(float(str(valor).replace(",", ".")))
            except (TypeError, ValueError):
                raise ErroConfiguracao(f"Valor inválido para '{chave}': use um número inteiro.") from None
            if not minimo <= inteiro <= maximo:
                raise ErroConfiguracao(f"'{chave}' deve estar entre {minimo} e {maximo}.")
            gravado = str(inteiro)
        else:
            gravado = str(valor or "").strip()
            if chave == "tema" and gravado not in TEMAS:
                raise ErroConfiguracao("Tema inválido: use 'claro' ou 'escuro'.")
            if len(gravado) > 500:
                raise ErroConfiguracao(f"Texto muito longo para '{chave}' (máximo 500 caracteres).")
        banco.config_gravar(chave, gravado)
        salvos[chave] = gravado
    banco.registrar_log("configuracoes_alteradas", ", ".join(sorted(salvos)) or "(nada)", *_autor(autor))
    return salvos


def _autor(autor) -> tuple[int | None, str]:
    if not autor:
        return None, ""
    try:
        return int(autor["id"]), str(autor["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, str(autor)


def empresa(banco: Banco) -> dict:
    """Dados da empresa usados nos documentos impressos."""
    return {
        "nome": banco.config_pegar("empresa_nome", "MR Logística"),
        "documento": banco.config_pegar("empresa_documento", ""),
        "endereco": banco.config_pegar("empresa_endereco", ""),
        "telefone": banco.config_pegar("empresa_telefone", ""),
        "email": banco.config_pegar("empresa_email", ""),
    }


def informacoes_sistema(banco: Banco) -> dict:
    """Dados exibidos em Configurações > Sobre/Armazenamento."""
    from . import __version__

    tamanho = backup_mod.tamanho_banco_atual()
    fotos = list(pasta_fotos().glob("*")) if pasta_fotos().exists() else []
    return {
        "versao": __version__,
        "banco": str(caminho_banco()),
        "pasta_dados": str(pasta_dados()),
        "pasta_backups": str(pasta_backups()),
        "tamanho_banco": tamanho["legivel"],
        "tamanho_bytes": tamanho["total"],
        "qtd_fotos": len(fotos),
        "qtd_backups": len(backup_mod.listar()),
        "tabelas": len(banco.tabelas()),
        "versao_esquema": banco.versao_atual(),
        "integridade": banco.integridade(),
        "configuracoes": carregar(banco),
    }


def diagnostico(banco: Banco) -> list[str]:
    """Checklist de saúde do banco (executado pelo botão "Verificar dados")."""
    resultado = [
        f"Integridade do banco: {'OK' if banco.integridade()[0] else 'FALHOU — ' + str(banco.integridade()[1])}",
        f"Versão do esquema: {banco.versao_atual()}",
        f"Tamanho: {backup_mod.tamanho_banco_atual()['legivel']}",
    ]
    divergencias = estoque_mod.verificar_saldos(banco)
    resultado.append(
        "Saldos de estoque conferem com o histórico." if not divergencias
        else f"{len(divergencias)} produto(s) com saldo divergente — use 'Recalcular saldos'."
    )
    problemas = produtos_mod.validar_integridade(banco)
    resultado.extend(problemas[:20] if problemas else ["Cadastro de produtos sem inconsistências."])
    duplicados = produtos_mod.duplicados_por_nome(banco)
    resultado.append(
        "Nenhum produto com nome duplicado." if not duplicados
        else f"{len(duplicados)} nome(s) de produto duplicado(s) — vale revisar."
    )
    sem_codigo = banco.consultar_valor(
        "SELECT COUNT(*) FROM produtos WHERE ativo=1 AND (codigo_barras IS NULL OR codigo_barras='')"
    )
    resultado.append(f"{sem_codigo} produto(s) ativo(s) sem código de barras.")
    return resultado


def restaurar_padrao(banco: Banco, autor=None) -> dict:
    """Volta as configurações ao padrão de fábrica (não apaga dados de cadastro)."""
    from .esquema import CONFIG_PADRAO

    for chave, valor in CONFIG_PADRAO.items():
        if chave in CHAVES_CONHECIDAS:
            banco.config_gravar(chave, valor)
    banco.registrar_log("configuracoes_padrao", "Configurações restauradas", *_autor(autor))
    return carregar(banco)


def atalhos_de_teclado() -> list[dict]:
    """Lista de atalhos globais exibida na janela de ajuda (F1).

    Mantida aqui para que a tela de Configurações e o README mostrem sempre os
    mesmos atalhos que a aplicação realmente usa.
    """
    return [
        {"teclas": "F1", "acao": "Mostrar esta janela de atalhos"},
        {"teclas": "F2", "acao": "PDV — frente de caixa (venda rápida)"},
        {"teclas": "F3", "acao": "Vendas (histórico, cancelamento e devolução)"},
        {"teclas": "F4", "acao": "Caixa (abertura, sangria, suprimento, fechamento)"},
        {"teclas": "F5", "acao": "Produtos"},
        {"teclas": "F6", "acao": "Clientes"},
        {"teclas": "F7", "acao": "Estoque — movimentações"},
        {"teclas": "F8", "acao": "Contas a receber (fiado)"},
        {"teclas": "F9", "acao": "Contas a pagar"},
        {"teclas": "F10", "acao": "Relatórios"},
        {"teclas": "F11", "acao": "Etiquetas de código de barras"},
        {"teclas": "F12", "acao": "Configurações"},
        {"teclas": "Ctrl+B", "acao": "Foco no campo de busca (menu ou tabela da tela)"},
        {"teclas": "Ctrl+R", "acao": "Recarregar a tela atual"},
        {"teclas": "Ctrl+N", "acao": "Novo registro / nova venda no PDV"},
        {"teclas": "Ctrl+E", "acao": "Exportar a tabela exibida (Excel, PDF ou CSV)"},
        {"teclas": "Ctrl+P", "acao": "Imprimir (recibo, relatório ou etiquetas)"},
        {"teclas": "Ctrl+T", "acao": "Alternar tema claro/escuro"},
        {"teclas": "Ctrl+L", "acao": "Bloquear a tela (pede senha para voltar)"},
        {"teclas": "Ctrl+U", "acao": "Trocar de usuário"},
        {"teclas": "Esc", "acao": "Fechar janelas e diálogos / voltar o foco"},
        {"teclas": "Duplo clique", "acao": "Abre ou edita o registro selecionado na tabela"},
    ]


def pdv_atalhos() -> list[dict]:
    """Atalhos específicos da tela de venda (PDV)."""
    return [
        {"teclas": "Enter (no campo código)", "acao": "Bipar/adicionar produto"},
        {"teclas": "F2", "acao": "Buscar produto por nome"},
        {"teclas": "F3", "acao": "Alterar quantidade do item selecionado"},
        {"teclas": "F4", "acao": "Preço/unitário do item selecionado"},
        {"teclas": "F5", "acao": "Desconto no item selecionado"},
        {"teclas": "F6", "acao": "Desconto/acréscimo na venda"},
        {"teclas": "F7", "acao": "Identificar cliente"},
        {"teclas": "F8", "acao": "Excluir item selecionado"},
        {"teclas": "F9", "acao": "Limpar o carrinho"},
        {"teclas": "F10", "acao": "Suspende/retoma venda (venda em aberto)"},
        {"teclas": "F12", "acao": "Finalizar venda (pagamento)"},
        {"teclas": "Ctrl+P", "acao": "Imprimir recibo da última venda"},
        {"teclas": "+ / -", "acao": "Aumenta/diminui a quantidade do item"},
        {"teclas": "Esc", "acao": "Fecha diálogos / volta o foco para o código"},
    ]
