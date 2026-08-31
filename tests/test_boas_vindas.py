"""E-mail de boas-vindas ao cadastrar usuário.

O ponto fraco do desenho é conhecido e está escrito no módulo: senha por
e-mail fica na caixa de entrada, é encaminhável e sobrevive a backup. O padrão
mais forte seria um link de primeiro acesso com validade curta. Como a senha
provisória foi o que se pediu, estes testes trancam as quatro defesas que a
tornam aceitável — e a que mais importa é a última: **a senha não aparece em
lugar nenhum além do e-mail**.
"""
from __future__ import annotations

import re

import pytest

from api.correio import boas_vindas as bv


def test_a_senha_e_gerada_e_nao_tem_caractere_ambiguo():
    """Senha provisória digitada por gente vira "Mudar@123" em toda a empresa,
    e aí o elo fraco deixa de ser o e-mail e passa a ser o padrão que todo
    mundo conhece. E O/0 e l/1/I são o que faz alguém digitar errado e pedir
    outra — numa senha que vai ser LIDA de um e-mail, isso importa."""
    vistas = {bv.gerar_senha() for _ in range(200)}
    assert len(vistas) == 200, "senha repetiu: gerador não é aleatório o bastante"
    for s in vistas:
        assert len(s) == bv.SENHA_TAM
        assert not (set(s) & set("Oo0lI1")), f"caractere ambíguo em {s}"
        assert re.search(r"[!@#$%&*\-+=]", s), "sem símbolo"
        assert re.search(r"[2-9]", s), "sem dígito"


def test_o_overview_lista_SO_o_que_aquele_usuario_abre():
    """Mandar as 65 telas para quem tem 8 é promessa quebrada no primeiro
    clique — e faz a pessoa achar que o sistema está com defeito quando está
    só com perfil."""
    g = bv.telas_do_usuario(["home", "fluxo", "km"], admin=False)
    rotulos = [r for _, ts in g for r in ts]
    assert "Visão Geral" in rotulos and "Análise de KM" in rotulos
    assert "Saúde do Servidor" not in rotulos
    assert len(rotulos) == 3


def test_administrador_nao_recebe_a_lista_das_65_telas():
    """65 telas num e-mail não é boas-vindas, é intimidação: o texto diz que
    ele abre todas em vez de enumerá-las."""
    _, texto, html = bv.montar("Fulano", "f@x.com", "Senha123!", "https://x",
                               admin=True)
    assert "TODAS AS TELAS" in texto
    assert "todas as telas" in html
    # e não despeja a enumeração
    assert "Saúde do Servidor" not in html


def test_o_email_diz_endereco_usuario_e_que_a_senha_e_provisoria():
    """Um e-mail de acesso sem os três é papel picado."""
    _, texto, html = bv.montar("Maria Silva", "maria@x.com", "Abc123!@#xyz",
                               "https://cortex.exemplo.com.br", telas=["home"])
    for parte in ("https://cortex.exemplo.com.br", "maria@x.com", "Abc123!@#xyz"):
        assert parte in texto and parte in html
    assert "provisória" in texto.lower() and "provisória" in html.lower()
    # cumprimento pelo PRIMEIRO nome: "Bem-vindo, Maria Silva" soa a formulário
    assert "Maria." in texto


def test_o_html_e_seguro_para_outlook():
    """O Outlook renderiza com o motor do Word: flex, grid e imagem de fundo
    são ignorados calados, e o e-mail chega desmontado sem ninguém saber.

    O `<style>` do layout NÃO é proibido — ele existe para declarar tema claro
    e conter a reescrita de cor do Outlook.com. O que se exige é que ele não
    carregue LAYOUT: o Gmail descarta o bloco em parte dos casos, e a
    mensagem tem de continuar de pé quando isso acontece."""
    _, _, html = bv.montar("F", "f@x.com", "S3nh4!", "https://x", telas=["home"])
    for proibido in ("display:flex", "display:grid", "background-image",
                     "position:absolute"):
        assert proibido not in html, f"{proibido} não sobrevive ao Outlook"
    assert "<table" in html and "cellpadding" in html
    if "<style>" in html:
        bloco = html.split("<style>", 1)[1].split("</style>", 1)[0]
        for layout in ("display:", "width:", "float:", "flex"):
            assert layout not in bloco, f"layout no <style>: {layout}"


def test_o_html_escapa_o_que_veio_de_fora():
    """Nome e e-mail vêm de formulário. Um `<script>` no nome não pode
    atravessar para o corpo do e-mail."""
    _, _, html = bv.montar('<script>x</script>', 'a"b@x.com', "S3nh4!",
                           "https://x", telas=["home"])
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_sem_o_endereco_do_painel_o_envio_RECUSA(monkeypatch):
    """E-mail de acesso sem dizer ONDE entrar não serve para nada, e mandar
    assim gasta a única primeira impressão que existe. A URL não tem padrão de
    propósito — adivinhar host manda gente nova para lugar nenhum."""
    monkeypatch.setattr(bv.cfg, "configurado", lambda: True)
    r = bv.enviar_boas_vindas("a@x.com", "A", "S3nh4!", "   ")
    assert r["ok"] is False and "CORTEX_URL" in r["erro"]


def test_sem_correio_configurado_o_envio_RECUSA_dizendo_onde_configurar(monkeypatch):
    monkeypatch.setattr(bv.cfg, "configurado", lambda: False)
    r = bv.enviar_boas_vindas("a@x.com", "A", "S3nh4!", "https://x")
    assert r["ok"] is False and "Correio" in r["erro"]


def test_a_senha_NAO_vai_para_a_trilha(monkeypatch):
    """A defesa que mais importa. Um audit_log com senhas dentro seria pior
    que o e-mail: o e-mail ao menos expira quando a pessoa troca a senha; a
    trilha fica para sempre e é lida por mais gente."""
    capturado = {}

    def _falso(dests, assunto, corpo, **kw):
        capturado.update({"dests": dests, "corpo": corpo, "kw": kw})
        return {"ok": True, "erro": "", "destinatarios": dests}

    monkeypatch.setattr(bv.cfg, "configurado", lambda: True)
    monkeypatch.setattr(bv.envio, "enviar", _falso)
    bv.enviar_boas_vindas("a@x.com", "Ana", "SenhaSecreta9!", "https://x",
                          telas=["home"], autor="admin@x.com")
    # a senha está no CORPO — é o objetivo do e-mail, texto e HTML
    assert "SenhaSecreta9!" in capturado["corpo"]
    assert "SenhaSecreta9!" in capturado["kw"]["corpo_html"]
    # ...e em NENHUM metadado. São ESTES que a trilha grava em `correio_envios`:
    # quem mandou, de onde veio e para quem foi. O corpo não é registrado.
    for chave in ("usuario", "origem"):
        assert "SenhaSecreta9!" not in str(capturado["kw"].get(chave, "")),             f"senha vazou em {chave}"
    assert capturado["kw"]["origem"] == "boas_vindas"
    assert capturado["kw"]["usuario"] == "admin@x.com"


def test_o_email_de_TESTE_avisa_que_a_senha_nao_vale():
    """Sem a tarja, um teste enviado a um diretor é indistinguível de um
    acesso real — e ele vai tentar entrar com uma senha que não existe."""
    assunto, texto, html = bv.montar("F", "f@x.com", "S3nh4!", "https://x",
                                     telas=["home"], teste=True)
    assert assunto.startswith("[TESTE]")
    assert "e-mail de teste" in html.lower()


def test_perfil_sem_tela_nenhuma_avisa_em_vez_de_sair_vazio():
    """Perfil sem tela liberada é erro de cadastro, e o e-mail é a última
    chance de alguém perceber antes de a pessoa tentar entrar e ver o painel
    em branco."""
    _, _, html = bv.montar("F", "f@x.com", "S3nh4!", "https://x", telas=[])
    assert "ainda não tem telas liberadas" in html


# ── E-MAIL DO CÓRTEX NÃO TEM ÁREA ESCURA ─────────────────────────────────────
# Esta regra já foi quebrada duas vezes — a segunda foi este próprio e-mail,
# que nasceu com faixa navy no topo. Ela volta porque é fácil de esquecer e
# porque nada a cobrava. Agora cobra.

def _luminancia(hexa: str) -> float:
    r, g, b = int(hexa[1:3], 16), int(hexa[3:5], 16), int(hexa[5:7], 16)
    return 0.299*r + 0.587*g + 0.114*b


def _fundos(html: str) -> set:
    return set(re.findall(r"background(?:-color)?:\s*(#[0-9A-Fa-f]{6})", html))


# 110 separa o que exige texto claro por cima do que não exige: o navy
# (#14181D, luminância ~23) e o navy médio (#2C3742, ~53) ficam de fora.
LIMIAR_ESCURO = 110

# A REGRA É SOBRE MOLDURA, NÃO SOBRE COR QUE CARREGA SIGNIFICADO.
#
# O semáforo (#1E7F4F, #B97709, #C03221) tem luminância abaixo do limiar, e
# ainda assim ele FICA: numa barra de "autorizados × rejeitados" a cor é a
# informação, e clareá-la seria inventar tons de estado que o design system
# proíbe justamente para o verde não virar dois verdes.
#
# O laranja (#E85D10) fica porque é o accent documentado para superfície
# clara — é ele que substituiu o amarelo da marca quando o fundo escuro saiu.
#
# O que a regra proíbe é o resto: faixa, cabeçalho, painel e bloco de
# moldura em tom escuro.
EXCECOES = {"#1E7F4F", "#B97709", "#C03221", "#E85D10"}


@pytest.mark.parametrize("caso", ["normal", "admin", "sem_telas", "teste"])
def test_o_email_de_boas_vindas_nao_tem_area_escura(caso):
    """Fundo escuro em e-mail imprime mal, some no modo de leitura de vários
    clientes e briga com o tema escuro do aparelho, que já inverte tudo por
    conta própria. Texto escuro é outra coisa — a regra é sobre ÁREA."""
    _, _, html = bv.montar(
        "Fulano", "f@x.com", "S3nh4!", "https://x",
        telas=[] if caso == "sem_telas" else ["home", "fluxo"],
        admin=(caso == "admin"), teste=(caso == "teste"))
    escuros = {c for c in _fundos(html)
               if _luminancia(c) < LIMIAR_ESCURO and c.upper() not in EXCECOES}
    assert not escuros, f"fundo escuro no e-mail: {sorted(escuros)}"


def test_o_layout_compartilhado_nao_tem_area_escura():
    """A regra tem de valer para TODO e-mail, não só para este. É por isso que
    o layout é um módulo só: o relatório agendado sai pelo mesmo caminho."""
    from api.correio import painel as p
    html = p.documento("T", [
        p.cabecalho("Relatório", "subtítulo"),
        p.secao("Seção", "hint"),
        p.kpis([{"rotulo": "A", "valor": "1", "estado": "ok"}]),
        p.tabela(["a", "b"], [["1", "2"]]),
        p.paragrafo("texto", destaque=True),
        p.barras([{"rotulo": "x", "valor": 10}]),
        p.botao("Entrar", "https://x"),
        p.campos([("Rótulo", "valor")], titulo="Caixa"),
    ], origem="teste")
    escuros = {c for c in _fundos(html)
               if _luminancia(c) < LIMIAR_ESCURO and c.upper() not in EXCECOES}
    assert not escuros, f"fundo escuro no layout: {sorted(escuros)}"


def test_a_MARCA_aparece_no_email_e_o_amarelo_nao():
    """O e-mail é onde a marca aparece no tom ORIGINAL, e é medido: `#942821`
    rende **8,12:1 sobre branco**. No painel ele daria 1,92:1 sobre o navy da
    barra lateral, e por isso lá existe uma versão clareada — aqui a superfície
    é branca, então não há adaptação a fazer.

    O amarelo `#FFD31C` que este projeto chamava de "marca" continua barrado:
    1,44:1 no branco, e sobretudo **não é a marca** — o usuário corrigiu, e a
    paleta real saiu dos arquivos de marca do próprio repositório.

    Asserção nos DOIS sentidos de propósito: só provar a ausência do amarelo
    passaria com o e-mail sem identidade nenhuma, que é exatamente o estado de
    onde este trabalho partiu."""
    from api.correio import painel as p
    html = p.documento("T", [p.cabecalho("R")], origem="t")
    assert "#FFD31C" not in html.upper()
    assert "#942821" in html.upper(), "o e-mail saiu sem a cor da marca"
    assert "#1E172F" in html.upper(), "o título saiu sem a tinta da marca"


@pytest.mark.parametrize("relatorio", ["contrapartida", "acoes_pendentes", "digest"])
def test_os_relatorios_agendados_tambem_nao_tem_area_escura(relatorio):
    """A regra vale para TODO e-mail do sistema. Os relatórios agendados são
    os que mais saem — e eram eles que tinham a faixa navy no topo."""
    from api.correio import relatorios as rel
    try:
        r = rel.montar(relatorio)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"relatório indisponível sem banco: {type(exc).__name__}")
    html = r.get("html", "") if isinstance(r, dict) else ""
    escuros = {c for c in _fundos(html)
               if _luminancia(c) < LIMIAR_ESCURO and c.upper() not in EXCECOES}
    assert not escuros, f"fundo escuro em {relatorio}: {sorted(escuros)}"
