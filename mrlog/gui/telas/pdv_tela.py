"""
PDV — Frente de Caixa.

Tela de venda rápida, pensada para o uso com **leitor de código de barras USB**
(modo teclado): o campo de código fica sempre com o foco, cada bipada adiciona o
produto ao carrinho e bipar o mesmo produto de novo apenas soma a quantidade.

Recursos:
  * bipagem, digitação de código interno e busca por nome (F2);
  * quantidade em qualquer unidade compatível (venda fracionada: 250 g de 1 kg);
  * desconto no item e na venda (com limite por perfil e liberação de supervisor);
  * pagamento misto, troco automático e fiado com vencimento;
  * venda suspensa (guarda e retoma depois), cancelamento de item e do cupom;
  * impressão do recibo não fiscal após cada venda;
  * cadastro rápido do produto quando o código bipado não existe.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ... import caixa as caixa_mod
from ... import clientes as clientes_mod
from ... import configuracoes as config_mod
from ... import formas_pagamento
from ... import impressao as impressao_mod
from ... import produtos as produtos_mod
from ... import unidades as unidades_mod
from ... import usuarios as usuarios_mod
from ... import vendas as vendas_mod
from ...caminhos import pasta_fotos
from ...utils import formatar_cpf_cnpj, formatar_dinheiro, formatar_quantidade, formatar_telefone, hoje
from .. import dialogs
from ..dialogs_pagamento import DialogoPagamento
from ..tema import FONTE_BASE, FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO, FONTE_VALOR
from ..widgets import Tabela
from . import Tela
from .produtos_tela import cadastro_rapido, selecionar_produto

COLUNAS_CARRINHO = [
    {"chave": "item", "rotulo": "Item", "largura": 46, "tipo": "inteiro", "alinhamento": "centro"},
    {"chave": "codigo", "rotulo": "Código", "largura": 84},
    {"chave": "nome", "rotulo": "Produto", "largura": 300},
    {"chave": "quantidade_texto", "rotulo": "Quantidade", "largura": 110, "alinhamento": "centro"},
    {"chave": "preco_unitario", "rotulo": "Preço unit.", "largura": 100, "tipo": "dinheiro"},
    {"chave": "desconto", "rotulo": "Desconto", "largura": 90, "tipo": "dinheiro"},
    {"chave": "total_liquido", "rotulo": "Total", "largura": 110, "tipo": "dinheiro"},
    {"chave": "estoque_texto", "rotulo": "Estoque", "largura": 100, "alinhamento": "centro"},
]


class PdvTela(Tela):
    titulo = "PDV — Frente de Caixa"
    descricao = "Bipe o código de barras, confira o carrinho e finalize o pagamento."

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self.config = config_mod.carregar(self.banco)
        self.carrinho = vendas_mod.Carrinho(self.banco, vendedor=ctx.usuario, config=self._config_carrinho())
        self.ultima_venda: dict | None = None
        self.suspensas: dict[int, dict] = {}
        self._foto_atual = None
        self._montar_interface()
        self._registrar_teclas()
        self._verificar_caixa()

    def _config_carrinho(self) -> dict:
        return {
            "venda_permite_preco_zero": bool(self.config.get("venda_permite_preco_zero")),
            "venda_permite_estoque_negativo": bool(self.config.get("venda_permite_estoque_negativo")),
            "venda_exige_caixa_aberto": bool(self.config.get("venda_exige_caixa_aberto")),
        }

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.corpo.rowconfigure(1, weight=1)
        self.corpo.columnconfigure(0, weight=4)
        self.corpo.columnconfigure(1, weight=1)

        self._montar_topo()
        self._montar_carrinho()
        self._montar_totais()
        self._montar_rodape()

    def _montar_topo(self):
        topo = ttk.Frame(self.corpo, style="Card.TFrame", padding=(10, 8))
        topo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        topo.columnconfigure(2, weight=1)

        ttk.Label(topo, text="🛒 Código do produto:", style="Card.TLabel", font=FONTE_SUBTITULO).grid(
            row=0, column=0, sticky="w")
        self.entrada_codigo = ttk.Entry(topo, width=30, font=FONTE_SUBTITULO)
        self.entrada_codigo.grid(row=0, column=1, sticky="w", padx=(6, 6))
        self.entrada_codigo.bind("<Return>", self._ao_bipar)
        self.entrada_codigo.bind("<KP_Enter>", self._ao_bipar)
        self.entrada_codigo.bind("<FocusOut>", lambda e: self._reagendar_foco())

        ttk.Button(topo, text="Adicionar (Enter)", style="Primario.TButton",
                   command=self._ao_bipar).grid(row=0, column=2, sticky="w")
        ttk.Button(topo, text="Buscar produto (F2)", command=self.buscar_produto).grid(row=0, column=3, sticky="w", padx=6)
        ttk.Button(topo, text="Qtd (F3)", command=self.alterar_quantidade).grid(row=0, column=4, sticky="w")

        segunda = ttk.Frame(topo, style="Card.TFrame")
        segunda.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        segunda.columnconfigure(3, weight=1)

        ttk.Label(segunda, text="Vendedor:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.combo_vendedor = ttk.Combobox(segunda, width=22, state="readonly",
                                           values=[u["nome"] for u in usuarios_mod.vendedores(self.banco)])
        self.combo_vendedor.grid(row=0, column=1, sticky="w", padx=(4, 12))
        self.combo_vendedor.set(str(self.usuario["nome"]) if self.usuario else "")
        self.combo_vendedor.bind("<<ComboboxSelected>>", lambda e: self._definir_vendedor())

        ttk.Label(segunda, text="Cliente:", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.entrada_cliente = ttk.Entry(segunda, width=34)
        self.entrada_cliente.grid(row=0, column=3, sticky="ew", padx=(4, 6))
        self.entrada_cliente.insert(0, "Consumidor final")
        self.entrada_cliente.configure(state="readonly")
        ttk.Button(segunda, text="Identificar cliente (F7)", command=self.identificar_cliente).grid(row=0, column=4, sticky="w")

        self.rotulo_caixa = ttk.Label(segunda, text="", style="Card.TLabel")
        self.rotulo_caixa.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        self._job_foco = None

    def _montar_carrinho(self):
        quadro = ttk.Frame(self.corpo, style="TFrame")
        quadro.grid(row=1, column=0, sticky="nsew")
        quadro.rowconfigure(0, weight=1)
        quadro.columnconfigure(0, weight=1)
        self.tabela = Tabela(quadro, self.tema, COLUNAS_CARRINHO, ao_selecionar=self._ao_selecionar_item,
                             ao_duplo_clique=lambda linha: self.alterar_quantidade(), mostrar_busca=False, altura=14)
        self.tabela.grid(row=0, column=0, sticky="nsew")

    def _montar_totais(self):
        painel = ttk.Frame(self.corpo, style="Card.TFrame", padding=12)
        painel.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        painel.columnconfigure(0, weight=1)

        self.rotulo_foto = tk.Label(painel, text="📷", width=20, height=7, relief="solid", bd=1,
                                    background=self.tema.cor("bg_alt"), foreground=self.tema.cor("fg_fraco"))
        self.rotulo_foto.grid(row=0, column=0, pady=(0, 8))

        linhas = [
            ("Subtotal", "subtotal", "fg"),
            ("Desconto itens", "desconto_itens", "perigo"),
            ("Desconto venda", "desconto_venda", "perigo"),
            ("Acréscimo", "acrescimo", "alerta"),
        ]
        self.rotulos: dict[str, tk.Label] = {}
        for indice, (rotulo, chave, cor) in enumerate(linhas, start=1):
            quadro = ttk.Frame(painel, style="Card.TFrame")
            quadro.grid(row=indice, column=0, sticky="ew")
            ttk.Label(quadro, text=rotulo, style="Card.Suave.TLabel").pack(side="left")
            valor = tk.Label(quadro, text=formatar_dinheiro(0), font=FONTE_BASE, anchor="e",
                             background=self.tema.cor("bg_card"), foreground=self.tema.cor(cor))
            valor.pack(side="right")
            self.rotulos[chave] = valor

        ttk.Label(painel, text="TOTAL A PAGAR", style="Card.Suave.TLabel").grid(row=6, column=0, sticky="w", pady=(12, 0))
        self.rotulo_total = tk.Label(painel, text="R$ 0,00", font=FONTE_VALOR, anchor="w",
                                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"))
        self.rotulo_total.grid(row=7, column=0, sticky="ew")
        self.rotulo_itens = tk.Label(painel, text="0 item(ns)", font=FONTE_PEQUENA, anchor="w",
                                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg_suave"))
        self.rotulo_itens.grid(row=8, column=0, sticky="ew")
        self.rotulo_lucro = tk.Label(painel, text="", font=FONTE_PEQUENA, anchor="w",
                                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("sucesso"))
        self.rotulo_lucro.grid(row=9, column=0, sticky="ew", pady=(2, 8))

        ttk.Button(painel, text="✔ FINALIZAR VENDA (F12)", style="Sucesso.TButton",
                   command=self.finalizar_venda).grid(row=10, column=0, sticky="ew", pady=(6, 4))
        ttk.Button(painel, text="Desconto na venda (F6)", command=self.desconto_venda).grid(row=11, column=0, sticky="ew", pady=2)
        ttk.Button(painel, text="Limpar carrinho (F9)", command=self.limpar_carrinho).grid(row=12, column=0, sticky="ew", pady=2)
        ttk.Button(painel, text="Suspender venda (F10)", command=self.suspender_venda).grid(row=13, column=0, sticky="ew", pady=2)
        ttk.Button(painel, text="Vendas suspensas", command=self.listar_suspensas).grid(row=14, column=0, sticky="ew", pady=2)

        self.quadro_dia = ttk.Frame(painel, style="Card.TFrame")
        self.quadro_dia.grid(row=15, column=0, sticky="ew", pady=(12, 0))
        self.rotulo_dia = tk.Label(self.quadro_dia, text="", font=FONTE_PEQUENA, justify="left", anchor="w",
                                   background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg_suave"))
        self.rotulo_dia.pack(fill="x")

    def _montar_rodape(self):
        rodape = ttk.Frame(self.corpo, style="Card.TFrame", padding=(10, 6))
        rodape.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.rotulo_mensagem = ttk.Label(rodape, text="Pronto para vender: bipe o primeiro produto.",
                                         style="Card.TLabel", wraplength=1000, justify="left")
        self.rotulo_mensagem.pack(side="left", fill="x", expand=True)
        ttk.Button(rodape, text="Atalhos do PDV", command=self.mostrar_atalhos).pack(side="right")

    # ------------------------------------------------------------------ atalhos
    def _registrar_teclas(self):
        mapa = {
            "<F2>": self.buscar_produto,
            "<F3>": self.alterar_quantidade,
            "<F4>": self.alterar_preco,
            "<F5>": self.desconto_item,
            "<F6>": self.desconto_venda,
            "<F7>": self.identificar_cliente,
            "<F8>": self.remover_item,
            "<F9>": self.limpar_carrinho,
            "<F10>": self.suspender_venda,
            "<F12>": self.finalizar_venda,
            "<plus>": lambda: self._ajustar_quantidade(1),
            "<minus>": lambda: self._ajustar_quantidade(-1),
            "<Delete>": self.remover_item,
            "<Control-p>": self.imprimir_ultima,
            "<Control-P>": self.imprimir_ultima,
            "<Control-n>": self.nova_venda,
            "<Control-N>": self.nova_venda,
        }
        for sequencia, comando in mapa.items():
            self.bind(sequencia, lambda e, c=comando: self._executar(c))

    def _executar(self, comando):
        try:
            comando()
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro no PDV.")
        return "break"

    def ao_tecla(self, tecla: str) -> bool:
        """Captura as teclas F do PDV (a janela principal não troca de tela)."""
        mapa = {
            "<F2>": self.buscar_produto,
            "<F3>": self.alterar_quantidade,
            "<F4>": self.alterar_preco,
            "<F5>": self.desconto_item,
            "<F6>": self.desconto_venda,
            "<F7>": self.identificar_cliente,
            "<F8>": self.remover_item,
            "<F9>": self.limpar_carrinho,
            "<F10>": self.suspender_venda,
            "<F12>": self.finalizar_venda,
        }
        comando = mapa.get(tecla)
        if comando is None:
            return False
        self._executar(comando)
        return True

    def focar_principal(self):
        try:
            self.entrada_codigo.focus_set()
        except tk.TclError:
            pass

    focar_busca = focar_principal

    def _reagendar_foco(self):
        """Devolve o foco ao campo de código para o leitor continuar funcionando."""
        if not self.config.get("pdv_bipador_ativo", True):
            return
        if self._job_foco:
            try:
                self.after_cancel(self._job_foco)
            except tk.TclError:
                pass
        self._job_foco = self.after(300, self._devolver_foco)

    def _devolver_foco(self):
        try:
            if not self.winfo_exists():
                return
            if self.ctx.app._ha_modal():
                return
            foco = self.winfo_toplevel().focus_get()
        except (KeyError, tk.TclError, AttributeError):
            foco = None
        if not self.config.get("pdv_bipador_ativo", True):
            return
        if foco is None or foco is self.winfo_toplevel():
            self.focar_principal()

    # ------------------------------------------------------------------ caixa
    def _verificar_caixa(self):
        caixa = caixa_mod.caixa_aberto(self.banco)
        self.ctx.caixa_aberto = caixa
        if caixa:
            posicao = caixa_mod.posicao(self.banco, caixa["id"])
            self.rotulo_caixa.configure(
                text=f"Caixa aberto por {caixa['usuario_nome'] or '—'} • gaveta (dinheiro): "
                     f"{formatar_dinheiro(posicao['valor_sistema'])} • {posicao['qtd_vendas']} venda(s)",
                foreground=self.tema.cor("sucesso"),
            )
        else:
            self.rotulo_caixa.configure(
                text="⚠ Caixa fechado — vendas em dinheiro/Pix/cartão não serão registradas no caixa. "
                     "Abra o caixa (F4 no menu) ou use o botão ao lado.",
                foreground=self.tema.cor("perigo"),
            )
            ttk.Button(self.rotulo_caixa.master, text="Abrir caixa agora", command=self._abrir_caixa_rapido).grid(
                row=1, column=5, sticky="w", padx=(8, 0))
        self._atualizar_dia()

    def _abrir_caixa_rapido(self):
        if not self.ctx.pode("caixa"):
            self.ctx.exigir_permissao("caixa", "abrir o caixa")
            return
        valor = dialogs.pedir_valor(self, self.tema, "Abertura de caixa", "Valor inicial em gaveta (troco)",
                                    0, tipo="dinheiro", dica="Deixe 0 para abrir sem troco.")
        if valor is None:
            return
        try:
            caixa_mod.abrir(self.banco, valor_abertura=int(valor), observacao="Abertura rápida pelo PDV",
                            autor=self.usuario)
        except caixa_mod.ErroCaixa as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self._limpar_botao_abrir()
        self._verificar_caixa()
        self.ctx.app.atualizar_caixa()
        dialogs.sucesso(self, self.tema, "Caixa aberto. Boas vendas!")

    def _limpar_botao_abrir(self):
        for filho in self.rotulo_caixa.master.winfo_children():
            if isinstance(filho, ttk.Button) and "Abrir caixa" in str(filho.cget("text")):
                filho.destroy()

    def _atualizar_dia(self):
        resumo = vendas_mod.resumo_dia(self.banco)
        self.rotulo_dia.configure(
            text=(f"Hoje ({resumo['data'][8:10]}/{resumo['data'][5:7]}): {resumo['quantidade']} venda(s) • "
                  f"{formatar_dinheiro(resumo['total'])} • lucro {formatar_dinheiro(resumo['lucro'])} • "
                  f"ticket {formatar_dinheiro(resumo['ticket_medio'])}"),
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg_suave"),
        )

    # ------------------------------------------------------------------ bipagem
    def _ao_bipar(self, _evento=None):
        codigo = self.entrada_codigo.get().strip()
        self.entrada_codigo.delete(0, "end")
        if not codigo:
            self.focar_principal()
            return "break"
        produto, como = produtos_mod.resolver_bipagem(self.banco, codigo)
        if produto is None:
            self._mensagem(f"Código '{codigo}' não encontrado no cadastro.", erro=True)
            if dialogs.confirmar(self, self.tema,
                                 f"Nenhum produto cadastrado com o código '{codigo}'.\n\n"
                                 "Deseja cadastrar este produto agora (cadastro rápido)?",
                                 "Código desconhecido", "Cadastrar", "Cancelar"):
                novo = cadastro_rapido(self.ctx, codigo)
                if novo:
                    self._adicionar(novo)
            self.focar_principal()
            return "break"
        if como == "nome":
            self._mensagem(f"Produto localizado pelo nome: {produto['nome']}")
        self._adicionar(produto)
        self.focar_principal()
        return "break"

    def _adicionar(self, produto, quantidade: float = 1.0, unidade: str | None = None):
        if bool(self.config.get("pdv_confirmar_quantidade")):
            dados = self._perguntar_quantidade(produto, quantidade)
            if dados is None:
                return
            quantidade, unidade = dados
        try:
            item = self.carrinho.adicionar(produto, quantidade, unidade=unidade)
        except vendas_mod.ErroVenda as exc:
            dialogs.alerta(self, self.tema, str(exc), "Não foi possível adicionar")
            self.focar_principal()
            return
        self._mensagem(f"{item.nome} • {item.descricao_quantidade()} • {formatar_dinheiro(item.total_liquido)}")
        self._redesenhar(selecionar=item.produto_id)
        self._mostrar_foto(item)

    def _perguntar_quantidade(self, produto, quantidade_padrao: float = 1.0):
        """Quando ativado nas configurações, pergunta quantidade/unidade antes de somar."""
        siglas = unidades_mod.siglas_permitidas(produto, self.banco)
        dialogo = dialogs.Modal(self, self.tema, f"Quantidade — {produto['nome']}", largura=400, altura=230)
        ttk.Label(dialogo.corpo, text="Quantidade:", style="TLabel").pack(anchor="w")
        entrada = ttk.Entry(dialogo.corpo, width=14, justify="right", font=FONTE_SUBTITULO)
        entrada.pack(anchor="w", pady=(2, 6))
        entrada.insert(0, str(quantidade_padrao).replace(".", ","))
        entrada.select_range(0, "end")
        entrada.focus_set()
        ttk.Label(dialogo.corpo, text="Unidade:", style="TLabel").pack(anchor="w")
        combo = ttk.Combobox(dialogo.corpo, values=siglas, width=8, state="readonly")
        combo.set(produto["unidade_venda"] or produto["unidade_base"])
        combo.pack(anchor="w", pady=(2, 6))
        ttk.Label(dialogo.corpo,
                  text=f"Estoque: {formatar_quantidade(produto['estoque_atual'] or 0)} {produto['unidade_base']}",
                  style="Suave.TLabel").pack(anchor="w")

        def confirmar(_evento=None):
            texto = entrada.get().strip().replace(",", ".")
            try:
                quantidade = float(texto)
            except ValueError:
                dialogs.alerta(dialogo, self.tema, "Quantidade inválida.")
                return
            dialogo.confirmar((quantidade, combo.get()))

        entrada.bind("<Return>", confirmar)
        dialogo.barra_botoes((("Adicionar", confirmar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
        return dialogo.abrir()

    def buscar_produto(self):
        produto = selecionar_produto(self.ctx, "Buscar produto para venda")
        if produto:
            self._adicionar(produto)
        self.focar_principal()

    # ------------------------------------------------------------------ carrinho
    def _redesenhar(self, selecionar: int | None = None):
        linhas = []
        for indice, item in enumerate(self.carrinho.itens, start=1):
            saldo = produtos_mod.pegar_simples(self.banco, item.produto_id)
            estoque = float(saldo["estoque_atual"] or 0) if saldo else 0.0
            ja_no_carrinho = sum(i.quantidade_base for i in self.carrinho.itens if i.produto_id == item.produto_id)
            linhas.append({
                "item": indice,
                "produto_id": item.produto_id,
                "codigo": item.codigo,
                "nome": item.nome,
                "quantidade_texto": item.descricao_quantidade(),
                "preco_unitario": item.preco_unitario,
                "desconto": int(item.desconto or 0),
                "total_liquido": item.total_liquido,
                "estoque_texto": f"{formatar_quantidade(estoque)} {item.unidade_base}",
                "_tag": ("alerta" if ja_no_carrinho > estoque and estoque > 0 else ""),
            })
        self.tabela.carregar(linhas, resumo=f"{len(linhas)} item(ns) no carrinho")
        if selecionar is not None:
            self.tabela.selecionar_por("produto_id", selecionar)
        self._atualizar_totais()

    def _atualizar_totais(self):
        totais = self.carrinho.totais()
        self.rotulos["subtotal"].configure(text=formatar_dinheiro(totais.subtotal))
        self.rotulos["desconto_itens"].configure(text=formatar_dinheiro(totais.desconto_itens))
        self.rotulos["desconto_venda"].configure(text=formatar_dinheiro(totais.desconto_venda))
        self.rotulos["acrescimo"].configure(text=formatar_dinheiro(totais.acrescimo))
        self.rotulo_total.configure(text=formatar_dinheiro(totais.total), background=self.tema.cor("bg_card"),
                                    foreground=self.tema.cor("fg"))
        self.rotulo_itens.configure(text=f"{totais.quantidade_itens} item(ns) • {formatar_quantidade(totais.quantidade_produtos)} un.",
                                    background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg_suave"))
        self.rotulo_lucro.configure(text=f"Lucro estimado: {formatar_dinheiro(totais.lucro)} ({totais.margem_pct:.1f}%)".replace(".", ","),
                                    background=self.tema.cor("bg_card"), foreground=self.tema.cor("sucesso"))

    def _indice_item(self) -> int | None:
        linha = self.tabela.linha_selecionada()
        if not linha:
            dialogs.alerta(self, self.tema, "Selecione um item do carrinho primeiro.")
            return None
        return int(linha["item"]) - 1

    def _ao_selecionar_item(self, linha: dict | None):
        if linha:
            produto = produtos_mod.pegar(self.banco, linha["produto_id"])
            if produto:
                self._mostrar_foto_por_produto(produto)

    def _mostrar_foto(self, item):
        produto = produtos_mod.pegar(self.banco, item.produto_id)
        if produto:
            self._mostrar_foto_por_produto(produto)

    def _mostrar_foto_por_produto(self, produto):
        try:
            caminho = produtos_mod.caminho_foto(produto)
        except Exception:
            caminho = None
        self._foto_atual = None
        if caminho and caminho.exists():
            try:
                from PIL import Image, ImageTk

                imagem = Image.open(caminho)
                imagem.thumbnail((150, 150))
                self._foto_atual = ImageTk.PhotoImage(imagem)
                self.rotulo_foto.configure(image=self._foto_atual, text="", width=150, height=150)
                return
            except Exception:
                pass
        self.rotulo_foto.configure(image="", text="📷\nsem foto", width=20, height=7)

    def _mensagem(self, texto: str, erro: bool = False):
        self.rotulo_mensagem.configure(text=texto, foreground=self.tema.cor("perigo" if erro else "fg"))
        self.ctx.status(texto)

    # ------------------------------------------------------------------ edição de itens
    def alterar_quantidade(self):
        indice = self._indice_item()
        if indice is None:
            return
        item = self.carrinho.item(indice)
        if not item:
            return
        produto = produtos_mod.pegar(self.banco, item.produto_id)
        siglas = unidades_mod.siglas_permitidas(produto, self.banco)
        dados = dialogs.formulario(
            self, self.tema, f"Quantidade — {item.nome}",
            [
                {"chave": "quantidade", "rotulo": "Quantidade", "tipo": "quantidade", "obrigatorio": True,
                 "decimais": 4, "minimo": 0.0001},
                {"chave": "unidade", "rotulo": "Unidade", "tipo": "lista", "opcoes": siglas, "largura": 12},
            ],
            {"quantidade": item.quantidade, "unidade": item.unidade}, largura=400,
            texto=f"Estoque disponível: {formatar_quantidade(produto['estoque_atual'] or 0)} {produto['unidade_base']}",
        )
        if not dados:
            return
        try:
            self.carrinho.alterar_quantidade(indice, float(dados["quantidade"]), unidade=dados.get("unidade"))
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self._redesenhar(selecionar=item.produto_id)
        self.focar_principal()

    def _ajustar_quantidade(self, delta: float):
        """Teclas + / -: aumenta ou diminui 1 unidade do item selecionado."""
        indice = self._indice_item()
        if indice is None:
            return
        item = self.carrinho.item(indice)
        if not item:
            return
        nova = item.quantidade + delta
        if nova <= 0:
            self.remover_item()
            return
        try:
            self.carrinho.alterar_quantidade(indice, nova)
        except vendas_mod.ErroVenda as exc:
            self._mensagem(str(exc), erro=True)
            return
        self._redesenhar(selecionar=item.produto_id)

    def alterar_preco(self):
        if not self.ctx.pode("produtos_preco_editar"):
            if not self.ctx.senha_supervisor("Alteração de preço unitário de item no PDV"):
                return
        indice = self._indice_item()
        if indice is None:
            return
        item = self.carrinho.item(indice)
        valor = dialogs.pedir_valor(self, self.tema, f"Preço unitário — {item.nome}",
                                    f"Novo preço por {item.unidade}", item.preco_unitario, tipo="dinheiro",
                                    dica=f"Preço atual: {formatar_dinheiro(item.preco_unitario)}")
        if valor is None:
            return
        try:
            self.carrinho.alterar_preco(indice, int(valor))
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.banco.registrar_log("pdv_preco_alterado", f"{item.nome}: {formatar_dinheiro(item.preco_unitario)}",
                                 self.usuario["id"] if self.usuario else None, self.ctx.nome_usuario)
        self._redesenhar(selecionar=item.produto_id)
        self.focar_principal()

    def desconto_item(self):
        indice = self._indice_item()
        if indice is None:
            return
        item = self.carrinho.item(indice)
        limite = self.ctx.limite_desconto()
        dados = dialogs.formulario(
            self, self.tema, f"Desconto no item — {item.nome}",
            [
                {"chave": "tipo", "rotulo": "Tipo de desconto", "tipo": "lista", "opcoes": ["Valor (R$)", "Percentual (%)"],
                 "largura": 18},
                {"chave": "valor", "rotulo": "Valor", "tipo": "quantidade", "obrigatorio": True, "decimais": 2},
            ],
            {"tipo": "Percentual (%)", "valor": 0}, largura=400,
            texto=f"Total da linha: {formatar_dinheiro(item.total_bruto)}\nSeu limite de desconto: {limite:.0f}%",
        )
        if not dados:
            return
        try:
            if str(dados["tipo"]).startswith("Percentual"):
                percentual = float(dados["valor"])
                if percentual > limite and not self.ctx.senha_supervisor(
                        f"Desconto de {percentual:.1f}% acima do limite do perfil ({limite:.0f}%)"):
                    return
                self.carrinho.desconto_no_item(indice, percentual=percentual)
            else:
                centavos = int(round(float(dados["valor"]) * 100))
                percentual_equivalente = (centavos * 100.0 / item.total_bruto) if item.total_bruto else 0.0
                if percentual_equivalente > limite and not self.ctx.senha_supervisor(
                        f"Desconto de {percentual_equivalente:.1f}% acima do limite do perfil ({limite:.0f}%)"):
                    return
                self.carrinho.desconto_no_item(indice, valor=centavos)
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self._redesenhar(selecionar=item.produto_id)
        self.focar_principal()

    def desconto_venda(self):
        if not self.carrinho.itens:
            dialogs.alerta(self, self.tema, "O carrinho está vazio.")
            return
        totais = self.carrinho.totais()
        limite = self.ctx.limite_desconto()
        dados = dialogs.formulario(
            self, self.tema, "Desconto / acréscimo na venda",
            [
                {"chave": "tipo", "rotulo": "Operação", "tipo": "lista",
                 "opcoes": ["Desconto em R$", "Desconto em %", "Acréscimo em R$"], "largura": 20},
                {"chave": "valor", "rotulo": "Valor", "tipo": "quantidade", "obrigatorio": True, "decimais": 2},
            ],
            {"tipo": "Desconto em %", "valor": 0}, largura=440,
            texto=f"Subtotal: {formatar_dinheiro(totais.subtotal)}\nSeu limite de desconto: {limite:.0f}%",
        )
        if not dados:
            return
        tipo = str(dados["tipo"])
        try:
            valor = float(dados["valor"])
            if tipo == "Acréscimo em R$":
                self.carrinho.definir_acrescimo(int(round(valor * 100)))
                self.carrinho.desconto_valor = 0
            elif tipo == "Desconto em %":
                if valor > limite and not self.ctx.senha_supervisor(
                        f"Desconto de {valor:.1f}% acima do limite do perfil ({limite:.0f}%)"):
                    return
                self.carrinho.definir_desconto(percentual=valor, limite_pct=limite)
            else:
                centavos = int(round(valor * 100))
                percentual = (centavos * 100.0 / totais.subtotal) if totais.subtotal else 0.0
                if percentual > limite and not self.ctx.senha_supervisor(
                        f"Desconto de {percentual:.1f}% acima do limite do perfil ({limite:.0f}%)"):
                    return
                self.carrinho.definir_desconto(valor=centavos, limite_pct=limite)
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self._redesenhar()
        self.focar_principal()

    def remover_item(self):
        indice = self._indice_item()
        if indice is None:
            return
        item = self.carrinho.remover(indice)
        if item:
            self._mensagem(f"Item removido: {item.nome}")
        self._redesenhar()
        self.focar_principal()

    def limpar_carrinho(self):
        if not self.carrinho.itens:
            return
        if not dialogs.confirmar(self, self.tema, "Limpar todos os itens do carrinho?", "Limpar carrinho",
                                 "Limpar", "Cancelar"):
            return
        self.nova_venda()

    def nova_venda(self):
        self.carrinho = vendas_mod.Carrinho(self.banco, vendedor=self._vendedor_atual(), config=self._config_carrinho())
        self._rotulo_cliente("Consumidor final")
        self._redesenhar()
        self._mensagem("Nova venda iniciada. Bipe o primeiro produto.")
        self.focar_principal()

    def identificar_cliente(self):
        colunas = [
            {"chave": "nome", "rotulo": "Cliente", "largura": 260},
            {"chave": "documento_texto", "rotulo": "CPF/CNPJ", "largura": 150},
            {"chave": "telefone_texto", "rotulo": "Telefone", "largura": 130},
            {"chave": "saldo_devedor", "rotulo": "Saldo devedor", "largura": 120, "tipo": "dinheiro"},
            {"chave": "limite_credito", "rotulo": "Limite", "largura": 110, "tipo": "dinheiro"},
        ]

        def buscar(termo: str):
            linhas = []
            for cliente in clientes_mod.listar(self.banco, filtro=termo):
                linha = dict(cliente)
                linha["documento_texto"] = formatar_cpf_cnpj(linha.get("cpf_cnpj") or "")
                linha["telefone_texto"] = formatar_telefone(linha.get("celular") or linha.get("telefone") or "")
                linhas.append(linha)
            return linhas

        linha = dialogs.selecionar_registro(
            self, self.tema, "Identificar cliente", colunas, buscar(""), ao_buscar=buscar, largura=820,
            texto="Digite o nome ou CPF/CNPJ. Clique duas vezes para selecionar.",
        )
        if linha is None:
            return
        if not linha:
            if dialogs.confirmar(self, self.tema, "Vender como consumidor final (sem cliente)?", "Cliente",
                                 "Sim", "Cancelar"):
                try:
                    self.carrinho.definir_cliente(None)
                except vendas_mod.ErroVenda as exc:
                    dialogs.erro(self, self.tema, str(exc))
                self._rotulo_cliente("Consumidor final")
            self.focar_principal()
            return
        cliente = clientes_mod.pegar(self.banco, linha["id"])
        self.definir_cliente(cliente)
        self.focar_principal()

    def definir_cliente(self, cliente):
        """Vincula o cliente ao carrinho e atualiza o rótulo exibido no PDV."""
        if not cliente:
            return False
        try:
            self.carrinho.definir_cliente(cliente)
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc))
            return False
        texto_cliente = f"{cliente['nome']}"
        if clientes_mod.tem_limite(cliente):
            texto_cliente += f"  •  crédito disponível {formatar_dinheiro(clientes_mod.credito_disponivel(cliente))}"
        if int(cliente["saldo_devedor"] or 0) > 0:
            texto_cliente += f"  •  deve {formatar_dinheiro(int(cliente['saldo_devedor']))}"
        self._rotulo_cliente(texto_cliente)
        self._mensagem(f"Cliente: {cliente['nome']}")
        return True

    def _rotulo_cliente(self, texto: str):
        self.entrada_cliente.configure(state="normal")
        self.entrada_cliente.delete(0, "end")
        self.entrada_cliente.insert(0, texto)
        self.entrada_cliente.configure(state="readonly")


    def _vendedor_atual(self):
        nome = self.combo_vendedor.get().strip()
        for usuario in usuarios_mod.vendedores(self.banco):
            if usuario["nome"] == nome:
                return usuario
        return self.usuario

    def _definir_vendedor(self):
        vendedor = self._vendedor_atual()
        self.carrinho.vendedor = vendedor
        self._mensagem(f"Vendedor: {vendedor['nome'] if vendedor else '—'}")
        self.focar_principal()

    # ------------------------------------------------------------------ venda suspensa
    def suspender_venda(self):
        if not self.carrinho.itens:
            dialogs.alerta(self, self.tema, "Não há itens para suspender.")
            return
        descricao = dialogs.pedir_texto(self, self.tema, "Suspender venda", "Identificação da venda suspensa",
                                        valor=f"Mesa/pedido {len(self.suspensas) + 1}", obrigatorio=False,
                                        dica="Ex.: 'Cliente João — voltou ao carro'", largura=440)
        if descricao is None:
            return
        identificador = (max(self.suspensas) + 1) if self.suspensas else 1
        self.suspensas[identificador] = {
            "descricao": descricao or f"Venda {identificador}",
            "itens": [item.como_dict() for item in self.carrinho.itens],
            "cliente": dict(self.carrinho.cliente) if self.carrinho.cliente else None,
            "desconto": self.carrinho.desconto_valor,
            "acrescimo": self.carrinho.acrescimo,
            "vendedor": self.carrinho.vendedor,
            "hora": hoje(),
        }
        self.nova_venda()
        self._mensagem(f"Venda suspensa ({identificador}): {descricao or 'sem descrição'} — use 'Vendas suspensas' para retomar.")

    def listar_suspensas(self):
        if not self.suspensas:
            dialogs.info(self, self.tema, "Nenhuma venda suspensa nesta sessão.")
            return
        colunas = [
            {"chave": "id", "rotulo": "Nº", "largura": 50, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "descricao", "rotulo": "Identificação", "largura": 260},
            {"chave": "itens", "rotulo": "Itens", "largura": 70, "tipo": "inteiro", "alinhamento": "centro"},
            {"chave": "total", "rotulo": "Total", "largura": 110, "tipo": "dinheiro"},
            {"chave": "cliente", "rotulo": "Cliente", "largura": 200},
        ]
        dados = []
        for identificador, venda in self.suspensas.items():
            total = sum(int(i["total_liquido"]) for i in venda["itens"])
            dados.append({
                "id": identificador, "descricao": venda["descricao"], "itens": len(venda["itens"]),
                "total": total, "cliente": (venda["cliente"] or {}).get("nome", "Consumidor final"),
            })
        linha = dialogs.selecionar_registro(self, self.tema, "Vendas suspensas", colunas, dados, largura=760,
                                            texto="Selecione a venda e clique em 'Selecionar' para retomá-la.")
        if not linha:
            return
        self.retomar_venda(int(linha["id"]))

    def retomar_venda(self, identificador: int):
        venda = self.suspensas.get(identificador)
        if not venda:
            return
        if self.carrinho.itens and not dialogs.confirmar(
                self, self.tema, "O carrinho atual tem itens e será substituído pela venda suspensa. Continuar?",
                "Retomar venda", "Retomar", "Cancelar"):
            return
        self.nova_venda()
        for item in venda["itens"]:
            produto = produtos_mod.pegar(self.banco, item["produto_id"])
            if not produto:
                continue
            try:
                self.carrinho.adicionar(produto, float(item["quantidade"]), unidade=item["unidade"],
                                        preco_unitario=int(item["preco_unitario"]))
            except vendas_mod.ErroVenda as exc:
                dialogs.alerta(self, self.tema, f"Item '{item['nome']}' não pôde ser retomado:\n{exc}")
        if venda.get("cliente"):
            cliente = clientes_mod.pegar(self.banco, venda["cliente"]["id"])
            if cliente:
                self.definir_cliente(cliente)
        self.carrinho.desconto_valor = int(venda.get("desconto") or 0)
        self.carrinho.acrescimo = int(venda.get("acrescimo") or 0)
        if venda.get("vendedor"):
            self.carrinho.vendedor = venda["vendedor"]
        self.suspensas.pop(identificador, None)
        self._redesenhar()
        self._mensagem(f"Venda suspensa {identificador} retomada.")
        self.focar_principal()

    # ------------------------------------------------------------------ finalização
    def finalizar_venda(self):
        if not self.carrinho.itens:
            dialogs.alerta(self, self.tema, "O carrinho está vazio — bipe um produto para iniciar a venda.")
            self.focar_principal()
            return
        totais = self.carrinho.totais()
        if totais.total <= 0 and not self.config.get("venda_permite_preco_zero"):
            dialogs.alerta(self, self.tema, "O total da venda não pode ser zero.")
            return
        caixa = caixa_mod.caixa_aberto(self.banco)
        if not caixa and self.config.get("venda_exige_caixa_aberto"):
            if not dialogs.confirmar(self, self.tema,
                                     "O caixa está fechado e o sistema está configurado para exigir caixa aberto.\n\n"
                                     "Abrir o caixa agora com valor inicial zero?",
                                     "Caixa fechado", "Abrir caixa", "Cancelar"):
                return
            try:
                caixa_mod.abrir(self.banco, valor_abertura=0, observacao="Abertura automática pelo PDV",
                                autor=self.usuario)
            except caixa_mod.ErroCaixa as exc:
                dialogs.erro(self, self.tema, str(exc))
                return
            self._limpar_botao_abrir()
            self._verificar_caixa()
        dialogo = DialogoPagamento(self, self.tema, self.ctx, totais.total,
                                   cliente=self.carrinho.cliente, quantidade_itens=totais.quantidade_itens)
        resultado = dialogo.abrir()
        if not resultado:
            self.focar_principal()
            return
        try:
            venda = vendas_mod.finalizar(
                self.banco, self.carrinho, resultado["pagamentos"],
                cliente=self.carrinho.cliente, vendedor=self._vendedor_atual(),
                observacao=resultado.get("observacao", ""),
                vencimento_fiado=resultado.get("vencimento_fiado", ""),
                limite_desconto_pct=self.ctx.limite_desconto(),
            )
        except vendas_mod.ErroVenda as exc:
            dialogs.erro(self, self.tema, str(exc), "Venda não concluída")
            self.focar_principal()
            return
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro inesperado ao gravar a venda.")
            self.focar_principal()
            return
        self.ultima_venda = venda
        self.nova_venda()
        self._verificar_caixa()
        self.ctx.app.atualizar_caixa()
        self._mostrar_conclusao(venda)

    def _mostrar_conclusao(self, venda: dict):
        linhas = [
            f"Cupom nº {int(venda['numero']):06d} concluído!",
            f"Total: {formatar_dinheiro(int(venda['total']))}",
        ]
        if int(venda.get("troco") or 0) > 0:
            linhas.append(f"Troco: {formatar_dinheiro(int(venda['troco']))}")
        if int(venda.get("fiado") or 0) > 0:
            linhas.append(f"Lançado no fiado: {formatar_dinheiro(int(venda['fiado']))} (conta a receber gerada)")
        linhas.append(f"Cliente: {venda.get('cliente_nome', 'Consumidor final')}")
        resposta = dialogs.mensagem(self, self.tema, "Venda concluída", "\n".join(linhas), "sucesso",
                                    ("Imprimir recibo", "Nova venda"))
        if resposta == "Imprimir recibo":
            self.imprimir_recibo(int(venda["venda_id"]))
        self.focar_principal()

    # ------------------------------------------------------------------ recibo
    def imprimir_recibo(self, venda_id: int, largura: str = ""):
        try:
            caminho = impressao_mod.gerar_recibo_pdf(
                self.banco, venda_id,
                largura=largura or str(self.banco.config_pegar("recibo_largura", "80mm") or "80mm"),
            )
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Não foi possível gerar o recibo.")
            return
        from . import imprimir_documento

        imprimir_documento(self, self.tema, caminho, "Recibo não fiscal")
        self.focar_principal()

    def imprimir_ultima(self):
        if not self.ultima_venda:
            dialogs.alerta(self, self.tema, "Nenhuma venda concluída nesta sessão para reimprimir.")
            return
        self.imprimir_recibo(int(self.ultima_venda["venda_id"]))

    # ------------------------------------------------------------------ outros
    def mostrar_atalhos(self):
        from ... import configuracoes as config

        linhas = config.pdv_atalhos()
        texto = "\n".join(f"{item['teclas']:<28} {item['acao']}" for item in linhas)
        dialogs.mensagem(self, self.tema, "Atalhos do PDV", texto, "info", ("Fechar",))

    def carregar(self):
        """Recarrega configurações, caixa e o resumo do dia (chamado ao entrar na tela)."""
        self.config = config_mod.carregar(self.banco)
        self.carrinho.config = self._config_carrinho()
        self._limpar_botao_abrir()
        self._verificar_caixa()
        self._redesenhar()
        self.focar_principal()

    def ao_sair(self):
        if not self.carrinho.itens:
            return True
        resposta = dialogs.mensagem(
            self, self.tema, "Venda em andamento",
            f"O carrinho tem {self.carrinho.quantidade_itens} item(ns).\n\n"
            "O que deseja fazer antes de sair do PDV?",
            "pergunta", ("Suspender venda", "Manter no carrinho", "Limpar carrinho"),
        )
        if resposta == "Suspender venda":
            self.suspender_venda()
            return True
        if resposta == "Limpar carrinho":
            self.carrinho.limpar()
            self._redesenhar()
            return True
        if resposta == "Manter no carrinho":
            return True
        return False

    def receber_parametros(self, parametros: dict):
        """Recebe o foco vindo de outras telas (clientes, produtos, estoque...)."""
        parametros = parametros or {}
        if parametros.get("cliente_id"):
            cliente = clientes_mod.pegar(self.banco, parametros["cliente_id"])
            if cliente and int(cliente["ativo"] or 0):
                self.definir_cliente(cliente)
            elif cliente:
                dialogs.alerta(self, self.tema, f"O cliente “{cliente['nome']}” está desativado.")
        if parametros.get("produto_id"):
            produto = produtos_mod.pegar(self.banco, parametros["produto_id"])
            if produto:
                self._adicionar(produto)
        if parametros.get("codigo"):
            self.entrada_codigo.delete(0, "end")
            self.entrada_codigo.insert(0, str(parametros["codigo"]))
            self._ao_bipar()

    def atualizar_tema(self):
        self.tabela.atualizar_tema()
        for rotulo in list(self.rotulos.values()) + [self.rotulo_total, self.rotulo_itens, self.rotulo_lucro,
                                                      self.rotulo_dia]:
            try:
                rotulo.configure(background=self.tema.cor("bg_card"))
            except tk.TclError:
                continue
        self.rotulo_foto.configure(background=self.tema.cor("bg_alt"))
        self._verificar_caixa()
