"""GESTÃO À VISTA DO CCO — o painel de TV da central de controle operacional.

Nasceu do painel "Gestão a Vista - CCO" do Avacorp (15/09/2026, pedido de
quem opera): os mesmos números e a mesma leitura por etapa — programação,
coleta, emissão do CT-e, entrega, e onde a operação trava.

AS REGRAS SÃO DO CÓRTEX, NÃO DO AVACORP, e isso foi decisão de quem opera.
As lupas do painel de lá abrem consultas internas do Avacorp (CST), que não
ficam na réplica que o CÓRTEX lê; nenhum recorte do ERP conferido em
15/09/2026 (cliente, contrato de freetime, filial, operação, programação de
embarque) levou as 269 coletas da janela às 30 que o painel de lá mostrava.
Até o SQL de lá chegar, cada número daqui diz a regra que o produz — e eles
NÃO batem com o Avacorp. Quem comparar os dois vai achar diferença, e a
diferença é esta.

A JANELA é a do filtro padrão de lá: de ontem a amanhã, pela janela de
carregamento (programação, coleta, emissão, freetime de carga) ou pela de
entrega (entrega, freetime de descarga, pendência). A janela sai como em
`horas_paradas/fonte.py` — `dtcoletar` quando o remetente está definido, o
agendamento da primeira `coleta_cliente` quando não — e os eventos são os do
Monitoramento SAC do ERP: 394/395 carregamento, 396/397 descarga, 425–440
motivo de atraso na coleta, 441–456 motivo de atraso na entrega.

O DENOMINADOR SÓ TEM QUEM O SAC ACOMPANHA. Medido em 15/09/2026 sobre 30
dias fechados: 68% das coletas têm algum apontamento SAC, e por cliente vai
de 17% a 100% (Maxion, Tupy, Forvia e Whirlpool acima de 96%; MWM 25%,
Adient 22%). Coleta sem chegada apontada num cliente que o SAC não acompanha
não está atrasada — está sem apontamento, e contá-la como atraso pintaria de
vermelho justamente quem não é monitorado. Então coleta, emissão, entrega,
freetime e pendência só contam os clientes com cobertura de pelo menos 90%
nos 30 dias fechados, e o painel DIZ quantas coletas ficaram de fora. A
programação (a coleta tem veículo?) não depende de apontamento e conta todos.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta

from . import db
from . import freetime as _ft
from . import queries as _q
from .queries import cached

log = logging.getLogger("cortex.cco")

#: Ontem, hoje e amanhã — o filtro padrão do painel do Avacorp.
JANELA_DIAS = 1

#: Cobertura mínima de apontamento SAC para o cliente entrar no denominador.
#: O corte tem degrau: em 15/09/2026 os clientes ou passavam de 96% ou
#: ficavam abaixo de 78% — 90% separa os dois grupos sem ficar na beira de
#: nenhum.
COBERTURA_MIN = 0.90
COBERTURA_DIAS = 30

#: Quanto depois da SAÍDA do carregamento o CT-e ainda conta como no prazo.
#: Medido em 15/09/2026, 1.592 coletas monitoradas de 30 dias: o CT-e sai
#: uma mediana de 20 min depois do apontamento de saída (o apontamento é a
#: saída da doca, e o caminhão ainda está no pátio); 22% saem antes, 57% em
#: até 30 min, 70% em até 60 min, 82% em até 2 h. Uma hora separa a rotina
#: do caminhão que saiu para a estrada sem documento.
TOLERANCIA_CTE_MIN = 60

#: Chegou no destino e o fim da descarga não foi apontado depois disto: é
#: pendência de finalização. A ocorrência 401 (viagem finalizada) não serve
#: para isso — medida no mesmo dia, só metade das viagens com fim de descarga
#: a recebe (823 de 1.599), e contar a falta dela acenderia metade da frota.
PENDENTE_FIM_H = 24

#: Sem chegada apontada e a janela vencida há mais que isto: é o APONTAMENTO
#: que falta, e não a carga que está atrasada. Medido em 15/09/2026 sobre 30
#: dias fechados dos clientes monitorados: das chegadas que FORAM apontadas,
#: só 3 de 1.256 coletas e 10 de 1.266 entregas chegaram mais de 24 h depois
#: da janela (menos de 1%) — e, nos mesmos dias, 53 entregas nunca tiveram a
#: chegada apontada, quase todas com CT-e emitido. Sem este corte a entrega de
#: anteontem que ninguém apontou ficaria "atrasada" no mural para sempre.
SEM_APONTAMENTO_H = 24

#: Permanência acima disto é quase sempre apontamento que faltou (a saída
#: nunca foi lançada), e não estadia — o mesmo teto de 24 h do SAC/freetime
#: (`queries.SAC_DET_SQL`).
TETO_PERMANENCIA_H = 24

#: Quantos avisos vão para o rodapé. O servidor corta e DIZ o total.
MAX_ALERTAS = 20

#: Quantos dias antes da janela uma coleta pode ter sido emitida e ainda ter
#: janela dentro dela — a mesma folga da Horas Paradas.
FOLGA_EMISSAO_DIAS = 45

_K = ("{a}.grupo = {b}.grupo AND {a}.empresa = {b}.empresa"
      " AND {a}.filial = {b}.filial AND {a}.unidade = {b}.unidade"
      " AND {a}.diferenciadornumero = {b}.diferenciadornumero"
      " AND {a}.serie = {b}.serie AND {a}.numero = {b}.numero")


def _k(a: str, b: str) -> str:
    return _K.format(a=a, b=b)


_CHAVE = ("grupo, empresa, filial, unidade, diferenciadornumero, serie, numero")

# Quem o SAC acompanha: fração das coletas de cada cliente, nos 30 dias
# FECHADOS, que tem pelo menos uma ocorrência SAC (a descrição, como no
# Monitoramento SAC do ERP). O dia em curso fica fora: nele a coleta da tarde
# ainda não teve tempo de ser apontada.
COBERTURA_SQL = """
WITH col AS (
  SELECT c.grupo, c.empresa, c.filial, c.unidade, c.diferenciadornumero,
         c.serie, c.numero, acc.codigo AS cod,
         btrim(coalesce(ac.descricao, '')) AS cliente
  FROM coleta c
  JOIN agrupamentocliente_cnpjcpfcodigo acc
    ON acc.grupo = c.grupo AND acc.empresa = c.empresa
   AND acc.cnpjcpfcodigo = c.cnpjcpfcodigopagadorfrete AND acc.vinculo = 1
  LEFT JOIN agrupamentocliente ac
    ON ac.grupo = acc.grupo AND ac.empresa = acc.empresa AND ac.codigo = acc.codigo
  WHERE c.dtcancelamento IS NULL
    AND c.dtcoletar >= current_date - %(dias)s
    AND c.dtcoletar <  current_date
)
SELECT col.cod, max(col.cliente) AS cliente, count(*) AS coletas,
       sum(CASE WHEN EXISTS (
             SELECT 1 FROM coleta_ocorrencia o
             JOIN ocorrencia oc ON oc.codigo = o.ocorrencia
             WHERE """ + _k("o", "col") + """
               AND oc.descricao ILIKE '%%sac%%')
           THEN 1 ELSE 0 END) AS com_sac
FROM col
GROUP BY col.cod
"""

_MERC = _ft.sql_equivalente(_ft.sql_normalizar("a.mercadorias"))

# SEM `FILTER`: o ERP é PostgreSQL 9.3. O primeiro apontamento de cada código
# vale, na ordem de lançamento — a mesma leitura da Horas Paradas.
CCO_SQL = f"""
WITH col AS (
  SELECT c.grupo, c.empresa, c.filial, c.unidade, c.diferenciadornumero,
         c.serie, c.numero, c.mercadorias,
         btrim(coalesce(c.veiculo, '')) AS veiculo,
         acc.codigo AS cod, btrim(coalesce(ac.descricao, '')) AS cliente,
         CASE WHEN c.remetentedefinido = 1 THEN c.dtcoletar
              ELSE coalesce((SELECT x.dtagendamentocoleta FROM coleta_cliente x
                             WHERE {_k("x", "c")} ORDER BY x.sequencia LIMIT 1),
                            c.dtcoletar) END AS jc,
         CASE WHEN c.destinatariodefinido = 1 THEN c.dtprevisaochegadaviagem
              ELSE coalesce((SELECT x.dtagendamentoentrega FROM coleta_cliente x
                             WHERE {_k("x", "c")} ORDER BY x.sequencia LIMIT 1),
                            c.dtprevisaochegadaviagem) END AS je
  FROM coleta c
  LEFT JOIN agrupamentocliente_cnpjcpfcodigo acc
    ON acc.grupo = c.grupo AND acc.empresa = c.empresa
   AND acc.cnpjcpfcodigo = c.cnpjcpfcodigopagadorfrete AND acc.vinculo = 1
  LEFT JOIN agrupamentocliente ac
    ON ac.grupo = acc.grupo AND ac.empresa = acc.empresa AND ac.codigo = acc.codigo
  WHERE c.dtcancelamento IS NULL
    AND c.dtemissao >= %(de)s::date - {FOLGA_EMISSAO_DIAS}
),
alvo AS (
  SELECT * FROM col
  WHERE jc::date BETWEEN %(de)s AND %(ate)s
     OR je::date BETWEEN %(de)s AND %(ate)s
),
ev AS (
  SELECT o.grupo, o.empresa, o.filial, o.unidade, o.diferenciadornumero,
         o.serie, o.numero, o.ocorrencia, o.dtocorrencia,
         btrim(coalesce(oc.descricao, '')) AS descricao,
         row_number() OVER (PARTITION BY o.grupo, o.empresa, o.filial, o.unidade,
                                         o.diferenciadornumero, o.serie, o.numero,
                                         o.ocorrencia
                            ORDER BY o.sequenciaocorrencia) AS rn
  FROM coleta_ocorrencia o
  JOIN alvo a ON {_k("a", "o")}
  LEFT JOIN ocorrencia oc ON oc.codigo = o.ocorrencia
  WHERE o.ocorrencia IN (394, 395, 396, 397, 401)
     OR o.ocorrencia BETWEEN 425 AND 456
),
evc AS (
  SELECT {_CHAVE},
         max(CASE WHEN ocorrencia = 394 AND rn = 1 THEN dtocorrencia END) AS cc,
         max(CASE WHEN ocorrencia = 395 AND rn = 1 THEN dtocorrencia END) AS sc,
         max(CASE WHEN ocorrencia = 396 AND rn = 1 THEN dtocorrencia END) AS cd,
         max(CASE WHEN ocorrencia = 397 AND rn = 1 THEN dtocorrencia END) AS fd,
         -- 401 VIAGEM FINALIZADA: não serve de pendência (só metade das
         -- viagens a recebe), mas quando existe é prova de que a entrega
         -- aconteceu
         max(CASE WHEN ocorrencia = 401 THEN 1 ELSE 0 END) AS fin,
         max(CASE WHEN ocorrencia BETWEEN 425 AND 440 THEN 1 ELSE 0 END) AS motivo_coleta,
         max(CASE WHEN ocorrencia BETWEEN 441 AND 456 THEN 1 ELSE 0 END) AS motivo_entrega,
         -- o TEXTO do motivo, para o modal: o cartão conta a coleta, o
         -- detalhe diz qual motivo o SAC apontou
         string_agg(DISTINCT CASE WHEN ocorrencia BETWEEN 425 AND 440 THEN descricao END,
                    ' · ' ORDER BY CASE WHEN ocorrencia BETWEEN 425 AND 440
                                        THEN descricao END) AS motivo_coleta_txt,
         string_agg(DISTINCT CASE WHEN ocorrencia BETWEEN 441 AND 456 THEN descricao END,
                    ' · ' ORDER BY CASE WHEN ocorrencia BETWEEN 441 AND 456
                                        THEN descricao END) AS motivo_entrega_txt
  FROM ev
  GROUP BY {_CHAVE}
),
cte AS (
  SELECT kc.grupo, kc.empresa, kc.filialdocumento AS filial,
         kc.unidadedocumento AS unidade,
         kc.diferenciadornumerodocumento AS diferenciadornumero,
         kc.seriedocumento AS serie, kc.numerodocumento AS numero,
         min(kn.dtemissao) AS cte_em
  FROM conhecimento_composicao kc
  JOIN conhecimento kn
    ON kn.grupo = kc.grupo AND kn.empresa = kc.empresa AND kn.filial = kc.filial
   AND kn.unidade = kc.unidade AND kn.diferenciadornumero = kc.diferenciadornumero
   AND kn.serie = kc.serie AND kn.numero = kc.numero AND kn.dtcancelamento IS NULL
  JOIN alvo a
    ON a.grupo = kc.grupo AND a.empresa = kc.empresa AND a.filial = kc.filialdocumento
   AND a.unidade = kc.unidadedocumento
   AND a.diferenciadornumero = kc.diferenciadornumerodocumento
   AND a.serie = kc.seriedocumento AND a.numero = kc.numerodocumento
  WHERE kc.tipodocumento = 27
  GROUP BY 1, 2, 3, 4, 5, 6, 7
),
{_q.SAC_FT_REP},
{_q.SAC_FT_MERC}
SELECT a.numero, a.filial, a.cod, a.cliente, a.veiculo, a.jc, a.je,
       evc.cc, evc.sc, evc.cd, evc.fd,
       coalesce(evc.motivo_coleta, 0) AS motivo_coleta,
       coalesce(evc.motivo_entrega, 0) AS motivo_entrega,
       coalesce(evc.fin, 0) AS fin,
       evc.motivo_coleta_txt, evc.motivo_entrega_txt,
       cte.cte_em,
       -- A CLÁUSULA DE FREETIME é a do módulo da casa: a da mercadoria, a
       -- genérica do contrato, e o último recurso — a mesma do SAC/freetime.
       extract(epoch FROM coalesce(esp.freetimecarga, ger.freetimecarga,
                                   ft.freetimecarga)) / 3600 AS ft_carga_h,
       extract(epoch FROM coalesce(esp.freetimedescarga, ger.freetimedescarga,
                                   ft.freetimedescarga)) / 3600 AS ft_descarga_h,
       current_timestamp AT TIME ZONE 'America/Sao_Paulo' AS agora
FROM alvo a
LEFT JOIN evc ON {_k("evc", "a")}
LEFT JOIN cte ON {_k("cte", "a")}
LEFT JOIN ft ON ft.agrupamentocliente = a.cod
LEFT JOIN ftm esp ON esp.ag = a.cod AND esp.merc <> '' AND esp.merc = {_MERC}
LEFT JOIN ftm ger ON ger.ag = a.cod AND ger.merc = ''
"""


def _horas(fim: datetime, ini: datetime) -> float:
    return (fim - ini).total_seconds() / 3600


def _hm(horas: float) -> str:
    """2,67 h → "2h40"; menos de uma hora sai em minutos."""
    minutos = int(round(horas * 60))
    h, m = divmod(minutos, 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


def _pct(bom: int, ruim: int) -> float | None:
    """Pontualidade só existe com base: zero no prazo e zero atrasadas é
    ausência, e não 0% nem 100%."""
    tot = bom + ruim
    return round(100.0 * bom / tot, 1) if tot else None


#: OS MODAIS (quem opera, 15/09/2026: "ao clicar nos cards trazer um modal com
#: o detalhamento"). Cada cartão e os estados que o modal dele mostra, na
#: ordem das abas — o que pede ação primeiro.
ESTADOS = {
    "programacao": ("atrasadas", "no_prazo"),
    "coletas": ("atrasadas", "a_vencer", "no_prazo", "sem_apontamento"),
    "emissoes": ("atrasadas", "aguardando", "no_prazo"),
    "entregas": ("atrasadas", "a_vencer", "no_prazo", "sem_apontamento"),
    "carregamento": ("freetime", "motivos", "sem_clausula"),
    "descarga": ("freetime", "motivos", "sem_clausula"),
    "pendentes": ("pendentes",),
}
CARDS_DETALHE = tuple(ESTADOS) + ("cobertura",)

TITULOS = {"programacao": "Programação", "coletas": "Coletas",
           "emissoes": "Emissão do CT-e", "entregas": "Entregas",
           "carregamento": "Carregamento", "descarga": "Descarga",
           "pendentes": "Pendentes de finalização",
           "cobertura": "Acompanhados pelo SAC"}

_ROTULOS = {"atrasadas": "Atrasadas", "no_prazo": "No prazo",
            "a_vencer": "A vencer", "sem_apontamento": "Sem apontamento",
            "aguardando": "Aguardando CT-e", "freetime": "Freetime excedido",
            "motivos": "Motivo de atraso", "sem_clausula": "Sem cláusula de freetime",
            "pendentes": "Sem fim de descarga", "monitorados": "Acompanhados",
            "fora": "Fora da conta"}
_ROTULO_CARD = {("programacao", "atrasadas"): "Sem veículo, janela vencida",
                ("coletas", "no_prazo"): "Chegou na janela",
                ("entregas", "no_prazo"): "Chegou na janela"}


def rotulo(card: str, estado: str) -> str:
    return _ROTULO_CARD.get((card, estado), _ROTULOS[estado])


def regras() -> dict:
    """A regra de cada cartão, em texto, escrita a partir das MESMAS constantes
    que o código usa — o modal diz a conta que produziu a lista."""
    t, s, p = TOLERANCIA_CTE_MIN, SEM_APONTAMENTO_H, PENDENTE_FIM_H
    ft = ("o relógio começa no que vier depois (a janela ou a chegada) e vai "
          "até a saída — ou até agora, se o veículo segue lá — contra a "
          "cláusula de freetime do contrato (a da mercadoria, a genérica, ou a "
          f"de último recurso); permanência acima de {TETO_PERMANENCIA_H} h é "
          "apontamento que faltou e fica fora")
    return {
        "programacao": "Coletas com janela de carregamento de ontem a amanhã, de "
                       "TODOS os clientes. Atrasada = sem veículo e com a janela "
                       "já vencida.",
        "coletas": "Clientes acompanhados pelo SAC. No prazo = chegada ao "
                   "carregamento (SAC 394) até a janela. Atrasada = chegou "
                   f"depois, ou ainda não chegou com a janela vencida há até {s} h. "
                   "Sem apontamento = carregou (tem saída ou CT-e) sem a chegada "
                   f"lançada, ou janela vencida há mais de {s} h. Atraso = chegada "
                   "(ou agora) menos a janela.",
        "emissoes": f"No prazo = CT-e emitido até {t} min depois da saída do "
                    f"carregamento (SAC 395). Atrasada = depois disso, ou saiu há "
                    f"mais de {t} min sem CT-e. Aguardando = carregando, ou saiu "
                    f"há menos de {t} min.",
        "entregas": "Clientes acompanhados pelo SAC. No prazo = chegada no "
                    "destino (SAC 396) até a janela de entrega. Atrasada = chegou "
                    f"depois, ou ainda não chegou com a janela vencida há até {s} h. "
                    "Sem apontamento = descarregou (397) ou viagem finalizada "
                    f"(401) sem a chegada lançada, ou janela vencida há mais de {s} h.",
        "carregamento": f"Freetime excedido na carga: {ft}. Motivo de atraso = "
                        "ocorrência SAC 425 a 440 apontada na coleta.",
        "descarga": f"Freetime excedido na descarga: {ft}. Motivo de atraso = "
                    "ocorrência SAC 441 a 456 apontada na coleta.",
        "pendentes": f"Chegou no destino (SAC 396) há mais de {p} h e o fim da "
                     "descarga (397) não foi apontado.",
        "cobertura": f"Entra na pontualidade o cliente com pelo menos "
                     f"{int(COBERTURA_MIN * 100)}% das coletas apontadas pelo SAC "
                     f"nos {COBERTURA_DIAS} dias fechados. Os outros ficam fora: "
                     "sem apontamento, uma coleta sem chegada lançada não é "
                     "atraso.",
    }


def _fmt(v) -> str | None:
    return v.strftime("%Y-%m-%d %H:%M") if v else None


def _linha_det(r: dict, horas: float | None = None, **extra) -> dict:
    """Uma coleta no modal: a identificação e os horários que as regras usam.
    Motorista não entra — a coleta e a placa bastam para achar a carga no ERP.
    `horas` tem SINAL: positivo é atraso ou excesso; negativo, antecedência ou o
    que falta para a janela."""
    d = {"coleta": r["numero"], "filial": r["filial"],
         "cliente": r["cliente"] or "sem cliente", "veiculo": r["veiculo"] or None,
         "janela_carga": _fmt(r["jc"]), "chegada_carga": _fmt(r["cc"]),
         "saida_carga": _fmt(r["sc"]), "cte": _fmt(r["cte_em"]),
         "janela_entrega": _fmt(r["je"]), "chegada_entrega": _fmt(r["cd"]),
         "fim_descarga": _fmt(r["fd"]),
         "horas": None if horas is None else round(horas, 2)}
    d.update(extra)
    return d


def classificar(linhas: list[dict], agora: datetime, monitorados, de: date,
                ate: date, detalhe: bool = False) -> dict:
    """As regras do painel, sobre as linhas do ERP. Função PURA: é aqui que o
    teste afirma cada regra com linha escrita à mão.

    `monitorados` são os códigos de cliente com cobertura SAC de 90%+.

    `detalhe=True` devolve também, por cartão e estado, a LISTA das coletas —
    montada no MESMO ponto em que o contador soma (`marca`), então o modal
    nunca discorda do número do cartão.
    """
    monitorados = set(monitorados or ())
    dentro = lambda x: x is not None and de <= x.date() <= ate  # noqa: E731
    tol = timedelta(minutes=TOLERANCIA_CTE_MIN)

    prog = {"total": 0, "no_prazo": 0, "atrasadas": 0}
    col = {"no_prazo": 0, "atrasadas": 0, "a_vencer": 0, "sem_apontamento": 0}
    emi = {"no_prazo": 0, "atrasadas": 0, "aguardando": 0}
    ent = {"no_prazo": 0, "atrasadas": 0, "a_vencer": 0, "sem_apontamento": 0}
    car = {"motivos": 0, "freetime": 0, "freetime_agora": 0, "sem_clausula": 0}
    des = {"motivos": 0, "freetime": 0, "freetime_agora": 0, "sem_clausula": 0}
    pend = {"pendentes": 0}
    alertas: list[dict] = []
    fora: Counter = Counter()
    cli_mon: set = set()
    n_mon = 0
    det = {c: {e: [] for e in es} for c, es in ESTADOS.items()} if detalhe else None
    por_cliente: dict = {}

    def marca(card: str, bloco: dict, estado: str, r: dict,
              horas: float | None = None, **extra) -> None:
        bloco[estado] += 1
        if det is not None:
            det[card][estado].append(_linha_det(r, horas, **extra))

    def avisa(tipo: str, horas: float, texto: str) -> None:
        alertas.append({"tipo": tipo, "horas": round(horas, 2), "texto": texto})

    def freetime(ft_h, janela, chegada, saida, card: str, bloco: dict,
                 rotulo_: str, r, motivo_txt) -> None:
        """O relógio começa no que vier DEPOIS — a janela ou a chegada: o
        veículo que chega cedo não consome freetime, e o que chega atrasado não
        cobra do cliente o próprio atraso. É a conta da planilha que o cliente
        aceita (crônica da Horas Paradas)."""
        if ft_h is None:
            marca(card, bloco, "sem_clausula", r)
            return
        inicio = max(janela, chegada) if janela else chegada
        dur = _horas(saida or agora, inicio)
        if dur <= ft_h or dur > TETO_PERMANENCIA_H:
            return
        marca(card, bloco, "freetime", r, dur - ft_h, freetime_h=round(ft_h, 2),
              permanencia_h=round(dur, 2), agora=not saida, motivo=motivo_txt)
        if not saida:
            bloco["freetime_agora"] += 1
            avisa("freetime", dur - ft_h, f"{rotulo_} além do freetime · coleta "
                  f"{r['numero']} · {r['cliente'] or 'sem cliente'} · +{_hm(dur - ft_h)}")

    for r in linhas:
        jc, je = r["jc"], r["je"]
        na_carga, na_entrega = dentro(jc), dentro(je)
        cliente = r["cliente"] or "sem cliente"
        # o SQL já recorta pela janela; aqui é para a contagem dos
        # acompanhados (`coletas` da cobertura) e a lista do modal contarem as
        # MESMAS linhas
        if not (na_carga or na_entrega):
            continue
        if detalhe:
            pc = por_cliente.setdefault(r["cod"], {"cliente": cliente, "coletas": 0})
            pc["coletas"] += 1

        if na_carga:
            prog["total"] += 1
            if not r["veiculo"] and jc < agora:
                marca("programacao", prog, "atrasadas", r, _horas(agora, jc))
                avisa("programacao", _horas(agora, jc),
                      f"Sem veículo · coleta {r['numero']} · {cliente} · janela há "
                      f"{_hm(_horas(agora, jc))}")
            else:
                marca("programacao", prog, "no_prazo", r,
                      _horas(agora, jc) if not r["veiculo"] else None)

        if r["cod"] not in monitorados:
            fora[cliente] += 1
            continue
        n_mon += 1
        cli_mon.add(r["cod"])

        if na_carga:
            cc, sc, cte_em = r["cc"], r["sc"], r["cte_em"]
            if cc:
                marca("coletas", col, "no_prazo" if cc <= jc else "atrasadas", r,
                      _horas(cc, jc))
            elif jc >= agora:
                marca("coletas", col, "a_vencer", r, _horas(agora, jc))
            elif sc or cte_em or _horas(agora, jc) > SEM_APONTAMENTO_H:
                # carregou (tem saída ou CT-e), ou a janela venceu há mais de
                # um dia: é o apontamento que falta, não o veículo
                marca("coletas", col, "sem_apontamento", r, _horas(agora, jc))
            else:
                marca("coletas", col, "atrasadas", r, _horas(agora, jc))
                # sem veículo, o aviso é o da programação: a mesma coleta não
                # ocupa duas vezes o rodapé
                if r["veiculo"]:
                    avisa("coleta", _horas(agora, jc), f"Veículo não chegou · coleta "
                          f"{r['numero']} · {cliente} · +{_hm(_horas(agora, jc))}")

            if cc or sc:
                if cte_em:
                    marca("emissoes", emi, "no_prazo" if (sc is None or cte_em <= sc + tol)
                          else "atrasadas", r, _horas(cte_em, sc) if sc else None)
                elif sc and agora > sc + tol:
                    marca("emissoes", emi, "atrasadas", r, _horas(agora, sc))
                    avisa("cte", _horas(agora, sc), f"Saiu sem CT-e · coleta "
                          f"{r['numero']} · {cliente} · há {_hm(_horas(agora, sc))}")
                else:
                    marca("emissoes", emi, "aguardando", r,
                          _horas(agora, sc) if sc else None)

            if cc:
                freetime(r["ft_carga_h"], jc, cc, sc, "carregamento", car,
                         "No cliente", r, r.get("motivo_coleta_txt"))
            if r["motivo_coleta"]:
                marca("carregamento", car, "motivos", r,
                      motivo=r.get("motivo_coleta_txt"))

        if na_entrega:
            cd, fd = r["cd"], r["fd"]
            if cd:
                marca("entregas", ent, "no_prazo" if cd <= je else "atrasadas", r,
                      _horas(cd, je))
            elif je >= agora:
                marca("entregas", ent, "a_vencer", r, _horas(agora, je))
            elif fd or r.get("fin") or _horas(agora, je) > SEM_APONTAMENTO_H:
                # descarregou (fim de descarga), a viagem foi finalizada, ou a
                # janela venceu há mais de um dia: é a chegada que não foi
                # apontada, não a carga que não chegou
                marca("entregas", ent, "sem_apontamento", r, _horas(agora, je))
            else:
                marca("entregas", ent, "atrasadas", r, _horas(agora, je))
                avisa("entrega", _horas(agora, je), f"Entrega atrasada · coleta "
                      f"{r['numero']} · {cliente} · +{_hm(_horas(agora, je))}")

            if cd:
                freetime(r["ft_descarga_h"], je, cd, fd, "descarga", des,
                         "Na descarga", r, r.get("motivo_entrega_txt"))
                if not fd and _horas(agora, cd) > PENDENTE_FIM_H:
                    marca("pendentes", pend, "pendentes", r, _horas(agora, cd))
                    avisa("pendente", _horas(agora, cd), f"Sem fim de descarga · "
                          f"coleta {r['numero']} · {cliente} · chegou há "
                          f"{_hm(_horas(agora, cd))}")
            if r["motivo_entrega"]:
                marca("descarga", des, "motivos", r,
                      motivo=r.get("motivo_entrega_txt"))

    alertas.sort(key=lambda a: -a["horas"])
    res = {
        "kpis": {
            "programacao": prog,
            "coletas": {**col, "pontualidade": _pct(col["no_prazo"], col["atrasadas"])},
            "emissoes": emi,
            "entregas": {**ent, "pontualidade": _pct(ent["no_prazo"], ent["atrasadas"])},
            "carregamento": car,
            "descarga": des,
            "pendentes_finalizacao": pend["pendentes"],
        },
        "cobertura": {
            "clientes": len(cli_mon),
            "coletas": n_mon,
            "fora_coletas": sum(fora.values()),
            "fora_clientes": [c for c, _ in fora.most_common(3)],
            "fora_clientes_n": len(fora),
        },
        "alertas": alertas[:MAX_ALERTAS],
        "alertas_total": len(alertas),
    }
    if detalhe:
        res["detalhe"] = det
        res["por_cliente"] = por_cliente
    return res


@cached(ttl=3600)
def clientes_monitorados() -> dict:
    """Os clientes que o SAC acompanha — cobertura muda devagar, então a
    leitura de 30 dias é refeita a cada hora, não a cada minuto da TV."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(COBERTURA_SQL, {"dias": COBERTURA_DIAS})
        rows = cur.fetchall()
    codigos = sorted(r["cod"] for r in rows
                     if r["coletas"] and r["com_sac"] / r["coletas"] >= COBERTURA_MIN)
    clientes = [{"cod": r["cod"], "cliente": r.get("cliente") or "sem cliente",
                 "coletas": r["coletas"], "com_sac": r["com_sac"],
                 "pct": round(100.0 * r["com_sac"] / r["coletas"], 1) if r["coletas"] else None}
                for r in rows]
    return {"codigos": codigos, "avaliados": len(rows), "clientes": clientes}


# UMA LEITURA para o cartão e para o modal: com dois caches, o modal podia vir
# de uma leitura dois minutos mais nova que o número que a pessoa clicou, e a
# lista não bateria com ele. SEM `velha_ate`, e é requisito: o painel publica
# "agora" (veículo que não chegou, caminhão que saiu sem CT-e). Guard:
# tests/test_leitura_velha.py.
@cached(ttl=120)
def _leitura_cco() -> dict:
    hoje = date.today()
    de = hoje - timedelta(days=JANELA_DIAS)
    ate = hoje + timedelta(days=JANELA_DIAS)
    monit = clientes_monitorados()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CCO_SQL, {"de": de, "ate": ate})
        linhas = cur.fetchall()
    agora = linhas[0]["agora"] if linhas else datetime.now()
    return {"linhas": linhas, "agora": agora, "de": de, "ate": ate, "monit": monit}


def _ordena(card: str, estado: str, linhas: list[dict]) -> list[dict]:
    """O que pede ação sai do mais velho para o mais novo; o que está em dia,
    pela janela."""
    if estado in ("no_prazo", "a_vencer"):
        campo = "janela_entrega" if card in ("entregas", "pendentes", "descarga") else "janela_carga"
        return sorted(linhas, key=lambda x: (x.get(campo) or "9999", x["coleta"]))
    return sorted(linhas, key=lambda x: (x["horas"] is None, -(x["horas"] or 0), x["coleta"]))


def get_cco_detalhe(card: str) -> dict:
    """A lista por trás de um cartão, da MESMA leitura e da MESMA contagem."""
    if card not in CARDS_DETALHE:
        raise ValueError(f"cartão desconhecido: {card!r}")
    lt = _leitura_cco()
    res = classificar(lt["linhas"], lt["agora"], lt["monit"]["codigos"],
                      lt["de"], lt["ate"], detalhe=True)
    base = {"card": card, "titulo": TITULOS[card], "regra": regras()[card],
            "periodo": {"de": lt["de"].isoformat(), "ate": lt["ate"].isoformat()},
            "agora": lt["agora"].strftime("%Y-%m-%d %H:%M")}
    if card == "cobertura":
        cob = {c["cod"]: c for c in lt["monit"].get("clientes", [])}
        mon = set(lt["monit"]["codigos"])
        base["cobertura_min_pct"] = int(round(COBERTURA_MIN * 100))
        base["cobertura_dias"] = COBERTURA_DIAS
        grupos: dict = {"monitorados": [], "fora": []}
        for cod, pc in res["por_cliente"].items():
            c30 = cob.get(cod) or {}
            grupos["monitorados" if cod in mon else "fora"].append({
                "cliente": pc["cliente"], "coletas": pc["coletas"],
                "cobertura_pct": c30.get("pct"), "coletas_30d": c30.get("coletas")})
        base["estados"] = [
            {"estado": e, "rotulo": rotulo(card, e), "n": sum(x["coletas"] for x in grupos[e]),
             "linhas": sorted(grupos[e], key=lambda x: (-x["coletas"], x["cliente"]))}
            for e in ("monitorados", "fora")]
        return base
    base["estados"] = [
        {"estado": e, "rotulo": rotulo(card, e), "n": len(res["detalhe"][card][e]),
         "linhas": _ordena(card, e, res["detalhe"][card][e])}
        for e in ESTADOS[card]]
    return base


def get_cco() -> dict:
    lt = _leitura_cco()
    monit = lt["monit"]
    res = classificar(lt["linhas"], lt["agora"], monit["codigos"], lt["de"], lt["ate"])
    de, ate, agora = lt["de"], lt["ate"], lt["agora"]
    res["periodo"] = {"de": de.isoformat(), "ate": ate.isoformat()}
    res["agora"] = agora.strftime("%Y-%m-%d %H:%M")
    res["cobertura"]["clientes_avaliados"] = monit["avaliados"]
    res["regras"] = {"tolerancia_cte_min": TOLERANCIA_CTE_MIN,
                     "cobertura_min": COBERTURA_MIN,
                     "cobertura_dias": COBERTURA_DIAS,
                     "pendente_fim_h": PENDENTE_FIM_H}
    res["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    res["fonte"] = ("ERP AVA · coleta + ocorrências SAC (394–397, motivos "
                    "425–456) + CT-e (conhecimento_composicao 27) + freetime "
                    "(sulista.sac_freetimecliente) · regras do CÓRTEX, não as "
                    "do painel CCO do Avacorp")
    return res
