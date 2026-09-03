# -*- coding: utf-8 -*-
"""A régua diária da 3S e o aviso que sai dela.

Os guards são das decisões que mudam o número (dia fechado, "nunca" separado de
"mudo") e das duas que impedem o aviso de mentir: a recusa quando o cano de
posições morre, e o anexo que só vai quando a LISTA muda — não quando a
contagem muda.
"""
from __future__ import annotations

import datetime as dt

import pytest

from api import comunicacao_3s as c3
from api.whatsapp import valores

HOJE = dt.date(2026, 9, 2)


def _linha(placa, dias=0, com_motor=False, rastr="3S DISTRIBUICAO LTDA",
           frota=None):
    """Um veículo. `dias=None` = nunca teve posição."""
    return {
        "placa": placa, "numerofrota": frota, "com_motor": com_motor,
        "rastreadora": rastr,
        "ultima": None if dias is None
        else dt.datetime.combine(HOJE - dt.timedelta(days=dias), dt.time(7, 0)),
    }


def _stub_erp(monkeypatch, linhas):
    class _Cur:
        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            return linhas

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(c3.db, "get_conn", lambda: _Conn())


# ---------------------------------------------------------------- a medição

def test_o_dia_e_fechado_e_a_consulta_corta_na_meia_noite(monkeypatch):
    """Às 09:00, medir "hoje" contaria como muda toda carreta que ainda não
    reportou desde a meia-noite. O corte é `< 00:00 do dia seguinte`, e é ele
    que faz a série de ontem valer a mesma coisa se remedida amanhã."""
    vistos = {}

    class _Cur:
        def execute(self, sql, params=None):
            vistos["params"] = params

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(c3.db, "get_conn", lambda: _Conn())
    c3.medir(HOJE)
    assert vistos["params"] == (HOJE + dt.timedelta(days=1),)


def test_nunca_comunicou_nao_se_mistura_com_leitura_velha(monkeypatch):
    """Ausência de leitura é provisionamento, contrato ou aparelho que não
    existe; leitura velha é falha. São cobranças diferentes, e uma lista só
    faria a 3S responder a única coisa fácil."""
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A2", dias=40),
                            _linha("A3", dias=0), _linha("A4", dias=5)])
    m = c3.medir(HOJE)
    g = m["grupos"][0]
    assert (g["nunca"], g["mudo_15d"], g["comunicou"]) == (1, 1, 1)
    sit = {p["placa"]: p["situacao"] for p in m["placas"]}
    assert sit == {"A1": "nunca", "A2": "mudo15", "A3": "comunicou",
                   "A4": "parou"}


def test_o_nome_da_rastreadora_e_o_curto(monkeypatch):
    """"3S" é como se fala dela; "3S DISTRIBUICAO E COMERCIALIZACAO DE
    PRODUTOS LTDA" é como ela assina. O alvo do alerta casa com o curto."""
    _stub_erp(monkeypatch, [_linha("A1", rastr="3S DISTRIBUICAO E COM LTDA")])
    assert c3.medir(HOJE)["grupos"][0]["rastreadora"] == c3.ALVO


# --------------------------------------------------- a gravação e a diferença

def test_a_gravacao_e_idempotente(monkeypatch, esquema_pg):
    """O agendador repete quando a máquina acorda. Uma segunda linha para o
    mesmo dia dobraria a frota na curva."""
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A2", dias=0)])
    med = c3.medir(HOJE)
    c3.gravar(med, esquema=esquema_pg)
    c3.gravar(med, esquema=esquema_pg)
    serie = c3.historico(30, c3.ALVO, esquema=esquema_pg)
    assert len(serie) == 1 and serie[0]["frota"] == 2
    assert len(c3.placas_do_dia(HOJE, c3.ALVO, esquema=esquema_pg)) == 2


def test_placa_que_sai_da_frota_nao_sobrevive_na_foto(monkeypatch, esquema_pg):
    """A regravação do dia apaga as placas antes de inserir. Sem isso a placa
    vendida continuaria na lista de cobrança para sempre."""
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A2", dias=None)])
    c3.gravar(c3.medir(HOJE), esquema=esquema_pg)
    _stub_erp(monkeypatch, [_linha("A1", dias=None)])
    c3.gravar(c3.medir(HOJE), esquema=esquema_pg)
    assert [p["placa"] for p in
            c3.placas_do_dia(HOJE, c3.ALVO, esquema=esquema_pg)] == ["A1"]


def test_a_lista_muda_mesmo_com_a_contagem_igual(monkeypatch, esquema_pg):
    """ESTE é o motivo de guardar placa e não só número: 2 ontem e 2 hoje pode
    ser a mesma lista parada ou uma que voltou e outra que caiu. A segunda é
    notícia, e some inteira num número que não mudou."""
    ontem = HOJE - dt.timedelta(days=1)
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A2", dias=None)])
    c3.gravar(c3.medir(ontem), esquema=esquema_pg)
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A3", dias=None)])
    c3.gravar(c3.medir(HOJE), esquema=esquema_pg)

    d = c3.diferenca(HOJE, ontem, c3.ALVO, esquema=esquema_pg)
    assert d["mudou"] and d["entraram"] == ["A3"] and d["sairam"] == ["A2"]


def test_lista_parada_nao_conta_como_mudanca(monkeypatch, esquema_pg):
    ontem = HOJE - dt.timedelta(days=1)
    linhas = [_linha("A1", dias=None), _linha("A2", dias=None)]
    _stub_erp(monkeypatch, linhas)
    c3.gravar(c3.medir(ontem), esquema=esquema_pg)
    c3.gravar(c3.medir(HOJE), esquema=esquema_pg)
    assert not c3.diferenca(HOJE, ontem, c3.ALVO, esquema=esquema_pg)["mudou"]


def test_quem_comunicou_fica_fora_da_lista_de_cobranca(monkeypatch, esquema_pg):
    """O anexo existe para cobrar quem NÃO comunica. Uma lista com todo mundo
    não é lista, é o cadastro."""
    ontem = HOJE - dt.timedelta(days=1)
    # o dublê não executa o SQL, então a data de cada dia é montada aqui: A2
    # comunicou NO dia medido nas duas vezes
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A2", dias=1)])
    c3.gravar(c3.medir(ontem), esquema=esquema_pg)
    _stub_erp(monkeypatch, [_linha("A1", dias=None), _linha("A2", dias=0)])
    c3.gravar(c3.medir(HOJE), esquema=esquema_pg)
    # A2 comunicou nos dois dias — não pode aparecer como entrada nem saída
    d = c3.diferenca(HOJE, ontem, c3.ALVO, esquema=esquema_pg)
    assert d["entraram"] == [] and d["sairam"] == []


# ------------------------------------------------------------- a recusa

def test_com_o_cano_morto_o_aviso_RECUSA_em_vez_de_culpar_a_3S(monkeypatch,
                                                              esquema_pg):
    """Se a integração de posições parar, a leitura crua diria "0 comunicaram":
    alarme verdadeiro no número e falso na conclusão. O aviso precisa acusar o
    lado certo — e a régua é a frota COM MOTOR, que num dia normal comunica em
    82%."""
    _stub_erp(monkeypatch, [_linha("T%d" % i, dias=None, com_motor=True,
                                   rastr="RASTER LTDA") for i in range(10)]
              + [_linha("C1", dias=None)])
    d = c3.status_alerta(HOJE, esquema=esquema_pg)
    assert "erro" in d
    assert "integração de posições" in d["erro"]
    assert "3S" in d["erro"]


def test_com_o_cano_vivo_o_aviso_sai(monkeypatch, esquema_pg):
    _stub_erp(monkeypatch, [_linha("T%d" % i, dias=0, com_motor=True,
                                   rastr="RASTER LTDA") for i in range(10)]
              + [_linha("C1", dias=None)])
    d = c3.status_alerta(HOJE, esquema=esquema_pg)
    assert "erro" not in d and d["hoje"]["nunca"] == 1


def test_a_recusa_sobe_como_ValueError_para_o_canal(monkeypatch):
    """`montar_texto` só usa a mensagem do provedor quando ela é ValueError —
    caso contrário grava "não foi possível ler os números", que é verdadeiro e
    inútil quando o motivo real é "a coleta está parada"."""
    with pytest.raises(ValueError) as exc:
        valores.comunicacao_3s({"erro": "a integração de posições parece parada"})
    assert "integração" in str(exc.value)


# ------------------------------------------------------------- o texto

def _dados(nunca=142, comunicou=53, mudou=True, primeira=False, placas=None):
    return {
        "dia": HOJE, "alvo": "3S",
        "hoje": {"frota": 223, "comunicou": comunicou, "nunca": nunca,
                 "mudo_15d": 25, "parou": 3},
        "anterior": {"dia": HOJE - dt.timedelta(days=1), "frota": 223,
                     "comunicou": 50, "nunca": 145, "mudo_15d": 25},
        "diferenca": {"primeira": primeira, "mudou": mudou,
                      "entraram": ["A9"] if mudou else [],
                      "sairam": ["A8"] if mudou else []},
        "placas": placas if placas is not None
        else [{"placa": "A1", "situacao": "nunca", "ultima": None}],
    }


def test_o_aviso_nao_fala_da_frota_com_motor():
    """Saiu do texto a pedido de quem opera — ela respondia uma pergunta que
    não é a deste aviso. O que ela protegia continua em `status_alerta`."""
    v = valores.comunicacao_3s(_dados())
    assert "cano" not in v
    junto = " ".join(str(x) for k, x in v.items() if k != "_anexo")
    assert "motor" not in junto.lower()


def test_o_anexo_so_vai_quando_a_lista_muda():
    """Um PDF de cinco páginas todo dia vira o anexo que ninguém abre —
    inclusive no dia em que ele importa."""
    assert "_anexo" in valores.comunicacao_3s(_dados(mudou=True))
    assert "_anexo" not in valores.comunicacao_3s(_dados(mudou=False))


def test_sem_ninguem_a_cobrar_nao_ha_anexo():
    """Lista vazia não vira PDF de zero páginas."""
    v = valores.comunicacao_3s(_dados(
        mudou=True, placas=[{"placa": "A1", "situacao": "comunicou",
                             "ultima": HOJE}]))
    assert "_anexo" not in v


def test_o_texto_diz_o_que_mudou_e_nao_so_que_mudou():
    v = valores.comunicacao_3s(_dados(mudou=True))
    assert "entraram 1" in v["lista"] and "saíram 1" in v["lista"]
    v2 = valores.comunicacao_3s(_dados(mudou=False))
    assert "mesma de ontem" in v2["lista"] and "sem anexo" in v2["lista"]


def test_a_barra_de_progresso_acompanha_o_numero():
    """A barra é a única coisa da mensagem que se lê sem ler."""
    v = valores.comunicacao_3s(_dados(comunicou=223))
    assert v["barra"].startswith("🟩" * 10) and "100%" in v["barra"]
    v0 = valores.comunicacao_3s(_dados(comunicou=0))
    assert v0["barra"].startswith("⬜" * 10) and "0%" in v0["barra"]


# ------------------------------------------------------------- o anexo

def test_o_pdf_repete_o_cabecalho_da_secao_na_pagina_seguinte():
    """Sem isso a página 2 abre numa placa solta e quem lê não sabe se aquilo é
    "nunca comunicou" ou "parou" — a distinção que o anexo existe para fazer.
    E a seção que COMEÇA numa folha nova não é continuação de si mesma."""
    pypdf = pytest.importorskip("pypdf")
    from api import comunicacao_pdf

    placas = [{"placa": "AAA%04d" % i, "situacao": "nunca", "ultima": None}
              for i in range(120)]
    placas += [{"placa": "BBB0001", "situacao": "mudo15",
                "ultima": HOJE - dt.timedelta(days=40)}]
    r = pypdf.PdfReader(__import__("io").BytesIO(
        comunicacao_pdf.gerar(HOJE, placas)))
    assert len(r.pages) > 1
    titulos = [l.strip() for p in r.pages
               for l in (p.extract_text() or "").split("\n")
               if "NUNCA COMUNICARAM" in l or "SEM COMUNICAR" in l]
    assert titulos[0].endswith("(120)"), titulos[0]
    assert "continuação" in titulos[1]
    # a seção nova nunca nasce marcada como continuação
    novas = [t for t in titulos if "SEM COMUNICAR" in t]
    assert novas and "continuação" not in novas[0], novas


def test_o_anexo_separa_as_tres_cobrancas():
    pypdf = pytest.importorskip("pypdf")
    from api import comunicacao_pdf

    r = pypdf.PdfReader(__import__("io").BytesIO(comunicacao_pdf.gerar(HOJE, [
        {"placa": "A1", "situacao": "nunca", "ultima": None},
        {"placa": "A2", "situacao": "mudo15",
         "ultima": HOJE - dt.timedelta(days=40)},
        {"placa": "A3", "situacao": "parou",
         "ultima": HOJE - dt.timedelta(days=5)}])))
    txt = "\n".join(p.extract_text() or "" for p in r.pages)
    for chave in ("NUNCA COMUNICARAM", "SEM COMUNICAR HÁ MAIS DE 15 DIAS",
                  "PARARAM NOS ÚLTIMOS 15 DIAS"):
        assert chave in txt
    # e diz DESDE QUANDO, que é o que torna a lista cobrável
    assert "nenhuma posição registrada" in txt and "40 dias" in txt


# ------------------------------------------------------------- o canal

def test_a_agenda_aceita_GRUPO_como_destinatario(monkeypatch):
    """A agenda nasceu só com telefone e recusava id de grupo com a mensagem
    errada ("Telefone inválido"), enquanto o ENVIO já aceitava grupo."""
    from api.whatsapp import agenda, modelos

    monkeypatch.setattr(modelos, "obter",
                        lambda chave, esquema=None: {"chave": chave,
                                                     "nome": "x", "ativo": 1})
    v = agenda.validar({"modelo": "m", "destinatarios": "120363411494074894-group",
                        "frequencia": "diario", "hora": "09:00"})
    assert v["destinatarios"] == "120363411494074894-group"


def test_o_anexo_passa_pelas_mesmas_travas_do_texto(monkeypatch):
    """Um `enviar_anexo` paralelo seria o atalho por onde o freio deixaria de
    valer justamente para a mensagem mais pesada. Aqui: canal DESLIGADO tem de
    barrar o anexo igual barra o texto."""
    from api.whatsapp import config as cfg
    from api.whatsapp import envio

    original = cfg.ler()          # captura ANTES de trocar: `lambda` que chama
    monkeypatch.setattr(          # o próprio `ler` já trocado recorre sem fim
        cfg, "ler", lambda: {**original, "ativo": False})
    r = envio.enviar("120363411494074894-group", "oi", registrar=False,
                     anexo=(b"%PDF-1.4", "x.pdf", "pdf"))
    assert not r["ok"] and r["erro"]
