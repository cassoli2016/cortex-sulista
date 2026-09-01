# tests/contrapartida/test_certificado.py
"""Leitura do .pfx: validar no CADASTRO e nao na transmissao.

Senha errada descoberta na hora de transmitir vira rejeicao DOCUMENTO A
DOCUMENTO - com ~3 mil CT-e/mes, some no meio de um lote e para a operacao.
"""
from __future__ import annotations

import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from api.contrapartida.certificado import (CertificadoInvalido,
                                           conferir_titularidade, ler)


def _pfx(cn: str, dias: int = 200, senha: bytes = b"segredo") -> bytes:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    agora = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
         .public_key(k.public_key()).serial_number(x509.random_serial_number())
         # o vencido nasce com a janela inteira no passado: not_valid_after
         # anterior ao not_valid_before e recusado pela propria biblioteca
         .not_valid_before(agora + datetime.timedelta(days=min(dias, 0) - 1))
         .not_valid_after(agora + datetime.timedelta(days=dias))
         .sign(k, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(
        b"t", k, c, None, serialization.BestAvailableEncryption(senha))


def test_extrai_titular_cnpj_e_validade_do_proprio_arquivo():
    """Dado que sai do certificado nao precisa ser digitado - e por isso nao
    pode ser digitado errado."""
    d = ler(_pfx("ACME TRANSPORTES LTDA:12345678000199"), "segredo")
    assert d["titular"] == "ACME TRANSPORTES LTDA"
    assert d["cnpj"] == "12345678000199"
    assert not d["vencido"] and d["dias"] > 190


def test_senha_errada_falha_AGORA():
    with pytest.raises(CertificadoInvalido):
        ler(_pfx("X:12345678000199"), "errada")


def test_arquivo_que_nao_e_pfx():
    with pytest.raises(CertificadoInvalido):
        ler(b"isto nao e um pkcs12", "seja la qual for")


def test_arquivo_vazio():
    with pytest.raises(CertificadoInvalido):
        ler(b"", "x")


def test_certificado_vencido_e_detectado():
    d = ler(_pfx("X:12345678000199", dias=-5), "segredo")
    assert d["vencido"] and d["dias"] < 0


def test_certificado_do_agregado_ERRADO_gera_aviso():
    """Certificado trocado assina o documento errado, e isso nao aparece em
    conferencia nenhuma depois."""
    d = ler(_pfx("OUTRA EMPRESA:99999999000199"), "segredo")
    aviso = conferir_titularidade(d, "12345678000199")
    assert aviso and "diferente" in aviso


def test_certificado_certo_nao_gera_aviso():
    d = ler(_pfx("ACME:12345678000199"), "segredo")
    assert conferir_titularidade(d, "12.345.678/0001-99") is None


def test_sem_cnpj_no_titular_AVISA_em_vez_de_bloquear():
    """Ha e-CNPJ cujo commonName nao carrega o numero. Bloquear impediria
    cadastro legitimo; passar calado assinaria errado."""
    d = ler(_pfx("EMPRESA SEM NUMERO"), "segredo")
    aviso = conferir_titularidade(d, "12345678000199")
    assert aviso and "não deu para conferir" in aviso


def test_a_leitura_nao_devolve_chave_privada_nem_senha():
    d = ler(_pfx("X:12345678000199"), "segredo")
    # aviso_senha é TEXTO de diagnóstico (qual variante abriu), nunca a senha
    assert set(d) == {"aviso_senha", "titular", "cnpj", "valida_de",
                      "valida_ate", "vencido", "dias"}
    assert "segredo" not in str(d)


def test_senha_com_espaco_colado_abre_e_avisa():
    """Copiar a senha do e-mail/WhatsApp cola espaço ou quebra invisível —
    a variante limpa abre, o aviso ensina, e o COFRE recebe a que abriu."""
    from api.contrapartida.certificado import senha_que_abre
    pfx = _pfx("X:12345678000199")
    d = ler(pfx, "segredo \n")
    assert d["aviso_senha"] and "espa" in d["aviso_senha"]
    assert senha_que_abre(pfx, "segredo \n") == "segredo"
    assert ler(pfx, "segredo")["aviso_senha"] is None
    assert senha_que_abre(pfx, "segredo") == "segredo"


def test_arquivo_que_nem_e_der_tem_mensagem_propria():
    """O .cer/.pem público que a AC manda junto não pode virar 'senha
    incorreta' — a pessoa redigitaria a senha dez vezes."""
    import pytest as _pt
    with _pt.raises(CertificadoInvalido) as exc:
        ler(b"-----BEGIN CERTIFICATE-----", "x")
    assert ".cer" in str(exc.value)


def test_arquivo_truncado_e_dito_sem_culpar_a_senha():
    """Anexo cortado na transferência não é 'senha incorreta'."""
    import pytest as _pt
    inteiro = _pfx("X:12345678000199")
    with _pt.raises(CertificadoInvalido) as exc:
        ler(inteiro[: len(inteiro) // 2], "segredo")
    assert "INCOMPLETO" in str(exc.value)


def test_senha_errada_em_p12_moderno_diz_que_o_arquivo_esta_integro():
    """PBES2 visível sem senha: o diagnóstico afasta a dúvida do arquivo."""
    import pytest as _pt
    with _pt.raises(CertificadoInvalido) as exc:
        ler(_pfx("X:12345678000199"), "senha-que-nao-e")
    assert "moderno e íntegro" in str(exc.value)
