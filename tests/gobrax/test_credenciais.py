"""Cofre local de credenciais de integração.

O que este teste protege é uma coisa só: o segredo entra e não volta. Um token
que vaza no payload da tela, no log ou numa mensagem de erro está tão exposto
quanto um token colado numa conversa.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from api import credenciais as cred


@pytest.fixture
def cofre(tmp_path, monkeypatch):
    p = tmp_path / "credenciais.json"
    monkeypatch.setattr(cred, "CAMINHO", p)
    monkeypatch.delenv("GOBRAX_TOKEN", raising=False)
    return p


def test_cofre_vazio_diz_que_nao_esta_configurado(cofre):
    st = cred.status("GOBRAX_TOKEN")
    assert st["configurado"] is False
    assert st["mascarado"] is None
    assert st["origem"] is None


def test_grava_e_relata_sem_devolver_o_valor(cofre):
    cred.gravar("GOBRAX_TOKEN", "eyJhbGciOiJIUzI1NiJ9.PAYLOAD.assinatura-secreta")
    st = cred.status("GOBRAX_TOKEN")
    assert st["configurado"] is True
    assert st["origem"] == "cofre"
    assert "assinatura-secreta" not in json.dumps(st)
    assert "PAYLOAD" not in json.dumps(st)


def test_mascara_mostra_so_as_pontas(cofre):
    cred.gravar("GOBRAX_TOKEN", "abcdefghijklmnopqrstuvwxyz")
    assert cred.status("GOBRAX_TOKEN")["mascarado"] == "abcd…wxyz"


def test_token_curto_demais_nao_e_aceito(cofre):
    """Valor curto é engano de colagem, não credencial."""
    with pytest.raises(ValueError):
        cred.gravar("GOBRAX_TOKEN", "abc")


def test_valor_vazio_apaga_a_credencial(cofre):
    cred.gravar("GOBRAX_TOKEN", "abcdefghijklmnopqrstuvwxyz")
    cred.gravar("GOBRAX_TOKEN", "")
    assert cred.status("GOBRAX_TOKEN")["configurado"] is False


def test_ler_devolve_o_valor_para_quem_precisa_chamar_a_api(cofre):
    cred.gravar("GOBRAX_TOKEN", "abcdefghijklmnopqrstuvwxyz")
    assert cred.ler("GOBRAX_TOKEN") == "abcdefghijklmnopqrstuvwxyz"


def test_cofre_vence_a_variavel_de_ambiente(cofre, monkeypatch):
    """O que o usuário acabou de configurar na tela tem de valer — senão ele
    salva e nada acontece."""
    monkeypatch.setenv("GOBRAX_TOKEN", "valor-do-env-com-tamanho-bom")
    cred.gravar("GOBRAX_TOKEN", "valor-do-cofre-com-tamanho-bom")
    assert cred.ler("GOBRAX_TOKEN") == "valor-do-cofre-com-tamanho-bom"
    assert cred.status("GOBRAX_TOKEN")["origem"] == "cofre"


def test_sem_cofre_cai_na_variavel_de_ambiente(cofre, monkeypatch):
    monkeypatch.setenv("GOBRAX_TOKEN", "valor-do-env-com-tamanho-bom")
    assert cred.ler("GOBRAX_TOKEN") == "valor-do-env-com-tamanho-bom"
    assert cred.status("GOBRAX_TOKEN")["origem"] == "ambiente"


def test_arquivo_nasce_sem_permissao_para_outros(cofre):
    cred.gravar("GOBRAX_TOKEN", "abcdefghijklmnopqrstuvwxyz")
    modo = stat.S_IMODE(os.stat(cofre).st_mode)
    assert modo & (stat.S_IRWXG | stat.S_IRWXO) == 0, oct(modo)


def test_arquivo_corrompido_nao_derruba_a_aplicacao(cofre):
    cofre.write_text("{ isto não é json", encoding="utf-8")
    assert cred.status("GOBRAX_TOKEN")["configurado"] is False
    assert cred.ler("GOBRAX_TOKEN") is None
