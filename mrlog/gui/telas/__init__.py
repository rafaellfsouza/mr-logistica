"""
Infraestrutura comum das telas do MR Logística.

Todas as telas herdam de :class:`Tela` (cabeçalho + área de conteúdo) ou de
:class:`TelaLista` (tela com grade de dados, busca, filtros, botões de ação,
formulário de cadastro/edição e exportação). Assim cada módulo novo precisa
apenas descrever **o quê** exibir — a mecânica (validação, mensagens, tema,
exportação) já está pronta aqui.

Contrato esperado pela janela principal (``mrlog.gui.app``)::

    class MinhaTela(TelaLista):
        def carregar(self): ...        # (re)carrega os dados
        def focar_busca(self): ...     # Ctrl+B
        def ao_tecla(self, tecla): ... # opcional: capturar F1..F12 (devolver True)
        def ao_sair(self): ...         # opcional: retornar False impede trocar de tela
        def atualizar_tema(self): ...  # opcional: reagir ao tema claro/escuro
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable, Iterable, Sequence

from ... import exportacao as exportacao_mod
from ... import impressao as impressao_mod
from .. import dialogs
from ..tema import FONTE_BASE, FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO, Tema
from ..widgets import BarraFerramentas, Tabela


# --------------------------------------------------------------------------------------
# Helpers de exportação / impressão
# --------------------------------------------------------------------------------------


def colunas_para_exportacao(colunas: Sequence[dict]) -> list[dict]:
    """Converte as colunas da grade no formato esperado por ``mrlog.exportacao``."""
    return [
        {"chave": c["chave"], "rotulo": c.get("rotulo", c["chave"]), "tipo": c.get("tipo", "texto")}
        for c in colunas
        if c.get("visivel", True)
    ]


def limpar_dados_exportacao(colunas: Sequence[dict], linhas: Iterable[dict]) -> list[dict]:
    """Remove chaves internas (``_tag...``) e mantém apenas as colunas visíveis."""
    chaves = [c["chave"] for c in colunas if c.get("visivel", True)]
    resultado = []
    for linha in linhas or []:
        resultado.append({chave: linha.get(chave) for chave in chaves})
    return resultado


class DialogoExportar(dialogs.Modal):
    """Escolhe formato, destino e opções de exportação."""

    FORMATOS = (("xlsx", "Excel (.xlsx) — abre no Excel/LibreOffice"),
                ("pdf", "PDF (.pdf) — pronto para imprimir"),
                ("csv", "CSV (.csv) — texto separado por ponto e vírgula"))

    def __init__(self, mestre, tema: Tema, titulo_arquivo: str, qtd_registros: int, periodo: str = ""):
        super().__init__(mestre, tema, "Exportar dados", largura=520)
        self._formato = tk.StringVar(value="xlsx")
        self._caminho = tk.StringVar(value="")
        self._abrir = tk.BooleanVar(value=True)
        ttk.Label(self.corpo, text=f"{titulo_arquivo} — {qtd_registros} registro(s).",
                  style="TLabel", font=FONTE_SUBTITULO).pack(anchor="w")
        if periodo:
            ttk.Label(self.corpo, text=periodo, style="Suave.TLabel").pack(anchor="w", pady=(2, 6))
        ttk.Label(self.corpo, text="Formato do arquivo:", style="TLabel").pack(anchor="w", pady=(8, 2))
        for valor, rotulo in self.FORMATOS:
            ttk.Radiobutton(self.corpo, text=rotulo, value=valor, variable=self._formato).pack(anchor="w", padx=8)
        quadro = ttk.Frame(self.corpo, style="TFrame")
        quadro.pack(fill="x", pady=(10, 4))
        ttk.Label(quadro, text="Salvar em:", style="TLabel").pack(side="left")
        ttk.Button(quadro, text="Escolher pasta e nome...", command=self._escolher).pack(side="right")
        self.rotulo_destino = ttk.Label(self.corpo, text="(será sugerido automaticamente)", style="Suave.TLabel",
                                        wraplength=470, justify="left")
        self.rotulo_destino.pack(anchor="w")
        ttk.Checkbutton(self.corpo, text="Abrir a pasta após salvar", variable=self._abrir).pack(anchor="w", pady=(10, 0))
        self.barra_botoes((("Exportar", self._exportar, "Primario.TButton"), ("Cancelar", self.cancelar, "TButton")))

    def _escolher(self):
        formato = self._formato.get()
        sugestao = exportacao_mod.caminho_sugerido(self.title(), formato, pasta=Path.home())
        tipos = {"xlsx": [("Excel", "*.xlsx")], "pdf": [("PDF", "*.pdf")], "csv": [("CSV", "*.csv")]}[formato]
        caminho = filedialog.asksaveasfilename(
            parent=self, title="Salvar como", initialfile=sugestao.name, initialdir=str(Path.home()),
            filetypes=tipos + [("Todos os arquivos", "*.*")], defaultextension=f".{formato}",
        )
        if caminho:
            self._caminho.set(caminho)
            self.rotulo_destino.configure(text=caminho)

    def _exportar(self):
        self.confirmar({"formato": self._formato.get(), "caminho": self._caminho.get(), "abrir": bool(self._abrir.get())})


def exportar_dados(mestre, tema: Tema, titulo: str, colunas: Sequence[dict], linhas: Sequence[dict],
                   periodo: str = "", filtros: str = "", totais: dict | None = None,
                   resumo: Sequence[str] = ()) -> str | None:
    """Fluxo completo de exportação: pergunta o formato, salva e mostra o resultado.

    Devolve o caminho do arquivo gerado ou ``None`` se o usuário cancelar.
    """
    if not linhas:
        dialogs.alerta(mestre, tema, "Não há registros para exportar nesta tela (a lista está vazia).")
        return None
    escolha = DialogoExportar(mestre, tema, titulo, len(linhas), periodo).abrir()
    if not escolha:
        return None
    formato = escolha["formato"]
    destino = escolha["caminho"]
    if not destino:
        pasta = filedialog.askdirectory(parent=mestre, title="Escolha a pasta de destino", initialdir=str(Path.home()))
        if not pasta:
            return None
        destino = str(Path(pasta) / exportacao_mod.caminho_sugerido(titulo, formato, pasta=pasta).name)
    dados = {
        "chave": titulo,
        "titulo": titulo,
        "periodo": periodo,
        "filtros": filtros,
        "colunas": colunas_para_exportacao(colunas),
        "linhas": limpar_dados_exportacao(colunas, linhas),
        "totais": totais or {},
        "resumo": list(resumo or []),
        "arquivo": destino,
    }
    try:
        caminho = exportacao_mod.exportar(dados, destino, formato)
    except exportacao_mod.ErroExportacao as exc:
        dialogs.erro(mestre, tema, str(exc), "Falha na exportação")
        return None
    except PermissionError:
        dialogs.erro(mestre, tema,
                     "Não foi possível gravar o arquivo — ele pode estar aberto em outro programa.\n"
                     "Feche o arquivo e tente novamente.", "Falha na exportação")
        return None
    dialogs.sucesso(mestre, tema, f"Arquivo gerado com sucesso:\n{caminho}", "Exportação concluída")
    if escolha.get("abrir"):
        abrir_pasta_do_arquivo(caminho)
    return caminho


def abrir_pasta_do_arquivo(caminho: str | Path) -> None:
    """Abre o gerenciador de arquivos destacando o arquivo (Windows/macOS/Linux)."""
    caminho = Path(caminho)
    pasta = caminho.parent
    try:
        if tk._default_root and tk._default_root.tk.call("info", "platform") == "windows":  # type: ignore[attr-defined]
            subprocess.Popen(["explorer", "/select,", str(caminho)])
            return
    except Exception:
        pass
    impressao_mod.abrir_pasta(pasta)


def abrir_arquivo(caminho: str | Path) -> tuple[bool, str]:
    """Abre o arquivo com o programa padrão do sistema (PDF, imagem, planilha...)."""
    return impressao_mod.imprimir_arquivo(caminho, silencioso=False)


def imprimir_documento(mestre, tema: Tema, caminho: str | Path, titulo: str = "documento") -> None:
    """Gera/abre um PDF e oferece impressão direta."""
    caminho = Path(caminho)
    if not caminho.exists():
        dialogs.erro(mestre, tema, f"Arquivo não encontrado:\n{caminho}", "Impressão")
        return
    resposta = dialogs.mensagem(
        mestre, tema, "Impressão",
        f"{titulo} gerado em:\n{caminho}\n\nO que deseja fazer?",
        "pergunta", ("Imprimir", "Abrir", "Fechar"),
    )
    if resposta == "Imprimir":
        ok, mensagem = impressao_mod.imprimir_arquivo(caminho, silencioso=False)
        if ok:
            dialogs.sucesso(mestre, tema, "Enviado para a impressora padrão.\n" + mensagem)
        else:
            dialogs.alerta(mestre, tema, f"Não foi possível imprimir automaticamente.\n{mensagem}\n\n"
                                         "O arquivo será aberto para você imprimir manualmente.")
            abrir_arquivo(caminho)
    elif resposta == "Abrir":
        ok, mensagem = abrir_arquivo(caminho)
        if not ok:
            dialogs.alerta(mestre, tema, mensagem)


# --------------------------------------------------------------------------------------
# Tela base
# --------------------------------------------------------------------------------------


class Tela(ttk.Frame):
    """Tela com cabeçalho (título, descrição e ações) e área de conteúdo."""

    titulo: str = ""
    descricao: str = ""

    def __init__(self, mestre, ctx):
        super().__init__(mestre, style="TFrame")
        self.ctx = ctx
        self.banco = ctx.banco
        self.tema = ctx.tema
        self.usuario = ctx.usuario
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._cabecalho()
        self.corpo = ttk.Frame(self, style="TFrame")
        self.corpo.grid(row=2, column=0, sticky="nsew")
        self.corpo.columnconfigure(0, weight=1)
        self.corpo.rowconfigure(0, weight=1)

    # --- cabeçalho --------------------------------------------------------------
    def _cabecalho(self):
        topo = ttk.Frame(self, style="TFrame")
        topo.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        topo.columnconfigure(0, weight=1)
        ttk.Label(topo, text=self.titulo, style="TLabel", font=FONTE_TITULO).grid(row=0, column=0, sticky="w")
        if self.descricao:
            ttk.Label(topo, text=self.descricao, style="Suave.TLabel", wraplength=900,
                      justify="left").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.quadro_acoes = ttk.Frame(topo, style="TFrame")
        self.quadro_acoes.grid(row=0, column=1, rowspan=2, sticky="ne")
        self.barra: BarraFerramentas | None = None  # montada por _montar_barra()

    # --- utilidades -------------------------------------------------------------
    def pode(self, chave: str) -> bool:
        return self.ctx.pode(chave)

    def exigir(self, chave: str, acao: str) -> bool:
        return self.ctx.exigir_permissao(chave, acao)

    def status(self, texto: str):
        self.ctx.status(texto)

    def carregar(self):
        """(Re)carrega os dados da tela — sobrescrever nas subclasses."""

    def focar_busca(self):
        """Ctrl+B — sobrescrever para focar o campo de busca da tela."""

    def focar_principal(self):
        """Chamado ao abrir a tela: devolve o foco ao campo principal."""

    def ao_tecla(self, tecla: str) -> bool:
        """Retorne ``True`` para consumir a tecla e impedir a ação global."""
        return False

    def ao_entrar(self):
        """Chamado sempre que a tela é exibida."""

    def ao_sair(self):
        """Retorne ``False`` para impedir a troca de tela (ex.: venda em andamento)."""
        return True

    def receber_parametros(self, parametros: dict):
        """Recebe parâmetros passados por outra tela (ex.: abrir um produto)."""

    def atualizar_tema(self):
        """Reagir à troca de tema claro/escuro."""

    def _montar_barra(self, botoes: Sequence[tuple] = (), lado_direito: Sequence[tuple] = ()) -> BarraFerramentas:
        barra = BarraFerramentas(self, self.tema, botoes=botoes, lado_direito=lado_direito)
        barra.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.barra = barra
        return barra


# --------------------------------------------------------------------------------------
# Tela com grade de dados (lista/CRUD)
# --------------------------------------------------------------------------------------


class TelaLista(Tela):
    """Tela padrão de listagem: toolbar + filtros + tabela + painel de detalhes.

    Subclasses informam, no mínimo, ``colunas`` e ``carregar_dados``; para ter
    cadastro/edição/exclusão completos basta implementar ``campos_formulario``,
    ``valores_formulario``, ``salvar_registro`` e ``excluir_registro``.
    """

    permissao_editar: str = ""
    permissao_excluir: str = ""

    def __init__(
        self,
        mestre,
        ctx,
        colunas: Sequence[dict],
        carregar_dados: Callable[[], Iterable[dict]],
        resumo: Callable[[Sequence[dict]], str] | None = None,
        novo: Callable[[dict], Any] | None = None,
        editar: Callable[[dict, dict], Any] | None = None,
        excluir: Callable[[dict], Any] | None = None,
        ao_selecionar: Callable[[dict | None], None] | None = None,
        ao_duplo_clique: Callable[[dict], None] | None = None,
        detalhes: Callable[[dict], list[tuple[str, str]]] | None = None,
        acoes: Sequence[tuple] = (),
        filtros: Callable[[tk.Widget], None] | None = None,
        titulo_exportacao: str = "",
        tamanho_pagina: int = 0,
        modo_selecao: str = "browse",
        altura_tabela: int = 18,
        texto_vazio: str = "",
    ):
        super().__init__(mestre, ctx)
        self.colunas = [dict(c) for c in colunas]
        self.carregar_dados = carregar_dados
        self.fn_resumo = resumo
        self.fn_novo = novo
        self.fn_editar = editar
        self.fn_excluir = excluir
        self.fn_ao_selecionar = ao_selecionar
        self.fn_ao_duplo_clique = ao_duplo_clique
        self.fn_detalhes = detalhes
        self.acoes = list(acoes)
        self.filtros_funcao = filtros
        self.titulo_exportacao = titulo_exportacao or self.titulo
        self.texto_vazio = texto_vazio
        self.modo_selecao = modo_selecao
        self.altura_tabela = altura_tabela
        self.tamanho_pagina = int(tamanho_pagina or 0)
        self.filtro_valores: dict[str, Any] = {}
        self._dados: list[dict] = []
        self._montar_interface()
        self._registrar_teclas()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        botoes: list[tuple] = []
        if self.fn_novo:
            botoes.append(("＋ Novo", self.novo, "Primario.TButton", "Ctrl+N"))
        if self.fn_editar:
            botoes.append(("✎ Editar", self.editar, "TButton", "Enter"))
        if self.fn_excluir:
            botoes.append(("🗑 Excluir", self.excluir, "TButton", "Del"))
        for texto, comando, estilo, atalho in self.acoes:
            botoes.append((texto, comando, estilo, atalho))
        botoes.append(("⟳ Atualizar", self.carregar, "TButton", "Ctrl+R"))
        lado_direito = [("⭳ Exportar", self.exportar, "TButton")]
        self._montar_barra(botoes, lado_direito)

        if self.filtros_funcao:
            self.quadro_filtros = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
            self.quadro_filtros.grid(row=2, column=0, sticky="ew", pady=(0, 6))
            self.filtros_funcao(self.quadro_filtros)

        self.tabela = Tabela(
            self, self.tema, self.colunas,
            ao_selecionar=self._ao_selecionar,
            ao_duplo_clique=self._duplo_clique,
            selecao=self.modo_selecao,
            tamanho_pagina=self.tamanho_pagina,
            altura=self.altura_tabela,
        )
        self.tabela.grid(row=3, column=0, sticky="nsew")
        # A linha 2 (onde a classe base cria ``self.corpo``) fica só com os filtros:
        # todo o espaço extra pertence à tabela.
        self.corpo.grid_remove()
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=1)

        self.painel_detalhes = ttk.Frame(self, style="Card.TFrame", padding=10)
        self.painel_detalhes.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.painel_detalhes.grid_remove()
        self.canvas_detalhes = tk.Canvas(self.painel_detalhes, height=110, highlightthickness=0,
                                         background=self.tema.cor("bg_card"))
        self.canvas_detalhes.pack(fill="both", expand=True)
        self.texto_detalhes = tk.Text(self.canvas_detalhes, wrap="word", height=5, borderwidth=0,
                                      font=FONTE_PEQUENA, background=self.tema.cor("bg_card"),
                                      foreground=self.tema.cor("fg"), state="disabled")
        self.canvas_detalhes.create_window((0, 0), window=self.texto_detalhes, anchor="nw")

        if self.barra is not None:
            if self.fn_novo:
                self.barra.habilitar("＋ Novo", self._pode_editar())
            if self.fn_editar:
                self.barra.habilitar("✎ Editar", self._pode_editar())
            if self.fn_excluir:
                self.barra.habilitar("🗑 Excluir", self._pode_excluir())

    def _registrar_teclas(self):
        for sequencia, comando in (
            ("<Control-n>", self.novo),
            ("<Control-N>", self.novo),
            ("<Control-e>", self.exportar),
            ("<Control-E>", self.exportar),
            ("<Control-r>", self.carregar),
            ("<Control-R>", self.carregar),
            ("<Control-b>", self.focar_busca),
            ("<Control-B>", self.focar_busca),
            ("<Delete>", self.excluir),
            ("<Return>", self._enter),
        ):
            self.bind(sequencia, lambda e, c=comando: self._executar_tecla(c))

    def _executar_tecla(self, comando: Callable):
        if comando is None or not callable(comando):
            return None
        resultado = comando()
        return "break"

    def _enter(self):
        if self.fn_editar:
            return self.editar()
        return self._duplo_clique(self.tabela.linha_selecionada())

    # ------------------------------------------------------------------ permissões
    def _pode_editar(self) -> bool:
        return (not self.permissao_editar) or self.pode(self.permissao_editar)

    def _pode_excluir(self) -> bool:
        return (not self.permissao_excluir) or self.pode(self.permissao_excluir)

    # ------------------------------------------------------------------ dados
    def carregar(self):
        try:
            dados = list(self.carregar_dados() or [])
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao carregar os dados desta tela.")
            dados = []
        for linha in dados:
            tag = self._tag_linha(linha)
            if tag:
                linha["_tag"] = tag
        self._dados = dados
        resumo = self.fn_resumo(dados) if self.fn_resumo else ""
        if not dados and self.texto_vazio:
            resumo = self.texto_vazio
        self.tabela.carregar(dados, resumo=resumo)
        self.status(f"{self.titulo}: {len(dados)} registro(s).")
        if self.fn_detalhes:
            self.painel_detalhes.grid_remove()

    def _tag_linha(self, linha: dict) -> str:
        """Cor de fundo da linha (``perigo``, ``alerta``, ``sucesso``...)."""
        return ""

    def registros(self) -> list[dict]:
        return self.tabela.registros()

    def selecionado(self) -> dict | None:
        return self.tabela.linha_selecionada()

    def exigir_selecao(self) -> dict | None:
        linha = self.selecionado()
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione um registro na tabela para continuar.")
        return linha

    # ------------------------------------------------------------------ seleção
    def _ao_selecionar(self, linha: dict | None):
        if linha and self.fn_detalhes:
            self._mostrar_detalhes(linha)
        elif self.fn_detalhes:
            self.painel_detalhes.grid_remove()
        if self.fn_ao_selecionar:
            try:
                self.fn_ao_selecionar(linha)
            except Exception as exc:
                self.ctx.avisar_erro(exc)

    def _mostrar_detalhes(self, linha: dict):
        try:
            pares = list(self.fn_detalhes(linha) or [])
        except Exception:
            pares = []
        self.texto_detalhes.configure(state="normal")
        self.texto_detalhes.delete("1.0", "end")
        for rotulo, valor in pares:
            if not valor:
                continue
            self.texto_detalhes.insert("end", f"{rotulo}: ", "rotulo")
            self.texto_detalhes.insert("end", f"{valor}\n")
        self.texto_detalhes.tag_configure("rotulo", font=("Segoe UI", 9, "bold"))
        self.texto_detalhes.configure(state="disabled", background=self.tema.cor("bg_card"),
                                      foreground=self.tema.cor("fg"))
        self.canvas_detalhes.configure(background=self.tema.cor("bg_card"))
        self.painel_detalhes.grid()
        self.painel_detalhes.update_idletasks()
        try:
            self.canvas_detalhes.configure(scrollregion=self.canvas_detalhes.bbox("all"))
        except tk.TclError:
            pass

    def _duplo_clique(self, linha: dict | None):
        if not linha:
            return
        if self.fn_ao_duplo_clique:
            self.fn_ao_duplo_clique(linha)
        elif self.fn_editar:
            self.editar()

    # ------------------------------------------------------------------ CRUD
    def novo(self):
        if self.fn_novo is None:
            return
        if not self._pode_editar():
            self.exigir(self.permissao_editar, "cadastrar/editar registros nesta tela")
            return
        try:
            self.fn_novo(self)
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Não foi possível concluir o cadastro.")

    def editar(self, linha: dict | None = None):
        if self.fn_editar is None:
            return
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        if not self._pode_editar():
            self.exigir(self.permissao_editar, "editar registros nesta tela")
            return
        try:
            self.fn_editar(self, linha)
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Não foi possível salvar as alterações.")

    def excluir(self, linha: dict | None = None):
        if self.fn_excluir is None:
            return
        linha = linha or self.exigir_selecao()
        if not linha:
            return None
        if not self._pode_excluir():
            self.exigir(self.permissao_excluir, "excluir registros nesta tela")
            return None
        try:
            resultado = self.fn_excluir(self, linha)
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Não foi possível excluir o registro.")
            return None
        return resultado

    # ------------------------------------------------------------------ exportação
    def exportar(self):
        linhas = self.tabela.registros()
        if not linhas:
            dialogs.alerta(self, self.tema, "Não há registros para exportar nesta tela.")
            return None
        caminho = exportar_dados(
            self, self.tema, self.titulo_exportacao, self.colunas, linhas,
            periodo=self.periodo_exportacao(), filtros=self.filtros_texto(),
        )
        if caminho:
            self.status(f"Exportado: {caminho}")
        return caminho

    def periodo_exportacao(self) -> str:
        from ...utils import hoje

        return f"Gerado em {hoje()}"

    def filtros_texto(self) -> str:
        ativos = [f"{chave}={valor}" for chave, valor in self.filtro_valores.items() if valor not in ("", None, "todos")]
        return "; ".join(ativos)

    # ------------------------------------------------------------------ busca / tema
    def focar_busca(self):
        if getattr(self, "tabela", None) is not None:
            self.tabela.focar_busca()

    def atualizar_tema(self):
        if getattr(self, "tabela", None) is not None:
            self.tabela.atualizar_tema()
        if getattr(self, "texto_detalhes", None) is not None:
            self.texto_detalhes.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"))
            self.canvas_detalhes.configure(background=self.tema.cor("bg_card"))
        self.painel_detalhes.configure(style="Card.TFrame")

    def imprimir_lista(self):
        """Gera um PDF com a tabela exibida e oferece impressão."""
        linhas = self.tabela.registros()
        if not linhas:
            dialogs.alerta(self, self.tema, "Não há registros para imprimir.")
            return
        try:
            caminho = exportacao_mod.exportar(
                {
                    "chave": self.titulo_exportacao,
                    "titulo": self.titulo_exportacao,
                    "periodo": self.periodo_exportacao(),
                    "colunas": colunas_para_exportacao(self.colunas),
                    "linhas": limpar_dados_exportacao(self.colunas, linhas),
                    "totais": {},
                    "resumo": [],
                },
                exportacao_mod.caminho_sugerido(self.titulo_exportacao, "pdf"),
                "pdf",
            )
        except exportacao_mod.ErroExportacao as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        imprimir_documento(self, self.tema, caminho, self.titulo_exportacao)


# --------------------------------------------------------------------------------------
# Formulário auxiliar (evita repetir código nas telas)
# --------------------------------------------------------------------------------------


def abrir_formulario(tela: Tela, titulo: str, campos: Sequence[dict], valores: dict | None = None,
                     texto: str = "", largura: int = 520, validar: Callable[[dict], str] | None = None) -> dict | None:
    """Abre um formulário modal ligado à tela (usa a janela principal como mestre)."""
    return dialogs.formulario(tela.ctx.janela, tela.tema, titulo, campos, valores, largura=largura,
                              texto=texto, validar=validar)
