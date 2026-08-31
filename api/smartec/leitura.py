"""Leitura da Smartec para a tela.

O QUE ESTA TELA RESPONDE, E POR QUE NÃO É "MAIS UMA DE MULTAS"
=============================================================
A tela de Multas que já existe lê `infracaotransito_registro` no ERP e responde
"o que foi autuado". Esta responde **"o que ainda dá para fazer"**, e são
perguntas diferentes:

  - 51 notificações AINDA NO PRAZO de indicar condutor — passado o prazo, vira
    autuação por não indicar (art. 257 §8º), que é 61 das 212 multas em aberto
    desta frota. É o único número aqui que expira.
  - R$ 5.818 de desconto disponível, que evapora no vencimento do boleto.
  - 8 cronotacógrafos VENCIDOS, que é veículo circulando irregular.
  - o acesso ao SNE expirando, que desliga tudo isso em silêncio.

AS DUAS ESPÉCIES NUNCA SE SOMAM
===============================
`multa` e `notificacao` são estágios do MESMO auto: a notificação vira multa
se ninguém indicar condutor nem recorrer. Somar as duas conta a mesma infração
duas vezes — o total sairia R$ 126 mil onde o exigível hoje é R$ 41,8 mil. Toda
consulta aqui filtra por espécie, e a tela mostra as duas lado a lado com
rótulo dizendo o que cada uma é.

"EM ABERTO" É `sumiu_em IS NULL`
================================
A API só devolve o que está em aberto; o que foi resolvido para de vir e a
coleta carimba `sumiu_em`. Consultar sem esse filtro devolve o acumulado
histórico, que é outra pergunta (e é legítima — `historico()` a responde).
"""
from __future__ import annotations

from .. import pglocal

ESQUEMA: str | None = None


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


ABERTO = "sumiu_em IS NULL"


def kpis(esquema: str | None = None) -> dict:
    """Os números do topo. Cada um com o denominador que o torna legível."""
    esq = _esq(esquema)

    inf = pglocal.query(f"""
        SELECT especie,
               count(*)::int                                    AS n,
               count(DISTINCT renavam)::int                     AS veiculos,
               coalesce(sum(valor_a_pagar), 0)::float8          AS valor,
               coalesce(sum(valor_com_desconto), 0)::float8     AS valor_desc,
               coalesce(sum(pontuacao), 0)::int                 AS pontos,
               sum(CASE WHEN valor_a_pagar > 0 THEN 1 ELSE 0 END)::int
                                                                AS com_valor,
               sum(CASE WHEN vencimento < current_date THEN 1 ELSE 0 END)::int
                                                                AS vencidas
          FROM smt_infracoes WHERE {ABERTO} GROUP BY especie
    """, esquema=esq)
    por_especie = {r["especie"]: dict(r) for r in inf}

    # O desconto só existe onde a Smartec informou os DOIS valores. Somar
    # `valor - valor_com_desconto` sobre a tabela inteira trataria o campo
    # ausente como desconto zero e diluiria o número; pior, na notificação o
    # campo nem vem, e o "desconto" sairia igual ao valor cheio.
    desc = pglocal.um(f"""
        SELECT coalesce(sum(valor_a_pagar - valor_com_desconto), 0)::float8
                   AS economia,
               count(*)::int AS n
          FROM smt_infracoes
         WHERE {ABERTO} AND especie = 'multa'
           AND valor_a_pagar IS NOT NULL AND valor_com_desconto IS NOT NULL
           AND valor_com_desconto < valor_a_pagar
    """, esquema=esq) or {}

    # O NÚMERO QUE EXPIRA. `prazo_indicacao >= hoje` é o que ainda dá para
    # tratar; o resto já passou e não volta.
    prazo = pglocal.um(f"""
        SELECT sum(CASE WHEN prazo_indicacao >= current_date
                        THEN 1 ELSE 0 END)::int                  AS no_prazo,
               sum(CASE WHEN prazo_indicacao >= current_date
                         AND prazo_indicacao <= current_date + 7
                        THEN 1 ELSE 0 END)::int                  AS ate_7d,
               coalesce(sum(CASE WHEN prazo_indicacao >= current_date
                        THEN valor_a_pagar ELSE 0 END), 0)::float8
                                                                 AS valor_no_prazo,
               sum(CASE WHEN prazo_indicacao IS NULL THEN 1 ELSE 0 END)::int
                                                                 AS sem_prazo,
               count(*)::int                                     AS total
          FROM smt_infracoes
         WHERE {ABERTO} AND especie = 'notificacao'
    """, esquema=esq) or {}

    # DENOMINADOR: quantos veículos a Smartec cobre. Sem isto, "96 veículos
    # com multa" não se lê.
    frota = pglocal.um("""
        SELECT count(*)::int AS cadastrados,
               sum(CASE WHEN tipo ILIKE '%%TRATOR%%' OR tipo ILIKE '%%CAMINH%%'
                        THEN 1 ELSE 0 END)::int AS com_motor
          FROM smt_veiculos
    """, esquema=esq) or {}

    acessos = pglocal.query("""
        SELECT servico, cnpj, empresa, situacao, data_expiracao,
               (data_expiracao - current_date)::int AS dias
          FROM smt_acessos ORDER BY data_expiracao NULLS LAST
    """, esquema=esq)

    lic = pglocal.um("""
        SELECT count(*)::int AS total,
               sum(CASE WHEN cronotacografo < current_date
                        THEN 1 ELSE 0 END)::int AS crono_vencido,
               sum(CASE WHEN cronotacografo >= current_date
                         AND cronotacografo <= current_date + 90
                        THEN 1 ELSE 0 END)::int AS crono_90d
          FROM smt_licencas
    """, esquema=esq) or {}

    antt = pglocal.um("""
        SELECT count(*)::int AS n,
               coalesce(sum(impeditiva), 0)::int AS impeditivas,
               count(DISTINCT placa)::int AS veiculos
          FROM smt_antt
    """, esquema=esq) or {}

    return {
        "multas": por_especie.get("multa", {}),
        "notificacoes": por_especie.get("notificacao", {}),
        "economia": dict(desc),
        "prazo": dict(prazo),
        "frota": dict(frota),
        "acessos": [dict(a) for a in acessos],
        "licencas": dict(lic),
        "antt": dict(antt),
    }


def infracoes(especie: str = "multa", limite: int = 300,
              esquema: str | None = None) -> list[dict]:
    """As linhas, ordenadas por URGÊNCIA e não por data.

    A ordenação é a decisão de produto desta tabela: notificação com prazo de
    indicação a vencer vem antes de tudo, porque é a única que some se
    ninguém agir. Ordenar por data de infração poria as mais velhas no topo —
    exatamente as que já não têm conserto.
    """
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query(f"""
        SELECT i.identificador, i.placa, i.renavam, i.ait, i.data_infracao,
               i.hora, i.local_infracao, i.municipio, i.uf, i.descricao,
               i.codigo_infracao, i.pontuacao, i.orgao, i.orgao_adesao_sne,
               i.valor_a_pagar, i.valor_com_desconto, i.vencimento,
               i.prazo_indicacao, i.situacao_boleto, i.linha_digitavel,
               i.boleto_vencimento, i.url_boleto, i.url_penalidade,
               i.motorista_nome, i.visto_em,
               v.frota, v.prefixo, v.tipo AS tipo_veiculo,
               -- Dias até o prazo que importa em cada espécie. Negativo já
               -- passou.
               CASE WHEN i.especie = 'notificacao'
                    THEN (i.prazo_indicacao - current_date)
                    ELSE (i.vencimento - current_date) END::int AS dias
          FROM smt_infracoes i
          LEFT JOIN smt_veiculos v ON v.renavam = i.renavam
         WHERE i.{ABERTO} AND i.especie = %(especie)s
         ORDER BY
           -- 1º as que ainda dá para tratar, da mais urgente para a menos
           CASE WHEN i.especie = 'notificacao'
                 AND i.prazo_indicacao >= current_date THEN 0 ELSE 1 END,
           CASE WHEN i.especie = 'notificacao'
                THEN i.prazo_indicacao ELSE i.vencimento END
             NULLS LAST,
           i.data_infracao DESC
         LIMIT %(limite)s
    """, {"especie": especie, "limite": limite}, esquema=esq)]


def por_veiculo(especie: str = "multa", limite: int = 50,
                esquema: str | None = None) -> list[dict]:
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query(f"""
        SELECT i.placa, i.renavam, v.frota, v.prefixo, v.tipo AS tipo_veiculo,
               count(*)::int AS n,
               coalesce(sum(i.valor_a_pagar), 0)::float8 AS valor,
               coalesce(sum(i.pontuacao), 0)::int AS pontos,
               min(i.data_infracao) AS mais_antiga,
               max(i.data_infracao) AS mais_recente
          FROM smt_infracoes i
          LEFT JOIN smt_veiculos v ON v.renavam = i.renavam
         WHERE i.{ABERTO} AND i.especie = %(especie)s
         GROUP BY 1,2,3,4,5 ORDER BY valor DESC, n DESC LIMIT %(limite)s
    """, {"especie": especie, "limite": limite}, esquema=esq)]


def por_infracao(especie: str = "multa", limite: int = 20,
                 esquema: str | None = None) -> list[dict]:
    """Ranking por tipo de infração — é onde se vê o que é comportamento.

    Junta com o catálogo do CTB para trazer a gravidade, que a linha da
    infração não carrega.
    """
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query(f"""
        SELECT i.codigo_infracao, i.descricao, count(*)::int AS n,
               coalesce(sum(i.valor_a_pagar), 0)::float8 AS valor,
               coalesce(sum(i.pontuacao), 0)::int AS pontos,
               max(c.gravidade) AS gravidade,
               count(DISTINCT i.renavam)::int AS veiculos
          FROM smt_infracoes i
          -- O catálogo chaveia pelo código CONCATENADO ("74550"), a infração
          -- guarda os dois pedaços. Ver a nota em armazenamento._linha_infracao.
          LEFT JOIN smt_infracoes_ctb c
                 ON c.desdobramento = i.codigo_infracao || i.desdobramento
         WHERE i.{ABERTO} AND i.especie = %(especie)s
         GROUP BY 1,2 ORDER BY n DESC, valor DESC LIMIT %(limite)s
    """, {"especie": especie, "limite": limite}, esquema=esq)]


def por_orgao(especie: str = "multa", limite: int = 15,
              esquema: str | None = None) -> list[dict]:
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query(f"""
        SELECT i.orgao, i.uf, count(*)::int AS n,
               coalesce(sum(i.valor_a_pagar), 0)::float8 AS valor,
               max(i.orgao_adesao_sne)::int AS adeso_sne
          FROM smt_infracoes i
         WHERE i.{ABERTO} AND i.especie = %(especie)s AND i.orgao <> ''
         GROUP BY 1,2 ORDER BY valor DESC LIMIT %(limite)s
    """, {"especie": especie, "limite": limite}, esquema=esq)]


def mensal(esquema: str | None = None) -> list[dict]:
    """Série mensal das infrações em aberto, POR MÊS DA INFRAÇÃO.

    O intervalo é GERADO com `generate_series`, não colhido do `GROUP BY`: mês
    sem infração simplesmente não voltaria da consulta e o gráfico emendaria
    março em julho, desenhando uma queda que não houve. É a lição da série da
    jornada, e aqui o caso é ainda mais provável — meses sem multa em aberto
    são comuns quando as antigas já foram pagas.
    """
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query(f"""
        WITH lim AS (
            SELECT date_trunc('month', coalesce(min(data_infracao),
                                                current_date))::date AS de,
                   date_trunc('month', current_date)::date AS ate
              FROM smt_infracoes WHERE {ABERTO}
        ), meses AS (
            SELECT generate_series(greatest(de, (ate - interval '23 months')::date),
                                   ate, interval '1 month')::date AS mes
              FROM lim
        )
        SELECT to_char(m.mes, 'YYYY-MM') AS mes,
               coalesce(sum(CASE WHEN i.especie = 'multa'
                                 THEN 1 ELSE 0 END), 0)::int AS multas,
               coalesce(sum(CASE WHEN i.especie = 'notificacao'
                                 THEN 1 ELSE 0 END), 0)::int AS notificacoes,
               coalesce(sum(CASE WHEN i.especie = 'multa'
                                 THEN i.valor_a_pagar ELSE 0 END),
                        0)::float8 AS valor
          FROM meses m
          LEFT JOIN smt_infracoes i
                 ON date_trunc('month', i.data_infracao)::date = m.mes
                AND i.{ABERTO}
         GROUP BY m.mes ORDER BY m.mes
    """, esquema=esq)]


def licencas(esquema: str | None = None) -> list[dict]:
    """Vencimentos de documentação, do mais urgente para o menos.

    `menor_venc` é o mínimo entre as cinco datas — é ele que ordena, porque o
    que importa é o PRIMEIRO documento a vencer, não o cronotacógrafo
    especificamente.
    """
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query("""
        SELECT l.renavam, l.placa, l.frota, l.cronotacografo, l.emtu, l.csv,
               l.pp_civ, l.pp_cipp_ctpp, v.tipo AS tipo_veiculo,
               least(coalesce(l.cronotacografo, '9999-12-31'::date),
                     coalesce(l.emtu,           '9999-12-31'::date),
                     coalesce(l.csv,            '9999-12-31'::date),
                     coalesce(l.pp_civ,         '9999-12-31'::date),
                     coalesce(l.pp_cipp_ctpp,   '9999-12-31'::date))
                   AS menor_venc,
               (least(coalesce(l.cronotacografo, '9999-12-31'::date),
                      coalesce(l.emtu,           '9999-12-31'::date),
                      coalesce(l.csv,            '9999-12-31'::date),
                      coalesce(l.pp_civ,         '9999-12-31'::date),
                      coalesce(l.pp_cipp_ctpp,   '9999-12-31'::date))
                - current_date)::int AS dias
          FROM smt_licencas l
          LEFT JOIN smt_veiculos v ON v.renavam = l.renavam
         ORDER BY menor_venc
    """, esquema=esq)]


def antt(limite: int = 200, esquema: str | None = None) -> list[dict]:
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query("""
        SELECT a.ait, a.processo, a.data_infracao, a.tipo, a.descricao,
               a.placa, a.situacao, a.impeditiva, a.data_notificacao,
               a.local_infracao, a.valor, a.vencimento, v.frota
          FROM smt_antt a
          LEFT JOIN smt_veiculos v ON v.placa = a.placa
         ORDER BY a.impeditiva DESC NULLS LAST, a.data_infracao DESC
         LIMIT %(limite)s
    """, {"limite": limite}, esquema=esq)]


def antt_por_situacao(esquema: str | None = None) -> list[dict]:
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query("""
        SELECT coalesce(nullif(situacao, ''), '(sem situação)') AS situacao,
               count(*)::int AS n,
               coalesce(sum(impeditiva), 0)::int AS impeditivas
          FROM smt_antt GROUP BY 1 ORDER BY n DESC
    """, esquema=esq)]


def cobertura(esquema: str | None = None) -> dict:
    """Quais veículos da Smartec o AVA conhece, e quais ficaram de fora.

    O cruzamento é em PYTHON porque as duas pontas estão em bancos diferentes
    (a frota no AVA, a Smartec no banco local) — não há JOIN possível. Mesma
    situação das diárias × jornada.

    A chave é o RENAVAM, e ela é sólida: bate em 301 de 301 sem divergência.
    """
    esq = _esq(esquema)
    smt = {r["renavam"]: dict(r) for r in pglocal.query(
        "SELECT renavam, placa, tipo, frota FROM smt_veiculos", esquema=esq)}
    try:
        from ..db import get_conn
        with get_conn() as cx:
            # A UTILIZAÇÃO, e não `tipofrota`. Medido em 31/08/2026:
            # `tipofrota = 1` junta FROTA (240), LOCAÇÃO (67) e PREVENTIVA (1),
            # então chamar isso de "frota própria" infla o denominador em 28% e
            # põe caminhão alugado na conta do que é nosso. `utilizacaoveiculo`
            # tem o domínio inteiro — FROTA, LOCACAO, AGREGADOS, TERCEIROS —, e
            # é ele que permite NOMEAR cada grupo pelo que ele é.
            #
            # O denominador continua sendo frota + locação, porque é quem a
            # Smartec cobre e quem gera multa que a empresa responde. O que
            # muda é o rótulo dizer isso — a mesma lição da Análise de KM, em
            # que "frota própria" somava TRA+LOC e não batia com linha nenhuma.
            linhas = cx.execute("""
                SELECT upper(trim(v.placa)) AS placa,
                       coalesce(nullif(trim(v.codigorenavam), ''), '') AS renavam,
                       v.tipofrota, v.numerofrota,
                       upper(coalesce(u.descricao, '')) AS utilizacao
                  FROM veiculo v
                  LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
                 WHERE v.ativoinativo = 1 AND v.placa IS NOT NULL
                   AND trim(v.placa) <> ''
            """).fetchall()
    except Exception:  # noqa: BLE001
        # Sem o AVA a tela não fica sem a lista de multas — só sem a
        # conferência de cobertura. Degradar é melhor que derrubar.
        return {"disponivel": False}

    ativos = [dict(r) for r in linhas]
    rnv_smt = {r.lstrip("0") for r in smt if r}
    # QUEM DEVE ESTAR NA SMARTEC: o que a empresa opera e por cuja multa ela
    # responde — frota própria e locação. Agregado e terceiro têm dono, e a
    # infração deles não é nossa.
    NOSSOS = ("FROTA", "LOCACAO")
    proprios = [v for v in ativos if v["utilizacao"] in NOSSOS]
    fora = [v for v in proprios
            if (v["renavam"] or "").lstrip("0") not in rnv_smt]
    sem_renavam = [v for v in proprios if not v["renavam"]]
    por_uso: dict[str, int] = {}
    for v in proprios:
        por_uso[v["utilizacao"]] = por_uso.get(v["utilizacao"], 0) + 1
    return {
        "disponivel": True,
        "smartec": len(smt),
        "ativos_ava": len(ativos),
        "proprios": len(proprios),
        "cobertos": len(proprios) - len(fora),
        # A COMPOSIÇÃO vai junto do total: "308 da frota própria" esconde que
        # 67 são alugados, e alguém vai comparar esse número com o da Análise
        # de KM e achar que um dos dois está errado.
        "composicao": por_uso,
        "fora": [{"placa": v["placa"], "frota": v["numerofrota"],
                  "renavam": v["renavam"], "uso": v["utilizacao"]}
                 for v in fora[:40]],
        "fora_total": len(fora),
        "sem_renavam": len(sem_renavam),
    }


def historico(limite: int = 200, esquema: str | None = None) -> list[dict]:
    """O que SAIU da lista — pago, defesa provida ou baixado pelo órgão.

    A Smartec não diz o motivo (a linha simplesmente para de vir), e a tela
    diz isso: "resolvida" aqui significa "deixou de constar", não "paga".
    Afirmar pagamento seria inventar o que a fonte não disse.
    """
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query("""
        SELECT identificador, especie, placa, ait, data_infracao, descricao,
               valor_a_pagar, orgao, situacao_boleto, primeiro_visto_em,
               sumiu_em, (sumiu_em::date - primeiro_visto_em::date)::int AS dias
          FROM smt_infracoes WHERE sumiu_em IS NOT NULL
         ORDER BY sumiu_em DESC LIMIT %(limite)s
    """, {"limite": limite}, esquema=esq)]


def cargas(limite: int = 30, esquema: str | None = None) -> list[dict]:
    esq = _esq(esquema)
    return [dict(r) for r in pglocal.query("""
        SELECT id, recurso, inicio, fim, status, itens, chamadas, mensagem,
               round(extract(epoch FROM (fim - inicio))::numeric, 1)::float8
                   AS segundos
          FROM smt_carga ORDER BY inicio DESC LIMIT %(limite)s
    """, {"limite": limite}, esquema=esq)]


def estado(esquema: str | None = None) -> dict:
    """O resumo que a Saúde do Servidor lê.

    Vermelho é "não está chegando", e SÓ isso: dado parado ou a ÚLTIMA
    passagem de algum recurso tendo falhado. Recusa isolada no meio do
    histórico vai para o detalhe — alarme que acende sem haver problema ensina
    a ignorar o alarme.
    """
    esq = _esq(esquema)
    ultimas = pglocal.query("""
        SELECT DISTINCT ON (recurso) recurso, status, fim, itens, mensagem
          FROM smt_carga WHERE fim IS NOT NULL
         ORDER BY recurso, inicio DESC
    """, esquema=esq)
    falhando = [dict(r) for r in ultimas if r["status"] == "erro"]
    ultimo = max((r["fim"] for r in ultimas if r["fim"]), default=None)

    acessos = pglocal.query("""
        SELECT servico, cnpj, empresa, data_expiracao,
               (data_expiracao - current_date)::int AS dias
          FROM smt_acessos WHERE data_expiracao IS NOT NULL
         ORDER BY data_expiracao
    """, esquema=esq)
    return {
        "ultima_coleta": ultimo,
        "recursos": [dict(r) for r in ultimas],
        "falhando": falhando,
        "acessos": [dict(a) for a in acessos],
    }


# ═══════════════════════════════════════════════════ alerta de prazo
#
# O QUE ESTA FUNÇÃO PRECISA ACERTAR, e é uma coisa só: quando NÃO falar.
#
# Ela alimenta um disparo automático de WhatsApp. Três respostas diferentes
# saem daqui e as três precisam ser distinguíveis, porque a ação de cada uma
# é outra:
#
#   há notificação vencendo   -> manda
#   não há                    -> CALA, e isso é sucesso
#   não dá para saber         -> CALA e DIZ o motivo, e isso é falha
#
# O terceiro caso é o perigoso. Se a coleta da Smartec parar, a consulta
# devolve zero notificação no prazo — indistinguível de "está tudo indicado".
# O alerta silenciaria justamente quando parou de enxergar, que é a família do
# "integração parada se disfarça de tela vazia" que já custou 136 dias na
# RasterJOR. Por isso o frescor é conferido ANTES do conteúdo: sem coleta
# recente esta função recusa, em vez de afirmar que não há prazo correndo.
HORAS_FRESCOR = 18


def prazo_indicacao_alerta(dias: int = 2, esquema: str | None = None) -> dict:
    """Notificações cujo prazo de indicar condutor vence em até `dias`.

    Devolve sempre um dict com `erro` (não dá para saber), `silencio` (não há
    o que avisar) ou os itens. Nunca levanta por ausência de dado.
    """
    esq = _esq(esquema)

    # 1) O DADO ESTÁ FRESCO? Antes de qualquer número.
    ult = pglocal.um("""
        SELECT max(fim) AS fim
          FROM smt_carga
         WHERE recurso = 'notificacao' AND status IN ('ok', 'vazio')
           AND fim IS NOT NULL
    """, esquema=esq) or {}
    fim = ult.get("fim")
    if fim is None:
        return {"erro": "a coleta de notificações da Smartec nunca rodou"}
    from datetime import datetime, timezone
    horas = (datetime.now(timezone.utc) - fim).total_seconds() / 3600.0
    if horas > HORAS_FRESCOR:
        return {"erro": (f"a última coleta de notificações foi há {horas:.0f} h "
                         f"— com dado velho não dá para afirmar prazo")}

    linhas = [dict(r) for r in pglocal.query(f"""
        SELECT placa, ait, orgao, descricao, pontuacao, valor_a_pagar,
               prazo_indicacao,
               (prazo_indicacao - current_date)::int AS dias
          FROM smt_infracoes
         WHERE {ABERTO} AND especie = 'notificacao'
           AND prazo_indicacao IS NOT NULL
           AND prazo_indicacao >= current_date
           AND prazo_indicacao <= current_date + %(dias)s
         ORDER BY prazo_indicacao, placa
    """, {"dias": int(dias)}, esquema=esq)]

    if not linhas:
        # SUCESSO. Silêncio aqui é a resposta certa — alarme que acende sem
        # haver problema ensina a ignorar o alarme.
        return {"silencio": "nenhuma notificação com prazo a vencer"}

    hoje = [x for x in linhas if x["dias"] == 0]
    return {
        "itens": linhas,
        "hoje": hoje,
        "depois": [x for x in linhas if x["dias"] > 0],
        "total_hoje": sum(float(x["valor_a_pagar"] or 0) for x in hoje),
        "total": sum(float(x["valor_a_pagar"] or 0) for x in linhas),
        "coletado_ha_h": round(horas, 1),
    }
