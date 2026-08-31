# -*- coding: utf-8 -*-
"""Cliente do QualP — rota com PRAÇAS DE PEDÁGIO, tarifa vigente e piso ANTT.

POR QUE O QUALP ENTRA AQUI
==========================
A tabela de preço de praça do ERP está congelada: são **921 praças ativas**,
849 com algum valor, e apenas **64 (7%) com tarifa de 2025 em diante** — a mais
recente é de 01/08/2025. Pedágio reajusta todo ano. Validar "preço cobrado por
praça" contra ela hoje compararia cobrança de 2026 com tarifa de 2019 a 2024 e
produziria diferença falsa em quase toda praça.

Medido em 30/08/2026, não suposto.

O FORMATO NÃO ESTAVA NA DOCUMENTAÇÃO — SAIU DO CLIENTE DELES
============================================================
Dez formas de parâmetro plano deram `HTTP 500` seguidas. O endpoint recebe UM
parâmetro só, `json`, com o objeto inteiro dentro:

    GET /api/site/router?json=<JSON codificado>

Isso foi lido no bundle do próprio site (`searchRouter` → `makeRequestParams`),
não adivinhado. Quando a dúvida for de FORMATO, o cliente que sabe chamar está
publicado — e ler leva menos tempo que a terceira tentativa.

O TETO, QUE DECIDE O DESENHO — E A CONTA DO SITE NÃO O LEVANTA
==============================================================
O endpoint responde **três consultas por dia, por IP** — a quarta volta
`HTTP 402` com a mensagem em português.

**Eu supus que a conta resolveria, e medi o contrário.** Com usuário e senha
configurados, `POST /api/site/login/authenticate` devolve `login_cod` e
`login_token` normalmente — o login FUNCIONA —, e a quarta consulta continua
sendo recusada com o mesmo 402. Duas coisas explicam:

- `makeRequestParams`, no cliente deles, manda **`login_cod:""` FIXO**: nem o
  site logado põe a sessão no corpo do router. Ela viaja pela instância de
  HTTP deles (cabeçalho ou cookie), não pelo `json`.
- E a mensagem diz "consultas **gratuitas**", o que aponta para plano pago. O
  QualP tem uma **API comercial separada** (`api.qualp.com.br`, com chave),
  que é outro produto da conta do site.

Então o teto é do endpoint do SITE e a conta não muda isso. O módulo mantém o
login porque ele é barato, memoizado e pode passar a valer; mas **quem projeta
em cima disto precisa contar com três consultas por dia** até haver chave da
API comercial. Por isso este módulo NÃO é chamado por viagem: ele alimenta um
CACHE de praça, e quem valida trabalha sobre o cache. Uma tela que consultasse
a rota de cada vale morreria no quarto registro do dia.

O QUE A RESPOSTA TRAZ, ALÉM DO PEDÁGIO
======================================
- `pedagios.pracas[]` — cada praça com **`codigo_antt`**, que é a MESMA chave
  da `pracapedagio.codigoantt` do ERP: é por ela que os dois mundos se ligam.
  Mais `tarifa`, `data_ultima_atualizacao`, concessionária, sentido, km,
  `porcentagem_tag`, `porcentagem_fim_semana`, `is_free_flow`, `is_ferry`.
- `rota.total_tolls` — bruto, com tag, fim de semana e líquido, e a média por
  eixo de cada um.
- `balancas[]` — as balanças do trajeto.
- `frete` e `frete_retorno_vazio` — o **piso ANTT por eixo × tipo de carga**,
  com `antt_resolucao` dizendo qual resolução está em vigor. O CÓRTEX calcula
  isso hoje a partir de YAML versionado à mão; comparar os dois é trabalho de
  outra rodada, e está anotado.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from .. import credenciais, tls

log = logging.getLogger(__name__)

BASE = "https://app.qualp.com.br/api"

# Sem User-Agent e Referer o endpoint responde 500. Não é proteção — é a origem
# que ele espera de quem chama a API do próprio site.
_CAB = {
    "Accept": "application/json",
    "Referer": "https://qualp.com.br/",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
}

TEMPO_S = 45


class QualpIndisponivel(RuntimeError):
    """Falha ao falar com o QualP, já com a mensagem pronta para a tela."""


class QualpSemCota(QualpIndisponivel):
    """`HTTP 402`: as três consultas gratuitas do dia acabaram.

    Classe PRÓPRIA porque o conserto é outro: não é tentar de novo nem
    investigar rede — é esperar o dia virar ou pôr a conta de assinante. Quem
    chama precisa distinguir para não repetir a chamada em laço.
    """


# A AUTENTICAÇÃO NÃO É POR CHAVE — é usuário e senha, trocados por um par
# `login_cod` + `login_token`. Lido do bundle deles:
#
#     POST /api/site/login/authenticate  {username, password}
#       -> {success, data: {login_cod, login_token, …}}
#
# e o `login_cod` volta DENTRO do `json` do router (o anônimo manda `""`).
# Vale registrar porque a diferença muda o desenho: chave seria um segredo
# imutável no cofre; sessão precisa ser renovada e cacheada, e um par expirado
# se parece com "sem cota" se ninguém distinguir.
_SESSAO: dict = {}


def credencial() -> tuple[str | None, str | None]:
    """Usuário e senha do cofre. Sem eles vale o limite de 3 consultas/dia."""
    try:
        return credenciais.ler("QUALP_USUARIO"), credenciais.ler("QUALP_SENHA")
    except Exception:  # noqa: BLE001 - cofre ausente não derruba a leitura
        return None, None


def autenticar(forcar: bool = False) -> dict:
    """Troca usuário/senha pelo par de sessão, e o memoiza.

    Memoiza porque cada `autenticar()` é uma ida à rede: fazer login a cada
    consulta gastaria duas chamadas onde uma basta, e num teto de três por dia
    isso é a diferença entre uma consulta e nenhuma.
    """
    u, s = credencial()
    if not (u and s):
        return {}
    if _SESSAO and not forcar:
        return _SESSAO
    dados = json.dumps({"username": u, "password": s}).encode()
    req = urllib.request.Request(
        BASE + "/site/login/authenticate", data=dados,
        headers={**_CAB, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_S,
                                    context=tls.contexto()) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise QualpIndisponivel(
            "O QualP recusou o login (HTTP %s). Confira usuario e senha em "
            "Gestao > Integracoes." % exc.code) from None
    except Exception as exc:  # noqa: BLE001
        raise QualpIndisponivel(
            "Nao foi possivel falar com o QualP (%s)." % type(exc).__name__) from None
    if not d.get("success") or not d.get("data"):
        raise QualpIndisponivel(
            "O QualP recusou o login: %s" % (d.get("message") or "sem motivo"))
    dd = d["data"]
    _SESSAO.clear()
    _SESSAO.update({"login_cod": str(dd.get("login_cod") or ""),
                    "login_token": str(dd.get("login_token") or "")})
    return _SESSAO


def regime() -> str:
    """`logado` ou `anonimo` — e nenhum dos dois muda o TETO.

    Chamava-se `assinante` e devolvia a promessa errada: medido em 30/08/2026,
    a conta do site autentica e a quarta consulta do dia continua recusada. O
    que levantaria o teto é chave da API comercial (`api.qualp.com.br`), que é
    outro produto.

    O nome importa porque ele vai para o cartão de integração: "assinante"
    convidava a planejar em cima de um limite que não existe.
    """
    u, s = credencial()
    return "logado" if (u and s) else "anonimo"


def _get(caminho: str, params: dict) -> dict:
    url = BASE + caminho + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_CAB)
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_S,
                                    context=tls.contexto()) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        corpo = ""
        try:
            corpo = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        if exc.code == 402:
            raise QualpSemCota(
                "O QualP recusou: as tres consultas gratuitas do dia acabaram. "
                "MEDIDO em 30/08/2026: a conta do site NAO levanta este teto - "
                "o login funciona e a quarta consulta continua sendo recusada. "
                "O que levanta e uma chave da API comercial (api.qualp.com.br), "
                "que e produto separado da conta do site.") from None
        raise QualpIndisponivel(
            "O QualP respondeu HTTP %s. %s" % (exc.code, _resumo(corpo))) from None
    except Exception as exc:  # noqa: BLE001
        raise QualpIndisponivel(
            "Nao foi possivel falar com o QualP (%s)." % type(exc).__name__) from None


def _resumo(corpo: str) -> str:
    """A mensagem do fornecedor, se for legível; senão, nada.

    Repetir JSON cru na tela não ajuda ninguém — e a do QualP vem em português
    e diz o conserto ("limite de 3 consultas gratuitas por dia").
    """
    try:
        return str(json.loads(corpo).get("message") or "")[:160]
    except Exception:  # noqa: BLE001
        return ""


def rota(waypoints: list[str], *, eixos: int = 6, categoria: str = "caminhao",
         data: str | None = None, volta: bool = False) -> dict:
    """Rota entre os pontos, com as praças e a tarifa de cada uma.

    `costing:"bus"` é o que ELES usam para caminhão — não é engano de cópia, é
    o perfil do motor de rotas deles, lido do bundle.

    `data` no formato `YYYY-MM-DD` pede a tarifa VIGENTE NAQUELE DIA
    (`config_pedagio.prices_from_date`) — é o que permite conferir uma viagem
    de março contra o preço de março, e não contra o de hoje. Sem isso toda
    validação retroativa erraria pelo reajuste do ano.
    """
    # A SESSÃO ENTRA NO CORPO, não num cabeçalho — é onde o cliente deles a
    # põe. Sem credencial o `login_cod` vai vazio, que é a chamada anônima e
    # continua funcionando (com o teto de três por dia).
    ses = autenticar()
    corpo = {
        "login_cod": ses.get("login_cod", ""),
        "login_token": ses.get("login_token", ""),
        "waypoints": waypoints,
        "config_rota": {
            "volta": volta,
            "costing": "bus",
            "costing_options": {"bus": {"shortest": False,
                                        "toll_booth_penalty": 0,
                                        "top_speed": 140}},
            "directions_options": {"units": "km", "language": "pt-BR",
                                   "directions_type": "maneuvers",
                                   "narrative": True},
        },
        "config_veiculo": {"categoria": categoria, "eixos": eixos},
        "config_pedagio": {"prices_from_date": data or ""},
        "consumo_combustivel": {"preco": 0, "consumo": 0},
        "mc": "mc",
        "type_route": "efficient",
    }
    return _get("/site/router", {"json": json.dumps(corpo, ensure_ascii=False)})


def _rota0(resposta: dict) -> dict:
    rotas = resposta.get("rotas") or []
    r0 = rotas[0] if isinstance(rotas, list) else rotas
    return r0 if isinstance(r0, dict) else {}


def pracas_da_rota(resposta: dict, eixos: int) -> list[dict]:
    """As praças, no formato que o CÓRTEX guarda.

    `eixos` entra na saída de propósito: a `tarifa` que volta é a do eixo
    PEDIDO na consulta — o QualP já multiplica. Guardar isso sem registrar
    quantos eixos foram pedidos produziria um cache que mistura preço de 5 e de
    6 eixos na mesma linha, e a validação passaria a acusar diferença que ela
    mesma criou.
    """
    fora = []
    for p in ((_rota0(resposta).get("pedagios") or {}).get("pracas")) or []:
        fora.append({
            "codigo_antt": (p.get("codigo_antt") or "").strip() or None,
            "id_qualp": p.get("id"),
            "eixos": eixos,
            "nome": p.get("nome"),
            "rodovia": p.get("rodovia"),
            "uf": p.get("uf"),
            "cidade": p.get("cidade"),
            "km": p.get("km"),
            "sentido": p.get("sentido"),
            "concessionaria": p.get("concessionaria"),
            "lat": p.get("lat"),
            "lng": p.get("lng"),
            "tarifa": float(p.get("tarifa") or 0),
            "tarifa_tag": (float(p["tarifa_tag"])
                           if p.get("tarifa_tag") is not None else None),
            "tarifa_fim_semana": (float(p["tarifa_fim_semana"])
                                  if p.get("tarifa_fim_semana") is not None else None),
            "pct_tag": float(p.get("porcentagem_tag") or 0),
            "pct_fim_semana": float(p.get("porcentagem_fim_semana") or 0),
            "free_flow": bool(p.get("is_free_flow")),
            "balsa": bool(p.get("is_ferry")),
            "atualizada_em": p.get("data_ultima_atualizacao"),
        })
    return fora


def total_da_rota(resposta: dict) -> dict:
    """Bruto, com tag, fim de semana e líquido — e a média por eixo de cada um."""
    return ((_rota0(resposta).get("rota") or {}).get("total_tolls") or {}).get("raw") or {}


def resolucao_antt(resposta: dict) -> dict:
    """Qual resolução da ANTT o cálculo usou — vai para o ⓘ da tela.

    Número sem a norma que o gerou não se discute com ninguém.
    """
    return resposta.get("antt_resolucao") or {}
