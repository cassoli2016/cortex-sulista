"""O mapa do Milk Run e a legenda dele, conferidos no HTML.

Por que existe: a cor do pino e a cor do selo da tabela nasceram do mesmo
significado e viviam em dois lugares. Duplicada, uma delas muda sozinha e o
mapa passa a discordar da tabela sobre o mesmo ponto — erro silencioso, porque
nada quebra. Aqui as duas tabelas de estado sao comparadas chave a chave.
"""
import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def _dict_js(html: str, nome: str) -> dict[str, str]:
    """Le as CHAVES de um objeto literal de topo do index.html."""
    m = re.search(rf"const {nome} *= *{{(.*?)}};", html, re.S)
    assert m, f"{nome} nao encontrado"
    return {k: v.strip() for k, v in re.findall(r"(\w+) *: *([^,\n]+)", m.group(1))}


def test_a_paleta_do_mapa_cobre_os_mesmos_estados_da_tabela(html):
    """MILK_COR (mapa/legenda) e MILK_EST (selo da tabela) descrevem o mesmo
    conjunto de situacoes. Estado novo em um e nao no outro deixa o ponto sem
    cor no mapa ou sem rotulo na legenda."""
    assert set(_dict_js(html, "MILK_COR")) == set(_dict_js(html, "MILK_EST"))


def test_as_cores_do_pino_sao_as_do_semaforo(html):
    """Sem tom fora do design system: ok, atencao, neutro e alerta."""
    assert set(_dict_js(html, "MILK_COR").values()) == {
        "'#1E7F4F'",  # concluido - verde --green
        "'#B97709'",  # no local  - ambar --yellow
        "'#6B7580'",  # pendente  - neutro --n500
        "'#C03221'",  # frustrada - vermelho --red
    }


def test_a_legenda_fica_no_canto_inferior_esquerdo(html):
    """Pedido do usuario, e tambem o unico canto livre: o zoom do Leaflet ocupa
    o superior esquerdo e a atribuicao do OSM o inferior direito."""
    assert "L.control({position:'bottomleft'})" in html


def test_a_legenda_so_lista_estado_que_existe_no_recorte(html):
    """Item com contagem zero ocupa espaco e nao ensina nada — e ainda sugere
    que ha pontos daquele tipo escondidos no mapa."""
    assert "MILK_ORDEM.filter(e => comCoord.some(p=>p.estado===e))" in html


def test_o_pino_traz_a_ordem_da_parada(html):
    """Num milk run a sequencia decide a leitura ('a terceira parada travou');
    o circulo liso so dizia o estado."""
    assert 'class="milk-pin"' in html and "${p.sequencia||''}" in html


def test_nao_sobrou_marcador_liso_no_milk_run(html):
    """circleMarker ainda e usado em OUTRAS telas; o que nao pode e voltar a
    existir dentro do milkMapa, que perderia o numero da parada."""
    m = re.search(r"async function milkMapa\(pts\)\{(.*?)\n}", html, re.S)
    assert m, "milkMapa nao encontrada"
    assert "circleMarker" not in m.group(1)
