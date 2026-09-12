# -*- coding: utf-8 -*-
"""Os avisos do app do motorista — o que é NOVO para ele, no app e no celular.

PEDIDO DE QUEM OPERA (11/09/2026): "notificações quando tiver algo novo
relacionado ao motorista ou recado do RH". Os tipos foram escolhidos por quem
opera: recado do RH (a conversa e o mural), multa nova, registro novo no ERP e
viagem nova programada.

TRÊS DECISÕES QUE ESTE MÓDULO CARREGA
=====================================
1. **O AVISO NÃO LEVA CONTEÚDO para fora do app.** A notificação é lida na TELA
   DE BLOQUEIO, às vezes num aparelho compartilhado (5 dos 585 motoristas
   dividem o número) — a mesma regra do aviso do RH por WhatsApp
   (`conversas.AVISO`). O push diz "o RH respondeu", "há uma nova multa"; o que
   foi e quanto é, só dentro do app, com a sessão dele.
2. **A LISTA DE AVISOS É A FONTE, e o push é o mensageiro.** Todo aviso nasce
   numa linha de `mot_avisos`, que o app mostra na aba Avisos com "não lido";
   o push só entrega a quem ligou a notificação. Quem não ligou — ou está num
   iPhone sem o app na Tela de Início — vê o mesmo aviso ao abrir o app.
3. **O QUE VEM DE FORA SE DESCOBRE POR VARREDURA, e a PRIMEIRA passada não
   avisa.** Multa (Smartec), registro e viagem (ERP) não passam por este
   código: o relógio (`agendador.py`) compara o que existe agora com o que já
   foi visto, por motorista e por tipo. Na primeira vez que um motorista é
   varrido, o que já existe vira VISTO e ninguém é avisado — senão o primeiro
   dia do sistema seria uma avalanche de novidades de duas semanas atrás.

**O ACESSO MESTRE NÃO MARCA NEM INSCREVE:** quem administra conferindo o app de
um motorista não pode apagar o "não lido" dele, e o celular de quem confere não
pode passar a receber as notificações de outra pessoa.

**O CÓDIGO DO ERP** (para pessoa física, o CPF) é a chave interna, como no
resto do módulo, e não sai: nem no payload, nem no push.
"""
from __future__ import annotations

import json
import logging

from api import pglocal

from .conversas import Recusa

log = logging.getLogger("cortex.motorista.avisos")

#: tipo -> o que o PUSH diz (um e vários), a aba do app que responde e o
#: rótulo da lista. O texto do push é GENÉRICO de propósito — ver o docstring.
TIPOS: dict[str, dict] = {
    "rh": {"um": "Você tem uma resposta do RH.",
           "varios": "Você tem {n} respostas do RH.",
           "aba": "rh", "rotulo": "Resposta do RH"},
    "mural": {"um": "Há um novo recado do RH.",
              "varios": "Há {n} novos recados do RH.",
              "aba": "rh", "rotulo": "Recado do RH"},
    "multa": {"um": "Há uma nova multa no seu app.",
              "varios": "Há {n} novas multas no seu app.",
              "aba": "multas", "rotulo": "Multa"},
    "registro": {"um": "Há um novo registro no seu app.",
                 "varios": "Há {n} novos registros no seu app.",
                 "aba": "registros", "rotulo": "Registro"},
    "viagem": {"um": "Você tem uma nova viagem programada.",
               "varios": "Você tem {n} novas viagens programadas.",
               "aba": "viagem", "rotulo": "Viagem"},
}
CORPO_PUSH = "Abra o app do motorista para ver."

#: As fontes da VARREDURA (as outras duas nascem na rota do RH).
FONTES = ("multa", "registro", "viagem")
#: O que entrou na fonte nos últimos N dias. Curto de propósito: a varredura
#: roda de dez em dez minutos, e o que importa é o que acabou de chegar.
JANELA_DIAS = 15
#: `mot_avisos_vistos` guarda isto; a janela é bem menor, então nada que já saiu
#: dela volta a ser "novo".
PODA_VISTOS_DIAS = 60
LIMITE_LISTA = 40
LIMITE_DESPACHO = 400
#: Aviso mais velho que isto, ainda não entregue (API fora do ar, por exemplo),
#: é carimbado sem push: "nova viagem" de ontem à noite, chegando agora, é
#: notícia velha com cara de nova.
VELHO_PARA_PUSH_H = 6


def _esq(esquema: str | None = None) -> str | None:
    """O schema lido NA CHAMADA — ver `sessao._esq`."""
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def texto_push(tipo: str, n: int = 1) -> str:
    t = TIPOS[tipo]
    return t["um"] if n <= 1 else t["varios"].format(n=n)


# ═══════════════════════════════════════════════════════ registrar ═══════

def registrar(motorista_codigo: str, tipo: str, ref: str, detalhe: str = "",
              *, esquema: str | None = None) -> int | None:
    """Um aviso para UM motorista. Devolve o id novo, ou None se já existia."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo de aviso desconhecido: {tipo}")
    linha = pglocal.um(
        """INSERT INTO mot_avisos(motorista_codigo, tipo, ref, detalhe)
           VALUES (%(c)s, %(t)s, %(r)s, %(d)s)
           ON CONFLICT (motorista_codigo, tipo, ref) DO NOTHING
           RETURNING id""",
        {"c": str(motorista_codigo), "t": tipo, "r": str(ref)[:200],
         "d": (detalhe or "")[:200]}, _esq(esquema))
    return int(linha["id"]) if linha else None


def para_todos(tipo: str, ref: str, detalhe: str = "", *,
               esquema: str | None = None) -> int:
    """O mesmo aviso para TODO motorista ativo, numa instrução só (o mural)."""
    with pglocal.get_conn(_esq(esquema)) as cx:
        with cx.cursor() as cur:
            cur.execute(
                """INSERT INTO mot_avisos(motorista_codigo, tipo, ref, detalhe)
                   SELECT motorista_codigo, %s, %s, %s
                     FROM mot_vinculos WHERE ativo
                   ON CONFLICT (motorista_codigo, tipo, ref) DO NOTHING""",
                (tipo, str(ref)[:200], (detalhe or "")[:200]))
            n = cur.rowcount
        cx.commit()
    return n


def da_conversa(conversa_id, *, esquema: str | None = None) -> int | None:
    """O aviso de "o RH escreveu" nesta conversa. A REF é a ÚLTIMA mensagem do
    RH: cada resposta nova é um aviso novo, e a mesma resposta é um só."""
    linha = pglocal.um(
        """SELECT c.motorista_codigo, c.titulo,
                  (SELECT max(m.id) FROM mot_mensagens m
                    WHERE m.conversa_id = c.id AND m.papel = 'rh') AS msg
             FROM mot_conversas c
             JOIN mot_vinculos v ON v.motorista_codigo = c.motorista_codigo
            WHERE c.id = %(id)s AND v.ativo""",
        {"id": int(conversa_id)}, _esq(esquema))
    if not linha or not linha["msg"]:
        return None
    return registrar(linha["motorista_codigo"], "rh", "msg:%d" % linha["msg"],
                     linha["titulo"] or "", esquema=esquema)


# ═══════════════════════════════════════════════════════ o motorista ═════

def nao_lidos(motorista_codigo: str, esquema: str | None = None) -> int:
    r = pglocal.um(
        """SELECT count(*)::int AS n FROM mot_avisos
            WHERE motorista_codigo = %(c)s AND lido_em IS NULL""",
        {"c": str(motorista_codigo)}, _esq(esquema))
    return int((r or {}).get("n") or 0)


def meus(sessao: dict, esquema: str | None = None) -> dict:
    """A aba Avisos: os últimos avisos DELE, quantos não leu, e o estado da
    notificação neste servidor. O código sai da SESSÃO, nunca do pedido."""
    from api import push
    esq = _esq(esquema)
    cod = str(sessao["motorista_codigo"])
    linhas = pglocal.query(
        """SELECT id, tipo, detalhe, criado_em, lido_em FROM mot_avisos
            WHERE motorista_codigo = %(c)s
            ORDER BY criado_em DESC, id DESC LIMIT %(n)s""",
        {"c": cod, "n": LIMITE_LISTA}, esq)
    aparelhos = pglocal.um(
        "SELECT count(*)::int AS n FROM mot_push_subs WHERE motorista_codigo = %(c)s",
        {"c": cod}, esq)
    ligado = push.habilitado()
    return {
        "itens": [{"id": int(l["id"]), "tipo": l["tipo"],
                   "rotulo": TIPOS[l["tipo"]]["rotulo"],
                   "titulo": TIPOS[l["tipo"]]["um"],
                   "detalhe": l["detalhe"] or "",
                   "aba": TIPOS[l["tipo"]]["aba"],
                   "quando": l["criado_em"].isoformat(),
                   "lido": l["lido_em"] is not None} for l in linhas],
        "nao_lidos": nao_lidos(cod, esq),
        "push": {"habilitado": ligado,
                 # A chave PÚBLICA do VAPID: é pública por definição (o
                 # navegador precisa dela para se inscrever). A privada nunca
                 # sai de `api/push.py`.
                 "chave": push._pub() if ligado else "",
                 "aparelhos": int((aparelhos or {}).get("n") or 0),
                 "mestre": bool(sessao.get("mestre"))},
    }


def marcar_lidos(sessao: dict, ids=None, aba: str = "",
                 esquema: str | None = None) -> dict:
    """Marca como lido: os ids pedidos, ou os de uma ABA (ao abri-la), ou todos.
    Sempre só os DELE — o código da sessão está no WHERE."""
    if sessao.get("mestre"):
        return {"ok": True, "marcados": 0, "mestre": True}
    params: dict = {"c": str(sessao["motorista_codigo"])}
    filtro = ""
    if ids:
        try:
            params["ids"] = [int(i) for i in list(ids)[:200]]
        except (TypeError, ValueError):
            raise Recusa("Aviso inválido.") from None
        filtro = " AND id = ANY(%(ids)s)"
    elif aba:
        tipos = [t for t, v in TIPOS.items() if v["aba"] == aba]
        if not tipos:
            raise Recusa("Aba desconhecida.")
        params["tipos"] = tipos
        filtro = " AND tipo = ANY(%(tipos)s)"
    with pglocal.get_conn(_esq(esquema)) as cx:
        with cx.cursor() as cur:
            cur.execute(
                "UPDATE mot_avisos SET lido_em = now() "
                "WHERE motorista_codigo = %(c)s AND lido_em IS NULL" + filtro, params)
            n = cur.rowcount
        cx.commit()
    return {"ok": True, "marcados": n}


def inscrever(sessao: dict, sub: dict, esquema: str | None = None) -> dict:
    """Liga a notificação NESTE aparelho. Um endereço de push tem UM dono: o
    celular compartilhado passa a avisar quem ligou por último nele."""
    from api import push
    if sessao.get("mestre"):
        raise Recusa("No acesso da administração as notificações ficam "
                     "desligadas: elas iriam para o celular de quem está "
                     "conferindo, e não para o do motorista.")
    if not push.habilitado():
        raise Recusa("As notificações ainda não estão ligadas no servidor.")
    sub = sub if isinstance(sub, dict) else {}
    ep = str(sub.get("endpoint") or "")
    chaves = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    if (not ep.startswith("https://") or len(ep) > 1000
            or not chaves.get("p256dh") or not chaves.get("auth")):
        raise Recusa("Este navegador não mandou uma inscrição válida.")
    pglocal.executar(
        """INSERT INTO mot_push_subs(endpoint, p256dh, auth, motorista_codigo)
           VALUES (%(e)s, %(p)s, %(a)s, %(c)s)
           ON CONFLICT (endpoint) DO UPDATE SET p256dh = excluded.p256dh,
             auth = excluded.auth, motorista_codigo = excluded.motorista_codigo,
             falhas = 0""",
        {"e": ep, "p": str(chaves["p256dh"])[:300], "a": str(chaves["auth"])[:300],
         "c": str(sessao["motorista_codigo"])}, _esq(esquema))
    return {"ok": True, "id": int(sessao["motorista_id"])}


def desinscrever(sessao: dict, endpoint: str, esquema: str | None = None) -> dict:
    """Desliga a notificação deste aparelho — só se o aparelho for DELE."""
    pglocal.executar(
        "DELETE FROM mot_push_subs WHERE endpoint = %(e)s AND motorista_codigo = %(c)s",
        {"e": str(endpoint or ""), "c": str(sessao["motorista_codigo"])},
        _esq(esquema))
    return {"ok": True, "id": int(sessao["motorista_id"])}


# ═══════════════════════════════════════════════════════ o push ══════════

def _webpush(sub: dict, payload: str) -> str:
    """Um push. `ok`, `morta` (o navegador desinstalou/expirou) ou `falha`."""
    from pywebpush import WebPushException, webpush

    from api import push
    info = {"endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
    try:
        webpush(info, payload, vapid_private_key=push._priv(),
                vapid_claims={"sub": push._subject()}, ttl=3600)
        return "ok"
    except WebPushException as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code in (404, 410):
            return "morta"
        log.warning("push do motorista falhou (%s)", code)
        return "falha"
    except Exception as exc:  # noqa: BLE001
        log.warning("push do motorista: %s", type(exc).__name__)
        return "falha"


def despachar(esquema: str | None = None, enviar=None) -> dict:
    """Entrega os avisos ainda não entregues. UM push por motorista e por tipo:
    três multas novas na mesma passada são "Há 3 novas multas", não três
    vibrações seguidas. `enviar` existe para o teste — nenhum teste manda push.
    """
    from api import push
    esq = _esq(esquema)
    if enviar is None and not push.habilitado():
        return {"enviados": 0, "motivo": "push desligado no servidor"}
    enviar = enviar or _webpush
    pend = pglocal.query(
        """SELECT id, motorista_codigo, tipo,
                  (criado_em < now() - %(velho)s * interval '1 hour') AS velho
             FROM mot_avisos WHERE push_em IS NULL
            ORDER BY id LIMIT %(n)s""",
        {"n": LIMITE_DESPACHO, "velho": VELHO_PARA_PUSH_H}, esq)
    if not pend:
        return {"enviados": 0}
    codigos = sorted({p["motorista_codigo"] for p in pend})
    subs: dict[str, list] = {}
    for s in pglocal.query(
            "SELECT * FROM mot_push_subs WHERE motorista_codigo = ANY(%(c)s)",
            {"c": codigos}, esq):
        subs.setdefault(s["motorista_codigo"], []).append(s)

    grupos: dict[tuple, list] = {}
    for p in pend:
        grupos.setdefault((p["motorista_codigo"], p["tipo"], bool(p["velho"])), []).append(p)
    enviados = 0
    for (cod, tipo, velho), avisos in grupos.items():
        entregues = 0
        if not velho:
            payload = json.dumps({"title": texto_push(tipo, len(avisos)),
                                  "body": CORPO_PUSH,
                                  "url": "/motorista#" + TIPOS[tipo]["aba"],
                                  "tag": "motorista-" + tipo})
            for s in subs.get(cod, []):
                r = enviar(s, payload)
                if r == "ok":
                    entregues += 1
                    pglocal.executar(
                        "UPDATE mot_push_subs SET ultimo_ok_em = now(), falhas = 0 "
                        "WHERE endpoint = %(e)s", {"e": s["endpoint"]}, esq)
                elif r == "morta":
                    pglocal.executar("DELETE FROM mot_push_subs WHERE endpoint = %(e)s",
                                     {"e": s["endpoint"]}, esq)
                else:
                    pglocal.executar(
                        "UPDATE mot_push_subs SET falhas = falhas + 1 WHERE endpoint = %(e)s",
                        {"e": s["endpoint"]}, esq)
        pglocal.executar(
            "UPDATE mot_avisos SET push_em = now(), entregues = %(n)s "
            "WHERE id = ANY(%(ids)s)",
            {"n": entregues, "ids": [int(a["id"]) for a in avisos]}, esq)
        enviados += entregues
    return {"enviados": enviados, "avisos": len(pend)}


# ═══════════════════════════════════════════════════════ a varredura ═════

_MULTAS_SQL = """
SELECT v.motorista_codigo AS codigo, v.identificador AS ref,
       coalesce(i.descricao, '') AS descricao,
       to_char(i.data_infracao, 'DD/MM') AS data
  FROM smt_infracao_viagem v
  JOIN smt_infracoes i ON i.identificador = v.identificador
 WHERE v.motorista_codigo = ANY(%(mots)s)
   AND v.casada_em >= now() - %(dias)s * interval '1 day'
"""

# AS DUAS DO ERP SÃO UMA CONSULTA PARA A FROTA INTEIRA, e não uma por
# motorista: a varredura roda de dez em dez minutos, e oitenta idas ao ERP por
# passada seriam oitenta chances de disputar a réplica com quem está usando o
# painel. A chave de cada linha é a CHAVE PRIMÁRIA da tabela no ERP — a data,
# ali, é de dia inteiro e se preenche com atraso.
_REGISTROS_SQL = """
SELECT m.cnpjcpfcodigo AS codigo,
       concat_ws('.', m.grupo, m.empresa, m.vinculo, m.filialdigitado,
                 m.unidadedigitado, m.sequencia) AS ref,
       regexp_replace(coalesce(o.descricao,''), '[^ -ÿ]', '', 'g') AS tipo,
       to_char(m.dt, 'DD/MM') AS data
  FROM cadastro_vinculo_motoristaocorrencia m
  LEFT JOIN ocorrenciamotorista o ON o.codigo = m.ocorrenciamotorista
 WHERE m.cnpjcpfcodigo = ANY(%(mots)s)
   AND m.dtinc >= current_date - %(dias)s
"""

# A MESMA POLÍTICA DA ABA VIAGEM (`viagem.VIAGEM_SQL`): cancelada não conta, e
# só a programação liberada (`semaforo = 1`). Duas telas lendo a mesma fonte
# com políticas diferentes discordam por construção — o aviso diria "nova
# viagem" de uma programação que a aba não mostra.
_VIAGENS_SQL = """
SELECT trim(cast(p.motorista AS text)) AS codigo,
       concat_ws('.', p.grupo, p.empresa, p.diferenciadornumero, p.numero) AS ref,
       coalesce(nullif(trim(p.cidadeorigem),''),'')  AS cidade_origem,
       coalesce(nullif(trim(p.uforigem),''),'')      AS uf_origem,
       coalesce(nullif(trim(p.cidadedestino),''),'') AS cidade_destino,
       coalesce(nullif(trim(p.ufdestino),''),'')     AS uf_destino
  FROM programacaoembarque p
 WHERE trim(cast(p.motorista AS text)) = ANY(%(mots)s)
   AND p.dtcancelamento IS NULL
   AND p.semaforo = 1
   AND p.dtinc >= current_date - %(dias)s
"""


def _cidade(c: str, uf: str) -> str:
    c, uf = (c or "").strip(), (uf or "").strip()
    return f"{c}/{uf}" if c and uf else (c or uf)


def _ler_multas(ativos: list[str], esq) -> list[dict]:
    return [{"codigo": l["codigo"], "ref": l["ref"],
             "detalhe": " · ".join(x for x in ((l["descricao"] or "")[:80], l["data"] or "") if x)}
            for l in pglocal.query(_MULTAS_SQL, {"mots": ativos, "dias": JANELA_DIAS}, esq)]


def _ler_registros(ativos: list[str], esq) -> list[dict]:
    from api import db
    return [{"codigo": str(l["codigo"]).strip(), "ref": l["ref"],
             "detalhe": " · ".join(x for x in ((l["tipo"] or "").strip()[:80], l["data"] or "") if x)}
            for l in db.query(_REGISTROS_SQL, {"mots": ativos, "dias": JANELA_DIAS})]


def _ler_viagens(ativos: list[str], esq) -> list[dict]:
    from api import db
    saida = []
    for l in db.query(_VIAGENS_SQL, {"mots": ativos, "dias": JANELA_DIAS}):
        o = _cidade(l["cidade_origem"], l["uf_origem"])
        d = _cidade(l["cidade_destino"], l["uf_destino"])
        saida.append({"codigo": str(l["codigo"]).strip(), "ref": l["ref"],
                      "detalhe": f"{o} → {d}" if o and d else (o or d)})
    return saida


LEITORES = {"multa": _ler_multas, "registro": _ler_registros, "viagem": _ler_viagens}


def _comparar(tipo: str, ativos: list[str], itens: list[dict], esq) -> dict:
    """Decide o que é NOVO e grava. A primeira passada de cada motorista vira
    base (vista, sem aviso); as seguintes avisam só o que ainda não foi visto."""
    conjunto = set(ativos)
    marcados = {l["motorista_codigo"] for l in pglocal.query(
        "SELECT motorista_codigo FROM mot_avisos_marca WHERE tipo = %(t)s",
        {"t": tipo}, esq)}
    vistos = {(l["motorista_codigo"], l["ref"]) for l in pglocal.query(
        """SELECT motorista_codigo, ref FROM mot_avisos_vistos
            WHERE tipo = %(t)s AND motorista_codigo = ANY(%(c)s)""",
        {"t": tipo, "c": ativos}, esq)}
    novos, ja = [], set()
    for i in itens:
        chave = (i["codigo"], str(i["ref"]))
        if i["codigo"] in conjunto and chave not in vistos and chave not in ja:
            ja.add(chave)
            novos.append(i)
    avisados = 0
    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            for i in novos:
                cur.execute(
                    """INSERT INTO mot_avisos_vistos(motorista_codigo, tipo, ref)
                       VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (i["codigo"], tipo, str(i["ref"])[:200]))
                if i["codigo"] in marcados:
                    cur.execute(
                        """INSERT INTO mot_avisos(motorista_codigo, tipo, ref, detalhe)
                           VALUES (%s,%s,%s,%s)
                           ON CONFLICT (motorista_codigo, tipo, ref) DO NOTHING""",
                        (i["codigo"], tipo, str(i["ref"])[:200],
                         (i.get("detalhe") or "")[:200]))
                    avisados += cur.rowcount
            base = sorted(conjunto - marcados)
            for c in base:
                cur.execute(
                    """INSERT INTO mot_avisos_marca(motorista_codigo, tipo)
                       VALUES (%s,%s) ON CONFLICT DO NOTHING""", (c, tipo))
        cx.commit()
    return {"novos": avisados, "base": len(base), "lidos": len(itens)}


def varrer(esquema: str | None = None, leitores: dict | None = None) -> dict:
    """Uma passada pelas três fontes. Uma fonte que cai NÃO derruba as outras,
    e NUNCA levanta para quem chamou — o relógio não pode morrer porque o ERP
    teve uma manhã ruim. `leitores` existe para o teste: nenhum teste lê o ERP."""
    esq = _esq(esquema)
    leitores = {**LEITORES, **(leitores or {})}
    ativos = [l["motorista_codigo"] for l in pglocal.query(
        "SELECT motorista_codigo FROM mot_vinculos WHERE ativo", esquema=esq)]
    resultado: dict = {}
    if ativos:
        for tipo in FONTES:
            try:
                resultado[tipo] = _comparar(tipo, ativos, leitores[tipo](ativos, esq), esq)
            except Exception as exc:  # noqa: BLE001
                log.warning("varredura de avisos (%s) falhou: %s", tipo, type(exc).__name__)
                resultado[tipo] = {"erro": type(exc).__name__}
    erros = "; ".join(f"{t}: {r['erro']}" for t, r in resultado.items() if "erro" in r)
    novos = sum(r.get("novos", 0) for r in resultado.values())
    pglocal.executar(
        """INSERT INTO mot_avisos_varredura(id, rodou_em, erro, novos)
           VALUES (1, now(), %(e)s, %(n)s)
           ON CONFLICT (id) DO UPDATE SET rodou_em = excluded.rodou_em,
             erro = excluded.erro, novos = excluded.novos""",
        {"e": erros or None, "n": novos}, esq)
    pglocal.executar(
        "DELETE FROM mot_avisos_vistos WHERE visto_em < now() - %(d)s * interval '1 day'",
        {"d": PODA_VISTOS_DIAS}, esq)
    return resultado


# ═══════════════════════════════════════════════════════ a Saúde ═════════

def contagem(esquema: str | None = None) -> dict:
    """Para a Saúde do Servidor e o Copiloto. SÓ CONTAGENS."""
    r = pglocal.um(
        """SELECT (SELECT count(DISTINCT motorista_codigo) FROM mot_push_subs)::int AS inscritos,
                  (SELECT count(*) FROM mot_push_subs)::int AS aparelhos,
                  (SELECT count(*) FROM mot_avisos
                    WHERE criado_em > now() - interval '24 hours')::int AS avisos_24h,
                  (SELECT count(*) FROM mot_avisos WHERE push_em IS NULL)::int AS pendentes,
                  (SELECT rodou_em FROM mot_avisos_varredura WHERE id = 1) AS varredura_em,
                  (SELECT erro FROM mot_avisos_varredura WHERE id = 1) AS varredura_erro""",
        esquema=_esq(esquema)) or {}
    return {"inscritos": int(r.get("inscritos") or 0),
            "aparelhos": int(r.get("aparelhos") or 0),
            "avisos_24h": int(r.get("avisos_24h") or 0),
            "pendentes": int(r.get("pendentes") or 0),
            "varredura_em": r.get("varredura_em"),
            "varredura_erro": r.get("varredura_erro")}
