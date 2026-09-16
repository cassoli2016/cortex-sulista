# -*- coding: utf-8 -*-
"""O canal entre o setor de agregados e o proprietário — fila, não conversa.

Pedido de quem opera (16/09/2026), no molde do canal do RH do app do motorista
(`api/motorista/conversas.py`): **isto não é chat, é FILA COM ASSUNTO, DONO E
ESTADO**. A razão é a mesma de lá, e vale em dobro aqui — a casa já fala com o
agregado pelo WhatsApp, e um segundo canal sem estado seria só mais um lugar
onde a pergunta se perde. O que muda em relação a "mandei no zap": a fila diz
QUEM está atendendo, DESDE QUANDO e se ACABOU.

═══════════════════════════════════════════════════════════════════════════
O ESCOPO VEM DA SESSÃO, E O ID QUE VEM DO NAVEGADOR NÃO BASTA
═══════════════════════════════════════════════════════════════════════════
Esta é a primeira coisa do app do agregado em que o navegador manda um
IDENTIFICADOR DE LINHA (`conversa_id`) — até aqui todo escopo saía da sessão e
não havia o que forjar.

Então a regra é dura e vale para TODA função do lado do dono: o
`proprietario_codigo` da sessão entra na cláusula `WHERE`, **junto** do id —
nunca uma busca por id seguida de um `if` conferindo o dono. As duas formas
parecem iguais e não são: o `if` é a linha que alguém apaga numa refatoração, e
o sintoma é ler a conversa de outra pessoa (aqui, sobre o dinheiro dela).

═══════════════════════════════════════════════════════════════════════════
O WHATSAPP AVISA, MAS NÃO ABRE A JANELA
═══════════════════════════════════════════════════════════════════════════
`entrada.py` abre a janela de horário (08:00–20:00) de propósito: um código de
entrada é resposta a alguém que está com o celular na mão esperando por ele.
**Aqui é o contrário e a janela FICA** — resposta do setor é mensagem de
empresa, exatamente o que a janela existe para conter. E o texto do aviso NÃO
leva o conteúdo: o que se escreve aqui é sobre o dinheiro de um fornecedor, e
WhatsApp é lido em tela de bloqueio (medido: 3 dos 63 donos dividem o número
com outro cadastro). O canal tem o conteúdo; o aviso só diz que ele existe.

═══════════════════════════════════════════════════════════════════════════
O QUE NÃO ENTRA AQUI
═══════════════════════════════════════════════════════════════════════════
**Anexo e foto ficam para depois, de propósito** — upload é módulo (limite,
tipo, ACL, retenção), não campo, e o `sup_anexos` já mostrou isso.

**Nada de decisão automática.** O app relata e o setor decide: nenhuma mensagem
daqui altera acerto, lançamento ou cadastro. O AVA é somente leitura.
"""
from __future__ import annotations

import logging

from .. import pglocal

log = logging.getLogger("cortex.agregado.conversas")

#: Quantas conversas ABERTAS um proprietário pode ter ao mesmo tempo. Não é
#: desconfiança: é o que impede a fila do setor de virar impossível de atender
#: por causa de um dono com um dia ruim — e o que faz "aberta há N dias"
#: continuar significando alguma coisa.
MAX_ABERTAS = 5

#: Teto do texto de uma mensagem. Recusa LEGÍVEL, nunca truncamento silencioso:
#: cortar o que a pessoa escreveu sem avisar é perder a metade que importava.
MAX_TEXTO = 2000

#: Estados. `aguardando_agregado` existe para a caixa distinguir "eu devo uma
#: resposta" de "eu já respondi" — sem ele, os dois casos são "em_atendimento"
#: e a fila não ordena.
STATUS = ("aberta", "em_atendimento", "aguardando_agregado", "resolvida")

#: Os que ainda pedem alguém. `resolvida` é o único fim.
ABERTOS = ("aberta", "em_atendimento", "aguardando_agregado")

#: Teto da caixa do setor, com contador ao lado — top-N sem contador vira total
#: falso.
LIMITE_CAIXA = 200

#: O aviso que sai no WhatsApp. NÃO leva assunto nem conteúdo: ver o docstring.
AVISO = ("Voce tem uma resposta do setor de agregados da Sulista no app. "
         "Abra o aplicativo para ler.")


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota. Nunca 5xx: o Cloudflare troca o
    corpo de 5xx pela página dele e a mensagem não chega a ninguém."""


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _texto(bruto: str) -> str:
    t = " ".join(str(bruto or "").split())
    if not t:
        raise Recusa("Escreva a sua mensagem.")
    if len(t) > MAX_TEXTO:
        raise Recusa("A mensagem é longa demais (máximo de %d caracteres). "
                     "Mande em partes." % MAX_TEXTO)
    return t


# ═══════════════════════════════════════════════════════════ os assuntos ═══

def assuntos(quem: str = "agregado", esquema: str | None = None) -> list[dict]:
    """A lista fechada, do lado de quem pergunta.

    O `ajuda` vai junto porque é ele que resolve metade dos pedidos ANTES de
    virar fila: "a multa entra como desconto no acerto" não precisa de ninguém
    do setor.
    """
    return [dict(r) for r in pglocal.query(
        """SELECT chave, rotulo, ajuda FROM agr_assuntos
            WHERE ativo AND quem_abre IN (%(q)s, 'ambos')
            ORDER BY ordem, rotulo""",
        {"q": str(quem)}, _esq(esquema))]


def _assunto(chave: str, quem: str, esquema: str | None) -> dict:
    linha = pglocal.um(
        """SELECT chave, rotulo FROM agr_assuntos
            WHERE chave = %(c)s AND ativo AND quem_abre IN (%(q)s, 'ambos')""",
        {"c": str(chave or ""), "q": quem}, esquema)
    if not linha:
        # LISTA FECHADA É FECHADA NO SERVIDOR. A tela só oferece o que pode,
        # mas quem garante é isto — a alternativa seria um `assunto` livre
        # chegando pelo corpo do pedido, que é o mesmo que não ter lista.
        raise Recusa("Escolha um assunto da lista.")
    return dict(linha)


# ═══════════════════════════════════════════════ escrita (comum aos dois) ══

def _mensagem(cx, conversa_id: int, papel: str, *, texto: str = "",
              evento: str = "", autor_id=None, autor_nome: str = "") -> int:
    """Insere a mensagem e reencosta o carimbo da conversa, NA MESMA transação.

    Os dois juntos, sempre: `ultima_em` é o que ordena a caixa do setor, e uma
    mensagem gravada sem ele seria alguém esperando no fim da fila para sempre
    — defeito mudo, que só aparece quando a pessoa reclama de não ter sido
    atendida.
    """
    with cx.cursor() as cur:
        cur.execute(
            """INSERT INTO agr_mensagens(conversa_id, papel, autor_id,
                                         autor_nome, texto, evento)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (int(conversa_id), papel, autor_id, autor_nome or "", texto, evento))
        mid = cur.fetchone()["id"]
        cur.execute("UPDATE agr_conversas SET ultima_em = now() WHERE id = %s",
                    (int(conversa_id),))
    return int(mid)


def _cabecalho(c: dict) -> dict:
    return {"id": int(c["id"]), "assunto": c["assunto"],
            "assunto_rotulo": c["assunto_rotulo"], "origem": c["origem"],
            "titulo": c["titulo"] or "", "status": c["status"],
            "aberta": c["status"] in ABERTOS,
            "criada_em": c["criada_em"].isoformat() if c["criada_em"] else None,
            # O NOME DE QUEM ATENDE SAI, e é deliberado: "o setor" não devolve
            # ligação nenhuma; "a Fernanda está com o seu acerto" devolve.
            "atendente": c["atribuido_nome"] or ""}


def _mensagens(linhas) -> list[dict]:
    return [{"id": int(m["id"]), "papel": m["papel"],
             "autor": m["autor_nome"] or "", "texto": m["texto"] or "",
             "evento": m["evento"] or "",
             "quando": m["criada_em"].isoformat() if m["criada_em"] else None}
            for m in linhas]


# ═══════════════════════════════════════════════════ o lado do agregado ════

_MINHAS_SQL = """
SELECT c.id, c.assunto, a.rotulo AS assunto_rotulo, c.origem, c.titulo,
       c.status, c.criada_em, c.ultima_em, c.atribuido_nome,
       (SELECT count(*) FROM agr_mensagens m
         WHERE m.conversa_id = c.id AND m.papel = 'setor'
           AND (c.visto_agregado_em IS NULL
                OR m.criada_em > c.visto_agregado_em))::int AS nao_lidas,
       (SELECT m.texto FROM agr_mensagens m
         WHERE m.conversa_id = c.id AND m.evento = ''
         ORDER BY m.id DESC LIMIT 1) AS ultimo_texto
  FROM agr_conversas c
  JOIN agr_assuntos a ON a.chave = c.assunto
 WHERE c.proprietario_codigo = %(dono)s
 ORDER BY (c.status = 'resolvida'), c.ultima_em DESC
"""


def minhas(sessao: dict, esquema: str | None = None) -> dict:
    """As conversas de QUEM ESTÁ LOGADO. O código sai da sessão."""
    esq = _esq(esquema)
    linhas = pglocal.query(_MINHAS_SQL,
                           {"dono": str(sessao["proprietario_codigo"])}, esq)
    itens = [{
        "id": int(l["id"]),
        "assunto": l["assunto"], "assunto_rotulo": l["assunto_rotulo"],
        "origem": l["origem"], "titulo": l["titulo"] or "",
        "status": l["status"], "aberta": l["status"] in ABERTOS,
        "criada_em": l["criada_em"].isoformat() if l["criada_em"] else None,
        "ultima_em": l["ultima_em"].isoformat() if l["ultima_em"] else None,
        "nao_lidas": int(l["nao_lidas"] or 0),
        "resumo": (l["ultimo_texto"] or "")[:120],
        "atendente": l["atribuido_nome"] or "",
    } for l in linhas]
    return {
        "conversas": itens,
        "nao_lidas": sum(i["nao_lidas"] for i in itens),
        "abertas": sum(1 for i in itens if i["aberta"]),
        "assuntos": assuntos("agregado", esq),
        "max_abertas": MAX_ABERTAS,
        "fonte": "CÓRTEX · canal do setor de agregados",
    }


def _minha(proprietario_codigo: str, conversa_id, esquema) -> dict:
    """A conversa, SE for dele. O dono entra no WHERE, junto do id.

    Não existe aqui uma busca por id seguida de conferência do dono: as duas
    formas parecem iguais e não são.
    """
    try:
        cid = int(conversa_id)
    except (TypeError, ValueError):
        raise Recusa("Conversa não encontrada.") from None
    linha = pglocal.um(
        """SELECT c.*, a.rotulo AS assunto_rotulo
             FROM agr_conversas c
             JOIN agr_assuntos a ON a.chave = c.assunto
            WHERE c.id = %(id)s AND c.proprietario_codigo = %(dono)s""",
        {"id": cid, "dono": str(proprietario_codigo)}, esquema)
    if not linha:
        # A MESMA RECUSA para "não existe" e "não é sua": distinguir as duas
        # transformaria esta rota num contador de conversas alheias.
        raise Recusa("Conversa não encontrada.")
    return dict(linha)


def ler(sessao: dict, conversa_id, esquema: str | None = None) -> dict:
    """Abre a conversa e MARCA COMO VISTA — as duas coisas, porque abrir é ler."""
    esq = _esq(esquema)
    c = _minha(sessao["proprietario_codigo"], conversa_id, esq)
    msgs = pglocal.query(
        """SELECT id, papel, autor_nome, texto, evento, criada_em
             FROM agr_mensagens WHERE conversa_id = %(id)s ORDER BY id""",
        {"id": c["id"]}, esq)
    pglocal.executar(
        "UPDATE agr_conversas SET visto_agregado_em = now() WHERE id = %(id)s",
        {"id": c["id"]}, esq)
    return {"conversa": _cabecalho(c), "mensagens": _mensagens(msgs)}


def abrir(sessao: dict, assunto: str, texto: str,
          esquema: str | None = None) -> dict:
    """O proprietário abre um pedido. Assunto da lista, texto dele."""
    esq = _esq(esquema)
    a = _assunto(assunto, "agregado", esq)
    t = _texto(texto)
    dono = str(sessao["proprietario_codigo"])

    r = pglocal.um(
        """SELECT count(*) AS abertas,
                  sum(CASE WHEN assunto = %(a)s THEN 1 ELSE 0 END) AS mesmo
             FROM agr_conversas
            WHERE proprietario_codigo = %(dono)s AND status <> 'resolvida'""",
        {"dono": dono, "a": a["chave"]}, esq) or {}
    if int(r.get("mesmo") or 0):
        # RECUSA QUE ENSINA: mandar para a conversa que já existe é melhor que
        # abrir a segunda — duas filas sobre o mesmo assunto é como o setor
        # responde uma e a outra envelhece.
        raise Recusa("Você já tem um pedido aberto sobre %s. "
                     "Continue por ele — é a mesma conversa."
                     % a["rotulo"].lower())
    if int(r.get("abertas") or 0) >= MAX_ABERTAS:
        raise Recusa("Você já tem %d pedidos em aberto. Aguarde a resposta de "
                     "um deles antes de abrir outro." % MAX_ABERTAS)

    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            cur.execute(
                """INSERT INTO agr_conversas(proprietario_codigo, assunto, origem,
                                             status, visto_agregado_em)
                   VALUES (%s,%s,'agregado','aberta', now()) RETURNING id""",
                (dono, a["chave"]))
            cid = int(cur.fetchone()["id"])
        _mensagem(cx, cid, "sistema", evento="abertura",
                  texto="Pedido aberto sobre %s." % a["rotulo"])
        _mensagem(cx, cid, "agregado", texto=t,
                  autor_nome=sessao.get("nome") or "")
        cx.commit()
    return {"id": cid, "assunto": a["chave"], "assunto_rotulo": a["rotulo"]}


def responder(sessao: dict, conversa_id, texto: str,
              esquema: str | None = None) -> dict:
    """O proprietário escreve numa conversa DELE."""
    esq = _esq(esquema)
    c = _minha(sessao["proprietario_codigo"], conversa_id, esq)
    t = _texto(texto)
    if c["status"] == "resolvida":
        # REABRIR É EXPLÍCITO, e não efeito de escrever: sem isso, uma conversa
        # fechada volta para a fila sem ninguém decidir, e a fila deixa de ter
        # fim.
        raise Recusa("Este pedido já foi encerrado. Abra um novo se ainda "
                     "precisar de alguma coisa.")
    with pglocal.get_conn(esq) as cx:
        _mensagem(cx, c["id"], "agregado", texto=t,
                  autor_nome=sessao.get("nome") or "")
        with cx.cursor() as cur:
            # Ele escreveu: a bola volta para o setor. `visto_agregado_em`
            # também avança — quem acabou de escrever leu tudo o que havia.
            cur.execute(
                """UPDATE agr_conversas
                      SET status = CASE WHEN status = 'aguardando_agregado'
                                        THEN 'em_atendimento' ELSE status END,
                          status_em = now(), visto_agregado_em = now()
                    WHERE id = %s""", (c["id"],))
        cx.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════ o lado do setor ═══

_CAIXA_SQL = """
SELECT c.id, c.proprietario_codigo, v.id AS agregado_id, v.nome AS agregado,
       c.assunto, a.rotulo AS assunto_rotulo, c.origem, c.titulo, c.status,
       c.criada_em, c.ultima_em, c.atribuido_id, c.atribuido_nome,
       (SELECT count(*) FROM agr_mensagens m
         WHERE m.conversa_id = c.id AND m.papel = 'agregado'
           AND (c.visto_setor_em IS NULL OR m.criada_em > c.visto_setor_em))::int
         AS nao_lidas,
       (SELECT m.texto FROM agr_mensagens m
         WHERE m.conversa_id = c.id AND m.evento = ''
         ORDER BY m.id DESC LIMIT 1) AS ultimo_texto,
       extract(epoch FROM (now() - c.ultima_em))::bigint AS parada_seg
  FROM agr_conversas c
  JOIN agr_assuntos a ON a.chave = c.assunto
  JOIN agr_vinculos v ON v.proprietario_codigo = c.proprietario_codigo
 WHERE (%(st)s = '' OR c.status = %(st)s)
   AND (%(st)s <> '' OR c.status <> 'resolvida')
   AND (%(q)s = '' OR v.nome ILIKE %(like)s)
 ORDER BY (c.status = 'resolvida'), c.ultima_em
 LIMIT %(lim)s
"""


def caixa(status: str = "", busca: str = "", esquema: str | None = None) -> dict:
    """A caixa de entrada do setor de agregados.

    **ORDENA PELO MAIS PARADO, não pelo mais recente.** É a diferença entre uma
    fila e uma caixa de e-mail: numa caixa por data, quem escreveu há três
    semanas nunca mais é visto — e é exatamente essa pessoa que liga cobrando o
    acerto. `parada_dias` vai no payload para a tela poder gritar.
    """
    esq = _esq(esquema)
    termo = " ".join(str(busca or "").strip().split())
    st = str(status or "").strip()
    if st and st not in STATUS:
        raise Recusa("Estado desconhecido.")
    par = {"st": st, "q": termo, "like": f"%{termo}%", "lim": LIMITE_CAIXA}
    linhas = pglocal.query(_CAIXA_SQL, par, esq)
    tot = pglocal.um(
        """SELECT count(*)::int AS total,
                  sum(CASE WHEN status = 'aberta' THEN 1 ELSE 0 END)::int AS abertas,
                  sum(CASE WHEN status <> 'resolvida' THEN 1 ELSE 0 END)::int AS vivas,
                  sum(CASE WHEN status <> 'resolvida'
                            AND ultima_em < now() - interval '3 days'
                           THEN 1 ELSE 0 END)::int AS paradas
             FROM agr_conversas""", esquema=esq) or {}
    itens = [{
        "id": int(l["id"]),
        # O CÓDIGO DO ERP NÃO SAI NEM PARA O PAINEL: ele é o CPF para pessoa
        # física, e a tela precisa do nome, não do documento.
        "agregado_id": int(l["agregado_id"]), "agregado": l["agregado"] or "",
        "assunto": l["assunto"], "assunto_rotulo": l["assunto_rotulo"],
        "origem": l["origem"], "titulo": l["titulo"] or "",
        "status": l["status"], "atendente": l["atribuido_nome"] or "",
        "criada_em": l["criada_em"].isoformat() if l["criada_em"] else None,
        "ultima_em": l["ultima_em"].isoformat() if l["ultima_em"] else None,
        "parada_dias": round(float(l["parada_seg"] or 0) / 86400.0, 1),
        "nao_lidas": int(l["nao_lidas"] or 0),
        "resumo": (l["ultimo_texto"] or "")[:160],
    } for l in linhas]
    return {"conversas": itens, "mostrados": len(itens),
            "total": int(tot.get("total") or 0),
            "abertas": int(tot.get("abertas") or 0),
            "vivas": int(tot.get("vivas") or 0),
            "paradas": int(tot.get("paradas") or 0),
            "limite": LIMITE_CAIXA, "assuntos": assuntos("setor", esq),
            "status": STATUS}


def _do_setor(conversa_id, esquema) -> dict:
    try:
        cid = int(conversa_id)
    except (TypeError, ValueError):
        raise Recusa("Conversa não encontrada.") from None
    linha = pglocal.um(
        """SELECT c.*, a.rotulo AS assunto_rotulo, v.nome AS agregado,
                  v.id AS agregado_id
             FROM agr_conversas c
             JOIN agr_assuntos a ON a.chave = c.assunto
             JOIN agr_vinculos v ON v.proprietario_codigo = c.proprietario_codigo
            WHERE c.id = %(id)s""", {"id": cid}, esquema)
    if not linha:
        raise Recusa("Conversa não encontrada.")
    return dict(linha)


def ler_setor(conversa_id, esquema: str | None = None) -> dict:
    """Abre a conversa no painel e marca como vista pelo setor."""
    esq = _esq(esquema)
    c = _do_setor(conversa_id, esq)
    msgs = pglocal.query(
        """SELECT id, papel, autor_nome, texto, evento, criada_em
             FROM agr_mensagens WHERE conversa_id = %(id)s ORDER BY id""",
        {"id": c["id"]}, esq)
    pglocal.executar(
        "UPDATE agr_conversas SET visto_setor_em = now() WHERE id = %(id)s",
        {"id": c["id"]}, esq)
    cab = _cabecalho(c)
    cab.update({"agregado": c["agregado"] or "",
                "agregado_id": int(c["agregado_id"])})
    return {"conversa": cab, "mensagens": _mensagens(msgs)}


def abrir_setor(agregado_id, assunto: str, titulo: str, texto: str, *,
                autor_id=None, autor_nome: str = "",
                esquema: str | None = None) -> dict:
    """O setor abre uma conversa com um proprietário (um recado, um pedido).

    O alvo vem pelo ID OPACO do vínculo, nunca pelo código do ERP: a lista que
    a tela do painel usa também só publica id e nome.
    """
    esq = _esq(esquema)
    a = _assunto(assunto, "setor", esq)
    t = _texto(texto)
    try:
        aid = int(agregado_id)
    except (TypeError, ValueError):
        raise Recusa("Escolha um proprietário.") from None
    alvo = pglocal.um(
        "SELECT proprietario_codigo, nome FROM agr_vinculos "
        "WHERE id = %(id)s AND ativo", {"id": aid}, esq)
    if not alvo:
        raise Recusa("Proprietário não encontrado ou desligado.")
    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            cur.execute(
                """INSERT INTO agr_conversas(proprietario_codigo, assunto, origem,
                                             titulo, status, status_por,
                                             atribuido_id, atribuido_nome,
                                             visto_setor_em)
                   VALUES (%s,%s,'setor',%s,'aguardando_agregado',%s,%s,%s, now())
                   RETURNING id""",
                (alvo["proprietario_codigo"], a["chave"],
                 " ".join(str(titulo or "").split())[:120],
                 autor_nome or "", autor_id, autor_nome or ""))
            cid = int(cur.fetchone()["id"])
        _mensagem(cx, cid, "sistema", evento="abertura",
                  texto="%s abriu um pedido sobre %s."
                        % (autor_nome or "O setor", a["rotulo"]))
        _mensagem(cx, cid, "setor", texto=t, autor_id=autor_id,
                  autor_nome=autor_nome or "")
        cx.commit()
    return {"id": cid, "assunto": a["chave"], "assunto_rotulo": a["rotulo"]}


def responder_setor(conversa_id, texto: str, *, autor_id=None,
                    autor_nome: str = "", esquema: str | None = None) -> dict:
    """O setor responde. Quem responde PEGA a conversa, se ela não tinha dono.

    Atribuir no ato é o que faz "em_atendimento" significar alguma coisa: sem
    isso, a caixa tem conversas respondidas sem dono, e ninguém sabe de quem
    cobrar a próxima resposta.
    """
    esq = _esq(esquema)
    c = _do_setor(conversa_id, esq)
    t = _texto(texto)
    with pglocal.get_conn(esq) as cx:
        _mensagem(cx, c["id"], "setor", texto=t, autor_id=autor_id,
                  autor_nome=autor_nome or "")
        with cx.cursor() as cur:
            cur.execute(
                """UPDATE agr_conversas
                      SET status = CASE WHEN status = 'resolvida' THEN status
                                        ELSE 'aguardando_agregado' END,
                          status_em = now(), status_por = %s,
                          visto_setor_em = now(),
                          atribuido_id = coalesce(atribuido_id, %s),
                          atribuido_nome = CASE WHEN atribuido_nome = ''
                                                THEN %s ELSE atribuido_nome END
                    WHERE id = %s""",
                (autor_nome or "", autor_id, autor_nome or "", c["id"]))
        cx.commit()
    return {"ok": True, "id": int(c["id"])}


def mudar_status(conversa_id, status: str, *, autor_id=None,
                 autor_nome: str = "", esquema: str | None = None) -> dict:
    """Pegar, devolver ou encerrar. Toda mudança vira mensagem de SISTEMA, na
    mesma linha do tempo — é assim que a conversa se lê depois."""
    esq = _esq(esquema)
    novo = str(status or "").strip()
    if novo not in STATUS:
        raise Recusa("Estado desconhecido.")
    c = _do_setor(conversa_id, esq)
    if c["status"] == novo:
        return {"ok": True, "id": int(c["id"]), "status": novo}
    rotulos = {"aberta": "devolveu para a fila",
               "em_atendimento": "pegou o atendimento",
               "aguardando_agregado": "está aguardando o proprietário",
               "resolvida": "encerrou o pedido"}
    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            cur.execute(
                """UPDATE agr_conversas
                      SET status = %s, status_em = now(), status_por = %s,
                          visto_setor_em = now(),
                          atribuido_id = CASE WHEN %s = 'aberta' THEN NULL
                                              ELSE coalesce(atribuido_id, %s) END,
                          atribuido_nome = CASE WHEN %s = 'aberta' THEN ''
                                                WHEN atribuido_nome = '' THEN %s
                                                ELSE atribuido_nome END
                    WHERE id = %s""",
                (novo, autor_nome or "", novo, autor_id, novo,
                 autor_nome or "", c["id"]))
        _mensagem(cx, c["id"], "sistema", evento="status",
                  texto="%s %s." % (autor_nome or "O setor",
                                    rotulos.get(novo, "mudou o estado")))
        cx.commit()
    return {"ok": True, "id": int(c["id"]), "status": novo}


def telefone_de(conversa_id, esquema: str | None = None) -> tuple[str, str]:
    """O telefone do dono da conversa, para o aviso. Sai do vínculo, nunca do
    corpo do pedido."""
    linha = pglocal.um(
        """SELECT v.telefone, v.nome FROM agr_conversas c
             JOIN agr_vinculos v ON v.proprietario_codigo = c.proprietario_codigo
            WHERE c.id = %(id)s AND v.ativo""",
        {"id": int(conversa_id)}, _esq(esquema))
    if not linha:
        return "", ""
    return str(linha["telefone"] or ""), str(linha["nome"] or "")


def contagem(esquema: str | None = None) -> dict:
    """Para a Saúde do Servidor e para o sino do painel: o tamanho da fila e o
    que está parado. A fila PARADA é o único número que diz se o canal está
    funcionando — sem ele, "ninguém lê" volta a ser sensação."""
    r = pglocal.um(
        """SELECT count(*)::int AS total,
                  sum(CASE WHEN status <> 'resolvida' THEN 1 ELSE 0 END)::int AS vivas,
                  sum(CASE WHEN status = 'aberta' THEN 1 ELSE 0 END)::int AS abertas,
                  sum(CASE WHEN status <> 'resolvida'
                            AND ultima_em < now() - interval '3 days'
                           THEN 1 ELSE 0 END)::int AS paradas,
                  max(ultima_em) AS ultima
             FROM agr_conversas""", esquema=_esq(esquema)) or {}
    return {"total": int(r.get("total") or 0), "vivas": int(r.get("vivas") or 0),
            "abertas": int(r.get("abertas") or 0),
            "paradas": int(r.get("paradas") or 0),
            "ultima": r.get("ultima").isoformat() if r.get("ultima") else None}
