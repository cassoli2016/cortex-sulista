# -*- coding: utf-8 -*-
"""O painel de administração dos monitoramentos (tela `mon`).

O QUE ESTES GUARDS PROTEGEM: uma tela que mostra TELEFONE de gente que não é
usuária do sistema, lendo de DOIS bancos diferentes, sobre um recurso cuja
falha é muda. Cada um desses três é um jeito diferente de a tela mentir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.rastreio import painel


def _ins(**kw) -> dict:
    agora = datetime.now(timezone.utc)
    base = {"id": 1, "grupo": 1, "empresa": 1, "filial": 2, "numero": 94540,
            "serie": 2, "telefone": "5541996859121",
            "criado_em": agora - timedelta(hours=5),
            "expira_em": agora + timedelta(days=15),
            "ativo": True, "cancelado_em": None, "cancelado_por": None,
            "ultimo_envio": agora - timedelta(minutes=30), "envios": 2,
            "expirada": False}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# como a inscrição terminou
# --------------------------------------------------------------------------
def test_expirar_NAO_e_cancelar():
    """A inscrição morre sozinha aos 15 dias porque ninguém volta para
    cancelar. Contar isso como desistência faria a taxa de cancelamento mentir
    para cima — e é ela que diz se o recurso está incomodando alguém."""
    assert painel._fim(_ins(ativo=True, expirada=True))[0] == "expirada"
    assert painel._fim(_ins(ativo=False, cancelado_por="pagina"))[0] == "pagina"


def test_motivo_desconhecido_sai_CRU_e_dizendo_que_e_cru():
    """`encerrar()` aceita texto livre. Código sem tabela de domínio não vira
    rótulo inventado: melhor um código feio e verdadeiro que um bonito e
    errado."""
    chave, rotulo = painel._fim(_ins(ativo=False, cancelado_por="sei la o que"))
    assert chave == "outro"
    assert "sei la o que" in rotulo


def test_quem_encerrou_pela_TELA_nao_vira_uma_linha_por_administrador():
    """`cancelado_por` guarda `admin:<e-mail>`. Agrupar por esse texto cru
    faria a tabela "como os monitoramentos terminam" ganhar UMA LINHA POR
    ADMINISTRADOR — identidade virando dimensão, que é como uma tabela de
    resumo deixa de caber na tela."""
    a = painel._fim(_ins(ativo=False, cancelado_por="admin:ana@sulista.local"))
    b = painel._fim(_ins(ativo=False, cancelado_por="admin:bruno@sulista.local"))
    assert a == b, "dois administradores, uma linha só"
    assert a[0] == "admin"


def test_o_email_de_quem_encerrou_NAO_se_perde():
    """Ele sai do rótulo e vai para o detalhe da linha — que é onde a pergunta
    'quem foi?' se faz. Agrupar sem guardar seria perder a resposta."""
    l = painel._linha(_ins(ativo=False, cancelado_por="admin:ana@sulista.local"), {})
    assert l["fim_detalhe"] == "ana@sulista.local"
    assert "ana@sulista.local" not in l["fim_rotulo"]
    # E quem terminou por outro motivo não ganha detalhe nenhum.
    assert painel._linha(_ins(ativo=False, cancelado_por="pagina"), {})["fim_detalhe"] is None


# --------------------------------------------------------------------------
# os dois bancos
# --------------------------------------------------------------------------
def test_o_ERP_fora_do_ar_NAO_derruba_a_tela(monkeypatch):
    """A carga mora no AVA, que é réplica de produção de TERCEIRO. Sem ele a
    inscrição ainda aparece — documento, telefone e datas vivem no banco da
    casa. O que some é o enriquecimento."""
    def _explode(sql, p):
        raise RuntimeError("replica fora do ar")

    monkeypatch.setattr(painel.db, "query", _explode)
    assert painel._cargas([_ins()]) == {}
    l = painel._linha(_ins(), {})
    assert l["documento"] == "CT-e 94540"
    assert l["origem"] is None and l["destino"] is None
    # E A TELA DIZ QUE FALTOU, em vez de apresentar a carga como inexistente.
    assert l["estado"] == "desconhecido"


def test_a_carga_e_buscada_em_UM_LOTE_e_nao_uma_por_linha(monkeypatch):
    """Uma consulta por linha seria N+1 contra a réplica de um terceiro — é
    assim que se derruba a tela no dia em que houver duzentas inscrições."""
    chamadas = []

    def _conta(sql, p):
        chamadas.append(p)
        return []

    monkeypatch.setattr(painel.db, "query", _conta)
    painel._cargas([_ins(id=1, numero=1), _ins(id=2, numero=2),
                    _ins(id=3, numero=3)])
    assert len(chamadas) == 1, "uma consulta para o lote inteiro"
    assert len(chamadas[0]["chaves"]) == 3


def test_cargas_repetidas_viram_UMA_chave(monkeypatch):
    """Duas pessoas acompanhando a MESMA carga é o caso normal (remetente e
    destinatário). Mandar a chave duas vezes só engorda a consulta."""
    chamadas = []
    monkeypatch.setattr(painel.db, "query",
                        lambda sql, p: chamadas.append(p) or [])
    painel._cargas([_ins(id=1, telefone="1"), _ins(id=2, telefone="2")])
    assert len(chamadas[0]["chaves"]) == 1


# --------------------------------------------------------------------------
# o que a tela mostra
# --------------------------------------------------------------------------
def test_o_telefone_sai_FORMATADO_e_nunca_em_URL():
    """Guardado normalizado, exibido formatado — a casa tem UM validador de
    telefone e é ele que manda no formato. A ação de encerrar manda o `id`,
    não o número."""
    l = painel._linha(_ins(), {})
    assert l["telefone"] == "(41) 99685-9121"
    assert "id" in l and isinstance(l["id"], int)


def test_ultimo_envio_velho_NAO_vira_alarme_no_payload():
    """O aviso não reenvia mensagem idêntica: caminhão parado a noite toda
    produz, corretamente, zero envio. O payload entrega a IDADE e deixa a
    interpretação para a tela — que a explica em vez de pintar de vermelho."""
    agora = datetime.now(timezone.utc)
    l = painel._linha(_ins(ultimo_envio=agora - timedelta(hours=9)), {})
    assert l["ultimo_envio_min"] >= 8 * 60
    assert "alerta" not in repr(l) and "erro" not in repr(l)


def test_sem_nenhum_envio_a_idade_e_NULA_e_nao_zero():
    """Zero seria lido como 'agora'. Ausência de envio é ausência, e a tela
    escreve 'n/d'."""
    assert painel._linha(_ins(ultimo_envio=None), {})["ultimo_envio_min"] is None


def test_a_duracao_de_quem_ainda_acompanha_conta_ate_AGORA():
    """Inscrição viva não tem fim; medir até `cancelado_em` nulo daria `None` e
    a coluna ficaria vazia justamente para quem está em curso."""
    assert painel._linha(_ins(), {})["horas"] >= 4.9


# --------------------------------------------------------------------------
# os tetos vêm do código, não da tela
# --------------------------------------------------------------------------
def test_os_tetos_sao_LIDOS_das_constantes(monkeypatch):
    """Digitar os números na tela faria ela mentir no dia em que o limite
    mudasse no código — e ninguém conferiria."""
    from api.rastreio import assinatura
    monkeypatch.setattr(painel.pglocal, "query", lambda sql, p: [])
    f = painel._freios()
    assert f["teto_por_fone"] == assinatura.MAX_ATIVAS_POR_FONE
    assert f["teto_por_carga"] == assinatura.MAX_POR_CARGA
    assert f["teto_criadas_24h"] == assinatura.MAX_CRIADAS_24H
    assert f["dias_validade"] == assinatura.DIAS_VALIDADE


# --------------------------------------------------------------------------
# a ação de encerrar
# --------------------------------------------------------------------------
def test_encerrar_inscricao_inexistente_e_RECUSA_e_nao_falha(monkeypatch):
    """Recusa legível é 4xx. Um 5xx aqui viraria a página do Cloudflare no
    lugar da mensagem — o corpo do erro nunca chegaria em quem clicou."""
    monkeypatch.setattr(painel.pglocal, "query", lambda sql, p: [])
    r = painel.encerrar(99, "ana@sulista.local")
    assert r["ok"] is False and r["motivo"]


def test_encerrar_grava_QUEM_foi(monkeypatch):
    """Um 'cancelado' genérico misturaria a desistência de quem espera a carga
    com a intervenção de quem administra — que são coisas opostas para quem lê
    o número."""
    from api.rastreio import assinatura
    gravado = []
    monkeypatch.setattr(painel.pglocal, "query", lambda sql, p: [{"id": 7}])
    monkeypatch.setattr(assinatura, "encerrar",
                        lambda i, m: gravado.append((i, m)))
    assert painel.encerrar(7, "ana@sulista.local")["ok"] is True
    assert gravado[0][0] == 7
    assert gravado[0][1].startswith("admin:")
    assert "ana@sulista.local" in gravado[0][1]


@pytest.mark.parametrize("ruim", ["abc", None, ""])
def test_encerrar_com_id_invalido_recusa_sem_tocar_no_banco(monkeypatch, ruim):
    def _nao_chame(*a, **k):
        raise AssertionError("nao devia consultar o banco")

    monkeypatch.setattr(painel.pglocal, "query", _nao_chame)
    assert painel.encerrar(ruim, "ana@sulista.local")["ok"] is False
