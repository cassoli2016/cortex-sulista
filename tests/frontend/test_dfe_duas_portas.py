"""A tela de Notas de Entrada com as DUAS portas — no navegador.

NO NAVEGADOR, e nao no texto do arquivo, pela mesma razao do guard do
certificado ao lado: a versao de texto-fonte deste arquivo passaria com o
codigo dentro de um `if(false)`. E ja houve um defeito aqui que so o navegador
pega -- `window.USER` contra `USER`, que e `let` de topo.

O QUE ESTE ARQUIVO PROTEGE:

  - o documento que chegou por e-mail NAO tem NSU, e o link do XML dele nao
    pode ser montado com `cnpj=&nsu=` (baixaria nada, sem erro);
  - "sem protocolo" e "so resumo" sao badges DIFERENTES, porque pedem coisas
    diferentes de quem le;
  - a coluna Origem diz de onde veio e QUEM mandou.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

CHAVE_SEFAZ = "41260912345678000199550010000012341000012349"
CHAVE_MAIL = "35260902258243000400550020002355131539874225"
SHA = "b" * 64

CAIXAS = {
    "caixas": [
        {"cnpj": "76104397000123", "apelido": "FIL MTZ", "uf": "PR",
         "ultimo_nsu": "000000001144010", "max_nsu": "000000001144010",
         "falta": 0, "ultima_consulta": "2026-09-08T08:40:00-03:00",
         "idade_h": 1.0, "cstat": "137", "motivo": "Nenhum documento",
         "parada": False,
         "certificado": {"cnpj": "76104397000123", "tem_certificado": True,
                         "valida_ate": "2026-09-29", "dias": 22,
                         "vencido": False, "erro": None},
         "documentos": {"total": 1, "pendentes": 0}},
    ],
    "total": {"total": 1, "pendentes": 0, "nfe": 1, "cte": 0, "eventos": 0,
              "email": 2, "email_sem_protocolo": 1},
    # O ESTADO DA SEGUNDA PORTA, como o servidor manda quando ela ainda nao foi
    # configurada -- que e o estado real no dia da entrega.
    "email": {"configurada": False, "caixa": "", "falta": ["ID do tenant"],
              "mensagens": 0, "vazias": 0, "ultima_mensagem": None,
              "ultima_coleta": None, "ultimo_sucesso": None, "ultimo_erro": None,
              "arquivos": {"total": 2, "email": 1, "upload": 1, "completos": 1,
                           "ultimo": "2026-09-08T12:00:00-03:00"}},
    "documentos": [
        {"cnpj": "76104397000123", "nsu": "000000001144010", "tipo": "nfe",
         "chave": CHAVE_SEFAZ, "emitente_nome": "RAIZEN S.A.",
         "emitente": "33453598024499", "destinatario": "76104397000123",
         "valor": 31250.0, "emitido_em": "2026-09-08T02:13:48-03:00",
         "situacao": "100", "completo": True, "descricao": None,
         "evento_tipo": None, "origem": "sefaz", "sha256": None,
         "remetente": None, "eventos": [], "cancelada": False,
         "tem_carta": False},
        {"cnpj": None, "nsu": None, "tipo": "nfe", "chave": CHAVE_MAIL,
         "emitente_nome": "FORNECEDOR DO CLIENTE LTDA",
         "emitente": "02258243000400", "destinatario": "98765432000188",
         "valor": 1840.30, "emitido_em": "2026-09-07T10:00:00-03:00",
         "situacao": "100", "completo": True, "descricao": None,
         "evento_tipo": None, "origem": "email", "sha256": SHA,
         "remetente": "expedicao@cliente.com.br", "eventos": [],
         "cancelada": False, "tem_carta": False},
        {"cnpj": None, "nsu": None, "tipo": "nfe", "chave": "9" * 44,
         "emitente_nome": "OUTRO FORNECEDOR", "emitente": "11111111111111",
         "destinatario": "98765432000188", "valor": 100.0,
         "emitido_em": "2026-09-06T10:00:00-03:00", "situacao": None,
         "completo": False, "descricao": None, "evento_tipo": None,
         "origem": "upload", "sha256": "c" * 64,
         "remetente": "operador@sulista.com.br", "eventos": [],
         "cancelada": False, "tem_carta": False},
    ],
}


def _abrir(pg, base_url, enviado=None, resposta=None):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo, status = ADMIN, 200
        elif "/api/dfe/arquivo" in u:
            if enviado is not None:
                enviado.append(json.loads(route.request.post_data))
            corpo, status = (resposta or {"ok": True, "documentos": 1,
                                          "novos": 1, "repetidos": 0,
                                          "falhas": 0, "ignorados": []}), 200
        elif "/api/dfe" in u:
            corpo, status = CAIXAS, 200
        else:
            corpo, status = {}, 200
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#dfe")
    pg.wait_for_selector("#dfe-docs tr", state="attached", timeout=20000)
    return erros


def test_a_tela_abre_sem_erro_com_as_duas_portas(pagina):
    pg, base = pagina
    assert _abrir(pg, base) == []


def test_o_documento_de_EMAIL_baixa_pelo_sha_e_nao_por_nsu(pagina):
    """O DEFEITO QUE ISTO IMPEDE E MUDO: o documento que chegou por e-mail nao
    tem NSU, e um link montado com `cnpj=&nsu=` levaria a uma resposta vazia
    sem erro nenhum na tela -- o botao existe, a pessoa clica, nao vem nada.
    """
    pg, base = pagina
    _abrir(pg, base)
    linha = pg.inner_html("#dfe-docs tr:nth-child(2)")
    assert "sha=" + SHA in linha, linha
    assert "nsu=" not in linha
    # e o da SEFAZ continua pelo par (cnpj, nsu), que e o endereco dele
    primeira = pg.inner_html("#dfe-docs tr:nth-child(1)")
    assert "nsu=000000001144010" in primeira and "sha=" not in primeira


def test_a_coluna_ORIGEM_diz_a_porta_e_quem_mandou(pagina):
    pg, base = pagina
    _abrir(pg, base)
    linhas = pg.inner_text("#dfe-docs")
    assert "SEFAZ" in linhas and "NSU 000000001144010" in linhas
    assert "e-mail" in linhas and "expedicao@cliente.com.br" in linhas
    assert "enviado na tela" in linhas


def test_SEM_PROTOCOLO_nao_se_confunde_com_SO_RESUMO(pagina):
    """As duas sao ausencia do mesmo XML e pedem coisas DIFERENTES: uma espera
    a manifestacao de ciencia (e ha o que fazer sobre isso), a outra pede o
    arquivo certo a quem enviou. Um rotulo so mandaria alguem procurar uma
    manifestacao que nao existe."""
    pg, base = pagina
    _abrir(pg, base)
    terceira = pg.inner_text("#dfe-docs tr:nth-child(3)")
    assert "sem protocolo" in terceira
    assert "só resumo" not in terceira


def test_enviar_um_XML_pela_tela_manda_o_arquivo_e_avisa(pagina):
    """A porta que funciona sem depender da TI: enquanto o aplicativo do
    Microsoft 365 nao existe, quem recebeu a nota no proprio e-mail arrasta o
    arquivo aqui."""
    pg, base = pagina
    enviado = []
    _abrir(pg, base, enviado=enviado)
    pg.set_input_files("#dfe-arq", {
        "name": "nota.xml", "mimeType": "application/xml",
        "buffer": b"<nfeProc><NFe/></nfeProc>"})
    pg.wait_for_function(
        "() => (document.getElementById('dfe-env-msg')||{}).textContent"
        "        .includes('guardado')", timeout=15000)
    assert len(enviado) == 1
    assert enviado[0]["nome"] == "nota.xml"
    assert enviado[0]["conteudo_b64"], "o arquivo nao foi junto"
    # O CAMPO SE LIMPA: sem isso, escolher o MESMO arquivo de novo nao dispara
    # `change` nenhum e a tela parece travada.
    assert pg.eval_on_selector("#dfe-arq", "el => el.value") == ""


def test_arquivo_RECUSADO_diz_o_motivo_de_cada_um(pagina):
    """"Nao deu certo" sem dizer o que veio faz a pessoa tentar o mesmo arquivo
    de novo."""
    pg, base = pagina
    _abrir(pg, base, resposta={"erro": "sem_documento",
                               "mensagem": "Nenhum documento fiscal neste arquivo.",
                               "ignorados": ["danfe.pdf: raiz '?' não é documento fiscal"]})

    # a rota devolve 200 no dublê acima; aqui o que se afirma é o caminho da
    # RECUSA, então a resposta precisa vir como recusa de verdade
    def rota(route):
        u = route.request.url
        if "/api/dfe/arquivo" in u:
            route.fulfill(status=409, content_type="application/json",
                          body=json.dumps({
                              "erro": "sem_documento",
                              "mensagem": "Nenhum documento fiscal neste arquivo."}))
        elif "/api/auth/me" in u:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(ADMIN))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(CAIXAS))

    pg.route("**/api/**", rota)
    pg.set_input_files("#dfe-arq", {
        "name": "danfe.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"})
    pg.wait_for_function(
        "() => (document.getElementById('dfe-env-msg')||{}).textContent"
        "        .includes('danfe.pdf')", timeout=15000)


def test_o_KPI_soma_as_duas_portas_e_diz_quanto_e_de_cada(pagina):
    """O total e o que decide; a procedencia vai no sub-rotulo. Um numero que
    escondesse a segunda porta faria a pessoa achar que a recolha trouxe menos
    do que trouxe."""
    pg, base = pagina
    _abrir(pg, base)
    banda = pg.inner_text("#dfe-kpis")
    # A FRASE INTEIRA, e nao "3 aparece em algum lugar": a banda tem cinco
    # cards cheios de numero, e `"3" in banda` seria verde com qualquer coisa.
    assert "2 por e-mail · 1 recolhidos da SEFAZ" in banda, banda
