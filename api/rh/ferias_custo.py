"""Custo de férias — o que JÁ FOI PAGO e o que está PROVISIONADO.

A tela de Férias respondia "quem precisa gozar". Não respondia "quanto isso
custa", que é a pergunta de quem aprova a escala. Este módulo entrega os dois
lados, e eles vêm de fontes de qualidade diferente — por isso não se somam num
número só:

  REALIZADO  — eventos da ficha financeira (`flp_fichaeventos`). É o que a
               folha pagou, sem estimativa nenhuma.
  PROVISÃO   — o passivo de quem ainda não gozou. É ESTIMATIVA sobre o salário
               base, e o módulo MEDE o quanto ela subestima em vez de afirmar
               que está certa (ver `fator`, no fim).

O EVENTO QUE PROVA QUE A DOBRA NÃO É HIPÓTESE
=============================================
`FERIAS EM DOBRO`, `1/3 FERIAS EM DOBRO` e as diferenças delas somam
R$ 12.154 em 12 meses, em 23 lançamentos. O KPI de dobra da tela de risco lê ZERO hoje — e está certo: ele
mede o estado AGORA, e a dobra que houve já foi paga e quitada. Os dois números
não se contradizem, medem tempos diferentes, e é por isso que este cartão
existe: sem ele, "nenhuma em dobra" se leria como "isto nunca acontece aqui".

O EVENTO TRUNCADO QUE NÃO ENTRA NO TOTAL
========================================
O GLOBUS trunca `desceven` em 22 caracteres. `MEDIAS S/ VARIAVEIS -` (códigos
109 e 110, mais as quatro diferenças dele: R$ 190.822 em 12 meses)
provavelmente termina em "FERIAS": 679 dos 768 lançamentos caem numa
competência em que a MESMA pessoa recebeu férias.
89% não é evidência, é indício — então ele fica FORA do total afirmado e
aparece como linha própria, com o percentual à mostra. É a mesma regra da
coluna "Tipo (cód.)" da Manutenção: código sem domínio não vira rótulo
inventado.

O QUE A PROVISÃO NÃO INCLUI, E POR QUE NÃO SE INVENTA
=====================================================
- **FGTS entra**: 8% fixados em lei, iguais para todo regime, e a alíquota é
  dita na tela.
- **INSS patronal NÃO entra**: a alíquota depende do enquadramento e há
  eventos de SIMPLES na ficha desta empresa. Estimar 20% somaria milhões
  inventados. Mesma decisão do Custo de Folha.
- **As médias de variáveis não entram na estimativa**, porque a base é o
  salário BASE. A folha real paga média de hora extra e adicional noturno
  sobre as férias — então o passivo real é MAIOR que o estimado. O módulo não
  se cala sobre isso: mede o fator no realizado e o entrega em `fator`.

CUIDADO COM A FICHA CANCELADA
=============================
`flp_ferias.statusferias='S'` é ficha EXCLUÍDA (230 de 233 têm `dtexclferias`),
não "sim". Contar dias por ela inflaria o denominador do custo por dia em 42%.
O filtro é `dtexclferias IS NULL`.
"""
from __future__ import annotations

from api import db_folha as db
from api.queries_folha import _janela_futura

EMPRESA = 1

# Um terço constitucional (art. 7º, XVII): o custo de um dia de férias é 4/3 do
# dia de salário.
UM_TERCO = 4.0 / 3.0
FGTS = 0.08
DIAS_MES = 30.0
DIAS_PERIODO = 30.0          # art. 130, I: 30 dias corridos sem falta relevante
AVO = DIAS_PERIODO / 12.0    # 2,5 dias por mês trabalhado


def _q(sql: str, params: dict | None = None) -> list[dict]:
    """Roda passando SÓ os binds que aparecem no SQL.

    O Oracle recusa bind SOBRANDO com `ORA-01036: illegal variable name/number`
    — e as consultas deste módulo compartilham um dicionário só (empresa,
    datas, unidade, chapa) do qual cada uma usa um subconjunto diferente. É o
    mesmo `_qb` de `queries_folha`, pela mesma razão: sem ele, acrescentar um
    filtro quebra as consultas que não o usam, e o erro aponta para a consulta
    inocente que veio depois."""
    import re as _re
    p = params or {}
    usados = set(_re.findall(r":(\w+)", sql))
    return db.query(sql, {k: v for k, v in p.items() if k in usados})


def _f(v) -> float:
    """`numeric` do banco vira `Decimal`, e o `json` não o serializa — e o
    estouro acontece no `render()` da resposta, DEPOIS do `try/except` da
    rota. Converter no limite do módulo é onde o tipo do banco para de
    importar."""
    return round(float(v or 0), 2)


# ── quais eventos são férias ────────────────────────────────────────────────
#
# Casados por NOME, um a um, contra a lista real de `flp_eventos` desta base —
# não por padrão adivinhado. A ORDEM importa: "1/3 FERIAS EM DOBRO" tem de
# cair em dobra antes de cair em terço, senão o cartão da dobra desapareceria
# dentro do total de férias gozadas, que é justamente onde ninguém o veria.
NATUREZAS = [
    ("Dobra (art. 137)",       ("FERIAS EM DOBRO", "1/3 FERIAS EM DOBRO",
                                "MEDIAS S/ FERIAS EM DO", "MEDIAS S/ ABONO EM DOB",
                                "DIFERENCA DE FERIAS EM")),
    ("Abono pecuniário",       ("ABONO PECUNIARIO", "1/3 S/ ABONO PECUNIARI",
                                "1/3 MEDIA ABONO PEC", "DIFERENCA ABONO DE FER",
                                "DIFERENCA 1/3 S/ ABONO")),
    ("Indenizadas (rescisão)", ("FERIAS INDENIZADAS", "1/3 FERIAS VENCIDAS",
                                "FERIAS 1/3 INDENIZADO", "FERIAS SOBRE AVISO",
                                "FERIAS (MEDIAS)")),
    ("Proporcionais",          ("FERIAS PROPORCIONAIS", "1/3 FERIAS PROPORCIONA",
                                "MEDIAS S/ FERIAS PROPO", "MEDIA HR FER PROPORCIO",
                                "MEDIA VL FER PROPORCIO")),
    ("Gozadas (normais)",      ("FERIAS NORMAIS", "1/3 S/ REMUNERACAO DE",
                                "1/3 MEDIA DE FERIAS", "MEDIAS S/ FERIAS VENCI",
                                "DIFERENCA DE FERIAS NO", "DIFERENCA 1/3 FERIAS N",
                                "DIFERENCA 1/3 S/ REMUN", "DIFEREN_A DE FERIAS")),
]

# O `_` É CURINGA DE UM CARACTERE, e ele existe por um defeito de dado que
# custou R$ 3.843 de custo inventado antes de aparecer.
#
# O evento 490 está gravado como `DIFEREN<Ç>A DE FERIAS`, com o cedilha em
# latin-1 (byte 199) dentro de uma coluna que o resto do ERP escreve sem
# acento. A primeira versão o alcançou pelo prefixo curto `DIFEREN` — que
# casa TAMBÉM `DIFERENCA DE SALARIO`, `DIFERENCA 13o`, `DIFERENCA PTS`,
# `DIFERENCA SALARIO CCT`, `DIFERENCA DE DIARIA` e `DIFERENCA ADIC NOTURNO`.
# Nenhuma delas é férias, e todas entravam no total.
#
# O que torna esse erro da família mais perigosa: R$ 3.843 sobre R$ 1,83
# milhão é 0,21%. Nenhum número muda de ordem de grandeza, nenhuma proporção
# se desloca, nenhum veredito da tela vira. Só apareceu porque a soma do
# módulo foi conferida contra a soma manual dos eventos — um segundo caminho
# para o mesmo número.
_CURINGA = "_"


def _casa(nome: str, padrao: str) -> bool:
    """`startswith` com `_` valendo um caractere qualquer, igual ao LIKE."""
    if len(nome) < len(padrao):
        return False
    return all(p == _CURINGA or p == c for p, c in zip(padrao, nome))


# Os eventos cujo nome o ERP cortou antes de dizer a que eles se referem: os
# dois de `MEDIAS S/ VARIAVEIS -` e as quatro diferenças deles, que herdam a
# mesma dúvida pela mesma razão. Ficam FORA do total — ver o cabeçalho.
CINZA_CODS = (109, 110, 365, 368, 412, 415)
CINZA_NOME = "MEDIAS S/ VARIAVEIS -"

# Só proventos: `tipoeven='B'` são BASES de cálculo (base de IRRF, de INSS) e
# somá-las contaria a mesma férias três vezes; `'D'` são descontos, que saem do
# líquido do empregado e não do custo do empregador.
_PROV = "fe.tipoeven = 'P'"

_JOIN = ("FROM flp_fichaeventos ff "
         "JOIN flp_eventos fe ON ff.codevento = fe.codevento "
         "JOIN flp_funcionarios fu ON fu.codintfunc = ff.codintfunc "
         "AND fu.codigoempresa = :emp")

# Todo nome que este módulo reconhece como férias, para o WHERE.
_TODOS = tuple(sorted({n for _, nomes in NATUREZAS for n in nomes}))
_FILTRO_NOMES = " OR ".join(
    "UPPER(fe.desceven) LIKE '{}%'".format(n.replace("'", "''"))
    for n in _TODOS)


def natureza(desc: str) -> str:
    u = (desc or "").upper().strip()
    for rotulo, nomes in NATUREZAS:
        for n in nomes:
            if _casa(u, n):
                return rotulo
    return "Outras rubricas de férias"


def _periodo(dt_de: str, dt_ate: str) -> tuple[str, str]:
    """Normaliza o intervalo. Sem datas, os últimos 12 meses fechados mais o
    corrente — o recorte que a tela abria antes de o filtro existir.

    As datas chegam em ISO (YYYY-MM-DD) e voltam assim. Qualquer coisa que não
    seja ISO é DESCARTADA em vez de corrigida: adivinhar se `03/04` é março ou
    abril produz um recorte plausível e errado, que é a pior das saídas."""
    import datetime as _dt

    def _ok(s: str) -> str:
        try:
            return _dt.date.fromisoformat((s or "").strip()).isoformat()
        except ValueError:
            return ""

    de, ate = _ok(dt_de), _ok(dt_ate)
    if not de or not ate:
        hoje = _dt.date.today()
        ate = ate or hoje.isoformat()
        # DOZE COMPETÊNCIAS, contando a corrente — o mesmo que o preset
        # "Últimos 12 meses" da tela produz. Recuar 12 meses cheios daria
        # TREZE, e o KPI diria "em 13 meses" sobre um filtro rotulado 12.
        # Dois recortes com o mesmo nome é o começo de uma discussão sobre
        # qual está certo.
        ano, mes = hoje.year, hoje.month - 11
        while mes <= 0:
            ano, mes = ano - 1, mes + 12
        de = de or _dt.date(ano, mes, 1).isoformat()
    if de > ate:
        de, ate = ate, de
    return de, ate


def get_ferias_custo(dt_de: str = "", dt_ate: str = "", filial: str = "",
                     chapa: str = "") -> dict:
    """Custo de férias: realizado na ficha + provisão + o que está agendado.

    O intervalo recorta o que TEM data: o realizado pela competência da ficha e
    as agendadas pela data de início do gozo. O passivo provisionado NÃO segue
    o filtro, e não é omissão — ele é a foto do que se deve HOJE, e recortá-lo
    por um intervalo passado devolveria um número que não significa nada. A
    tela diz isso num selo, porque enterrar a ressalva no texto do ⓘ faz o
    número parecer filtrado quando não é."""
    de, ate = _periodo(dt_de, dt_ate)
    # As AGENDADAS são futuro e o realizado é passado: o mesmo filtro recorta
    # os dois, cada um no seu sentido. Ver `_janela_futura`.
    fde, fate = _janela_futura(dt_de, dt_ate)
    p = {"emp": EMPRESA, "de": de, "ate": ate, "fde": fde, "fate": fate}
    filtro_ev = ""
    if filial:
        # A ficha financeira não carrega a unidade; ela vem do cadastro. Um
        # EXISTS mantém o filtro sem multiplicar linha de evento, que é o que
        # um JOIN a mais faria numa tabela com histórico por competência.
        filtro_ev = (" AND EXISTS (SELECT 1 FROM vw_funcionarios v2"
                     " WHERE v2.codintfunc = ff.codintfunc"
                     " AND v2.descsecao = :filial)")
        p["filial"] = filial
    if chapa:
        filtro_ev += (" AND EXISTS (SELECT 1 FROM vw_funcionarios v3"
                      " WHERE v3.codintfunc = ff.codintfunc"
                      " AND TRIM(v3.chapafunc) = TRIM(:chapa))")
        p["chapa"] = chapa.strip()
    filtro_fil = " AND vf.descsecao = :filial" if filial else ""
    if chapa:
        filtro_fil += " AND TRIM(vf.chapafunc) = TRIM(:chapa)"
    pf = {"emp": EMPRESA, "de": de, "ate": ate, "fde": fde, "fate": fate,
          **({"filial": filial} if filial else {}),
          **({"chapa": chapa.strip()} if chapa else {})}

    # `TRUNC(...,'MM')` no limite inferior: competência é MÊS, e um intervalo
    # que comece dia 15 cortaria a competência inteira daquele mês fora, o que
    # se leria como mês sem férias.
    janela = ("ff.competficha >= TRUNC(TO_DATE(:de,'YYYY-MM-DD'),'MM')"
              " AND ff.competficha <= TO_DATE(:ate,'YYYY-MM-DD')")

    linhas = _q(f"""
        SELECT fe.desceven ev, TO_CHAR(ff.competficha,'YYYY-MM') comp,
               COUNT(*) n, SUM(ff.valorficha) tot
        {_JOIN}
        WHERE {_PROV} AND ({_FILTRO_NOMES}) AND {janela}
          {filtro_ev}
        GROUP BY fe.desceven, TO_CHAR(ff.competficha,'YYYY-MM')""", p)

    # ── realizado: por natureza, por evento e por competência ──────────────
    por_nat: dict[str, dict] = {}
    por_comp: dict[str, float] = {}
    por_ev: dict[str, dict] = {}
    total = 0.0
    for r in linhas:
        v = float(r["tot"] or 0)
        nat = natureza(r["ev"])
        d = por_nat.setdefault(nat, {"natureza": nat, "valor": 0.0, "n": 0})
        d["valor"] += v
        d["n"] += int(r["n"] or 0)
        por_comp[r["comp"]] = por_comp.get(r["comp"], 0.0) + v
        e = por_ev.setdefault(r["ev"], {"ev": r["ev"], "valor": 0.0, "n": 0,
                                        "natureza": nat})
        e["valor"] += v
        e["n"] += int(r["n"] or 0)
        total += v

    dobra_d = por_nat.get("Dobra (art. 137)", {})

    naturezas = sorted(
        ({"natureza": d["natureza"], "valor": _f(d["valor"]), "n": d["n"],
          "pct": round(d["valor"] / total * 100, 1) if total else 0.0}
         for d in por_nat.values()), key=lambda x: -x["valor"])

    eventos = sorted(({"ev": (d["ev"] or "").strip(), "valor": _f(d["valor"]),
                       "n": d["n"], "natureza": d["natureza"]}
                      for d in por_ev.values()), key=lambda x: -x["valor"])

    # A série é GERADA, não colhida. Mês em que ninguém saiu de férias não
    # volta do `GROUP BY`, e o gráfico emendaria o mês anterior no seguinte,
    # desenhando continuidade sobre um buraco — a mesma armadilha que fez a
    # série da jornada ligar abril em agosto. Aqui a ausência é legítima e
    # vale ZERO, então ela precisa aparecer como zero.
    comps = _q("""SELECT TO_CHAR(ADD_MONTHS(TRUNC(TO_DATE(:de,'YYYY-MM-DD'),'MM'),
                                            LEVEL-1),'YYYY-MM') c
                  FROM dual CONNECT BY LEVEL <=
                    MONTHS_BETWEEN(TRUNC(TO_DATE(:ate,'YYYY-MM-DD'),'MM'),
                                   TRUNC(TO_DATE(:de,'YYYY-MM-DD'),'MM')) + 1""",
               {"de": de, "ate": ate})
    serie = [{"comp": c, "valor": _f(por_comp.get(c, 0.0))}
             for c in sorted(x["c"] for x in comps)]
    n_meses = max(1, len(serie))

    # ── a zona cinzenta: evento cujo nome o ERP cortou ─────────────────────
    _cods = ",".join(str(c) for c in CINZA_CODS)
    cinza = _q(f"""
        SELECT COUNT(*) n, SUM(ff.valorficha) tot,
               SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM flp_fichaeventos f2
                     JOIN flp_eventos e2 ON f2.codevento = e2.codevento
                     WHERE f2.codintfunc = ff.codintfunc
                       AND f2.competficha = ff.competficha
                       AND e2.tipoeven = 'P'
                       AND UPPER(e2.desceven) LIKE 'FERIAS%')
                   THEN 1 ELSE 0 END) com_ferias
        FROM flp_fichaeventos ff
        JOIN flp_funcionarios fu ON fu.codintfunc = ff.codintfunc
             AND fu.codigoempresa = :emp
        WHERE ff.codevento IN ({_cods}) {filtro_ev} AND {janela}""", p)[0]
    c_n, c_ok = int(cinza["n"] or 0), int(cinza["com_ferias"] or 0)

    # ── provisão: o passivo de quem ainda não gozou ────────────────────────
    #
    # Dois pedaços somados por pessoa:
    #   VENCIDO — período aquisitivo fechado e não gozado: 30 dias inteiros.
    #   AVOS    — o período EM CURSO, a 2,5 dias por mês completo (art. 130).
    #
    # QUAL período está em curso depende de já haver direito vencido: quem tem,
    # está acumulando o SEGUNDO (que começou no dia seguinte ao fim do
    # primeiro); quem não tem, ainda está no primeiro. Usar sempre a mesma data
    # contaria os avos do período errado — em quem acabou de fechar um período,
    # somaria doze avos dele ao vencido que ele já é, dobrando o passivo dessas
    # pessoas.
    prov = _q(f"""
        SELECT vf.descsecao filial, COUNT(*) pessoas,
               SUM(CASE WHEN fe.proxaquifinfer <= TRUNC(SYSDATE)
                        THEN 1 ELSE 0 END) com_vencido,
               SUM(CASE WHEN fe.proxaquifinfer <= TRUNC(SYSDATE)
                        THEN vf.salbase / :dm * :dp ELSE 0 END) base_vencido,
               SUM(vf.salbase / :dm * :avo * LEAST(12, GREATEST(0,
                   FLOOR(MONTHS_BETWEEN(TRUNC(SYSDATE),
                     CASE WHEN fe.proxaquifinfer <= TRUNC(SYSDATE)
                          THEN fe.proxaquifinfer
                          ELSE fe.proxaquiinifer END))))) base_avos,
               SUM(vf.salbase) massa
        FROM vw_ferias fe
        JOIN vw_funcionarios vf ON vf.codintfunc = fe.codintfunc
        WHERE vf.situacaofunc = 'A' AND vf.codigoempresa = :emp {filtro_fil}
        GROUP BY vf.descsecao ORDER BY 5 DESC""",
              {**pf, "dm": DIAS_MES, "dp": DIAS_PERIODO, "avo": AVO})

    def _prov_linha(r) -> dict:
        venc = float(r["base_vencido"] or 0) * UM_TERCO
        avos = float(r["base_avos"] or 0) * UM_TERCO
        return {"filial": r["filial"] or "(sem unidade)",
                "pessoas": int(r["pessoas"] or 0),
                "com_vencido": int(r["com_vencido"] or 0),
                "vencido": _f(venc), "avos": _f(avos),
                "fgts": _f((venc + avos) * FGTS),
                "total": _f((venc + avos) * (1 + FGTS))}

    prov_l = [_prov_linha(r) for r in prov]
    pr_venc = sum(x["vencido"] for x in prov_l)
    pr_avos = sum(x["avos"] for x in prov_l)
    pr_fgts = sum(x["fgts"] for x in prov_l)

    # ── exposição à dobra: o que vira dobro se ninguém agendar ─────────────
    #
    # A dobra paga o período DUAS vezes, então o custo EVITÁVEL é UMA vez o
    # período — é esse o número que a decisão usa, e não o dobro cheio, que
    # incluiria as férias que teriam de ser pagas de qualquer jeito.
    exp = _q(f"""
        SELECT COUNT(*) n, SUM(vf.salbase / :dm * :dp) base
        FROM vw_ferias fe
        JOIN vw_funcionarios vf ON vf.codintfunc = fe.codintfunc
        WHERE vf.situacaofunc = 'A' AND vf.codigoempresa = :emp {filtro_fil}
          AND fe.proxaquifinfer <= TRUNC(SYSDATE)
          AND TRUNC(ADD_MONTHS(fe.proxaquifinfer, 12))
              BETWEEN TRUNC(SYSDATE) - 365 AND TRUNC(SYSDATE) + 180""",
             {**pf, "dm": DIAS_MES, "dp": DIAS_PERIODO})[0]
    exp_v = float(exp["base"] or 0) * UM_TERCO * (1 + FGTS)

    # ── o FATOR: o quanto a estimativa sobre salário base subestima ────────
    #
    # Medido, não suposto. De um lado o que a folha PAGOU de férias gozadas; do
    # outro, o que o salário base das MESMAS pessoas daria pelos MESMOS dias.
    # Sem este número o passivo sairia com cara de valor exato, quando ele
    # ignora as médias de hora extra e adicional noturno que a folha paga por
    # cima — e ignorá-las erra sempre para o mesmo lado, o de menos.
    fat = _q("""
        SELECT SUM(fr.diasgozofer * vf.salbase) base_dia, SUM(fr.diasgozofer) dias
        FROM flp_ferias fr
        JOIN vw_funcionarios vf ON vf.codintfunc = fr.codintfunc
        WHERE vf.codigoempresa = :emp AND fr.dtexclferias IS NULL
          AND fr.gozoinifer >= TRUNC(TO_DATE(:de,'YYYY-MM-DD'),'MM')
          AND fr.gozoinifer < TRUNC(SYSDATE,'MM')""",
             {"emp": EMPRESA, "de": de})[0]
    dias_gozo = float(fat["dias"] or 0)
    # O realizado comparável é SÓ o das férias efetivamente gozadas: rescisão,
    # proporcional e abono não têm dia de gozo e inflariam o numerador contra
    # um denominador que não os contém.
    real_gozo = por_nat.get("Gozadas (normais)", {}).get("valor", 0.0)
    est_gozo = float(fat["base_dia"] or 0) / DIAS_MES * UM_TERCO
    fator = round(real_gozo / est_gozo, 2) if est_gozo else None

    # ── FÉRIAS AGENDADAS: o custo que ainda não entrou na folha ────────────
    #
    # A pergunta que nem o realizado nem a provisão respondem: quanto vai sair
    # de caixa nos próximos meses por causa do que JÁ está marcado. O realizado
    # é passado e a provisão é o passivo inteiro (inclusive de quem não tem
    # data nenhuma); esta é a fatia com data, que é a única que dá para pôr num
    # fluxo de caixa.
    #
    # DIAS = fim − início + 1. O `+ 1` não é detalhe: sem ele, férias de 30 dias
    # viram 29, e o erro é de 3,3% em TODA linha — pequeno o bastante para
    # nunca chamar atenção e grande o bastante para o número nunca fechar com
    # a folha.
    #
    # `gozofinfer >= SYSDATE` inclui quem JÁ ESTÁ de férias hoje: o dinheiro
    # dessas ainda não saiu inteiro, e excluí-las por já terem começado deixaria
    # sete pessoas fora da conta do mês corrente.
    ag_where = (f"""
        FROM vw_ferias fe
        JOIN vw_funcionarios vf ON vf.codintfunc = fe.codintfunc
        WHERE vf.situacaofunc = 'A' AND vf.codigoempresa = :emp {filtro_fil}
          AND fe.gozofinfer >= TRUNC(SYSDATE) AND fe.gozoinifer IS NOT NULL
          AND fe.gozoinifer <= TO_DATE(:fate,'YYYY-MM-DD')""")
    ag_dias = "(fe.gozofinfer - fe.gozoinifer + 1)"
    # O ABONO PECUNIÁRIO TAMBÉM ESTÁ AGENDADO, E TAMBÉM SE PAGA.
    #
    # `abpecinifer`/`abpecfinfer` são os dias VENDIDOS (art. 143: até um terço
    # do período convertido em dinheiro). Contar só o gozo subestimava o custo
    # em 13,7% — R$ 7.734 sobre R$ 56.615, em 5 das 20 pessoas. O erro é do pior
    # tipo: some dentro de um total plausível, e só aparece quando alguém
    # pergunta "de quem é esse dinheiro?".
    #
    # A distinção importa para quem lê: o gozo é ausência (a pessoa não está no
    # posto) e o abono é só desembolso (ela trabalha e recebe a mais). Por isso
    # os dois voltam separados, e a coluna de DIAS da escala continua sendo só
    # a do gozo.
    ag_abono = ("(CASE WHEN fe.abpecinifer IS NOT NULL"
                " THEN fe.abpecfinfer - fe.abpecinifer + 1 ELSE 0 END)")
    ag_tot = _q(f"""SELECT COUNT(*) n, SUM({ag_dias}) dias, SUM({ag_abono}) dias_abono,
                    SUM(vf.salbase / :dm * {ag_dias}) base,
                    SUM(vf.salbase / :dm * {ag_abono}) base_abono,
                    SUM(CASE WHEN fe.abpecinifer IS NOT NULL THEN 1 ELSE 0 END) com_abono
                    {ag_where}""", {**pf, "dm": DIAS_MES})[0]
    ag_mes = [{"mes": r["m"], "n": int(r["n"] or 0), "dias": int(r["dias"] or 0),
               "dias_abono": int(r["dias_abono"] or 0),
               "custo": _f((float(r["base"] or 0) + float(r["base_abono"] or 0))
                           * UM_TERCO * (1 + FGTS))}
              for r in _q(f"""
        SELECT TO_CHAR(fe.gozoinifer,'YYYY-MM') m, COUNT(*) n,
               SUM({ag_dias}) dias, SUM({ag_abono}) dias_abono,
               SUM(vf.salbase / :dm * {ag_dias}) base,
               SUM(vf.salbase / :dm * {ag_abono}) base_abono
        {ag_where}
        GROUP BY TO_CHAR(fe.gozoinifer,'YYYY-MM')
        ORDER BY 1""", {**pf, "dm": DIAS_MES})]

    # ── QUEM, e não só quanto ──────────────────────────────────────────────
    #
    # ATENÇÃO, E ESTÁ DITO NA TELA: o custo POR PESSOA permite deduzir o
    # salário base (custo ÷ dias × 30 ÷ 1,4333). É a primeira vez que este
    # módulo entrega algo assim — todo o resto é agregado por unidade ou por
    # natureza. Entra porque uma escala de férias se aprova por pessoa, e uma
    # linha sem valor não deixa ninguém decidir nada; e porque a tela `ferias`
    # já é restrita pelo RBAC a quem cuida de folha. O que continua fora, aqui
    # também: CPF, dado bancário e o salário em si como coluna.
    #
    # Cargo, área e unidade estão preenchidos em 20 de 20 — não há o cuidado
    # de "campo vazio" a tomar, e isso foi conferido antes de a coluna existir.
    ag_det = [{
        "nome": r["nome"], "chapa": (r["chapa"] or "").strip(),
        "cargo": (r["cargo"] or "").strip() or None,
        "area": (r["area"] or "").strip() or None,
        "filial": r["filial"], "ini": r["ini"], "fim": r["fim"],
        "dias": int(r["dias"] or 0), "dias_abono": int(r["dias_abono"] or 0),
        "ab_ini": r["ab_ini"], "ab_fim": r["ab_fim"],
        "agora": bool(r["agora"]),
        "custo": _f((float(r["base"] or 0) + float(r["base_abono"] or 0))
                    * UM_TERCO * (1 + FGTS)),
    } for r in _q(f"""
        SELECT vf.nomefunc nome, vf.chapafunc chapa,
               vf.descfuncaocompleta cargo, vf.descarea area, vf.descsecao filial,
               TO_CHAR(fe.gozoinifer,'YYYY-MM-DD') ini,
               TO_CHAR(fe.gozofinfer,'YYYY-MM-DD') fim,
               {ag_dias} dias, {ag_abono} dias_abono,
               TO_CHAR(fe.abpecinifer,'YYYY-MM-DD') ab_ini,
               TO_CHAR(fe.abpecfinfer,'YYYY-MM-DD') ab_fim,
               CASE WHEN TRUNC(SYSDATE) BETWEEN fe.gozoinifer AND fe.gozofinfer
                    THEN 1 ELSE 0 END agora,
               vf.salbase / :dm * {ag_dias} base,
               vf.salbase / :dm * {ag_abono} base_abono
        {ag_where}
        ORDER BY fe.gozoinifer, vf.nomefunc""", {**pf, "dm": DIAS_MES})]

    ag_base_gozo = float(ag_tot["base"] or 0)
    ag_base_abono = float(ag_tot["base_abono"] or 0)
    ag_custo = (ag_base_gozo + ag_base_abono) * UM_TERCO * (1 + FGTS)

    return {
        "periodo": {"de": de, "ate": ate},
        "meses": n_meses,
        "filtros": {"filial": filial, "chapa": chapa,
                    "dt_de": de, "dt_ate": ate},
        "agendadas": {
            "n": int(ag_tot["n"] or 0),
            "dias": int(ag_tot["dias"] or 0),
            "dias_abono": int(ag_tot["dias_abono"] or 0),
            "com_abono": int(ag_tot["com_abono"] or 0),
            "custo": _f(ag_custo),
            "custo_gozo": _f(ag_base_gozo * UM_TERCO * (1 + FGTS)),
            "custo_abono": _f(ag_base_abono * UM_TERCO * (1 + FGTS)),
            "por_mes": ag_mes,
            "detalhe": ag_det,
        },
        "kpis": {
            "realizado": _f(total),
            "dobra_paga": _f(dobra_d.get("valor", 0.0)),
            "dobra_lanc": int(dobra_d.get("n", 0)),
            "medio_mes": _f(total / n_meses),
            "agendado": _f(ag_custo),
            "agendado_n": int(ag_tot["n"] or 0),
            "agendado_dias": int(ag_tot["dias"] or 0),
            "provisao": _f(pr_venc + pr_avos + pr_fgts),
            "prov_vencido": _f(pr_venc),
            "prov_avos": _f(pr_avos),
            "prov_fgts": _f(pr_fgts),
            "exposicao": _f(exp_v),
            "exposicao_n": int(exp["n"] or 0),
            "dias_gozados": int(dias_gozo),
            "fator": fator,
            "fgts_pct": FGTS * 100,
        },
        "naturezas": naturezas,
        "eventos": eventos[:20],
        "eventos_total": len(eventos),
        "serie": serie,
        "provisao_filial": prov_l,
        "cinza": {"nome": CINZA_NOME, "valor": _f(cinza["tot"]),
                  "n": c_n, "com_ferias": c_ok,
                  "pct": round(c_ok / c_n * 100, 1) if c_n else 0.0},
        "fonte": "ERP GLOBUS · flp_fichaeventos (realizado) × vw_ferias "
                 "(provisão, estimada sobre salário base)",
        "atualizado_em": _q("SELECT TO_CHAR(SYSDATE,'YYYY-MM-DD HH24:MI') agora "
                            "FROM dual")[0]["agora"],
    }
