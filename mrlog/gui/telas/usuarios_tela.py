"""
Tela de **Usuários** — login, perfis e permissões.

Regras de segurança aplicadas aqui (e reforçadas no módulo :mod:`mrlog.usuarios`):
- usuários nunca são apagados, apenas **desativados** (mantém o histórico de vendas);
- o sistema não fica sem administrador ativo;
- ninguém desativa a si mesmo nem altera o próprio perfil;
- a senha é guardada como hash PBKDF2 (nunca em texto puro).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ... import usuarios as usuarios_mod
from ...utils import formatar_data, formatar_telefone
from .. import dialogs
from . import TelaLista

OPCOES_PERFIL = [(perfil, usuarios_mod.ROTULOS_PERFIS[perfil]) for perfil in usuarios_mod.PERFIS]
FILTROS_PERFIL = ["(todos)"] + [rotulo for _, rotulo in OPCOES_PERFIL]


class DialogoPermissoes(dialogs.Modal):
    """Mostra o que cada perfil pode fazer (matriz de permissões do sistema)."""

    GRUPOS = (
        ("Operação", ("painel", "pdv", "vendas", "vendas_cancelar", "vendas_devolver")),
        ("Cadastros", ("produtos", "produtos_editar", "produtos_excluir", "produtos_preco_editar", "categorias",
                       "clientes", "clientes_editar", "fornecedores", "fornecedores_editar")),
        ("Estoque", ("estoque", "estoque_movimentar", "etiquetas")),
        ("Financeiro", ("financeiro", "contas_receber", "contas_pagar", "caixa")),
        ("Relatórios e sistema", ("relatorios", "relatorios_financeiros", "usuarios", "configuracoes", "backup",
                                  "logs")),
    )

    ROTULOS = {
        "painel": "Painel (dashboard)", "pdv": "PDV — frente de caixa", "vendas": "Consultar vendas",
        "vendas_cancelar": "Cancelar venda", "vendas_devolver": "Registrar devolução",
        "produtos": "Consultar produtos", "produtos_editar": "Cadastrar/editar produtos",
        "produtos_excluir": "Excluir produtos", "produtos_preco_editar": "Alterar preço na venda",
        "categorias": "Categorias", "clientes": "Consultar clientes", "clientes_editar": "Editar clientes",
        "fornecedores": "Consultar fornecedores", "fornecedores_editar": "Editar fornecedores",
        "estoque": "Consultar estoque", "estoque_movimentar": "Movimentar estoque",
        "etiquetas": "Imprimir etiquetas", "financeiro": "Financeiro (visão geral)",
        "contas_receber": "Contas a receber", "contas_pagar": "Contas a pagar", "caixa": "Caixa diário",
        "relatorios": "Relatórios operacionais", "relatorios_financeiros": "Relatórios financeiros (lucro)",
        "usuarios": "Gerenciar usuários", "configuracoes": "Configurações do sistema",
        "backup": "Backup e restauração", "logs": "Log de auditoria",
    }

    def __init__(self, mestre, tema):
        super().__init__(mestre, tema, "Permissões por perfil", largura=760, altura=620)
        perfis = list(usuarios_mod.PERFIS)

        descricao = tk.Text(self.corpo, height=4, wrap="word", borderwidth=0, font=("Segoe UI", 9),
                            background=tema.cor("bg_card"), foreground=tema.cor("fg"))
        descricao.pack(fill="x", pady=(0, 6))
        descricao.insert("1.0", usuarios_mod.descricao_permissoes())
        descricao.configure(state="disabled")

        quadro = ttk.Frame(self.corpo, style="TFrame")
        quadro.pack(fill="both", expand=True)
        ttk.Label(quadro, text="Permissão", style="TLabel", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        for coluna, perfil in enumerate(perfis, start=1):
            ttk.Label(quadro, text=usuarios_mod.ROTULOS_PERFIS[perfil], style="TLabel",
                      font=("Segoe UI", 9, "bold")).grid(row=0, column=coluna, sticky="w", padx=6, pady=4)
        quadro.columnconfigure(0, weight=1)
        linha = 1
        for titulo_grupo, chaves in self.GRUPOS:
            ttk.Label(quadro, text=titulo_grupo, style="Suave.TLabel", font=("Segoe UI", 9, "bold")).grid(
                row=linha, column=0, columnspan=len(perfis) + 1, sticky="w", padx=6, pady=(8, 2))
            linha += 1
            for chave in chaves:
                ttk.Label(quadro, text=self.ROTULOS.get(chave, chave), style="TLabel").grid(
                    row=linha, column=0, sticky="w", padx=12, pady=1)
                for coluna, perfil in enumerate(perfis, start=1):
                    tem = chave in usuarios_mod.permissoes_do_perfil(perfil)
                    ttk.Label(quadro, text="✔" if tem else "—", style="TLabel",
                              foreground=tema.cor("sucesso") if tem else tema.cor("fg_fraco")).grid(
                        row=linha, column=coluna, sticky="w", padx=6)
                linha += 1
        ttk.Label(quadro, text="Desconto máximo sem senha de supervisor", style="TLabel").grid(
            row=linha, column=0, sticky="w", padx=12, pady=(8, 1))
        for coluna, perfil in enumerate(perfis, start=1):
            limite = usuarios_mod.LIMITE_DESCONTO[perfil]
            ttk.Label(quadro, text=("Sem limite" if limite >= 100 else f"{limite:g}%"), style="TLabel",
                      foreground=tema.cor("info")).grid(row=linha, column=coluna, sticky="w", padx=6)
        self.barra_botoes((("Fechar", self.cancelar, "Primario.TButton"),))


class UsuariosTela(TelaLista):
    titulo = "Usuários"
    descricao = "Logins, perfis e permissões do sistema (administrador, gerente e vendedor)."
    permissao_editar = "usuarios"
    permissao_excluir = "usuarios"

    def __init__(self, mestre, ctx):
        self._perfil = tk.StringVar(value="(todos)")
        self._incluir_inativos = tk.BooleanVar(value=True)
        super().__init__(
            mestre, ctx,
            colunas=[
                {"chave": "nome", "rotulo": "Nome", "largura": 220},
                {"chave": "login", "rotulo": "Login", "largura": 140},
                {"chave": "perfil_texto", "rotulo": "Perfil", "largura": 130},
                {"chave": "limite_texto", "rotulo": "Desc. máx.", "largura": 90, "alinhamento": "centro"},
                {"chave": "email", "rotulo": "E-mail", "largura": 200},
                {"chave": "telefone_texto", "rotulo": "Telefone", "largura": 130},
                {"chave": "ultimo_login_texto", "rotulo": "Último login", "largura": 150},
                {"chave": "troca_texto", "rotulo": "Trocar senha", "largura": 100, "alinhamento": "centro"},
                {"chave": "situacao", "rotulo": "Situação", "largura": 90, "alinhamento": "centro"},
            ],
            carregar_dados=self._dados,
            resumo=self._resumo,
            novo=self._novo,
            editar=self._editar,
            ao_duplo_clique=lambda linha: self.editar(linha=linha),
            detalhes=self._detalhes,
            acoes=(
                ("🔑 Trocar minha senha", self.trocar_minha_senha, "TButton", "F2"),
                ("🔄 Redefinir senha", self.redefinir_senha, "TButton", "F3"),
                ("⏻ Desativar / Reativar", self.alternar_status, "TButton", "F4"),
                ("🧾 Vendas do usuário", self.ver_vendas, "TButton", "F5"),
                ("🛡 Permissões dos perfis", self.ver_permissoes, "TButton", "F6"),
            ),
            filtros=self._montar_filtros,
            titulo_exportacao="Usuarios",
            texto_vazio="Nenhum usuário encontrado com os filtros atuais.",
        )

    # ------------------------------------------------------------------ interface
    def _montar_filtros(self, pai: tk.Widget):
        ttk.Label(pai, text="Perfil:", style="TLabel").pack(side="left")
        ttk.Combobox(pai, textvariable=self._perfil, values=FILTROS_PERFIL, width=16,
                     state="readonly").pack(side="left", padx=(4, 14))
        self._perfil.trace_add("write", lambda *_: self.carregar())
        tk.Checkbutton(
            pai, text="Mostrar inativos", variable=self._incluir_inativos, command=self.carregar,
            background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
            activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
            selectcolor=self.tema.cor("bg_input"), highlightthickness=0,
        ).pack(side="left")
        ttk.Label(pai, text="Usuários não são excluídos: use Desativar para bloquear o acesso.",
                  style="Suave.TLabel").pack(side="right")

    def atualizar_tema(self):
        super().atualizar_tema()
        for filho in getattr(self, "quadro_filtros", ()).winfo_children():
            if isinstance(filho, tk.Checkbutton):
                filho.configure(background=self.tema.cor("bg_card"), foreground=self.tema.cor("fg"),
                                activebackground=self.tema.cor("bg_card"), activeforeground=self.tema.cor("fg"),
                                selectcolor=self.tema.cor("bg_input"))

    def ao_tecla(self, tecla: str) -> bool:
        acoes = {"F2": self.trocar_minha_senha, "F3": self.redefinir_senha, "F4": self.alternar_status,
                 "F5": self.ver_vendas, "F6": self.ver_permissoes}
        comando = acoes.get(tecla)
        if comando:
            comando()
            return True
        return False

    # ------------------------------------------------------------------ dados
    def _dados(self) -> list[dict]:
        perfil_filtro = self._perfil.get()
        usuarios = usuarios_mod.listar(self.banco, incluir_inativos=bool(self._incluir_inativos.get()))
        linhas = []
        for usuario in usuarios:
            perfil = str(usuario["perfil"] or "").lower()
            if perfil_filtro not in ("", "(todos)") and usuarios_mod.ROTULOS_PERFIS.get(perfil) != perfil_filtro:
                continue
            linha = dict(usuario)
            linha["perfil_texto"] = usuarios_mod.ROTULOS_PERFIS.get(perfil, perfil.title())
            limite = usuarios_mod.LIMITE_DESCONTO.get(perfil, 0.0)
            linha["limite_texto"] = "Sem limite" if limite >= 100 else f"{limite:g}%"
            linha["telefone_texto"] = formatar_telefone(usuario["telefone"] or "")
            linha["ultimo_login_texto"] = (formatar_data(usuario["ultimo_login"], com_hora=True)
                                           if usuario["ultimo_login"] else "nunca entrou")
            linha["troca_texto"] = "Sim" if int(usuario["trocar_senha"] or 0) else "Não"
            ativo = int(usuario["ativo"] or 0)
            linha["situacao"] = "Ativo" if ativo else "Inativo"
            linha["eh_eu"] = int(usuario["id"]) == int(self.usuario["id"])
            if linha["eh_eu"]:
                linha["_tag"] = "info"
            elif not ativo:
                linha["_tag"] = "neutro"
            linhas.append(linha)
        return linhas

    def _resumo(self, dados) -> str:
        contagem = usuarios_mod.contagem_por_perfil(self.banco)
        partes = [f"{usuarios_mod.ROTULOS_PERFIS[p]}: {contagem.get(p, 0)}" for p in usuarios_mod.PERFIS]
        return f"{len(dados)} usuário(s) listado(s) • ativos por perfil → " + " • ".join(partes)

    def _detalhes(self, linha: dict) -> list[tuple[str, str]]:
        perfil = str(linha["perfil"] or "").lower()
        permissoes = sorted(usuarios_mod.permissoes_do_perfil(perfil))
        return [
            ("Código", linha["id"]),
            ("Login", linha["login"]),
            ("Perfil", usuarios_mod.ROTULOS_PERFIS.get(perfil, perfil)),
            ("E-mail", linha["email"]),
            ("Telefone", formatar_telefone(linha["telefone"] or "") or "—"),
            ("Situação", linha["situacao"]),
            ("Último login", linha["ultimo_login_texto"]),
            ("Exigir troca de senha", linha["troca_texto"]),
            ("Desconto máximo", linha["limite_texto"]),
            ("Criado em", formatar_data(linha["criado_em"], com_hora=True)),
            ("Permissões", ", ".join(permissoes)),
        ]

    # ------------------------------------------------------------------ formulário
    def _formulario(self, usuario):
        editando = usuario is not None
        valores: dict[str, Any] = {}
        if editando:
            valores = {
                "nome": usuario["nome"], "login": usuario["login"], "perfil": usuario["perfil"],
                "email": usuario["email"] or "", "telefone": usuario["telefone"] or "",
                "ativo": int(usuario["ativo"] or 0), "trocar_senha": int(usuario["trocar_senha"] or 0),
            }
        else:
            valores = {"perfil": "vendedor", "ativo": 1, "trocar_senha": 1}

        secoes = [
            ("Acesso", [
                {"chave": "nome", "rotulo": "Nome completo", "tipo": "texto", "largura": 32, "obrigatorio": True,
                 "colunas": 2},
                {"chave": "login", "rotulo": "Login (nome de acesso)", "tipo": "texto", "largura": 22,
                 "obrigatorio": True, "dica": "Sem espaços; usado para entrar no sistema"},
                {"chave": "perfil", "rotulo": "Perfil", "tipo": "lista", "opcoes": OPCOES_PERFIL, "largura": 22,
                 "dica": usuarios_mod.DESCRICAO_PERFIS["vendedor"]},
            ]),
            ("Contato", [
                {"chave": "email", "rotulo": "E-mail", "tipo": "texto", "largura": 30},
                {"chave": "telefone", "rotulo": "Telefone", "tipo": "texto", "largura": 18, "mascara": "telefone"},
            ]),
            ("Situação", [
                {"chave": "ativo", "rotulo": "Usuário ativo", "tipo": "marcar"},
                {"chave": "trocar_senha", "rotulo": "Exigir troca de senha no próximo login", "tipo": "marcar",
                 "colunas": 2},
            ]),
        ]

        dialogo = dialogs.DialogoFormulario(
            self.ctx.janela, self.tema,
            "Editar usuário" if editando else "Novo usuário",
            secoes, valores, largura=640, altura=520,
            texto="" if editando else "Após salvar você definirá a senha inicial do usuário.",
            validar=self._validar_formulario,
        )
        resultado = dialogo.abrir()
        if resultado is None:
            return
        if editando:
            self._salvar(usuario, resultado)
        else:
            self._criar(resultado)

    @staticmethod
    def _validar_formulario(dados: dict) -> str:
        nome = str(dados.get("nome") or "").strip()
        login = str(dados.get("login") or "").strip()
        if len(nome) < 2:
            return "Informe o nome do usuário (mínimo 2 letras)."
        if not login:
            return "Informe o login."
        if " " in login:
            return "O login não pode conter espaços."
        if dados.get("email") and "@" not in str(dados["email"]):
            return "E-mail inválido."
        return ""

    def _criar(self, dados: dict):
        """Pede a senha inicial e cria o usuário."""
        senhas = dialogs.pedir_senha(
            self.ctx.janela, self.tema, f"Senha inicial — {dados['nome']}",
            texto="Defina a senha inicial (mínimo 4 caracteres).\n"
                  "Se a opção “exigir troca de senha” estiver marcada, o usuário criará\n"
                  "uma senha própria no primeiro acesso.",
            confirmar=True,
        )
        if not senhas:
            dialogs.info(self, self.tema, "Cadastro cancelado — nenhuma senha foi definida.")
            return None
        registro = {
            "nome": dados.get("nome") or "", "login": dados.get("login") or "",
            "perfil": dados.get("perfil") or "vendedor", "email": dados.get("email") or "",
            "telefone": dados.get("telefone") or "", "ativo": int(bool(dados.get("ativo", 1))),
            "trocar_senha": int(bool(dados.get("trocar_senha", 0))),
        }
        try:
            usuario_id = usuarios_mod.criar(self.banco, registro, senhas["senha"], autor=self.usuario)
        except usuarios_mod.ErroUsuario as exc:
            dialogs.erro(self, self.tema, str(exc))
            return None
        self.carregar()
        self.tabela.selecionar_por("id", usuario_id)
        dialogs.sucesso(self, self.tema,
                        f"Usuário “{registro['nome']}” criado com o perfil "
                        f"{usuarios_mod.ROTULOS_PERFIS.get(registro['perfil'], registro['perfil'])}.")
        return usuario_id

    def _salvar(self, usuario, dados: dict):
        registro = {
            "nome": dados.get("nome") or "", "login": dados.get("login") or "",
            "perfil": dados.get("perfil") or "vendedor", "email": dados.get("email") or "",
            "telefone": dados.get("telefone") or "", "ativo": int(bool(dados.get("ativo", 1))),
            "trocar_senha": int(bool(dados.get("trocar_senha", 0))),
        }
        try:
            usuarios_mod.atualizar(self.banco, int(usuario["id"]), registro, autor=self.usuario)
        except usuarios_mod.ErroUsuario as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        self.tabela.selecionar_por("id", int(usuario["id"]))
        dialogs.sucesso(self, self.tema, "Usuário atualizado.")
        # Editou o próprio cadastro? Recarrega a sessão para o cabeçalho e as permissões.
        if int(usuario["id"]) == int(self.usuario["id"]):
            self.ctx.atualizar_usuario(usuarios_mod.pegar(self.banco, int(usuario["id"])))

    def _novo(self, _tela=None):
        self._formulario(None)

    def _editar(self, _tela=None, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        usuario = usuarios_mod.pegar(self.banco, linha["id"])
        if not usuario:
            dialogs.erro(self, self.tema, "Usuário não encontrado.")
            self.carregar()
            return
        self._formulario(usuario)

    # ------------------------------------------------------------------ ações
    def alternar_status(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        usuario_id = int(linha["id"])
        ativo = int(linha["ativo"] or 0)
        if ativo:
            if not dialogs.confirmar(self, self.tema,
                                     f"Desativar o usuário “{linha['nome']}” ({linha['login']})?\n\n"
                                     "Ele não conseguirá mais entrar no sistema; as vendas já registradas "
                                     "permanecem no histórico.",
                                     "Desativar usuário", "Desativar", "Cancelar"):
                return
        try:
            usuarios_mod.atualizar(self.banco, usuario_id, {"ativo": 0 if ativo else 1}, autor=self.usuario)
        except usuarios_mod.ErroUsuario as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.info(self, self.tema, "Usuário desativado." if ativo else "Usuário reativado.")

    def trocar_minha_senha(self):
        senhas = dialogs.pedir_senha(self.ctx.janela, self.tema, "Trocar a minha senha",
                                     texto="Informe a senha atual e a nova senha (mínimo 4 caracteres).",
                                     confirmar=True, atual=True)
        if not senhas:
            return
        try:
            usuarios_mod.alterar_senha(self.banco, int(self.usuario["id"]), senhas["atual"], senhas["senha"],
                                       senhas["confirmar"], autor=self.usuario)
        except usuarios_mod.ErroUsuario as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema, "Senha alterada com sucesso.")

    def redefinir_senha(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        if not self.pode("usuarios"):
            self.exigir("usuarios", "redefinir a senha de outro usuário")
            return
        if int(linha["id"]) == int(self.usuario["id"]):
            dialogs.alerta(self, self.tema,
                           "Para trocar a sua própria senha use **Trocar minha senha** (F2) — "
                           "ela pede a senha atual.")
            return
        senhas = dialogs.pedir_senha(self.ctx.janela, self.tema, f"Redefinir senha — {linha['nome']}",
                                     texto="Defina uma nova senha para este usuário.\n"
                                           "Ele será obrigado a trocá-la no próximo login.",
                                     confirmar=True)
        if not senhas:
            return
        try:
            usuarios_mod.resetar_senha(self.banco, int(linha["id"]), senhas["senha"], autor=self.usuario)
        except usuarios_mod.ErroUsuario as exc:
            dialogs.erro(self, self.tema, str(exc))
            return
        self.carregar()
        dialogs.sucesso(self, self.tema,
                        f"Senha de “{linha['nome']}” redefinida.\nEle deverá criar uma nova senha no próximo login.")

    def ver_vendas(self, linha: dict | None = None):
        linha = linha or self.exigir_selecao()
        if not linha:
            return
        self.ctx.navegar("vendas", {"vendedor_nome": linha["nome"]})

    def ver_permissoes(self):
        DialogoPermissoes(self.ctx.janela, self.tema).abrir()

    # ------------------------------------------------------------------ navegação
    def receber_parametros(self, parametros: dict):
        parametros = parametros or {}
        if parametros.get("perfil"):
            # o trace da variável já recarrega a grade
            self._perfil.set(usuarios_mod.ROTULOS_PERFIS.get(str(parametros["perfil"]).lower(), "(todos)"))
        if parametros.get("usuario_id"):
            self.tabela.selecionar_por("id", int(parametros["usuario_id"]))
