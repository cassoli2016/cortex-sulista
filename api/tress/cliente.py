# -*- coding: utf-8 -*-
"""Cliente do webservice da 3S Tecnologia (SOAP/ASP.NET, `data_export.asmx`).

QUATRO COISAS QUE ESTE FORNECEDOR FAZ DIFERENTE (WSDL lido em 03/09/2026,
72 operações publicadas):

1. **Login e senha vão no CORPO de cada requisição**, como na RasterIntegra.
   Por isso o `_sanitizar` varre o corpo de qualquer erro antes de ele virar
   exceção: a lição da Z-API (a URL era a credencial) vale aqui para o XML.

2. **O XML precisa de ESCAPE.** A senha entra como texto dentro de uma tag, e
   um `&` cru quebra o documento inteiro — o servidor responde 400 e a pessoa
   procura o erro na credencial. Nada é interpolado sem `escape()`.

3. **O resultado vem ESCAPADO DENTRO do resultado.** A resposta é um XML SOAP
   cujo `<...Result>` contém outro XML inteiro em entidades HTML
   (`&lt;Veiculo&gt;`). Sem o `unescape` no meio, o corpo parece texto solto e
   nenhum parser acha nada.

4. **Erro chega como TEXTO no lugar do resultado**, com HTTP 200 e sem código:
   `<ValidaLoginResult>Erro: Usuário ou senha inválidos</ValidaLoginResult>`.
   Quem decide se deu certo é o CONTEÚDO, nunca o status HTTP.

A credencial é EXCLUSIVA do CÓRTEX (TRESS_* no cofre). A senha da 3S tem 6
caracteres, abaixo do mínimo de 8 que a casa exige por padrão — está na lista
de exceções de `credenciais.MINIMO_POR_CREDENCIAL`, porque o tamanho da senha
quem decide é quem a emite.
"""
from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request
from xml.sax.saxutils import escape as _escape

from api import tls as _tls
from api.credenciais import ler as _cred_ler

log = logging.getLogger("cortex.tress")

TIMEOUT = 180
NAMESPACE = "http://servicos.3stecnologia.com.br/data_export"
URL_PADRAO = "https://www.3stecnologia.eti.br/data_export/data_export.asmx"

#: A 3S devolve o erro em texto, sem código. Estes são os começos conhecidos.
_ERRO = re.compile(r"^\s*(erro|error)\b", re.I)


class TressNaoConfigurado(RuntimeError):
    """Sem credencial não é falha: é instalação incompleta."""


class TressIndisponivel(RuntimeError):
    """O fornecedor não respondeu, ou respondeu recusando."""


def _cred(nome: str) -> str:
    return (_cred_ler(nome) or "").strip()


def configurado() -> bool:
    return bool(_cred("TRESS_LOGIN") and _cred("TRESS_SENHA"))


def base_url() -> str:
    return (_cred("TRESS_API_BASE_URL") or URL_PADRAO).strip().rstrip("/")


def _sanitizar(texto: str) -> str:
    """Tira a credencial de qualquer texto que vá para log ou exceção."""
    fora = str(texto or "")
    for nome in ("TRESS_LOGIN", "TRESS_SENHA", "TRESS_TOKEN"):
        v = _cred(nome)
        if v and len(v) >= 3:
            fora = fora.replace(v, "***")
    # e o XML da requisição, caso ele volte no corpo do erro
    fora = re.sub(r"<(Usuario|Senha)>.*?</\1>", r"<\1>***</\1>", fora, flags=re.S)
    return fora


def chamar(operacao: str, **parametros) -> str:
    """Uma chamada SOAP. Devolve o CONTEÚDO do `<...Result>`, já desescapado.

    Levanta `TressIndisponivel` quando o fornecedor recusa — inclusive nos
    casos em que ele responde HTTP 200 com a palavra "Erro" no lugar do
    resultado, que é o normal desta API.
    """
    if not configurado():
        raise TressNaoConfigurado(
            "faltam TRESS_LOGIN e TRESS_SENHA — cadastrar em Gestão › "
            "Integrações › 3S (credencial exclusiva do CÓRTEX, nunca a do ERP)")

    campos = [("Usuario", _cred("TRESS_LOGIN")), ("Senha", _cred("TRESS_SENHA"))]
    campos += [(k, v) for k, v in parametros.items()]
    corpo = "".join("<%s>%s</%s>" % (k, _escape(str(v)), k) for k, v in campos)
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><%s xmlns="%s">%s</%s></soap:Body></soap:Envelope>'
        % (operacao, NAMESPACE, corpo, operacao))

    req = urllib.request.Request(
        base_url(), data=envelope.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": '"%s/%s"' % (NAMESPACE, operacao),
                 "User-Agent": "CORTEX-Sulista/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT,
                                    context=_tls.contexto()) as resp:
            bruto = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        corpo_erro = exc.read()[:300].decode("utf-8", "replace")
        raise TressIndisponivel(
            "HTTP %s em %s: %s" % (exc.code, operacao,
                                   _sanitizar(corpo_erro))) from None
    except Exception as exc:  # noqa: BLE001
        # SÓ o nome da classe: str(exc) de urllib carrega a URL.
        raise TressIndisponivel(
            "Não foi possível falar com a 3S (%s)." % type(exc).__name__) from None

    achado = re.search(r"<%sResult>(.*?)</%sResult>" % (operacao, operacao),
                       bruto, re.S)
    if not achado:
        falha = re.search(r"<faultstring>(.*?)</faultstring>", bruto, re.S)
        raise TressIndisponivel(
            "a 3S respondeu sem o resultado de %s%s" % (
                operacao,
                (": " + _sanitizar(falha.group(1))[:160]) if falha else ""))

    resultado = html.unescape(achado.group(1)).strip()
    # ERRO CHEGA COMO TEXTO, com HTTP 200. Quem decide é o conteúdo.
    if _ERRO.match(resultado) and len(resultado) < 300:
        raise TressIndisponivel("%s: %s" % (operacao, _sanitizar(resultado)))
    return resultado


def registros(xml: str) -> list[dict]:
    """As linhas de um resultado, sem depender do nome da tabela.

    A 3S embrulha cada operação num nome próprio (`<tbVeiculo>`,
    `<tbUltimaPosicao>`…). Casar por `tb\\w+` em vez de fixar o nome poupa uma
    constante por operação e não erra quando o fornecedor renomeia — o que já
    aconteceu com outros deste ramo.
    """
    fora = []
    for bloco in re.findall(r"<(tb\w+)>(.*?)</\1>", xml, re.S):
        campos = dict(re.findall(r"<(\w+)>(.*?)</\1>", bloco[1], re.S))
        fora.append({k: (v or "").strip() for k, v in campos.items()})
    return fora


def testar() -> dict:
    """Diagnóstico para a Saúde do Servidor. Nunca levanta."""
    if not configurado():
        return {"ok": False, "estado": "info",
                "mensagem": "sem credencial — instalação incompleta"}
    try:
        chamar("ValidaLogin")
        return {"ok": True, "estado": "ok", "mensagem": "credencial aceita"}
    except TressIndisponivel as exc:
        return {"ok": False, "estado": "erro", "mensagem": str(exc)[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "estado": "erro",
                "mensagem": "falha inesperada (%s)" % type(exc).__name__}
