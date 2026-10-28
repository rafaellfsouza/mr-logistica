"""
Janela principal do MR Logística.

Responsabilidades deste módulo:
  * criar a janela raiz e aplicar o tema (claro/escuro);
  * exibir o **login** e controlar o usuário da sessão;
  * montar o **menu lateral** com todos os módulos, respeitando permissões;
  * hospedar as telas (``mrlog/gui/telas/*.py``) em uma área central;
  * barra de status (usuário, caixa, data/hora) e atalhos globais de teclado;
  * bloqueio automático por inatividade e troca de usuário.

As telas são carregadas sob demanda (importação preguiçosa), o que deixa a
abertura do sistema rápida mesmo com muitos módulos.
"""

from __future__ import annotations

import importlib
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any, Callable

from .. import NOME_APP, __version__
from .. import caixa as caixa_mod
from .. import configuracoes as config_mod
from .. import usuarios as usuarios_mod
from ..banco import Banco
from ..caminhos import caminho_icone, caminho_icone_exe, pasta_dados
from .tema import FONTE_BASE, FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO, Tema
from .widgets import BarraStatus, EtiquetaEstado

# --------------------------------------------------------------------------------------
# Registro de telas
# --------------------------------------------------------------------------------------

#: Cada item descreve um módulo do menu lateral.
#: ``modulo`` é o caminho do módulo Python e ``classe`` o nome da classe da tela.
TELAS: list[dict] = [
    # --- grupo, id, rótulo, ícone, permissão, módulo, classe, atalho
    {"grupo": "Operação", "id": "painel", "rotulo": "Painel", "icone": "📊", "permissao": "painel",
     "modulo": "painel_tela", "classe": "PainelTela", "atalho": "F1", "favorito": True},
    {"grupo": "Operação", "id": "pdv", "rotulo": "PDV — Frente de Caixa", "icone": "🛒", "permissao": "pdv",
     "modulo": "pdv_tela", "classe": "PdvTela", "atalho": "F2", "favorito": True},
    {"grupo": "Operação", "id": "vendas", "rotulo": "Vendas", "icone": "🧾", "permissao": "vendas",
     "modulo": "vendas_tela", "classe": "VendasTela", "atalho": "F3"},
    {"grupo": "Operação", "id": "caixa", "rotulo": "Caixa", "icone": "💵", "permissao": "caixa",
     "modulo": "caixa_tela", "classe": "CaixaTela", "atalho": "F4", "favorito": True},

    {"grupo": "Cadastros", "id": "produtos", "rotulo": "Produtos", "icone": "📦", "permissao": "produtos",
     "modulo": "produtos_tela", "classe": "ProdutosTela", "atalho": "F5", "favorito": True},
    {"grupo": "Cadastros", "id": "categorias", "rotulo": "Categorias", "icone": "🏷️", "permissao": "categorias",
     "modulo": "categorias_tela", "classe": "CategoriasTela"},
    {"grupo": "Cadastros", "id": "clientes", "rotulo": "Clientes", "icone": "👤", "permissao": "clientes",
     "modulo": "clientes_tela", "classe": "ClientesTela", "atalho": "F6"},
    {"grupo": "Cadastros", "id": "fornecedores", "rotulo": "Fornecedores", "icone": "🚚", "permissao": "fornecedores",
     "modulo": "fornecedores_tela", "classe": "FornecedoresTela"},
    {"grupo": "Cadastros", "id": "usuarios", "rotulo": "Usuários", "icone": "🔐", "permissao": "usuarios",
     "modulo": "usuarios_tela", "classe": "UsuariosTela"},

    {"grupo": "Estoque", "id": "estoque", "rotulo": "Movimentações", "icone": "🔄", "permissao": "estoque",
     "modulo": "estoque_tela", "classe": "EstoqueTela", "atalho": "F7"},
    {"grupo": "Estoque", "id": "ajuste", "rotulo": "Ajuste de inventário", "icone": "📝", "permissao": "estoque_movimentar",
     "modulo": "ajuste_tela", "classe": "AjusteTela"},
    {"grupo": "Estoque", "id": "lotes", "rotulo": "Lotes e validade", "icone": "📅", "permissao": "estoque",
     "modulo": "lotes_tela", "classe": "LotesTela"},

    {"grupo": "Financeiro", "id": "contas_receber", "rotulo": "Contas a receber", "icone": "📥", "permissao": "contas_receber",
     "modulo": "contas_receber_tela", "classe": "ContasReceberTela", "atalho": "F8"},
    {"grupo": "Financeiro", "id": "contas_pagar", "rotulo": "Contas a pagar", "icone": "📤", "permissao": "contas_pagar",
     "modulo": "contas_pagar_tela", "classe": "ContasPagarTela", "atalho": "F9"},

    {"grupo": "Ferramentas", "id": "relatorios", "rotulo": "Relatórios", "icone": "📈", "permissao": "relatorios",
     "modulo": "relatorios_tela", "classe": "RelatoriosTela", "atalho": "F10", "favorito": True},
    {"grupo": "Ferramentas", "id": "etiquetas", "rotulo": "Etiquetas de código de barras", "icone": "🖨️",
     "permissao": "etiquetas", "modulo": "etiquetas_tela", "classe": "EtiquetasTela", "atalho": "F11"},
    {"grupo": "Ferramentas", "id": "backup", "rotulo": "Backup e restauração", "icone": "💾", "permissao": "backup",
     "modulo": "backup_tela", "classe": "BackupTela"},
    {"grupo": "Ferramentas", "id": "configuracoes", "rotulo": "Configurações", "icone": "⚙️", "permissao": "configuracoes",
     "modulo": "configuracoes_tela", "classe": "ConfiguracoesTela", "atalho": "F12"},
]

GRUPOS_ORDEM = ("Operação", "Cadastros", "Estoque", "Financeiro", "Ferramentas")


def tela_por_id(identificador: str) -> dict | None:
    for item in TELAS:
        if item["id"] == identificador:
            return item
    return None


# --------------------------------------------------------------------------------------
# Contexto compartilhado entre as telas
# --------------------------------------------------------------------------------------


class Contexto:
    """Tudo o que uma tela precisa para funcionar.

    As telas recebem este objeto no construtor e usam ``ctx.banco``,
    ``ctx.usuario``, ``ctx.pode(...)``, ``ctx.navegar(...)``, ``ctx.info(...)`` etc.
    Isso evita que cada tela precise conhecer a janela principal.
    """

    def __init__(self, app: "Aplicacao", banco: Banco, tema: Tema):
        self.app = app
        self.banco = banco
        self.tema = tema
        self.usuario: Any = None
        self.caixa_aberto: Any = None
        self.modo_teste = bool(getattr(app, "sem_login", False))
        self.erros_teste: list[str] = []

    @property
    def janela(self) -> tk.Tk:
        """Janela principal (propriedade para não depender da ordem de criação)."""
        return self.app.janela

    # --- sessão -------------------------------------------------------------------
    @property
    def perfil(self) -> str:
        return str(self.usuario["perfil"]) if self.usuario else ""

    @property
    def nome_usuario(self) -> str:
        return str(self.usuario["nome"]) if self.usuario else "—"

    def pode(self, chave: str) -> bool:
        return usuarios_mod.pode(self.usuario, chave)

    def limite_desconto(self) -> float:
        return usuarios_mod.limite_desconto(self.usuario)

    def atualizar_usuario(self, usuario) -> None:
        """Recarrega os dados da sessão (usado quando o próprio cadastro é editado)."""
        self.usuario = usuario
        try:
            self.app._atualizar_cabecalho_usuario()
            self.app._atualizar_status()
        except Exception:
            pass

    def exigir_permissao(self, chave: str, acao: str = "") -> bool:
        """Se o usuário não tem a permissão, avisa e devolve ``False``."""
        if self.pode(chave):
            return True
        if self.modo_teste:
            self.erros_teste.append(f"permissão negada: {chave} ({acao})")
            return False
        from . import dialogs

        dialogs.erro(
            self.janela, self.tema,
            f"Você não tem permissão para {acao or 'executar esta ação'}.\n"
            f"Perfil atual: {usuarios_mod.ROTULOS_PERFIS.get(self.perfil, self.perfil)}.\n\n"
            "Peça a liberação a um administrador do sistema.",
            "Acesso negado",
        )
        return False

    # --- navegação ----------------------------------------------------------------
    def navegar(self, tela_id: str, parametros: dict | None = None):
        self.app.abrir_tela(tela_id, parametros)

    def tela_atual(self):
        return self.app.tela_atual

    # --- mensagens ----------------------------------------------------------------
    def status(self, texto: str):
        self.app.barra_status.definir(texto=texto)

    def info(self, texto: str, titulo: str = "Aviso"):
        if self.modo_teste:
            self.erros_teste.append(f"[info] {texto}")
            return
        from . import dialogs

        dialogs.info(self.janela, self.tema, texto, titulo)

    def sucesso(self, texto: str, titulo: str = "Concluído"):
        if self.modo_teste:
            print(f"      [sucesso] {texto.splitlines()[0]}", flush=True)
            return
        from . import dialogs

        dialogs.sucesso(self.janela, self.tema, texto, titulo)

    def alerta(self, texto: str, titulo: str = "Atenção"):
        if self.modo_teste:
            self.erros_teste.append(f"[alerta] {texto}")
            return
        from . import dialogs

        dialogs.alerta(self.janela, self.tema, texto, titulo)

    def erro(self, texto: str, titulo: str = "Erro"):
        if self.modo_teste:
            self.erros_teste.append(f"[erro] {texto}")
            return
        from . import dialogs

        dialogs.erro(self.janela, self.tema, texto, titulo)

    def confirmar(self, texto: str, titulo: str = "Confirmação", sim: str = "Sim", nao: str = "Não") -> bool:
        if self.modo_teste:
            return False  # nunca confirma ações destrutivas durante os testes
        from . import dialogs

        return dialogs.confirmar(self.janela, self.tema, texto, titulo, sim, nao)

    def avisar_erro(self, exc: Exception, contexto: str = ""):
        if self.modo_teste:
            import traceback

            traceback.print_exc()
            self.erros_teste.append(f"[exceção] {contexto} {exc}")
            return
        from . import dialogs

        dialogs.avisar_erro(self.janela, self.tema, exc, contexto)

    def senha_supervisor(self, motivo: str = "") -> bool:
        """Liberação por senha de administrador (desconto acima do limite etc.)."""
        from . import dialogs

        usuarios = usuarios_mod.listar(self.banco, incluir_inativos=False)
        administradores = [u for u in usuarios if u["perfil"] == "administrador"]
        if not administradores:
            self.erro("Nenhum administrador ativo cadastrado para autorizar esta operação.")
            return False
        escolha = administradores[0]
        if len(administradores) > 1:
            linha = dialogs.selecionar_registro(
                self.janela, self.tema, "Autorização de supervisor",
                [{"chave": "nome", "rotulo": "Administrador", "largura": 220},
                 {"chave": "login", "rotulo": "Login", "largura": 140}],
                [dict(u) for u in administradores],
                texto=f"{motivo}\n\nSelecione o administrador que autoriza:".strip(),
                largura=460,
            )
            if not linha:
                return False
            escolha = usuarios_mod.pegar(self.banco, linha["id"])
        resultado = dialogs.pedir_senha(
            self.janela, self.tema, "Autorização de supervisor",
            texto=f"{motivo}\n\nAdministrador: {escolha['nome']} ({escolha['login']})".strip(),
        )
        if not resultado:
            return False
        try:
            autenticado = usuarios_mod.autenticar(self.banco, escolha["login"], resultado.get("senha", ""))
        except usuarios_mod.ErroUsuario as exc:
            self.erro(str(exc))
            return False
        if not autenticado:
            self.erro("Senha incorreta. Operação não autorizada.")
            return False
        self.banco.registrar_log(
            "autorizacao", f"{motivo or 'liberação'} autorizada por {escolha['login']}",
            self.usuario["id"] if self.usuario else None, self.nome_usuario,
        )
        return True


# --------------------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------------------


class JanelaLogin(tk.Toplevel):
    """Tela de acesso (modal). Devolve o usuário autenticado em ``resultado``."""

    def __init__(self, mestre: tk.Tk, banco: Banco, tema: Tema, titulo: str = "Acesso ao sistema"):
        super().__init__(mestre)
        self.banco = banco
        self.tema = tema
        self.resultado = None
        self.titulo_janela = titulo
        self.title(titulo)
        self.configure(background=tema.cor("bg"))
        self.resizable(False, False)
        self.transient(mestre)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self._montar()
        self._centralizar()
        self.bind("<Return>", lambda e: self._entrar())
        self.bind("<Escape>", lambda e: self._fechar())

    def _montar(self):
        tema = self.tema
        quadro = ttk.Frame(self, style="Card.TFrame", padding=22)
        quadro.pack(fill="both", expand=True, padx=14, pady=14)

        topo = ttk.Frame(quadro, style="TFrame")
        topo.pack(fill="x")
        tk.Label(topo, text="MR", font=("Segoe UI", 26, "bold"), background=tema.cor("bg_card"),
                 foreground=tema.cor("primaria")).pack(side="left")
        ttk.Label(topo, text=f"{NOME_APP}\nGestão comercial, estoque e PDV", style="TLabel",
                  font=FONTE_SUBTITULO, justify="left").pack(side="left", padx=(10, 0))

        ttk.Separator(quadro, orient="horizontal").pack(fill="x", pady=(14, 12))

        usuarios = usuarios_mod.listar(self.banco, incluir_inativos=False)
        nomes = [u["nome"] for u in usuarios] or ["admin"]
        ttk.Label(quadro, text="Usuário", style="TLabel").pack(anchor="w")
        self.combo_usuario = ttk.Combobox(quadro, values=nomes, state="normal", width=34)
        self.combo_usuario.pack(fill="x", pady=(2, 8))
        if nomes:
            self.combo_usuario.set(nomes[0])

        ttk.Label(quadro, text="Senha", style="TLabel").pack(anchor="w")
        self.entrada_senha = ttk.Entry(quadro, show="•", width=34)
        self.entrada_senha.pack(fill="x", pady=(2, 8))
        self.entrada_senha.focus_set()

        self.rotulo_erro = ttk.Label(quadro, text="", foreground=tema.cor("perigo"), wraplength=320, justify="left")
        self.rotulo_erro.pack(anchor="w", pady=(0, 4))

        botoes = ttk.Frame(quadro, style="TFrame")
        botoes.pack(fill="x", pady=(6, 0))
        ttk.Button(botoes, text="Entrar", style="Primario.TButton", command=self._entrar).pack(side="left")
        ttk.Button(botoes, text="Sair", command=self._fechar).pack(side="left", padx=(8, 0))

        rodape = ttk.Frame(quadro, style="TFrame")
        rodape.pack(fill="x", pady=(14, 0))
        ttk.Label(
            rodape,
            text="Primeiro acesso: usuário admin / senha admin\n(o sistema pede a troca da senha).",
            style="Suave.TLabel", justify="left", wraplength=320,
        ).pack(side="left")
        ttk.Label(rodape, text=f"v{__version__}", style="Suave.TLabel").pack(side="right")

    def _centralizar(self):
        self.update_idletasks()
        largura, altura = self.winfo_reqwidth(), self.winfo_reqheight()
        mestre = self.master
        x = mestre.winfo_rootx() + (mestre.winfo_width() - largura) // 2
        y = mestre.winfo_rooty() + (mestre.winfo_height() - altura) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _fechar(self):
        self.resultado = None
        self.destroy()

    def _entrar(self):
        nome = self.combo_usuario.get().strip()
        senha = self.entrada_senha.get()
        if not nome:
            self.rotulo_erro.configure(text="Selecione ou digite o usuário.")
            return
        # aceita o nome ou o login
        candidatos = usuarios_mod.listar(self.banco, incluir_inativos=False)
        alvo = next((u for u in candidatos if u["nome"].lower() == nome.lower() or u["login"].lower() == nome.lower()), None)
        login = alvo["login"] if alvo else nome
        try:
            usuario = usuarios_mod.autenticar(self.banco, login, senha)
        except usuarios_mod.ErroUsuario as exc:
            self.rotulo_erro.configure(text=str(exc))
            self.entrada_senha.delete(0, "end")
            return
        if not usuario:
            self.rotulo_erro.configure(text="Usuário ou senha incorretos.")
            self.entrada_senha.delete(0, "end")
            self.entrada_senha.focus_set()
            return
        self.resultado = usuario
        self.destroy()


# --------------------------------------------------------------------------------------
# Aplicação principal
# --------------------------------------------------------------------------------------


class Aplicacao:
    """Controla a janela principal, o menu lateral e a troca de telas."""

    LARGURA_MENU = 268

    def __init__(self, banco: Banco | None = None, tema_nome: str | None = None, sem_login: bool = False):
        self.banco = banco or Banco()
        self.sem_login = bool(sem_login)   # usado pelos testes automatizados
        self.tema = Tema(tema_nome or self.banco.config_pegar("tema", "claro"))
        self.contexto = Contexto(self, self.banco, self.tema)
        self._telas: dict[str, Any] = {}
        self._botoes_menu: dict[str, tk.Widget] = {}
        self.tela_id_atual: str = ""
        self._ultimo_evento = time.time()
        self._relogio_job = None
        self._inatividade_job = None

        self.janela = tk.Tk()
        self.janela.title(f"{NOME_APP} — v{__version__}")
        self.janela.geometry("1366x820")
        self.janela.minsize(1024, 640)
        icone = caminho_icone()
        if icone:
            try:
                self._icone = tk.PhotoImage(file=str(icone))
                self.janela.iconphoto(True, self._icone)
            except tk.TclError:
                self._icone = None
        # no Windows o .ico deixa o ícone da barra de tarefas mais nítido
        if sys.platform.startswith("win"):
            icone_exe = caminho_icone_exe()
            if icone_exe:
                try:
                    self.janela.iconbitmap(default=str(icone_exe))
                except tk.TclError:
                    pass
        self.tema.aplicar(self.janela)
        self.janela.protocol("WM_DELETE_WINDOW", self.ao_fechar)
        self._montar_layout()
        self._registrar_atalhos()
        self._observar_inatividade()

    # ------------------------------------------------------------------ layout
    def _montar_layout(self):
        raiz = self.janela
        principal = ttk.Frame(raiz, style="TFrame")
        principal.pack(fill="both", expand=True)
        principal.columnconfigure(1, weight=1)
        principal.rowconfigure(0, weight=1)

        # ---- barra superior (identidade + ações rápidas)
        topo = ttk.Frame(raiz, style="Card.TFrame", padding=(12, 8))
        topo.pack(side="top", fill="x")
        tk.Label(topo, text="MR", font=("Segoe UI", 18, "bold"), background=self.tema.cor("bg_card"),
                 foreground=self.tema.cor("primaria")).pack(side="left")
        ttk.Label(topo, text=f" {NOME_APP}", style="Card.TLabel", font=FONTE_TITULO).pack(side="left")
        self.rotulo_tela = ttk.Label(topo, text="", style="Card.Suave.TLabel", font=FONTE_SUBTITULO)
        self.rotulo_tela.pack(side="left", padx=(16, 0))

        self.quadro_acoes = ttk.Frame(topo, style="Card.TFrame")
        self.quadro_acoes.pack(side="right")
        self.etiqueta_caixa = EtiquetaEstado(self.quadro_acoes, self.tema, "neutro", "Caixa fechado")
        self.etiqueta_caixa.pack(side="right", padx=(8, 0))
        for texto, comando in (
            ("🔒 Bloquear", self.bloquear),
            ("👤 Trocar usuário", self.trocar_usuario),
            ("🌓 Tema", self.alternar_tema),
        ):
            ttk.Button(self.quadro_acoes, text=texto, command=comando, style="TButton").pack(side="right", padx=(6, 0))

        # ---- menu lateral
        self.menu = ttk.Frame(principal, style="Menu.TFrame", width=self.LARGURA_MENU, padding=(0, 6))
        self.menu.grid(row=0, column=0, sticky="ns")
        self.menu.grid_propagate(False)

        busca_quadro = ttk.Frame(self.menu, style="Menu.TFrame", padding=(10, 4, 10, 8))
        busca_quadro.pack(fill="x")
        self.entrada_busca_menu = ttk.Entry(busca_quadro, width=24)
        self.entrada_busca_menu.pack(fill="x")
        self.entrada_busca_menu.insert(0, "Buscar módulo...")
        self.entrada_busca_menu.configure(foreground=self.tema.cor("fg_fraco"))
        self.entrada_busca_menu.bind("<FocusIn>", self._busca_menu_focus)
        self.entrada_busca_menu.bind("<FocusOut>", lambda e: self._busca_menu_sair())
        self.entrada_busca_menu.bind("<KeyRelease>", lambda e: self._filtrar_menu())
        self.entrada_busca_menu.bind("<Return>", lambda e: self._abrir_primeiro_filtrado())

        self.quadro_menu = tk.Frame(self.menu, background=self.tema.cor("bg_menu"))
        self.quadro_menu.pack(fill="both", expand=True)
        self.canvas_menu = tk.Canvas(self.quadro_menu, background=self.tema.cor("bg_menu"), highlightthickness=0)
        barra_menu = ttk.Scrollbar(self.quadro_menu, orient="vertical", command=self.canvas_menu.yview)
        self.canvas_menu.configure(yscrollcommand=barra_menu.set)
        barra_menu.pack(side="right", fill="y")
        self.canvas_menu.pack(side="left", fill="both", expand=True)
        self.interno_menu = tk.Frame(self.canvas_menu, background=self.tema.cor("bg_menu"))
        self.janela_interna = self.canvas_menu.create_window((0, 0), window=self.interno_menu, anchor="nw")
        self.interno_menu.bind("<Configure>", lambda e: self.canvas_menu.configure(scrollregion=self.canvas_menu.bbox("all")))
        self.canvas_menu.bind("<Configure>", lambda e: self.canvas_menu.itemconfigure(self.janela_interna, width=e.width))
        self.canvas_menu.bind_all("<MouseWheel>", self._roda_menu)

        rodape_menu = tk.Frame(self.menu, background=self.tema.cor("bg_menu"))
        rodape_menu.pack(side="bottom", fill="x")
        self.rotulo_usuario = tk.Label(rodape_menu, text="", font=FONTE_PEQUENA, justify="left", anchor="w",
                                       background=self.tema.cor("bg_menu"), foreground=self.tema.cor("fg"))
        self.rotulo_usuario.pack(fill="x", padx=12, pady=(6, 2))
        self.rotulo_pasta = tk.Label(rodape_menu, text="", font=("Segoe UI", 8), justify="left", anchor="w",
                                     wraplength=self.LARGURA_MENU - 24,
                                     background=self.tema.cor("bg_menu"), foreground=self.tema.cor("fg_fraco"))
        self.rotulo_pasta.pack(fill="x", padx=12, pady=(0, 8))

        # ---- área de telas
        self.area = ttk.Frame(principal, style="TFrame", padding=(12, 10, 12, 4))
        self.area.grid(row=0, column=1, sticky="nsew")
        self.area.rowconfigure(0, weight=1)
        self.area.columnconfigure(0, weight=1)

        # ---- barra de status
        self.barra_status = BarraStatus(raiz, self.tema)
        self.barra_status.pack(side="bottom", fill="x")
        self.tema.registrar(self.barra_status)

        self._montar_menu()
        self._atualizar_cabecalho_usuario()

    def _roda_menu(self, evento):
        # só rola o menu quando o mouse está sobre ele
        widget = self.janela.winfo_containing(evento.x_root, evento.y_root)
        while widget is not None:
            if widget is self.canvas_menu:
                self.canvas_menu.yview_scroll(int(-1 * (evento.delta / 120)), "units")
                return "break"
            widget = getattr(widget, "master", None)
        return None

    # ------------------------------------------------------------------ menu lateral
    def _montar_menu(self):
        for filho in self.interno_menu.winfo_children():
            filho.destroy()
        self._botoes_menu.clear()
        cor_menu = self.tema.cor("bg_menu")
        favoritos = tk.Frame(self.interno_menu, background=cor_menu)
        favoritos.pack(fill="x", padx=8, pady=(2, 6))
        for item in TELAS:
            if item.get("favorito") and self._visivel(item):
                self._criar_botao(favoritos, item, compacto=True)
        tk.Frame(favoritos, height=1, background=self.tema.cor("borda")).pack(fill="x", pady=(6, 2))

        for grupo in GRUPOS_ORDEM:
            itens = [i for i in TELAS if i["grupo"] == grupo and self._visivel(i)]
            if not itens:
                continue
            rotulo = tk.Label(self.interno_menu, text=grupo.upper(), font=("Segoe UI", 8, "bold"), anchor="w",
                              background=self.tema.cor("bg_menu"), foreground=self.tema.cor("fg_fraco"))
            rotulo.pack(fill="x", padx=14, pady=(8, 2))
            rotulo.item_menu = True
            for item in itens:
                self._criar_botao(self.interno_menu, item)

    def _visivel(self, item: dict) -> bool:
        return self.contexto.pode(item["permissao"]) if item.get("permissao") else True

    def _criar_botao(self, pai: tk.Widget, item: dict, compacto: bool = False):
        cor_fundo = self.tema.cor("bg_menu")
        botao = tk.Frame(pai, background=cor_fundo, cursor="hand2")
        botao.pack(fill="x", padx=8, pady=1)
        texto = f"{item['icone']}  {item['rotulo']}" if not compacto else f"{item['icone']} {item['rotulo'].split(' —')[0]}"
        if item.get("atalho") and not compacto:
            texto += f"   ({item['atalho']})"
        rotulo = tk.Label(botao, text=texto, anchor="w", font=FONTE_PEQUENA, background=cor_fundo,
                          foreground=self.tema.cor("fg_menu"), padx=10, pady=(6 if compacto else 5))
        rotulo.pack(fill="x")
        for widget in (botao, rotulo):
            widget.bind("<Button-1>", lambda e, i=item["id"]: self.abrir_tela(i))
            widget.bind("<Enter>", lambda e, w=botao, l=rotulo: self._hover(w, l, True))
            widget.bind("<Leave>", lambda e, w=botao, l=rotulo: self._hover(w, l, False))
        botao.rotulo = rotulo
        if item["id"] in self._botoes_menu:
            anterior = self._botoes_menu[item["id"]]
            if isinstance(anterior, list):
                anterior.append(botao)
            else:
                self._botoes_menu[item["id"]] = [anterior, botao]
        else:
            self._botoes_menu[item["id"]] = botao
        return botao

    def _hover(self, quadro: tk.Frame, rotulo: tk.Label, ativo: bool):
        if getattr(quadro, "selecionado", False):
            return
        cor = self.tema.cor("bg_menu_hover") if ativo else self.tema.cor("bg_menu")
        quadro.configure(background=cor)
        rotulo.configure(background=cor)

    def _marcar_selecionado(self, tela_id: str):
        for chave, valor in self._botoes_menu.items():
            botoes = valor if isinstance(valor, list) else [valor]
            for botao in botoes:
                selecionado = chave == tela_id
                botao.selecionado = selecionado
                cor = self.tema.cor("bg_menu_ativo") if selecionado else self.tema.cor("bg_menu")
                fg = self.tema.cor("fg_menu_ativo") if selecionado else self.tema.cor("fg_menu")
                botao.configure(background=cor)
                botao.rotulo.configure(background=cor, foreground=fg,
                                       font=(FONTE_PEQUENA[0], FONTE_PEQUENA[1], "bold" if selecionado else "normal"))

    def _filtrar_menu(self):
        termo = self.entrada_busca_menu.get().strip().lower()
        if termo in ("", "buscar módulo..."):
            self._montar_menu()
            self._marcar_selecionado(self.tela_id_atual)
            return
        for filho in self.interno_menu.winfo_children():
            filho.destroy()
        self._botoes_menu.clear()
        encontrados = [i for i in TELAS if self._visivel(i) and termo in f"{i['rotulo']} {i['grupo']}".lower()]
        if not encontrados:
            tk.Label(self.interno_menu, text="Nenhum módulo encontrado.", font=FONTE_PEQUENA,
                     background=self.tema.cor("bg_menu"), foreground=self.tema.cor("fg_fraco"),
                     anchor="w", padx=14, pady=8).pack(fill="x")
            return
        for item in encontrados:
            self._criar_botao(self.interno_menu, item)

    def _abrir_primeiro_filtrado(self):
        if self._botoes_menu:
            primeiro = next(iter(self._botoes_menu))
            self.abrir_tela(primeiro)
            self._limpar_busca_menu()

    def _busca_menu_focus(self, _evento=None):
        if self.entrada_busca_menu.get().strip() == "Buscar módulo...":
            self.entrada_busca_menu.delete(0, "end")
            self.entrada_busca_menu.configure(foreground=self.tema.cor("fg"))

    def _busca_menu_sair(self):
        if not self.entrada_busca_menu.get().strip():
            self.entrada_busca_menu.insert(0, "Buscar módulo...")
            self.entrada_busca_menu.configure(foreground=self.tema.cor("fg_fraco"))
            self._montar_menu()
            self._marcar_selecionado(self.tela_id_atual)

    def _limpar_busca_menu(self):
        if self.entrada_busca_menu.get().strip() in ("", "Buscar módulo..."):
            return
        self.entrada_busca_menu.delete(0, "end")
        self.entrada_busca_menu.insert(0, "Buscar módulo...")
        self.entrada_busca_menu.configure(foreground=self.tema.cor("fg_fraco"))
        self._montar_menu()
        self._marcar_selecionado(self.tela_id_atual)

    # ------------------------------------------------------------------ telas
    @property
    def tela_atual(self):
        return self._telas.get(self.tela_id_atual)

    def abrir_tela(self, tela_id: str, parametros: dict | None = None):
        item = tela_por_id(tela_id)
        if not item:
            self.contexto.erro(f"Módulo desconhecido: '{tela_id}'.")
            return
        if not self.contexto.pode(item["permissao"]):
            self.contexto.exigir_permissao(item["permissao"], f"acessar {item['rotulo']}")
            return
        atual = self.tela_atual
        if atual is not None and hasattr(atual, "ao_sair"):
            if atual.ao_sair() is False:
                return
        if atual is not None:
            atual.grid_remove()
        tela = self._telas.get(tela_id)
        if tela is None:
            tela = self._criar_tela(item)
            if tela is None:
                return
            self._telas[tela_id] = tela
        tela.grid(row=0, column=0, sticky="nsew")
        tela.tkraise()
        self.tela_id_atual = tela_id
        self.rotulo_tela.configure(text=f"{item['icone']}  {item['rotulo']}")
        self._marcar_selecionado(tela_id)
        self._limpar_busca_menu()
        if parametros and hasattr(tela, "receber_parametros"):
            tela.receber_parametros(parametros)
        if hasattr(tela, "carregar"):
            try:
                tela.carregar()
            except Exception as exc:  # nunca deixa a tela quebrada derrubar o app
                self.contexto.avisar_erro(exc, f"Erro ao carregar {item['rotulo']}.")
        if hasattr(tela, "ao_entrar"):
            tela.ao_entrar()
        self._atualizar_status()
        if hasattr(tela, "focar_principal"):
            tela.after(80, tela.focar_principal)

    def _criar_tela(self, item: dict):
        try:
            modulo = importlib.import_module(f"mrlog.gui.telas.{item['modulo']}")
        except Exception as exc:
            self.contexto.avisar_erro(exc, f"Não foi possível abrir o módulo {item['rotulo']}.")
            return None
        classe = getattr(modulo, item["classe"], None)
        if classe is None:
            self.contexto.erro(f"Módulo {item['modulo']} não define a classe {item['classe']}.")
            return None
        try:
            return classe(self.area, self.contexto)
        except Exception as exc:
            import traceback

            traceback.print_exc()
            if self.sem_login:  # modo de teste: não abre diálogo modal
                raise
            self.contexto.avisar_erro(exc, f"Erro ao montar {item['rotulo']}.")
            return None

    def recarregar_tela_atual(self):
        tela = self.tela_atual
        if tela is not None and hasattr(tela, "carregar"):
            try:
                tela.carregar()
            except Exception as exc:
                self.contexto.avisar_erro(exc)
        self._atualizar_status()

    def tela_inicial(self):
        for preferida in ("painel", "pdv", "vendas"):
            item = tela_por_id(preferida)
            if item and self.contexto.pode(item["permissao"]):
                self.abrir_tela(preferida)
                return
        disponiveis = [i["id"] for i in TELAS if self._visivel(i)]
        if disponiveis:
            self.abrir_tela(disponiveis[0])

    # ------------------------------------------------------------------ status / cabeçalho
    def _atualizar_cabecalho_usuario(self):
        ctx = self.contexto
        self.rotulo_usuario.configure(
            text=f"{ctx.nome_usuario}\n{usuarios_mod.ROTULOS_PERFIS.get(ctx.perfil, ctx.perfil)}"
        )
        self.rotulo_pasta.configure(text=f"Dados: {pasta_dados()}")

    def _atualizar_status(self):
        from ..utils import formatar_dinheiro

        ctx = self.contexto
        try:
            ctx.caixa_aberto = caixa_mod.caixa_aberto(self.banco)
        except Exception:
            ctx.caixa_aberto = None
        if ctx.caixa_aberto:
            try:
                posicao = caixa_mod.posicao(self.banco, ctx.caixa_aberto["id"])
                dinheiro = posicao["formas"].get("Dinheiro", {})
                gaveta = int(dinheiro.get("saldo", 0) or 0)
                texto = f"Caixa aberto • {posicao['qtd_vendas']} venda(s) • {formatar_dinheiro(posicao['total_vendas'])}"
                self.etiqueta_caixa.definir("sucesso", "Caixa aberto")
                self.barra_status.definir(
                    direita=f"{texto} • Gaveta: {formatar_dinheiro(gaveta)}"
                )
            except Exception:
                self.etiqueta_caixa.definir("sucesso", "Caixa aberto")
        else:
            self.etiqueta_caixa.definir("alerta", "Caixa fechado")
            self.barra_status.definir(direita="Caixa fechado — abra o caixa (F4) para registrar vendas em dinheiro.")
        self._atualizar_relogio()

    def _atualizar_relogio(self):
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        usuario = f"{self.contexto.nome_usuario} ({usuarios_mod.ROTULOS_PERFIS.get(self.contexto.perfil, '')})"
        self.barra_status.direita.configure(text=f"{self.barra_status.direita.cget('text').split(' • ')[0]}")
        self.rotulo_relogio_texto = agora
        if not hasattr(self, "_rotulo_relogio"):
            self._rotulo_relogio = ttk.Label(self.barra_status, text="", style="Suave.TLabel")
            self._rotulo_relogio.pack(side="right", padx=(12, 0))
        self._rotulo_relogio.configure(text=f"{usuario}   |   {agora}")
        if self._relogio_job:
            self.janela.after_cancel(self._relogio_job)
        self._relogio_job = self.janela.after(30_000, self._atualizar_relogio)

    def atualizar_caixa(self):
        self._atualizar_status()

    # ------------------------------------------------------------------ atalhos
    def _registrar_atalhos(self):
        """Atalhos globais. A tela atual tem prioridade (pode consumir a tecla)."""
        janela = self.janela
        for item in TELAS:
            if item.get("atalho"):
                janela.bind_all(
                    f"<{item['atalho']}>",
                    lambda e, i=item["id"]: self._tecla_global(i),
                )
        janela.bind_all("<Control-r>", lambda e: self._acao_global(self.recarregar_tela_atual))
        janela.bind_all("<Control-R>", lambda e: self._acao_global(self.recarregar_tela_atual))
        janela.bind_all("<Control-b>", lambda e: self._acao_global(self.focar_busca))
        janela.bind_all("<Control-B>", lambda e: self._acao_global(self.focar_busca))
        janela.bind_all("<Control-n>", lambda e: self._acao_global(self.ctrl_n))
        janela.bind_all("<Control-N>", lambda e: self._acao_global(self.ctrl_n))
        janela.bind_all("<Control-l>", lambda e: self._acao_global(self.bloquear))
        janela.bind_all("<Control-L>", lambda e: self._acao_global(self.bloquear))
        janela.bind_all("<Control-u>", lambda e: self._acao_global(self.trocar_usuario))
        janela.bind_all("<Control-U>", lambda e: self._acao_global(self.trocar_usuario))
        janela.bind_all("<Control-t>", lambda e: self._acao_global(self.alternar_tema))
        janela.bind_all("<Control-T>", lambda e: self._acao_global(self.alternar_tema))
        janela.bind_all("<Control-F2>", lambda e: self._acao_global(self.nova_venda))
        janela.bind_all("<Control-e>", lambda e: self._tecla_tela("<Control-e>"))
        janela.bind_all("<Control-E>", lambda e: self._tecla_tela("<Control-E>"))
        janela.bind_all("<Control-p>", lambda e: self._tecla_tela("<Control-p>"))
        janela.bind_all("<Control-P>", lambda e: self._tecla_tela("<Control-P>"))
        # qualquer atividade reinicia o contador de bloqueio automático
        janela.bind_all("<KeyPress>", self._marcar_atividade, add="+")
        janela.bind_all("<Button-1>", self._marcar_atividade, add="+")

    def _ha_modal(self) -> bool:
        """True se há alguma janela modal aberta (evita atalhos "vazando" p/ diálogos)."""
        try:
            return self.janela.grab_current() is not None
        except tk.TclError:
            return False

    def _acao_global(self, acao: Callable):
        self._marcar_atividade()
        if self._ha_modal():
            return "break"
        try:
            acao()
        except Exception as exc:
            self.contexto.avisar_erro(exc)
        return "break"

    def _tecla_tela(self, tecla: str):
        """Encaminha a tecla apenas para a tela atual (Ctrl+E, Ctrl+P...)."""
        self._marcar_atividade()
        if self._ha_modal():
            return "break"
        tela = self.tela_atual
        if tela is not None and hasattr(tela, "ao_tecla"):
            if tela.ao_tecla(tecla):
                return "break"
        if tela is not None:
            if tecla.lower() == "<control-e>" and hasattr(tela, "exportar"):
                tela.exportar()
            elif tecla.lower() == "<control-p>" and hasattr(tela, "imprimir_lista"):
                tela.imprimir_lista()
        return "break"

    def _tecla_global(self, tela_id: str):
        """Teclas F2..F12: a tela atual tem prioridade e pode consumi-las (caso do PDV)."""
        self._marcar_atividade()
        item = tela_por_id(tela_id)
        tela = self.tela_atual
        if tela is not None and item and hasattr(tela, "ao_tecla"):
            try:
                if tela.ao_tecla(f"<{item['atalho']}>"):
                    return "break"
            except Exception as exc:
                self.contexto.avisar_erro(exc)
        self.abrir_tela(tela_id)
        return "break"

    def ctrl_n(self):
        tela = self.tela_atual
        if tela is not None and hasattr(tela, "novo"):
            tela.novo()
        elif self.contexto.pode("pdv"):
            self.abrir_tela("pdv")

    def _ajuda(self):
        self._marcar_atividade()
        self.mostrar_atalhos()
        return "break"

    def focar_busca(self):
        """Ctrl+B: busca do menu ou busca da tela atual."""
        tela = self.tela_atual
        if tela is not None and hasattr(tela, "focar_busca"):
            tela.focar_busca()
        else:
            self.entrada_busca_menu.focus_set()
            self._busca_menu_focus()

    def mostrar_atalhos(self):
        from . import dialogs

        linhas = config_mod.atalhos_de_teclado()
        texto = "\n".join(f"{item['teclas']:<26} {item['acao']}" for item in linhas)
        dialogs.mensagem(self.janela, self.tema, "Atalhos de teclado", texto, "info", ("Fechar",))

    # ------------------------------------------------------------------ tema
    def alternar_tema(self, nome: str | None = None):
        novo = nome or ("claro" if self.tema.eh_escuro else "escuro")
        self.tema.trocar(novo)
        config_mod.salvar(self.banco, {"tema": novo}, autor=self.contexto.usuario)
        self.tema.aplicar(self.janela)
        self._remontar_aparencia()
        self.barra_status.definir(texto=f"Tema {novo} aplicado.")

    def _remontar_aparencia(self):
        """Reaplica cores dos widgets tk 'puros' (menu, cartões) após trocar o tema."""
        self._montar_menu()
        self._marcar_selecionado(self.tela_id_atual)
        self.menu.configure(style="Menu.TFrame")
        self.quadro_menu.configure(background=self.tema.cor("bg_menu"))
        self.canvas_menu.configure(background=self.tema.cor("bg_menu"))
        self.interno_menu.configure(background=self.tema.cor("bg_menu"))
        self.rotulo_usuario.configure(background=self.tema.cor("bg_menu"), foreground=self.tema.cor("fg"))
        self.rotulo_pasta.configure(background=self.tema.cor("bg_menu"), foreground=self.tema.cor("fg_fraco"))
        for tela in self._telas.values():
            if hasattr(tela, "atualizar_tema"):
                try:
                    tela.atualizar_tema()
                except tk.TclError:
                    pass
        self._atualizar_status()

    # ------------------------------------------------------------------ sessão
    def _marcar_atividade(self, _evento=None):
        self._ultimo_evento = time.time()
        self._agendar_verificacao()

    def _observar_inatividade(self):
        self._agendar_verificacao()

    def _agendar_verificacao(self):
        if self._inatividade_job:
            try:
                self.janela.after_cancel(self._inatividade_job)
            except tk.TclError:
                pass
        self._inatividade_job = self.janela.after(15_000, self._verificar_inatividade)

    def _verificar_inatividade(self):
        try:
            limite = int(self.banco.config_pegar_int("bloqueio_inatividade_min", 0) or 0)
        except Exception:
            limite = 0
        if limite > 0 and self.contexto.usuario is not None:
            ocioso = (time.time() - self._ultimo_evento) / 60.0
            if ocioso >= limite:
                self.bloquear()
                return
        self._agendar_verificacao()

    def trocar_usuario(self):
        if not self.contexto.confirmar("Encerrar a sessão atual e entrar com outro usuário?"):
            return
        self.deslogar(sair=False)

    def bloquear(self):
        """Bloqueia a tela exigindo a senha do usuário atual para voltar."""
        from . import dialogs

        usuario = self.contexto.usuario
        if usuario is None:
            return
        bloqueio = tk.Toplevel(self.janela)
        bloqueio.title(f"{NOME_APP} — bloqueado")
        bloqueio.configure(background=self.tema.cor("bg"))
        bloqueio.transient(self.janela)
        bloqueio.resizable(False, False)
        bloqueio.attributes("-topmost", True)
        try:
            bloqueio.grab_set()
        except tk.TclError:
            pass
        quadro = ttk.Frame(bloqueio, style="Card.TFrame", padding=24)
        quadro.pack(padx=20, pady=20)
        ttk.Label(quadro, text="🔒 Tela bloqueada", style="TLabel", font=FONTE_TITULO).pack(anchor="w")
        ttk.Label(quadro, text=f"Usuário: {usuario['nome']} ({usuarios_mod.ROTULOS_PERFIS.get(usuario['perfil'], '')})",
                  style="Suave.TLabel").pack(anchor="w", pady=(4, 10))
        ttk.Label(quadro, text="Senha para continuar:", style="TLabel").pack(anchor="w")
        entrada = ttk.Entry(quadro, show="•", width=32)
        entrada.pack(fill="x", pady=(2, 8))
        entrada.focus_set()
        aviso = ttk.Label(quadro, text="", foreground=self.tema.cor("perigo"))
        aviso.pack(anchor="w")

        def liberar(_evento=None):
            try:
                autenticado = usuarios_mod.autenticar(self.banco, usuario["login"], entrada.get())
            except usuarios_mod.ErroUsuario as exc:
                aviso.configure(text=str(exc))
                return
            if not autenticado:
                aviso.configure(text="Senha incorreta.")
                entrada.delete(0, "end")
                return
            bloqueio.destroy()
            self._marcar_atividade()
            self.barra_status.definir(texto="Sessão retomada.")

        def encerrar():
            bloqueio.destroy()
            self.deslogar(sair=False)

        entrada.bind("<Return>", liberar)
        botoes = ttk.Frame(quadro, style="TFrame")
        botoes.pack(fill="x", pady=(8, 0))
        ttk.Button(botoes, text="Desbloquear", style="Primario.TButton", command=liberar).pack(side="left")
        ttk.Button(botoes, text="Trocar usuário", command=encerrar).pack(side="left", padx=(8, 0))
        ttk.Button(botoes, text="Sair do sistema", command=self.ao_fechar).pack(side="left", padx=(8, 0))
        bloqueio.update_idletasks()
        largura, altura = bloqueio.winfo_reqwidth(), bloqueio.winfo_reqheight()
        x = self.janela.winfo_rootx() + (self.janela.winfo_width() - largura) // 2
        y = self.janela.winfo_rooty() + (self.janela.winfo_height() - altura) // 2
        bloqueio.geometry(f"+{max(0, x)}+{max(0, y)}")

    def deslogar(self, sair: bool = False):
        """Limpa a sessão (mantém as telas em cache vazias) e pede login novamente."""
        for tela in list(self._telas.values()):
            try:
                tela.destroy()
            except tk.TclError:
                pass
        self._telas.clear()
        self.contexto.usuario = None
        self.tela_id_atual = ""
        self.rotulo_tela.configure(text="")
        self._montar_menu()
        if not self._login():
            if sair:
                self.janela.destroy()
            else:
                self.ao_fechar(confirmar=False)
            return
        self._atualizar_cabecalho_usuario()
        self.tela_inicial()

    def _login(self) -> bool:
        """Exibe o login. Devolve ``True`` quando autenticado."""
        if self.sem_login:
            self.contexto.usuario = usuarios_mod.pegar_por_login(self.banco, "admin")
            return bool(self.contexto.usuario)
        while True:
            dialogo = JanelaLogin(self.janela, self.banco, self.tema)
            self.janela.wait_window(dialogo)
            usuario = dialogo.resultado
            if usuario is None:
                return False
            self.contexto.usuario = usuario
            self._marcar_atividade()
            self._agendar_verificacao()
            if int(usuario["trocar_senha"] or 0):
                from . import dialogs

                dados = dialogs.pedir_senha(
                    self.janela, self.tema, "Trocar senha (obrigatório)",
                    texto=f"Olá, {usuario['nome']}! Por segurança, defina uma nova senha para o primeiro acesso.",
                    confirmar=True,
                )
                if not dados:
                    self.contexto.usuario = None
                    continue
                try:
                    usuarios_mod.alterar_senha(self.banco, usuario["id"], "", dados["senha"], dados["confirmar"])
                except usuarios_mod.ErroUsuario as exc:
                    from . import dialogs as d

                    d.erro(self.janela, self.tema, str(exc))
                    self.contexto.usuario = None
                    continue
                usuarios_mod.marcar_troca_feita(self.banco, usuario["id"])
                self.contexto.usuario = usuarios_mod.pegar(self.banco, usuario["id"])
                self.contexto.sucesso("Senha atualizada com sucesso.")
            return True

    # ------------------------------------------------------------------ ciclo de vida
    def executar(self):
        if not self._login():
            return
        self._atualizar_cabecalho_usuario()
        self.tela_inicial()
        self._verificar_primeira_execucao()
        self.janela.mainloop()

    def _verificar_primeira_execucao(self):
        """Avisos úteis na primeira execução (empresa não configurada etc.)."""
        from . import dialogs

        try:
            ja_viu = self.banco.config_pegar_bool("primeira_execucao_aviso_visto", False)
        except Exception:
            ja_viu = True
        if not ja_viu:
            try:
                self.banco.config_gravar("primeira_execucao_aviso_visto", "1")
            except Exception:
                pass
            dialogs.mensagem(
                self.janela, self.tema, f"Bem-vindo ao {NOME_APP}",
                "Este sistema funciona 100% offline: os dados ficam salvos em\n"
                f"{pasta_dados()}\n\n"
                "Sugestão de primeiros passos:\n"
                "1) Cadastre a empresa em Configurações (sai nos recibos);\n"
                "2) Cadastre categorias e produtos;\n"
                "3) Gere etiquetas de código de barras;\n"
                "4) Abra o caixa e comece a vender pelo PDV.",
                "sucesso", ("Entendi",),
            )

    def ao_fechar(self, confirmar: bool = True):
        from . import dialogs

        if self.contexto.caixa_aberto is None:
            try:
                self.contexto.caixa_aberto = caixa_mod.caixa_atual(self.banco)
            except Exception:
                self.contexto.caixa_aberto = None
        if confirmar:
            texto = "Deseja realmente sair do MR Logística?"
            if self.contexto.caixa_aberto:
                texto = ("O caixa ainda está ABERTO. Recomendamos fechá-lo antes de sair.\n\n"
                         "Deseja sair mesmo assim?")
            if not dialogs.confirmar(self.janela, self.tema, texto, "Sair do sistema", "Sair", "Cancelar"):
                return
        try:
            if self.contexto.usuario:
                self.banco.registrar_log("logout", self.contexto.usuario["login"], self.contexto.usuario["id"],
                                         self.contexto.usuario["nome"])
        except Exception:
            pass
        try:
            from .. import backup as backup_mod

            backup_mod.automatico(self.banco, autor=self.contexto.usuario)
        except Exception:
            pass
        self.janela.destroy()

    # ------------------------------------------------------------------ utilidades
    def iniciar(self):
        self.janela.deiconify()
        self.executar()


# --------------------------------------------------------------------------------------
# Ponto de entrada
# --------------------------------------------------------------------------------------


def executar(banco: Banco | None = None) -> int:
    """Cria e executa a aplicação. Devolve o código de saída do processo."""
    from .. import usuarios as usuarios_mod2

    banco = banco or Banco()
    usuarios_mod2.garantir_administrador(banco)
    pendente = None
    try:
        from .. import backup as backup_mod

        pendente = backup_mod.restauracao_pendente()
    except Exception:
        pendente = None
    app = Aplicacao(banco=banco)
    if pendente:
        from . import dialogs

        # A restauração já recarrega as telas na hora; aqui só avisamos que a cópia
        # de segurança do banco anterior continua guardada (pode ser apagada depois).
        dialogs.info(app.janela, app.tema,
                     "Existe uma cópia de segurança de uma restauração recente:\n"
                     f"{pendente.name}\n\n"
                     "Ela está na pasta de backups e pode ser excluída assim que você "
                     "confirmar que os dados restaurados estão corretos.")
    app.iniciar()
    return 0


if __name__ == "__main__":  # permite "python -m mrlog.gui.app" durante o desenvolvimento
    executar()
