"""O sino de notificações — o que ele promete e o erro que já cometeu.

O DEFEITO QUE ORIGINOU METADE DESTE ARQUIVO
===========================================
A primeira versão pintou o ícone com `var(--n0)`. `--n0` é o token da
SUPERFÍCIE, não da tinta — e a barra de topo tem `background:var(--n0)`. No
tema claro isso deu **branco sobre branco**: o botão existia, media 36px,
respondia ao clique e era invisível.

Nenhuma medida de cor sozinha pega isso: `getComputedStyle` devolvia
`rgb(255,255,255)`, que é uma cor perfeitamente válida. O que pega é comparar
a tinta com o FUNDO REAL, que é o que este arquivo faz — a mesma régua do
`auditar_tema.py`, agora aplicada a um componente só e em toda carga.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

NOTIF = {
    "itens": [{
        "chave": "boas_vindas", "tipo": "boas_vindas",
        "titulo": "Bem-vindo ao CÓRTEX, Marcos",
        "texto": "Este é o painel de gestão da Sulista.",
        "dica": "Todo cartão tem um ⓘ no título.",
        "acao": {"rotulo": "Abrir a documentação", "view": "doc"},
    }],
    "nao_lidas": 1,
}
VAZIO = {"itens": [], "nao_lidas": 0}


def _abrir(pg, base_url, notif=NOTIF, largura=1500):
    """Sobe a tela com o sino alimentado pelo payload dado."""
    estado = {"lidas": False, "posts": []}

    def rota(route):
        u = route.request.url
        if "/api/notificacoes/lida" in u:
            estado["lidas"] = True
            estado["posts"].append(route.request.post_data)
            corpo = VAZIO
        elif "/api/notificacoes" in u:
            corpo = VAZIO if estado["lidas"] else notif
        elif "/api/auth/me" in u:
            corpo = ADMIN
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.set_viewport_size({"width": largura, "height": 900})
    pg.route("**/api/**", rota)
    pg.goto(f"{base_url}/static/index.html#home")
    pg.wait_for_timeout(900)
    return estado


def _rgb(txt):
    n = [int(x) for x in txt.replace("rgba", "rgb").strip("rgb() ").split(",")[:3]]
    return tuple(n)


def _lum(c):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ── o defeito que já aconteceu ──────────────────────────────────────────────


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_o_sino_NAO_e_da_cor_do_fundo_em_que_esta(pagina, tema):
    """Branco sobre branco. O botão existia, respondia ao clique e não se via.

    A conferência é contra o FUNDO REAL — subir a árvore até o primeiro
    ancestral opaco —, e não contra um valor esperado: a barra de topo é clara
    num tema e escura no outro, então qualquer cor fixa esperada estaria errada
    metade das vezes.
    """
    pg, base = pagina
    pg.emulate_media(color_scheme=tema)
    _abrir(pg, base)
    cores = pg.evaluate("""()=>{
      const b=document.getElementById('sinoBtn');
      if(!b) return null;
      const ic=b.querySelector('.ic svg')||b.querySelector('.ic')||b;
      let fundo='rgba(0, 0, 0, 0)', el=b;
      while(el && (fundo==='rgba(0, 0, 0, 0)' || fundo==='transparent')){
        fundo=getComputedStyle(el).backgroundColor; el=el.parentElement;
      }
      return {tinta:getComputedStyle(ic).color, fundo:fundo};
    }""")
    assert cores, "o sino não existe na barra de topo"
    c = _contraste(_rgb(cores["tinta"]), _rgb(cores["fundo"]))
    assert c >= 3.0, (
        "o sino tem contraste %.2f:1 contra o fundo em que está (tinta %s, "
        "fundo %s) — no tema %s ele fica invisível"
        % (c, cores["tinta"], cores["fundo"], tema))


# ── o que o sino promete ────────────────────────────────────────────────────


def test_zero_deixa_o_badge_EM_BRANCO_e_nao_em_zero(pagina):
    """Um "0" permanente ensina a ignorar o sino, que é o oposto do que ele
    existe para fazer. Mesma regra do contador de sub-aba."""
    pg, base = pagina
    _abrir(pg, base, notif=VAZIO)
    assert pg.inner_text("#sinoPino").strip() == ""
    assert not pg.is_visible("#sinoPino"), "`.pino:empty` tem de esconder"


def test_o_badge_conta_o_que_ha(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.inner_text("#sinoPino").strip() == "1"
    # o número tem de estar no rótulo acessível, não só no desenho
    assert "1" in (pg.get_attribute("#sinoBtn", "aria-label") or "")


def test_o_painel_abre_e_fecha_e_nao_nasce_aberto(pagina):
    """Painel aberto no boot cobriria a tela toda vez que alguém entrasse."""
    pg, base = pagina
    _abrir(pg, base)
    assert not pg.is_visible("#sinoPanel")
    pg.click("#sinoBtn"); pg.wait_for_timeout(250)
    assert pg.is_visible("#sinoPanel")
    assert pg.get_attribute("#sinoBtn", "aria-expanded") == "true"
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    assert not pg.is_visible("#sinoPanel")


def test_dispensar_manda_a_CHAVE_e_zera_o_badge(pagina):
    """O POST manda a chave, e a contagem nova vem do SERVIDOR na mesma
    resposta — recalcular no cliente criaria duas contas para o mesmo número.
    """
    pg, base = pagina
    estado = _abrir(pg, base)
    pg.click("#sinoBtn"); pg.wait_for_timeout(250)
    pg.click(".sinoitem .acoes button:not(.pri)")
    pg.wait_for_timeout(450)
    assert estado["lidas"], "o dispensar não chamou a API"
    assert json.loads(estado["posts"][0])["chave"] == "boas_vindas"
    assert pg.inner_text("#sinoPino").strip() == ""


def test_o_vazio_DIZ_o_que_esperar(pagina):
    """Quem abre um sino vazio precisa saber se ele está quebrado ou se de fato
    não há nada."""
    pg, base = pagina
    _abrir(pg, base, notif=VAZIO)
    pg.click("#sinoBtn"); pg.wait_for_timeout(250)
    txt = pg.inner_text("#sinoLista").lower()
    assert "nenhuma notifica" in txt
    assert "aparece aqui" in txt


def test_o_sino_e_alcancavel_no_CELULAR(pagina):
    """A barra de topo tinha 450px de conteúdo numa tela de 390: o sino ficava
    inteiro fora da tela — inalcançável justamente no aparelho em que a
    notificação mais serve."""
    pg, base = pagina
    _abrir(pg, base, largura=390)
    caixa = pg.evaluate("""()=>{
      const b=document.getElementById('sinoBtn');
      const r=b.getBoundingClientRect();
      return {esq:r.left, dir:r.right, larg:innerWidth};
    }""")
    assert caixa["dir"] <= caixa["larg"] + 1 and caixa["esq"] >= -1, (
        "o sino está fora da tela no celular: %s" % caixa)
    assert pg.is_visible("#sinoBtn")
