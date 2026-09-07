# -*- coding: utf-8 -*-
"""O canal entre o RH e o motorista — fila com dono, não conversa.

═══════════════════════════════════════════════════════════════════════════
ISTO CONTRARIA O ESCOPO ESCRITO, E A CONTRARIEDADE ESTÁ PAGA
═══════════════════════════════════════════════════════════════════════════
`docs/APP_MOTORISTA.md` §10 põe **chat** na lista do que fica de fora: "a casa
já tem WhatsApp; um segundo canal de conversa é um canal que ninguém lê e uma
expectativa de resposta que ninguém atende". Quem opera pediu o canal mesmo
assim, em 07/09/2026 — e a razão do escopo não foi ignorada, foi endereçada:

**isto não é conversa, é FILA COM ASSUNTO, DONO E ESTADO** — a mesma forma dos
chamados do Suporte (`sup_chamados`), que funciona na casa há tempo.

| O escopo temia | O que impede aqui |
|---|---|
| "ninguém lê" | `visto_rh_em`: a caixa do RH ordena por quem espera há mais tempo, e a Saúde do Servidor mede a fila parada |
| "expectativa que ninguém atende" | assunto de LISTA FECHADA + `status` + `atribuido_id`: "aberta há N dias" vira número, não sensação |

Se um dia a fila estiver cheia e velha, a Saúde vai dizer — e aí a decisão de
manter ou desligar o canal se toma com o número na mesa, que é a única forma de
essa decisão ser diferente da que o escopo já tinha tomado no escuro.

═══════════════════════════════════════════════════════════════════════════
O ESCOPO VEM DA SESSÃO, E O ID QUE VEM DO NAVEGADOR NÃO BASTA
═══════════════════════════════════════════════════════════════════════════
Esta é a primeira coisa do app do motorista em que o navegador manda um
IDENTIFICADOR DE LINHA (`conversa_id`). Até aqui todo escopo saía da sessão e
não havia o que forjar.

Então a regra é dura e vale para TODA função do lado do motorista: o
`motorista_codigo` da sessão entra na cláusula `WHERE`, **junto** do id — nunca
uma busca por id seguida de um `if` conferindo o dono. As duas formas parecem
iguais e não são: o `if` é uma linha que alguém apaga numa refatoração, e o
sintoma é ler a conversa de outra pessoa. Há guard varrendo isso.

═══════════════════════════════════════════════════════════════════════════
O WHATSAPP AVISA, MAS NÃO ABRE A JANELA
═══════════════════════════════════════════════════════════════════════════
`entrada.py` abre a janela de horário (08:00–20:00) de propósito: um código de
entrada é resposta a alguém que está com o celular na mão, às 03:40, esperando
por ela.

**Aqui é o contrário e a janela FICA.** Resposta do RH é mensagem de empresa —
exatamente o que a janela existe para conter. Um aviso de férias às 3 da manhã
é a denúncia que faz o número da casa ser banido, e o motorista perderia junto
o canal que a torre usa. Quem está dormindo lê de manhã; o estado está no app,
que é onde ele mora.

O teto do dia também fica, e por isso **não existe comunicado em massa por
WhatsApp** neste módulo: 300 motoristas contra um teto de 60 destinatários
distintos por dia seriam cinco dias de ondas gastando a reputação do número que
fala com clientes. Comunicado do RH chega pela marca no app. Decidido com quem
opera em 07/09/2026, com o número na mesa.

═══════════════════════════════════════════════════════════════════════════
O QUE NÃO ENTRA AQUI
═══════════════════════════════════════════════════════════════════════════
**Anexo e foto ficam para depois, de propósito.** Foto de documento é metade do
valor deste canal e é também upload, limite de tamanho, tipo de arquivo, ACL e
retenção — e o `sup_anexos` já mostrou que isso é um módulo, não um campo. Ele
entra quando a fila provar que existe uso; o que não se faz é meia
implementação de upload num canal que trata de documento de trabalhador.

**Nada de decisão automática.** O app relata e o RH decide — nenhuma mensagem
daqui altera férias, ponto, folha ou cadastro. É a mesma regra do resto do app:
jornada não se aponta duas vezes, e o AVA é somente leitura.
"""
from __future__ import annotations

import logging

from .. import pglocal

log = logging.getLogger("cortex.motorista.conversas")

#: Quantas conversas ABERTAS um motorista pode ter ao mesmo tempo. Não é
#: desconfiança do motorista: é o que impede a fila do RH de virar impossível de
#: atender por causa de uma pessoa com um dia ruim — e o que faz "aberta há N
#: dias" continuar significando alguma coisa.
MAX_ABERTAS = 5

#: Teto do texto de uma mensagem. Recusa LEGÍVEL, nunca truncamento silencioso:
#: cortar o que a pessoa escreveu sem avisar é perder a metade que importava.
MAX_TEXTO = 2000

#: Estados. `aguardando_motorista` existe para a caixa do RH distinguir "eu
#: devo uma resposta" de "eu já respondi" — sem ele, os dois casos são
#: "em_atendimento" e a fila não ordena.
STATUS = ("aberta", "em_atendimento", "aguardando_motorista", "resolvida")

#: Os que ainda pedem alguém. `resolvida` é o único fim.
ABERTOS = ("aberta", "em_atendimento", "aguardando_motorista")


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

def assuntos(quem: str = "motorista", esquema: str | None = None) -> list[dict]:
    """A lista fechada, do lado de quem pergunta.

    `quem_abre = 'ambos'` aparece nos dois lados. O `ajuda` vai junto porque é
    ele que resolve metade dos pedidos ANTES de virar fila: "seu contracheque
    está no app do Globus" não precisa de ninguém do RH.
    """
    return [dict(r) for r in pglocal.query(
        """SELECT chave, rotulo, ajuda, pede_ciencia
             FROM mot_assuntos
            WHERE ativo AND quem_abre IN (%(q)s, 'ambos')
            ORDER BY ordem, rotulo""",
        {"q": str(quem)}, _esq(esquema))]


def _assunto(chave: str, quem: str, esquema: str | None) -> dict:
    linha = pglocal.um(
        """SELECT chave, rotulo, pede_ciencia FROM mot_assuntos
            WHERE chave = %(c)s AND ativo AND quem_abre IN (%(q)s, 'ambos')""",
        {"c": str(chave or ""), "q": quem}, esquema)
    if not linha:
        # LISTA FECHADA É FECHADA NO SERVIDOR. A tela só oferece o que pode,
        # mas quem garante é isto — a alternativa seria um `assunto` livre
        # chegando pelo corpo do pedido, que é a mesma coisa que não ter lista.
        raise Recusa("Escolha um assunto da lista.")
    return dict(linha)


# ═══════════════════════════════════════════════ escrita (comum aos dois) ══

def _mensagem(cx, conversa_id: int, papel: str, *, texto: str = "",
              evento: str = "", autor_id=None, autor_nome: str = "") -> int:
    """Insere a mensagem e reencosta o carimbo da conversa, NA MESMA transação.

    Os dois juntos, sempre: `ultima_em` é o que ordena a caixa do RH, e uma
    mensagem gravada sem ele seria uma pessoa esperando no fim da fila para
    sempre — defeito mudo, que só aparece quando alguém reclama de não ter sido
    atendido.
    """
    with cx.cursor() as cur:
        cur.execute(
            """INSERT INTO mot_mensagens(conversa_id, papel, autor_id,
                                         autor_nome, texto, evento)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (int(conversa_id), papel, autor_id, autor_nome or "", texto, evento))
        mid = cur.fetchone()["id"]
        cur.execute("UPDATE mot_conversas SET ultima_em = now() WHERE id = %s",
                    (int(conversa_id),))
    return int(mid)


# ═══════════════════════════════════════════════════ o lado do motorista ═══

_MINHAS_SQL = """
SELECT c.id, c.assunto, a.rotulo AS assunto_rotulo, c.origem, c.titulo,
       c.status, c.criada_em, c.ultima_em, c.atribuido_nome,
       a.pede_ciencia,
       (SELECT count(*) FROM mot_mensagens m
         WHERE m.conversa_id = c.id AND m.papel = 'rh'
           AND (c.visto_motorista_em IS NULL
                OR m.criada_em > c.visto_motorista_em))::int AS nao_lidas,
       (SELECT max(m.criada_em) FROM mot_mensagens m
         WHERE m.conversa_id = c.id AND m.evento = 'ciencia') AS ciencia_em,
       (SELECT m.texto FROM mot_mensagens m
         WHERE m.conversa_id = c.id AND m.evento = ''
         ORDER BY m.id DESC LIMIT 1) AS ultimo_texto
  FROM mot_conversas c
  JOIN mot_assuntos a ON a.chave = c.assunto
 WHERE c.motorista_codigo = %(mot)s
 ORDER BY (c.status = 'resolvida'), c.ultima_em DESC
"""


def minhas(sessao: dict, esquema: str | None = None) -> dict:
    """As conversas de QUEM ESTÁ LOGADO. O código sai da sessão."""
    esq = _esq(esquema)
    linhas = pglocal.query(_MINHAS_SQL,
                           {"mot": str(sessao["motorista_codigo"])}, esq)
    itens = []
    for l in linhas:
        itens.append({
            "id": int(l["id"]),
            "assunto": l["assunto"],
            "assunto_rotulo": l["assunto_rotulo"],
            "origem": l["origem"],
            "titulo": l["titulo"] or "",
            "status": l["status"],
            "aberta": l["status"] in ABERTOS,
            "criada_em": l["criada_em"].isoformat() if l["criada_em"] else None,
            "ultima_em": l["ultima_em"].isoformat() if l["ultima_em"] else None,
            "nao_lidas": int(l["nao_lidas"] or 0),
            "resumo": (l["ultimo_texto"] or "")[:120],
            # Comunicado que ainda não teve ciência é o único item deste app
            # que PEDE uma ação do motorista. A tela destaca; nada é feito por
            # ele automaticamente.
            "pede_ciencia": bool(l["pede_ciencia"]) and not l["ciencia_em"],
            "ciencia_em": (l["ciencia_em"].isoformat()
                           if l["ciencia_em"] else None),
        })
    return {
        "conversas": itens,
        "nao_lidas": sum(i["nao_lidas"] for i in itens),
        "pendencias": sum(1 for i in itens if i["pede_ciencia"]),
        "abertas": sum(1 for i in itens if i["aberta"]),
        "assuntos": assuntos("motorista", esq),
        "max_abertas": MAX_ABERTAS,
        "fonte": "CÓRTEX · canal do RH",
    }


def _minha(motorista_codigo: str, conversa_id, esquema) -> dict:
    """A conversa, SE for dele. O dono entra no WHERE, junto do id.

    Não existe aqui uma busca por id seguida de conferência do dono: as duas
    formas parecem iguais e não são — o `if` é a linha que alguém apaga, e o
    sintoma é ler a conversa de outra pessoa.
    """
    try:
        cid = int(conversa_id)
    except (TypeError, ValueError):
        raise Recusa("Conversa não encontrada.") from None
    linha = pglocal.um(
        """SELECT c.*, a.rotulo AS assunto_rotulo, a.pede_ciencia
             FROM mot_conversas c
             JOIN mot_assuntos a ON a.chave = c.assunto
            WHERE c.id = %(id)s AND c.motorista_codigo = %(mot)s""",
        {"id": cid, "mot": str(motorista_codigo)}, esquema)
    if not linha:
        # A MESMA RECUSA para "não existe" e "não é sua". Distinguir as duas
        # transformaria esta rota num contador de conversas alheias.
        raise Recusa("Conversa não encontrada.")
    return dict(linha)


def ler(sessao: dict, conversa_id, esquema: str | None = None) -> dict:
    """Abre a conversa e MARCA COMO VISTA — as duas coisas, porque abrir é ler.

    O carimbo é de LADO, não de mensagem: um booleano por mensagem obrigaria a
    escrever N linhas para marcar uma conversa como lida, e é a mesma escolha de
    `aud_sessoes` e `mot_sessoes`.
    """
    esq = _esq(esquema)
    c = _minha(sessao["motorista_codigo"], conversa_id, esq)
    msgs = pglocal.query(
        """SELECT id, papel, autor_nome, texto, evento, criada_em
             FROM mot_mensagens WHERE conversa_id = %(id)s ORDER BY id""",
        {"id": c["id"]}, esq)
    pglocal.executar(
        "UPDATE mot_conversas SET visto_motorista_em = now() WHERE id = %(id)s",
        {"id": c["id"]}, esq)
    return {"conversa": _cabecalho(c), "mensagens": _mensagens(msgs)}


def _cabecalho(c: dict) -> dict:
    return {"id": int(c["id"]), "assunto": c["assunto"],
            "assunto_rotulo": c["assunto_rotulo"], "origem": c["origem"],
            "titulo": c["titulo"] or "", "status": c["status"],
            "aberta": c["status"] in ABERTOS,
            "pede_ciencia": bool(c["pede_ciencia"]),
            "criada_em": c["criada_em"].isoformat() if c["criada_em"] else None,
            # O NOME DE QUEM ATENDE SAI, e é deliberado: "o RH" não devolve
            # ligação nenhuma; "a Fernanda está com o seu pedido" devolve.
            "atendente": c["atribuido_nome"] or ""}


def _mensagens(linhas) -> list[dict]:
    return [{"id": int(m["id"]), "papel": m["papel"],
             "autor": m["autor_nome"] or "", "texto": m["texto"] or "",
             "evento": m["evento"] or "",
             "quando": m["criada_em"].isoformat() if m["criada_em"] else None}
            for m in linhas]


def abrir(sessao: dict, assunto: str, texto: str,
          esquema: str | None = None) -> dict:
    """O motorista abre um pedido. Assunto da lista, texto dele."""
    esq = _esq(esquema)
    a = _assunto(assunto, "motorista", esq)
    t = _texto(texto)
    mot = str(sessao["motorista_codigo"])

    r = pglocal.um(
        """SELECT count(*) AS abertas,
                  sum(CASE WHEN assunto = %(a)s THEN 1 ELSE 0 END) AS mesmo
             FROM mot_conversas
            WHERE motorista_codigo = %(mot)s AND status <> 'resolvida'""",
        {"mot": mot, "a": a["chave"]}, esq) or {}
    if int(r.get("mesmo") or 0):
        # RECUSA QUE ENSINA: mandar para a conversa que já existe é melhor que
        # abrir a segunda, porque duas filas sobre o mesmo assunto é como o RH
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
                """INSERT INTO mot_conversas(motorista_codigo, assunto, origem,
                                             status, visto_motorista_em)
                   VALUES (%s,%s,'motorista','aberta', now()) RETURNING id""",
                (mot, a["chave"]))
            cid = int(cur.fetchone()["id"])
        _mensagem(cx, cid, "sistema", evento="abertura",
                  texto="Pedido aberto sobre %s." % a["rotulo"])
        _mensagem(cx, cid, "motorista", texto=t,
                  autor_nome=sessao.get("nome") or "")
        cx.commit()
    return {"id": cid, "assunto": a["chave"], "assunto_rotulo": a["rotulo"]}


def responder(sessao: dict, conversa_id, texto: str,
              esquema: str | None = None) -> dict:
    """O motorista escreve numa conversa DELE."""
    esq = _esq(esquema)
    c = _minha(sessao["motorista_codigo"], conversa_id, esq)
    t = _texto(texto)
    if c["status"] == "resolvida":
        # REABRIR É EXPLÍCITO, e não um efeito de escrever. Sem isso, uma
        # conversa fechada volta para a fila do RH sem ninguém decidir — e a
        # fila deixa de ter fim, que é a falha que o escopo previa.
        raise Recusa("Este pedido já foi encerrado. Abra um novo se ainda "
                     "precisar de alguma coisa.")
    with pglocal.get_conn(esq) as cx:
        _mensagem(cx, c["id"], "motorista", texto=t,
                  autor_nome=sessao.get("nome") or "")
        with cx.cursor() as cur:
            # Ele escreveu: a bola volta para o RH. `visto_motorista_em` também
            # avança — quem acabou de escrever leu tudo o que havia.
            cur.execute(
                """UPDATE mot_conversas
                      SET status = CASE WHEN status = 'aguardando_motorista'
                                        THEN 'em_atendimento' ELSE status END,
                          status_em = now(), visto_motorista_em = now()
                    WHERE id = %s""", (c["id"],))
        cx.commit()
    return {"ok": True}


def dar_ciencia(sessao: dict, conversa_id, esquema: str | None = None) -> dict:
    """"Li e entendi" num comunicado do RH.

    É o que transforma "mandamos o comunicado" em prova de que ele leu — e vira
    mensagem de SISTEMA, com data, na mesma linha do tempo. Idempotente: dois
    toques no botão não geram duas ciências.
    """
    esq = _esq(esquema)
    c = _minha(sessao["motorista_codigo"], conversa_id, esq)
    if not c["pede_ciencia"]:
        raise Recusa("Este assunto não pede confirmação de leitura.")
    ja = pglocal.um(
        "SELECT id FROM mot_mensagens WHERE conversa_id = %(id)s "
        "AND evento = 'ciencia' LIMIT 1", {"id": c["id"]}, esq)
    if ja:
        return {"ok": True, "ja_tinha": True}
    with pglocal.get_conn(esq) as cx:
        _mensagem(cx, c["id"], "sistema", evento="ciencia",
                  texto="%s confirmou que leu este comunicado."
                        % (sessao.get("nome") or "O motorista"))
        with cx.cursor() as cur:
            cur.execute(
                "UPDATE mot_conversas SET status = 'resolvida', status_em = now(), "
                "status_por = 'ciencia do motorista', visto_motorista_em = now() "
                "WHERE id = %s", (c["id"],))
        cx.commit()
    return {"ok": True, "ja_tinha": False}


# ═══════════════════════════════════════════════════════ o lado do RH ══════

_CAIXA_SQL = """
SELECT c.id, c.motorista_codigo, v.id AS motorista_id, v.nome AS motorista,
       c.assunto, a.rotulo AS assunto_rotulo, c.origem, c.titulo, c.status,
       c.criada_em, c.ultima_em, c.atribuido_id, c.atribuido_nome,
       (SELECT count(*) FROM mot_mensagens m
         WHERE m.conversa_id = c.id AND m.papel = 'motorista'
           AND (c.visto_rh_em IS NULL OR m.criada_em > c.visto_rh_em))::int
         AS nao_lidas,
       (SELECT m.texto FROM mot_mensagens m
         WHERE m.conversa_id = c.id AND m.evento = ''
         ORDER BY m.id DESC LIMIT 1) AS ultimo_texto,
       extract(epoch FROM (now() - c.ultima_em))::bigint AS parada_seg
  FROM mot_conversas c
  JOIN mot_assuntos a ON a.chave = c.assunto
  JOIN mot_vinculos v ON v.motorista_codigo = c.motorista_codigo
 WHERE (%(st)s = '' OR c.status = %(st)s)
   AND (%(st)s <> '' OR c.status <> 'resolvida')
   AND (%(q)s = '' OR v.nome ILIKE %(like)s)
 ORDER BY (c.status = 'resolvida'), c.ultima_em
 LIMIT %(lim)s
"""

#: Teto da caixa. Com contador ao lado — Top-N sem contador vira total falso.
LIMITE_CAIXA = 200


def caixa(status: str = "", busca: str = "", esquema: str | None = None) -> dict:
    """A caixa de entrada do RH.

    **ORDENA PELO MAIS PARADO, não pelo mais recente.** É a diferença entre uma
    fila e uma caixa de e-mail: numa caixa por data, quem escreveu há três
    semanas nunca mais é visto, e é exatamente essa pessoa que liga para a
    torre. `parada_seg` vai no payload para a tela poder gritar.
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
             FROM mot_conversas""", esquema=esq) or {}

    itens = []
    for l in linhas:
        itens.append({
            "id": int(l["id"]),
            # O CÓDIGO DO ERP NÃO SAI NEM PARA O PAINEL. Ele é o CPF para
            # pessoa física, e a tela precisa do nome, não do documento.
            "motorista_id": int(l["motorista_id"]),
            "motorista": l["motorista"] or "",
            "assunto": l["assunto"], "assunto_rotulo": l["assunto_rotulo"],
            "origem": l["origem"], "titulo": l["titulo"] or "",
            "status": l["status"],
            "atendente": l["atribuido_nome"] or "",
            "criada_em": l["criada_em"].isoformat() if l["criada_em"] else None,
            "ultima_em": l["ultima_em"].isoformat() if l["ultima_em"] else None,
            "parada_dias": round(float(l["parada_seg"] or 0) / 86400.0, 1),
            "nao_lidas": int(l["nao_lidas"] or 0),
            "resumo": (l["ultimo_texto"] or "")[:160],
        })
    return {
        "conversas": itens,
        "mostradas": len(itens),
        "limite": LIMITE_CAIXA,
        "resumo": {"total": tot.get("total") or 0,
                   "abertas": tot.get("abertas") or 0,
                   "vivas": tot.get("vivas") or 0,
                   # A FILA PARADA é o número que decide se este canal está
                   # funcionando. Sem ele, "temos um canal com o motorista" é
                   # uma frase; com ele, é uma medição.
                   "paradas_3d": tot.get("paradas") or 0},
        "assuntos": assuntos("rh", esq),
        "estados": list(STATUS),
        "fonte": "CÓRTEX · canal do RH (mot_conversas)",
    }


def ler_rh(conversa_id, esquema: str | None = None) -> dict:
    """A conversa inteira, do lado do RH — e marca como vista."""
    esq = _esq(esquema)
    try:
        cid = int(conversa_id)
    except (TypeError, ValueError):
        raise Recusa("Conversa não encontrada.") from None
    c = pglocal.um(
        """SELECT c.*, a.rotulo AS assunto_rotulo, a.pede_ciencia,
                  v.id AS motorista_id, v.nome AS motorista, v.telefone
             FROM mot_conversas c
             JOIN mot_assuntos a ON a.chave = c.assunto
             JOIN mot_vinculos v ON v.motorista_codigo = c.motorista_codigo
            WHERE c.id = %(id)s""", {"id": cid}, esq)
    if not c:
        raise Recusa("Conversa não encontrada.")
    msgs = pglocal.query(
        """SELECT id, papel, autor_nome, texto, evento, criada_em
             FROM mot_mensagens WHERE conversa_id = %(id)s ORDER BY id""",
        {"id": cid}, esq)
    pglocal.executar(
        "UPDATE mot_conversas SET visto_rh_em = now() WHERE id = %(id)s",
        {"id": cid}, esq)
    cab = _cabecalho(dict(c))
    cab.update({"motorista": c["motorista"] or "",
                "motorista_id": int(c["motorista_id"]),
                "status": c["status"]})
    return {"conversa": cab, "mensagens": _mensagens(msgs)}


def abrir_rh(motorista_id, assunto: str, titulo: str, texto: str, *,
             autor_id=None, autor_nome: str = "",
             esquema: str | None = None) -> dict:
    """O RH abre — comunicado ou pedido de documento — para UM motorista.

    **UM, e não uma lista.** Comunicado em massa parece a coisa óbvia e é
    justamente o que este módulo não faz: 300 conversas abertas de uma vez
    entopem a fila que o resto do desenho existe para manter atendível, e o
    aviso teria de sair por WhatsApp, contra o teto de 60 destinatários/dia do
    número que fala com clientes. Se um dia houver comunicado em massa, ele é
    outro objeto — um mural, sem fila e sem resposta —, e não este.
    """
    esq = _esq(esquema)
    a = _assunto(assunto, "rh", esq)
    t = _texto(texto)
    try:
        mid = int(motorista_id)
    except (TypeError, ValueError):
        raise Recusa("Escolha um motorista.") from None
    alvo = pglocal.um(
        "SELECT motorista_codigo, nome FROM mot_vinculos "
        "WHERE id = %(id)s AND ativo", {"id": mid}, esq)
    if not alvo:
        raise Recusa("Motorista não encontrado ou desligado.")

    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            cur.execute(
                """INSERT INTO mot_conversas(motorista_codigo, assunto, origem,
                                             titulo, status, status_por,
                                             atribuido_id, atribuido_nome,
                                             visto_rh_em)
                   VALUES (%s,%s,'rh',%s,'aguardando_motorista',%s,%s,%s, now())
                   RETURNING id""",
                (alvo["motorista_codigo"], a["chave"],
                 " ".join(str(titulo or "").split())[:120],
                 autor_nome or "", autor_id, autor_nome or ""))
            cid = int(cur.fetchone()["id"])
        _mensagem(cx, cid, "sistema", evento="abertura",
                  texto="%s abriu esta conversa sobre %s."
                        % (autor_nome or "O RH", a["rotulo"]))
        _mensagem(cx, cid, "rh", texto=t, autor_id=autor_id,
                  autor_nome=autor_nome or "")
        cx.commit()
    return {"id": cid, "motorista": alvo["nome"] or "",
            "avisar": alvo["motorista_codigo"]}


def responder_rh(conversa_id, texto: str, *, autor_id=None,
                 autor_nome: str = "", esquema: str | None = None) -> dict:
    """O RH responde. Devolve quem avisar — o envio é da rota, não daqui.

    **A AUDITORIA E A GRAVAÇÃO VÊM ANTES DA AÇÃO EXTERNA**, que é regra da
    casa: se o WhatsApp falhar, a resposta continua existindo no app e o
    motorista a lê quando abrir. O contrário — mandar primeiro e gravar
    depois — deixaria o aviso dizendo que há uma resposta que não existe.
    """
    esq = _esq(esquema)
    c = ler_rh(conversa_id, esq)["conversa"]
    t = _texto(texto)
    with pglocal.get_conn(esq) as cx:
        _mensagem(cx, c["id"], "rh", texto=t, autor_id=autor_id,
                  autor_nome=autor_nome or "")
        with cx.cursor() as cur:
            # Respondeu: a bola é do motorista, e quem atende passa a ser quem
            # respondeu (se ainda não havia dono). Atribuir no ato evita a fila
            # de conversas "em atendimento" sem ninguém dentro.
            cur.execute(
                """UPDATE mot_conversas
                      SET status = 'aguardando_motorista', status_em = now(),
                          status_por = %s, visto_rh_em = now(),
                          atribuido_id = coalesce(atribuido_id, %s),
                          atribuido_nome = CASE WHEN atribuido_nome = ''
                                                THEN %s ELSE atribuido_nome END
                    WHERE id = %s""",
                (autor_nome or "", autor_id, autor_nome or "", c["id"]))
        cx.commit()
    return {"ok": True, "conversa_id": c["id"]}


def mudar_status(conversa_id, status: str, *, autor_nome: str = "",
                 esquema: str | None = None) -> dict:
    """Muda o estado, com o motivo escrito na linha do tempo.

    O evento vira mensagem de SISTEMA porque é assim que a conversa se lê
    depois — "ele pediu, fulano pegou, respondeu, encerrou" numa coluna só, sem
    juntar duas tabelas na cabeça de quem lê.
    """
    esq = _esq(esquema)
    novo = str(status or "").strip()
    if novo not in STATUS:
        raise Recusa("Estado desconhecido.")
    c = ler_rh(conversa_id, esq)["conversa"]
    if c["status"] == novo:
        return {"ok": True, "sem_mudanca": True}
    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            cur.execute(
                "UPDATE mot_conversas SET status = %s, status_em = now(), "
                "status_por = %s WHERE id = %s",
                (novo, autor_nome or "", c["id"]))
        _mensagem(cx, c["id"], "sistema", evento="status",
                  texto="%s mudou o estado para %s."
                        % (autor_nome or "O RH", novo.replace("_", " ")))
        cx.commit()
    return {"ok": True}


def telefone_de(conversa_id, esquema: str | None = None) -> tuple[str, str]:
    """(telefone normalizado, nome) do motorista da conversa. Para o aviso."""
    linha = pglocal.um(
        """SELECT v.telefone, v.nome FROM mot_conversas c
             JOIN mot_vinculos v ON v.motorista_codigo = c.motorista_codigo
            WHERE c.id = %(id)s AND v.ativo""",
        {"id": int(conversa_id)}, _esq(esquema))
    if not linha:
        return "", ""
    return (linha["telefone"] or ""), (linha["nome"] or "")


#: O texto do aviso. Curto, sem o conteúdo da resposta e SEM o assunto: o que
#: o RH escreveu pode ser sobre salário, saúde ou desligamento, e WhatsApp é
#: lido em tela de bloqueio, muitas vezes num aparelho compartilhado (medido:
#: 5 dos 585 motoristas dividem o número com outro). O canal tem o conteúdo; o
#: aviso só diz que ele existe.
AVISO = ("Voce tem uma resposta do RH no app do motorista.\n"
         "Abra o app para ler.")


def contagem(esquema: str | None = None) -> dict:
    """Para a Saúde do Servidor e o snapshot do Copiloto. SÓ CONTAGENS."""
    r = pglocal.um(
        """SELECT count(*)::int AS total,
                  sum(CASE WHEN status <> 'resolvida' THEN 1 ELSE 0 END)::int AS vivas,
                  sum(CASE WHEN status = 'aberta' THEN 1 ELSE 0 END)::int AS sem_dono,
                  sum(CASE WHEN status <> 'resolvida'
                            AND ultima_em < now() - interval '3 days'
                           THEN 1 ELSE 0 END)::int AS paradas,
                  max(ultima_em) AS ultima
             FROM mot_conversas""", esquema=_esq(esquema)) or {}
    return {"total": r.get("total") or 0, "vivas": r.get("vivas") or 0,
            "sem_dono": r.get("sem_dono") or 0,
            "paradas_3d": r.get("paradas") or 0,
            "ultima": r["ultima"].isoformat() if r.get("ultima") else None}
