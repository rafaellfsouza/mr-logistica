"""
Tela de etiquetas com código de barras.

Fecha o ciclo do leitor de código de barras: quando um produto é cadastrado sem
código, aqui é possível **gerar um EAN-13 interno** (faixa 200–299, reservada para
uso do próprio estabelecimento) e **imprimir as etiquetas** em folha adesiva
(Pimaco) ou em rolo térmico.

Fluxo de uso:
  1. filtre os produtos (busca, categoria ou "somente sem código de barras");
  2. selecione e clique em "＋ Adicionar" — eles entram na fila de etiquetas;
  3. ajuste a quantidade de cada item (duplo clique na fila), o modelo de folha e
     o que aparece na etiqueta (preço, código interno, marca);
  4. "Pré-visualizar" mostra uma etiqueta de exemplo, "Gerar PDF" cria a folha e
     "Imprimir" manda direto para a impressora padrão.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import categorias as categorias_mod
from ... import etiquetas as etiquetas_mod
from ... import produtos as produtos_mod
from .. import dialogs
from ..tema import FONTE_SUBTITULO
from ..widgets import Tabela
from . import Tela, imprimir_documento

#: Colunas da grade de produtos (esquerda).
COLUNAS_PRODUTOS = [
    {"chave": "codigo", "rotulo": "Código", "largura": 90},
    {"chave": "codigo_barras", "rotulo": "Código de barras", "largura": 130},
    {"chave": "nome", "rotulo": "Produto", "largura": 260},
    {"chave": "categoria_nome", "rotulo": "Categoria", "largura": 130},
    {"chave": "marca", "rotulo": "Marca", "largura": 110},
    {"chave": "preco_venda", "rotulo": "Preço venda", "largura": 100, "tipo": "dinheiro"},
    {"chave": "unidade_base", "rotulo": "Un", "largura": 50, "alinhamento": "centro"},
    {"chave": "estoque_atual", "rotulo": "Estoque", "largura": 80, "tipo": "quantidade"},
]

#: Colunas da fila de etiquetas (direita).
COLUNAS_FILA = [
    {"chave": "codigo", "rotulo": "Código", "largura": 80},
    {"chave": "nome", "rotulo": "Produto", "largura": 200},
    {"chave": "codigo_barras", "rotulo": "Código de barras", "largura": 130},
    {"chave": "preco_venda", "rotulo": "Preço", "largura": 90, "tipo": "dinheiro"},
    {"chave": "quantidade", "rotulo": "Etiquetas", "largura": 80, "tipo": "inteiro", "alinhamento": "centro"},
]

#: Máximo de produtos adicionados de uma vez (evita travar a interface).
LIMITE_ADICAO = 500


class EtiquetasTela(Tela):
    """Geração e impressão de etiquetas de código de barras."""

    titulo = "Etiquetas de código de barras"
    descricao = ("Gere códigos internos para produtos sem código de barras e imprima etiquetas em folha "
                 "adesiva ou rolo térmico — com preço, código e marca.")

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self._fila: list[dict] = []
        self._categoria_id: int | None = None
        self._montar_barra(
            [
                ("🖨 Imprimir etiquetas", self.imprimir, "Primario.TButton", "Ctrl+P"),
                ("📄 Gerar PDF", self.gerar_pdf, "TButton"),
                ("👁 Pré-visualizar", self.previsualizar, "TButton"),
                ("🔢 Gerar código de barras", self.gerar_codigo_selecionados, "TButton"),
                ("🔢 Gerar p/ todos sem código", self.gerar_codigo_todos, "TButton"),
                ("⟳ Atualizar", self.carregar, "TButton", "Ctrl+R"),
            ],
            lado_direito=[("🗑 Remover da fila", self.remover_selecionados, "TButton"),
                          ("✖ Limpar fila", self.limpar_fila, "TButton")],
        )
        self._montar_interface()
        self._registrar_teclas()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.corpo.columnconfigure(0, weight=3)
        self.corpo.columnconfigure(1, weight=2)
        self.corpo.rowconfigure(0, weight=1)

        # --- esquerda: escolha de produtos ---------------------------------------
        esquerda = ttk.Frame(self.corpo, style="Card.TFrame", padding=10)
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        esquerda.columnconfigure(0, weight=1)
        esquerda.rowconfigure(2, weight=1)
        ttk.Label(esquerda, text="1. Escolha os produtos", style="Card.TLabel",
                  font=FONTE_SUBTITULO).grid(row=0, column=0, sticky="w")

        filtros = ttk.Frame(esquerda, style="Card.TFrame")
        filtros.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        filtros.columnconfigure(1, weight=1)
        ttk.Label(filtros, text="Categoria:", style="Card.Suave.TLabel").grid(row=0, column=0, sticky="w",
                                                                              padx=(0, 6))
        self.var_categoria = tk.StringVar(value="(todas)")
        self.combo_categoria = ttk.Combobox(filtros, textvariable=self.var_categoria, state="readonly", width=22)
        self.combo_categoria.grid(row=0, column=1, sticky="w")
        self.combo_categoria.bind("<<ComboboxSelected>>", lambda _e: self._categoria_mudou())
        self.var_sem_codigo = tk.BooleanVar(value=False)
        ttk.Checkbutton(filtros, text="Somente produtos SEM código de barras", variable=self.var_sem_codigo,
                        style="Card.TCheckbutton", command=self.carregar).grid(row=0, column=2, sticky="w",
                                                                               padx=(12, 0))
        self.var_incluir_inativos = tk.BooleanVar(value=False)
        ttk.Checkbutton(filtros, text="Incluir inativos", variable=self.var_incluir_inativos,
                        style="Card.TCheckbutton", command=self.carregar).grid(row=0, column=3, sticky="w",
                                                                               padx=(12, 0))
        botoes_fila = ttk.Frame(esquerda, style="Card.TFrame")
        botoes_fila.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(botoes_fila, text="＋ Adicionar selecionados", style="Primario.TButton",
                   command=self.adicionar_selecionados).pack(side="left")
        ttk.Button(botoes_fila, text="＋ Adicionar todos os filtrados",
                   command=self.adicionar_todos).pack(side="left", padx=(6, 0))
        ttk.Button(botoes_fila, text="Ir para o cadastro do produto",
                   command=self.abrir_produto).pack(side="right")
        self.rotulo_pendentes = ttk.Label(botoes_fila, text="", style="Card.Suave.TLabel")
        self.rotulo_pendentes.pack(side="left", padx=(12, 0))

        self.tabela_produtos = Tabela(
            esquerda, self.tema, COLUNAS_PRODUTOS,
            ao_duplo_clique=lambda linha: self.adicionar([linha]),
            selecao="extended",
            altura=18,
            busca_placeholder="Buscar produto... (Ctrl+B)",
        )
        self.tabela_produtos.grid(row=2, column=0, sticky="nsew")

        # --- direita: fila + opções ----------------------------------------------
        direita = ttk.Frame(self.corpo, style="Card.TFrame", padding=10)
        direita.grid(row=0, column=1, sticky="nsew")
        direita.columnconfigure(0, weight=1)
        direita.rowconfigure(2, weight=1)
        ttk.Label(direita, text="2. Fila de etiquetas", style="Card.TLabel",
                  font=FONTE_SUBTITULO).grid(row=0, column=0, sticky="w")

        opcoes = ttk.Frame(direita, style="Card.TFrame")
        opcoes.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        opcoes.columnconfigure(1, weight=1)
        ttk.Label(opcoes, text="Modelo da folha:", style="Card.Suave.TLabel").grid(row=0, column=0, sticky="w",
                                                                                  padx=(0, 6))
        self.var_modelo = tk.StringVar(value=etiquetas_mod.MODELO_PADRAO)
        self.combo_modelo = ttk.Combobox(opcoes, textvariable=self.var_modelo, state="readonly",
                                         values=etiquetas_mod.modelos())
        self.combo_modelo.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        self.combo_modelo.bind("<<ComboboxSelected>>", lambda _e: self._modelo_mudou())

        ttk.Label(opcoes, text="Etiquetas por produto:", style="Card.Suave.TLabel").grid(row=1, column=0, sticky="w",
                                                                                        padx=(0, 6), pady=(4, 0))
        self.var_quantidade = tk.StringVar(value="1")
        self.spin_quantidade = ttk.Spinbox(opcoes, textvariable=self.var_quantidade, from_=1, to=999, width=8)
        self.spin_quantidade.grid(row=1, column=1, sticky="w", pady=(4, 0))

        self.var_preco = tk.BooleanVar(value=True)
        self.var_codigo_interno = tk.BooleanVar(value=True)
        self.var_marca = tk.BooleanVar(value=False)
        conteudo = ttk.Frame(opcoes, style="Card.TFrame")
        conteudo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(conteudo, text="Preço", variable=self.var_preco,
                        style="Card.TCheckbutton").pack(side="left")
        ttk.Checkbutton(conteudo, text="Código interno", variable=self.var_codigo_interno,
                        style="Card.TCheckbutton").pack(side="left", padx=(10, 0))
        ttk.Checkbutton(conteudo, text="Marca", variable=self.var_marca,
                        style="Card.TCheckbutton").pack(side="left", padx=(10, 0))

        self.tabela_fila = Tabela(
            direita, self.tema, COLUNAS_FILA,
            ao_duplo_clique=self.definir_quantidade,
            selecao="extended",
            mostrar_busca=False,
            altura=14,
        )
        self.tabela_fila.grid(row=2, column=0, sticky="nsew")

        rodape = ttk.Frame(direita, style="Card.TFrame")
        rodape.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(rodape, text="Quantidade...", command=self.definir_quantidade).pack(side="left")
        self.rotulo_fila = ttk.Label(rodape, text="Nenhuma etiqueta na fila.", style="Card.Suave.TLabel")
        self.rotulo_fila.pack(side="left", padx=(12, 0))

        self._recarregar_categorias()
        self._atualizar_fila()

    def _registrar_teclas(self):
        for sequencia, comando in (
            ("<Control-p>", self.imprimir),
            ("<Control-P>", self.imprimir),
            ("<Return>", self.adicionar_selecionados),
        ):
            self.bind(sequencia, lambda _e, c=comando: (c(), "break")[1])

    # ------------------------------------------------------------------ filtros
    def _recarregar_categorias(self):
        categorias = categorias_mod.listar(self.banco)
        self._categorias = [(0, "(todas)")] + [(int(c["id"]), str(c["nome"])) for c in categorias]
        self.combo_categoria.configure(values=[rotulo for _id, rotulo in self._categorias])
        atual = self.var_categoria.get()
        if atual not in [rotulo for _id, rotulo in self._categorias]:
            self.var_categoria.set("(todas)")

    def _categoria_mudou(self):
        rotulo = self.var_categoria.get()
        self._categoria_id = None
        for identificador, texto in self._categorias:
            if texto == rotulo:
                self._categoria_id = identificador or None
                break
        self.carregar()

    def _produtos_filtrados(self) -> list:
        return produtos_mod.listar(
            self.banco,
            categoria_id=self._categoria_id,
            incluir_inativos=bool(self.var_incluir_inativos.get()),
            apenas_sem_barras=bool(self.var_sem_codigo.get()),
            limite=2000,
        )

    # ------------------------------------------------------------------ carga
    def carregar(self):
        self._recarregar_categorias()
        dados = [dict(p) for p in self._produtos_filtrados()]
        for linha in dados:
            linha["codigo_barras"] = linha.get("codigo_barras") or "—"
            if not linha.get("codigo_barras") or linha["codigo_barras"] == "—":
                linha["_tag"] = "alerta"
        self.tabela_produtos.carregar(dados)
        sem_codigo = len(etiquetas_mod.produtos_sem_codigo(self.banco))
        self.rotulo_pendentes.configure(
            text=f"{sem_codigo} produto(s) sem código de barras" if sem_codigo
                 else "Todos os produtos ativos já têm código")
        # mantém a fila sincronizada com o banco (preços e códigos podem ter mudado)
        self._sincronizar_fila()
        self._atualizar_fila()
        self.status(f"{len(dados)} produto(s) listados • {len(self._fila)} na fila de etiquetas.")

    def _sincronizar_fila(self):
        atualizada = []
        for item in self._fila:
            produto = produtos_mod.pegar_simples(self.banco, item["produto_id"])
            if not produto:
                continue
            item["codigo"] = produto["codigo"]
            item["nome"] = produto["nome"]
            item["codigo_barras"] = produto["codigo_barras"] or "—"
            item["preco_venda"] = int(produto["preco_venda"] or 0)
            atualizada.append(item)
        self._fila = atualizada

    def _atualizar_fila(self):
        total = sum(int(i["quantidade"]) for i in self._fila)
        self.tabela_fila.carregar(
            [dict(i) for i in self._fila],
            resumo=f"{len(self._fila)} produto(s) • {total} etiqueta(s)",
        )
        self.rotulo_fila.configure(
            text=f"{total} etiqueta(s) para imprimir" if total else "Nenhuma etiqueta na fila.")

    def focar_busca(self):
        self.tabela_produtos.focar_busca()

    # ------------------------------------------------------------------ fila
    def _quantidade_padrao(self) -> int:
        try:
            quantidade = int(float(self.var_quantidade.get() or 1))
        except ValueError:
            quantidade = 1
        return max(1, min(quantidade, 999))

    def adicionar(self, linhas) -> int:
        """Coloca produtos na fila (repetidos somam quantidade). Devolve quantos entraram."""
        quantidade = self._quantidade_padrao()
        adicionados = 0
        for linha in linhas or []:
            if not linha:
                continue
            produto_id = int(linha["id"])
            existente = next((i for i in self._fila if i["produto_id"] == produto_id), None)
            if existente:
                existente["quantidade"] = int(existente["quantidade"]) + quantidade
                adicionados += 1
                continue
            if len(self._fila) >= LIMITE_ADICAO:
                dialogs.alerta(self, self.tema, f"Limite de {LIMITE_ADICAO} produtos na fila atingido.\n"
                                                "Imprima as etiquetas atuais e limpe a fila para continuar.")
                break
            self._fila.append({
                "produto_id": produto_id,
                "codigo": linha.get("codigo") or "",
                "nome": linha.get("nome") or "",
                "codigo_barras": linha.get("codigo_barras") or "—",
                "preco_venda": int(linha.get("preco_venda") or 0),
                "unidade_base": linha.get("unidade_base") or "",
                "quantidade": quantidade,
            })
            adicionados += 1
        if adicionados:
            self._atualizar_fila()
        return adicionados

    def adicionar_selecionados(self):
        linhas = self.tabela_produtos.linhas_selecionadas()
        if not linhas:
            dialogs.alerta(self, self.tema, "Selecione um ou mais produtos na lista da esquerda.\n\n"
                                            "Dica: segure Ctrl ou Shift para escolher vários.")
            return 0
        adicionados = self.adicionar(linhas)
        self.status(f"{adicionados} produto(s) adicionado(s) à fila de etiquetas.")
        return adicionados

    def adicionar_todos(self):
        dados = self.tabela_produtos.registros()
        if not dados:
            dialogs.alerta(self, self.tema, "Nenhum produto com os filtros atuais.")
            return 0
        total_etiquetas = len(dados) * self._quantidade_padrao()
        if len(dados) > 200 and not dialogs.confirmar(
            self, self.tema,
            f"Serão adicionados {len(dados)} produtos à fila ({total_etiquetas} etiquetas no total).\n\n"
            "Continuar?", "Adicionar todos", "Adicionar", "Cancelar"):
            return 0
        adicionados = self.adicionar(dados)
        self.status(f"{adicionados} produto(s) adicionado(s) à fila de etiquetas.")
        return adicionados

    def remover_selecionados(self):
        linhas = self.tabela_fila.linhas_selecionadas()
        if not linhas:
            dialogs.alerta(self, self.tema, "Selecione itens na fila de etiquetas para remover.")
            return
        ids = {int(l["produto_id"]) for l in linhas}
        self._fila = [i for i in self._fila if i["produto_id"] not in ids]
        self._atualizar_fila()
        self.status(f"{len(ids)} produto(s) removido(s) da fila.")

    def limpar_fila(self):
        if not self._fila:
            dialogs.info(self, self.tema, "A fila de etiquetas já está vazia.")
            return
        if not dialogs.confirmar(self, self.tema, f"Remover todos os {len(self._fila)} produto(s) da fila?",
                                 "Limpar fila", "Limpar", "Cancelar"):
            return
        self._fila = []
        self._atualizar_fila()

    def definir_quantidade(self, linha: dict | None = None):
        """Define quantas etiquetas imprimir de cada produto selecionado na fila."""
        linhas = [linha] if isinstance(linha, dict) else self.tabela_fila.linhas_selecionadas()
        linhas = [l for l in linhas if l]
        if not linhas:
            dialogs.alerta(self, self.tema, "Selecione um item na fila de etiquetas.")
            return
        nomes = ", ".join(str(l["nome"]) for l in linhas[:3])
        if len(linhas) > 3:
            nomes += f" e mais {len(linhas) - 3}"
        valor = dialogs.pedir_valor(self.ctx.janela, self.tema, "Quantidade de etiquetas",
                                    f"Quantas etiquetas imprimir de:\n{nomes}?",
                                    valor=int(linhas[0]["quantidade"]), tipo="quantidade", minimo=1,
                                    dica="De 1 a 999 etiquetas por produto.")
        if not valor:
            return
        quantidade = max(1, min(int(float(valor)), 999))
        ids = {int(l["produto_id"]) for l in linhas}
        for item in self._fila:
            if item["produto_id"] in ids:
                item["quantidade"] = quantidade
        self._atualizar_fila()
        self.status(f"Quantidade definida: {quantidade} etiqueta(s) por produto.")

    def abrir_produto(self):
        linha = self.tabela_produtos.linha_selecionada()
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione um produto para abrir o cadastro.")
            return
        self.ctx.navegar("produtos", {"produto_id": int(linha["id"])})

    # ------------------------------------------------------------------ códigos de barras
    def gerar_codigo_selecionados(self):
        linhas = self.tabela_produtos.linhas_selecionadas()
        if not linhas:
            dialogs.alerta(self, self.tema, "Selecione os produtos que precisam de código de barras.")
            return 0
        gerados = 0
        erros = []
        for linha in linhas:
            if linha.get("codigo_barras") and linha["codigo_barras"] != "—":
                continue
            try:
                etiquetas_mod.gerar_codigo_para_produto(self.banco, int(linha["id"]), autor=self.usuario)
                gerados += 1
            except Exception as exc:
                erros.append(f"{linha['nome']}: {exc}")
        if erros:
            dialogs.alerta(self, self.tema, "Não foi possível gerar código para:\n" + "\n".join(erros[:5]))
        if gerados:
            self.carregar()
            dialogs.sucesso(self, self.tema, f"{gerados} código(s) de barras interno(s) gerado(s).\n\n"
                                             "Agora adicione os produtos à fila e imprima as etiquetas.")
        elif not erros:
            dialogs.info(self, self.tema, "Os produtos selecionados já possuem código de barras.")
        return gerados

    def gerar_codigo_todos(self):
        pendentes = etiquetas_mod.produtos_sem_codigo(self.banco)
        if not pendentes:
            dialogs.info(self, self.tema, "Todos os produtos ativos já possuem código de barras.")
            return 0
        if not dialogs.confirmar(self, self.tema,
                                 f"{len(pendentes)} produto(s) sem código de barras.\n\n"
                                 "Gerar um EAN-13 interno (faixa 200–299) para todos?",
                                 "Gerar códigos", "Gerar", "Cancelar"):
            return 0
        gerados = 0
        erros = []
        for produto in pendentes:
            try:
                etiquetas_mod.gerar_codigo_para_produto(self.banco, int(produto["id"]), autor=self.usuario)
                gerados += 1
            except Exception as exc:
                erros.append(f"{produto['nome']}: {exc}")
        self.carregar()
        if erros:
            dialogs.alerta(self, self.tema,
                           f"{gerados} código(s) gerado(s), mas houve {len(erros)} falha(s):\n"
                           + "\n".join(erros[:5]))
        if gerados:
            dialogs.sucesso(self, self.tema, f"{gerados} código(s) gerado(s) para produtos sem código de barras.")
        return gerados

    # ------------------------------------------------------------------ impressão
    def _ids_e_quantidades(self) -> tuple[list[int], list[int]]:
        ids = [int(i["produto_id"]) for i in self._fila]
        quantidades = [int(i["quantidade"]) for i in self._fila]
        return ids, quantidades

    def _opcoes(self) -> dict:
        return {
            "mostrar_preco": bool(self.var_preco.get()),
            "mostrar_codigo_interno": bool(self.var_codigo_interno.get()),
            "mostrar_marca": bool(self.var_marca.get()),
        }

    def _modelo_mudou(self):
        self.status(f"Modelo selecionado: {self.var_modelo.get()}")

    def _checar_fila(self) -> bool:
        if not self._fila:
            dialogs.alerta(self, self.tema, "A fila de etiquetas está vazia.\n\n"
                                            "Selecione produtos na lista da esquerda e clique em “＋ Adicionar”.")
            return False
        sem_codigo = [i["nome"] for i in self._fila
                      if not (i.get("codigo_barras") and i["codigo_barras"] != "—") and not i.get("codigo")]
        if sem_codigo:
            dialogs.alerta(self, self.tema, "Estes produtos não têm código para imprimir:\n"
                                            + "\n".join(sem_codigo[:5])
                                            + "\n\nUse “🔢 Gerar código de barras” antes de imprimir.")
            return False
        return True

    def gerar_pdf(self):
        """Monta a folha A4 com as etiquetas e oferece imprimir/abrir."""
        if not self._checar_fila():
            return None
        ids, quantidades = self._ids_e_quantidades()
        configuracao = etiquetas_mod.aplicar_modelo(self.var_modelo.get())
        try:
            caminho = etiquetas_mod.gerar_pdf(
                self.banco, ids,
                colunas=configuracao["colunas"], linhas_por_pagina=configuracao["linhas"],
                largura_mm=configuracao["largura_mm"], altura_mm=configuracao["altura_mm"],
                quantidades=quantidades, **self._opcoes(),
            )
        except etiquetas_mod.ErroEtiqueta as exc:
            dialogs.erro(self, self.tema, str(exc), "Etiquetas")
            return None
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao gerar a folha de etiquetas.")
            return None
        total = sum(quantidades)
        self.status(f"Folha de etiquetas gerada: {total} etiqueta(s) em {caminho}")
        imprimir_documento(self, self.tema, caminho, f"Etiquetas ({total} unidades)")
        return caminho

    def imprimir(self):
        """Gera e envia direto para a impressora padrão."""
        if not self._checar_fila():
            return False
        ids, quantidades = self._ids_e_quantidades()
        try:
            ok, mensagem, caminho = etiquetas_mod.imprimir(
                self.banco, ids, modelo=self.var_modelo.get(), quantidades=quantidades, **self._opcoes(),
            )
        except etiquetas_mod.ErroEtiqueta as exc:
            dialogs.erro(self, self.tema, str(exc), "Etiquetas")
            return False
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao imprimir as etiquetas.")
            return False
        if ok:
            dialogs.sucesso(self, self.tema, f"{mensagem}\n\nArquivo: {caminho}", "Etiquetas enviadas")
            return True
        dialogs.alerta(self, self.tema, f"Não foi possível imprimir automaticamente.\n{mensagem}\n\n"
                                        "A folha será aberta para você imprimir manualmente.")
        imprimir_documento(self, self.tema, caminho, "Etiquetas")
        return False

    def imprimir_lista(self):
        """Atalho global Ctrl+P (mesmo comportamento de “Imprimir etiquetas”)."""
        return self.imprimir()

    def previsualizar(self):
        linha = self.tabela_fila.linha_selecionada()
        if not linha:
            if not self._fila:
                dialogs.alerta(self, self.tema, "Adicione produtos à fila para ver uma prévia da etiqueta.")
                return None
            linha = self._fila[0]
        try:
            caminho = etiquetas_mod.salvar_png(
                self.banco, int(linha["produto_id"]),
                mostrar_preco=bool(self.var_preco.get()),
                mostrar_codigo_interno=bool(self.var_codigo_interno.get()),
                mostrar_marca=bool(self.var_marca.get()),
            )
        except etiquetas_mod.ErroEtiqueta as exc:
            dialogs.erro(self, self.tema, str(exc), "Pré-visualização")
            return None
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao gerar a prévia da etiqueta.")
            return None
        dialogs.mostrar_imagem(self.ctx.janela, self.tema, f"Etiqueta — {linha['nome']}", caminho, largura=460)
        return caminho

    # ------------------------------------------------------------------ integração
    def ao_tecla(self, tecla: str) -> bool:
        if tecla == "<F11>":
            self.gerar_pdf()
            return True
        return False

    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("apenas_sem_codigo") is not None:
            self.var_sem_codigo.set(bool(parametros["apenas_sem_codigo"]))
        self.carregar()
        ids = parametros.get("produto_ids") or []
        if ids:
            linhas = []
            for produto_id in ids:
                produto = produtos_mod.pegar_simples(self.banco, int(produto_id))
                if produto:
                    linhas.append(dict(produto))
            if linhas:
                self.adicionar(linhas)
                self.status(f"{len(linhas)} produto(s) adicionado(s) à fila de etiquetas.")

    def atualizar_tema(self):
        self.tabela_produtos.atualizar_tema()
        self.tabela_fila.atualizar_tema()

    # ------------------------------------------------------------------ utilidades
    def registros(self) -> list[dict]:
        """Produtos listados (usado pelos testes automatizados)."""
        return self.tabela_produtos.registros()

    def fila(self) -> list[dict]:
        return [dict(i) for i in self._fila]
