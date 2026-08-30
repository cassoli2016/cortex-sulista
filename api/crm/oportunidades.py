"""Oportunidades e suas lanes — o negócio e as rotas que o compõem.

A oportunidade NÃO guarda o valor do negócio. Ele é a soma das lanes
(`valor_viagem × viagens_mes`), calculada na leitura, e a razão é o defeito
clássico de total desnormalizado: no dia em que alguém edita uma lane, um total
gravado passa a discordar das próprias linhas — e discorda em silêncio, que é o
pior jeito de um número errar.

`receita_mensal_manual` é a exceção declarada: vale enquanto a oportunidade não
tem lane nenhuma, que é o estado legítimo de um negócio recém-aberto em
qualificação. Assim que a primeira lane entra, o manual deixa de ser lido — e a
tela DIZ de onde veio o número (`origem_receita`), porque um valor que muda de
fonte sem avisar é um valor em que ninguém confia.
"""
from __future__ import annotations

from .. import pglocal
from . import precificacao
from .comum import (DadoInvalido, ESTAGIOS, ESTAGIOS_FECHADOS, ESTAGIOS_TODOS,
                    MOTIVOS_PERDA, PROB_PADRAO, ROTULO_CARGA, ROTULO_ESTAGIO,
                    ROTULO_MOTIVO, ROTULO_TIPO_OPO, TIPOS_CARGA,
                    TIPOS_OPORTUNIDADE, TITULO_MAX, VEICULOS, _esq, agora,
                    data_br, decimais, escolha, hoje, init_db, inteiro, iso,
                    pessoa, proximo_codigo, texto, uf, valor_br)

_COLUNAS = """
    o.id, o.conta_id, o.ano, o.sequencia, o.codigo, o.titulo, o.tipo,
    o.estagio, o.probabilidade, o.receita_mensal_manual, o.meses_contrato,
    o.dono_id, o.dono_nome, o.abertura, o.previsao_fechamento, o.fechada_em,
    o.motivo_perda, o.perda_detalhe, o.concorrente, o.observacoes,
    o.criado_por, o.criado_em, o.alterado_por, o.alterado_em
"""

_COLUNAS_LANE = """
    id, oportunidade_id, contrato_id, origem_cidade, origem_uf,
    destino_cidade, destino_uf, km, km_vazio, tipo_veiculo, eixos, tipo_carga,
    viagens_mes, valor_viagem, pedagio, observacoes, ordem
"""

# A receita e a contagem de lanes vêm de um agregado, não de N consultas: a
# lista do kanban desenha as quatro colunas de uma vez e uma consulta por
# oportunidade seria uma ida ao banco por cartão.
_AGREGADO_LANES = """
    LEFT JOIN (
        SELECT oportunidade_id,
               count(*) AS lanes,
               sum(CASE WHEN valor_viagem IS NOT NULL AND viagens_mes IS NOT NULL
                        THEN valor_viagem * viagens_mes ELSE 0 END) AS receita,
               sum(CASE WHEN valor_viagem IS NULL OR viagens_mes IS NULL
                        THEN 1 ELSE 0 END) AS sem_preco,
               sum(CASE WHEN km IS NOT NULL AND viagens_mes IS NOT NULL
                        THEN (km + coalesce(km_vazio, 0)) * viagens_mes
                        ELSE 0 END) AS km_mes
        FROM crm_lanes WHERE oportunidade_id IS NOT NULL
        GROUP BY oportunidade_id
    ) l ON l.oportunidade_id = o.id
"""


def _linha(r: dict) -> dict:
    """Normaliza a linha crua e acrescenta o que é DERIVADO.

    Tudo o que sai daqui — receita, probabilidade efetiva, valor ponderado,
    atraso da previsão, idade — é calculado. Nenhum desses campos existe no
    banco, e é de propósito.
    """
    d = dict(r)
    iso(d, "abertura", "previsao_fechamento", "fechada_em")
    decimais(d, "receita_mensal_manual", "receita_lanes", "km_mes")

    d["estagio_rotulo"] = ROTULO_ESTAGIO.get(d["estagio"], d["estagio"])
    d["tipo_rotulo"] = ROTULO_TIPO_OPO.get(d["tipo"], d["tipo"])
    d["motivo_rotulo"] = ROTULO_MOTIVO.get(d["motivo_perda"]) if d.get("motivo_perda") else None
    d["aberta"] = d["estagio"] in ESTAGIOS

    lanes = int(d.pop("lanes_n", 0) or 0)
    receita_lanes = d.pop("receita_lanes", None)
    d["lanes"] = lanes
    d["lanes_sem_preco"] = int(d.pop("lanes_sem_preco", 0) or 0)

    # A regra do cabeçalho do módulo, num lugar só.
    if lanes:
        d["receita_mes"] = receita_lanes or 0.0
        d["origem_receita"] = "lanes"
    elif d.get("receita_mensal_manual") is not None:
        d["receita_mes"] = d["receita_mensal_manual"]
        d["origem_receita"] = "manual"
    else:
        d["receita_mes"] = None
        d["origem_receita"] = None

    # Probabilidade: a do negócio quando alguém opinou, a do estágio quando não.
    # `probabilidade_padrao` diz qual das duas está valendo — sem isso a tela
    # não consegue mostrar "50% (padrão do estágio)" contra "20% (o vendedor
    # disse)", que são coisas muito diferentes numa previsão.
    padrao = PROB_PADRAO.get(d["estagio"], 0)
    d["probabilidade_efetiva"] = (d["probabilidade"] if d["probabilidade"] is not None
                                  else padrao)
    d["probabilidade_padrao"] = d["probabilidade"] is None
    d["valor_ponderado"] = ((d["receita_mes"] * d["probabilidade_efetiva"] / 100.0)
                            if d["receita_mes"] is not None else None)

    # Valor do CONTRATO inteiro, quando há prazo. Uma oportunidade de R$ 80 mil
    # por 36 meses e uma de R$ 80 mil spot não valem o mesmo, e o pipeline
    # mensal sozinho as mostra idênticas.
    d["valor_total"] = ((d["receita_mes"] * d["meses_contrato"])
                        if (d["receita_mes"] is not None and d.get("meses_contrato"))
                        else None)

    hj = hoje()
    prev = d.get("previsao_fechamento")
    if prev and d["aberta"]:
        from datetime import date as _d
        dias = (_d.fromisoformat(prev) - hj).days
        d["dias_para_previsao"] = dias
        # Previsão vencida com a oportunidade aberta é o sinal mais barato de
        # pipeline podre que existe: ou a data era otimista, ou o negócio
        # morreu e ninguém fechou o cartão.
        d["previsao_vencida"] = dias < 0
    else:
        d["dias_para_previsao"] = None
        d["previsao_vencida"] = False

    if d.get("abertura"):
        from datetime import date as _d
        fim = _d.fromisoformat(d["fechada_em"]) if d.get("fechada_em") else hj
        d["idade_dias"] = (fim - _d.fromisoformat(d["abertura"])).days
    else:
        d["idade_dias"] = None
    return d


# ------------------------------------------------------------------ leitura --

def listar(*, conta_id: int | None = None, estagio: str = "",
           dono_id: int | None = None, busca: str = "",
           incluir_fechadas: bool = False, tipo: str = "",
           esquema: str | None = None) -> list[dict]:
    onde: list[str] = []
    p: dict = {}
    if conta_id:
        onde.append("o.conta_id = %(conta)s")
        p["conta"] = int(conta_id)
    if estagio.strip():
        onde.append("o.estagio = %(est)s")
        p["est"] = estagio.strip()
    elif not incluir_fechadas:
        onde.append("o.estagio NOT IN ('ganha', 'perdida')")
    if dono_id:
        onde.append("o.dono_id = %(dono)s")
        p["dono"] = int(dono_id)
    if tipo.strip():
        onde.append("o.tipo = %(tipo)s")
        p["tipo"] = tipo.strip()
    if busca.strip():
        onde.append("(o.titulo ILIKE %(q)s OR o.codigo ILIKE %(q)s "
                    "OR c.nome ILIKE %(q)s)")
        p["q"] = f"%{busca.strip()}%"
    filtro = ("WHERE " + " AND ".join(onde)) if onde else ""
    linhas = pglocal.query(f"""
        SELECT {_COLUNAS}, c.nome AS conta_nome,
               c.ava_agrupamento AS conta_ava,
               coalesce(l.lanes, 0) AS lanes_n,
               l.receita AS receita_lanes,
               coalesce(l.sem_preco, 0) AS lanes_sem_preco,
               l.km_mes AS km_mes
        FROM crm_oportunidades o
        JOIN crm_contas c ON c.id = o.conta_id
        {_AGREGADO_LANES}
        {filtro}
        ORDER BY o.previsao_fechamento NULLS LAST, o.id DESC
    """, p, esquema=_esq(esquema))
    return [_linha(r) for r in linhas]


def obter(oportunidade_id: int, *, esquema: str | None = None) -> dict | None:
    """A oportunidade com as lanes JÁ AVALIADAS (R$/km, piso ANTT, margem)."""
    esq = _esq(esquema)
    r = pglocal.um(f"""
        SELECT {_COLUNAS}, c.nome AS conta_nome, c.ava_agrupamento AS conta_ava,
               c.segmento AS conta_segmento,
               coalesce(l.lanes, 0) AS lanes_n, l.receita AS receita_lanes,
               coalesce(l.sem_preco, 0) AS lanes_sem_preco, l.km_mes AS km_mes
        FROM crm_oportunidades o
        JOIN crm_contas c ON c.id = o.conta_id
        {_AGREGADO_LANES}
        WHERE o.id = %s
    """, (int(oportunidade_id),), esquema=esq)
    if not r:
        return None
    d = _linha(r)
    ref = precificacao.referencia_ckm()
    d["lanes_detalhe"] = lanes(oportunidade_id, referencia=ref, esquema=esq)
    d["resumo_lanes"] = precificacao.resumir(d["lanes_detalhe"])
    d["referencia_ckm"] = ref
    return d


def lanes(oportunidade_id: int | None = None, *, contrato_id: int | None = None,
          referencia: dict | None = None,
          esquema: str | None = None) -> list[dict]:
    """As lanes de uma oportunidade OU de um contrato, já avaliadas.

    A mesma função serve aos dois porque a lane é o mesmo conceito nos dois
    momentos (ver `crm_lanes` em 0026_crm.sql) — e é assim que o R$/km e o piso
    da ANTT ficam garantidamente iguais entre a proposta e o contrato assinado.
    """
    if (oportunidade_id is None) == (contrato_id is None):
        raise DadoInvalido("Informe a oportunidade OU o contrato.")
    col = "oportunidade_id" if oportunidade_id is not None else "contrato_id"
    ident = int(oportunidade_id if oportunidade_id is not None else contrato_id)
    linhas = pglocal.query(
        f"SELECT {_COLUNAS_LANE} FROM crm_lanes WHERE {col}=%s ORDER BY ordem, id",
        (ident,), esquema=_esq(esquema))
    ref = referencia if referencia is not None else precificacao.referencia_ckm()
    saida = []
    for l in linhas:
        d = dict(l)
        decimais(d, "km", "km_vazio", "viagens_mes", "valor_viagem", "pedagio")
        d["rotulo"] = _rotulo_lane(d)
        d["carga_rotulo"] = ROTULO_CARGA.get(d["tipo_carga"], d["tipo_carga"] or None)
        d["calc"] = precificacao.avaliar_lane(
            d, ckm_marginal=ref.get("ckm_marginal"),
            ckm_cheio=ref.get("ckm_cheio"))
        saida.append(d)
    return saida


def lanes_de_varias(ids: list[int], *, referencia: dict | None = None,
                    esquema: str | None = None) -> dict[int, list[dict]]:
    """As lanes de VÁRIAS oportunidades, numa consulta só.

    Existe para o painel: ele precisa avaliar todas as lanes abertas para achar
    as que estão abaixo do piso, e um `lanes()` por oportunidade seria uma ida
    ao banco por cartão do kanban — na tela de ABERTURA, que é a que todo mundo
    paga. Mesma razão de `ava.carteira` buscar todas as contas de uma vez.
    """
    limpos = sorted({int(i) for i in ids if i})
    if not limpos:
        return {}
    linhas = pglocal.query(
        f"SELECT {_COLUNAS_LANE} FROM crm_lanes "
        "WHERE oportunidade_id = ANY(%s) ORDER BY oportunidade_id, ordem, id",
        (limpos,), esquema=_esq(esquema))
    ref = referencia if referencia is not None else precificacao.referencia_ckm()
    saida: dict[int, list[dict]] = {}
    for l in linhas:
        d = dict(l)
        decimais(d, "km", "km_vazio", "viagens_mes", "valor_viagem", "pedagio")
        d["rotulo"] = _rotulo_lane(d)
        d["carga_rotulo"] = ROTULO_CARGA.get(d["tipo_carga"], d["tipo_carga"] or None)
        d["calc"] = precificacao.avaliar_lane(
            d, ckm_marginal=ref.get("ckm_marginal"),
            ckm_cheio=ref.get("ckm_cheio"))
        saida.setdefault(int(d["oportunidade_id"]), []).append(d)
    return saida


def _rotulo_lane(d: dict) -> str:
    """`Joinville/SC → Betim/MG`, com o que houver.

    Lane sem cidade nenhuma vira "(rota não informada)" e não uma seta solta:
    uma linha com "→" e nada dos lados parece defeito de renderização, e alguém
    vai abrir chamado para o que é campo em branco.
    """
    def parte(cidade: str, sigla: str) -> str:
        c = (cidade or "").strip()
        u = (sigla or "").strip()
        if c and u:
            return f"{c}/{u}"
        return c or u or ""
    a, b = parte(d.get("origem_cidade"), d.get("origem_uf")), \
        parte(d.get("destino_cidade"), d.get("destino_uf"))
    if not a and not b:
        return "(rota não informada)"
    return f"{a or '?'} → {b or '?'}"


# ------------------------------------------------------------------ escrita --

def gravar(dados: dict, *, usuario: str = "",
           oportunidade_id: int | None = None,
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
    estagio = escolha(dados.get("estagio"), ESTAGIOS_TODOS, "O estágio",
                      padrao="qualificacao")
    motivo, detalhe, fechada = _fechamento(dados, estagio, oportunidade_id, esq)

    prob = dados.get("probabilidade")
    campos = {
        "conta_id": conta_id,
        "titulo": texto(dados.get("titulo"), "o título", maximo=TITULO_MAX,
                        obrigatorio=True),
        "tipo": escolha(dados.get("tipo"), TIPOS_OPORTUNIDADE, "O tipo",
                        padrao="contrato"),
        "estagio": estagio,
        "probabilidade": (None if prob in (None, "") else
                          inteiro(prob, "a probabilidade", minimo=0, maximo=100)),
        "receita_mensal_manual": valor_br(dados.get("receita_mensal_manual"),
                                          "a receita mensal estimada"),
        "meses_contrato": (None if dados.get("meses_contrato") in (None, "") else
                           inteiro(dados.get("meses_contrato"),
                                   "o prazo em meses", minimo=1, maximo=120)),
        "dono_id": dono_id, "dono_nome": dono_nome,
        "abertura": data_br(dados.get("abertura"), "a data de abertura") or hoje(),
        "previsao_fechamento": data_br(dados.get("previsao_fechamento"),
                                       "a previsão de fechamento"),
        "fechada_em": fechada,
        "motivo_perda": motivo,
        "perda_detalhe": detalhe,
        "concorrente": texto(dados.get("concorrente"), "o concorrente",
                             maximo=TITULO_MAX),
        "observacoes": texto(dados.get("observacoes"), "as observações"),
    }
    ts = agora()
    if oportunidade_id:
        campos["alterado_por"], campos["alterado_em"] = usuario, ts
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(oportunidade_id)
        pglocal.executar(f"UPDATE crm_oportunidades SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo = int(oportunidade_id)
    else:
        ano, seq, codigo = proximo_codigo("crm_oportunidades", "OPO",
                                          esquema=esq)
        campos.update({"ano": ano, "sequencia": seq, "codigo": codigo,
                       "criado_por": usuario, "alterado_por": usuario,
                       "criado_em": ts, "alterado_em": ts})
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_oportunidades({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo = int(r["id"])
    return obter(novo, esquema=esq)


def _fechamento(dados: dict, estagio: str, oportunidade_id: int | None,
                esq: str | None) -> tuple[str, str, object]:
    """Motivo, detalhe e data de fechamento — com as regras do CHECK do banco.

    Validar aqui e não deixar o banco recusar não é redundância: a mensagem do
    CHECK ("new row violates check constraint crm_opo_perda_ck") não diz a
    ninguém que falta escolher o motivo da perda. O CHECK continua sendo a rede
    de baixo, para a próxima tela que gravar sem passar por aqui.
    """
    motivo = texto(dados.get("motivo_perda"), "o motivo da perda", maximo=40).lower()
    detalhe = texto(dados.get("perda_detalhe"), "o detalhe da perda")
    if estagio not in ESTAGIOS_FECHADOS:
        # Reabrir limpa o carimbo, como `concluida_em` de ges_acoes volta a
        # NULL: manter a data da primeira conclusão faria o tempo de ciclo
        # medir um fechamento que foi desfeito.
        return "", detalhe if estagio == "perdida" else "", None
    if estagio == "perdida":
        if motivo and motivo not in MOTIVOS_PERDA:
            raise DadoInvalido(
                f"Motivo da perda deve ser um de: {', '.join(MOTIVOS_PERDA)}.")
        if not motivo:
            raise DadoInvalido(
                "Escolha o motivo da perda. É o único dado que transforma uma "
                "perda em aprendizado — sem ele não dá para saber se o problema "
                "é preço ou capacidade.")
    else:
        motivo = ""
    data = data_br(dados.get("fechada_em"), "a data de fechamento")
    if data is None:
        anterior = pglocal.um(
            "SELECT fechada_em FROM crm_oportunidades WHERE id=%s",
            (int(oportunidade_id or 0),), esquema=esq) if oportunidade_id else None
        data = (anterior or {}).get("fechada_em") or hoje()
    return motivo, detalhe, data


def mover(oportunidade_id: int, estagio: str, *, usuario: str = "",
          motivo_perda: str = "", perda_detalhe: str = "",
          esquema: str | None = None) -> dict:
    """A transição de estágio isolada — o caminho do arraste no kanban.

    Rota própria, e não o `gravar` com o corpo inteiro, pela mesma razão do
    andamento de ação na Gestão: mover é a operação FREQUENTE, e obrigar o
    formulário completo para arrastar um cartão é o que faz o funil ficar
    desatualizado. Quem move para "perdida" ainda precisa do motivo — a tela
    pede, porque é a única hora em que alguém lembra.
    """
    esq = _esq(esquema)
    atual = pglocal.um(
        "SELECT id, estagio, titulo, codigo, conta_id FROM crm_oportunidades "
        "WHERE id=%s", (int(oportunidade_id),), esquema=esq)
    if not atual:
        raise DadoInvalido("Esta oportunidade não existe mais.")
    novo = escolha(estagio, ESTAGIOS_TODOS, "O estágio")
    motivo, detalhe, fechada = _fechamento(
        {"motivo_perda": motivo_perda, "perda_detalhe": perda_detalhe},
        novo, oportunidade_id, esq)
    pglocal.executar("""
        UPDATE crm_oportunidades
           SET estagio=%s, motivo_perda=%s, perda_detalhe=%s, fechada_em=%s,
               alterado_por=%s, alterado_em=%s
         WHERE id=%s
    """, (novo, motivo, detalhe, fechada, usuario, agora(),
          int(oportunidade_id)), esquema=esq)
    return obter(oportunidade_id, esquema=esq)


def excluir(oportunidade_id: int, *, esquema: str | None = None) -> None:
    pglocal.executar("DELETE FROM crm_oportunidades WHERE id=%s",
                     (int(oportunidade_id),), esquema=_esq(esquema))


# -------------------------------------------------------------------- lanes --

def gravar_lane(dados: dict, *, lane_id: int | None = None,
                esquema: str | None = None) -> dict:
    """Cria ou edita uma lane, de oportunidade OU de contrato.

    `eixos` pode vir do nome do veículo (`VEICULOS`) quando a tela mandou a
    composição em vez do número — é o caminho normal, porque quem cota escolhe
    "Carreta LS (3 eixos)" e não precisa saber que a ANTT conta 6.
    """
    esq = _esq(esquema)
    init_db(esq)
    opo = dados.get("oportunidade_id")
    ctr = dados.get("contrato_id")
    if (opo in (None, "", 0)) == (ctr in (None, "", 0)):
        raise DadoInvalido("A lane pertence a uma oportunidade OU a um "
                           "contrato — informe exatamente um.")
    veiculo = texto(dados.get("tipo_veiculo"), "o veículo", maximo=120)
    eixos = dados.get("eixos")
    if eixos in (None, "") and veiculo in VEICULOS:
        eixos = VEICULOS[veiculo]
    campos = {
        "oportunidade_id": int(opo) if opo not in (None, "", 0) else None,
        "contrato_id": int(ctr) if ctr not in (None, "", 0) else None,
        "origem_cidade": texto(dados.get("origem_cidade"), "a cidade de origem",
                               maximo=120),
        "origem_uf": uf(dados.get("origem_uf"), "a UF de origem"),
        "destino_cidade": texto(dados.get("destino_cidade"),
                                "a cidade de destino", maximo=120),
        "destino_uf": uf(dados.get("destino_uf"), "a UF de destino"),
        "km": _num(dados.get("km"), "a distância", 0.1, 6000),
        "km_vazio": _num(dados.get("km_vazio"), "o km vazio", 0, 6000),
        "tipo_veiculo": veiculo,
        "eixos": (None if eixos in (None, "") else
                  inteiro(eixos, "os eixos", minimo=2, maximo=9)),
        "tipo_carga": _carga(dados.get("tipo_carga")),
        "viagens_mes": _num(dados.get("viagens_mes"), "as viagens por mês",
                            0.1, 2000),
        "valor_viagem": valor_br(dados.get("valor_viagem"), "o valor da viagem"),
        "pedagio": valor_br(dados.get("pedagio"), "o pedágio"),
        "observacoes": texto(dados.get("observacoes"), "as observações"),
        "ordem": inteiro(dados.get("ordem"), "a ordem", minimo=0, maximo=9999,
                         padrao=0),
    }
    if lane_id:
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(lane_id)
        pglocal.executar(f"UPDATE crm_lanes SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo = int(lane_id)
    else:
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_lanes({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo = int(r["id"])
    r = pglocal.um(f"SELECT {_COLUNAS_LANE} FROM crm_lanes WHERE id=%s",
                   (novo,), esquema=esq)
    d = dict(r)
    decimais(d, "km", "km_vazio", "viagens_mes", "valor_viagem", "pedagio")
    ref = precificacao.referencia_ckm()
    d["rotulo"] = _rotulo_lane(d)
    d["carga_rotulo"] = ROTULO_CARGA.get(d["tipo_carga"], d["tipo_carga"] or None)
    d["calc"] = precificacao.avaliar_lane(
        d, ckm_marginal=ref.get("ckm_marginal"), ckm_cheio=ref.get("ckm_cheio"))
    return d


def _num(valor, rotulo: str, minimo: float, maximo: float):
    """Número decimal com FAIXA FÍSICA conferida.

    A régua não é preciosismo: `_CTA_KM_SANO` do combustível descartava o
    odômetro resetado e ainda assim deixava passar 0,23 km/l, porque validava
    só um lado. Aqui km fora de 0–6.000 e viagens fora de 0–2.000 são erro de
    digitação, não rota exótica, e aceitá-los faz o total da oportunidade — e
    portanto o pipeline inteiro — mentir por uma tecla.
    """
    if valor in (None, ""):
        return None
    v = valor_br(valor, rotulo)
    if v is None:
        return None
    if not (minimo <= v <= maximo):
        raise DadoInvalido(
            f"{rotulo[0].upper()}{rotulo[1:]} deve ficar entre "
            f"{minimo:g} e {maximo:g} — {v:g} está fora da faixa possível.")
    return v


def _carga(valor) -> str:
    s = texto(valor, "o tipo de carga", maximo=60).strip().lower()
    if not s:
        return ""
    if s not in TIPOS_CARGA:
        raise DadoInvalido(
            "Tipo de carga deve ser uma das classes da tabela ANTT "
            f"({', '.join(TIPOS_CARGA[:4])}…) — é dela que sai o piso mínimo.")
    return s


def excluir_lane(lane_id: int, *, esquema: str | None = None) -> None:
    pglocal.executar("DELETE FROM crm_lanes WHERE id=%s", (int(lane_id),),
                     esquema=_esq(esquema))


def catalogo() -> dict:
    """As listas que o formulário de oportunidade e de lane precisam."""
    return {
        "estagios": [{"valor": e, "rotulo": ROTULO_ESTAGIO[e],
                      "probabilidade": PROB_PADRAO[e]} for e in ESTAGIOS],
        "estagios_fechados": [{"valor": e, "rotulo": ROTULO_ESTAGIO[e]}
                              for e in ESTAGIOS_FECHADOS],
        "tipos": [{"valor": t, "rotulo": ROTULO_TIPO_OPO[t]}
                  for t in TIPOS_OPORTUNIDADE],
        "motivos_perda": [{"valor": m, "rotulo": ROTULO_MOTIVO[m]}
                          for m in MOTIVOS_PERDA],
        "cargas": [{"valor": c, "rotulo": ROTULO_CARGA.get(c, c)}
                   for c in TIPOS_CARGA],
        "veiculos": [{"nome": n, "eixos": e} for n, e in VEICULOS.items()],
    }
