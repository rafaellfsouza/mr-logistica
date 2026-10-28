"""
Painel (dashboard) — visão geral do negócio em uma tela.

Mostra cartões com os principais indicadores, gráfico de vendas dos últimos dias,
produtos mais vendidos, últimas vendas e alertas que exigem atenção. Todos os
cartões e alertas são clicáveis e levam direto para a tela relacionada.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ... import painel as painel_mod
from ... import produtos as produtos_mod
from ... import vendas as vendas_mod
from ...utils import formatar_data, formatar_dinheiro, formatar_quantidade, hoje
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO, FONTE_VALOR
from ..widgets import Cartao, EtiquetaEstado, Tabela, QuadroRolavel, grafico_barras
from . import Tela

#: nomes usados pelo núcleo -> id da tela no menu lateral
MAPA_TELAS = {
    "painel": "painel",
    "pdv": "pdv",
    "vendas": "vendas",
    "caixa": "caixa",
    "produtos": "produtos",
    "estoque": "estoque",
    "estoque_baixo": "estoque",
    "lotes": "lotes",
    "contas_receber": "contas_receber",
    "contas_pagar": "contas_pagar",
    "clientes": "clientes",
    "fornecedores": "fornecedores",
    "relatorios": "relatorios",
    "etiquetas": "etiquetas",
    "backup": "backup",
    "configuracoes": "configuracoes",
    "usuarios": "usuarios",
}

CORES_NIVEL = {"critico": "perigo", "atencao": "alerta", "info": "info", "ok": "sucesso"}


class PainelTela(Tela):
    titulo = "Painel"
    descricao = "Indicadores do dia, alertas e atalhos para as principais rotinas."

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self.dados: dict = {}
        self._cartoes: list[Cartao] = []
        self._grafico = None
        self._montar_interface()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.rolavel = QuadroRolavel(self.corpo, self.tema)
        self.rolavel.grid(row=0, column=0, sticky="nsew")
        quadro = self.rolavel.quadro

        # --- saudação + ações rápidas
        topo = tk.Frame(quadro, background=self.tema.cor("bg"))
        topo.pack(fill="x", pady=(0, 8))
        self.rotulo_saudacao = tk.Label(topo, text="", font=FONTE_TITULO, background=self.tema.cor("bg"),
                                        foreground=self.tema.cor("fg"), anchor="w")
        self.rotulo_saudacao.pack(side="left")
        acoes = tk.Frame(topo, background=self.tema.cor("bg"))
        acoes.pack(side="right")
        for texto, comando, estilo in (
            ("🛒 Nova venda (F2)", lambda: self.ctx.navegar("pdv"), "Primario.TButton"),
            ("📦 Produtos", lambda: self.ctx.navegar("produtos"), "TButton"),
            ("💵 Caixa", lambda: self.ctx.navegar("caixa"), "TButton"),
            ("📈 Relatórios", lambda: self.ctx.navegar("relatorios"), "TButton"),
            ("⟳ Atualizar", self.carregar, "TButton"),
        ):
            ttk.Button(acoes, text=texto, command=comando, style=estilo).pack(side="left", padx=(6, 0))

        # --- cartões de indicadores
        self.quadro_cartoes = tk.Frame(quadro, background=self.tema.cor("bg"))
        self.quadro_cartoes.pack(fill="x")

        # --- gráfico + alertas
        meio = tk.Frame(quadro, background=self.tema.cor("bg"))
        meio.pack(fill="x", pady=(12, 0))
        meio.columnconfigure(0, weight=3)
        meio.columnconfigure(1, weight=2)

        cartao_grafico = tk.Frame(meio, background=self.tema.cor("bg_card"), highlightbackground=self.tema.cor("borda"),
                                  highlightthickness=1)
        cartao_grafico.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.titulo_grafico = tk.Label(cartao_grafico, text="Vendas dos últimos 14 dias", font=FONTE_SUBTITULO,
                                       background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"), anchor="w")
        self.titulo_grafico.pack(fill="x", padx=10, pady=(8, 0))
        self.quadro_grafico = tk.Frame(cartao_grafico, background=self.tema.cor("bg_card"))
        self.quadro_grafico.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        cartao_alertas = tk.Frame(meio, background=self.tema.cor("bg_card"), highlightbackground=self.tema.cor("borda"),
                                  highlightthickness=1)
        cartao_alertas.grid(row=0, column=1, sticky="nsew")
        tk.Label(cartao_alertas, text="Alertas", font=FONTE_SUBTITULO, background=self.tema.cor("bg_card"),
                 foreground=self.tema.cor("fg"), anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        self.quadro_alertas = tk.Frame(cartao_alertas, background=self.tema.cor("bg_card"))
        self.quadro_alertas.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # --- tabelas inferiores
        inferior = tk.Frame(quadro, background=self.tema.cor("bg"))
        inferior.pack(fill="x", pady=(12, 0))
        inferior.columnconfigure(0, weight=1)
        inferior.columnconfigure(1, weight=1)

        esquerda = tk.Frame(inferior, background=self.tema.cor("bg"))
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Label(esquerda, text="Produtos mais vendidos (30 dias)", font=FONTE_SUBTITULO,
                 background=self.tema.cor("bg"), foreground=self.tema.cor("fg"), anchor="w").pack(fill="x")
        self.tabela_top = Tabela(
            esquerda, self.tema,
            [{"chave": "posicao", "rotulo": "#", "largura": 40, "tipo": "inteiro", "alinhamento": "centro"},
             {"chave": "nome", "rotulo": "Produto", "largura": 240},
             {"chave": "quantidade", "rotulo": "Qtd", "largura": 80, "tipo": "quantidade"},
             {"chave": "unidade", "rotulo": "Un.", "largura": 50, "alinhamento": "centro"},
             {"chave": "total", "rotulo": "Faturamento", "largura": 110, "tipo": "dinheiro"},
             {"chave": "lucro", "rotulo": "Lucro", "largura": 100, "tipo": "dinheiro"}],
            ao_duplo_clique=lambda linha: self.ctx.navegar("produtos", {"termo": linha["nome"]}),
            mostrar_busca=False, altura=8,
        )
        self.tabela_top.pack(fill="both", expand=True)

        direita = tk.Frame(inferior, background=self.tema.cor("bg"))
        direita.grid(row=0, column=1, sticky="nsew")
        tk.Label(direita, text="Últimas vendas", font=FONTE_SUBTITULO, background=self.tema.cor("bg"),
                 foreground=self.tema.cor("fg"), anchor="w").pack(fill="x")
        self.tabela_vendas = Tabela(
            direita, self.tema,
            [{"chave": "numero", "rotulo": "Nº", "largura": 60, "tipo": "inteiro"},
             {"chave": "hora", "rotulo": "Hora", "largura": 60, "alinhamento": "centro"},
             {"chave": "cliente", "rotulo": "Cliente", "largura": 180},
             {"chave": "formas", "rotulo": "Pagamento", "largura": 130},
             {"chave": "total", "rotulo": "Total", "largura": 100, "tipo": "dinheiro"},
             {"chave": "status_texto", "rotulo": "Situação", "largura": 110, "alinhamento": "centro"}],
            ao_duplo_clique=self._abrir_venda,
            mostrar_busca=False, altura=8,
        )
        self.tabela_vendas.pack(fill="both", expand=True)

        rodape = tk.Frame(quadro, background=self.tema.cor("bg"))
        rodape.pack(fill="x", pady=(12, 4))
        self.rotulo_resumo = tk.Label(rodape, text="", font=FONTE_PEQUENA, background=self.tema.cor("bg"),
                                      foreground=self.tema.cor("fg_suave"), justify="left", anchor="w")
        self.rotulo_resumo.pack(fill="x")

    # ------------------------------------------------------------------ dados
    def carregar(self):
        try:
            self.dados = painel_mod.indicadores(self.banco)
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao montar o painel.")
            return
        self._desenhar_cartoes()
        self._desenhar_grafico()
        self._desenhar_alertas()
        self._preencher_tabelas()
        self._preencher_resumo()
        self.ctx.app.atualizar_caixa()
        self.status(f"Painel atualizado em {formatar_data(hoje(), com_hora=True)[:16]}.")

    def _saudacao(self) -> str:
        from datetime import datetime

        hora = datetime.now().hour
        periodo = "Bom dia" if hora < 12 else ("Boa tarde" if hora < 18 else "Boa noite")
        nome = str(self.usuario["nome"]).split()[0] if self.usuario else ""
        return f"{periodo}, {nome}!" if nome else f"{periodo}!"

    def _desenhar_cartoes(self):
        for filho in self.quadro_cartoes.winfo_children():
            filho.destroy()
        self._cartoes.clear()
        self.rotulo_saudacao.configure(text=self._saudacao(), background=self.tema.cor("bg"),
                                       foreground=self.tema.cor("fg"))
        cartoes = painel_mod.cartoes(self.banco)
        for indice, dados in enumerate(cartoes):
            cor = dados.get("cor", "info")
            cor = {"atencao": "alerta"}.get(cor, cor)
            tela_alvo = MAPA_TELAS.get(str(dados.get("tela", "")), "")
            cartao = Cartao(
                self.quadro_cartoes, self.tema,
                titulo=dados["titulo"], valor=dados["valor"], detalhe=dados.get("detalhe", ""),
                cor=cor, largura_minima=210,
                ao_clicar=(lambda t=tela_alvo: self.ctx.navegar(t)) if tela_alvo else None,
            )
            cartao.grid(row=indice // 4, column=indice % 4, sticky="nsew", padx=(0, 10), pady=(0, 10))
            self.quadro_cartoes.columnconfigure(indice % 4, weight=1)
            self._cartoes.append(cartao)

    def _desenhar_grafico(self):
        for filho in self.quadro_grafico.winfo_children():
            filho.destroy()
        serie = self.dados.get("serie_vendas", [])
        valores = [item["total"] for item in serie]
        rotulos = [item["rotulo"] for item in serie]
        self._grafico = grafico_barras(
            self.quadro_grafico, self.tema, valores, rotulos,
            titulo="", altura=180, cor="grafico",
            formatador=lambda v: formatar_dinheiro(int(v), simbolo=False),
        )
        total = sum(valores)
        self.titulo_grafico.configure(
            text=f"Vendas dos últimos {len(serie)} dias — total {formatar_dinheiro(total)}",
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
        )

    def _desenhar_alertas(self):
        for filho in self.quadro_alertas.winfo_children():
            filho.destroy()
        alertas = self.dados.get("alertas", [])
        if not alertas:
            tk.Label(self.quadro_alertas, text="✔ Nada pendente. Tudo em ordem!", font=FONTE_PEQUENA,
                     background=self.tema.cor("bg_card"), foreground=self.tema.cor("sucesso"),
                     anchor="w", justify="left").pack(fill="x", pady=4)
            return
        for alerta in alertas[:8]:
            cor = CORES_NIVEL.get(alerta.get("nivel", "info"), "info")
            quadro = tk.Frame(self.quadro_alertas, background=self.tema.cor(f"{cor}_bg"), cursor="hand2")
            quadro.pack(fill="x", pady=2)
            rotulo = tk.Label(quadro, text=f"● {alerta['titulo']}", font=("Segoe UI", 9, "bold"), anchor="w",
                              background=self.tema.cor(f"{cor}_bg"), foreground=self.tema.cor(cor))
            rotulo.pack(fill="x", padx=8, pady=(4, 0))
            texto = tk.Label(quadro, text=alerta.get("texto", ""), font=FONTE_PEQUENA, anchor="w", justify="left",
                             wraplength=340, background=self.tema.cor(f"{cor}_bg"), foreground=self.tema.cor("fg"))
            texto.pack(fill="x", padx=8, pady=(0, 4))
            tela_alvo = MAPA_TELAS.get(str(alerta.get("tela", "")), "")
            if tela_alvo:
                for widget in (quadro, rotulo, texto):
                    widget.bind("<Button-1>", lambda e, t=tela_alvo: self.ctx.navegar(t))

    def _preencher_tabelas(self):
        top = []
        for indice, item in enumerate(self.dados.get("top_produtos", []), start=1):
            top.append({**item, "posicao": indice})
        self.tabela_top.carregar(top, resumo="" if top else "Nenhuma venda nos últimos 30 dias.")

        vendas = []
        rotulos = {
            "concluida": "Concluída", "parcialmente_devolvida": "Devolvida (parcial)",
            "devolvida": "Devolvida", "cancelada": "Cancelada",
        }
        for item in self.dados.get("ultimas_vendas", []):
            linha = dict(item)
            linha["status_texto"] = rotulos.get(linha.get("status"), linha.get("status", ""))
            linha["_tag"] = "perigo" if linha.get("status") == "cancelada" else ""
            vendas.append(linha)
        self.tabela_vendas.carregar(vendas, resumo="" if vendas else "Nenhuma venda nos últimos 7 dias.")

    def _preencher_resumo(self):
        linhas = painel_mod.texto_resumo(self.banco)
        self.rotulo_resumo.configure(text="\n".join(linhas), background=self.tema.cor("bg"),
                                     foreground=self.tema.cor("fg_suave"))

    def _abrir_venda(self, linha: dict):
        self.ctx.navegar("vendas", {"venda_id": linha["id"]})

    # ------------------------------------------------------------------ interações
    def focar_busca(self):
        self.tabela_vendas.focar_busca()

    def atualizar_tema(self):
        for widget in (self.rotulo_saudacao, self.rotulo_resumo, self.titulo_grafico):
            try:
                widget.configure(background=self.tema.cor("bg" if widget is not self.titulo_grafico else "bg_card"),
                                 foreground=self.tema.cor("fg" if widget is not self.rotulo_resumo else "fg_suave"))
            except tk.TclError:
                continue
        for quadro in (self.quadro_cartoes, self.rolavel.quadro):
            try:
                quadro.configure(background=self.tema.cor("bg"))
            except tk.TclError:
                continue
        for cartao in self._cartoes:
            cartao.atualizar_tema()
        self.tabela_top.atualizar_tema()
        self.tabela_vendas.atualizar_tema()
        self.carregar()

    def ao_tecla(self, tecla: str) -> bool:
        return False
