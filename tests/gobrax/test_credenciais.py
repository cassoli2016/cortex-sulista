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


# ------------------------------------------------- panorama por fornecedor
#
# A tela deixou de ser uma lista plana de 22 campos: o que ela desenha é um
# cartão por fornecedor, com o estado calculado aqui.


@pytest.fixture
def cofre_limpo(tmp_path, monkeypatch):
    p = tmp_path / "credenciais.json"
    monkeypatch.setattr(cred, "CAMINHO", p)
    for nome in cred.CAMPOS:
        monkeypatch.delenv(nome, raising=False)
    return p


def _svc(chave):
    return next(s for s in cred.panorama() if s["chave"] == chave)


def test_todo_campo_pertence_a_um_servico(cofre_limpo):
    """Campo que não entra em nenhum cartão fica invisível na tela e ninguém
    descobre por que a integração não liga."""
    no_catalogo = {c for s in cred.SERVICOS
                   for c in [x for m in s["modos"] for x in m["campos"]] + s["ajustes"]}
    assert no_catalogo == set(cred.CAMPOS)


def test_sem_nada_configurado_o_servico_esta_desligado(cofre_limpo):
    s = _svc("prolog")
    assert s["estado"] == "desligada"
    assert s["modo_ativo"] is None


def test_um_modo_completo_basta_para_ligar(cofre_limpo):
    """A Prolog aceita token OU Basic OU OAuth2 — cobrar os onze campos era o
    que fazia a tela inteira parecer desconfigurada."""
    cred.gravar("PROLOG_TOKEN", "token-da-prolog-1234")
    cred.gravar("PROLOG_FILIAIS", "12,15")
    s = _svc("prolog")
    assert s["estado"] == "ativa"
    assert s["modo_ativo"] == "token"
    assert s["falta"] == []


def test_credencial_sem_o_ajuste_obrigatorio_fica_incompleta(cofre_limpo):
    """Token da Prolog sem filial lista pneu nenhum: é 'incompleta', não
    'ativa'."""
    cred.gravar("PROLOG_TOKEN", "token-da-prolog-1234")
    s = _svc("prolog")
    assert s["estado"] == "incompleta"
    assert s["falta"] == ["filiais"]


def test_campo_opcional_nao_conta_como_falta(cofre_limpo):
    """MONKEY_TOKEN_URL tem padrão no cliente — exigi-lo faria a tela dizer
    que falta o que não falta."""
    cred.gravar("MONKEY_CLIENT_ID", "id-do-cliente-monkey")
    cred.gravar("MONKEY_CLIENT_SECRET", "segredo-do-cliente-monkey")
    cred.gravar("MONKEY_SELLER_ID", "42")
    s = _svc("monkey")
    assert s["modo_ativo"] == "oauth"
    assert s["estado"] == "ativa"


def test_modo_ativo_bate_com_o_que_o_cliente_usa(cofre_limpo):
    """A ORDEM dos modos no catálogo é a mesma prioridade de `modo_auth()`.
    Se divergir, a tela diz que autentica de um jeito e o código usa outro."""
    from api.monkey import cliente as mk
    from api.pneus import cliente as pl

    cred.gravar("PROLOG_USUARIO", "usuario")
    cred.gravar("PROLOG_SENHA", "senha-da-prolog")
    assert _svc("prolog")["modo_ativo"] == pl.modo_auth() == "basic"

    # token entra depois e passa na frente — nos dois lugares
    cred.gravar("PROLOG_TOKEN", "token-da-prolog-1234")
    assert _svc("prolog")["modo_ativo"] == pl.modo_auth() == "token"

    cred.gravar("MONKEY_CLIENT_ID", "id-do-cliente-monkey")
    cred.gravar("MONKEY_CLIENT_SECRET", "segredo-do-cliente-monkey")
    assert _svc("monkey")["modo_ativo"] == mk.modo_auth() == "oauth"
    cred.gravar("MONKEY_TOKEN", "token-estatico-da-monkey")
    assert _svc("monkey")["modo_ativo"] == mk.modo_auth() == "token"


def test_nenhum_segredo_aparece_no_panorama(cofre_limpo):
    """A regra do módulo, agora valendo para o payload inteiro da tela."""
    # valor ÚNICO e sem prefixo comum: "…monkey_token" é começo de
    # "…monkey_token_url", e um `in` acusaria vazamento que não existe
    segredos = {}
    for i, nome in enumerate(cred.CAMPOS):
        valor = f"conteudo-{i:02d}-do-cofre-fim"
        cred.gravar(nome, valor)
        segredos[nome] = valor
    bruto = json.dumps(cred.panorama(), ensure_ascii=False)
    for nome, valor in segredos.items():
        if cred.e_segredo(nome):
            assert valor not in bruto, nome
        else:
            # configuração VOLTA de propósito: é o que dá para conferir
            assert valor in bruto, nome


def test_campo_fora_do_catalogo_e_tratado_como_segredo(cofre_limpo):
    """Credencial nova que esquecerem de descrever não pode vazar por omissão."""
    assert cred.e_segredo("CREDENCIAL_QUE_NAO_EXISTE") is True
