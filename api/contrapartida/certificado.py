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


def _variantes_de_senha(senha: str) -> list:
    """(bytes a tentar, aviso quando NÃO for a original, senha em texto).

    A senha certa pode falhar por detalhe invisível: espaço/quebra colada ao
    copiar do e-mail ou WhatsApp, ou acento em codificação antiga (latin-1).
    Tentar as variantes custa nada, e AVISAR qual funcionou ensina o que
    aconteceu — em vez do "senha incorreta" que faz digitar dez vezes.
    """
    orig = senha or ""
    out = [(orig.encode("utf-8"), None, orig)]
    if orig != orig.strip():
        out.append((orig.strip().encode("utf-8"),
                    "A senha veio com espaço ou quebra de linha colada "
                    "(acontece ao copiar do e-mail/WhatsApp) — abriu depois "
                    "de removê-los.", orig.strip()))
    try:
        latin = orig.encode("latin-1")
        if latin != orig.encode("utf-8"):
            out.append((latin, "A senha tem caractere acentuado e o "
                        "certificado foi gerado com codificação antiga — "
                        "abriu na codificação latin-1.", orig))
    except UnicodeEncodeError:
        pass
    if orig:
        out.append((b"", "O arquivo não tem senha — abriu com a senha em "
                    "branco.", ""))
    return out


def senha_que_abre(bruto: bytes, senha: str) -> str | None:
    """A senha (em texto) que de fato ABRE o arquivo, para o COFRE.

    Existe separada de `ler()` de propósito: os metadados que a tela mostra
    não podem carregar segredo (há guard cobrando isso). Quem grava a senha
    chama aqui — gravar a DIGITADA quando quem abriu foi a variante sem o
    espaço colado faria a transmissão falhar meses depois, longe da causa.
    """
    from cryptography.hazmat.primitives.serialization import pkcs12
    for tent, _aviso, texto in _variantes_de_senha(senha):
        try:
            pkcs12.load_key_and_certificates(bruto, tent)
            return texto
        except Exception:  # noqa: BLE001
            continue
    return None


def ler(bruto: bytes, senha: str) -> dict:
    """Abre o .pfx e devolve titular, CNPJ e validade. NUNCA devolve a senha
    nem a chave privada — só os metadados que a tela precisa mostrar."""
    from cryptography.hazmat.primitives.serialization import pkcs12

    if not bruto:
        raise CertificadoInvalido("Arquivo vazio.")
    if bruto[:1] != b"\x30":
        # PKCS#12 e DER e DER comeca com SEQUENCE (0x30). Um arquivo que nem
        # comeca assim nao e p12 nenhum — e provavelmente o .cer/.pem publico
        # que a AC manda JUNTO do certificado, ou um zip. Dizer ISSO poupa a
        # pessoa de re-digitar a senha dez vezes.
        raise CertificadoInvalido(
            "Este arquivo não é um .pfx/.p12: o formato não confere. "
            "Confira se não é o arquivo .cer/.pem público (que a AC manda "
            "junto) ou um .zip por abrir — o certificado A1 é o arquivo "
            "que EXIGE senha.")

    tentativas = _variantes_de_senha(senha)

    cert = None
    aviso_senha: str | None = None
    ultimo: Exception | None = None
    for tent, aviso, _txt in tentativas:
        try:
            _chave, cert, _extras = pkcs12.load_key_and_certificates(bruto, tent)
            aviso_senha = aviso
            break
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
    if cert is None and ultimo is not None:
        # a mensagem da biblioteca nao distingue senha errada de arquivo
        # corrompido; dizer as hipoteses REAIS e mais util que repassar o erro
        log.warning("pfx nao abriu: %s", type(ultimo).__name__)
        raise CertificadoInvalido(
            "Não foi possível abrir o certificado: a senha não confere "
            "(tentei também sem espaços nas pontas e em codificação antiga). "
            "Confira se a senha é a do ARQUIVO A1 — a AC costuma emitir uma "
            "senha de instalação e outra de revogação, e não são a mesma.") \
            from None
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
        "aviso_senha": aviso_senha,
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
