# -*- coding: utf-8 -*-
"""O painel de TV do CCO (`tvcco`, 15/09/2026): as regras, uma a uma.

Cada regra é afirmada sobre linhas escritas à mão, na forma que o ERP devolve
(`api/cco.CCO_SQL`), contra a função PURA `classificar`. Os cortes que as
regras usam (tolerância do CT-e, cobertura SAC, 24 h sem apontamento) saíram
de medições que estão escritas no módulo — o teste prova que o código aplica
o corte que o comentário diz, e na fronteira.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from api import auth, cco, copiloto

AGORA = datetime(2026, 9, 15, 12, 0)
DE, ATE = date(2026, 9, 14), date(2026, 9, 16)
MON = {1}


def _l(**kw):
    base = {"numero": 100, "filial": 1, "cod": 1, "cliente": "CLIENTE A",
            "veiculo": "ABC1D23", "jc": None, "je": None, "cc": None,
            "sc": None, "cd": None, "fd": None, "motivo_coleta": 0,
            "motivo_entrega": 0, "fin": 0, "cte_em": None,
            "ft_carga_h": None, "ft_descarga_h": None}
    base.update(kw)
    return base


def _c(*linhas, agora=AGORA):
    return cco.classificar(list(linhas), agora, MON, DE, ATE)


H = lambda h: timedelta(hours=h)  # noqa: E731
M = lambda m: timedelta(minutes=m)  # noqa: E731


# ------------------------------------------------------------ programação

def test_programacao_atrasada_e_so_sem_veiculo_com_janela_vencida():
    d = _c(_l(numero=1, veiculo="", jc=AGORA - H(2)),          # sem veículo, venceu
           _l(numero=2, veiculo="", jc=AGORA + H(3)),          # sem veículo, à frente
           _l(numero=3, veiculo="XYZ9Z99", jc=AGORA - H(5)))   # com veículo, venceu
    p = d["kpis"]["programacao"]
    assert p == {"total": 3, "no_prazo": 2, "atrasadas": 1}
    # a coleta 1 também está atrasada na COLETA, mas o rodapé fala dela uma
    # vez só (pela programação); a 3 tem veículo e é aviso de coleta
    assert [a["tipo"] for a in d["alertas"]] == ["coleta", "programacao"]
    assert d["kpis"]["coletas"]["atrasadas"] == 2


def test_programacao_conta_TODOS_os_clientes_e_o_resto_so_os_monitorados():
    """Ter veículo não depende de apontamento SAC; chegar no prazo depende."""
    fora = _l(cod=9, cliente="SEM SAC", veiculo="", jc=AGORA - H(1),
              je=AGORA - H(1))
    d = _c(fora)
    assert d["kpis"]["programacao"]["atrasadas"] == 1
    assert d["kpis"]["coletas"]["atrasadas"] == 0
    assert d["kpis"]["entregas"]["atrasadas"] == 0
    assert d["cobertura"]["fora_coletas"] == 1
    assert d["cobertura"]["fora_clientes"] == ["SEM SAC"]


def test_fora_da_janela_nao_conta():
    d = _c(_l(veiculo="", jc=datetime(2026, 9, 10, 8, 0)))
    assert d["kpis"]["programacao"]["total"] == 0


# ------------------------------------------------------------ coleta

def test_coleta_chegou_na_janela_ou_depois():
    d = _c(_l(jc=AGORA - H(4), cc=AGORA - H(4)),              # na hora: no prazo
           _l(jc=AGORA - H(4), cc=AGORA - H(4) + M(1)))       # 1 min depois
    c = d["kpis"]["coletas"]
    assert (c["no_prazo"], c["atrasadas"]) == (1, 1)
    assert c["pontualidade"] == 50.0


def test_coleta_sem_chegada():
    d = _c(_l(jc=AGORA + H(2)),                               # à frente
           _l(jc=AGORA - H(3), sc=AGORA - H(1)),              # saiu: falta apontar
           _l(jc=AGORA - H(3), cte_em=AGORA - H(1)),          # tem CT-e: idem
           _l(jc=AGORA - H(3)),                               # nada: atrasada
           _l(jc=AGORA - H(cco.SEM_APONTAMENTO_H) - M(1)))    # um dia: falta apontar
    c = d["kpis"]["coletas"]
    assert c == {"no_prazo": 0, "atrasadas": 1, "a_vencer": 1,
                 "sem_apontamento": 3, "pontualidade": 0.0}
    assert any(a["texto"].startswith("Veículo não chegou") for a in d["alertas"])


def test_o_corte_de_24h_e_na_fronteira():
    no_limite = _c(_l(jc=AGORA - H(cco.SEM_APONTAMENTO_H)))
    assert no_limite["kpis"]["coletas"]["atrasadas"] == 1


# ------------------------------------------------------------ emissão

@pytest.mark.parametrize("depois_min, esperado", [
    (-30, "no_prazo"),                         # CT-e antes da saída
    (cco.TOLERANCIA_CTE_MIN, "no_prazo"),      # exatamente na tolerância
    (cco.TOLERANCIA_CTE_MIN + 1, "atrasadas"),
])
def test_emissao_conta_da_saida_do_carregamento(depois_min, esperado):
    sc = AGORA - H(5)
    d = _c(_l(jc=AGORA - H(8), cc=AGORA - H(8), sc=sc, cte_em=sc + M(depois_min)))
    e = d["kpis"]["emissoes"]
    assert e[esperado] == 1 and sum(e.values()) == 1, e


def test_emissao_sem_ct_e():
    d = _c(_l(jc=AGORA - H(3), cc=AGORA - H(3), sc=AGORA - M(20)),     # saiu há 20 min
           _l(jc=AGORA - H(3), cc=AGORA - H(3), sc=AGORA - H(2)),      # saiu há 2 h
           _l(jc=AGORA - H(1), cc=AGORA - H(1)),                       # carregando
           _l(jc=AGORA - H(3), cc=AGORA - H(3), cte_em=AGORA - H(1)))  # CT-e sem saída
    e = d["kpis"]["emissoes"]
    assert e == {"no_prazo": 1, "atrasadas": 1, "aguardando": 2}
    assert any(a["texto"].startswith("Saiu sem CT-e") for a in d["alertas"])


def test_emissao_so_conta_quem_ja_chegou_ou_saiu():
    d = _c(_l(jc=AGORA + H(2)))
    assert sum(d["kpis"]["emissoes"].values()) == 0


# ------------------------------------------------------------ entrega

def test_entrega():
    d = _c(_l(je=AGORA - H(6), cd=AGORA - H(7)),                  # antes
           _l(je=AGORA - H(6), cd=AGORA - H(5)),                  # depois
           _l(je=AGORA + H(3)),                                   # à frente
           _l(je=AGORA - H(3), fd=AGORA - H(1)),                  # descarregou
           _l(je=AGORA - H(3), fin=1),                            # viagem finalizada
           _l(je=AGORA - H(3)),                                   # atrasada
           _l(je=AGORA - H(cco.SEM_APONTAMENTO_H) - M(1)))        # falta apontar
    e = d["kpis"]["entregas"]
    assert e == {"no_prazo": 1, "atrasadas": 2, "a_vencer": 1,
                 "sem_apontamento": 3, "pontualidade": 33.3}


def test_pontualidade_sem_base_e_nula_e_nao_zero():
    d = _c()
    assert d["kpis"]["coletas"]["pontualidade"] is None
    assert d["kpis"]["entregas"]["pontualidade"] is None


# ------------------------------------------------------------ freetime

def test_freetime_comeca_no_que_vier_depois_janela_ou_chegada():
    """Os três casos separam as três regras possíveis: só da chegada daria 2,
    só da janela daria 2, e "o que vier depois" dá 1."""
    jc = datetime(2026, 9, 15, 8, 0)
    muito_cedo = _l(numero=1, jc=jc, cc=jc - H(2), sc=jc + H(2.5), ft_carga_h=3.0)
    cedo = _l(numero=2, jc=jc, cc=jc - H(1), sc=jc + H(3.5), ft_carga_h=3.0)
    tarde = _l(numero=3, jc=jc, cc=jc + H(2), sc=jc + H(4.5), ft_carga_h=3.0)
    d = _c(muito_cedo, cedo, tarde)
    # muito cedo: da janela 08:00 à saída 10:30 = 2h30 -> não (da chegada: 4h30)
    # cedo:       da janela 08:00 à saída 11:30 = 3h30 -> EXCEDEU
    # tarde:      da chegada 10:00 à saída 12:30 = 2h30 -> não (da janela: 4h30)
    assert d["kpis"]["carregamento"]["freetime"] == 1


def test_freetime_agora_e_o_teto_de_24h():
    agora_no_cliente = _l(jc=AGORA - H(5), cc=AGORA - H(5), ft_carga_h=3.0)
    esquecido = _l(jc=AGORA - H(30), cc=AGORA - H(30), ft_carga_h=3.0)
    sem_clausula = _l(jc=AGORA - H(5), cc=AGORA - H(5))
    d = _c(agora_no_cliente, esquecido, sem_clausula)
    car = d["kpis"]["carregamento"]
    assert (car["freetime"], car["freetime_agora"], car["sem_clausula"]) == (1, 1, 1)
    assert any(a["texto"].startswith("No cliente além do freetime") for a in d["alertas"])


def test_freetime_de_descarga():
    je = AGORA - H(6)
    d = _c(_l(je=je, cd=je, fd=je + H(5), ft_descarga_h=4.0),     # 5h > 4h
           _l(je=je, cd=je, fd=je + H(3), ft_descarga_h=4.0))     # 3h < 4h
    assert d["kpis"]["descarga"]["freetime"] == 1


def test_motivos_de_atraso_apontados():
    d = _c(_l(jc=AGORA - H(3), cc=AGORA - H(2), motivo_coleta=1),
           _l(je=AGORA - H(3), cd=AGORA - H(2), motivo_entrega=1))
    assert d["kpis"]["carregamento"]["motivos"] == 1
    assert d["kpis"]["descarga"]["motivos"] == 1


# ------------------------------------------------------------ pendência

def test_pendente_de_finalizacao_e_chegada_sem_fim_de_descarga_ha_mais_de_24h():
    d = _c(_l(numero=1, je=AGORA - H(25), cd=AGORA - H(cco.PENDENTE_FIM_H) - M(1)),
           _l(numero=2, je=AGORA - H(25), cd=AGORA - H(cco.PENDENTE_FIM_H) + M(1)),
           _l(numero=3, je=AGORA - H(25), cd=AGORA - H(30), fd=AGORA - H(20)))
    assert d["kpis"]["pendentes_finalizacao"] == 1


# ------------------------------------------------------------ rodapé

def test_os_avisos_saem_do_mais_velho_e_o_corte_diz_o_total():
    # cliente fora do monitoramento: só o aviso de programação, um por linha
    linhas = [_l(numero=i, cod=9, veiculo="", jc=AGORA - H(1 + i / 10))
              for i in range(cco.MAX_ALERTAS + 5)]
    d = _c(*linhas)
    assert d["alertas_total"] == cco.MAX_ALERTAS + 5
    assert len(d["alertas"]) == cco.MAX_ALERTAS
    horas = [a["horas"] for a in d["alertas"]]
    assert horas == sorted(horas, reverse=True)


def test_hm():
    assert cco._hm(2 + 40 / 60) == "2h40"
    assert cco._hm(0.5) == "30 min"


# ------------------------------------------------------------ SQL

def test_o_sql_e_do_postgres_9_3_e_nao_tem_percent_solto():
    """O ERP é 9.3 (sem FILTER), e todo `%` que não é placeholder do psycopg
    precisa vir dobrado — senão a consulta morre na execução, não no teste."""
    for sql in (cco.CCO_SQL, cco.COBERTURA_SQL):
        assert "FILTER (" not in sql.upper()
        sem_ph = re.sub(r"%\(\w+\)s", "", sql)
        assert not re.search(r"%(?!%)", sem_ph.replace("%%", "")), \
            "percent solto no SQL do CCO"


def test_o_sql_le_os_eventos_do_monitoramento_sac():
    for cod in ("394", "395", "396", "397", "401"):
        assert cod in cco.CCO_SQL
    assert "BETWEEN 425 AND 456" in cco.CCO_SQL
    assert "tipodocumento = 27" in cco.CCO_SQL


def test_o_sql_traz_o_texto_do_motivo_e_o_nome_do_cliente_da_cobertura():
    """O modal diz QUAL motivo o SAC apontou e o nome de quem ficou fora da
    conta — o cartão só contava."""
    assert "motivo_coleta_txt, evc.motivo_entrega_txt" in cco.CCO_SQL
    assert cco.CCO_SQL.count("string_agg(DISTINCT") == 2
    assert "LEFT JOIN ocorrencia oc ON oc.codigo = o.ocorrencia" in cco.CCO_SQL
    assert "max(col.cliente) AS cliente" in cco.COBERTURA_SQL


# ------------------------------------------------------------ registros

def test_a_tela_esta_registrada_no_rbac_no_perfil_e_no_copiloto():
    assert "tvcco" in auth.TELAS
    assert set(dict(auth.ROTA_TELAS)["/api/operacao/cco"]) == {"tvcco"}
    modelos = {nome: telas for nome, _d, telas in auth._PERFIS_MODELO}
    assert "tvcco" in modelos["Painéis TV"]
    telas, _abas = copiloto.FONTE_TELAS["cco_gestao_vista"]
    assert "tvcco" in telas
    assert "cco_gestao_vista" in copiloto._FONTES_ROTULO


def test_nenhum_prefixo_de_rota_engole_a_do_cco():
    rota = "/api/operacao/cco"
    antes = [p for p, _ in auth.ROTA_TELAS if rota.startswith(p) and p != rota]
    assert not antes, antes


def test_a_leitura_e_uma_so_e_nao_tem_rede_de_leitura_velha():
    """O cartão e o modal dividem UMA leitura em cache: com um cache cada, o
    modal podia vir de uma leitura mais nova que o número clicado."""
    import inspect
    fonte = inspect.getsource(cco)
    assert "@cached(ttl=120)\ndef _leitura_cco" in fonte
    assert "@cached(ttl=120)\ndef get_cco" not in fonte
    assert fonte.count("\n@cached(") == 2, "só a leitura e a cobertura têm cache"


def test_a_rota_do_detalhe_esta_no_rbac_antes_da_generica():
    rotas = [p for p, _ in auth.ROTA_TELAS]
    assert set(dict(auth.ROTA_TELAS)["/api/operacao/cco/detalhe"]) == {"tvcco"}
    assert rotas.index("/api/operacao/cco/detalhe") < rotas.index("/api/operacao/cco")


# ------------------------------------------------------------ o detalhe (modais)

def _dia_cheio():
    """Uma linha em cada situação de cada cartão: o guard de que a lista bate
    com o número só prova alguma coisa se nenhuma aba ficar vazia."""
    jc = AGORA - H(4)
    return [
        _l(numero=1, veiculo="", jc=AGORA - H(2)),                   # sem veículo
        _l(numero=2, jc=AGORA + H(3)),                               # a vencer
        _l(numero=3, jc=jc, cc=jc - M(30), sc=jc + H(1),             # no prazo, CT-e ok
           cte_em=jc + H(1) + M(10), ft_carga_h=3.0),
        _l(numero=4, jc=jc, cc=jc + H(1), sc=AGORA - H(2),           # chegou tarde, saiu sem CT-e
           motivo_coleta=1, motivo_coleta_txt="ATRASO NA COLETA - TRANSITO"),
        _l(numero=5, jc=AGORA - H(3), sc=AGORA - H(1)),              # saiu sem chegada apontada
        _l(numero=6, jc=AGORA - H(5), cc=AGORA - H(5), ft_carga_h=3.0),  # segue lá além do freetime
        _l(numero=7, je=AGORA - H(6), cd=AGORA - H(7), fd=AGORA - H(4), ft_descarga_h=1.0),
        _l(numero=8, je=AGORA - H(6), cd=AGORA - H(5), fd=AGORA - H(4),
           motivo_entrega=1, motivo_entrega_txt="ATRASO NA ENTREGA - DOCA"),
        _l(numero=9, je=AGORA + H(3)),
        _l(numero=10, je=AGORA - H(3), fd=AGORA - H(1)),
        _l(numero=11, je=AGORA - H(3)),
        _l(numero=12, je=AGORA - H(25), cd=AGORA - H(25)),           # sem fim de descarga
        _l(numero=13, cod=9, cliente="SEM SAC", jc=AGORA - H(1)),    # fora da conta
    ]


def _contagem(kpis):
    return {c: {e: (kpis["pendentes_finalizacao"] if c == "pendentes" else kpis[c][e])
                for e in es} for c, es in cco.ESTADOS.items()}


def test_a_lista_do_modal_e_o_numero_do_cartao():
    d = cco.classificar(_dia_cheio(), AGORA, MON, DE, ATE, detalhe=True)
    contagem = _contagem(d["kpis"])
    listas = {c: {e: len(v) for e, v in es.items()} for c, es in d["detalhe"].items()}
    assert listas == contagem
    vazias = [(c, e) for c, es in contagem.items() for e, n in es.items() if not n]
    assert not vazias, vazias


def test_todo_contador_do_cartao_tem_a_sua_lista():
    """Contador novo no cartão sem aba no modal seria número sem detalhe."""
    k = _c()["kpis"]
    derivados = {"total", "pontualidade", "freetime_agora"}
    for card, estados in cco.ESTADOS.items():
        if card == "pendentes":
            assert estados == ("pendentes",) and "pendentes_finalizacao" in k
            continue
        assert set(estados) == set(k[card]) - derivados, card


def test_sem_detalhe_o_cartao_nao_monta_lista():
    d = _c(*_dia_cheio())
    assert "detalhe" not in d and "por_cliente" not in d


def test_a_linha_do_modal_diz_os_horarios_e_nao_leva_motorista():
    d = cco.classificar(_dia_cheio(), AGORA, MON, DE, ATE, detalhe=True)["detalhe"]
    atr = {x["coleta"]: x for x in d["coletas"]["atrasadas"]}
    assert atr[4]["horas"] == 1.0                                # chegou 1 h depois
    assert atr[4]["chegada_carga"] == "2026-09-15 09:00"
    assert d["coletas"]["no_prazo"][0]["horas"] == -0.5          # antecedência: negativo
    ft = d["carregamento"]["freetime"][0]
    assert (ft["coleta"], ft["freetime_h"], ft["permanencia_h"], ft["agora"], ft["horas"]) \
        == (6, 3.0, 5.0, True, 2.0)
    assert d["carregamento"]["motivos"][0]["motivo"] == "ATRASO NA COLETA - TRANSITO"
    assert d["descarga"]["motivos"][0]["motivo"] == "ATRASO NA ENTREGA - DOCA"
    chaves = set().union(*(x.keys() for es in d.values() for ls in es.values() for x in ls))
    assert not {c for c in chaves if "motorista" in c or "cpf" in c}, chaves


def _leitura_falsa(linhas):
    return {"linhas": linhas, "agora": AGORA, "de": DE, "ate": ATE,
            "monit": {"codigos": [1], "avaliados": 2, "clientes": [
                {"cod": 1, "cliente": "CLIENTE A", "coletas": 40, "com_sac": 39, "pct": 97.5},
                {"cod": 9, "cliente": "SEM SAC", "coletas": 20, "com_sac": 5, "pct": 25.0}]}}


def test_o_cartao_e_o_modal_saem_da_MESMA_leitura(monkeypatch):
    chamadas = []
    lt = _leitura_falsa(_dia_cheio())
    monkeypatch.setattr(cco, "_leitura_cco", lambda: chamadas.append(1) or lt)
    painel = cco.get_cco()
    contagem = _contagem(painel["kpis"])
    for card in cco.ESTADOS:
        det = cco.get_cco_detalhe(card)
        assert [e["estado"] for e in det["estados"]] == list(cco.ESTADOS[card])
        for e in det["estados"]:
            assert e["n"] == len(e["linhas"]) == contagem[card][e["estado"]], (card, e)
        assert det["agora"] == painel["agora"] and det["regra"]
    assert len(chamadas) == 1 + len(cco.ESTADOS)


def test_o_que_pede_acao_sai_do_mais_velho(monkeypatch):
    linhas = [_l(numero=i, jc=AGORA - H(i)) for i in (1, 5, 3)]
    monkeypatch.setattr(cco, "_leitura_cco", lambda: _leitura_falsa(linhas))
    det = cco.get_cco_detalhe("coletas")
    assert det["estados"][0]["estado"] == "atrasadas"
    assert [x["coleta"] for x in det["estados"][0]["linhas"]] == [5, 3, 1]


def test_o_modal_da_cobertura_separa_acompanhados_e_fora(monkeypatch):
    lt = _leitura_falsa(_dia_cheio())
    monkeypatch.setattr(cco, "_leitura_cco", lambda: lt)
    det = cco.get_cco_detalhe("cobertura")
    grupos = {e["estado"]: e for e in det["estados"]}
    painel = cco.get_cco()["cobertura"]
    assert grupos["monitorados"]["n"] == painel["coletas"] == 12
    assert grupos["fora"]["n"] == painel["fora_coletas"] == 1
    assert grupos["fora"]["linhas"] == [{"cliente": "SEM SAC", "coletas": 1,
                                         "cobertura_pct": 25.0, "coletas_30d": 20}]
    assert det["cobertura_min_pct"] == 90


def test_cartao_desconhecido_e_recusa_legivel():
    with pytest.raises(ValueError):
        cco.get_cco_detalhe("financeiro")
    from api import main
    assert main.operacao_cco_detalhe("financeiro").status_code == 409


def test_a_regra_do_modal_e_escrita_com_as_constantes(monkeypatch):
    monkeypatch.setattr(cco, "TOLERANCIA_CTE_MIN", 45)
    monkeypatch.setattr(cco, "PENDENTE_FIM_H", 36)
    r = cco.regras()
    assert "45 min" in r["emissoes"] and "36 h" in r["pendentes"]
    assert set(r) == set(cco.CARDS_DETALHE)
