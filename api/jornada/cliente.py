"""Cliente da API da RasterJOR (produto "E-Ponto - External API", v1.0.0).

O CONTRATO SAIU DA OPENAPI do fornecedor, em
https://www.rasterjor.com.br/external-api/openapi.json — a página de docs é um
Swagger UI e só devolve o título, mas a spec está ao lado dela.

Antes de ter a spec eu havia inferido caminhos e parâmetros do payload que o
AVA guardava em `dados_brutos_api`, e ERREI os dois: faltava o prefixo
`/external-api` e os parâmetros de data mudam POR ENDPOINT. Os nomes dos
CAMPOS, esses, a inferência acertou — e a spec confirma:

    {"driver_name": …, "driver_id": 230057, "driver_document": "27630264860",
     "branch_name": "SULISTA - MTZ", "work_schedule_name": "MATRIZ - DSR",
     "date": "2026-01-31", "start": null, "end": null,
     "total_time": 0, "activity_time": 0, "driving_time": 0,
     "stopped_in_journey_time": 0, "over_time": 0, "missing_time": 0,
     "activity_time_over_max_time": 0, "journey_type": "D",
     "kilometers_driven": null, "repose_time": 0, "missing_repose_time": 0,
     "meal_time": 0, "rest_time": 0}

Tempos em MINUTOS inteiros, datas em ISO. `kilometers_driven` e as datas de
início/fim vêm NULAS em dia sem jornada — e é por isso que todo acesso passa
por `_i()`/`_f()`, que tratam nulo sem transformar em zero silencioso.

═══════════════════════════════════════════════════════════════════════════
O QUE ESTE MÓDULO NÃO FAZ, e é deliberado
═══════════════════════════════════════════════════════════════════════════

NÃO INVENTA A URL NEM O CAMINHO. `RASTERJOR_API_BASE_URL` e as credenciais
vivem no cofre e não têm valor padrão. Sem elas `configurado()` devolve False e
a coleta RECUSA dizendo o que falta, em vez de bater num host adivinhado — que
no melhor caso dá 404 e no pior acerta o endpoint errado de outra empresa.

NÃO É "MODO TESTE" MAIS FROUXO. A coleta de um dia é a mesma chamada, com a
mesma trilha em `jor_carga`, seja ela disparada pelo agendador ou pela tela.
Caminho paralelo vira o atalho para rodar sem registro.
"""
from __future__ import annotations

import json as _json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from api import tls as _tls
from datetime import date as _date
from datetime import timedelta as _timedelta

from .. import credenciais

TIMEOUT = 60

# Recursos × endpoint, LIDOS DA OPENAPI do fornecedor
# (https://www.rasterjor.com.br/external-api/openapi.json — "E-Ponto - External
# API", v1.0.0). Antes daqui eu tinha inferido os caminhos e os parâmetros do
# payload que o AVA guardava, e errei os dois:
#
#   inferido            real
#   /drivers            /external-api/drivers/
#   /productivity       /external-api/productivity-report
#   start_date/end_date from_date/to_date  (produtividade)
#   start_date/end_date start/end          (inconformidades e ausências)
#
# O NOME DO PARÂMETRO DE DATA MUDA POR ENDPOINT, e não é padronizado nem dentro
# da própria API: produtividade e anomalias usam from_date/to_date,
# inconformidades e ausências usam start/end, e exceções de jornada e diárias
# usam data_inicial/data_final. Um único par serviria para nenhum deles.
#
# A ordem importa na coleta: motorista primeiro, porque jornada e
# inconformidade referenciam o CPF.
RECURSOS = ("motoristas", "jornadas", "inconformidades", "ausencias")

CATALOGO = {
    "motoristas": {
        "caminho": "/external-api/drivers/",
        "de": None, "ate": None,          # cadastro: não aceita janela
        "pagina": False,
    },
    "jornadas": {
        "caminho": "/external-api/productivity-report",
        "de": "from_date", "ate": "to_date",
        "pagina": False,                  # devolve array puro, sem envelope
    },
    "inconformidades": {
        "caminho": "/external-api/unconformities/",
        "de": "start", "ate": "end",
        "pagina": True,                   # {items, total, total_pages}
    },
    "ausencias": {
        "caminho": "/external-api/absences/",
        "de": "start", "ate": "end",      # date-time, não date
        "pagina": False,
        "datahora": True,
    },
}

# ── DUAS REGRAS DA API, descobertas na primeira chamada real ─────────────
#
# 1. SÓ CONSULTA RETROATIVA (D-1). Pedir uma janela que termine hoje devolve
#    HTTP 400: "Período inválido, são permitidas apenas consultas retroativas
#    (D-1)". A coleta corta `ate` em ontem sozinha — deixar o agendador
#    descobrir isso todo dia às 00h05 seria uma falha diária evitável.
#
# 2. LIMITE DE TAXA DE 10 MINUTOS no relatório de produtividade, e ele NÃO vem
#    como 429: vem HTTP **200** com `{"mensagem": "Faltam 10 minutos para
#    fazer outra consulta"}`. Um cliente que confia no código de status trata
#    isso como sucesso — e como o corpo é um objeto, ele vira UM registro
#    falso. Foi o que aconteceu aqui antes de olhar o conteúdo: janelas de 7 e
#    de 93 dias "traziam 1 registro" em 145 ms, contra 632 em 7 s.
#
#    É a mesma classe da Z-API, ao contrário: lá um 200 com `error` no corpo
#    era descritivo e não indicava falha; aqui um 200 sem `error` nenhum É a
#    falha. A regra que sobrevive às duas: ler o CORPO, não o status.
D_MENOS_1 = True
INTERVALO_CONSULTA_MIN = 10

# 3. JANELA MÁXIMA DE 31 DIAS. Pedir mais devolve "O período de busca deve ter
#    no máximo 31 dias" — e chega de DUAS formas diferentes na mesma API: HTTP
#    400 com `{"detail": …}` nas inconformidades e HTTP 200 com
#    `{"mensagem": …}` nas ausências. Quem tratar só o 400 acha que a segunda
#    deu certo e trouxe zero.
#
#    O cliente FATIA a janela em pedaços de 31 dias e concatena. Sem isso, o
#    preenchimento do buraco de quatro meses seria impossível pela rotina e
#    alguém teria de rodar oito comandos à mão.
JANELA_MAX_DIAS = 31

# 4. LIMITE DE TAXA ENTRE CHAMADAS. Fatiar em 31 dias resolve a janela e cria o
#    problema seguinte: as fatias saem em rajada e a API responde "Limite de
#    consultas excedido aguarde 30 segundos". Ela DIZ quantos segundos, então o
#    cliente espera e repete a fatia — uma vez.
#
#    O teto existe para não transformar espera em travamento: o relatório de
#    produtividade pede DEZ MINUTOS, e dormir dez minutos dentro de uma
#    requisição seria pior que a recusa. Acima do teto a recusa sobe, com o
#    motivo, e quem lê decide quando voltar.
ESPERA_MAX_S = 90
_RE_SEGUNDOS = re.compile(r"(\d+)\s*segundo", re.I)
_RE_MINUTOS = re.compile(r"(\d+)\s*minuto", re.I)


def _espera_pedida(msg: str) -> int:
    """Segundos que a recusa manda esperar, ou 0 se ela não fala em espera."""
    m = _RE_SEGUNDOS.search(msg)
    if m:
        return int(m.group(1))
    m = _RE_MINUTOS.search(msg)
    return int(m.group(1)) * 60 if m else 0

# Chaves que a API usa para falar em vez de responder. Um objeto que só traz
# uma delas, sem lista de dados, é recusa — não registro.
_CHAVES_RECUSA = ("mensagem", "detail", "message", "erro", "error")

# Teto de páginas por recurso numa passagem. NÃO é otimização: é o freio que
# impede uma resposta com `total_pages` absurdo (ou um laço que não avança) de
# virar requisição infinita contra o fornecedor. 200 páginas de 500 dão 100 mil
# registros, muito acima de qualquer janela real.
PAGINAS_MAX = 200
PAGINA_TAMANHO = 500


class NaoConfigurado(RuntimeError):
    """Falta credencial. Não é falha de rede: é instalação incompleta."""


class RasterIndisponivel(RuntimeError):
    """A API não respondeu ou respondeu erro. A mensagem já vem limpa."""


class RasterRecusou(RuntimeError):
    """A API funcionou e disse NÃO, com um motivo que a pessoa precisa ler.

    Separada de `RasterIndisponivel` pelo mesmo motivo que o CÓRTEX separa 409
    de 502: "faltam 10 minutos para outra consulta" e "o servidor caiu" pedem
    reações opostas — a primeira é esperar, a segunda é investigar.
    """


def _cred(nome: str) -> str:
    return (credenciais.ler(nome) or "").strip()


# O prefixo que TODO caminho da API carrega. Fica aqui porque o `base_url()`
# precisa saber removê-lo da ponta.
PREFIXO = "/external-api"


def base_url() -> str:
    """A raiz do host, SEM o prefixo da API.

    Normaliza porque as duas formas são igualmente naturais de colar: a
    documentação vive em `…/external-api/docs`, então quem copia da barra do
    navegador cola `https://www.rasterjor.com.br/external-api` — e aí os
    caminhos do catálogo, que já começam por `/external-api`, produziriam
    `/external-api/external-api/drivers/` e 404 em tudo. Aconteceu na primeira
    chamada real.

    Recusar a URL "errada" seria pedantismo: as duas apontam para o mesmo
    lugar e o cliente sabe qual é qual.
    """
    u = _cred("RASTERJOR_API_BASE_URL").rstrip("/")
    if u.endswith(PREFIXO):
        u = u[: -len(PREFIXO)]
    return u


def configurado() -> bool:
    """URL + alguma forma de autenticação. Sem os dois não há chamada."""
    return bool(base_url() and (_cred("RASTERJOR_TOKEN")
                                or (_cred("RASTERJOR_USUARIO")
                                    and _cred("RASTERJOR_SENHA"))))


def o_que_falta() -> str:
    """A frase que a tela mostra. Dizer QUAL campo falta poupa a viagem ao
    cofre para descobrir — e é o tipo de mensagem que o CLAUDE.md cobra."""
    if not base_url():
        return ("Falta a URL da API da RasterJOR "
                "(RASTERJOR_API_BASE_URL, em Gestão › Integrações).")
    if not (_cred("RASTERJOR_TOKEN") or (_cred("RASTERJOR_USUARIO")
                                         and _cred("RASTERJOR_SENHA"))):
        return ("Falta a autenticação da RasterJOR: um token "
                "(RASTERJOR_TOKEN) ou o par usuário e senha.")
    return ""


def _sanitizar(texto: str) -> str:
    """Nada de segredo em mensagem de erro.

    A lição é da Z-API, onde a URL ERA a credencial e `str(exc)` do urllib a
    despejava na tela, no log e na trilha. Aqui o token vai em cabeçalho, mas a
    senha pode aparecer numa URL malformada — e a varredura custa nada.
    """
    saida = texto or ""
    for nome in ("RASTERJOR_TOKEN", "RASTERJOR_SENHA", "RASTERJOR_USUARIO"):
        v = _cred(nome)
        if v and len(v) >= 4:
            saida = saida.replace(v, "…")
    return saida


def _cabecalhos() -> dict:
    h = {"Accept": "application/json"}
    tok = _cred("RASTERJOR_TOKEN")
    if tok:
        prefixo = _cred("RASTERJOR_AUTH_PREFIXO") or "Bearer"
        cab = _cred("RASTERJOR_AUTH_HEADER") or "Authorization"
        h[cab] = f"{prefixo} {tok}".strip()
    else:
        import base64
        par = f"{_cred('RASTERJOR_USUARIO')}:{_cred('RASTERJOR_SENHA')}"
        h["Authorization"] = "Basic " + base64.b64encode(par.encode()).decode()
    return h


def _uma_pagina(recurso: str, cfg: dict, de, ate, pagina: int | None):
    """Uma requisição. Devolve (registros, total_pages, ms)."""
    caminho = _cred(f"RASTERJOR_PATH_{recurso.upper()}") or cfg["caminho"]
    q: dict = {}
    if de and cfg.get("de"):
        q[cfg["de"]] = f"{de}T00:00:00" if cfg.get("datahora") else de
    if ate and cfg.get("ate"):
        q[cfg["ate"]] = f"{ate}T23:59:59" if cfg.get("datahora") else ate
    if pagina is not None:
        q["page"] = pagina
        q["page_size"] = PAGINA_TAMANHO
    url = base_url() + caminho + ("?" + urllib.parse.urlencode(q) if q else "")

    t0 = time.monotonic()
    req = urllib.request.Request(url, headers=_cabecalhos(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_tls.contexto()) as resp:
            corpo = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RasterIndisponivel(
            f"HTTP {exc.code} em {recurso}: "
            f"{_sanitizar(exc.read()[:200].decode('utf-8', 'replace'))}") from None
    except Exception as exc:  # noqa: BLE001
        raise RasterIndisponivel(
            f"{type(exc).__name__} ao chamar {recurso}: "
            f"{_sanitizar(str(exc))[:200]}") from None
    ms = int((time.monotonic() - t0) * 1000)

    try:
        dados = _json.loads(corpo)
    except ValueError:
        raise RasterIndisponivel(
            f"{recurso} devolveu algo que não é JSON "
            f"({len(corpo)} bytes começando por {corpo[:40]!r}).") from None

    # A API mistura as duas formas: produtividade, motoristas e ausências vêm
    # como ARRAY puro; inconformidades e eventos vêm em {items, total,
    # total_pages}. Enfiar uma lista num `dict.get()` devolveria "nenhum
    # registro" sem erro nenhum — foi o que aconteceu com o /groups da Z-API.
    if isinstance(dados, list):
        return dados, 1, ms
    if isinstance(dados, dict):
        for chave in ("items", "data", "results", "records", "content"):
            if isinstance(dados.get(chave), list):
                return dados[chave], int(dados.get("total_pages") or 1), ms
        # 200 QUE É RECUSA. Sem lista de dados e com uma chave de mensagem, o
        # que veio foi a API dizendo não — limite de taxa, período inválido.
        # Devolver `[dados]` faria disso um registro falso, e a trilha
        # registraria "1 lido" numa coleta que não trouxe nada.
        recado = next((str(dados[c]) for c in _CHAVES_RECUSA
                       if dados.get(c)), "")
        if recado:
            raise RasterRecusou(f"{recurso}: {_sanitizar(recado)[:200]}")
        return [dados], 1, ms
    raise RasterIndisponivel(
        f"{recurso} devolveu {type(dados).__name__}, esperado lista ou objeto.")


def _fatias(de: str | None, ate: str | None):
    """A janela em pedaços de no máximo `JANELA_MAX_DIAS`.

    Sem janela (cadastro), devolve uma fatia vazia — a chamada acontece uma
    vez, sem parâmetro de data.
    """
    if not de or not ate:
        yield (de, ate)
        return
    d0 = _date.fromisoformat(de)
    d1 = _date.fromisoformat(ate)
    while d0 <= d1:
        fim = min(d0 + _timedelta(days=JANELA_MAX_DIAS - 1), d1)
        yield (d0.isoformat(), fim.isoformat())
        d0 = fim + _timedelta(days=1)


def _paginado(recurso: str, cfg: dict, de, ate) -> tuple[list, int]:
    """Todas as páginas de UMA fatia."""
    if not cfg.get("pagina"):
        linhas, _, ms = _uma_pagina(recurso, cfg, de, ate, None)
        return linhas, ms
    tudo: list = []
    total_ms = 0
    pagina = 1
    while pagina <= PAGINAS_MAX:
        linhas, total_pag, ms = _uma_pagina(recurso, cfg, de, ate, pagina)
        total_ms += ms
        tudo.extend(linhas)
        # PÁGINA VAZIA ENCERRA mesmo com `total_pages` alto: sem isso, uma API
        # que devolve total_pages errado faria o laço rodar até o teto.
        if not linhas or pagina >= total_pag:
            break
        pagina += 1
    return tudo, total_ms


def chamar(recurso: str, *, de: str | None = None,
           ate: str | None = None) -> tuple[list, int]:
    """Todos os registros do recurso na janela. Devolve (lista, milissegundos).

    FATIA em 31 dias (limite da API) e PAGINA dentro de cada fatia
    (`unconformities` devolve `total_pages`). Ler só a primeira página traria
    500 de milhares sem erro nenhum — o tipo de perda que não aparece como
    falha, só como número menor do que devia.
    """
    if not configurado():
        raise NaoConfigurado(o_que_falta())
    cfg = CATALOGO.get(recurso)
    if not cfg:
        raise RasterIndisponivel(f"recurso desconhecido: {recurso}")

    tudo: list = []
    total_ms = 0
    for f_de, f_ate in _fatias(de if cfg.get("de") else None,
                               ate if cfg.get("ate") else None):
        try:
            linhas, ms = _paginado(recurso, cfg, f_de, f_ate)
        except RasterRecusou as exc:
            s = _espera_pedida(str(exc))
            if not s or s > ESPERA_MAX_S:
                raise
            time.sleep(s + 1)
            linhas, ms = _paginado(recurso, cfg, f_de, f_ate)
        tudo.extend(linhas)
        total_ms += ms
    return tudo, total_ms

def diagnostico() -> dict:
    """Para a Saúde e para a tela de Integrações. NÃO chama a API: dizer se a
    credencial existe não deve custar uma requisição."""
    return {"configurado": configurado(), "falta": o_que_falta(),
            "base_url": base_url(), "recursos": list(RECURSOS)}
