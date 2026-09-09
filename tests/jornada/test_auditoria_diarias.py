"""Auditoria das diárias — as réguas, e o que cada uma se recusa a afirmar.

O QUE ESTA SUÍTE PROTEGE
========================
A auditoria compara o que a FOLHA pagou (evento DIARIAS PAGAS, pagamento
semanal) com o que a JORNADA registrou (RasterJOR, no banco do CÓRTEX). Ela
NÃO julga se o motorista tinha direito a meia ou a inteira — essa regra é da
empresa, depende de pernoite e acordo, e foi medido que meia e inteira não se
separam por tempo de direção nem por km. Um teste aqui embaixo cobra esse
limite, porque a tentação de "melhorar" a auditoria com um classificador é
exatamente o que a transformaria em acusação por palpite.

O ACHADO QUE JUSTIFICOU O MÓDULO
================================
**A competência 2026-07-31 é cópia exata da de 2026-07-07**: as MESMAS 78
pessoas, com o MESMO valor ao centavo, R$ 32.063,63. É a única repetição
exata de 2026 — o que também diz que a régua não é barulhenta.

TRÊS COISAS QUE VIRARAM REGRA AQUI
==================================
1. **Repetição do mesmo fato não é recorrência.** 31 pessoas da mesma filial
   fora da tarifa no mesmo dia são UM evento de folha, não 31 achados; 267
   pagamentos sem filial são 12 PESSOAS. Sem agrupar, essas duas réguas somam
   298 linhas e enterram as outras seis.
2. **A janela curta acusa a pessoa errada.** O teto de diárias por dia
   trabalhado medido em 7 dias reprova 33,5% da folha — que é a defasagem da
   competência, não erro de ninguém. Em 14 dias, 3,7%.
3. **O dinheiro não se conta duas vezes.** Os achados individuais que caem
   dentro de uma semana repetida ou de um lote de filial continuam na lista
   (é o que nomeia a pessoa), mas não entram no total — senão o relatório de
   auditoria cometeria o erro que ele existe para achar.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.jornada import auditoria_diarias as aud
from api.jornada import diarias


# ── a chave, que precisa ser a MESMA das duas telas ─────────────────────────


def test_a_normalizacao_do_nome_e_a_MESMA_da_tela_de_diarias():
    """Duas normalizações diferentes fariam a aba Diárias e a auditoria dela
    discordarem sobre quem é a mesma pessoa — a pior discordância possível
    entre duas telas que se citam."""
    for nome in ("José  da Silva ", "  ANA   PAULA  ", "JOAO", "",
                 "MARIA DAS GRAÇAS"):
        assert aud._norm(nome) == diarias._norm(nome)


# ── a tarifa derivada ───────────────────────────────────────────────────────


def _pag(dia, nome, valor):
    return {"pago_em": dia, "nome": nome, "matricula": "1", "cargo": "MOT",
            "valor": valor, "lancamentos": 1}


def test_a_tarifa_sai_do_MDC_dos_pagamentos_da_filial():
    """Não há cadastro de tarifa que a casa possa ler. O que há é a
    regularidade: a inteira é o dobro da meia, então todo pagamento é múltiplo
    inteiro da meia — e o MDC do mês devolve a meia."""
    m = [x * 57.48 for x in (4, 5, 6, 7, 8)]
    pagos = _mes_de(date(2026, 3, 3), m) + _mes_de(date(2026, 4, 7), m)
    t = aud.derivar_tarifas(pagos, lambda n: "CRZ")
    assert t["CRZ"]["taxas"] == [57.48]


def _mes_de(dia, valores):
    return [_pag(dia, "P%d" % i, v) for i, v in enumerate(valores)]


def test_uma_taxa_de_UM_MES_SO_nao_vira_tarifa():
    """No mês do reajuste as duas tarifas se misturam e o MDC despenca para
    centavos. Se um mês bastasse, esse centavo viraria tarifa — e passaria a
    explicar QUALQUER valor, inocentando exatamente o que a régua procura."""
    m = [x * 57.48 for x in (4, 5, 6, 7, 8)]
    pagos = (_mes_de(date(2026, 3, 3), m) + _mes_de(date(2026, 4, 7), m)
             # um mês só, e com valores que derrubam o MDC para 3 centavos
             + _mes_de(date(2026, 6, 9),
                       [124.89, 350.10, 228.06, 461.28, 516.87]))
    t = aud.derivar_tarifas(pagos, lambda n: "CRZ")
    assert t["CRZ"]["taxas"] == [57.48], "a taxa de um mês só virou tarifa"
    assert 0.03 in t["CRZ"]["descartadas"], (
        "a descartada precisa ficar à vista: é o mês do reajuste")


def test_filial_com_POUCOS_pagamentos_no_mes_nao_inventa_tarifa():
    """O MDC de UM valor é o próprio valor: sem piso, uma filial com um
    pagamento no mês "descobriria" uma tarifa igual ao que foi pago, e ela
    explicaria aquele pagamento sozinha. A régua se inocentaria pelo dado que
    devia julgar."""
    pagos = [_pag(date(2026, 3, 3), "A", 1234.56),
             _pag(date(2026, 4, 7), "A", 1234.56)]
    t = aud.derivar_tarifas(pagos, lambda n: "MINI")
    assert t.get("MINI", {}).get("taxas", []) == [], (
        "dois pagamentos soltos viraram tarifa")


def test_a_tarifa_MAIOR_e_testada_primeiro():
    """50,00 e 100,00 convivendo: pela menor, todo valor da maior também fecha,
    e a diferença entre pagar uma inteira e duas meias sumiria."""
    assert aud._unidades(100.0, [50.0, 100.0]) == (100.0, 1)


def test_valor_que_nao_fecha_com_tarifa_nenhuma_devolve_None():
    assert aud._unidades(123.45, [57.48, 61.02]) == (None, None)


# ── a semana repetida: o achado que justificou o módulo ─────────────────────


def test_competencia_que_REPETE_outra_por_inteiro_e_achado():
    """2026-07-31 é cópia exata de 2026-07-07: mesmas pessoas, mesmo centavo.
    78 pessoas coincidirem ao centavo não acontece por acaso — uma semana em
    que cada motorista trabalha dias diferentes produz valores diferentes."""
    pagos = [_pag(date(2026, 7, 7), "A", 344.88), _pag(date(2026, 7, 7), "B", 287.40),
             _pag(date(2026, 7, 14), "A", 402.36), _pag(date(2026, 7, 14), "B", 229.92),
             _pag(date(2026, 7, 31), "A", 344.88), _pag(date(2026, 7, 31), "B", 287.40)]
    a = aud.semanas_duplicadas(pagos)
    assert len(a) == 1
    assert a[0]["quando"] == date(2026, 7, 31)
    assert a[0]["copia_de"] == "2026-07-07"
    assert a[0]["severidade"] == "erro"
    assert a[0]["valor"] == 632.28


def test_semana_PARECIDA_nao_e_semana_repetida():
    """A assinatura é o conjunto (pessoa, valor) inteiro, e não o total: dois
    totais podem coincidir por acaso, o conjunto não. Sem isso a régua acusaria
    semanas normais e ninguém confiaria nela."""
    pagos = [_pag(date(2026, 7, 7), "A", 300.0), _pag(date(2026, 7, 7), "B", 200.0),
             # mesmo TOTAL de R$ 500, pessoas com valores trocados
             _pag(date(2026, 7, 14), "A", 200.0), _pag(date(2026, 7, 14), "B", 300.0)]
    assert aud.semanas_duplicadas(pagos) == []


def test_a_folha_MENSAL_fica_de_fora_da_regua_de_repeticao():
    """A mensal É a soma das semanais por construção (`diarias._consolidar`).
    Compará-la com uma semanal reencontraria aquela duplicidade, e a régua
    acusaria TODO mês — vermelho permanente, que ninguém lê."""
    sql = " ".join(aud.PAGAMENTOS_SQL.split())
    assert "tipo_folha IS DISTINCT FROM 1" in sql, (
        "a auditoria voltou a ler a folha mensal junto com a semanal")


# ── agrupar: repetição do mesmo fato não é recorrência ──────────────────────


def _fora(dia, nome, filial, valor):
    return {"quando": dia, "nome": nome, "filial": filial,
            "matricula": "1", "cargo": "MOT", "valor": valor}


def test_a_filial_inteira_fora_da_tarifa_no_mesmo_dia_vira_UM_lote():
    dia = date(2026, 7, 21)
    xs = [_fora(dia, "A", "MTZ", 370.0), _fora(dia, "B", "MTZ", 580.0),
          _fora(dia, "C", "MTZ", 625.0), _fora(dia, "D", "MTZ", 805.0)]
    a = aud._agrupar_fora_da_tarifa(xs, {"MTZ": {"taxas": [50.0, 55.0]}},
                                    {"MTZ": 6000.0})
    assert len(a) == 1, "quatro pessoas viraram quatro achados"
    assert a[0]["tipo"] == "tarifa_lote" and a[0]["pessoas"] == 4


def test_o_lote_cujo_MDC_e_a_DIFERENCA_entre_tarifas_e_o_RETROATIVO():
    """Em 21/07/2026, na MTZ, o MDC dos desvios deu R$ 5,00 — exatamente
    55,00 − 50,00. Reconhecer isso muda a pergunta para a folha de "o que é
    isto?" para "confirma que é o retroativo?", e tira o achado do vermelho."""
    dia = date(2026, 7, 21)
    xs = [_fora(dia, n, "MTZ", v) for n, v in
          (("A", 370.0), ("B", 580.0), ("C", 625.0), ("D", 805.0))]
    a = aud._agrupar_fora_da_tarifa(xs, {"MTZ": {"taxas": [50.0, 55.0]}},
                                    {"MTZ": 6000.0})[0]
    assert a["mdc"] == 5.0
    assert a["severidade"] == "revisar", "o retroativo do reajuste não é erro"
    assert "retroativo" in a["titulo"]


def test_lote_cujo_MDC_nao_bate_com_diferenca_nenhuma_continua_ERRO():
    """É o caso de CRZ 01/09 e SBC 09/06: o MDC não é a diferença entre duas
    tarifas conhecidas, então não há explicação à mão e o achado fica em
    vermelho, que é onde deve ficar até alguém explicar."""
    dia = date(2026, 9, 1)
    xs = [_fora(dia, n, "CRZ", v) for n, v in
          (("A", 805.03), ("B", 817.16), ("C", 849.98), ("D", 938.14))]
    a = aud._agrupar_fora_da_tarifa(xs, {"CRZ": {"taxas": [57.48]}},
                                    {"CRZ": 6500.0})[0]
    assert a["severidade"] == "erro"
    assert a["vezes_a_tipica"] and a["vezes_a_tipica"] > 0


def test_desvio_de_POUCAS_pessoas_continua_individual():
    """Lote é evento de folha; duas pessoas é erro de duas pessoas, e cada uma
    precisa aparecer com o nome dela."""
    dia = date(2026, 5, 5)
    xs = [_fora(dia, "A", "CRZ", 123.45), _fora(dia, "B", "CRZ", 543.21)]
    a = aud._agrupar_fora_da_tarifa(xs, {"CRZ": {"taxas": [57.48]}}, {})
    assert len(a) == 2 and all(x["tipo"] == "tarifa" for x in a)
    assert {x["nome"] for x in a} == {"A", "B"}


def test_sem_filial_vira_um_achado_por_PESSOA_e_nao_por_pagamento():
    """São 12 pessoas e 267 pagamentos em 2026. Uma linha por pagamento faria
    desta régua uma parede em que as outras somem — e a pergunta é uma só por
    pessoa, não uma por semana."""
    xs = [_fora(date(2026, 1, 6), "A", None, 100.0),
          _fora(date(2026, 1, 13), "A", None, 200.0),
          _fora(date(2026, 2, 3), "A", None, 300.0),
          _fora(date(2026, 1, 6), "B", None, 50.0)]
    a = aud._juntar_sem_filial(xs)
    assert len(a) == 2
    assert a[0]["nome"] == "A" and a[0]["valor"] == 600.0
    assert a[0]["pagamentos"] == 3
    assert "2026-01-06" in a[0]["detalhe"] and "2026-02-03" in a[0]["detalhe"]


# ── o dinheiro não se conta duas vezes ──────────────────────────────────────


def test_achado_DENTRO_de_um_lote_nao_soma_de_novo():
    """A semana repetida traz R$ 32 mil e, dentro dela, os achados individuais
    da mesma data. Somar os dois seria cometer, no relatório de auditoria,
    exatamente o erro que ele existe para achar."""
    dia = date(2026, 7, 31)
    achados = [
        aud._achado("competencia_duplicada", "erro", "x", quando=dia,
                    filial=None, valor=32063.63),
        aud._achado("ausencia", "erro", "y", quando=dia, filial="SBC",
                    valor=700.0),
        aud._achado("sem_jornada", "erro", "z", quando=date(2026, 6, 2),
                    filial="SBC", valor=610.20),
    ]
    assert aud._dinheiro_sem_repetir(achados) == pytest.approx(32063.63 + 610.20)


def test_lote_de_FILIAL_so_engole_achado_da_MESMA_filial():
    """O lote da SBC não explica o achado da CRZ no mesmo dia — engolir por
    data faria a régua esconder dinheiro de outra filial."""
    dia = date(2026, 6, 9)
    achados = [
        aud._achado("tarifa_lote", "erro", "x", quando=dia, filial="SBC",
                    valor=13444.59),
        aud._achado("sem_jornada", "erro", "y", quando=dia, filial="CRZ",
                    valor=500.0),
    ]
    assert aud._dinheiro_sem_repetir(achados) == pytest.approx(13944.59)


def test_o_resumo_PUBLICA_o_total_sem_repetir_e_nao_so_a_funcao():
    """O guard que faltava, e a lição de como ele faltou.

    Os dois testes acima chamam `_dinheiro_sem_repetir` DIRETO. Sabotar o lugar
    que a usa — trocar a chamada em `_resumo` por um `sum` cru — deixava os dois
    VERDES: a função continuava certa, só tinha parado de ser usada. Verde que
    nunca ficaria vermelho não conferiu nada, e aqui ele cobria justamente o
    número que a tela mostra.

    Este passa por `auditar()` e cobra o valor publicado no resumo.
    """
    from datetime import timedelta
    dias_uteis = [date(2026, 3, 1) + timedelta(days=i) for i in range(60)]
    jornada = [{"nome": n, "data": d, "filial": "CRZ", "min_total": 600}
               for n in ("A", "B", "C", "D", "E") for d in dias_uteis]
    # F tem filial conhecida e NENHUM dia trabalhado
    jornada += [{"nome": "F", "data": date(2026, 3, 2), "filial": "CRZ",
                 "min_total": 0}]

    semana = [287.40] * 6                       # 5 x 57,48, seis pessoas
    quem = ("A", "B", "C", "D", "E", "F")
    pagos = []
    for dia in (date(2026, 3, 3), date(2026, 3, 10)):   # a segunda é cópia
        pagos += [_pag(dia, n, v) for n, v in zip(quem, semana)]
    # segundo mês, para a tarifa de 57,48 virar catálogo
    pagos += [_pag(date(2026, 4, 7), n, 287.40) for n in quem[:5]]

    r = aud.auditar({"pagamentos": pagos, "granular": [], "jornada": jornada,
                     "ausencias": [], "de": date(2026, 3, 1),
                     "ate": date(2026, 5, 1)})
    tipos = [a["tipo"] for a in r["achados"]]
    assert tipos.count("competencia_duplicada") == 1, tipos
    assert tipos.count("sem_jornada") == 2, "F devia cair nas duas datas"

    dup = 287.40 * 6                            # a semana repetida inteira
    fora = 287.40                               # o F da data NÃO duplicada
    assert r["resumo"]["valor_em_erro"] == pytest.approx(dup + fora), (
        "o resumo somou de novo o achado que já estava dentro da semana "
        "repetida — o relatório de auditoria cometeu o erro que ele acha")


# ── ausência ────────────────────────────────────────────────────────────────


def test_ausencia_sem_FIM_nao_engole_o_ano_do_motorista():
    """Afastamento com `fim` vazio apareceria como ausência eterna e calaria
    todas as outras réguas para aquela pessoa — uma linha mal fechada tirando
    um motorista inteiro da auditoria, sem sintoma."""
    from datetime import datetime
    linhas = [{"nome": "A", "tipo": "AFASTAMENTO",
               "inicio": datetime(2026, 1, 5), "fim": datetime(2030, 1, 1)}]
    dias = aud._dias_de_ausencia(linhas)
    assert list(dias["A"]) == [date(2026, 1, 5)]


def test_ausencia_normal_vira_todos_os_dias_do_intervalo():
    from datetime import datetime
    linhas = [{"nome": "A", "tipo": "ATESTADO MEDICO",
               "inicio": datetime(2026, 3, 2), "fim": datetime(2026, 3, 5)}]
    dias = aud._dias_de_ausencia(linhas)
    assert sorted(dias["A"]) == [date(2026, 3, d) for d in (2, 3, 4, 5)]
    assert dias["A"][date(2026, 3, 3)] == "ATESTADO MEDICO"


# ── os limites que a tela precisa dizer ─────────────────────────────────────


def test_a_janela_do_teto_e_de_CATORZE_dias():
    """Medido: em 7 dias a régua reprova 33,5% da folha, que é a defasagem da
    competência e não erro de ninguém; em 14, 3,7%. Apertar isto sem refazer a
    medição transforma a auditoria em gerador de falso alarme."""
    assert aud.JANELA_TETO_DIAS == 14
    assert aud.MEIAS_POR_DIA == 2


def test_a_leitura_da_jornada_tem_FOLGA_para_tras():
    """A régua do teto olha os 14 dias ANTERIORES ao pagamento. Sem a folga na
    consulta, o primeiro pagamento do recorte seria julgado contra uma janela
    vazia — acusando quem só teve o azar de estar na borda."""
    import api.jornada.auditoria_diarias as m
    chamadas = []

    class _FalsoPG:
        @staticmethod
        def query(sql, params, esquema=None):
            chamadas.append(params)
            return []

    class _FalsoAVA:
        @staticmethod
        def query(sql, params):
            return []

    m.db, m.pglocal = _FalsoAVA, _FalsoPG
    try:
        m.levantar(date(2026, 3, 1), date(2026, 4, 1))
    finally:
        from api import db as _db, pglocal as _pg
        m.db, m.pglocal = _db, _pg
    assert chamadas, "a jornada não foi consultada"
    assert chamadas[0]["de"] == date(2026, 3, 1) - __import__(
        "datetime").timedelta(days=aud.JANELA_TETO_DIAS)


def test_as_reguas_por_DIA_dizem_quando_NAO_rodam():
    """A carga por dia parou em 12/02/2026. Quando o recorte não a alcança, as
    duas réguas que olham a diária individual não rodam — e régua que some sem
    dizer nada se lê como régua que passou."""
    dados = {"pagamentos": [], "granular": [], "jornada": [], "ausencias": [],
             "de": date(2026, 6, 1), "ate": date(2026, 7, 1)}
    r = aud.auditar(dados)
    assert r["resumo"]["granular_aplicavel"] is False
    assert r["resumo"]["granular_dias"] == 0


def test_as_fontes_MORTAS_saem_com_a_DATA_em_que_pararam():
    """A tela diz a data, nunca "faz tempo" — é a lição da RasterJOR que ficou
    136 dias fora do ar sem ninguém notar, porque o sintoma é uma tela vazia e
    tela vazia se lê como "ninguém rodou"."""
    assert aud.DIAGNOSTICO_FONTES, "o diagnóstico das fontes sumiu"
    for f in aud.DIAGNOSTICO_FONTES:
        assert f["parou"] and len(f["parou"]) == 10, f
        assert f["custo"], "fonte morta sem dizer o que a morte dela custa"
    graves = [f for f in aud.DIAGNOSTICO_FONTES if f["grave"]]
    assert any("integracao_diarias_rasterjor" in f["fonte"] for f in graves), (
        "a carga que sustentava a auditoria por dia precisa estar entre as graves")


def test_severidade_desconhecida_ESTOURA_em_vez_de_passar():
    """Severidade que a tela não conhece cairia num `if` sem `else` e sairia
    sem cor nenhuma — achado grave desenhado como informação."""
    with pytest.raises(ValueError):
        aud._achado("x", "gravissimo", "t")


def test_a_auditoria_NAO_julga_meia_contra_inteira():
    """O limite que este módulo escolheu, e que precisa continuar escolhido.

    A regra de quem tem direito a meia ou a inteira depende de pernoite,
    distância e acordo — e foi MEDIDO que ela não se deriva da jornada (meia e
    inteira têm p05 zero de direção nas duas e faixas sobrepostas em todo o
    miolo). Uma régua que classificasse isso erraria em silêncio e a tela
    passaria a acusar gente por palpite.
    """
    tipos = {a["tipo"] for a in aud.auditar(
        {"pagamentos": [], "granular": [], "jornada": [], "ausencias": [],
         "de": date(2026, 1, 1), "ate": date(2026, 2, 1)})["achados"]}
    proibidos = {"meia_indevida", "inteira_indevida", "tipo_errado"}
    assert not (tipos & proibidos)
    fonte = __import__("pathlib").Path(aud.__file__).read_text(encoding="utf-8")
    assert "não julga" in fonte or "NÃO julga" in fonte
