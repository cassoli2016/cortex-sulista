"""O contexto TLS da casa — com raízes de verdade.

O DEFEITO, MEDIDO EM 30/08/2026
===============================
`ssl.create_default_context()` neste servidor Windows carrega **45 CAs**. Não
são 45 escolhidas: é o que o armazém de raízes do Windows tinha em cache no
momento. O Windows preenche esse armazém **sob demanda**, quando um programa
gráfico encontra um certificado novo — e um serviço que roda como SISTEMA, sem
sessão interativa, pode nunca disparar essa atualização.

O sintoma não parece o que é. `api.tomtom.com` apresenta um certificado
LEGÍTIMO, emitido pela IdenTrust/HydrantID, e o Python recusa com:

    [SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain

"Certificado autoassinado" manda procurar proxy corporativo, firewall que
intercepta TLS, certificado vencido — tudo errado. O que aconteceu foi só a
RAIZ não estar no armazém, e aí o topo da cadeia (que é autoassinado, como toda
raiz) aparece como não confiável. Levei três diagnósticos até imprimir o
emissor e ver que o certificado era o verdadeiro.

E ISTO NÃO É UM PROBLEMA DA TOMTOM
==================================
Todo cliente HTTP do CÓRTEX — Gobrax, Z-API, Monkey, Prolog, RasterJOR, ANTT,
Ollama — sai por `urllib`. Os que funcionam hoje funcionam porque a raiz deles
CALHOU de estar entre as 45. O dia em que um fornecedor trocar de autoridade
certificadora, a integração cai com essa mensagem enganosa, e quem investigar
vai procurar no lugar errado.

`certifi` já estava instalado (vem com `requests`) e traz o conjunto do
Mozilla, com ~150 raízes, atualizado a cada versão. Preferi-lo ao armazém do
sistema troca "o que o Windows resolveu cachear" por uma lista explícita e
versionada.

FALLBACK, NÃO SUBSTITUIÇÃO CEGA: sem `certifi` instalado volta ao padrão do
sistema, que é o comportamento anterior. Uma dependência ausente não pode
derrubar toda chamada externa do sistema.
"""
from __future__ import annotations

import logging
import ssl

log = logging.getLogger(__name__)

_ctx: ssl.SSLContext | None = None


def contexto() -> ssl.SSLContext:
    """O contexto TLS para toda chamada externa. Memoizado — montar um
    contexto lê e parseia ~150 certificados, e isso não muda em execução."""
    global _ctx
    if _ctx is not None:
        return _ctx
    try:
        import certifi
        _ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception as exc:  # noqa: BLE001
        log.warning("certifi indisponível (%s) — usando as raízes do sistema; "
                    "fornecedor com CA fora do cache do Windows vai falhar "
                    "com 'self-signed certificate in certificate chain'",
                    type(exc).__name__)
        _ctx = ssl.create_default_context()
    return _ctx


def diagnostico() -> dict:
    """Quantas raízes cada armazém oferece. É o número que explica a falha.

    Vai para a Saúde: quando uma integração cair com erro de certificado, a
    primeira pergunta é "quantas raízes o processo enxerga?", e 45 contra 150
    responde na hora.
    """
    try:
        sistema = len(ssl.create_default_context().get_ca_certs())
    except Exception:  # noqa: BLE001
        sistema = None
    try:
        import certifi  # noqa: F401
        nosso = len(contexto().get_ca_certs())
        fonte = "certifi"
    except Exception:  # noqa: BLE001
        nosso, fonte = sistema, "sistema"
    return {"raizes": nosso, "fonte": fonte, "raizes_do_sistema": sistema}
