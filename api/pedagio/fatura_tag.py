# -*- coding: utf-8 -*-
"""Grava a fatura da administradora de tag e confronta a tarifa com o ERP.

A LEITURA DO PDF ESTÁ EM `semparar.py`; AQUI SÓ ENTRA O QUE JÁ CONFERIU
======================================================================
`importar()` recusa a fatura cujo detalhe não fecha com o resumo impresso nela
mesma. Uma fatura de meio milhão importada pela metade produz número plausível
e errado, e é isso que a recusa impede — não é preciosismo de validação.

A TARIFA CORRENTE VEM DA MODA, NUNCA DA MÉDIA
=============================================
A mesma praça e a mesma categoria aparecem com valores diferentes ao longo do
mês, e a média entre a tarifa velha e a nova é um valor que nunca foi cobrado
de ninguém. Pior: uma única travessia com valor atípico (categoria errada, eixo
suspenso, o próprio dia do reajuste) desloca a média e nada denuncia.

A moda resolve os dois, e dá de brinde a tarifa ANTERIOR — o segundo valor mais
frequente — e a data em que a troca aconteceu. Abaixo de `PCT_MODA_MINIMO` não
há tarifa a afirmar, e a resposta é `n/d` com o percentual à mostra: ali a praça
cobra por eixo NO CHÃO enquanto a categoria declara o veículo inteiro.

É a mesma régua que `pracas.observada()` já aplica ao extrato da administradora
de vale, e de propósito: dois módulos que respondem "qual é a tarifa desta
praça" com critérios diferentes viram reunião sobre qual está certo.

O CASAMENTO COM O CADASTRO É POR RODOVIA + KM, E O KM É AO METRO
================================================================
Não é por nome: a fatura escreve "S. JOSÉ PINHAIS" e o ERP escreve "São José
dos Pinhais P01 (Sul - Norte)"; escreve "S.B. DO CAMPO" onde o cadastro diz
"Piratininga". Casar por texto perderia quase tudo e, pior, casaria errado.

Rodovia + km bate ao metro: SP160 km 32,381 é uma praça só no Brasil. Medido na
fatura de ago/2026 — 110 praças casam com km IDÊNTICO (7.728 travessias, 45% do
volume) e outras 87 casam com até 1 km de diferença. O confronto é publicado
com o desvio de km ao lado, porque casamento a 900 metros é hipótese e
casamento ao metro é fato, e quem lê precisa saber qual está vendo.

O QUE A COMPARAÇÃO MEDIU, E POR QUE ELA NÃO ACUSA NINGUÉM
=========================================================
Sete faturas (fev a ago/2026, R$ 3,34 mi de pedágio de tag), só nas praças de
casamento firme — rodovia + km ao metro:

    competência   praças   confere   erro da tabela do ERP
    2026-02          90      7           -3,8%
    2026-03          88      7           -3,8%
    2026-04          89      7           -4,5%
    2026-05          84      7           -4,0%
    2026-06          84      7           -4,2%
    2026-07          81      7           -3,9%
    2026-08          81      2           -6,0%

A SÉRIE É O ACHADO, não o número de um mês. O erro fica estável entre -3,8% e
-4,5% por seis meses e SALTA para -6,0% em agosto, com as praças que conferiam
caindo de 7 para 2. Não é ruído: é o reajuste de 01/07/2026 chegando à fatura
de agosto sem chegar ao cadastro.

E O REAJUSTE ESTÁ DATADO NO PRÓPRIO DADO, sem fonte externa. Comparando, para
cada praça, o último dia da tarifa velha com o primeiro da nova: 92 praças
trocaram de tarifa nos sete meses, **52 delas em 01/07/2026** (mais 8 no dia 2
e 4 no dia 4 — só porque não houve travessia nelas no dia 1º), e uma onda menor
de 13 em março. A mediana do reajuste é **+5,26%** (p25 4,76%, p75 5,84%).

É a demonstração de que a tarifa observada FUNCIONA como fonte: ela enxerga o
reajuste no dia em que ele acontece, enquanto `pracapedagio_valor` tem sua
vigência mais recente em 01/08/2025.

MAS 11 PRAÇAS VÃO PARA O OUTRO LADO, E ISSO NÃO É TABELA ERRADA. Cinco são CCR
Viaoeste, com o real em 0,79 e 0,68 da tabela; duas Renovias em 0,53; duas Rota
das Bandeiras em 0,87. Razão constante DENTRO da concessionária não parece
cadastro velho, parece desconto contratual de tag. Por isso a tela agrupa o
desvio por concessionária: é o recorte que separa "nosso cadastro envelheceu"
de "há um desconto que ninguém lançou", que são consertos de donos diferentes.

O veredito não é do painel. A evidência vai ao lado do número, como no plano de
manutenção com marcador furado.
"""
from __future__ import annotations

import collections
import logging

from api import pglocal
from api.pedagio import semparar

log = logging.getLogger(__name__)

# O teste redireciona para um schema próprio (fixture `esquema_pg`), que é o
# padrão da casa para módulo que escreve no banco local.
ESQUEMA: str | None = None

# Uma travessia só não estabelece tarifa: pode ser categoria errada, eixo
# suspenso ou o próprio dia do reajuste. Cinco é o piso para a moda valer — o
# mesmo de `pracas.MINIMO_OBSERVACOES`, e igual de propósito.
MINIMO_OBSERVACOES = 5

# E ter cinco não basta: se o valor mais frequente responde por menos da
# metade, não há tarifa a afirmar.
PCT_MODA_MINIMO = 50.0

# Casamento com o cadastro do ERP. Ao metro é fato; até 1 km é hipótese, e sai
# rotulada como tal. Acima disso não se casa: a praça seguinte pode estar ali.
KM_EXATO = 0.005
KM_MAXIMO = 1.0


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def _janela(de: str | None, ate: str | None):
    """O recorte é pela DATA DA TRAVESSIA, não pela competência da fatura.

    A diferença importa: a fatura de agosto cobre passagens de 03/07 a 02/08,
    então filtrar por competência devolve travessias de julho quando se pediu
    agosto. Quem olha a tela está recortando o instante em que o veículo passou
    na praça, e é isso que o filtro tem de recortar.

    O `ate` é INCLUSIVO — quem digita 31/08 espera o dia 31 inteiro, e um
    `<=` contra um timestamp corta às 00:00:00 e perde o dia.
    """
    cond, params = [], {}
    if de:
        cond.append("AND t.ts >= %(de)s::date")
        params["de"] = de
    if ate:
        cond.append("AND t.ts < (%(ate)s::date + 1)")
        params["ate"] = ate
    return " ".join(cond), params


# ── gravação ────────────────────────────────────────────────────────────────

_INSERT_TRAV = """
INSERT INTO ped_travessias
    (fatura_id, tipo, placa, ts, concessionaria, embarcador, praca,
     rodovia, km, sentido, cidade, categoria, eixos, viagem, valor, dc)
VALUES (%(fatura_id)s, %(tipo)s, %(placa)s, %(ts)s, %(concessionaria)s,
        %(embarcador)s, %(praca)s, %(rodovia)s, %(km)s, %(sentido)s,
        %(cidade)s, %(categoria)s, %(eixos)s, %(viagem)s, %(valor)s, %(dc)s)
"""

_INSERT_CRED = """
INSERT INTO ped_creditos (fatura_id, data, hora, placa, tag, descricao, valor, dc)
VALUES (%(fatura_id)s, %(data)s, %(hora)s, %(placa)s, %(tag)s, %(descricao)s,
        %(valor)s, %(dc)s)
"""

_UPSERT_FATURA = """
INSERT INTO ped_faturas
    (administradora, numero_fatura, numero_nf, cnpj_emissor, codigo_cliente,
     competencia, dt_emissao, dt_fechamento, dt_vencimento, total_fatura,
     total_passagens, total_vale, total_plano, total_estacion, total_creditos,
     qtd_declarada, paginas, arquivo_nome, arquivo_sha256, importado_por)
VALUES (%(administradora)s, %(numero_fatura)s, %(numero_nf)s, %(cnpj_emissor)s,
        %(codigo_cliente)s, %(competencia)s, %(dt_emissao)s, %(dt_fechamento)s,
        %(dt_vencimento)s, %(total_fatura)s, %(total_passagens)s,
        %(total_vale)s, %(total_plano)s, %(total_estacion)s,
        %(total_creditos)s, %(qtd_declarada)s, %(paginas)s, %(arquivo_nome)s,
        %(arquivo_sha256)s, %(importado_por)s)
ON CONFLICT (administradora, numero_fatura) DO UPDATE SET
    numero_nf = EXCLUDED.numero_nf, cnpj_emissor = EXCLUDED.cnpj_emissor,
    codigo_cliente = EXCLUDED.codigo_cliente, competencia = EXCLUDED.competencia,
    dt_emissao = EXCLUDED.dt_emissao, dt_fechamento = EXCLUDED.dt_fechamento,
    dt_vencimento = EXCLUDED.dt_vencimento, total_fatura = EXCLUDED.total_fatura,
    total_passagens = EXCLUDED.total_passagens, total_vale = EXCLUDED.total_vale,
    total_plano = EXCLUDED.total_plano, total_estacion = EXCLUDED.total_estacion,
    total_creditos = EXCLUDED.total_creditos, qtd_declarada = EXCLUDED.qtd_declarada,
    paginas = EXCLUDED.paginas, arquivo_nome = EXCLUDED.arquivo_nome,
    arquivo_sha256 = EXCLUDED.arquivo_sha256, importado_em = now(),
    importado_por = EXCLUDED.importado_por
RETURNING id
"""


class ImportacaoRecusada(Exception):
    """A fatura não fecha consigo mesma. Traz o que não bateu."""

    def __init__(self, mensagem: str, conferencia: dict):
        super().__init__(mensagem)
        self.conferencia = conferencia


def importar(nome: str, bruto: bytes, usuario: str | None = None,
             esquema: str | None = None) -> dict:
    """Lê, confere e grava. Reimportar a MESMA fatura substitui, nunca duplica.

    A unidade de idempotência é a FATURA, não a travessia — ver o cabeçalho da
    migration 0030 para por que não há chave natural de linha aqui.
    """
    lido = semparar.ler(nome, bruto)
    conf = semparar.conferir(lido)
    if not conf["ok"]:
        raise ImportacaoRecusada(
            "A fatura não fecha com o resumo impresso nela mesma, então não foi "
            "gravada: " + "; ".join(conf["achados"]), conf)

    cab = lido["cabecalho"]
    tot = lido["totais_impressos"]
    dados = {**cab,
             "total_fatura": tot.get("FATURA"),
             "total_passagens": tot.get("PEDÁGIO"),
             "total_vale": tot.get("VALE PEDÁGIO"),
             "total_plano": tot.get("PLANO CONTRATADO"),
             "total_estacion": tot.get("ESTACIONAMENTO"),
             "total_creditos": tot.get("CRÉDITOS"),
             "qtd_declarada": sum(r["qtd_passagens"] for r in lido["resumo"]),
             "importado_por": usuario}
    dados.pop("paginas_", None)

    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_FATURA, dados)
            fatura_id = cur.fetchone()["id"]
            # Tudo na MESMA transação: apagar e não conseguir regravar deixaria
            # a fatura existindo com zero travessia, que se lê como "mês sem
            # pedágio" — pior que não ter importado.
            cur.execute("DELETE FROM ped_travessias WHERE fatura_id = %s", (fatura_id,))
            cur.execute("DELETE FROM ped_creditos WHERE fatura_id = %s", (fatura_id,))
            cur.executemany(_INSERT_TRAV,
                            [{**t, "fatura_id": fatura_id} for t in lido["travessias"]])
            cur.executemany(_INSERT_CRED,
                            [{**c, "fatura_id": fatura_id} for c in lido["creditos"]])
    return {"fatura_id": fatura_id, "numero_fatura": cab["numero_fatura"],
            "competencia": cab["competencia"], "placas": conf["placas"],
            "travessias": len(lido["travessias"]), "creditos": len(lido["creditos"]),
            "conferencia": conf}


def faturas(esquema: str | None = None) -> list[dict]:
    """As faturas importadas, da mais recente para a mais antiga."""
    return [dict(r) for r in pglocal.query("""
        SELECT f.id, f.administradora, f.numero_fatura, f.numero_nf, f.competencia,
               f.dt_fechamento, f.dt_vencimento,
               f.total_fatura::float8   AS total_fatura,
               f.total_passagens::float8 AS total_passagens,
               f.total_vale::float8      AS total_vale,
               f.total_creditos::float8  AS total_creditos,
               f.importado_em, f.importado_por, f.arquivo_nome,
               (SELECT count(*) FROM ped_travessias t
                 WHERE t.fatura_id = f.id AND t.tipo = 'tag')::int  AS travessias_tag,
               (SELECT count(*) FROM ped_travessias t
                 WHERE t.fatura_id = f.id AND t.tipo = 'vale')::int AS travessias_vale,
               (SELECT count(DISTINCT t.placa) FROM ped_travessias t
                 WHERE t.fatura_id = f.id)::int                     AS placas
          FROM ped_faturas f
         ORDER BY f.dt_fechamento DESC NULLS LAST, f.id DESC""",
        esquema=_esq(esquema))]


# ── a tarifa que está sendo cobrada ─────────────────────────────────────────

_TARIFA_SQL = """
SELECT t.rodovia, t.km::float8 AS km, t.sentido, t.cidade,
       max(t.praca)          AS praca,
       max(t.concessionaria) AS concessionaria,
       t.eixos,
       (t.valor / t.eixos)::float8 AS tarifa_eixo,
       count(*)::int         AS n,
       sum(t.valor)::float8  AS valor,
       min(t.ts)             AS visto_de,
       max(t.ts)             AS visto_ate
  FROM ped_travessias t
  JOIN ped_faturas f ON f.id = t.fatura_id
 WHERE t.tipo = 'tag' AND t.dc = 'D'
   AND t.eixos IS NOT NULL AND t.eixos > 0
   AND t.rodovia IS NOT NULL
   {FILTRO}
 GROUP BY t.rodovia, t.km, t.sentido, t.cidade, t.eixos, (t.valor / t.eixos)
"""


def tarifa_observada(de: str | None = None, ate: str | None = None,
                     esquema: str | None = None) -> list[dict]:
    """A tarifa por eixo de cada praça, pela MODA do que foi cobrado.

    Agrupa por praça (rodovia + km + sentido) e não por praça + eixos: a tarifa
    por eixo é a mesma para todas as categorias da mesma praça — é isso que a
    leitura de "61 são 7 eixos" prova —, então juntar as categorias dá mais
    observações para a moda em vez de espalhá-las em baldes pequenos.
    """
    filtro, params = _janela(de, ate)
    linhas = pglocal.query(_TARIFA_SQL.replace("{FILTRO}", filtro), params or None,
                           esquema=_esq(esquema))

    por_praca: dict[tuple, dict] = {}
    for r in linhas:
        chave = (r["rodovia"], round(float(r["km"]), 3), r["sentido"])
        a = por_praca.setdefault(chave, {
            "rodovia": r["rodovia"], "km": round(float(r["km"]), 3),
            "sentido": r["sentido"], "cidade": r["cidade"], "praca": r["praca"],
            "concessionaria": r["concessionaria"], "n": 0, "valor": 0.0,
            "contagem": collections.Counter(), "eixos": set(),
            "visto_de": r["visto_de"], "visto_ate": r["visto_ate"]})
        a["n"] += r["n"]
        a["valor"] += float(r["valor"])
        a["contagem"][round(float(r["tarifa_eixo"]), 2)] += r["n"]
        a["eixos"].add(r["eixos"])
        a["visto_de"] = min(a["visto_de"], r["visto_de"])
        a["visto_ate"] = max(a["visto_ate"], r["visto_ate"])

    saida = []
    for a in por_praca.values():
        comuns = a["contagem"].most_common()
        moda, nmoda = comuns[0]
        pct = round(100.0 * nmoda / a["n"], 1)
        # Abaixo do piso não se afirma tarifa: o percentual vai à tela no lugar
        # do número, que é o que permite a quem lê julgar por conta própria.
        firme = a["n"] >= MINIMO_OBSERVACOES and pct >= PCT_MODA_MINIMO
        saida.append({
            "rodovia": a["rodovia"], "km": a["km"], "sentido": a["sentido"],
            "cidade": a["cidade"], "praca": a["praca"],
            "concessionaria": a["concessionaria"],
            "tarifa_eixo": moda if firme else None,
            "pct_moda": pct, "firme": firme,
            "tarifa_anterior": comuns[1][0] if len(comuns) > 1 else None,
            "valores_distintos": len(comuns),
            "n": a["n"], "valor": round(a["valor"], 2),
            "eixos": sorted(a["eixos"]),
            "visto_de": a["visto_de"], "visto_ate": a["visto_ate"]})
    saida.sort(key=lambda x: -x["valor"])
    return saida


# ── confronto com o cadastro de praças do ERP ───────────────────────────────

# A tarifa VIGENTE por praça, uma linha por praça. `DISTINCT ON` e não dois
# `max()`: pegar max(dtvigencia) e max(valorpedagioeixo) no mesmo GROUP BY
# devolve a data de uma linha com o preço de outra, e já devolveu em 28 praças
# desta base. O `NULLS LAST` também não é enfeite — em DESC o Postgres põe NULL
# primeiro, e a praça com uma linha sem data ganharia a tarifa sem vigência.
_ERP_PRACAS_SQL = """
SELECT p.id, p.descricao, p.nomeconcessionaria, p.uf, p.cidade,
       p.descricaorodovia, p.kmlocalizacao::float8 AS km, p.ativoinativo,
       v.dtvigencia::date          AS vigencia,
       v.valorpedagioeixo::float8  AS tarifa_eixo
  FROM pracapedagio p
  LEFT JOIN (SELECT DISTINCT ON (idpracapedagio)
                    idpracapedagio, dtvigencia, valorpedagioeixo
               FROM pracapedagio_valor
              ORDER BY idpracapedagio, dtvigencia DESC NULLS LAST) v
    ON v.idpracapedagio = p.id
 WHERE p.kmlocalizacao IS NOT NULL
"""

_RE_ROD = __import__("re").compile(r"^([A-Z]{2}\d{3})")


def _rodovia_erp(txt: str | None) -> str | None:
    t = (txt or "").upper().replace(" ", "")
    m = _RE_ROD.match(t)
    return m.group(1) if m else None


def confronto_erp(de: str | None = None, ate: str | None = None,
                  esquema: str | None = None) -> dict:
    """A tarifa observada contra a cadastrada em `pracapedagio_valor`.

    Casa por rodovia + km. O desvio de km vai em cada linha e a leitura é
    separada em duas: `exato` (ao metro, e é fato) e `aproximado` (até 1 km, e
    é hipótese). Publicar as duas juntas num número só faria um casamento a 900
    metros pesar igual a um casamento exato.
    """
    from api import db

    obs = [x for x in tarifa_observada(de, ate, esquema) if x["firme"]]
    try:
        cadastro = db.query(_ERP_PRACAS_SQL)
    except Exception as exc:  # noqa: BLE001
        # Sem o ERP a tarifa observada continua valendo — ela é nossa. O que
        # não dá é para dizer se o cadastro está certo, e a tela DIZ isso em
        # vez de mostrar uma tabela de desvios vazia, que se leria como "está
        # tudo em dia".
        log.warning("confronto de praça sem o AVA: %s", exc)
        return {"erro": "sem_erp", "pracas_observadas": len(obs), "linhas": []}

    indice: dict[tuple[str, int], list[dict]] = {}
    for p in cadastro:
        rod = _rodovia_erp(p["descricaorodovia"])
        if rod:
            indice.setdefault((rod, round(float(p["km"]))), []).append(p)

    linhas, sem_par = [], []
    for o in obs:
        cands = []
        for dk in (0, 1, -1):
            cands += indice.get((o["rodovia"], round(o["km"]) + dk), [])
        cands = [c for c in cands if abs(float(c["km"]) - o["km"]) <= KM_MAXIMO]
        if not cands:
            sem_par.append(o)
            continue
        # Prefere quem TEM tarifa e está mais perto: casar com a praça sem
        # tarifa cadastrada devolveria "sem cadastro" tendo o cadastro ao lado.
        melhor = sorted(cands, key=lambda c: (c["tarifa_eixo"] is None,
                                              abs(float(c["km"]) - o["km"])))[0]
        dkm = round(abs(float(melhor["km"]) - o["km"]), 3)
        erp = melhor["tarifa_eixo"]
        dif = None if erp is None else round(o["tarifa_eixo"] - float(erp), 2)
        linhas.append({
            **{k: o[k] for k in ("praca", "rodovia", "km", "sentido", "cidade",
                                 "concessionaria", "tarifa_eixo", "n", "valor")},
            "erp_id": melhor["id"], "erp_descricao": melhor["descricao"],
            "erp_concessionaria": melhor["nomeconcessionaria"],
            "erp_uf": melhor["uf"], "erp_cidade": melhor["cidade"],
            "erp_tarifa_eixo": None if erp is None else round(float(erp), 2),
            "vigencia": melhor["vigencia"], "dkm": dkm, "exato": dkm <= KM_EXATO,
            "diferenca": dif,
            "razao": None if not erp else round(o["tarifa_eixo"] / float(erp), 3),
            # Quanto o mês teria sido se a tabela do ERP fosse usada para
            # calcular. É o número que diz o TAMANHO do erro em reais, e não só
            # que a tarifa está velha.
            "valor_pela_tabela": None if not erp else round(
                o["valor"] * float(erp) / o["tarifa_eixo"], 2)})

    firmes = [x for x in linhas if x["exato"] and x["erp_tarifa_eixo"]]
    real = round(sum(x["valor"] for x in firmes), 2)
    tabela = round(sum(x["valor_pela_tabela"] for x in firmes), 2)
    confere = [x for x in firmes if abs(x["diferenca"]) <= 0.005]

    # Agrupado por concessionária, que é o recorte que separa cadastro velho de
    # desconto contratual: razão constante dentro de uma concessionária não é
    # tabela desatualizada.
    porconc: dict[str, dict] = {}
    for x in firmes:
        c = x["erp_concessionaria"] or x["concessionaria"] or "—"
        a = porconc.setdefault(c, {"concessionaria": c, "pracas": 0, "n": 0,
                                   "valor": 0.0, "tabela": 0.0, "razoes": []})
        a["pracas"] += 1
        a["n"] += x["n"]
        a["valor"] += x["valor"]
        a["tabela"] += x["valor_pela_tabela"]
        if x["razao"]:
            a["razoes"].append(x["razao"])
    grupos = []
    for a in porconc.values():
        rz = sorted(a["razoes"])
        grupos.append({"concessionaria": a["concessionaria"], "pracas": a["pracas"],
                       "n": a["n"], "valor": round(a["valor"], 2),
                       "valor_pela_tabela": round(a["tabela"], 2),
                       "diferenca": round(a["tabela"] - a["valor"], 2),
                       "razao_mediana": rz[len(rz) // 2] if rz else None})
    grupos.sort(key=lambda g: -abs(g["diferenca"]))

    linhas.sort(key=lambda x: -abs((x["diferenca"] or 0) * x["n"]))
    return {
        "linhas": linhas, "grupos": grupos,
        "pracas_observadas": len(obs),
        "pracas_casadas": len(linhas),
        "pracas_exatas": len(firmes),
        "pracas_sem_par": len(sem_par),
        "confere": len(confere),
        "valor_real": real,
        "valor_pela_tabela": tabela,
        "diferenca": round(tabela - real, 2),
        "erro_pct": round(100.0 * (tabela - real) / real, 2) if real else None,
    }


# ── o resumo que a tela lê ──────────────────────────────────────────────────

_POR_PLACA_SQL = """
SELECT t.placa,
       sum(CASE WHEN t.tipo = 'tag'  AND t.dc = 'D' THEN t.valor ELSE 0 END)::float8 AS tag,
       sum(CASE WHEN t.tipo = 'vale' AND t.dc = 'D' THEN t.valor ELSE 0 END)::float8 AS vale_debito,
       sum(CASE WHEN t.tipo = 'vale' AND t.dc = 'C' THEN t.valor ELSE 0 END)::float8 AS vale_credito,
       count(CASE WHEN t.tipo = 'tag' AND t.dc = 'D' THEN 1 END)::int  AS n_tag,
       count(CASE WHEN t.tipo = 'vale' AND t.dc = 'D' THEN 1 END)::int AS n_vale
  FROM ped_travessias t
  JOIN ped_faturas f ON f.id = t.fatura_id
 WHERE 1 = 1 {FILTRO}
 GROUP BY t.placa
"""

# A MODALIDADE VEM DE `utilizacaoveiculo`, E NÃO DE `tipofrota`, e a diferença
# não é cosmética: `tipofrota` só tem três valores (própria, terceiro,
# agregado) e dobra a LOCAÇÃO — 215 veículos — dentro de um deles. A tela ficava
# dizendo "Frota própria" para carro alugado.
#
# E o rótulo é o MESMO de `frota_identidade.modalidade()`, usado pelo resto da
# tela de pedágio. Dois mapas para o mesmo conceito é a armadilha dos dois
# armazéns do parâmetro da premiação: enquanto ninguém edita, eles concordam.


def resumo(de: str | None = None, ate: str | None = None,
           esquema: str | None = None) -> dict:
    """KPIs da fatura mais recente (ou da competência pedida).

    A QUEBRA POR MODALIDADE É O NÚMERO QUE MUDA A LEITURA. A casa registrava
    "a frota própria passa por tag", e é verdade — mas 78,5% do que o tag paga
    é de veículo AGREGADO. Sem a quebra, esse gasto se lê como custo de frota
    própria e vai para a conta errada.

    A placa sem cadastro no ERP vira "não cadastrada" e é CONTADA, nunca somada
    em silêncio a um dos baldes: nesta fatura são zero de 192, e o dia em que
    deixar de ser zero é exatamente o dia em que alguém precisa saber.
    """
    from api import db
    from api import frota_identidade

    filtro, params = _janela(de, ate)
    linhas = pglocal.query(_POR_PLACA_SQL.replace("{FILTRO}", filtro),
                           params or None, esquema=_esq(esquema))
    if not linhas:
        return {"vazio": True, "de": de, "ate": ate}

    placas = [r["placa"] for r in linhas]
    cadastro: dict[str, dict] = {}
    try:
        for v in db.query("SELECT placa, utilizacaoveiculo, numerofrota, tipoveiculo "
                          "FROM veiculo WHERE placa = ANY(%(p)s)", {"p": placas}):
            cadastro[v["placa"]] = v
    except Exception as exc:  # noqa: BLE001
        log.warning("resumo do tag sem o cadastro de veículo: %s", exc)

    baldes: dict[str, dict] = {}
    for r in linhas:
        v = cadastro.get(r["placa"])
        rot = (frota_identidade.modalidade(v["utilizacaoveiculo"]) if v
               else "Não cadastrada")
        a = baldes.setdefault(rot, {"modalidade": rot, "placas": 0, "tag": 0.0,
                                    "n_tag": 0, "vale_debito": 0.0})
        a["placas"] += 1
        a["tag"] += r["tag"]
        a["n_tag"] += r["n_tag"]
        a["vale_debito"] += r["vale_debito"]

    total_tag = round(sum(r["tag"] for r in linhas), 2)
    modalidades = sorted(baldes.values(), key=lambda x: -x["tag"])
    for m in modalidades:
        m["tag"] = round(m["tag"], 2)
        m["vale_debito"] = round(m["vale_debito"], 2)
        m["pct"] = round(100.0 * m["tag"] / total_tag, 1) if total_tag else None

    veic = []
    for r in sorted(linhas, key=lambda x: -x["tag"])[:30]:
        v = cadastro.get(r["placa"]) or {}
        veic.append({
            "placa": r["placa"],
            "rotulo": frota_identidade.rotulo(v.get("numerofrota"), r["placa"]),
            "modalidade": frota_identidade.modalidade(v.get("utilizacaoveiculo")),
            "tag": round(r["tag"], 2), "n_tag": r["n_tag"],
            "vale_debito": round(r["vale_debito"], 2), "n_vale": r["n_vale"],
            "por_travessia": round(r["tag"] / r["n_tag"], 2) if r["n_tag"] else None})

    # O vale dentro da fatura: quanto o embarcador cobriu do que a praça cobrou.
    vd = round(sum(r["vale_debito"] for r in linhas), 2)
    vc = round(sum(r["vale_credito"] for r in linhas), 2)
    return {
        "vazio": False, "de": de, "ate": ate,
        "placas": len(linhas), "sem_cadastro": sum(1 for r in linhas
                                                   if r["placa"] not in cadastro),
        "total_tag": total_tag,
        "travessias_tag": sum(r["n_tag"] for r in linhas),
        "modalidades": modalidades,
        "veiculos": veic,
        "vale_debito": vd, "vale_credito": vc,
        "vale_liquido": round(vd - vc, 2),
        "travessias_vale": sum(r["n_vale"] for r in linhas),
    }
