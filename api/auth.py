"""CÓRTEX — autenticação, perfis de acesso e auditoria (área de Gestão).

Armazenamento local em SQLite (data/auth.db) — o ERP AVA é somente leitura,
então usuários/perfis/audit vivem aqui. Senhas com Argon2; sessão via JWT
(HS256, APP_SECRET do .env) em cookie HttpOnly com renovação deslizante.

A permissão é POR TELA do painel (as chaves do objeto VIEWS do frontend).
Cada rota /api/* é mapeada às telas que a consomem (ROTA_TELAS); o usuário
precisa ter ao menos uma delas. /api/gestao/* exige perfil administrador.
Toda escrita entra em audit_log (regra CLAUDE.md §8).
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from . import db as _db  # noqa: F401  (importa para garantir o .env carregado)

log = logging.getLogger("cortex.auth")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "auth.db"
COOKIE = "cortex_sess"
_ph = PasswordHasher()

# Segredo de assinatura: sem APP_SECRET no .env, gera um efêmero (derruba as
# sessões a cada restart, mas nunca roda com segredo previsível).
SECRET = os.environ.get("APP_SECRET", "").strip()
if not SECRET or SECRET.startswith("__"):
    SECRET = os.urandom(32).hex()
    log.warning("APP_SECRET ausente no .env — usando segredo efêmero (sessões caem no restart)")

# ---------------------------------------------------------------- telas/RBAC

# Telas do painel (mesmas chaves/rótulos do objeto VIEWS do index.html).
TELAS: dict[str, tuple[str, str]] = {  # chave -> (rótulo, grupo do menu)
    "home":    ("Visão Geral", "Início"),
    "cop":     ("Copiloto Cortex", "Início"),
    "fluxo":   ("Fluxo de Caixa e Bancos", "Financeiro"),
    "receber": ("Contas a Receber", "Financeiro"),
    "cob":     ("Régua de Cobrança", "Financeiro"),
    "pagar":   ("Contas a Pagar", "Financeiro"),
    "com":     ("Clientes e RKM", "Comercial"),
    "clif":    ("Consulta de Cliente", "Comercial"),
    "crm":     ("CRM — Leads e Projetos", "Comercial"),
    "drecli":  ("DRE por Cliente", "Comercial"),
    "dre":     ("DRE Gerencial", "Controladoria"),
    "cont":    ("Contabilidade", "Controladoria"),
    "qual":    ("Qualidade e Certidões", "Controladoria"),
    "agr":     ("Agregados e Terceiros", "Operação"),
    "mvb":     ("Make vs Buy", "Operação"),
    "km":      ("Análise de KM", "Operação"),
    "prog":    ("Programação Inteligente", "Operação"),
    "torre":   ("Torre de Controle", "Operação"),
    "jorn":    ("Jornada do Motorista", "Operação"),
    "cex":     ("Custos Extras", "Operação"),
    "sac":     ("SAC / Freetime", "Operação"),
    "port":    ("Portaria", "Operação"),
    "oc":      ("Ordens de Compra", "Suprimentos"),
    "custos":  ("Painel de Custos", "Suprimentos"),
    "comb":    ("Combustível", "Frota"),
    "man":     ("Manutenção", "Frota"),
    "veic":    ("Veículos", "Frota"),
    "mprev":   ("Manutenção Preventiva", "Frota"),
    "comrast": ("Comunicação Rastreadora", "Frota"),
    "veicf":   ("Consulta de Veículo", "Frota"),
    "mul":     ("Multas", "Frota"),
    "rh":      ("RH — Vagas", "Recursos Humanos"),
    "hc":      ("Headcount", "Recursos Humanos"),
    "folha":   ("Custo de Folha", "Recursos Humanos"),
    "tvfat":   ("Painel TV — Faturamento", "Painéis TV"),
    "tvope":   ("Painel TV — Operação", "Painéis TV"),
}

# Rota (prefixo) -> telas que a consomem. Prefixos mais específicos primeiro.
ROTA_TELAS: list[tuple[str, frozenset[str]]] = [
    # metadados de filtro (empresa/filiais) usados por todas as telas com filtro:
    # basta ter QUALQUER tela atribuída — nunca fica aberto a usuário sem acesso.
    ("/api/financeiro/filtros",       frozenset(TELAS)),
    ("/api/financeiro/contabil",      frozenset({"cont"})),
    ("/api/qualidade",                frozenset({"qual"})),
    ("/api/rh/headcount",             frozenset({"hc"})),
    ("/api/rh/folha-custo",           frozenset({"folha"})),
    ("/api/rh/vagas",                 frozenset({"rh"})),
    ("/api/financeiro/overview",      frozenset({"fluxo", "receber", "pagar"})),
    ("/api/financeiro/dre-cliente",   frozenset({"drecli"})),
    ("/api/financeiro/dre",           frozenset({"dre"})),
    ("/api/financeiro/cobranca",      frozenset({"cob"})),
    ("/api/visao-geral",              frozenset({"home", "tvfat", "tvope"})),
    ("/api/alertas",                  frozenset({"home"})),
    ("/api/suprimentos/custos",       frozenset({"custos"})),
    ("/api/suprimentos/ordens-compra", frozenset({"oc"})),
    ("/api/suprimentos/agregados",    frozenset({"agr"})),
    ("/api/frota/manutencao-preventiva", frozenset({"mprev"})),
    ("/api/frota/comunicacao-rastreadora", frozenset({"comrast"})),
    ("/api/frota/veiculos",           frozenset({"veic"})),
    ("/api/frota/veiculo",            frozenset({"veicf"})),
    ("/api/frota/combustivel",        frozenset({"comb", "tvope"})),
    ("/api/frota/manutencao",         frozenset({"man"})),
    ("/api/frota/multas",             frozenset({"mul"})),
    ("/api/operacao/torre",           frozenset({"torre", "tvope"})),
    ("/api/operacao/programacao",     frozenset({"prog", "tvope"})),
    ("/api/operacao/seguranca",       frozenset({"tvope"})),
    ("/api/operacao/analise-km",      frozenset({"km", "tvope"})),
    ("/api/operacao/make-vs-buy",     frozenset({"mvb"})),
    ("/api/jornada/painel",           frozenset({"jorn"})),
    ("/api/jornada/motorista",        frozenset({"jorn"})),
    ("/api/operacao/custos-extras",   frozenset({"cex"})),
    ("/api/operacao/sac-freetime",    frozenset({"sac"})),
    ("/api/operacao/portaria",        frozenset({"port"})),
    ("/api/comercial/crm",            frozenset({"crm"})),
    ("/api/comercial/clientes",       frozenset({"com"})),
    ("/api/comercial/cliente",        frozenset({"clif"})),
    ("/api/copiloto",                 frozenset({"cop"})),
    ("/api/tv",                       frozenset({"tvfat", "tvope"})),
]

# Rotas liberadas sem sessão (a página raiz mostra o overlay de login;
# /static tem o logo usado na tela de login).
_PUBLICAS = ("/api/auth/login", "/api/auth/setup", "/api/auth/setup-status", "/api/health")


def _rota_publica(path: str) -> bool:
    return (path == "/" or path.startswith("/static/") or path in _PUBLICAS)


def _local_direto(headers: Headers, cliente: str) -> bool:
    """Acesso direto DESTA máquina. O Cloudflare Tunnel roda local (o tráfego
    dele também chega como loopback), mas a borda sempre põe Cf-Connecting-IP —
    a ausência do header distingue o acesso local de verdade."""
    return cliente in ("127.0.0.1", "::1") and not headers.get("cf-connecting-ip")


# ---------------------------------------------------------------- SQLite

@contextmanager
def _conn():
    """Conexão curta: transação automática (commit/rollback) e close garantido."""
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        with c:
            yield c
    finally:
        c.close()


_CONFIG_PADRAO = {
    "sessao_ttl_min": os.environ.get("JWT_TTL_MIN", "480"),
    "max_tentativas": "5",
    "bloqueio_min": "15",
    "senha_min": "8",
}

# Perfis-modelo por área (não-admin), semeados UMA vez (flag em config) para
# agilizar o cadastro de usuários. O admin pode editar/excluir à vontade — a
# exclusão NÃO ressuscita no restart (o flag impede o reseed). Telas cross-área
# (home/cop/TV) vazam dados de outras áreas (ex.: snapshot do copiloto), então
# ficam fora dos perfis de área e só entram no perfil amplo "Diretoria".
# Perfis-modelo alinhados aos grupos do menu (reorg 2026-07-17).
_PERFIS_MODELO = [
    ("Comercial",   "Clientes/RKM, consulta por cliente, CRM (leads/projetos) e DRE por cliente.",
     ["com", "clif", "crm", "drecli"]),
    ("Financeiro",  "Caixa, recebíveis, pagáveis e cobrança.",
     ["fluxo", "receber", "pagar", "cob"]),
    ("Controladoria", "DRE gerencial, contabilidade, DRE/margem por cliente e qualidade/certidões.",
     ["dre", "cont", "drecli", "qual"]),
    ("Operação",    "Torre de controle, programação, jornada, custos extras, SAC/freetime, portaria, análise de KM, agregados e make-vs-buy.",
     ["torre", "prog", "jorn", "cex", "sac", "port", "km", "agr", "mvb"]),
    ("Frota",       "Veículos, consulta por placa, combustível, manutenção, preventiva, rastreadora e multas.",
     ["veic", "veicf", "comb", "man", "mprev", "comrast", "mul"]),
    ("Suprimentos", "Ordens de compra e painel de custos.",
     ["oc", "custos"]),
    ("Painéis TV",  "Apenas os painéis de TV (faturamento e operação) — para telão/quiosque.",
     ["tvfat", "tvope"]),
    ("Diretoria",   "Visão executiva ampla: consolidado, copiloto e principais indicadores.",
     ["home", "cop", "fluxo", "dre", "drecli", "com", "km", "torre", "jorn", "mvb", "veic", "rh", "hc", "folha"]),
]


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS perfis(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            descricao TEXT DEFAULT '',
            admin INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS perfil_telas(
            perfil_id INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
            tela TEXT NOT NULL,
            PRIMARY KEY(perfil_id, tela)
        );
        CREATE TABLE IF NOT EXISTS usuarios(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            perfil_id INTEGER NOT NULL REFERENCES perfis(id),
            ativo INTEGER NOT NULL DEFAULT 1,
            deve_trocar_senha INTEGER NOT NULL DEFAULT 1,
            token_ver INTEGER NOT NULL DEFAULT 0,
            falhas INTEGER NOT NULL DEFAULT 0,
            bloqueado_ate TEXT,
            criado_em TEXT NOT NULL,
            ultimo_login TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            usuario TEXT NOT NULL,
            acao TEXT NOT NULL,
            alvo TEXT DEFAULT '',
            detalhe TEXT DEFAULT '',
            ip TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);
        CREATE TABLE IF NOT EXISTS config(
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );
        """)
        for k, v in _CONFIG_PADRAO.items():
            c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES(?,?)", (k, v))
        # perfil administrador sempre existe (o setup cria o primeiro usuário nele)
        c.execute(
            "INSERT OR IGNORE INTO perfis(nome, descricao, admin, criado_em) VALUES(?,?,1,?)",
            ("Administrador", "Acesso total, inclusive à área de Gestão.", _agora()),
        )
        _seed_perfis_modelo(c)


def _seed_perfis_modelo(c: sqlite3.Connection) -> None:
    """Semeia os perfis-modelo por área UMA única vez (idempotente via flag).

    Não recria perfis que o admin tenha excluído: o flag 'perfis_modelo_v1'
    marca que o seed já rodou, independentemente do que exista depois.
    """
    # v2 (reorg de menu 2026-07-17): adiciona perfis-modelo novos (ex.: Controladoria)
    # sem tocar nos existentes/editados pelo admin (INSERT OR IGNORE por nome).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v2'").fetchone():
        for nome, desc, telas in _PERFIS_MODELO:
            cur = c.execute(
                "INSERT OR IGNORE INTO perfis(nome, descricao, admin, criado_em) VALUES(?,?,0,?)",
                (nome, desc, _agora()))
            if cur.rowcount:  # inserido agora (nome ainda não existia)
                c.executemany("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                              [(cur.lastrowid, t) for t in telas])
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v1', '1')")
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v2', '1')")

    # v3 (jornada 2026-07-17): adiciona a tela 'jorn' aos perfis Operação e
    # Diretoria já existentes (sem recriar perfis editados pelo admin).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v3'").fetchone():
        for perfil_nome in ("Operação", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=?", (perfil_nome,)).fetchone()
            if row:
                c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                          (row["id"], "jorn"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v3', '1')")

    # v4 (custos extras 2026-07-17): adiciona a tela 'cex' ao perfil Operação.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v4'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Operação'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "cex"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v4', '1')")

    # v5 (SAC/freetime 2026-07-17): adiciona a tela 'sac' ao perfil Operação.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v5'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Operação'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "sac"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v5', '1')")

    # v6 (manutenção preventiva 2026-07-17): adiciona a tela 'mprev' ao perfil Frota.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v6'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Frota'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "mprev"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v6', '1')")

    # v7 (comunicação rastreadora 2026-07-17): adiciona 'comrast' ao perfil Frota.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v7'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Frota'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "comrast"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v7', '1')")

    # v8 (qualidade 2026-07-17): adiciona a tela 'qual' ao perfil Controladoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v8'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Controladoria'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "qual"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v8', '1')")

    # v9 (portaria 2026-07-17): adiciona a tela 'port' ao perfil Operação.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v9'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Operação'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "port"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v9', '1')")

    # v10 (CRM 2026-07-17): adiciona a tela 'crm' ao perfil Comercial.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v10'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Comercial'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "crm"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v10', '1')")

    # v11 (RH vagas 2026-07-17): adiciona a tela 'rh' ao perfil Diretoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v11'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "rh"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v11', '1')")

    # v12 (folha GLOBUS 2026-07-18): telas 'hc' e 'folha' ao perfil Diretoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v12'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            for t in ("hc", "folha"):
                c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                          (row["id"], t))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v12', '1')")

    # v13 (painel de custos 2026-07-18): tela 'custos' ao perfil Suprimentos.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v13'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Suprimentos'").fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      (row["id"], "custos"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v13', '1')")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cfg(chave: str) -> int:
    with _conn() as c:
        row = c.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    try:
        return int(row["valor"]) if row else int(_CONFIG_PADRAO[chave])
    except (ValueError, KeyError):
        return int(_CONFIG_PADRAO.get(chave, "0"))


def audit(usuario: str, acao: str, alvo: str = "", detalhe: str = "", ip: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(?,?,?,?,?,?)",
            (_agora(), usuario, acao, alvo, detalhe, ip),
        )


def _telas_do_perfil(c: sqlite3.Connection, perfil_id: int, admin: bool) -> list[str]:
    if admin:
        return list(TELAS.keys())
    rows = c.execute("SELECT tela FROM perfil_telas WHERE perfil_id=?", (perfil_id,)).fetchall()
    return [r["tela"] for r in rows if r["tela"] in TELAS]


# ---------------------------------------------------------------- sessão/JWT

def _emitir_token(usuario_id: int, token_ver: int) -> str:
    agora = datetime.now(timezone.utc)
    ttl = max(5, cfg("sessao_ttl_min"))
    return jwt.encode(
        {"sub": str(usuario_id), "ver": token_ver,
         "iat": agora, "exp": agora + timedelta(minutes=ttl)},
        SECRET, algorithm="HS256",
    )


def _cookie_kwargs(https: bool) -> dict:
    return {"key": COOKIE, "httponly": True, "samesite": "lax", "path": "/", "secure": https}


def _set_cookie(resp: Response, token: str, https: bool) -> None:
    resp.set_cookie(value=token, max_age=cfg("sessao_ttl_min") * 60, **_cookie_kwargs(https))


def _https(request: Request) -> bool:
    return (request.headers.get("x-forwarded-proto", request.url.scheme) == "https")


def sessao_atual(token: str | None) -> dict | None:
    """Valida o JWT e carrega o usuário. None = sem sessão válida."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    with _conn() as c:
        u = c.execute(
            """SELECT u.*, p.nome AS perfil_nome, p.admin AS perfil_admin
               FROM usuarios u JOIN perfis p ON p.id = u.perfil_id
               WHERE u.id = ?""", (int(claims["sub"]),),
        ).fetchone()
        if not u or not u["ativo"] or u["token_ver"] != claims.get("ver"):
            return None
        telas = _telas_do_perfil(c, u["perfil_id"], bool(u["perfil_admin"]))
    return {
        "id": u["id"], "nome": u["nome"], "email": u["email"],
        "perfil_id": u["perfil_id"], "perfil": u["perfil_nome"],
        "admin": bool(u["perfil_admin"]), "telas": telas,
        "deve_trocar_senha": bool(u["deve_trocar_senha"]),
        "token_ver": u["token_ver"], "exp": claims["exp"], "iat": claims["iat"],
    }


def _payload_me(s: dict) -> dict:
    return {k: s[k] for k in ("id", "nome", "email", "perfil", "perfil_id",
                              "admin", "telas", "deve_trocar_senha")}


# ---------------------------------------------------------------- middleware

def _cookie_do_scope(scope) -> str | None:
    cookies = Headers(scope=scope).get("cookie") or ""
    for parte in cookies.split(";"):
        nome, _, valor = parte.strip().partition("=")
        if nome == COOKIE:
            return valor or None
    return None


def _telas_da_rota(path: str) -> frozenset[str] | None:
    for prefixo, telas in ROTA_TELAS:
        if path.startswith(prefixo):
            return telas
    return None


class AuthMiddleware:
    """ASGI puro (não bufferiza o SSE do copiloto). Protege todo /api/*."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if _rota_publica(path):
            return await self.app(scope, receive, send)

        # digest de alertas: uso do cron local, sem sessão
        if path.startswith("/api/alertas/digest"):
            cliente = (scope.get("client") or ("", 0))[0]
            if _local_direto(Headers(scope=scope), cliente):
                return await self.app(scope, receive, send)

        sess = sessao_atual(_cookie_do_scope(scope))
        if sess is None:
            resp = JSONResponse(status_code=401, content={
                "erro": "nao_autenticado", "mensagem": "Faça login para continuar."})
            return await resp(scope, receive, send)

        if path.startswith("/api/gestao") and not sess["admin"]:
            resp = JSONResponse(status_code=403, content={
                "erro": "sem_permissao",
                "mensagem": "Área restrita ao perfil administrador."})
            return await resp(scope, receive, send)

        telas = _telas_da_rota(path)
        if telas is not None and not sess["admin"] and not (telas & set(sess["telas"])):
            resp = JSONResponse(status_code=403, content={
                "erro": "sem_permissao",
                "mensagem": "Seu perfil não tem acesso a esta área."})
            return await resp(scope, receive, send)

        scope.setdefault("state", {})["sessao"] = sess

        # renovação deslizante: reemite o cookie quando passou metade do TTL.
        # NUNCA em /api/auth/*: logout e trocar-senha emitem o próprio Set-Cookie
        # (o cookie de renovação apagaria o delete/trocaria por token_ver antigo).
        novo_cookie: str | None = None
        exp = datetime.fromtimestamp(sess["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(sess["iat"], tz=timezone.utc)
        if not path.startswith("/api/auth/") and datetime.now(timezone.utc) > iat + (exp - iat) / 2:
            https = Headers(scope=scope).get("x-forwarded-proto", scope.get("scheme")) == "https"
            token = _emitir_token(sess["id"], sess["token_ver"])
            tmp = Response()
            _set_cookie(tmp, token, https)
            novo_cookie = tmp.headers["set-cookie"]

        async def send_com_cookie(message):
            if novo_cookie and message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", novo_cookie.encode()))
                message = {**message, "headers": headers}
            await send(message)

        return await self.app(scope, receive, send_com_cookie if novo_cookie else send)


# ---------------------------------------------------------------- rotas: auth

router_auth = APIRouter(prefix="/api/auth")

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def _ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


def _sem_usuarios() -> bool:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"] == 0


def _req_local_direto(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1") and not request.headers.get("cf-connecting-ip")


@router_auth.get("/setup-status")
def setup_status(request: Request) -> JSONResponse:
    # via túnel público o setup nunca é oferecido — só no acesso local direto
    return JSONResponse({"precisa_setup": _sem_usuarios() and _req_local_direto(request)})


@router_auth.post("/setup")
def setup(payload: dict, request: Request) -> JSONResponse:
    """Cria o PRIMEIRO administrador. Só com a base vazia e acesso local direto."""
    if not _req_local_direto(request):
        return JSONResponse(status_code=403, content={
            "erro": "somente_local",
            "mensagem": "O primeiro acesso é feito localmente: http://127.0.0.1:8010"})
    if not _sem_usuarios():
        return JSONResponse(status_code=403, content={
            "erro": "setup_ja_feito", "mensagem": "Já existe usuário cadastrado."})
    nome = (payload.get("nome") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    senha = payload.get("senha") or ""
    if not nome or not _EMAIL_RE.match(email):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe nome e e-mail válidos."})
    if len(senha) < cfg("senha_min"):
        return JSONResponse(status_code=422, content={
            "erro": "senha_fraca",
            "mensagem": f"A senha precisa de ao menos {cfg('senha_min')} caracteres."})
    with _conn() as c:
        perfil = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        cur = c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES(?,?,?,?,1,0,?)""",
            (nome, email, _ph.hash(senha), perfil["id"], _agora()))
        uid = cur.lastrowid
    audit(email, "setup_admin", alvo=email, detalhe="primeiro administrador criado",
          ip=_ip(request))
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, _emitir_token(uid, 0), _https(request))
    return resp


@router_auth.post("/login")
def login(payload: dict, request: Request) -> JSONResponse:
    email = (payload.get("email") or "").strip().lower()
    senha = payload.get("senha") or ""
    generico = JSONResponse(status_code=401, content={
        "erro": "credenciais_invalidas", "mensagem": "E-mail ou senha incorretos."})
    if not email or not senha:
        return generico
    with _conn() as c:
        u = c.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    if not u:
        _ph.hash(senha)  # iguala o tempo de resposta p/ e-mail inexistente
        audit(email, "login_falha", detalhe="usuario_inexistente", ip=_ip(request))
        return generico
    if not u["ativo"]:
        audit(email, "login_falha", detalhe="usuario_inativo", ip=_ip(request))
        return generico
    if u["bloqueado_ate"] and u["bloqueado_ate"] > _agora():
        audit(email, "login_falha", detalhe="conta_bloqueada", ip=_ip(request))
        return JSONResponse(status_code=401, content={
            "erro": "conta_bloqueada",
            "mensagem": f"Conta bloqueada por tentativas até {u['bloqueado_ate'][11:16]}."})
    try:
        _ph.verify(u["senha_hash"], senha)
    except VerifyMismatchError:
        # incremento atômico (evita corrida que esticaria o limite de tentativas)
        with _conn() as c:
            falhas = c.execute(
                "UPDATE usuarios SET falhas=falhas+1 WHERE id=? RETURNING falhas",
                (u["id"],)).fetchone()["falhas"]
            bloqueio = None
            if falhas >= cfg("max_tentativas"):
                bloqueio = (datetime.now() + timedelta(minutes=cfg("bloqueio_min"))
                            ).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("UPDATE usuarios SET falhas=0, bloqueado_ate=? WHERE id=?",
                          (bloqueio, u["id"]))
        audit(email, "login_falha",
              detalhe="senha_incorreta" + ("; conta bloqueada" if bloqueio else ""),
              ip=_ip(request))
        return generico
    with _conn() as c:
        c.execute("UPDATE usuarios SET falhas=0, bloqueado_ate=NULL, ultimo_login=? WHERE id=?",
                  (_agora(), u["id"]))
    audit(email, "login_ok", ip=_ip(request))
    token = _emitir_token(u["id"], u["token_ver"])
    sess = sessao_atual(token)
    resp = JSONResponse(_payload_me(sess))
    _set_cookie(resp, token, _https(request))
    return resp


@router_auth.get("/me")
def me(request: Request) -> JSONResponse:
    return JSONResponse(_payload_me(request.state.sessao))


@router_auth.post("/logout")
def logout(request: Request) -> JSONResponse:
    sess = request.state.sessao
    # invalida a sessão no servidor (token roubado deixa de valer, não só o cookie)
    with _conn() as c:
        c.execute("UPDATE usuarios SET token_ver=token_ver+1 WHERE id=?", (sess["id"],))
    audit(sess["email"], "logout", ip=_ip(request))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router_auth.post("/trocar-senha")
def trocar_senha(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    atual, nova = payload.get("senha_atual") or "", payload.get("senha_nova") or ""
    if len(nova) < cfg("senha_min"):
        return JSONResponse(status_code=422, content={
            "erro": "senha_fraca",
            "mensagem": f"A nova senha precisa de ao menos {cfg('senha_min')} caracteres."})
    with _conn() as c:
        u = c.execute("SELECT senha_hash FROM usuarios WHERE id=?", (sess["id"],)).fetchone()
    try:
        _ph.verify(u["senha_hash"], atual)
    except VerifyMismatchError:
        return JSONResponse(status_code=401, content={
            "erro": "senha_incorreta", "mensagem": "A senha atual não confere."})
    nova_ver = sess["token_ver"] + 1
    with _conn() as c:
        c.execute("UPDATE usuarios SET senha_hash=?, deve_trocar_senha=0, token_ver=? WHERE id=?",
                  (_ph.hash(nova), nova_ver, sess["id"]))
    audit(sess["email"], "trocar_senha", ip=_ip(request))
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, _emitir_token(sess["id"], nova_ver), _https(request))
    return resp


# ---------------------------------------------------------------- rotas: gestão
# (middleware já garante sessão + admin em tudo que está sob /api/gestao)

router_gestao = APIRouter(prefix="/api/gestao")


@router_gestao.get("/telas")
def telas_registro() -> JSONResponse:
    return JSONResponse({"telas": [
        {"chave": k, "rotulo": rot, "grupo": grp} for k, (rot, grp) in TELAS.items()]})


@router_gestao.get("/usuarios")
def usuarios_lista() -> JSONResponse:
    with _conn() as c:
        rows = c.execute(
            """SELECT u.id, u.nome, u.email, u.perfil_id, p.nome AS perfil,
                      p.admin AS perfil_admin, u.ativo, u.deve_trocar_senha,
                      u.bloqueado_ate, u.criado_em, u.ultimo_login
               FROM usuarios u JOIN perfis p ON p.id=u.perfil_id
               ORDER BY u.nome""").fetchall()
    return JSONResponse({"usuarios": [dict(r) for r in rows]})


def _valida_usuario_payload(payload: dict, novo: bool) -> tuple[dict | None, str | None]:
    nome = (payload.get("nome") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    if novo and (not nome or not _EMAIL_RE.match(email)):
        return None, "Informe nome e e-mail válidos."
    if email and not _EMAIL_RE.match(email):
        return None, "E-mail inválido."
    return {"nome": nome, "email": email}, None


def _admins_ativos_exceto(c: sqlite3.Connection, usuario_id: int) -> int:
    return c.execute(
        """SELECT COUNT(*) AS n FROM usuarios u JOIN perfis p ON p.id=u.perfil_id
           WHERE p.admin=1 AND u.ativo=1 AND u.id<>?""", (usuario_id,)).fetchone()["n"]


@router_gestao.post("/usuarios")
def usuario_criar(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    dados, erro = _valida_usuario_payload(payload, novo=True)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    senha = payload.get("senha_temporaria") or ""
    if len(senha) < cfg("senha_min"):
        return JSONResponse(status_code=422, content={
            "erro": "senha_fraca",
            "mensagem": f"A senha temporária precisa de ao menos {cfg('senha_min')} caracteres."})
    perfil_id = payload.get("perfil_id")
    with _conn() as c:
        if not isinstance(perfil_id, int) or not c.execute(
                "SELECT 1 FROM perfis WHERE id=?", (perfil_id,)).fetchone():
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "Perfil inexistente."})
        try:
            cur = c.execute(
                """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                        deve_trocar_senha, criado_em)
                   VALUES(?,?,?,?,1,1,?)""",
                (dados["nome"], dados["email"], _ph.hash(senha), perfil_id, _agora()))
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=422, content={
                "erro": "email_em_uso", "mensagem": "Já existe usuário com esse e-mail."})
    audit(sess["email"], "usuario_criar", alvo=dados["email"],
          detalhe=f"perfil_id={perfil_id}", ip=_ip(request))
    return JSONResponse({"ok": True, "id": cur.lastrowid})


@router_gestao.post("/usuarios/{usuario_id}")
def usuario_editar(usuario_id: int, payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    dados, erro = _valida_usuario_payload(payload, novo=False)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    with _conn() as c:
        u = c.execute(
            """SELECT u.*, p.admin AS perfil_admin FROM usuarios u
               JOIN perfis p ON p.id=u.perfil_id WHERE u.id=?""", (usuario_id,)).fetchone()
        if not u:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Usuário não existe."})

        mudancas, valores, detalhes = [], [], []
        if dados["nome"]:
            mudancas.append("nome=?"); valores.append(dados["nome"]); detalhes.append("nome")
        if dados["email"] and dados["email"] != u["email"]:
            mudancas.append("email=?"); valores.append(dados["email"]); detalhes.append("email")

        if isinstance(payload.get("perfil_id"), int) and payload["perfil_id"] != u["perfil_id"]:
            novo_p = c.execute("SELECT * FROM perfis WHERE id=?", (payload["perfil_id"],)).fetchone()
            if not novo_p:
                return JSONResponse(status_code=422, content={
                    "erro": "parametro_invalido", "mensagem": "Perfil inexistente."})
            if u["perfil_admin"] and not novo_p["admin"] and u["ativo"] \
                    and _admins_ativos_exceto(c, usuario_id) == 0:
                return JSONResponse(status_code=422, content={
                    "erro": "ultimo_admin",
                    "mensagem": "Não é possível rebaixar o último administrador ativo."})
            mudancas.append("perfil_id=?"); valores.append(payload["perfil_id"])
            detalhes.append(f"perfil_id={payload['perfil_id']}")
            mudancas.append("token_ver=token_ver+1")  # força novo login com o novo perfil

        if isinstance(payload.get("ativo"), bool) and payload["ativo"] != bool(u["ativo"]):
            if not payload["ativo"]:
                if usuario_id == sess["id"]:
                    return JSONResponse(status_code=422, content={
                        "erro": "auto_desativacao",
                        "mensagem": "Você não pode desativar o próprio usuário."})
                if u["perfil_admin"] and _admins_ativos_exceto(c, usuario_id) == 0:
                    return JSONResponse(status_code=422, content={
                        "erro": "ultimo_admin",
                        "mensagem": "Não é possível desativar o último administrador ativo."})
            mudancas.append("ativo=?"); valores.append(int(payload["ativo"]))
            mudancas.append("token_ver=token_ver+1")
            detalhes.append("ativado" if payload["ativo"] else "desativado")

        senha_nova = payload.get("resetar_senha") or ""
        if senha_nova:
            if len(senha_nova) < cfg("senha_min"):
                return JSONResponse(status_code=422, content={
                    "erro": "senha_fraca",
                    "mensagem": f"A senha precisa de ao menos {cfg('senha_min')} caracteres."})
            mudancas += ["senha_hash=?", "deve_trocar_senha=1", "token_ver=token_ver+1",
                         "falhas=0", "bloqueado_ate=NULL"]
            valores.append(_ph.hash(senha_nova))
            detalhes.append("senha_resetada")

        if payload.get("desbloquear"):
            mudancas += ["falhas=0", "bloqueado_ate=NULL"]
            detalhes.append("desbloqueado")

        if not mudancas:
            return JSONResponse({"ok": True, "mensagem": "Nada a alterar."})
        try:
            c.execute(f"UPDATE usuarios SET {', '.join(mudancas)} WHERE id=?",
                      (*valores, usuario_id))
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=422, content={
                "erro": "email_em_uso", "mensagem": "Já existe usuário com esse e-mail."})
    audit(sess["email"], "usuario_editar", alvo=u["email"],
          detalhe="; ".join(detalhes), ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.post("/usuarios/{usuario_id}/excluir")
def usuario_excluir(usuario_id: int, request: Request) -> JSONResponse:
    sess = request.state.sessao
    if usuario_id == sess["id"]:
        return JSONResponse(status_code=422, content={
            "erro": "auto_exclusao", "mensagem": "Você não pode excluir o próprio usuário."})
    with _conn() as c:
        u = c.execute(
            """SELECT u.email, u.ativo, p.admin AS perfil_admin FROM usuarios u
               JOIN perfis p ON p.id=u.perfil_id WHERE u.id=?""", (usuario_id,)).fetchone()
        if not u:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Usuário não existe."})
        if u["perfil_admin"] and u["ativo"] and _admins_ativos_exceto(c, usuario_id) == 0:
            return JSONResponse(status_code=422, content={
                "erro": "ultimo_admin",
                "mensagem": "Não é possível excluir o último administrador ativo."})
        c.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
    audit(sess["email"], "usuario_excluir", alvo=u["email"], ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.get("/perfis")
def perfis_lista() -> JSONResponse:
    with _conn() as c:
        perfis = [dict(r) for r in c.execute(
            """SELECT p.*, (SELECT COUNT(*) FROM usuarios u WHERE u.perfil_id=p.id) AS usuarios
               FROM perfis p ORDER BY p.admin DESC, p.nome""").fetchall()]
        for p in perfis:
            p["telas"] = _telas_do_perfil(c, p["id"], bool(p["admin"]))
    return JSONResponse({"perfis": perfis})


def _valida_perfil_payload(payload: dict) -> tuple[str, list[str], str | None]:
    nome = (payload.get("nome") or "").strip()
    telas = payload.get("telas") or []
    if not nome:
        return "", [], "Informe o nome do perfil."
    if not isinstance(telas, list) or any(t not in TELAS for t in telas):
        return "", [], "Lista de telas inválida."
    return nome, telas, None


@router_gestao.post("/perfis")
def perfil_criar(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    nome, telas, erro = _valida_perfil_payload(payload)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    admin = 1 if payload.get("admin") else 0
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES(?,?,?,?)",
                (nome, (payload.get("descricao") or "").strip(), admin, _agora()))
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=422, content={
                "erro": "nome_em_uso", "mensagem": "Já existe perfil com esse nome."})
        pid = cur.lastrowid
        c.executemany("INSERT INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      [(pid, t) for t in telas])
    audit(sess["email"], "perfil_criar", alvo=nome,
          detalhe=f"admin={admin}; telas={','.join(telas) or '-'}", ip=_ip(request))
    return JSONResponse({"ok": True, "id": pid})


@router_gestao.post("/perfis/{perfil_id}")
def perfil_editar(perfil_id: int, payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    nome, telas, erro = _valida_perfil_payload(payload)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    admin = 1 if payload.get("admin") else 0
    with _conn() as c:
        p = c.execute("SELECT * FROM perfis WHERE id=?", (perfil_id,)).fetchone()
        if not p:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Perfil não existe."})
        if p["admin"] and not admin:
            outros = c.execute(
                """SELECT COUNT(*) AS n FROM usuarios u JOIN perfis p2 ON p2.id=u.perfil_id
                   WHERE p2.admin=1 AND u.ativo=1 AND p2.id<>?""", (perfil_id,)).fetchone()["n"]
            if outros == 0:
                return JSONResponse(status_code=422, content={
                    "erro": "ultimo_admin",
                    "mensagem": "Este é o único perfil com administradores ativos — "
                                "crie outro admin antes de rebaixá-lo."})
        try:
            c.execute("UPDATE perfis SET nome=?, descricao=?, admin=? WHERE id=?",
                      (nome, (payload.get("descricao") or "").strip(), admin, perfil_id))
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=422, content={
                "erro": "nome_em_uso", "mensagem": "Já existe perfil com esse nome."})
        c.execute("DELETE FROM perfil_telas WHERE perfil_id=?", (perfil_id,))
        c.executemany("INSERT INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                      [(perfil_id, t) for t in telas])
    audit(sess["email"], "perfil_editar", alvo=nome,
          detalhe=f"admin={admin}; telas={','.join(telas) or '-'}", ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.post("/perfis/{perfil_id}/excluir")
def perfil_excluir(perfil_id: int, request: Request) -> JSONResponse:
    sess = request.state.sessao
    with _conn() as c:
        p = c.execute("SELECT * FROM perfis WHERE id=?", (perfil_id,)).fetchone()
        if not p:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Perfil não existe."})
        em_uso = c.execute("SELECT COUNT(*) AS n FROM usuarios WHERE perfil_id=?",
                           (perfil_id,)).fetchone()["n"]
        if em_uso:
            return JSONResponse(status_code=422, content={
                "erro": "perfil_em_uso",
                "mensagem": f"Perfil em uso por {em_uso} usuário(s). Reatribua antes de excluir."})
        c.execute("DELETE FROM perfis WHERE id=?", (perfil_id,))
    audit(sess["email"], "perfil_excluir", alvo=p["nome"], ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.get("/auditoria")
def auditoria(limite: int = 200, busca: str | None = None) -> JSONResponse:
    limite = max(1, min(limite, 1000))
    busca = (busca or "").strip()
    sql = "SELECT * FROM audit_log"
    params: tuple = ()
    if busca:
        sql += " WHERE usuario LIKE ? OR acao LIKE ? OR alvo LIKE ? OR detalhe LIKE ?"
        like = f"%{busca}%"
        params = (like, like, like, like)
    sql += " ORDER BY id DESC LIMIT ?"
    with _conn() as c:
        rows = c.execute(sql, (*params, limite)).fetchall()
    return JSONResponse({"eventos": [dict(r) for r in rows]})


_CONFIG_LIMITES = {  # chave -> (mínimo, máximo)
    "sessao_ttl_min": (5, 1440 * 7),
    "max_tentativas": (3, 20),
    "bloqueio_min": (1, 1440),
    "senha_min": (6, 64),
}


@router_gestao.get("/config")
def config_get() -> JSONResponse:
    return JSONResponse({k: cfg(k) for k in _CONFIG_PADRAO})


@router_gestao.post("/config")
def config_set(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    # valida TUDO antes de gravar QUALQUER coisa (evita commit parcial em erro 422)
    novos: dict[str, int] = {}
    for chave, (lo, hi) in _CONFIG_LIMITES.items():
        if chave not in payload:
            continue
        try:
            valor = int(payload[chave])
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": f"{chave} deve ser inteiro."})
        if not (lo <= valor <= hi):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"{chave} deve estar entre {lo} e {hi}."})
        novos[chave] = valor
    if novos:
        with _conn() as c:
            for chave, valor in novos.items():
                c.execute("INSERT INTO config(chave, valor) VALUES(?,?) "
                          "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                          (chave, str(valor)))
        audit(sess["email"], "config_seguranca",
              detalhe="; ".join(f"{k}={v}" for k, v in novos.items()), ip=_ip(request))
    return JSONResponse({"ok": True, "config": {k: cfg(k) for k in _CONFIG_PADRAO}})


init_db()
