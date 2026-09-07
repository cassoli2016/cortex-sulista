# -*- coding: utf-8 -*-
"""A Central de Integracoes: a juncao de duas fontes que ja existiam.

A pergunta "a integracao X esta bem?" tinha resposta em dois lugares e inteira
em nenhum: Gestao > Integracoes diz se esta CONFIGURADA, a Saude do Servidor
diz se esta CHEGANDO DADO. Uma integracao pode estar configurada e parada ha
cinco dias -- e e a JUNCAO que responde se da para confiar no numero que a tela
de Telemetria esta mostrando agora.

O RISCO DESTE MODULO E A PONTE. `CARTAO_DA_SAUDE` casa a chave do fornecedor
com o NOME do cartao na Saude, e e um mapa escrito a mao. Mapa escrito a mao
deixou DOIS guards cegos nesta casa nesta semana (`MODULOS_SQL` sem o proprio
modulo do agrupador; a lista de agendadores nomeando "aviso-carga" quando a
thread se chama "rastreio-aviso"). Por isso os dois lados sao conferidos aqui:
todo nome mapeado EXISTE entre os cartoes, e todo fornecedor externo do cofre
esta mapeado ou declarado como sob demanda.
"""
from __future__ import annotations

import pytest

from api import credenciais, integracoes as it


# ============================================================ a ponte

def test_todo_nome_mapeado_EXISTE_entre_os_cartoes_da_saude():
    """Renomear um cartao na Saude deixaria a integracao correspondente sem
    chegada de dado -- em silencio, mostrando "ainda nao tem medicao" para uma
    coleta que esta viva. Ausencia nao tem sintoma, entao ela leva guard."""
    from api import servidor
    nomes = {c.get("nome") for c in servidor._servicos()}
    fora = {k: v for k, v in it.CARTAO_DA_SAUDE.items() if v not in nomes}
    assert not fora, (
        "estes cartoes da Saude foram renomeados ou sumiram, e o mapa de "
        "api/integracoes.py ficou apontando para o nome antigo: %s.\n"
        "Cartoes que existem hoje: %s" % (fora, sorted(nomes)))


def test_todo_fornecedor_EXTERNO_do_cofre_esta_declarado():
    """O outro lado: integracao nova entra no cofre de credenciais e aparece
    nesta tela sozinha -- mas sem cartao e sem declaracao ela apareceria com
    "ainda nao tem medicao", que e uma frase, nao uma decisao.

    Aqui se cobra a DECISAO: ou tem cartao na Saude, ou esta declarada como
    consultada sob demanda, ou esta declarada como nao-fornecedor. Nenhuma das
    tres e o padrao -- alguem tem de escolher.
    """
    chaves = {s["chave"] for s in credenciais.SERVICOS}
    decididas = (set(it.CARTAO_DA_SAUDE) | set(it.SOB_DEMANDA)
                 | set(it.NAO_SAO_FORNECEDOR))
    fora = sorted(chaves - decididas)
    assert not fora, (
        "integracao(oes) no cofre sem decisao em api/integracoes.py: %s.\n"
        "Escolha uma: CARTAO_DA_SAUDE (tem coleta que pode parar), "
        "SOB_DEMANDA (consultada na hora, nao ha coleta que envelheca) ou "
        "NAO_SAO_FORNECEDOR (nao e integracao externa)." % fora)


def test_o_mapa_nao_inventa_fornecedor():
    """A ponte tambem nao pode citar chave que o cofre nao tem: seria um cartao
    da Saude casado com um fornecedor que nao existe, e o teste de cima
    passaria por vacuidade sobre ele."""
    chaves = {s["chave"] for s in credenciais.SERVICOS}
    for mapa, rot in ((it.CARTAO_DA_SAUDE, "CARTAO_DA_SAUDE"),
                      (it.SOB_DEMANDA, "SOB_DEMANDA"),
                      (it.NAO_SAO_FORNECEDOR, "NAO_SAO_FORNECEDOR")):
        fora = sorted(set(mapa) - chaves)
        assert not fora, "%s cita chave que nao existe no cofre: %s" % (rot, fora)


# ============================================== o semaforo vale o PIOR

def _cartao(nome, status, detalhe="x"):
    return {"nome": nome, "status": status, "detalhe": detalhe}


def test_configurada_com_a_coleta_PARADA_nao_e_em_dia():
    """O motivo de a tela existir, em um teste. Nas duas telas antigas isto
    aparecia como dois verdes em lugares diferentes: 'credencial ok' numa,
    'coleta parada' na outra, e ninguem juntava."""
    d = it.panorama([_cartao(it.CARTAO_DA_SAUDE["gobrax"], "alerta",
                             "atualizado ha 5 dias")])
    gob = next(i for i in d["integracoes"] if i["chave"] == "gobrax")
    assert gob["chegada"]["status"] == "alerta"
    if gob["configuracao"]["status"] == "ok":
        assert gob["estado"] == "alerta", (
            "configuracao em dia com coleta parada nao pode sair como 'em dia'")


def test_desligada_NAO_e_vermelho():
    """Integracao que ninguem contratou nao e defeito, e recurso que nao existe
    nesta instalacao. Pintar de vermelho o que esta certo e como se ensina a
    ignorar vermelho."""
    for linha in it.panorama([])["integracoes"]:
        if linha["configuracao"]["estado"] == "desligada":
            assert linha["estado"] != "erro", linha["nome"]


@pytest.mark.parametrize("estados,esperado", [
    (("ok", "ok"), "ok"),
    (("ok", "alerta"), "alerta"),
    (("alerta", "erro"), "erro"),
    (("info", "ok"), "info"),
    ((None, "ok"), "ok"),
    ((None, None), "info"),
])
def test_o_pior_dos_dois_lados(estados, esperado):
    assert it._pior(*estados) == esperado


# ====================================== sob demanda nao e coleta parada

def test_fornecedor_sob_demanda_nao_acende_alarme():
    """TomTom e QualP sao consultados na hora, por viagem e por rota. Nao ha
    "ultima coleta" para envelhecer -- cobrar frescor deles acenderia alarme
    todo dia com tudo funcionando, e alarme diario vira ruido."""
    d = it.panorama([])
    for chave in it.SOB_DEMANDA:
        linha = next((i for i in d["integracoes"] if i["chave"] == chave), None)
        if linha is None:
            continue
        assert linha["chegada"]["regime"] == "sob_demanda"
        assert linha["chegada"]["status"] == "info"
        assert linha["estado"] != "erro"


def test_o_que_nao_e_fornecedor_fica_de_fora():
    """`cortex` e o endereco do proprio painel e `motorista_mestre` e um
    segredo NOSSO. Os dois moram no cofre porque e la que a tela de
    configuracao le -- aqui virariam integracoes que nunca respondem."""
    chaves = {i["chave"] for i in it.panorama([])["integracoes"]}
    assert not (chaves & it.NAO_SAO_FORNECEDOR)


# ============================================== nao vaza segredo, nunca

def test_o_panorama_NAO_carrega_valor_de_credencial():
    """E isto que permite a tela ser de RBAC normal em vez de viver atras de
    /api/gestao: ela diz que falta um token, nunca qual e.

    Confere contra os valores REAIS do cofre desta instalacao -- um duble
    provaria o duble. Onde nao ha valor configurado o teste nao afirma nada
    (e o `skip` diz isso, em vez de passar em silencio)."""
    import json

    valores = []
    for nome in credenciais.CONHECIDAS:
        v = credenciais.ler(nome)
        if v and len(v) >= 8:
            valores.append(v)
    if not valores:
        pytest.skip("nenhuma credencial configurada nesta instalacao")

    texto = json.dumps(it.panorama([]), ensure_ascii=False)
    vazou = [n for n, v in zip(credenciais.CONHECIDAS, valores) if v in texto]
    assert not vazou, "o panorama carregou o VALOR de: %s" % vazou


# ================================================ o detalhe que o modal abre

def _dicts(no):
    """Todo dicionario da arvore, em qualquer profundidade."""
    if isinstance(no, dict):
        yield no
        for v in no.values():
            yield from _dicts(v)
    elif isinstance(no, list):
        for v in no:
            yield from _dicts(v)


def test_o_detalhe_do_modal_NAO_tem_chave_de_valor_em_lugar_nenhum():
    """O irmao ESTRUTURAL do teste acima, e a razao de existir separado.

    `test_o_panorama_NAO_carrega_valor_de_credencial` compara com os valores
    REAIS do cofre -- o que e mais forte onde ha o que comparar, e um `skip`
    onde nao ha. Numa worktree limpa, num CI, ou numa instalacao que ainda nao
    configurou nada, ele nao afirma coisa alguma: seria um guard verde por
    vacuidade justamente onde ninguem esta olhando.

    Este afirma sobre a FORMA e roda sempre: nenhum dicionario do panorama, em
    profundidade nenhuma, pode carregar `valor` ou `mascarado`. Sao as duas
    chaves que `credenciais.status()` produz e que fariam a tela mostrar (ou
    deixar mostravel no HTML) o conteudo de uma credencial.
    """
    proibidas = {"valor", "mascarado"}
    achadas = [(d.get("rotulo") or d.get("chave") or d.get("nome"), k)
               for d in _dicts(it.panorama([]))
               for k in proibidas & set(d)]
    assert not achadas, "o detalhe do modal carregou %s" % (achadas,)


def test_o_resumo_do_campo_e_LISTA_DE_PERMISSAO_e_nao_copia_e_apaga():
    """Campo novo no catalogo de credenciais tem de entrar INVISIVEL.

    Copiar o dicionario e apagar as chaves ruins tem o defeito oposto -- a
    chave nova entra visivel, e a falha nao tem sintoma nenhum: a tela
    continua pintando, so que com uma coisa a mais dentro do HTML.
    """
    campo = {"rotulo": "Token", "obrigatorio": True, "configurado": True,
             "segredo": True, "valor": "abc", "mascarado": "ab…c",
             "chave_que_ninguem_previu": "conteudo"}
    assert set(it._campo_publico(campo)) == {
        "rotulo", "obrigatorio", "configurado", "segredo"}


def test_o_modal_sabe_ONDE_se_edita_e_ONDE_se_mede():
    """As duas pontas que o modal nomeia. `aba` existe para quem se configura
    em OUTRO lugar (o SMTP na aba de E-mail, a Z-API na de WhatsApp) -- sem
    ela o modal ofereceria um formulario que nao e o que vale, e editar a mesma
    senha em dois lugares e o que fazia salvar num e conferir no outro."""
    por_chave = {l["chave"]: l for l in it.panorama([])["integracoes"]}

    assert por_chave["smtp"]["aba"] == "email"
    assert por_chave["zapi"]["aba"] == "whatsapp"
    assert por_chave["gobrax"]["aba"] is None, (
        "a Gobrax se configura no proprio modal; apontar para uma aba mandaria "
        "quem opera para uma tela que nao tem o campo dela")

    assert por_chave["gobrax"]["cartao_saude"] == it.CARTAO_DA_SAUDE["gobrax"]
    assert por_chave["qualp"]["cartao_saude"] is None, (
        "fornecedor sob demanda nao tem cartao de chegada para nomear")


def test_todo_modo_de_autenticacao_chega_com_os_campos_dele():
    """A Prolog aceita tres formas e o cliente usa a PRIMEIRA completa. Sem os
    campos de cada uma, o modal diria "tres formas" sem dizer o que preencher
    em qualquer uma delas."""
    prolog = next(l for l in it.panorama([])["integracoes"]
                  if l["chave"] == "prolog")
    modos = prolog["configuracao"]["modos"]
    assert [m["chave"] for m in modos] == ["token", "basic", "oauth"]
    assert all(m["campos"] for m in modos), (
        "modo sem campo nenhum e um formulario vazio no modal")
    # E o catalogo real e a referencia: nao inventar rotulo aqui.
    catalogo = next(s for s in credenciais.SERVICOS if s["chave"] == "prolog")
    assert [m["rotulo"] for m in modos] == [m["rotulo"] for m in catalogo["modos"]]


# ============================================================ a rota e a tela

def test_a_rota_exige_sessao():
    from fastapi.testclient import TestClient
    from api import main
    # TestClient FORA de `with`: sem lifespan. O `_startup_auth` aplicaria
    # migration no schema de PRODUCAO.
    cliente = TestClient(main.app)
    assert cliente.get("/api/integracoes").status_code == 401


def test_a_tela_esta_registrada_no_RBAC():
    """Tela de RBAC NORMAL, e nao mais uma coisa atras de /api/gestao: quem
    opera precisa saber que a telemetria parou de chegar sem depender de um
    administrador."""
    from api import auth
    assert "integ" in auth.TELAS
    assert auth.TELAS["integ"][1] == "Administração"
    assert not auth.rota_sem_tela("/api/integracoes"), (
        "a rota nao pode ser de todo usuario logado: ela e da tela `integ`")
    alvo = [telas for rota, telas in auth.ROTA_TELAS
            if rota == "/api/integracoes"]
    assert alvo == [frozenset({"integ"})], alvo


def test_a_rota_NAO_esta_sob_api_gestao():
    """Se estivesse, o middleware a trataria como admin e a decisao de abrir a
    tela por perfil viraria letra morta."""
    assert not any(r.startswith("/api/gestao") and "integ" in t
                   for r, t in auth_rotas())


def auth_rotas():
    from api import auth
    return [(r, t) for r, t in auth.ROTA_TELAS]
