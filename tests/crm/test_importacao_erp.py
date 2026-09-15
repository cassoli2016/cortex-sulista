"""Importação do CRM do ERP para o CRM do CÓRTEX (15/09/2026).

O que ela não pode fazer, e cada teste guarda uma dessas coisas:
1. traduzir um estado do ERP para um estado que diz OUTRA coisa — cada
   combinação real (status × ativo × motivo) tem o seu destino conferido;
2. perder o que o vocabulário de cá não tem: o texto do ERP vai junto;
3. brigar com os CHECKs do banco em silêncio — entregue sem data e não
   entregue com data, os dois casos reais, entram com a data tratada E dita;
4. duplicar ao rodar de novo, ou reescrever o que já é do CÓRTEX;
5. gravar na simulação;
6. deixar um registro ruim derrubar os outros;
7. levar nome de pessoa para o código (o repositório é público).

As linhas do dublê COPIAM o formato do ERP (tipos e códigos), não saem do
código testado.
"""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from api import pglocal
from api.crm import comum, importacao as imp

TZ = timezone(timedelta(hours=-3))


def _lead(i, cliente, **kw):
    base = {"id": i, "data": datetime(2026, 5, 4, 0, 0), "dtinclusao": datetime(2026, 5, 4, 9, 12, tzinfo=TZ),
            "dtalteracao": datetime(2026, 6, 1, 17, 45, tzinfo=TZ), "responsavel": 3,
            "cliente": cliente, "nomecliente": "Maria Compras", "emailcliente": "maria@exemplo.test",
            "telefonecliente": "(47) 99999-8888", "telefonecliente2": None,
            "unidade_regiao": "JOINVILLE - SC", "segmento": "AUTOMOTIVO LEVE", "origem_lead": 4,
            "descricao_servico": "Transporte de peças Joinville x Betim\nsegunda linha", "potencial": 150000.0,
            "temperatura": 1, "status_negociacao": 3, "previsao_fechamento": datetime(2026, 10, 30),
            "motivo_perda": None, "observacoes": "cliente pediu retorno em outubro", "ativoinativo": 1}
    return {**base, **kw}


def _projeto(i, numeroid, versao, cliente, **kw):
    base = {"id": i, "numeroid": numeroid, "versao": versao, "projeto": f"Estudo {numeroid}",
            "cliente": cliente, "segmento": "AUTOMOTIVO PESADO", "tipo_negocio": 2, "escopo_principal": 1,
            "detalhe_operacao": "carreta LS, 20 viagens/mês", "temperatura": 2, "status_negocio": 2,
            "status_negociacao": 2, "data_recebimento": datetime(2026, 3, 2), "data_inicio": datetime(2026, 3, 3),
            "deadline": datetime(2026, 3, 10), "data_entrega": datetime(2026, 3, 9),
            "data_aceite_declinio": datetime(2026, 3, 20), "solicitante": 1, "responsavel_projeto": 1,
            "rob": 88000.0, "rol": 80000.0, "lucro": 9000.0, "lucro_pct": 11, "csp": 70000.0,
            "prazocliente": 30, "motivo_declinio": None, "motivo_perda": "Preço",
            "data_inclusao": datetime(2026, 3, 2, 8, 0, tzinfo=TZ),
            "data_alteracao": datetime(2026, 3, 20, 15, 0, tzinfo=TZ)}
    return {**base, **kw}


CFG = {"responsavel_lead": {"3": "Pessoa Três"}, "responsavel_projeto": {"1": "Pessoa Um"},
       "solicitante": {}}


# ─────────────────────────────────────────── a tradução, sem banco ─────────

@pytest.mark.parametrize("status,ativo,motivo,esperado", [
    # as combinações REAIS (sulista.gestaocomercial, 15/09/2026), com a contagem
    (3, 1, None, ("qualificacao", "")),            # 185
    (3, 2, "6", ("perdida", "sem_retorno")),      # 76
    (2, 2, "6", ("perdida", "nao_qualificado")),  # 37
    (1, 1, None, ("levantamento", "")),            # 36
    (None, 2, None, ("perdida", "outro")),         # 6
    (None, None, None, ("qualificacao", "")),      # 5
    (3, 1, "6", ("qualificacao", "")),             # 2 — motivo num lead ATIVO não fecha
    (2, 1, None, ("perdida", "nao_qualificado")),  # 2
    (1, 1, "4", ("levantamento", "")),             # 1
])
def test_cada_combinacao_real_do_lead_tem_o_seu_estagio(status, ativo, motivo, esperado):
    est, mot, _ = imp.estagio_do_lead({"status_negociacao": status, "ativoinativo": ativo,
                                       "motivo_perda": motivo})
    assert (est, mot) == esperado


def test_motivo_sem_equivalente_leva_o_texto_do_erp():
    est, mot, det = imp.estagio_do_lead({"status_negociacao": 3, "ativoinativo": 2, "motivo_perda": "3"})
    assert (est, mot) == ("perdida", "outro")
    assert "Sem prioridade no momento" in det


def test_lead_ativo_com_motivo_entra_aberto_e_diz_o_motivo():
    op = imp.oportunidade_do_lead(_lead(1, "X", motivo_perda="6"))
    assert op["estagio"] == "qualificacao" and op["fechada_em"] is None
    assert "Não respondeu" in op["observacoes"] and "seguia ativo" in op["observacoes"]


def test_oportunidade_leva_as_datas_e_o_potencial_mensal_do_erp():
    op = imp.oportunidade_do_lead(_lead(7, "X"))
    assert op["abertura"] == date(2026, 5, 4)
    assert op["previsao_fechamento"] == date(2026, 10, 30)
    assert op["receita_mensal_manual"] == 150000.0
    assert op["criado_em"] == "2026-05-04T09:12:00" and op["alterado_em"] == "2026-06-01T17:45:00"
    assert op["titulo"] == "Transporte de peças Joinville x Betim"
    for txt in ("lead nº 7", "Temperatura no ERP: Frio", "JOINVILLE - SC", "retorno em outubro"):
        assert txt in op["observacoes"]


def test_perda_nao_fecha_antes_de_abrir():
    op = imp.oportunidade_do_lead(_lead(1, "X", ativoinativo=2, motivo_perda="1",
                                        dtalteracao=datetime(2026, 1, 1, tzinfo=TZ)))
    assert op["fechada_em"] == op["abertura"]


def test_contato_com_telefone_estranho_nao_some_nem_entra_torto():
    ct = imp.contato_do_lead(_lead(1, "X", telefonecliente="ramal 32", emailcliente="sem arroba"))
    assert ct["telefone"] == "" and ct["email"] == ""
    assert "ramal 32" in ct["observacoes"] and "sem arroba" in ct["observacoes"]
    ok = imp.contato_do_lead(_lead(1, "X"))
    assert ok["telefone"] == "5547999998888" and ok["email"] == "maria@exemplo.test"


def test_normalizar_nome_so_tira_caixa_acento_pontuacao_e_espaco():
    assert imp.normalizar_nome("Tupy  S.A.") == imp.normalizar_nome("TUPY S A")
    assert imp.normalizar_nome("Fundição Açu") == "FUNDICAO ACU"
    assert imp.normalizar_nome("TUPY") != imp.normalizar_nome("TUPY SC")


def test_projeto_nao_entregue_com_data_de_entrega_perde_a_data_e_diz():
    """21 projetos reais: o banco de cá recusa entrega em quem não está entregue."""
    campos, _ = imp.projeto_do_erp(_projeto(1, 10, 1, "X", status_negocio=3), CFG, set())
    assert campos["status"] == "nao_iniciado" and campos["entrega"] is None
    assert "09/03/2026" in campos["observacoes"]


def test_projeto_entregue_sem_data_usa_o_aceite_e_diz():
    """2 projetos reais: entregue exige data de entrega."""
    campos, _ = imp.projeto_do_erp(_projeto(1, 10, 1, "X", data_entrega=None), CFG, set())
    assert campos["entrega"] == date(2026, 3, 20)
    assert "aceite" in campos["observacoes"]


def test_projeto_leva_negociacao_tipo_e_valores_nas_observacoes():
    campos, resp = imp.projeto_do_erp(_projeto(1, 10, 1, "X"), CFG, set())
    assert resp == "Pessoa Um" and campos["solicitante"] == "Cliente"
    assert campos["rob_mensal_manual"] == 88000.0 and campos["percentual"] == 100
    for txt in ("negociação no ERP: Não aceita", "Tipo de negócio no ERP: SPOT",
                "Motivo informado no ERP: Preço", "ROL/mês no ERP"):
        assert txt in campos["observacoes"]


def test_declinado_sem_motivo_ainda_passa_no_check_e_diz():
    campos, _ = imp.projeto_do_erp(_projeto(1, 10, 1, "X", status_negocio=4, motivo_perda=None,
                                            data_entrega=None), CFG, set())
    assert campos["status"] == "declinado" and campos["motivo_encerramento"] == "outro"
    assert "sem motivo" in campos["encerrado_detalhe"]


def test_codigo_sem_nome_no_de_para_aparece_como_codigo():
    faltam: set = set()
    _, resp = imp.projeto_do_erp(_projeto(1, 10, 1, "X", responsavel_projeto=4), CFG, faltam)
    assert resp == "Responsável 4 no ERP" and "responsavel_projeto 4" in faltam


def test_os_nomes_de_pessoas_ficam_fora_do_git():
    """O de-para mora em data/, que o .gitignore tira do repositório público."""
    raiz = Path(imp.__file__).resolve().parents[2]
    assert imp.CONFIG.parent == raiz / "data"
    r = subprocess.run(["git", "check-ignore", "-q", str(imp.CONFIG)], cwd=raiz)
    assert r.returncode == 0, "data/crm_importacao.json não está ignorado pelo git"


# ─────────────────────────────────────────── com banco de verdade ──────────

@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    pglocal.executar("INSERT INTO crm_contas(nome, ava_agrupamento, ava_nome, dono_nome) "
                     "VALUES('TUPY', 7, 'TUPY', 'A definir')", esquema=esquema_pg)
    return esquema_pg


def _erp():
    return {
        "leads": [
            _lead(1, "Metalúrgica Açu Ltda"),
            _lead(2, "METALURGICA ACU LTDA.", nomecliente="Maria Compras"),   # mesma empresa, mesmo contato
            _lead(3, "TUPY", ativoinativo=2, motivo_perda="4"),               # conta que já existe
            _lead(4, "Suzano", status_negociacao=1, emailcliente="x@y.test", nomecliente="João"),
        ],
        "projetos": [
            _projeto(10, 100, 1, "TUPY", status_negocio=3, data_entrega=None, data_aceite_declinio=None),
            _projeto(11, 100, 2, "TUPY"),
            _projeto(12, 101, 1, "Volvo", status_negocio=1, data_entrega=None, data_aceite_declinio=None),
        ],
        "repactuacoes": [
            {"id": 1, "cliente": 7, "grupo": "TUPY", "mes_repac": datetime(2026, 2, 1), "d1": 3.1,
             "dd1": datetime(2026, 2, 5), "d2": None, "dd2": None, "d3": None, "dd3": None, "neg": 2.0,
             "dneg": datetime(2026, 2, 10), "total": 5.1, "status": 1, "observacao": "repasse diesel",
             "dtinclusao": datetime(2026, 2, 3, tzinfo=TZ)},
            {"id": 2, "cliente": 99, "grupo": "SEM CONTA", "mes_repac": datetime(2026, 2, 1), "d1": None,
             "dd1": None, "d2": None, "dd2": None, "d3": None, "dd3": None, "neg": None, "dneg": None,
             "total": None, "status": None, "observacao": None, "dtinclusao": None},
        ],
        "grupos": {"VOLVO": {"codigo": 12, "nome": "VOLVO"}},
    }


def _contagens(esq):
    return {t: pglocal.um(f"SELECT count(*) AS n FROM {t}", esquema=esq)["n"]
            for t in ("crm_contas", "crm_contatos", "crm_oportunidades", "crm_projetos",
                      "crm_projeto_andamentos", "crm_interacoes", "crm_importados")}


def test_importa_e_rodar_de_novo_nao_duplica_nem_reescreve(esq):
    r = imp.importar(aplicar=True, esquema=esq, erp=_erp(), config=CFG)
    assert not r["falhas"], r["falhas"]
    assert r["leads"]["importados"] == 4
    assert r["contas"]["criadas"] == 3, r["contas"]          # Metalúrgica, Suzano, Volvo
    assert r["contas"]["vinculadas_ao_grupo"] == 1            # Volvo pelo nome do grupo 12
    assert r["contatos"] == 3, "o mesmo contato em dois leads da mesma empresa entrou duas vezes"
    assert r["projetos"]["importados"] == 2 and r["projetos"]["andamentos"] == 3
    assert r["repactuacoes"]["importadas"] == 1 and r["repactuacoes"]["sem_conta"] == ["SEM CONTA"]
    antes = _contagens(esq)
    tupy = pglocal.um("SELECT id FROM crm_contas WHERE ava_agrupamento=7", esquema=esq)["id"]
    assert pglocal.um("SELECT count(*) AS n FROM crm_oportunidades WHERE conta_id=%s", (tupy,),
                      esquema=esq)["n"] == 1, "o lead TUPY não caiu na conta que já existia"
    assert pglocal.um("SELECT count(*) AS n FROM crm_interacoes WHERE conta_id=%s AND automatica=1",
                      (tupy,), esquema=esq)["n"] == 1
    # o time edita no CÓRTEX; a reimportação não pode desfazer
    pglocal.executar("UPDATE crm_oportunidades SET titulo='editado no CÓRTEX' WHERE conta_id=%s",
                     (tupy,), esquema=esq)
    r2 = imp.importar(aplicar=True, esquema=esq, erp=_erp(), config=CFG)
    assert r2["leads"]["importados"] == 0 and r2["leads"]["ja_importados"] == 4
    assert r2["projetos"]["ja_importados"] == 2 and r2["repactuacoes"]["ja_importadas"] == 1
    assert _contagens(esq) == antes
    assert pglocal.um("SELECT titulo FROM crm_oportunidades WHERE conta_id=%s", (tupy,),
                      esquema=esq)["titulo"] == "editado no CÓRTEX"


def test_os_estados_do_banco_saem_como_o_erp_disse(esq):
    imp.importar(aplicar=True, esquema=esq, erp=_erp(), config=CFG)
    ops = pglocal.query(
        "SELECT titulo, estagio, motivo_perda, dono_nome, receita_mensal_manual::float8 AS rm, criado_em "
        "FROM crm_oportunidades", esquema=esq)
    assert sorted(r["estagio"] for r in ops) == ["levantamento", "perdida", "qualificacao", "qualificacao"]
    assert [r["motivo_perda"] for r in ops if r["estagio"] == "perdida"] == ["concorrente"]
    assert {r["dono_nome"] for r in ops} == {"Pessoa Três"}
    assert all(r["criado_em"].startswith("2026-05-04") for r in ops), "carimbou 'agora'"
    p = {r["codigo"]: r for r in pglocal.query(
        "SELECT codigo, status, versao, entrega, responsavel_nome FROM crm_projetos", esquema=esq)}
    assert sorted((x["status"], x["versao"]) for x in p.values()) == [("em_execucao", 1), ("entregue", 2)]


def test_o_de_para_mesma_conta_junta_o_nome_do_erp_a_conta_escolhida(esq):
    """"TUPY SC" não é "TUPY" pelo texto — só vira a mesma conta porque alguém
    que conhece o cliente disse. E o de-para para conta inexistente não some."""
    erp = _erp()
    erp["projetos"].append(_projeto(13, 102, 1, "Tupy SC"))
    cfg = {**CFG, "mesma_conta": {imp.normalizar_nome("TUPY SC"): "TUPY",
                                  imp.normalizar_nome("Suzano"): "CONTA QUE NAO EXISTE"}}
    r = imp.importar(aplicar=True, esquema=esq, erp=erp, config=cfg)
    assert r["contas"]["juntadas_pelo_de_para"] == 1
    tupy = pglocal.um("SELECT id FROM crm_contas WHERE ava_agrupamento=7", esquema=esq)["id"]
    assert pglocal.um("SELECT count(*) AS n FROM crm_projetos WHERE conta_id=%s", (tupy,),
                      esquema=esq)["n"] == 2, "o projeto de TUPY SC não caiu na conta TUPY"
    assert pglocal.um("SELECT count(*) AS n FROM crm_contas WHERE nome ILIKE 'tupy sc'",
                      esquema=esq)["n"] == 0
    assert any("CONTA QUE NAO EXISTE" in x for x in r["responsaveis_sem_nome"])


def test_ler_config_normaliza_as_chaves_do_de_para(tmp_path):
    arq = tmp_path / "cfg.json"
    arq.write_text('{"mesma_conta": {"Cahdam Volta Grande S.A.": "CAHDAM"}}', encoding="utf-8")
    cfg = imp.ler_config(arq)
    assert cfg["mesma_conta"] == {"CAHDAM VOLTA GRANDE S A": "CAHDAM"}
    assert cfg["responsavel_lead"] == {}


def test_simulacao_conta_tudo_e_nao_grava_nada(esq):
    antes = _contagens(esq)
    r = imp.importar(aplicar=False, esquema=esq, erp=_erp(), config=CFG)
    assert r["aplicado"] is False and r["leads"]["importados"] == 4 and r["projetos"]["importados"] == 2
    assert _contagens(esq) == antes


def test_um_lead_impossivel_nao_derruba_os_outros(esq):
    erp = _erp()
    erp["leads"].append(_lead(9, "Empresa Gigante", potencial=1e15))   # não cabe em numeric(14,2)
    r = imp.importar(aplicar=True, esquema=esq, erp=erp, config=CFG)
    assert [f[:2] for f in r["falhas"]] == [("lead", 9)]
    assert r["leads"]["importados"] == 4
    # a conta do lead que falhou fica (savepoint próprio), sem oportunidade órfã
    assert pglocal.um("SELECT count(*) AS n FROM crm_oportunidades", esquema=esq)["n"] == 4
