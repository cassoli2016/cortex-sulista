"""As regras de negócio da Smartec que, se erradas, produzem número plausível.

Nenhum defeito coberto aqui daria erro visível: todos produziriam uma tela
bonita com o número errado, que é o tipo caro.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.smartec import armazenamento as arm
from api.smartec import leitura as lei


# Corpo REAL de uma MULTA, copiado da resposta do fornecedor.
MULTA = {
    "PLACA": "BBX3375", "RENAVAM": "1142889448",
    "IDENTIFICADOR_SMARTEC": "b4d6cea6-42da-11f1-808d-42010a9e0023",
    "AIT": "1VA2645802", "AIT_SNE": "1VA2645802", "AIT_DETRAN": "1VA2645802",
    "RENAINF": "11249794722", "AIT_ORIGINARIA": None,
    "DATA_INFRACAO": "31/03/2026", "Hora": "11:01:00",
    "LOCAL_INFRACAO": "SP 148 KM 031", "VALOR_A_PAGAR": 130.16,
    "VALOR_COM_DESCONTO": 104.13, "VALOR_DESCONTO": 26.04,
    "MUNICIPIO": "SAO BERNARDO DO CAMPO", "UF": "SP",
    "DESCRICAO": "Velocidade - ate 20%", "CODIGO_INFRACAO": "7455",
    "DESDOBRAMENTO": "0", "PONTUACAO": 4, "CODIGO_ORGAO": "126200",
    "ORGAO": "DER - SP", "ORGAO_ADESAO_SNE": 1,
    "VENCIMENTO_INFRACAO": "08/06/2026", "DATA_PESQUISA": "28/04/2026",
    "PENALIDADE": "https://x/MULTA.pdf", "Boleto": "https://x/BOLETO.pdf",
    "SITUACAO_BOLETO": "Pronto", "LINHA_DIGITAVEL": "856100000012",
    "MOTORISTA_NOME": "AGREGADO",
}

# Corpo REAL de uma NOTIFICAÇÃO. REPARE nos nomes: LOCAL (não LOCAL_INFRACAO),
# ORGAO_AUTUADOR (não ORGAO), PRAZO_INDICACAO (não VENCIMENTO_INFRACAO) e
# DESDOBRAMENTO vazio (a multa manda "0"). Foi esta diferença de vocabulário
# que gravou 483 notificações com o órgão em branco, sem erro nenhum.
NOTIFICACAO = {
    "PLACA": "BBX3375", "RENAVAM": "1142889448",
    "IDENTIFICADOR_SMARTEC": "8d28fa95-3807-11f1-808d-42010a9e0023",
    "AIT": "1VA2645802", "DATA_INFRACAO": "31/03/2026", "Hora": "11:01:00",
    "LOCAL": "SP 148 KM 031", "VALOR_A_PAGAR": 130.16,
    "MUNICIPIO": "SAO BERNARDO DO CAMPO", "UF": "SP",
    "DESCRICAO": "Velocidade - ate 20%", "CODIGO_INFRACAO": "7455",
    "DESDOBRAMENTO": "", "PONTUACAO": 4, "CODIGO_ORGAO": "126200",
    "ORGAO_AUTUADOR": "DER - SP", "ORGAO_ADESAO_SNE": 1,
    "PRAZO_INDICACAO": "20/05/2026", "DATA_PESQUISA": "14/04/2026",
    "NOTIFICACAO": "https://x/NOTIFICACAO.pdf", "MOTORISTA_NOME": "AGREGADO",
}


@pytest.fixture
def esq(esquema_pg):
    return esquema_pg


def _uma(esq, sql):
    return pglocal.um(sql, esquema=esq)


def test_a_notificacao_usa_OUTROS_NOMES_de_campo(esq):
    """Órgão, prazo e local mudam de nome entre as duas espécies.

    Ler só o vocabulário da multa grava a notificação com órgão vazio e prazo
    nulo — e o prazo é justamente o campo que torna a notificação acionável.
    """
    arm.gravar_infracoes([NOTIFICACAO], "notificacao", esq)
    r = _uma(esq, "SELECT orgao, prazo_indicacao, local_infracao, "
                  "url_penalidade FROM smt_infracoes")
    assert r["orgao"] == "DER - SP", "ORGAO_AUTUADOR não foi lido"
    assert r["prazo_indicacao"] is not None, "PRAZO_INDICACAO não foi lido"
    assert r["local_infracao"] == "SP 148 KM 031", "LOCAL não foi lido"
    assert r["url_penalidade"].endswith("NOTIFICACAO.pdf")


def test_o_desdobramento_vazio_vira_zero_e_casa_com_o_catalogo(esq):
    """A multa manda "0" e a notificação manda "" para a MESMA infração.

    O catálogo do CTB chaveia pelo código concatenado ("74550"). Sem
    normalizar, metade das linhas não casaria e a gravidade sairia nula só
    nelas — um defeito que só aparece comparando as duas abas.
    """
    arm.gravar_infracoes([MULTA], "multa", esq)
    arm.gravar_infracoes([NOTIFICACAO], "notificacao", esq)
    arm.gravar_infracoes_ctb([{
        "CODIGO": "7455", "CODIGO_DESDOBRAMENTO": "74550",
        "INFRACAO": "Velocidade ate 20%", "GRAVIDADE": "MEDIA", "PONTOS": 4,
    }], esq)
    desd = [r["desdobramento"] for r in
            pglocal.query("SELECT desdobramento FROM smt_infracoes", esquema=esq)]
    assert set(desd) == {"0"}, f"desdobramento não normalizado: {desd}"
    for especie in ("multa", "notificacao"):
        linhas = lei.por_infracao(especie, 5, esquema=esq)
        assert linhas[0]["gravidade"] == "MEDIA", \
            f"catálogo não casou em {especie}"


def test_multa_e_notificacao_NAO_SE_SOMAM(esq):
    """São o mesmo auto em estágios diferentes.

    Somar contaria a mesma infração duas vezes. Aqui as duas linhas têm o
    MESMO AIT de propósito — é o caso real.
    """
    arm.gravar_infracoes([MULTA], "multa", esq)
    arm.gravar_infracoes([NOTIFICACAO], "notificacao", esq)
    k = lei.kpis(esquema=esq)
    assert k["multas"]["n"] == 1
    assert k["notificacoes"]["n"] == 1
    assert k["multas"]["valor"] == pytest.approx(130.16)
    # o KPI de multa NÃO pode ter absorvido a notificação
    assert k["multas"]["valor"] != pytest.approx(260.32)


def test_fechar_ausentes_RECUSA_quando_a_coleta_falhou(esq):
    """O teste mais importante deste arquivo.

    A API só devolve o que está em aberto, então o fechamento marca como
    resolvido tudo que não veio. Se a varredura falhou no meio, os veículos
    não visitados "não vieram" — e fechar marcaria a frota inteira como
    resolvida. Um timeout de rede viraria "parabéns, zeramos as multas".

    A PRIMEIRA VERSÃO DESTE TESTE PASSAVA POR VACUIDADE: ela gravava a multa e
    chamava o fechamento no mesmo instante, e a implementação de então tinha
    uma janela de 1 minuto que sozinha já impedia o fechamento. Sabotar o
    guard não fazia o teste cair. Aqui a coleta é declarada como tendo
    começado DEPOIS da gravação, que é o caso em que o fechamento realmente
    agiria — e é só assim que o guard fica sendo a única coisa que segura.
    """
    from datetime import datetime, timedelta, timezone
    arm.gravar_infracoes([MULTA], "multa", esq)
    rnv = MULTA["RENAVAM"].lstrip("0")
    depois = datetime.now(timezone.utc) + timedelta(minutes=5)

    fechadas = arm.fechar_ausentes("multa", [rnv], coleta_completa=False,
                                   inicio=depois, esquema=esq)
    assert fechadas == 0
    aberta = _uma(esq, "SELECT sumiu_em FROM smt_infracoes")
    assert aberta["sumiu_em"] is None, (
        "coleta incompleta NAO pode fechar infracao nenhuma")


def test_fechar_ausentes_FECHA_quando_a_coleta_foi_completa(esq):
    """A contraprova: com a coleta completa, o que não veio é fechado.

    Sem este par, o teste acima ficaria verde numa implementação que nunca
    fecha nada — que é o outro jeito de a função estar errada.
    """
    from datetime import datetime, timedelta, timezone
    arm.gravar_infracoes([MULTA], "multa", esq)
    rnv = MULTA["RENAVAM"].lstrip("0")
    depois = datetime.now(timezone.utc) + timedelta(minutes=5)

    fechadas = arm.fechar_ausentes("multa", [rnv], coleta_completa=True,
                                   inicio=depois, esquema=esq)
    assert fechadas == 1
    assert _uma(esq, "SELECT sumiu_em FROM smt_infracoes")["sumiu_em"] is not None


def test_coleta_LENTA_nao_fecha_o_que_ela_mesma_acabou_de_ver(esq):
    """A fronteira é o INÍCIO da coleta, não uma janela fixa de tempo.

    A varredura de notificações faz 160 chamadas. Com a Smartec lenta ela
    passa de um minuto — e a implementação antiga, que comparava contra
    `now() - 1 minuto`, fecharia as infrações gravadas no COMEÇO da própria
    passagem. A coleta marcaria como resolvido o que ela mesma acabou de ver.
    """
    from datetime import datetime, timedelta, timezone
    inicio = datetime.now(timezone.utc) - timedelta(minutes=30)  # coleta longa
    arm.gravar_infracoes([MULTA], "multa", esq)                  # vista AGORA
    rnv = MULTA["RENAVAM"].lstrip("0")

    fechadas = arm.fechar_ausentes("multa", [rnv], coleta_completa=True,
                                   inicio=inicio, esquema=esq)
    assert fechadas == 0, "fechou uma infração que a própria coleta trouxe"
    assert _uma(esq, "SELECT sumiu_em FROM smt_infracoes")["sumiu_em"] is None


def test_a_infracao_que_volta_a_aparecer_REABRE(esq):
    """Instabilidade da API não pode aposentar uma multa para sempre."""
    arm.gravar_infracoes([MULTA], "multa", esq)
    pglocal.executar("UPDATE smt_infracoes SET sumiu_em = now()", esquema=esq)
    assert _uma(esq, "SELECT sumiu_em FROM smt_infracoes")["sumiu_em"] is not None

    arm.gravar_infracoes([MULTA], "multa", esq)   # veio de novo
    assert _uma(esq, "SELECT sumiu_em FROM smt_infracoes")["sumiu_em"] is None


def test_recoletar_ATUALIZA_e_nao_duplica(esq):
    """Recoletar é o caso NORMAL: o boleto muda de situação ao longo do mês."""
    arm.gravar_infracoes([MULTA], "multa", esq)
    pago = dict(MULTA, SITUACAO_BOLETO="Pago", VALOR_A_PAGAR=133.04)
    arm.gravar_infracoes([pago], "multa", esq)
    r = _uma(esq, "SELECT count(*)::int n, max(situacao_boleto) sit "
                  "FROM smt_infracoes")
    assert r["n"] == 1, "chave natural não deduplicou"
    assert r["sit"] == "Pago", "o estado novo não sobrescreveu o antigo"


def test_infracao_SEM_identificador_e_descartada(esq):
    """Sem a chave não há como deduplicar, e inventar uma faria a mesma
    infração entrar de novo a cada coleta."""
    arm.gravar_infracoes([dict(MULTA, IDENTIFICADOR_SMARTEC=None)], "multa", esq)
    assert _uma(esq, "SELECT count(*)::int n FROM smt_infracoes")["n"] == 0


def test_data_invalida_do_fornecedor_vira_nulo(esq):
    """A Smartec manda "00/00/0000" para dizer "não há".

    Deixar passar poria 30/11/0000 na tela ou derrubaria a linha inteira por
    causa de um campo acessório.
    """
    arm.gravar_infracoes([dict(MULTA, VENCIMENTO_INFRACAO="00/00/0000")],
                         "multa", esq)
    assert _uma(esq, "SELECT vencimento FROM smt_infracoes")["vencimento"] is None


def test_a_serie_mensal_GERA_os_meses_vazios(esq):
    """Mês sem infração em aberto não voltaria do GROUP BY.

    O gráfico emendaria março em julho e desenharia uma queda que não houve.
    """
    arm.gravar_infracoes([MULTA], "multa", esq)
    meses = [m["mes"] for m in lei.mensal(esquema=esq)]
    assert "2026-03" in meses
    assert len(meses) > 1, "a série tem de cobrir o intervalo, não só os meses com dado"
    assert meses == sorted(meses)
    # e os gerados vêm zerados, não ausentes
    vazios = [m for m in lei.mensal(esquema=esq) if m["mes"] != "2026-03"]
    assert all(m["multas"] == 0 for m in vazios)


def test_o_valor_zero_do_ipva_nao_vira_ausencia(esq):
    """IPVA R$ 0,00 é ISENÇÃO, e é um fato. Campo ausente é outra coisa."""
    arm.gravar_ipva([{"RENAVAM": "123", "PLACA": "AAA1A11", "VALOR": 0.00,
                      "DATA_PESQUISA": "01/08/2026"}], esq)
    r = _uma(esq, "SELECT ipva_valor FROM smt_licenciamento")
    assert r["ipva_valor"] is not None and float(r["ipva_valor"]) == 0.0


def test_o_valor_do_licenciamento_nao_apaga_o_mes_do_calendario(esq):
    """São duas chamadas diferentes que escrevem na mesma linha.

    Um UPSERT que zerasse `mes` na consulta de valor apagaria o calendário —
    e o campo não vem nessa resposta, então "não veio" viraria "é nulo".
    """
    arm.gravar_licenciamento_calendario(
        [{"RENAVAM": "123", "PLACA": "AAA1A11", "UF": "PR", "Mes": 7,
          "TIPO": "CAMINHAO"}], esq)
    arm.gravar_licenciamento_valor(
        [{"Renavam": "123", "Placa": "AAA1A11", "Uf": "PR", "Valor": 94.61}], esq)
    r = _uma(esq, "SELECT mes, valor_taxa FROM smt_licenciamento")
    assert r["mes"] == 7, "o mês do calendário foi apagado pela consulta de valor"
    assert float(r["valor_taxa"]) == pytest.approx(94.61)


def test_a_trilha_registra_ate_a_coleta_VAZIA(esq):
    """"Não trouxe nada" tem de ser distinguível de "não rodou".

    Sem isso os dois são o mesmo silêncio — foi assim que a RasterJOR ficou
    136 dias parada.
    """
    cid = arm.carga_abrir("multa", esq)
    arm.carga_fechar(cid, "vazio", 0, 1, "nenhum veículo com pendência", esq)
    r = _uma(esq, "SELECT status, itens FROM smt_carga")
    assert r["status"] == "vazio" and r["itens"] == 0
