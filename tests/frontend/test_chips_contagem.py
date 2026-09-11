"""O NÚMERO não pode ficar colado no rótulo do chip.

Relatado por quem opera em 10/09/2026, nos filtros da Operação MWM: a tela
mostrava "Todos13", "Pendentes0", "Coletados13".

O ESPAÇO EXISTIA NO HTML e o CSS o jogava fora. O chip é montado como
`${rotulo} <span>${n}</span>` — há um espaço literal ali —, mas `button.ghost`
é `display:inline-flex`, e um contêiner flex DESCARTA o nó de texto em branco
entre dois filhos. Quem lê o HTML jura que o espaço está lá; quem olha a tela
lê "Todos13".

É a família do "a regra de CSS pode existir, estar certa e NÃO VALER": só o
navegador diz quem venceu. Por isso este guard MEDE O PIXEL — um teste que
procurasse o espaço no texto-fonte passaria com a tela errada, que é
exatamente o estado em que o defeito viveu.
"""
from __future__ import annotations

import json

import pytest

USUARIO = {"nome": "T", "email": "t@s.local", "admin": True,
           "perfil": "Administrador", "telas": []}

PONTOS = [{"ponto": "FORN %d" % i, "cidade": "SAO BERNARDO DO CAMPO",
           "uf": "SP", "lat": -23.69 - i / 100, "lng": -46.56 - i / 100,
           "sequencia": i, "estado": e, "coleta": 900 + i,
           "previsto": "2026-09-10 08:00", "chegada": None, "placa": "ABC1D23"}
          for i, e in enumerate(
              ["coletada", "aguardando", "no_local", "frustrada", "coletada"], 1)]

CORPO = {
    "kpis": {"solicitacoes": 5, "coletas": 1, "coletadas": 2, "frustradas": 1,
             "pendentes": 1, "realizado": 66.7, "pontos": 5},
    "dias": [], "coletas": [{"coleta": 901, "pontos": PONTOS}],
    "veiculos_pos": {}, "fornecedores": [], "tipos": [],
}

# Mede o vao REAL entre o fim do rotulo e o comeco do numero. O `Range` existe
# para isso: o rotulo e um no de TEXTO solto dentro do botao, e no de texto nao
# tem `getBoundingClientRect()` proprio.
_VAOS = """() => [...document.querySelectorAll('#milk-chips button')].map(b => {
  const txt = [...b.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
  const sp  = b.querySelector('span');
  if(!txt || !sp) return {rotulo: b.textContent.trim(), vao: null};
  const r = document.createRange(); r.selectNodeContents(txt);
  return {rotulo: b.textContent.trim(),
          vao: Math.round(sp.getBoundingClientRect().left
                          - r.getBoundingClientRect().right)};
})"""


@pytest.fixture
def chips(pagina):
    pg, base = pagina

    def rota(r):
        u = r.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            CORPO if "/api/operacao/milkrun" in u else {})
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(base + "/static/index.html#milkrun")
    pg.wait_for_selector("#milk-chips button", timeout=15000)
    pg.wait_for_timeout(400)
    return pg


def test_o_numero_NAO_fica_colado_no_rotulo_do_chip(chips):
    """O vão medido na tela, e não a regra escrita no CSS."""
    vaos = chips.evaluate(_VAOS)
    assert len(vaos) == 5, "os cinco chips de situação sumiram: %r" % vaos
    for c in vaos:
        assert c["vao"] is not None, (
            "chip sem número ou sem rótulo: %r" % c["rotulo"])
        assert c["vao"] >= 4, (
            "%r: o número está a %s px do rótulo — colado. O espaço do HTML "
            "não vale dentro de um contêiner flex."
            % (c["rotulo"], c["vao"]))


def test_o_vao_nao_e_tao_grande_que_desgrude_o_numero_do_rotulo(chips):
    """A outra ponta: um vão largo faz o número parecer de outro chip, e numa
    fila de cinco botões isso é pior que colado — o olho associa errado."""
    for c in chips.evaluate(_VAOS):
        assert c["vao"] <= 14, (
            "%r: %s px separam o número do rótulo — ele desgruda do próprio "
            "chip" % (c["rotulo"], c["vao"]))
