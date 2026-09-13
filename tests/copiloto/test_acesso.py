"""O Copiloto responde só com o que a pessoa pode abrir (13/09/2026).

Pedido de quem opera, depois dos acessos por usuário: "o copiloto precisa
restringir". Até aqui o snapshot era UM para todo mundo: quem tinha a tela do
Copiloto perguntava sobre a DRE, a folha ou o caixa sem ter nenhuma dessas
telas — e tirar uma tela de alguém não tirava o número dela do chat.

Três regras, conferidas aqui sem banco:
1. toda fonte do snapshot DECLARA as telas que a enxergam (sem padrão: fonte
   nova sem dono reprova a suíte);
2. o retrato continua um só, montado uma vez (custa ~12 consultas no ERP), e
   é CORTADO por pessoa: admin vê tudo, sem sessão não vê nada, aba tirada
   tira a fonte dela, e login de cliente só vê o que é público;
3. o prompt e o ⓘ de procedência dizem só as telas e as fontes da pessoa.
"""
from __future__ import annotations

import inspect
import json

import pytest

from api import acessos, auth, copiloto

COMUM = {"admin": False, "telas": ["fluxo"], "abas_tiradas": [], "cliente_cnpj_raiz": ""}
ADMIN = {"admin": True, "telas": [], "abas_tiradas": [], "cliente_cnpj_raiz": ""}


# ──────────────────────────────────────────────────── quem vê cada fonte ───

def test_toda_fonte_declara_quem_a_ve():
    assert set(copiloto.FONTE_TELAS) == set(copiloto._FONTES_ROTULO)
    validas = set(auth.TELAS) | set(auth.TELAS_TODO_LOGADO)
    for f, (telas, abas) in copiloto.FONTE_TELAS.items():
        assert telas, f"{f}: fonte sem tela nenhuma"
        assert set(telas) <= validas, (f, set(telas) - validas)
        assert set(abas) <= set(acessos.ABAS), (f, set(abas) - set(acessos.ABAS))
        for a in abas:
            assert acessos.ABAS[a]["tela"] in telas, f"{f}: a aba {a} é de outra tela"


def test_admin_ve_todas_e_sem_sessao_nada():
    assert copiloto.fontes_visiveis(ADMIN) == set(copiloto._FONTES_ROTULO)
    assert copiloto.fontes_visiveis(None) == set()


def test_quem_so_tem_o_fluxo_ve_o_caixa_e_o_publico():
    ver = copiloto.fontes_visiveis(COMUM)
    assert {"financeiro_caixa", "radar_mercado", "calendario", "aplicativos"} <= ver
    assert not ({"onde_atacar", "dre_excluidos", "people", "ferias_custo",
                 "portal_cliente", "projecao_caixa"} & ver)


def test_aba_tirada_tira_a_fonte_dela():
    s = {**COMUM, "telas": ["dre"]}
    assert {"onde_atacar", "dre_excluidos"} <= copiloto.fontes_visiveis(s)
    s["abas_tiradas"] = ["dre.atk"]
    ver = copiloto.fontes_visiveis(s)
    assert "onde_atacar" not in ver and "dre_excluidos" in ver


def test_login_de_cliente_so_ve_o_publico():
    """O portal do cliente SOMA as contas de todos os clientes com login; um
    cliente com a tela do Copiloto veria a operação dos outros."""
    s = {**COMUM, "telas": ["cliop", "cop", "fluxo"], "cliente_cnpj_raiz": "12345678"}
    ver = copiloto.fontes_visiveis(s)
    publicas = {f for f, (t, _) in copiloto.FONTE_TELAS.items()
                if set(t) & set(auth.TELAS_TODO_LOGADO)}
    assert "portal_cliente" not in ver and "financeiro_caixa" not in ver
    assert ver and ver <= publicas


# ──────────────────────────────────────────────────────────── o retrato ────

def _falsas():
    return {f: (lambda f=f: {"valor_de": f}) for f in copiloto._FONTES_ROTULO}


@pytest.fixture
def retrato(monkeypatch):
    monkeypatch.setattr(copiloto, "_fontes_do_snapshot", _falsas)
    monkeypatch.setattr(copiloto, "_SNAP", {"ts": 0.0, "texto": "", "falhas": [], "dados": {}})


def test_o_retrato_da_pessoa_so_tem_as_fontes_dela(retrato):
    texto = copiloto._snapshot_para(COMUM)
    d = json.loads(texto)
    assert "financeiro_caixa" in d and "onde_atacar" not in d
    assert '"valor_de": "people"' not in texto, "o valor da fonte escondida vazou"
    ocultas = len(copiloto._FONTES_ROTULO) - len(copiloto.fontes_visiveis(COMUM))
    assert d["fora_do_acesso"] == ocultas > 0


def test_admin_recebe_o_retrato_inteiro(retrato):
    d = json.loads(copiloto._snapshot_para(ADMIN))
    assert set(copiloto._FONTES_ROTULO) <= set(d)
    assert "fora_do_acesso" not in d


def test_o_retrato_e_montado_UMA_vez_para_todos(monkeypatch):
    montagens = []

    def contando():
        montagens.append(1)
        return _falsas()

    monkeypatch.setattr(copiloto, "_fontes_do_snapshot", contando)
    monkeypatch.setattr(copiloto, "_SNAP", {"ts": 0.0, "texto": "", "falhas": [], "dados": {}})
    copiloto._snapshot_para(COMUM)
    copiloto._snapshot_para(ADMIN)
    copiloto._snapshot_para({**COMUM, "telas": ["dre"]})
    assert len(montagens) == 1, "o corte por pessoa não pode refazer as consultas"


def test_a_falha_de_uma_fonte_so_aparece_para_quem_a_ve(monkeypatch):
    falsas = _falsas()
    falsas["onde_atacar"] = lambda: (_ for _ in ()).throw(RuntimeError("fora"))
    monkeypatch.setattr(copiloto, "_fontes_do_snapshot", lambda: falsas)
    monkeypatch.setattr(copiloto, "_SNAP", {"ts": 0.0, "texto": "", "falhas": [], "dados": {}})
    assert "fontes_indisponiveis" not in json.loads(copiloto._snapshot_para(COMUM))
    d = json.loads(copiloto._snapshot_para({**COMUM, "telas": ["dre"]}))
    assert d["fontes_indisponiveis"] == ["onde_atacar"]


# ──────────────────────────────────────────── prompt e procedência (ⓘ) ─────

def test_o_prompt_lista_so_as_telas_da_pessoa():
    p = copiloto.prompt_sistema(COMUM)
    assert "Fluxo de Caixa e Bancos" in p and "DRE Gerencial" not in p
    assert "DRE Gerencial" in copiloto.prompt_sistema(ADMIN)


def test_o_prompt_manda_dizer_que_a_area_esta_fora_do_acesso():
    assert "fora do acesso" in copiloto.prompt_sistema(COMUM).lower()


def test_a_procedencia_da_pessoa(retrato):
    copiloto._snapshot()
    c = copiloto.contexto(COMUM)
    assert "Fluxo de Caixa e Bancos" in c["fontes"]
    assert copiloto._FONTES_ROTULO["onde_atacar"] not in c["fontes"]
    assert c["telas"] == len(c["fontes"])


def test_chat_stream_e_contexto_EXIGEM_a_sessao():
    """Sem padrão de propósito: rota nova que esquecer de passar a sessão
    quebra na hora, em vez de entregar o retrato inteiro."""
    for fn in (copiloto.chat, copiloto.stream, copiloto.contexto, copiloto._snapshot_para):
        p = inspect.signature(fn).parameters["sess"]
        assert p.default is inspect.Parameter.empty, fn.__name__
