"""O que mora no banco da casa: o PERFIL de cada cliente e os AJUSTES.

O perfil é a regra de cobrança do cliente (como a conta se faz) e o layout
(como ele recebe). O ajuste é a correção de UM horário de UMA coleta, com
motivo. Nenhum dos dois tem valor padrão escondido: o que não foi dito HERDA
o padrão da casa, e o padrão está escrito aqui (`PADRAO`).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from psycopg.types.json import Jsonb

from .. import pglocal
from . import planilha, regras

log = logging.getLogger("cortex.horas_paradas")

ESQUEMA: str | None = None

#: Qual horário decide em que período a carga cai. O padrão é o FIM DA
#: DESCARGA porque é quando a conta fecha: antes dele, a estadia da descarga
#: ainda está correndo, e cobrar a carga pela metade para completar depois
#: faria o mesmo frete aparecer em duas semanas.
RECORTES = {
    "fim_descarga": "descarga_saida",
    "chegada_descarga": "descarga_chegada",
    "saida_carga": "carga_saida",
    "janela_carga": "carga_janela",
}
PERIODOS = ("dia", "semana", "mes")

PADRAO = {
    "inicio_carga": regras.MAIOR,
    "inicio_descarga": regras.MAIOR,
    "arredondamento_min": 0,
    "recorte": "fim_descarga",
    "periodo": "semana",
    "regras": [],
    "colunas": [{"campo": c, "titulo": planilha.CATALOGO[c][0]}
                for c in planilha.COLUNAS_PADRAO],
    "aba": "",
    "arquivo": "",
}

CAMPOS_HORA = ("carga_janela", "carga_chegada", "carga_saida",
               "descarga_janela", "descarga_chegada", "descarga_saida")
CAMPOS_AJUSTE = CAMPOS_HORA + ("incluir", "referencia")
MOTIVO_MIN = 5
LIMITE_REGRAS = 50
LIMITE_COLUNAS = 60


class Recusa(ValueError):
    """Pedido que não se grava, com a razão legível para quem pediu."""


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def _texto(v, teto: int) -> str:
    return " ".join(str(v or "").split())[:teto]


def _opcional_num(v, nome: str, teto: float):
    if v is None or v == "":
        return None          # HERDA — nunca zero
    try:
        x = float(str(v).replace(",", "."))
    except ValueError:
        raise Recusa("%s precisa ser um número." % nome) from None
    if not 0 <= x <= teto:
        raise Recusa("%s fora da faixa (0 a %s)." % (nome, teto))
    return x


def validar_config(cfg: dict | None) -> dict:
    """A configuração normalizada, ou `Recusa` com o motivo.

    CHAVE AUSENTE = HERDA O PADRÃO (regra da casa para edição parcial). Uma
    configuração vazia é um perfil que cobra pelo padrão da casa, e isso é
    válido.
    """
    cfg = dict(cfg or {})
    out: dict = {}
    for perna in regras.PERNAS:
        k = "inicio_" + perna
        v = cfg.get(k, PADRAO[k])
        if v not in regras.INICIOS:
            raise Recusa("Início do relógio (%s) inválido: %r." % (perna, v))
        out[k] = v
    arr = int(cfg.get("arredondamento_min", PADRAO["arredondamento_min"]) or 0)
    if arr not in regras.ARREDONDAMENTOS:
        raise Recusa("Arredondamento deve ser um de %s minutos." % (regras.ARREDONDAMENTOS,))
    out["arredondamento_min"] = arr
    rec = cfg.get("recorte", PADRAO["recorte"])
    if rec not in RECORTES:
        raise Recusa("Recorte do período inválido: %r." % rec)
    out["recorte"] = rec
    per = cfg.get("periodo", PADRAO["periodo"])
    if per not in PERIODOS:
        raise Recusa("Período inválido: %r." % per)
    out["periodo"] = per
    out["aba"] = _texto(cfg.get("aba", ""), 31)
    out["arquivo"] = _texto(cfg.get("arquivo", ""), 100)

    rs = cfg.get("regras", [])
    if not isinstance(rs, list) or len(rs) > LIMITE_REGRAS:
        raise Recusa("Regras: até %d, em lista." % LIMITE_REGRAS)
    out["regras"] = []
    for i, r in enumerate(rs, start=1):
        if not isinstance(r, dict):
            raise Recusa("Regra %d inválida." % i)
        perna = r.get("perna") or "ambas"
        if perna not in ("carga", "descarga", "ambas"):
            raise Recusa("Regra %d: perna inválida." % i)
        inicio = r.get("inicio") or None
        if inicio is not None and inicio not in regras.INICIOS:
            raise Recusa("Regra %d: início do relógio inválido." % i)
        clausula = r.get("clausula") or None
        if clausula not in (None, "generica"):
            raise Recusa("Regra %d: cláusula inválida." % i)
        mercs = [_texto(m, 80) for m in (r.get("mercadorias") or []) if _texto(m, 80)]
        dests = [_texto(d, 20) for d in (r.get("destinos") or []) if _texto(d, 20)]
        regra = {
            "nome": _texto(r.get("nome"), 80) or ("Regra %d" % i),
            "perna": perna, "mercadorias": mercs[:40], "destinos": dests[:40],
            "inicio": inicio, "clausula": clausula,
            "freetime_h": _opcional_num(r.get("freetime_h"), "Regra %d: freetime" % i, 72),
            "valor_h": _opcional_num(r.get("valor_h"), "Regra %d: valor da hora" % i, 10000),
        }
        # REGRA QUE NÃO MUDA NADA não entra calada: ela "casa" e responde,
        # e a linha passaria a dizer que foi ela — sem ter feito coisa
        # alguma. É permitida só quando é EXCEÇÃO de uma geral que vem
        # depois (manter o contrato para um destino antes de trocar para
        # os demais), e aí precisa ter condição.
        if not (regra["inicio"] or regra["clausula"] or regra["freetime_h"] is not None
                or regra["valor_h"] is not None) and not (mercs or dests):
            raise Recusa("Regra %d não tem condição nem efeito." % i)
        out["regras"].append(regra)

    cols = cfg.get("colunas", PADRAO["colunas"])
    if not isinstance(cols, list) or not cols or len(cols) > LIMITE_COLUNAS:
        raise Recusa("Colunas da planilha: de 1 a %d." % LIMITE_COLUNAS)
    out["colunas"] = []
    for c in cols:
        campo = (c or {}).get("campo") if isinstance(c, dict) else c
        if campo not in planilha.CATALOGO:
            raise Recusa("Coluna desconhecida: %r." % campo)
        titulo = _texto((c or {}).get("titulo") if isinstance(c, dict) else "", 60)
        out["colunas"].append({"campo": campo,
                               "titulo": titulo or planilha.CATALOGO[campo][0]})
    return out


def _linha_perfil(r: dict) -> dict:
    r = dict(r)
    r["config"] = validar_config(r.get("config") or {})
    for k in ("criado_em", "atualizado_em"):
        if r.get(k) is not None:
            r[k] = r[k].isoformat()
    return r


def listar_perfis(esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hp_perfil ORDER BY cliente_nome, id")
        return [_linha_perfil(r) for r in cur.fetchall()]


def perfil(pid: int, esquema: str | None = None) -> dict | None:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hp_perfil WHERE id = %s", (int(pid),))
        r = cur.fetchone()
    return _linha_perfil(r) if r else None


def criar_perfil(cliente_codigo: int, cliente_nome: str, autor: str,
                 esquema: str | None = None) -> dict:
    if not autor:
        raise Recusa("Perfil sem autor não entra.")
    cfg = validar_config({})
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM hp_perfil WHERE cliente_codigo = %s",
                    (int(cliente_codigo),))
        if cur.fetchone():
            raise Recusa("Este cliente já tem perfil de horas paradas.")
        cur.execute(
            """INSERT INTO hp_perfil (cliente_codigo, cliente_nome, config,
                                      criado_por, atualizado_por)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (int(cliente_codigo), _texto(cliente_nome, 120), Jsonb(cfg), autor, autor))
        r = cur.fetchone()
        cur.execute("INSERT INTO hp_perfil_versao (perfil_id, config, autor)"
                    " VALUES (%s, %s, %s)", (r["id"], Jsonb(cfg), autor))
        conn.commit()
    return _linha_perfil(r)


def salvar_config(pid: int, cfg: dict, autor: str,
                  esquema: str | None = None) -> dict:
    """Grava a configuração e guarda a VERSÃO. Sem mudança, não versiona."""
    if not autor:
        raise Recusa("Alteração sem autor não entra.")
    novo = validar_config(cfg)
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT config FROM hp_perfil WHERE id = %s FOR UPDATE", (int(pid),))
        atual = cur.fetchone()
        if not atual:
            raise Recusa("Perfil não encontrado.")
        if validar_config(atual["config"]) != novo:
            cur.execute("""UPDATE hp_perfil SET config = %s, atualizado_por = %s,
                                  atualizado_em = now() WHERE id = %s""",
                        (Jsonb(novo), autor, int(pid)))
            cur.execute("INSERT INTO hp_perfil_versao (perfil_id, config, autor)"
                        " VALUES (%s, %s, %s)", (int(pid), Jsonb(novo), autor))
        conn.commit()
    return perfil(pid, esquema=esquema)


def versoes(pid: int, esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, autor, em FROM hp_perfil_versao WHERE perfil_id = %s"
                    " ORDER BY em DESC, id DESC LIMIT 30", (int(pid),))
        return [{"id": r["id"], "autor": r["autor"], "em": r["em"].isoformat()}
                for r in cur.fetchall()]


# ───────────────────────────── os ajustes ──────────────────────────────────

_RE_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")


def normalizar_valor(campo: str, valor) -> str:
    """O valor do ajuste na forma em que é gravado, ou `Recusa`."""
    if campo not in CAMPOS_AJUSTE:
        raise Recusa("Campo não ajustável: %r." % campo)
    v = str(valor if valor is not None else "").strip()
    if campo in CAMPOS_HORA:
        if not _RE_DT.match(v):
            raise Recusa("Horário inválido — use dia e hora (AAAA-MM-DD HH:MM).")
        return datetime.fromisoformat(v.replace(" ", "T")).strftime("%Y-%m-%dT%H:%M")
    if campo == "incluir":
        if v not in ("sim", "nao"):
            raise Recusa("Incluir: 'sim' ou 'nao'.")
        return v
    v = _texto(v, 60)
    if not v:
        raise Recusa("Referência vazia — para voltar ao padrão, desfaça o ajuste.")
    return v


def ajustar(coleta_chave: str, campo: str, valor, valor_erp, motivo: str,
            autor: str, esquema: str | None = None) -> dict:
    motivo = _texto(motivo, 300)
    if len(motivo) < MOTIVO_MIN:
        raise Recusa("Escreva o motivo do ajuste — é ele que responde à "
                     "contestação do cliente daqui a um mês.")
    if not autor:
        raise Recusa("Ajuste sem autor não entra.")
    if not coleta_chave or coleta_chave.count("|") != 6:
        raise Recusa("Coleta sem chave completa.")
    v = normalizar_valor(campo, valor)
    erp = None if valor_erp in (None, "") else str(valor_erp)[:40]
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hp_ajuste (coleta_chave, campo, valor, valor_erp, motivo, autor)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (coleta_chave, campo) DO UPDATE
                 SET valor = EXCLUDED.valor, valor_erp = EXCLUDED.valor_erp,
                     motivo = EXCLUDED.motivo, autor = EXCLUDED.autor, em = now()
               RETURNING *""", (coleta_chave, campo, v, erp, motivo, autor))
        r = dict(cur.fetchone())
        conn.commit()
    r["em"] = r["em"].isoformat()
    return r


def desfazer(coleta_chave: str, campo: str, esquema: str | None = None) -> bool:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM hp_ajuste WHERE coleta_chave = %s AND campo = %s",
                    (coleta_chave, campo))
        n = cur.rowcount
        conn.commit()
    return bool(n)


def ajustes_de(chaves: list[str], esquema: str | None = None) -> dict[str, dict]:
    """{chave: {campo: linha}} das coletas pedidas. Lista vazia, nada."""
    if not chaves:
        return {}
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hp_ajuste WHERE coleta_chave = ANY(%s)",
                    (list(chaves),))
        rs = cur.fetchall()
    out: dict[str, dict] = {}
    for r in rs:
        r = dict(r)
        r["em"] = r["em"].isoformat()
        out.setdefault(r["coleta_chave"], {})[r["campo"]] = r
    return out


def contagem(esquema: str | None = None) -> dict:
    """Escalares para a Saúde e o Copiloto: quantos perfis, quantos ajustes."""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("""SELECT (SELECT count(*) FROM hp_perfil)::int AS perfis,
                              (SELECT count(*) FROM hp_ajuste)::int AS ajustes,
                              (SELECT max(em) FROM hp_ajuste) AS ultimo_ajuste""")
        r = dict(cur.fetchone())
    r["ultimo_ajuste"] = r["ultimo_ajuste"].isoformat() if r["ultimo_ajuste"] else None
    return r
