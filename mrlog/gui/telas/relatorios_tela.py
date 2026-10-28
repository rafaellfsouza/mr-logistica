"""
Tela de Relatórios.

Um único lugar para gerar **todos** os relatórios do sistema (vendas, financeiro,
estoque e cadastros). A lista da esquerda vem direto de :data:`mrlog.relatorios.meta`
— ou seja, quando um relatório novo é cadastrado no módulo de dados ele aparece
aqui automaticamente, sem tocar nesta tela.

Fluxo:
  1. o usuário escolhe o relatório (clique único já gera o resultado);
  2. o painel de parâmetros é montado dinamicamente conforme o que aquele
     relatório aceita (período, cliente, vendedor, categoria, situação...);
  3. o resultado aparece em cartões + grade (com busca, ordenação e paginação);
  4. é possível exportar para Excel/PDF/CSV, imprimir e ver o detalhe da linha.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ... import categorias as categorias_mod
from ... import estoque as estoque_mod
from ... import exportacao as exportacao_mod
from ... import formas_pagamento
from ... import fornecedores as fornecedores_mod
from ... import relatorios as relatorios_mod
from ... import usuarios as usuarios_mod
from ...esquema import CATEGORIAS_DESPESA
from ...utils import (
    converter_data_br,
    formatar_data,
    formatar_dinheiro,
    formatar_quantidade,
    hoje,
    intervalo_padrao,
    primeiro_dia_mes,
    somar_dias,
)
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO
from ..widgets import Cartao, Tabela
from . import DialogoExportar, Tela, abrir_pasta_do_arquivo, imprimir_documento

# --------------------------------------------------------------------------------------
# Tabelas de apoio
# --------------------------------------------------------------------------------------

#: Períodos prontos (o usuário também pode digitar datas livres em "Personalizado").
PERIODOS: tuple[tuple[str, object], ...] = (
    ("Hoje", "hoje"),
    ("Ontem", "ontem"),
    ("Últimos 7 dias", 7),
    ("Últimos 30 dias", 30),
    ("Últimos 90 dias", 90),
    ("Este mês", "mes_atual"),
    ("Mês anterior", "mes_anterior"),
    ("Últimos 12 meses", 365),
    ("Este ano", "ano_atual"),
    ("Personalizado", "personalizado"),
)
PERIODO_PADRAO = "Últimos 30 dias"

#: Situações aceitas pelos relatórios de contas a receber/pagar.
OPCOES_STATUS_CONTA = (
    ("pendentes", "Pendentes (em aberto)"),
    ("aberta", "Em aberto (a vencer)"),
    ("parcial", "Parciais"),
    ("vencida", "Vencidas"),
    ("paga", "Quitadas"),
    ("cancelada", "Canceladas"),
    ("todas", "Todas"),
)

#: Ordem do ranking "produtos mais vendidos".
OPCOES_ORDEM = (("total", "Por faturamento (R$)"), ("quantidade", "Por quantidade vendida"))

#: Tipos de movimentação de estoque.
OPCOES_TIPO_MOVIMENTO = (("", "Entradas e saídas"), ("entrada", "Somente entradas"), ("saida", "Somente saídas"))

#: Rótulos/formato dos totais devolvidos pelos relatórios.
FORMATO_TOTAIS = {
    "total": "dinheiro", "total_liquido": "dinheiro", "lucro": "dinheiro", "receita": "dinheiro",
    "receita_liquida": "dinheiro", "cmv": "dinheiro", "despesas": "dinheiro", "resultado": "dinheiro",
    "saldo": "dinheiro", "valor": "dinheiro", "valor_estoque": "dinheiro", "estoque_valor": "dinheiro",
    "a_receber": "dinheiro", "a_pagar": "dinheiro", "vencido": "dinheiro", "recebido": "dinheiro",
    "pago": "dinheiro", "custo": "dinheiro", "ticket_medio": "dinheiro", "subtotal": "dinheiro",
    "desconto": "dinheiro", "entradas": "dinheiro", "saidas": "dinheiro", "troco": "dinheiro",
    "fiado": "dinheiro", "margem": "percentual", "participacao": "percentual",
    "vendas": "inteiro", "produtos": "inteiro", "clientes": "inteiro", "fornecedores": "inteiro",
    "usuarios": "inteiro", "lotes": "inteiro", "itens": "inteiro", "movimentos": "inteiro",
    "contas": "inteiro", "titulos": "inteiro", "fechamentos": "inteiro", "quantidade": "quantidade",
}

#: Rótulos amigáveis dos totais (os não listados são derivados da chave).
ROTULOS_TOTAIS = {
    "total": "Total", "total_liquido": "Total líquido", "lucro": "Lucro", "receita": "Receita",
    "receita_liquida": "Receita líquida", "cmv": "CMV", "despesas": "Despesas", "resultado": "Resultado",
    "saldo": "Saldo", "valor": "Valor", "valor_estoque": "Valor em estoque", "estoque_valor": "Valor em estoque",
    "a_receber": "A receber", "a_pagar": "A pagar", "vencido": "Vencido", "recebido": "Recebido",
    "pago": "Pago", "custo": "Custo", "ticket_medio": "Ticket médio", "subtotal": "Subtotal",
    "desconto": "Descontos", "entradas": "Entradas", "saidas": "Saídas", "troco": "Troco",
    "fiado": "Fiado", "margem": "Margem", "participacao": "Participação", "vendas": "Vendas",
    "produtos": "Produtos", "clientes": "Clientes", "fornecedores": "Fornecedores",
    "usuarios": "Usuários", "lotes": "Lotes", "itens": "Itens", "movimentos": "Movimentações",
    "contas": "Contas", "titulos": "Títulos", "fechamentos": "Fechamentos", "quantidade": "Quantidade",
}

#: Chaves que, mesmo sem rótulo conhecido, devem ser tratadas como dinheiro.
_INDICIOS_DINHEIRO = ("total", "valor", "lucro", "saldo", "receita", "custo", "despesa", "pago",
                      "recebido", "prejuizo", "troco", "fiado", "cmv", "resultado", "margem_em")


def _formatar_total(chave: str, valor) -> str:
    """Formata um total do relatório de acordo com o tipo esperado."""
    formato = FORMATO_TOTAIS.get(chave)
    if formato is None:
        formato = "dinheiro" if any(indicio in chave for indicio in _INDICIOS_DINHEIRO) else "inteiro"
    try:
        if formato == "dinheiro":
            return formatar_dinheiro(int(valor or 0))
        if formato == "percentual":
            return f"{float(valor or 0):.2f}%".replace(".", ",")
        if formato == "quantidade":
            return formatar_quantidade(valor)
        return str(int(valor or 0))
    except (TypeError, ValueError):
        return str(valor)


def _rotulo_total(chave: str) -> str:
    if chave in ROTULOS_TOTAIS:
        return ROTULOS_TOTAIS[chave]
    return chave.replace("_", " ").strip().capitalize()


def _tag_da_linha(linha: dict) -> str:
    """Realce automático de linhas críticas (vencidas, estoque baixo, lotes vencidos)."""
    situacao = str(linha.get("situacao") or "").strip().upper()
    if situacao in ("VENCIDO", "CRÍTICO", "CRITICO", "BAIXO", "NEGATIVO"):
        return "perigo"
    if situacao in ("ATENÇÃO", "ATENCAO", "PARCIAL"):
        return "alerta"
    status = str(linha.get("status") or "").strip().lower()
    if status in ("vencida", "vencido", "inativo", "bloqueado"):
        return "perigo" if status.startswith("venc") else "neutro"
    if status in ("paga", "quitada", "concluida", "ativo", "fechado"):
        return "sucesso"
    if status in ("parcial", "parcialmente_devolvida", "aberto"):
        return "alerta"
    dias = linha.get("dias_para_vencer")
    if isinstance(dias, (int, float)) and dias < 0:
        return "perigo"
    if isinstance(dias, (int, float)) and dias <= 7:
        return "alerta"
    estoque_atual = linha.get("estoque_atual")
    estoque_minimo = linha.get("estoque_minimo")
    if isinstance(estoque_atual, (int, float)) and isinstance(estoque_minimo, (int, float)):
        if estoque_minimo > 0 and estoque_atual <= estoque_minimo:
            return "alerta"
    return ""


class DialogoDetalhesLinha(dialogs.Modal):
    """Mostra todos os campos de uma linha do relatório (duplo clique na grade)."""

    def __init__(self, mestre, tema, titulo: str, colunas: list[dict], linha: dict):
        super().__init__(mestre, tema, titulo, largura=620, altura=520)
        ttk.Label(self.corpo, text="Detalhes do registro", style="TLabel", font=FONTE_SUBTITULO).pack(anchor="w")
        ttk.Label(self.corpo, text="Valores exatamente como aparecem no relatório.",
                  style="Suave.TLabel").pack(anchor="w", pady=(0, 8))
        quadro = ttk.Frame(self.corpo, style="Card.TFrame", padding=10)
        quadro.pack(fill="both", expand=True)
        quadro.columnconfigure(1, weight=1)
        for indice, coluna in enumerate(colunas):
            valor = relatorios_mod._formata_valor(coluna, linha.get(coluna["chave"]))  # noqa: SLF001
            ttk.Label(quadro, text=f"{coluna['rotulo']}:", style="Card.Suave.TLabel").grid(
                row=indice, column=0, sticky="nw", padx=(0, 10), pady=2)
            ttk.Label(quadro, text=valor or "—", style="Card.TLabel", wraplength=380,
                      justify="left").grid(row=indice, column=1, sticky="w", pady=2)
        self.barra_botoes((("Fechar", None, "Primario.TButton"),))


class RelatoriosTela(Tela):
    """Relatórios com parâmetros dinâmicos, exportação e impressão."""

    titulo = "Relatórios"
    descricao = ("Vendas, financeiro, estoque e cadastros — escolha o relatório, ajuste o período e "
                 "exporte para Excel, PDF ou CSV (ou imprima direto).")

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self._chave = ""
        self._relatorio: dict | None = None
        self._campos: dict[str, dict] = {}
        self._tree_itens: dict[str, str] = {}
        self._externos: dict = {}
        self._montar_barra(
            [
                ("▶ Gerar", self.gerar, "Primario.TButton", "Ctrl+Enter"),
                ("⭳ Exportar", self.exportar, "TButton", "Ctrl+E"),
                ("🖨 Imprimir", self.imprimir_lista, "TButton", "Ctrl+P"),
                ("⟳ Atualizar", self.carregar, "TButton", "Ctrl+R"),
            ],
            lado_direito=[("🔎 Detalhes", self.ver_detalhes, "TButton"), ("ℹ Ajuda", self.mostrar_ajuda, "TButton")],
        )
        self._montar_interface()
        self._registrar_teclas()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.corpo.columnconfigure(0, weight=0)
        self.corpo.columnconfigure(1, weight=1)
        self.corpo.rowconfigure(0, weight=1)

        # --- coluna esquerda: lista de relatórios --------------------------------
        esquerda = ttk.Frame(self.corpo, style="Card.TFrame", padding=10)
        esquerda.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        esquerda.rowconfigure(2, weight=1)
        esquerda.columnconfigure(0, weight=1)
        ttk.Label(esquerda, text="Relatórios disponíveis", style="Card.TLabel",
                  font=FONTE_SUBTITULO).grid(row=0, column=0, sticky="w")
        busca = ttk.Frame(esquerda, style="Card.TFrame")
        busca.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        busca.columnconfigure(0, weight=1)
        self.entrada_busca = ttk.Entry(busca)
        self.entrada_busca.grid(row=0, column=0, sticky="ew")
        self.entrada_busca.insert(0, "Filtrar relatório...")
        self.entrada_busca.configure(foreground=self.tema.cor("fg_fraco"))
        self.entrada_busca.bind("<FocusIn>", self._busca_focus_in)
        self.entrada_busca.bind("<FocusOut>", self._busca_focus_out)
        self.entrada_busca.bind("<KeyRelease>", lambda _e: self._montar_lista())
        self.entrada_busca.bind("<Return>", lambda _e: self._selecionar_primeiro_filtro())

        self.lista = ttk.Treeview(esquerda, show="tree", selectmode="browse", height=20)
        self.lista.grid(row=2, column=0, sticky="nsew")
        barra_lista = ttk.Scrollbar(esquerda, orient="vertical", command=self.lista.yview)
        barra_lista.grid(row=2, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=barra_lista.set)
        self.lista.bind("<<TreeviewSelect>>", self._ao_selecionar_relatorio)

        self.rotulo_descricao = ttk.Label(esquerda, text="", style="Card.Suave.TLabel", wraplength=280,
                                          justify="left")
        self.rotulo_descricao.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # --- coluna direita: parâmetros + resultado -------------------------------
        direita = ttk.Frame(self.corpo, style="TFrame")
        direita.grid(row=0, column=1, sticky="nsew")
        direita.columnconfigure(0, weight=1)
        direita.rowconfigure(2, weight=1)

        self.quadro_parametros = ttk.Frame(direita, style="Card.TFrame", padding=10)
        self.quadro_parametros.grid(row=0, column=0, sticky="ew")
        self.quadro_parametros.columnconfigure(0, weight=1)
        self.quadro_parametros.columnconfigure(1, weight=1)

        self.quadro_resumo = ttk.Frame(direita, style="TFrame")
        self.quadro_resumo.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        self.quadro_resumo.columnconfigure(0, weight=1)

        self.quadro_resultado = ttk.Frame(direita, style="TFrame")
        self.quadro_resultado.grid(row=2, column=0, sticky="nsew")
        self.quadro_resultado.columnconfigure(0, weight=1)
        self.quadro_resultado.rowconfigure(0, weight=1)
        self.tabela: Tabela | None = None
        self._montar_vazio()

    def _montar_vazio(self):
        for filho in self.quadro_resultado.winfo_children():
            filho.destroy()
        self.tabela = None
        ttk.Label(self.quadro_resultado,
                  text="Escolha um relatório na lista ao lado.\n\n"
                       "O resultado aparece aqui, com busca, ordenação e exportação.",
                  style="Suave.TLabel", justify="center", font=FONTE_SUBTITULO).grid(row=0, column=0, sticky="nsew")

    def _registrar_teclas(self):
        for sequencia, comando in (
            ("<Control-Return>", self.gerar),
            ("<Control-e>", self.exportar),
            ("<Control-E>", self.exportar),
            ("<Control-p>", self.imprimir_lista),
            ("<Control-P>", self.imprimir_lista),
        ):
            self.bind(sequencia, lambda _e, c=comando: (c(), "break")[1])

    # ------------------------------------------------------------------ busca da lista
    def _busca_focus_in(self, _evento=None):
        if self.entrada_busca.get() == "Filtrar relatório...":
            self.entrada_busca.delete(0, "end")
            self.entrada_busca.configure(foreground=self.tema.cor("fg"))

    def _busca_focus_out(self, _evento=None):
        if not self.entrada_busca.get().strip():
            self.entrada_busca.insert(0, "Filtrar relatório...")
            self.entrada_busca.configure(foreground=self.tema.cor("fg_fraco"))

    def focar_busca(self):
        self.entrada_busca.focus_set()
        self._busca_focus_in()

    def _texto_busca(self) -> str:
        texto = self.entrada_busca.get().strip()
        return "" if texto == "Filtrar relatório..." else texto

    def _selecionar_primeiro_filtro(self):
        filhos = [f for grupo in self.lista.get_children() for f in self.lista.get_children(grupo)]
        if filhos:
            self.lista.selection_set(filhos[0])
            self.lista.focus(filhos[0])
            self._ao_selecionar_relatorio()

    # ------------------------------------------------------------------ lista de relatórios
    def _montar_lista(self):
        filtro = self._texto_busca().lower()
        anterior = self.lista.selection()
        chave_anterior = self._chave
        self.lista.delete(*self.lista.get_children())
        self._tree_itens = {}
        for grupo, itens in relatorios_mod.meta().items():
            visiveis = [i for i in itens if not filtro or filtro in i["titulo"].lower()]
            if not visiveis:
                continue
            pai = self.lista.insert("", "end", text=f"  {grupo}", open=True)
            for item in visiveis:
                filho = self.lista.insert(pai, "end", text=f"     {item['titulo']}", iid=item["chave"])
                self._tree_itens[item["chave"]] = filho
        if chave_anterior in self._tree_itens:
            self.lista.selection_set(self._tree_itens[chave_anterior])
        elif anterior:
            try:
                self.lista.selection_set(anterior)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ parâmetros
    def _limpar_campos(self):
        for filho in self.quadro_parametros.winfo_children():
            filho.destroy()
        self._campos = {}

    def _rotulo_campo(self, pai, texto: str, linha: int, coluna: int) -> ttk.Frame:
        quadro = ttk.Frame(pai, style="Card.TFrame")
        quadro.grid(row=linha, column=coluna, sticky="ew", padx=(0 if coluna == 0 else 8, 8 if coluna == 0 else 0),
                    pady=4)
        quadro.columnconfigure(0, weight=1)
        ttk.Label(quadro, text=texto, style="Card.Suave.TLabel", font=FONTE_PEQUENA).grid(row=0, column=0, sticky="w")
        return quadro

    def _montar_parametros(self, chave: str):
        """Cria os campos de filtro aceitos pelo relatório escolhido."""
        self._limpar_campos()
        aceitos = list(relatorios_mod.info(chave).get("parametros") or [])
        if not aceitos:
            ttk.Label(self.quadro_parametros, text="Este relatório não tem parâmetros — mostra a posição atual.",
                      style="Card.Suave.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
            return

        linha = 0
        if "data_inicial" in aceitos or "data_final" in aceitos:
            self._campo_periodo(linha)
            linha += 1

        coluna = 0
        for nome in aceitos:
            if nome in ("data_inicial", "data_final"):
                continue
            self._criar_campo(nome, linha, coluna)
            coluna += 1
            if coluna > 1:
                coluna = 0
                linha += 1
        self._aplicar_externos()

    def _campo_periodo(self, linha: int):
        quadro = self._rotulo_campo(self.quadro_parametros, "Período do relatório", linha, 0)
        quadro.grid(columnspan=2, sticky="ew", padx=(0, 0))
        interno = ttk.Frame(quadro, style="Card.TFrame")
        interno.grid(row=1, column=0, sticky="ew")
        interno.columnconfigure(1, weight=1)
        interno.columnconfigure(3, weight=1)
        ttk.Label(interno, text="De", style="Card.Suave.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.var_data_inicial = tk.StringVar(value="")
        self.entrada_inicial = ttk.Entry(interno, textvariable=self.var_data_inicial, width=12)
        self.entrada_inicial.grid(row=0, column=1, sticky="ew")
        ttk.Label(interno, text="Até", style="Card.Suave.TLabel").grid(row=0, column=2, sticky="w", padx=(8, 4))
        self.var_data_final = tk.StringVar(value="")
        self.entrada_final = ttk.Entry(interno, textvariable=self.var_data_final, width=12)
        self.entrada_final.grid(row=0, column=3, sticky="ew")

        rapidos = ttk.Frame(quadro, style="Card.TFrame")
        rapidos.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(rapidos, text="Períodos rápidos:", style="Card.Suave.TLabel").pack(side="left", padx=(0, 6))
        self.var_periodo = tk.StringVar(value=PERIODO_PADRAO)
        combo = ttk.Combobox(rapidos, textvariable=self.var_periodo, state="readonly", width=20,
                             values=[rotulo for rotulo, _ in PERIODOS])
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._periodo_mudou())
        for rotulo, valor in (("Hoje", "hoje"), ("7 dias", 7), ("30 dias", 30), ("Este mês", "mes_atual")):
            ttk.Button(rapidos, text=rotulo, width=9,
                       command=lambda v=valor: self._periodo_rapido(v)).pack(side="left", padx=(6, 0))
        self._combo_periodo = combo
        self._periodo_mudou()

    def _periodo_rapido(self, valor):
        for rotulo, candidato in PERIODOS:
            if candidato == valor:
                self.var_periodo.set(rotulo)
                break
        self._periodo_mudou()

    def _periodo_mudou(self):
        personalizado = self.var_periodo.get() == "Personalizado"
        estado = "normal" if personalizado else "readonly"
        self.entrada_inicial.configure(state="normal")
        self.entrada_final.configure(state="normal")
        if not personalizado:
            ini, fim = self._resolver_periodo(self.var_periodo.get())
            self.var_data_inicial.set(formatar_data(ini))
            self.var_data_final.set(formatar_data(fim))
        self.entrada_inicial.configure(state=estado)
        self.entrada_final.configure(state=estado)

    def _resolver_periodo(self, rotulo: str) -> tuple[str, str]:
        valor = dict(PERIODOS).get(rotulo, 30)
        referencia = hoje()
        if isinstance(valor, int):
            return intervalo_padrao(valor)
        if valor == "hoje":
            return referencia, referencia
        if valor == "ontem":
            ontem = somar_dias(referencia, -1)
            return ontem, ontem
        if valor == "mes_atual":
            return primeiro_dia_mes(referencia), referencia
        if valor == "mes_anterior":
            ultimo_anterior = somar_dias(primeiro_dia_mes(referencia), -1)
            return primeiro_dia_mes(ultimo_anterior), ultimo_anterior
        if valor == "ano_atual":
            return f"{referencia[:4]}-01-01", referencia
        # personalizado: usa o que estiver digitado
        ini = converter_data_br(self.var_data_inicial.get()) or intervalo_padrao(30)[0]
        fim = converter_data_br(self.var_data_final.get()) or referencia
        if ini > fim:
            ini, fim = fim, ini
        return ini, fim

    # --- campos individuais ------------------------------------------------------
    def _criar_campo(self, nome: str, linha: int, coluna: int):
        if nome == "cliente_id":
            self._campo_registro(nome, "Cliente", linha, coluna, self._escolher_cliente)
        elif nome == "produto_id":
            self._campo_registro(nome, "Produto", linha, coluna, self._escolher_produto)
        elif nome == "vendedor_id":
            valores = [(0, "(todos os vendedores)")] + [
                (int(u["id"]), str(u["nome"])) for u in usuarios_mod.vendedores(self.banco)
            ]
            self._campo_lista(nome, "Vendedor", valores, linha, coluna)
        elif nome == "categoria_id":
            valores = [(0, "(todas as categorias)")] + [
                (int(c["id"]), str(c["nome"])) for c in categorias_mod.listar(self.banco)
            ]
            self._campo_lista(nome, "Categoria", valores, linha, coluna)
        elif nome == "fornecedor_id":
            valores = [(0, "(todos os fornecedores)")] + [
                (int(f["id"]), str(f["nome"])) for f in fornecedores_mod.listar(self.banco)
            ]
            self._campo_lista(nome, "Fornecedor", valores, linha, coluna)
        elif nome == "forma":
            valores = [("", "(todas as formas)")] + [(f, f) for f in formas_pagamento.TODAS]
            self._campo_lista(nome, "Forma de pagamento", valores, linha, coluna)
        elif nome == "categoria":
            valores = [("", "(todas as categorias)")] + [(c, c) for c in CATEGORIAS_DESPESA]
            self._campo_lista(nome, "Categoria de despesa", valores, linha, coluna)
        elif nome == "status":
            self._campo_lista(nome, "Situação", OPCOES_STATUS_CONTA, linha, coluna)
        elif nome == "tipo":
            self._campo_lista(nome, "Tipo de movimento", OPCOES_TIPO_MOVIMENTO, linha, coluna)
        elif nome == "motivo":
            valores = [("", "(todos os motivos)")] + [(codigo, rotulo) for codigo, rotulo in estoque_mod.MOTIVOS.items()]
            self._campo_lista(nome, "Motivo", valores, linha, coluna)
        elif nome == "por":
            self._campo_lista(nome, "Ordenar ranking por", OPCOES_ORDEM, linha, coluna)
        elif nome == "limite":
            self._campo_numero(nome, "Quantos itens listar", linha, coluna, 5, 500, 20)
        elif nome == "dias":
            padrao = self.banco.config_pegar_int("alerta_validade_dias", 30)
            self._campo_numero(nome, "Vencendo em até (dias)", linha, coluna, 1, 365, padrao)
        elif nome in ("apenas_baixo", "incluir_inativos", "incluir_canceladas"):
            self._campo_marcar(nome, linha, coluna)
        else:
            self._campo_texto(nome, linha, coluna)

    def _campo_texto(self, nome: str, linha: int, coluna: int):
        rotulos = {"texto": "Busca livre (nome, código...)"}
        quadro = self._rotulo_campo(self.quadro_parametros, rotulos.get(nome, nome.replace("_", " ").capitalize()),
                                    linha, coluna)
        var = tk.StringVar(value="")
        entrada = ttk.Entry(quadro, textvariable=var)
        entrada.grid(row=1, column=0, sticky="ew")
        entrada.bind("<Return>", lambda _e: self.gerar())
        self._campos[nome] = {"tipo": "texto", "var": var, "widget": entrada}

    def _campo_lista(self, nome: str, rotulo: str, valores, linha: int, coluna: int, padrao=None):
        quadro = self._rotulo_campo(self.quadro_parametros, rotulo, linha, coluna)
        rotulos = [r for _v, r in valores]
        var = tk.StringVar(value=rotulos[0])
        combo = ttk.Combobox(quadro, textvariable=var, values=rotulos, state="readonly")
        combo.grid(row=1, column=0, sticky="ew")
        if padrao is not None:
            var.set(str(padrao))
        self._campos[nome] = {"tipo": "lista", "var": var, "widget": combo, "valores": list(valores)}

    def _campo_numero(self, nome: str, rotulo: str, linha: int, coluna: int, minimo: int, maximo: int, padrao: int):
        quadro = self._rotulo_campo(self.quadro_parametros, rotulo, linha, coluna)
        var = tk.StringVar(value=str(padrao))
        spin = ttk.Spinbox(quadro, textvariable=var, from_=minimo, to=maximo, width=10)
        spin.grid(row=1, column=0, sticky="w")
        self._campos[nome] = {"tipo": "numero", "var": var, "widget": spin, "min": minimo, "max": maximo}

    def _campo_marcar(self, nome: str, linha: int, coluna: int):
        rotulos = {
            "apenas_baixo": "Somente produtos abaixo do mínimo",
            "incluir_inativos": "Incluir registros inativos",
            "incluir_canceladas": "Incluir vendas canceladas",
        }
        quadro = self._rotulo_campo(self.quadro_parametros, rotulos.get(nome, nome), linha, coluna)
        var = tk.BooleanVar(value=False)
        marcar = ttk.Checkbutton(quadro, text=rotulos.get(nome, nome), variable=var,
                                 style="Card.TCheckbutton", command=self.gerar)
        marcar.grid(row=1, column=0, sticky="w")
        self._campos[nome] = {"tipo": "marcar", "var": var, "widget": marcar}

    def _campo_registro(self, nome: str, rotulo: str, linha: int, coluna: int, comando):
        quadro = self._rotulo_campo(self.quadro_parametros, rotulo, linha, coluna)
        var = tk.StringVar(value="")
        linha_interna = ttk.Frame(quadro, style="Card.TFrame")
        linha_interna.grid(row=1, column=0, sticky="ew")
        linha_interna.columnconfigure(0, weight=1)
        entrada = ttk.Entry(linha_interna, textvariable=var, state="readonly")
        entrada.grid(row=0, column=0, sticky="ew")
        ttk.Button(linha_interna, text="Escolher...", width=11, command=comando).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(linha_interna, text="Limpar", width=8,
                   command=lambda: self._limpar_registro(nome)).grid(row=0, column=2, padx=(6, 0))
        self._campos[nome] = {"tipo": "registro", "var": var, "widget": entrada, "id": None}

    def _limpar_registro(self, nome: str):
        campo = self._campos.get(nome)
        if campo:
            campo["id"] = None
            campo["var"].set("")
            self.gerar()

    def _escolher_cliente(self):
        from .clientes_tela import selecionar_cliente

        cliente = selecionar_cliente(self.ctx, "Filtrar relatório por cliente", incluir_inativos=True)
        if cliente:
            campo = self._campos.get("cliente_id")
            if campo:
                campo["id"] = int(cliente["id"])
                campo["var"].set(str(cliente["nome"]))
            self.gerar()

    def _escolher_produto(self):
        from .produtos_tela import selecionar_produto

        produto = selecionar_produto(self.ctx, "Filtrar relatório por produto")
        if produto:
            campo = self._campos.get("produto_id")
            if campo:
                campo["id"] = int(produto["id"])
                campo["var"].set(f"{produto['codigo']} — {produto['nome']}")
            self.gerar()

    def _aplicar_externos(self):
        """Aplica parâmetros recebidos de outra tela (``ctx.navegar('relatorios', {...})``)."""
        externos = self._externos or {}
        if not externos:
            return
        tem_periodo = bool(getattr(self, "var_periodo", None)) and self.entrada_inicial.winfo_exists()
        if tem_periodo and (externos.get("data_inicial") or externos.get("data_final")):
            self.var_periodo.set("Personalizado")
            self._periodo_mudou()
            self.entrada_inicial.configure(state="normal")
            self.entrada_final.configure(state="normal")
            if externos.get("data_inicial"):
                self.var_data_inicial.set(formatar_data(str(externos["data_inicial"])[:10]))
            if externos.get("data_final"):
                self.var_data_final.set(formatar_data(str(externos["data_final"])[:10]))
        for nome, campo in self._campos.items():
            if nome not in externos:
                continue
            valor = externos[nome]
            if campo["tipo"] == "registro":
                campo["id"] = int(valor) if valor else None
                campo["var"].set(externos.get(f"{nome}_texto") or (str(valor) if valor else ""))
            elif campo["tipo"] == "lista":
                alvo = "" if valor in (None, "") else str(valor)
                for candidato, rotulo in campo["valores"]:
                    if str(candidato) == alvo:
                        campo["var"].set(rotulo)
                        break
            elif campo["tipo"] == "marcar":
                campo["var"].set(bool(valor))
            else:
                campo["var"].set(str(valor))
        self._externos = {}

    def parametros(self) -> dict:
        """Monta o dicionário de parâmetros do relatório a partir dos campos visíveis."""
        parametros: dict = {}
        aceitos = list(relatorios_mod.info(self._chave).get("parametros") or []) if self._chave else []
        if "data_inicial" in aceitos or "data_final" in aceitos:
            ini, fim = self._resolver_periodo(self.var_periodo.get())
            parametros["data_inicial"] = ini
            parametros["data_final"] = fim
        for nome, campo in self._campos.items():
            if nome not in aceitos:
                continue
            tipo = campo["tipo"]
            if tipo == "marcar":
                parametros[nome] = bool(campo["var"].get())
            elif tipo == "numero":
                try:
                    valor = int(float(campo["var"].get() or 0))
                except ValueError:
                    valor = int(campo.get("min") or 0)
                parametros[nome] = max(int(campo.get("min") or 0), min(valor, int(campo.get("max") or valor)))
            elif tipo == "registro":
                parametros[nome] = campo.get("id") or None
            elif tipo == "lista":
                rotulo = campo["var"].get()
                valor = ""
                for candidato, texto in campo["valores"]:
                    if texto == rotulo:
                        valor = candidato
                        break
                parametros[nome] = valor if valor not in (None, "") else None
            else:
                parametros[nome] = campo["var"].get().strip()
        return {chave: valor for chave, valor in parametros.items() if valor not in (None, "", False)}

    # ------------------------------------------------------------------ geração
    def carregar(self):
        if not self._tree_itens:
            self._montar_lista()
        if not self._chave:
            chaves = list(relatorios_mod.disponiveis())
            self._chave = chaves[0] if chaves else ""
        self._montar_lista()
        if self._chave in self._tree_itens:
            self.lista.selection_set(self._tree_itens[self._chave])
            self.lista.see(self._tree_itens[self._chave])
        self._montar_parametros(self._chave) if self._chave else None
        self.gerar(silencioso=True)

    def _ao_selecionar_relatorio(self, _evento=None):
        selecao = self.lista.selection()
        if not selecao:
            return
        chave = selecao[0]
        if chave not in relatorios_mod.RELATORIOS:
            return  # clicou no título de um grupo
        if chave == self._chave and self._relatorio:
            return
        self._chave = chave
        self._relatorio = None
        self._montar_parametros(chave)
        self.gerar(silencioso=True)

    def gerar(self, silencioso: bool = False):
        """Gera (ou regenera) o relatório escolhido e mostra o resultado."""
        if not self._chave:
            if not silencioso:
                dialogs.alerta(self, self.tema, "Escolha um relatório na lista ao lado.")
            return None
        try:
            parametros = self.parametros()
            relatorio = relatorios_mod.gerar(self.banco, self._chave, parametros)
        except relatorios_mod.ErroRelatorio as exc:
            dialogs.erro(self, self.tema, str(exc), "Relatório")
            return None
        except Exception as exc:  # erro de dados/consulta: mostra sem derrubar a tela
            self.ctx.avisar_erro(exc, f"Erro ao gerar o relatório '{relatorios_mod.info(self._chave)['titulo']}'.")
            return None
        self._relatorio = relatorio
        self._mostrar_resultado(relatorio)
        self._descricao_relatorio()
        if not silencioso:
            self.status(f"{relatorio['titulo']}: {len(relatorio['linhas'])} registro(s) gerado(s).")
        return relatorio

    def _descricao_relatorio(self):
        if not self._chave or self._chave not in relatorios_mod.RELATORIOS:
            self.rotulo_descricao.configure(text="")
            return
        info = relatorios_mod.info(self._chave)
        parametros = ", ".join(info.get("parametros") or ()) or "nenhum"
        self.rotulo_descricao.configure(
            text=f"{info['titulo']}\nGrupo: {info['grupo']}\nParâmetros: {parametros}\n\n"
                 "Dica: duplo clique numa linha mostra o registro completo."
        )

    def _colunas_tabela(self, relatorio: dict) -> list[dict]:
        colunas = []
        for coluna in relatorio.get("colunas") or []:
            colunas.append({
                "chave": coluna["chave"],
                "rotulo": coluna.get("rotulo", coluna["chave"]),
                "tipo": coluna.get("tipo", "texto"),
                "largura": max(64, int(coluna.get("largura") or 12) * 8 + 14),
                "alinhamento": coluna.get("alinhamento", ""),
            })
        return colunas

    def _mostrar_resultado(self, relatorio: dict):
        for filho in self.quadro_resultado.winfo_children():
            filho.destroy()
        self.tabela = None

        # --- cartões de totais + resumo ------------------------------------------
        for filho in self.quadro_resumo.winfo_children():
            filho.destroy()
        cartoes = ttk.Frame(self.quadro_resumo, style="TFrame")
        cartoes.grid(row=0, column=0, sticky="ew")
        cartoes.columnconfigure(0, weight=1)
        totais = {k: v for k, v in (relatorio.get("totais") or {}).items() if v not in (None, "", 0)}
        pares = [("Registros", str(len(relatorio.get("linhas") or [])), "info")]
        for indice, (chave, valor) in enumerate(list(totais.items())[:3]):
            cor = "sucesso" if chave in ("lucro", "receita", "receita_liquida", "resultado") else (
                "perigo" if chave in ("vencido", "a_pagar", "despesas", "prejuizo") else "neutro")
            pares.append((_rotulo_total(chave), _formatar_total(chave, valor), cor))
            cartoes.columnconfigure(indice + 1, weight=1)
        for indice, (titulo, valor, cor) in enumerate(pares):
            detalhe = relatorio.get("periodo") or ""
            cartao = Cartao(cartoes, self.tema, titulo, valor, detalhe, cor=cor, largura_minima=170)
            cartao.grid(row=0, column=indice, sticky="ew", padx=(0, 8))
        if not totais:
            cartoes.columnconfigure(1, weight=1)

        resumo = list(relatorio.get("resumo") or [])
        if resumo:
            ttk.Label(self.quadro_resumo, text="  •  ".join(resumo), style="Suave.TLabel", wraplength=1000,
                      justify="left").grid(row=1, column=0, sticky="w", pady=(2, 0))
        if relatorio.get("filtros"):
            ttk.Label(self.quadro_resumo, text=f"Filtros aplicados: {relatorio['filtros']}",
                      style="Suave.TLabel").grid(row=2, column=0, sticky="w")

        # --- grade ----------------------------------------------------------------
        linhas = [dict(l) for l in (relatorio.get("linhas") or [])]
        for linha in linhas:
            tag = _tag_da_linha(linha)
            if tag:
                linha["_tag"] = tag
        colunas = self._colunas_tabela(relatorio)
        if not colunas:
            ttk.Label(self.quadro_resultado, text="Este relatório não devolveu colunas.",
                      style="Suave.TLabel").grid(row=0, column=0, sticky="nsew")
            return
        self.tabela = Tabela(
            self.quadro_resultado, self.tema, colunas,
            ao_duplo_clique=self.ver_detalhes,
            tamanho_pagina=500,
            altura=16,
            busca_placeholder="Filtrar resultado... (Ctrl+B)",
        )
        self.tabela.grid(row=0, column=0, sticky="nsew")
        resumo_grade = f"{len(linhas)} registro(s)"
        if relatorio.get("periodo"):
            resumo_grade += f" • {relatorio['periodo']}"
        self.tabela.carregar(linhas, resumo=resumo_grade)

    # ------------------------------------------------------------------ detalhes / exportação
    def ver_detalhes(self, linha: dict | None = None):
        if not self._relatorio:
            dialogs.alerta(self, self.tema, "Gere um relatório primeiro.")
            return
        linha = linha if isinstance(linha, dict) else (self.tabela.linha_selecionada() if self.tabela else None)
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione uma linha na grade para ver os detalhes.")
            return
        DialogoDetalhesLinha(self.ctx.janela, self.tema, f"{self._relatorio['titulo']} — detalhes",
                             list(self._relatorio.get("colunas") or []), linha).abrir()

    def _dados_exportacao(self, arquivo) -> dict:
        relatorio = self._relatorio or {}
        return {
            "chave": relatorio.get("chave", self._chave),
            "titulo": relatorio.get("titulo", "Relatório"),
            "periodo": relatorio.get("periodo", ""),
            "filtros": relatorio.get("filtros", ""),
            "colunas": relatorio.get("colunas") or [],
            "linhas": relatorio.get("linhas") or [],
            "totais": relatorio.get("totais") or {},
            "resumo": list(relatorio.get("resumo") or []),
            "arquivo": arquivo,
        }

    def exportar(self):
        """Ctrl+E — pergunta o formato/destino e grava o arquivo."""
        return self._exportar_relatorio()

    def _exportar_relatorio(self, formato: str = ""):
        if not self._relatorio:
            dialogs.alerta(self, self.tema, "Gere um relatório antes de exportar.")
            return None
        if not self._relatorio.get("linhas"):
            dialogs.alerta(self, self.tema, "O relatório não tem registros para exportar com os filtros atuais.")
            return None
        titulo = self._relatorio["titulo"]
        if formato:
            pasta = filedialog.askdirectory(parent=self, title="Escolha a pasta de destino",
                                            initialdir=str(Path.home()))
            if not pasta:
                return None
            destino = str(exportacao_mod.caminho_sugerido(titulo, formato, pasta=pasta))
            abrir = True
        else:
            escolha = DialogoExportar(self, self.tema, titulo, len(self._relatorio["linhas"]),
                                      self._relatorio.get("periodo", "")).abrir()
            if not escolha:
                return None
            formato = escolha["formato"]
            destino = escolha["caminho"]
            abrir = bool(escolha.get("abrir"))
            if not destino:
                pasta = filedialog.askdirectory(parent=self, title="Escolha a pasta de destino",
                                                initialdir=str(Path.home()))
                if not pasta:
                    return None
                destino = str(exportacao_mod.caminho_sugerido(titulo, formato, pasta=pasta))
        try:
            caminho = exportacao_mod.exportar(self._dados_exportacao(destino), destino, formato)
        except exportacao_mod.ErroExportacao as exc:
            dialogs.erro(self, self.tema, str(exc), "Falha na exportação")
            return None
        except PermissionError:
            dialogs.erro(self, self.tema,
                         "Não foi possível gravar o arquivo — ele pode estar aberto em outro programa.\n"
                         "Feche o arquivo e tente novamente.", "Falha na exportação")
            return None
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao exportar o relatório.")
            return None
        dialogs.sucesso(self, self.tema, f"Arquivo gerado com sucesso:\n{caminho}", "Exportação concluída")
        self.status(f"Exportado: {caminho}")
        if abrir:
            abrir_pasta_do_arquivo(caminho)
        return caminho

    def exportar_rapido(self, formato: str):
        """Atalho usado por outros pontos do sistema (ex.: painel)."""
        return self._exportar_relatorio(formato)

    def imprimir_lista(self):
        """Ctrl+P — gera o PDF do relatório e oferece impressão."""
        if not self._relatorio:
            dialogs.alerta(self, self.tema, "Gere um relatório antes de imprimir.")
            return None
        if not self._relatorio.get("linhas"):
            dialogs.alerta(self, self.tema, "O relatório não tem registros para imprimir com os filtros atuais.")
            return None
        titulo = self._relatorio["titulo"]
        try:
            caminho = exportacao_mod.exportar(
                self._dados_exportacao(exportacao_mod.caminho_sugerido(titulo, "pdf")),
                exportacao_mod.caminho_sugerido(titulo, "pdf"), "pdf",
            )
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao gerar o PDF do relatório.")
            return None
        imprimir_documento(self, self.tema, caminho, titulo)
        return caminho

    # ------------------------------------------------------------------ ajuda / tema
    def mostrar_ajuda(self):
        total = len(relatorios_mod.disponiveis())
        dialogs.mensagem(
            self.ctx.janela, self.tema, "Como usar os relatórios",
            f"Este módulo tem {total} relatórios prontos, divididos em Vendas, Financeiro, Estoque e Cadastros.\n\n"
            "1. Clique no relatório desejado na lista da esquerda — o resultado é gerado na hora.\n"
            "2. Ajuste o período e os filtros no painel acima da grade e clique em “Gerar” (Ctrl+Enter).\n"
            "3. Use “Exportar” (Ctrl+E) para salvar em Excel, PDF ou CSV, ou “Imprimir” (Ctrl+P) para mandar\n"
            "    direto para a impressora padrão.\n"
            "4. Duplo clique numa linha mostra todos os campos daquele registro.\n\n"
            "Atalhos: Ctrl+B filtra o resultado • Ctrl+R atualiza • Ctrl+E exporta • Ctrl+P imprime.",
            "info", ("OK",),
        )

    def ao_tecla(self, tecla: str) -> bool:
        if tecla == "<F10>":
            self.gerar()
            return True
        return False

    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        self._externos = {k: v for k, v in parametros.items() if k not in ("relatorio", "chave", "id")}
        chave = str(parametros.get("relatorio") or parametros.get("chave") or parametros.get("id") or "")
        if chave in relatorios_mod.RELATORIOS:
            self._chave = chave
        self.carregar()

    def atualizar_tema(self):
        if self.tabela is not None:
            self.tabela.atualizar_tema()
        if self._relatorio:
            self._mostrar_resultado(self._relatorio)
