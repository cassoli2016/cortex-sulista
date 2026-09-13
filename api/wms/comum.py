# -*- coding: utf-8 -*-
"""O que o WMS inteiro compartilha: domínios, a transação e a tradução das
recusas do banco para frase de gente.

POR QUE A TRADUÇÃO MORA AQUI
============================
As duas regras que não podem falhar — saldo nunca negativo e kardex imutável —
são do BANCO (trigger em `sql/cortex/0090_wms.sql`), não do Python: regra que
só existe na rota é a que a próxima rota esquece, e a que uma corrida entre
duas pessoas na mesma doca atravessa. O preço é que a recusa chega como
exceção do psycopg. `transacao()` a converte em `DadoInvalido` (vira 409 com
a mensagem inteira), e é um ponto só para todos os arquivos do módulo.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg

from .. import pglocal
from ..validacao import DadoInvalido

# Redirecionado pelos testes para o schema descartável (fixture `esquema_pg`).
# TODOS os arquivos do módulo leem daqui — é um ponto só para esquecer.
ESQUEMA: str | None = None

TIPOS_ENDERECO = ("porta_palete", "picking", "blocado", "doca", "expedicao", "avaria")
# Onde a mercadoria é GUARDADA — e, por isso, de onde a separação tira.
TIPOS_GUARDA = ("porta_palete", "picking", "blocado")
ROTULO_TIPO = {
    "porta_palete": "Porta-palete", "picking": "Picking", "blocado": "Blocado (chão)",
    "doca": "Doca", "expedicao": "Expedição", "avaria": "Avaria / quarentena",
}
MOTIVOS_BLOQUEIO = ("avaria", "quarentena", "inspeção", "estrutura danificada",
                    "reservado ao cliente", "outro")

# A trava consultiva que o trigger do kardex usa. O Python pega a MESMA antes
# de ler o disponível: são reentrantes na mesma sessão, então o trigger não
# espera por quem já a tem.
TRAVA = 84084

_RE_PLACA = re.compile(r"^[A-Z]{3}[0-9][0-9A-Z][0-9]{2}$")
_RE_CHAVE = re.compile(r"^[0-9]{44}$")


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


# ------------------------------------------------------------ transação
_MSG_UNICA = {
    "ux_wms_recebimento_nf": "Esta nota já tem um recebimento aberto ou conferido.",
    "wms_armazem_codigo_key": "Já existe um armazém com este código.",
    "wms_endereco_armazem_id_codigo_key": "Este endereço já existe neste armazém.",
    "wms_produto_depositante_cnpj_codigo_key": "Este produto já está cadastrado para o depositante.",
    "wms_depositante_pkey": "Este depositante já está cadastrado.",
}


@contextmanager
def transacao(esquema: str | None = None):
    """Uma transação, com a recusa do banco traduzida.

    A mensagem do trigger começa com 'WMS:' e é escrita para a tela; qualquer
    outra exceção do banco segue como falha nossa (500), porque é.
    """
    try:
        with pglocal.get_conn(_esq(esquema)) as conn:
            yield conn
    except psycopg.errors.RaiseException as exc:
        msg = (exc.diag.message_primary or str(exc)).strip()
        raise DadoInvalido(msg.removeprefix("WMS:").strip()) from None
    except psycopg.errors.UniqueViolation as exc:
        raise DadoInvalido(_MSG_UNICA.get(exc.diag.constraint_name or "",
                                          "Registro duplicado.")) from None


def travar_produtos(cur, produtos) -> None:
    """Pega a trava de cada produto em ORDEM CRESCENTE — duas liberações que
    pedissem os mesmos produtos em ordens diferentes se travariam uma à outra
    (deadlock) sem esta ordem."""
    for pid in sorted({int(p) for p in produtos}):
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (TRAVA, pid))


def auditar(cur, usuario: str, acao: str, alvo: str = "", detalhe: str = "") -> None:
    """A trilha entra NA MESMA transação da ação: ou as duas ficam, ou nenhuma.
    (Aqui não há ação externa para auditar antes — tudo é o banco da casa.)

    O carimbo é o de `auth._agora()`, e não `now()`: a trilha é uma coluna de
    texto lida pela tela de Auditoria, e dois formatos de data na mesma coluna
    ordenariam errado."""
    from .. import auth
    cur.execute(
        "INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip)"
        " VALUES(%s, %s, %s, %s, %s, '')",
        (auth._agora(), usuario or "", acao, alvo, detalhe[:2000]))


def ler(sql: str, params=None, esquema: str | None = None) -> list[dict]:
    return pglocal.query(sql, params, esquema=_esq(esquema))


def curinga(texto) -> str | None:
    """Padrão de ILIKE montado no PYTHON, com `%` e `_` do usuário escapados:
    `%` escrito dentro da constante SQL vira placeholder do psycopg, e o `_`
    digitado casaria qualquer caractere."""
    t = str(texto or "").strip()
    if not t:
        return None
    return "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ------------------------------------------------------------ validação
def cnpj(valor, rotulo: str = "o CNPJ do depositante") -> str:
    d = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if len(d) not in (11, 14):
        raise DadoInvalido(f"Informe {rotulo} com 14 dígitos (ou CPF com 11).")
    return d


def chave_nf(valor, *, obrigatoria: bool = False) -> str:
    d = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if not d:
        if obrigatoria:
            raise DadoInvalido("Informe a chave de acesso da nota (44 dígitos).")
        return ""
    if not _RE_CHAVE.match(d):
        raise DadoInvalido(f"A chave de acesso tem 44 dígitos — esta tem {len(d)}.")
    return d


def placa(valor, *, obrigatoria: bool = False) -> str:
    p = re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())
    if not p:
        if obrigatoria:
            raise DadoInvalido("Informe a placa do veículo.")
        return ""
    if not _RE_PLACA.match(p):
        raise DadoInvalido(f"Placa {valor!s} não tem o formato ABC1234 nem ABC1D23.")
    return p


def lote(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip().upper()[:40]


def inteiro_id(valor, rotulo: str) -> int:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        raise DadoInvalido(f"Escolha {rotulo}.") from None
    if n <= 0:
        raise DadoInvalido(f"Escolha {rotulo}.")
    return n


# ------------------------------------------------------------ serialização
def limpar(linha: dict | None) -> dict | None:
    """Converte no LIMITE do módulo: `Decimal`, `date` e `UUID` estouram no
    `JSONResponse` DEPOIS do `try` da rota — 500 em texto, sem pista."""
    if linha is None:
        return None
    out = {}
    for k, v in linha.items():
        if isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, (datetime, date)):
            v = v.isoformat()
        elif isinstance(v, UUID):
            v = str(v)
        out[k] = v
    return out


def limpar_todas(linhas) -> list[dict]:
    return [limpar(x) for x in (linhas or [])]
