"""Gestão — atas, planos de ação e acompanhamento.

O que estes testes protegem, em ordem de importância:

1. **Atraso é derivado.** Se alguém um dia "otimizar" gravando um status
   'atrasada', `test_atraso_e_derivado_nao_gravado` quebra. É a regra que
   impede a tela de dizer que está tudo em dia no dia em que uma rotina falha.
2. **Apagar a ata não apaga o compromisso.** É a única forma de perder
   informação neste módulo, e ela tem de continuar impossível.
3. **O histórico é prova.** Prorrogação e mudança de status geram andamento;
   conclusão carimba data e reabrir a apaga.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import pglocal
from api.gestao import acoes, atas, comum, painel


@pytest.fixture()
def esq(esquema_pg):
    """O schema do teste, com os módulos redirecionados para ele."""
    comum.ESQUEMA = esquema_pg
    try:
        yield esquema_pg
    finally:
        comum.ESQUEMA = None


@pytest.fixture()
def usuario(esq):
    pglocal.executar(
        "INSERT INTO perfis(nome,descricao,admin,criado_em)"
        " VALUES('teste','',1,'2026-01-01')", esquema=esq)
    pid = pglocal.um("SELECT id FROM perfis LIMIT 1", esquema=esq)["id"]
    pglocal.executar(
        "INSERT INTO usuarios(nome,email,senha_hash,perfil_id,ativo,criado_em)"
        " VALUES('Ana Souza','ana@x.com','h',%s,1,'2026-01-01')",
        (pid,), esquema=esq)
    return pglocal.um("SELECT id FROM usuarios LIMIT 1", esquema=esq)["id"]


def _acao(esq, **kw):
    base = {"o_que": "Fazer algo", "responsavel_nome": "Fulano",
            "prazo": (date.today() + timedelta(days=10)).isoformat()}
    base.update(kw)
    return acoes.gravar(base, usuario="teste", esquema=esq)


# --------------------------------------------------------------------- ações

def test_atraso_e_derivado_nao_gravado(esq):
    """A regra central do módulo: não existe status 'atrasada' na tabela."""
    a = _acao(esq, prazo=(date.today() - timedelta(days=5)).isoformat())
    assert a["atrasada"] is True and a["dias_atraso"] == 5
    assert a["farol"] == "critico"
    # o que está GRAVADO continua sendo 'aberta'
    cru = pglocal.um("SELECT status FROM ges_acoes WHERE id=%s", (a["id"],),
                     esquema=esq)
    assert cru["status"] == "aberta"
    # e o CHECK do banco recusa o status inventado
    with pytest.raises(Exception):
        pglocal.executar("UPDATE ges_acoes SET status='atrasada' WHERE id=%s",
                         (a["id"],), esquema=esq)


def test_concluida_nao_fica_atrasada(esq):
    a = _acao(esq, prazo=(date.today() - timedelta(days=30)).isoformat(),
              status="concluida")
    assert a["atrasada"] is False
    assert a["farol"] == "ok"


def test_vence_em_7_dias(esq):
    a = _acao(esq, prazo=(date.today() + timedelta(days=3)).isoformat())
    assert a["vence_em_7"] is True and a["dias_para_prazo"] == 3
    assert a["farol"] == "atencao"


def test_responsavel_e_obrigatorio(esq):
    with pytest.raises(comum.DadoInvalido, match="[Rr]esponsável"):
        acoes.gravar({"o_que": "x", "prazo": "2026-12-01"}, esquema=esq)


def test_responsavel_por_id_herda_o_nome(esq, usuario):
    a = _acao(esq, responsavel_id=usuario, responsavel_nome="")
    assert a["responsavel"] == "Ana Souza"
    assert a["responsavel_nome"] == "Ana Souza"   # gravado junto do id


def test_usuario_inexistente_e_recusado(esq):
    """Id de usuário apagado gravaria ação sem dono que ninguém veria."""
    with pytest.raises(comum.DadoInvalido, match="não existe"):
        acoes.gravar({"o_que": "x", "responsavel_id": 999999,
                      "prazo": "2026-12-01"}, esquema=esq)


def test_valor_aceita_virgula_decimal(esq):
    """<input type=number> descarta a vírgula: 1234,56 viraria 123456."""
    assert _acao(esq, quanto="1.400.000,50")["quanto"] == 1400000.50
    assert _acao(esq, quanto="1.234")["quanto"] == 1234.0      # milhar pt-BR
    assert _acao(esq, quanto="0,99")["quanto"] == 0.99
    assert _acao(esq, quanto="")["quanto"] is None             # não estimado


def test_valor_invalido_e_recusado(esq):
    with pytest.raises(comum.DadoInvalido):
        _acao(esq, quanto="mil reais")


def test_data_aceita_iso_e_br(esq):
    # o contrato de saída é ISO: `JSONResponse` não serializa `date`, e é o
    # formato que o <input type=date> devolve
    assert _acao(esq, prazo="2026-12-01")["prazo"] == "2026-12-01"
    assert _acao(esq, prazo="01/12/2026")["prazo"] == "2026-12-01"
    with pytest.raises(comum.DadoInvalido):
        _acao(esq, prazo="31/02/2026")


def test_percentual_100_com_acao_aberta_e_recusado(esq):
    with pytest.raises(comum.DadoInvalido, match="100%"):
        _acao(esq, percentual=100, status="aberta")


def test_percentual_positivo_promove_para_em_andamento(esq):
    assert _acao(esq, percentual=30, status="aberta")["status"] == "em_andamento"


def test_concluir_forca_100_e_carimba_data(esq):
    a = _acao(esq, status="concluida", percentual=40)
    assert a["percentual"] == 100 and a["concluida_em"]


def test_reabrir_limpa_a_data_de_conclusao(esq):
    """Manter o carimbo faria o tempo de ciclo medir a primeira conclusão de
    uma tarefa que seguiu aberta por mais dois meses."""
    a = _acao(esq, status="concluida")
    assert a["concluida_em"]
    b = acoes.registrar_andamento(a["id"], "Reaberto.", status="aberta",
                                  esquema=esq)
    assert b["concluida_em"] is None


# ---------------------------------------------------------------- histórico

def test_criacao_gera_andamento_de_abertura(esq):
    a = _acao(esq)
    assert a["andamentos"] == 1
    assert a["parada_dias"] == 0      # nasce em zero, não em nulo


def test_prorrogacao_deixa_rastro(esq):
    """Sem o contador, a ação adiada seis vezes é igual à que nasceu ontem."""
    a = _acao(esq, prazo="2026-12-01")
    acoes.gravar({"o_que": a["o_que"], "responsavel_nome": "Fulano",
                  "prazo": "2027-01-15"}, acao_id=a["id"], esquema=esq)
    d = acoes.obter(a["id"], esquema=esq)
    assert d["prorrogacoes"] == 1
    assert any("Prazo alterado" in (h["texto"] or "") for h in d["historico"])


def test_mudanca_de_responsavel_deixa_rastro(esq):
    a = _acao(esq)
    acoes.gravar({"o_que": a["o_que"], "responsavel_nome": "Sicrano",
                  "prazo": a["prazo"]},
                 acao_id=a["id"], esquema=esq)
    d = acoes.obter(a["id"], esquema=esq)
    assert any("Responsável alterado" in (h["texto"] or "")
               for h in d["historico"])


def test_andamento_vazio_sem_mudanca_e_recusado(esq):
    a = _acao(esq)
    with pytest.raises(comum.DadoInvalido):
        acoes.registrar_andamento(a["id"], "", esquema=esq)


def test_andamento_muda_status_e_percentual(esq):
    a = _acao(esq)
    d = acoes.registrar_andamento(a["id"], "Andou.", status="em_andamento",
                                  percentual=40, esquema=esq)
    assert d["status"] == "em_andamento" and d["percentual"] == 40
    assert d["andamentos"] == 2


# --------------------------------------------------------------------- atas

def test_codigo_sequencial_por_ano(esq):
    a = atas.gravar({"titulo": "A", "data": "2026-03-01"}, esquema=esq)
    b = atas.gravar({"titulo": "B", "data": "2026-08-01"}, esquema=esq)
    c = atas.gravar({"titulo": "C", "data": "2027-01-05"}, esquema=esq)
    assert (a["codigo"], b["codigo"], c["codigo"]) == (
        "ATA-2026-001", "ATA-2026-002", "ATA-2027-001")


def test_ata_nasce_rascunho(esq):
    """Publicar é um ato, não o efeito de abrir o formulário."""
    assert atas.gravar({"titulo": "A", "data": "2026-03-01"},
                       esquema=esq)["status"] == "rascunho"


def test_participante_duplicado_por_nome_e_deduplicado(esq):
    a = atas.gravar({"titulo": "A", "data": "2026-03-01", "participantes": [
        {"nome": "Cristian Cassoli"}, {"nome": "cristian cassoli"},
        {"nome": "Outro", "presente": 0}]}, esquema=esq)
    assert a["participantes"] == 2 and a["presentes"] == 1


def test_hora_fim_antes_do_inicio_e_recusada(esq):
    with pytest.raises(comum.DadoInvalido, match="antes de começar"):
        atas.gravar({"titulo": "A", "data": "2026-03-01",
                     "hora_inicio": "14:00", "hora_fim": "09:00"}, esquema=esq)


def test_participantes_ausentes_no_payload_nao_apagam_a_lista(esq):
    """Chave ausente = não mexi; lista vazia = não havia ninguém."""
    a = atas.gravar({"titulo": "A", "data": "2026-03-01",
                     "participantes": [{"nome": "Zé"}]}, esquema=esq)
    b = atas.gravar({"titulo": "A editada", "data": "2026-03-01"},
                    reuniao_id=a["id"], esquema=esq)
    assert b["participantes"] == 1
    c = atas.gravar({"titulo": "A", "data": "2026-03-01", "participantes": []},
                    reuniao_id=a["id"], esquema=esq)
    assert c["participantes"] == 0


def test_apagar_ata_nao_apaga_as_acoes(esq):
    """A única forma de perder informação neste módulo — e tem de ser
    impossível. O compromisso assumido não deixa de existir porque alguém
    arrumou o registro da reunião."""
    a = atas.gravar({"titulo": "A", "data": "2026-03-01"}, esquema=esq)
    ac = _acao(esq, reuniao_id=a["id"])
    atas.excluir(a["id"], esquema=esq)
    viva = acoes.obter(ac["id"], esquema=esq)
    assert viva is not None
    assert viva["reuniao_id"] is None          # órfã, mas viva


def test_ata_inexistente_e_recusada_na_acao(esq):
    with pytest.raises(comum.DadoInvalido, match="ata"):
        _acao(esq, reuniao_id=999999)


# ------------------------------------------------------------------- painel

def test_resumo_sem_conclusao_nao_inventa_ciclo_zero(esq):
    """Zero em verde faria parecer velocidade perfeita onde não houve
    conclusão nenhuma — a regra do 'não informado'."""
    _acao(esq)
    r = painel.resumo(esq)
    assert r["ciclo_medio"] is None and r["ciclo_n"] == 0
    assert r["pct_no_prazo"] is None


def test_resumo_conta_por_farol(esq):
    _acao(esq, prazo=(date.today() - timedelta(days=2)).isoformat())
    _acao(esq, prazo=(date.today() + timedelta(days=2)).isoformat())
    _acao(esq, prazo=(date.today() + timedelta(days=90)).isoformat())
    r = painel.resumo(esq)
    assert (r["abertas"], r["atrasadas"], r["vence_7"], r["em_dia"]) == (3, 1, 1, 2)


def test_por_responsavel_marca_base_fraca(esq):
    """Menos de 3 ações é anedota, não série — fica atenuado, nunca escondido."""
    for _ in range(4):
        _acao(esq, responsavel_nome="Muitas")
    _acao(esq, responsavel_nome="Poucas")
    linhas = {l["responsavel"]: l for l in painel.por_responsavel(esq)}
    assert linhas["Muitas"]["base_fraca"] is False
    assert linhas["Poucas"]["base_fraca"] is True


def test_por_responsavel_ordena_por_atrasadas(esq):
    _acao(esq, responsavel_nome="Em dia")
    _acao(esq, responsavel_nome="Devendo",
          prazo=(date.today() - timedelta(days=9)).isoformat())
    assert painel.por_responsavel(esq)[0]["responsavel"] == "Devendo"


def test_area_vazia_vira_rotulo_explicito(esq):
    _acao(esq)
    assert painel.por_area(esq)[0]["area"] == "(sem área)"


def test_evolucao_tem_12_meses_mesmo_sem_dado(esq):
    assert len(painel.evolucao(esq)) == 12


def test_paradas_usa_o_ultimo_andamento(esq):
    a = _acao(esq)
    assert painel.paradas(esq, dias=21) == []
    pglocal.executar("UPDATE ges_andamentos SET ts='2020-01-01T00:00:00'"
                     " WHERE acao_id=%s", (a["id"],), esquema=esq)
    p = painel.paradas(esq, dias=21)
    assert len(p) == 1 and p[0]["parada_dias"] > 1000


def test_minhas_filtra_pelo_responsavel(esq, usuario):
    _acao(esq, responsavel_id=usuario)
    _acao(esq, responsavel_nome="Outro")
    m = painel.minhas(usuario, esq)
    assert m["abertas"] == 1


def test_minhas_sem_usuario_nao_estoura(esq):
    assert painel.minhas(None, esq)["acoes"] == []


def test_tudo_traz_o_payload_da_tela(esq):
    _acao(esq)
    d = painel.tudo(esq)
    for chave in ("resumo", "por_responsavel", "por_area", "evolucao",
                  "paradas", "atrasadas", "proximas", "usuarios", "areas"):
        assert chave in d, chave


# -------------------------------------------------------------------- lista

def test_lista_ordena_atrasadas_primeiro(esq):
    _acao(esq, o_que="futura", prazo=(date.today() + timedelta(days=30)).isoformat())
    _acao(esq, o_que="atrasada", prazo=(date.today() - timedelta(days=3)).isoformat())
    assert acoes.listar(esq)[0]["o_que"] == "atrasada"


def test_lista_joga_encerradas_para_o_fim(esq):
    """Lista dominada por registro encerrado enterra o que precisa de ação."""
    _acao(esq, o_que="concluida", status="concluida")
    _acao(esq, o_que="aberta")
    assert acoes.listar(esq)[0]["o_que"] == "aberta"


def test_filtro_de_atrasadas(esq):
    _acao(esq, o_que="ok")
    _acao(esq, o_que="tarde", prazo=(date.today() - timedelta(days=1)).isoformat())
    r = acoes.listar(esq, atrasadas=True)
    assert [a["o_que"] for a in r] == ["tarde"]


def test_busca_alcanca_o_responsavel(esq):
    _acao(esq, responsavel_nome="Joana Silva")
    _acao(esq, responsavel_nome="Outro")
    assert len(acoes.listar(esq, busca="joana")) == 1


def test_contar_ignora_o_limite(esq):
    for i in range(5):
        _acao(esq, o_que=f"a{i}")
    assert len(acoes.listar(esq, limite=2)) == 2
    assert acoes.contar(esq) == 5


def test_excluir_devolve_a_acao_para_a_auditoria(esq):
    a = _acao(esq, o_que="some")
    apagada = acoes.excluir(a["id"], esquema=esq)
    assert apagada["o_que"] == "some"
    assert acoes.obter(a["id"], esquema=esq) is None
    assert acoes.excluir(a["id"], esquema=esq) is None


def test_o_payload_serializa_em_json(esq):
    """`JSONResponse` não serializa `datetime.date` — a rota estouraria com
    500, que o Cloudflare troca pela página de erro dele, e a tela receberia
    "erro interno da API" sem JSON nenhum."""
    import json
    _acao(esq)
    atas.gravar({"titulo": "A", "data": "2026-03-01"}, esquema=esq)
    json.dumps(painel.tudo(esq))          # levanta TypeError se escapar um date
    json.dumps(acoes.listar(esq))
    json.dumps(atas.listar(esq))


# ------------------------------------------------------ relatório de e-mail

def test_relatorio_de_cobranca_nao_levanta(esq):
    """Relatório que estoura na rotina desassistida some do mundo."""
    from api.correio import relatorios
    _acao(esq, prazo=(date.today() - timedelta(days=4)).isoformat())
    r = relatorios.montar("acoes_pendentes")
    for chave in ("assunto", "html", "texto", "vazio"):
        assert chave in r
    assert "falha ao gerar" not in r["assunto"]
    assert r["vazio"] is False      # "o plano está em dia" também é notícia
