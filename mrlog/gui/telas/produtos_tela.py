"""
Tela de **Produtos** — cadastro completo, busca por código de barras e integrações
com estoque, etiquetas e PDV.

Destaques:
  * o campo "Bipar / código" fica com o foco assim que a tela abre: basta passar o
    produto no leitor para localizá-lo (ou cadastrá-lo, se for desconhecido);
  * cadastro com unidades de medida e conversão (venda fracionada), margem de lucro
    calculada automaticamente, foto opcional, lote/validade;
  * ações rápidas: entrada de estoque, gerar código de barras, imprimir etiquetas,
    desativar/reativar, reajuste de preços.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Sequence

from ... import categorias as categorias_mod
from ... import codigobarras
from ... import estoque as estoque_mod
from ... import fornecedores as fornecedores_mod
from ... import produtos as produtos_mod
from ... import unidades as unidades_mod
from ...caminhos import pasta_fotos
from ...utils import formatar_dinheiro, formatar_quantidade
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO
from ..widgets import CampoImagem, Tabela
from . import TelaLista, abrir_formulario, exportar_dados, imprimir_documento


class ProdutosTela(TelaLista):
    titulo = "Produtos"
    descricao = "Cadastro de produtos com código de barras, unidades, preços e estoque."
    permissao_editar = "produtos_editar"
    permissao_excluir = "produtos_excluir"

    def __init__(self, mestre, ctx):
        self._foto_atual: str = ""
        self._filtro_barras = tk.StringVar(value="Não")
        self._filtro_status = tk.StringVar(value="Ativos")
        self._apenas_baixo = tk.BooleanVar(value=False)
        self._apenas_sem_barras = tk.BooleanVar(value=False)
        self._termo = tk.StringVar(value="")
        self._categoria = tk.StringVar(value="")
        self._fornecedor = tk.StringVar(value="")
        self._opcoes_categoria: list[tuple[int, str]] = []
        self._opcoes_fornecedor: list[tuple[int, str]] = []
        super().__init__(
            mestre, ctx,
            colunas=self._colunas(),
            carregar_dados=self._dados,
            resumo=self._resumo,
            novo=self._novo,
            editar=self._editar,
            excluir=self._excluir,
            detalhes=self._detalhes,
            acoes=(
                ("📥 Entrada de estoque", self.entrada_estoque, "TButton", ""),
                ("🔖 Gerar código de barras", self.gerar_codigo, "TButton", ""),
                ("🖨️ Etiquetas", self.ir_para_etiquetas, "TButton", ""),
                ("⏻ Desativar/Reativar", self.alternar_status, "TButton", ""),
                ("📄 Ficha do produto", self.ficha_produto, "TButton", ""),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Produtos",
            altura_tabela=16,
            texto_vazio="Nenhum produto cadastrado. Clique em '＋ Novo' (Ctrl+N) para começar.",
        )
        self._montar_bipador()
        self._recarregar_opcoes()

    # ------------------------------------------------------------------ colunas
    @staticmethod
    def _colunas() -> list[dict]:
        return [
            {"chave": "codigo", "rotulo": "Código", "largura": 90, "tipo": "texto"},
            {"chave": "codigo_barras", "rotulo": "Cód. barras", "largura": 120, "tipo": "texto"},
            {"chave": "nome", "rotulo": "Produto", "largura": 300, "tipo": "texto"},
            {"chave": "categoria_nome", "rotulo": "Categoria", "largura": 130, "tipo": "texto"},
            {"chave": "marca", "rotulo": "Marca", "largura": 100, "tipo": "texto"},
            {"chave": "unidade_venda", "rotulo": "Un.", "largura": 50, "tipo": "texto", "alinhamento": "centro"},
            {"chave": "preco_venda", "rotulo": "Preço venda", "largura": 100, "tipo": "dinheiro"},
            {"chave": "preco_custo", "rotulo": "Custo", "largura": 90, "tipo": "dinheiro"},
            {"chave": "margem_pct", "rotulo": "Margem", "largura": 80, "tipo": "percentual"},
            {"chave": "estoque_atual", "rotulo": "Estoque", "largura": 90, "tipo": "quantidade"},
            {"chave": "estoque_minimo", "rotulo": "Mínimo", "largura": 80, "tipo": "quantidade"},
            {"chave": "fornecedor_nome", "rotulo": "Fornecedor", "largura": 150, "tipo": "texto"},
            {"chave": "status_texto", "rotulo": "Situação", "largura": 110, "tipo": "texto", "alinhamento": "centro"},
        ]

    # ------------------------------------------------------------------ filtros
    def _montar_filtros(self, pai: tk.Widget):
        ttk.Label(pai, text="Categoria:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.combo_categoria = ttk.Combobox(pai, textvariable=self._categoria, width=18, state="readonly", values=())
        self.combo_categoria.grid(row=0, column=1, padx=(0, 10))
        self.combo_categoria.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Fornecedor:", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.combo_fornecedor = ttk.Combobox(pai, textvariable=self._fornecedor, width=18, state="readonly", values=())
        self.combo_fornecedor.grid(row=0, column=3, padx=(0, 10))
        self.combo_fornecedor.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Label(pai, text="Situação:", style="Card.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 4))
        combo_status = ttk.Combobox(pai, textvariable=self._filtro_status, width=14, state="readonly",
                                    values=("Ativos", "Inativos", "Todos"))
        combo_status.grid(row=0, column=5, padx=(0, 10))
        combo_status.bind("<<ComboboxSelected>>", lambda e: self.carregar())

        ttk.Checkbutton(pai, text="Só estoque baixo", variable=self._apenas_baixo,
                        style="Card.TCheckbutton", command=self.carregar).grid(row=0, column=6, sticky="w")
        ttk.Checkbutton(pai, text="Só sem código de barras", variable=self._apenas_sem_barras,
                        style="Card.TCheckbutton", command=self.carregar).grid(row=0, column=7, sticky="w", padx=(6, 0))

        ttk.Label(pai, text="Busca (nome, código, barras, marca):", style="Card.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        entrada = ttk.Entry(pai, textvariable=self._termo, width=44)
        entrada.grid(row=1, column=2, columnspan=3, sticky="ew", pady=(8, 0))
        entrada.bind("<KeyRelease>", lambda e: self.carregar())
        ttk.Button(pai, text="Limpar filtros", command=self._limpar_filtros).grid(row=1, column=5, sticky="w", pady=(8, 0))
        pai.columnconfigure(3, weight=1)
        self._entrada_busca_filtro = entrada

    def _limpar_filtros(self):
        self._termo.set("")
        self._categoria.set("")
        self._fornecedor.set("")
        self._filtro_status.set("Ativos")
        self._apenas_baixo.set(False)
        self._apenas_sem_barras.set(False)
        self.carregar()

    def _recarregar_opcoes(self):
        self._opcoes_categoria = categorias_mod.opcoes(self.banco)
        self._opcoes_fornecedor = fornecedores_mod.opcoes(self.banco)
        nomes_categoria = ["(todas)"] + [nome for _, nome in self._opcoes_categoria]
        nomes_fornecedor = ["(todos)"] + [nome for _, nome in self._opcoes_fornecedor]
        if getattr(self, "combo_categoria", None) is not None:
            self.combo_categoria.configure(values=nomes_categoria)
            self.combo_fornecedor.configure(values=nomes_fornecedor)
            if not self._categoria.get():
                self.combo_categoria.set("(todas)")
            if not self._fornecedor.get():
                self.combo_fornecedor.set("(todos)")

    def _id_categoria(self) -> int | None:
        nome = self._categoria.get().strip()
        if nome in ("", "(todas)"):
            return None
        for identificador, rotulo in self._opcoes_categoria:
            if rotulo == nome:
                return identificador
        return None

    def _id_fornecedor(self) -> int | None:
        nome = self._fornecedor.get().strip()
        if nome in ("", "(todos)"):
            return None
        for identificador, rotulo in self._opcoes_fornecedor:
            if rotulo == nome:
                return identificador
        return None

    # ------------------------------------------------------------------ dados
    def _dados(self) -> list[dict]:
        self._recarregar_opcoes()
        status = self._filtro_status.get()
        produtos = produtos_mod.listar(
            self.banco,
            filtro=self._termo.get().strip(),
            categoria_id=self._id_categoria(),
            fornecedor_id=self._id_fornecedor(),
            incluir_inativos=status in ("Inativos", "Todos"),
            apenas_estoque_baixo=bool(self._apenas_baixo.get()),
            apenas_sem_barras=bool(self._apenas_sem_barras.get()),
        )
        if status == "Inativos":
            produtos = [p for p in produtos if not int(p["ativo"] or 0)]
        linhas = []
        for produto in produtos:
            linha = dict(produto)
            linha["status_texto"] = "Ativo" if int(produto["ativo"] or 0) else "Inativo"
            linhas.append(linha)
        return linhas

    def _resumo(self, dados: Sequence[dict]) -> str:
        total_venda = sum(int(d["preco_venda"] or 0) * float(d["estoque_atual"] or 0) for d in dados)
        total_custo = sum(int(d["preco_custo"] or 0) * float(d["estoque_atual"] or 0) for d in dados)
        baixos = sum(1 for d in dados if float(d["estoque_minimo"] or 0) > 0 and float(d["estoque_atual"] or 0) <= float(d["estoque_minimo"] or 0))
        texto = (f"{len(dados)} produto(s) • Estoque a custo: {formatar_dinheiro(int(total_custo))} • "
                 f"a preço de venda: {formatar_dinheiro(int(total_venda))}")
        if baixos:
            texto += f" • {baixos} abaixo do mínimo"
        return texto

    def _tag_linha(self, linha: dict) -> str:
        if not int(linha.get("ativo") or 0):
            return "neutro"
        minimo = float(linha.get("estoque_minimo") or 0)
        atual = float(linha.get("estoque_atual") or 0)
        if minimo > 0 and atual <= 0:
            return "perigo"
        if minimo > 0 and atual <= minimo:
            return "alerta"
        return ""

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        produto = produtos_mod.pegar(self.banco, linha["id"])
        if not produto:
            return []
        pares = [
            ("Descrição", produto["descricao"]),
            ("Localização", produto["localizacao"]),
            ("Unidade de estoque", f"{produto['unidade_base']} ({produto['unidade_base_nome']})"),
            ("Unidade de venda", f"{produto['unidade_venda']} — fator {formatar_quantidade(produto['fator_venda'])}"),
            ("Preço por unidade de estoque", formatar_dinheiro(produtos_mod.preco_por_unidade_base(produto))),
            ("Vende fracionado", "Sim" if int(produto["permite_fracionar"] or 0) else "Não"),
            ("Controla lote", "Sim" if int(produto["controla_lote"] or 0) else "Não"),
            ("Validade padrão", f"{produto['validade_dias']} dias" if produto["validade_dias"] else ""),
            ("Total já vendido", formatar_quantidade(produto["total_vendido"] or 0)),
            ("Última venda", str(produto["ultima_venda_em"] or "")[:16].replace("T", " ")),
            ("Custo médio", formatar_dinheiro(int(produto["preco_custo"] or 0))),
            ("Observação", produto["observacao"]),
        ]
        return [(rotulo, valor) for rotulo, valor in pares if valor]

    # ------------------------------------------------------------------ bipador
    def _montar_bipador(self):
        """Campo de código de barras sempre pronto para o leitor (USB)."""
        quadro = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
        quadro.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(quadro, text="🔎 Bipar / digitar código:", style="Card.TLabel",
                  font=FONTE_SUBTITULO).pack(side="left")
        self.entrada_codigo = ttk.Entry(quadro, width=28)
        self.entrada_codigo.pack(side="left", padx=(8, 6))
        self.entrada_codigo.bind("<Return>", self._ao_bipar)
        self.entrada_codigo.bind("<KP_Enter>", self._ao_bipar)
        self.entrada_codigo.bind("<FocusOut>", lambda e: self._reagendar_foco())
        ttk.Button(quadro, text="Localizar", command=self._ao_bipar).pack(side="left")
        ttk.Button(quadro, text="Cadastrar novo (F5)", command=self._novo).pack(side="left", padx=6)
        self.rotulo_bip = ttk.Label(quadro, text="", style="Card.Suave.TLabel", wraplength=520, justify="left")
        self.rotulo_bip.pack(side="left", padx=(12, 0))
        self._job_foco = None

    def _reagendar_foco(self):
        """Mantém o campo de código pronto para o leitor quando nada mais está em uso."""
        if self._job_foco:
            try:
                self.after_cancel(self._job_foco)
            except tk.TclError:
                pass
        self._job_foco = self.after(400, self._devolver_foco)

    def _devolver_foco(self):
        try:
            if not self.winfo_exists():
                return
            foco = self.winfo_toplevel().focus_get()
        except (KeyError, tk.TclError):
            foco = None
        if foco is None:
            self.focar_principal()

    def focar_principal(self):
        try:
            self.entrada_codigo.focus_set()
        except tk.TclError:
            pass

    def focar_busca(self):
        if getattr(self, "_entrada_busca_filtro", None) is not None:
            self._entrada_busca_filtro.focus_set()
            self._entrada_busca_filtro.select_range(0, "end")

    def _ao_bipar(self, _evento=None):
        codigo = self.entrada_codigo.get().strip()
        if not codigo:
            return "break"
        self.entrada_codigo.delete(0, "end")
        produto, como = produtos_mod.resolver_bipagem(self.banco, codigo)
        if produto is None:
            self.rotulo_bip.configure(text=f"'{codigo}' não encontrado.")
            if self._pode_editar() and dialogs.confirmar(
                self, self.tema,
                f"Nenhum produto encontrado para o código '{codigo}'.\n\nDeseja cadastrar este produto agora?",
                "Código desconhecido", "Cadastrar", "Cancelar",
            ):
                self._formulario(None, codigo_barras_inicial=codigo)
            return "break"
        self.rotulo_bip.configure(
            text=f"{produto['codigo']} — {produto['nome']} • "
                 f"{formatar_quantidade(produto['estoque_atual'] or 0)} {produto['unidade_base']} em estoque • "
                 f"{formatar_dinheiro(int(produto['preco_venda'] or 0))}/{produto['unidade_venda']}"
        )
        self._selecionar_na_tabela(produto["id"])
        if como == "nome":
            self.status(f"Produto localizado pelo nome: {produto['nome']}")
        return "break"

    def _selecionar_na_tabela(self, produto_id: int):
        self.tabela.selecionar_por("id", produto_id)

    # ------------------------------------------------------------------ formulário
    def _novo(self, _tela=None):
        self._formulario(None)

    def _editar(self, _tela=None, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        produto = produtos_mod.pegar(self.banco, linha["id"])
        if not produto:
            dialogs.erro(self, self.tema, "Produto não encontrado (pode ter sido excluído).")
            self.carregar()
            return
        self._formulario(produto)

    def _formulario(self, produto, codigo_barras_inicial: str = ""):
        unidades = unidades_mod.todas(self.banco)
        opcoes_unidade = [(u.sigla, u.rotulo) for u in unidades]
        opcoes_categoria = [(None, "(sem categoria)")] + list(categorias_mod.opcoes(self.banco))
        opcoes_fornecedor = [(None, "(sem fornecedor)")] + list(fornecedores_mod.opcoes(self.banco))
        editando = produto is not None

        valores: dict[str, Any] = {}
        if editando:
            valores = {
                "codigo": produto["codigo"], "codigo_barras": produto["codigo_barras"] or "",
                "nome": produto["nome"], "descricao": produto["descricao"],
                "categoria_id": produto["categoria_id"], "marca": produto["marca"],
                "fornecedor_id": produto["fornecedor_id"], "localizacao": produto["localizacao"],
                "unidade_base": produto["unidade_base"], "unidade_venda": produto["unidade_venda"],
                "fator_venda": float(produto["fator_venda"] or 1),
                "permite_fracionar": int(produto["permite_fracionar"] or 0),
                "decimais": int(produto["decimais"] or 0),
                "preco_custo": int(produto["preco_custo"] or 0),
                "preco_venda": int(produto["preco_venda"] or 0),
                "margem": float(produto["margem_pct"] or 0),
                "estoque_minimo": float(produto["estoque_minimo"] or 0),
                "estoque_maximo": float(produto["estoque_maximo"] or 0),
                "controla_lote": int(produto["controla_lote"] or 0),
                "validade_dias": produto["validade_dias"] if produto["validade_dias"] is not None else "",
                "peso_gramas": produto["peso_gramas"] or "",
                "observacao": produto["observacao"],
                "ativo": int(produto["ativo"] or 0),
                "foto": produto["foto"] or "",
            }
        else:
            valores = {
                "codigo": produtos_mod.proximo_codigo(self.banco),
                "codigo_barras": codigo_barras_inicial,
                "unidade_base": "un", "unidade_venda": "un", "fator_venda": 1.0,
                "permite_fracionar": 1, "decimais": 0, "ativo": 1,
            }

        secoes = [
            ("Identificação", [
                {"chave": "codigo", "rotulo": "Código interno", "tipo": "texto", "largura": 16, "obrigatorio": True,
                 "dica": "Deixe em branco para gerar automaticamente"},
                {"chave": "codigo_barras", "rotulo": "Código de barras (EAN)", "tipo": "texto", "largura": 18,
                 "apenas_numero": True, "dica": "Bipe a embalagem ou deixe vazio"},
                {"chave": "nome", "rotulo": "Nome do produto", "tipo": "texto", "largura": 34, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "descricao", "rotulo": "Descrição", "tipo": "texto", "largura": 34, "multilinea": True,
                 "altura": 3, "colunas": 3},
                {"chave": "categoria_id", "rotulo": "Categoria", "tipo": "lista", "opcoes": opcoes_categoria, "largura": 24},
                {"chave": "marca", "rotulo": "Marca", "tipo": "texto", "largura": 20},
                {"chave": "fornecedor_id", "rotulo": "Fornecedor", "tipo": "lista", "opcoes": opcoes_fornecedor, "largura": 24},
                {"chave": "localizacao", "rotulo": "Localização (prateleira)", "tipo": "texto", "largura": 20},
            ]),
            ("Unidades de medida", [
                {"chave": "unidade_base", "rotulo": "Unidade de estoque", "tipo": "lista", "opcoes": opcoes_unidade,
                 "largura": 22, "obrigatorio": True, "dica": "Como o saldo é controlado (ex.: kg)"},
                {"chave": "unidade_venda", "rotulo": "Unidade de venda", "tipo": "lista", "opcoes": opcoes_unidade,
                 "largura": 22, "obrigatorio": True, "dica": "Como o produto é vendido (ex.: g)"},
                {"chave": "fator_venda", "rotulo": "Fator (base em 1 de venda)", "tipo": "quantidade", "largura": 12,
                 "decimais": 6, "dica": "Ex.: 1 cx = 12 un → fator 12"},
                {"chave": "permite_fracionar", "rotulo": "Permitir venda fracionada", "tipo": "marcar",
                 "dica": "Ex.: vender 250 g de um produto estocado em kg"},
                {"chave": "decimais", "rotulo": "Casas decimais na quantidade", "tipo": "quantidade", "largura": 8,
                 "decimais": 0, "minimo": 0, "maximo": 4},
            ]),
            ("Preços", [
                {"chave": "preco_custo", "rotulo": "Preço de custo (por un. de venda)", "tipo": "dinheiro", "largura": 14},
                {"chave": "preco_venda", "rotulo": "Preço de venda (por un. de venda)", "tipo": "dinheiro", "largura": 14,
                 "obrigatorio": True},
                {"chave": "margem", "rotulo": "Margem de lucro (%)", "tipo": "quantidade", "largura": 10, "decimais": 2,
                 "dica": "Calculada automaticamente"},
            ]),
            ("Estoque", [
                {"chave": "estoque_minimo", "rotulo": "Estoque mínimo", "tipo": "quantidade", "largura": 12, "decimais": 3},
                {"chave": "estoque_maximo", "rotulo": "Estoque máximo (0 = sem limite)", "tipo": "quantidade",
                 "largura": 12, "decimais": 3},
                {"chave": "estoque_inicial", "rotulo": "Saldo inicial" + ("" if not editando else " (só no cadastro)"),
                 "tipo": "quantidade", "largura": 12, "decimais": 3,
                 "dica": "Gera uma movimentação de inventário inicial"},
            ]),
            ("Lote, validade e outros", [
                {"chave": "controla_lote", "rotulo": "Controlar lote e validade", "tipo": "marcar",
                 "dica": "Exige informar lote/validade nas entradas"},
                {"chave": "validade_dias", "rotulo": "Validade padrão (dias)", "tipo": "quantidade", "largura": 10,
                 "decimais": 0, "dica": "Opcional — pode ser informada por lote"},
                {"chave": "peso_gramas", "rotulo": "Peso (gramas)", "tipo": "quantidade", "largura": 10, "decimais": 3},
                {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "multilinea": True,
                 "altura": 3, "colunas": 3},
                {"chave": "ativo", "rotulo": "Produto ativo", "tipo": "marcar"},
            ]),
        ]

        dialogo = dialogs.DialogoFormulario(
            self.ctx.janela, self.tema,
            "Editar produto" if editando else "Novo produto",
            secoes, valores, largura=760, altura=640,
        )
        # campo de foto (widget próprio, fora do formulário genérico)
        quadro_foto = ttk.Frame(dialogo.corpo, style="TFrame")
        quadro_foto.pack(side="bottom", fill="x", pady=(0, 4))
        campo_foto = CampoImagem(quadro_foto, self.tema, "Foto do produto (opcional)", largura=110, altura=110)
        campo_foto.pack(side="left")
        if valores.get("foto"):
            from ...caminhos import pasta_fotos as _pasta_fotos

            caminho = _pasta_fotos() / valores["foto"]
            if caminho.exists():
                campo_foto.definir(str(caminho))
        self._campo_foto = campo_foto

        # cálculo automático da margem / preço
        campo_custo = dialogo.campo("preco_custo")
        campo_venda = dialogo.campo("preco_venda")
        campo_margem = dialogo.campo("margem")

        def recalcular_margem(_valor=None):
            custo = campo_custo.valor() or 0
            venda = campo_venda.valor() or 0
            if venda > 0:
                campo_margem.definir(round(produtos_mod.calcular_margem(custo, venda), 2))

        def aplicar_margem(_valor=None):
            custo = campo_custo.valor() or 0
            margem = campo_margem.valor() or 0
            if custo > 0 and margem > 0:
                campo_venda.definir(produtos_mod.preco_por_margem(custo, margem))
                recalcular_margem()

        campo_custo.ao_alterar = lambda _v: recalcular_margem()
        campo_venda.ao_alterar = lambda _v: recalcular_margem()
        ttk.Button(quadro_foto, text="Calcular preço pela margem", command=aplicar_margem).pack(side="left", padx=12)
        ttk.Button(quadro_foto, text="Gerar código de barras",
                   command=lambda: self._gerar_barras_no_formulario(dialogo)).pack(side="left")
        if editando:
            dialogo.campo("estoque_inicial").habilitar(False)
            dialogo.campo("unidade_base").habilitar(False)

        resultado = dialogo.abrir()
        if resultado is None:
            return
        self._salvar(produto, resultado, campo_foto.valor())

    def _gerar_barras_no_formulario(self, dialogo):
        try:
            codigo = produtos_mod.gerar_codigo_barras(self.banco)
        except Exception as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        dialogo.campo("codigo_barras").definir(codigo)
        self.status(f"Código de barras gerado: {codigo}")

    def _salvar(self, produto, dados: dict, foto: str):
        registro = {
            "codigo": dados.get("codigo") or "",
            "codigo_barras": dados.get("codigo_barras") or "",
            "nome": dados.get("nome") or "",
            "descricao": dados.get("descricao") or "",
            "categoria_id": dados.get("categoria_id"),
            "marca": dados.get("marca") or "",
            "fornecedor_id": dados.get("fornecedor_id"),
            "localizacao": dados.get("localizacao") or "",
            "unidade_base": dados.get("unidade_base") or "un",
            "unidade_venda": dados.get("unidade_venda") or "un",
            "fator_venda": dados.get("fator_venda") or 1,
            "permite_fracionar": dados.get("permite_fracionar", 1),
            "decimais": dados.get("decimais", 0),
            "preco_custo": dados.get("preco_custo", 0),
            "preco_venda": dados.get("preco_venda", 0),
            "estoque_minimo": dados.get("estoque_minimo", 0),
            "estoque_maximo": dados.get("estoque_maximo", 0),
            "controla_lote": dados.get("controla_lote", 0),
            "validade_dias": dados.get("validade_dias", ""),
            "peso_gramas": dados.get("peso_gramas", 0),
            "observacao": dados.get("observacao") or "",
            "ativo": dados.get("ativo", 1),
        }
        try:
            if produto is None:
                produto_id = produtos_mod.criar(
                    self.banco, registro,
                    estoque_inicial=float(dados.get("estoque_inicial") or 0),
                    foto=foto or None, autor=self.usuario,
                )
                texto = f"Produto '{registro['nome']}' cadastrado com sucesso."
            else:
                produto_id = produtos_mod.atualizar(self.banco, produto["id"], registro, foto=foto or None,
                                                    autor=self.usuario)
                texto = f"Produto '{registro['nome']}' atualizado."
        except produtos_mod.ErroProduto as exc:
            dialogs.erro(self, self.tema, str(exc), "Não foi possível salvar o produto")
            return
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao salvar o produto.")
            return
        novo = produtos_mod.pegar(self.banco, produto_id)
        if novo and produtos_mod.preco_abaixo_do_custo(novo):
            texto += "\n\nAtenção: o preço de venda está abaixo do preço de custo (margem negativa)."
        self.carregar()
        self._selecionar_na_tabela(produto_id)
        dialogs.sucesso(self, self.tema, texto)
        if produto is None and dialogs.confirmar(self, self.tema,
                                                 "Deseja imprimir etiquetas de código de barras deste produto agora?",
                                                 "Etiquetas", "Sim", "Depois"):
            self.ctx.navegar("etiquetas", {"produto_ids": [produto_id]})

    def _excluir(self, _tela, linha: dict):
        if not dialogs.confirmar(self, self.tema,
                                 f"Excluir definitivamente o produto '{linha['nome']}'?\n\n"
                                 "Esta ação não pode ser desfeita.", "Excluir produto", "Excluir", "Cancelar"):
            return None
        try:
            produtos_mod.excluir(self.banco, linha["id"], autor=self.usuario)
        except produtos_mod.ErroProduto as exc:
            dialogs.alerta(self, self.tema, str(exc), "Exclusão bloqueada")
            return None
        self.carregar()
        dialogs.sucesso(self, self.tema, f"Produto '{linha['nome']}' excluído.")
        return True

    # ------------------------------------------------------------------ ações
    def alternar_status(self):
        linha = self.exigir_selecao()
        if not linha or not self._pode_editar():
            return
        ativo = int(linha["ativo"] or 0)
        try:
            if ativo:
                if not dialogs.confirmar(self, self.tema,
                                         f"Desativar '{linha['nome']}'?\nEle deixa de aparecer no PDV e nas buscas.",
                                         "Desativar produto", "Desativar", "Cancelar"):
                    return
                produtos_mod.desativar(self.banco, linha["id"], autor=self.usuario)
                self.status(f"Produto '{linha['nome']}' desativado.")
            else:
                produtos_mod.reativar(self.banco, linha["id"], autor=self.usuario)
                self.status(f"Produto '{linha['nome']}' reativado.")
        except produtos_mod.ErroProduto as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()

    def gerar_codigo(self):
        linha = self.exigir_selecao()
        if not linha or not self._pode_editar():
            return
        produto = produtos_mod.pegar(self.banco, linha["id"])
        if produto["codigo_barras"]:
            if not dialogs.confirmar(self, self.tema,
                                     f"Este produto já tem o código {produto['codigo_barras']}.\nGerar um novo código?",
                                     "Gerar código", "Gerar novo", "Cancelar"):
                return
        try:
            codigo = produtos_mod.gerar_codigo_barras(self.banco, produto["id"], autor=self.usuario)
        except Exception as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Código de barras gerado para '{produto['nome']}':\n{codigo}\n\n"
                        "Agora você pode imprimir as etiquetas (F11).")

    def gerar_codigo_em_lote(self):
        """Gera código de barras para todos os produtos que ainda não têm."""
        if not self._pode_editar():
            return
        pendentes = produtos_mod.listar(self.banco, apenas_sem_barras=True, incluir_inativos=False)
        if not pendentes:
            dialogs.info(self, self.tema, "Todos os produtos ativos já possuem código de barras.")
            return
        if not dialogs.confirmar(self, self.tema,
                                 f"{len(pendentes)} produto(s) sem código de barras.\nGerar códigos EAN-13 internos para todos?",
                                 "Gerar códigos", "Gerar", "Cancelar"):
            return
        quantidade = 0
        try:
            for produto in pendentes:
                produtos_mod.gerar_codigo_barras(self.banco, produto["id"], autor=self.usuario)
                quantidade += 1
        except Exception as exc:
            dialogs.alerta(self, self.tema, f"{quantidade} código(s) gerado(s) antes do erro:\n{exc}")
        self.carregar()
        dialogs.sucesso(self, self.tema, f"{quantidade} código(s) de barras gerado(s).")

    def ir_para_etiquetas(self):
        linha = self.selecionado()
        parametros = {"produto_ids": [linha["id"]]} if linha else {}
        self.ctx.navegar("etiquetas", parametros)

    def entrada_estoque(self):
        """Entrada rápida (compra/devolução) direto da tela de produtos."""
        if not self.exigir("estoque_movimentar", "dar entrada no estoque"):
            return
        linha = self.exigir_selecao()
        if not linha:
            return
        produto = produtos_mod.pegar(self.banco, linha["id"])
        controla_lote = int(produto["controla_lote"] or 0)
        campos = [
            {"chave": "quantidade", "rotulo": f"Quantidade ({produto['unidade_base']})", "tipo": "quantidade",
             "obrigatorio": True, "decimais": 3, "minimo": 0.0001},
            {"chave": "custo", "rotulo": "Custo unitário", "tipo": "dinheiro",
             "dica": "Em branco mantém o custo atual do produto"},
            {"chave": "motivo", "rotulo": "Motivo", "tipo": "lista", "largura": 30,
             "opcoes": [(chave, rotulo) for chave, rotulo in estoque_mod.MOTIVOS.items()
                        if chave in ("compra", "devolucao_cliente", "transferencia_entrada",
                                     "producao", "ajuste_positivo", "outros")]},
            {"chave": "documento", "rotulo": "Nº do documento / nota", "tipo": "texto", "largura": 20},
            {"chave": "observacao", "rotulo": "Observação", "tipo": "texto", "largura": 34, "colunas": 2},
        ]
        if controla_lote:
            campos += [
                {"chave": "lote", "rotulo": "Número do lote", "tipo": "texto", "largura": 18, "obrigatorio": True},
                {"chave": "validade", "rotulo": "Validade do lote", "tipo": "data"},
            ]
        valores = {"custo": int(produto["preco_custo"] or 0), "motivo": "compra"}
        dados = abrir_formulario(self, f"Entrada de estoque — {produto['nome']}", campos, valores, largura=560)
        if not dados:
            return
        try:
            estoque_mod.entrada(
                self.banco, produto["id"], float(dados["quantidade"]),
                motivo=dados["motivo"],
                custo_unitario=int(dados["custo"] or 0),
                documento=dados.get("documento", ""),
                observacao=dados.get("observacao", ""),
                lote_numero=dados.get("lote", ""),
                validade=dados.get("validade", ""),
                fornecedor_id=produto["fornecedor_id"],
                autor=self.usuario,
            )
        except estoque_mod.ErroEstoque as exc:
            dialogs.erro(self, self.tema, str(exc), "Entrada não registrada")
            return
        self.carregar()
        self.ctx.app.atualizar_caixa()
        atual = produtos_mod.pegar(self.banco, produto["id"])
        dialogs.sucesso(self, self.tema,
                        f"Entrada registrada.\nNovo saldo: {formatar_quantidade(atual['estoque_atual'] or 0)} "
                        f"{atual['unidade_base']}\nCusto médio: {formatar_dinheiro(int(atual['preco_custo'] or 0))}")

    def ficha_produto(self):
        linha = self.exigir_selecao()
        if not linha:
            return
        from ... import impressao as impressao_mod

        try:
            caminho = impressao_mod.gerar_ficha_produto_pdf(self.banco, linha["id"])
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Não foi possível gerar a ficha do produto.")
            return
        imprimir_documento(self, self.tema, caminho, "Ficha do produto")

    def reajustar_precos(self):
        """Reajuste em massa (por categoria ou geral) — exige permissão de preços."""
        if not self.exigir("produtos_preco_editar", "reajustar preços"):
            return
        opcoes = [(None, "(todos os produtos)")] + list(categorias_mod.opcoes(self.banco))
        dados = abrir_formulario(
            self, "Reajuste de preços de venda",
            [
                {"chave": "percentual", "rotulo": "Percentual (%)", "tipo": "quantidade", "obrigatorio": True,
                 "decimais": 2, "minimo": -99.0, "dica": "Use negativo para desconto (ex.: -5)"},
                {"chave": "categoria_id", "rotulo": "Aplicar em", "tipo": "lista", "opcoes": opcoes, "largura": 28},
            ],
            {"percentual": 0}, largura=460,
            texto="O reajuste é aplicado sobre o preço de venda atual e fica registrado no log do sistema.",
        )
        if not dados:
            return
        if not dialogs.confirmar(self, self.tema,
                                 f"Aplicar reajuste de {dados['percentual']}% nos preços de venda?",
                                 "Confirmar reajuste", "Aplicar", "Cancelar"):
            return
        try:
            quantidade = produtos_mod.aplicar_reajuste(self.banco, float(dados["percentual"]),
                                                       categoria_id=dados.get("categoria_id"), autor=self.usuario)
        except produtos_mod.ErroProduto as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, f"{quantidade} produto(s) reajustado(s).")

    # ------------------------------------------------------------------ teclas
    def ao_tecla(self, tecla: str) -> bool:
        if tecla == "<F5>":
            self._novo()
            return True
        return False

    def receber_parametros(self, parametros: dict):
        """Recebe o foco vindo de outras telas (categorias, fornecedores, estoque...)."""
        parametros = parametros or {}
        if parametros.get("categoria"):
            self._categoria.set(str(parametros["categoria"]))
        if parametros.get("fornecedor"):
            self._fornecedor.set(str(parametros["fornecedor"]))
        if parametros.get("apenas_estoque_baixo") is not None:
            self._apenas_baixo.set(bool(parametros["apenas_estoque_baixo"]))
        if parametros.get("apenas_sem_barras") is not None:
            self._sem_barras.set(bool(parametros["apenas_sem_barras"]))
        if "termo" in parametros:
            self._termo.set(str(parametros["termo"] or ""))
        if any(chave in parametros for chave in
               ("categoria", "fornecedor", "termo", "apenas_estoque_baixo", "apenas_sem_barras")):
            self.carregar()
        if parametros.get("produto_id"):
            self._selecionar_na_tabela(int(parametros["produto_id"]))

    def atualizar_tema(self):
        super().atualizar_tema()
        self.rotulo_bip.configure(style="Card.Suave.TLabel")


# --------------------------------------------------------------------------------------
# Cadastro rápido (usado pelo PDV quando o código bipado não existe)
# --------------------------------------------------------------------------------------


def cadastro_rapido(ctx, codigo_barras_digitado: str = ""):
    """Abre um cadastro enxuto e devolve o produto criado (ou ``None``).

    Chamado pelo PDV quando o leitor bipa um código desconhecido: o código já vem
    preenchido e o produto é criado com o mínimo de campos, sem tirar o operador
    do fluxo da venda.
    """
    unidades = unidades_mod.todas(ctx.banco)
    opcoes_unidade = [(u.sigla, u.rotulo) for u in unidades]
    opcoes_categoria = [(None, "(sem categoria)")] + list(categorias_mod.opcoes(ctx.banco))
    secoes = [
        ("", [
            {"chave": "codigo_barras", "rotulo": "Código de barras", "tipo": "texto", "largura": 18,
             "apenas_numero": True, "dica": "Já preenchido pelo leitor"},
            {"chave": "codigo", "rotulo": "Código interno", "tipo": "texto", "largura": 14,
             "dica": "Vazio = automático"},
            {"chave": "nome", "rotulo": "Nome do produto", "tipo": "texto", "largura": 30, "obrigatorio": True,
             "colunas": 2},
            {"chave": "categoria_id", "rotulo": "Categoria", "tipo": "lista", "opcoes": opcoes_categoria, "largura": 22},
            {"chave": "unidade_base", "rotulo": "Unidade", "tipo": "lista", "opcoes": opcoes_unidade, "largura": 22},
            {"chave": "preco_venda", "rotulo": "Preço de venda", "tipo": "dinheiro", "largura": 12, "obrigatorio": True},
            {"chave": "preco_custo", "rotulo": "Preço de custo", "tipo": "dinheiro", "largura": 12},
            {"chave": "estoque_inicial", "rotulo": "Estoque inicial", "tipo": "quantidade", "largura": 10,
             "decimais": 3},
            {"chave": "permite_fracionar", "rotulo": "Permitir venda fracionada", "tipo": "marcar"},
        ]),
    ]
    valores = {
        "codigo_barras": codigo_barras_digitado,
        "codigo": produtos_mod.proximo_codigo(ctx.banco),
        "unidade_base": "un", "permite_fracionar": 1,
    }
    dialogo = dialogs.DialogoFormulario(
        ctx.janela, ctx.tema, "Cadastro rápido de produto", secoes, valores, largura=620, altura=460,
        texto_rotulo_botao="Cadastrar e adicionar",
    )
    resultado = dialogo.abrir()
    if resultado is None:
        return None
    registro = {
        "codigo": resultado.get("codigo") or "",
        "codigo_barras": resultado.get("codigo_barras") or "",
        "nome": resultado.get("nome") or "",
        "categoria_id": resultado.get("categoria_id"),
        "unidade_base": resultado.get("unidade_base") or "un",
        "unidade_venda": resultado.get("unidade_base") or "un",
        "fator_venda": 1,
        "permite_fracionar": resultado.get("permite_fracionar", 1),
        "preco_custo": resultado.get("preco_custo", 0),
        "preco_venda": resultado.get("preco_venda", 0),
        "ativo": 1,
    }
    try:
        produto_id = produtos_mod.criar(ctx.banco, registro,
                                        estoque_inicial=float(resultado.get("estoque_inicial") or 0),
                                        autor=ctx.usuario)
    except produtos_mod.ErroProduto as exc:
        dialogs.erro(ctx.janela, ctx.tema, str(exc), "Não foi possível cadastrar")
        return None
    ctx.banco.registrar_log("produto_cadastro_rapido", f"{registro['codigo_barras']} — {registro['nome']}",
                            ctx.usuario["id"] if ctx.usuario else None, ctx.nome_usuario)
    dialogs.sucesso(ctx.janela, ctx.tema, f"Produto '{registro['nome']}' cadastrado.", "Cadastro rápido")
    return produtos_mod.pegar(ctx.banco, produto_id)


def selecionar_produto(ctx, titulo: str = "Selecionar produto", texto: str = ""):
    """Diálogo de busca de produtos usado pelo PDV e por outras telas."""
    colunas = [
        {"chave": "codigo", "rotulo": "Código", "largura": 90},
        {"chave": "codigo_barras", "rotulo": "Barras", "largura": 120},
        {"chave": "nome", "rotulo": "Produto", "largura": 280},
        {"chave": "unidade_venda", "rotulo": "Un.", "largura": 50, "alinhamento": "centro"},
        {"chave": "preco_venda", "rotulo": "Preço", "largura": 90, "tipo": "dinheiro"},
        {"chave": "estoque_atual", "rotulo": "Estoque", "largura": 90, "tipo": "quantidade"},
    ]

    def buscar(termo: str):
        produtos = produtos_mod.buscar(ctx.banco, termo, limite=200)
        return [dict(p) for p in produtos]

    linha = dialogs.selecionar_registro(
        ctx.janela, ctx.tema, titulo, colunas, buscar(""), ao_buscar=buscar, largura=780,
        texto=texto or "Digite parte do nome, código ou código de barras e clique duas vezes no produto.",
    )
    if not linha:
        return None
    return produtos_mod.pegar(ctx.banco, linha["id"])
