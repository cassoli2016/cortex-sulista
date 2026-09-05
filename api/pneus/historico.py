# -*- coding: utf-8 -*-
"""O histórico de movimentação de pneu, da Prolog para o banco da casa.

É a parte que SÓ a Prolog tem. O instantâneo local dá o estado de hoje — a
semeadura já o traz sem gastar requisição —, mas a história de como cada pneu
chegou até aqui está em `/api/v3/tire-relocations`, e é ela que responde as
perguntas que decidem dinheiro: quanto esta carcaça rodou em cada vida, quanto
custou cada recapagem, quantos pneus morrem cedo e em qual veículo.

5.013 dos 8.572 já estão sucateados. Sem esta coleta eles são uma lápide sem
inscrição.

COMO A COLETA ANDA, e por que mês a mês PARA TRÁS. A cota da Prolog é de cerca
de dez requisições por janela, então nenhuma varredura "de uma vez" existe
aqui. A coleta caminha por MÊS, do mais recente para o mais antigo:

- o mês corrente é sempre revisitado, porque ele ainda recebe movimento;
- depois ela recua um mês por vez enquanto houver orçamento de requisições, e
  grava até onde chegou.

Isso entrega os 12 meses recentes primeiro — que é o que a análise de CPK e
desgaste precisa — e deixa a arqueologia chegar sozinha, sem lógica de fase
nenhuma: caminhar para trás já faz o recente vir antes. Medido: agosto/2026
teve 271 processos, então doze meses são ~33 páginas de 100, umas cinco
execuções.

O QUE ENTRA DE CADA MOVIMENTO. Um processo da Prolog carrega VÁRIOS pneus
(o exemplo real trouxe 11 num só), e cada pneu vira:

- um `pne_evento`, com a origem e o destino crus guardados junto — o mapa para
  o nosso vocabulário é enumerável (o enum deles tem quatro valores), mas
  guardar o par cru é o que permite descobrir depois que erramos o mapa;
- uma `pne_inspecao` com os QUATRO sulcos e a pressão daquele instante, que é
  o que constrói a curva de desgaste;
- o custo e a banda da recapagem em `pne_vida`, quando o movimento traz
  serviço com `introduceNewTireLifeCycle`;
- a MEDIDA do pneu em `pne_modelo` (`tireSizeFormatted`), que o instantâneo
  não traz e que estava vazia nos 8.572.
"""
from __future__ import annotations

import calendar
import datetime
import logging

from .. import pglocal
from . import cliente

log = logging.getLogger("cortex.pneus.historico")

ROTA = "relocations"

#: Requisições por execução. Fica ABAIXO da cota observada de propósito: a
#: execução que termina por conta própria deixa a integração saudável; a que
#: termina em 429 deixa a próxima chamada de qualquer outra tela falhando.
ORCAMENTO = 8

#: Teto da página. É o mesmo limite dos pneus.
PAGINA = 100

#: Até onde recuar. Não é palpite: pneu com mais de dez anos de história não
#: decide compra nenhuma, e a cota gasta ali é cota que não foi para o recente.
#: Quem quiser mais funda o piso — a coleta continua de onde parou.
PISO = "2016-01"


def _mes(d: datetime.date) -> str:
    return d.strftime("%Y-%m")


def _anterior(mes: str) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    return "%04d-%02d" % (a - 1, 12) if m == 1 else "%04d-%02d" % (a, m - 1)


def _limites(mes: str) -> tuple[str, str]:
    a, m = int(mes[:4]), int(mes[5:7])
    return "%s-01" % mes, "%04d-%02d-%02d" % (a, m, calendar.monthrange(a, m)[1])


#: `source` e `destination` da Prolog: enum FECHADO de quatro valores
#: (INVENTORY, ANALYSIS, INSTALLED, DISPOSAL), lido do spec. Como é fechado, o
#: mapa abaixo cobre tudo — não há caso "outro" para adivinhar.
#:
#: A ORDEM IMPORTA. Recapagem vence tudo porque ela é a que abre vida nova, e o
#: par de estados dela (ANALYSIS -> INVENTORY) é indistinguível de uma simples
#: volta ao estoque. Transferência vem depois, porque mudar de filial é o
#: assunto do movimento mesmo quando o estado não muda.
def _tipo(rel: dict, proc: dict) -> str:
    servicos = rel.get("tireServices") or []
    if any(s.get("introduceNewTireLifeCycle") for s in servicos):
        return "retorno_recapagem"
    de = ((proc.get("fromBranchOffice") or {}).get("id"))
    para = ((proc.get("toBranchOffice") or {}).get("id"))
    if de is not None and para is not None and de != para:
        return "transferencia"
    origem = (rel.get("source") or "").upper()
    destino = (rel.get("destination") or "").upper()
    if destino == "INSTALLED":
        return "instalacao"
    if origem == "INSTALLED":
        return "remocao"
    if destino == "DISPOSAL":
        return "sucata"
    if origem == "DISPOSAL":
        return "restauracao"
    return "inventario"


#: Faixa física do hodômetro de um caminhão. Medido na página de 100 processos
#: (05/09/2026): 31 de 478 movimentos vinham fora dela — valores 1, 134 e
#: 7.359.990. Nenhum dos três é caminhão; são o campo em branco preenchido no
#: susto e o dedo no zero. Fora da faixa vira NULO, nunca km.
ODO_MIN, ODO_MAX = 1000, 3_000_000


def _odometro(proc: dict):
    """O hodômetro do processo, ou None. É ele que dá o km da VIDA do pneu — a
    diferença entre a instalação e a remoção — e por isso ele não pode virar
    zero nem número absurdo: os dois estragam o CPK em silêncio."""
    v = proc.get("odometerReading")
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if ODO_MIN <= v <= ODO_MAX else None


def _placa(proc: dict):
    """A placa do veículo do processo.

    VEM SUJA: 28 das 478 chegaram com tabulação ou espaço nas bordas
    (`'	FZS5B14'`, `'STK5C17	'`). Sem o `strip` o cruzamento com o cadastro
    do ERP falha nessas — e falha em silêncio, virando "veículo sem km".
    """
    v = ((proc.get("vehicle") or {}).get("licensePlate") or "").strip().upper()
    return v or None


def _sulcos(rel: dict) -> list | None:
    """Os quatro sulcos, NA ORDEM em que a Prolog os nomeia: interno, meio
    interno, meio externo, externo. A ordem é o que torna o array legível — sem
    ela seriam quatro números soltos."""
    campos = ("innerTreadDepth", "middleInnerTreadDepth",
              "middleOuterTreadDepth", "outerTreadDepth")
    vs = [rel.get(c) for c in campos]
    return vs if any(v is not None for v in vs) else None


def _estado() -> dict:
    try:
        r = pglocal.query(
            "SELECT cursor, registros FROM pne_sync WHERE rota = %s", (ROTA,))
    except Exception:  # noqa: BLE001
        return {"cursor": None, "registros": 0}
    return dict(r[0]) if r else {"cursor": None, "registros": 0}


def _gravar_estado(cursor: str | None, registros: int, erro: str | None) -> None:
    # O "ultimo OK" so anda quando a execucao terminou sem erro. Decidido em
    # Python e nao num CASE dentro do SQL: com o parametro nu o psycopg nao tem
    # tipo para inferir, e o erro que ele devolve nao aponta para ca.
    agora = datetime.datetime.now(datetime.timezone.utc)
    pglocal.executar("""
        INSERT INTO pne_sync (rota, cursor, ultima_em, ultimo_ok_em,
                              registros, ultimo_erro, atualizado_em)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (rota) DO UPDATE SET
            cursor       = COALESCE(EXCLUDED.cursor, pne_sync.cursor),
            ultima_em    = EXCLUDED.ultima_em,
            ultimo_ok_em = COALESCE(EXCLUDED.ultimo_ok_em, pne_sync.ultimo_ok_em),
            registros    = pne_sync.registros + EXCLUDED.registros,
            ultimo_erro  = EXCLUDED.ultimo_erro,
            atualizado_em = EXCLUDED.atualizado_em""",
        (ROTA, cursor, agora, None if erro else agora, registros, erro, agora))


def _gravar_processo(cur, proc: dict, perdidos: list,
                     atualizados: list) -> int:
    """Grava os pneus de UM processo. Devolve quantos eventos entraram.

    `perdidos` recebe os `tireId` que nao existem no nosso banco. Eles NAO
    somem em silencio: campo ausente em conferidor vira achado, e um numero
    alto aqui significa que a semeadura ficou para tras da movimentacao.
    """
    quando = proc.get("submittedAt")
    quem = ((proc.get("submittedBy") or {}).get("name") or "").strip() or None
    novos = 0

    for rel in (proc.get("tireRelocations") or []):
        tire = str(rel.get("tireId") or "").strip()
        rel_id = str(rel.get("id") or "").strip()
        if not tire or not rel_id:
            continue

        cur.execute("SELECT id, modelo_id FROM pne_pneu WHERE prolog_id = %s",
                    (tire,))
        pneu = cur.fetchone()
        if not pneu:
            # PNEU QUE NAO ESTA NO NOSSO BANCO. Acontece com carcaca que a
            # Prolog ja removeu do cadastro: o movimento existe, o pneu nao.
            # Criar a carcaca aqui com o pouco que o movimento traz seria
            # inventar cadastro; o evento fica de fora e a contagem diz quantos.
            perdidos.append(tire)
            continue
        pneu_id = pneu["id"]

        # A MEDIDA, que o instantaneo nao traz e que estava vazia nos 8.572.
        #
        # NAO se preenche a medida no registro generico que a semeadura criou.
        # Tentei assim e deu UniqueViolation: o generico (marca, modelo, '')
        # vira (marca, modelo, '295/80 R22.5') e colide com o registro que ja
        # existe com essa medida. Pior, a semeadura seguinte recriaria o
        # generico, e os dois ficariam brigando pela mesma linha a cada rodada.
        #
        # O certo e o oposto: a medida CRIA (ou acha) o modelo de verdade, e o
        # pneu passa a apontar para ele. O generico fica para tras, sem pneus,
        # e some do catalogo util sozinho.
        medida = (rel.get("tireSizeFormatted") or "").strip()
        if medida and pneu["modelo_id"]:
            cur.execute("SELECT marca, modelo, desenho, medida FROM pne_modelo "
                        "WHERE id = %s", (pneu["modelo_id"],))
            m = cur.fetchone()
            if m and (m["medida"] or "") != medida:
                cur.execute("""
                    INSERT INTO pne_modelo (marca, modelo, medida, desenho,
                                            origem)
                    VALUES (%s,%s,%s,%s,'prolog')
                    ON CONFLICT (marca, modelo, coalesce(medida,''),
                                 coalesce(desenho,''))
                    DO UPDATE SET marca = EXCLUDED.marca
                    -- A COLETA NAO SOBRESCREVE O QUE A CASA CRIOU.
                    WHERE pne_modelo.origem <> 'cortex'
                    RETURNING id""",
                    (m["marca"], m["modelo"], medida, m["desenho"]))
                cur.execute("UPDATE pne_pneu SET modelo_id = %s WHERE id = %s",
                            (cur.fetchone()["id"], pneu_id))

        # PLACA, POSICAO E HODOMETRO. Estavam no payload desde sempre e a casa
        # nao lia: as tres colunas ficaram 100% vazias nos 2.497 eventos
        # importados, e sem hodometro nao ha km de vida — que e o denominador
        # do CPK. E a licao da Gobrax outra vez (14 indicadores, 3 lidos): ler
        # a resposta INTEIRA do fornecedor uma vez custa dez minutos.
        #
        # POSICAO SO EXISTE NA INSTALACAO, e isso nao e lacuna: medido, ela vem
        # em 100% dos movimentos com destino INSTALLED e em 0% dos outros —
        # pneu que vai para o estoque nao tem posicao em eixo nenhum.
        cur.execute("""
            INSERT INTO pne_evento
                (pneu_id, tipo, ocorrido_em, vida, observacao, origem,
                 usuario, prolog_id, placa, posicao, km_veiculo)
            VALUES (%s,%s,%s,%s,%s,'prolog',%s,%s,%s,%s,%s)
            ON CONFLICT (origem, prolog_id) DO UPDATE SET
                -- DO UPDATE, e nao DO NOTHING, de proposito: os eventos ja
                -- coletados precisam RECEBER os campos novos na proxima volta.
                -- Com DO NOTHING eles ficariam vazios para sempre e so os
                -- futuros teriam km — um buraco que ninguem veria.
                placa      = COALESCE(EXCLUDED.placa,      pne_evento.placa),
                posicao    = COALESCE(EXCLUDED.posicao,    pne_evento.posicao),
                km_veiculo = COALESCE(EXCLUDED.km_veiculo, pne_evento.km_veiculo)
            RETURNING (xmax = 0) AS inserido""",
            (pneu_id, _tipo(rel, proc), quando,
             rel.get("tireLifeCycleAtRelocation"),
             # O PAR CRU vai junto: o mapa acima e nosso e pode estar errado, e
             # sem o original nao ha como descobrir depois.
             "%s -> %s" % (rel.get("source"), rel.get("destination")),
             quem, rel_id, _placa(proc),
             (rel.get("tirePositionDestinationNomenclature") or "").strip() or None,
             _odometro(proc)))
        # NOVO x ATUALIZADO. Com `DO UPDATE` o `rowcount` e 1 nos dois casos, e
        # o contador de "eventos novos" passaria a somar tambem o retrabalho de
        # backfill — a coleta pareceria estar achando historia nova quando so
        # esta preenchendo coluna. `xmax = 0` distingue INSERT de UPDATE.
        linha = cur.fetchone()
        if linha and linha["inserido"]:
            novos += 1
        else:
            atualizados[0] += 1

        sulcos = _sulcos(rel)
        if sulcos or rel.get("pressure") is not None:
            # A PLACA E A POSICAO VAO JUNTO. Sem elas a medicao e um sulco
            # solto no tempo: para virar TAXA DE DESGASTE ela precisa saber em
            # que veiculo o pneu estava, porque e do veiculo que sai o km
            # rodado entre duas medicoes. Sem a placa, 5.500 leituras de patio
            # — as unicas com data de verdade — ficavam inuteis para a curva.
            #
            # DO UPDATE pela mesma razao do evento: as ja gravadas precisam
            # RECEBER os campos na proxima volta, senao so as futuras teriam.
            cur.execute("""
                INSERT INTO pne_inspecao
                    (pneu_id, medido_em, sulcos_mm, pressao_psi, origem,
                     usuario, prolog_id, placa, posicao)
                VALUES (%s,%s,%s,%s,'prolog',%s,%s,%s,%s)
                ON CONFLICT (origem, prolog_id) DO UPDATE SET
                    placa   = COALESCE(EXCLUDED.placa,   pne_inspecao.placa),
                    posicao = COALESCE(EXCLUDED.posicao, pne_inspecao.posicao)""",
                (pneu_id, quando, sulcos, rel.get("pressure"), quem,
                 "rel:%s" % rel_id, _placa(proc),
                 (rel.get("tirePositionDestinationNomenclature") or "").strip()
                 or None))

        # RECAPAGEM: custo e banda entram na VIDA que ela abre.
        for s in (rel.get("tireServices") or []):
            if not s.get("introduceNewTireLifeCycle"):
                continue
            vida = s.get("tireLifeCycleAtService")
            if vida is None:
                continue
            cur.execute("""
                INSERT INTO pne_vida (pneu_id, numero, custo, banda, recapadora)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (pneu_id, numero) DO UPDATE SET
                    custo      = COALESCE(EXCLUDED.custo, pne_vida.custo),
                    banda      = COALESCE(EXCLUDED.banda, pne_vida.banda),
                    recapadora = COALESCE(EXCLUDED.recapadora, pne_vida.recapadora)
                -- A COLETA NAO SOBRESCREVE O QUE A CASA CRIOU.
                WHERE pne_vida.origem <> 'cortex'""",
                (pneu_id, int(vida) + 1, s.get("tireServiceCost"),
                 s.get("treadModelName"), s.get("treadMakeName")))
    return novos


def _mes_completo(cur, cli, mes: str, orcamento: int, perdidos: list,
                  atualizados: list):
    """Varre um mês. Devolve (requisições gastas, eventos novos, terminou)."""
    de, ate = _limites(mes)
    gastas = novos = 0
    pagina = 1
    while gastas < orcamento:
        r = cli.get("/api/v3/tire-relocations", {
            "branchOfficesId": cliente.filiais_configuradas(),
            "startDate": de, "endDate": ate,
            "pageSize": PAGINA, "pageNumber": pagina})
        gastas += 1
        for proc in (r.get("content") or []):
            novos += _gravar_processo(cur, proc, perdidos, atualizados)
        if r.get("lastPage") or r.get("empty"):
            return gastas, novos, True
        pagina += 1
    return gastas, novos, False


def sincronizar(orcamento: int = ORCAMENTO) -> dict:
    """Avança o histórico o quanto a cota permitir. NUNCA levanta.

    Falha de rede ou cota estourada não é defeito nosso e não pode derrubar a
    tarefa: ela se registra em `pne_sync.ultimo_erro` e a próxima execução
    continua de onde parou.
    """
    if not cliente.pronto():
        return {"ok": False, "erro": "integração da Prolog não configurada"}

    cli = cliente.Cliente()
    hoje = datetime.date.today()
    est = _estado()
    cursor = est.get("cursor")
    gastas = novos = 0
    meses = []
    perdidos: list = []
    # LISTA DE UM ELEMENTO como contador compartilhado: `_gravar_processo` roda
    # por processo e precisa somar num lugar so, sem devolver tupla por todas
    # as camadas.
    atualizados: list = [0]
    erro = None

    try:
        with pglocal.get_conn() as conn, conn.cursor() as cur:
            # O MES CORRENTE SEMPRE: ele ainda recebe movimento, e um cursor
            # que so anda para tras nunca voltaria para busca-lo.
            g, n, fim = _mes_completo(cur, cli, _mes(hoje),
                                      orcamento - gastas, perdidos, atualizados)
            gastas += g
            novos += n
            meses.append({"mes": _mes(hoje), "completo": fim, "eventos": n})

            alvo = cursor or _mes(hoje)
            while gastas < orcamento and alvo > PISO:
                alvo = _anterior(alvo)
                g, n, fim = _mes_completo(cur, cli, alvo, orcamento - gastas,
                                          perdidos, atualizados)
                gastas += g
                novos += n
                meses.append({"mes": alvo, "completo": fim, "eventos": n})
                if not fim:
                    # ORCAMENTO ACABOU NO MEIO DO MES: nao avanca o cursor. A
                    # proxima execucao refaz o mes inteiro, e refazer e barato
                    # porque tudo entra por ON CONFLICT DO NOTHING.
                    break
                cursor = alvo
    except Exception as exc:  # noqa: BLE001
        erro = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        log.warning("sincronismo do historico parou: %s", erro)

    _gravar_estado(cursor, novos, erro)
    return {"ok": erro is None, "erro": erro, "requisicoes": gastas,
            "eventos_novos": novos, "eventos_atualizados": atualizados[0],
            "cursor": cursor, "meses": meses,
            "piso": PISO,
            # SE DECLARA: pneu do movimento que nao existe no nosso banco e
            # sinal de que a semeadura ficou para tras, nao ruido.
            "pneus_nao_encontrados": len(set(perdidos))}
