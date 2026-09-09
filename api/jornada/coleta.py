"""Coleta da jornada — escreve nas tabelas `jor_*` do banco local do CÓRTEX.

DUAS ENTRADAS, um destino:

- `coletar()`    — chama a API da RasterJOR. É a rotina do dia a dia.
- `carga_ava()`  — copia o histórico de `sulista.rasterjor_*` do AVA. Roda uma
                   vez, para não perder os quinze meses que a rotina externa
                   chegou a trazer antes de morrer (01/01/2025 a 15/04/2026).

TODA PASSAGEM GRAVA EM `jor_carga`, inclusive a que falhou e a que não trouxe
nada. É essa trilha que faz a Saúde do Servidor descobrir uma parada no dia em
que ela acontece — a rotina anterior vivia no AVA e ficou 136 dias parada sem
sinal nenhum, porque o único sintoma era uma tela vazia.

IDEMPOTÊNCIA É REQUISITO, não otimização. A API devolve o dia inteiro a cada
chamada e o dia só fecha à noite: recoletar é o caso NORMAL. Todo `INSERT` é
`ON CONFLICT … DO UPDATE` sobre a chave natural — (documento, data) para a
jornada e (documento, tipo, chave_evento) para inconformidade e ausência.

CADA GRAVADOR ACEITA OS DOIS VOCABULÁRIOS, o da OpenAPI e o das colunas do AVA
(`start` × `start_datetime`, `driving_time` × `driving_time_minutes`). Não é
tolerância preguiçosa: a carga inicial lê do AVA e a coleta lê da API, e ter um
gravador por origem seria ter duas regras de conversão para manter iguais.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from .. import migracoes, pglocal
from . import cliente
from . import normalizar_nome

log = logging.getLogger("cortex.jornada.coleta")

ESQUEMA: str | None = None

# Janela padrão de uma passagem. 7 dias e não 1 porque a RasterJOR corrige
# jornada retroativamente (ajuste de marcação feito pelo RH no dia seguinte), e
# coletar só ontem deixaria a correção para trás para sempre.
#
# A janela SEMPRE termina em ontem: a API recusa consulta que alcance hoje
# ("são permitidas apenas consultas retroativas (D-1)").
JANELA_DIAS = 7


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _i(v) -> int:
    """Inteiro tolerante a nulo. A API manda `null` em dia sem jornada, e
    `int(None)` estoura no meio de um lote de mil linhas."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _t(v) -> str:
    return ("" if v is None else str(v)).strip()


def _dt(v):
    """ISO com ou sem timezone → datetime ingênuo. A RasterJOR manda
    `2026-01-31T06:49:12.000-03:00` em alguns campos e `2026-01-31 06:49` em
    outros; guardar os dois formatos crus faria a comparação de horário
    depender de quem gravou."""
    s = _t(v)
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=None) if d.tzinfo else d
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
    return None


def _data(v):
    d = _dt(v)
    return d.date() if d else None


def _trilha(cur, recurso, de, ate, ok, lidos, gravados, ms, msg, origem):
    cur.execute(
        "INSERT INTO jor_carga(ts, recurso, de, ate, ok, lidos, gravados, ms,"
        " mensagem, origem) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (_agora(), recurso, de, ate, 1 if ok else 0, lidos, gravados, ms,
         (msg or "")[:500], origem))


# ───────────────────────────────────────────────────── gravação (upsert)

def _grava_motoristas(cur, linhas, ts, origem) -> int:
    n = 0
    for r in linhas:
        doc = _t(r.get("documento") or r.get("driver_document") or r.get("cpf"))
        if not doc:
            continue                       # sem CPF não há como casar com nada
        cur.execute("""
            INSERT INTO jor_motoristas(documento, nome, api_id, ativo, filial,
                escala, cargo, admissao, cidade_base, coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (documento) DO UPDATE SET
              nome=EXCLUDED.nome, api_id=EXCLUDED.api_id, ativo=EXCLUDED.ativo,
              filial=EXCLUDED.filial, escala=EXCLUDED.escala,
              cargo=EXCLUDED.cargo, admissao=EXCLUDED.admissao,
              cidade_base=EXCLUDED.cidade_base, coletado_em=EXCLUDED.coletado_em,
              origem=EXCLUDED.origem
        """, (doc, _t(r.get("nome") or r.get("name") or r.get("driver_name")),
              r.get("api_id") or r.get("id") or r.get("driver_id"),
              0 if r.get("ativo") is False or r.get("active") is False else 1,
              _t(r.get("filial") or r.get("branch") or r.get("branch_name")),
              _t(r.get("escala") or r.get("work_schedule")
                 or r.get("work_schedule_name")),
              _t(r.get("cargo") or r.get("role")),
              _data(r.get("admissao") or r.get("admission_date")),
              _t(r.get("cidade_base") or r.get("base_city")), ts, origem))
        n += 1
    return n


def _grava_jornadas(cur, linhas, ts, origem) -> int:
    n = 0
    for r in linhas:
        doc = _t(r.get("driver_document") or r.get("documento"))
        dia = _data(r.get("date") or r.get("report_date") or r.get("data"))
        if not doc or not dia:
            continue
        cur.execute("""
            INSERT INTO jor_jornadas(documento, data, nome, filial, escala, tipo,
                inicio, fim, min_total, min_atividade, min_direcao, min_parado,
                min_refeicao, min_descanso, min_repouso, min_extra, min_falta,
                min_falta_repouso, min_atividade_acima, km, coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (documento, data) DO UPDATE SET
              nome=EXCLUDED.nome, filial=EXCLUDED.filial, escala=EXCLUDED.escala,
              tipo=EXCLUDED.tipo, inicio=EXCLUDED.inicio, fim=EXCLUDED.fim,
              min_total=EXCLUDED.min_total, min_atividade=EXCLUDED.min_atividade,
              min_direcao=EXCLUDED.min_direcao, min_parado=EXCLUDED.min_parado,
              min_refeicao=EXCLUDED.min_refeicao, min_descanso=EXCLUDED.min_descanso,
              min_repouso=EXCLUDED.min_repouso, min_extra=EXCLUDED.min_extra,
              min_falta=EXCLUDED.min_falta,
              min_falta_repouso=EXCLUDED.min_falta_repouso,
              min_atividade_acima=EXCLUDED.min_atividade_acima,
              km=EXCLUDED.km, coletado_em=EXCLUDED.coletado_em,
              origem=EXCLUDED.origem
        """, (doc, dia,
              _t(r.get("driver_name") or r.get("nome")),
              _t(r.get("branch_name") or r.get("filial")),
              _t(r.get("work_schedule_name") or r.get("escala")),
              _t(r.get("journey_type") or r.get("tipo")),
              _dt(r.get("start") or r.get("journey_start") or r.get("inicio")),
              _dt(r.get("end") or r.get("journey_end") or r.get("fim")),
              _i(r.get("total_time") or r.get("total_time_minutes")),
              _i(r.get("activity_time") or r.get("activity_time_minutes")),
              _i(r.get("driving_time") or r.get("driving_time_minutes")),
              _i(r.get("stopped_in_journey_time")
                 or r.get("stopped_in_journey_minutes")),
              _i(r.get("meal_time") or r.get("meal_time_minutes")),
              _i(r.get("rest_time") or r.get("rest_time_minutes")),
              _i(r.get("repose_time") or r.get("repose_time_minutes")),
              _i(r.get("over_time") or r.get("over_time_minutes")),
              _i(r.get("missing_time") or r.get("missing_time_minutes")),
              _i(r.get("missing_repose_time")
                 or r.get("missing_repose_time_minutes")),
              _i(r.get("activity_time_over_max_time")
                 or r.get("activity_over_max_time_minutes")),
              _f(r.get("kilometers_driven") or r.get("km")), ts, origem))
        n += 1
    return n


def _grava_inconformidades(cur, linhas, ts, origem) -> int:
    n = 0
    for r in linhas:
        # A API e a tabela do AVA chamam os MESMOS campos por nomes
        # diferentes, e a coleta lê da primeira enquanto a carga inicial lê da
        # segunda. Medido na primeira coleta real: 425 registros lidos e ZERO
        # gravados, porque o gravador só conhecia o vocabulário do AVA.
        #   API   unconformity   date              start   end
        #   AVA   unconformity_type  unconformity_date  event_start  event_end
        doc = _t(r.get("driver_document") or r.get("documento"))
        tipo = _t(r.get("unconformity") or r.get("unconformity_type")
                  or r.get("tipo"))
        ini = _dt(r.get("start") or r.get("event_start") or r.get("inicio"))
        dia = _data(r.get("date") or r.get("unconformity_date") or r.get("data"))
        if ini and not dia:
            dia = ini.date()
        if not doc or not tipo or not dia:
            continue                       # sem a chave natural não entra
        # 56% DAS INCONFORMIDADES NÃO TÊM HORA DE INÍCIO, e a primeira versão
        # deste loader as DESCARTAVA — 55.017 de 98.109 linhas, justamente os
        # tipos mais frequentes (EXCESSO DE JORNADA, SEM PARADA PARA REFEIÇÃO,
        # INTERVALO). Elas são fato do DIA, não intervalo. `chave_evento` dá o
        # que o UNIQUE precisa sem inventar horário em `inicio`.
        chave = ini or datetime.combine(dia, datetime.min.time())
        cur.execute("""
            INSERT INTO jor_inconformidades(documento, data, tipo, nome, placa,
                inicio, fim, chave_evento, duracao_min, velocidade, observacao,
                coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (documento, tipo, chave_evento) DO UPDATE SET
              data=EXCLUDED.data, nome=EXCLUDED.nome, placa=EXCLUDED.placa,
              inicio=EXCLUDED.inicio, fim=EXCLUDED.fim,
              duracao_min=EXCLUDED.duracao_min,
              velocidade=EXCLUDED.velocidade, observacao=EXCLUDED.observacao,
              coletado_em=EXCLUDED.coletado_em, origem=EXCLUDED.origem
        """, (doc, dia,
              tipo, _t(r.get("driver_name") or r.get("nome")),
              _t(r.get("plate") or r.get("placa")), ini,
              _dt(r.get("end") or r.get("event_end") or r.get("fim")), chave,
              _i(r.get("duration_minutes") or r.get("duracao_min")) or None,
              _f(r.get("speed") or r.get("velocidade")),
              _t(r.get("observation") or r.get("observacao")), ts, origem))
        n += 1
    return n


def _grava_ausencias(cur, linhas, ts, origem) -> int:
    n = 0
    for r in linhas:
        doc = _t(r.get("cpf") or r.get("documento") or r.get("driver_document"))
        tipo = _t(r.get("absence_type") or r.get("tipo"))
        # `start` é o nome da OpenAPI; `start_datetime` é como a tabela do
        # AVA chama. Os dois convivem: a carga inicial lê do AVA e a coleta
        # lê da API, e o mesmo gravador atende as duas.
        ini = _dt(r.get("start") or r.get("start_datetime") or r.get("inicio"))
        if not doc or not ini:
            continue
        cur.execute("""
            INSERT INTO jor_ausencias(externo_id, documento, nome, tipo,
                descricao, observacao, inicio, fim, coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (documento, tipo, inicio) DO UPDATE SET
              externo_id=EXCLUDED.externo_id, nome=EXCLUDED.nome,
              descricao=EXCLUDED.descricao, observacao=EXCLUDED.observacao,
              fim=EXCLUDED.fim, coletado_em=EXCLUDED.coletado_em,
              origem=EXCLUDED.origem
        """, (r.get("external_id") or r.get("externo_id"), doc,
              _t(r.get("driver_name") or r.get("nome")), tipo,
              _t(r.get("description") or r.get("descricao")),
              _t(r.get("observation") or r.get("observacao")), ini,
              _dt(r.get("end") or r.get("end_datetime") or r.get("fim")),
              ts, origem))
        n += 1
    return n


# ── os cinco recursos que faltavam ──────────────────────────────────────────


def _grava_diarias(cur, linhas, ts, origem, dia) -> int:
    """A diária APURADA de UM dia. O `dia` vem de fora, e é o ponto todo.

    O endpoint devolve `{periodo, motoristas:[{cpf, nome, diarias:[…]}]}` — um
    AGREGADO do período pedido, sem data por item. Quem chama pede um dia por
    vez (`_passagem_diarias`), e por isso `dia` é parâmetro e não algo que se
    procure no payload: procurar ali devolveria `None` para sempre, e a coluna
    `data` ficaria nula sem erro nenhum.
    """
    n = 0
    for env in linhas:
        # `chamar()` devolve o envelope inteiro numa lista de um elemento
        # (é o caminho do dict sem chave de lista em `_uma_pagina`).
        for m in (env.get("motoristas") or []):
            doc = _t(m.get("cpf") or m.get("documento"))
            if not doc:
                continue
            for d in (m.get("diarias") or []):
                tipo = _t(d.get("tipo"))
                if not tipo:
                    continue
                cur.execute("""
                    INSERT INTO jor_diarias(documento, data, tipo, pais, nome,
                        quantidade, valor_unitario, valor_total, coletado_em,
                        origem)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (documento, data, tipo, pais) DO UPDATE SET
                      nome=EXCLUDED.nome, quantidade=EXCLUDED.quantidade,
                      valor_unitario=EXCLUDED.valor_unitario,
                      valor_total=EXCLUDED.valor_total,
                      coletado_em=EXCLUDED.coletado_em, origem=EXCLUDED.origem
                """, (doc, dia, tipo, _t(d.get("pais")) or "BR",
                      _t(m.get("nome")), _i(d.get("quantidade")),
                      _f(d.get("valor_unitario")), _f(d.get("valor_total")),
                      ts, origem))
                n += 1
    return n


def _grava_eventos(cur, linhas, ts, origem) -> int:
    """As macros. Chave natural (documento, codigo, inicio) — a API não dá id."""
    n = 0
    for r in linhas:
        doc = _t(r.get("driver_document") or r.get("documento"))
        cod = r.get("event_code")
        ini = _dt(r.get("event_start") or r.get("inicio"))
        if not doc or cod is None or not ini:
            continue                       # sem a chave natural não entra
        cur.execute("""
            INSERT INTO jor_eventos(documento, codigo, inicio, nome, evento,
                fim, duracao_min, origem_evento, placa, filial, escala,
                coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (documento, codigo, inicio) DO UPDATE SET
              nome=EXCLUDED.nome, evento=EXCLUDED.evento, fim=EXCLUDED.fim,
              duracao_min=EXCLUDED.duracao_min,
              origem_evento=EXCLUDED.origem_evento, placa=EXCLUDED.placa,
              filial=EXCLUDED.filial, escala=EXCLUDED.escala,
              coletado_em=EXCLUDED.coletado_em, origem=EXCLUDED.origem
        """, (doc, _i(cod), ini, _t(r.get("driver_name")),
              _t(r.get("event_name")), _dt(r.get("event_end")),
              _i(r.get("event_duration")) or None,
              _t(r.get("origin")), _t(r.get("vehicle_plate")),
              _t(r.get("branch")), _t(r.get("work_schedule")), ts, origem))
        n += 1
    return n


def _grava_excecoes(cur, linhas, ts, origem) -> int:
    """As exceções de jornada — a única família SEM CPF.

    A fonte manda `nome_motorista` e mais nada que identifique a pessoa. O nome
    normalizado vai numa coluna à parte, gravado UMA vez aqui: se cada consulta
    normalizasse por conta própria, duas telas acabariam discordando sobre quem
    é a mesma pessoa — que é exatamente o defeito que a chave por CPF das
    outras tabelas existe para evitar.
    """
    n = 0
    for r in linhas:
        ger = _dt(r.get("data_geracao") or r.get("gerada_em"))
        nome = _t(r.get("nome_motorista") or r.get("nome"))
        cod = r.get("codigo_tipo_excecao")
        if not ger or not nome or cod is None:
            continue
        cur.execute("""
            INSERT INTO jor_excecoes(gerada_em, nome, nome_norm, codigo_tipo,
                tipo, veiculo, status, nivel, coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (gerada_em, nome, codigo_tipo) DO UPDATE SET
              nome_norm=EXCLUDED.nome_norm, tipo=EXCLUDED.tipo,
              veiculo=EXCLUDED.veiculo, status=EXCLUDED.status,
              nivel=EXCLUDED.nivel, coletado_em=EXCLUDED.coletado_em,
              origem=EXCLUDED.origem
        """, (ger, nome, normalizar_nome(nome), _i(cod),
              _t(r.get("nome_excecao")), _t(r.get("nome_veiculo")),
              _i(r.get("status_excecao")) if r.get("status_excecao") is not None else None,
              _i(r.get("nivel_excecao")) if r.get("nivel_excecao") is not None else None,
              ts, origem))
        n += 1
    return n


def _grava_anomalias(cur, linhas, ts, origem) -> int:
    """A régua do próprio fornecedor. Chave é o id DELE — o único recurso da
    família em que a RasterJOR dá identidade estável, e é ela que permite ver a
    mesma anomalia mudar de `resolved` sem duplicar."""
    n = 0
    for r in linhas:
        ident = r.get("id")
        if ident is None:
            continue
        cur.execute("""
            INSERT INTO jor_anomalias(id_externo, momento, criada_em, tipo,
                placa, nome, documento, descricao, resolvida, coletado_em,
                origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id_externo) DO UPDATE SET
              momento=EXCLUDED.momento, criada_em=EXCLUDED.criada_em,
              tipo=EXCLUDED.tipo, placa=EXCLUDED.placa, nome=EXCLUDED.nome,
              documento=EXCLUDED.documento, descricao=EXCLUDED.descricao,
              resolvida=EXCLUDED.resolvida, coletado_em=EXCLUDED.coletado_em,
              origem=EXCLUDED.origem
        """, (_i(ident), _dt(r.get("moment")), _dt(r.get("created_at")),
              _i(r.get("type")) if r.get("type") is not None else None,
              _t(r.get("vehicle_plate")), _t(r.get("driver_name")),
              _t(r.get("driver_document")), _t(r.get("description")),
              1 if r.get("resolved") else 0, ts, origem))
        n += 1
    return n


def _grava_veiculos(cur, linhas, ts, origem) -> int:
    """O estado ATUAL da frota que a RasterJOR enxerga. SNAPSHOT por placa.

    A cópia deste mesmo recurso no ERP guardava CADA leitura e chegou a 124.665
    linhas para ~175 veículos — um log que ninguém consulta e que só cresce.
    Aqui a placa é a chave: a linha é sobrescrita e `coletado_em` diz de quando
    é o estado.
    """
    n = 0
    for r in linhas:
        placa = _t(r.get("vehicle_plate") or r.get("placa"))
        if not placa:
            continue
        cur.execute("""
            INSERT INTO jor_veiculos(placa, motorista, ultima_posicao,
                latitude, longitude, evento_atual, evento_duracao,
                coletado_em, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (placa) DO UPDATE SET
              motorista=EXCLUDED.motorista,
              ultima_posicao=EXCLUDED.ultima_posicao,
              latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude,
              evento_atual=EXCLUDED.evento_atual,
              evento_duracao=EXCLUDED.evento_duracao,
              coletado_em=EXCLUDED.coletado_em, origem=EXCLUDED.origem
        """, (placa, _t(r.get("current_associated_driver")),
              _t(r.get("last_position")), _f(r.get("latitude")),
              _f(r.get("longitude")), _t(r.get("actual_event")),
              _t(r.get("actual_event_duration")), ts, origem))
        n += 1
    return n


# A DIÁRIA NÃO ESTÁ AQUI de propósito: o gravador dela precisa saber QUE DIA
# está gravando, e essa informação não vem no payload. Ela tem passagem própria
# (`_passagem_diarias`), e deixá-la fora deste mapa é o que impede alguém de
# chamá-la pelo caminho genérico e gravar o dia errado.
_GRAVA = {"motoristas": _grava_motoristas, "jornadas": _grava_jornadas,
          "inconformidades": _grava_inconformidades,
          "ausencias": _grava_ausencias, "eventos": _grava_eventos,
          "excecoes": _grava_excecoes, "anomalias": _grava_anomalias,
          "veiculos": _grava_veiculos}


def _passagem_diarias(cur, p_de: str, p_ate: str, ts: str) -> tuple[int, int, int]:
    """A diária de cada dia da janela, UMA CHAMADA POR DIA.

    POR QUE UM DIA POR VEZ, e por que isto não é desperdício:

    O endpoint `/diarias/` AGREGA o período pedido. Pedindo 01/01 a 31/01 ele
    responde "fulano: 12 meias e 4 inteiras" — o total do mês, sem dizer em que
    dias elas caíram. Uma chamada por semana custaria sete vezes menos e
    devolveria um número que não dá para pôr em dia nenhum; distribuir o
    agregado pelos dias seria INVENTAR data, e data inventada vira gráfico.

    A auditoria da diária existe para responder "esta diária, deste dia, está
    certa?". Sem o dia, ela volta a ser o que era: uma comparação de totais
    semanais, que é o que a folha já dava.

    Devolve (lidos, gravados, ms) da janela inteira — UMA linha em `jor_carga`
    por passagem, e não uma por dia: a trilha existe para a Saúde ver a coleta,
    e 250 linhas por carga histórica esconderiam as outras.
    """
    d0 = date.fromisoformat(p_de)
    d1 = date.fromisoformat(p_ate)
    lidos = gravados = ms = 0
    dia = d0
    while dia <= d1:
        iso = dia.isoformat()
        linhas, t = cliente.chamar("diarias", de=iso, ate=iso)
        ms += t
        # o envelope traz uma lista de motoristas; "lidos" conta pessoas com
        # diária no dia, que é o número que faz sentido na trilha
        lidos += sum(len(e.get("motoristas") or []) for e in linhas)
        gravados += _grava_diarias(cur, linhas, ts, "api", dia)
        dia += timedelta(days=1)
    return lidos, gravados, ms


# ─────────────────────────────────────────────────────────── coleta da API

def coletar(de: str | None = None, ate: str | None = None,
            recursos: tuple[str, ...] | None = None,
            esquema: str | None = None) -> dict:
    """Uma passagem da coleta. NUNCA levanta: devolve o resultado por recurso.

    A rotina roda desassistida — exceção que sobe some do mundo, enquanto uma
    linha `ok=0` em `jor_carga` é lida pela Saúde na manhã seguinte.
    """
    init_db(esquema)
    hoje = date.today()
    # A API só aceita consulta retroativa: janela que termine hoje volta 400.
    # Cortar aqui evita uma falha diária que o agendador descobriria sozinho.
    ontem = hoje - timedelta(days=1)
    p_ate = min(ate or ontem.isoformat(), ontem.isoformat())
    p_de = de or (ontem - timedelta(days=JANELA_DIAS)).isoformat()
    if p_de > p_ate:
        p_de = p_ate
    ts = _agora()
    saida = {"de": p_de, "ate": p_ate, "recursos": {}, "ok": True, "erro": ""}

    if not cliente.configurado():
        saida["ok"] = False
        saida["erro"] = cliente.o_que_falta()
        with pglocal.get_conn(_esq(esquema)) as cx:
            cur = cx.cursor()
            _trilha(cur, "todos", p_de, p_ate, False, 0, 0, 0, saida["erro"], "api")
            cx.commit()
        return saida

    for recurso in (recursos or cliente.RECURSOS):
        t0 = time.monotonic()
        lidos = gravados = 0
        ok, msg = True, ""
        try:
            if recurso == "diarias":
                # UMA CHAMADA POR DIA — ver `_passagem_diarias`. O caminho é
                # separado porque o gravador precisa saber o dia, e o dia não
                # está no payload.
                with pglocal.get_conn(_esq(esquema)) as cx:
                    cur = cx.cursor()
                    lidos, gravados, ms = _passagem_diarias(cur, p_de, p_ate, ts)
                    _trilha(cur, recurso, p_de, p_ate, True, lidos, gravados,
                            ms, "", "api")
                    cx.commit()
                saida["recursos"][recurso] = {"ok": True, "lidos": lidos,
                                              "gravados": gravados, "erro": ""}
                continue
            # QUEM É CADASTRO SAI DO CATÁLOGO, não de uma lista de nomes aqui:
            # `motoristas` e `veiculos` não aceitam janela, e escrever o nome
            # deles neste `if` foi o que fez a segunda entrar pedindo data.
            cfg = cliente.CATALOGO[recurso]
            janela = ({"de": p_de, "ate": p_ate}
                      if cfg.get("de") and cfg.get("ate") else {})
            linhas, ms = cliente.chamar(recurso, **janela)
            lidos = len(linhas)
            with pglocal.get_conn(_esq(esquema)) as cx:
                cur = cx.cursor()
                gravados = _GRAVA[recurso](cur, linhas, ts, "api")
                _trilha(cur, recurso, p_de, p_ate, True, lidos, gravados, ms, "", "api")
                cx.commit()
        except Exception as exc:                      # noqa: BLE001
            ok = False
            # tipo da exceção, nunca str(exc) cru de rede — pode carregar URL
            # Recusa de negócio (limite de taxa, período inválido) tem
            # mensagem que a pessoa precisa ler; falha de transporte também.
            # O que NÃO pode vazar é `str()` de exceção de rede, que carrega
            # URL — e a URL pode carregar credencial.
            msg = (str(exc) if isinstance(exc, (cliente.RasterIndisponivel,
                                                cliente.RasterRecusou,
                                                cliente.NaoConfigurado))
                   else f"{type(exc).__name__} ao gravar {recurso}")
            log.warning("coleta de jornada falhou em %s: %s", recurso, msg)
            ms = int((time.monotonic() - t0) * 1000)
            try:
                with pglocal.get_conn(_esq(esquema)) as cx:
                    cur = cx.cursor()
                    _trilha(cur, recurso, p_de, p_ate, False, lidos, 0, ms, msg, "api")
                    cx.commit()
            except Exception:                          # noqa: BLE001
                pass                                   # trilha não pode derrubar
            saida["ok"] = False
            saida["erro"] = saida["erro"] or msg
        saida["recursos"][recurso] = {"ok": ok, "lidos": lidos,
                                      "gravados": gravados, "erro": msg}
    return saida


def coletar_agora(esquema: str | None = None) -> dict:
    """SÓ o recurso de tempo real. É a rotina que mantém o painel de TV vivo.

    POR QUE ELA EXISTE SEPARADA da coleta normal, que roda duas vezes ao dia:

    `/vehicles/` é o único recurso que responde AGORA — posições de minutos
    atrás. Todo o resto da API é D-1 por regra do fornecedor, e não ganha nada
    em ser lido de cinco em cinco minutos: seria bater no fornecedor 288 vezes
    por dia para reler o mesmo ontem.

    O contrário também é verdade, e é o que motivou esta função: com a cadência
    de 12 horas o painel de TV mostraria ZERO veículos reportando, porque a
    régua de frescor dele é de 30 minutos. Um painel de tempo real alimentado
    duas vezes ao dia não é um painel desatualizado — é um painel vazio.

    Uma chamada, sem janela (é cadastro + estado), e trilha em `jor_carga` como
    todas as outras: se ela parar, a Saúde vê pelo mesmo caminho.
    """
    init_db(esquema)
    ts = _agora()
    recurso = cliente.RECURSO_TEMPO_REAL
    if not cliente.configurado():
        return {"ok": False, "erro": cliente.o_que_falta(), "gravados": 0}
    t0 = time.monotonic()
    try:
        linhas, ms = cliente.chamar(recurso)
        with pglocal.get_conn(_esq(esquema)) as cx:
            cur = cx.cursor()
            gravados = _GRAVA[recurso](cur, linhas, ts, "api")
            _trilha(cur, recurso, None, None, True, len(linhas), gravados,
                    ms, "", "api")
            cx.commit()
        return {"ok": True, "erro": "", "lidos": len(linhas),
                "gravados": gravados, "ms": ms}
    except Exception as exc:                          # noqa: BLE001
        msg = (str(exc) if isinstance(exc, (cliente.RasterIndisponivel,
                                            cliente.RasterRecusou,
                                            cliente.NaoConfigurado))
               else f"{type(exc).__name__} ao gravar {recurso}")
        log.warning("coleta de tempo real falhou: %s", msg)
        try:
            with pglocal.get_conn(_esq(esquema)) as cx:
                cur = cx.cursor()
                _trilha(cur, recurso, None, None, False, 0, 0,
                        int((time.monotonic() - t0) * 1000), msg, "api")
                cx.commit()
        except Exception:                              # noqa: BLE001
            pass
        return {"ok": False, "erro": msg, "gravados": 0}


# ──────────────────────────────────────────── carga inicial a partir do AVA

_AVA = {
    "motoristas": ("""SELECT cpf AS documento, name AS nome, id AS api_id,
             active AS ativo, branch AS filial, work_schedule AS escala,
             role AS cargo, admission_date AS admissao, base_city AS cidade_base
        FROM sulista.rasterjor_drivers""", None),
    "jornadas": ("""SELECT driver_document, driver_name, branch_name,
             work_schedule_name, report_date AS date, journey_start AS start,
             journey_end AS "end", total_time_minutes, activity_time_minutes,
             driving_time_minutes, stopped_in_journey_minutes,
             meal_time_minutes, rest_time_minutes, repose_time_minutes,
             over_time_minutes, missing_time_minutes,
             missing_repose_time_minutes, activity_over_max_time_minutes,
             journey_type, kilometers_driven
        FROM sulista.rasterjor_productivity_report""", "report_date"),
    "inconformidades": ("""SELECT driver_document, driver_name, plate,
             unconformity_type, unconformity_date, event_start, event_end,
             duration_minutes, speed, observation
        FROM sulista.rasterjor_unconformities""", "unconformity_date"),
    "ausencias": ("""SELECT external_id, cpf, driver_name, absence_type,
             description, observation, start_datetime, end_datetime
        FROM sulista.rasterjor_absences""", "start_datetime"),
}


def carga_ava(recursos: tuple[str, ...] | None = None, lote: int = 5000,
              esquema: str | None = None) -> dict:
    """Copia o histórico de `sulista.rasterjor_*` (AVA) para as tabelas locais.

    Roda uma vez. É dado REAL — 01/01/2025 a 15/04/2026 — que a rotina externa
    trouxe antes de parar, e jogá-lo fora seria perder quinze meses de jornada
    por causa de uma mudança de encanamento.

    Marca `origem='ava'` em tudo: no dia em que os números divergirem da coleta
    própria, é essa coluna que diz de onde cada linha veio.
    """
    from .. import db as ava
    init_db(esquema)
    ts = _agora()
    saida = {"recursos": {}, "ok": True}
    for recurso in (recursos or cliente.RECURSOS):
        sql, dcol = _AVA[recurso]
        t0 = time.monotonic()
        try:
            linhas = ava.query(sql + (f" ORDER BY {dcol}" if dcol else ""))
            gravados = 0
            with pglocal.get_conn(_esq(esquema)) as cx:
                cur = cx.cursor()
                for i in range(0, len(linhas), lote):
                    gravados += _GRAVA[recurso](cur, linhas[i:i+lote], ts, "ava")
                _trilha(cur, recurso, None, None, True, len(linhas), gravados,
                        int((time.monotonic()-t0)*1000),
                        "carga inicial a partir de sulista.rasterjor_*", "ava")
                cx.commit()
            saida["recursos"][recurso] = {"ok": True, "lidos": len(linhas),
                                          "gravados": gravados}
        except Exception as exc:                       # noqa: BLE001
            log.warning("carga_ava falhou em %s: %s", recurso, exc)
            saida["ok"] = False
            saida["recursos"][recurso] = {"ok": False, "lidos": 0,
                                          "gravados": 0,
                                          "erro": f"{type(exc).__name__}"}
    return saida


# ────────────────────────────────────────────────────────────── diagnóstico

def diagnostico(esquema: str | None = None) -> dict:
    """Estado da INGESTÃO — é o que a Saúde do Servidor lê.

    Mede o banco local, não a API: perguntar ao fornecedor se ele respondeu
    custaria uma requisição a cada 5 s de recarga da Saúde.
    """
    d = {"configurado": cliente.configurado(), "falta": cliente.o_que_falta()}
    try:
        r = pglocal.um("""
            SELECT max(data)::date AS ultimo_dado,
                   count(*)::int   AS jornadas
              FROM jor_jornadas""", esquema=_esq(esquema)) or {}
        d["ultimo_dado"] = (r["ultimo_dado"].isoformat()
                            if r.get("ultimo_dado") else None)
        d["jornadas"] = r.get("jornadas") or 0
        c = pglocal.um("""
            SELECT ts, recurso, ok, lidos, gravados, mensagem
              FROM jor_carga ORDER BY id DESC LIMIT 1""",
                       esquema=_esq(esquema))
        d["ultima_carga"] = dict(c) if c else None
        f = pglocal.um("""
            SELECT count(*)::int AS n FROM jor_carga
             WHERE ok = 0 AND ts >= %s""",
                       ((datetime.now() - timedelta(days=2)).isoformat(),),
                       esquema=_esq(esquema)) or {}
        d["falhas_48h"] = f.get("n") or 0
        d["dias_sem_dado"] = ((date.today() - date.fromisoformat(d["ultimo_dado"])).days
                              if d.get("ultimo_dado") else None)
    except Exception as exc:                           # noqa: BLE001
        if pglocal.sem_tabela(exc):
            d["erro"] = "tabelas ausentes — rode scripts/migrar_schema.py"
        else:
            d["erro"] = type(exc).__name__
    return d
