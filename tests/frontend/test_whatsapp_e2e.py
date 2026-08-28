"""A aba WhatsApp da tela de Gestão, no navegador.

Dois riscos que só aparecem aqui e nenhum teste de backend pega:

1. **O campo de segredo não pode voltar preenchido.** Os três tokens da Z-API
   nunca saem do servidor; se um dia a tela passasse a exibi-los, o teste de
   backend continuaria verde — é o `value` do input que denuncia.
2. **O número que decide o envio tem de estar ao lado do botão que envia.**
   "Quantos destinatários diferentes já foram hoje" enterrado numa aba de
   configuração é o mesmo que não existir na hora de mandar.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

CONFIG = {
    "ativo": True, "limite_dia": 60, "intervalo_seg": 5,
    "janela_inicio": "08:00", "janela_fim": "20:00",
    "assinatura": "Sulista Transportes", "atualizado_em": "2026-08-27 09:00:00",
    "credenciais_ok": True, "instancia": "3D2F…9077", "token_ok": True,
    "client_token_ok": True, "pronto": True, "dentro_da_janela": True,
    "limite_max": 500,
}
RESPOSTA = {
    "config": CONFIG,
    "conexao": {"ok": True, "conectado": True, "celular": True, "erro": "",
                "configurado": True, "em": "2026-08-27 09:10:00"},
    "resumo": {"total": 3, "ok": 2, "falha": 1, "numeros": 2, "hoje": 41,
               "ultimo": "2026-08-27 09:05:00"},
    "envios": [
        {"id": 3, "ts": "2026-08-27 09:05:00", "usuario": "ana@sulista",
         "telefone": "5547999998888", "mensagem": "Sua carga saiu.",
         "origem": "manual", "ok": 1, "erro": "", "message_id": "D24..."},
        {"id": 2, "ts": "2026-08-27 08:40:00", "usuario": "ana@sulista",
         "telefone": "5511988887777", "mensagem": "", "origem": "manual",
         "ok": 0, "erro": "Limite diário atingido", "message_id": ""},
    ],
}


def _abrir(pg, base_url, resposta=None):
    def rota(route):
        u = route.request.url
        corpo = (ADMIN if "/api/auth/me" in u
                 else (resposta or RESPOSTA) if "/gestao/whatsapp" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-whatsapp", timeout=20000)
    pg.click("#gtab-whatsapp")
    pg.wait_for_timeout(600)
    return erros


def test_a_aba_abre_e_carrega_sem_erro(pagina):
    pg, base = pagina
    erros = _abrir(pg, base)
    assert erros == []
    assert pg.is_visible("#gpane-whatsapp")


def test_os_tres_campos_de_segredo_ficam_VAZIOS(pagina):
    """Nem o token, nem o id da instância — que na Z-API é metade da
    credencial, porque os dois formam a URL."""
    pg, base = pagina
    _abrir(pg, base)
    for campo in ("#wa-inst", "#wa-tok", "#wa-ctok"):
        assert pg.input_value(campo) == "", f"{campo} voltou preenchido"
        assert pg.get_attribute(campo, "type") == "password"


def test_o_gasto_do_dia_aparece_no_cartao_de_ENVIAR(pagina):
    """Não na configuração: a pergunta "ainda posso mandar?" nasce na hora de
    mandar."""
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#wa-envio-hint")
    assert "41 de 60" in txt and "restam 19" in txt


def test_desconectado_aparece_no_topo_e_nao_so_no_erro(pagina):
    """Enquanto a instância está fora, a Z-API aceita e enfileira: o estado
    tem de ser visível ANTES de alguém tentar enviar."""
    pg, base = pagina
    fora = {**RESPOSTA, "conexao": {"ok": True, "conectado": False,
                                    "celular": False, "configurado": True,
                                    "erro": "You are not connected."}}
    _abrir(pg, base, fora)
    txt = pg.inner_text("#wa-conexao")
    assert "desconectado" in txt.lower()


def test_o_telefone_da_trilha_e_mostrado_formatado(pagina):
    """O banco guarda só dígitos para o contador de destinatários funcionar;
    ninguém lê telefone assim."""
    pg, base = pagina
    _abrir(pg, base)
    assert "(47) 99999-8888" in pg.inner_text("#wa-hist")


def test_recusa_registrada_aparece_como_NAO_SAIU_com_o_motivo(pagina):
    """A trilha guarda a recusa junto com o envio — é o registro dela que
    responde por que a mensagem não saiu."""
    pg, base = pagina
    _abrir(pg, base)
    html = pg.inner_html("#wa-hist")
    assert "não saiu" in html
    assert "Limite diário atingido" in html


# ------------------------------------------------------- duas instâncias

def _inst(chave, rotulo, *, configurado=True, conectado=True, hoje=0):
    return {"chave": chave, "rotulo": rotulo, "configurado": configurado,
            "instancia": "3D2F…9077" if configurado else "",
            "client_token_ok": False, "hoje": hoje,
            "conexao": {"ok": configurado, "conectado": conectado,
                        "celular": conectado, "configurado": configurado,
                        "erro": "" if conectado else "não pareada"}}


SO_UMA = {**RESPOSTA, "instancias": [
    _inst("principal", "Principal", hoje=41),
    _inst("backup", "Reserva", configurado=False, conectado=False)]}

AS_DUAS = {**RESPOSTA,
           "resumo": {**RESPOSTA["resumo"], "hoje_por_instancia":
                      {"principal": 41, "backup": 3}},
           "instancias": [_inst("principal", "Principal", hoje=41),
                          _inst("backup", "Reserva", hoje=3)]}


def test_com_uma_instancia_o_seletor_NAO_aparece(pagina):
    """Escolha de um item é ruído — e pior, sugere um reserva que ninguém
    cadastrou."""
    pg, base = pagina
    _abrir(pg, base, SO_UMA)
    assert pg.get_attribute("#wa-inst-box", "hidden") is not None
    assert "não configurada" in pg.inner_text("#wa-conexao2")


def test_com_duas_o_seletor_aparece_com_a_cota_de_CADA_numero(pagina):
    """A pergunta "ainda posso mandar?" tem resposta diferente para cada
    aparelho: a cota é por número, porque a reputação é dele."""
    pg, base = pagina
    _abrir(pg, base, AS_DUAS)
    assert pg.get_attribute("#wa-inst-box", "hidden") is None
    opcoes = pg.inner_text("#wa-envinst")
    assert "Principal" in opcoes and "41 hoje" in opcoes
    assert "Reserva" in opcoes and "3 hoje" in opcoes


def test_reserva_desconectado_aparece_no_seletor_e_no_cabecalho(pagina):
    """Escolher um aparelho fora do ar sem aviso é mandar para uma fila que
    dispara sozinha depois."""
    pg, base = pagina
    resposta = {**AS_DUAS, "instancias": [
        _inst("principal", "Principal", hoje=41),
        _inst("backup", "Reserva", conectado=False, hoje=3)]}
    _abrir(pg, base, resposta)
    assert "desconectado" in pg.inner_text("#wa-envinst")
    assert "não conectada" in pg.inner_text("#wa-conexao2")


def test_a_trilha_diz_por_qual_numero_cada_mensagem_saiu(pagina):
    pg, base = pagina
    resposta = {**AS_DUAS, "envios": [
        {"id": 9, "ts": "2026-08-28 10:00:00", "usuario": "ana@sulista",
         "telefone": "5547999998888", "mensagem": "oi", "origem": "manual",
         "ok": 1, "erro": "", "message_id": "M", "modelo": "",
         "instancia": "backup"}]}
    _abrir(pg, base, resposta)
    assert "Reserva" in pg.inner_text("#wa-hist")


def test_salvar_reserva_DESCONECTADA_confirma_que_salvou(pagina):
    """O caso real: um número reserva fica cadastrado e PARADO, esperando o dia
    em que for preciso. Se o resultado do teste de conexão ("reserva: não
    conectada") caísse por cima da confirmação, a tela diria que falhou
    justamente no caso que ela precisa aceitar — e a pessoa tentaria de novo
    achando que não gravou.
    """
    pg, base = pagina
    salvos = []

    resposta = {**AS_DUAS, "instancias": [
        _inst("principal", "Principal", hoje=41),
        _inst("backup", "Reserva", conectado=False, hoje=0)]}

    def rota(route):
        u, req = route.request.url, route.request
        if "/api/gestao/credenciais" in u and req.method == "POST":
            salvos.append(json.loads(req.post_data or "{}")["nome"])
            corpo = {"ok": True}
        elif "/whatsapp/conexao" in u:
            corpo = ({"conectado": True, "erro": ""} if "principal" in u
                     else {"conectado": False, "erro": "não pareada"})
        elif "/api/auth/me" in u:
            corpo = ADMIN
        elif "/gestao/whatsapp" in u:
            corpo = resposta
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-whatsapp", timeout=20000)
    pg.click("#gtab-whatsapp")
    pg.wait_for_timeout(600)

    pg.fill("#wa-inst2", "77AA11BB22CC3344")
    pg.fill("#wa-tok2", "99DD88EE77FF6655")
    pg.click("#wa-cred-salvar")
    pg.wait_for_timeout(900)

    assert salvos == ["ZAPI2_INSTANCIA", "ZAPI2_TOKEN"], salvos
    texto = pg.inner_text("#wa-cred-err")
    assert "salvas" in texto, f"a confirmação sumiu: {texto!r}"
    # o estado da reserva aparece JUNTO, sem apagar a confirmação
    assert "reserva" in texto.lower()
    # e os campos de segredo ficam vazios depois de salvos
    assert pg.input_value("#wa-inst2") == "" and pg.input_value("#wa-tok2") == ""


def test_reserva_desconectada_ainda_assim_fica_no_cadastro(pagina):
    """Salvar não depende de estar conectada — e a tela diz isso, para ninguém
    achar que precisa parear antes de cadastrar."""
    pg, base = pagina
    resposta = {**AS_DUAS, "instancias": [
        _inst("principal", "Principal", hoje=41),
        _inst("backup", "Reserva", conectado=False, hoje=0)]}
    _abrir(pg, base, resposta)
    nota = pg.inner_text(".wa-inst-nota")
    assert "cadastrado e desconectado" in nota
    assert "salvas do mesmo jeito" in nota
