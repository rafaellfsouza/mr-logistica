"""
Camada de acesso ao banco de dados SQLite.

Um único objeto :class:`Banco` é criado no início do programa e compartilhado por
todas as telas. Ele:

* abre o arquivo em modo WAL (leituras não travam escritas);
* liga as chaves estrangeiras (integridade referencial real);
* devolve as linhas como ``sqlite3.Row`` (acesso por nome de coluna);
* controla a versão do esquema e aplica migrações pendentes;
* registra tudo na trilha de auditoria (tabela ``logs``).

Não há servidor nem internet: o banco é um arquivo local
(``~/.mrlogistica/mrlogistica.db``).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import esquema
from .caminhos import caminho_banco

VERSAO_ESQUEMA_ATUAL = esquema.MIGRACOES[-1][0]

_bloqueio = threading.RLock()  # protege o acesso ao SQLite quando houver threads auxiliares


class ErroBanco(Exception):
    """Erro de acesso a dados (arquivo corrompido, restrição violada etc.)."""


class Banco:
    """Conexão SQLite com utilitários de consulta e controle de transação."""

    def __init__(self, caminho: str | Path | None = None, aplicar_migracoes: bool = True):
        self.caminho = Path(caminho) if caminho else caminho_banco()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conexao: sqlite3.Connection | None = None
        self._profundidade_transacao = 0
        self._abrir()
        if aplicar_migracoes:
            self.migrar()

    # ------------------------------------------------------------------ conexão
    def _abrir(self) -> None:
        try:
            con = sqlite3.connect(
                str(self.caminho),
                check_same_thread=False,
                isolation_level=None,  # controle manual de transação
                timeout=15.0,
            )
        except sqlite3.Error as exc:  # arquivo corrompido / sem permissão
            raise ErroBanco(f"Não foi possível abrir o banco em {self.caminho}: {exc}") from exc
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA busy_timeout = 15000")
        con.execute("PRAGMA temp_store = MEMORY")
        self._conexao = con

    @property
    def conexao(self) -> sqlite3.Connection:
        if self._conexao is None:
            self._abrir()
        assert self._conexao is not None
        return self._conexao

    def fechar(self) -> None:
        """Fecha a conexão liberando os arquivos ``-wal``/``-shm`` (usado no backup)."""
        if self._conexao is not None:
            self._profundidade_transacao = 0
            try:
                self._conexao.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conexao.close()
            except sqlite3.Error:
                pass
            self._conexao = None

    # ------------------------------------------------------------------ consultas
    def executar(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        """Executa um comando SQL com parâmetros posicionais."""
        with _bloqueio:
            try:
                return self.conexao.execute(sql, tuple(params))
            except sqlite3.Error as exc:
                raise ErroBanco(f"Falha ao executar SQL: {exc}\n{sql}") from exc

    def executemuitos(self, sql: str, sequencia: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with _bloqueio:
            try:
                return self.conexao.executemany(sql, [tuple(p) for p in sequencia])
            except sqlite3.Error as exc:
                raise ErroBanco(f"Falha ao executar SQL em lote: {exc}") from exc

    def consultar(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """Retorna todas as linhas da consulta."""
        return list(self.executar(sql, params).fetchall())

    def consultar_uma(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        """Retorna a primeira linha da consulta (ou ``None``)."""
        return self.executar(sql, params).fetchone()

    def consultar_valor(self, sql: str, params: Sequence[Any] = (), padrao=None):
        """Retorna a primeira coluna da primeira linha."""
        linha = self.consultar_uma(sql, params)
        if linha is None or len(linha) == 0:
            return padrao
        valor = linha[0]
        return padrao if valor is None else valor

    def inserir(self, tabela: str, dados: dict) -> int:
        """Insere um registro a partir de um dicionário e devolve o ``id`` gerado."""
        campos = list(dados.keys())
        sql = f"INSERT INTO {tabela} ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})"
        cur = self.executar(sql, [dados[c] for c in campos])
        return int(cur.lastrowid)

    def atualizar(self, tabela: str, registro_id: int, dados: dict) -> int:
        """Atualiza um registro pelo ``id`` e devolve o número de linhas afetadas."""
        if not dados:
            return 0
        campos = list(dados.keys())
        sql = f"UPDATE {tabela} SET {', '.join(f'{c}=?' for c in campos)} WHERE id=?"
        cur = self.executar(sql, [dados[c] for c in campos] + [registro_id])
        return cur.rowcount

    def excluir(self, tabela: str, registro_id: int) -> int:
        """Exclusão física (usada apenas onde não há histórico ligado)."""
        cur = self.executar(f"DELETE FROM {tabela} WHERE id=?", (registro_id,))
        return cur.rowcount

    # ------------------------------------------------------------------ transação
    class _Transacao:
        def __init__(self, banco: "Banco"):
            self.banco = banco

        def __enter__(self) -> "Banco._Transacao":
            self.banco.iniciar()
            return self

        def __exit__(self, tipo, valor, traceback) -> bool:
            if tipo is None:
                self.banco.confirmar()
            else:
                self.banco.desfazer()
            return False

    def transacao(self) -> "Banco._Transacao":
        """Context manager: ``with banco.transacao(): ...`` — confirma ou desfaz sozinho.

        Qualquer erro dentro do bloco desfaz **tudo**, garantindo que uma venda nunca
        fique gravada pela metade (itens sem pagamento, estoque baixado sem cupom etc.).
        """
        return Banco._Transacao(self)

    def iniciar(self) -> None:
        """Inicia uma transação. Chamadas aninhadas apenas incrementam o contador."""
        with _bloqueio:
            if self._profundidade_transacao == 0:
                self.conexao.execute("BEGIN IMMEDIATE")
            self._profundidade_transacao += 1

    def confirmar(self) -> None:
        """Confirma a transação mais externa (as internas só decrementam o contador)."""
        with _bloqueio:
            if self._profundidade_transacao <= 0:
                return
            self._profundidade_transacao -= 1
            if self._profundidade_transacao == 0:
                self.conexao.execute("COMMIT")

    def desfazer(self) -> None:
        """Desfaz toda a pilha de transações (rollback completo)."""
        with _bloqueio:
            self._profundidade_transacao = 0
            try:
                self.conexao.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    @property
    def em_transacao(self) -> bool:
        return self._profundidade_transacao > 0

    # ------------------------------------------------------------------ versão / migração
    def versao_atual(self) -> int:
        try:
            v = self.consultar_valor("SELECT valor FROM meta WHERE chave='versao'")
        except ErroBanco:
            return 0
        try:
            return int(v) if v else 0
        except (TypeError, ValueError):
            return 0

    def migrar(self) -> int:
        """Aplica as migrações pendentes e devolve a versão final do esquema."""
        self.executar("CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT)")
        atual = self.versao_atual()
        with self.transacao():
            for versao, criar, semear in esquema.MIGRACOES:
                if versao <= atual:
                    continue
                criar(self.conexao)
                if semear:
                    semear(self.conexao)
                self.executar(
                    "INSERT INTO meta (chave, valor) VALUES ('versao', ?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                    (str(versao),),
                )
                atual = versao
        return atual

    # ------------------------------------------------------------------ configurações
    def config_pegar(self, chave: str, padrao: str = "") -> str:
        valor = self.consultar_valor("SELECT valor FROM config WHERE chave=?", (chave,))
        return padrao if valor is None else str(valor)

    def config_pegar_int(self, chave: str, padrao: int = 0) -> int:
        try:
            return int(float(self.config_pegar(chave, str(padrao))))
        except (TypeError, ValueError):
            return padrao

    def config_pegar_bool(self, chave: str, padrao: bool = False) -> bool:
        return self.config_pegar(chave, "1" if padrao else "0") in ("1", "true", "True", "sim")

    def config_gravar(self, chave: str, valor) -> None:
        self.executar(
            "INSERT INTO config (chave, valor) VALUES (?,?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (chave, "" if valor is None else str(valor)),
        )

    def config_todas(self) -> dict[str, str]:
        return {l["chave"]: (l["valor"] or "") for l in self.consultar("SELECT chave, valor FROM config")}

    # ------------------------------------------------------------------ auditoria
    def registrar_log(self, acao: str, detalhe: str = "", usuario_id=None, usuario_nome: str = "") -> None:
        """Grava uma entrada na trilha de auditoria (nunca interrompe a operação)."""
        from .utils import agora_iso

        try:
            self.executar(
                "INSERT INTO logs (usuario_id, usuario_nome, acao, detalhe, criado_em) VALUES (?,?,?,?,?)",
                (usuario_id, usuario_nome, acao, detalhe, agora_iso()),
            )
        except ErroBanco:
            pass

    def logs(self, limite: int = 500, filtro: str = "") -> list[sqlite3.Row]:
        sql = "SELECT * FROM logs"
        params: list[Any] = []
        if filtro:
            sql += " WHERE acao LIKE ? OR detalhe LIKE ? OR usuario_nome LIKE ?"
            params += [f"%{filtro}%"] * 3
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limite))
        return self.consultar(sql, params)

    # ------------------------------------------------------------------ utilidades
    def proximo_numero(self, tabela: str, coluna: str = "numero") -> int:
        """Próximo número sequencial de uma tabela (usado no número do cupom)."""
        valor = self.consultar_valor(f"SELECT COALESCE(MAX({coluna}),0) FROM {tabela}") or 0
        return int(valor) + 1

    def integridade(self) -> tuple[bool, str]:
        """Executa ``PRAGMA integrity_check`` e devolve ``(ok, mensagem)``."""
        try:
            resultado = self.consultar_valor("PRAGMA integrity_check", padrao="")
            ok = str(resultado).strip().lower() == "ok"
            return ok, str(resultado)
        except ErroBanco as exc:
            return False, str(exc)

    def compactar(self) -> None:
        """Reduz o tamanho físico do arquivo (``VACUUM``). Não pode rodar em transação."""
        with _bloqueio:
            self.desfazer()
            self.conexao.execute("VACUUM")

    def tabelas(self) -> list[str]:
        return [
            l["name"]
            for l in self.consultar("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        ]
