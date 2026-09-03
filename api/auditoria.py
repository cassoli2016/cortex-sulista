"""Auditoria de USO — quem entra, por quanto tempo e em que telas.

O `audit_log` (em `api/auth.py`) responde *"quem MEXEU no sistema"*: toda
escrita passa por ele. Este módulo responde a outra pergunta, que ele nunca
respondeu — *"quem USA o sistema"*: quantos acessos, de quanta gente, por
quanto tempo, e em que telas.

## Por que não dava para tirar isso do que já existia

391 logins para 11 logouts. Ninguém sai pelo botão — fecha a aba. Duração de
sessão medida por `login → logout` teria 3% de amostra e sairia na tela com
cara de número exato. Por isso a sessão recebe um **"visto por último"**
enquanto a pessoa navega, e a duração é `até o último sinal de vida`, não `até
o logout que quase nunca vem`.

## O que se grava, e o que não

Grava-se a CHAVE da tela (`home`, `dre`) e o horário. **Não** se grava filtro,
parâmetro, conteúdo, nem corpo de requisição. Auditoria de uso existe para
dimensionar o sistema e achar tela que ninguém abre — não para reconstituir o
que cada pessoa leu. O user-agent entra reduzido a navegador/SO.

## Estado que envelhece não se grava

"Sessão aberta" não é coluna: é `fim IS NULL AND visto_em > agora − JANELA`,
calculado na leitura. Status gravado precisa de rotina para virar, e no dia em
que ela não roda a tela mente (regra da casa, `docs/LICOES.md`).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from . import pglocal

log = logging.getLogger("cortex.auditoria")

# Manopla de redirecionamento para os testes, como em `api/auth.py`.
ESQUEMA: str | None = None

# Uma sessão sem sinal de vida há mais que isto não conta como "aberta agora".
# 15 min é maior que o intervalo do ping da tela (5 min) com folga para uma
# rede ruim, e menor que o tempo em que alguém "esqueceu a aba aberta" vira
# ruído no indicador de quem está no sistema.
JANELA_VIVA_MIN = 15

# Passo do "visto por último": não se escreve a cada navegação. Duas telas
# abertas no mesmo minuto não são dois sinais de vida diferentes, e a escrita
# por clique transformaria a auditoria num gargalo do próprio painel.
PASSO_VISTO_SEG = 60


def _conn():
    return pglocal.get_conn(ESQUEMA)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------

_NAV = (("Edg", "Edge"), ("OPR", "Opera"), ("Chrome", "Chrome"),
        ("Firefox", "Firefox"), ("Safari", "Safari"))
_SO = (("Windows", "Windows"), ("iPhone", "iPhone"), ("iPad", "iPad"),
       ("Android", "Android"), ("Macintosh", "macOS"), ("Linux", "Linux"))


def resumir_agente(ua: str) -> str:
    """'Chrome · Windows' a partir do user-agent.

    A string inteira é longa, muda a cada atualização do navegador e não
    responde nada melhor que estas duas palavras. Guardar menos é a escolha
    certa quando o dado é sobre pessoas.
    """
    ua = ua or ""
    nav = next((rot for chave, rot in _NAV if chave in ua), "")
    so = next((rot for chave, rot in _SO if chave in ua), "")
    return " · ".join(x for x in (nav, so) if x)


def abrir_sessao(usuario_id: int | None, email: str, ip: str = "",
                 agente: str = "") -> int | None:
    """Registra um login. Nunca levanta: auditoria não derruba o acesso.

    Se a gravação falhar, a pessoa entra do mesmo jeito e o problema aparece no
    log. Trilha que impede de trabalhar vira trilha desligada.
    """
    try:
        agora = _agora()
        with _conn() as c:
            r = c.execute(
                """INSERT INTO aud_sessoes(usuario_id, email, inicio, visto_em, ip, agente)
                   VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                (usuario_id, (email or "").lower(), agora, agora, ip,
                 resumir_agente(agente))).fetchone()
        return r["id"]
    except Exception as exc:  # noqa: BLE001
        log.warning("auditoria: nao registrou o login (%s)", type(exc).__name__)
        return None


def fechar_sessao(sessao_id: int | None, motivo: str = "logout") -> None:
    """Fecha na saída EXPLÍCITA. Sessão abandonada não passa por aqui — e é
    isso que o `visto_em` resolve."""
    if not sessao_id:
        return
    try:
        with _conn() as c:
            c.execute("UPDATE aud_sessoes SET fim=%s, fim_motivo=%s "
                      "WHERE id=%s AND fim IS NULL", (_agora(), motivo, sessao_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("auditoria: nao fechou a sessao (%s)", type(exc).__name__)


_TELA_OK = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


def registrar(sessao_id: int | None, tela: str = "") -> None:
    """Sinal de vida da sessão e, se veio tela, a abertura dela.

    A TELA É VALIDADA contra um formato estreito antes de entrar. O valor chega
    do navegador, e o que chega do navegador não é dado, é entrada: sem isto a
    tabela viraria depósito de qualquer string que alguém resolvesse mandar.
    """
    if not sessao_id:
        return
    agora = _agora()
    try:
        with _conn() as c:
            # `visto_em` só avança de PASSO em PASSO: duas telas abertas no
            # mesmo minuto não são dois sinais de vida diferentes.
            c.execute(
                "UPDATE aud_sessoes SET visto_em=%s "
                "WHERE id=%s AND fim IS NULL AND visto_em < %s",
                (agora, sessao_id,
                 (datetime.now() - timedelta(seconds=PASSO_VISTO_SEG)
                  ).strftime("%Y-%m-%d %H:%M:%S")))
            if tela and _TELA_OK.match(tela):
                c.execute(
                    """INSERT INTO aud_telas(sessao_id, tela, aberturas, primeira, ultima)
                       VALUES(%s,%s,1,%s,%s)
                       ON CONFLICT (sessao_id, tela) DO UPDATE
                         SET aberturas = aud_telas.aberturas + 1, ultima = EXCLUDED.ultima""",
                    (sessao_id, tela, agora, agora))
    except Exception as exc:  # noqa: BLE001
        log.warning("auditoria: nao registrou atividade (%s)", type(exc).__name__)


# ---------------------------------------------------------------------------
# Leitura — os indicadores
# ---------------------------------------------------------------------------
#
# DURAÇÃO DE UMA SESSÃO = coalesce(fim, visto_em) − inicio. Nunca `now() −
# inicio`: a aba esquecida aberta a noite toda viraria uma sessão de 14 horas e
# levaria a média junto.
_DUR = ("(EXTRACT(EPOCH FROM (coalesce(s.fim, s.visto_em)::timestamp "
        "- s.inicio::timestamp)))")


def _janela(dias: int) -> tuple[str, str]:
    fim = date.today() + timedelta(days=1)
    return (date.today() - timedelta(days=dias - 1)).isoformat(), fim.isoformat()


def resumo(dias: int = 30) -> dict:
    """KPIs, série diária, por pessoa e por tela. Uma chamada, uma conexão."""
    de, ate = _janela(dias)
    limite_vivo = (datetime.now() - timedelta(minutes=JANELA_VIVA_MIN)
                   ).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        kpis = c.execute(f"""
            SELECT count(*)::int AS acessos,
                   count(DISTINCT s.email)::int AS pessoas,
                   coalesce(avg({_DUR}), 0)::float8 AS dur_media,
                   coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY {_DUR}), 0)::float8 AS dur_mediana,
                   coalesce(sum({_DUR}), 0)::float8 AS dur_total
            FROM aud_sessoes s
            WHERE s.inicio >= %s AND s.inicio < %s""", (de, ate)).fetchone()

        abertas = c.execute(
            "SELECT count(*)::int AS n, count(DISTINCT email)::int AS pessoas "
            "FROM aud_sessoes WHERE fim IS NULL AND visto_em >= %s",
            (limite_vivo,)).fetchone()

        # O intervalo de dias é GERADO, não colhido: dia sem acesso tem de
        # aparecer como zero, senão a linha do gráfico emenda e some o buraco.
        serie = c.execute(f"""
            WITH dias AS (
              SELECT to_char(generate_series(%s::date, %s::date - 1, '1 day'), 'YYYY-MM-DD') AS dia
            )
            SELECT d.dia,
                   count(s.id)::int AS acessos,
                   count(DISTINCT s.email)::int AS pessoas,
                   coalesce(avg({_DUR}), 0)::float8 AS dur_media
            FROM dias d LEFT JOIN aud_sessoes s ON left(s.inicio, 10) = d.dia
            GROUP BY d.dia ORDER BY d.dia""", (de, ate)).fetchall()

        pessoas = c.execute(f"""
            SELECT s.email,
                   count(*)::int AS acessos,
                   coalesce(sum({_DUR}), 0)::float8 AS dur_total,
                   coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY {_DUR}), 0)::float8 AS dur_mediana,
                   max(s.visto_em) AS ultima_vez,
                   count(DISTINCT s.ip)::int AS ips
            FROM aud_sessoes s
            WHERE s.inicio >= %s AND s.inicio < %s
            GROUP BY 1 ORDER BY 2 DESC""", (de, ate)).fetchall()

        telas = c.execute("""
            SELECT t.tela, sum(t.aberturas)::int AS aberturas,
                   count(DISTINCT s.email)::int AS pessoas, max(t.ultima) AS ultima
            FROM aud_telas t JOIN aud_sessoes s ON s.id = t.sessao_id
            WHERE s.inicio >= %s AND s.inicio < %s
            GROUP BY 1 ORDER BY 2 DESC""", (de, ate)).fetchall()

        agentes = c.execute("""
            SELECT coalesce(nullif(agente,''), 'não identificado') AS agente,
                   count(*)::int AS acessos
            FROM aud_sessoes WHERE inicio >= %s AND inicio < %s
            GROUP BY 1 ORDER BY 2 DESC""", (de, ate)).fetchall()

        falhas = c.execute("""
            SELECT usuario AS email, count(*)::int AS tentativas, max(ts) AS ultima,
                   count(DISTINCT ip)::int AS ips
            FROM audit_log WHERE acao = 'login_falha' AND ts >= %s AND ts < %s
            GROUP BY 1 ORDER BY 2 DESC""", (de, ate)).fetchall()

        acoes = c.execute("""
            SELECT acao, count(*)::int AS n, count(DISTINCT usuario)::int AS pessoas,
                   max(ts) AS ultima
            FROM audit_log
            WHERE ts >= %s AND ts < %s AND acao NOT IN ('login_ok','login_falha','logout')
            GROUP BY 1 ORDER BY 2 DESC""", (de, ate)).fetchall()

        escritas = sum(r["n"] for r in acoes)

    return {
        "dias": dias, "de": de, "ate": ate,
        "kpis": {
            "acessos": kpis["acessos"], "pessoas": kpis["pessoas"],
            "dur_media": kpis["dur_media"], "dur_mediana": kpis["dur_mediana"],
            "dur_total": kpis["dur_total"],
            "abertas": abertas["n"], "abertas_pessoas": abertas["pessoas"],
            "escritas": escritas,
            "falhas": sum(r["tentativas"] for r in falhas),
        },
        "serie": [dict(r) for r in serie],
        "pessoas": [dict(r) for r in pessoas],
        "telas": [dict(r) for r in telas],
        "agentes": [dict(r) for r in agentes],
        "falhas": [dict(r) for r in falhas],
        "acoes": [dict(r) for r in acoes],
        "janela_viva_min": JANELA_VIVA_MIN,
    }


def telas_sem_uso(telas_do_sistema: dict, dias: int = 30) -> list[dict]:
    """As telas que NINGUÉM abriu na janela — o indicador que só existe se
    alguém cruzar o registro de telas com o uso.

    Vale mais que o Top-N: a lista das mais usadas confirma o que já se
    imagina; a das nunca abertas é a que muda decisão (tirar do menu, treinar
    quem deveria usar, ou descobrir que a tela não serve).
    """
    de, ate = _janela(dias)
    with _conn() as c:
        usadas = {r["tela"] for r in c.execute(
            """SELECT DISTINCT t.tela FROM aud_telas t
               JOIN aud_sessoes s ON s.id = t.sessao_id
               WHERE s.inicio >= %s AND s.inicio < %s""", (de, ate)).fetchall()}
    return sorted(
        ({"tela": k, "rotulo": v[0], "grupo": v[1]}
         for k, v in telas_do_sistema.items() if k not in usadas),
        key=lambda x: (x["grupo"], x["rotulo"]))


def snapshot_copiloto() -> dict:
    """Só escalares (sem e-mail, sem IP) para o snapshot do Copiloto."""
    try:
        r = resumo(30)
        k = r["kpis"]
        return {"acessos_30d": k["acessos"], "pessoas_30d": k["pessoas"],
                "sessao_mediana_min": round((k["dur_mediana"] or 0) / 60, 1),
                "sessoes_abertas": k["abertas"],
                "escritas_30d": k["escritas"], "falhas_login_30d": k["falhas"],
                "telas_usadas_30d": len(r["telas"])}
    except Exception as exc:  # noqa: BLE001
        log.warning("auditoria: snapshot falhou (%s)", type(exc).__name__)
        return {}


def diagnostico() -> dict:
    """Para a Saúde do Servidor: a trilha está viva e crescendo?"""
    d = {"ok": False, "erro": None, "sessoes": 0, "acoes": 0,
         "abertas": 0, "ultimo_acesso": None}
    try:
        limite = (datetime.now() - timedelta(minutes=JANELA_VIVA_MIN)
                  ).strftime("%Y-%m-%d %H:%M:%S")
        with _conn() as c:
            d["sessoes"] = c.execute(
                "SELECT count(*)::int AS n FROM aud_sessoes").fetchone()["n"]
            d["abertas"] = c.execute(
                "SELECT count(*)::int AS n FROM aud_sessoes "
                "WHERE fim IS NULL AND visto_em >= %s", (limite,)).fetchone()["n"]
            d["ultimo_acesso"] = c.execute(
                "SELECT max(inicio) AS m FROM aud_sessoes").fetchone()["m"]
            d["acoes"] = c.execute(
                "SELECT count(*)::int AS n FROM audit_log").fetchone()["n"]
        d["ok"] = True
    except Exception as exc:  # noqa: BLE001
        d["erro"] = type(exc).__name__
    return d
