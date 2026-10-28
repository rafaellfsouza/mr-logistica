"""
Teste de fumaça (smoke test) do núcleo do MR Logística.

Simula **um dia inteiro de operação** de ponta a ponta, sem interface gráfica:

abertura de caixa → cadastro de fornecedor/cliente/categoria → cadastro de produtos
(com unidades diferentes e controle de lote) → entrada de mercadoria → venda com
bipador e venda fracionada → pagamento misto com troco → venda no fiado →
recebimento parcial → devolução parcial → cancelamento de venda → sangria/suprimento
→ despesa → contas a pagar → relatórios → exportação Excel/PDF → etiquetas →
backup → fechamento de caixa.

Execute com::

    python tests/smoke_test.py

Ele usa uma pasta de dados temporária (não toca nos seus dados reais) e imprime
PASSO/OK em cada etapa. Se qualquer etapa falhar, o script termina com erro.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# Garante que o pacote "mrlog" seja encontrado mesmo rodando de outra pasta.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PASTA_TEMPORARIA = tempfile.mkdtemp(prefix="mrlog_smoke_")
os.environ["MRLOG_DATA_DIR"] = PASTA_TEMPORARIA

_PASSOS = 0
_FALHAS: list[str] = []


def passo(descricao: str):
    """Marca o início de uma etapa do teste."""
    global _PASSOS
    _PASSOS += 1
    print(f"[{_PASSOS:02d}] {descricao} ... ", end="", flush=True)


def ok(extra: str = "") -> None:
    print(f"OK {extra}".rstrip())


def falhou(erro: Exception) -> None:
    _FALHAS.append(str(erro))
    print("FALHOU")
    traceback.print_exc()


def checar(condicao: bool, mensagem: str) -> None:
    """Afirmação com mensagem amigável."""
    if not condicao:
        raise AssertionError(mensagem)


def main() -> int:  # noqa: C901 - teste sequencial e longo de propósito
    from mrlog import (
        backup,
        caixa,
        categorias,
        clientes,
        contas_pagar,
        contas_receber,
        estoque,
        etiquetas,
        exportacao,
        fornecedores,
        impressao,
        produtos,
        relatorios,
        unidades,
        usuarios,
        vendas,
    )
    from mrlog.banco import Banco
    from mrlog.utils import formatar_dinheiro as fd

    banco = Banco()
    print(f"Banco de teste: {banco.caminho}")

    # ------------------------------------------------------------------ 1. estrutura
    passo("Estrutura do banco (tabelas, unidades, categorias, usuário admin)")
    try:
        checar(banco.versao_atual() >= 1, "esquema não migrado")
        checar(len(banco.tabelas()) >= 18, f"poucas tabelas: {banco.tabelas()}")
        checar(len(unidades.todas(banco)) >= 20, "unidades não semeadas")
        checar(len(categorias.listar(banco)) >= 10, "categorias não semeadas")
        checar(unidades.converter(1, "kg", "g", banco=banco) == 1000.0, "conversão kg->g errada")
        checar(unidades.converter(250, "g", "kg", banco=banco) == 0.25, "conversão g->kg errada")
        admin = usuarios.autenticar(banco, "admin", "admin")
        checar(admin is not None, "login admin/admin falhou")
        checar(usuarios.pode(admin, "configuracoes"), "admin sem permissão total")
        ok(f"(admin={admin['nome']}, {len(banco.tabelas())} tabelas)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 2. cadastros
    passo("Cadastros (fornecedor, cliente, categoria)")
    try:
        forn_id = fornecedores.criar(
            banco,
            {
                "nome": "Distribuidora Alfa",
                "cnpj_cpf": "12345678000195",
                "cidade": "Belo Horizonte",
                "uf": "MG",
                "prazo_dias": 28,
                "telefone": "3133334444",
            },
            autor=admin,
        )
        cat_id = categorias.criar(banco, "Mercearia", "Itens de mercearia", autor=admin)
        cli_id = clientes.criar(
            banco, {"nome": "Maria Souza", "cpf_cnpj": "12345678909", "limite_credito": "200,00"}, autor=admin
        )
        checar(fornecedores.pegar(banco, forn_id)["nome"] == "Distribuidora Alfa", "fornecedor não gravado")
        checar(clientes.pegar(banco, cli_id)["limite_credito"] == 20000, "limite de crédito errado")
        try:
            clientes.criar(banco, {"nome": "Duplicada", "cpf_cnpj": "12345678909"})
            raise AssertionError("CPF duplicado não foi bloqueado")
        except clientes.ErroCliente:
            pass
        ok(f"(fornecedor #{forn_id}, cliente #{cli_id})")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 3. produtos
    passo("Produtos: unidade fracionada (kg), caixa com fator, lote/validade")
    try:
        cafe = produtos.criar(
            banco,
            {
                "codigo": "P0001",
                "codigo_barras": "7891000315507",
                "nome": "Café torrado e moído 1 kg",
                "descricao": "Café superior",
                "categoria_id": cat_id,
                "fornecedor_id": forn_id,
                "marca": "Café Bom",
                "unidade_base": "kg",
                "unidade_venda": "kg",
                "preco_custo": "20,00",
                "preco_venda": "32,00",
                "estoque_minimo": 2,
                "permite_fracionar": 1,
                "decimais": 3,
                "peso_gramas": 1000,
            },
            estoque_inicial=10,
            autor=admin,
        )
        refri = produtos.criar(
            banco,
            {
                "codigo": "P0002",
                "nome": "Refrigerante cola 2 L",
                "categoria_id": cat_id,
                "fornecedor_id": forn_id,
                "unidade_base": "un",
                "unidade_venda": "cx",
                "fator_venda": 6,
                "preco_custo": "4,50",
                "preco_venda": "48,00",
                "estoque_minimo": 12,
                "controla_lote": 1,
                "validade_dias": 180,
            },
            autor=admin,
        )
        parafuso = produtos.criar(
            banco,
            {"codigo": "P0003", "nome": "Parafuso 1/4", "unidade_base": "un", "preco_custo": "0,10", "preco_venda": "0,50"},
            estoque_inicial=100,
            autor=admin,
        )
        p = produtos.pegar(banco, cafe)
        checar(p["margem_pct"] == 37.5, f"margem errada: {p['margem_pct']}")
        checar(estoque.saldo(banco, cafe) == 10.0, "estoque inicial não lançado")
        checar(produtos.preco_por_unidade_base(produtos.pegar(banco, refri)) == 800, "preço por unidade base errado")
        checar(unidades.converter_para_base(produtos.pegar(banco, cafe), 250, "g", banco) == 0.25, "250 g != 0,25 kg")
        checar(unidades.converter_para_base(produtos.pegar(banco, refri), 1, "cx", banco) == 6.0, "1 cx != 6 un")
        checar(produtos.por_codigo_barras(banco, "7891000315507")["id"] == cafe, "busca por código de barras falhou")
        checar(produtos.resolver_bipagem(banco, "7891000315507")[1] == "barras", "bipagem não reconhecida")
        checar(produtos.resolver_bipagem(banco, "P0003")[1] == "codigo", "bipagem por código interno falhou")
        checar(produtos.resolver_bipagem(banco, "9999999999999")[0] is None, "código inexistente retornou produto")
        ok(f"({produtos.resumo(banco)['total']} produtos)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 4. estoque
    passo("Estoque: entrada com lote, custo médio, saída, ajuste e histórico")
    try:
        estoque.entrada(banco, refri, 24, motivo="compra", custo_unitario=450, lote_numero="L1", autor=admin)
        estoque.entrada(banco, refri, 12, motivo="compra", custo_unitario=510, lote_numero="L2", autor=admin)
        checar(estoque.saldo(banco, refri) == 36.0, "saldo do refri errado")
        custo_medio = produtos.pegar(banco, refri)["preco_custo"]
        esperado = int(round((24 * 450 + 12 * 510) / 36))
        checar(custo_medio == esperado, f"custo médio {custo_medio} != {esperado}")
        lotes = estoque.lotes_do_produto(banco, refri)
        checar(len(lotes) == 2, f"esperava 2 lotes, vieram {len(lotes)}")
        estoque.saida(banco, refri, 1, motivo="venda", unidade="cx", autor=admin)
        checar(estoque.saldo(banco, refri) == 30.0, "saída de 1 cx não baixou 6 un")
        checar(estoque.lotes_do_produto(banco, refri)[0]["numero"] == "L1", "FEFO não consumiu o lote mais antigo")
        resultado = estoque.ajuste(banco, cafe, 9.5, observacao="Contagem física", autor=admin)
        checar(resultado["diferenca"] == -0.5, f"ajuste calculou {resultado['diferenca']}")
        checar(estoque.saldo(banco, cafe) == 9.5, "saldo após ajuste errado")
        historico = estoque.historico(banco, produto_id=cafe)
        checar(len(historico) >= 2, "histórico incompleto")
        checar(estoque.verificar_saldos(banco) == [], "saldo gravado diverge do histórico")
        try:
            estoque.saida(banco, refri, 1000, motivo="venda", autor=admin)
            raise AssertionError("saída acima do estoque não foi bloqueada")
        except estoque.ErroEstoque:
            pass
        carrinho_teste = vendas.Carrinho(banco, admin)
        try:
            carrinho_teste.adicionar(produtos.pegar(banco, refri), 100, unidade="cx")
            raise AssertionError("carrinho aceitou quantidade acima do estoque")
        except vendas.ErroVenda:
            pass
        ok(f"(custo médio {fd(custo_medio)}, {len(historico)} movimentos do café)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 5. caixa
    passo("Caixa: abertura, suprimento, sangria e despesa")
    try:
        try:
            caixa.sangria(banco, 100, autor=admin)
            raise AssertionError("sangria sem caixa aberto não foi bloqueada")
        except caixa.ErroCaixa:
            pass
        caixa_id = caixa.abrir(banco, "50,00", observacao="Fundo de troco", autor=admin)
        try:
            caixa.abrir(banco, "10,00", autor=admin)
            raise AssertionError("dois caixas abertos ao mesmo tempo")
        except caixa.ErroCaixa:
            pass
        caixa.suprimento(banco, "20,00", "Reforço de troco", autor=admin)
        caixa.lancar_despesa(banco, "Café para a equipe", "8,50", "Outros", "Dinheiro", admin)
        caixa.sangria(banco, "10,00", "Depósito bancário", autor=admin)
        posicao = caixa.por_forma(banco, caixa_id)
        checar(posicao["Dinheiro"]["saldo"] == 5150, f"saldo em dinheiro {posicao['Dinheiro']['saldo']} != 5150")
        ok(f"(saldo gaveta {fd(caixa.valor_sistema(banco, caixa_id))})")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 6. PDV
    passo("PDV: bipador (mesmo produto 2x), venda fracionada e pagamento misto com troco")
    try:
        carrinho = vendas.Carrinho(banco, admin)
        produto_bipado, tipo = produtos.resolver_bipagem(banco, "7891000315507")
        checar(tipo == "barras" and produto_bipado is not None, "bipagem falhou")
        item1 = carrinho.adicionar(produto_bipado, 1)                 # 1 kg
        item2 = carrinho.adicionar(produto_bipado, 1)                 # bipou de novo
        checar(item1 is item2 and item2.quantidade == 2.0, "bipar o mesmo produto não somou quantidade")
        carrinho.adicionar(produtos.pegar(banco, cafe), 0.25, unidade="kg", sobrescrever=True)  # 250 g avulso
        carrinho.adicionar(produtos.pegar(banco, refri), 1, unidade="cx")
        carrinho.adicionar(produtos.pegar(banco, parafuso), 10)
        carrinho.definir_cliente(clientes.pegar(banco, cli_id))
        totais = carrinho.totais()
        # 2 kg (R$64) + 0,25 kg (R$8) + 1 cx (R$48) + 10 un (R$5) = R$125,00
        checar(totais.subtotal == 12500, f"subtotal {fd(totais.subtotal)} != R$ 125,00")
        carrinho.definir_desconto(percentual=10, limite_pct=usuarios.limite_desconto(admin))
        totais = carrinho.totais()
        checar(totais.total == 11250, f"total com desconto {fd(totais.total)} != R$ 112,50")
        rateio = carrinho.ratear_desconto()
        checar(sum(r["desconto_total"] for r in rateio) == totais.desconto_itens + totais.desconto_venda,
               "rateio do desconto não fecha")
        resultado = vendas.finalizar(
            banco,
            carrinho,
            [
                {"forma": "Dinheiro", "valor": "60,00", "recebido": "100,00"},
                {"forma": "Pix", "valor": totais.total - 6000},
            ],
            cliente=clientes.pegar(banco, cli_id),
            vendedor=admin,
        )
        venda_id = resultado["venda_id"]
        checar(resultado["troco"] == 4000, f"troco {fd(resultado['troco'])} != R$ 40,00")
        checar(estoque.saldo(banco, cafe) == 7.25, f"saldo do café {estoque.saldo(banco, cafe)} != 7,25")
        checar(estoque.saldo(banco, refri) == 24.0, "baixa da caixa errada")
        checar(estoque.saldo(banco, parafuso) == 90.0, "baixa dos parafusos errada")
        checar(len(carrinho) == 0, "carrinho não foi limpo após a venda")
        checar(estoque.verificar_saldos(banco) == [], "saldo divergente após a venda")
        ok(f"(cupom {resultado['numero']:06d} = {fd(resultado['total'])}, troco {fd(resultado['troco'])})")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 7. fiado
    passo("Financeiro: venda no fiado, limite de crédito e recebimento parcial")
    try:
        carrinho = vendas.Carrinho(banco, admin)
        carrinho.adicionar(produtos.pegar(banco, refri), 2, unidade="un")
        carrinho.definir_cliente(clientes.pegar(banco, cli_id))
        fiado = vendas.finalizar(
            banco,
            carrinho,
            [{"forma": "Fiado", "valor": 1600}],
            cliente=clientes.pegar(banco, cli_id),
            vendedor=admin,
            vencimento_fiado="30/12/2030",
        )
        conta_id = fiado["conta_receber_id"]
        checar(conta_id, "conta a receber não foi criada")
        conta = contas_receber.pegar(banco, conta_id)
        checar(conta["saldo"] == 1600, f"saldo do fiado {fd(conta['saldo'])} != R$ 16,00")
        rec = contas_receber.receber(banco, conta_id, "6,00", forma="Pix", autor=admin)
        checar(rec["saldo"] == 1000 and rec["status"] == "parcial", f"recebimento parcial errado: {rec}")
        try:
            contas_receber.receber(banco, conta_id, "500,00", autor=admin)
            raise AssertionError("recebimento maior que o saldo não foi bloqueado")
        except contas_receber.ErroContaReceber:
            pass
        # Cliente com limite apertado: a venda no fiado precisa ser bloqueada.
        cli_limite = clientes.criar(banco, {"nome": "José Limite", "limite_credito": "10,00"}, autor=admin)
        carrinho = vendas.Carrinho(banco, admin)
        carrinho.adicionar(produtos.pegar(banco, refri), 2, unidade="un")
        try:
            vendas.finalizar(
                banco, carrinho, [{"forma": "Fiado", "valor": 1600}],
                cliente=clientes.pegar(banco, cli_limite), vendedor=admin,
            )
            raise AssertionError("limite de crédito não foi respeitado")
        except vendas.ErroVenda as exc:
            checar("Limite de crédito excedido" in str(exc), f"mensagem inesperada: {exc}")
        carrinho = vendas.Carrinho(banco, admin)
        carrinho.adicionar(produtos.pegar(banco, cafe), 1)
        try:
            vendas.finalizar(banco, carrinho, [{"forma": "Fiado", "valor": 3200}], vendedor=admin)
            raise AssertionError("fiado sem cliente não foi bloqueado")
        except vendas.ErroVenda:
            pass
        ok(f"(fiado {fd(conta['valor'])}, saldo {fd(contas_receber.pegar(banco, conta_id)['saldo'])})")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 8. devolução
    passo("Vendas: devolução parcial e cancelamento com estorno de estoque")
    try:
        devoluveis = vendas.itens_devoluveis(banco, venda_id)
        item_cafe = next(i for i in devoluveis if i["codigo"] == "P0001" and i["quantidade_disponivel"] >= 0.5)
        saldo_antes = estoque.saldo(banco, cafe)
        devolucao = vendas.devolver(
            banco, venda_id, [{"venda_item_id": item_cafe["venda_item_id"], "quantidade_base": 0.5}],
            motivo="Cliente desistiu", tipo_reembolso="dinheiro", autor=admin,
        )
        # 0,5 kg de um item de 2 kg cujo total líquido (já com 10% de desconto) era R$ 57,60:
        # a devolução é proporcional -> R$ 14,40.
        checar(devolucao["valor"] == 1440, f"valor devolvido {fd(devolucao['valor'])} != R$ 14,40")
        checar(devolucao["status"] == "parcialmente_devolvida", f"status {devolucao['status']}")
        checar(abs(estoque.saldo(banco, cafe) - (saldo_antes + 0.5)) < 1e-6, "estoque não foi reposto na devolução")
        checar(vendas.pegar(banco, venda_id)["total_liquido"] == 11250 - 1440, "receita líquida errada após devolução")

        carrinho = vendas.Carrinho(banco, admin)
        carrinho.adicionar(produtos.pegar(banco, parafuso), 20)
        venda_cancelar = vendas.finalizar(
            banco, carrinho, [{"forma": "Cartão de crédito", "valor": 1000, "parcelas": 2}], vendedor=admin
        )
        saldo_parafuso = estoque.saldo(banco, parafuso)
        cancelamento = vendas.cancelar(banco, venda_cancelar["venda_id"], motivo="Lançamento errado", autor=admin)
        checar(cancelamento["total_reembolso"] == 1000, "estorno do cartão errado")
        checar(estoque.saldo(banco, parafuso) == saldo_parafuso + 20, "estoque não voltou no cancelamento")
        checar(vendas.pegar(banco, venda_cancelar["venda_id"])["status"] == "cancelada", "status não é cancelada")
        try:
            vendas.cancelar(banco, venda_cancelar["venda_id"], motivo="duas vezes", autor=admin)
            raise AssertionError("cancelamento duplicado não foi bloqueado")
        except vendas.ErroVenda:
            pass
        try:
            vendas.cancelar(banco, venda_id, "", autor=admin)
            raise AssertionError("cancelamento sem motivo não foi bloqueado")
        except vendas.ErroVenda:
            pass
        ok(f"(devolvido {fd(devolucao['valor'])}, cancelada a venda {venda_cancelar['numero']:06d})")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 9. contas a pagar
    passo("Contas a pagar: lançamento, pagamento parcial e quitação")
    try:
        conta_pagar_id = contas_pagar.criar(
            banco, "Compra de mercadoria — Distribuidora Alfa", "1.200,00", vencimento="30/12/2030",
            fornecedor_id=forn_id, categoria="Fornecedores", autor=admin,
        )
        contas_pagar.pagar(banco, conta_pagar_id, "200,00", "Pix", autor=admin)
        parcial = contas_pagar.pegar(banco, conta_pagar_id)
        checar(parcial["status"] == "parcial" and parcial["saldo"] == 100000, f"conta parcial errada: {parcial['status']}")
        try:
            contas_pagar.quitar(banco, conta_pagar_id, "Dinheiro", autor=admin)
            raise AssertionError("pagamento em dinheiro acima da gaveta não foi bloqueado")
        except contas_pagar.ErroContaPagar:
            pass
        contas_pagar.quitar(banco, conta_pagar_id, "Pix", autor=admin)
        checar(contas_pagar.pegar(banco, conta_pagar_id)["status"] == "paga", "conta não quitou")
        resumo = contas_pagar.resumo(banco)
        checar(resumo["pago_total"] == 120000, f"total pago {fd(resumo['pago_total'])}")
        ok(f"(pago {fd(resumo['pago_total'])} em {resumo['qtd_abertas']} conta(s) em aberto)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 10. relatórios
    passo("Relatórios: 12 relatórios com linhas e totais")
    try:
        nomes = relatorios.disponiveis()
        checar(len(nomes) >= 12, f"só {len(nomes)} relatórios disponíveis")
        lotes_365 = relatorios.gerar(banco, "lotes_validade", {"dias": 365})
        checar(lotes_365["linhas"], "relatório de lotes/validade não encontrou os lotes do refri")
        despesas = relatorios.gerar(banco, "despesas", {})
        checar(any(l["categoria"] == "Fornecedores" for l in despesas["linhas"]),
               "despesas pagas não apareceram no relatório (regime de caixa)")
        for chave in nomes:
            dados = relatorios.gerar(banco, chave, {})
            checar("colunas" in dados and "linhas" in dados, f"relatório {chave} sem estrutura")
            print(f"\n      - {dados['titulo']}: {len(dados['linhas'])} linha(s)", end="")
        resumo_vendas = relatorios.gerar(banco, "vendas_por_dia", {})
        checar(resumo_vendas["linhas"], "relatório de vendas por dia vazio")
        mais_vendidos = relatorios.gerar(banco, "produtos_mais_vendidos", {"limite": 5})
        checar(mais_vendidos["linhas"], "produtos mais vendidos vazio")
        lucro = relatorios.gerar(banco, "lucro", {})
        checar(lucro["linhas"], "relatório de lucro vazio")
        ok("")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 11. exportação
    passo("Exportação: Excel (.xlsx), CSV e PDF")
    try:
        destino = Path(PASTA_TEMPORARIA) / "saida"
        destino.mkdir(exist_ok=True)
        dados = relatorios.gerar(banco, "vendas_por_produto", {})
        xls = exportacao.exportar(dados, destino / "vendas.xlsx", formato="xlsx")
        pdf = exportacao.exportar(dados, destino / "vendas.pdf", formato="pdf")
        csv = exportacao.exportar(dados, destino / "vendas.csv", formato="csv")
        for arquivo in (xls, pdf, csv):
            checar(Path(arquivo).exists(), f"{arquivo} não foi criado")
        checar(Path(xls).stat().st_size > 3000, f"xlsx muito pequeno: {Path(xls).stat().st_size} bytes")
        checar(Path(pdf).stat().st_size > 1000, f"pdf muito pequeno: {Path(pdf).stat().st_size} bytes")
        checar(Path(csv).stat().st_size > 100, f"csv muito pequeno: {Path(csv).stat().st_size} bytes")
        recibo = impressao.gerar_recibo_pdf(banco, venda_id, destino / "recibo.pdf")
        checar(Path(recibo).exists(), "recibo não gerado")
        ok(f"(xlsx {Path(xls).stat().st_size} bytes, pdf {Path(pdf).stat().st_size} bytes)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 12. etiquetas
    passo("Etiquetas: geração de código interno, PNG e folha em PDF")
    try:
        sem_barras = produtos.listar(banco, apenas_sem_barras=True)
        checar(sem_barras, "deveria existir produto sem código de barras")
        novo_codigo = etiquetas.gerar_codigo_para_produto(banco, sem_barras[0]["id"], autor=admin)
        checar(novo_codigo and len(novo_codigo) == 13, f"código gerado inválido: {novo_codigo}")
        png = etiquetas.salvar_png(banco, sem_barras[0]["id"], Path(PASTA_TEMPORARIA) / "etiqueta.png")
        checar(Path(png).exists() and Path(png).stat().st_size > 200, "PNG da etiqueta não gerado")
        pdf = etiquetas.gerar_pdf(banco, [sem_barras[0]["id"]] * 14, Path(PASTA_TEMPORARIA) / "etiquetas.pdf")
        checar(Path(pdf).exists() and Path(pdf).stat().st_size > 1000, "folha de etiquetas não gerada")
        ok(f"({novo_codigo})")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 13. usuários
    passo("Usuários e permissões: vendedor limitado, troca de senha")
    try:
        vend_id = usuarios.criar(
            banco,
            {"nome": "Carlos Vendedor", "login": "carlos", "perfil": "vendedor"},
            "senha123",
            autor=admin,
        )
        vendedor = usuarios.autenticar(banco, "carlos", "senha123")
        checar(vendedor is not None, "login do vendedor falhou")
        checar(usuarios.pode(vendedor, "pdv"), "vendedor sem acesso ao PDV")
        checar(not usuarios.pode(vendedor, "configuracoes"), "vendedor com acesso a configurações")
        checar(not usuarios.pode(vendedor, "usuarios"), "vendedor com acesso a usuários")
        checar(usuarios.limite_desconto(vendedor) == 10.0, "limite de desconto do vendedor errado")
        usuarios.alterar_senha(banco, vend_id, "senha123", "novaSenha1", "novaSenha1", autor=vendedor)
        checar(usuarios.autenticar(banco, "carlos", "novaSenha1") is not None, "nova senha não funcionou")
        checar(usuarios.autenticar(banco, "carlos", "senha123") is None, "senha antiga continuou válida")
        try:
            usuarios.atualizar(banco, vend_id, {"ativo": 0}, autor=vendedor)
            raise AssertionError("vendedor conseguiu desativar a si mesmo")
        except usuarios.ErroUsuario:
            pass
        ok("(perfis administrador/gerente/vendedor)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 14. backup
    passo("Backup e restauração do banco")
    try:
        arquivo = backup.criar(banco, autor=admin)
        checar(Path(arquivo).exists() and Path(arquivo).stat().st_size > 10000, "backup vazio")
        lista = backup.listar()
        checar(lista, "nenhum backup listado")
        banco2 = backup.restaurar_para_banco_temporario(arquivo)
        checar(banco2.consultar_valor("SELECT COUNT(*) FROM vendas") == banco.consultar_valor("SELECT COUNT(*) FROM vendas"),
               "backup não contém as vendas")
        banco2.fechar()
        ok(f"({Path(arquivo).name}, {Path(arquivo).stat().st_size // 1024} KB)")
    except Exception as exc:
        falhou(exc)
        return 1

    # ------------------------------------------------------------------ 15. fechamento
    passo("Fechamento de caixa e conferência final")
    try:
        posicao = caixa.posicao(banco, caixa_id)
        esperado = posicao["valor_sistema"]
        if esperado < 1000:
            # Estornos de devolução/cancelamento podem esvaziar a gaveta: reforça o troco.
            caixa.suprimento(banco, "100,00", "Reforço para estornos", autor=admin)
            esperado = caixa.valor_sistema(banco, caixa_id)
        fechamento = caixa.fechar(banco, caixa_id, esperado + 500, observacao="Sobra de R$ 5,00", autor=admin)
        checar(fechamento["diferenca"] == 500, f"diferença {fd(fechamento['diferenca'])} != R$ 5,00")
        checar(caixa.caixa_aberto(banco) is None, "caixa continuou aberto")
        checar(banco.integridade()[0], "banco corrompido")
        checar(estoque.verificar_saldos(banco) == [], "saldos divergentes no final")
        checar(len(banco.logs()) > 10, "trilha de auditoria vazia")
        resumo = vendas.resumo_dia(banco)
        ok(
            f"(vendas {resumo['quantidade']} = {fd(resumo['total'])}, lucro {fd(resumo['lucro'])}, "
            f"caixa {fd(fechamento['valor_sistema'])}, diferença {fd(fechamento['diferenca'])})"
        )
    except Exception as exc:
        falhou(exc)
        return 1

    banco.fechar()
    print("\n" + "=" * 78)
    if _FALHAS:
        print(f"FALHOU: {len(_FALHAS)} etapa(s) com erro -> {_FALHAS}")
        return 1
    print(f"SUCESSO: {_PASSOS} etapas executadas sem erros.")
    print(f"Pasta de dados temporária: {PASTA_TEMPORARIA}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
