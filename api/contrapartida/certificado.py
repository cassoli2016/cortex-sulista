# api/contrapartida/certificado.py
"""Leitura e validação do arquivo .pfx do agregado.

POR QUE VALIDAR NO CADASTRO, E NÃO NA TRANSMISSÃO
=================================================
Senha errada, arquivo trocado ou certificado vencido descobertos na hora de
transmitir viram rejeição DOCUMENTO A DOCUMENTO — com ~3 mil CT-e por mês, é o
tipo de erro que para a operação e some no meio de um lote.

Aqui o .pfx é ABERTO com a senha no momento do cadastro. Se abrir, dá para ler
do próprio certificado quem é o titular e até quando vale — dado que não
precisa ser digitado e, por isso, não pode ser digitado errado.

E há uma checagem que só o arquivo responde: se o CNPJ dentro do certificado é
mesmo o do agregado. Certificado do agregado errado assina o documento errado,
e isso não aparece em conferência nenhuma depois.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

log = logging.getLogger("cortex.contrapartida.certificado")

# 5 MB cobre com folga qualquer .pfx (os reais tem dezenas de KB); serve para
# recusar pelo header antes de materializar o corpo em memoria.
MAX_BYTES = 5 * 1024 * 1024


class CertificadoInvalido(ValueError):
    """Arquivo nao abre, senha errada, ou nao e um PKCS#12."""


def _so_digitos(t: str) -> str:
    return re.sub(r"[^0-9]", "", t or "")


def ler(bruto: bytes, senha: str) -> dict:
    """Abre o .pfx e devolve titular, CNPJ e validade. NUNCA devolve a senha
    nem a chave privada — só os metadados que a tela precisa mostrar."""
    from cryptography.hazmat.primitives.serialization import pkcs12

    if not bruto:
        raise CertificadoInvalido("Arquivo vazio.")
    try:
        _chave, cert, _extras = pkcs12.load_key_and_certificates(
            bruto, (senha or "").encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        # a mensagem da biblioteca nao distingue senha errada de arquivo
        # corrompido; dizer as duas hipoteses e mais util que repassar o erro
        log.warning("pfx nao abriu: %s", type(exc).__name__)
        raise CertificadoInvalido(
            "Não foi possível abrir o certificado: senha incorreta ou arquivo "
            "que não é um .pfx/.p12 válido.") from None
    if cert is None:
        raise CertificadoInvalido("O arquivo não contém certificado.")

    titular = ""
    for atrib in cert.subject:
        if atrib.oid.dotted_string == "2.5.4.3":       # commonName
            titular = str(atrib.value)
            break
    # e-CNPJ traz o CNPJ no proprio commonName ("RAZAO SOCIAL:12345678000199")
    doc = ""
    m = re.search(r"(\d{14})\b", titular)
    if m:
        doc = m.group(1)

    fim = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    if fim.tzinfo is None:
        fim = fim.replace(tzinfo=timezone.utc)
    ini = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before
    if ini.tzinfo is None:
        ini = ini.replace(tzinfo=timezone.utc)
    agora = datetime.now(timezone.utc)

    return {
        "titular": titular.split(":")[0].strip() or titular,
        "cnpj": doc,
        "valida_de": ini.date().isoformat(),
        "valida_ate": fim.date().isoformat(),
        "vencido": fim < agora,
        "dias": (fim.date() - agora.date()).days,
    }


def conferir_titularidade(lido: dict, cnpj_agregado: str) -> str | None:
    """Devolve o AVISO quando o certificado nao e do agregado, ou None.

    Nao levanta excecao: ha e-CNPJ de matriz assinando por filial, e ha
    certificado cujo commonName nao carrega o numero. Bloquear todos os casos
    impediria cadastro legitimo; deixar passar calado assinaria o documento
    errado sem ninguem ver. Entao: grava e AVISA.
    """
    doc = _so_digitos(lido.get("cnpj", ""))
    alvo = _so_digitos(cnpj_agregado)
    if not doc:
        return ("O certificado não traz o CNPJ no nome do titular — não deu "
                "para conferir se ele é mesmo deste agregado.")
    if doc != alvo:
        return (f"O CNPJ dentro do certificado ({doc}) é diferente do cadastro "
                f"do agregado ({alvo}). Se não for matriz assinando por filial, "
                "o certificado está trocado — e certificado trocado assina o "
                "documento errado sem aparecer em conferência nenhuma depois.")
    return None
