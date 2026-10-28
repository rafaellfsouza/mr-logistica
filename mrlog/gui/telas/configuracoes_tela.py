"""
Tela de Configurações.

Reúne tudo o que o usuário pode ajustar sem tocar em arquivo nenhum:

* **Empresa e recibo** — dados que saem impressos nos recibos e comprovantes;
* **Aparência** — tema claro/escuro (aplicado na hora) e a tabela de atalhos;
* **Operação e PDV** — regras da venda (caixa aberto, preço zero, estoque
  negativo), bipador, alertas de estoque e validade, etiquetas por página;
* **Backup e dados** — backup automático, quantos manter, pasta de dados,
  compactação do banco (VACUUM);
* **Sobre e diagnóstico** — versão, esquema, bibliotecas e o checklist de saúde
  dos dados (saldos de estoque, produtos inconsistentes, duplicados...).

Tudo é gravado na tabela ``config`` do próprio banco SQLite (nada de arquivos
espalhados), e o botão "Restaurar padrões" volta às configurações de fábrica sem
apagar nenhum cadastro.
"""

from __future__ import annotations

import platform
import sys
import tkinter as tk
from tkinter import ttk

from ... import configuracoes as configuracoes_mod
from ... import impressao as impressao_mod
from ...caminhos import caminho_banco, pasta_backups, pasta_dados, pasta_fotos
from ...utils import formatar_data, hoje
from .. import dialogs
from ..tema import FONTE_PEQUENA, FONTE_SUBTITULO, FONTE_TITULO
from ..widgets import Cartao, QuadroRolavel, Tabela
from . import Tela

# --------------------------------------------------------------------------------------
# Descrição dos campos
# --------------------------------------------------------------------------------------

#: Cada entrada vira um widget na aba indicada e é gravada pela chave correspondente.
CAMPOS: list[dict] = [
    # --- empresa e recibo -----------------------------------------------------------
    {"chave": "empresa_nome", "aba": "empresa", "rotulo": "Nome da empresa / loja", "tipo": "texto",
     "dica": "Aparece no cabeçalho de recibos, relatórios e etiquetas.", "largura": 44},
    {"chave": "empresa_documento", "aba": "empresa", "rotulo": "CNPJ ou CPF", "tipo": "texto", "largura": 24},
    {"chave": "empresa_endereco", "aba": "empresa", "rotulo": "Endereço", "tipo": "texto", "largura": 44},
    {"chave": "empresa_telefone", "aba": "empresa", "rotulo": "Telefone", "tipo": "texto", "largura": 20},
    {"chave": "empresa_email", "aba": "empresa", "rotulo": "E-mail", "tipo": "texto", "largura": 32},
    {"chave": "recibo_titulo", "aba": "empresa", "rotulo": "Título do recibo não fiscal", "tipo": "texto",
     "largura": 44},
    {"chave": "recibo_mensagem", "aba": "empresa", "rotulo": "Mensagem de rodapé do recibo", "tipo": "texto",
     "dica": "Ex.: “Obrigado pela preferência! Volte sempre.”", "largura": 44},
    {"chave": "recibo_largura", "aba": "empresa", "rotulo": "Largura do papel da impressora", "tipo": "lista",
     "opcoes": ("58mm", "80mm", "A4"), "largura": 12},
    {"chave": "recibo_mostrar_endereco", "aba": "empresa", "rotulo": "Mostrar endereço da empresa no recibo",
     "tipo": "bool"},

    # --- operação e PDV -------------------------------------------------------------
    {"chave": "venda_exige_caixa_aberto", "aba": "operacao", "rotulo": "Exigir caixa aberto para vender",
     "tipo": "bool", "dica": "Se desligado, as vendas entram no caixa do dia automaticamente."},
    {"chave": "venda_permite_preco_zero", "aba": "operacao", "rotulo": "Permitir vender produto com preço zero",
     "tipo": "bool"},
    {"chave": "venda_permite_estoque_negativo", "aba": "operacao",
     "rotulo": "Permitir venda com estoque negativo", "tipo": "bool",
     "dica": "Útil quando o estoque físico ainda não foi lançado no sistema."},
    {"chave": "pdv_bipador_ativo", "aba": "operacao", "rotulo": "Leitor de código de barras (bipador) ativo",
     "tipo": "bool", "dica": "Mantém o foco no campo de código para bipar sem clicar."},
    {"chave": "pdv_confirmar_quantidade", "aba": "operacao",
     "rotulo": "Perguntar a quantidade a cada bipagem", "tipo": "bool"},
    {"chave": "alerta_estoque_ativo", "aba": "operacao", "rotulo": "Alertar produtos abaixo do estoque mínimo",
     "tipo": "bool"},
    {"chave": "alerta_validade_dias", "aba": "operacao", "rotulo": "Alertar lotes que vencem em até (dias)",
     "tipo": "int", "min": 1, "max": 365},
    {"chave": "etiquetas_por_pagina", "aba": "operacao", "rotulo": "Etiquetas por folha (padrão de impressão)",
     "tipo": "int", "min": 1, "max": 120},

    # --- backup ---------------------------------------------------------------------
    {"chave": "backup_automatico", "aba": "backup", "rotulo": "Backup automático ao abrir e ao fechar",
     "tipo": "bool"},
    {"chave": "manter_backups", "aba": "backup", "rotulo": "Manter os últimos (backups)", "tipo": "int",
     "min": 1, "max": 200, "dica": "Os mais antigos são apagados automaticamente."},
]

#: Abas da janela (ordem de exibição).
ABAS = (
    ("empresa", "Empresa e recibo"),
    ("aparencia", "Aparência e atalhos"),
    ("operacao", "Operação e PDV"),
    ("backup", "Backup e dados"),
    ("sobre", "Sobre e diagnóstico"),
)

#: Bibliotecas opcionais que o sistema usa (mostradas no diagnóstico).
BIBLIOTECAS = (("PIL", "Pillow — fotos e etiquetas"), ("openpyxl", "Excel (.xlsx)"),
               ("reportlab", "PDF — recibos, relatórios e etiquetas"))


def _versao_biblioteca(nome: str) -> str:
    try:
        modulo = __import__(nome)
    except ImportError:
        return "ausente"
    versao = getattr(modulo, "__version__", "")
    if not versao:
        versao = getattr(getattr(modulo, "PIL", modulo), "__version__", "")
    return str(versao or "instalada")


class ConfiguracoesTela(Tela):
    """Preferências do sistema, dados da empresa, backup e diagnóstico."""

    titulo = "Configurações"
    descricao = "Dados da empresa, recibo, tema, regras de venda, bipador, alertas, backup e diagnóstico dos dados."

    def __init__(self, mestre, ctx):
        super().__init__(mestre, ctx)
        self._vars: dict[str, tk.Variable] = {}
        self._rotulos_info: dict[str, ttk.Label] = {}
        self.var_tema = tk.StringVar(value="claro")
        self._montar_barra(
            [
                ("💾 Salvar alterações", self.salvar, "Primario.TButton", "Ctrl+S"),
                ("↺ Restaurar padrões", self.restaurar_padrao, "TButton"),
                ("🩺 Diagnóstico dos dados", self.diagnostico, "TButton"),
                ("⟳ Recarregar", self.carregar, "TButton", "Ctrl+R"),
            ],
            lado_direito=[("💾 Ir para Backup", self.ir_para_backup, "TButton"),
                          ("📁 Abrir pasta de dados", self.abrir_pasta_dados, "TButton")],
        )
        self._montar_interface()
        self._registrar_teclas()

    # ------------------------------------------------------------------ interface
    def _montar_interface(self):
        self.corpo.rowconfigure(0, weight=1)
        self.abas = ttk.Notebook(self.corpo)
        self.abas.grid(row=0, column=0, sticky="nsew")
        self._abas: dict[str, ttk.Frame] = {}
        for chave, rotulo in ABAS:
            quadro = QuadroRolavel(self.abas, self.tema)
            self.abas.add(quadro, text=f"  {rotulo}  ")
            conteudo = quadro.quadro
            conteudo.columnconfigure(0, weight=1)
            self._abas[chave] = conteudo
        self._montar_empresa()
        self._montar_aparencia()
        self._montar_operacao()
        self._montar_backup()
        self._montar_sobre()

    def _titulo_secao(self, pai, texto: str, linha: int):
        ttk.Label(pai, text=texto, style="TLabel", font=FONTE_SUBTITULO).grid(
            row=linha, column=0, sticky="w", pady=(12, 4))
        ttk.Separator(pai, orient="horizontal").grid(row=linha + 1, column=0, sticky="ew", pady=(0, 6))
        return linha + 2

    def _criar_campo(self, pai, especificacao: dict, linha: int) -> int:
        chave = especificacao["chave"]
        tipo = especificacao["tipo"]
        if tipo == "bool":
            # opção liga/desliga: o próprio rótulo vira o texto da caixa de seleção
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(pai, text=especificacao["rotulo"], variable=var,
                            style="TCheckbutton").grid(row=linha, column=0, sticky="w")
            self._vars[especificacao["chave"]] = var
            linha += 1
            if especificacao.get("dica"):
                ttk.Label(pai, text=especificacao["dica"], style="Suave.TLabel", wraplength=760,
                          justify="left").grid(row=linha, column=0, sticky="w", padx=(22, 0))
                linha += 1
            return linha + 1

        ttk.Label(pai, text=especificacao["rotulo"], style="TLabel", font=FONTE_PEQUENA).grid(
            row=linha, column=0, sticky="w")
        linha += 1
        if tipo == "int":
            var = tk.StringVar(value="0")
            ttk.Spinbox(pai, textvariable=var, from_=especificacao.get("min", 0),
                        to=especificacao.get("max", 999), width=8).grid(row=linha, column=0, sticky="w")
        elif tipo == "lista":
            var = tk.StringVar(value="")
            ttk.Combobox(pai, textvariable=var, values=list(especificacao.get("opcoes") or ()),
                         state="readonly", width=especificacao.get("largura", 20)).grid(
                row=linha, column=0, sticky="w")
        else:
            var = tk.StringVar(value="")
            ttk.Entry(pai, textvariable=var, width=especificacao.get("largura", 40)).grid(
                row=linha, column=0, sticky="w")
        self._vars[chave] = var
        linha += 1
        if especificacao.get("dica"):
            ttk.Label(pai, text=especificacao["dica"], style="Suave.TLabel", wraplength=760,
                      justify="left").grid(row=linha, column=0, sticky="w")
            linha += 1
        return linha + 1

    def _montar_empresa(self):
        pai = self._abas["empresa"]
        linha = self._titulo_secao(pai, "Dados da empresa (saem nos documentos impressos)", 0)
        for especificacao in CAMPOS:
            if especificacao["aba"] == "empresa":
                linha = self._criar_campo(pai, especificacao, linha)
        aviso = ttk.Label(pai, text="Esses dados aparecem no recibo não fiscal, nos comprovantes de "
                                    "contas a receber/pagar e nos relatórios em PDF.",
                          style="Suave.TLabel", wraplength=760, justify="left")
        aviso.grid(row=linha, column=0, sticky="w", pady=(6, 0))

    def _montar_aparencia(self):
        pai = self._abas["aparencia"]
        linha = self._titulo_secao(pai, "Tema da interface", 0)
        quadro = ttk.Frame(pai, style="TFrame")
        quadro.grid(row=linha, column=0, sticky="w")
        ttk.Radiobutton(quadro, text="Claro", value="claro", variable=self.var_tema,
                        style="TRadiobutton", command=self._aplicar_tema).pack(side="left")
        ttk.Radiobutton(quadro, text="Escuro", value="escuro", variable=self.var_tema,
                        style="TRadiobutton", command=self._aplicar_tema).pack(side="left", padx=(16, 0))
        ttk.Label(pai, text="O tema é aplicado imediatamente e fica gravado para as próximas aberturas "
                            "(atalho: Ctrl+T).", style="Suave.TLabel", wraplength=760,
                  justify="left").grid(row=linha + 1, column=0, sticky="w", pady=(4, 0))

        linha = self._titulo_secao(pai, "Atalhos de teclado", linha + 3)
        seletor = ttk.Frame(pai, style="TFrame")
        seletor.grid(row=linha, column=0, sticky="w")
        self.var_grupo_atalhos = tk.StringVar(value="Atalhos gerais")
        ttk.Combobox(seletor, textvariable=self.var_grupo_atalhos, state="readonly", width=24,
                     values=("Atalhos gerais", "Atalhos do PDV (venda)")).pack(side="left")
        self.var_grupo_atalhos.trace_add("write", lambda *_a: self._carregar_atalhos())

        self.tabela_atalhos = Tabela(
            pai, self.tema,
            [{"chave": "teclas", "rotulo": "Teclas", "largura": 190},
             {"chave": "acao", "rotulo": "Ação", "largura": 460}],
            mostrar_busca=False, altura=16,
        )
        self.tabela_atalhos.grid(row=linha + 1, column=0, sticky="ew", pady=(8, 0))

    def _montar_operacao(self):
        pai = self._abas["operacao"]
        linha = self._titulo_secao(pai, "Regras da venda e do PDV", 0)
        for especificacao in CAMPOS:
            if especificacao["aba"] == "operacao":
                linha = self._criar_campo(pai, especificacao, linha)

    def _montar_backup(self):
        pai = self._abas["backup"]
        linha = self._titulo_secao(pai, "Backup automático", 0)
        for especificacao in CAMPOS:
            if especificacao["aba"] == "backup":
                linha = self._criar_campo(pai, especificacao, linha)

        linha = self._titulo_secao(pai, "Onde os dados ficam guardados", linha)
        self.cartoes_dados = {}
        quadro = ttk.Frame(pai, style="TFrame")
        quadro.grid(row=linha, column=0, sticky="ew")
        for indice, chave in enumerate(("banco", "pasta", "backups")):
            quadro.columnconfigure(indice, weight=1)
            cartao = Cartao(quadro, self.tema, "", "—", "", cor="info", largura_minima=220)
            cartao.grid(row=0, column=indice, sticky="ew", padx=(0, 8))
            self.cartoes_dados[chave] = cartao
        linha += 1
        ttk.Button(pai, text="🧹 Compactar banco de dados (libera espaço)",
                   command=self.compactar).grid(row=linha, column=0, sticky="w", pady=(8, 0))
        linha += 1
        ttk.Button(pai, text="💾 Abrir tela de backup e restauração",
                   command=self.ir_para_backup).grid(row=linha, column=0, sticky="w", pady=(6, 0))

    def _montar_sobre(self):
        pai = self._abas["sobre"]
        ttk.Label(pai, text="MR Logística", style="Titulo.TLabel", font=FONTE_TITULO).grid(
            row=0, column=0, sticky="w", pady=(12, 0))
        self.rotulo_versao = ttk.Label(pai, text="", style="Suave.TLabel", wraplength=760, justify="left")
        self.rotulo_versao.grid(row=1, column=0, sticky="w", pady=(2, 8))

        self.quadro_sistema = ttk.Frame(pai, style="TFrame", padding=10)
        self.quadro_sistema.grid(row=2, column=0, sticky="ew")
        self.quadro_sistema.columnconfigure(1, weight=1)

        linha = self._titulo_secao(pai, "Diagnóstico dos dados", 3)
        ttk.Label(pai, text="Verifica integridade do banco, saldos de estoque, produtos inconsistentes, "
                            "nomes duplicados e códigos de barras pendentes.",
                  style="Suave.TLabel", wraplength=760, justify="left").grid(row=linha, column=0, sticky="w")
        ttk.Button(pai, text="🩺 Executar diagnóstico agora", style="Primario.TButton",
                   command=self.diagnostico).grid(row=linha + 1, column=0, sticky="w", pady=(8, 0))
        self.texto_diagnostico = tk.Text(pai, width=96, height=12, wrap="word", borderwidth=0,
                                         font=FONTE_PEQUENA, background=self.tema.cor("bg_card"),
                                         foreground=self.tema.cor("fg"), state="disabled")
        self.texto_diagnostico.grid(row=linha + 2, column=0, sticky="ew", pady=(8, 0))
        self.tema.registrar(self.texto_diagnostico, background="bg_card", foreground="fg")

    def _registrar_teclas(self):
        for sequencia, comando in (
            ("<Control-s>", self.salvar),
            ("<Control-S>", self.salvar),
            ("<Control-r>", self.carregar),
            ("<Control-R>", self.carregar),
        ):
            self.bind(sequencia, lambda _e, c=comando: (c(), "break")[1])

    # ------------------------------------------------------------------ carga
    def carregar(self):
        configuracao = configuracoes_mod.carregar(self.banco)
        for especificacao in CAMPOS:
            chave = especificacao["chave"]
            var = self._vars.get(chave)
            if var is None:
                continue
            valor = configuracao.get(chave)
            if especificacao["tipo"] == "bool":
                var.set(bool(valor))
            elif especificacao["tipo"] == "int":
                var.set(str(int(valor or 0)))
            else:
                var.set("" if valor is None else str(valor))
        self.var_tema.set(str(configuracao.get("tema") or "claro"))
        self._carregar_atalhos()
        self._atualizar_informacoes()

    def _carregar_atalhos(self):
        grupo = self.var_grupo_atalhos.get()
        atalhos = configuracoes_mod.pdv_atalhos() if grupo.startswith("Atalhos do PDV") \
            else configuracoes_mod.atalhos_de_teclado()
        self.tabela_atalhos.carregar([dict(a) for a in atalhos], resumo=f"{len(atalhos)} atalho(s)")

    def _atualizar_informacoes(self):
        try:
            info = configuracoes_mod.informacoes_sistema(self.banco)
        except Exception:
            info = {}
        versao = info.get("versao", "?")
        self.rotulo_versao.configure(
            text=f"Versão {versao} • esquema do banco v{info.get('versao_esquema', '?')} • "
                 f"{info.get('tabelas', 0)} tabelas\n"
                 f"Python {sys.version.split()[0]} ({platform.system()} {platform.release()}) • "
                 f"Tkinter {tk.TkVersion}\n"
                 f"Bibliotecas: " + " • ".join(f"{nome} {_versao_biblioteca(nome)}"
                                              for nome, _descricao in BIBLIOTECAS)
        )
        for filho in self.quadro_sistema.winfo_children():
            filho.destroy()
        self.quadro_sistema.columnconfigure(1, weight=1)
        integridade = info.get("integridade")
        if isinstance(integridade, (tuple, list)):
            texto_integridade = "OK" if integridade[0] else f"FALHOU — {integridade[1]}"
        else:
            texto_integridade = str(integridade or "—")
        pares = [
            ("Banco de dados", info.get("banco", str(caminho_banco()))),
            ("Pasta de dados", info.get("pasta_dados", str(pasta_dados()))),
            ("Pasta de backups", info.get("pasta_backups", str(pasta_backups()))),
            ("Tamanho do banco", info.get("tamanho_banco", "—")),
            ("Backups guardados", str(info.get("qtd_backups", 0))),
            ("Fotos de produtos", str(info.get("qtd_fotos", 0))),
            ("Integridade do banco", texto_integridade),
            ("Dados salvos em", f"{formatar_data(hoje())} — tudo local, sem internet"),
        ]
        for indice, (rotulo, valor) in enumerate(pares):
            ttk.Label(self.quadro_sistema, text=f"{rotulo}:", style="Suave.TLabel").grid(
                row=indice, column=0, sticky="nw", padx=(0, 10), pady=2)
            ttk.Label(self.quadro_sistema, text=str(valor), style="TLabel", wraplength=620,
                      justify="left").grid(row=indice, column=1, sticky="w", pady=2)
        if hasattr(self, "cartoes_dados"):
            self.cartoes_dados["banco"].definir("Banco de dados", info.get("tamanho_banco", "—"),
                                                str(info.get("banco", caminho_banco())), cor="info")
            self.cartoes_dados["pasta"].definir("Fotos de produtos", str(info.get("qtd_fotos", 0)),
                                                str(pasta_fotos()), cor="neutro")
            self.cartoes_dados["backups"].definir("Backups", str(info.get("qtd_backups", 0)),
                                                  str(pasta_backups()),
                                                  cor="sucesso" if info.get("qtd_backups") else "alerta")

    # ------------------------------------------------------------------ tema
    def _aplicar_tema(self):
        nome = self.var_tema.get()
        if nome == self.tema.nome:
            return
        try:
            configuracoes_mod.salvar(self.banco, {"tema": nome}, autor=self.usuario)
        except configuracoes_mod.ErroConfiguracao:
            pass
        self.ctx.app.alternar_tema(nome)
        self.status(f"Tema {nome} aplicado.")

    # ------------------------------------------------------------------ valores / gravação
    def valores(self) -> dict:
        """Lê os widgets e devolve o dicionário pronto para ``configuracoes.salvar``."""
        resultado: dict = {}
        for especificacao in CAMPOS:
            chave = especificacao["chave"]
            var = self._vars.get(chave)
            if var is None:
                continue
            if especificacao["tipo"] == "bool":
                resultado[chave] = bool(var.get())
            elif especificacao["tipo"] == "int":
                try:
                    numero = int(float(var.get() or 0))
                except ValueError:
                    numero = int(especificacao.get("min") or 0)
                resultado[chave] = max(int(especificacao.get("min") or 0),
                                       min(numero, int(especificacao.get("max") or numero)))
                var.set(str(resultado[chave]))
            else:
                resultado[chave] = str(var.get()).strip()
                if especificacao.get("obrigatorio") and not resultado[chave]:
                    raise configuracoes_mod.ErroConfiguracao(
                        f"O campo “{especificacao['rotulo']}” não pode ficar vazio.")
        resultado["tema"] = self.var_tema.get()
        return resultado

    def salvar(self):
        try:
            valores = self.valores()
            salvos = configuracoes_mod.salvar(self.banco, valores, autor=self.usuario)
        except configuracoes_mod.ErroConfiguracao as exc:
            dialogs.erro(self, self.tema, str(exc), "Configurações")
            return False
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao salvar as configurações.")
            return False
        self._aplicar_tema()
        self._atualizar_informacoes()
        dialogs.sucesso(self, self.tema, f"{len(salvos)} configuração(ões) salva(s).\n\n"
                                         "As mudanças valem imediatamente para todas as telas.",
                        "Configurações salvas")
        self.status("Configurações salvas.")
        return True

    def restaurar_padrao(self):
        if not dialogs.confirmar(self, self.tema,
                                 "Voltar todas as configurações ao padrão de fábrica?\n\n"
                                 "Nenhum cadastro (produtos, clientes, vendas...) é apagado — apenas as "
                                 "preferências, os dados da empresa e as regras de venda.",
                                 "Restaurar padrões", "Restaurar", "Cancelar"):
            return False
        try:
            configuracoes_mod.restaurar_padrao(self.banco, autor=self.usuario)
        except Exception as exc:
            self.ctx.avisar_erro(exc, "Erro ao restaurar as configurações padrão.")
            return False
        self.carregar()
        self._aplicar_tema()
        dialogs.sucesso(self, self.tema, "Configurações restauradas ao padrão de fábrica.")
        return True

    # ------------------------------------------------------------------ manutenção
    def diagnostico(self):
        dialogo = dialogs.progresso(self.ctx.janela, self.tema, "Diagnóstico",
                                    "Verificando banco, estoque e cadastros...")
        try:
            linhas = configuracoes_mod.diagnostico(self.banco)
        except Exception as exc:
            dialogs.finalizar_progresso(dialogo)
            self.ctx.avisar_erro(exc, "Erro ao executar o diagnóstico.")
            return []
        dialogs.finalizar_progresso(dialogo)
        self.texto_diagnostico.configure(state="normal")
        self.texto_diagnostico.delete("1.0", "end")
        for linha in linhas:
            self.texto_diagnostico.insert("end", f"• {linha}\n")
        self.texto_diagnostico.configure(state="disabled", background=self.tema.cor("bg_card"),
                                         foreground=self.tema.cor("fg"))
        self._atualizar_informacoes()
        dialogs.mensagem(self.ctx.janela, self.tema, "Diagnóstico concluído",
                         "\n".join(f"• {l}" for l in linhas), "info", ("OK",))
        return linhas

    def compactar(self):
        if not dialogs.confirmar(self, self.tema,
                                 "Compactar o banco de dados (VACUUM)?\n\n"
                                 "O arquivo é reescrito para ocupar menos espaço. Leva alguns segundos e "
                                 "é recomendável ter um backup recente.", "Compactar banco", "Compactar",
                                 "Cancelar"):
            return False
        dialogo = dialogs.progresso(self.ctx.janela, self.tema, "Compactando", "Reescrevendo o banco...")
        try:
            self.banco.compactar()
        except Exception as exc:
            dialogs.finalizar_progresso(dialogo)
            self.ctx.avisar_erro(exc, "Erro ao compactar o banco.")
            return False
        dialogs.finalizar_progresso(dialogo)
        self._atualizar_informacoes()
        dialogs.sucesso(self, self.tema, "Banco compactado com sucesso.")
        return True

    def abrir_pasta_dados(self):
        impressao_mod.abrir_pasta(pasta_dados())
        self.status(f"Pasta de dados: {pasta_dados()}")

    def ir_para_backup(self):
        self.ctx.navegar("backup")

    # ------------------------------------------------------------------ integração
    def focar_busca(self):
        self.abas.focus()

    def atualizar_tema(self):
        self.tabela_atalhos.atualizar_tema()
        for cartao in getattr(self, "cartoes_dados", {}).values():
            cartao.atualizar_tema()
        if hasattr(self, "texto_diagnostico"):
            self.texto_diagnostico.configure(background=self.tema.cor("bg_card"),
                                             foreground=self.tema.cor("fg"))

    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        self.carregar()
        aba = str(parametros.get("aba") or "")
        for indice, (chave, _rotulo) in enumerate(ABAS):
            if chave == aba:
                self.abas.select(indice)
                break
