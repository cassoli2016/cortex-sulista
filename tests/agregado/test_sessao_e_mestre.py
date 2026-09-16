# -*- coding: utf-8 -*-
"""A sessão do agregado e o acesso mestre.

O QUE ESTE ARQUIVO PROTEGE, em uma frase: que um token abra exatamente um app,
e que o acesso de conferência da casa seja curto, contado e visível.

O caso do `tipo` no token não é hipotético: os três apps da casa assinam com o
MESMO segredo (`auth.SECRET`). Sem a marca, um cookie de motorista — copiado de
um aparelho para o outro, ou reaproveitado por engano — abriria o extrato
financeiro de um fornecedor.
"""
from __future__ import annotations

import jwt
import pytest

from api import auth, pglocal
from api.agregado import mestre as amestre
from api.agregado import sessao as ases
from tests.agregado.conftest import cadastrar

COD = "12345678000190"
FONE = "5541999990001"


def _sessao(esq, **kw) -> tuple[int, str]:
    ident = cadastrar(esq, COD, FONE, **kw)
    sid = ases.abrir(COD, aparelho="ap1", esquema=esq)
    return ident, ases.emitir(ident, sid)


def test_a_sessao_carrega_o_dono_e_o_documento_nao_sai_no_token(esq):
    ident, token = _sessao(esq)
    claims = jwt.decode(token, auth.SECRET, algorithms=["HS256"])
    assert claims["tipo"] == ases.TIPO == "agregado"
    assert claims["sub"] == str(ident) and COD not in str(claims)
    sess = ases.atual(token, esq)
    assert sess["proprietario_codigo"] == COD and sess["mestre"] is False


def test_token_do_app_do_motorista_nao_abre_o_app_do_agregado(esq):
    """Mesmo segredo, mesma forma, `sub` colidindo de propósito: o que separa
    os dois é o `tipo`, e é isso que este teste prova."""
    ident, _ = _sessao(esq)
    sid = pglocal.um("SELECT max(id) AS id FROM agr_sessoes", {}, esq)["id"]
    from api.motorista import sessao as msessao
    token_motorista = msessao.emitir(ident, int(sid))
    assert ases.atual(token_motorista, esq) is None
    # e o contrário também: o do agregado não vale lá
    assert msessao.atual(ases.emitir(ident, int(sid)), esq) is None


def test_desligar_derruba_a_sessao_na_requisicao_seguinte(esq):
    """O JWT diz "é meu e não venceu"; não diz "esta pessoa ainda pode
    entrar". Sem a conferência do vínculo, um desligado seguiria vendo o
    dinheiro dos veículos por 30 dias."""
    _, token = _sessao(esq)
    assert ases.atual(token, esq)
    pglocal.executar("UPDATE agr_vinculos SET ativo = false", {}, esq)
    assert ases.atual(token, esq) is None


def test_encerrar_derruba_o_aparelho_e_nao_os_outros(esq):
    ident = cadastrar(esq, COD, FONE)
    s1 = ases.abrir(COD, aparelho="ap1", esquema=esq)
    s2 = ases.abrir(COD, aparelho="ap2", esquema=esq)
    t1, t2 = ases.emitir(ident, s1), ases.emitir(ident, s2)
    ases.encerrar(s1, esq)
    assert ases.atual(t1, esq) is None and ases.atual(t2, esq)


def test_token_com_sub_de_outro_vinculo_e_recusado(esq):
    """Trocar o `sub` não acontece por acidente: a resposta é recusar, e não
    confiar no id que veio no token."""
    _, _ = _sessao(esq)
    outro = cadastrar(esq, "99988877766", "5541999990002", nome="Outro")
    sid = pglocal.um("SELECT max(id) AS id FROM agr_sessoes", {}, esq)["id"]
    assert ases.atual(ases.emitir(outro, int(sid)), esq) is None


# ─────────────────────────────── acesso mestre ───────────────────────────────

SEGREDO = "codigo-mestre-de-teste-1234"


@pytest.fixture
def com_segredo(monkeypatch):
    monkeypatch.setattr(amestre, "_segredo", lambda: SEGREDO)
    return SEGREDO


def test_sem_segredo_configurado_o_acesso_simplesmente_nao_existe(esq, monkeypatch):
    """**Não configurado não é falha, é instalação incompleta** — e a recusa é
    a MESMA de um código errado, senão a rota responde de graça se vale a pena
    continuar tentando."""
    monkeypatch.setattr(amestre, "_segredo", lambda: "")
    assert amestre.configurado() is False
    with pytest.raises(amestre.Recusa) as exc:
        amestre.conferir("qualquer-coisa", ip="1.1.1.1", esquema=esq)
    assert str(exc.value) == amestre.RECUSA


def test_segredo_curto_e_recusado_pelo_piso_de_tamanho(esq, monkeypatch):
    """O piso impede alguém de pôr "sulista2026" num acesso que abre o
    financeiro de 201 fornecedores. E é aplicado em `_segredo`, para não
    existir caminho no módulo em que um segredo curto valha por acidente.

    O cofre é dublado junto com o `.env`: sem isso o teste dependeria do que
    estiver configurado nesta máquina, e passaria (ou não) por acidente.
    """
    from api import credenciais
    monkeypatch.setattr(credenciais, "ler", lambda *a, **k: "")
    curto = "sulista2026"
    assert len(curto) < amestre.TAMANHO_MINIMO
    monkeypatch.setenv(amestre.CHAVE, curto)
    assert amestre.configurado() is False
    with pytest.raises(amestre.Recusa):
        amestre.conferir(curto, ip="7.7.7.7", esquema=esq)
    # e um segredo do tamanho certo passa a valer — o piso é o único motivo da
    # recusa acima, e não uma indisponibilidade qualquer
    monkeypatch.setenv(amestre.CHAVE, "x" * amestre.TAMANHO_MINIMO)
    assert amestre.configurado() is True


def test_o_teto_conta_so_o_que_errou_e_o_acerto_zera(esq, com_segredo):
    """O teto existe contra ADIVINHAÇÃO, e adivinhação produz ERRO. Contar
    acerto junto punia quem confere — foi defeito real do app do motorista, com
    seis conferências certas barradas na sétima."""
    for _ in range(amestre.MAX_TENTATIVAS_HORA + 2):
        amestre.conferir(SEGREDO, ip="9.9.9.9", esquema=esq)      # não levanta
    for _ in range(amestre.MAX_TENTATIVAS_HORA - 1):
        with pytest.raises(amestre.Recusa):
            amestre.conferir("errado", ip="9.9.9.9", esquema=esq)
    amestre.conferir(SEGREDO, ip="9.9.9.9", esquema=esq)          # o acerto zera
    with pytest.raises(amestre.Recusa):
        amestre.conferir("errado", ip="9.9.9.9", esquema=esq)
    amestre.conferir(SEGREDO, ip="9.9.9.9", esquema=esq)


def test_o_teto_estourado_barra_ate_o_codigo_certo(esq, com_segredo):
    for _ in range(amestre.MAX_TENTATIVAS_HORA):
        with pytest.raises(amestre.Recusa):
            amestre.conferir("errado", ip="8.8.8.8", esquema=esq)
    with pytest.raises(amestre.Recusa):
        amestre.conferir(SEGREDO, ip="8.8.8.8", esquema=esq)


def test_a_sessao_mestre_e_curta_marcada_e_no_escopo_do_dono(esq, com_segredo):
    """Ela lê exatamente o que aquele dono leria: mesmo escopo, mesmas funções.
    A marca serve à tarja, ao prazo e à trilha."""
    ident = cadastrar(esq, COD, FONE, nome="Transportes Fulano")
    r = amestre.abrir(ident, ip="1.1.1.1", esquema=esq)
    sess = ases.atual(r["token"], esq)
    assert sess["mestre"] is True
    assert sess["proprietario_codigo"] == COD
    claims = jwt.decode(r["token"], auth.SECRET, algorithms=["HS256"])
    horas = (claims["exp"] - claims["iat"]) / 3600
    assert abs(horas - amestre.TTL_HORAS) < 0.05
    assert horas < ases.TTL_DIAS * 24          # muito mais curta que a normal


def test_a_lista_do_mestre_nao_traz_documento_e_diz_o_total(esq, com_segredo):
    for i in range(3):
        cadastrar(esq, f"1112223334{i}", f"554199999000{i}", nome=f"Dono {i}")
    r = amestre.agregados(esquema=esq)
    assert r["total"] == 3 and r["mostrados"] == 3
    assert all(set(a) == {"id", "nome"} for a in r["agregados"])
    assert "1112223334" not in str(r)
    assert amestre.agregados("Dono 1", esquema=esq)["total"] == 1


def test_agregado_desligado_nao_abre_nem_para_o_mestre(esq, com_segredo):
    """Recusa diferente da do código, de propósito: quem chegou aqui já provou
    o segredo, e esconder o motivo faria tentar o mesmo botão para sempre."""
    ident = cadastrar(esq, COD, FONE, ativo=False)
    with pytest.raises(amestre.Recusa) as exc:
        amestre.abrir(ident, esquema=esq)
    assert str(exc.value) != amestre.RECUSA
