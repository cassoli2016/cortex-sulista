# -*- coding: utf-8 -*-
"""As INSPEÇÕES de verdade — sulco medido no pátio, com data e hodômetro.

O QUE ELAS MUDAM. A curva de desgaste hoje se apoia em 79 pneus com taxa
própria contra 2.299 usando a mediana da frota, e a razão é a fonte: o que
existia eram as medições que vinham de carona numa movimentação (5.500) mais o
instantâneo do dia. `GET /api/v3/tire-inspections/vehicles` é a inspeção como
evento próprio — a pessoa foi ao pátio, mediu os quatro sulcos e a pressão de
cada pneu do veículo, e o registro traz a DATA e o HODÔMETRO.

O HODÔMETRO É O GRANDE GANHO. Com ele a taxa de desgaste vira uma subtração
entre duas leituras do MESMO hodômetro — sem placa, sem engate, sem janela de
365 dias. A derivação de `api/pneus/km.py` continua existindo para o pneu que
não tem duas inspeções, e vira o SEGUNDO CAMINHO para conferir esta.

TRÊS DIFERENÇAS DESTE ENDPOINT PARA O DE MOVIMENTAÇÃO, e cada uma já custou
tempo de alguém em algum lugar:

1. **`pageNumber` começa em ZERO** aqui e em UM nas movimentações. Começar
   errado pula a primeira página inteira — sem erro, e a falta só aparece como
   "esse mês veio menor".
2. **`includeMeasures` é OBRIGATÓRIO** e é ele que traz os sulcos. Sem ele o
   endpoint responde 200 com as inspeções vazias de medida, o que se parece
   exatamente com "não mediram nada".
3. A posição vem como INTEIRO (`tirePositionAtInspection`), não como a sigla
   que as movimentações trazem. Sem tabela de domínio para o inteiro, ele fica
   guardado cru — código sem dicionário não vira rótulo inventado.

IDEMPOTENTE por `(inspeção, pneu)`: repetir a coleta não duplica, e o
`DO UPDATE` deixa uma passada futura preencher campo que hoje falta.
"""
from __future__ import annotations

import calendar
import datetime
import logging

from .. import pglocal
from . import cliente

log = logging.getLogger("cortex.pneus.inspecoes")

ROTA = "inspecoes"

#: Requisições por execução. Fica abaixo da cota observada de propósito: a
#: execução que termina por conta própria deixa a integração saudável; a que
#: termina em 429 deixa a próxima chamada de qualquer outra tela falhando.
ORCAMENTO = 6

PAGINA = 100

#: Até onde recuar. Inspeção de três anos atrás não decide troca nenhuma, e a
#: cota gasta ali é cota que não foi para o recente.
PISO = "2024-01"

#: A MESMA faixa física do hodômetro do histórico. Um vem do processo de
#: movimentação e o outro da inspeção, mas é o mesmo painel do mesmo caminhão —
#: e os mesmos dedos trocados (1 km, 7,3 milhões) aparecem nos dois.
ODO_MIN, ODO_MAX = 1000, 3_000_000


def _mes(d: datetime.date) -> str:
    return d.strftime("%Y-%m")


def _anterior(mes: str) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    return "%04d-%02d" % (a - 1, 12) if m == 1 else "%04d-%02d" % (a, m - 1)


def _limites(mes: str) -> tuple[str, str]:
    a, m = int(mes[:4]), int(mes[5:7])
    return "%s-01" % mes, "%04d-%02d-%02d" % (a, m, calendar.monthrange(a, m)[1])


def _odometro(v):
    """O hodômetro da inspeção, ou None. Fora da faixa física vira NULO, nunca
    km: um hodômetro errado não estraga a taxa de desgaste — ele a estraga em
    SILÊNCIO, com um número plausível."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if ODO_MIN <= v <= ODO_MAX else None


def _placa(insp: dict):
    """A placa do veículo inspecionado.

    `strip` porque ela VEM SUJA — 28 de 478 chegaram com tabulação ou espaço
    nas bordas no endpoint irmão, e sem a limpeza o veículo não casa com o
    cadastro do ERP. Falha calada: vira "sem km".
    """
    v = ((insp.get("vehicle") or {}).get("licensePlate") or "").strip().upper()
    return v or None


def _sulcos(m: dict) -> list | None:
    """Os quatro sulcos, NA ORDEM em que a Prolog os nomeia: interno, meio
    interno, meio externo, externo. A ordem é o que torna o array legível."""
    campos = ("measuredInnerTreadDepth", "measuredMiddleInnerTreadDepth",
              "measuredMiddleOuterTreadDepth", "measuredOuterTreadDepth")
    vs = [m.get(c) for c in campos]
    return vs if any(v is not None for v in vs) else None


def _estado() -> dict:
    try:
        r = pglocal.query(
            "SELECT cursor, registros FROM pne_sync WHERE rota = %s", (ROTA,))
    except Exception:  # noqa: BLE001
        return {"cursor": None, "registros": 0}
    return dict(r[0]) if r else {"cursor": None, "registros": 0}


def _gravar_estado(cursor, registros: int, erro: str | None) -> None:
    agora = datetime.datetime.now(datetime.timezone.utc)
    try:
        pglocal.executar("""
            INSERT INTO pne_sync (rota, cursor, ultima_em, ultimo_ok_em,
                                  registros, ultimo_erro, atualizado_em)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (rota) DO UPDATE SET
                cursor       = COALESCE(EXCLUDED.cursor, pne_sync.cursor),
                ultima_em    = EXCLUDED.ultima_em,
                ultimo_ok_em = COALESCE(EXCLUDED.ultimo_ok_em,
                                        pne_sync.ultimo_ok_em),
                registros    = pne_sync.registros + EXCLUDED.registros,
                ultimo_erro  = EXCLUDED.ultimo_erro,
                atualizado_em = EXCLUDED.atualizado_em""",
            (ROTA, cursor, agora, None if erro else agora, registros, erro,
             agora))
    except Exception:  # noqa: BLE001
        pass


def _gravar_inspecao(cur, insp: dict, perdidos: list) -> int:
    """Grava as medidas de UMA inspeção. Devolve quantas entraram."""
    quando = insp.get("submittedAt")
    ident = str(insp.get("id") or "").strip()
    if not quando or not ident:
        return 0
    quem = ((insp.get("submittedBy") or {}).get("name") or "").strip() or None
    placa = _placa(insp)
    odo = _odometro(insp.get("odometerReading"))
    n = 0

    for m in (insp.get("inspectionMeasures") or []):
        tire = str(m.get("tireId") or "").strip()
        if not tire:
            continue
        cur.execute("SELECT id FROM pne_pneu WHERE prolog_id = %s", (tire,))
        pneu = cur.fetchone()
        if not pneu:
            # PNEU QUE NAO ESTA NO NOSSO BANCO: carcaca que a Prolog ja removeu
            # do cadastro. Criar aqui seria inventar cadastro a partir de uma
            # medida; o registro fica de fora e a contagem diz quantos.
            perdidos.append(tire)
            continue
        sulcos = _sulcos(m)
        if sulcos is None and m.get("measuredPressure") is None:
            continue
        cur.execute("""
            INSERT INTO pne_inspecao
                (pneu_id, medido_em, sulcos_mm, pressao_psi, pressao_rec_psi,
                 placa, posicao, km_veiculo, origem, usuario, prolog_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'prolog',%s,%s)
            ON CONFLICT (origem, prolog_id) DO UPDATE SET
                -- DO UPDATE e nao DO NOTHING: uma passada futura precisa poder
                -- preencher campo que hoje falta, senao o buraco fica para
                -- sempre e so as inspecoes novas ficam completas.
                km_veiculo = COALESCE(EXCLUDED.km_veiculo,
                                      pne_inspecao.km_veiculo),
                placa      = COALESCE(EXCLUDED.placa, pne_inspecao.placa),
                posicao    = COALESCE(EXCLUDED.posicao, pne_inspecao.posicao)""",
            (pneu["id"], quando, sulcos, m.get("measuredPressure"),
             m.get("recommendedPressure"), placa,
             # A POSICAO VEM COMO INTEIRO aqui (a sigla so existe no endpoint
             # de movimentacao). Sem dicionario para o inteiro, ele fica cru —
             # codigo sem tabela de dominio nao vira rotulo inventado.
             (str(m["tirePositionAtInspection"])
              if m.get("tirePositionAtInspection") is not None else None),
             odo, quem, "insp:%s:%s" % (ident, tire)))
        n += 1
    return n


def _mes_completo(cur, cli, mes: str, orcamento: int, perdidos: list):
    """Varre um mês. Devolve (requisições gastas, medidas novas, terminou)."""
    de, ate = _limites(mes)
    gastas = novas = 0
    # PAGINA ZERO. Este endpoint comeca em zero e o de movimentacao em um —
    # comecar errado pula a primeira pagina inteira, sem erro nenhum.
    pagina = 0
    while gastas < orcamento:
        r = cli.get("/api/v3/tire-inspections/vehicles", {
            "branchOfficesId": cliente.filiais_configuradas(),
            "startDate": de, "endDate": ate,
            # OBRIGATORIO, e e ele que traz os sulcos: sem ele o endpoint
            # responde 200 com inspecoes vazias de medida, o que se parece
            # exatamente com "nao mediram nada".
            "includeMeasures": "true",
            "pageSize": PAGINA, "pageNumber": pagina})
        gastas += 1
        for insp in (r.get("content") or []):
            novas += _gravar_inspecao(cur, insp, perdidos)
        if r.get("lastPage") or r.get("empty"):
            return gastas, novas, True
        pagina += 1
    return gastas, novas, False


def sincronizar(orcamento: int = ORCAMENTO) -> dict:
    """Avança as inspeções o quanto a cota permitir. NUNCA levanta."""
    if not cliente.pronto():
        return {"ok": False, "erro": "integração da Prolog não configurada"}

    cli = cliente.Cliente()
    hoje = datetime.date.today()
    cursor = _estado().get("cursor")
    gastas = novas = 0
    meses: list = []
    perdidos: list = []
    erro = None

    try:
        with pglocal.get_conn() as conn, conn.cursor() as cur:
            # O MES CORRENTE SEMPRE: ele ainda recebe inspecao, e um cursor que
            # so anda para tras nunca voltaria para busca-lo.
            g, n, fim = _mes_completo(cur, cli, _mes(hoje), orcamento, perdidos)
            gastas += g
            novas += n
            meses.append({"mes": _mes(hoje), "completo": fim, "medidas": n})

            alvo = cursor or _mes(hoje)
            while gastas < orcamento and alvo > PISO:
                alvo = _anterior(alvo)
                g, n, fim = _mes_completo(cur, cli, alvo, orcamento - gastas,
                                          perdidos)
                gastas += g
                novas += n
                meses.append({"mes": alvo, "completo": fim, "medidas": n})
                if not fim:
                    # ORCAMENTO ACABOU NO MEIO DO MES: nao avanca o cursor. A
                    # proxima execucao refaz o mes inteiro, e refazer e barato
                    # porque tudo entra por chave natural.
                    break
                cursor = alvo
    except Exception as exc:  # noqa: BLE001
        erro = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        log.warning("sincronismo das inspecoes parou: %s", erro)

    _gravar_estado(cursor, novas, erro)
    return {"ok": erro is None, "erro": erro, "requisicoes": gastas,
            "medidas": novas, "cursor": cursor, "meses": meses, "piso": PISO,
            # SE DECLARA: medida de pneu que nao existe no nosso banco e sinal
            # de que a semeadura ficou para tras, nao ruido.
            "pneus_nao_encontrados": len(set(perdidos))}
