"""
Temas (claro e escuro) e estilo visual do aplicativo.

Toda cor usada na interface sai daqui. Trocar o tema em tempo real é possível
porque os widgets consultam ``Tema.cor(...)`` e o método :meth:`Tema.aplicar`
reconfigura os estilos do ``ttk`` e repinta os widgets marcados.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

CLARO = {
    "bg": "#f1f5f9",
    "bg_alt": "#e2e8f0",
    "bg_card": "#ffffff",
    "bg_input": "#ffffff",
    "bg_menu": "#0f2438",
    "bg_menu_hover": "#1b3a57",
    "bg_menu_ativo": "#2f6f9f",
    "bg_selecao": "#cfe2f3",
    "bg_strip": "#f7fafc",
    "fg": "#111827",
    "fg_suave": "#4b5563",
    "fg_fraco": "#8a94a6",
    "fg_menu": "#dbe6f0",
    "fg_menu_ativo": "#ffffff",
    "borda": "#cbd5e1",
    "borda_forte": "#94a3b8",
    "primaria": "#1d4ed8",
    "primaria_hover": "#1e40af",
    "primaria_fg": "#ffffff",
    "sucesso": "#15803d",
    "sucesso_bg": "#dcfce7",
    "alerta": "#b45309",
    "alerta_bg": "#fef3c7",
    "perigo": "#b91c1c",
    "perigo_bg": "#fee2e2",
    "info": "#0e7490",
    "info_bg": "#cffafe",
    "neutro": "#475569",
    "neutro_bg": "#e2e8f0",
    "grafico": "#2563eb",
    "grafico_2": "#16a34a",
    "sombra": "#00000018",
}

ESCURO = {
    "bg": "#111827",
    "bg_alt": "#1f2937",
    "bg_card": "#1b2432",
    "bg_input": "#0f172a",
    "bg_menu": "#0b1220",
    "bg_menu_hover": "#1e293b",
    "bg_menu_ativo": "#2563eb",
    "bg_selecao": "#1e3a5f",
    "bg_strip": "#16202e",
    "fg": "#e5e7eb",
    "fg_suave": "#b6c2d2",
    "fg_fraco": "#7d8aa0",
    "fg_menu": "#c7d3e1",
    "fg_menu_ativo": "#ffffff",
    "borda": "#2c3a4d",
    "borda_forte": "#43556d",
    "primaria": "#3b82f6",
    "primaria_hover": "#2563eb",
    "primaria_fg": "#0b1220",
    "sucesso": "#4ade80",
    "sucesso_bg": "#14351f",
    "alerta": "#fbbf24",
    "alerta_bg": "#3a2c0c",
    "perigo": "#f87171",
    "perigo_bg": "#3b1518",
    "info": "#22d3ee",
    "info_bg": "#0d3140",
    "neutro": "#94a3b8",
    "neutro_bg": "#243040",
    "grafico": "#60a5fa",
    "grafico_2": "#34d399",
    "sombra": "#00000055",
}

PALETAS = {"claro": CLARO, "escuro": ESCURO}

FONTE_BASE = ("Segoe UI", 10)
FONTE_PEQUENA = ("Segoe UI", 9)
FONTE_TITULO = ("Segoe UI", 16, "bold")
FONTE_SUBTITULO = ("Segoe UI", 11, "bold")
FONTE_VALOR = ("Segoe UI", 20, "bold")
FONTE_MONO = ("Consolas", 10)


class Tema:
    """Guarda o tema atual e aplica o estilo em toda a aplicação."""

    def __init__(self, nome: str = "claro"):
        self.nome = nome if nome in PALETAS else "claro"
        self._widgets: list = []
        self._callbacks: list = []

    # ------------------------------------------------------------------ cores
    @property
    def paleta(self) -> dict:
        return PALETAS[self.nome]

    def cor(self, chave: str, padrao: str = "#000000") -> str:
        return self.paleta.get(chave, padrao)

    def eh_escuro(self) -> bool:
        return self.nome == "escuro"

    def trocar(self, nome: str | None = None) -> str:
        """Alterna entre claro/escuro (ou define um tema específico)."""
        if nome in PALETAS:
            self.nome = nome
        else:
            self.nome = "escuro" if self.nome == "claro" else "claro"
        return self.nome

    # ------------------------------------------------------------------ estilo ttk
    def aplicar(self, raiz: tk.Misc) -> None:
        """Configura os estilos do ttk e repinta os widgets registrados."""
        try:
            estilo = ttk.Style(raiz)
        except tk.TclError:  # pragma: no cover - sem display
            return
        temas_disponiveis = estilo.theme_names()
        preferido = "clam" if "clam" in temas_disponiveis else temas_disponiveis[0]
        try:
            estilo.theme_use(preferido)
        except tk.TclError:
            pass

        bg = self.cor("bg")
        card = self.cor("bg_card")
        entrada = self.cor("bg_input")
        fg = self.cor("fg")
        borda = self.cor("borda")
        primaria = self.cor("primaria")
        selecao = self.cor("bg_selecao")

        estilo.configure(".", background=bg, foreground=fg, fieldbackground=entrada,
                         font=FONTE_BASE, bordercolor=borda, lightcolor=borda, darkcolor=borda)
        estilo.configure("TFrame", background=bg)
        estilo.configure("Card.TFrame", background=card)
        estilo.configure("TLabel", background=bg, foreground=fg)
        estilo.configure("Card.TLabel", background=card, foreground=fg)
        estilo.configure("Suave.TLabel", background=bg, foreground=self.cor("fg_suave"), font=FONTE_PEQUENA)
        estilo.configure("Card.Suave.TLabel", background=card, foreground=self.cor("fg_suave"), font=FONTE_PEQUENA)
        estilo.configure("Titulo.TLabel", background=bg, foreground=fg, font=FONTE_TITULO)
        estilo.configure("Card.Titulo.TLabel", background=card, foreground=fg, font=FONTE_SUBTITULO)
        estilo.configure("Valor.TLabel", background=card, foreground=fg, font=FONTE_VALOR)

        estilo.configure("TButton", padding=(12, 6), background=self.cor("bg_alt"), foreground=fg,
                         bordercolor=borda, focuscolor=borda)
        estilo.map("TButton", background=[("active", self.cor("borda"))], foreground=[("active", fg)])

        estilo.configure("Primario.TButton", background=primaria, foreground=self.cor("primaria_fg"),
                         bordercolor=primaria, padding=(14, 7), font=("Segoe UI", 10, "bold"))
        estilo.map("Primario.TButton", background=[("active", self.cor("primaria_hover")), ("disabled", self.cor("borda"))],
                   foreground=[("active", self.cor("primaria_fg")), ("disabled", self.cor("fg_fraco"))])

        estilo.configure("Sucesso.TButton", background=self.cor("sucesso"), foreground="#ffffff", bordercolor=self.cor("sucesso"))
        estilo.map("Sucesso.TButton", background=[("active", self.cor("sucesso"))])
        estilo.configure("Perigo.TButton", background=self.cor("perigo"), foreground="#ffffff", bordercolor=self.cor("perigo"))
        estilo.map("Perigo.TButton", background=[("active", self.cor("perigo"))])
        estilo.configure("Link.TButton", background=bg, foreground=primaria, borderwidth=0, padding=(4, 2))
        estilo.map("Link.TButton", background=[("active", bg)])

        estilo.configure("TEntry", fieldbackground=entrada, foreground=fg, insertcolor=fg,
                         bordercolor=borda, lightcolor=borda, darkcolor=borda, padding=4)
        estilo.map("TEntry", bordercolor=[("focus", primaria)], lightcolor=[("focus", primaria)])
        estilo.configure("TCombobox", fieldbackground=entrada, background=self.cor("bg_alt"), foreground=fg,
                         arrowcolor=fg, bordercolor=borda, padding=3)
        estilo.map("TCombobox", fieldbackground=[("readonly", entrada)], foreground=[("readonly", fg)],
                   selectbackground=[("readonly", entrada)], selectforeground=[("readonly", fg)])
        estilo.configure("TSpinbox", fieldbackground=entrada, foreground=fg, arrowcolor=fg, bordercolor=borda)

        estilo.configure("Treeview", background=card, fieldbackground=card, foreground=fg,
                         rowheight=26, bordercolor=borda, font=FONTE_BASE)
        estilo.map("Treeview", background=[("selected", primaria)], foreground=[("selected", self.cor("primaria_fg"))])
        estilo.configure("Treeview.Heading", background=self.cor("bg_alt"), foreground=fg,
                         font=("Segoe UI", 9, "bold"), relief="flat", padding=(6, 6))
        estilo.map("Treeview.Heading", background=[("active", self.cor("borda"))])

        estilo.configure("TNotebook", background=bg, bordercolor=borda)
        estilo.configure("TNotebook.Tab", background=self.cor("bg_alt"), foreground=self.cor("fg_suave"),
                         padding=(14, 7), font=FONTE_PEQUENA)
        estilo.map("TNotebook.Tab", background=[("selected", card)], foreground=[("selected", fg)])

        estilo.configure("Horizontal.TProgressbar", background=primaria, troughcolor=self.cor("bg_alt"),
                         bordercolor=borda, lightcolor=primaria, darkcolor=primaria)
        estilo.configure("TCheckbutton", background=bg, foreground=fg)
        estilo.map("TCheckbutton", background=[("active", bg)])
        estilo.configure("Card.TCheckbutton", background=card, foreground=fg)
        estilo.map("Card.TCheckbutton", background=[("active", card)])
        estilo.configure("TRadiobutton", background=bg, foreground=fg)
        estilo.map("TRadiobutton", background=[("active", bg)])
        estilo.configure("Horizontal.TScrollbar", background=self.cor("bg_alt"), troughcolor=bg,
                         arrowcolor=fg, bordercolor=borda)
        estilo.configure("Vertical.TScrollbar", background=self.cor("bg_alt"), troughcolor=bg,
                         arrowcolor=fg, bordercolor=borda)
        estilo.configure("Vertical.TScrollbar", gripcount=0)
        estilo.configure("TLabelframe", background=bg, foreground=fg, bordercolor=borda)
        estilo.configure("TLabelframe.Label", background=bg, foreground=self.cor("fg_suave"), font=FONTE_PEQUENA)
        estilo.configure("Card.TLabelframe", background=card, bordercolor=borda)
        estilo.configure("Card.TLabelframe.Label", background=card, foreground=self.cor("fg_suave"))
        estilo.configure("TSeparator", background=borda)
        estilo.configure("TPanedwindow", background=bg)
        estilo.configure("TMenubutton", background=self.cor("bg_alt"), foreground=fg, padding=(8, 4))
        estilo.configure("TMenubutton", arrowcolor=fg)

        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                continue
        for widget in list(self._widgets):
            try:
                if not widget.winfo_exists():
                    self._widgets.remove(widget)
                    continue
                self._repintar(widget)
            except tk.TclError:
                continue

    # ------------------------------------------------------------------ widgets
    def registrar(self, widget, **cores) -> None:
        """Registra um widget para ser repintado na troca de tema.

        ``cores`` mapeia opções do Tk (``background``, ``foreground``...) para chaves
        da paleta: ``tema.registrar(frame, background='bg_card', foreground='fg')``.
        """
        widget._mrlog_cores = cores  # type: ignore[attr-defined]
        self._widgets.append(widget)
        self._repintar(widget)

    def _repintar(self, widget) -> None:
        cores = getattr(widget, "_mrlog_cores", None)
        if not cores:
            return
        try:
            configuracao = {}
            for opcao, chave in cores.items():
                configuracao[opcao] = self.cor(chave)
            widget.configure(**configuracao)
        except tk.TclError:
            pass

    def ao_trocar(self, callback) -> None:
        """Registra uma função chamada sempre que o tema for aplicado (telas redesenham gráficos)."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    # ------------------------------------------------------------------ utilidades
    def cor_estado(self, estado: str) -> tuple[str, str]:
        """Devolve (fundo, texto) para estados semânticos usados em etiquetas."""
        mapa = {
            "concluida": ("sucesso_bg", "sucesso"),
            "paga": ("sucesso_bg", "sucesso"),
            "aberto": ("sucesso_bg", "sucesso"),
            "ativo": ("sucesso_bg", "sucesso"),
            "ok": ("sucesso_bg", "sucesso"),
            "parcial": ("info_bg", "info"),
            "parcialmente_devolvida": ("info_bg", "info"),
            "aberta": ("info_bg", "info"),
            "vencida": ("perigo_bg", "perigo"),
            "cancelada": ("perigo_bg", "perigo"),
            "cancelado": ("perigo_bg", "perigo"),
            "inativo": ("neutro_bg", "neutro"),
            "fechado": ("neutro_bg", "neutro"),
            "devolvida": ("alerta_bg", "alerta"),
            "baixo": ("alerta_bg", "alerta"),
            "zerado": ("perigo_bg", "perigo"),
            "vencido": ("perigo_bg", "perigo"),
            "critico": ("perigo_bg", "perigo"),
            "atencao": ("alerta_bg", "alerta"),
            "info": ("info_bg", "info"),
        }
        fundo, texto = mapa.get(str(estado or "").lower(), ("neutro_bg", "neutro"))
        return self.cor(fundo), self.cor(texto)
