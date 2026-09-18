# -*- coding: utf-8 -*-
"""A identidade do motorista e o cadastro que a premiação nova usa.

O que estes testes seguram, e por que cada um existe:

- **o CPF do GR tem 14 dígitos** (zeros à esquerda). Comparado cru, o
  cruzamento folha × GR dava ZERO em 15.235 viagens — o defeito mais caro
  possível, porque parece "o fornecedor não manda motorista";
- **a folha manda, a decisão da casa fica**: sincronizar não pode desfazer o
  tipo nem a filial que alguém decidiu na tela (é a mesma regra que protege a
  classificação de ocorrências);
- **quem some da folha é desligado, não apagado**: o histórico de premiação
  precisa continuar tendo dono;
- **filial que não casa fica VAZIA**, pedindo decisão — filial inventada paga
  o valor errado.

Nada aqui vai à folha nem ao ERP: as duas entram por substituição. O banco
local é o `esquema_pg` (schema descartável), nunca produção.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.premiacao import identidade as ident

#: a função de verdade, guardada antes de a fixture substituí-la — o teste do
#: ERP fora do ar precisa dela para exercitar o `try` que ela tem dentro.
_OPERACAO_REAL = ident._operacao


# ------------------------------------------------------------------ as chaves
@pytest.mark.parametrize("bruto, esperado", [
    ("00012345678901", "12345678901"),       # GR: 14 dígitos com zeros à esquerda
    ("123.456.789-01", "12345678901"),       # folha: com pontuação
    ("12345678901", "12345678901"),          # ERP: cru
    (" 12345678901 ", "12345678901"),
    (None, ""), ("", ""), ("123", ""),       # o que não é CPF não vira chave
])
def test_o_cpf_de_QUALQUER_fonte_vira_a_mesma_chave(bruto, esperado):
    assert ident.cpf(bruto) == esperado


def test_o_nome_da_gobrax_perde_o_prefixo_numerico():
    """A Gobrax devolve "3781 - FULANO" em parte do cadastro."""
    assert ident.nome_chave("3781 - João da Silva") == "JOAO DA SILVA"
    assert ident.nome_chave("  joão   da  silva ") == "JOAO DA SILVA"
    # hífen que NÃO é prefixo numérico não se perde
    assert ident.nome_chave("MARIA-JOSE DA SILVA") == "MARIA-JOSE DA SILVA"


@pytest.mark.parametrize("area, sigla", [
    ("MOT SBC", "SBC"), ("SBC (CD)", "SBC"), ("SAO BERNARDO DO CAMPO", "SBC"),
    ("MOT CRUZEIRO", "CRZ"), ("MOT MATRIZ", "MTZ"), ("MOT JOINVILLE", "JOI"),
    ("MOT POUSO ALEGRE", "PSA"),
    ("FINANCEIRO", None), ("MOT AUDI", None), ("", None), (None, None),
])
def test_a_filial_sai_da_lotacao_e_o_que_nao_casa_fica_VAZIO(area, sigla):
    """Filial inventada paga o valor errado: o que não casa fica em branco e a
    tela pede decisão."""
    assert ident.filial_da_area(area) == sigla


def test_a_sugestao_de_tipo_vem_da_OPERACAO():
    assert ident.sugerir_tipo(12) == "RODOVIARIO"
    assert ident.sugerir_tipo(0) == "MANOBRA"


# ------------------------------------------------------------------ o cadastro
def _folha(*pessoas):
    """Cada pessoa: (cpf, nome, area, admissao)."""
    return [{"cpf": c, "nome": n, "chapa": "C" + c[-3:], "funcao": "MOT CARRETEIRO",
             "area": a, "admissao": adm} for c, n, a, adm in pessoas]


@pytest.fixture
def base(monkeypatch, esquema_pg):
    ident.ESQUEMA = esquema_pg
    monkeypatch.setattr(ident, "_cadastros_erp", lambda cpfs: {c: c for c in cpfs})
    monkeypatch.setattr(ident, "_operacao", lambda dias=90: {"11111111111": {"viagens": 30}})
    yield esquema_pg
    ident.ESQUEMA = None


def _liga_folha(monkeypatch, pessoas):
    import api.queries_folha as qf
    monkeypatch.setattr(qf, "_q", lambda sql, params=None: pessoas)


def test_a_primeira_sincronizacao_traz_a_folha_com_tipo_sugerido(base, monkeypatch):
    _liga_folha(monkeypatch, _folha(
        ("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01"),
        ("22222222222", "MOTORISTA DOIS", "MOT CRUZEIRO", "2019-06")))
    r = ident.sincronizar(autor="teste")
    assert (r["lidos"], r["novos"], r["desligados"]) == (2, 2, 0)
    por = {m["nome"]: m for m in ident.listar()}
    assert por["MOTORISTA UM"]["tipo"] == "RODOVIARIO"     # tem viagem
    assert por["MOTORISTA DOIS"]["tipo"] == "MANOBRA"      # não tem
    assert all(m["tipo_origem"] == "sugerido" for m in por.values())
    assert por["MOTORISTA UM"]["filial"] == "SBC"
    assert por["MOTORISTA UM"]["admissao"] == "2022-01"


def test_sincronizar_de_novo_NAO_duplica_nem_desliga(base, monkeypatch):
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    ident.sincronizar(autor="teste")
    r = ident.sincronizar(autor="teste")
    assert (r["novos"], r["atualizados"], r["desligados"]) == (0, 1, 0)
    assert len(ident.listar()) == 1


def test_a_DECISAO_da_casa_sobrevive_a_sincronizacao(base, monkeypatch):
    """A folha não sabe quem é manobrista; quem decidiu foi gente."""
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    ident.sincronizar(autor="teste")
    ident.decidir("11111111111", autor="gestor", tipo="MANOBRA", filial="JOI")
    ident.sincronizar(autor="teste")
    m = ident.listar()[0]
    assert (m["tipo"], m["tipo_origem"]) == ("MANOBRA", "manual")
    assert (m["filial"], m["filial_origem"]) == ("JOI", "manual")


def test_o_tipo_SUGERIDO_acompanha_a_operacao(base, monkeypatch):
    """Quem não é decisão de ninguém continua seguindo o que a pessoa faz."""
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    ident.sincronizar(autor="teste")
    assert ident.listar()[0]["tipo"] == "RODOVIARIO"
    monkeypatch.setattr(ident, "_operacao", lambda dias=90: {})   # parou de rodar
    ident.sincronizar(autor="teste")
    assert ident.listar()[0]["tipo"] == "MANOBRA"


def test_quem_sai_da_folha_e_DESLIGADO_e_nao_apagado(base, monkeypatch):
    """O histórico de premiação dele precisa continuar tendo dono."""
    _liga_folha(monkeypatch, _folha(
        ("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01"),
        ("22222222222", "MOTORISTA DOIS", "MOT SBC", "2019-06")))
    ident.sincronizar(autor="teste")
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    r = ident.sincronizar(autor="teste")
    assert r["desligados"] == 1
    assert len(ident.listar()) == 1                      # ativos
    assert len(ident.listar(ativos=False)) == 2          # o desligado continua lá


def test_a_folha_fora_do_ar_deixa_RASTRO_e_nao_apaga_ninguem(base, monkeypatch):
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    ident.sincronizar(autor="teste")

    import api.queries_folha as qf

    def explode(sql, params=None):
        raise RuntimeError("ORA-12541")
    monkeypatch.setattr(qf, "_q", explode)
    with pytest.raises(RuntimeError):
        ident.sincronizar(autor="teste")
    e = ident.estado()
    assert e["ativos"] == 1, "a falha da folha nao pode desligar ninguem"
    assert "RuntimeError" in (e["ultima_carga"] or {})["erro"]


def test_o_ERP_fora_do_ar_nao_impede_a_sincronizacao(base, monkeypatch):
    """A folha é a fonte do cadastro; o ERP só dá a sugestão de tipo e o código."""
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))

    monkeypatch.setattr(ident, "_operacao", _OPERACAO_REAL)

    def explode(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(ident.erp, "query", explode)
    r = ident.sincronizar(autor="teste")
    assert r["novos"] == 1
    assert ident.listar()[0]["tipo"] == "MANOBRA"   # sem operação, ninguém rodou


def test_decidir_exige_autor_e_recusa_quem_nao_esta_no_cadastro(base, monkeypatch):
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    ident.sincronizar(autor="teste")
    with pytest.raises(ValueError, match="Informe quem"):
        ident.decidir("11111111111", autor="", tipo="MANOBRA")
    with pytest.raises(ValueError, match="fora do cadastro"):
        ident.decidir("99999999999", autor="gestor", tipo="MANOBRA")
    with pytest.raises(ValueError, match="Tipo inválido"):
        ident.decidir("11111111111", autor="gestor", tipo="PILOTO")


def test_o_estado_diz_o_que_falta_decidir(base, monkeypatch):
    _liga_folha(monkeypatch, _folha(
        ("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01"),
        ("22222222222", "MOTORISTA DOIS", "MOT AUDI", "2019-06")))
    ident.sincronizar(autor="teste")
    e = ident.estado()
    assert e["ativos"] == 2 and e["sem_filial"] == 1 and e["decididos"] == 0
    ident.decidir("22222222222", autor="gestor", filial="JOI")
    assert ident.estado()["sem_filial"] == 0


def test_a_tabela_guarda_CPF_mas_a_listagem_fala_por_CODIGO(base, monkeypatch):
    """CPF é PII: fica no banco local como chave, e a tela usa o código do
    cadastro do ERP, como o resto da casa já faz."""
    _liga_folha(monkeypatch, _folha(("11111111111", "MOTORISTA UM", "MOT SBC", "2022-01")))
    ident.sincronizar(autor="teste")
    colunas = pglocal.query(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'prm_motorista'", (base,))
    nomes = {c["column_name"] for c in colunas}
    assert "cpf" in nomes and "cadastro_codigo" in nomes
    assert ident.listar()[0]["cadastro_codigo"] == "11111111111"
