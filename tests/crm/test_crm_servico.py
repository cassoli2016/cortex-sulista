"""As regras do CRM que nenhum CHECK do banco garante sozinho.

Cada teste aqui existe por uma decisão declarada em `sql/cortex/0026_crm.sql`
ou no cabeçalho de um módulo — e é o teste que impede a decisão de ser desfeita
por alguém que a achou complicada. Em especial: **nenhum estado comercial é
gravado**. Situação da conta, atraso de atividade e vigência de contrato são
todos derivados, e o dia em que um deles virar coluna a tela passa a mentir sem
que nada pareça errado.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api.crm import atividades, contas, contratos, oportunidades, precificacao
from api.crm import comum
from api.validacao import DadoInvalido


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    """Schema descartável, com o CKM e o ERP fora do caminho.

    `referencia_ckm` e `ava.carteira` falam com o AVA (réplica remota do ERP).
    Deixá-los ativos faria cada teste esperar o timeout de conexão numa
    máquina sem VPN — e o que se prova aqui é a regra do CRM, não a do ERP.
    Os dois já degradam sozinhos; quem cobra isso é `test_sem_erp_*`.
    """
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    # O dublê traz os QUATRO CKM, como a referência real: o produtivo (por km
    # CARREGADO) e o bruto (por km TOTAL RODADO). Omitir o bruto — que foi o
    # que a primeira versão fez — deixa o cálculo de resultado sem o
    # denominador certo, e o teste passaria por vacuidade.
    # A relação entre eles é a da frota: bruto = produtivo × (km_carregado /
    # km_total). Com 30% de retorno vazio, o fator é 0,7.
    monkeypatch.setattr(precificacao, "referencia_ckm",
                        lambda *a, **k: {"disponivel": True,
                                         "ckm_marginal": 3.50,
                                         "ckm_cheio": 5.20,
                                         "ckm_bruto": 2.45,
                                         "ckm_bruto_cheio": 3.64,
                                         "competencia_de": "2026-01",
                                         "competencia_ate": "2026-06",
                                         "fonte": "dublê de teste"})
    return esquema_pg


def _conta(esq, **extra) -> dict:
    base = {"nome": "TUPY FUNDIÇÕES", "dono_nome": "Ana Vendas",
            "segmento": "Automotivo"}
    return contas.gravar({**base, **extra}, usuario="teste@x", esquema=esq)


def _opo(esq, conta, **extra) -> dict:
    base = {"conta_id": conta["id"], "titulo": "Contrato eixo sul",
            "dono_nome": "Ana Vendas", "estagio": "proposta"}
    return oportunidades.gravar({**base, **extra}, usuario="teste@x",
                                esquema=esq)


# =================================================== situação NUNCA é gravada

def test_situacao_da_conta_nao_existe_como_coluna(esq):
    """A regra central: prospect/ativo/parado é lido, não escrito.

    Se alguém acrescentar a coluna, este teste continua passando — por isso ele
    confere o que importa de verdade: que a situação de uma conta SEM vínculo
    com o ERP seja 'prospect' sem que ninguém a tenha informado, e que mandar
    o campo no payload não a mude.
    """
    c = _conta(esq, situacao="ativo", tipo="cliente")
    assert c["situacao"] == "prospect"
    assert "situacao" not in _colunas(esq, "crm_contas")


def _colunas(esq: str, tabela: str) -> set[str]:
    from api import pglocal
    return {r["column_name"] for r in pglocal.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s", (esq, tabela), esquema=esq)}


def test_atividade_nao_tem_status_atrasada(esq):
    """Atraso é `quando < hoje AND status='aberta'`, calculado na leitura.

    Status de atraso GRAVADO precisa de alguém para virar, e no dia em que a
    rotina não roda a tela diz que está tudo em dia. Mesma armadilha do
    marcador de manutenção preventiva parado em 77.534 km.
    """
    c = _conta(esq)
    a = atividades.gravar(
        {"conta_id": c["id"], "assunto": "Ligar", "responsavel_nome": "Ana",
         "quando": (date.today() - timedelta(days=3)).isoformat()},
        usuario="teste@x", esquema=esq)
    assert a["atrasada"] is True and a["dias"] == -3
    with pytest.raises(Exception):
        atividades.gravar(
            {"conta_id": c["id"], "assunto": "X", "responsavel_nome": "Ana",
             "quando": date.today().isoformat(), "status": "atrasada"},
            usuario="teste@x", esquema=esq)


def test_vigencia_de_contrato_e_derivada(esq):
    """Vigente/a vencer/vencido saem das datas; só a rescisão é fato gravado."""
    c = _conta(esq)
    hj = date.today()
    vigente = contratos.gravar(
        {"conta_id": c["id"], "objeto": "FTL", "dono_nome": "Ana",
         "inicio": (hj - timedelta(days=400)).isoformat(),
         "fim": (hj + timedelta(days=300)).isoformat()},
        usuario="teste@x", esquema=esq)
    vencendo = contratos.gravar(
        {"conta_id": c["id"], "objeto": "FTL 2", "dono_nome": "Ana",
         "inicio": (hj - timedelta(days=400)).isoformat(),
         "fim": (hj + timedelta(days=30)).isoformat()},
        usuario="teste@x", esquema=esq)
    vencido = contratos.gravar(
        {"conta_id": c["id"], "objeto": "FTL 3", "dono_nome": "Ana",
         "inicio": (hj - timedelta(days=800)).isoformat(),
         "fim": (hj - timedelta(days=10)).isoformat()},
        usuario="teste@x", esquema=esq)
    assert (vigente["situacao"], vencendo["situacao"], vencido["situacao"]) == \
        ("vigente", "a_vencer", "vencido")
    assert "situacao" not in _colunas(esq, "crm_contratos")


def test_contrato_sem_fim_e_indeterminado_nao_vencido(esq):
    """Contrato sem prazo fica vigente para sempre — é a verdade, não lacuna.

    Marcar 'vencido' quem não tem prazo seria inventar um fim que ninguém
    contratou, e encheria a tela de alarme falso.
    """
    c = _conta(esq)
    t = contratos.gravar(
        {"conta_id": c["id"], "objeto": "Indeterminado", "dono_nome": "Ana",
         "inicio": "2020-01-01"}, usuario="teste@x", esquema=esq)
    assert t["situacao"] == "vigente" and t["indeterminado"] is True
    assert t["dias_para_fim"] is None


def test_reajuste_pendente_compara_o_ANO_e_nao_so_o_mes(esq):
    """O ciclo é o último aniversário do mês de reajuste que já passou.

    Comparar só o mês diria que um contrato ajustado em janeiro do ano PASSADO
    está em dia em janeiro deste — e o reajuste esquecido é dinheiro na mesa.
    """
    c = _conta(esq)
    hj = date.today()
    mes = hj.month
    ciclo = date(hj.year, mes, 1)
    t = contratos.gravar(
        {"conta_id": c["id"], "objeto": "Reajustável", "dono_nome": "Ana",
         "inicio": "2020-01-01", "indice_reajuste": "ipca",
         "mes_reajuste": mes,
         "ultimo_reajuste": (ciclo - timedelta(days=365)).isoformat()},
        usuario="teste@x", esquema=esq)
    assert t["reajuste_pendente"] is True
    t2 = contratos.registrar_reajuste(t["id"], percentual="7,5",
                                      quando=ciclo.isoformat(),
                                      usuario="teste@x", esquema=esq)
    assert t2["reajuste_pendente"] is False
    assert t2["percentual_ultimo"] == 7.5


def test_contrato_novo_nao_deve_reajuste_do_ciclo_anterior(esq):
    """Alarme que acende sem haver problema ensina a ignorar o alarme.

    Contrato assinado depois do início do ciclo não deve reajuste nenhum —
    cobrá-lo de um contrato de dois meses é o falso positivo que faz a tela
    perder credibilidade.
    """
    c = _conta(esq)
    hj = date.today()
    t = contratos.gravar(
        {"conta_id": c["id"], "objeto": "Recém-assinado", "dono_nome": "Ana",
         "inicio": hj.isoformat(), "mes_reajuste": hj.month},
        usuario="teste@x", esquema=esq)
    assert t["reajuste_pendente"] is False


# ============================================== a receita sai das lanes, sempre

def test_receita_vem_das_lanes_e_o_manual_deixa_de_valer(esq):
    """Total desnormalizado discorda das próprias linhas — em silêncio.

    Enquanto não há lane, o valor manual vale (oportunidade em qualificação é
    assim mesmo). Na primeira lane ele para de ser lido, e `origem_receita`
    DIZ qual dos dois está valendo: um número que muda de fonte sem avisar é um
    número em que ninguém confia.
    """
    c = _conta(esq)
    o = _opo(esq, c, receita_mensal_manual="50.000,00")
    assert (o["receita_mes"], o["origem_receita"]) == (50000.0, "manual")

    oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "origem_cidade": "Joinville",
         "origem_uf": "SC", "destino_cidade": "Betim", "destino_uf": "MG",
         "km": "1.180", "viagens_mes": "20", "valor_viagem": "9.000,00"},
        esquema=esq)
    o2 = oportunidades.obter(o["id"], esquema=esq)
    assert (o2["receita_mes"], o2["origem_receita"]) == (180000.0, "lanes")
    assert "receita_mensal" not in _colunas(esq, "crm_oportunidades")


def test_lane_sem_preco_e_contada_e_nao_vira_zero(esq):
    """Total com lanes em branco não é o valor do negócio.

    É a mesma armadilha do "ROB R$ 0 em verde" do CRM antigo: parecia pipeline
    sem valor, era lacuna de cadastro.
    """
    c = _conta(esq)
    o = _opo(esq, c)
    oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "origem_cidade": "A", "origem_uf": "SC",
         "destino_cidade": "B", "destino_uf": "PR", "km": "300",
         "viagens_mes": "10", "valor_viagem": "3.000,00"}, esquema=esq)
    oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "origem_cidade": "C", "origem_uf": "SC",
         "destino_cidade": "D", "destino_uf": "SP", "km": "500"},
        esquema=esq)
    o2 = oportunidades.obter(o["id"], esquema=esq)
    assert o2["resumo_lanes"]["lanes"] == 2
    assert o2["resumo_lanes"]["lanes_sem_preco"] == 1
    assert o2["receita_mes"] == 30000.0


# ======================================================== precificação da lane

def test_rkm_do_carregado_e_do_total_sao_diferentes_e_ambos_saem(esq):
    """A diferença entre os dois É o custo do retorno vazio.

    Sem os dois lado a lado, a lane de 400 km de ida com 400 de volta vazia
    parece tão boa quanto a que tem carga nos dois sentidos.
    """
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "origem_cidade": "A", "origem_uf": "SC",
         "destino_cidade": "B", "destino_uf": "MG", "km": "1000",
         "km_vazio": "1000", "viagens_mes": "10", "valor_viagem": "8.000,00",
         "tipo_veiculo": "Carreta LS (3 eixos)", "tipo_carga": "carga_geral"},
        esquema=esq)
    calc = ln["calc"]
    assert calc["rkm"] == 8.0
    assert calc["rkm_total"] == 4.0
    assert calc["retorno_vazio"] == 0.5


def test_resultado_da_viagem_nao_desconta_o_vazio_duas_vezes(esq):
    """A regra do glossário: resultado = valor − CKM_bruto × km_TOTAL.

    A primeira versão comparava o R$/km sobre o km TOTAL com o CKM PRODUTIVO
    (por km carregado) — e o produtivo já é o custo inteiro da frota dividido
    só pelo km carregado, ou seja, JÁ absorveu o custo de rodar vazio.
    Descontava-se o retorno vazio duas vezes, e toda lane com volta vazia saía
    deficitária. O defeito só apareceu com o CKM real do razão (R$ 13,28/km
    produtivo em ago/2026) — com um dublê de R$ 3,50 ele passava despercebido.

    Aqui: 1.000 km carregados + 1.000 vazios, R$ 8.000 a viagem, CKM bruto de
    R$ 2,45/km rodado.
      custo    = 2,45 × 2.000 = 4.900
      resultado= 8.000 − 4.900 = 3.100  (e NÃO 4,00 − 3,50 = 0,50/km)
    """
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "km": "1000", "km_vazio": "1000",
         "viagens_mes": "10", "valor_viagem": "8.000,00"}, esquema=esq)
    calc = ln["calc"]
    assert calc["custo_viagem"] == pytest.approx(4900.0)
    assert calc["resultado_viagem"] == pytest.approx(3100.0)
    assert calc["margem_km"] == pytest.approx(3100.0 / 2000)
    assert calc["margem_pct"] == pytest.approx(3100.0 / 8000)
    assert calc["margem_mes"] == pytest.approx(31000.0)
    # o produtivo continua saindo, como REFERÊNCIA na tela — mas não é ele que
    # multiplica o km
    assert calc["ckm_marginal"] == 3.50
    assert calc["ckm_bruto"] == 2.45


def test_lane_sem_ckm_nao_inventa_margem(esq, monkeypatch):
    """Sem o razão do AVA a cotação continua útil: o piso da ANTT não depende
    dele. O que some é a margem, e some como None — não como zero."""
    monkeypatch.setattr(precificacao, "referencia_ckm",
                        lambda *a, **k: {"disponivel": False,
                                         "ckm_marginal": None,
                                         "ckm_cheio": None, "ckm_bruto": None,
                                         "ckm_bruto_cheio": None,
                                         "fonte": "indisponível"})
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "km": "1000", "viagens_mes": "10",
         "valor_viagem": "8.000,00", "tipo_veiculo": "Carreta LS (3 eixos)",
         "tipo_carga": "carga_geral"}, esquema=esq)
    calc = ln["calc"]
    assert calc["resultado_viagem"] is None
    assert calc["margem_km"] is None
    assert calc["piso"]["estado"] == "calculado"   # o piso continua


def test_eixos_saem_do_veiculo_escolhido(esq):
    """Quem cota escolhe a composição, não o número de eixos da ANTT.

    Errar o eixo muda o coeficiente e portanto o piso — e ninguém que vende
    frete precisa saber que uma carreta LS de 3 eixos soma 6 na tabela.
    """
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "km": "500",
         "tipo_veiculo": "Carreta LS (3 eixos)"}, esquema=esq)
    assert ln["eixos"] == 6


def test_piso_ausente_nao_e_zero(esq):
    """Lane sem eixos/carga tem piso NÃO CALCULÁVEL, com o motivo.

    Aprovar um frete porque o piso desconhecido virou zero é o oposto do que a
    conferência existe para fazer.
    """
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "km": "500", "viagens_mes": "4",
         "valor_viagem": "1.000,00"}, esquema=esq)
    piso = ln["calc"]["piso"]
    assert piso["valor"] is None
    assert piso["abaixo"] is False
    assert piso["estado"] in ("sem_eixos", "sem_carga")
    assert piso["motivo"]


def test_piso_acusa_frete_abaixo_do_minimo_legal(esq):
    """O número que torna a cotação diferente de um CRM genérico."""
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "km": "1000", "viagens_mes": "10",
         "valor_viagem": "500,00", "tipo_veiculo": "Carreta LS (3 eixos)",
         "tipo_carga": "carga_geral"}, esquema=esq)
    piso = ln["calc"]["piso"]
    assert piso["estado"] == "calculado"
    assert piso["abaixo"] is True and piso["gap"] < 0
    assert "piso ANTT" in ln["calc"]["alerta"]["texto"]
    # e o valor sai em pt-BR, com vírgula decimal e ponto de milhar
    assert "R$ " in ln["calc"]["alerta"]["texto"]
    assert ln["calc"]["alerta"]["texto"].count(",") == 1


def test_faixa_fisica_da_lane_e_recusada_com_a_faixa_dita(esq):
    """Régua física: km fora de 0–6.000 é digitação, não rota exótica."""
    c = _conta(esq)
    o = _opo(esq, c)
    with pytest.raises(DadoInvalido) as e:
        oportunidades.gravar_lane(
            {"oportunidade_id": o["id"], "km": "95000"}, esquema=esq)
    assert "fora da faixa" in str(e.value)


def test_virgula_decimal_nao_vira_cem_vezes_o_valor(esq):
    """`<input type=number>` DESCARTA a vírgula: 1234,56 vira 123456.

    O campo chega como texto e passa por `valor_br`. É a regra que existe no
    `numBR()` do index.html e que aqui não pode divergir.
    """
    c = _conta(esq)
    o = _opo(esq, c)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "km": "100",
         "valor_viagem": "1.234,56"}, esquema=esq)
    assert ln["valor_viagem"] == 1234.56


# ================================================== oportunidade: fechamento

def test_perda_exige_motivo(esq):
    """Perda sem motivo não vira aprendizado nenhum."""
    c = _conta(esq)
    o = _opo(esq, c)
    with pytest.raises(DadoInvalido) as e:
        oportunidades.mover(o["id"], "perdida", usuario="teste@x", esquema=esq)
    assert "motivo" in str(e.value).lower()
    d = oportunidades.mover(o["id"], "perdida", motivo_perda="preco",
                            usuario="teste@x", esquema=esq)
    assert d["motivo_rotulo"] == "Preço" and d["fechada_em"]


def test_reabrir_limpa_o_carimbo_de_fechamento(esq):
    """Manter a data da primeira conclusão faria o tempo de ciclo medir um
    fechamento que foi desfeito — como `concluida_em` de `ges_acoes`."""
    c = _conta(esq)
    o = _opo(esq, c)
    ganha = oportunidades.mover(o["id"], "ganha", usuario="teste@x",
                                esquema=esq)
    assert ganha["fechada_em"] is not None
    reaberta = oportunidades.mover(o["id"], "negociacao", usuario="teste@x",
                                   esquema=esq)
    assert reaberta["fechada_em"] is None
    assert reaberta["aberta"] is True


def test_probabilidade_padrao_do_estagio_e_sobreponivel_e_dito_qual_vale(esq):
    """Previsão com probabilidade fixa por estágio é previsão do PROCESSO."""
    c = _conta(esq)
    o = _opo(esq, c, receita_mensal_manual="100.000,00")
    assert o["probabilidade_efetiva"] == 50  # padrão de "proposta"
    assert o["probabilidade_padrao"] is True
    assert o["valor_ponderado"] == 50000.0
    o2 = oportunidades.gravar({**{"conta_id": c["id"], "titulo": o["titulo"],
                                  "dono_nome": "Ana", "estagio": "proposta",
                                  "receita_mensal_manual": "100.000,00"},
                               "probabilidade": 20},
                              usuario="teste@x", oportunidade_id=o["id"],
                              esquema=esq)
    assert o2["probabilidade_efetiva"] == 20
    assert o2["probabilidade_padrao"] is False
    assert o2["valor_ponderado"] == 20000.0


# ================================================== contatos, interações, PII

def test_telefone_e_guardado_normalizado_pelo_validador_do_whatsapp(esq):
    """Duas noções de "telefone válido" dariam número que o cadastro aceita e
    o envio recusa — descoberto na hora em que a mensagem não chega."""
    c = _conta(esq)
    ct = contas.gravar_contato(
        {"conta_id": c["id"], "nome": "Carlos", "telefone": "(47) 99999-8888"},
        usuario="teste@x", esquema=esq)
    assert ct["telefone"] == "5547999998888"
    assert ct["telefone_fmt"] == "(47) 99999-8888"
    with pytest.raises(DadoInvalido):
        contas.gravar_contato(
            {"conta_id": c["id"], "nome": "X", "telefone": "123"},
            usuario="teste@x", esquema=esq)


def test_um_contato_principal_por_conta(esq):
    """Marcar o segundo rebaixa o primeiro — é o que a pessoa quis dizer."""
    c = _conta(esq)
    a = contas.gravar_contato({"conta_id": c["id"], "nome": "A",
                               "principal": True}, esquema=esq)
    contas.gravar_contato({"conta_id": c["id"], "nome": "B",
                           "principal": True}, esquema=esq)
    lista = {x["nome"]: x["principal"] for x in contas.contatos(c["id"],
                                                                esquema=esq)}
    assert lista == {"A": False, "B": True}
    assert a["principal"] is True  # era, na hora


def test_interacao_nao_tem_editar_nem_excluir(esq):
    """Append-only: interação editável deixa de ser prova de que houve contato."""
    assert not hasattr(atividades, "editar_interacao")
    assert not hasattr(atividades, "excluir_interacao")


def test_concluir_atividade_de_contato_registra_a_interacao(esq):
    """Quem acabou de ligar está com o resumo na cabeça — é a única hora em que
    ele escreve. Pedir depois é o que faz o histórico ficar vazio."""
    c = _conta(esq)
    a = atividades.gravar(
        {"conta_id": c["id"], "tipo": "ligacao", "assunto": "Retorno",
         "responsavel_nome": "Ana", "quando": date.today().isoformat()},
        usuario="teste@x", esquema=esq)
    atividades.concluir(a["id"], usuario="teste@x",
                        resumo="Pediu prazo maior", esquema=esq)
    hist = atividades.interacoes(conta_id=c["id"], esquema=esq)
    assert len(hist) == 1
    assert hist[0]["resumo"] == "Pediu prazo maior"
    assert hist[0]["canal"] == "ligacao"


def test_concluir_tarefa_que_nao_e_contato_nao_inventa_interacao(esq):
    """Concluir "montar proposta" não é ter falado com ninguém.

    Registrá-la faria o "dias sem contato" mentir para BAIXO — justamente o
    número que serve para cobrar contato.
    """
    c = _conta(esq)
    a = atividades.gravar(
        {"conta_id": c["id"], "tipo": "cotacao", "assunto": "Montar planilha",
         "responsavel_nome": "Ana", "quando": date.today().isoformat()},
        usuario="teste@x", esquema=esq)
    atividades.concluir(a["id"], usuario="teste@x", esquema=esq)
    assert atividades.interacoes(conta_id=c["id"], esquema=esq) == []


def test_dias_sem_contato_distingue_nunca_de_hoje(esq):
    """None (nunca falaram) e 0 (falaram hoje) são estados muito diferentes."""
    c = _conta(esq)
    assert contas.obter(c["id"], com_erp=False, esquema=esq)["dias_sem_contato"] is None
    atividades.registrar({"conta_id": c["id"], "canal": "ligacao",
                          "resumo": "Primeira conversa"},
                         usuario="teste@x", esquema=esq)
    assert contas.obter(c["id"], com_erp=False, esquema=esq)["dias_sem_contato"] == 0


# ============================================================ conta: exclusão

def test_conta_com_historico_nao_e_excluida_e_a_mensagem_diz_o_que_fazer(esq):
    """Apagar levaria o histórico junto — e a conta que alguém quer apagar é
    justamente a que tem histórico ruim."""
    c = _conta(esq)
    _opo(esq, c)
    with pytest.raises(DadoInvalido) as e:
        contas.excluir(c["id"], esquema=esq)
    assert "Arquivar" in str(e.value)
    p = contas.pendencias(c["id"], esquema=esq)
    assert p["oportunidades"] == 1
    # arquivar tira da lista sem apagar nada
    contas.arquivar(c["id"], usuario="teste@x", esquema=esq)
    assert contas.listar(esquema=esq) == []
    assert len(contas.listar(incluir_arquivadas=True, esquema=esq)) == 1


def test_dois_vinculos_no_mesmo_grupo_economico_sao_recusados(esq, monkeypatch):
    """Duas contas no mesmo grupo dividiriam a receita e as oportunidades em
    duas metades — e o índice único do banco diria só "duplicate key"."""
    from api.crm import ava
    monkeypatch.setattr(ava, "agrupamentos",
                        lambda: [{"codigo": 7, "nome": "TUPY"}])
    _conta(esq, ava_agrupamento=7)
    with pytest.raises(DadoInvalido) as e:
        contas.gravar({"nome": "TUPY 2", "dono_nome": "Ana",
                       "ava_agrupamento": 7}, usuario="teste@x", esquema=esq)
    assert "já está vinculado" in str(e.value)


def test_vinculo_inexistente_no_erp_e_recusado(esq, monkeypatch):
    """Código digitado errado gravaria uma conta que PARECE vinculada e cuja
    receita vem sempre vazia — e "cliente sem faturamento" é leitura de
    negócio, não de cadastro. O erro se disfarçaria de fato."""
    from api.crm import ava
    monkeypatch.setattr(ava, "agrupamentos",
                        lambda: [{"codigo": 7, "nome": "TUPY"}])
    with pytest.raises(DadoInvalido) as e:
        contas.gravar({"nome": "X", "dono_nome": "Ana",
                       "ava_agrupamento": 999}, usuario="teste@x", esquema=esq)
    assert "não existe no cadastro do ERP" in str(e.value)


def test_sem_erp_a_lista_de_contas_continua_de_pe(esq, monkeypatch):
    """O CRM é útil sem o ERP: a oportunidade, a atividade e o contato são
    todos do banco local. Trocar "a lista com uma coluna a menos" por "nenhuma
    lista" seria perder muito para ganhar nada."""
    from api.crm import ava
    monkeypatch.setattr(ava, "agrupamentos",
                        lambda: [{"codigo": 7, "nome": "TUPY"}])
    _conta(esq, ava_agrupamento=7)

    def explode(*a, **k):
        raise RuntimeError("AVA fora do ar")
    monkeypatch.setattr(ava, "carteira", explode)
    lista = contas.listar(esquema=esq)
    assert len(lista) == 1
    assert lista[0]["situacao"] == "indisponivel"
    assert lista[0]["erp_indisponivel"] == "RuntimeError"


# ================================================================== série ERP

def test_preencher_meses_nao_emenda_mes_ausente():
    """`GROUP BY` não devolve o mês que não existe.

    Emendar dois meses distantes numa linha contínua faz "parou" parecer
    "caiu" — foi assim que a jornada emendou abril em agosto sobre quatro
    meses de coleta parada.
    """
    from api.crm import ava
    hoje = date.today()
    atual = f"{hoje.year:04d}-{hoje.month:02d}"
    serie = ava.preencher_meses([{"mes": atual, "receita": 10.0,
                                  "viagens": 1, "km": 5.0}], meses=6)
    assert len(serie) == 6
    assert serie[-1]["mes"] == atual and serie[-1]["receita"] == 10.0
    assert all(m.get("sem_movimento") for m in serie[:-1])
