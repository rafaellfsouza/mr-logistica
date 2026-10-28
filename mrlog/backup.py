"""
Backup e restauração dos dados.

O banco inteiro cabe em **um único arquivo** (``mrlogistica.db``), então o backup é
uma cópia fiel feita com a API ``sqlite3.Connection.backup`` — segura mesmo com o
sistema em uso (não copia um arquivo "pela metade").

Recursos:

* backup manual e automático (na abertura/fechamento do sistema, configurável);
* lista de backups com data, tamanho e integridade;
* restauração com **cópia de segurança automática** do banco atual;
* limpeza dos backups antigos (quantidade configurável);
* verificação de integridade (``PRAGMA integrity_check``).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .banco import Banco, ErroBanco
from .caminhos import caminho_banco, pasta_backups, pasta_dados
from .utils import formatar_data


class ErroBackup(Exception):
    """Falha ao criar, validar ou restaurar um backup."""


PADRAO_NOME = "backup-mrlogistica-%Y%m%d-%H%M%S.db"


def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def criar(banco: Banco, destino=None, autor=None, compactar: bool = True) -> str:
    """Cria um backup e devolve o caminho do arquivo gerado."""
    destino = Path(destino) if destino else pasta_backups() / f"backup-mrlogistica-{_carimbo()}.db"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino = destino.with_name(f"{destino.stem}-{_carimbo()}{destino.suffix}")
    try:
        if compactar:
            # Garante que o conteúdo do WAL esteja no arquivo principal antes da cópia.
            banco.executar("PRAGMA wal_checkpoint(TRUNCATE)")
        origem = sqlite3.connect(str(banco.caminho))
        try:
            target = sqlite3.connect(str(destino))
            try:
                origem.backup(target)
            finally:
                target.close()
        finally:
            origem.close()
    except (sqlite3.Error, OSError) as exc:
        if destino.exists():
            try:
                destino.unlink()
            except OSError:
                pass
        raise ErroBackup(f"Falha ao criar o backup: {exc}") from exc
    ok, mensagem = verificar(destino)
    if not ok:
        raise ErroBackup(f"Backup criado, mas falhou na verificação: {mensagem}")
    if autor is not None:
        banco.registrar_log("backup_criado", str(destino), *_autor(autor))
    return str(destino)


def _autor(autor) -> tuple[int | None, str]:
    try:
        return int(autor["id"]), str(autor["nome"] or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None, ""


def listar(pasta: Path | None = None) -> list[dict]:
    """Lista os backups disponíveis (mais recentes primeiro)."""
    base = Path(pasta) if pasta else pasta_backups()
    if not base.exists():
        return []
    arquivos = [a for a in base.glob("*.db") if a.is_file()]
    resultado = []
    for arquivo in sorted(arquivos, key=lambda a: a.stat().st_mtime, reverse=True):
        stat = arquivo.stat()
        resultado.append(
            {
                "caminho": str(arquivo),
                "nome": arquivo.name,
                "data": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "tamanho": stat.st_size,
                "tamanho_legivel": _tamanho_legivel(stat.st_size),
            }
        )
    return resultado


def _tamanho_legivel(bytes_: int) -> str:
    valor = float(bytes_)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            return f"{valor:.1f} {unidade}".replace(".", ",")
        valor /= 1024
    return f"{valor:.1f} GB"


def verificar(caminho) -> tuple[bool, str]:
    """Confere se o arquivo é um banco SQLite íntegro."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        return False, "Arquivo não encontrado."
    if arquivo.stat().st_size < 4096:
        return False, "Arquivo pequeno demais para ser um banco válido."
    try:
        conexao = sqlite3.connect(str(arquivo))
        try:
            resultado = conexao.execute("PRAGMA integrity_check").fetchone()
            versao = conexao.execute("SELECT valor FROM meta WHERE chave='versao'").fetchone()
        finally:
            conexao.close()
    except sqlite3.DatabaseError as exc:
        return False, f"Arquivo corrompido ou não é um banco do MR Logística: {exc}"
    if not resultado or str(resultado[0]).lower() != "ok":
        return False, f"Verificação de integridade falhou: {resultado}"
    return True, f"OK (esquema versão {versao[0] if versao else '?'})"


def abrir_backup(caminho) -> Banco:
    """Abre um backup como banco somente leitura (para consultar antes de restaurar)."""
    ok, mensagem = verificar(caminho)
    if not ok:
        raise ErroBackup(mensagem)
    try:
        banco = Banco(caminho=Path(caminho), aplicar_migracoes=False)
    except ErroBanco as exc:
        raise ErroBackup(str(exc)) from exc
    return banco


def resumo_backup(caminho) -> dict:
    """Resumo do conteúdo de um backup (mostrado antes de restaurar)."""
    banco = abrir_backup(caminho)
    try:
        contagens = {}
        for tabela in ("produtos", "clientes", "fornecedores", "vendas", "movimentacoes",
                       "contas_receber", "contas_pagar", "usuarios", "caixa_diario"):
            try:
                contagens[tabela] = int(banco.consultar_valor(f"SELECT COUNT(*) FROM {tabela}") or 0)
            except ErroBanco:
                contagens[tabela] = 0
        ultima_venda = banco.consultar_valor("SELECT MAX(criada_em) FROM vendas") or "—"
        return {
            "arquivo": Path(caminho).name,
            "versao": banco.versao_atual(),
            "contagens": contagens,
            "ultima_venda": ultima_venda,
            "integridade": banco.integridade(),
        }
    finally:
        banco.fechar()


def restaurar(banco: Banco, caminho_backup, autor=None) -> dict:
    """Restaura um backup no lugar do banco atual.

    Passos: valida o backup → cria cópia de segurança do banco atual → fecha as
    conexões → substitui o arquivo → reabre e migra. Devolve um dicionário com o
    caminho restaurado e o caminho da cópia de segurança.
    """
    arquivo = Path(caminho_backup)
    ok, mensagem = verificar(arquivo)
    if not ok:
        raise ErroBackup(mensagem)
    banco_atual = Path(banco.caminho)
    seguranca = None
    if banco_atual.exists():
        seguranca = pasta_backups() / f"antes-da-restauracao-{_carimbo()}.db"
        try:
            banco.executar("PRAGMA wal_checkpoint(TRUNCATE)")
            shutil.copy2(banco_atual, seguranca)
        except OSError as exc:
            raise ErroBackup(f"Não foi possível criar a cópia de segurança: {exc}") from exc
    try:
        banco.fechar()
        for sufixo in ("", "-wal", "-shm"):
            extra = Path(str(banco_atual) + sufixo)
            if extra.exists():
                try:
                    extra.unlink()
                except OSError:
                    pass
        shutil.copy2(arquivo, banco_atual)
    except OSError as exc:
        if seguranca and seguranca.exists():
            try:
                shutil.copy2(seguranca, banco_atual)
            except OSError:
                pass
        raise ErroBackup(
            f"Falha ao restaurar: {exc}. "
            "Feche outros programas que possam estar usando a pasta de dados e tente novamente."
        ) from exc
    banco._abrir()  # reabre a conexão apontando para o arquivo restaurado
    versao = banco.migrar()
    banco.registrar_log("backup_restaurado", f"de {arquivo.name} (esquema v{versao})", *_autor(autor))
    return {"restaurado": str(arquivo), "copia_seguranca": str(seguranca) if seguranca else None, "versao": versao}


def restaurar_para_banco_temporario(caminho_backup) -> Banco:
    """Abre o backup sem tocar no banco em uso (usado em testes e comparações)."""
    return abrir_backup(caminho_backup)


def exportar_para(banco: Banco, destino, autor=None) -> str:
    """Salva uma cópia do banco num caminho escolhido (pendrive, nuvem, e-mail)."""
    destino = Path(destino)
    if destino.suffix.lower() != ".db":
        destino = destino.with_suffix(".db")
    if destino.exists():
        raise ErroBackup(f"Já existe um arquivo em {destino}. Escolha outro nome.")
    return criar(banco, destino=destino, autor=autor)


def excluir(caminho, autor=None) -> bool:
    """Remove um arquivo de backup."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        return False
    try:
        arquivo.unlink()
        return True
    except OSError as exc:
        raise ErroBackup(f"Não foi possível excluir o backup: {exc}") from exc


def limpeza_automatica(banco: Banco, manter: int | None = None) -> list[str]:
    """Apaga os backups excedentes, mantendo os ``manter`` mais recentes."""
    if manter is None:
        manter = banco.config_pegar_int("manter_backups", 10)
    if manter <= 0:
        return []
    backups = listar()
    removidos = []
    for antigo in backups[max(1, int(manter)):]:
        try:
            if excluir(antigo["caminho"]):
                removidos.append(antigo["nome"])
        except ErroBackup:
            continue
    return removidos


def automatico(banco: Banco, autor=None) -> str | None:
    """Backup automático (usado ao abrir/fechar o sistema, se habilitado)."""
    if not banco.config_pegar_bool("backup_automatico", True):
        return None
    try:
        caminho = criar(banco, autor=autor)
        limpeza_automatica(banco)
        return caminho
    except ErroBackup:
        return None


def tamanho_banco_atual() -> dict:
    """Tamanho dos arquivos do banco em uso (db, wal e shm)."""
    base = caminho_banco()
    total = 0
    detalhes = {}
    for sufixo in ("", "-wal", "-shm"):
        arquivo = Path(str(base) + sufixo)
        if arquivo.exists():
            tamanho = arquivo.stat().st_size
            detalhes[arquivo.name] = tamanho
            total += tamanho
    return {"total": total, "legivel": _tamanho_legivel(total), "arquivos": detalhes, "pasta": str(pasta_dados())}


def restauracao_pendente() -> Path | None:
    """Indica se existe cópia de segurança de uma restauração recente."""
    arquivos = sorted(pasta_backups().glob("antes-da-restauracao-*.db"), key=lambda a: a.stat().st_mtime, reverse=True)
    return arquivos[0] if arquivos else None
