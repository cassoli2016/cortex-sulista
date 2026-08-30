"""Contas e contatos — a empresa e as pessoas dela.

A conta é o centro do CRM: é dela que penduram oportunidades, atividades,
interações e contratos, e é ela que carrega o vínculo com o ERP
(`ava_agrupamento`) por onde entra a receita real.

DUAS REGRAS QUE NÃO SE NEGOCIAM AQUI:

- **Situação não é campo, é leitura.** `prospect`/`ativo`/`parado` sai de
  `api/crm/ava.py` a cada consulta. Ver o cabeçalho de `0026_crm.sql`.
- **Conta não se apaga, se arquiva.** `DELETE` levaria em cascata o histórico
  de interações, que é o ativo do CRM — e a conta que alguém quer apagar é
  justamente a que tem histórico ruim, que é o que mais interessa guardar.
"""
from __future__ import annotations

from .. import pglocal
from . import ava
from .comum import (DadoInvalido, ORIGENS, SEGMENTOS, TITULO_MAX, _esq, agora,
                    cnpj, cnpj_fmt, dias_desde, email, escolha, hoje, init_db,
                    inteiro, iso, pessoa, telefone, telefone_fmt, texto, uf)
from .comum import PAPEIS_CONTATO, ROTULO_PAPEL

# Lista de colunas NUM LUGAR SÓ. Estava repetida em `listar()` e `obter()` no
# módulo de modelos do WhatsApp, e acrescentar campo em uma e esquecer da outra
# fez o ENVIO trabalhar com a regra pela metade. Aqui o custo seria uma ficha
# que não mostra o campo novo — mais discreto e igualmente chato de achar.
_COLUNAS = """
    c.id, c.nome, c.nome_fantasia, c.cnpj, c.ava_agrupamento, c.ava_nome,
    c.segmento, c.origem, c.cidade, c.uf, c.site, c.dono_id, c.dono_nome,
    c.observacoes, c.arquivada, c.criado_por, c.criado_em, c.alterado_por,
    c.alterado_em
"""

_COLUNAS_CONTATO = """
    id, conta_id, nome, cargo, papel, email, telefone, principal, ativo,
    observacoes, criado_em, alterado_em
"""


def _linha(r: dict) -> dict:
    d = dict(r)
    d["cnpj_fmt"] = cnpj_fmt(d.get("cnpj") or "")
    d["arquivada"] = bool(d.get("arquivada"))
    return d


# ------------------------------------------------------------------ leitura --

def listar(*, busca: str = "", situacao: str = "", dono_id: int | None = None,
           segmento: str = "", incluir_arquivadas: bool = False,
           parada_dias: int = ava.PARADA_DIAS,
           esquema: str | None = None) -> list[dict]:
    """As contas, já com a leitura da carteira real do ERP.

    O filtro de SITUAÇÃO é aplicado em PYTHON, depois de enriquecer — e não em
    SQL — porque a situação não existe no banco local: ela sai do AVA. Tentar
    filtrá-la no `WHERE` exigiria gravar a coluna, que é exatamente o que este
    módulo não faz.

    O enriquecimento é UMA consulta ao AVA para todas as contas da lista (ver
    `ava.carteira`), não uma por conta.
    """
    onde = [] if incluir_arquivadas else ["c.arquivada = 0"]
    p: dict = {}
    if busca.strip():
        onde.append("(c.nome ILIKE %(q)s OR c.nome_fantasia ILIKE %(q)s "
                    "OR c.cnpj LIKE %(qd)s OR c.ava_nome ILIKE %(q)s)")
        p["q"] = f"%{busca.strip()}%"
        p["qd"] = f"%{''.join(ch for ch in busca if ch.isdigit())}%" or "%"
    if dono_id:
        onde.append("c.dono_id = %(dono)s")
        p["dono"] = int(dono_id)
    if segmento.strip():
        onde.append("c.segmento = %(seg)s")
        p["seg"] = segmento.strip()
    filtro = ("WHERE " + " AND ".join(onde)) if onde else ""
    linhas = pglocal.query(
        f"SELECT {_COLUNAS} FROM crm_contas c {filtro} ORDER BY c.nome",
        p, esquema=_esq(esquema))
    contas = [_linha(r) for r in linhas]
    _enriquecer(contas, parada_dias)
    if situacao.strip():
        contas = [c for c in contas if c["situacao"] == situacao.strip()]
    return contas


def _enriquecer(contas: list[dict], parada_dias: int) -> None:
    """Acrescenta receita real e situação, no lugar.

    Falha do AVA NÃO derruba a lista: as contas voltam com `situacao` =
    'indisponivel' e o motivo. O CRM continua sendo útil sem o ERP (a
    oportunidade, a atividade e o contato são todos do banco local), e trocar
    "a lista com uma coluna a menos" por "nenhuma lista" seria perder muito
    para ganhar nada.
    """
    codigos = [c["ava_agrupamento"] for c in contas if c.get("ava_agrupamento")]
    try:
        dados = ava.carteira(codigos) if codigos else {}
        falhou = None
    except Exception as exc:  # noqa: BLE001
        dados, falhou = {}, type(exc).__name__
    for c in contas:
        ag = c.get("ava_agrupamento")
        d = dados.get(int(ag)) if ag else None
        if falhou and ag:
            c.update({"situacao": "indisponivel", "dias_sem_viagem": None,
                      "erp_indisponivel": falhou})
        else:
            c.update(ava.situacao(ag, d, parada_dias))
        c["receita_12m"] = (d or {}).get("receita_12m")
        c["receita_90d"] = (d or {}).get("receita_90d")
        c["viagens_12m"] = (d or {}).get("viagens_12m")
        c["km_12m"] = (d or {}).get("km_12m")
        c["ultima_viagem"] = (d or {}).get("ultima_viagem")


def obter(conta_id: int, *, com_erp: bool = True,
          esquema: str | None = None) -> dict | None:
    """A ficha 360: cadastro, contatos, pipeline, histórico e a receita real.

    Vai tudo numa chamada porque a ficha não desenha nada sem o conjunto, e
    seis chamadas para montar uma tela são seis chances de meia tela na rede
    ruim — o mesmo motivo do `/api/gestao/painel`.
    """
    esq = _esq(esquema)
    r = pglocal.um(f"SELECT {_COLUNAS} FROM crm_contas c WHERE c.id=%s",
                   (int(conta_id),), esquema=esq)
    if not r:
        return None
    conta = _linha(r)
    _enriquecer([conta], ava.PARADA_DIAS)

    conta["contatos"] = contatos(conta_id, esquema=esq)
    conta["oportunidades"] = _oportunidades_da_conta(conta_id, esq)
    conta["atividades"] = _atividades_da_conta(conta_id, esq)
    conta["interacoes"] = _interacoes_da_conta(conta_id, esq)
    conta["contratos"] = _contratos_da_conta(conta_id, esq)

    # "Há quanto tempo ninguém fala com este cliente" — a pergunta central do
    # CRM, e a que um cadastro bonito não responde. None (nunca houve contato)
    # e 0 (falaram hoje) são estados diferentes e a tela os mostra diferente.
    ultima = conta["interacoes"][0]["ts"] if conta["interacoes"] else None
    conta["dias_sem_contato"] = dias_desde(ultima)
    conta["ultimo_contato"] = ultima

    if com_erp and conta.get("ava_agrupamento"):
        try:
            serie = ava.serie_mensal(conta["ava_agrupamento"])
            conta["serie_mensal"] = ava.preencher_meses(serie, 24)
            conta["rotas_erp"] = ava.rotas(conta["ava_agrupamento"])
        except Exception as exc:  # noqa: BLE001
            conta["serie_mensal"] = []
            conta["rotas_erp"] = []
            conta["erp_indisponivel"] = type(exc).__name__
    else:
        conta["serie_mensal"] = []
        conta["rotas_erp"] = []
    return conta


def _oportunidades_da_conta(conta_id: int, esq: str | None) -> list[dict]:
    from . import oportunidades as op
    return op.listar(conta_id=conta_id, incluir_fechadas=True, esquema=esq)


def _atividades_da_conta(conta_id: int, esq: str | None) -> list[dict]:
    from . import atividades as at
    return at.listar(conta_id=conta_id, esquema=esq)


def _interacoes_da_conta(conta_id: int, esq: str | None) -> list[dict]:
    from . import atividades as at
    return at.interacoes(conta_id=conta_id, esquema=esq)


def _contratos_da_conta(conta_id: int, esq: str | None) -> list[dict]:
    from . import contratos as ct
    return ct.listar(conta_id=conta_id, esquema=esq)


# ------------------------------------------------------------------ escrita --

def gravar(dados: dict, *, usuario: str = "", conta_id: int | None = None,
           esquema: str | None = None) -> dict:
    """Cria ou edita. Devolve a conta gravada, já enriquecida."""
    esq = _esq(esquema)
    init_db(esq)
    nome = texto(dados.get("nome"), "o nome da conta", maximo=TITULO_MAX,
                 obrigatorio=True)
    doc = cnpj(dados.get("cnpj"))
    dono_id, dono_nome = pessoa(dados.get("dono_id"), dados.get("dono_nome"),
                                "Responsável", esquema=esq)
    vinculo, vinculo_nome = _resolver_vinculo(dados, conta_id, esq)

    campos = {
        "nome": nome,
        "nome_fantasia": texto(dados.get("nome_fantasia"), "o nome fantasia",
                               maximo=TITULO_MAX),
        "cnpj": doc,
        "ava_agrupamento": vinculo,
        "ava_nome": vinculo_nome,
        "segmento": texto(dados.get("segmento"), "o segmento", maximo=120),
        "origem": texto(dados.get("origem"), "a origem", maximo=120),
        "cidade": texto(dados.get("cidade"), "a cidade", maximo=120),
        "uf": uf(dados.get("uf"), "a UF"),
        "site": texto(dados.get("site"), "o site", maximo=300),
        "dono_id": dono_id, "dono_nome": dono_nome,
        "observacoes": texto(dados.get("observacoes"), "as observações"),
    }
    ts = agora()
    if conta_id:
        campos["alterado_por"], campos["alterado_em"] = usuario, ts
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(conta_id)
        pglocal.executar(f"UPDATE crm_contas SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo_id = int(conta_id)
    else:
        campos["criado_por"] = campos["alterado_por"] = usuario
        campos["criado_em"] = campos["alterado_em"] = ts
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_contas({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo_id = int(r["id"])
    return obter(novo_id, com_erp=False, esquema=esq)


def _resolver_vinculo(dados: dict, conta_id: int | None,
                      esq: str | None) -> tuple[int | None, str]:
    """O código do grupo econômico do ERP, conferido contra o cadastro real.

    Confere que o agrupamento EXISTE, pelo mesmo motivo de `pessoa()` conferir
    o usuário: um código digitado errado gravaria uma conta que parece
    vinculada e cuja receita vem sempre vazia — e "cliente sem faturamento" é
    uma leitura de negócio, não de cadastro. O erro se disfarçaria de fato.

    E confere que o grupo não está JÁ vinculado a outra conta. O banco tem o
    índice único, mas a mensagem dele ("duplicate key value violates unique
    constraint") não diz a quem — e a quem é a única coisa útil aqui.
    """
    bruto = dados.get("ava_agrupamento")
    if bruto in (None, "", 0, "0"):
        return None, ""
    codigo = inteiro(bruto, "o grupo econômico do ERP", minimo=1,
                     maximo=99999999)
    try:
        catalogo = {int(a["codigo"]): a["nome"] for a in ava.agrupamentos()}
    except Exception:  # noqa: BLE001
        # ERP fora do ar: aceita o vínculo sem conferir, e o nome fica com o
        # que a tela mandou. Recusar aqui impediria de cadastrar cliente numa
        # manhã em que o AVA está lento — e o vínculo errado se corrige, a
        # oportunidade perdida não.
        return codigo, texto(dados.get("ava_nome"), "o nome no ERP", maximo=TITULO_MAX)
    if codigo not in catalogo:
        raise DadoInvalido(
            f"O grupo econômico {codigo} não existe no cadastro do ERP. "
            f"Escolha um da lista — o vínculo é o que traz a receita real.")
    ocupada = pglocal.um(
        "SELECT id, nome FROM crm_contas WHERE ava_agrupamento=%s AND id <> %s",
        (codigo, int(conta_id or 0)), esquema=esq)
    if ocupada:
        raise DadoInvalido(
            f"O grupo {catalogo[codigo]!r} já está vinculado à conta "
            f"{ocupada['nome']!r}. Duas contas no mesmo grupo dividiriam a "
            f"receita e as oportunidades em duas metades.")
    return codigo, catalogo[codigo]


def arquivar(conta_id: int, *, arquivada: bool = True, usuario: str = "",
             esquema: str | None = None) -> dict:
    esq = _esq(esquema)
    pglocal.executar(
        "UPDATE crm_contas SET arquivada=%s, alterado_por=%s, alterado_em=%s "
        "WHERE id=%s",
        (1 if arquivada else 0, usuario, agora(), int(conta_id)), esquema=esq)
    return obter(conta_id, com_erp=False, esquema=esq)


def pendencias(conta_id: int, esquema: str | None = None) -> dict:
    """O que a conta perde ao ser excluída — para a confirmação da tela dizer.

    Mesma regra da exclusão de ata na Gestão: a confirmação diz quantas ações
    ficarão órfãs, porque é a consequência que não se vê ao clicar. Aqui o
    CASCADE é mais duro (leva oportunidades e histórico junto), então a tela
    precisa mostrar o número ANTES.
    """
    esq = _esq(esquema)
    r = pglocal.um("""
        SELECT (SELECT count(*) FROM crm_oportunidades WHERE conta_id=%(c)s) AS opos,
               (SELECT count(*) FROM crm_interacoes   WHERE conta_id=%(c)s) AS inter,
               (SELECT count(*) FROM crm_contratos    WHERE conta_id=%(c)s) AS ctrs,
               (SELECT count(*) FROM crm_contatos     WHERE conta_id=%(c)s) AS cts
    """, {"c": int(conta_id)}, esquema=esq) or {}
    return {"oportunidades": int(r.get("opos") or 0),
            "interacoes": int(r.get("inter") or 0),
            "contratos": int(r.get("ctrs") or 0),
            "contatos": int(r.get("cts") or 0)}


def excluir(conta_id: int, *, esquema: str | None = None) -> None:
    """Exclusão de verdade — só para conta cadastrada por engano.

    A tela oferece ARQUIVAR como caminho normal e só mostra este quando a conta
    não tem nada pendurado (`pendencias` toda zerada). Não é a rota que decide
    isso: é aqui, porque a regra tem de valer também para a próxima tela que
    chamar.
    """
    esq = _esq(esquema)
    p = pendencias(conta_id, esq)
    if any(p.values()):
        tem = ", ".join(f"{v} {k}" for k, v in p.items() if v)
        raise DadoInvalido(
            f"Esta conta tem {tem} e não pode ser excluída — apagá-la levaria "
            f"o histórico junto. Use Arquivar: ela sai da lista e o registro "
            f"fica.")
    pglocal.executar("DELETE FROM crm_contas WHERE id=%s", (int(conta_id),),
                     esquema=esq)


# ----------------------------------------------------------------- contatos --

def contatos(conta_id: int, *, incluir_inativos: bool = False,
             esquema: str | None = None) -> list[dict]:
    onde = "conta_id=%s" + ("" if incluir_inativos else " AND ativo=1")
    linhas = pglocal.query(
        f"SELECT {_COLUNAS_CONTATO} FROM crm_contatos WHERE {onde} "
        "ORDER BY principal DESC, nome",
        (int(conta_id),), esquema=_esq(esquema))
    return [{**c,
             "principal": bool(c["principal"]), "ativo": bool(c["ativo"]),
             "papel_rotulo": ROTULO_PAPEL.get(c["papel"], c["papel"]),
             "telefone_fmt": telefone_fmt(c["telefone"])}
            for c in linhas]


def gravar_contato(dados: dict, *, usuario: str = "",
                   contato_id: int | None = None,
                   esquema: str | None = None) -> dict:
    esq = _esq(esquema)
    init_db(esq)
    conta_id = inteiro(dados.get("conta_id"), "a conta", minimo=1,
                       maximo=99999999)
    if not pglocal.um("SELECT 1 FROM crm_contas WHERE id=%s", (conta_id,),
                      esquema=esq):
        raise DadoInvalido("Esta conta não existe mais.")
    campos = {
        "conta_id": conta_id,
        "nome": texto(dados.get("nome"), "o nome do contato", maximo=TITULO_MAX,
                      obrigatorio=True),
        "cargo": texto(dados.get("cargo"), "o cargo", maximo=120),
        "papel": escolha(dados.get("papel"), PAPEIS_CONTATO, "O papel",
                         padrao="operacional"),
        "email": email(dados.get("email")),
        "telefone": telefone(dados.get("telefone")),
        "principal": 1 if dados.get("principal") else 0,
        "ativo": 0 if dados.get("ativo") is False else 1,
        "observacoes": texto(dados.get("observacoes"), "as observações"),
    }
    ts = agora()
    if contato_id:
        campos["alterado_por"], campos["alterado_em"] = usuario, ts
        sets = ", ".join(f"{k}=%({k})s" for k in campos)
        campos["id"] = int(contato_id)
        pglocal.executar(f"UPDATE crm_contatos SET {sets} WHERE id=%(id)s",
                         campos, esquema=esq)
        novo = int(contato_id)
    else:
        campos["criado_por"] = campos["alterado_por"] = usuario
        campos["criado_em"] = campos["alterado_em"] = ts
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        r = pglocal.um(
            f"INSERT INTO crm_contatos({cols}) VALUES({vals}) RETURNING id",
            campos, esquema=esq)
        novo = int(r["id"])
    # Um principal por conta. A regra é aplicada AQUI e não por constraint
    # porque o índice único parcial recusaria a gravação com uma mensagem que
    # ninguém entende — enquanto o que a pessoa quis dizer ao marcar o segundo
    # é claramente "agora é este". Rebaixar o anterior faz o que ela quis.
    if campos["principal"]:
        pglocal.executar(
            "UPDATE crm_contatos SET principal=0 WHERE conta_id=%s AND id<>%s",
            (conta_id, novo), esquema=esq)
    r = pglocal.um(f"SELECT {_COLUNAS_CONTATO} FROM crm_contatos WHERE id=%s",
                   (novo,), esquema=esq)
    return {**r, "principal": bool(r["principal"]), "ativo": bool(r["ativo"]),
            "papel_rotulo": ROTULO_PAPEL.get(r["papel"], r["papel"]),
            "telefone_fmt": telefone_fmt(r["telefone"])}


def excluir_contato(contato_id: int, *, esquema: str | None = None) -> None:
    """Contato sai de verdade — ao contrário da conta.

    Aqui o CASCADE não leva histórico: `crm_interacoes.contato_id` e
    `crm_atividades.contato_id` são `ON DELETE SET NULL`, então a interação
    continua existindo, só deixa de apontar para a pessoa. É a diferença entre
    apagar o interlocutor e apagar a conversa.
    """
    pglocal.executar("DELETE FROM crm_contatos WHERE id=%s", (int(contato_id),),
                     esquema=_esq(esquema))


def catalogo() -> dict:
    """Listas de apoio dos formulários, num lugar só."""
    return {"segmentos": list(SEGMENTOS), "origens": list(ORIGENS),
            "papeis": [{"valor": p, "rotulo": ROTULO_PAPEL[p]}
                       for p in PAPEIS_CONTATO]}
