"""Projetos — a execução do que foi vendido.

A oportunidade responde "vamos fechar?"; o projeto responde "está entrando no
ar no prazo, com o escopo combinado, rendendo o que foi prometido?". São
perguntas com donos diferentes, e por isso são objetos diferentes.

O QUE ESTE MÓDULO FAZ QUE O ERP DE ORIGEM NÃO FAZ:

1. **Idade e atraso são DERIVADOS.** No `sulista.pipelineprojetos` existe uma
   coluna `aging_dias` preenchida em ZERO de 194 projetos — e tipada como
   `timestamp`, apesar do nome. A tela que a lia mostrava "—" em todas as
   linhas desde sempre. Aqui não há coluna nenhuma de tempo: tudo sai das datas
   contra hoje.

2. **Separa o COMBINADO do ACONTECIDO.** `deadline` × `entrega`,
   `inicio_previsto` × `inicio_real`. Guardar só o que aconteceu faz projeto
   entregue com três meses de atraso parecer entregue no prazo.

3. **Compara o ROB prometido com a receita REAL do ERP** — e diz, em voz alta,
   a limitação dessa comparação: a receita do AVA é do CLIENTE, não do projeto.
   Ver `_realizado`.
"""
from __future__ import annotations

from datetime import date

from .. import pglocal
from . import ava, precificacao
from .comum import (DadoInvalido, TITULO_MAX, _esq, agora, data_br, decimais,
                    escolha, hoje, init_db, inteiro, iso, pessoa,
                    proximo_codigo, texto, valor_br)

# O ciclo de vida da entrega. `implantacao` existe separado de `em_execucao`
# porque são coisas diferentes para quem cobra: implantação tem data de fim
# prevista e alguém correndo atrás; execução é regime, e o que se acompanha
# nela é volume e margem, não prazo.
STATUS = ("nao_iniciado", "implantacao", "em_execucao", "entregue",
          "declinado", "cancelado")
STATUS_ABERTOS = ("nao_iniciado", "implantacao", "em_execucao")
ROTULO_STATUS = {
    "nao_iniciado": "Não iniciado", "implantacao": "Em implantação",
    "em_execucao": "Em execução", "entregue": "Entregue",
    "declinado": "Declinado", "cancelado": "Cancelado"}

# Motivos de encerramento sem venda. Lista fechada pela mesma razão dos motivos
# de perda: o valor só existe para ser AGRUPADO, e campo livre com 40 grafias
# de "cliente desistiu" não responde nada.
MOTIVOS = ("cliente_desistiu", "sem_capacidade", "inviavel_operacional",
           "inviavel_comercial", "prazo", "concorrente", "outro")
ROTULO_MOTIVO = {
    "cliente_desistiu": "Cliente desistiu", "sem_capacidade": "Sem capacidade",
    "inviavel_operacional": "Inviável na operação",
    "inviavel_comercial": "Inviável no preço", "prazo": "Prazo inexequível",
    "concorrente": "Perdeu para concorrente", "outro": "Outro"}

# Escopos típicos. Lista ABERTA (texto livre com sugestão), como as áreas da
# Gestão: engessar obrigaria migration para cada escopo novo.
ESCOPOS = ("Transporte FTL", "Milk run", "Transferência", "Distribuição",
           "Dedicado", "Armazenagem", "Logística reversa", "Spot recorrente",
           "Outro")

# Quantos dias sem andamento fazem um projeto virar assunto. Menor que o da
# conta sem contato (45) porque projeto em implantação tem cadência semanal —
# três semanas sem ninguém escrever nada não é "andando devagar", é parado.
PARADO_DIAS = 21

_COLUNAS = """
    p.id, p.conta_id, p.oportunidade_id, p.contrato_id, p.ano, p.sequencia,
    p.codigo, p.nome, p.escopo, p.detalhe, p.versao, p.status, p.recebimento,
    p.inicio_previsto, p.deadline, p.inicio_real, p.entrega, p.aceite,
    p.prazo_cliente_dias, p.solicitante, p.responsavel_id, p.responsavel_nome,
    p.rob_mensal_manual, p.percentual, p.motivo_encerramento,
    p.encerrado_detalhe, p.observacoes, p.criado_por, p.criado_em,
    p.alterado_por, p.alterado_em
"""

# Receita e contagem das lanes do projeto, num agregado só — a lista desenha
# dezenas de linhas e uma consulta por projeto seria uma ida ao banco por linha.
_AGREGADO = """
    LEFT JOIN (
        SELECT projeto_id, count(*) AS lanes,
               sum(CASE WHEN valor_viagem IS NOT NULL AND viagens_mes IS NOT NULL
                        THEN valor_viagem * viagens_mes ELSE 0 END) AS receita,
               sum(CASE WHEN valor_viagem IS NULL OR viagens_mes IS NULL
                        THEN 1 ELSE 0 END) AS sem_preco
        FROM crm_lanes WHERE projeto_id IS NOT NULL GROUP BY projeto_id
    ) l ON l.projeto_id = p.id
"""

_ANDAMENTO = """
    LEFT JOIN (
        SELECT projeto_id, max(ts) AS ultimo, count(*) AS n
        FROM crm_projeto_andamentos GROUP BY projeto_id
    ) a ON a.projeto_id = p.id
"""


def _linha(r: dict) -> dict:
    """Normaliza e acrescenta TUDO o que é derivado.

    Nenhum dos campos calculados aqui existe no banco, e é de propósito — ver
    o cabeçalho de `0027_crm_projetos.sql`.
    """
    d = dict(r)
    iso(d, "recebimento", "inicio_previsto", "deadline", "inicio_real",
        "entrega", "aceite")
    decimais(d, "rob_mensal_manual", "receita_lanes")
    d["status_rotulo"] = ROTULO_STATUS.get(d["status"], d["status"])
    d["motivo_rotulo"] = (ROTULO_MOTIVO.get(d["motivo_encerramento"])
                          if d.get("motivo_encerramento") else None)
    d["aberto"] = d["status"] in STATUS_ABERTOS

    lanes = int(d.pop("lanes_n", 0) or 0)
    receita = d.pop("receita_lanes", None)
    d["lanes"] = lanes
    d["lanes_sem_preco"] = int(d.pop("lanes_sem_preco", 0) or 0)
    # Mesma regra da oportunidade: o valor sai das lanes; o manual só vale
    # enquanto não houver nenhuma, e a tela DIZ qual dos dois está valendo.
    if lanes:
        d["rob_mensal"] = receita or 0.0
        d["origem_rob"] = "lanes"
    elif d.get("rob_mensal_manual") is not None:
        d["rob_mensal"] = d["rob_mensal_manual"]
        d["origem_rob"] = "manual"
    else:
        d["rob_mensal"] = None
        d["origem_rob"] = None

    hj = hoje()
    dl = date.fromisoformat(d["deadline"]) if d.get("deadline") else None
    ent = date.fromisoformat(d["entrega"]) if d.get("entrega") else None
    ini = date.fromisoformat(d["inicio_real"]) if d.get("inicio_real") else None
    rec = date.fromisoformat(d["recebimento"]) if d.get("recebimento") else None

    # ATRASO: só faz sentido no que está aberto e tem prazo. Projeto entregue
    # não "está atrasado" — ele atrasou ou não, e isso é `dias_de_atraso`.
    if dl and d["aberto"]:
        d["dias_para_deadline"] = (dl - hj).days
        d["atrasado"] = (dl - hj).days < 0
    else:
        d["dias_para_deadline"] = None
        d["atrasado"] = False

    # CUMPRIMENTO DE PRAZO: o combinado contra o que aconteceu. Só existe para
    # quem entregou E tinha prazo — sem os dois, não há afirmação possível, e
    # inventar zero faria a média de pontualidade mentir.
    if ent and dl:
        d["dias_de_atraso"] = (ent - dl).days
        d["no_prazo"] = (ent - dl).days <= 0
    else:
        d["dias_de_atraso"] = None
        d["no_prazo"] = None

    d["duracao_dias"] = (ent - ini).days if (ent and ini) else None
    d["idade_dias"] = ((ent or hj) - (rec or ini)).days if (rec or ini) else None

    ultimo = d.pop("ultimo_andamento", None)
    d["ultimo_andamento"] = ultimo
    d["andamentos"] = int(d.pop("n_andamentos", 0) or 0)
    if ultimo and d["aberto"]:
        try:
            dias = (hj - date.fromisoformat(str(ultimo)[:10])).days
        except ValueError:
            dias = None
        d["parado_dias"] = dias
        d["parado"] = bool(dias is not None and dias > PARADO_DIAS)
    else:
        # Projeto aberto que NUNCA teve andamento conta desde a criação: sem
        # isso, o que ninguém tocou desde o primeiro dia escaparia do alerta
        # justamente por não ter histórico.
        base = (d.get("criado_em") or "")[:10]
        try:
            dias = (hj - date.fromisoformat(base)).days if base else None
        except ValueError:
            dias = None
        d["parado_dias"] = dias if d["aberto"] else None
        d["parado"] = bool(d["aberto"] and dias is not None and dias > PARADO_DIAS)
    return d


# ------------------------------------------------------------------ leitura --

def listar(*, conta_id: int | None = None, status: str = "",
           responsavel_id: int | None = None, busca: str = "",
           incluir_fechados: bool = False,
           esquema: str | None = None) -> list[dict]:
    onde: list[str] = []
    p: dict = {}
    if conta_id:
        onde.append("p.conta_id = %(conta)s")
        p["conta"] = int(conta_id)
    if status.strip():
        onde.append("p.status = %(st)s")
        p["st"] = status.strip()
    elif not incluir_fechados:
        onde.append("p.status IN ('nao_iniciado', 'implantacao', 'em_execucao')")
    if responsavel_id:
        onde.append("p.responsavel_id = %(resp)s")
        p["resp"] = int(responsavel_id)
    if busca.strip():
        onde.append("(p.nome ILIKE %(q)s OR p.codigo ILIKE %(q)s "
                    "OR c.nome ILIKE %(q)s OR p.escopo ILIKE %(q)s)")
        p["q"] = f"%{busca.strip()}%"
    filtro = ("WHERE " + " AND ".join(onde)) if onde else ""
    linhas = pglocal.query(f"""
        SELECT {_COLUNAS}, c.nome AS conta_nome, c.ava_agrupamento AS conta_ava,
               o.codigo AS oportunidade_codigo, t.codigo AS contrato_codigo,
               coalesce(l.lanes, 0) AS lanes_n, l.receita AS receita_lanes,
               coalesce(l.sem_preco, 0) AS lanes_sem_preco,
               a.ultimo AS ultimo_andamento, coalesce(a.n, 0) AS n_andamentos
        FROM crm_projetos p
        JOIN crm_contas c ON c.id = p.conta_id
        LEFT JOIN crm_oportunidades o ON o.id = p.oportunidade_id
        LEFT JOIN crm_contratos t ON t.id = p.contrato_id
        {_AGREGADO}
        {_ANDAMENTO}
        {filtro}
        ORDER BY p.deadline NULLS LAST, p.id DESC
    """, p, esquema=_esq(esquema))
    return [_linha(r) for r in linhas]


def obter(projeto_id: int, *, com_erp: bool = True,
          esquema: str | None = None) -> dict | None:
    esq = _esq(esquema)
    r = pglocal.um(f"""
        SELECT {_COLUNAS}, c.nome AS conta_nome, c.ava_agrupamento AS conta_ava,
               o.codigo AS oportunidade_codigo, o.titulo AS oportunidade_titulo,
               t.codigo AS contrato_codigo,
               coalesce(l.lanes, 0) AS lanes_n, l.receita AS receita_lanes,
               coalesce(l.sem_preco, 0) AS lanes_sem_preco,
               a.ultimo AS ultimo_andamento, coalesce(a.n, 0) AS n_andamentos
        FROM crm_projetos p
        JOIN crm_contas c ON c.id = p.conta_id
        LEFT JOIN crm_oportunidades o ON o.id = p.oportunidade_id
        LEFT JOIN crm_contratos t ON t.id = p.contrato_id
        {_AGREGADO}
        {_ANDAMENTO}
        WHERE p.id = %s
    """, (int(projeto_id),), esquema=esq)
    if not r:
        return None
    from . import oportunidades as op
    d = _linha(r)
    ref = precificacao.referencia_ckm()
    d["lanes_detalhe"] = op.lanes(projeto_id=projeto_id, referencia=ref,
                                  esquema=esq)
    d["resumo_lanes"] = precificacao.resumir(d["lanes_detalhe"])
    d["referencia_ckm"] = ref
    d["historico"] = andamentos(projeto_id, esquema=esq)
    d["realizado"] = _realizado(d, esq) if com_erp else None
    return d


def _realizado(d: dict, esq: str | None) -> dict:
    """O que o projeto ADICIONOU ao faturamento do cliente — não "quanto do
    prometido foi entregue", porque essa pergunta o ERP não sabe responder.

    A LIMITAÇÃO QUE DEFINE ESTE BLOCO: **a receita do AVA é do CLIENTE, não do
    projeto.** Não há campo de projeto na programação de embarque, e não vai
    haver. A primeira versão daqui dividia a receita do cliente pelo ROB
    prometido e chamava o resultado de "atingimento" — na bancada, com dado
    real, deu **480%**: R$ 2,05 mi/mês de faturamento da TUPY sobre R$ 428 mil
    prometidos por UM projeto. O número estava aritmeticamente certo e era uma
    mentira com sinal de porcentagem, do tipo que ninguém questiona porque vem
    com casa decimal.

    O que se mede aqui, então, é a VARIAÇÃO: quanto o cliente faturava por mês
    antes de o projeto começar, quanto fatura desde então, e a diferença. Essa
    diferença é comparável ao ROB prometido, porque as duas são incrementos —
    e é a leitura que alguém de fato quer ("prometemos R$ 428 mil por mês; o
    faturamento subiu quanto?").

    Continua não sendo prova, e a tela continua dizendo por quê:
      - a variação também absorve sazonalidade, reajuste e qualquer outro
        negócio que tenha entrado no mesmo período;
      - com DOIS OU MAIS projetos abertos na conta, nem a variação é
        atribuível a um deles — `atribuivel` fica falso e a tela avisa.

    É a mesma disciplina do "664 de 836 rastreadores sem sinal": o denominador
    precisa conter só o que o numerador pode explicar. Quando não contém,
    diz-se — e quando nem assim dá, mede-se outra coisa.
    """
    ag = d.get("conta_ava")
    saida = {"disponivel": False, "motivo": "", "prometido": d.get("rob_mensal"),
             "atribuivel": False, "projetos_na_conta": None, "meses": [],
             "media_antes": None, "media_depois": None, "variacao": None,
             "atingimento": None, "desde": None, "meses_antes": 0,
             "meses_depois": 0}
    if not ag:
        saida["motivo"] = ("a conta não está vinculada a um grupo econômico do "
                           "ERP — sem o vínculo não há receita real para "
                           "comparar")
        return saida
    inicio = d.get("inicio_real")
    if not inicio:
        saida["motivo"] = ("o projeto ainda não começou (sem data de início "
                           "real) — não há período depois para comparar")
        return saida

    n = pglocal.um(
        "SELECT count(*) AS n FROM crm_projetos WHERE conta_id=%s "
        "AND status IN ('nao_iniciado','implantacao','em_execucao')",
        (d["conta_id"],), esquema=esq)
    saida["projetos_na_conta"] = int((n or {}).get("n") or 0)
    saida["atribuivel"] = saida["projetos_na_conta"] <= 1

    try:
        serie = ava.serie_mensal(ag)
    except Exception as exc:  # noqa: BLE001
        saida["motivo"] = f"o ERP não respondeu ({type(exc).__name__})"
        return saida

    corte = inicio[:7]
    # O mês do início fica FORA das duas metades: ele é parcial dos dois lados,
    # e somá-lo a qualquer uma delas puxa a média para o lado errado.
    antes = [m for m in serie if m["mes"] < corte]
    depois = [m for m in serie if m["mes"] > corte]
    saida.update(desde=corte, meses=serie, meses_antes=len(antes),
                 meses_depois=len(depois))
    if not depois:
        saida["motivo"] = ("o projeto começou neste mês — ainda não há mês "
                           "fechado depois do início para comparar")
        saida["disponivel"] = True
        return saida
    if not antes:
        saida["motivo"] = ("não há histórico do cliente antes do início — sem "
                           "a base, a variação não tem contra o que ser medida")
        saida["disponivel"] = True
        saida["media_depois"] = sum(m["receita"] for m in depois) / len(depois)
        return saida

    saida["disponivel"] = True
    saida["media_antes"] = sum(m["receita"] for m in antes) / len(antes)
    saida["media_depois"] = sum(m["receita"] for m in depois) / len(depois)
    saida["variacao"] = saida["media_depois"] - saida["media_antes"]
    if saida["prometido"]:
        saida["atingimento"] = saida["variacao"] / saida["prometido"]
    return saida


def andamentos(projeto_id: int, *, esquema: str | None = None) -> list[dict]:
    return pglocal.query(
        "SELECT id, ts, usuario, texto, status_de, status_para, percentual, "
        "       versao "
        "FROM crm_projeto_andamentos WHERE projeto_id=%s ORDER BY ts DESC, id DESC",
        (int(projeto_id),), esquema=_esq(esquema))


# ------------------------------------------------------------------ escrita --

def gravar(dados: dict, *, usuario: str = "", projeto_id: int | None = None,
           esquema: str | None = None) -> dict:
    esq = _esq(esquema)
    init_db(esq)
    conta_id = inteiro(dados.get("conta_id"), "a conta", minimo=1,
                       maximo=99999999)
    if not pglocal.um("SELECT 1 FROM crm_contas WHERE id=%s", (conta_id,),
                      esquema=esq):
        raise DadoInvalido("Esta conta não existe mais.")
    resp_id, resp_nome = pessoa(dados.get("responsavel_id"),
                                dados.get("responsavel_nome"), "Responsável",
                                esquema=esq)
    status = escolha(dados.get("status"), STATUS, "O status",
                     padrao="nao_iniciado")
    motivo, detalhe = _encerramento(dados, status)
    campos = {
        "conta_id": conta_id,
        "oportunidade_id": _ref(dados.get("oportunidade_id")),
        "contrato_id": _ref(dados.get("contrato_id")),
        "nome": texto(dados.get("nome"), "o nome do projeto",
                      maximo=TITULO_MAX, obrigatorio=True),
        "escopo": texto(dados.get("escopo"), "o escopo", maximo=120),
        "detalhe": texto(dados.get("detalhe"), "o detalhe da operação"),
        "status": status,
        "recebimento": data_br(dados.get("recebimento"), "a data de recebimento"),
        "inicio_previsto": data_br(dados.get("inicio_previsto"),
                                   "o início previsto"),
        "deadline": data_br(dados.get("deadline"), "o prazo"),
        "inicio_real": data_br(dados.get("inicio_real"), "o início real"),
        "entrega": data_br(dados.get("entrega"), "a data de entrega"),
        "aceite": data_br(dados.get("aceite"), "a data de aceite"),
        "prazo_cliente_dias": (None if dados.get("prazo_cliente_dias") in (None, "")
                               else inteiro(dados.get("prazo_cliente_dias"),
                                            "o prazo do cliente", minimo=0,
                                            maximo=3650)),
        "solicitante": texto(dados.get("solicitante"), "o solicitante",
                             maximo=TITULO_MAX),
        "responsavel_id": resp_id, "responsavel_nome": resp_nome,
        "rob_mensal_manual": valor_br(dados.get("rob_mensal_manual"),
                                      "o ROB mensal estimado"),
        "percentual": inteiro(dados.get("percentual"), "o percentual",
                              minimo=0, maximo=100, padrao=0),
        "motivo_encerramento": motivo, "encerrado_detalhe": detalhe,
        "observacoes": texto(dados.get("observacoes"), "as observações"),
    }
    _conferir_datas(campos)
    ts = agora()
    if projeto_id:
        antes = obter(projeto_id, com_erp=False, esquema=esq)
        if not antes:
            raise DadoInvalido("Este projeto não existe mais.")
        campos["alterado_por"], campos["alterado_em"] = usuario, ts
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(projeto_id)
        pglocal.executar(f"UPDATE crm_projetos SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo = int(projeto_id)
        if antes["status"] != status:
            _andamento(novo, usuario, "", antes["status"], status, None,
                       None, esq)
    else:
        ano, seq, codigo = proximo_codigo("crm_projetos", "PRJ", esquema=esq)
        campos.update({"ano": ano, "sequencia": seq, "codigo": codigo,
                       "versao": 1, "criado_por": usuario,
                       "alterado_por": usuario, "criado_em": ts,
                       "alterado_em": ts})
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_projetos({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo = int(r["id"])
        _andamento(novo, usuario, "Projeto criado.", None, status, 0, 1, esq)
    return obter(novo, com_erp=False, esquema=esq)


def _ref(v):
    return int(v) if v not in (None, "", 0, "0") else None


def _encerramento(dados: dict, status: str) -> tuple[str, str]:
    motivo = texto(dados.get("motivo_encerramento"), "o motivo",
                   maximo=40).lower()
    detalhe = texto(dados.get("encerrado_detalhe"), "o detalhe do encerramento")
    if status not in ("declinado", "cancelado"):
        return "", ""
    if not motivo:
        raise DadoInvalido(
            "Escolha o motivo do encerramento. É o único dado que transforma "
            "um projeto perdido em aprendizado — sem ele não dá para saber se "
            "o problema foi preço, prazo ou capacidade.")
    if motivo not in MOTIVOS:
        raise DadoInvalido(f"O motivo deve ser um de: {', '.join(MOTIVOS)}.")
    return motivo, detalhe


def _conferir_datas(c: dict) -> None:
    """Recusa a inversão AQUI, com a frase que explica.

    O CHECK do banco também recusa, e continua sendo a rede de baixo para a
    próxima tela que gravar sem passar por aqui — mas a mensagem dele
    ("violates check constraint crm_proj_ordem_ck") não diz a ninguém qual das
    três datas está fora de ordem.
    """
    pares = [("recebimento", "inicio_real", "o início real não pode ser "
                                            "anterior ao recebimento"),
             ("inicio_real", "entrega", "a entrega não pode ser anterior ao "
                                        "início real"),
             ("entrega", "aceite", "o aceite não pode ser anterior à entrega")]
    for a, b, msg in pares:
        if c.get(a) and c.get(b) and c[b] < c[a]:
            raise DadoInvalido(f"Datas fora de ordem: {msg}.")
    if c["status"] == "entregue" and not c.get("entrega"):
        raise DadoInvalido(
            "Projeto entregue precisa da data de entrega — é dela que sai o "
            "cumprimento de prazo.")
    if c["status"] != "entregue" and c.get("entrega"):
        raise DadoInvalido(
            "Só projeto com status Entregue pode ter data de entrega. Mude o "
            "status ou apague a data.")


def _andamento(projeto_id: int, usuario: str, texto_: str, de: str | None,
               para: str | None, pct: int | None, versao: int | None,
               esq: str | None) -> None:
    pglocal.executar(
        "INSERT INTO crm_projeto_andamentos"
        "(projeto_id, ts, usuario, texto, status_de, status_para, percentual,"
        " versao) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (int(projeto_id), agora(), usuario, texto_, de, para, pct, versao),
        esquema=esq)


def registrar_andamento(projeto_id: int, *, texto_: str = "",
                        status: str = "", percentual=None, usuario: str = "",
                        esquema: str | None = None) -> dict:
    """O caminho curto do acompanhamento — escrever o que andou.

    Rota própria, e não o formulário completo, pela mesma razão do andamento de
    ação na Gestão: é a operação FREQUENTE, e obrigar o formulário inteiro para
    dizer "o cliente confirmou a doca" é o que faz o histórico ficar vazio.
    """
    esq = _esq(esquema)
    p = obter(projeto_id, com_erp=False, esquema=esq)
    if not p:
        raise DadoInvalido("Este projeto não existe mais.")
    txt = texto(texto_, "o andamento")
    novo_status = escolha(status, STATUS, "O status", padrao=p["status"])
    pct = (None if percentual in (None, "") else
           inteiro(percentual, "o percentual", minimo=0, maximo=100))
    if not txt and novo_status == p["status"] and pct is None:
        raise DadoInvalido("Escreva o que andou, mude o status ou informe o "
                           "percentual.")
    if novo_status != p["status"]:
        if novo_status in ("declinado", "cancelado"):
            raise DadoInvalido(
                "Encerrar um projeto pede o motivo — use Editar, que tem o "
                "campo. O andamento serve para o que anda, não para o que "
                "para.")
        if novo_status == "entregue":
            raise DadoInvalido(
                "Marcar como entregue pede a data da entrega — use Editar.")
        sets = {"status": novo_status, "alterado_por": usuario,
                "alterado_em": agora(), "id": int(projeto_id)}
        pglocal.executar(
            "UPDATE crm_projetos SET status=%(status)s, "
            "alterado_por=%(alterado_por)s, alterado_em=%(alterado_em)s "
            "WHERE id=%(id)s", sets, esquema=esq)
    if pct is not None:
        pglocal.executar(
            "UPDATE crm_projetos SET percentual=%s WHERE id=%s",
            (pct, int(projeto_id)), esquema=esq)
    _andamento(projeto_id, usuario, txt,
               p["status"] if novo_status != p["status"] else None,
               novo_status if novo_status != p["status"] else None,
               pct, None, esq)
    return obter(projeto_id, esquema=esq)


def de_oportunidade(oportunidade_id: int, dados: dict | None = None, *,
                    usuario: str = "", esquema: str | None = None) -> dict:
    """Abre o projeto a partir da oportunidade GANHA, copiando as lanes.

    CÓPIA e não referência, pelo mesmo motivo do contrato: a proposta é o que
    foi oferecido e o projeto é o que se combinou entregar. Apontar o projeto
    para as lanes da oportunidade faria uma correção na proposta reescrever o
    escopo prometido — e é justamente contra esse escopo que o realizado vai
    ser medido depois.
    """
    esq = _esq(esquema)
    init_db(esq)
    o = pglocal.um(
        "SELECT id, conta_id, titulo, estagio, meses_contrato, dono_id, "
        "       dono_nome FROM crm_oportunidades WHERE id=%s",
        (int(oportunidade_id),), esquema=esq)
    if not o:
        raise DadoInvalido("Esta oportunidade não existe mais.")
    if o["estagio"] != "ganha":
        raise DadoInvalido(
            "O projeto nasce da oportunidade GANHA. Esta está em "
            f"“{o['estagio']}” — mova para Ganha antes de abrir a entrega.")
    ja = pglocal.um("SELECT codigo FROM crm_projetos WHERE oportunidade_id=%s",
                    (int(oportunidade_id),), esquema=esq)
    if ja:
        raise DadoInvalido(
            f"Esta oportunidade já gerou o projeto {ja['codigo']}. Um segundo "
            f"projeto para a mesma venda dividiria o ROB prometido em dois.")
    base = {"conta_id": o["conta_id"], "nome": o["titulo"],
            "oportunidade_id": o["id"], "responsavel_id": o["dono_id"],
            "responsavel_nome": o["dono_nome"] if not o["dono_id"] else "",
            "recebimento": hoje().isoformat(), "status": "nao_iniciado"}
    p = gravar({**base, **(dados or {})}, usuario=usuario, esquema=esq)
    n = pglocal.executar("""
        INSERT INTO crm_lanes(
            projeto_id, origem_cidade, origem_uf, destino_cidade, destino_uf,
            km, km_vazio, tipo_veiculo, eixos, tipo_carga, viagens_mes,
            valor_viagem, pedagio, observacoes, ordem)
        SELECT %(prj)s, origem_cidade, origem_uf, destino_cidade, destino_uf,
               km, km_vazio, tipo_veiculo, eixos, tipo_carga, viagens_mes,
               valor_viagem, pedagio, observacoes, ordem
        FROM crm_lanes WHERE oportunidade_id = %(opo)s
    """, {"prj": p["id"], "opo": int(oportunidade_id)}, esquema=esq)
    d = obter(p["id"], com_erp=False, esquema=esq)
    d["lanes_copiadas"] = n
    return d


def excluir(projeto_id: int, *, esquema: str | None = None) -> None:
    """Projeto que não vingou se DECLINA, não se apaga — o histórico do que se
    tentou entregar é o que explica a capacidade da operação. A exclusão existe
    para o registro criado por engano."""
    pglocal.executar("DELETE FROM crm_projetos WHERE id=%s",
                     (int(projeto_id),), esquema=_esq(esquema))


def catalogo() -> dict:
    return {
        "status": [{"valor": s, "rotulo": ROTULO_STATUS[s]} for s in STATUS],
        "status_abertos": list(STATUS_ABERTOS),
        "motivos": [{"valor": m, "rotulo": ROTULO_MOTIVO[m]} for m in MOTIVOS],
        "escopos": list(ESCOPOS),
        "parado_dias": PARADO_DIAS,
    }
