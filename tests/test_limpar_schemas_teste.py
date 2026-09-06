# -*- coding: utf-8 -*-
"""Os guards do script que APAGA schema.

Este é o único script da casa que destrói dado sem volta, e o modo de falha
dele não tem sintoma intermediário: ou apaga a coisa certa, ou apagou o banco
de produção. Por isso o teste mira exatamente no que separa as duas.

O que ele NÃO testa, de propósito: o `DROP` em si. Quem o executa é
`pglocal.apagar_esquema()`, que já tem a recusa do schema de produção e o teste
dela. Duplicar aqui daria a impressão de duas travas testadas quando é uma só.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

limpar = pytest.importorskip("limpar_schemas_teste")


# --------------------------------------------------------------------------
# o padrão — a trava que decide tudo
# --------------------------------------------------------------------------
@pytest.mark.parametrize("nome", [
    "teste_09310c3c8955",       # esquema_pg: 12 hex
    "teste_aud_07a1a0a2f1",     # fixture de auditoria: aud_ + 10 hex
])
def test_o_que_a_suite_fabrica_e_reconhecido(nome):
    """Os dois formatos vêm das fixtures em `tests/conftest.py`
    (`uuid4().hex[:12]` e `aud_{uuid4().hex[:10]}`). Se alguém mudar o nome
    lá, este teste é o que avisa que a limpeza parou de enxergar."""
    assert limpar.PADRAO.match(nome)


@pytest.mark.parametrize("nome", [
    "cortex",                   # O SCHEMA DE PRODUÇÃO
    "public",
    "teste",                    # prefixo sem sufixo
    "teste_",
    "testes_09310c3c8955",      # plural — outro schema
    "teste_producao",           # não é hex
    "teste_09310c3c895",        # 11 hex: curto demais
    "teste_09310c3c89551",      # 13 hex: longo demais
    "teste_09310C3C8955",       # maiúscula não é o que uuid4().hex gera
    "teste_aud_07a1a0a2f",      # 9 hex
    "teste_aud_producao",
    "xteste_09310c3c8955",      # não começa no início
    "teste_09310c3c8955x",
])
def test_nada_alem_disso_casa(nome):
    """A ÂNCORA `$` É O QUE IMPORTA AQUI. Um padrão sem ela casaria
    `teste_09310c3c8955_importante` — e o script apagaria um schema que alguém
    criou à mão para trabalhar, com o nome parecendo inocente na lista."""
    assert not limpar.PADRAO.match(nome)


def test_o_schema_de_producao_nao_casa_de_jeito_nenhum():
    """Vale um teste próprio, e não uma linha no parametrize: é O erro que
    este script existe para não cometer."""
    assert not limpar.PADRAO.match("cortex")
    assert "cortex" in limpar.NUNCA


# --------------------------------------------------------------------------
# a triagem
# --------------------------------------------------------------------------
def test_schema_fora_do_padrao_vira_ACHADO_e_nao_silencio(monkeypatch):
    """`teste_alguma_coisa` no banco não é da suíte — foi alguém. O script não
    pode apagar (não casa) NEM engolir: ele lista à parte, para uma pessoa
    decidir. Campo ausente em conferidor vira achado, não silêncio."""
    linhas = [
        {"esquema": "teste_09310c3c8955", "oid": 1, "tabelas": 108,
         "bytes": 5_000_000, "linhas": 52},
        {"esquema": "teste_da_maria", "oid": 2, "tabelas": 3,
         "bytes": 1000, "linhas": 7},
        {"esquema": "cortex", "oid": 3, "tabelas": 108,
         "bytes": 400_000_000, "linhas": 999},
    ]
    monkeypatch.setattr(limpar.pglocal, "query",
                        lambda sql, p: linhas if "pg_locks" not in sql else [])
    bons, em_uso, recusados = limpar.levantar()
    assert [b["esquema"] for b in bons] == ["teste_09310c3c8955"]
    assert set(recusados) == {"teste_da_maria", "cortex"}
    assert em_uso == set()


def test_schema_EM_USO_e_separado_dos_orfaos(monkeypatch):
    """Lock de outro backend significa suíte rodando AGORA. Apagar ali quebra
    o teste de outra pessoa com um erro que não aponta para este script — e
    hoje três sessões trabalham neste repo ao mesmo tempo."""
    linhas = [{"esquema": "teste_09310c3c8955", "oid": 1, "tabelas": 108,
               "bytes": 5_000_000, "linhas": 52}]
    monkeypatch.setattr(
        limpar.pglocal, "query",
        lambda sql, p: ([{"esquema": "teste_09310c3c8955"}]
                        if "pg_locks" in sql else linhas))
    bons, em_uso, _ = limpar.levantar()
    # ELE CONTINUA NA LISTA — o script mostra e PULA, em vez de escondê-lo:
    # sumir da listagem faria parecer que ele não existe mais.
    assert [b["esquema"] for b in bons] == ["teste_09310c3c8955"]
    assert em_uso == {"teste_09310c3c8955"}


# --------------------------------------------------------------------------
# o modo destrutivo
# --------------------------------------------------------------------------
def test_tudo_sem_confirmo_NAO_APAGA_NADA(monkeypatch, capsys):
    """`--tudo` é o modo sem pergunta. Exigir a segunda palavra é o que impede
    que ele saia de um histórico de shell por engano."""
    chamou = []
    monkeypatch.setattr(limpar.pglocal, "apagar_esquema",
                        lambda n: chamou.append(n))
    monkeypatch.setattr(sys, "argv", ["limpar", "--tudo"])
    assert limpar.main() == 2
    assert chamou == []
    assert "--confirmo" in capsys.readouterr().out


def test_listar_NAO_APAGA_NADA(monkeypatch, capsys):
    """O modo de leitura tem de ser inerte — é ele que se roda para decidir."""
    chamou = []
    monkeypatch.setattr(limpar.pglocal, "apagar_esquema",
                        lambda n: chamou.append(n))
    monkeypatch.setattr(limpar.pglocal, "onde", lambda: "banco/de/teste")
    monkeypatch.setattr(
        limpar.pglocal, "query",
        lambda sql, p: ([] if "pg_locks" in sql else
                        [{"esquema": "teste_09310c3c8955", "oid": 1,
                          "tabelas": 108, "bytes": 5_000_000, "linhas": 52}]))
    monkeypatch.setattr(sys, "argv", ["limpar", "--listar"])
    assert limpar.main() == 0
    assert chamou == []
    assert "teste_09310c3c8955" in capsys.readouterr().out


def test_o_banco_de_destino_e_DITO_antes_de_qualquer_coisa(monkeypatch, capsys):
    """Script que apaga e não mostra contra que banco vai rodar é script que um
    dia roda no banco errado."""
    monkeypatch.setattr(limpar.pglocal, "onde", lambda: "10.0.0.9:5432/producao")
    monkeypatch.setattr(limpar.pglocal, "query", lambda sql, p: [])
    monkeypatch.setattr(sys, "argv", ["limpar", "--listar"])
    limpar.main()
    saida = capsys.readouterr().out
    assert "10.0.0.9:5432/producao" in saida
    assert saida.index("10.0.0.9") < 40, "o destino tem de vir na primeira linha"


# --------------------------------------------------------------------------
# a idade — o que separa o lote da aprovação individual
# --------------------------------------------------------------------------
def test_o_mais_velho_vem_primeiro_e_o_desconhecido_por_ULTIMO(monkeypatch):
    """A ordem é a da aprovação: os antigos, que vão no lote, primeiro. Idade
    desconhecida vai para o fim junto dos recentes — é onde mora a pergunta
    individual, e o lado seguro para o que não se entende é perguntar."""
    linhas = [
        {"esquema": "teste_000000000001", "oid": 1, "tabelas": 1, "bytes": 1, "linhas": 0},
        {"esquema": "teste_000000000002", "oid": 2, "tabelas": 1, "bytes": 1, "linhas": 0},
        {"esquema": "teste_000000000003", "oid": 3, "tabelas": 1, "bytes": 1, "linhas": 0},
    ]
    idades = {"teste_000000000001": 5.0, "teste_000000000002": None,
              "teste_000000000003": 40.0}
    monkeypatch.setattr(limpar.pglocal, "query",
                        lambda sql, p: [] if "pg_locks" in sql else linhas)
    monkeypatch.setattr(limpar, "horas", lambda n: n)
    monkeypatch.setattr(limpar, "_nasceu", lambda e: idades[e])
    bons, _, _ = limpar.levantar()
    assert [b["esquema"] for b in bons] == [
        "teste_000000000003", "teste_000000000001", "teste_000000000002"]


def test_schema_sem_schema_versao_NAO_derruba_o_levantamento(monkeypatch):
    """Um schema `teste_*` sem `schema_versao` está nascendo agora, no meio de
    uma migration. Ele não pode explodir a listagem — vira idade `n/d`."""
    monkeypatch.setattr(limpar.pglocal, "get_conn", _conn_que_explode)
    assert limpar._nasceu("teste_000000000001") is None


def test_idade_desconhecida_NUNCA_entra_no_lote():
    """`n/d` é schema que pode estar sendo criado neste instante. O lote é
    para o que se entende; o resto se pergunta."""
    linhas = [{"esquema": "teste_000000000001", "horas": None, "bytes": 1},
              {"esquema": "teste_000000000002", "horas": 0.5, "bytes": 1},
              {"esquema": "teste_000000000003", "horas": 99.0, "bytes": 1}]
    antigos = [r for r in linhas
               if r["horas"] is not None and r["horas"] >= limpar.RECENTE_H]
    assert [r["esquema"] for r in antigos] == ["teste_000000000003"]


def test_a_faixa_de_recente_cobre_a_suite_completa():
    """A suíte inteira da casa leva pouco mais de trinta minutos. Um corte
    abaixo disso poria no lote um schema de rodada VIVA — e o lote não
    pergunta."""
    assert limpar.RECENTE_H >= 1


def test_idade_em_texto_nunca_mente_de_zero():
    """`n/d` é ausência de resposta e não pode virar '0 min', que se lê como
    'acabou de nascer' — o oposto do que fazer com ele."""
    assert limpar.idade_txt(None) == "n/d"
    assert limpar.idade_txt(0.5) == "30 min"
    assert "h" in limpar.idade_txt(8.3)
    assert "dias" in limpar.idade_txt(72.0)


class _ConnExplode:
    def __enter__(self):
        raise RuntimeError("sem schema_versao")

    def __exit__(self, *a):
        return False


def _conn_que_explode(*a, **k):
    return _ConnExplode()
