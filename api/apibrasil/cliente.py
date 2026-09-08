"""Cliente da APIBrasil (https://gateway.apibrasil.io).

O QUE ESTA INTEGRAÇÃO ACRESCENTA — E O QUE ELA NÃO ACRESCENTA
=============================================================
Medido no ERP em 07/09/2026, sobre as 1.977 placas ativas, ANTES de gastar a
primeira consulta. O cadastro do AVA está praticamente completo na parte de
IDENTIDADE, para os três vínculos:

  campo                próprio  agregado  terceiro
  numerochassi           100%     100%       98%
  codigorenavam          100%     100%      100%
  marcaveiculo           100%     100%      100%
  modeloveiculo          100%     100%      100%
  anofabricacao          100%     100%       95%
  ufemplacamento         100%     100%      100%
  tara / capacidade      100%     100%      100%

Então **a APIBrasil não é para descobrir marca e chassi** — isso o ERP já
sabe. O que ela acrescenta, e ninguém mais tem:

  · **situação da placa no Detran** e o CRLV (licenciado? vencido? débito?);
  · **restrição** — roubo/furto, alienação, leilão, sinistro/baixa;
  · **FIPE**, que no ERP existe em 51% dos próprios e em 0% de agregado e
    terceiro;
  · **conferência** do que o ERP afirma: chassi, marca e ano vindos do Detran
    contra os digitados no AVA. É o único caminho para saber que um cadastro
    de 100% de preenchimento está 100% CORRETO — preenchido e correto são
    perguntas diferentes, e só a segunda decide.

E há uma sobreposição que precisa ser dita para não se pagar duas vezes: a
**Smartec já cobre licenciamento e IPVA de 302 placas próprias**
(`smt_licenciamento`, 303 linhas) e a cor de todas elas — campo que o ERP tem
zerado. `smt_restricoes` existe e está VAZIA, então restrição continua sem
fonte. A coleta pode pular o que a Smartec já traz; ver `api/equipamentos/`.

AUTENTICAÇÃO: DOIS SEGREDOS, NÃO UM
===================================
`Authorization: Bearer <token>` é da CONTA e vale para todas as APIs;
`DeviceToken` é do PRODUTO contratado. Uma conta com quatro produtos tem
quatro DeviceTokens, e usar o de um produto no caminho de outro devolve erro
de autorização que se lê como "credencial errada" — quando o errado é o par.
Por isso o catálogo aceita um DeviceToken POR PRODUTO, com um geral de reserva.

O QUE ESTÁ CONFIRMADO E O QUE NÃO ESTÁ
======================================
Só `dados` tem caminho confirmado em documentação pública
(`POST /api/v2/vehicles/dados`, corpo `{"placa": "..."}`). Os outros três
caminhos do catálogo estão marcados `confirmado=False` porque foram inferidos,
e **inferir caminho de fornecedor no melhor caso dá 404 e no pior acerta o
endpoint de outra coisa** — foi a lição da RasterJOR. `sondar()` confirma cada
um contra a API real, com UMA consulta, e é o que deve rodar antes de qualquer
carga. Enquanto não confirmado, o produto não entra em coleta em massa.
"""
from __future__ import annotations

import json as _json
import logging
import ssl
import time
import urllib.error
import urllib.request

from api import tls as _tls

from .. import credenciais

log = logging.getLogger(__name__)

BASE = "https://gateway.apibrasil.io/api/v2"
TIMEOUT = 60

# `User-Agent` próprio por hábito da casa: a Smartec devolve 403 para o
# `Python-urllib/3.13` padrão, e o sintoma (funciona no curl, falha no código)
# manda procurar defeito no lugar errado.
CABECALHOS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Cortex-Sulista/1.0",
}


class ApiBrasilErro(RuntimeError):
    """Falha ao falar com a APIBrasil. A mensagem já vem sanitizada."""


class ApiBrasilNaoConfigurado(ApiBrasilErro):
    """Faltam credenciais. Instalação incompleta, não falha de integração."""


class ApiBrasilRecusa(ApiBrasilErro):
    """A APIBrasil respondeu e disse NÃO, com motivo que a pessoa precisa ler.

    Separada porque o conserto é outro: aqui o CÓRTEX funcionou e o fornecedor
    recusou (cota do dia esgotada, produto não contratado, placa inválida).
    Vira 4xx na rota, nunca 5xx — o Cloudflare troca o corpo dos 5xx da origem
    pela página dele e a mensagem nunca cruzaria o túnel.
    """


class ApiBrasilSemDado(ApiBrasilErro):
    """A placa foi consultada e o Detran não a conhece.

    NÃO é falha, e não pode ser tratada como uma: é um FATO sobre a placa, e
    um fato que interessa — placa ativa no ERP que o Detran não conhece é
    cadastro furado, e é dos achados mais valiosos desta integração.
    """


# ──────────────────────────────────────────────────────────────── catálogo
#
# A tela manda a CHAVE; o servidor monta o caminho. Nunca URL livre vinda do
# navegador — regra da casa para playground de fornecedor.
#
# `confirmado` diz se o caminho veio de documentação/resposta real ou de
# inferência. Ver o cabeçalho do módulo: só `dados` está confirmado.
CATALOGO: dict[str, dict] = {
    "dados": {
        "path": "/vehicles/dados",
        "confirmado": True,
        "credencial": "APIBRASIL_DEVICE_TOKEN_DADOS",
        "doc": "Identidade do veículo no Detran: marca, modelo, versão, "
               "chassi, ano, cor, combustível, município e UF de emplacamento.",
    },
    "crlv": {
        "path": "/vehicles/crlv",
        "confirmado": False,
        "credencial": "APIBRASIL_DEVICE_TOKEN_CRLV",
        "doc": "Situação do licenciamento: exercício, vencimento, débitos, "
               "IPVA e restrições administrativas.",
    },
    "fipe": {
        "path": "/vehicles/fipe",
        "confirmado": False,
        "credencial": "APIBRASIL_DEVICE_TOKEN_FIPE",
        "doc": "Valor de mercado da placa pela tabela FIPE, com o mês de "
               "referência.",
    },
    "seguranca": {
        "path": "/vehicles/seguranca",
        "confirmado": False,
        "credencial": "APIBRASIL_DEVICE_TOKEN_SEGURANCA",
        "doc": "Restrição de roubo/furto, histórico de leilão, sinistro e "
               "baixa. É a triagem de quem entra no pátio.",
    },
}

PRODUTOS = tuple(CATALOGO)


def _bearer() -> str:
    tok = (credenciais.ler("APIBRASIL_TOKEN") or "").strip()
    if not tok:
        raise ApiBrasilNaoConfigurado(
            "Token da APIBrasil não configurado. "
            "Administração › Integrações › APIBrasil.")
    return tok


def _device(produto: str) -> str:
    """O DeviceToken do produto, com o geral de reserva.

    Sem valor padrão inventado: conta que contratou só `dados` não tem
    DeviceToken de FIPE, e devolver o do `dados` ali produziria um erro de
    autorização que se lê como token errado.
    """
    op = CATALOGO.get(produto) or {}
    especifico = (credenciais.ler(op.get("credencial", "")) or "").strip()
    if especifico:
        return especifico
    geral = (credenciais.ler("APIBRASIL_DEVICE_TOKEN") or "").strip()
    if not geral:
        raise ApiBrasilNaoConfigurado(
            f"DeviceToken do produto '{produto}' não configurado, e não há "
            f"DeviceToken geral. Administração › Integrações › APIBrasil.")
    return geral


def configurado(produto: str | None = None) -> bool:
    """Ausência de credencial NÃO é falha: é instalação incompleta.

    A Saúde marca `info` e diz o que falta, em vez de vermelho — alarme que
    acende sem haver problema ensina a ignorar o alarme.
    """
    try:
        _bearer()
        if produto:
            _device(produto)
        return True
    except ApiBrasilNaoConfigurado:
        return False


def _segredos() -> list[str]:
    """Todo valor que não pode sair daqui em texto nenhum."""
    fora = []
    for nome in ("APIBRASIL_TOKEN", "APIBRASIL_DEVICE_TOKEN",
                 *(op["credencial"] for op in CATALOGO.values())):
        v = (credenciais.ler(nome) or "").strip()
        if v:
            fora.append(v)
    return fora


def _sanitizar(texto: str) -> str:
    """Tira as credenciais de qualquer texto que saia deste módulo.

    Aqui os tokens vão em CABEÇALHO, e é justamente por isso que a limpeza
    precisa existir: biblioteca de HTTP ecoa cabeçalho em erro de conexão e em
    `repr` de request, e cabeçalho ecoado em log é credencial publicada — num
    repositório que é público.
    """
    if not texto:
        return texto
    for segredo in _segredos():
        texto = texto.replace(segredo, "***")
    return texto


def _ctx() -> ssl.SSLContext:
    """TLS pela raiz do certifi, nunca pelo armazém do Windows.

    Em serviço SISTEMA o armazém fica incompleto e o erro que aparece é
    "self-signed certificate in chain", que manda procurar proxy quando o que
    falta é raiz.
    """
    return _tls.contexto()


def _mensagem(payload) -> str:
    """A mensagem legível de uma resposta de erro, sem adivinhar formato.

    A APIBrasil não publica um envelope de erro único, então em vez de fixar
    uma chave o código procura as usuais e, não achando nenhuma, devolve o
    corpo truncado — que é pior de ler mas nunca é MENTIRA, ao contrário de
    uma chave escolhida a dedo que devolve vazio quando o formato muda.
    """
    if isinstance(payload, dict):
        for chave in ("message", "mensagem", "error", "erro", "detail",
                      "description", "msg"):
            v = payload.get(chave)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                interno = _mensagem(v)
                if interno and not interno.startswith("{"):
                    return interno
        # ENVELOPE. A APIBrasil embrulha o resultado (`{"response": {...}}`),
        # e uma recusa aninhada sairia sem texto se a busca parasse no topo --
        # recusa sem mensagem e pior que corpo truncado, porque quem le nao
        # tem o que investigar.
        for v in payload.values():
            if isinstance(v, dict):
                interno = _mensagem(v)
                if interno and not interno.startswith("{"):
                    return interno
    return str(payload)[:300]


#: Mensagens que falam da CONTA, não da placa. Elas vêm ANTES de qualquer
#: outra leitura porque a mais comum delas — "Plano ativo não encontrado" —
#: CONTÉM "não encontrado", e sem esta lista ela seria lida como "o Detran não
#: conhece esta placa".
#:
#: MEDIDO em 08/09/2026 com o Bearer no cofre e sem produto contratado:
#: HTTP 404 {"error":true,"message":"Plano ativo não encontrado."}
#:
#: A confusão não teria sintoma: uma carga de 1.446 placas gravaria todas como
#: desconhecidas do Detran — um "achado" falso e caro, porque desconhecida no
#: Detran é justamente o sinal de cadastro furado que se foi buscar. O painel
#: mostraria 1.446 problemas graves onde há uma assinatura a resolver.
_ERRO_DE_CONTA = (
    "plano", "assinatura", "subscription", "credito", "crédito", "saldo",
    "nao autorizado", "não autorizado", "unauthorized", "forbidden",
    "token", "limite excedido", "quota", "cota",
)


def _erro_de_conta(payload) -> bool:
    """A recusa é sobre a NOSSA conta, não sobre a placa perguntada."""
    texto = _mensagem(payload).lower()
    return any(m in texto for m in _ERRO_DE_CONTA)


def _vazio(payload) -> bool:
    """A resposta diz "não encontrei esta PLACA"?

    Regra por ENDPOINT, nunca genérica: a Smartec manda ausência com HTTP 400
    e a RasterJOR com HTTP 200 e mensagem no corpo. Aqui a decisão é pelo
    TEXTO da mensagem, porque é o que sobrevive à variação de status.

    E a ordem importa mais que a lista: erro de CONTA é conferido primeiro,
    senão "Plano ativo não encontrado" cai no "não encontrado" e vira ausência
    de placa. Ver `_ERRO_DE_CONTA`.
    """
    if _erro_de_conta(payload):
        return False
    texto = _mensagem(payload).lower()
    return any(m in texto for m in (
        "nao encontrado", "não encontrado", "not found", "nenhum registro",
        "sem retorno", "nao localizado", "não localizado", "no data"))


def chamar(produto: str, placa: str, *, exigir_confirmado: bool = True) -> dict:
    """Consulta UMA placa num produto do catálogo. Devolve o corpo decodificado.

    `exigir_confirmado` protege a carga em massa: produto de caminho inferido
    só é chamado por `sondar()`, que gasta uma consulta de propósito para
    descobrir se o caminho existe. Sem esse freio, uma carga de 1.977 placas
    contra um caminho errado gasta a cota inteira em 404.
    """
    op = CATALOGO.get(produto)
    if op is None:
        raise ApiBrasilErro(f"Produto desconhecido: {produto}")
    if exigir_confirmado and not op["confirmado"]:
        raise ApiBrasilRecusa(
            f"O caminho do produto '{produto}' ainda não foi confirmado "
            f"contra a API real. Rode a sonda antes da carga.")

    placa = (placa or "").strip().upper().replace("-", "").replace(" ", "")
    if not placa:
        raise ApiBrasilRecusa("Placa vazia.")

    cabecalhos = {
        **CABECALHOS,
        "Authorization": f"Bearer {_bearer()}",
        "DeviceToken": _device(produto),
    }
    url = f"{BASE}{op['path']}"
    dados = _json.dumps({"placa": placa}).encode("utf-8")
    req = urllib.request.Request(url, data=dados, headers=cabecalhos,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx()) as r:
            bruto = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        texto = ""
        try:
            texto = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        try:
            payload = _json.loads(texto) if texto else None
        except ValueError:
            payload = None
        if payload is not None:
            if _vazio(payload):
                raise ApiBrasilSemDado(
                    f"O Detran não conhece a placa {placa}.") from None
            raise ApiBrasilRecusa(_sanitizar(_mensagem(payload))) from None
        # Sem corpo legível o status é tudo que se sabe — e dizê-lo é melhor
        # que inventar uma causa.
        raise ApiBrasilErro(
            f"HTTP {exc.code} da APIBrasil em {produto}") from None
    except urllib.error.URLError as exc:
        raise ApiBrasilErro(
            f"Não foi possível falar com a APIBrasil: "
            f"{_sanitizar(str(exc.reason))}") from None
    except TimeoutError:
        raise ApiBrasilErro(
            f"A APIBrasil não respondeu em {TIMEOUT}s.") from None

    try:
        payload = _json.loads(bruto) if bruto.strip() else {}
    except ValueError:
        raise ApiBrasilErro(
            "A APIBrasil respondeu algo que não é JSON.") from None

    # HTTP 200 com "não encontrei" no corpo. Ler o CORPO, não o status.
    if _vazio(payload):
        raise ApiBrasilSemDado(f"O Detran não conhece a placa {placa}.")
    return payload if isinstance(payload, dict) else {"resposta": payload}


def consultar(produto: str, placa: str, *,
              exigir_confirmado: bool = True) -> dict:
    """`chamar` com o relógio junto — é o que a coleta grava no livro-caixa.

    Devolve sempre um dicionário com o mesmo formato, inclusive na falha:
    `{ok, payload, erro, ms, sem_dado}`. Coleta que precisa distinguir "não
    consultei" de "consultei e não achou" não pode receber exceção nuns casos
    e valor noutros.
    """
    inicio = time.monotonic()
    fora = {"ok": False, "payload": None, "erro": None, "sem_dado": False}
    try:
        fora["payload"] = chamar(produto, placa,
                                 exigir_confirmado=exigir_confirmado)
        fora["ok"] = True
    except ApiBrasilSemDado as exc:
        fora["sem_dado"] = True
        fora["erro"] = _sanitizar(str(exc))
    except ApiBrasilErro as exc:
        fora["erro"] = _sanitizar(str(exc))
    except Exception as exc:  # noqa: BLE001
        # Log leva o TIPO da exceção, nunca o texto cru de uma exceção de
        # integração — é onde cabeçalho e URL vazam.
        log.warning("apibrasil %s: %s", produto, type(exc).__name__)
        fora["erro"] = f"falha inesperada ({type(exc).__name__})"
    fora["ms"] = int((time.monotonic() - inicio) * 1000)
    return fora


def sondar(placa: str) -> dict:
    """Gasta UMA consulta por produto para descobrir o que a conta responde.

    É o instrumento que substitui adivinhação por medição, e existe por três
    perguntas que nenhuma documentação respondeu:

      · o caminho do produto existe? (três dos quatro foram inferidos);
      · a conta contratou o produto? (404 e 403 dizem coisas diferentes);
      · QUE CAMPOS o corpo traz? A documentação diz "e muito mais", e é sobre
        esse "muito mais" que o cadastro vai ser escrito.

    Devolve o corpo REAL de cada produto. Quem escreve o de-para lê daqui — e
    nunca de exemplo de blog, porque dublê montado a partir de suposição testa
    a suposição.
    """
    fora: dict[str, dict] = {}
    for produto in PRODUTOS:
        r = consultar(produto, placa, exigir_confirmado=False)
        chaves = sorted(r["payload"].keys()) if isinstance(r["payload"], dict) else []
        fora[produto] = {**r, "chaves_do_topo": chaves,
                         "confirmado_no_catalogo": CATALOGO[produto]["confirmado"]}
    return fora
