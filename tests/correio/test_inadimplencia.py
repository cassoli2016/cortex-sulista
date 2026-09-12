# -*- coding: utf-8 -*-
"""O e-mail da inadimplência (13h, dia útil) e o dia que ele lê.

Nenhum teste vai ao ERP: a consulta reusa a regra oficial de `api/queries.py`
(com guard de texto aqui) e o cálculo do dia é `inadimplencia.montar`, função
pura. Nomes e valores são de mentira — o repositório é público, e a carteira da
casa não é.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from api import queries
from api.correio import agenda, relatorios
from api.financeiro import inadimplencia as fi

SEX = date(2026, 9, 11)   # sexta-feira
SEG = date(2026, 9, 14)   # segunda-feira
CNPJ = "11222333000181"   # fictício


def _serie(hoje: date, *, inicial=400_000.0, entra=5_000.0, sai=3_000.0,
           sabado_entra=7_000.0):
    """30 dias corridos até ONTEM, com o fechamento andando pelo fluxo — o
    formato que `SERIE_SQL` devolve. No sábado vence título e ninguém paga."""
    out, v = [], inicial
    for k in range(30, 0, -1):
        d = hoje - timedelta(days=k)
        e = sabado_entra if d.isoweekday() == 6 else (entra if d.isoweekday() <= 5 else 0.0)
        r = sai if d.isoweekday() <= 5 else 0.0
        v = v + e - r
        out.append({"dia": d, "vencido": v, "entrou": e, "recuperado": r, "cancelado": 0.0})
    return out


def _dia(hoje=SEG, *, vencido=500_000.0, aberto=10_000_000.0, top=None,
         novos=None, avencer=None, serie=None, lido_em=None, aging=None,
         mais_90=40_000.0):
    tot = {"vencido": vencido, "titulos": 120, "clientes": 14,
           "mais_90": mais_90, "titulos_mais_90": 9}
    aging = aging if aging is not None else [
        {"faixa": "1_a_vencer", "qtd": 5000, "valor": aberto - vencido},
        {"faixa": "2_vencido_ate_30", "qtd": 80, "valor": 300_000.0},
        {"faixa": "3_vencido_31_90", "qtd": 31, "valor": 160_000.0},
        {"faixa": "4_vencido_91_365", "qtd": 9, "valor": 40_000.0}]
    top = top if top is not None else [
        {"codigo": CNPJ, "cliente": "TRANSPORTADORA FICTICIA LTDA", "titulos": 12,
         "vencido": 200_000.0,
         "vencimento_mais_antigo": (hoje - timedelta(days=95)).isoformat()},
        {"codigo": "44555666000172", "cliente": "INDUSTRIA DE MENTIRA SA",
         "titulos": 3, "vencido": 50_000.0,
         "vencimento_mais_antigo": (hoje - timedelta(days=12)).isoformat()}]
    novos = novos if novos is not None else [
        {"cliente": "COMERCIO DUBLE ME", "titulos": 2, "valor": 30_000.0,
         "venc_de": (hoje - timedelta(days=3)).isoformat(),
         "venc_ate": (hoje - timedelta(days=1)).isoformat()}]
    avencer = avencer if avencer is not None else [
        {"cliente": "LOGISTICA INVENTADA LTDA", "titulos": 5, "valor": 90_000.0,
         "venc_de": (hoje + timedelta(days=1)).isoformat(),
         "venc_ate": (hoje + timedelta(days=4)).isoformat()}]
    return fi.montar(hoje=hoje, tot=tot, ab={"aberto": aberto, "titulos": 5120},
                     aging=aging, top=top, novos=novos, avencer=avencer,
                     pend={"valor": 1_000_000.0, "docs": 100},
                     serie=serie if serie is not None else _serie(hoje),
                     lido_em=lido_em or datetime.now())


@pytest.fixture
def email(monkeypatch):
    def gerar(**kw):
        dia = _dia(**kw)
        monkeypatch.setattr(fi, "resumo", lambda: dia)
        return relatorios.montar("inadimplencia")
    return gerar


# ═══════════════════════════════════════════════════════ dias úteis ══════

def test_os_dias_uteis_pulam_o_fim_de_semana():
    assert fi.uteis_antes(SEG, 3) == [date(2026, 9, 9), date(2026, 9, 10), SEX]
    assert fi.uteis_depois(SEX, 1) == SEG
    assert fi.uteis_depois(SEX, 5) == date(2026, 9, 18)


def test_o_que_venceu_no_FIM_DE_SEMANA_entra_na_segunda():
    """O título que venceu no sábado entrou em atraso no fim de semana, e é na
    segunda que alguém pode fazer algo com ele."""
    serie = _serie(date(2026, 9, 15))    # vai até a segunda, dia 14
    pts = fi.por_dia_util(serie, [SEX, SEG])
    assert len(pts) == 1, "o primeiro dia só serve de borda"
    seg = pts[0]
    assert seg["dia"] == SEG
    assert seg["entrou"] == 7_000.0 + 5_000.0, "sábado + segunda"
    assert seg["recuperado"] == 3_000.0
    assert seg["vencido"] == [s for s in serie if s["dia"] == SEG][0]["vencido"]


# ═══════════════════════════════════════════════════════ o dia ═══════════

def test_a_taxa_usa_os_MESMOS_limiares_da_tela():
    """Duas réguas para o mesmo número se contradizem na primeira vez que alguém
    compara o e-mail com a tela Contas a Receber."""
    html = (Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"
            ).read_text(encoding="utf-8")
    m = re.search(r"fr>([0-9.]+)\?'bad':\(fr>([0-9.]+)\?'warn'", html)
    assert m, "o semáforo do cartão Vencido saiu da tela — conferir a régua"
    assert (float(m.group(1)), float(m.group(2))) == (fi.ALTA, fi.ATENCAO)
    assert fi.estado_taxa(0.04) == "ok"
    assert fi.estado_taxa(0.051) == "warn"
    assert fi.estado_taxa(0.10) == "warn"
    assert fi.estado_taxa(0.1001) == "bad"
    assert fi.estado_taxa(None) == "neutro"


def test_o_CODIGO_do_cliente_nao_sai_do_modulo():
    r = _dia()
    assert CNPJ not in json.dumps(r, default=str)
    assert r["devedores"][0]["cliente"] == "TRANSPORTADORA FICTICIA LTDA"


def test_as_faixas_saem_TODAS_mesmo_a_que_nao_tem_titulo():
    """A faixa de mais de um ano sem título é informação ("não há crônico"),
    não linha que some."""
    r = _dia()
    assert [f["faixa"] for f in r["faixas"]] == [c for c, _ in fi.FAIXAS]
    assert r["faixas"][-1]["valor"] == 0 and r["faixas"][-1]["titulos"] == 0


def test_a_variacao_e_contra_o_FECHAMENTO_do_ultimo_dia_util():
    serie = _serie(SEG)
    r = _dia(serie=serie)
    sexta = [s for s in serie if s["dia"] == SEX][0]["vencido"]
    assert r["ultimo_fechamento"]["dia"] == SEX.isoformat()
    assert r["variacao"] == pytest.approx(500_000.0 - sexta)
    assert all(p["dia"] < SEG.isoformat() for p in r["pontos"]), \
        "o dia em curso não entra na série: às 13h ele está pela metade"
    assert len(r["pontos"]) == fi.DIAS_UTEIS_SERIE


def test_a_janela_soma_o_fluxo_dos_ultimos_5_dias_uteis():
    r = _dia()
    # 5 úteis (seg 7 a sex 11) + o sábado 12 e o domingo 13? Não: a janela
    # termina no último dia útil FECHADO (sex 11); o sábado 5 e o domingo 6
    # entram na segunda 7, que é o primeiro da janela.
    assert r["entrou"] == pytest.approx(5 * 5_000.0 + 7_000.0)
    assert r["recuperado"] == pytest.approx(5 * 3_000.0)


def test_mais_antigo_concentracao_e_listas():
    r = _dia()
    assert r["devedores"][0]["dias_mais_antigo"] == 95
    assert r["concentracao"] == pytest.approx(250_000.0 / 500_000.0)
    assert r["novos"]["valor"] == 30_000.0 and r["novos"]["clientes"] == 1
    assert r["a_vencer"]["itens"][0]["cliente"] == "LOGISTICA INVENTADA LTDA"
    muitos = [{"cliente": f"CLIENTE {k}", "titulos": 1, "valor": float(k)}
              for k in range(1, 16)]
    r2 = _dia(avencer=muitos)
    assert len(r2["a_vencer"]["itens"]) == fi.TOP and r2["a_vencer"]["clientes"] == 15
    assert r2["a_vencer"]["itens"][0]["valor"] == 15.0, "do maior para o menor"


def test_saldo_de_CENTAVOS_sai_da_lista_fica_no_total_e_se_DIZ(email):
    """Visto no e-mail real de 12/09/2026: três clientes com uma dúzia de
    títulos somando centavos apareciam como "R$ 0" na lista de quem cobrar."""
    novos = [{"cliente": "COMERCIO DUBLE ME", "titulos": 2, "valor": 30_000.0,
              "venc_ate": "2026-09-11"},
             {"cliente": "RESIDUO FICTICIO SA", "titulos": 12, "valor": 0.37,
              "venc_ate": "2026-09-08"}]
    r = _dia(novos=novos)
    assert [c["cliente"] for c in r["novos"]["itens"]] == ["COMERCIO DUBLE ME"]
    assert r["novos"]["residuais"] == 1 and r["novos"]["clientes"] == 2
    assert r["novos"]["valor"] == pytest.approx(30_000.37), "o total não perde nada"
    h = email(novos=novos)["html"]
    assert "RESIDUO FICTICIO SA" not in h
    assert "1 cliente(s) só com saldo abaixo de R$ 1,00" in h
    # O recorte termina no título da seção SEGUINTE: a tabela de faixas mostra
    # "R$ 0" na faixa sem título, e ali o zero é informação, não ruído.
    secao = h.split("Entraram em atraso e continuam em aberto", 1)[1]
    secao = secao.split("Vencem nos próximos", 1)[0]
    assert ">R$ 0<" not in secao


def test_o_Copiloto_recebe_SO_numeros(monkeypatch):
    """O snapshot vai para o prompt do chat, que pode cair no fallback
    externo: é por levar só número que esse fallback pode existir."""
    dia = _dia()
    monkeypatch.setattr(fi, "resumo", lambda: dia)
    c = fi.resumo_copiloto()
    bruto = json.dumps(c, default=str)
    for nome in ("TRANSPORTADORA FICTICIA", "INDUSTRIA DE MENTIRA", "COMERCIO DUBLE",
                 "LOGISTICA INVENTADA", CNPJ):
        assert nome not in bruto, nome
    assert all(isinstance(v, (int, float, str, type(None))) for v in c.values())
    assert c["taxa_inadimplencia_pct"] == 5.0 and c["vencido"] == 500_000.0


# ═══════════════════════════════════════════════════ a regra oficial ═════

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_a_serie_usa_a_MESMA_regra_de_documento_das_telas():
    """Se a regra oficial mudar em `queries.py` (um documento novo, outro
    status de CT-e), a série daqui não pode ficar para trás calada."""
    docs = _norm(fi.DOCS)
    assert docs in _norm(queries._COB_WHERE)
    assert docs in _norm(queries._REC_OF_WHERE)
    assert docs in _norm(fi.SERIE_SQL)
    assert "f.composicao=1" in fi.SERIE_SQL and "f.grupo=1" in fi.SERIE_SQL
    assert fi.VENC == queries._REC_OF_VENC
    assert queries._COB_WHERE in fi.TOTAIS_SQL and queries._COB_WHERE in fi.NOVOS_SQL
    assert queries._REC_OF_WHERE in fi.AVENCER_SQL and queries._REC_OF_WHERE in fi.ABERTO_SQL


def test_a_serie_nao_perde_o_dia_sem_nada_vencido():
    """`GROUP BY` não devolve o dia sem linha: sem o LEFT JOIN, o gráfico
    emendaria o dia anterior no seguinte."""
    assert "LEFT JOIN base ON true" in fi.SERIE_SQL


# ═══════════════════════════════════════════════════════ o e-mail ════════

def test_o_email_responde_as_TRES_perguntas(email):
    r = email()
    h = r["html"]
    for trecho in ("Vencido agora", "Taxa de inadimplência", "Desde o último fechamento",
                   "Vencido no fechamento de cada dia útil", "Entrou em atraso por dia útil",
                   "Recuperado por dia útil", "Por faixa de atraso", "Maiores devedores",
                   "Entraram em atraso e continuam em aberto",
                   "Vencem nos próximos 5 dias úteis", "Como se mede"):
        assert trecho in h, trecho
    assert "TRANSPORTADORA FICTICIA LTDA" in h and "LOGISTICA INVENTADA LTDA" in h
    assert r["assunto"].startswith("[CÓRTEX] Inadimplência 14/09 — R$ 500 mil vencidos (5,0%)")
    assert r["vazio"] is False


def test_o_grafico_e_CELULA_e_a_unica_imagem_e_a_logo(email):
    h = email()["html"]
    assert "<svg" not in h
    assert all(s.startswith("cid:") for s in re.findall(r'<img[^>]+src="([^"]+)"', h))


def test_o_codigo_do_cliente_nao_vai_no_email(email):
    r = email()
    assert CNPJ not in r["html"] and CNPJ not in r["texto"]


def test_NADA_vencido_ainda_manda(email):
    """"Nada vencido" é a notícia que o financeiro quer receber."""
    r = email(vencido=0.0, top=[], novos=[], mais_90=0.0,
              aging=[{"faixa": "1_a_vencer", "qtd": 10, "valor": 1_000.0}])
    assert r["vazio"] is False
    assert "nada vencido" in r["assunto"]
    assert "Nada que venceu" in r["html"]


def test_a_leitura_VELHA_e_dita(email):
    """Se o ERP cair na hora do envio, sai a última leitura boa — e o e-mail
    tem de dizer de quando ela é."""
    r = email(lido_em=datetime.now() - timedelta(hours=3))
    assert "última leitura boa" in r["html"]
    r2 = email(lido_em=datetime.now())
    assert "última leitura boa" not in r2["html"]


def test_ERP_fora_vira_email_de_falha_e_nao_excecao(monkeypatch):
    def fora():
        raise RuntimeError("ERP fora")
    monkeypatch.setattr(fi, "resumo", fora)
    r = relatorios.montar("inadimplencia")
    assert "falha" in r["assunto"].lower() and r["html"]


def test_o_texto_puro_leva_os_numeros_que_decidem(email):
    t = email()["texto"]
    assert "Vencido agora" in t and "R$ 500.000" in t
    assert "TRANSPORTADORA FICTICIA LTDA" in t


def test_o_catalogo_manda_mesmo_sem_nada_a_dizer():
    item = relatorios.CATALOGO["inadimplencia"]
    assert item["monta"] is relatorios.inadimplencia
    assert item["pular_vazio"] is False


# ═══════════════════════════════════════════════════ só em dia útil ══════

def _ag(**kw):
    base = {"id": 1, "relatorio": "inadimplencia", "destinatarios": "a@b.com",
            "frequencia": "diario", "hora": "13:00", "dia_semana": None,
            "dia_mes": None, "dias_uteis": True, "ativo": True, "ultima_execucao": None}
    return {**base, **kw}


def test_dia_util_e_so_do_DIARIO_e_nasce_desligado():
    base = {"relatorio": "inadimplencia", "destinatarios": "a@b.com"}
    assert agenda.validar(base)["dias_uteis"] is False
    assert agenda.validar({**base, "dias_uteis": True})["dias_uteis"] is True
    assert agenda.validar({**base, "dias_uteis": True, "frequencia": "semanal",
                           "dia_semana": 6})["dias_uteis"] is False, \
        "um semanal de sábado com a caixa ligada nunca sairia"


def test_no_sabado_NAO_sai_e_na_sexta_sai():
    pode, porque = agenda.deve_rodar(_ag(), datetime(2026, 9, 12, 13, 5))
    assert not pode and "fim de semana" in porque
    pode, _ = agenda.deve_rodar(_ag(), datetime(2026, 9, 11, 13, 5))
    assert pode
    assert agenda.descrever(_ag()) == "todo dia útil às 13:00"


def test_a_escolha_GRAVA_e_VOLTA_do_banco(esquema_pg, monkeypatch):
    monkeypatch.setattr(agenda, "ESQUEMA", esquema_pg)
    novo = agenda.gravar({"relatorio": "inadimplencia", "destinatarios": "a@b.com",
                          "hora": "13:00", "dias_uteis": True}, "teste@local")
    lido = [a for a in agenda.listar() if a["id"] == novo["id"]][0]
    assert lido["dias_uteis"] is True and lido["hora"] == "13:00"
    agenda.gravar({"id": novo["id"], "relatorio": "inadimplencia",
                   "destinatarios": "a@b.com", "hora": "13:00"}, "teste@local")
    lido = [a for a in agenda.listar() if a["id"] == novo["id"]][0]
    assert lido["dias_uteis"] is False, "chave ausente no formulário é 'todos os dias'"
