"""
Widgets reutilizáveis do MR Logística.

Tudo aqui é construído sobre ``tkinter``/``ttk`` puro (sem bibliotecas de tema de
terceiros) e respeita o tema claro/escuro definido em :mod:`mrlog.gui.tema`:

* :class:`QuadroRolavel` — painel com barra de rolagem e roda do mouse;
* :class:`Tabela` — grade com colunas tipadas, ordenação, busca, filtros e páginas;
* campos prontos (``CampoTexto``, ``CampoDinheiro``, ``CampoData``, ``CampoLista``...);
* :class:`BarraFerramentas`, :class:`Cartao`, :class:`EtiquetaEstado`,
  :class:`BarraStatus` e :func:`grafico_barras`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable, Sequence

from ..utils import (
    contem_sem_acento,
    formatar_data,
    formatar_dinheiro,
    formatar_quantidade,
    normalizar,
    para_centavos,
    para_reais,
)
from .tema import (
    FONTE_BASE,
    FONTE_MONO,
    FONTE_PEQUENA,
    FONTE_SUBTITULO,
    FONTE_TITULO,
    FONTE_VALOR,
    Tema,
)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def formatar_valor(valor: Any, tipo: str) -> str:
    """Formata um valor de acordo com o tipo declarado da coluna."""
    if valor is None:
        return ""
    tipo = (tipo or "texto").lower()
    if tipo == "dinheiro":
        return formatar_dinheiro(int(valor or 0))
    if tipo == "quantidade":
        return formatar_quantidade(valor)
    if tipo == "inteiro":
        try:
            return f"{int(valor or 0)}"
        except (TypeError, ValueError):
            return str(valor)
    if tipo == "percentual":
        try:
            return f"{float(valor or 0):.2f}%".replace(".", ",")
        except (TypeError, ValueError):
            return str(valor)
    if tipo == "data":
        return formatar_data(valor)
    if tipo == "data_hora":
        return formatar_data(valor, com_hora=True)
    return str(valor)


def _limpar_texto(widget) -> None:
    widget.delete(0, tk.END)


# --------------------------------------------------------------------------------------
# Quadro com rolagem
# --------------------------------------------------------------------------------------


class QuadroRolavel(ttk.Frame):
    """Container com rolagem vertical (Canvas + Scrollbar) e suporte à roda do mouse."""

    def __init__(self, mestre, tema: Tema, **kwargs):
        super().__init__(mestre, style="TFrame", **kwargs)
        self.tema = tema
        self._canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self._barra = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._quadro = ttk.Frame(self._canvas, style="TFrame")
        self._quadro_id = self._canvas.create_window((0, 0), window=self._quadro, anchor="nw")

        self._canvas.configure(yscrollcommand=self._barra.set)
        self._barra.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._quadro.bind("<Configure>", self._ao_configurar)
        self._canvas.bind("<Configure>", self._ao_configurar_canvas)
        self._canvas.bind_all("<MouseWheel>", self._roda, add="+")          # Windows/macOS
        self._canvas.bind_all("<Button-4>", self._roda, add="+")            # Linux (cima)
        self._canvas.bind_all("<Button-5>", self._roda, add="+")            # Linux (baixo)
        self.bind("<Destroy>", self._ao_destruir)
        tema.registrar(self._canvas, background="bg")
        tema.registrar(self._quadro, background="bg")

    # o conteúdo do quadro rolável
    @property
    def quadro(self) -> ttk.Frame:
        return self._quadro

    def _ao_configurar(self, _evento=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all") or (0, 0, 0, 0))

    def _ao_configurar_canvas(self, evento):
        self._canvas.itemconfigure(self._quadro_id, width=evento.width)

    def _roda(self, evento):
        """Só rola se o ponteiro estiver sobre este quadro (evita brigar com outras telas)."""
        try:
            widget = self.winfo_containing(evento.x_root, evento.y_root)
        except (KeyError, tk.TclError):
            return
        while widget is not None:
            if widget is self._quadro or widget is self._canvas:
                break
            widget = getattr(widget, "master", None)
        else:
            return
        if widget is None:
            return
        delta = -1 if getattr(evento, "num", 0) == 4 else (1 if getattr(evento, "num", 0) == 5 else 0)
        if delta == 0:
            delta = -1 if evento.delta > 0 else 1
        if self._canvas.yview() != (0.0, 1.0):
            self._canvas.yview_scroll(delta, "units")

    def _ao_destruir(self, _evento=None):
        try:
            self._canvas.unbind_all("<MouseWheel>")
            self._canvas.unbind_all("<Button-4>")
            self._canvas.unbind_all("<Button-5>")
        except tk.TclError:
            pass

    def rolar_para_topo(self):
        self._canvas.yview_moveto(0)


# --------------------------------------------------------------------------------------
# Tabela (Treeview) com busca, filtros, ordenação e paginação
# --------------------------------------------------------------------------------------


class Tabela(ttk.Frame):
    """Grade de dados pronta para uso nas telas.

    ``colunas`` é uma lista de dicionários::

        {"chave": "nome", "rotulo": "Produto", "largura": 260, "tipo": "texto",
         "alinhamento": "esquerda", "visivel": True}

    Tipos suportados: ``texto``, ``dinheiro``, ``quantidade``, ``inteiro``,
    ``percentual``, ``data`` e ``data_hora``.
    """

    def __init__(
        self,
        mestre,
        tema: Tema,
        colunas: Sequence[dict],
        ao_selecionar: Callable[[dict | None], None] | None = None,
        ao_duplo_clique: Callable[[dict], None] | None = None,
        selecao: str = "browse",
        mostrar_busca: bool = True,
        busca_placeholder: str = "Buscar... (Ctrl+B)",
        tamanho_pagina: int = 0,
        altura: int = 18,
        ao_buscar: Callable[[str], None] | None = None,
    ):
        super().__init__(mestre, style="TFrame")
        self.tema = tema
        self.colunas = [dict(c) for c in colunas]
        #: texto "fantasma" mostrado na busca — também serve para saber se o campo está vazio
        self.busca_placeholder = busca_placeholder
        self.ao_selecionar = ao_selecionar
        self.ao_duplo_clique = ao_duplo_clique
        self.ao_buscar = ao_buscar
        self.tamanho_pagina = int(tamanho_pagina or 0)
        self._dados: list[dict] = []
        self._visiveis: list[dict] = []
        self._ordenar_por: str = ""
        self._ordenar_desc = False
        self._pagina = 0
        self._filtro_texto = ""
        self._filtros: dict[str, Any] = {}
        self._tags_por_linha: dict[str, tuple] = {}
        self._linha_selecionada: dict | None = None

        if mostrar_busca:
            topo = ttk.Frame(self, style="TFrame")
            topo.pack(side="top", fill="x", pady=(0, 6))
            self.entrada_busca = ttk.Entry(topo, width=34)
            self.entrada_busca.pack(side="left", fill="x", expand=True)
            self.entrada_busca.insert(0, busca_placeholder)
            self.entrada_busca.configure(foreground=tema.cor("fg_fraco"))
            self.entrada_busca.bind("<FocusIn>", self._busca_focus_in)
            self.entrada_busca.bind("<FocusOut>", self._busca_focus_out)
            self.entrada_busca.bind("<KeyRelease>", lambda e: self._aplicar(0))
            ttk.Button(topo, text="Limpar", width=8, command=self.limpar_busca).pack(side="left", padx=(6, 0))
        else:
            self.entrada_busca = None

        corpo = ttk.Frame(self, style="TFrame")
        corpo.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(
            corpo,
            columns=[c["chave"] for c in self.colunas if c.get("visivel", True)],
            show="headings",
            selectmode=selecao,
            height=altura,
        )
        barra_y = ttk.Scrollbar(corpo, orient="vertical", command=self.tree.yview)
        barra_x = ttk.Scrollbar(corpo, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=barra_y.set, xscrollcommand=barra_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        barra_y.grid(row=0, column=1, sticky="ns")
        barra_x.grid(row=1, column=0, sticky="ew")
        corpo.rowconfigure(0, weight=1)
        corpo.columnconfigure(0, weight=1)

        for coluna in self.colunas:
            if not coluna.get("visivel", True):
                continue
            chave = coluna["chave"]
            self.tree.heading(
                chave,
                text=str(coluna.get("rotulo", chave)),
                command=lambda c=chave: self.ordenar_por(c),
                anchor=self._anchor(coluna),
            )
            self.tree.column(
                chave,
                width=int(coluna.get("largura", 120)),
                minwidth=48,
                anchor=self._anchor(coluna),
                stretch=bool(coluna.get("elastico", coluna.get("tipo") == "texto")),
            )

        self.tree.bind("<<TreeviewSelect>>", self._ao_selecionar_evento)
        self.tree.bind("<Double-1>", self._ao_duplo_clique_evento)
        self.tree.bind("<Return>", self._ao_duplo_clique_evento)

        rodape = ttk.Frame(self, style="TFrame")
        rodape.pack(side="bottom", fill="x", pady=(4, 0))
        self.rotulo_resumo = ttk.Label(rodape, text="", style="Suave.TLabel")
        self.rotulo_resumo.pack(side="left")
        self.quadro_paginas = ttk.Frame(rodape, style="TFrame")
        self.quadro_paginas.pack(side="right")
        self._montar_paginacao()

        self._configurar_tags()

    # ------------------------------------------------------------------ aparência
    @staticmethod
    def _anchor(coluna: dict) -> str:
        alinhamento = str(coluna.get("alinhamento") or ("esquerda" if coluna.get("tipo", "texto") == "texto" else "direita"))
        return {"esquerda": "w", "direita": "e", "centro": "center"}.get(alinhamento, "w")

    def _configurar_tags(self):
        cores = {
            "perigo": (self.tema.cor("perigo_bg"), self.tema.cor("perigo")),
            "alerta": (self.tema.cor("alerta_bg"), self.tema.cor("alerta")),
            "sucesso": (self.tema.cor("sucesso_bg"), self.tema.cor("sucesso")),
            "info": (self.tema.cor("info_bg"), self.tema.cor("info")),
            "neutro": (self.tema.cor("neutro_bg"), self.tema.cor("fg_suave")),
            "negrito": (self.tema.cor("bg_card"), self.tema.cor("fg")),
            "zebra": (self.tema.cor("bg_strip"), self.tema.cor("fg")),
        }
        for nome, (fundo, texto) in cores.items():
            try:
                self.tree.tag_configure(nome, background=fundo, foreground=texto)
            except tk.TclError:
                pass
        self.tree.tag_configure("negrito", font=("Segoe UI", 10, "bold"))

    def atualizar_tema(self):
        self._configurar_tags()
        self._aplicar(self._pagina)

    # ------------------------------------------------------------------ dados
    def carregar(self, dados: Iterable[dict], resumo: str = "") -> None:
        """Substitui os dados da tabela (mantém busca, filtros e ordenação)."""
        self._dados = [dict(d) for d in dados or []]
        if resumo:
            self.rotulo_resumo.configure(text=resumo)
        else:
            self._atualizar_resumo()
        self._aplicar(0)

    def definir_filtros(self, **filtros) -> None:
        """Define filtros adicionais (``None`` ou ``''`` desliga o filtro)."""
        for chave, valor in filtros.items():
            if valor in (None, "", "todos", "todas"):
                self._filtros.pop(chave, None)
            else:
                self._filtros[chave] = valor
        self._aplicar(0)

    def _aplicar(self, pagina: int = 0) -> None:
        texto = self._filtro_texto
        if self.entrada_busca is not None and self.entrada_busca.get() not in ("", self.busca_placeholder):
            texto = self.entrada_busca.get()
        linhas = self._filtrar(texto)
        linhas = self._ordenar(linhas)
        self._visiveis = linhas
        total_paginas = 1
        if self.tamanho_pagina > 0:
            total_paginas = max(1, -(-len(linhas) // self.tamanho_pagina))
            self._pagina = max(0, min(pagina, total_paginas - 1))
            inicio = self._pagina * self.tamanho_pagina
            linhas_pagina = linhas[inicio : inicio + self.tamanho_pagina]
        else:
            self._pagina = 0
            linhas_pagina = linhas
        self._renderizar(linhas_pagina)
        self._montar_paginacao(total_paginas)
        self._atualizar_resumo()

    def _filtrar(self, texto: str) -> list[dict]:
        linhas = self._dados
        for chave, esperado in self._filtros.items():
            if isinstance(esperado, (list, tuple, set)):
                linhas = [l for l in linhas if str(l.get(chave)) in {str(x) for x in esperado}]
            elif isinstance(esperado, Callable):
                linhas = [l for l in linhas if esperado(l)]
            else:
                linhas = [l for l in linhas if str(l.get(chave, "")).strip().lower() == str(esperado).strip().lower()]
        if texto:
            termo = normalizar(texto)
            filtradas = []
            for linha in linhas:
                alvo = " ".join(normalizar(formatar_valor(v, "texto")) for v in linha.values() if v is not None)
                if termo in alvo:
                    filtradas.append(linha)
            linhas = filtradas
        return linhas

    def _ordenar(self, linhas: list[dict]) -> list[dict]:
        if not self._ordenar_por:
            return linhas
        chave = self._ordenar_por
        coluna = next((c for c in self.colunas if c["chave"] == chave), None)
        tipo = (coluna or {}).get("tipo", "texto")

        def valor(linha):
            v = linha.get(chave)
            if v is None:
                return (1, "")
            if tipo in ("dinheiro", "inteiro"):
                try:
                    return (0, float(v))
                except (TypeError, ValueError):
                    return (1, str(v))
            if tipo in ("quantidade", "percentual"):
                try:
                    return (0, float(v))
                except (TypeError, ValueError):
                    return (1, str(v))
            return (0, normalizar(v))

        return sorted(linhas, key=valor, reverse=self._ordenar_desc)

    def _renderizar(self, linhas: Sequence[dict]) -> None:
        self._tags_por_linha.clear()
        self.tree.delete(*self.tree.get_children())
        colunas_visiveis = [c for c in self.colunas if c.get("visivel", True)]
        for indice, linha in enumerate(linhas):
            valores = [formatar_valor(linha.get(c["chave"]), c.get("tipo", "texto")) for c in colunas_visiveis]
            identificadores = [k for k, v in linha.items() if k.startswith("_tag")]
            tags: list[str] = []
            if indice % 2 == 1:
                tags.append("zebra")
            for chave_tag in identificadores:
                if linha[chave_tag]:
                    tags.append(str(linha[chave_tag]))
            if linha.get("_tag"):
                tags.append(str(linha["_tag"]))
            item_id = self.tree.insert("", "end", values=valores, tags=tuple(dict.fromkeys(tags)))
            self._tags_por_linha[item_id] = linha
        if self._linha_selecionada is not None:
            for item_id, linha in self._tags_por_linha.items():
                if linha is self._linha_selecionada:
                    self.tree.selection_set(item_id)
                    self.tree.focus(item_id)
                    break

    def _atualizar_resumo(self) -> None:
        total = len(self._dados)
        visiveis = len(self._visiveis)
        if visiveis == total:
            texto = f"{total} registro(s)"
        else:
            texto = f"{visiveis} de {total} registro(s)"
        if self.tamanho_pagina > 0 and total:
            texto += f" — página {self._pagina + 1}"
        if not str(self.rotulo_resumo.cget("text")).startswith(("Total", "Selecionado")):
            self.rotulo_resumo.configure(text=texto)

    def definir_resumo(self, texto: str) -> None:
        self.rotulo_resumo.configure(text=texto)

    # ------------------------------------------------------------------ paginação
    def _montar_paginacao(self, total_paginas: int = 1) -> None:
        for filho in self.quadro_paginas.winfo_children():
            filho.destroy()
        if self.tamanho_pagina <= 0 or total_paginas <= 1:
            return
        ttk.Button(self.quadro_paginas, text="◀", width=3, command=lambda: self._aplicar(self._pagina - 1)).pack(side="left")
        ttk.Label(
            self.quadro_paginas,
            text=f" {self._pagina + 1} / {total_paginas} ",
            style="Suave.TLabel",
        ).pack(side="left")
        ttk.Button(self.quadro_paginas, text="▶", width=3, command=lambda: self._aplicar(self._pagina + 1)).pack(side="left")

    # ------------------------------------------------------------------ seleção
    def _ao_selecionar_evento(self, _evento=None):
        linha = self.linha_selecionada()
        if self.ao_selecionar:
            self.ao_selecionar(linha)

    def _ao_duplo_clique_evento(self, _evento=None):
        linha = self.linha_selecionada()
        if linha and self.ao_duplo_clique:
            self.ao_duplo_clique(linha)
            return "break"
        return None

    def linha_selecionada(self) -> dict | None:
        selecao = self.tree.selection()
        if not selecao:
            self._linha_selecionada = None
            return None
        self._linha_selecionada = self._tags_por_linha.get(selecao[0])
        return self._linha_selecionada

    def linhas_selecionadas(self) -> list[dict]:
        return [self._tags_por_linha[i] for i in self.tree.selection() if i in self._tags_por_linha]

    def selecionar_por(self, chave: str, valor) -> bool:
        """Seleciona (e torna visível) a linha cujo campo ``chave`` é igual a ``valor``."""
        for item_id, linha in self._tags_por_linha.items():
            if str(linha.get(chave)) == str(valor):
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.tree.see(item_id)
                self._linha_selecionada = linha
                if self.ao_selecionar:
                    self.ao_selecionar(linha)
                return True
        return False

    def selecionar_primeiro(self) -> None:
        itens = self.tree.get_children()
        if itens:
            self.tree.selection_set(itens[0])
            self.tree.focus(itens[0])
            if self.ao_selecionar:
                self.ao_selecionar(self._tags_por_linha.get(itens[0]))

    def ordenar_por(self, chave: str) -> None:
        """Clique no cabeçalho: alterna ascendente/descendente."""
        if self._ordenar_por == chave:
            self._ordenar_desc = not self._ordenar_desc
        else:
            self._ordenar_por = chave
            self._ordenar_desc = False
        for coluna in self.colunas:
            if not coluna.get("visivel", True):
                continue
            rotulo = str(coluna.get("rotulo", coluna["chave"]))
            sufixo = ""
            if coluna["chave"] == self._ordenar_por:
                sufixo = "  ▼" if self._ordenar_desc else "  ▲"
            self.tree.heading(coluna["chave"], text=rotulo + sufixo)
        self._aplicar(self._pagina)

    # ------------------------------------------------------------------ busca
    def _busca_focus_in(self, _evento=None):
        if self.entrada_busca is None:
            return
        if self.entrada_busca.get() in ("", self.busca_placeholder):
            _limpar_texto(self.entrada_busca)
            self.entrada_busca.configure(foreground=self.tema.cor("fg"))

    def _busca_focus_out(self, _evento=None):
        if self.entrada_busca is None:
            return
        if not self.entrada_busca.get().strip():
            self.entrada_busca.insert(0, self.busca_placeholder)
            self.entrada_busca.configure(foreground=self.tema.cor("fg_fraco"))
            self._aplicar(0)

    def focar_busca(self) -> None:
        if self.entrada_busca is not None:
            self.entrada_busca.focus_set()
            self._busca_focus_in()
            self.entrada_busca.select_range(0, tk.END)

    def limpar_busca(self) -> None:
        if self.entrada_busca is not None:
            _limpar_texto(self.entrada_busca)
            self._busca_focus_out()
        self._aplicar(0)

    def buscar(self, texto: str) -> None:
        if self.entrada_busca is not None:
            _limpar_texto(self.entrada_busca)
            self.entrada_busca.insert(0, texto)
            self.entrada_busca.configure(foreground=self.tema.cor("fg"))
        self._aplicar(0)
        if self.ao_buscar:
            self.ao_buscar(texto)

    # ------------------------------------------------------------------ utilidades
    def registros(self) -> list[dict]:
        return list(self._visiveis)

    def total_registros(self) -> int:
        return len(self._dados)

    def limpar(self) -> None:
        self.carregar([])

    def exportaveis(self) -> list[list[Any]]:
        """Dados formatados (para "copiar como texto"/exportação rápida)."""
        colunas_visiveis = [c for c in self.colunas if c.get("visivel", True)]
        linhas = [[c.get("rotulo", c["chave"]) for c in colunas_visiveis]]
        for linha in self._visiveis:
            linhas.append([formatar_valor(linha.get(c["chave"]), c.get("tipo", "texto")) for c in colunas_visiveis])
        return linhas


# --------------------------------------------------------------------------------------
# Campos de formulário
# --------------------------------------------------------------------------------------


class CampoBase(ttk.Frame):
    """Base dos campos: rótulo + widget + validação + leitura/gravação de valor."""

    def __init__(self, mestre, tema: Tema, rotulo: str, obrigatorio: bool = False, dica: str = "", largura: int = 0):
        super().__init__(mestre, style="TFrame")
        self.tema = tema
        self.rotulo_texto = rotulo
        self.obrigatorio = obrigatorio
        self.dica = dica
        texto = f"{rotulo} *" if obrigatorio else rotulo
        self.rotulo = ttk.Label(self, text=texto, style="TLabel")
        self.rotulo.pack(anchor="w")
        self._widget = None
        self._erro = None
        self.largura = largura

    # API comum -------------------------------------------------------------
    @property
    def widget(self):
        return self._widget

    def focar(self):
        if self._widget is not None:
            try:
                self._widget.focus_set()
            except tk.TclError:
                pass

    def habilitar(self, estado: bool = True):
        if self._widget is not None:
            self._widget.configure(state=("normal" if estado else "disabled"))

    def valor(self):
        raise NotImplementedError

    def definir(self, valor):
        raise NotImplementedError

    def validar(self) -> tuple[bool, str]:
        """Retorna ``(ok, mensagem)``. A classe base checa apenas obrigatoriedade."""
        if self.obrigatorio:
            v = self.valor()
            if v in (None, "", 0) or (isinstance(v, str) and not v.strip()):
                return False, f"O campo '{self.rotulo_texto}' é obrigatório."
        return True, ""

    def mostrar_erro(self, mensagem: str = "") -> None:
        if self._erro is None:
            self._erro = tk.Label(self, text="", anchor="w", font=("Segoe UI", 8))
            self._erro.pack(anchor="w")
        if mensagem:
            self._erro.configure(text=mensagem, foreground=self.tema.cor("perigo"))
        else:
            self._erro.configure(text="")

    def limpar_erro(self):
        if self._erro is not None:
            self._erro.configure(text="")


class CampoTexto(CampoBase):
    """Campo de texto simples (com opção de várias linhas e limite de caracteres)."""

    def __init__(self, mestre, tema: Tema, rotulo: str, obrigatorio: bool = False, dica: str = "",
                 largura: int = 30, multilinea: bool = False, altura: int = 4, limite: int = 0,
                 apenas_numero: bool = False, mascara: str = "", maiusculas: bool = False):
        super().__init__(mestre, tema, rotulo, obrigatorio, dica, largura)
        self.limite = int(limite or 0)
        self.apenas_numero = apenas_numero
        self.mascara = mascara
        self.maiusculas = maiusculas
        if multilinea:
            quadro = ttk.Frame(self, style="TFrame")
            quadro.pack(fill="both", expand=True)
            self._widget = tk.Text(quadro, height=altura, width=largura, wrap="word", relief="solid", bd=1,
                                   font=FONTE_BASE, undo=True)
            barra = ttk.Scrollbar(quadro, orient="vertical", command=self._widget.yview)
            self._widget.configure(yscrollcommand=barra.set)
            barra.pack(side="right", fill="y")
            self._widget.pack(side="left", fill="both", expand=True)
            tema.registrar(self._widget, background="bg_input", foreground="fg", insertbackground="fg")
        else:
            self._widget = ttk.Entry(self, width=largura)
            self._widget.pack(fill="x", expand=True)
            if self.limite:
                comando = self._widget.register(lambda s: len(s) <= self.limite)
                self._widget.configure(validate="key", validatecommand=(comando, "%P"))
            if apenas_numero:
                self._widget.configure(validate="key",
                                       validatecommand=(self._widget.register(self._so_numero), "%P"))
        if dica:
            ttk.Label(self, text=dica, style="Suave.TLabel").pack(anchor="w")
        self.aplicar_estilo_entrada()

    def _so_numero(self, texto: str) -> bool:
        return texto == "" or texto.replace(".", "").replace(",", "").replace("-", "").isdigit()

    def aplicar_estilo_entrada(self):
        if isinstance(self._widget, tk.Text):
            self._widget.configure(
                background=self.tema.cor("bg_input"), foreground=self.tema.cor("fg"),
                insertbackground=self.tema.cor("fg"), highlightthickness=1,
                highlightbackground=self.tema.cor("borda"), highlightcolor=self.tema.cor("primaria"),
            )

    def valor(self) -> str:
        if isinstance(self._widget, tk.Text):
            texto = self._widget.get("1.0", tk.END).strip()
        else:
            texto = self._widget.get().strip()
        if self.maiusculas:
            texto = texto.upper()
        if self.mascara == "documento":
            from ..utils import formatar_cpf_cnpj

            texto = formatar_cpf_cnpj(texto) if texto else ""
        elif self.mascara == "telefone":
            from ..utils import formatar_telefone

            texto = formatar_telefone(texto) if texto else ""
        return texto

    def definir(self, valor) -> None:
        texto = "" if valor is None else str(valor)
        if isinstance(self._widget, tk.Text):
            self._widget.delete("1.0", tk.END)
            self._widget.insert("1.0", texto)
        else:
            _limpar_texto(self._widget)
            self._widget.insert(0, texto)
        self.limpar_erro()


class CampoDinheiro(CampoTexto):
    """Campo monetário: aceita ``1234,56`` / ``R$ 1.234,56`` e devolve **centavos**."""

    def __init__(self, mestre, tema: Tema, rotulo: str, obrigatorio: bool = False, dica: str = "",
                 largura: int = 14, permitir_negativo: bool = False, ao_alterar: Callable[[int], None] | None = None):
        super().__init__(mestre, tema, rotulo, obrigatorio, dica, largura)
        self.permitir_negativo = permitir_negativo
        self.ao_alterar = ao_alterar
        if isinstance(self._widget, ttk.Entry):
            self._widget.configure(justify="right")
            self._widget.bind("<FocusOut>", self._ao_sair)
            self._widget.bind("<KeyRelease>", lambda e: self.ao_alterar and self.ao_alterar(self.valor()))

    def _ao_sair(self, _evento=None):
        centavos = self.valor()
        self.definir(centavos)

    def valor(self) -> int:
        bruto = self._widget.get().strip() if isinstance(self._widget, ttk.Entry) else ""
        if not bruto:
            return 0
        return para_centavos(bruto)

    def reais(self) -> float:
        return para_reais(self.valor())

    def definir(self, valor) -> None:
        if valor is None or valor == "":
            centavos = 0
        elif isinstance(valor, str):
            centavos = para_centavos(valor)
        else:
            centavos = int(valor)
        _limpar_texto(self._widget)
        self._widget.insert(0, formatar_dinheiro(centavos, simbolo=False) if centavos else "0,00")
        self.limpar_erro()

    def validar(self) -> tuple[bool, str]:
        ok, mensagem = super().validar()
        if not ok:
            return ok, mensagem
        if self.valor() < 0 and not self.permitir_negativo:
            return False, f"'{self.rotulo_texto}' não pode ser negativo."
        return True, ""


class CampoQuantidade(CampoTexto):
    """Campo numérico para quantidades (aceita vírgula decimal e devolve ``float``)."""

    def __init__(self, mestre, tema: Tema, rotulo: str, obrigatorio: bool = False, dica: str = "",
                 largura: int = 10, minimo: float = 0.0, maximo: float = 1_000_000.0,
                 decimais: int = 4, ao_alterar: Callable[[float], None] | None = None):
        super().__init__(mestre, tema, rotulo, obrigatorio, dica, largura)
        self.minimo = minimo
        self.maximo = maximo
        self.decimais = decimais
        self.ao_alterar = ao_alterar
        if isinstance(self._widget, ttk.Entry):
            self._widget.configure(justify="right")
            self._widget.bind("<FocusOut>", self._ao_sair)
            self._widget.bind("<KeyRelease>", lambda e: self.ao_alterar and self.ao_alterar(self.valor()))

    def _ao_sair(self, _evento=None):
        self.definir(self.valor())

    def valor(self) -> float:
        bruto = self._widget.get().strip().replace(",", ".") if isinstance(self._widget, ttk.Entry) else ""
        if not bruto:
            return 0.0
        try:
            return round(float(bruto), self.decimais)
        except ValueError:
            return 0.0

    def definir(self, valor) -> None:
        try:
            numero = float(str(valor).replace(",", ".")) if valor not in (None, "") else 0.0
        except (TypeError, ValueError):
            numero = 0.0
        _limpar_texto(self._widget)
        self._widget.insert(0, formatar_quantidade(round(numero, self.decimais)))
        self.limpar_erro()

    def validar(self) -> tuple[bool, str]:
        valor = self.valor()
        if valor < self.minimo:
            return False, f"'{self.rotulo_texto}' deve ser maior ou igual a {self.minimo}."
        if valor > self.maximo:
            return False, f"'{self.rotulo_texto}' deve ser menor ou igual a {self.maximo}."
        return True, ""


class CampoLista(CampoBase):
    """Combobox (lista suspensa) com valores exibidos e valores reais separados."""

    def __init__(self, mestre, tema: Tema, rotulo: str, opcoes: Sequence = (), obrigatorio: bool = False,
                 dica: str = "", largura: int = 28, valores: Sequence | None = None, vazio: str = "",
                 somente_leitura: bool = True, ao_alterar: Callable | None = None):
        super().__init__(mestre, tema, rotulo, obrigatorio, dica, largura)
        self._rotulos: list[str] = []
        self._valores: list = []
        self.vazio = vazio
        self.ao_alterar = ao_alterar
        self._widget = ttk.Combobox(self, width=largura, state=("readonly" if somente_leitura else "normal"))
        self._widget.pack(fill="x", expand=True)
        self._widget.bind("<<ComboboxSelected>>", lambda e: self.ao_alterar and self.ao_alterar(self.valor()))
        if dica:
            ttk.Label(self, text=dica, style="Suave.TLabel").pack(anchor="w")
        self.definir_opcoes(opcoes, valores)

    def definir_opcoes(self, opcoes: Sequence, valores: Sequence | None = None) -> None:
        """``opcoes`` pode ser ``['a','b']`` ou ``[(id, 'rótulo'), ...]``."""
        self._rotulos, self._valores = [], []
        itens = list(opcoes or [])
        if itens and isinstance(itens[0], (tuple, list)):
            for valor, rotulo in itens:
                self._valores.append(valor)
                self._rotulos.append(str(rotulo))
        else:
            for item in itens:
                self._valores.append(item)
                self._rotulos.append(str(item))
        if self.vazio:
            self._rotulos.insert(0, self.vazio)
            self._valores.insert(0, None)
        self._widget.configure(values=self._rotulos)
        if self._rotulos and self._widget.get() not in self._rotulos:
            self._widget.current(0)

    def valor(self):
        texto = self._widget.get()
        if texto == self.vazio or texto == "":
            return None
        try:
            indice = self._rotulos.index(texto)
            return self._valores[indice]
        except ValueError:
            return texto

    def rotulo(self) -> str:
        return self._widget.get()

    def definir(self, valor) -> None:
        if valor in (None, ""):
            if self.vazio:
                self._widget.set(self.vazio)
            else:
                self._widget.set("")
            self.limpar_erro()
            return
        for indice, existente in enumerate(self._valores):
            if str(existente) == str(valor):
                self._widget.current(indice)
                self.limpar_erro()
                return
        self._widget.set(str(valor))
        self.limpar_erro()


class CampoData(CampoBase):
    """Data no formato brasileiro (``DD/MM/AAAA``), com validação real e calendário."""

    def __init__(self, mestre, tema: Tema, rotulo: str, obrigatorio: bool = False, dica: str = "",
                 largura: int = 12, padrao_hoje: bool = False):
        super().__init__(mestre, tema, rotulo, obrigatorio, dica or "DD/MM/AAAA", largura)
        self._widget = ttk.Entry(self, width=largura)
        self._widget.pack(side="left", fill="x", expand=True)
        botao = ttk.Button(self, text="📅", width=3, command=self.abrir_calendario)
        botao.pack(side="left", padx=(4, 0))
        if padrao_hoje:
            from ..utils import hoje

            self.definir(hoje())

    def valor(self) -> str:
        """Devolve a data em ISO (``YYYY-MM-DD``) ou ``''``."""
        from ..utils import converter_data_br

        return converter_data_br(self._widget.get()) or ""

    def definir(self, valor) -> None:
        from ..utils import converter_data_br, formatar_data

        iso = converter_data_br(str(valor or ""))
        _limpar_texto(self._widget)
        self._widget.insert(0, formatar_data(iso) if iso else "")
        self.limpar_erro()

    def validar(self) -> tuple[bool, str]:
        texto = self._widget.get().strip()
        if not texto:
            if self.obrigatorio:
                return False, f"O campo '{self.rotulo_texto}' é obrigatório."
            return True, ""
        if not self.valor():
            return False, f"Data inválida em '{self.rotulo_texto}'. Use DD/MM/AAAA."
        return True, ""

    def abrir_calendario(self) -> None:
        """Calendário simples (três botões: hoje, +/- dia e +/- mês) sem dependências."""
        from datetime import date, timedelta

        janela = tk.Toplevel(self)
        janela.title(f"Selecionar {self.rotulo_texto}")
        janela.configure(background=self.tema.cor("bg_card"))
        janela.resizable(False, False)
        janela.transient(self.winfo_toplevel())
        janela.grab_set()
        atual = self.valor() or date.today().isoformat()
        try:
            selecionada = date.fromisoformat(atual)
        except ValueError:
            selecionada = date.today()

        rotulo = ttk.Label(janela, style="Card.TLabel")
        rotulo.pack(pady=6)

        def desenhar():
            rotulo.configure(text=selecionada.strftime("%d/%m/%Y"))

        quadro = ttk.Frame(janela, style="Card.TFrame")
        quadro.pack(padx=10, pady=4)

        def mover(dias=0, meses=0):
            nonlocal selecionada
            selecionada = selecionada + timedelta(days=dias)
            if meses:
                mes = selecionada.month - 1 + meses
                ano = selecionada.year + mes // 12
                mes = mes % 12 + 1
                dia = min(selecionada.day, [31, 29 if ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0) else 28,
                                            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1])
                selecionada = selecionada.replace(year=ano, month=mes, day=dia)
            desenhar()

        ttk.Button(quadro, text="− ano", width=8, command=lambda: mover(meses=-12)).grid(row=0, column=0, padx=2)
        ttk.Button(quadro, text="− mês", width=8, command=lambda: mover(meses=-1)).grid(row=0, column=1, padx=2)
        ttk.Button(quadro, text="− dia", width=8, command=lambda: mover(dias=-1)).grid(row=0, column=2, padx=2)
        ttk.Button(quadro, text="+ dia", width=8, command=lambda: mover(dias=1)).grid(row=0, column=3, padx=2)
        ttk.Button(quadro, text="+ mês", width=8, command=lambda: mover(meses=1)).grid(row=0, column=4, padx=2)
        ttk.Button(quadro, text="+ ano", width=8, command=lambda: mover(meses=12)).grid(row=0, column=5, padx=2)

        base = ttk.Frame(janela, style="Card.TFrame")
        base.pack(padx=10, pady=8)
        ttk.Button(base, text="Hoje", command=lambda: (mover(0), _definir(date.today()))).pack(side="left", padx=3)

        def _definir(data: date):
            nonlocal selecionada
            selecionada = data
            self.definir(data.isoformat())
            janela.destroy()

        ttk.Button(base, text="Hoje", command=lambda: _definir(date.today())).pack(side="left", padx=3)
        ttk.Button(base, text="OK", style="Primario.TButton", command=lambda: _definir(selecionada)).pack(side="left", padx=3)
        ttk.Button(base, text="Cancelar", command=janela.destroy).pack(side="left", padx=3)
        desenhar()
        janela.bind("<Escape>", lambda e: janela.destroy())
        janela.focus_set()


class CampoImagem(CampoBase):
    """Seletor de foto do produto, com pré-visualização."""

    def __init__(self, mestre, tema: Tema, rotulo: str = "Foto", largura: int = 120, altura: int = 120):
        super().__init__(mestre, tema, rotulo, False, "JPG, PNG, GIF, BMP ou WEBP (máx. 8 MB)", largura)
        self.largura_px = largura
        self.altura_px = altura
        self._caminho: str = ""
        self._imagem = None
        self.rotulo_imagem = tk.Label(
            self, text="sem foto", width=largura, height=altura, relief="solid", bd=1,
            background=tema.cor("bg_alt"), foreground=tema.cor("fg_fraco"), font=FONTE_PEQUENA,
        )
        self.rotulo_imagem.pack(anchor="w", pady=2)
        botoes = ttk.Frame(self, style="TFrame")
        botoes.pack(anchor="w")
        ttk.Button(botoes, text="Carregar...", command=self.carregar).pack(side="left")
        ttk.Button(botoes, text="Remover", command=self.remover).pack(side="left", padx=4)
        self._widget = self.rotulo_imagem

    def carregar(self) -> None:
        from tkinter import filedialog

        arquivo = filedialog.askopenfilename(
            title="Selecione a foto do produto",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"), ("Todos os arquivos", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if arquivo:
            self.definir(arquivo)

    def definir(self, valor) -> None:
        self._caminho = str(valor or "")
        if not self._caminho:
            self._imagem = None
            self.rotulo_imagem.configure(image="", text="sem foto")
            return
        try:
            from PIL import Image, ImageTk

            imagem = Image.open(self._caminho)
            imagem.thumbnail((self.largura_px, self.altura_px))
            self._imagem = ImageTk.PhotoImage(imagem)
            self.rotulo_imagem.configure(image=self._imagem, text="")
        except Exception:
            self._imagem = None
            self.rotulo_imagem.configure(image="", text="foto inválida")

    def remover(self) -> None:
        self.definir("")

    def valor(self) -> str:
        return self._caminho


class CampoMarcar(CampoBase):
    """Caixa de seleção (checkbox)."""

    def __init__(self, mestre, tema: Tema, rotulo: str, dica: str = "", ao_alterar: Callable[[bool], None] | None = None):
        super().__init__(mestre, tema, rotulo, False, dica)
        self._variavel = tk.BooleanVar(value=False)
        self._widget = ttk.Checkbutton(self, text=rotulo, variable=self._variavel)
        self._widget.pack(anchor="w")
        self.rotulo.pack_forget()
        if ao_alterar:
            self._variavel.trace_add("write", lambda *_: ao_alterar(bool(self._variavel.get())))
        if dica:
            ttk.Label(self, text=dica, style="Suave.TLabel").pack(anchor="w")

    def valor(self) -> int:
        return 1 if self._variavel.get() else 0

    def definir(self, valor) -> None:
        self._variavel.set(bool(int(valor or 0)))


# --------------------------------------------------------------------------------------
# Blocos visuais
# --------------------------------------------------------------------------------------


class Cartao(ttk.Frame):
    """Cartão com título, valor e detalhe (usado no painel e nos resumos)."""

    def __init__(self, mestre, tema: Tema, titulo: str = "", valor: str = "", detalhe: str = "",
                 cor: str = "info", ao_clicar: Callable | None = None, largura_minima: int = 190):
        super().__init__(mestre, style="Card.TFrame")
        self.tema = tema
        self.configure(padding=12)
        self.titulo = ttk.Label(self, text=titulo, style="Card.Suave.TLabel")
        self.titulo.pack(anchor="w")
        self.valor = tk.Label(
            self, text=valor, font=FONTE_VALOR, background=tema.cor("bg_card"),
            foreground=tema.cor("fg"), anchor="w", justify="left",
        )
        self.valor.pack(anchor="w", pady=(2, 0))
        self.detalhe = ttk.Label(self, text=detalhe, style="Card.Suave.TLabel", wraplength=largura_minima, justify="left")
        self.detalhe.pack(anchor="w", pady=(2, 0))
        self.barra = tk.Frame(self, height=4, background=tema.cor("info"))
        self.barra.pack(side="bottom", fill="x", pady=(8, 0))
        self.definir_cor(cor)
        if ao_clicar:
            for widget in (self, self.titulo, self.valor, self.detalhe):
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", lambda e: ao_clicar())

    def definir(self, titulo: str | None = None, valor: str | None = None, detalhe: str | None = None, cor: str | None = None):
        if titulo is not None:
            self.titulo.configure(text=titulo)
        if valor is not None:
            self.valor.configure(text=valor)
        if detalhe is not None:
            self.detalhe.configure(text=detalhe)
        if cor:
            self.definir_cor(cor)

    def definir_cor(self, cor: str):
        mapa = {
            "info": "info",
            "sucesso": "sucesso",
            "alerta": "alerta",
            "perigo": "perigo",
            "neutro": "neutro",
            "primaria": "primaria",
        }
        self.barra.configure(background=self.tema.cor(mapa.get(cor, "info")))

    def atualizar_tema(self):
        self.valor.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"))


class EtiquetaEstado(tk.Label):
    """Selo colorido com a situação de um registro (paga, vencida, cancelada...)."""

    ROTULOS = {
        "concluida": "Concluída",
        "parcialmente_devolvida": "Devolução parcial",
        "devolvida": "Devolvida",
        "cancelada": "Cancelada",
        "aberta": "Aberta",
        "parcial": "Parcial",
        "paga": "Paga",
        "vencida": "Vencida",
        "cancelado": "Cancelado",
        "aberto": "Aberto",
        "fechado": "Fechado",
    }

    def __init__(self, mestre, tema: Tema, estado: str = "", texto: str | None = None):
        super().__init__(mestre, text="", font=("Segoe UI", 9, "bold"), padx=8, pady=2)
        self.tema = tema
        self.definir(estado, texto)

    def definir(self, estado: str, texto: str | None = None):
        self._estado = str(estado or "")
        fundo, cor = self.tema.cor_estado(self._estado)
        self.configure(
            text=(texto if texto is not None else self.ROTULOS.get(self._estado.lower(), self._estado.title())),
            background=fundo, foreground=cor,
        )


class BarraFerramentas(ttk.Frame):
    """Linha de botões padrão das telas (novo, editar, excluir, exportar...)."""

    def __init__(self, mestre, tema: Tema, botoes: Sequence[tuple] = (), lado_direito: Sequence[tuple] = ()):
        """``botoes`` é uma sequência de ``(texto, comando, estilo, atalho)``."""
        super().__init__(mestre, style="TFrame")
        self.tema = tema
        self.botoes: dict[str, ttk.Button] = {}
        for especificacao in botoes:
            texto, comando = especificacao[0], especificacao[1]
            estilo = especificacao[2] if len(especificacao) > 2 else "TButton"
            atalho = especificacao[3] if len(especificacao) > 3 else ""
            rotulo = f"{texto}  ({atalho})" if atalho else texto
            botao = ttk.Button(self, text=rotulo, command=comando, style=estilo)
            botao.pack(side="left", padx=(0, 6), pady=4)
            self.botoes[texto] = botao
        for especificacao in lado_direito:
            texto, comando = especificacao[0], especificacao[1]
            estilo = especificacao[2] if len(especificacao) > 2 else "TButton"
            botao = ttk.Button(self, text=texto, command=comando, style=estilo)
            botao.pack(side="right", padx=(6, 0), pady=4)
            self.botoes[texto] = botao

    def habilitar(self, texto: str, estado: bool = True):
        botao = self.botoes.get(texto)
        if botao is not None:
            botao.configure(state=("normal" if estado else "disabled"))


class BarraStatus(ttk.Frame):
    """Barra inferior com mensagens e indicadores rápidos."""

    def __init__(self, mestre, tema: Tema):
        super().__init__(mestre, style="TFrame")
        self.tema = tema
        self.configure(padding=(8, 4))
        self.mensagem = ttk.Label(self, text="Pronto.", style="Suave.TLabel", anchor="w")
        self.mensagem.pack(side="left", fill="x", expand=True)
        self.direita = ttk.Label(self, text="", style="Suave.TLabel", anchor="e")
        self.direita.pack(side="right")

    def definir(self, texto: str = "", direita: str = ""):
        if texto:
            self.mensagem.configure(text=texto)
        if direita:
            self.direita.configure(text=direita)


# --------------------------------------------------------------------------------------
# Gráfico simples (canvas, sem dependências)
# --------------------------------------------------------------------------------------


def grafico_barras(
    mestre,
    tema: Tema,
    valores: Sequence[float],
    rotulos: Sequence[str] = (),
    titulo: str = "",
    altura: int = 170,
    cor: str = "grafico",
    formatador: Callable[[float], str] = str,
) -> tk.Canvas:
    """Desenha um gráfico de barras em um ``Canvas`` (usado no painel)."""
    canvas = tk.Canvas(mestre, height=altura, highlightthickness=0, bd=0, background=tema.cor("bg_card"))
    canvas.pack(fill="both", expand=True)
    if titulo:
        canvas.create_text(10, 14, text=titulo, anchor="w", fill=tema.cor("fg_suave"), font=FONTE_PEQUENA)

    def redesenhar(_evento=None):
        canvas.delete("all")
        largura = max(60, canvas.winfo_width())
        altura_canvas = max(60, canvas.winfo_height())
        margem_esquerda, margem_inferior, margem_superior = 12, 26, 26 if titulo else 12
        area_altura = altura_canvas - margem_inferior - margem_superior
        area_largura = largura - 2 * margem_esquerda
        if titulo:
            canvas.create_text(10, 13, text=titulo, anchor="w", fill=tema.cor("fg_suave"), font=FONTE_PEQUENA)
        if not valores:
            canvas.create_text(largura / 2, altura_canvas / 2, text="Sem dados no período",
                               fill=tema.cor("fg_fraco"), font=FONTE_PEQUENA)
            return
        canvas.create_line(margem_esquerda, altura_canvas - margem_inferior, largura - margem_esquerda,
                           altura_canvas - margem_inferior, fill=tema.cor("borda"))
        maior = max(max(valores), 1)
        n = len(valores)
        largura_barra = max(4, (area_largura / max(1, n)) * 0.62)
        passo = area_largura / max(1, n)
        cor_barra = tema.cor(cor)
        for i, valor in enumerate(valores):
            x_centro = margem_esquerda + passo * (i + 0.5)
            altura_barra = (float(valor) / maior) * (area_altura - 6) if maior else 0
            topo = altura_canvas - margem_inferior - altura_barra
            canvas.create_rectangle(
                x_centro - largura_barra / 2, topo, x_centro + largura_barra / 2,
                altura_canvas - margem_inferior, fill=cor_barra, outline="",
            )
            if n <= 16 and i < len(rotulos):
                canvas.create_text(x_centro, altura_canvas - margem_inferior + 9, text=str(rotulos[i]),
                                   fill=tema.cor("fg_fraco"), font=("Segoe UI", 7))
            if valor and n <= 10:
                canvas.create_text(x_centro, topo - 8, text=formatador(valor), fill=tema.cor("fg_suave"),
                                   font=("Segoe UI", 7))
        # linha de referência do maior valor
        canvas.create_text(largura - margem_esquerda, margem_superior - 12, text=f"máx.: {formatador(maior)}",
                           anchor="e", fill=tema.cor("fg_fraco"), font=("Segoe UI", 7))

    canvas.bind("<Configure>", redesenhar)
    canvas.after(60, redesenhar)
    canvas._redesenhar = redesenhar  # type: ignore[attr-defined]
    return canvas


def atualizar_grafico(canvas: tk.Canvas) -> None:
    """Força o redesenho de um gráfico (usado na troca de tema)."""
    redesenhar = getattr(canvas, "_redesenhar", None)
    if callable(redesenhar):
        redesenhar()
