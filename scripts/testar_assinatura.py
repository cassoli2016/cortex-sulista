# scripts/testar_assinatura.py
"""Prova que o certificado do agregado SERVE PARA ASSINAR — sem emitir nada.

O que este teste responde
-------------------------
Abrir o .pfx prova que a senha esta certa. NAO prova que a chave assina: um
certificado pode estar sem a extensao de uso que a SEFAZ exige, ou vir sem a
chave privada (so a parte publica). Isso so aparece na hora de transmitir, e
ai o custo e rejeicao documento a documento.

Aqui a chave assina um digest de verdade e a assinatura e CONFERIDA contra a
chave publica do proprio certificado.

O que ele NAO responde, e e importante dizer
--------------------------------------------
Nao prova que a SEFAZ aceita. A aceitacao depende da canonicalizacao exata
(C14N 1.0), do schema 4.0 e do encadeamento ate uma AC da ICP-Brasil - e e
justamente por isso que a transmissao vai para um provedor certificado, e nao
para codigo nosso.

Uso:  uv run python scripts/testar_assinatura.py <CNPJ>
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import ExtensionOID  # noqa: E402

from api.contrapartida import cadastro  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: testar_assinatura.py <CNPJ>")
        return 2
    cnpj = "".join(c for c in sys.argv[1] if c.isdigit())
    reg = cadastro.mapa().get(cnpj)
    if not reg or not reg.get("certificado"):
        print(f"Nenhum certificado cadastrado para {cnpj}.")
        return 1
    senha = cadastro.ler_senha(cnpj)
    if not senha:
        print("Senha nao esta no cofre — recadastre o certificado.")
        return 1
    arq = cadastro.DIR_CERT / (reg["certificado"].get("arquivo") or "")
    if not arq.exists():
        print(f"Arquivo nao encontrado: {arq.name}")
        return 1

    chave, cert, cadeia = pkcs12.load_key_and_certificates(
        arq.read_bytes(), senha.encode("utf-8"))
    print("=" * 74)
    print("CERTIFICADO")
    print("=" * 74)
    print(f"  titular      : {cert.subject.rfc4514_string()[:70]}")
    print(f"  emissor (AC) : {cert.issuer.rfc4514_string()[:70]}")
    print(f"  serie        : {cert.serial_number:x}")
    print(f"  validade     : {cert.not_valid_after_utc.date()}")
    print(f"  cadeia junto : {len(cadeia or [])} certificado(s) intermediario(s)")

    if chave is None:
        print("\n  FALHA: o arquivo NAO contem a chave privada — so a parte")
        print("  publica. Com ele nao se assina nada. Peca o .pfx completo.")
        return 1
    print(f"  chave        : {type(chave).__name__}, "
          f"{getattr(chave, 'key_size', '?')} bits")

    # A SEFAZ exige a extensao de uso para assinatura digital. Certificado sem
    # ela abre normalmente e e recusado so na transmissao.
    try:
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        ok_uso = ku.digital_signature
        print(f"  uso p/ assinar: {'SIM' if ok_uso else 'NAO — a SEFAZ recusa'}")
    except Exception:  # noqa: BLE001
        print("  uso p/ assinar: extensao ausente (a SEFAZ pode recusar)")

    print()
    print("=" * 74)
    print("ASSINATURA")
    print("=" * 74)
    # bytes canonicos de exemplo: e sobre isto que o XMLDSig assina de verdade
    alvo = (b'<infCte Id="CTe00000000000000000000000000000000000000000000">'
            b"<teste>assinatura do Cortex</teste></infCte>")
    if not isinstance(chave, rsa.RSAPrivateKey):
        print("  Chave nao e RSA — fora do padrao ICP-Brasil para CT-e.")
        return 1
    assinatura = chave.sign(alvo, padding.PKCS1v15(), hashes.SHA256())
    print(f"  assinou      : {len(assinatura)} bytes (RSA PKCS#1 v1.5, SHA-256)")

    try:
        cert.public_key().verify(assinatura, alvo, padding.PKCS1v15(),
                                 hashes.SHA256())
        print("  conferencia  : OK — a assinatura bate com a chave publica")
        print("                 do proprio certificado")
    except Exception as exc:  # noqa: BLE001
        print(f"  conferencia  : FALHOU — {exc}")
        return 1

    # prova negativa: conteudo alterado tem de invalidar
    try:
        cert.public_key().verify(assinatura, alvo + b" ", padding.PKCS1v15(),
                                 hashes.SHA256())
        print("  ALERTA: assinatura validou conteudo ADULTERADO — algo errado.")
        return 1
    except Exception:  # noqa: BLE001
        print("  adulteracao  : rejeitada, como esperado")

    print()
    print("Este certificado assina. O que ainda NAO esta provado: aceitacao")
    print("pela SEFAZ, que depende da canonicalizacao C14N, do schema 4.0 e do")
    print("encadeamento ate a ICP-Brasil — e e por isso que a transmissao vai")
    print("para um provedor certificado, nao para codigo nosso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
