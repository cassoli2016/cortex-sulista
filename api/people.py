"""People Analytics — o que as outras telas de RH não respondem.

NÃO REPETE O QUE JÁ EXISTE. Headcount já dá quadro, admissões, demissões e
turnover; Custo de Folha dá proventos e descontos por competência. Aqui entra o
que nenhuma das duas responde e decide gente: quem está afastado e há quanto
tempo, onde está o risco de sucessão, quanto custa cada área, qual a dispersão
salarial dentro do mesmo cargo, e em que momento da casa as pessoas saem.

LIDERANÇA É POR TÍTULO DO CARGO, e o título mora em `descfuncaocompleta` —
NÃO em `descfuncao`, que é `VARCHAR2(16)` e chega truncado ("COOR DE FATURAM",
"GER DE PROJETOS"). Filtrar pelo campo curto perderia chefia de verdade.

ATIVO É `vw_funcionarios.situacaofunc = 'A'`, a mesma definição do Headcount.
A tela de CNH já errou isso uma vez contando demitido como ativo, e duas telas
de RH com noções diferentes de quem trabalha aqui é defeito por construção.

AFASTADO NÃO É DEMITIDO NEM É ATIVO. O ERP usa a situação 'F': 12 pessoas hoje.
Elas continuam sendo da empresa (voltam), mas não estão no posto — somá-las ao
quadro ativo inflaria a capacidade, e ignorá-las esconderia o custo e a
reposição. Ficam contadas à parte, sempre.

FALECIMENTO É OUTRA COISA. Há afastamentos abertos de gente já desligada, e a
maioria tem motivo 12 = FALECIMENTO: o registro está certo — morte não tem data
de retorno. Tratá-los como "ficha nunca encerrada" seria acusar o cadastro de
um erro que não cometeu, e é o tipo de engano que só se evita lendo a tabela de
domínio antes de concluir.
"""
from __future__ import annotations

from .queries_folha import EMPRESA, _q

# Motivo de afastamento que significa desligamento definitivo — não volta e não
# entra em nenhuma conta de "quando retorna".
COND_FALECIMENTO = 12

# Acima disto um afastamento aberto deixa de ser acompanhamento e vira algo a
# conferir com o RH. Não é erro por si: auxílio-doença longo existe. Mas 5 anos
# sem retorno nem conversão em aposentadoria pede uma olhada humana.
AFASTAMENTO_LONGO_DIAS = 1825

_ATIVO = "vf.codigoempresa = :emp AND vf.situacaofunc = 'A'"

# LIDERANÇA — coordenador, supervisor, gerente e diretor, como o negócio define.
#
# CASA NO INÍCIO DE PALAVRA, e isso não é preciosismo de expressão regular: um
# `LIKE '%GER%'` ingênuo classificaria AJUDANTE GERAL, AUXILIAR SERVICOS GERAIS
# e SERVENTE LIMPEZA E SERVIÇOS GERAIS como gerência — três pessoas do chão de
# fábrica viradas em chefia, inflando massa salarial de liderança e esvaziando
# a de operação. Medido nesta base.
#
# OS PREFIXOS CURTOS SÃO OBRIGATÓRIOS, e a razão está no cadastro, não no
# truncamento: existe "COORD DE SUPORTE E IMPLANTAÇÃO" escrito assim no campo
# COMPLETO. `COORDENADOR%` sozinho deixaria essa pessoa de fora. `COOR%` cobre
# as duas grafias e não colide com nada — nenhuma outra função da base começa
# por COOR.
#
# `SUPERV%` pelo mesmo motivo; `DIRETOR%` fica inteiro porque `DIR%` alcançaria
# palavras comuns num título de cargo.
#
# NÃO ENTRAM, e a tela diz isso em vez de deixar quem lê adivinhar: LIDER DE
# PATIO e LIDER OPERACAO (liderança de turno, faixa salarial de analista, e o
# negócio não os listou), BUSINESS PARTNER, CONTADOR e ESPECIALISTA — senioridade
# alta sem equipe. Se um dia entrarem, entram aqui, não numa exceção na tela.
# O TRIM/UPPER não é cosmético: o cadastro tem "AUXILIAR ADMINISTRATIVO" e
# "AUXILIAR ADMINISTRATIVo", e sem normalizar a tela contaria dois cargos onde
# há um — medindo grafia em vez de função. Mesma razão de o telefone do
# WhatsApp ser guardado normalizado.
_CARGO = "UPPER(TRIM(vf.descfuncaocompleta))"
_CAMPO_CARGO = _CARGO
_PREFIXOS_LIDER = ("GERENTE", "COOR", "SUPERV", "DIRETOR")
LIDERANCA = "(" + " OR ".join(
    f"{_CAMPO_CARGO} LIKE '{p}%' OR {_CAMPO_CARGO} LIKE '% {p}%'"
    for p in _PREFIXOS_LIDER) + ")"

# Os que ficaram de fora por decisão, para a tela poder mostrá-los. É a mesma
# regra do "cobertura ruim de campo é informação, não sujeira para esconder":
# quem discorda da classificação precisa ver o que foi excluído.
_LIMITROFES = ("LIDER", "BUSINESS PARTNER", "CONTADOR", "ESPECIALISTA", "ESP ")

ESCOPOS = ("todos", "lideranca", "demais")


def _escopo_sql(escopo: str) -> str:
    """O recorte vira uma condição que TODA consulta da tela recebe.

    Filtro que só alguns cartões obedecem é pior que filtro nenhum: foi o que
    fazia a Análise de KM dizer 143.326 km vazios no cabeçalho e 95.632 na
    tabela logo abaixo, com o mesmo filtro aplicado.
    """
    if escopo == "lideranca":
        return f" AND {LIDERANCA}"
    if escopo == "demais":
        return f" AND NOT {LIDERANCA}"
    return ""


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def get_people(escopo: str = "todos") -> dict:
    escopo = escopo if escopo in ESCOPOS else "todos"
    esc = _escopo_sql(escopo)          # entra em TODA consulta desta função
    p = {"emp": EMPRESA}

    # ------------------------------------------------------------ quadro
    tot = _q(f"""
        SELECT COUNT(*) ativos,
               ROUND(SUM(vf.salbase), 2) massa,
               ROUND(AVG(vf.salbase), 2) media,
               ROUND(MEDIAN(vf.salbase), 2) mediana,
               ROUND(MEDIAN(MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc)/12), 1) casa_mediana,
               ROUND(MEDIAN(MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12), 1) idade_mediana,
               SUM(CASE WHEN vf.sexofunc='F' THEN 1 ELSE 0 END) mulheres,
               SUM(CASE WHEN MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12 >= 60
                        THEN 1 ELSE 0 END) sessenta_mais,
               SUM(CASE WHEN MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) <= 12
                        THEN 1 ELSE 0 END) menos_1_ano
        FROM vw_funcionarios vf WHERE {_ATIVO}{esc}""", p)[0]
    n = tot["ativos"] or 0

    # AFASTADOS: situacao 'F'. Nao entram no quadro ativo — somar inflaria a
    # capacidade; ignorar esconderia o custo e a reposicao.
    afast = _q(f"""
        SELECT COUNT(*) n, ROUND(SUM(vf.salbase),2) massa
        FROM vw_funcionarios vf
        WHERE vf.codigoempresa = :emp AND vf.situacaofunc = 'F'{esc}""", p)[0]

    # ---------------------------------------------------- afastamentos
    linhas_afast = [
        {"nome": r["nome"], "funcao": r["fun"], "filial": r["fil"],
         "motivo": (r["motivo"] or "").strip() or f"código {r['cond']}",
         "inicio": r["ini"], "dias": int(r["dias"] or 0),
         "na_empresa": r["sit"] == "F",
         "obito": r["cond"] == COND_FALECIMENTO,
         "longo": int(r["dias"] or 0) > AFASTAMENTO_LONGO_DIAS
         and r["cond"] != COND_FALECIMENTO}
        for r in _q(f"""
            SELECT vf.nomefunc nome, vf.descfuncaocompleta fun, vf.descsecao fil,
                   vf.situacaofunc sit, a.codcondi cond, c.desccondi motivo,
                   TO_CHAR(a.dtafast,'YYYY-MM-DD') ini,
                   TRUNC(SYSDATE) - TRUNC(a.dtafast) dias
            FROM flp_afastados a
            JOIN vw_funcionarios vf ON vf.codintfunc = a.codintfunc
            LEFT JOIN flp_condicao c ON c.codcondi = a.codcondi
            WHERE vf.codigoempresa = :emp AND a.dtretafast IS NULL{esc}
            ORDER BY a.dtafast""", p)]
    abertos_empresa = [x for x in linhas_afast if x["na_empresa"]]
    obitos = [x for x in linhas_afast if x["obito"]]
    longos = [x for x in abertos_empresa if x["longo"]]

    por_motivo: dict[str, int] = {}
    for x in abertos_empresa:
        por_motivo[x["motivo"]] = por_motivo.get(x["motivo"], 0) + 1

    # ------------------------------------------------- estrutura e custo
    por_area = [
        {"area": r["area"] or "(sem área)", "n": r["n"],
         "massa": r["massa"] or 0.0, "media": r["media"] or 0.0,
         "casa": r["casa"], "pct_massa": None}
        for r in _q(f"""
            SELECT vf.descarea area, COUNT(*) n,
                   ROUND(SUM(vf.salbase),2) massa, ROUND(AVG(vf.salbase),2) media,
                   ROUND(MEDIAN(MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc)/12),1) casa
            FROM vw_funcionarios vf WHERE {_ATIVO}{esc}
            GROUP BY vf.descarea ORDER BY SUM(vf.salbase) DESC""", p)]
    massa = tot["massa"] or 0.0
    for a in por_area:
        a["pct_massa"] = _pct(a["massa"], massa) if massa else None

    # CARGOS: dispersao dentro do MESMO cargo. Amplitude grande num cargo com
    # muita gente e onde mora discussao de equidade e de enquadramento.
    cargos = [
        {"cargo": r["cargo"] or "(sem função)", "n": r["n"],
         "menor": r["menor"], "mediana": r["mediana"], "maior": r["maior"],
         "amplitude": (round(r["maior"] / r["menor"], 2)
                       if r["menor"] and r["maior"] else None),
         "massa": r["massa"] or 0.0}
        for r in _q(f"""
            SELECT {_CARGO} cargo, COUNT(*) n,
                   ROUND(MIN(vf.salbase),2) menor,
                   ROUND(MEDIAN(vf.salbase),2) mediana,
                   ROUND(MAX(vf.salbase),2) maior,
                   ROUND(SUM(vf.salbase),2) massa
            FROM vw_funcionarios vf WHERE {_ATIVO}{esc}
            GROUP BY {_CARGO} ORDER BY COUNT(*) DESC""", p)]
    # SUCESSAO: funcao com UMA pessoa e ponto unico de falha; com salario alto,
    # e um ponto unico de falha caro.
    unicos = sorted((c for c in cargos if c["n"] == 1),
                    key=lambda c: -(c["massa"] or 0))

    piramide = _q(f"""
        SELECT faixa, COUNT(*) n, ROUND(SUM(salbase),2) massa FROM (
          SELECT CASE
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12 < 25 THEN '1 · até 24'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12 < 35 THEN '2 · 25 a 34'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12 < 45 THEN '3 · 35 a 44'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12 < 55 THEN '4 · 45 a 54'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtnasctofunc)/12 < 60 THEN '5 · 55 a 59'
            ELSE '6 · 60 ou mais' END faixa, vf.salbase
          FROM vw_funcionarios vf WHERE {_ATIVO}{esc})
        GROUP BY faixa ORDER BY faixa""", p)

    casa = _q(f"""
        SELECT faixa, COUNT(*) n FROM (
          SELECT CASE
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) <= 3  THEN '1 · até 3 meses'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) <= 12 THEN '2 · até 1 ano'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) <= 36 THEN '3 · 1 a 3 anos'
            WHEN MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) <= 120 THEN '4 · 3 a 10 anos'
            ELSE '5 · mais de 10 anos' END faixa
          FROM vw_funcionarios vf WHERE {_ATIVO}{esc})
        GROUP BY faixa ORDER BY faixa""", p)

    # SAIDA POR TEMPO DE CASA: NAO ENTRA NESTA TELA, e a razao importa.
    #
    # A pergunta e boa — quem sai nos primeiros meses e falha de recrutamento,
    # quem sai depois de anos e outra conversa. O dado e que nao sustenta: a
    # unica data de saida em `vw_funcionarios` e DATATERMINOCONTRATO, que o
    # proprio Headcount ja anotou como subcontando muito, e medida aqui ela
    # devolveu 18 saidas em 12 meses TODAS na faixa de 1 a 3 anos, com zero em
    # todas as outras. Distribuicao assim nao existe numa empresa de verdade.
    #
    # Publicar isso seria inventar um achado. A fonte boa de desligamento e o
    # evento de aviso previo na folha (`flp_fichaeventos`), que o Headcount ja
    # usa para a serie de demissoes — cruzar com tempo de casa por ali e
    # trabalho de outra rodada, com a conferencia que ele merece.

    # ------------------------------------------------- leitura da liderança
    # Vai SEMPRE, em qualquer escopo: em "Todos" é a proporção de chefia no
    # quadro; em "Liderança" é a conferência do próprio filtro. Quem discorda
    # da classificação precisa ver exatamente quem entrou — filtro que não se
    # audita vira número que ninguém defende numa reunião.
    lid_cargos = [
        {"cargo": r["cargo"] or "(sem função)", "n": r["n"],
         "massa": r["massa"] or 0.0, "media": r["media"] or 0.0}
        for r in _q(f"""
            SELECT {_CARGO} cargo, COUNT(*) n,
                   ROUND(SUM(vf.salbase),2) massa, ROUND(AVG(vf.salbase),2) media
            FROM vw_funcionarios vf WHERE {_ATIVO} AND {LIDERANCA}
            GROUP BY {_CARGO} ORDER BY AVG(vf.salbase) DESC""", p)]
    lid_n = sum(c["n"] for c in lid_cargos)
    lid_massa = sum(c["massa"] for c in lid_cargos)

    # Total do QUADRO INTEIRO — não do escopo. É o denominador de "quantos por
    # liderado", e usar o total filtrado daria 1 para 1 na aba Liderança.
    geral = _q(f"""SELECT COUNT(*) n, ROUND(SUM(vf.salbase),2) massa
                   FROM vw_funcionarios vf WHERE {_ATIVO}""", p)[0]
    geral_n = geral["n"] or 0

    # OS LIMÍTROFES. Declarados, não escondidos: são os cargos que alguém pode
    # esperar ver em liderança e que a regra deixou de fora de propósito.
    _lim = " OR ".join(f"{_CAMPO_CARGO} LIKE '{t}%' OR {_CAMPO_CARGO} LIKE '% {t}%'"
                       for t in _LIMITROFES)
    limitrofes = [
        {"cargo": r["cargo"] or "(sem função)", "n": r["n"], "media": r["media"] or 0.0}
        for r in _q(f"""
            SELECT {_CARGO} cargo, COUNT(*) n,
                   ROUND(AVG(vf.salbase),2) media
            FROM vw_funcionarios vf WHERE {_ATIVO} AND ({_lim}) AND NOT {LIDERANCA}
            GROUP BY {_CARGO} ORDER BY AVG(vf.salbase) DESC""", p)]

    # QUAIS DOS QUATRO NÍVEIS EXISTEM DE FATO. Sem isto a aba mostraria zero
    # diretores em silêncio, e zero silencioso lê-se como filtro quebrado — a
    # mesma regra do "zero que é ausência de lançamento não é desempenho".
    niveis = []
    for rotulo, prefixos in (("Diretor", ("DIRETOR",)), ("Gerente", ("GERENTE",)),
                             ("Coordenador", ("COOR",)), ("Supervisor", ("SUPERV",))):
        cond = " OR ".join(f"{_CAMPO_CARGO} LIKE '{x}%' OR {_CAMPO_CARGO} LIKE '% {x}%'"
                           for x in prefixos)
        r = _q(f"""SELECT COUNT(*) n, ROUND(SUM(vf.salbase),2) massa
                   FROM vw_funcionarios vf WHERE {_ATIVO} AND ({cond})""", p)[0]
        # Havia esse cargo na casa algum dia? É o que separa "nunca existiu"
        # de "existiu e hoje não há".
        j = _q(f"""SELECT COUNT(*) n FROM vw_funcionarios vf
                   WHERE vf.codigoempresa = :emp AND ({cond})""", p)[0]["n"] or 0
        niveis.append({"nivel": rotulo, "n": r["n"] or 0,
                       "massa": r["massa"] or 0.0, "ja_existiu": j > 0})

    return {
        "escopo": escopo,
        "lideranca": {
            "n": lid_n, "massa": lid_massa,
            "pct_pessoas": _pct(lid_n, geral_n),
            "pct_massa": (round(100 * lid_massa / (geral["massa"] or 1), 1)
                          if geral["massa"] else None),
            "quadro_total": geral_n,
            "por_liderado": (round((geral_n - lid_n) / lid_n, 1) if lid_n else None),
            "cargos": lid_cargos,
            "niveis": niveis,
            "limitrofes": limitrofes,
        },
        "kpis": {
            "ativos": n,
            "afastados": afast["n"] or 0,
            "afastados_massa": afast["massa"] or 0.0,
            "massa": massa,
            "salario_medio": tot["media"],
            "salario_mediano": tot["mediana"],
            "casa_mediana": tot["casa_mediana"],
            "idade_mediana": tot["idade_mediana"],
            "mulheres": tot["mulheres"] or 0,
            "pct_mulheres": _pct(tot["mulheres"] or 0, n),
            "sessenta_mais": tot["sessenta_mais"] or 0,
            "pct_sessenta": _pct(tot["sessenta_mais"] or 0, n),
            "menos_1_ano": tot["menos_1_ano"] or 0,
            "pct_menos_1_ano": _pct(tot["menos_1_ano"] or 0, n),
            "cargos": len(cargos),
            "cargos_unicos": len(unicos),
            "areas": len(por_area),
            "afast_longos": len(longos),
            "afast_obitos": len(obitos),
        },
        "piramide": [{"faixa": r["faixa"], "n": r["n"], "massa": r["massa"] or 0.0}
                     for r in piramide],
        "tempo_casa": [{"faixa": r["faixa"], "n": r["n"]} for r in casa],
        "por_area": por_area,
        "cargos": cargos,
        "cargos_unicos": unicos,
        "afastamentos": abertos_empresa,
        "afast_obitos": obitos,
        "por_motivo": por_motivo,
        "fonte": "ERP GLOBUS · vw_funcionarios × flp_afastados",
        "atualizado_em": _q("SELECT TO_CHAR(SYSDATE,'YYYY-MM-DD HH24:MI') a "
                            "FROM dual")[0]["a"],
    }
