"""O disparo automático do prazo de indicação — e as três respostas dele.

A coisa que este aviso precisa acertar é QUANDO NÃO FALAR. Ele tem três
saídas, e confundir duas delas produz o pior resultado possível:

    há notificação vencendo   -> manda
    não há                    -> CALA, e isso é sucesso
    não dá para saber         -> CALA e DIZ o motivo, e isso é falha

Trocar a terceira pela segunda é o erro caro: com a coleta parada, a consulta
devolve zero notificação no prazo — indistinguível de "está tudo indicado". O
aviso silenciaria justamente quando parou de enxergar. É a família do
"integração parada se disfarça de tela vazia", que já custou 136 dias na
RasterJOR.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from api import pglocal
from api.smartec import armazenamento as arm
from api.smartec import leitura as lei
from api.whatsapp import agenda, modelos, valores

from .test_armazenamento import NOTIFICACAO


def _notificacao(esq, dias_ate_prazo, ident="n1", placa="AUJ5G32"):
    prazo = (date.today() + timedelta(days=dias_ate_prazo)).strftime("%d/%m/%Y")
    arm.gravar_infracoes([dict(NOTIFICACAO, IDENTIFICADOR_SMARTEC=ident,
                               PLACA=placa, PRAZO_INDICACAO=prazo)],
                         "notificacao", esq)


def _coleta_ha(esq, horas):
    """Uma passagem de coleta concluída há N horas."""
    cid = arm.carga_abrir("notificacao", esq)
    pglocal.executar(
        "UPDATE smt_carga SET fim = now() - (%s || ' hours')::interval,"
        " status = 'ok' WHERE id = %s", (str(horas), cid), esquema=esq)


# ───────────────────────────────────────────── os três estados
def test_com_prazo_vencendo_o_alerta_TEM_conteudo(esquema_pg):
    esq = esquema_pg
    _coleta_ha(esq, 1)
    _notificacao(esq, 0)
    r = lei.prazo_indicacao_alerta(2, esquema=esq)
    assert not r.get("erro") and not r.get("silencio")
    assert len(r["hoje"]) == 1


def test_sem_nada_vencendo_o_alerta_SILENCIA(esquema_pg):
    """Silêncio é sucesso: mandar "0 notificações vencem hoje" toda manhã
    transforma o aviso em ruído, e no dia em que houver três ninguém lê."""
    esq = esquema_pg
    _coleta_ha(esq, 1)
    _notificacao(esq, 30)          # existe, mas fora da janela de 2 dias
    r = lei.prazo_indicacao_alerta(2, esquema=esq)
    assert r.get("silencio")
    assert not r.get("erro")


def test_com_a_COLETA_PARADA_o_alerta_RECUSA_em_vez_de_silenciar(esquema_pg):
    """O TESTE MAIS IMPORTANTE DESTE ARQUIVO.

    Sem a guarda de frescor, a consulta devolveria zero notificação no prazo —
    a mesma resposta de "está tudo indicado". O aviso calaria exatamente
    quando parou de enxergar, e ninguém saberia por dias.
    """
    esq = esquema_pg
    _coleta_ha(esq, lei.HORAS_FRESCOR + 5)
    _notificacao(esq, 0)           # HÁ prazo vencendo, e ele não pode sumir
    r = lei.prazo_indicacao_alerta(2, esquema=esq)
    assert r.get("erro"), "coleta velha tem de RECUSAR, nunca silenciar"
    assert "coleta" in r["erro"].lower()
    assert not r.get("silencio")


def test_sem_coleta_nenhuma_tambem_recusa(esquema_pg):
    esq = esquema_pg
    _notificacao(esq, 0)
    r = lei.prazo_indicacao_alerta(2, esquema=esq)
    assert r.get("erro") and "nunca rodou" in r["erro"]


# ───────────────────────────────────────────── o provedor
def test_o_provedor_NUNCA_devolve_variavel_vazia():
    """`montar_texto` recusa o envio se qualquer variável vier em branco.

    Isso morde num caso específico: só há notificação vencendo HOJE e nenhuma
    nos próximos dias. `proximos` ficaria vazio e o aviso inteiro seria
    engolido — justamente no dia mais urgente.
    """
    d = {"hoje": [{"placa": "AUJ5G32", "descricao": "Velocidade",
                   "ait": "1L1", "orgao": "DER-SP",
                   "valor_a_pagar": 195.23, "pontuacao": 5}],
         "depois": [], "total_hoje": 195.23}
    v = valores.smartec_prazo_indicacao(d)
    vazias = [k for k, x in v.items() if not str(x).strip()]
    assert not vazias, f"variável vazia engoliria o aviso: {vazias}"
    assert "Nenhuma outra" in v["proximos"]


def test_o_provedor_traduz_erro_em_EXCECAO(esquema_pg):
    """Erro tem de SUBIR: silenciar aqui afirmaria que não há prazo correndo
    quando a verdade é que ninguém está olhando."""
    with pytest.raises(ValueError) as e:
        valores.smartec_prazo_indicacao({"erro": "a coleta está parada há 40 h"})
    assert "40 h" in str(e.value)


def test_o_provedor_sinaliza_silencio_sem_levantar():
    v = valores.smartec_prazo_indicacao({"silencio": "nada a vencer"})
    assert v == {"_silencio": "nada a vencer"}


# ───────────────────────────────────────────── a agenda
@pytest.fixture
def rotina(esquema_pg):
    modelos.gravar({"chave": "t-prazo", "nome": "T", "contexto": "smartec_prazo",
                    "corpo": "{{data}} {{quantidade}} {{lista}} {{total}} {{proximos}}"},
                   esquema=esquema_pg)
    return {"id": 7, "modelo": "t-prazo", "destinatarios": "5541999999999"}


def _provedor(monkeypatch, fn):
    monkeypatch.setitem(valores.PROVEDORES, "smartec_prazo_indicacao", fn)


def test_silencio_NAO_e_registrado_como_falha(esquema_pg, rotina, monkeypatch):
    """Registrar como falha faria a tela mostrar vermelho todo dia em que a
    operação está em dia — e aí o vermelho para de querer dizer alguma coisa."""
    _provedor(monkeypatch, lambda d=None: {"_silencio": "nenhuma a vencer"})
    saida = agenda.executar(rotina, ensaio=True, esquema=esquema_pg)
    assert "nada a enviar" in saida
    assert "FALHA" not in saida and "não enviado" not in saida


def test_coleta_parada_vira_recusa_COM_O_MOTIVO(esquema_pg, rotina, monkeypatch):
    """"não foi possível ler os números" é verdadeiro e inútil quando o motivo
    real é "a coleta está parada há 40 h" — e é esse texto que vai para a tela."""
    def _falha(d=None):
        raise ValueError("a coleta de notificações foi há 40 h")
    _provedor(monkeypatch, _falha)
    vals, erro = agenda.montar_texto("t-prazo", esquema=esquema_pg)
    assert "40 h" in erro, f"o motivo real sumiu: {erro!r}"
    assert not vals


def test_com_dado_bom_a_agenda_MONTA_o_texto(esquema_pg, rotina, monkeypatch):
    _provedor(monkeypatch, lambda d=None: {
        "data": "31/08/2026", "quantidade": "3", "lista": "L",
        "total": "R$ 455,55", "proximos": "P"})
    vals, erro = agenda.montar_texto("t-prazo", esquema=esquema_pg)
    assert erro == ""
    assert vals["quantidade"] == "3"
    assert "_silencio" not in vals


def test_o_modelo_semeado_usa_SO_variaveis_do_contexto(esquema_pg):
    """Variável fora do contexto é recusada na gravação — mas o seed entra por
    SQL, que não passa pelo validador. Este teste é o que fecha essa porta."""
    m = modelos.obter("smartec-prazo-indicacao", esquema=esquema_pg)
    assert m, "o seed do modelo não foi aplicado"
    declaradas = modelos.variaveis_do_contexto("smartec_prazo")
    assert set(m["variaveis"]) <= declaradas, (
        f"o modelo usa variável que o contexto não conhece: "
        f"{sorted(set(m['variaveis']) - declaradas)}")
    assert "257" in m["corpo"], (
        "o texto tem de dizer POR QUE o prazo importa — perder o prazo não é "
        "perder desconto, é ganhar a multa do art. 257 §8º")
