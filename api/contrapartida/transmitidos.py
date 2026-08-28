# api/contrapartida/transmitidos.py
"""Acompanhamento dos CT-e de contrapartida JÁ TRANSMITIDOS.

POR QUE UMA TELA SÓ PARA ISTO
=============================
A tela de conciliação (`ctecp`) responde **quanto falta fazer**: a fila por
agregado, o cadastro que impede emitir, os certificados a vencer. O registro do
que já saiu morava lá dentro como uma tabela de trinta linhas, no meio de nove
outros cartões — e por isso não respondia a pergunta de quem acompanha:

  - quantos documentos estão VALENDO agora, e quanto isso soma;
  - quantos foram cancelados, e o cancelado não está mais valendo;
  - o que a SEFAZ recusou, e por quê;
  - quais já chegaram à contabilidade e quais ainda não.

AS TRÊS SEPARAÇÕES QUE ESTA TELA NÃO PODE PERDER
------------------------------------------------
1. **Autorizado ≠ valendo.** O cancelamento entra como linha própria e a
   original guarda `cstat='100'` para sempre. Contar "autorizados" como se
   fossem os documentos vigentes infla o número e some com o cancelamento —
   que é justamente o evento que alguém quer ver.
2. **Homologação ≠ produção.** Homologação não tem valor fiscal. Somar as duas
   produz um total que não existe em lugar nenhum.
3. **Recusado não emitiu nada.** Ele conta como tentativa e como aprendizado
   (o motivo da SEFAZ), nunca como documento.

O VALOR SAI DO XML, e não de uma coluna
---------------------------------------
`emissao` não guarda o valor do documento. Ele podia virar coluna, mas isso
significaria mexer no caminho que monta, assina e transmite — o caminho que
acabou de custar dez documentos reemitidos por causa de um campo. Aqui a
leitura é feita no XML já guardado, no SELECT, e nenhuma linha do módulo fiscal
muda por causa de um cartão de painel. Se um dia ficar lento, aí sim vira
coluna, com medição na mão.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from api.contrapartida import cadastro, emissao

log = logging.getLogger("cortex.contrapartida.transmitidos")

# `vTPrest` aparece uma vez no CT-e, dentro de `vPrest`. A âncora é o próprio
# nome da tag — `vRec` tem o mesmo valor e capturá-lo por engano daria um total
# certo por acidente, que é pior que um errado.
_VALOR = ("coalesce(nullif(substring(e.xml from"
          " '<vTPrest>([0-9]+\\.?[0-9]*)</vTPrest>'), '')::numeric, 0)")

# Documento cancelado não está valendo. A lista de códigos vem de `emissao`
# para não existir uma segunda definição de "cancelado" na casa.
_NAO_CANCELADO = ("NOT EXISTS (SELECT 1 FROM emissao k"
                  " WHERE k.chave = e.chave AND k.cstat = ANY(%(canc)s))")

# Evento de cancelamento não é transmissão de documento: fora de toda contagem
# de tentativa, senão a taxa de acerto mede o que não é trabalho.
_E_DOCUMENTO = "e.cstat IS NOT NULL AND e.cstat NOT LIKE 'CANC:%%'"


def _conn():
    return cadastro._conn()


_KPIS_SQL = f"""
SELECT
  count(*) FILTER (WHERE e.ambiente='1' AND e.cstat='100'
                     AND {_NAO_CANCELADO})                      AS validos,
  coalesce(sum({_VALOR}) FILTER (WHERE e.ambiente='1'
                AND e.cstat='100' AND {_NAO_CANCELADO}), 0)     AS valor_valido,
  count(*) FILTER (WHERE e.ambiente='1' AND e.cstat='100'
                     AND NOT ({_NAO_CANCELADO}))                AS cancelados,
  count(*) FILTER (WHERE e.ambiente='1' AND {_E_DOCUMENTO})     AS tentativas_prod,
  count(*) FILTER (WHERE e.ambiente='1' AND e.cstat='100')      AS autorizados_prod,
  count(*) FILTER (WHERE e.ambiente='2' AND {_E_DOCUMENTO})     AS tentativas_homo,
  count(*) FILTER (WHERE e.ambiente='2' AND e.cstat='100')      AS autorizados_homo,
  count(*) FILTER (WHERE e.ambiente='2' AND e.cstat='748')      AS esperadas_homo,
  count(*) FILTER (WHERE e.ambiente='1' AND e.cstat='100'
                     AND {_NAO_CANCELADO} AND e.xml IS NOT NULL
                     AND e.xml_prot IS NOT NULL)                AS com_arquivo,
  count(DISTINCT e.cnpj_emitente) FILTER (WHERE e.ambiente='1'
                     AND e.cstat='100' AND {_NAO_CANCELADO})    AS emitentes,
  -- NUMERO CONSUMIDO SEM RETORNO. `cstat` nulo com motivo diferente de
  -- 'reservado' significa que o documento PARTIU e a resposta nao voltou: ele
  -- pode estar autorizado na SEFAZ sem estar aqui. Nao se resolve por
  -- software - alguem consulta a chave no portal e decide.
  count(*) FILTER (WHERE e.cstat IS NULL
                     AND coalesce(e.xmotivo,'') <> 'reservado')  AS sem_retorno,
  min(e.quando) FILTER (WHERE e.ambiente='1' AND e.cstat='100') AS primeiro,
  max(e.quando) FILTER (WHERE e.ambiente='1' AND e.cstat='100') AS ultimo
FROM emissao e
"""

# Um documento por EMITENTE, que é a unidade que importa: cada agregado é uma
# empresa emitindo em série própria. A faixa de numeração vai junto porque é
# ela que denuncia buraco — número recusado é queimado e não volta.
_POR_EMITENTE_SQL = f"""
SELECT e.cnpj_emitente,
       count(*) FILTER (WHERE e.cstat='100' AND {_NAO_CANCELADO})   AS validos,
       count(*) FILTER (WHERE e.cstat='100'
                          AND NOT ({_NAO_CANCELADO}))               AS cancelados,
       count(*) FILTER (WHERE e.cstat <> '100' AND {_E_DOCUMENTO})  AS recusados,
       coalesce(sum({_VALOR}) FILTER (WHERE e.cstat='100'
                     AND {_NAO_CANCELADO}), 0)                      AS valor,
       min(e.numero) FILTER (WHERE {_E_DOCUMENTO})                  AS n_de,
       max(e.numero) FILTER (WHERE {_E_DOCUMENTO})                  AS n_ate,
       count(DISTINCT e.numero) FILTER (WHERE {_E_DOCUMENTO})       AS n_usados,
       max(e.quando) FILTER (WHERE e.cstat='100')                   AS ultimo
  FROM emissao e
 WHERE e.ambiente = %(amb)s
 GROUP BY e.cnpj_emitente
 ORDER BY 5 DESC, 2 DESC
"""

_LISTA_SQL = f"""
SELECT e.id, e.quando, e.quem, e.ambiente, e.cnpj_emitente, e.serie, e.numero,
       e.chave, e.chave_origem, e.cstat, e.xmotivo, e.protocolo,
       {_VALOR} AS valor,
       (e.xml IS NOT NULL AND e.xml_prot IS NOT NULL) AS tem_arquivo,
       NOT ({_NAO_CANCELADO}) AS cancelado,
       -- SO PARA PRODUCAO. A chave de 44 digitos NAO carrega o ambiente, e o
       -- cNF e deterministico (soma dos campos anteriores, nao aleatorio):
       -- o mesmo emitente, serie e numero no mesmo mes produz a MESMA chave em
       -- homologacao e em producao. Sem este `CASE`, a linha de teste aparecia
       -- na tela como "XML enviado a contabilidade" por casar com a chave do
       -- documento real — e homologacao nunca entra nessa fila.
       CASE WHEN e.ambiente = '1'
            THEN (SELECT m.ok FROM cte_xml_email m WHERE m.chave = e.chave)
       END AS xml_enviado
  FROM emissao e
 WHERE {_E_DOCUMENTO}
   AND e.quando >= %(desde)s
 ORDER BY e.id DESC
 LIMIT %(limite)s
"""


def _pct(parte: int, total: int) -> float | None:
    """`None` e não 0 quando não houve nada: "0% de acerto" sem nenhuma
    tentativa é um número que acusa alguém."""
    return round(100.0 * parte / total, 1) if total else None


def painel(dias: int = 90, limite: int = 200) -> dict:
    """Tudo que a tela precisa, numa ida ao banco por bloco.

    Não levanta por falha de leitura: é a tela onde se olha justamente quando
    alguma coisa não está indo, e um erro 500 esconderia o resto.
    """
    desde = (date.today() - timedelta(days=int(dias))).isoformat()
    par = {"canc": list(emissao.CANCELAMENTOS), "desde": desde,
           "limite": int(limite)}
    vazio = {"kpis": {}, "por_emitente": [], "documentos": [], "por_dia": [],
             "por_cstat": [], "alertas": [], "erro": None,
             "dias": int(dias), "gerado_em": _agora()}

    try:
        with _conn() as c:
            k = dict(c.execute(_KPIS_SQL, par).fetchone())
            por_emi = [dict(r) for r in c.execute(
                _POR_EMITENTE_SQL, {**par, "amb": emissao.PRODUCAO})]
            docs = [dict(r) for r in c.execute(_LISTA_SQL, par)]
    except Exception as exc:  # noqa: BLE001
        log.warning("painel de transmitidos indisponivel: %s", exc)
        # o TIPO, nunca o texto: a mensagem do psycopg pode trazer o conninfo
        return {**vazio, "erro": type(exc).__name__}

    nomes = _nomes()
    validos = int(k["validos"] or 0)

    kpis = {
        "validos": validos,
        "valor_valido": float(k["valor_valido"] or 0),
        "cancelados": int(k["cancelados"] or 0),
        "emitentes": int(k["emitentes"] or 0),
        "tentativas_prod": int(k["tentativas_prod"] or 0),
        "autorizados_prod": int(k["autorizados_prod"] or 0),
        "taxa_prod": _pct(int(k["autorizados_prod"] or 0),
                          int(k["tentativas_prod"] or 0)),
        "tentativas_homo": int(k["tentativas_homo"] or 0),
        "autorizados_homo": int(k["autorizados_homo"] or 0),
        # A 748 diz que o CT-e de origem não consta na base da SEFAZ, e em
        # homologação ele NUNCA vai constar — foi autorizado em produção. Fora
        # do denominador, contada à parte: deixá-la dentro faria o período de
        # teste medir o ambiente em vez do trabalho.
        "esperadas_homo": int(k["esperadas_homo"] or 0),
        "taxa_homo": _pct(int(k["autorizados_homo"] or 0),
                          max(int(k["tentativas_homo"] or 0)
                              - int(k["esperadas_homo"] or 0), 0)),
        "com_arquivo": int(k["com_arquivo"] or 0),
        "sem_arquivo": max(validos - int(k["com_arquivo"] or 0), 0),
        "pct_arquivo": _pct(int(k["com_arquivo"] or 0), validos),
        "sem_retorno": int(k["sem_retorno"] or 0),
        "primeiro": k["primeiro"], "ultimo": k["ultimo"],
    }
    kpis.update(_contabilidade())

    for r in por_emi:
        r["valor"] = float(r["valor"] or 0)
        r["nome"] = nomes.get(r["cnpj_emitente"])
        # BURACO NA FAIXA: números entre o menor e o maior que NENHUMA linha
        # ocupou. Não é o mesmo que "queimado por recusa" — esse está na coluna
        # de recusados, e o número recusado continua registrado. Buraco é
        # número que sumiu, e a única forma de isso acontecer neste código é
        # uma transmissão que falhou ANTES de ser gravada: o número foi
        # escolhido, o documento pode ter chegado à SEFAZ, e não há registro.
        de, ate, usados = r["n_de"], r["n_ate"], r["n_usados"]
        r["buracos"] = (max((ate - de + 1) - usados, 0)
                        if de is not None and ate is not None else 0)

    for r in docs:
        r["valor"] = float(r["valor"] or 0)
        r["nome"] = nomes.get(r["cnpj_emitente"])
        r["autorizado"] = str(r["cstat"]) == "100"
        r["ambiente_nome"] = emissao.AMBIENTES.get(str(r["ambiente"]), "?")

    return {"kpis": kpis, "por_emitente": por_emi, "documentos": docs,
            "por_dia": _por_dia(), "por_cstat": _por_cstat(),
            "alertas": _alertas(kpis, por_emi),
            "dias": int(dias), "erro": None, "gerado_em": _agora()}


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _nomes() -> dict[str, str]:
    """Razão social por CNPJ, do cadastro LOCAL (titular do certificado).

    Do local e não do ERP porque esta tela não pode passar a depender do AVA
    para escrever o nome de quem emitiu — e porque é leitura que já está a uma
    consulta de distância.
    """
    try:
        return {c: (v.get("certificado") or {}).get("titular")
                for c, v in cadastro.mapa().items()
                if (v.get("certificado") or {}).get("titular")}
    except Exception as exc:  # noqa: BLE001
        log.warning("titulares indisponiveis: %s", exc)
        return {}


def _por_dia() -> list[dict]:
    try:
        return emissao.por_dia(30)
    except Exception as exc:  # noqa: BLE001
        log.warning("serie diaria indisponivel: %s", exc)
        return []


def _por_cstat() -> list[dict]:
    from api.contrapartida.servico import _por_cstat as base
    try:
        return base(10)
    except Exception as exc:  # noqa: BLE001
        log.warning("agrupamento por cStat indisponivel: %s", exc)
        return []


def _contabilidade() -> dict:
    """Estado do envio dos XML — a última etapa do documento.

    Mora nesta tela porque "transmitido" não é o fim: um CT-e autorizado que
    não chega a quem escritura ainda não serviu para nada.
    """
    try:
        from api.contrapartida import xml_email
        e = xml_email.estado()
        return {"xml_ativo": bool(e.get("ativo")),
                "xml_fila": int(e.get("pendentes") or 0),
                "xml_enviados": int(e.get("enviados") or 0),
                "xml_parados": int(e.get("parados") or 0),
                "xml_destino": e.get("destinatarios"),
                "xml_ultimo": e.get("ultimo_envio")}
    except Exception as exc:  # noqa: BLE001
        log.warning("estado do envio de XML indisponivel: %s", exc)
        return {"xml_ativo": None, "xml_fila": 0, "xml_enviados": 0,
                "xml_parados": 0, "xml_destino": None, "xml_ultimo": None}


def _alertas(k: dict, por_emi: list[dict]) -> list[dict]:
    """O que exige ação AGORA. Cada um diz o número e o que fazer com ele."""
    av: list[dict] = []

    if k.get("sem_retorno"):
        av.append({"nivel": "bad", "texto":
                   f"{k['sem_retorno']} número(s) consumido(s) SEM retorno da "
                   f"SEFAZ. O documento partiu e a resposta não voltou — ele "
                   f"pode estar AUTORIZADO no órgão sem estar aqui. O número "
                   f"não é reaproveitado de propósito; consulte a chave no "
                   f"portal da SEFAZ antes de reemitir a origem."})

    if k.get("sem_arquivo"):
        av.append({"nivel": "bad", "texto":
                   f"{k['sem_arquivo']} documento(s) valendo SEM o XML "
                   f"guardado. A chave prova que existem; o arquivo é o que se "
                   f"importa e se arquiva — sem ele não há o que mandar para a "
                   f"contabilidade nem o que apresentar numa fiscalização."})

    if k.get("xml_parados"):
        av.append({"nivel": "bad", "texto":
                   f"{k['xml_parados']} XML parado(s) no envio à contabilidade: "
                   f"bateram o teto de tentativas e não voltam à fila sozinhos. "
                   f"Conserte a causa e reenfileire em Gestão › Integrações."})

    if k.get("xml_ativo") is False and k.get("xml_fila"):
        av.append({"nivel": "warn", "texto":
                   f"{k['xml_fila']} XML esperando, com o envio à contabilidade "
                   f"DESLIGADO. Enquanto estiver assim nenhum documento sai."})

    buracos = [r for r in por_emi if r.get("buracos")]
    if buracos:
        total = sum(r["buracos"] for r in buracos)
        quais = ", ".join(f"{(r['nome'] or r['cnpj_emitente'])[:22]} "
                          f"({r['buracos']})" for r in buracos[:3])
        av.append({"nivel": "warn", "texto":
                   f"{total} número(s) SUMIRAM da série 900, em "
                   f"{len(buracos)} emitente(s): {quais}. Número escolhido que "
                   f"não virou linha no registro significa transmissão que "
                   f"falhou antes de ser gravada — e o documento pode ter "
                   f"chegado à SEFAZ mesmo assim. Confira no portal antes de "
                   f"reemitir."})

    if not k.get("validos"):
        av.append({"nivel": "info", "texto":
                   "Nenhum CT-e de contrapartida valendo em produção. Os "
                   "números de homologação são de teste e não têm valor fiscal."})
    return av
