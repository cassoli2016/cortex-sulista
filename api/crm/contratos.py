"""Contratos — vigência, reajuste e a tabela de preço por lane.

NÃO EXISTE COLUNA DE STATUS. "Vigente", "vence em 40 dias" e "vencido" saem de
`inicio`, `fim` e da data de hoje; o único fato gravado é `cancelado_em`,
porque rescisão é um EVENTO e não passagem do tempo. É a mesma regra do atraso
de ação na Gestão e da situação da conta no CRM, e o custo de errá-la aqui é
específico: um contrato que renova sozinho por inércia enquanto a tela diz
"vigente" porque alguém marcou isso há dois anos.

O REAJUSTE segue o mesmo princípio. `mes_reajuste` + `ultimo_reajuste`
respondem "o reajuste deste ciclo já saiu?" sem gravar a resposta — e reajuste
esquecido é o dinheiro que fica na mesa sem ninguém ver, que é exatamente o
tipo de coisa que só aparece quando alguém pergunta.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import pglocal
from . import oportunidades as op
from . import precificacao
from .comum import (DadoInvalido, INDICES_REAJUSTE, ROTULO_INDICE, TITULO_MAX,
                    _esq, agora, data_br, decimais, escolha, hoje, init_db,
                    inteiro, iso, pessoa, proximo_codigo, texto, valor_br)

# Antecedência com que um vencimento vira assunto. 90 dias porque contrato de
# transporte com aviso prévio de 30 e negociação de mais 30 precisa começar
# antes disso — avisar no mês do vencimento é avisar tarde.
AVISO_DIAS = 90

_COLUNAS = """
    t.id, t.conta_id, t.oportunidade_id, t.ano, t.sequencia, t.codigo,
    t.objeto, t.inicio, t.fim, t.renovacao_automatica, t.aviso_previo_dias,
    t.indice_reajuste, t.mes_reajuste, t.ultimo_reajuste, t.percentual_ultimo,
    t.prazo_pagamento_dias, t.dono_id, t.dono_nome, t.cancelado_em,
    t.cancelado_motivo, t.observacoes, t.criado_por, t.criado_em,
    t.alterado_por, t.alterado_em
"""


def _linha(r: dict, aviso_dias: int = AVISO_DIAS) -> dict:
    d = dict(r)
    iso(d, "inicio", "fim", "ultimo_reajuste", "cancelado_em")
    decimais(d, "percentual_ultimo", "receita_lanes")
    d["renovacao_automatica"] = bool(d.get("renovacao_automatica"))
    d["indice_rotulo"] = ROTULO_INDICE.get(d["indice_reajuste"],
                                           d["indice_reajuste"])
    d.update(_vigencia(d, aviso_dias))
    d.update(_reajuste(d))
    return d


def _vigencia(d: dict, aviso_dias: int) -> dict:
    """Os quatro estados possíveis, todos derivados.

    - `cancelado`   — rescindido. Evento gravado, o único.
    - `a_iniciar`   — assinado e ainda não começou.
    - `vigente`     — dentro do prazo, sem vencimento próximo.
    - `a_vencer`    — dentro do prazo, mas o fim está a menos de `aviso_dias`.
    - `vencido`     — passou do fim sem renovar.

    Contrato SEM data de fim é indeterminado e fica `vigente` para sempre — o
    que é a verdade, e não um dado faltando. Marcar "vencido" quem não tem
    prazo seria inventar um fim que ninguém contratou.
    """
    hj = hoje()
    if d.get("cancelado_em"):
        return {"situacao": "cancelado", "dias_para_fim": None,
                "indeterminado": False}
    inicio = date.fromisoformat(d["inicio"]) if d.get("inicio") else None
    fim = date.fromisoformat(d["fim"]) if d.get("fim") else None
    if inicio and inicio > hj:
        return {"situacao": "a_iniciar",
                "dias_para_fim": (fim - hj).days if fim else None,
                "indeterminado": fim is None}
    if fim is None:
        return {"situacao": "vigente", "dias_para_fim": None,
                "indeterminado": True}
    dias = (fim - hj).days
    if dias < 0:
        return {"situacao": "vencido", "dias_para_fim": dias,
                "indeterminado": False}
    if dias <= aviso_dias:
        return {"situacao": "a_vencer", "dias_para_fim": dias,
                "indeterminado": False}
    return {"situacao": "vigente", "dias_para_fim": dias,
            "indeterminado": False}


def _reajuste(d: dict) -> dict:
    """Se o reajuste do ciclo corrente já saiu — derivado, nunca gravado.

    A conta é simples e a armadilha é o ANO: um contrato com reajuste em
    janeiro, ajustado pela última vez em janeiro do ano passado, está DEVENDO
    um ciclo — e comparar só o mês diria que está em dia. O ciclo corrente é o
    último aniversário do mês de reajuste que já passou.
    """
    if d.get("cancelado_em") or not d.get("mes_reajuste"):
        return {"reajuste_pendente": False, "reajuste_ciclo": None,
                "reajuste_dias": None}
    hj = hoje()
    mes = int(d["mes_reajuste"])
    ano = hj.year if hj.month >= mes else hj.year - 1
    ciclo = date(ano, mes, 1)
    ultimo = date.fromisoformat(d["ultimo_reajuste"]) if d.get("ultimo_reajuste") else None
    pendente = ultimo is None or ultimo < ciclo
    # Contrato que ainda não começou, ou que começou depois do início do ciclo,
    # não deve reajuste nenhum — cobrar reajuste de um contrato de dois meses
    # seria alarme falso, e alarme falso ensina a ignorar o alarme.
    inicio = date.fromisoformat(d["inicio"]) if d.get("inicio") else None
    if inicio and inicio >= ciclo:
        pendente = False
    return {"reajuste_pendente": bool(pendente),
            "reajuste_ciclo": ciclo.isoformat(),
            "reajuste_dias": (hj - ciclo).days if pendente else None}


# ------------------------------------------------------------------ leitura --

def listar(*, conta_id: int | None = None, situacao: str = "",
           dono_id: int | None = None, aviso_dias: int = AVISO_DIAS,
           esquema: str | None = None) -> list[dict]:
    """Os contratos, com vigência e reajuste calculados.

    O filtro de SITUAÇÃO é aplicado em Python porque a situação não existe no
    banco — pelo mesmo motivo do filtro de situação das contas. Filtrá-la em
    SQL exigiria gravá-la, que é o que este módulo não faz.
    """
    onde: list[str] = []
    p: dict = {}
    if conta_id:
        onde.append("t.conta_id = %(conta)s")
        p["conta"] = int(conta_id)
    if dono_id:
        onde.append("t.dono_id = %(dono)s")
        p["dono"] = int(dono_id)
    filtro = ("WHERE " + " AND ".join(onde)) if onde else ""
    linhas = pglocal.query(f"""
        SELECT {_COLUNAS}, c.nome AS conta_nome,
               c.ava_agrupamento AS conta_ava,
               o.codigo AS oportunidade_codigo,
               coalesce(l.lanes, 0) AS lanes,
               l.receita AS receita_lanes
        FROM crm_contratos t
        JOIN crm_contas c ON c.id = t.conta_id
        LEFT JOIN crm_oportunidades o ON o.id = t.oportunidade_id
        LEFT JOIN (
            SELECT contrato_id, count(*) AS lanes,
                   sum(CASE WHEN valor_viagem IS NOT NULL AND viagens_mes IS NOT NULL
                            THEN valor_viagem * viagens_mes ELSE 0 END) AS receita
            FROM crm_lanes WHERE contrato_id IS NOT NULL GROUP BY contrato_id
        ) l ON l.contrato_id = t.id
        {filtro}
        ORDER BY t.fim NULLS LAST, t.id DESC
    """, p, esquema=_esq(esquema))
    saida = [_linha(r, aviso_dias) for r in linhas]
    if situacao.strip():
        saida = [c for c in saida if c["situacao"] == situacao.strip()]
    return saida


def obter(contrato_id: int, *, esquema: str | None = None) -> dict | None:
    esq = _esq(esquema)
    r = pglocal.um(f"""
        SELECT {_COLUNAS}, c.nome AS conta_nome, c.ava_agrupamento AS conta_ava,
               o.codigo AS oportunidade_codigo,
               (SELECT count(*) FROM crm_lanes WHERE contrato_id = t.id) AS lanes,
               (SELECT sum(CASE WHEN valor_viagem IS NOT NULL AND viagens_mes IS NOT NULL
                                THEN valor_viagem * viagens_mes ELSE 0 END)
                  FROM crm_lanes WHERE contrato_id = t.id) AS receita_lanes
        FROM crm_contratos t
        JOIN crm_contas c ON c.id = t.conta_id
        LEFT JOIN crm_oportunidades o ON o.id = t.oportunidade_id
        WHERE t.id = %s
    """, (int(contrato_id),), esquema=esq)
    if not r:
        return None
    d = _linha(r)
    ref = precificacao.referencia_ckm()
    d["lanes_detalhe"] = op.lanes(contrato_id=contrato_id, referencia=ref,
                                  esquema=esq)
    d["resumo_lanes"] = precificacao.resumir(d["lanes_detalhe"])
    d["referencia_ckm"] = ref
    return d


# ------------------------------------------------------------------ escrita --

def gravar(dados: dict, *, usuario: str = "", contrato_id: int | None = None,
           esquema: str | None = None) -> dict:
    esq = _esq(esquema)
    init_db(esq)
    conta_id = inteiro(dados.get("conta_id"), "a conta", minimo=1,
                       maximo=99999999)
    if not pglocal.um("SELECT 1 FROM crm_contas WHERE id=%s", (conta_id,),
                      esquema=esq):
        raise DadoInvalido("Esta conta não existe mais.")
    dono_id, dono_nome = pessoa(dados.get("dono_id"), dados.get("dono_nome"),
                                "Responsável", esquema=esq)
    inicio = data_br(dados.get("inicio"), "o início da vigência",
                     obrigatorio=True)
    fim = data_br(dados.get("fim"), "o fim da vigência")
    if fim and fim < inicio:
        raise DadoInvalido("O fim da vigência não pode ser anterior ao início.")
    cancelado = data_br(dados.get("cancelado_em"), "a data de rescisão")
    motivo_cancel = texto(dados.get("cancelado_motivo"), "o motivo da rescisão",
                          maximo=TITULO_MAX)
    if cancelado and not motivo_cancel:
        raise DadoInvalido(
            "Informe o motivo da rescisão. Contrato que sai sem motivo "
            "registrado é o que ninguém consegue explicar seis meses depois.")
    campos = {
        "conta_id": conta_id,
        "oportunidade_id": (int(dados["oportunidade_id"])
                            if dados.get("oportunidade_id") not in (None, "", 0)
                            else None),
        "objeto": texto(dados.get("objeto"), "o objeto do contrato",
                        maximo=TITULO_MAX, obrigatorio=True),
        "inicio": inicio, "fim": fim,
        "renovacao_automatica": 1 if dados.get("renovacao_automatica") else 0,
        "aviso_previo_dias": (None if dados.get("aviso_previo_dias") in (None, "")
                              else inteiro(dados.get("aviso_previo_dias"),
                                           "o aviso prévio", minimo=0, maximo=365)),
        "indice_reajuste": escolha(dados.get("indice_reajuste"),
                                   INDICES_REAJUSTE, "O índice de reajuste",
                                   padrao="negociado"),
        "mes_reajuste": (None if dados.get("mes_reajuste") in (None, "")
                         else inteiro(dados.get("mes_reajuste"),
                                      "o mês do reajuste", minimo=1, maximo=12)),
        "ultimo_reajuste": data_br(dados.get("ultimo_reajuste"),
                                   "a data do último reajuste"),
        "percentual_ultimo": valor_br(dados.get("percentual_ultimo"),
                                      "o percentual do último reajuste"),
        "prazo_pagamento_dias": (None if dados.get("prazo_pagamento_dias") in (None, "")
                                 else inteiro(dados.get("prazo_pagamento_dias"),
                                              "o prazo de pagamento",
                                              minimo=0, maximo=365)),
        "dono_id": dono_id, "dono_nome": dono_nome,
        "cancelado_em": cancelado, "cancelado_motivo": motivo_cancel,
        "observacoes": texto(dados.get("observacoes"), "as observações"),
    }
    ts = agora()
    if contrato_id:
        campos["alterado_por"], campos["alterado_em"] = usuario, ts
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(contrato_id)
        pglocal.executar(f"UPDATE crm_contratos SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo = int(contrato_id)
    else:
        ano, seq, codigo = proximo_codigo("crm_contratos", "CTR", esquema=esq)
        campos.update({"ano": ano, "sequencia": seq, "codigo": codigo,
                       "criado_por": usuario, "alterado_por": usuario,
                       "criado_em": ts, "alterado_em": ts})
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_contratos({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo = int(r["id"])
    return obter(novo, esquema=esq)


def registrar_reajuste(contrato_id: int, *, percentual, quando=None,
                       usuario: str = "", esquema: str | None = None) -> dict:
    """Carimba o reajuste do ciclo. O caminho curto da tela de contratos.

    Rota própria porque é a operação frequente e porque a data importa: gravar
    `ultimo_reajuste` com a data em que alguém lembrou de registrar, e não com
    a da vigência do reajuste, faria o ciclo seguinte ser cobrado no mês errado.
    """
    esq = _esq(esquema)
    if not pglocal.um("SELECT 1 FROM crm_contratos WHERE id=%s",
                      (int(contrato_id),), esquema=esq):
        raise DadoInvalido("Este contrato não existe mais.")
    pct = valor_br(percentual, "o percentual do reajuste")
    if pct is None:
        raise DadoInvalido("Informe o percentual aplicado.")
    if not (-50 <= pct <= 100):
        raise DadoInvalido(
            f"O percentual de {pct:g}% está fora da faixa possível para um "
            f"reajuste de frete (-50% a 100%). Confira se não é o valor em "
            f"reais no lugar do percentual.")
    data = data_br(quando, "a data do reajuste") or hoje()
    pglocal.executar(
        "UPDATE crm_contratos SET ultimo_reajuste=%s, percentual_ultimo=%s, "
        "alterado_por=%s, alterado_em=%s WHERE id=%s",
        (data, pct, usuario, agora(), int(contrato_id)), esquema=esq)
    return obter(contrato_id, esquema=esq)


def excluir(contrato_id: int, *, esquema: str | None = None) -> None:
    """Exclui o contrato e a tabela de preço dele (CASCADE nas lanes).

    Contrato rescindido se RESCINDE (`cancelado_em`), não se apaga: o histórico
    de que houve contrato é o que explica a receita passada. A exclusão existe
    para o registro criado por engano.
    """
    pglocal.executar("DELETE FROM crm_contratos WHERE id=%s",
                     (int(contrato_id),), esquema=_esq(esquema))


def copiar_lanes_da_oportunidade(contrato_id: int, oportunidade_id: int, *,
                                 esquema: str | None = None) -> int:
    """Leva a tabela de preço da proposta ganha para o contrato.

    Cópia e NÃO referência: a proposta é o que foi oferecido e o contrato é o
    que foi assinado, e eles divergem com frequência (a última rodada de
    negociação mexe em duas lanes). Apontar o contrato para as lanes da
    oportunidade faria uma correção na proposta reescrever o contrato — em
    silêncio, e num documento que tem valor jurídico.
    """
    esq = _esq(esquema)
    return pglocal.executar("""
        INSERT INTO crm_lanes(
            contrato_id, origem_cidade, origem_uf, destino_cidade, destino_uf,
            km, km_vazio, tipo_veiculo, eixos, tipo_carga, viagens_mes,
            valor_viagem, pedagio, observacoes, ordem)
        SELECT %(ctr)s, origem_cidade, origem_uf, destino_cidade, destino_uf,
               km, km_vazio, tipo_veiculo, eixos, tipo_carga, viagens_mes,
               valor_viagem, pedagio, observacoes, ordem
        FROM crm_lanes WHERE oportunidade_id = %(opo)s
    """, {"ctr": int(contrato_id), "opo": int(oportunidade_id)}, esquema=esq)


def catalogo() -> dict:
    return {"indices": [{"valor": i, "rotulo": ROTULO_INDICE[i]}
                        for i in INDICES_REAJUSTE],
            "aviso_dias": AVISO_DIAS}
