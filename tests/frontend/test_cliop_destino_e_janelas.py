"""A tela Minha Operação com destinatário e janelas — NO NAVEGADOR.

No navegador, e não no texto do arquivo, porque a versão de texto-fonte deste
arquivo passaria com o código dentro de um `if(false)` — e porque os três
defeitos que este arquivo protege são todos MUDOS: eles não quebram a tela,
eles fazem uma informação não aparecer.

O QUE ESTE ARQUIVO PROTEGE:

  - a carga que CHEGOU continua na lista (ela sumia no instante da chegada,
    apagando as horas de veículo parado no pátio do cliente);
  - a carga PROGRAMADA aparece com a janela de carregamento, em vez de sumir;
  - cada linha diz DE ONDE veio o estado dela — apontamento, manifesto ou só
    a programação têm precisões diferentes;
  - o destinatário aparece, e é ele que separa duas docas na MESMA cidade;
  - o desvio da janela sai como CONTA (horas, com sinal) e nunca como veredito.

O PAYLOAD É COPIADO DO REAL. Ele foi tirado de uma resposta de produção em
09/09/2026 e teve os identificadores trocados por fictícios — a FORMA é a de
verdade (campos, tipos, o `marco_fonte` de cada caso, a janela em
"AAAA-MM-DD HH:MM"), que é o que faz o dublê testar alguma coisa. Dublê montado
a partir do que o consumidor espera testa o consumidor contra ele mesmo.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from tests.frontend.conftest import USUARIO

CASA = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _h(horas: float) -> str:
    """Horário relativo ao relógio, no formato da rota.

    Data fixa aqui acusaria a pessoa errada: a tela compara a janela com AGORA
    para decidir o que já venceu, e um literal de setembro de 2026 vira
    "venceu há meses" no dia seguinte ao commit.
    """
    return (datetime.now() + timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M")


def _carga(**kw):
    base = {
        "coleta": 1, "emissao": "2026-09-09",
        "origem": "CIDADE A", "uf_origem": "SP",
        "destino": "CIDADE B", "uf_destino": "RJ",
        "destinatario": "MONTADORA - CIDADE B/RJ",
        "placa": "AAA1A11",
        "marco": "Em viagem", "marco_cod": 400, "marco_em": _h(-3),
        "marco_fonte": "apontamento",
        "janela_carga": _h(-6), "janela_entrega": _h(2),
        "chegada": None, "chegada_fonte": None, "desvio_h": None,
        "pos": None, "eta": None, "eta_amostras": None,
    }
    base.update(kw)
    return base


# As quatro situações que a tela precisa saber distinguir, e que antes desta
# entrega ou não apareciam ou apareciam iguais.
CARGAS = [
    # 1) CHEGOU e ainda não descarregou -- a que sumia da tela.
    _carga(coleta=20222, marco="Chegada para descarga", marco_cod=396,
           marco_em=_h(-2), marco_fonte="apontamento",
           destinatario="MONTADORA - CIDADE B/RJ",
           janela_entrega=_h(-2.5), chegada=_h(-2),
           chegada_fonte="apontamento", desvio_h=0.5),
    # 2) chegou, e quem disse foi o MANIFESTO -- ninguem apontou.
    _carga(coleta=20213, marco="Chegada para descarga", marco_cod=396,
           marco_em=_h(-1), marco_fonte="manifesto",
           destinatario="PLANTA DO CLIENTE - CIDADE B/RJ",
           janela_entrega=_h(-3), chegada=_h(-1),
           chegada_fonte="manifesto", desvio_h=2.0),
    # 3) na estrada com manifesto AUTORIZADO e nenhum apontamento: sem hora.
    _carga(coleta=20214, marco="Em viagem", marco_cod=400, marco_em="",
           marco_fonte="manifesto", placa="BBB2B22",
           destinatario="OUTRO DESTINO - CIDADE C/MG"),
    # 4) PROGRAMADA -- a que voltou a aparecer, com a janela de carregamento.
    _carga(coleta=20241, marco="Programada", marco_cod=0, marco_em=_h(6),
           marco_fonte="programação", placa="",
           destinatario="OUTRO DESTINO - CIDADE C/MG",
           janela_carga=_h(6), janela_entrega=_h(18)),
]

AGORA = {
    "cargas": CARGAS,
    "em_curso": len(CARGAS),
    "sem_apontamento": 1,
    "por_destinatario": [
        {"destinatario": "MONTADORA - CIDADE B/RJ", "cargas": 1,
         "em_viagem": 0, "no_destino": 1, "na_origem": 0, "programadas": 0},
        {"destinatario": "OUTRO DESTINO - CIDADE C/MG", "cargas": 2,
         "em_viagem": 1, "no_destino": 0, "na_origem": 0, "programadas": 1},
        {"destinatario": "PLANTA DO CLIENTE - CIDADE B/RJ", "cargas": 1,
         "em_viagem": 0, "no_destino": 1, "na_origem": 0, "programadas": 0},
    ],
    "concluidas_na_janela": 713,
    "janela_dias": 45,
    "posicao": {"com_posicao": 0, "frescas": 0, "fontes": {}, "veiculos": 2,
                "fresca_ate_min": 120},
    "travado": True,
    "cliente_raiz": "11222333",
    "cliente_nome": "CLIENTE DUBLÊ S.A.",
    "fonte": "Sistema de gestão · leitura",
}


def _abrir(pg, base_url):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/portal/cliente" in u:
            corpo = AGORA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#cliop")
    pg.wait_for_selector("#cliop-agora tr", state="attached", timeout=20000)
    return erros


def test_a_tela_abre_sem_erro(pagina):
    pg, base = pagina
    assert _abrir(pg, base) == []


def test_a_carga_que_CHEGOU_continua_na_lista(pagina):
    """O defeito que mais mudava o painel, e ele era invisível.

    A carga sumia no instante da chegada, porque o encerramento do manifesto
    fechava a viagem — e ele é emitido na chegada, não na entrega. O cliente
    deixava de ver justamente as horas em que o veículo estava parado no pátio
    dele, que é o assunto da aba Permanência.
    """
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#cliop-agora")
    assert "20222" in txt, txt
    assert "20213" in txt, "a que chegou pelo manifesto também fica"


def test_a_carga_PROGRAMADA_aparece_com_a_janela_de_carregamento(pagina):
    """Ela some do painel sem erro nenhum — a ausência não tem sintoma."""
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#cliop-agora")
    assert "20241" in txt
    assert "Programada" in txt


def test_cada_linha_diz_DE_ONDE_veio_o_estado(pagina):
    """Apontamento, manifesto e programação têm precisões diferentes.

    Um estado vindo do manifesto é grosso (chegou, sem hora de doca); um
    vindo da programação é INTENÇÃO, não fato. Quem lê tem de separar os três
    sem abrir a documentação.
    """
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#cliop-agora")
    for fonte in ("apontamento", "manifesto", "programação"):
        assert fonte in txt, (fonte, txt)


def test_o_DESTINATARIO_separa_duas_docas_na_mesma_cidade(pagina):
    """As duas primeiras cargas vão para a MESMA cidade e destinatários
    diferentes. Agrupadas por rota elas seriam uma linha só — que é como a
    tela mostrava antes, e por isso não havia como acompanhar um destino."""
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#cliop-agora")
    assert "MONTADORA - CIDADE B/RJ" in txt
    assert "PLANTA DO CLIENTE - CIDADE B/RJ" in txt


def test_o_desvio_sai_como_CONTA_e_nao_como_veredito(pagina):
    """Horas com sinal, nunca "no prazo" nem percentual.

    A régua é a NOSSA janela programada; publicar um percentual num painel que
    o cliente lê transformaria a nossa previsão em compromisso contratual.
    """
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#cliop-agora")
    assert "+2h" in txt.replace(",0h", "h"), txt
    for proibido in ("no prazo", "No prazo", "% no praz", "pontualidade"):
        assert proibido not in txt, proibido


def test_a_banda_de_KPI_conta_as_PROGRAMADAS(pagina):
    """O KPI antigo era "na origem", que nesta operação é quase sempre zero —
    a passagem de chegada para saída do carregamento leva minutos."""
    pg, base = pagina
    _abrir(pg, base)
    kpis = pg.inner_text("#kpis-cliop")
    assert "Programadas" in kpis, kpis
    assert "No destino" in kpis
