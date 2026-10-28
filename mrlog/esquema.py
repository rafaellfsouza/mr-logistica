"""
Esquema do banco de dados SQLite do MR Logística.

Tudo que é estrutural fica aqui: tabelas, índices, triggers, visões e os dados
iniciais (sementes). O banco é **versionado**: cada migração é uma função
``_v1``, ``_v2``... registrada em ``MIGRACOES``. Ao abrir, o sistema compara a
versão gravada na tabela ``meta`` e aplica somente as migrações pendentes — assim
o usuário pode atualizar o executável sem perder os dados.

Convenções adotadas:

* **Dinheiro em centavos** (``INTEGER``) — nunca ``REAL``.
* **Datas em texto ISO** (``YYYY-MM-DD`` / ``YYYY-MM-DD HH:MM:SS``) — ordenam
  corretamente como string e são legíveis em qualquer editor SQLite.
* **Quantidades em ``REAL``** com 4 casas decimais (permite venda fracionada:
  0,250 kg, 1,5 L etc.).
* **Exclusão lógica** (``ativo = 0``) para cadastros: nada é apagado de verdade,
  preservando o histórico das vendas.
"""

from __future__ import annotations

# --------------------------------------------------------------------------------------
# Versão 1 — esquema completo
# --------------------------------------------------------------------------------------

V1_TABELAS = [
    # ------------------------------------------------------------------ configurações
    """
    CREATE TABLE IF NOT EXISTS config (
        chave   TEXT PRIMARY KEY,
        valor   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        chave   TEXT PRIMARY KEY,
        valor   TEXT
    )
    """,
    # ------------------------------------------------------------------ cadastros base
    """
    CREATE TABLE IF NOT EXISTS unidades (
        sigla       TEXT PRIMARY KEY,
        nome        TEXT NOT NULL,
        familia     TEXT NOT NULL,           -- massa | volume | comprimento | quantidade
        fator_base  REAL NOT NULL DEFAULT 1, -- quanto vale na unidade padrão da família
        ordem       INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categorias (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nome        TEXT NOT NULL UNIQUE,
        descricao   TEXT,
        ativo       INTEGER NOT NULL DEFAULT 1,
        criado_em   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fornecedores (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nome            TEXT NOT NULL,
        razao_social    TEXT,
        cnpj_cpf        TEXT,
        inscricao       TEXT,
        contato         TEXT,
        telefone        TEXT,
        celular         TEXT,
        email           TEXT,
        endereco        TEXT,
        numero          TEXT,
        bairro          TEXT,
        cidade          TEXT,
        uf              TEXT,
        cep             TEXT,
        prazo_dias      INTEGER NOT NULL DEFAULT 0,   -- prazo médio de pagamento (dias)
        observacao      TEXT,
        ativo           INTEGER NOT NULL DEFAULT 1,
        criado_em       TEXT NOT NULL,
        atualizado_em   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clientes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nome            TEXT NOT NULL,
        tipo            TEXT NOT NULL DEFAULT 'Física',   -- Física | Jurídica
        cpf_cnpj        TEXT,
        rg_inscricao    TEXT,
        contato         TEXT,
        telefone        TEXT,
        celular         TEXT,
        email           TEXT,
        endereco        TEXT,
        numero          TEXT,
        bairro          TEXT,
        cidade          TEXT,
        uf              TEXT,
        cep             TEXT,
        nascimento      TEXT,
        limite_credito  INTEGER NOT NULL DEFAULT 0,       -- centavos; 0 = sem limite definido
        observacao      TEXT,
        ativo           INTEGER NOT NULL DEFAULT 1,
        criado_em       TEXT NOT NULL,
        atualizado_em   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nome            TEXT NOT NULL,
        login           TEXT NOT NULL UNIQUE,
        senha_hash      TEXT NOT NULL,
        perfil          TEXT NOT NULL DEFAULT 'vendedor',  -- administrador | gerente | vendedor
        email           TEXT,
        telefone        TEXT,
        ativo           INTEGER NOT NULL DEFAULT 1,
        trocar_senha    INTEGER NOT NULL DEFAULT 0,        -- exige troca no próximo login
        criado_em       TEXT NOT NULL,
        atualizado_em   TEXT,
        ultimo_login    TEXT
    )
    """,
    # ------------------------------------------------------------------ produtos
    """
    CREATE TABLE IF NOT EXISTS produtos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo              TEXT NOT NULL UNIQUE,          -- código interno (SKU)
        codigo_barras       TEXT UNIQUE,                   -- EAN/UPC lido pelo bipador (aceita vazio)
        nome                TEXT NOT NULL,
        descricao           TEXT,
        categoria_id        INTEGER REFERENCES categorias(id)    ON DELETE SET NULL,
        marca               TEXT,
        fornecedor_id       INTEGER REFERENCES fornecedores(id)  ON DELETE SET NULL,
        unidade_base        TEXT NOT NULL DEFAULT 'un',    -- unidade em que o ESTOQUE é controlado
        unidade_venda       TEXT NOT NULL DEFAULT 'un',    -- unidade padrão de venda
        fator_venda         REAL NOT NULL DEFAULT 1,       -- 1 unidade de venda = X unidades base
        permite_fracionar   INTEGER NOT NULL DEFAULT 1,    -- aceita quantidade decimal (ex.: 250 g)
        decimais            INTEGER NOT NULL DEFAULT 0,    -- casas sugeridas para a quantidade
        preco_custo         INTEGER NOT NULL DEFAULT 0,    -- centavos (custo médio)
        preco_venda         INTEGER NOT NULL DEFAULT 0,    -- centavos
        estoque_atual       REAL NOT NULL DEFAULT 0,       -- em unidade base (mantido por trigger)
        estoque_minimo      REAL NOT NULL DEFAULT 0,
        estoque_maximo      REAL NOT NULL DEFAULT 0,       -- 0 = não controla
        localizacao         TEXT,
        peso_gramas         REAL,
        volume_ml           REAL,
        comprimento_mm      REAL,
        largura_mm          REAL,
        altura_mm           REAL,
        controla_lote       INTEGER NOT NULL DEFAULT 0,
        validade_dias       INTEGER,                       -- validade padrão ao receber um lote
        foto                TEXT,                          -- nome do arquivo em dados/fotos
        observacao          TEXT,
        ativo               INTEGER NOT NULL DEFAULT 1,
        criado_em           TEXT NOT NULL,
        atualizado_em       TEXT
    )
    """,
    # ------------------------------------------------------------------ estoque
    """
    CREATE TABLE IF NOT EXISTS lotes (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id        INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
        numero            TEXT,                              -- nº do lote do fabricante
        validade          TEXT,                              -- YYYY-MM-DD (vazio = sem validade)
        quantidade_inicial REAL NOT NULL DEFAULT 0,
        quantidade_atual  REAL NOT NULL DEFAULT 0,
        custo_unitario    INTEGER NOT NULL DEFAULT 0,        -- centavos por unidade base
        fornecedor_id     INTEGER REFERENCES fornecedores(id) ON DELETE SET NULL,
        documento         TEXT,                              -- nº da nota/romaneio do fornecedor
        observacao        TEXT,
        criado_em         TEXT NOT NULL,
        atualizado_em     TEXT,
        UNIQUE (produto_id, numero, validade)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS movimentacoes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id      INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
        lote_id         INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
        tipo            TEXT NOT NULL CHECK (tipo IN ('entrada','saida','ajuste')),
        motivo          TEXT NOT NULL,   -- compra, venda, devolucao_cliente, ajuste_inventario, ...
        quantidade      REAL NOT NULL,   -- SEMPRE positiva; o sinal vem do tipo
        unidade         TEXT NOT NULL DEFAULT 'un',
        custo_unitario  INTEGER NOT NULL DEFAULT 0,  -- centavos por unidade base
        valor_total     INTEGER NOT NULL DEFAULT 0,  -- centavos
        saldo_apos      REAL,                        -- estoque do produto logo após o movimento
        documento_id    INTEGER,                     -- venda/devolução/compra de origem
        lote_numero     TEXT,                        -- nº do lote afetado (informativo)
        lote_ref        INTEGER REFERENCES lotes(id) ON DELETE SET NULL, -- lote de referência SEM efeito no saldo do lote
        validade        TEXT,
        usuario_id      INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome    TEXT,
        observacao      TEXT,
        criado_em       TEXT NOT NULL
    )
    """,
    # ------------------------------------------------------------------ PDV / vendas
    """
    CREATE TABLE IF NOT EXISTS vendas (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        numero              INTEGER NOT NULL UNIQUE,     -- número sequencial do cupom
        cliente_id          INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
        cliente_nome        TEXT,
        vendedor_id         INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        vendedor_nome       TEXT,
        subtotal            INTEGER NOT NULL DEFAULT 0,  -- centavos
        desconto            INTEGER NOT NULL DEFAULT 0,  -- centavos
        acrescimo           INTEGER NOT NULL DEFAULT 0,  -- centavos
        total               INTEGER NOT NULL DEFAULT 0,  -- centavos
        custo_total         INTEGER NOT NULL DEFAULT 0,  -- centavos (CMV)
        lucro               INTEGER NOT NULL DEFAULT 0,  -- centavos
        valor_pago          INTEGER NOT NULL DEFAULT 0,  -- centavos recebidos na hora
        troco               INTEGER NOT NULL DEFAULT 0,  -- centavos
        valor_fiado         INTEGER NOT NULL DEFAULT 0,  -- centavos que viraram conta a receber
        status              TEXT NOT NULL DEFAULT 'concluida'
                            CHECK (status IN ('concluida','cancelada','devolvida','parcialmente_devolvida')),
        caixa_id            INTEGER REFERENCES caixa_diario(id) ON DELETE SET NULL,
        observacao          TEXT,
        cancelada_motivo    TEXT,
        cancelada_em        TEXT,
        criada_em           TEXT NOT NULL,
        data_venda          TEXT NOT NULL                -- YYYY-MM-DD (para filtros por período)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS venda_itens (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id            INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        produto_id          INTEGER REFERENCES produtos(id) ON DELETE SET NULL,
        codigo              TEXT NOT NULL,
        codigo_barras       TEXT,
        nome                TEXT NOT NULL,
        unidade             TEXT NOT NULL,
        quantidade          REAL NOT NULL,               -- na unidade vendida
        quantidade_base     REAL NOT NULL,               -- convertida para a unidade de estoque
        preco_unitario      INTEGER NOT NULL DEFAULT 0,  -- centavos, na unidade vendida
        desconto            INTEGER NOT NULL DEFAULT 0,  -- centavos, já rateado
        acrescimo           INTEGER NOT NULL DEFAULT 0,  -- centavos, já rateado
        total_bruto         INTEGER NOT NULL DEFAULT 0,
        total_liquido       INTEGER NOT NULL DEFAULT 0,
        custo_unitario      INTEGER NOT NULL DEFAULT 0,  -- centavos por unidade base
        custo_total         INTEGER NOT NULL DEFAULT 0,
        lucro               INTEGER NOT NULL DEFAULT 0,
        quantidade_devolvida REAL NOT NULL DEFAULT 0,    -- em unidade base
        ordem               INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS venda_pagamentos (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id      INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        forma         TEXT NOT NULL,   -- Dinheiro | Pix | Cartão de débito | Cartão de crédito | Fiado
        valor         INTEGER NOT NULL DEFAULT 0,
        parcelas      INTEGER NOT NULL DEFAULT 1,
        recebido      REAL NOT NULL DEFAULT 0,           -- quanto foi entregue (para troco em dinheiro)
        operadora     TEXT,                              -- maquininha/banco (opcional)
        documento     TEXT,                              -- NSU/ID da transação (opcional)
        criado_em     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS devolucoes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id      INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        valor         INTEGER NOT NULL DEFAULT 0,        -- centavos devolvidos ao cliente
        motivo        TEXT,
        tipo_reembolso TEXT NOT NULL DEFAULT 'dinheiro', -- dinheiro | credito | nenhum
        usuario_id    INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome  TEXT,
        criado_em     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS devolucao_itens (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        devolucao_id   INTEGER NOT NULL REFERENCES devolucoes(id) ON DELETE CASCADE,
        venda_item_id  INTEGER NOT NULL REFERENCES venda_itens(id) ON DELETE CASCADE,
        produto_id     INTEGER REFERENCES produtos(id) ON DELETE SET NULL,
        quantidade_base REAL NOT NULL,
        valor          INTEGER NOT NULL DEFAULT 0
    )
    """,
    # ------------------------------------------------------------------ financeiro
    """
    CREATE TABLE IF NOT EXISTS contas_receber (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id     INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
        cliente_nome   TEXT,
        venda_id       INTEGER REFERENCES vendas(id) ON DELETE SET NULL,
        descricao      TEXT NOT NULL,
        valor          INTEGER NOT NULL DEFAULT 0,       -- centavos
        valor_pago     INTEGER NOT NULL DEFAULT 0,
        desconto       INTEGER NOT NULL DEFAULT 0,       -- concedido no recebimento
        vencimento     TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'aberta'
                       CHECK (status IN ('aberta','parcial','paga','vencida','cancelada')),
        criado_em      TEXT NOT NULL,
        atualizado_em  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recebimentos (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        conta_id       INTEGER NOT NULL REFERENCES contas_receber(id) ON DELETE CASCADE,
        valor          INTEGER NOT NULL DEFAULT 0,
        forma          TEXT NOT NULL,
        caixa_id       INTEGER REFERENCES caixa_diario(id) ON DELETE SET NULL,
        usuario_id     INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome   TEXT,
        observacao     TEXT,
        criado_em      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contas_pagar (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        fornecedor_id  INTEGER REFERENCES fornecedores(id) ON DELETE SET NULL,
        fornecedor_nome TEXT,
        descricao      TEXT NOT NULL,
        categoria      TEXT NOT NULL DEFAULT 'Outros',
        valor          INTEGER NOT NULL DEFAULT 0,
        valor_pago     INTEGER NOT NULL DEFAULT 0,
        vencimento     TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'aberta'
                       CHECK (status IN ('aberta','parcial','paga','vencida','cancelada')),
        observacao     TEXT,
        criado_em      TEXT NOT NULL,
        atualizado_em  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pagamentos_conta (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        conta_id       INTEGER NOT NULL REFERENCES contas_pagar(id) ON DELETE CASCADE,
        valor          INTEGER NOT NULL DEFAULT 0,
        forma          TEXT NOT NULL,
        caixa_id       INTEGER REFERENCES caixa_diario(id) ON DELETE SET NULL,
        usuario_id     INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome   TEXT,
        observacao     TEXT,
        criado_em      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS caixa_diario (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        data             TEXT NOT NULL,
        usuario_id       INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome     TEXT,
        valor_abertura   INTEGER NOT NULL DEFAULT 0,     -- centavos (fundo de troco)
        valor_fechamento INTEGER NOT NULL DEFAULT 0,     -- contagem real informada
        valor_sistema    INTEGER NOT NULL DEFAULT 0,     -- calculado pelo sistema
        diferenca        INTEGER NOT NULL DEFAULT 0,     -- contagem - sistema (quebra de caixa)
        status           TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto','fechado')),
        abertura_em      TEXT NOT NULL,
        fechamento_em    TEXT,
        observacao       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS caixa_movimentos (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        caixa_id     INTEGER NOT NULL REFERENCES caixa_diario(id) ON DELETE CASCADE,
        tipo         TEXT NOT NULL CHECK (tipo IN ('entrada','saida')),
        categoria    TEXT NOT NULL,   -- Venda, Recebimento fiado, Suprimento, Sangria, Despesa, Devolução, Abertura
        descricao    TEXT,
        valor        INTEGER NOT NULL DEFAULT 0,
        forma        TEXT,            -- Dinheiro | Pix | Cartão ...
        referencia   TEXT,            -- nº do documento de origem (venda/conta/despesa)
        usuario_id   INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome TEXT,
        criado_em    TEXT NOT NULL
    )
    """,
    # ------------------------------------------------------------------ trilha de auditoria
    """
    CREATE TABLE IF NOT EXISTS logs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id   INTEGER,
        usuario_nome TEXT,
        acao         TEXT NOT NULL,     -- login, venda_finalizada, produto_alterado, backup ...
        detalhe      TEXT,
        criado_em    TEXT NOT NULL
    )
    """,
]

V1_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_prod_nome        ON produtos(nome)",
    "CREATE INDEX IF NOT EXISTS idx_prod_categoria   ON produtos(categoria_id)",
    "CREATE INDEX IF NOT EXISTS idx_prod_fornecedor  ON produtos(fornecedor_id)",
    "CREATE INDEX IF NOT EXISTS idx_prod_ativo       ON produtos(ativo)",
    "CREATE INDEX IF NOT EXISTS idx_mov_produto      ON movimentacoes(produto_id, criado_em)",
    "CREATE INDEX IF NOT EXISTS idx_mov_motivo       ON movimentacoes(motivo)",
    "CREATE INDEX IF NOT EXISTS idx_mov_documento    ON movimentacoes(documento_id)",
    "CREATE INDEX IF NOT EXISTS idx_lote_produto     ON lotes(produto_id, validade)",
    "CREATE INDEX IF NOT EXISTS idx_vendas_data      ON vendas(data_venda)",
    "CREATE INDEX IF NOT EXISTS idx_vendas_status    ON vendas(status)",
    "CREATE INDEX IF NOT EXISTS idx_vendas_cliente   ON vendas(cliente_id)",
    "CREATE INDEX IF NOT EXISTS idx_vendas_vendedor  ON vendas(vendedor_id)",
    "CREATE INDEX IF NOT EXISTS idx_vendas_caixa     ON vendas(caixa_id)",
    "CREATE INDEX IF NOT EXISTS idx_venda_itens_venda   ON venda_itens(venda_id)",
    "CREATE INDEX IF NOT EXISTS idx_venda_itens_produto ON venda_itens(produto_id)",
    "CREATE INDEX IF NOT EXISTS idx_pag_venda        ON venda_pagamentos(venda_id)",
    "CREATE INDEX IF NOT EXISTS idx_cr_cliente       ON contas_receber(cliente_id)",
    "CREATE INDEX IF NOT EXISTS idx_cr_status        ON contas_receber(status, vencimento)",
    "CREATE INDEX IF NOT EXISTS idx_cp_status        ON contas_pagar(status, vencimento)",
    "CREATE INDEX IF NOT EXISTS idx_caixa_data       ON caixa_diario(data)",
    "CREATE INDEX IF NOT EXISTS idx_caixamov_caixa   ON caixa_movimentos(caixa_id)",
    "CREATE INDEX IF NOT EXISTS idx_logs_data        ON logs(criado_em)",
]

# As triggers mantêm o campo produtos.estoque_atual sempre coerente com as movimentações
# — mesmo que alguém altere o banco por fora, o saldo não se perde.
V1_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_mov_ins
    AFTER INSERT ON movimentacoes
    BEGIN
        UPDATE produtos
           SET estoque_atual = COALESCE(estoque_atual,0) +
               CASE NEW.tipo WHEN 'entrada' THEN NEW.quantidade
                             WHEN 'saida'   THEN -NEW.quantidade
                             ELSE NEW.quantidade END
         WHERE id = NEW.produto_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_mov_del
    AFTER DELETE ON movimentacoes
    BEGIN
        UPDATE produtos
           SET estoque_atual = COALESCE(estoque_atual,0) -
               CASE OLD.tipo WHEN 'entrada' THEN OLD.quantidade
                             WHEN 'saida'   THEN -OLD.quantidade
                             ELSE OLD.quantidade END
         WHERE id = OLD.produto_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_mov_upd
    AFTER UPDATE OF quantidade, tipo ON movimentacoes
    BEGIN
        UPDATE produtos
           SET estoque_atual = COALESCE(estoque_atual,0)
               - (CASE OLD.tipo WHEN 'entrada' THEN OLD.quantidade
                                WHEN 'saida'   THEN -OLD.quantidade
                                ELSE OLD.quantidade END)
               + (CASE NEW.tipo WHEN 'entrada' THEN NEW.quantidade
                                WHEN 'saida'   THEN -NEW.quantidade
                                ELSE NEW.quantidade END)
         WHERE id = NEW.produto_id;
    END
    """,
    # Sincroniza o saldo do lote com as movimentações que apontam para ele.
    """
    CREATE TRIGGER IF NOT EXISTS trg_lote_mov_ins
    AFTER INSERT ON movimentacoes
    WHEN NEW.lote_id IS NOT NULL
    BEGIN
        UPDATE lotes
           SET quantidade_atual = MAX(0, COALESCE(quantidade_atual,0) +
               CASE NEW.tipo WHEN 'saida' THEN -NEW.quantidade ELSE NEW.quantidade END),
               atualizado_em = NEW.criado_em
         WHERE id = NEW.lote_id;
    END
    """,
]

# Visões prontas usadas pelos relatórios e pelas telas.
V1_VISOES = [
    """
    CREATE VIEW IF NOT EXISTS vw_produtos_completo AS
    SELECT p.*,
           c.nome  AS categoria_nome,
           f.nome  AS fornecedor_nome,
           f.telefone AS fornecedor_telefone,
           ub.nome AS unidade_base_nome,
           uv.nome AS unidade_venda_nome,
           (p.preco_venda - p.preco_custo) AS margem_valor,
           CASE WHEN p.preco_venda > 0
                THEN ROUND((p.preco_venda - p.preco_custo) * 100.0 / p.preco_venda, 2)
                ELSE 0 END AS margem_pct,
           (COALESCE(p.estoque_atual,0) * p.preco_custo)  AS estoque_custo,
           (COALESCE(p.estoque_atual,0) * p.preco_venda)  AS estoque_venda,
           (SELECT COALESCE(SUM(quantidade_base),0)
              FROM venda_itens vi
              JOIN vendas v ON v.id = vi.venda_id
             WHERE vi.produto_id = p.id
               AND v.status IN ('concluida','parcialmente_devolvida')) AS total_vendido,
           (SELECT MAX(v2.criada_em)
              FROM venda_itens vi2
              JOIN vendas v2 ON v2.id = vi2.venda_id
             WHERE vi2.produto_id = p.id
               AND v2.status IN ('concluida','parcialmente_devolvida')) AS ultima_venda_em
      FROM produtos p
      LEFT JOIN categorias  c  ON c.id = p.categoria_id
      LEFT JOIN fornecedores f ON f.id = p.fornecedor_id
      LEFT JOIN unidades ub ON ub.sigla = p.unidade_base
      LEFT JOIN unidades uv ON uv.sigla = p.unidade_venda
    """,
    """
    CREATE VIEW IF NOT EXISTS vw_estoque_baixo AS
    SELECT * FROM vw_produtos_completo
     WHERE ativo = 1
       AND estoque_minimo > 0
       AND COALESCE(estoque_atual,0) <= estoque_minimo
    """,
    """
    CREATE VIEW IF NOT EXISTS vw_lotes_validade AS
    SELECT l.*, p.codigo AS produto_codigo, p.nome AS produto_nome,
           p.unidade_base,
           CAST(julianday(l.validade) - julianday('now','localtime') AS INTEGER) AS dias_para_vencer
      FROM lotes l
      JOIN produtos p ON p.id = l.produto_id
     WHERE p.ativo = 1 AND l.quantidade_atual > 0 AND l.validade IS NOT NULL AND l.validade <> ''
    """,
    """
    CREATE VIEW IF NOT EXISTS vw_valor_devolvido AS
    SELECT d.venda_id AS venda_id,
           COALESCE(SUM(d.valor), 0)              AS devolvido,
           COALESCE(SUM(di.valor), 0)             AS custo_devolvido,
           COUNT(DISTINCT d.id)                   AS qtd_devolucoes
      FROM devolucoes d
      LEFT JOIN devolucao_itens di ON di.devolucao_id = d.id
     GROUP BY d.venda_id
    """,
    """
    CREATE VIEW IF NOT EXISTS vw_vendas_resumo AS
    SELECT v.*,
           (SELECT COUNT(*) FROM venda_itens vi WHERE vi.venda_id = v.id) AS qtd_itens,
           (SELECT COALESCE(SUM(vi.quantidade_base),0) FROM venda_itens vi WHERE vi.venda_id = v.id) AS qtd_produtos,
           COALESCE((SELECT vd.devolvido FROM vw_valor_devolvido vd WHERE vd.venda_id = v.id), 0) AS valor_devolvido,
           COALESCE((SELECT vd.custo_devolvido FROM vw_valor_devolvido vd WHERE vd.venda_id = v.id), 0) AS custo_devolvido,
           -- Valores líquidos (descontando devoluções): são estes que entram nos relatórios.
           CASE WHEN v.status = 'cancelada' THEN 0
                ELSE MAX(0, v.total - COALESCE((SELECT vd.devolvido FROM vw_valor_devolvido vd WHERE vd.venda_id = v.id),0))
           END AS total_liquido,
           CASE WHEN v.status = 'cancelada' THEN 0
                ELSE v.lucro - COALESCE((SELECT vd.custo_devolvido FROM vw_valor_devolvido vd WHERE vd.venda_id = v.id),0)
           END AS lucro_liquido
      FROM vendas v
    """,
]

# --------------------------------------------------------------------------------------
# Sementes (dados iniciais)
# --------------------------------------------------------------------------------------

#: (sigla, nome, família, fator na unidade padrão, ordem de exibição)
UNIDADES_SEMENTE = [
    # Quantidade — a base é sempre "un"; caixa/pacote/dúzia dependem do fator do produto
    ("un",    "Unidade",        "quantidade",  1.0,    1),
    ("cx",    "Caixa",          "quantidade",  1.0,    2),
    ("pct",   "Pacote",         "quantidade",  1.0,    3),
    ("dz",    "Dúzia",          "quantidade",  12.0,   4),
    ("par",   "Par",            "quantidade",  2.0,    5),
    ("fd",    "Fardo",          "quantidade",  1.0,    6),
    ("kit",   "Kit",            "quantidade",  1.0,    7),
    ("pc",    "Peça",           "quantidade",  1.0,    8),
    ("rl",    "Rolo",           "quantidade",  1.0,    9),
    ("fl",    "Folha",          "quantidade",  1.0,   10),
    ("serv",  "Serviço",        "quantidade",  1.0,   11),
    # Massa — base: grama
    ("mg",    "Miligrama",      "massa",       0.001,  20),
    ("g",     "Grama",          "massa",       1.0,    21),
    ("kg",    "Quilograma",     "massa",       1000.0, 22),
    ("t",     "Tonelada",       "massa",       1000000.0, 23),
    # Volume — base: mililitro
    ("ml",    "Mililitro",      "volume",      1.0,    30),
    ("l",     "Litro",          "volume",      1000.0, 31),
    ("m3",    "Metro cúbico",   "volume",      1000000.0, 32),
    # Comprimento — base: milímetro
    ("mm",    "Milímetro",      "comprimento", 1.0,    40),
    ("cm",    "Centímetro",     "comprimento", 10.0,   41),
    ("m",     "Metro",          "comprimento", 1000.0, 42),
    ("km",    "Quilômetro",     "comprimento", 1000000.0, 43),
]

CATEGORIAS_SEMENTE = [
    "Alimentos", "Bebidas", "Higiene e limpeza", "Papelaria", "Ferramentas",
    "Materiais de construção", "Elétrica", "Hidráulica", "EPI / Segurança",
    "Peças e acessórios", "Serviços", "Outros",
]

#: Formas de pagamento aceitas pelo PDV (a última, Fiado, gera conta a receber).
FORMAS_PAGAMENTO = ["Dinheiro", "Pix", "Cartão de débito", "Cartão de crédito", "Fiado"]
FORMA_FIADO = "Fiado"

#: Motivos de movimentação de estoque, com o tipo correspondente.
MOTIVOS_ENTRADA = {
    "compra": "Compra / entrada de mercadoria",
    "devolucao_cliente": "Devolução de cliente",
    "transferencia_entrada": "Transferência recebida",
    "producao": "Produção própria",
    "ajuste_positivo": "Ajuste de inventário (+)",
    "outros": "Outras entradas",
}
MOTIVOS_SAIDA = {
    "venda": "Venda",
    "devolucao_fornecedor": "Devolução a fornecedor",
    "perda": "Perda / avaria",
    "vencimento": "Baixa por vencimento",
    "consumo_interno": "Consumo interno / uso próprio",
    "transferencia_saida": "Transferência enviada",
    "ajuste_negativo": "Ajuste de inventário (−)",
    "outros": "Outras saídas",
}
MOTIVOS_AJUSTE = {
    "ajuste_inventario": "Ajuste de inventário",
    "inventario_inicial": "Inventário inicial (implantação)",
    "correcao": "Correção de saldo",
}

CATEGORIAS_DESPESA = [
    "Fornecedores", "Aluguel", "Energia elétrica", "Água", "Internet / Telefone",
    "Salários e encargos", "Impostos e taxas", "Manutenção", "Combustível",
    "Frete e logística", "Marketing", "Material de escritório", "Outros",
]

#: Configurações padrão gravadas na tabela ``config``.
CONFIG_PADRAO = {
    "empresa_nome": "MR Logística",
    "empresa_documento": "",
    "empresa_endereco": "",
    "empresa_telefone": "",
    "empresa_email": "",
    "recibo_titulo": "MR Logística",
    "recibo_mensagem": "Obrigado pela preferência! Volte sempre.",
    "recibo_mostrar_endereco": "1",
    "tema": "claro",
    "alerta_estoque_ativo": "1",
    "alerta_validade_dias": "30",
    "backup_automatico": "1",
    "manter_backups": "10",
    "venda_exige_caixa_aberto": "1",
    "venda_permite_preco_zero": "0",
    "venda_permite_estoque_negativo": "0",
    "etiquetas_por_pagina": "14",
    "pdv_bipador_ativo": "1",
    "pdv_confirmar_quantidade": "0",
    "recibo_largura": "80mm",
    "ultimo_usuario": "",
    "versao_esquema_instalada": "",
}


def criar_esquema_v1(cur) -> None:
    """Cria todas as tabelas, índices, triggers e visões da versão 1."""
    for sql in V1_TABELAS:
        cur.execute(sql)
    for sql in V1_INDICES:
        cur.execute(sql)
    for sql in V1_TRIGGERS:
        cur.execute(sql)
    for sql in V1_VISOES:
        cur.execute(sql)


def semear_v1(cur) -> None:
    """Insere os dados iniciais: unidades, categorias, configurações e usuário administrador."""
    from .utils import agora

    cur.executemany(
        "INSERT OR IGNORE INTO unidades (sigla, nome, familia, fator_base, ordem) VALUES (?,?,?,?,?)",
        UNIDADES_SEMENTE,
    )
    for nome in CATEGORIAS_SEMENTE:
        cur.execute(
            "INSERT OR IGNORE INTO categorias (nome, descricao, ativo, criado_em) VALUES (?,?,1,?)",
            (nome, "", agora()),
        )
    for chave, valor in CONFIG_PADRAO.items():
        cur.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?,?)", (chave, str(valor)))

    # Usuário administrador padrão: login "admin", senha "admin".
    # O sistema exige a troca dessa senha no primeiro acesso (configuração "trocar_senha").
    from .usuarios import criar_hash_senha

    cur.execute(
        """INSERT OR IGNORE INTO usuarios
           (nome, login, senha_hash, perfil, email, telefone, ativo, trocar_senha, criado_em)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "Administrador",
            "admin",
            criar_hash_senha("admin"),
            "administrador",
            "",
            "",
            1,
            1,  # obriga a troca da senha padrão no primeiro acesso
            agora(),
        ),
    )


#: Lista ordenada de migrações. Para evoluir o banco, adicione ``(_v2, semear_v2)`` etc.
MIGRACOES = [
    (1, criar_esquema_v1, semear_v1),
]
