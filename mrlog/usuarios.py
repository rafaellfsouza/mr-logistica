"""
Usuários, autenticação e permissões.

* Senhas são guardadas como **hash PBKDF2-SHA256 com salt** (120.000 iterações) —
  nunca em texto puro, nem mesmo no banco local.
* Três perfis prontos: ``administrador``, ``gerente`` e ``vendedor``, cada um com um
  conjunto de permissões. As telas consultam :func:`pode` antes de mostrar/permitir
  qualquer ação sensível.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Iterable

from .banco import Banco
from .utils import agora, agora_iso

# --------------------------------------------------------------------------------------
# Senha
# --------------------------------------------------------------------------------------

_ALGORITMO = "pbkdf2_sha256"
_ITERACOES = 120_000


def criar_hash_senha(senha: str) -> str:
    """Gera o hash armazenável da senha (formato ``algoritmo$iterações$salt$hash``)."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, _ITERACOES)
    return f"{_ALGORITMO}${_ITERACOES}${salt.hex()}${dk.hex()}"


def verificar_senha(senha: str, armazenado: str) -> bool:
    """Compara a senha digitada com o hash guardado (tempo constante)."""
    try:
        algoritmo, iteracoes, salt, esperado = str(armazenado).split("$")
        if algoritmo != _ALGORITMO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(salt), int(iteracoes))
        return hmac.compare_digest(dk.hex(), esperado)
    except (ValueError, TypeError):
        return False


def senha_forte(senha: str) -> tuple[bool, str]:
    """Exige no mínimo 4 caracteres (o sistema é local, mas evita senha em branco)."""
    s = str(senha or "")
    if len(s) < 4:
        return False, "A senha precisa ter pelo menos 4 caracteres."
    if s.strip() != s:
        return False, "A senha não pode começar ou terminar com espaço."
    return True, ""


# --------------------------------------------------------------------------------------
# Permissões
# --------------------------------------------------------------------------------------

PERFIS = ("administrador", "gerente", "vendedor")

ROTULOS_PERFIS = {
    "administrador": "Administrador",
    "gerente": "Gerente",
    "vendedor": "Vendedor",
}

DESCRICAO_PERFIS = {
    "administrador": "Acesso total: cadastros, estoque, financeiro, relatórios, usuários e configurações.",
    "gerente": "Gestão de cadastros, estoque, financeiro e relatórios. Não altera usuários nem configurações do sistema.",
    "vendedor": "Opera o PDV, consulta produtos/estoque, atende clientes e consulta as próprias vendas.",
}

#: Todas as chaves de permissão conhecidas (a interface usa exatamente estas).
PERMISSOES = (
    "painel",
    "pdv",
    "vendas",
    "vendas_cancelar",
    "vendas_devolver",
    "produtos",
    "produtos_editar",
    "produtos_excluir",
    "produtos_preco_editar",
    "categorias",
    "clientes",
    "clientes_editar",
    "fornecedores",
    "fornecedores_editar",
    "estoque",
    "estoque_movimentar",
    "financeiro",
    "contas_receber",
    "contas_pagar",
    "caixa",
    "relatorios",
    "relatorios_financeiros",
    "etiquetas",
    "usuarios",
    "configuracoes",
    "backup",
    "logs",
    "desconto_max_pct",  # especial: valor numérico (limite de desconto em %)
)

_PERMISSOES_TOTAL = frozenset(p for p in PERMISSOES if p != "desconto_max_pct")

MATRIZ_PERMISSOES: dict[str, frozenset[str]] = {
    "administrador": _PERMISSOES_TOTAL,
    "gerente": _PERMISSOES_TOTAL - {"usuarios", "configuracoes", "backup", "logs"},
    "vendedor": frozenset(
        {
            "painel",
            "pdv",
            "vendas",
            "produtos",
            "clientes",
            "clientes_editar",
            "estoque",
            "etiquetas",
        }
    ),
}

#: Limite de desconto por perfil, em porcentagem (0 a 100). 100 = sem limite.
LIMITE_DESCONTO = {"administrador": 100.0, "gerente": 50.0, "vendedor": 10.0}


def permissoes_do_perfil(perfil: str) -> frozenset[str]:
    return MATRIZ_PERMISSOES.get(str(perfil or "").lower(), frozenset({"painel", "pdv"}))


def pode(usuario, chave: str) -> bool:
    """O usuário tem a permissão ``chave``?"""
    if not usuario:
        return False
    perfil = str(usuario["perfil"] or "").lower()
    return chave in permissoes_do_perfil(perfil)


def limite_desconto(usuario) -> float:
    """Desconto máximo (em %) que o usuário pode conceder sem senha de supervisor."""
    if not usuario:
        return 0.0
    return float(LIMITE_DESCONTO.get(str(usuario["perfil"] or "").lower(), 0.0))


def descricao_permissoes() -> str:
    """Texto explicativo exibido na tela de usuários."""
    linhas = []
    for perfil in PERFIS:
        linhas.append(f"• {ROTULOS_PERFIS[perfil]}: {DESCRICAO_PERFIS[perfil]}")
    return "\n".join(linhas)


# --------------------------------------------------------------------------------------
# CRUD de usuários
# --------------------------------------------------------------------------------------

CAMPOS_EDITAVEIS = ("nome", "login", "perfil", "email", "telefone", "ativo", "trocar_senha")


class ErroUsuario(Exception):
    """Erro de cadastro/login de usuário."""


def listar(banco: Banco, incluir_inativos: bool = True, filtro: str = "") -> list:
    sql = "SELECT * FROM usuarios"
    condicoes, params = [], []
    if not incluir_inativos:
        condicoes.append("ativo=1")
    if filtro:
        condicoes.append("(nome LIKE ? OR login LIKE ? OR perfil LIKE ?)")
        params += [f"%{filtro}%"] * 3
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY nome"
    return banco.consultar(sql, params)


def pegar(banco: Banco, usuario_id: int):
    return banco.consultar_uma("SELECT * FROM usuarios WHERE id=?", (usuario_id,))


def pegar_por_login(banco: Banco, login: str):
    return banco.consultar_uma("SELECT * FROM usuarios WHERE LOWER(login)=LOWER(?)", (str(login or "").strip(),))


def _validar(banco: Banco, dados: dict, usuario_id: int | None = None) -> None:
    nome = str(dados.get("nome") or "").strip()
    login = str(dados.get("login") or "").strip()
    if not nome:
        raise ErroUsuario("Informe o nome do usuário.")
    if len(nome) < 2:
        raise ErroUsuario("Nome muito curto.")
    if not login:
        raise ErroUsuario("Informe o login (nome de acesso).")
    if len(login) < 3:
        raise ErroUsuario("O login precisa ter pelo menos 3 caracteres.")
    if " " in login:
        raise ErroUsuario("O login não pode conter espaços.")
    perfil = str(dados.get("perfil") or "vendedor").lower()
    if perfil not in PERFIS:
        raise ErroUsuario(f"Perfil inválido: '{perfil}'.")
    existe = banco.consultar_valor(
        "SELECT id FROM usuarios WHERE LOWER(login)=LOWER(?) AND (? IS NULL OR id<>?)",
        (login, usuario_id, usuario_id),
    )
    if existe:
        raise ErroUsuario(f"Já existe um usuário com o login '{login}'.")


def criar(banco: Banco, dados: dict, senha: str, autor=None) -> int:
    """Cadastra um novo usuário."""
    _validar(banco, dados)
    ok, msg = senha_forte(senha)
    if not ok:
        raise ErroUsuario(msg)
    registro = {
        "nome": str(dados["nome"]).strip(),
        "login": str(dados["login"]).strip(),
        "senha_hash": criar_hash_senha(senha),
        "perfil": str(dados.get("perfil") or "vendedor").lower(),
        "email": str(dados.get("email") or "").strip(),
        "telefone": str(dados.get("telefone") or "").strip(),
        "ativo": 1 if dados.get("ativo", 1) else 0,
        "trocar_senha": 1 if dados.get("trocar_senha", 0) else 0,
        "criado_em": agora_iso(),
        "atualizado_em": agora_iso(),
    }
    novo_id = banco.inserir("usuarios", registro)
    banco.registrar_log(
        "usuario_criado", f"{registro['nome']} ({registro['login']}) — perfil {registro['perfil']}",
        autor and autor["id"], autor and autor["nome"] or "",
    )
    return novo_id


def atualizar(banco: Banco, usuario_id: int, dados: dict, autor=None) -> int:
    """Altera os dados do usuário (sem trocar a senha)."""
    atual = pegar(banco, usuario_id)
    if not atual:
        raise ErroUsuario("Usuário não encontrado.")
    combinado = {**{k: atual[k] for k in CAMPOS_EDITAVEIS}, **dados}
    _validar(banco, combinado, usuario_id)

    # Regras de segurança: não deixar o sistema sem administrador e não se desativar.
    perfil_novo = str(combinado["perfil"]).lower()
    ativo_novo = 1 if combinado.get("ativo", 1) else 0
    if (perfil_novo != "administrador" or not ativo_novo) and atual["perfil"] == "administrador" and atual["ativo"]:
        outros = banco.consultar_valor(
            "SELECT COUNT(*) FROM usuarios WHERE perfil='administrador' AND ativo=1 AND id<>?", (usuario_id,)
        )
        if not outros:
            raise ErroUsuario(
                "Este é o único administrador ativo. Crie/outro administrador antes de "
                "rebaixar o perfil ou desativar este usuário."
            )
    if autor and int(autor["id"]) == int(usuario_id):
        if not ativo_novo:
            raise ErroUsuario("Você não pode desativar o seu próprio usuário.")
        if perfil_novo != str(autor["perfil"]).lower():
            raise ErroUsuario("Você não pode alterar o seu próprio perfil.")

    registro = {
        "nome": str(combinado["nome"]).strip(),
        "login": str(combinado["login"]).strip(),
        "perfil": perfil_novo,
        "email": str(combinado.get("email") or "").strip(),
        "telefone": str(combinado.get("telefone") or "").strip(),
        "ativo": ativo_novo,
        "trocar_senha": 1 if combinado.get("trocar_senha", 0) else 0,
        "atualizado_em": agora_iso(),
    }
    banco.atualizar("usuarios", usuario_id, registro)
    banco.registrar_log(
        "usuario_alterado", f"{registro['nome']} ({registro['login']})",
        autor and autor["id"], autor and autor["nome"] or "",
    )
    return usuario_id


def alterar_senha(banco: Banco, usuario_id: int, senha_atual: str, senha_nova: str, confirmar: str = "", autor=None) -> None:
    """Troca a senha exigindo a senha atual (exceto para o administrador resetando outro usuário)."""
    usuario = pegar(banco, usuario_id)
    if not usuario:
        raise ErroUsuario("Usuário não encontrado.")
    if senha_nova != (confirmar or senha_nova):
        raise ErroUsuario("A confirmação de senha não confere.")
    ok, msg = senha_forte(senha_nova)
    if not ok:
        raise ErroUsuario(msg)
    eh_o_mesmo = autor and int(autor["id"]) == int(usuario_id)
    if eh_o_mesmo or senha_atual is not None:
        if not verificar_senha(senha_atual or "", usuario["senha_hash"]):
            raise ErroUsuario("Senha atual incorreta.")
    if senha_nova == senha_atual:
        raise ErroUsuario("A nova senha deve ser diferente da atual.")
    banco.atualizar("usuarios", usuario_id, {"senha_hash": criar_hash_senha(senha_nova), "trocar_senha": 0, "atualizado_em": agora_iso()})
    banco.registrar_log("senha_alterada", usuario["login"], autor and autor["id"], autor and autor["nome"] or "")


def resetar_senha(banco: Banco, usuario_id: int, nova_senha: str, autor=None) -> None:
    """Redefine a senha de outro usuário (uso do administrador) e exige troca no próximo login."""
    usuario = pegar(banco, usuario_id)
    if not usuario:
        raise ErroUsuario("Usuário não encontrado.")
    ok, msg = senha_forte(nova_senha)
    if not ok:
        raise ErroUsuario(msg)
    banco.atualizar(
        "usuarios",
        usuario_id,
        {"senha_hash": criar_hash_senha(nova_senha), "trocar_senha": 1, "atualizado_em": agora_iso()},
    )
    banco.registrar_log(
        "senha_resetada", f"Senha de {usuario['login']} redefinida",
        autor and autor["id"], autor and autor["nome"] or "",
    )


def autenticar(banco: Banco, login: str, senha: str):
    """Valida login/senha. Devolve a linha do usuário ou ``None``."""
    usuario = pegar_por_login(banco, login)
    if not usuario:
        return None
    if not int(usuario["ativo"] or 0):
        raise ErroUsuario("Este usuário está desativado. Fale com o administrador.")
    if not verificar_senha(senha or "", usuario["senha_hash"]):
        return None
    banco.executar("UPDATE usuarios SET ultimo_login=? WHERE id=?", (agora_iso(), usuario["id"]))
    banco.registrar_log("login", f"{usuario['login']} ({usuario['perfil']})", usuario["id"], usuario["nome"])
    return usuario


def marcar_troca_feita(banco: Banco, usuario_id: int) -> None:
    banco.atualizar("usuarios", usuario_id, {"trocar_senha": 0, "atualizado_em": agora_iso()})


def vendedores(banco: Banco) -> list:
    """Usuários ativos que podem aparecer como vendedor no PDV."""
    return banco.consultar(
        "SELECT * FROM usuarios WHERE ativo=1 AND perfil IN ('administrador','gerente','vendedor') ORDER BY nome"
    )


def garantir_administrador(banco: Banco) -> None:
    """Se não houver nenhum administrador ativo, reativa/rebaixa o usuário 'admin' padrão.

    Protege contra o cenário "todo mundo se bloqueou para fora do sistema".
    """
    total = banco.consultar_valor("SELECT COUNT(*) FROM usuarios WHERE perfil='administrador' AND ativo=1") or 0
    if total:
        return
    padrao = pegar_por_login(banco, "admin")
    if padrao:
        banco.atualizar("usuarios", padrao["id"], {"perfil": "administrador", "ativo": 1, "atualizado_em": agora_iso()})
    else:
        criar(
            banco,
            {"nome": "Administrador", "login": "admin", "perfil": "administrador", "ativo": 1, "trocar_senha": 1},
            "admin",
        )


def contagem_por_perfil(banco: Banco) -> dict[str, int]:
    linhas = banco.consultar("SELECT perfil, COUNT(*) AS n FROM usuarios WHERE ativo=1 GROUP BY perfil")
    resultado = {p: 0 for p in PERFIS}
    for l in linhas:
        resultado[l["perfil"]] = int(l["n"])
    return resultado


def nomes_para_filtro(usuarios: Iterable) -> list[str]:
    return sorted({str(u["nome"]) for u in usuarios})
