"""Atividades (o compromisso) e interações (o que aconteceu).

DUAS TABELAS, e a separação é a decisão central deste módulo. `crm_atividades`
é o que alguém VAI fazer: mutável, com prazo, com atraso derivado.
`crm_interacoes` é o que ACONTECEU: append-only. Numa tabela só, editar o
registro de uma visita para virar "tarefa concluída" apaga a prova de que a
visita houve — e é esse histórico que responde "há quanto tempo ninguém fala
com este cliente", a pergunta que o CRM existe para responder.

NÃO EXISTE STATUS "ATRASADA". Atraso é `quando < hoje AND status = 'aberta'`,
calculado a cada leitura — a mesma regra de `ges_acoes`, pelo mesmo motivo:
status de atraso gravado precisa de alguém para virar, e no dia em que a rotina
não roda a tela diz que está tudo em dia.
"""
from __future__ import annotations

from .. import pglocal
from .comum import (CANAIS, DadoInvalido, RESUMO_MAX, ROTULO_ATIVIDADE,
                    SENTIDOS, STATUS_ATIVIDADE, TIPOS_ATIVIDADE, TITULO_MAX,
                    _esq, agora, data_br, dias_desde, escolha, hoje, init_db,
                    inteiro, iso, pessoa, texto)

_COLUNAS = """
    a.id, a.conta_id, a.oportunidade_id, a.contato_id, a.tipo, a.assunto,
    a.detalhe, a.quando, a.hora, a.responsavel_id, a.responsavel_nome,
    a.status, a.concluida_em, a.criado_por, a.criado_em, a.alterado_por,
    a.alterado_em
"""

_COLUNAS_INTER = """
    i.id, i.conta_id, i.oportunidade_id, i.contato_id, i.canal, i.sentido,
    i.ts, i.usuario, i.resumo, i.zap_envio_id, i.automatica
"""


def _linha(r: dict) -> dict:
    d = dict(r)
    iso(d, "quando")
    d["tipo_rotulo"] = ROTULO_ATIVIDADE.get(d["tipo"], d["tipo"])
    # A regra do cabeçalho, num lugar só.
    d["atrasada"] = bool(d["status"] == "aberta" and d.get("quando")
                         and d["quando"] < hoje().isoformat())
    if d.get("quando"):
        from datetime import date as _d
        d["dias"] = (_d.fromisoformat(d["quando"]) - hoje()).days
    else:
        d["dias"] = None
    d["hoje"] = bool(d.get("quando") == hoje().isoformat())
    return d


# ------------------------------------------------------- atividades: leitura --

def listar(*, conta_id: int | None = None, oportunidade_id: int | None = None,
           responsavel_id: int | None = None, status: str = "",
           atrasadas: bool = False, ate: str = "", limite: int = 300,
           esquema: str | None = None) -> list[dict]:
    onde: list[str] = []
    p: dict = {}
    if conta_id:
        # A atividade pendurada na OPORTUNIDADE também é da conta — sem o
        # segundo braço, a ficha da conta mostraria só metade da agenda dela,
        # e a metade que falta é justamente a das negociações em curso.
        onde.append("(a.conta_id = %(conta)s OR o.conta_id = %(conta)s)")
        p["conta"] = int(conta_id)
    if oportunidade_id:
        onde.append("a.oportunidade_id = %(opo)s")
        p["opo"] = int(oportunidade_id)
    if responsavel_id:
        onde.append("a.responsavel_id = %(resp)s")
        p["resp"] = int(responsavel_id)
    if status.strip():
        onde.append("a.status = %(st)s")
        p["st"] = status.strip()
    if atrasadas:
        onde.append("a.status = 'aberta' AND a.quando < current_date")
    if ate.strip():
        onde.append("a.quando <= %(ate)s::date")
        p["ate"] = ate.strip()
    filtro = ("WHERE " + " AND ".join(onde)) if onde else ""
    p["lim"] = max(1, min(int(limite), 1000))
    linhas = pglocal.query(f"""
        SELECT {_COLUNAS},
               coalesce(c.nome, oc.nome) AS conta_nome,
               coalesce(a.conta_id, o.conta_id) AS conta_efetiva,
               o.codigo AS oportunidade_codigo, o.titulo AS oportunidade_titulo,
               ct.nome AS contato_nome
        FROM crm_atividades a
        LEFT JOIN crm_contas c ON c.id = a.conta_id
        LEFT JOIN crm_oportunidades o ON o.id = a.oportunidade_id
        LEFT JOIN crm_contas oc ON oc.id = o.conta_id
        LEFT JOIN crm_contatos ct ON ct.id = a.contato_id
        {filtro}
        ORDER BY (a.status = 'aberta') DESC, a.quando, a.hora, a.id
        LIMIT %(lim)s
    """, p, esquema=_esq(esquema))
    return [_linha(r) for r in linhas]


def contar(**filtros) -> int:
    """Total sem o LIMIT — para o hint dizer "X de Y".

    Top-N em tabela sem contador vira total falso: o `LIMIT 20` da tela de
    Veículos fazia o hint dizer "1.373 veículos" quando os ativos eram 1.414.
    """
    esquema = filtros.pop("esquema", None)
    filtros["limite"] = 100000
    return len(listar(esquema=esquema, **filtros))


def obter(atividade_id: int, *, esquema: str | None = None) -> dict | None:
    r = pglocal.um(f"""
        SELECT {_COLUNAS}, coalesce(c.nome, oc.nome) AS conta_nome,
               o.codigo AS oportunidade_codigo, ct.nome AS contato_nome
        FROM crm_atividades a
        LEFT JOIN crm_contas c ON c.id = a.conta_id
        LEFT JOIN crm_oportunidades o ON o.id = a.oportunidade_id
        LEFT JOIN crm_contas oc ON oc.id = o.conta_id
        LEFT JOIN crm_contatos ct ON ct.id = a.contato_id
        WHERE a.id = %s
    """, (int(atividade_id),), esquema=_esq(esquema))
    return _linha(r) if r else None


# ------------------------------------------------------- atividades: escrita --

def gravar(dados: dict, *, usuario: str = "", atividade_id: int | None = None,
           esquema: str | None = None) -> dict:
    esq = _esq(esquema)
    init_db(esq)
    conta_id = dados.get("conta_id")
    opo_id = dados.get("oportunidade_id")
    conta_id = int(conta_id) if conta_id not in (None, "", 0) else None
    opo_id = int(opo_id) if opo_id not in (None, "", 0) else None
    if conta_id is None and opo_id is None:
        raise DadoInvalido("A atividade precisa estar ligada a uma conta ou a "
                           "uma oportunidade — tarefa solta ninguém encontra "
                           "depois.")
    resp_id, resp_nome = pessoa(dados.get("responsavel_id"),
                                dados.get("responsavel_nome"), "Responsável",
                                esquema=esq)
    status = escolha(dados.get("status"), STATUS_ATIVIDADE, "O status",
                     padrao="aberta")
    campos = {
        "conta_id": conta_id, "oportunidade_id": opo_id,
        "contato_id": (int(dados["contato_id"])
                       if dados.get("contato_id") not in (None, "", 0) else None),
        "tipo": escolha(dados.get("tipo"), TIPOS_ATIVIDADE, "O tipo",
                        padrao="ligacao"),
        "assunto": texto(dados.get("assunto"), "o assunto", maximo=TITULO_MAX,
                         obrigatorio=True),
        "detalhe": texto(dados.get("detalhe"), "o detalhe"),
        "quando": data_br(dados.get("quando"), "a data", obrigatorio=True),
        "hora": texto(dados.get("hora"), "a hora", maximo=5),
        "responsavel_id": resp_id, "responsavel_nome": resp_nome,
        "status": status,
        # O CHECK do banco exige o par (status, concluida_em) coerente. Montar
        # o carimbo aqui e não deixar o banco recusar é o que transforma
        # "violates check constraint" numa gravação que simplesmente funciona.
        "concluida_em": agora() if status == "concluida" else None,
    }
    ts = agora()
    if atividade_id:
        campos["alterado_por"], campos["alterado_em"] = usuario, ts
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(atividade_id)
        pglocal.executar(f"UPDATE crm_atividades SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo = int(atividade_id)
    else:
        campos["criado_por"] = campos["alterado_por"] = usuario
        campos["criado_em"] = campos["alterado_em"] = ts
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_atividades({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo = int(r["id"])
    return obter(novo, esquema=esq)


def concluir(atividade_id: int, *, usuario: str = "", resumo: str = "",
             registrar_interacao: bool = True,
             esquema: str | None = None) -> dict:
    """Conclui a tarefa e — por padrão — registra a INTERAÇÃO correspondente.

    É aqui que as duas tabelas se encontram, e a ligação é deliberada: quem
    acabou de ligar para o cliente está com o resumo na cabeça, e é o único
    momento em que ele vai escrever. Pedir depois, num formulário separado, é o
    que faz o histórico ficar vazio — o mesmo raciocínio do andamento de ação
    ter rota própria na Gestão.

    A interação só nasce se a atividade tiver um TIPO que corresponde a
    contato. Concluir "montar proposta" não é ter falado com ninguém, e
    registrá-la como interação faria o "dias sem contato" da conta mentir para
    baixo — justamente o número que serve para cobrar contato.
    """
    esq = _esq(esquema)
    a = obter(atividade_id, esquema=esq)
    if not a:
        raise DadoInvalido("Esta atividade não existe mais.")
    if a["status"] == "concluida":
        raise DadoInvalido("Esta atividade já está concluída.")
    pglocal.executar(
        "UPDATE crm_atividades SET status='concluida', concluida_em=%s, "
        "alterado_por=%s, alterado_em=%s WHERE id=%s",
        (agora(), usuario, agora(), int(atividade_id)), esquema=esq)
    conta = a.get("conta_efetiva") or a.get("conta_id")
    if registrar_interacao and conta and a["tipo"] in CANAIS:
        registrar(
            {"conta_id": conta, "oportunidade_id": a.get("oportunidade_id"),
             "contato_id": a.get("contato_id"), "canal": a["tipo"],
             "sentido": "saida",
             "resumo": resumo or f"{a['tipo_rotulo']}: {a['assunto']}"},
            usuario=usuario, esquema=esq)
    return obter(atividade_id, esquema=esq)


def excluir(atividade_id: int, *, esquema: str | None = None) -> None:
    pglocal.executar("DELETE FROM crm_atividades WHERE id=%s",
                     (int(atividade_id),), esquema=_esq(esquema))


# ------------------------------------------------------------------ interações --

def interacoes(*, conta_id: int | None = None,
               oportunidade_id: int | None = None, limite: int = 100,
               esquema: str | None = None) -> list[dict]:
    """O histórico, do mais recente para o mais antigo."""
    onde: list[str] = []
    p: dict = {"lim": max(1, min(int(limite), 1000))}
    if conta_id:
        onde.append("i.conta_id = %(conta)s")
        p["conta"] = int(conta_id)
    if oportunidade_id:
        onde.append("i.oportunidade_id = %(opo)s")
        p["opo"] = int(oportunidade_id)
    filtro = ("WHERE " + " AND ".join(onde)) if onde else ""
    linhas = pglocal.query(f"""
        SELECT {_COLUNAS_INTER}, c.nome AS conta_nome, ct.nome AS contato_nome,
               o.codigo AS oportunidade_codigo
        FROM crm_interacoes i
        JOIN crm_contas c ON c.id = i.conta_id
        LEFT JOIN crm_contatos ct ON ct.id = i.contato_id
        LEFT JOIN crm_oportunidades o ON o.id = i.oportunidade_id
        {filtro}
        ORDER BY i.ts DESC, i.id DESC
        LIMIT %(lim)s
    """, p, esquema=_esq(esquema))
    return [{**r, "automatica": bool(r["automatica"]),
             "dias": dias_desde(r["ts"])} for r in linhas]


def registrar(dados: dict, *, usuario: str = "", automatica: bool = False,
              zap_envio_id: int | None = None,
              esquema: str | None = None) -> dict:
    """Grava uma interação. APPEND-ONLY: não há editar nem excluir.

    A ausência de `editar` é a funcionalidade. Interação editável deixa de ser
    prova de que o contato houve — e quem errou o texto acrescenta outra, como
    em `ges_andamentos`.
    """
    esq = _esq(esquema)
    init_db(esq)
    conta_id = inteiro(dados.get("conta_id"), "a conta", minimo=1,
                       maximo=99999999)
    if not pglocal.um("SELECT 1 FROM crm_contas WHERE id=%s", (conta_id,),
                      esquema=esq):
        raise DadoInvalido("Esta conta não existe mais.")
    campos = {
        "conta_id": conta_id,
        "oportunidade_id": (int(dados["oportunidade_id"])
                            if dados.get("oportunidade_id") not in (None, "", 0)
                            else None),
        "contato_id": (int(dados["contato_id"])
                       if dados.get("contato_id") not in (None, "", 0) else None),
        "canal": escolha(dados.get("canal"), CANAIS, "O canal", padrao="ligacao"),
        "sentido": escolha(dados.get("sentido"), SENTIDOS, "O sentido",
                           padrao="saida"),
        "ts": dados.get("ts") or agora(),
        "usuario": usuario,
        "resumo": texto(dados.get("resumo"), "o resumo", maximo=RESUMO_MAX),
        "zap_envio_id": zap_envio_id,
        "automatica": 1 if automatica else 0,
    }
    cols = ", ".join(campos)
    vals = ", ".join(f"%({k})s" for k in campos)
    r = pglocal.um(
        f"INSERT INTO crm_interacoes({cols}) VALUES({vals}) RETURNING id",
        campos, esquema=esq)
    novo = int(r["id"])
    linha = pglocal.um(f"""
        SELECT {_COLUNAS_INTER}, c.nome AS conta_nome, ct.nome AS contato_nome
        FROM crm_interacoes i
        JOIN crm_contas c ON c.id = i.conta_id
        LEFT JOIN crm_contatos ct ON ct.id = i.contato_id
        WHERE i.id = %s
    """, (novo,), esquema=esq)
    return {**linha, "automatica": bool(linha["automatica"]),
            "dias": dias_desde(linha["ts"])}


def catalogo() -> dict:
    return {
        "tipos": [{"valor": t, "rotulo": ROTULO_ATIVIDADE[t]}
                  for t in TIPOS_ATIVIDADE],
        "canais": [{"valor": c, "rotulo": ROTULO_ATIVIDADE.get(c, c)}
                   for c in CANAIS],
        "sentidos": [{"valor": "saida", "rotulo": "Nós procuramos"},
                     {"valor": "entrada", "rotulo": "O cliente procurou"}],
    }
