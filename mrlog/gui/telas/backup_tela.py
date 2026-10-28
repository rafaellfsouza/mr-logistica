"""
Tela de backup e restauração.

O banco de dados é um único arquivo SQLite dentro da pasta de dados do usuário,
então "fazer backup" é copiar esse arquivo — mas a tela cuida de tudo o que torna
a operação segura:

* **Criar backup agora** (cópia íntegra, com ``wal_checkpoint`` para não perder
  lançamentos ainda em memória);
* **Exportar para...** um pendrive/nuvem (o usuário escolhe o destino);
* **Verificar integridade** (``PRAGMA integrity_check`` + versão do esquema);
* **Ver conteúdo** (quantos produtos, vendas, clientes... existem no backup);
* **Restaurar** — sempre criando antes uma cópia de segurança do banco atual
  (``antes-da-restauracao-*.db``), com avisos claros e recarga das telas depois;
* **Limpeza automática** (mantém os N backups mais recentes, configurável);
* **Backup automático** ao abrir/fechar o sistema (configuração gravada no banco).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ... import backup as backup_mod
from ... import caixa as caixa_mod
from ... import configuracoes as configuracoes_mod
from ...caminhos import pasta_backups
from ...utils import formatar_data, hoje
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO
from ..widgets import Cartao, Tabela
from . import Tela

#: Colunas da grade de backups.
COLUNAS = [
    {"chave": "nome", "rotulo": "Arquivo", "largura": 300},
    {"chave": "data", "rotulo": "Criado em", "largura": 150},
    {"chave": "tamanho_legivel", "rotulo": "Tamanho", "largura": 90, "alinhamento": "direita"},
    {"chave": "caminho", "rotulo": "Pasta", "largura": 380},
]

#: Rótulos amigáveis das tabelas mostradas no resumo do backup.
ROTULOS_TABELAS = {
    "produtos": "Produtos", "clientes": "Clientes", "fornecedores": "Fornecedores",
    "vendas": "Vendas", "movimentacoes": "Movimentações de estoque",
    "contas_receber": "Contas a receber", "contas_pagar": "Contas a pagar",
    "usuarios": "Usuários", "caixa_diario": "Aberturas de caixa",
}


class DialogoConteudoBackup(dialogs.Modal):
    """Mostra o que existe dentro de um arquivo de backup (antes de restaurar)."""

    def __init__(self, mestre, tema, resumo: dict):
        super().__init__(mestre, tema, f"Conteúdo do backup — {resumo.get('arquivo', '')}", largura=520)
        ttk.Label(self.corpo, text=f"Versão do esquema: {resumo.get('versao', '?')}",
                  style="TLabel", font=FONTE_SUBTITULO).pack(anchor="w")
        ttk.Label(self.corpo, text=f"Última venda registrada: {resumo.get('ultima_venda', '—')}",
                  style="Suave.TLabel").pack(anchor="w", pady=(2, 8))
        quadro = ttk.Frame(self.corpo, style="Card.TFrame", padding=10)
        quadro.pack(fill="both", expand=True)
        quadro.columnconfigure(1, weight=1)
        for indice, (tabela, quantidade) in enumerate((resumo.get("contagens") or {}).items()):
            ttk.Label(quadro, text=f"{ROTULOS_TABELAS.get(tabela, tabela)}:",
                      style="Card.Suave.TLabel").grid(row=indice, column=0, sticky="w", pady=2)
            ttk.Label(quadro, text=f"{quantidade}", style="Card.TLabel").grid(row=indice, column=1, sticky="w",
                                                                             padx=(10, 0), pady=2)
        integridade = resumo.get("integridade")
        if isinstance(integridade, (tuple, list)) and integridade:
            texto = "OK — arquivo íntegro" if integridade[0] else f"FALHOU — {integridade[1]}"
        elif integridade:
            texto = str(integridade)
        else:
            texto = ""
        if texto:
            ttk.Label(self.corpo, text=f"Verificação de integridade: {texto}",
                      style="Suave.TLabel").pack(anchor="w", pady=(8, 0))
        self.barra_botoes((("Fechar", None, "Primario.TButton"),))


class BackupTela(Tela):
    """Backup, verificação e restauração do banco de dados."""

    titulo = "Backup e restauração"
    descricao = ("Copie o banco de dados para um arquivo, verifique a integridade e restaure quando precisar. "
                 "Uma cópia de segurança é criada automaticamente antes de qualquer restauração.")

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self._cartoes: dict[str, Cartao] = {}
        self._montar_barra(
            [
                ("💾 Criar backup agora", self.criar_backup, "Primario.TButton"),
                ("♻ Restaurar selecionado", self.restaurar, "TButton"),
                ("✔ Verificar integridade", self.verificar, "TButton"),
                ("🔍 Ver conteúdo", self.ver_conteudo, "TButton"),
                ("🧹 Limpeza automática", self.limpeza, "TButton"),
                ("🗑 Excluir", self.excluir, "TButton"),
                ("⟳ Atualizar", self.carregar, "TButton", "Ctrl+R"),
            ],
            lado_direito=[("📁 Abrir pasta", self.abrir_pasta, "TButton"),
                          ("⭳ Exportar para...", self.exportar_para, "TButton")],
        )
        self._montar_interface()
        self._registrar_teclas()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.corpo.rowconfigure(0, weight=0)
        self.corpo.rowconfigure(1, weight=1)

        topo = ttk.Frame(self.corpo, style="TFrame")
        topo.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for indice in range(4):
            topo.columnconfigure(indice, weight=1)
        for indice, (chave, titulo) in enumerate((
            ("banco", "Banco de dados"), ("ultimo", "Último backup"),
            ("quantidade", "Backups guardados"), ("automatico", "Backup automático"),
        )):
            cartao = Cartao(topo, self.tema, titulo, "—", "", cor="info", largura_minima=180)
            cartao.grid(row=0, column=indice, sticky="ew", padx=(0, 8))
            self._cartoes[chave] = cartao

        quadro = ttk.Frame(self.corpo, style="TFrame")
        quadro.grid(row=1, column=0, sticky="nsew")
        quadro.columnconfigure(0, weight=1)
        quadro.columnconfigure(1, weight=0)
        quadro.rowconfigure(0, weight=1)

        self.tabela = Tabela(quadro, self.tema, COLUNAS, ao_selecionar=self._ao_selecionar,
                             ao_duplo_clique=lambda linha: self.ver_conteudo(linha), altura=18,
                             busca_placeholder="Buscar backup... (Ctrl+B)")
        self.tabela.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # --- painel direito: opções + detalhes do backup selecionado ----------------
        lateral = ttk.Frame(quadro, style="Card.TFrame", padding=10)
        lateral.grid(row=0, column=1, sticky="ns")
        lateral.columnconfigure(0, weight=1)
        ttk.Label(lateral, text="Opções de backup", style="Card.TLabel", font=FONTE_SUBTITULO).grid(
            row=0, column=0, sticky="w")

        self.var_automatico = tk.BooleanVar(value=True)
        ttk.Checkbutton(lateral, text="Backup automático ao abrir e ao fechar o sistema",
                        variable=self.var_automatico, style="Card.TCheckbutton",
                        command=self.salvar_opcoes).grid(row=1, column=0, sticky="w", pady=(8, 2))

        manter = ttk.Frame(lateral, style="Card.TFrame")
        manter.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        ttk.Label(manter, text="Manter os últimos", style="Card.Suave.TLabel").pack(side="left")
        self.var_manter = tk.StringVar(value="10")
        ttk.Spinbox(manter, textvariable=self.var_manter, from_=1, to=200, width=6,
                    command=self.salvar_opcoes).pack(side="left", padx=6)
        ttk.Label(manter, text="backups (os mais antigos são apagados)",
                  style="Card.Suave.TLabel").pack(side="left")

        ttk.Label(lateral, text="Detalhes do backup selecionado", style="Card.TLabel",
                  font=FONTE_SUBTITULO).grid(row=3, column=0, sticky="w", pady=(10, 4))
        self.texto_detalhes = tk.Text(lateral, width=46, height=14, wrap="word", borderwidth=0,
                                      font=FONTE_PEQUENA, background=self.tema.cor("bg_card"),
                                      foreground=self.tema.cor("fg"), state="disabled")
        self.texto_detalhes.grid(row=4, column=0, sticky="nsew")
        lateral.rowconfigure(4, weight=1)

        ttk.Button(lateral, text="🔍 Ver conteúdo do backup",
                   command=self.ver_conteudo).grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self._registros: list[dict] = []

    def _registrar_teclas(self):
        for sequencia, comando in (
            ("<Control-r>", self.carregar),
            ("<Control-R>", self.carregar),
            ("<Control-b>", self.focar_busca),
            ("<Control-B>", self.focar_busca),
            ("<Delete>", self.excluir),
        ):
            self.bind(sequencia, lambda _e, c=comando: (c(), "break")[1])

    # ------------------------------------------------------------------ dados
    def carregar(self):
        configuracao = configuracoes_mod.carregar(self.banco)
        self.var_automatico.set(bool(configuracao.get("backup_automatico", True)))
        self.var_manter.set(str(configuracao.get("manter_backups", 10)))

        self._registros = backup_mod.listar()
        self.tabela.carregar(self._registros, resumo=f"{len(self._registros)} arquivo(s) de backup")
        self._atualizar_cartoes()
        self.status(f"{len(self._registros)} backup(s) em {pasta_backups()}")

    def _atualizar_cartoes(self):
        tamanho = backup_mod.tamanho_banco_atual()
        self._cartoes["banco"].definir(
            valor=tamanho["legivel"],
            detalhe=f"Pasta de dados:\n{tamanho['pasta']}",
        )
        if self._registros:
            ultimo = self._registros[0]
            self._cartoes["ultimo"].definir(valor=ultimo["data"], detalhe=f"{ultimo['nome']} • "
                                                                          f"{ultimo['tamanho_legivel']}",
                                            cor="sucesso")
        else:
            self._cartoes["ultimo"].definir(valor="Nenhum", detalhe="Crie o primeiro backup agora.", cor="alerta")
        total = sum(int(r["tamanho"]) for r in self._registros)
        self._cartoes["quantidade"].definir(
            valor=f"{len(self._registros)} arquivo(s)",
            detalhe=backup_mod._tamanho_legivel(total) + " ocupados na pasta de backups",  # noqa: SLF001
        )
        automatico = bool(self.var_automatico.get())
        self._cartoes["automatico"].definir(
            valor="Ativo" if automatico else "Desativado",
            detalhe=f"Mantém os últimos {self.var_manter.get()} backups" if automatico
                    else "Ative para não correr riscos.",
            cor="sucesso" if automatico else "perigo",
        )
        pendente = backup_mod.restauracao_pendente()
        if pendente:
            self._cartoes["quantidade"].definir(
                detalhe=f"Cópia de segurança de restauração:\n{pendente.name}")

    def registros(self) -> list[dict]:
        return list(self._registros)

    def selecionado(self) -> dict | None:
        return self.tabela.linha_selecionada()

    def _exigir_selecao(self) -> dict | None:
        linha = self.selecionado()
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione um arquivo de backup na lista.")
        return linha

    def _ao_selecionar(self, linha: dict | None):
        self.texto_detalhes.configure(state="normal")
        self.texto_detalhes.delete("1.0", "end")
        if not linha:
            self.texto_detalhes.insert("end", "Nenhum backup selecionado.")
        else:
            for rotulo, valor in (
                ("Arquivo", linha["nome"]),
                ("Criado em", linha["data"]),
                ("Tamanho", linha["tamanho_legivel"]),
                ("Caminho", linha["caminho"]),
            ):
                self.texto_detalhes.insert("end", f"{rotulo}: ", "rotulo")
                self.texto_detalhes.insert("end", f"{valor}\n")
            self.texto_detalhes.insert(
                "end", "\nUse “Ver conteúdo” para saber o que há dentro deste arquivo "
                       "e “Restaurar selecionado” para voltar o sistema a esse ponto.\n")
        self.texto_detalhes.tag_configure("rotulo", font=("Segoe UI", 9, "bold"))
        self.texto_detalhes.configure(state="disabled", background=self.tema.cor("bg_card"),
                                      foreground=self.tema.cor("fg"))

    # ------------------------------------------------------------------ opções
    def salvar_opcoes(self):
        try:
            manter = int(float(self.var_manter.get() or 0))
        except ValueError:
            manter = 10
        manter = max(1, min(manter, 200))
        self.var_manter.set(str(manter))
        try:
            configuracoes_mod.salvar(
                self.banco,
                {"backup_automatico": bool(self.var_automatico.get()), "manter_backups": manter},
                autor=self.usuario,
            )
        except configuracoes_mod.ErroConfiguracao as exc:
            dialogs.erro(self, self.tema, str(exc), "Configurações de backup")
            return False
        self._atualizar_cartoes()
        self.status("Opções de backup salvas.")
        return True

    # ------------------------------------------------------------------ ações
    def criar_backup(self):
        dialogo = dialogs.progresso(self.ctx.janela, self.tema, "Criando backup",
                                    "Copiando o banco de dados... não feche o sistema.")
        try:
            caminho = backup_mod.criar(self.banco, autor=self.usuario)
        except backup_mod.ErroBackup as exc:
            dialogs.finalizar_progresso(dialogo)
            dialogs.erro(self, self.tema, str(exc), "Backup")
            return None
        except Exception as exc:
            dialogs.finalizar_progresso(dialogo)
            self.ctx.avisar_erro(exc, "Erro ao criar o backup.")
            return None
        dialogs.finalizar_progresso(dialogo)
        removidos = backup_mod.limpeza_automatica(self.banco)
        self.carregar()
        texto = f"Backup criado com sucesso:\n{caminho}"
        if removidos:
            texto += f"\n\nLimpeza automática: {len(removidos)} arquivo(s) antigo(s) removido(s)."
        dialogs.sucesso(self, self.tema, texto, "Backup concluído")
        return caminho

    def exportar_para(self):
        """Copia o banco para um destino escolhido (pendrive, nuvem, e-mail)."""
        destino = filedialog.asksaveasfilename(
            parent=self, title="Exportar banco de dados",
            initialdir=str(Path.home()),
            initialfile=f"mrlogistica-{hoje()}.db",
            filetypes=[("Banco MR Logística", "*.db"), ("Todos os arquivos", "*.*")],
            defaultextension=".db",
        )
        if not destino:
            return None
        try:
            caminho = backup_mod.exportar_para(self.banco, destino, autor=self.usuario)
        except backup_mod.ErroBackup as exc:
            dialogs.erro(self, self.tema, str(exc), "Exportar backup")
            return None
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao exportar o banco de dados.")
            return None
        dialogs.sucesso(self, self.tema, f"Cópia exportada para:\n{caminho}\n\n"
                                         "Guarde esse arquivo em local seguro (pendrive ou nuvem).",
                        "Exportação concluída")
        return caminho

    def verificar(self, linha: dict | None = None):
        linha = linha if isinstance(linha, dict) else self._exigir_selecao()
        if not linha:
            return None
        ok, mensagem = backup_mod.verificar(linha["caminho"])
        if ok:
            dialogs.sucesso(self, self.tema, f"{linha['nome']}\n\n{mensagem}", "Backup íntegro")
        else:
            dialogs.erro(self, self.tema, f"{linha['nome']}\n\n{mensagem}", "Problema no backup")
        return ok

    def ver_conteudo(self, linha: dict | None = None):
        linha = linha if isinstance(linha, dict) else self._exigir_selecao()
        if not linha:
            return None
        try:
            resumo = backup_mod.resumo_backup(linha["caminho"])
        except backup_mod.ErroBackup as exc:
            dialogs.erro(self, self.tema, str(exc), "Conteúdo do backup")
            return None
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao ler o conteúdo do backup.")
            return None
        DialogoConteudoBackup(self.ctx.janela, self.tema, resumo).abrir()
        return resumo

    def excluir(self, linha: dict | None = None):
        linha = linha if isinstance(linha, dict) else self._exigir_selecao()
        if not linha:
            return False
        if not dialogs.confirmar(self, self.tema,
                                 f"Excluir definitivamente o backup?\n\n{linha['nome']}\n"
                                 f"Criado em {linha['data']} ({linha['tamanho_legivel']})",
                                 "Excluir backup", "Excluir", "Cancelar"):
            return False
        try:
            removido = backup_mod.excluir(linha["caminho"], autor=self.usuario)
        except backup_mod.ErroBackup as exc:
            dialogs.erro(self, self.tema, str(exc), "Excluir backup")
            return False
        self.carregar()
        if removido:
            dialogs.sucesso(self, self.tema, "Backup excluído.")
        return bool(removido)

    def limpeza(self):
        manter = max(1, min(int(float(self.var_manter.get() or 10)), 200))
        if len(self._registros) <= manter:
            dialogs.info(self, self.tema, f"Nada a limpar: existem {len(self._registros)} backup(s) e a "
                                          f"configuração mantém {manter}.")
            return []
        if not dialogs.confirmar(self, self.tema,
                                 f"Manter apenas os {manter} backups mais recentes?\n\n"
                                 f"{len(self._registros) - manter} arquivo(s) serão excluídos "
                                 "definitivamente.", "Limpeza de backups", "Limpar", "Cancelar"):
            return []
        removidos = backup_mod.limpeza_automatica(self.banco, manter=manter)
        self.carregar()
        if removidos:
            dialogs.sucesso(self, self.tema, f"{len(removidos)} backup(s) antigo(s) removido(s):\n"
                                             + "\n".join(removidos[:6]))
        else:
            dialogs.info(self, self.tema, "Nenhum backup foi removido.")
        return removidos

    def abrir_pasta(self):
        from ... import impressao

        impressao.abrir_pasta(pasta_backups())
        self.status(f"Pasta de backups: {pasta_backups()}")

    # ------------------------------------------------------------------ restauração
    def restaurar(self, linha: dict | None = None):
        """Substitui o banco atual pelo backup escolhido (com cópia de segurança)."""
        if not self.exigir("backup", "restaurar um backup"):
            return False
        linha = linha if isinstance(linha, dict) else self._exigir_selecao()
        if not linha:
            return False
        caminho = Path(linha["caminho"])
        ok, mensagem = backup_mod.verificar(caminho)
        if not ok:
            dialogs.erro(self, self.tema, f"Este backup não pode ser restaurado:\n{mensagem}", "Backup inválido")
            return False
        try:
            resumo = backup_mod.resumo_backup(caminho)
        except backup_mod.ErroBackup as exc:
            resumo = {"arquivo": linha["nome"], "versao": "?", "contagens": {}, "ultima_venda": "—",
                      "integridade": str(exc)}
        DialogoConteudoBackup(self.ctx.janela, self.tema, resumo).abrir()

        contagens = resumo.get("contagens") or {}
        texto = (
            f"Restaurar o backup?\n\n"
            f"Arquivo: {linha['nome']}\n"
            f"Criado em: {linha['data']}\n"
            f"Produtos: {contagens.get('produtos', 0)} • Vendas: {contagens.get('vendas', 0)} • "
            f"Clientes: {contagens.get('clientes', 0)}\n\n"
            "TUDO o que foi lançado depois desse backup será substituído.\n"
            "Antes, o sistema cria uma cópia de segurança do banco atual (arquivo "
            "“antes-da-restauracao-*.db” na pasta de backups)."
        )
        if not dialogs.confirmar(self, self.tema, texto, "Restaurar backup", "Restaurar", "Cancelar"):
            return False

        caixa_aberto = caixa_mod.caixa_aberto(self.banco)
        if caixa_aberto and not dialogs.confirmar(
            self, self.tema,
            f"Existe um caixa aberto ({formatar_data(caixa_aberto['data'])}).\n\n"
            "Depois da restauração o estado do caixa passa a ser o do backup — o caixa aberto "
            "atual pode desaparecer da lista.\n\nContinuar mesmo assim?",
            "Caixa aberto", "Continuar", "Cancelar"):
            return False

        dialogo = dialogs.progresso(self.ctx.janela, self.tema, "Restaurando backup",
                                    "Substituindo o banco de dados... aguarde.")
        try:
            resultado = backup_mod.restaurar(self.banco, caminho, autor=self.usuario)
        except backup_mod.ErroBackup as exc:
            dialogs.finalizar_progresso(dialogo)
            dialogs.erro(self, self.tema, str(exc), "Restauração")
            return False
        except Exception as exc:
            dialogs.finalizar_progresso(dialogo)
            self.ctx.avisar_erro(exc, "Erro ao restaurar o backup.")
            return False
        dialogs.finalizar_progresso(dialogo)

        # as outras telas precisam ser recriadas: os dados mudaram por completo
        self._invalidar_telas()
        try:
            self.ctx.app.atualizar_caixa()
        except Exception:
            pass
        self.carregar()
        dialogs.sucesso(
            self, self.tema,
            f"Backup restaurado com sucesso.\n\n"
            f"Arquivo: {Path(resultado['restaurado']).name}\n"
            f"Esquema: versão {resultado.get('versao')}\n"
            + (f"Cópia de segurança do banco anterior: {Path(resultado['copia_seguranca']).name}"
               if resultado.get("copia_seguranca") else ""),
            "Restauração concluída",
        )
        self.ctx.navegar("painel")
        return True

    def _invalidar_telas(self, manter: tuple[str, ...] = ("backup",)):
        """Descarta as telas já criadas para que sejam remontadas com os dados restaurados."""
        telas = getattr(self.ctx.app, "_telas", None)
        if not isinstance(telas, dict):
            return
        for tela_id in list(telas.keys()):
            if tela_id in manter:
                continue
            widget = telas.pop(tela_id, None)
            if widget is None:
                continue
            try:
                widget.destroy()
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ integração
    def focar_busca(self):
        self.tabela.focar_busca()

    def atualizar_tema(self):
        self.tabela.atualizar_tema()
        for cartao in self._cartoes.values():
            cartao.atualizar_tema()
        self.texto_detalhes.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"))

    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        self.carregar()
        nome = parametros.get("selecionar")
        if nome and self._registros:
            for registro in self._registros:
                if str(registro["nome"]) == str(nome):
                    self.tabela.selecionar_por("nome", nome)
                    break
