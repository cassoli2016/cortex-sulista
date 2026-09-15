# -*- coding: utf-8 -*-
"""A TRATATIVA DA COBRANÇA: o que se está fazendo com cada valor em aberto.

Pedido de quem opera (15/09/2026): na Régua de Cobrança, o responsável
registra o que está sendo EFETIVAMENTE feito com os valores em aberto de cada
cliente, e todo o histórico fica.

QUATRO DECISÕES, cada uma com o porquê:

1. **A unidade é a LINHA DA RÉGUA** — o grupo de cliente, ou o cliente sem
   grupo —, porque é assim que se cobra: liga-se para o grupo, não para cada
   filial dele. O registro pode apontar QUAIS títulos do grupo ele trata (a
   contestação de um CT-e, a promessa que cobre duas faturas), e o servidor
   recusa título que não está em aberto no grupo.
2. **O histórico é SÓ ACRÉSCIMO, e quem garante é o BANCO** (gatilho em
   `sql/cortex/0094_cob_tratativa.sql`). Registro errado se corrige com um
   registro novo que diga o que mudou.
3. **A situação NÃO é gravada, é calculada** a cada leitura (`situacao`):
   "promessa vencida", "retorno atrasado" e "sem movimento" dependem de hoje.
4. **A chave do grupo não sai do servidor.** Ela leva o CNPJ quando o cliente
   não tem grupo (`queries._AGRUP_CHAVE`). A tela recebe `ref`, um resumo da
   chave (`queries.cobranca_ref`); a tabela guarda o `ref`, e o registro se
   confere contra a Régua VIVA do ERP (`linha_da_regua`): não se registra
   tratativa para quem não deve mais.

Cada registro guarda a FOTO do ERP no momento — o vencido e a quantidade de
títulos do grupo —, porque o histórico lido meses depois precisa dizer do que
se falava, e o ERP já terá mudado.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from .. import db, pglocal, queries

log = logging.getLogger("cortex.cobranca_tratativa")

ESQUEMA: str | None = None

TIPOS = {
    "contato": "Contato com o cliente",
    "promessa": "Promessa de pagamento",
    "negociacao": "Negociação / acordo",
    "contestacao": "Cliente contesta o valor",
    "sem_retorno": "Sem retorno do cliente",
    "protesto": "Protesto / negativação",
    "juridico": "Encaminhado ao jurídico",
    "outro": "Outro",
}
CANAIS = {"ligacao": "Ligação", "email": "E-mail", "whatsapp": "WhatsApp",
          "visita": "Visita", "outro": "Outro"}

#: Dias sem nenhum registro para a tratativa virar "sem movimento". Uma semana
#: é o ciclo da cobrança ativa: quem prometeu retorno e sumiu por mais que isso
#: deixou de estar sendo cobrado.
PARADA_DIAS = 7
#: Protesto e jurídico são ENTREGA do caso a outro rito, que anda em meses: ali
#: "sem movimento há 8 dias" seria alarme falso, e alarme falso ensina a
#: ignorar o alarme.
_SEM_PARADA = frozenset({"protesto", "juridico"})
MAX_DESCRICAO = 2000
MAX_TITULOS = 60
#: Promessa registrada DEPOIS de feita é aceita até 30 dias para trás — o
#: registro atrasado é melhor que nenhum, e ele já nasce "promessa vencida" se
#: for o caso. O retorno é o PRÓXIMO passo, então nunca fica no passado.
PROMESSA_PASSADO_DIAS = 30
HORIZONTE_DIAS = 366

_RE_REF = re.compile(r"^[0-9a-f]{16}$")
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_TITULO = re.compile(r"^\d{1,12}/\d{1,4}$")


class Recusa(ValueError):
    """Recusa legível: a mensagem vai para a tela como está."""


def ref_valido(ref) -> bool:
    return isinstance(ref, str) and bool(_RE_REF.match(ref))


# ─────────────────────────────────────────────── a Régua viva, no ERP ─────

# A Régua INTEIRA, sem o corte dos 30 maiores: o filtro por cliente da tela
# alcança grupo que está fora do top 30, e a tratativa tem de valer para ele.
_COB_CLI_TODOS_SQL = queries.COB_CLI_SQL.replace("LIMIT 30", "")
assert _COB_CLI_TODOS_SQL != queries.COB_CLI_SQL, "o corte do top 30 mudou de texto — conferir"


def linha_da_regua(ref: str) -> dict | None:
    """O cliente da Régua VIVA do ERP que tem este `ref`, com o vencido e os
    títulos de agora — ou None, se ele não deve mais nada vencido."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(_COB_CLI_TODOS_SQL, {"filial": None, "cliente": None})
        alvo = next((r for r in cur.fetchall()
                     if queries.cobranca_ref(r["chave"]) == ref), None)
        if alvo is None:
            return None
        cur.execute(queries.COB_TIT_SQL,
                    {"filial": None, "cliente": None, "chaves": [alvo["chave"]]})
        titulos = [f"{t['numero']}/{t['filial']}" for t in cur.fetchall()]
    return {"cliente": alvo["cliente"], "vencido": float(alvo["vencido"] or 0),
            "titulos": titulos}


# ──────────────────────────────────────────────────────────── validação ───

def _data(v, nome: str) -> date | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not _RE_DATA.match(v):
        raise Recusa(f"A {nome} não é uma data válida.")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise Recusa(f"A {nome} não é uma data válida.") from None


def _valor(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Recusa("O valor prometido tem de ser um número.")
    if not 0 < float(v) <= 1e9:
        raise Recusa("O valor prometido tem de ser maior que zero.")
    return round(float(v), 2)


def validar(dados: dict, *, titulos_do_grupo, hoje: date) -> dict:
    """O pedido da tela, limpo — ou `Recusa` dizendo o que falta."""
    if not isinstance(dados, dict):
        raise Recusa("Pedido inválido.")
    tipo = str(dados.get("tipo") or "").strip()
    if tipo not in TIPOS:
        raise Recusa("Escolha o que está sendo feito.")
    canal = str(dados.get("canal") or "").strip() or None
    if canal is not None and canal not in CANAIS:
        raise Recusa("Canal inválido.")
    descricao = str(dados.get("descricao") or "").strip()
    if not descricao:
        raise Recusa("Descreva o que foi feito ou combinado.")
    if len(descricao) > MAX_DESCRICAO:
        raise Recusa(f"A descrição passa de {MAX_DESCRICAO} caracteres.")
    p_data = _data(dados.get("promessa_data"), "data prometida")
    p_valor = _valor(dados.get("promessa_valor"))
    retorno = _data(dados.get("retorno_em"), "data de retorno")
    if tipo == "promessa" and p_data is None:
        raise Recusa("Promessa de pagamento precisa da data prometida.")
    if tipo != "promessa" and (p_data or p_valor):
        raise Recusa("Data e valor prometidos só valem para promessa de pagamento.")
    teto = hoje + timedelta(days=HORIZONTE_DIAS)
    if p_data and not hoje - timedelta(days=PROMESSA_PASSADO_DIAS) <= p_data <= teto:
        raise Recusa(f"A data prometida tem de estar entre {PROMESSA_PASSADO_DIAS} "
                     "dias atrás e um ano à frente.")
    if retorno and not hoje <= retorno <= teto:
        raise Recusa("O próximo retorno tem de ser de hoje em diante, dentro de um ano.")
    brutos = dados.get("titulos") or []
    if not isinstance(brutos, list) or len(brutos) > MAX_TITULOS:
        raise Recusa("Lista de títulos inválida.")
    titulos = sorted({str(t).strip() for t in brutos if str(t).strip()})
    if any(not _RE_TITULO.match(t) for t in titulos):
        raise Recusa("Lista de títulos inválida.")
    permitidos = set(titulos_do_grupo or [])
    fora = [t for t in titulos if t not in permitidos]
    if fora:
        raise Recusa("Título que não está em aberto neste cliente: "
                     + ", ".join(fora[:5]) + ".")
    return {"tipo": tipo, "canal": canal, "descricao": descricao,
            "promessa_data": p_data, "promessa_valor": p_valor,
            "retorno_em": retorno, "titulos": titulos}


# ──────────────────────────────────────────────────── gravar e ler ────────

_CAMPOS = """t.id, t.ref, t.cliente, t.tipo, t.canal, t.descricao, t.promessa_data,
       t.promessa_valor, t.retorno_em, t.titulos, t.vencido_ref, t.titulos_ref,
       t.autor, t.em, u.nome AS autor_nome"""
_DE = """FROM cob_tratativa t
LEFT JOIN usuarios u ON lower(u.email) = lower(t.autor)"""


def _iso(v):
    return v.isoformat() if v is not None else None


def _publicar(r: dict) -> dict:
    """A linha para a tela: rótulos, datas em ISO, e o NOME de quem registrou
    (o e-mail fica no banco e na trilha)."""
    autor = r.get("autor") or ""
    out = {
        "id": r["id"], "tipo": r["tipo"], "tipo_rotulo": TIPOS.get(r["tipo"], r["tipo"]),
        "canal": r["canal"],
        "canal_rotulo": CANAIS.get(r["canal"]) if r["canal"] else None,
        "descricao": r["descricao"],
        "promessa_data": _iso(r["promessa_data"]),
        "promessa_valor": float(r["promessa_valor"]) if r["promessa_valor"] is not None else None,
        "retorno_em": _iso(r["retorno_em"]),
        "titulos": list(r["titulos"] or []),
        "vencido_ref": float(r["vencido_ref"]) if r["vencido_ref"] is not None else None,
        "titulos_ref": r["titulos_ref"],
        "autor_nome": r.get("autor_nome") or autor.split("@")[0],
        "em": _iso(r["em"]),
    }
    if "total" in r:
        out["total"] = int(r["total"])
    return out


def registrar(ref: str, dados: dict, *, autor: str, linha: dict,
              hoje: date | None = None, esquema: str | None = None) -> dict:
    """Grava um registro da tratativa. `linha` é a da Régua viva
    (`linha_da_regua`): dela saem o nome, a foto do vencido e os títulos que o
    registro pode apontar."""
    if not ref_valido(ref):
        raise Recusa("Cliente inválido.")
    if not autor:
        raise Recusa("Sem a sessão de quem registra.")
    limpo = validar(dados, titulos_do_grupo=linha.get("titulos") or [],
                    hoje=hoje or date.today())
    with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cob_tratativa(ref, cliente, tipo, canal, descricao, promessa_data,"
            " promessa_valor, retorno_em, titulos, vencido_ref, titulos_ref, autor)"
            " VALUES (%(ref)s, %(cliente)s, %(tipo)s, %(canal)s, %(descricao)s,"
            " %(promessa_data)s, %(promessa_valor)s, %(retorno_em)s, %(titulos)s::text[],"
            " %(vencido_ref)s, %(titulos_ref)s, %(autor)s) RETURNING id",
            {**limpo, "ref": ref, "cliente": str(linha.get("cliente") or "")[:200],
             "vencido_ref": round(float(linha.get("vencido") or 0), 2),
             "titulos_ref": len(linha.get("titulos") or []), "autor": autor})
        novo = cur.fetchone()["id"]
        cur.execute(f"SELECT {_CAMPOS} {_DE} WHERE t.id = %s", (novo,))
        return _publicar(cur.fetchone())


def historico(ref: str, esquema: str | None = None) -> list[dict]:
    """TODOS os registros de um cliente, do mais novo para o mais antigo."""
    with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_CAMPOS} {_DE} WHERE t.ref = %s ORDER BY t.em DESC, t.id DESC",
                    (ref,))
        return [_publicar(r) for r in cur.fetchall()]


def ultimas(refs, esquema: str | None = None) -> dict[str, dict]:
    """O registro MAIS RECENTE de cada cliente, com quantos ele tem ao todo.
    A janela conta antes do `DISTINCT ON`, então `total` é o do cliente."""
    refs = sorted({r for r in refs if ref_valido(r)})
    if not refs:
        return {}
    with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT ON (t.ref) {_CAMPOS}, count(*) OVER (PARTITION BY t.ref) AS total"
            f" {_DE} WHERE t.ref = ANY(%s::text[]) ORDER BY t.ref, t.em DESC, t.id DESC",
            (refs,))
        return {r["ref"]: _publicar(r) for r in cur.fetchall()}


def registros_desde(quando: date, esquema: str | None = None) -> int:
    r = pglocal.um("SELECT count(*)::int AS n FROM cob_tratativa WHERE em >= %s",
                   (quando,), esquema or ESQUEMA)
    return (r or {}).get("n", 0)


# ─────────────────────────────────────────────── a situação, calculada ────

def _br(d: date) -> str:
    return d.strftime("%d/%m")


def _quando(dias: int) -> str:
    return "hoje" if dias <= 0 else ("ontem" if dias == 1 else f"há {dias} dias")


def situacao(ultima: dict | None, *, hoje: date) -> dict:
    """O estado do cliente a partir do ÚLTIMO registro, contra hoje. A ordem
    é a da urgência: promessa que venceu, retorno que ficou para trás, e só
    então o silêncio."""
    if not ultima:
        return {"estado": "sem_tratativa", "nivel": "warn", "rotulo": "sem tratativa"}
    tipo = ultima["tipo"]
    dias = (hoje - datetime.fromisoformat(ultima["em"]).date()).days
    prom = date.fromisoformat(ultima["promessa_data"]) if ultima.get("promessa_data") else None
    ret = date.fromisoformat(ultima["retorno_em"]) if ultima.get("retorno_em") else None
    rotulo = TIPOS.get(tipo, tipo).lower()
    if tipo == "promessa" and prom and prom < hoje:
        return {"estado": "promessa_vencida", "nivel": "bad",
                "rotulo": f"promessa vencida em {_br(prom)}"}
    if ret and ret < hoje:
        return {"estado": "retorno_atrasado", "nivel": "warn",
                "rotulo": f"retorno atrasado desde {_br(ret)}"}
    if tipo == "promessa" and prom:
        return {"estado": "promessa", "nivel": "good", "rotulo": f"promessa para {_br(prom)}"}
    if ret:
        return {"estado": "em_andamento", "nivel": "good",
                "rotulo": f"{rotulo} · retorno {_br(ret)}"}
    if dias > PARADA_DIAS and tipo not in _SEM_PARADA:
        return {"estado": "parada", "nivel": "warn", "rotulo": f"sem movimento há {dias} dias"}
    return {"estado": "em_andamento", "nivel": "good", "rotulo": f"{rotulo} · {_quando(dias)}"}


def _montar(u: dict | None, vencido, hoje: date) -> dict:
    u = dict(u) if u else None
    total = u.pop("total", 1) if u else 0
    novo = None
    if u and u.get("vencido_ref") is not None:
        d = round(float(vencido or 0) - u["vencido_ref"], 2)
        # o vencido que CRESCEU desde o último registro: título novo vencendo
        # sem que ninguém tenha falado dele
        novo = d if d >= 1 else None
    return {**situacao(u, hoje=hoje), "total": total, "ultima": u, "vencido_novo": novo}


def tratativa_de(ref: str, vencido, *, hoje: date | None = None,
                 esquema: str | None = None) -> dict:
    return _montar(ultimas([ref], esquema=esquema).get(ref), vencido, hoje or date.today())


def anexar(d: dict, *, hoje: date | None = None, esquema: str | None = None) -> dict:
    """A Régua com a tratativa de cada cliente — numa CÓPIA: o dicionário que
    chega é o do cache de `get_cobranca`, e escrever nele deixaria a tratativa
    de 90 segundos atrás grudada na próxima leitura.

    Sem o banco da casa a Régua segue (os valores são do ERP) e a tratativa
    vira None com `disponivel: False` — nunca "sem tratativa", que afirmaria
    que alguém conferiu."""
    hoje = hoje or date.today()
    novo = dict(d)
    clientes = [dict(c) for c in (d.get("clientes") or [])]
    novo["clientes"] = clientes
    base = {"tipos": TIPOS, "canais": CANAIS, "parada_dias": PARADA_DIAS}
    try:
        ult = ultimas([c.get("ref") for c in clientes], esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        log.warning("tratativas: leitura falhou (%s)", type(exc).__name__)
        for c in clientes:
            c["tratativa"] = None
        novo["tratativas"] = {**base, "disponivel": False}
        return novo
    contagem = {"sem_tratativa": 0, "promessa_vencida": 0, "retorno_atrasado": 0, "parada": 0}
    valor = dict.fromkeys(contagem, 0.0)
    for c in clientes:
        t = _montar(ult.get(c.get("ref")), c.get("vencido"), hoje)
        c["tratativa"] = t
        if t["estado"] in contagem:
            contagem[t["estado"]] += 1
            valor[t["estado"]] += float(c.get("vencido") or 0)
    novo["tratativas"] = {**base, "disponivel": True, "contagem": contagem,
                          "valor": {k: round(v, 2) for k, v in valor.items()}}
    return novo


def resumo_copiloto() -> dict:
    """Para o snapshot do Copiloto: SÓ ESCALARES — nenhum nome de cliente."""
    d = anexar(queries.get_cobranca(None))
    out = {"universo": "clientes da Régua de Cobrança (os 30 maiores saldos vencidos)",
           "clientes_na_regua": len(d["clientes"])}
    t = d["tratativas"]
    if not t["disponivel"]:
        return {**out, "tratativas_indisponiveis": True}
    for k, n in t["contagem"].items():
        out[f"clientes_{k}"] = n
        out[f"vencido_{k}"] = t["valor"][k]
    out["registros_ultimos_7_dias"] = registros_desde(date.today() - timedelta(days=7))
    return out
