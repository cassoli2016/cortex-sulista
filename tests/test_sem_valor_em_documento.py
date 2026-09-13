"""Valor em reais e taxa financeira não entram em documento versionado.

O repositório é PÚBLICO. Até 13/09/2026 o CLAUDE.md e as crônicas traziam o
caixa projetado, o custo de antecipação, a folha de horas extras e o efeito em
reais de decisões comerciais — cerca de 190 valores em 21 documentos, legíveis
por qualquer pessoa na internet. A regra (CLAUDE.md §8, item 1) é escrever
`R$ [valor omitido]`, a razão entre dois números ou a ordem de grandeza: a
lição sobrevive, o número de negócio não sai.

Escopo: todo `.md` versionado, menos o CHANGELOG.md — ele é gerado do
versoes.yaml, e bloco antigo de versão não se reescreve (regra da casa). O
bloco NOVO do versoes.yaml é cobrado à parte. `R$ 0` passa: é regra ("piso
nunca R$ 0"), não dado.

Isto limpa daqui para frente. O que já foi publicado continua no histórico do
git, e reescrever a `main` com push forçado é proibido aqui.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
VALOR = re.compile(r"R\$\s?(?!0(?:,00)?(?!\d|[.,]\d))\d")
TAXA = re.compile(r"\d+,\d+\s?%\s?a\.\s?[am]", re.IGNORECASE)


def _documentos() -> list[str]:
    r = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=RAIZ,
                       capture_output=True, check=True)
    return [f for f in r.stdout.decode("utf-8").split("\0")
            if f and f != "CHANGELOG.md"]


def _achados(texto: str) -> list[str]:
    return [l.strip()[:110] for l in texto.splitlines()
            if VALOR.search(l) or TAXA.search(l)]


def test_nenhum_documento_versionado_traz_valor_em_reais_ou_taxa():
    docs = _documentos()
    assert len(docs) > 20, f"só {len(docs)} documentos: a varredura olhou o lugar certo?"
    sujos = {}
    for f in docs:
        a = _achados((RAIZ / f).read_text(encoding="utf-8", errors="replace"))
        if a:
            sujos[f] = a[:3]
    assert not sujos, (
        "valor em reais ou taxa financeira em documento versionado — o "
        "repositório é público. Escreva `R$ [valor omitido]`, a razão entre "
        "dois números ou a ordem de grandeza: " + str(sujos)[:1500])


def test_o_bloco_novo_do_versoes_tambem_nao_traz_valor():
    topo = yaml.safe_load(
        (RAIZ / "docs" / "versoes.yaml").read_text(encoding="utf-8"))[0]
    assert not _achados(str(topo)), f"o bloco {topo['versao']} traz valor"


def test_o_detector_acha_o_que_devia_e_poupa_a_regra():
    """Sem isto os dois acima poderiam estar verdes por não detectar nada."""
    assert _achados("custou R$ 7.324,75 em 60 dias")
    assert _achados("sobra R$ 1,2 mi no caixa")
    assert _achados("deságio de 14,26% a.a.")
    assert _achados("rotativo de 15,67% a.MÊS")
    assert not _achados("lane sem eixos tem piso `n/d`, nunca R$ 0.")
    assert not _achados("R$ [valor omitido] de estadia")
    assert not _achados("o custo por km em R$/km")
