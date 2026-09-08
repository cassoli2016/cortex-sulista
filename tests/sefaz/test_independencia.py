# -*- coding: utf-8 -*-
"""A recolha e do CORTEX e NAO depende do ERP.

Decisao de arquitetura de quem opera (07/09/2026): o modulo e do TMS Cortex e
vai ser usado independente do AVA. Isso nao e observacao sobre como o codigo
saiu -- e requisito, e requisito sem guard vira comentario.

O QUE ACONTECE SEM ELE: alguem precisa do nome do cliente numa tela da recolha,
importa `api.db` "so para isso", e seis meses depois o modulo nao se copia mais
para o TMS -- ele se REESCREVE. E e reescrevendo que se perdem as sete
correcoes que a `erpbrasil.edoc` exigiu, uma a uma, contra o servico real.

O reaproveitamento entre CORTEX e TMS Sulista e por COPIA, nunca por import
(memoria `tms-sulista-projeto-separado`). Um modulo que so funciona com o AVA
por perto nao atravessa essa fronteira.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULO = Path(__file__).resolve().parents[2] / "api" / "sefaz"

#: O UNICO arquivo autorizado a ler o ERP -- e ele e opcional por construcao.
PONTE = "conciliacao.py"

#: Nomes que denunciam o AVA. Tabela do ERP citada num arquivo do nucleo e o
#: sintoma; `api.db` e a causa.
TABELAS_DO_ERP = ("conhecimento", "coleta_notafiscal", "programacaoembarque",
                  "ordemcompra", "planoconta", "lancamento", "sulista.")


def _arquivos_do_nucleo():
    return [f for f in sorted(MODULO.glob("*.py")) if f.name != PONTE]


@pytest.mark.parametrize("arq", _arquivos_do_nucleo(),
                         ids=lambda f: f.name)
def test_o_nucleo_NAO_importa_o_banco_do_ERP(arq):
    """`api.db` e a porta do AVA. Quem a abre no nucleo prende o modulo aqui.

    Le por `ast` e nao por texto: `# from api import db` num comentario nao e
    um import, e um guard que acusa comentario acaba desligado.
    """
    arvore = ast.parse(arq.read_text(encoding="utf-8"))
    culpados = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            culpados += [a.name for a in no.names if a.name.split(".")[-1] == "db"]
        elif isinstance(no, ast.ImportFrom):
            mod = no.module or ""
            if mod.split(".")[-1] == "db" or "db" in [a.name for a in no.names]:
                culpados.append("%s.%s" % (mod, [a.name for a in no.names]))
    assert not culpados, (
        "%s importa o banco do ERP: %s. So `%s` pode -- e ele e a PONTE, "
        "opcional por construcao. Precisa de dado do ERP no nucleo? A resposta "
        "e passar o dado por parametro, nao abrir a porta."
        % (arq.name, culpados, PONTE))


@pytest.mark.parametrize("arq", _arquivos_do_nucleo(),
                         ids=lambda f: f.name)
def test_o_nucleo_NAO_nomeia_tabela_do_ERP_em_SQL(arq):
    """O import e a causa; a tabela citada e o sintoma -- e da para ter o
    sintoma sem a causa (um SQL montado e passado para outro modulo executar).

    Confere so as CONSTANTES de modulo: a palavra "conhecimento" aparece em
    prosa nos docstrings desta casa, e acusar prosa seria guard que grita a
    toa.
    """
    arvore = ast.parse(arq.read_text(encoding="utf-8"))
    culpados = []
    for no in arvore.body:
        if not isinstance(no, (ast.Assign, ast.AnnAssign)):
            continue
        v = getattr(no, "value", None)
        if not (isinstance(v, ast.Constant) and isinstance(v.value, str)):
            continue
        baixo = v.value.lower()
        if "select" not in baixo and "from" not in baixo:
            continue
        culpados += [t for t in TABELAS_DO_ERP if t in baixo]
    assert not culpados, (
        "%s tem SQL contra tabela do ERP: %s. A recolha roda sem o AVA."
        % (arq.name, sorted(set(culpados))))


def test_a_TELA_sobrevive_ao_ERP_fora_do_ar(monkeypatch):
    """A prova pelo comportamento, e nao pela estrutura: com o ERP inteiro
    caindo, o panorama da recolha continua respondendo.

    E o cartao da conciliacao vira "nao sei" (None), e nao ZERO -- zero diria
    "conferi e nao ha nenhum sem par", que e uma afirmacao que ninguem fez.
    """
    from api.sefaz import conciliacao, painel

    def cai(*a, **k):
        raise RuntimeError("o AVA nao respondeu")

    monkeypatch.setattr("api.db.query", cai)
    d = painel.panorama()
    assert "caixas" in d and "total" in d, "o panorama caiu junto com o ERP"
    assert conciliacao.no_erp(["4" * 44]) == {}
    r = conciliacao.marcar([{"tipo": "nfe", "chave": "4" * 44}])
    assert r["comparaveis"] == 1


def test_apagar_a_PONTE_deixa_a_recolha_de_pe(monkeypatch):
    """O teste mais direto do requisito: sem `conciliacao` importavel, tudo o
    mais do modulo continua carregando e funcionando."""
    import builtins
    real = builtins.__import__

    def sem_ponte(nome, *a, **kw):
        if nome.endswith("conciliacao"):
            raise ImportError("conciliacao apagada")
        return real(nome, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", sem_ponte)
    from api.sefaz import armazenamento, busca, distribuicao, impressao, leitura
    assert leitura.classificar("procNFe_v4.00") == ("nfe", True)
    assert armazenamento.nsu(12) == "000000000000012"
    assert distribuicao.codigo_uf("PR") == 41
    assert impressao.rotulo("cte") == "DACTE"
    assert busca.local("x" * 44) is None
