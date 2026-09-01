# -*- coding: utf-8 -*-
"""Cliente do webservice RasterIntegra (DataSnap/Delphi, REST JSON).

TRÊS COISAS QUE ESTE FORNECEDOR FAZ DIFERENTE (manual 13.1, mapeado em
01/09/2026):

1. **O nome do método vai ENTRE ASPAS na URL**:
   `/datasnap/rest/TWebService/"getPosicoes"` — sem as aspas o DataSnap
   devolve 404 e a pessoa procura o erro na credencial.
2. **Login e senha vão no CORPO de toda requisição** (não em cabeçalho).
   Por isso o `_sanitizar` varre o corpo de qualquer erro: a lição da
   Z-API (a URL era a credencial) vale aqui para o payload.
3. **"Nenhum dado" e "recusa" chegam como HTTP 200** com `CodErro` no
   corpo: 0=ok, 99=SEM REGISTROS NOVOS (é resposta, não falha),
   102=CONSUMO INDEVIDO (rate-limit: getPosicoes 30s, getMensagens 15s —
   o ERP fura o dele; o nosso RESPEITA), 103=MÉTODO NÃO LIBERADO
   (contrato), 105=validação, 200=OPERAÇÃO NEGADA. Regra genérica de erro
   vale por ENDPOINT — quem decide é o CodErro, nunca só o HTTP.

A credencial é EXCLUSIVA do CÓRTEX (RASTERINTEGRA_* no cofre): a do ERP
foi encontrada exposta no próprio banco e o mesmo login em dois
consumidores dobraria o consumo do rate-limit.
"""
from __future__ import annotations

import json as _json
import logging
import time
import urllib.error
import urllib.request

from api import tls as _tls
from api.credenciais import ler as _cred_ler

log = logging.getLogger("cortex.rasterintegra")

TIMEOUT = 60
# O manual anuncia integra.logaegr.com.br, mas esse host NAO RESOLVE desta
# rede (gaierror medido em 01/09/2026); o alias que o ERP usa resolve
# (186.225.0.58) com 8888 (http) e 8443 (TLS) abertas — TLS por padrão.
URL_PADRAO = "https://integra.rastergr.com.br:8443"

# CodErro que são RESPOSTA, não falha (o corpo diz "não há nada novo")
COD_SEM_REGISTROS = 99


class RasterIntegraNaoConfigurado(RuntimeError):
    """Sem credencial não é falha: é instalação incompleta."""


class RasterIntegraIndisponivel(RuntimeError):
    """O fornecedor não respondeu, ou respondeu recusando."""


class MetodoNaoLiberado(RasterIntegraIndisponivel):
    """CodErro 103 — o contrato não libera este método (falar com a Raster)."""


def _cred(nome: str) -> str:
    try:
        return (_cred_ler(nome) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def configurado() -> bool:
    return bool(_cred("RASTERINTEGRA_LOGIN") and _cred("RASTERINTEGRA_SENHA"))


def base_url() -> str:
    return (_cred("RASTERINTEGRA_URL") or URL_PADRAO).rstrip("/")


def _sanitizar(texto: str) -> str:
    saida = texto or ""
    for nome in ("RASTERINTEGRA_SENHA", "RASTERINTEGRA_LOGIN"):
        v = _cred(nome)
        if v and len(v) >= 4:
            saida = saida.replace(v, "…")
    return saida


def chamar(metodo: str, corpo: dict | None = None) -> dict:
    """Uma chamada ao webservice. Injeta Login/Senha; lê o CodErro.

    Devolve o dict de resposta com CodErro 0 ou 99 (sem registros novos —
    o chamador decide o que o vazio significa). Qualquer outro CodErro
    levanta com a Descricao do próprio fornecedor, sanitizada.
    """
    if not configurado():
        raise RasterIntegraNaoConfigurado(
            "faltam RASTERINTEGRA_LOGIN e RASTERINTEGRA_SENHA — cadastrar em "
            "Gestão › Integrações › RasterIntegra (credencial exclusiva do "
            "CÓRTEX, nunca a do ERP)")
    # o DataSnap exige o método ENTRE ASPAS na URL (manual, todos os exemplos)
    url = f'{base_url()}/datasnap/rest/TWebService/%22{metodo}%22'
    payload = dict(corpo or {})
    # O AMBIENTE decide o BANCO que o servidor abre: sem ele o DataSnap
    # quebra com "Neither DSN nor SERVER keyword supplied" ANTES de validar
    # a credencial (medido em 01/09/2026 — meia hora de depuração que este
    # comentário poupa). TipoRetorno JSON idem: o padrão deles é XML.
    payload.setdefault("Ambiente", "Producao")
    payload.setdefault("TipoRetorno", "JSON")
    payload.setdefault("Login", _cred("RASTERINTEGRA_LOGIN"))
    payload.setdefault("Senha", _cred("RASTERINTEGRA_SENHA"))
    dados = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=dados, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT,
                                    context=_tls.contexto()) as resp:
            bruto = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RasterIntegraIndisponivel(
            f"HTTP {exc.code} em {metodo}: "
            f"{_sanitizar(exc.read()[:200].decode('utf-8', 'replace'))}") from None
    except Exception as exc:  # noqa: BLE001
        raise RasterIntegraIndisponivel(
            f"{type(exc).__name__} ao chamar {metodo}: "
            f"{_sanitizar(str(exc))[:200]}") from None
    ms = int((time.monotonic() - t0) * 1000)

    try:
        d = _json.loads(bruto)
    except ValueError:
        raise RasterIntegraIndisponivel(
            f"{metodo} devolveu algo que não é JSON "
            f"({len(bruto)} bytes começando por {_sanitizar(bruto[:40])!r})") from None
    # o DataSnap costuma embrulhar em {"result": [ {...} ]}
    if isinstance(d, dict) and isinstance(d.get("result"), list) and d["result"]:
        d = d["result"][0]
    if not isinstance(d, dict):
        raise RasterIntegraIndisponivel(
            f"{metodo}: resposta em formato inesperado ({type(d).__name__})")

    cod = d.get("CodErro")
    cod = int(cod) if cod is not None else 0
    if cod == 103:
        raise MetodoNaoLiberado(
            f"{metodo}: o contrato não libera este método (CodErro 103) — "
            "pedir a liberação à Raster")
    if cod not in (0, COD_SEM_REGISTROS):
        raise RasterIntegraIndisponivel(
            f"{metodo}: CodErro {cod} — "
            f"{_sanitizar(str(d.get('Descricao') or d.get('DescErro') or ''))[:200]}")
    log.info("rasterintegra %s: CodErro %s em %sms", metodo, cod, ms)
    d["_cod_erro"] = cod
    return d


def testar() -> dict:
    """Prova de vida barata: a tabela de erros do próprio webservice.

    `getTabela` é o método de domínio — se ele responde, a credencial vale
    e o transporte está certo. Devolve um resumo escalar, nunca o dump.
    """
    d = chamar("getTabela", {"NomeTabela": "ERROS_WEBSERVICE"})
    itens = d.get("Registros") or d.get("Tabela") or d.get("Itens") or []
    return {"ok": True, "itens": len(itens) if isinstance(itens, list) else 0,
            "cod_erro": d.get("_cod_erro", 0)}
