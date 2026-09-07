# -*- coding: utf-8 -*-
"""O Ritual Semanal de Gestão — o painel, as fontes e as regras do jogo.

DOIS RISCOS DIFERENTES SE GUARDAM AQUI, e o segundo é o que quase não tem
sintoma:

1. **As regras do jogo.** "Desvio sem ação não fecha pauta" e "três
   prioridades" existem no quadro da parede; se não valerem no código, o ritual
   vira uma reunião como as outras em duas semanas.

2. **As fontes automáticas.** Uma chave errada em `FONTES` — nome de campo,
   assinatura da função, caminho aninhado — NÃO levanta erro: `ler_fonte`
   captura e devolve `None`, e o indicador aparece vazio para sempre. Foi o que
   aconteceu ao escrever este módulo: três fontes da Operação nasceram mudas
   porque `get_analise_km` pede janela de data e foram chamadas sem argumento.
   Por isso o guard EXECUTA todas as fontes, e não só confere que a chave está
   escrita.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import pglocal
from api.gestao import comum, ritual


# ============================================================ as fontes

def test_toda_fonte_registrada_EXECUTA_sem_levantar():
    """O guard que teria pego as três mudas.

    Não afirma que a fonte devolve número — o ERP pode estar fora, e um teste
    que exige valor viraria alarme de terceiro. Afirma que ela RODA: chave
    inexistente, assinatura errada e caminho aninhado torto aparecem aqui.
    """
    for chave, f in ritual.FONTES.items():
        v = ritual.ler_fonte(chave)
        assert v is None or isinstance(v, float), (
            "%s devolveu %r, que não é número nem ausência" % (chave, v))


def test_as_QUATRO_gerencias_tem_fonte_automatica():
    """Se uma gerência não tem nenhuma fonte, o ritual nasce pedindo digitação
    inteira dela — e a promessa de "usar as ferramentas do CÓRTEX" fica só para
    as outras três. Isto é o guard da lista escrita à mão: as gerências vêm do
    SEED da migration, e as fontes do registro do módulo."""
    tem = {f.gerencia for f in ritual.FONTES.values()}
    assert tem >= {"comercial", "operacao", "manutencao", "rh"}, tem


def test_a_gerencia_da_fonte_existe_no_cadastro(esquema_pg):
    """Fonte apontando para gerência que o seed não cria é fonte que nunca
    aparece no formulário certo. Lista escrita à mão confere contra a outra
    ponta — as duas listas moram em arquivos diferentes."""
    chaves = {g["chave"] for g in ritual.gerencias(esquema=esquema_pg)}
    orfas = sorted({f.gerencia for f in ritual.FONTES.values()} - chaves)
    assert not orfas, "fonte apontando para gerência inexistente: %s" % orfas


def test_o_desvio_e_ORIENTADO_pelo_que_e_bom():
    """A coluna de desvio precisa poder ser lida de relance, e para isso
    positivo tem de ser sempre "melhor que a meta" — senão o painel põe lado a
    lado um −8% ótimo (multa abaixo da meta) e um −8% péssimo (receita abaixo
    da meta)."""
    # receita: realizado abaixo da meta é ruim -> negativo
    assert ritual._desvio(100, 92, "maior_melhor") == pytest.approx(-8)
    # multa: realizado abaixo da meta é BOM -> positivo
    assert ritual._desvio(100, 92, "menor_melhor") == pytest.approx(8)
    # sem meta não há desvio, e zero seria mentira ("está na meta")
    assert ritual._desvio(None, 92, "maior_melhor") is None
    assert ritual._desvio(0, 92, "maior_melhor") is None


# ============================================================ o ciclo

def _ciclo(esq, quando=None):
    return ritual.abrir_ciclo((quando or date.today()).isoformat(),
                              usuario="teste", esquema=esq)


def _indicador(esq, nome="Receita", fonte="manual", ger="comercial", **kw):
    gid = next(g["id"] for g in ritual.gerencias(esquema=esq) if g["chave"] == ger)
    d = {"nome": nome, "gerencia_id": gid, "fonte": fonte, "unidade": "R$"}
    d.update(kw)
    return ritual.salvar_indicador(d, esquema=esq)["id"]


def test_o_seed_cria_as_quatro_gerencias(esquema_pg):
    chaves = [g["chave"] for g in ritual.gerencias(esquema=esquema_pg)]
    assert chaves == ["comercial", "operacao", "manutencao", "rh"]


def test_abrir_a_MESMA_semana_duas_vezes_devolve_o_mesmo_ciclo(esquema_pg):
    """Dois painéis para a mesma semana é o erro que ninguém percebe: cada
    grupo preenche um, e na reunião os dois estão certos e diferentes."""
    a = _ciclo(esquema_pg)
    b = _ciclo(esquema_pg)
    assert a["id"] == b["id"]


def test_indicador_com_fonte_DESCONHECIDA_e_recusado(esquema_pg):
    """Chave inválida entraria como automática e ficaria vazia para sempre —
    sem erro nenhum. A recusa é na entrada porque descobrir na reunião custa a
    reunião."""
    with pytest.raises(ritual.DadoInvalido) as e:
        _indicador(esquema_pg, fonte="fonte_que_nao_existe")
    assert "desconhecida" in str(e.value).lower()


# ============================================================ o apontamento

def test_indicador_AUTOMATICO_recusa_realizado_digitado(esquema_pg):
    """E a recusa é dita. Gravar calado deixaria a pessoa achando que mandou no
    número, e a próxima pintura — que relê a fonte — desfaria na cara dela."""
    ind = _indicador(esquema_pg, nome="OS abertas", fonte="os_abertas",
                     ger="manutencao")
    c = _ciclo(esquema_pg)
    with pytest.raises(ritual.DadoInvalido) as e:
        ritual.apontar(c["id"], ind, {"realizado": 10}, "teste", esquema_pg)
    assert "não se digita" in str(e.value)


def test_indicador_manual_aceita_o_realizado(esquema_pg):
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"realizado": 8.5, "status": "verde"},
                   "teste", esquema_pg)
    linha = _linha(esquema_pg, c["id"], "NPS")
    assert linha["valor"] == pytest.approx(8.5)
    assert linha["preenchido"] is True


def test_o_apontamento_e_EDICAO_PARCIAL(esquema_pg):
    """Chave ausente não mexe; é o que permite o condutor ajustar a prioridade
    na reunião sem reenviar (e apagar) o desvio que o gerente escreveu."""
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"realizado": 8.5, "desvio": "queda no sul",
                                  "status": "amarelo"}, "ana", esquema_pg)
    ritual.apontar(c["id"], ind, {"status": "vermelho"}, "bruno", esquema_pg)
    linha = _linha(esquema_pg, c["id"], "NPS")
    assert linha["status"] == "vermelho"
    assert linha["desvio"] == "queda no sul", "a chave ausente apagou o desvio"
    assert linha["valor"] == pytest.approx(8.5)
    assert linha["preenchido_por"] == "bruno", "quem mexeu por último fica à vista"


def _linha(esq, ciclo_id, nome):
    p = ritual.painel(ciclo_id, esquema=esq)
    for g in p["gerencias"]:
        for l in g["linhas"]:
            if l["nome"] == nome:
                return l
    raise AssertionError("indicador %s não está no painel" % nome)


# ============================================================ regras do jogo

def _acao(esq, prazo=None, status="aberta"):
    r = pglocal.um("""INSERT INTO ges_acoes(o_que, responsavel_nome, prazo,
                                            status, criado_em)
                      VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                   ("Atacar o desvio", "Fulano",
                    prazo or (date.today() + timedelta(days=7)), status,
                    comum.agora()), esquema=esq)
    return r["id"]


def test_DESVIO_SEM_ACAO_NAO_FECHA_PAUTA(esquema_pg):
    """A regra central do quadro. Sem ela valendo no código, o ritual vira uma
    reunião comum em duas semanas."""
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"status": "vermelho", "realizado": 3},
                   "teste", esquema_pg)

    p = ritual.painel(c["id"], esquema=esquema_pg)
    assert len(p["bloqueios"]) == 1
    assert p["bloqueios"][0]["tipo"] == "desvio_sem_acao"

    with pytest.raises(ritual.DadoInvalido) as e:
        ritual.fechar(c["id"], "teste", esquema=esquema_pg)
    assert "não fecha pauta" in str(e.value)

    ritual.apontar(c["id"], ind, {"acao_id": _acao(esquema_pg)}, "teste", esquema_pg)
    assert ritual.fechar(c["id"], "teste", esquema=esquema_pg)["fechado"] is True


def test_VERDE_nao_exige_acao(esquema_pg):
    """Exigir ação de quem está na meta é o que ensina a inventar ação só para
    conseguir fechar a reunião."""
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"status": "verde", "realizado": 9},
                   "teste", esquema_pg)
    assert ritual.painel(c["id"], esquema=esquema_pg)["bloqueios"] == []


def test_forcar_o_fechamento_fica_REGISTRADO(esquema_pg):
    """A saída existe porque regra sem escape vira regra contornada por fora —
    alguém apontaria verde no vermelho para poder fechar, e aí o painel mente.
    O custo da exceção é ela ficar escrita."""
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"status": "vermelho"}, "teste", esquema_pg)
    r = ritual.fechar(c["id"], "ana", forcar=True, esquema=esquema_pg)
    assert r["com_bloqueio"] == 1
    obs = pglocal.um("SELECT observacoes FROM ges_ciclos WHERE id=%s",
                     (c["id"],), esquema=esquema_pg)["observacoes"]
    assert "ana" in obs and "sem ação" in obs


def test_ciclo_FECHADO_nao_aceita_apontamento(esquema_pg):
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"status": "verde"}, "teste", esquema_pg)
    ritual.fechar(c["id"], "teste", esquema=esquema_pg)
    with pytest.raises(ritual.DadoInvalido) as e:
        ritual.apontar(c["id"], ind, {"status": "vermelho"}, "teste", esquema_pg)
    assert "fechada" in str(e.value)


def test_SO_TRES_PRIORIDADES_e_o_teto_e_do_BANCO(esquema_pg):
    """A saída obrigatória da reunião são três entregas críticas. Uma quarta
    entrando em silêncio é como a lista deixa de significar prioridade — e o
    teto vive no índice único, não numa checagem que a próxima rota esquece."""
    c = _ciclo(esquema_pg)
    inds = [_indicador(esquema_pg, nome="Ind %d" % i, fonte="manual")
            for i in range(4)]
    for i, ind in enumerate(inds[:3], start=1):
        ritual.priorizar(c["id"], ind, i, "teste", esquema_pg)
    assert len(ritual.painel(c["id"], esquema=esquema_pg)["prioridades"]) == 3

    with pytest.raises(ritual.DadoInvalido):
        ritual.priorizar(c["id"], inds[3], 4, "teste", esquema_pg)

    # Trocar QUEM ocupa a posição 2 é operação de reunião e tem de funcionar.
    ritual.priorizar(c["id"], inds[3], 2, "teste", esquema_pg)
    p = ritual.painel(c["id"], esquema=esquema_pg)
    assert len(p["prioridades"]) == 3
    assert {d["prioridade"] for d in p["prioridades"]} == {1, 2, 3}


# ============================================== o fechamento da semana passada

def test_a_cobranca_olha_o_ciclo_ANTERIOR(esquema_pg):
    """A memória do que foi combinado é o que separa o ritual de uma conversa."""
    passada = _ciclo(esquema_pg, date.today() - timedelta(days=7))
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    feita = _acao(esquema_pg, prazo=date.today() - timedelta(days=1),
                  status="concluida")
    ritual.apontar(passada["id"], ind, {"status": "vermelho", "acao_id": feita},
                   "teste", esquema_pg)

    agora = _ciclo(esquema_pg)
    cob = ritual.cobranca(agora["id"], esquema=esquema_pg)
    assert cob["anterior"]["id"] == passada["id"]
    assert cob["resumo"] == {"prometidas": 1, "cumpridas": 1, "abertas": 0,
                             "taxa": 1.0}
    assert cob["itens"][0]["cumpriu"] is True


def test_sem_semana_anterior_a_taxa_e_NULA_e_nao_zero(esquema_pg):
    """0% diria "ninguém cumpriu nada" numa semana em que nada foi pedido."""
    c = _ciclo(esquema_pg)
    assert ritual.cobranca(c["id"], esquema=esquema_pg)["resumo"] == {}


def test_promessa_com_prazo_LA_NA_FRENTE_nao_e_descumprimento(esquema_pg):
    """Cobrar hoje uma ação que vence daqui a um mês é como a régua perde a
    credibilidade na terceira semana."""
    passada = _ciclo(esquema_pg, date.today() - timedelta(days=7))
    ind = _indicador(esquema_pg, nome="NPS", fonte="manual")
    longe = _acao(esquema_pg, prazo=date.today() + timedelta(days=30))
    ritual.apontar(passada["id"], ind, {"status": "vermelho", "acao_id": longe},
                   "teste", esquema_pg)
    cob = ritual.cobranca(_ciclo(esquema_pg)["id"], esquema=esquema_pg)
    assert cob["itens"] == [], "ação com prazo futuro entrou na cobrança"


# ============================================================ o painel

def test_o_painel_separa_SEM_STATUS_de_VERDE(esquema_pg):
    """Linha em branco não é linha verde. Somá-las como "sem problema" faria o
    painel ficar mais bonito exatamente quando ninguém preencheu."""
    _indicador(esquema_pg, nome="A", fonte="manual")
    _indicador(esquema_pg, nome="B", fonte="manual")
    c = _ciclo(esquema_pg)
    r = ritual.painel(c["id"], esquema=esquema_pg)["resumo"]
    # RELATIVO ao total, e nao "== 2": a migration SEMEIA oito indicadores, e
    # um teste que presume catalogo vazio esta medindo um banco que producao
    # nunca vai ter.
    assert r["verde"] == 0
    assert r["sem_status"] == r["indicadores"] >= 2


def test_o_painel_diz_quem_ainda_nao_preencheu(esquema_pg):
    """É a informação que existe ANTES da reunião, e a razão de o preenchimento
    ser antes dela."""
    _indicador(esquema_pg, nome="Indicador so do RH", fonte="manual", ger="rh")
    c = _ciclo(esquema_pg)
    pend = ritual.painel(c["id"], esquema=esquema_pg)["pendencias"]
    rh = next(p for p in pend if p["gerencia"] == "Recursos Humanos")
    assert "Indicador so do RH" in rh["indicadores"]
    assert rh["faltam"] == rh["de"], "ninguem preencheu nada ainda"


def test_indicador_inativado_SAI_do_painel_e_o_historico_fica(esquema_pg):
    """Inativar e não apagar: o apontamento de semanas passadas cita o
    indicador, e um DELETE reescreveria a história das reuniões."""
    ind = _indicador(esquema_pg, nome="A", fonte="manual")
    c = _ciclo(esquema_pg)
    ritual.apontar(c["id"], ind, {"status": "verde"}, "teste", esquema_pg)
    antes = ritual.painel(c["id"], esquema=esquema_pg)["resumo"]["indicadores"]
    ritual.excluir_indicador(ind, esquema=esquema_pg)
    depois = ritual.painel(c["id"], esquema=esquema_pg)["resumo"]["indicadores"]
    assert depois == antes - 1
    resta = pglocal.um("SELECT count(*) AS n FROM ges_apontamentos",
                       esquema=esquema_pg)["n"]
    assert resta == 1, "inativar apagou o apontamento"
