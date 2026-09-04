# -*- coding: utf-8 -*-
"""A Prolog alimentando o banco da casa, até o dia em que ela for desligada.

POR QUE ESTE MÓDULO EXISTE. O controle de pneu vive na Prolog e o CÓRTEX lia
uma FOTOGRAFIA: `data/pneus/pneus-atual.json`, sobrescrito a cada coleta. Foto
não tem história — 5.013 dos 8.572 pneus já estão sucateados e o arquivo não
diz quando, de qual veículo saíram nem quanto rodaram. A decisão foi construir
o módulo próprio; enquanto ele não substitui a Prolog, ela ABASTECE o nosso
banco todo dia, e no desligamento a memória já está aqui.

O ATALHO QUE ESTE MÓDULO APROVEITA. Os 8.572 pneus JÁ ESTÃO no arquivo local.
Semear o banco a partir dele custa ZERO requisição — e a cota da Prolog é de
cerca de dez por janela, com uma volta completa custando 86. Cada requisição
gasta com o que já temos é uma requisição a menos para o que só ela tem: o
histórico de movimentação. Por isso a semeadura vem primeiro e é de graça.

O QUE A SEMEADURA NÃO FAZ, e é bom dizer: ela não inventa história. Do
instantâneo sai o ESTADO de hoje — a carcaça, as vidas, onde o pneu está
montado e a última medição de sulco e pressão. Os eventos que levaram até aqui
estão na Prolog (`/api/v3/tire-relocations`) e vêm depois, por janela de data.
Um `pne_evento` fabricado a partir da foto seria história inventada com cara de
registro, que é pior que lacuna declarada.

IDEMPOTÊNCIA. Tudo entra por `ON CONFLICT … DO UPDATE` sobre chave natural
(`prolog_id`), porque a semeadura vai rodar muitas vezes — a cada coleta nova —
e uma segunda passada não pode dobrar carcaça, vida nem inspeção.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import pglocal
from . import servico

log = logging.getLogger("cortex.pneus.replica")

#: O estado da Prolog traduzido para o nosso vocabulário. Traduzir na ENTRADA e
#: não na leitura: se cada tela traduzir, cada tela erra de um jeito diferente,
#: e o dia em que a Prolog sumir o vocabulário dela fica encravado no código.
#:
#: `ANALYSIS` é o pneu que saiu do veículo e espera decisão — recapar, consertar
#: ou sucatear. Não é "rodando" nem "estoque", e juntá-lo a qualquer um dos dois
#: some com a fila que a operação precisa enxergar.
STATUS = {
    "INSTALLED": "rodando",
    "INVENTORY": "estoque",
    "ANALYSIS": "analise",
    "DISPOSAL": "sucata",
    "WASTE": "sucata",
    "RECAPPING": "recapagem",
    "REPAIR": "conserto",
}


def _n(v):
    """Número ou None. Zero vindo de campo vazio é a mentira mais comum aqui:
    'rodou 0 km' e 'não sabemos quanto rodou' decidem coisas opostas."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f != 0 else None


def _modelo_id(cur, p: dict) -> int | None:
    """A linha do catálogo para este pneu, criando se ainda não houver.

    MEDIDA VEM VAZIA e isso não é descuido nosso: no instantâneo ela está em
    branco nos 8.572, porque mora noutro endpoint da Prolog. A linha nasce sem
    medida e a sincronização a preenche depois — o que NÃO se faz é inventar
    uma medida para a chave ficar bonita.
    """
    marca = (p.get("marca") or "").strip() or None
    modelo = (p.get("modelo") or "").strip() or None
    if not marca and not modelo:
        return None
    cur.execute("""
        INSERT INTO pne_modelo (marca, modelo, medida, desenho, direcional)
        VALUES (%s, %s, %s, %s, %s)
        -- A CHAVE E SOBRE A EXPRESSAO, com o vazio normalizado: num indice
        -- unico NULL e sempre diferente de NULL, e como `medida` vem vazia
        -- nos 8.572, a chave crua nunca casava e o catalogo DOBRAVA a cada
        -- passada (8.572 -> 17.144, medido).
        ON CONFLICT (marca, modelo, coalesce(medida, ''), coalesce(desenho, ''))
        DO UPDATE
           SET direcional = COALESCE(EXCLUDED.direcional, pne_modelo.direcional)
        RETURNING id""",
        (marca or "(sem marca)", modelo or "(sem modelo)",
         (p.get("medida") or "").strip() or None,
         (p.get("desenho") or "").strip() or None,
         p.get("direcional")))
    return cur.fetchone()["id"]


def semear(limite: int | None = None) -> dict:
    """Traz o instantâneo local para o banco. Não gasta cota da Prolog.

    Devolve o que fez, para a Saúde e a tela poderem DIZER de quando é o
    retrato — número velho que se anuncia velho decide melhor que número
    fresco que não existe.
    """
    inst = servico.obter()
    pneus = inst.get("pneus") or []
    if limite:
        pneus = pneus[:limite]
    if not pneus:
        return {"ok": False, "erro": "nenhum instantâneo local para semear",
                "pneus": 0}

    colhido = inst.get("atualizado_em") or inst.get("coleta", {}).get("em")
    novos = atualizados = vidas = inspecoes = 0

    with pglocal.get_conn() as conn, conn.cursor() as cur:
        for p in pneus:
            pid_prolog = str(p.get("id") or "").strip()
            if not pid_prolog:
                continue
            modelo_id = _modelo_id(cur, p)
            placa = (p.get("placa") or "").strip().upper() or None
            status = STATUS.get(p.get("status") or "", "estoque")

            cur.execute("""
                INSERT INTO pne_pneu
                    (numero_fogo, serie, dot, modelo_id, filial, status,
                     vida_atual, placa_atual, posicao_atual, custo_aquisicao,
                     prolog_id, atualizado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (prolog_id) DO UPDATE SET
                    numero_fogo   = EXCLUDED.numero_fogo,
                    serie         = EXCLUDED.serie,
                    dot           = EXCLUDED.dot,
                    modelo_id     = COALESCE(EXCLUDED.modelo_id, pne_pneu.modelo_id),
                    filial        = EXCLUDED.filial,
                    status        = EXCLUDED.status,
                    vida_atual    = EXCLUDED.vida_atual,
                    placa_atual   = EXCLUDED.placa_atual,
                    posicao_atual = EXCLUDED.posicao_atual,
                    custo_aquisicao = COALESCE(EXCLUDED.custo_aquisicao,
                                               pne_pneu.custo_aquisicao),
                    atualizado_em = now()
                RETURNING id, (xmax = 0) AS inserido""",
                (p.get("frota") or None, p.get("serie") or None,
                 p.get("dot") or None, modelo_id, p.get("filial") or None,
                 status, int(p.get("vida") or 0), placa,
                 (p.get("posicao") or "").strip() or None,
                 _n(p.get("custo_compra")), pid_prolog))
            linha = cur.fetchone()
            pneu_id = linha["id"]
            if linha["inserido"]:
                novos += 1
            else:
                atualizados += 1

            # AS VIDAS. `cpk_por_vida` é onde o km realmente está: o campo
            # `previousTotalKilometersDriven` que o nome sugere vem VAZIO nos
            # 8.572, e o km por vida vem preenchido em 90% dos que rodam.
            for v in (p.get("cpk_por_vida") or []):
                numero = v.get("vida")
                if numero is None:
                    continue
                cur.execute("""
                    INSERT INTO pne_vida (pneu_id, numero, km)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (pneu_id, numero) DO UPDATE
                       SET km = COALESCE(EXCLUDED.km, pne_vida.km)""",
                    (pneu_id, int(numero), _n(v.get("km"))))
                vidas += 1

            # A MEDIÇÃO DE HOJE vira uma inspeção carimbada com a data da
            # COLETA, não com `now()`: o sulco foi medido no pátio antes disso,
            # e carimbar a hora da importação faria a série de desgaste ter
            # degraus onde só houve importação.
            sulcos = [s for s in (p.get("sulcos") or []) if s is not None]
            pressao = _n(p.get("pressao"))
            if (sulcos or pressao) and colhido:
                cur.execute("""
                    INSERT INTO pne_inspecao
                        (pneu_id, medido_em, sulcos_mm, pressao_psi,
                         pressao_rec_psi, placa, posicao, origem, prolog_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'prolog',%s)
                    ON CONFLICT (origem, prolog_id) DO NOTHING""",
                    (pneu_id, colhido, sulcos or None, pressao,
                     _n(p.get("pressao_rec")), placa,
                     (p.get("posicao") or "").strip() or None,
                     f"snap:{pid_prolog}:{colhido}"))
                inspecoes += cur.rowcount

            if placa:
                cur.execute("""
                    INSERT INTO pne_veiculo (placa, filial, atualizado_em)
                    VALUES (%s,%s, now())
                    ON CONFLICT (placa) DO UPDATE
                       SET filial = COALESCE(EXCLUDED.filial, pne_veiculo.filial),
                           atualizado_em = now()""",
                    (placa, p.get("filial") or None))

        cur.execute("""
            INSERT INTO pne_sync (rota, ultima_em, ultimo_ok_em, registros,
                                  ultimo_erro, atualizado_em)
            VALUES ('semeadura:instantaneo', now(), now(), %s, NULL, now())
            ON CONFLICT (rota) DO UPDATE SET
                ultima_em = now(), ultimo_ok_em = now(),
                registros = EXCLUDED.registros, ultimo_erro = NULL,
                atualizado_em = now()""", (len(pneus),))

    return {"ok": True, "pneus": len(pneus), "novos": novos,
            "atualizados": atualizados, "vidas": vidas,
            "inspecoes": inspecoes, "colhido_em": colhido,
            "fonte": "instantâneo local — nenhuma requisição à Prolog"}


def estado() -> dict:
    """O que já está no banco da casa. A tela e a Saúde leem daqui."""
    try:
        p = pglocal.query("""
            SELECT count(*)::int AS pneus,
                   sum(CASE WHEN status='rodando' THEN 1 ELSE 0 END)::int AS rodando,
                   sum(CASE WHEN status='sucata'  THEN 1 ELSE 0 END)::int AS sucata,
                   max(atualizado_em) AS atualizado_em
            FROM pne_pneu""")[0]
        ev = pglocal.query("""
            SELECT count(*)::int AS eventos, min(ocorrido_em) AS mais_antigo,
                   max(ocorrido_em) AS mais_novo
            FROM pne_evento""")[0]
        sync = pglocal.query(
            "SELECT rota, ultima_em, ultimo_ok_em, registros, ultimo_erro "
            "FROM pne_sync ORDER BY rota")
    except Exception as exc:  # noqa: BLE001
        log.warning("estado da replica falhou: %s", type(exc).__name__)
        return {"erro": "não foi possível ler o banco da casa"}
    return {**p, **ev, "sync": [dict(s) for s in sync],
            "agora": datetime.now(timezone.utc).isoformat()}
