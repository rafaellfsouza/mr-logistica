"""
Diálogos (janelas modais) usados em todo o sistema: avisos, confirmações,
formulários rápidos, seleção de registros, motivos de cancelamento etc.

Todos devolvem o resultado diretamente (``None`` quando o usuário cancela), o que
deixa o código das telas curto e legível.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Sequence

from ..utils import formatar_dinheiro
from .tema import FONTE_BASE, FONTE_PEQUENA, FONTE_SUBTITULO, Tema
from .widgets import (
    CampoData,
    CampoDinheiro,
    CampoLista,
    CampoMarcar,
    CampoQuantidade,
    CampoTexto,
    Tabela,
    formatar_valor,
)


# --------------------------------------------------------------------------------------
# Modo de teste automatizado
# --------------------------------------------------------------------------------------

#: Quando ``True`` (definido pelos testes automatizados), nenhum diálogo é exibido:
#: as funções devolvem respostas seguras e registram as mensagens em ``LOG_TESTE``.
#: Assim é possível testar o fluxo completo das telas sem travar em janelas modais.
MODO_TESTE = False
LOG_TESTE: list[str] = []
#: resposta devolvida por :func:`confirmar` em modo de teste (nunca confirma por padrão)
RESPOSTA_CONFIRMAR = False


def ativar_modo_teste(confirmar_padrao: bool = False) -> None:
    global MODO_TESTE, RESPOSTA_CONFIRMAR
    MODO_TESTE = True
    RESPOSTA_CONFIRMAR = bool(confirmar_padrao)
    LOG_TESTE.clear()


def desativar_modo_teste() -> None:
    global MODO_TESTE
    MODO_TESTE = False


def _registrar(tipo: str, texto: str) -> None:
    LOG_TESTE.append(f"[{tipo}] {texto}")
    print(f"      [{tipo}] {str(texto).splitlines()[0][:160]}", flush=True)


# --------------------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------------------


class Modal(tk.Toplevel):
    """Janela modal padrão do sistema (centralizada, sem redimensionar solto)."""

    def __init__(self, mestre, tema: Tema, titulo: str, largura: int = 460, altura: int = 0, redimensionavel: bool = True):
        super().__init__(mestre)
        self.tema = tema
        self.title(titulo)
        self.configure(background=tema.cor("bg"))
        self.resizable(redimensionavel, redimensionavel)
        self.transient(mestre.winfo_toplevel() if isinstance(mestre, tk.Widget) else mestre)
        self.resultado: Any = None
        self._fechada = False
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.cancelar)
        self.bind("<Escape>", lambda e: self.cancelar())
        self._largura = largura
        self._altura = altura
        self._corpo = ttk.Frame(self, style="TFrame", padding=14)
        self._corpo.pack(fill="both", expand=True)

    @property
    def corpo(self) -> ttk.Frame:
        return self._corpo

    def centralizar(self):
        self.update_idletasks()
        largura = max(self._largura, self.winfo_reqwidth())
        altura = max(self._altura, self.winfo_reqheight())
        pai = self.master
        try:
            x = pai.winfo_rootx() + (pai.winfo_width() - largura) // 2
            y = pai.winfo_rooty() + (pai.winfo_height() - altura) // 2
            x = max(0, x)
            y = max(0, y)
        except (tk.TclError, AttributeError):
            x = y = 80
        self.geometry(f"{largura}x{altura}+{x}+{y}")

    def cancelar(self, _evento=None):
        self.resultado = None
        self._fechada = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def confirmar(self, resultado: Any = True):
        self.resultado = resultado
        self._fechada = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def barra_botoes(self, textos: Sequence[tuple[str, Callable, str]] = (("OK", None, "Primario.TButton"),)) -> ttk.Frame:
        """Cria a barra inferior de botões. ``textos`` = [(rótulo, comando, estilo)]."""
        barra = ttk.Frame(self, style="TFrame", padding=(14, 0, 14, 12))
        barra.pack(side="bottom", fill="x")
        for rotulo, comando, estilo in textos:
            ttk.Button(
                barra, text=rotulo, style=estilo or "TButton",
                command=(comando if comando else lambda: self.confirmar(True)),
            ).pack(side="right", padx=(6, 0))
        return barra

    def abrir(self):
        """Exibe a janela e espera a resposta do usuário."""
        if MODO_TESTE:
            _registrar("dialogo", f"{self.title()} — cancelado automaticamente (modo de teste)")
            self.resultado = None
            self.destroy()
            return None
        self.centralizar()
        self.focus_force()
        try:
            self.wait_window(self)
        except tk.TclError:
            pass
        return self.resultado


# --------------------------------------------------------------------------------------
# Mensagens
# --------------------------------------------------------------------------------------


ICONES = {"info": "ℹ", "sucesso": "✔", "alerta": "⚠", "erro": "✖", "pergunta": "?"}


def mensagem(mestre, tema: Tema, titulo: str, texto: str, tipo: str = "info", botoes: Sequence[str] = ("OK",)) -> str:
    """Caixa de mensagem com ícone colorido. Devolve o rótulo do botão clicado."""
    if MODO_TESTE:
        _registrar(tipo, f"{titulo}: {texto}")
        return botoes[0] if botoes else "OK"
    cores = {"info": "info", "sucesso": "sucesso", "alerta": "alerta", "erro": "perigo", "pergunta": "info"}
    dialogo = Modal(mestre, tema, titulo, largura=430)
    topo = ttk.Frame(dialogo.corpo, style="TFrame")
    topo.pack(fill="x")
    icone = tk.Label(
        topo, text=ICONES.get(tipo, "ℹ"), font=("Segoe UI", 22),
        background=tema.cor("bg"), foreground=tema.cor(cores.get(tipo, "info")),
    )
    icone.pack(side="left", padx=(0, 10))
    rotulo = ttk.Label(dialogo.corpo, text=texto, style="TLabel", wraplength=320, justify="left", font=FONTE_BASE)
    rotulo.pack(side="left", fill="x", expand=True)
    resposta = {"valor": botoes[0] if botoes else "OK"}

    def escolher(valor):
        resposta["valor"] = valor
        dialogo.confirmar(valor)

    barra = ttk.Frame(dialogo, style="TFrame", padding=(14, 0, 14, 12))
    barra.pack(side="bottom", fill="x")
    for rotulo_botao in reversed(list(botoes)):
        estilo = "Primario.TButton" if rotulo_botao in ("OK", "Sim", "Confirmar", "Salvar") else "TButton"
        ttk.Button(barra, text=rotulo_botao, style=estilo, command=lambda r=rotulo_botao: escolher(r)).pack(
            side="right", padx=(6, 0)
        )
    dialogo.abrir()
    return resposta["valor"]


def info(mestre, tema: Tema, texto: str, titulo: str = "Aviso") -> None:
    mensagem(mestre, tema, titulo, texto, "info")


def sucesso(mestre, tema: Tema, texto: str, titulo: str = "Concluído") -> None:
    mensagem(mestre, tema, titulo, texto, "sucesso")


def alerta(mestre, tema: Tema, texto: str, titulo: str = "Atenção") -> None:
    mensagem(mestre, tema, titulo, texto, "alerta")


def erro(mestre, tema: Tema, texto: str, titulo: str = "Erro") -> None:
    mensagem(mestre, tema, titulo, texto, "erro")


def confirmar(mestre, tema: Tema, texto: str, titulo: str = "Confirmação",
              rotulo_sim: str = "Sim", rotulo_nao: str = "Não") -> bool:
    """Pergunta sim/não. Devolve ``True`` apenas se o usuário confirmar."""
    if MODO_TESTE:
        _registrar("pergunta", f"{titulo}: {texto} -> {'Sim' if RESPOSTA_CONFIRMAR else 'Não'}")
        return RESPOSTA_CONFIRMAR
    resposta = mensagem(mestre, tema, titulo, texto, "pergunta", (rotulo_sim, rotulo_nao))
    return resposta == rotulo_sim


def avisar_erro(mestre, tema: Tema, exc: Exception, contexto: str = "") -> None:
    """Mostra o erro de forma amigável (mensagem de negócio sem traceback)."""
    texto = str(exc) or exc.__class__.__name__
    if contexto:
        texto = f"{contexto}\n\n{texto}"
    erro(mestre, tema, texto, "Não foi possível concluir")


# --------------------------------------------------------------------------------------
# Formulários
# --------------------------------------------------------------------------------------


def criar_campo(especificacao: dict, mestre, tema: Tema):
    """Instancia o campo certo a partir de uma especificação de formulário."""
    tipo = str(especificacao.get("tipo", "texto"))
    rotulo = especificacao.get("rotulo", "")
    comum = {
        "obrigatorio": especificacao.get("obrigatorio", False),
        "dica": especificacao.get("dica", ""),
    }
    if tipo == "texto":
        return CampoTexto(mestre, tema, rotulo, largura=especificacao.get("largura", 34),
                          multilinea=especificacao.get("multilinea", False),
                          altura=especificacao.get("altura", 4), limite=especificacao.get("limite", 0),
                          mascara=especificacao.get("mascara", ""), maiusculas=especificacao.get("maiusculas", False),
                          **comum)
    if tipo == "dinheiro":
        return CampoDinheiro(mestre, tema, rotulo, largura=especificacao.get("largura", 14),
                             permitir_negativo=especificacao.get("permitir_negativo", False),
                             ao_alterar=especificacao.get("ao_alterar"), **comum)
    if tipo == "quantidade":
        return CampoQuantidade(mestre, tema, rotulo, largura=especificacao.get("largura", 12),
                               minimo=especificacao.get("minimo", 0.0),
                               maximo=especificacao.get("maximo", 1_000_000.0),
                               decimais=especificacao.get("decimais", 4),
                               ao_alterar=especificacao.get("ao_alterar"), **comum)
    if tipo == "lista":
        return CampoLista(mestre, tema, rotulo, opcoes=especificacao.get("opcoes", ()),
                          valores=especificacao.get("valores"), largura=especificacao.get("largura", 30),
                          vazio=especificacao.get("vazio", ""), somente_leitura=especificacao.get("somente_leitura", True),
                          ao_alterar=especificacao.get("ao_alterar"), **comum)
    if tipo == "data":
        return CampoData(mestre, tema, rotulo, largura=especificacao.get("largura", 12),
                         padrao_hoje=especificacao.get("padrao_hoje", False), **comum)
    if tipo == "marcar":
        return CampoMarcar(mestre, tema, rotulo, dica=especificacao.get("dica", ""))
    raise ValueError(f"Tipo de campo desconhecido: '{tipo}'.")


def formulario(mestre, tema: Tema, titulo: str, campos: Sequence[dict], valores: dict | None = None,
               largura: int = 480, texto: str = "", validar: Callable[[dict], str] | None = None) -> dict | None:
    """Formulário genérico em janela modal.

    ``campos`` é uma lista de especificações (ver :func:`criar_campo`) com a chave
    ``chave`` identificando o valor no dicionário devolvido. Devolve ``None`` se o
    usuário cancelar.
    """
    dialogo = Modal(mestre, tema, titulo, largura=largura)
    if texto:
        ttk.Label(dialogo.corpo, text=texto, style="Suave.TLabel", wraplength=largura - 40,
                  justify="left").pack(anchor="w", pady=(0, 8))
    instancias: dict[str, Any] = {}
    grade = ttk.Frame(dialogo.corpo, style="TFrame")
    grade.pack(fill="both", expand=True)
    linha = 0
    colunas_por_linha = 2 if largura >= 520 else 1
    coluna = 0
    for especificacao in campos:
        campo = criar_campo(especificacao, grade, tema)
        chave = especificacao["chave"]
        instancias[chave] = campo
        largura_total = especificacao.get("colunas", 1)
        if coluna + largura_total > colunas_por_linha:
            linha += 1
            coluna = 0
        campo.grid(row=linha, column=coluna, sticky="ew", padx=(0, 10), pady=5)
        grade.columnconfigure(coluna, weight=1)
        coluna += largura_total
    if valores:
        for chave, valor in valores.items():
            if chave in instancias:
                instancias[chave].definir(valor)

    def salvar():
        dados = {}
        for chave, campo in instancias.items():
            dados[chave] = campo.valor()
        for chave, campo in instancias.items():
            ok, mensagem_erro = campo.validar()
            if not ok:
                campo.mostrar_erro(mensagem_erro)
                campo.focar()
                return
            campo.limpar_erro()
        if validar:
            problema = validar(dados)
            if problema:
                alerta(dialogo, tema, problema)
                return
        dialogo.confirmar(dados)

    dialogo.barra_botoes((("Salvar", salvar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
    primeiro = next(iter(instancias.values()), None)
    if primeiro:
        primeiro.focar()
    return dialogo.abrir()


class DialogoFormulario(Modal):
    """Formulário completo em janela modal, com seções e rolagem.

    Usado pelos cadastros mais longos (produtos, clientes, fornecedores...).
    ``secoes`` é uma lista de ``(título, [especificações de campo])``; o título
    pode ser ``""`` para não desenhar cabeçalho.
    """

    def __init__(self, mestre, tema: Tema, titulo: str, secoes: Sequence[tuple[str, Sequence[dict]]],
                 valores: dict | None = None, largura: int = 720, altura: int = 620,
                 validar: Callable[[dict], str] | None = None,
                 texto_rotulo_botao: str = "Salvar", ao_salvar: Callable[[dict], Any] | None = None,
                 texto: str = ""):
        super().__init__(mestre, tema, titulo, largura=largura, altura=altura)
        self.instancias: dict[str, Any] = {}
        self.validar_extra = validar
        self.ao_salvar = ao_salvar
        if texto:
            ttk.Label(self.corpo, text=texto, style="Suave.TLabel", wraplength=largura - 40,
                      justify="left").pack(anchor="w", pady=(0, 4))
        self._construir(secoes, largura)
        if valores:
            for chave, valor in valores.items():
                if chave in self.instancias:
                    self.instancias[chave].definir(valor)
        self.barra_botoes(((texto_rotulo_botao, self.salvar, "Primario.TButton"),
                           ("Cancelar", self.cancelar, "TButton")))
        primeiro = next(iter(self.instancias.values()), None)
        if primeiro:
            primeiro.focar()

    def _construir(self, secoes: Sequence[tuple[str, Sequence[dict]]], largura: int):
        from .widgets import QuadroRolavel

        rolavel = QuadroRolavel(self.corpo, self.tema)
        rolavel.pack(fill="both", expand=True)
        quadro = rolavel.quadro
        colunas_por_linha = 3 if largura >= 760 else (2 if largura >= 520 else 1)
        for titulo_secao, campos in secoes:
            if titulo_secao:
                ttk.Label(quadro, text=titulo_secao, style="TLabel", font=FONTE_SUBTITULO).grid(
                    column=0, columnspan=colunas_por_linha, sticky="w", pady=(10, 2), padx=(2, 0)
                )
            linha = quadro.grid_size()[1]
            coluna = 0
            for especificacao in campos:
                campo = criar_campo(especificacao, quadro, self.tema)
                chave = especificacao["chave"]
                self.instancias[chave] = campo
                largura_total = int(especificacao.get("colunas", 1))
                if coluna + largura_total > colunas_por_linha:
                    linha += 1
                    coluna = 0
                campo.grid(row=linha, column=coluna, sticky="nw", padx=(0, 14), pady=4)
                coluna += largura_total
            for i in range(colunas_por_linha):
                quadro.columnconfigure(i, weight=1)

    def valores(self) -> dict:
        return {chave: campo.valor() for chave, campo in self.instancias.items()}

    def campo(self, chave: str):
        return self.instancias.get(chave)

    def salvar(self, _evento=None):
        dados = self.valores()
        for chave, campo in self.instancias.items():
            ok, mensagem_erro = campo.validar()
            if not ok:
                campo.mostrar_erro(mensagem_erro)
                campo.focar()
                return
            campo.limpar_erro()
        if self.validar_extra:
            problema = self.validar_extra(dados)
            if problema:
                alerta(self, self.tema, problema)
                return
        if self.ao_salvar:
            resultado = self.ao_salvar(dados)
            if resultado is False:
                return
            self.confirmar(dados if resultado is None else resultado)
        else:
            self.confirmar(dados)


def pedir_texto(mestre, tema: Tema, titulo: str, rotulo: str = "", valor: str = "", multilinea: bool = False,
                obrigatorio: bool = True, dica: str = "", largura: int = 420) -> str | None:
    """Pede um texto (usado em motivos, observações e renomeações)."""
    resultado = formulario(
        mestre, tema, titulo,
        [{"chave": "valor", "rotulo": rotulo or titulo, "tipo": "texto", "obrigatorio": obrigatorio,
          "multilinea": multilinea, "altura": 5, "largura": 44, "dica": dica}],
        {"valor": valor}, largura=largura,
    )
    return None if resultado is None else str(resultado["valor"]).strip()


def pedir_valor(mestre, tema: Tema, titulo: str, rotulo: str = "Valor", valor=0, tipo: str = "dinheiro",
                minimo: float = 0.0, dica: str = "", obrigatorio: bool = True):
    """Pede um número (dinheiro em centavos ou quantidade)."""
    especificacao = {"chave": "valor", "rotulo": rotulo, "tipo": tipo, "obrigatorio": obrigatorio, "dica": dica}
    if tipo == "quantidade":
        especificacao["minimo"] = minimo
        especificacao["decimais"] = 4
    resultado = formulario(mestre, tema, titulo, [especificacao], {"valor": valor}, largura=380)
    return None if resultado is None else resultado["valor"]


def pedir_senha(mestre, tema: Tema, titulo: str = "Senha", texto: str = "", confirmar: bool = False,
                atual: bool = False) -> dict | None:
    """Diálogo de senha (troca de senha, liberação de supervisor)."""
    dialogo = Modal(mestre, tema, titulo, largura=400)
    if texto:
        ttk.Label(dialogo.corpo, text=texto, style="Suave.TLabel", wraplength=360, justify="left").pack(anchor="w", pady=(0, 8))
    campos = {}
    if atual:
        campos["atual"] = ("Senha atual", True)
    campos["senha"] = ("Nova senha" if (atual or confirmar) else "Senha", True)
    if confirmar:
        campos["confirmar"] = ("Confirmar nova senha", True)
    entradas = {}
    for chave, (rotulo, _) in campos.items():
        quadro = ttk.Frame(dialogo.corpo, style="TFrame")
        quadro.pack(fill="x", pady=4)
        ttk.Label(quadro, text=rotulo, style="TLabel").pack(anchor="w")
        entrada = ttk.Entry(quadro, show="•", width=32)
        entrada.pack(fill="x")
        entradas[chave] = entrada
    rotulo_erro = ttk.Label(dialogo.corpo, text="", style="TLabel", foreground=tema.cor("perigo"),
                            wraplength=360, justify="left")
    rotulo_erro.pack(anchor="w", pady=(4, 0))

    def salvar():
        dados = {chave: entrada.get() for chave, entrada in entradas.items()}
        if "atual" in dados and len(dados["atual"]) < 1:
            rotulo_erro.configure(text="Informe a senha atual.")
            return
        if "senha" in dados and len(dados["senha"]) < 4 and (atual or confirmar):
            rotulo_erro.configure(text="A senha precisa ter pelo menos 4 caracteres.")
            return
        if confirmar and dados.get("senha") != dados.get("confirmar"):
            rotulo_erro.configure(text="A confirmação não confere com a nova senha.")
            return
        dialogo.confirmar(dados)

    dialogo.barra_botoes((("Confirmar", salvar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
    primeira = next(iter(entradas.values()))
    primeira.focus_set()
    dialogo.bind("<Return>", lambda e: salvar())
    return dialogo.abrir()


# --------------------------------------------------------------------------------------
# Seleção de registros
# --------------------------------------------------------------------------------------


def selecionar_registro(
    mestre,
    tema: Tema,
    titulo: str,
    colunas: Sequence[dict],
    dados: Sequence[dict],
    ao_buscar: Callable[[str], Sequence[dict]] | None = None,
    duplo_clique_confirma: bool = True,
    largura: int = 720,
    texto: str = "",
    chave_retorno: str = "",
):
    """Diálogo com busca e tabela para escolher um registro.

    Devolve a linha selecionada (dicionário) ou ``None``. Se ``ao_buscar`` for
    informado, a digitação consulta a fonte de dados (busca no banco).
    """
    dialogo = Modal(mestre, tema, titulo, largura=largura, altura=460)
    if texto:
        ttk.Label(dialogo.corpo, text=texto, style="Suave.TLabel", wraplength=largura - 40).pack(anchor="w", pady=(0, 6))

    quadro_busca = ttk.Frame(dialogo.corpo, style="TFrame")
    quadro_busca.pack(fill="x", pady=(0, 6))
    ttk.Label(quadro_busca, text="Buscar:", style="TLabel").pack(side="left")
    entrada = ttk.Entry(quadro_busca, width=40)
    entrada.pack(side="left", fill="x", expand=True, padx=(6, 6))

    tabela = Tabela(dialogo.corpo, tema, colunas, selecao="browse", mostrar_busca=False, altura=12)
    tabela.pack(fill="both", expand=True)
    tabela.carregar(list(dados))

    def filtrar(_evento=None):
        termo = entrada.get().strip()
        if ao_buscar and termo:
            tabela.carregar(list(ao_buscar(termo)))
        else:
            tabela.buscar(termo)

    entrada.bind("<KeyRelease>", filtrar)
    entrada.focus_set()

    if duplo_clique_confirma:
        tabela.ao_duplo_clique = lambda linha: dialogo.confirmar(linha)

    def ok():
        linha = tabela.linha_selecionada()
        if not linha:
            alerta(dialogo, tema, "Selecione um registro da lista.")
            return
        dialogo.confirmar(linha)

    dialogo.barra_botoes((("Selecionar", ok, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
    resultado = dialogo.abrir()
    if resultado is None or not chave_retorno:
        return resultado
    return resultado.get(chave_retorno)


def selecionar_varios(mestre, tema: Tema, titulo: str, colunas: Sequence[dict], dados: Sequence[dict],
                      texto: str = "", largura: int = 760) -> list[dict]:
    """Igual a :func:`selecionar_registro`, mas permite marcar vários itens."""
    dialogo = Modal(mestre, tema, titulo, largura=largura, altura=480)
    if texto:
        ttk.Label(dialogo.corpo, text=texto, style="Suave.TLabel", wraplength=largura - 40).pack(anchor="w", pady=(0, 6))
    tabela = Tabela(dialogo.corpo, tema, colunas, selecao="extended", altura=14)
    tabela.pack(fill="both", expand=True)
    tabela.carregar(list(dados))

    def ok():
        selecionadas = tabela.linhas_selecionadas()
        if not selecionadas:
            alerta(dialogo, tema, "Selecione ao menos um item (use Ctrl ou Shift para marcar vários).")
            return
        dialogo.confirmar(selecionadas)

    dialogo.barra_botoes((("Confirmar", ok, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
    return dialogo.abrir() or []


def escolher_opcao(mestre, tema: Tema, titulo: str, texto: str, opcoes: Sequence[str], largura: int = 420) -> str | None:
    """Lista simples de opções (botões). Devolve o texto escolhido."""
    dialogo = Modal(mestre, tema, titulo, largura=largura)
    ttk.Label(dialogo.corpo, text=texto, style="TLabel", wraplength=largura - 50, justify="left").pack(anchor="w", pady=(0, 8))
    for opcao in opcoes:
        ttk.Button(dialogo.corpo, text=opcao, command=lambda o=opcao: dialogo.confirmar(o)).pack(fill="x", pady=2)
    dialogo.barra_botoes((("Cancelar", dialogo.cancelar, "TButton"),))
    return dialogo.abrir()


# --------------------------------------------------------------------------------------
# Diálogos específicos do sistema
# --------------------------------------------------------------------------------------


def pedir_motivo(mestre, tema: Tema, titulo: str, texto: str, opcoes: Sequence[str] = (), obrigatorio: bool = True) -> str | None:
    """Pede um motivo (cancelamento de venda, perda, ajuste...)."""
    dialogo = Modal(mestre, tema, titulo, largura=460)
    ttk.Label(dialogo.corpo, text=texto, style="TLabel", wraplength=410, justify="left").pack(anchor="w")
    if opcoes:
        ttk.Label(dialogo.corpo, text="Motivos frequentes:", style="Suave.TLabel").pack(anchor="w", pady=(8, 2))
        quadro = ttk.Frame(dialogo.corpo, style="TFrame")
        quadro.pack(fill="x")
        for i, opcao in enumerate(opcoes):
            ttk.Button(quadro, text=opcao, command=lambda o=opcao: entrada.insert(0, o)).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2
            )
        quadro.columnconfigure(0, weight=1)
        quadro.columnconfigure(1, weight=1)
    ttk.Label(dialogo.corpo, text="Descreva o motivo *", style="TLabel").pack(anchor="w", pady=(10, 2))
    entrada = ttk.Entry(dialogo.corpo, width=52)
    entrada.pack(fill="x")
    entrada.focus_set()
    rotulo_erro = ttk.Label(dialogo.corpo, text="", foreground=tema.cor("perigo"))
    rotulo_erro.pack(anchor="w")

    def salvar(_evento=None):
        valor = entrada.get().strip()
        if obrigatorio and not valor:
            rotulo_erro.configure(text="Informe o motivo (fica registrado no histórico).")
            return
        dialogo.confirmar(valor)

    entrada.bind("<Return>", salvar)
    dialogo.barra_botoes((("Confirmar", salvar, "Primario.TButton"), ("Cancelar", dialogo.cancelar, "TButton")))
    return dialogo.abrir()


def mostrar_imagem(mestre, tema: Tema, titulo: str, caminho: str, largura: int = 420) -> None:
    """Amplia a foto de um produto (clique na miniatura)."""
    from PIL import Image, ImageTk

    dialogo = Modal(mestre, tema, titulo, largura=largura + 40, redimensionavel=False)
    try:
        imagem = Image.open(caminho)
        imagem.thumbnail((largura, largura))
        foto = ImageTk.PhotoImage(imagem)
    except Exception as exc:
        ttk.Label(dialogo.corpo, text=f"Não foi possível abrir a imagem:\n{exc}").pack()
        dialogo.barra_botoes()
        dialogo.abrir()
        return
    rotulo = tk.Label(dialogo.corpo, image=foto, background=tema.cor("bg"))
    rotulo.image = foto  # mantém a referência viva
    rotulo.pack()
    dialogo.barra_botoes((("Fechar", dialogo.confirmar, "Primario.TButton"),))
    dialogo.abrir()


def progresso(mestre, tema: Tema, titulo: str, texto: str = "") -> Modal:
    """Janela de progresso simples (usada em operações longas como backup)."""
    dialogo = Modal(mestre, tema, titulo, largura=380, redimensionavel=False)
    ttk.Label(dialogo.corpo, text=texto or "Aguarde...", style="TLabel", wraplength=340).pack(anchor="w")
    barra = ttk.Progressbar(dialogo.corpo, mode="indeterminate", length=340)
    barra.pack(fill="x", pady=10)
    barra.start(12)
    dialogo.update_idletasks()
    return dialogo


def finalizar_progresso(dialogo: Modal | None) -> None:
    if dialogo is not None:
        try:
            dialogo.destroy()
        except tk.TclError:
            pass
