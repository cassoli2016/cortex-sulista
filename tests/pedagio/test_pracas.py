"""Praça e tarifa — as regras que sustentam o número, e os erros já cometidos.

O CONTEXTO
==========
Medido em 30/08/2026, 12 meses, no que a administradora devolveu praça a praça:

    praças confrontadas ....   189
    travessias .............23.284
    calculado ..........R$ 593.697
    cobrado ............R$ 643.417   (+R$ 49.720)
    iguais ao centavo ......  11,2%

E 100% dessa diferença está em praça cuja tarifa cadastrada está PARADA —
903 das 934 praças com tarifa (96,7%), e 219 das 221 efetivamente
atravessadas. Não é cobrança indevida: é o cadastro encontrando a realidade.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest

from api.pedagio import pracas as P


# ── a régua de "parada" precisa ser UMA ─────────────────────────────────────


def test_o_corte_sai_do_MESMO_parametro_que_a_marca_da_linha():
    """Uma primeira versão contava desatualizadas por ANO (`ano < 2025`) e
    marcava a linha por MESES (>13). Régis Bittencourt, vigência 01/10/2024 e
    22 meses de idade, saía PARADA na tabela e ficava FORA do total do cartão.

    Dois jeitos de dizer a mesma coisa na mesma tela é a família dos dois
    armazéns do parâmetro da premiação, que concordaram por acaso até alguém
    editar um deles — e aí o formulário dizia "salvo" sem mudar nada.
    """
    hoje = dt.date(2026, 8, 30)
    corte = P._corte(hoje)
    # tudo estritamente antes do corte tem de ser `parada`, e nada depois
    assert P._parada(P._idade_meses(corte - dt.timedelta(days=1), hoje))
    assert not P._parada(P._idade_meses(corte, hoje))


def test_o_corte_atravessa_a_virada_do_ano():
    """13 meses antes de janeiro é dezembro do ano ANTERIOR ao anterior — a
    aritmética ingênua (`mes - 13`) daria mês zero ou negativo."""
    assert P._corte(dt.date(2026, 1, 15)) == dt.date(2024, 12, 1)
    assert P._corte(dt.date(2026, 12, 31)) == dt.date(2025, 11, 1)


def test_sem_vigencia_NAO_e_idade_infinita():
    """Praça sem tarifa cadastrada tem outro dono e outro conserto. Devolver
    um número aqui a poria no topo da lista de "tarifa mais velha", empurrando
    para baixo a que realmente está velha — e é essa que dá trabalho."""
    assert P._idade_meses(None) is None
    assert P._parada(None) is False


# ── o join, que é onde este módulo mais podia errar ─────────────────────────


def test_o_confronto_liga_pela_chave_COMPOSTA_das_duas_tabelas():
    """`sequencia` sozinha não identifica a travessia: a chave são sete
    campos. Conferido contra a contagem crua — 45.646 linhas dos dois lados,
    sem fan-out. Ligar por menos multiplicaria o valor cobrado."""
    sql = " ".join(P.CONFRONTO_PRACA_SQL.split())
    for campo in ("a.grupo = c.grupo", "a.empresa = c.empresa",
                  "a.filial = c.filial", "a.unidade = c.unidade",
                  "a.diferenciadorsequencia = c.diferenciadorsequencia",
                  "a.sequencia = c.sequencia",
                  "a.sequenciapracapedagio = c.sequenciapracapedagio"):
        assert campo in sql, "o join perdeu %s e vai multiplicar linha" % campo


def test_a_praca_e_identificada_pelo_ID_e_nunca_pela_descricao_da_adm():
    """A administradora ATUAL devolve `codigoexterno` em 98% e `descricao` em
    5%; nos trimestres anteriores era o contrário. Agrupar por `a.descricao`
    produziu uma linha "-" com 11.606 travessias — a maioria do volume, com
    todas as praças somadas juntas, e sem erro nenhum aparecer.

    Quem identifica a praça é `c.idpracapedagio`, 100% preenchido em todos os
    trimestres. O campo da administradora serve para o VALOR.
    """
    for nome in ("CONFRONTO_PRACA_SQL", "OBSERVADA_SQL", "TARIFA_EM_USO_SQL"):
        sql = " ".join(getattr(P, nome).split())
        assert "c.idpracapedagio" in sql, "%s não identifica a praça pelo id" % nome
        assert "a.descricao" not in sql, (
            "%s agrupa pela descrição da administradora, que fica vazia em "
            "trimestre inteiro" % nome)


def test_nenhum_SQL_tem_porcento_solto():
    """`%` dentro da string vira placeholder do psycopg e a consulta morre com
    `incomplete placeholder`. A explicação vai em comentário PYTHON, acima da
    constante — que é onde ela é lida de qualquer jeito."""
    for nome in dir(P):
        if not nome.endswith("_SQL"):
            continue
        soltos = [m.group(0) for m in
                  re.finditer(r"%(?!\()", getattr(P, nome))]
        assert not soltos, "%s tem %%: %s" % (nome, soltos)


# ── o que cada número diz, e o que ele se recusa a dizer ────────────────────


def test_a_razao_sai_dos_TOTAIS_e_nao_de_valores_arredondados(monkeypatch):
    """Arredondar antes de dividir move o número de lado da fronteira, e o
    limiar de leitura aqui é 1,00: decide se a frase é "a operadora cobrou
    mais" ou não."""
    linhas = [{"id": 1, "praca": "X", "uf": "SC", "travessias": 3,
               "calculado": 100.0, "cobrado": 100.004, "vigencia": None,
               "iguais": 3}]
    monkeypatch.setattr(P.db, "query", lambda *a, **k: linhas)
    r = P.confronto_praca("2026-01-01", "2026-12-31")
    assert r["linhas"][0]["razao"] == 1.0


def test_a_diferenca_e_separada_entre_tarifa_parada_e_o_resto(monkeypatch):
    """É o número que separa "a operadora está cobrando errado" de "o nosso
    cadastro está velho" — dois consertos, em lugares diferentes e com donos
    diferentes. Somados, o achado não decide nada."""
    hoje = dt.date(2026, 8, 30)
    linhas = [
        # tarifa velha: a diferença aqui se explica pelo cadastro
        {"id": 1, "praca": "Velha", "uf": "SP", "travessias": 10,
         "calculado": 100.0, "cobrado": 130.0,
         "vigencia": dt.date(2021, 7, 8), "iguais": 0},
        # tarifa recente: esta diferença é outra conversa
        {"id": 2, "praca": "Nova", "uf": "SC", "travessias": 10,
         "calculado": 100.0, "cobrado": 110.0,
         "vigencia": dt.date(2026, 8, 1), "iguais": 0},
    ]
    monkeypatch.setattr(P.db, "query", lambda *a, **k: linhas)
    r = P.confronto_praca("2026-01-01", "2026-12-31", hoje=hoje)
    assert r["diferenca"] == 40.0
    assert r["diferenca_parada"] == 30.0
    assert r["pct_diferenca_parada"] == 75.0


def _obs(praca, eixos, *pares, **extra):
    """Linhas de `OBSERVADA_SQL`: uma por (praça, eixos, VALOR).

    O formato mudou quando a média deu lugar à moda, e estes testes quebraram
    junto — corretamente, porque afirmavam sobre a implementação antiga. É a
    lição já catalogada nesta casa: teste amarrado à implementação cai sem
    haver defeito. Este helper deixa a INTENÇÃO no corpo do teste e o formato
    num lugar só.
    """
    return [{"id": extra.get("id", 1), "praca": praca, "uf": extra.get("uf", "SP"),
             "eixos": eixos, "valor": v, "n": n,
             "visto_de": dt.date(2026, 1, 1), "visto_ate": dt.date(2026, 6, 1),
             "vigencia": extra.get("vigencia"),
             "erp_eixo": extra.get("erp_eixo")}
            for v, n in pares]


def test_a_tarifa_e_a_MODA_e_nunca_a_media(monkeypatch):
    """Campina Grande do Sul, 5 eixos: R$ 20,50 em 42 travessias, R$ 21,50 em
    85 e R$ 80,28 UMA vez. A média dá R$ 21,63, que não é tarifa de nada, e a
    faixa de 20,50 a 80,28 faz a coluna parecer ruído.

    A tarifa é o valor que SE REPETE — e o segundo mais frequente é o
    anterior, o que data o reajuste de graça.
    """
    monkeypatch.setattr(P.db, "query", lambda *a, **k:
                        _obs("Campina", 5, (21.50, 85), (20.50, 42), (80.28, 1)))
    r = P.observada("2026-01-01", "2026-12-31")[0]
    assert r["valor"] == 21.50
    assert r["anterior"] == 20.50, "o segundo mais frequente é a tarifa anterior"
    assert r["por_eixo"] == 4.30


def test_valor_visto_UMA_vez_nao_vira_tarifa_anterior(monkeypatch):
    """R$ 80,28 numa travessia só é lançamento avulso. Apresentá-lo como "era
    R$ 80,28" inventaria um reajuste que nunca houve — e o número apareceria na
    tela ao lado da data em que foi visto, o que o faria parecer apurado."""
    monkeypatch.setattr(P.db, "query", lambda *a, **k:
                        _obs("Campina", 5, (21.50, 85), (80.28, 1)))
    assert P.observada("2026-01-01", "2026-12-31")[0]["anterior"] is None


def test_moda_FRACA_nao_vira_tarifa_afirmada(monkeypatch):
    """Ribeirão Pires com 6 eixos tem moda de 20%: ali o mesmo veículo paga
    valores diferentes, o que é esperado quando a praça cobra pelo eixo NO CHÃO
    e o vale declara o total. Afirmar "a tarifa é R$ 32,40" seria inventar
    precisão — vira n/d, como o `confidence` abaixo de 0,5 da TomTom."""
    monkeypatch.setattr(P.db, "query", lambda *a, **k:
                        _obs("Ribeirão Pires", 6, (32.40, 20), (18.00, 18),
                             (24.60, 17), (28.00, 16), (30.00, 15),
                             erp_eixo=3.90))
    r = P.observada("2026-01-01", "2026-12-31")[0]
    assert r["estabelecida"] is False
    assert r["desvio_pct"] is None, (
        "desvio contra um número que a própria tela não afirma é pior que "
        "não mostrar")


def test_desvio_contra_tarifa_AUSENTE_e_None_e_nunca_menos_cem_por_cento(monkeypatch):
    """Comparar contra zero produziria "-100%" em toda praça sem cadastro e
    afogaria as que TÊM cadastro e estão erradas — que são as acionáveis.
    Mesma regra do KPI que mostra travessão quando o filtro exclui a base."""
    monkeypatch.setattr(P.db, "query", lambda *a, **k:
                        _obs("Sem tarifa", 6, (30.0, 40), erp_eixo=None))
    r = P.observada("2026-01-01", "2026-12-31")[0]
    assert r["por_eixo"] == 5.0
    assert r["estabelecida"] is True
    assert r["desvio_pct"] is None


def test_poucas_travessias_nao_estabelecem_tarifa(monkeypatch):
    """Abaixo de cinco pode ser categoria errada, eixo suspenso ou o próprio
    dia do reajuste. Uma observação vira tarifa oficial na tela sem nada
    avisando."""
    linhas = (_obs("Rara", 6, (99.0, 2), id=1)
              + _obs("Comum", 6, (24.0, 90), id=2))
    monkeypatch.setattr(P.db, "query", lambda *a, **k: linhas)
    assert [x["praca"] for x in P.observada("2026-01-01", "2026-12-31")] == ["Comum"]


def test_o_residuo_fora_da_moda_e_contado(monkeypatch):
    """Dizer "a tarifa é R$ 25,80" com um quinto das cobranças fora dela seria
    esconder o que não se explicou. `fora` é o que sobra depois da moda e do
    anterior."""
    monkeypatch.setattr(P.db, "query", lambda *a, **k:
                        _obs("Mista", 6, (25.80, 60), (24.60, 30), (10.0, 5),
                             (12.0, 5)))
    r = P.observada("2026-01-01", "2026-12-31")[0]
    assert r["travessias"] == 100
    assert r["fora"] == 10


def test_a_cobertura_por_administradora_nomeia_quem_nao_manda(monkeypatch):
    """"70,8% sem contraparte" lê-se como dado furado. "A TARGET devolve a
    praça em 0% das 27.892 travessias" lê-se como pedido ao fornecedor. Mesma
    regra do denominador dos 664 rastreadores "sem sinal"."""
    linhas = [{"adm": 173, "nome": "TARGET", "travessias": 100,
               "sem_praca": 100, "calculado": 3300.0},
              {"adm": 50, "nome": "EFRETE", "travessias": 100,
               "sem_praca": 12, "calculado": 2700.0}]
    monkeypatch.setattr(P.db, "query", lambda *a, **k: linhas)
    r = P.por_administradora("2026-01-01", "2026-12-31")
    assert r[0]["pct_com_praca"] == 0.0
    assert r[1]["pct_com_praca"] == 88.0


# ── o que NÃO dá para conferir, e por que isso é um número e não um texto ────


def test_o_mdfe_e_SENSOR_e_nao_frase_fixa(monkeypatch):
    """Os três campos de vale-pedágio do manifesto estão vazios nas 126.295
    linhas do histórico, desde 31/05/2023 — medido. A tela DIZ que não dá para
    conferir, em vez de calar ou de inventar veredito a partir da ausência
    (mesma regra das multas, onde não se criou estimativa de custo sobre campo
    vazio).

    Mas o número é MEDIDO, não escrito: no dia em que o ERP passar a preencher,
    `conferivel` vira verdadeiro e a tela muda sozinha. Frase fixa envelheceria
    calada e continuaria dizendo "não dá" depois de passar a dar.
    """
    monkeypatch.setattr(P.db, "query", lambda *a, **k: [
        {"mdfe": 39222, "com_comprovante": 0, "com_fornecedor": 0,
         "com_ciot": 27672}])
    r = P.mdfe_vale("2025-08-31", "2026-08-30")
    assert r["conferivel"] is False
    assert r["pct_comprovante"] == 0.0

    monkeypatch.setattr(P.db, "query", lambda *a, **k: [
        {"mdfe": 100, "com_comprovante": 90, "com_fornecedor": 90,
         "com_ciot": 70}])
    r = P.mdfe_vale("2025-08-31", "2026-08-30")
    assert r["conferivel"] is True
    assert r["pct_comprovante"] == 90.0


def test_o_ciot_entra_na_conta_de_proposito(monkeypatch):
    """O CIOT é preenchido em 56% do MESMO registro. Sem ele ao lado, "os
    campos de vale estão vazios" lê-se como "o ERP não preenche documento
    eletrônico"; com ele, lê-se como "é este dado que não chega" — que é uma
    pergunta com destinatário."""
    monkeypatch.setattr(P.db, "query", lambda *a, **k: [
        {"mdfe": 100, "com_comprovante": 0, "com_fornecedor": 0,
         "com_ciot": 56}])
    assert P.mdfe_vale("2025-08-31", "2026-08-30")["pct_ciot"] == 56.0
