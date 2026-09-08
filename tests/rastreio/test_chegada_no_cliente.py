# -*- coding: utf-8 -*-
"""A chegada no cliente encerra o acompanhamento — e o que a separa da coleta.

O PEDIDO DE QUEM OPERA (08/09/2026): quando a carga chega no cliente, aquela é
a última mensagem, e o aviso para sozinho. Até então quem encerrava era a DATA
DE ENTREGA do CT-e, que a operação lança horas — às vezes um dia — depois de o
caminhão encostar na doca. Nesse intervalo o cliente recebia "faltam 0 km" de
hora em hora com o veículo parado no pátio dele, que é a mensagem que faz
alguém bloquear o número da empresa.

A ARMADILHA, e é o motivo de este arquivo existir: `CHEGADA NO CLIENTE` é a
MESMA macro que o rastreador manda quando o caminhão encosta para CARREGAR.
Encerrar na primeira ocorrência mataria o acompanhamento antes de a carga sair
da origem — e o cliente descobriria isso não recebendo mais nada.

AS LINHAS DE MACRO AQUI SÃO CÓPIA DO REAL, tiradas da viagem do CT-e 94540
(Joinville/SC ➜ São Leopoldo/RS, placa BCU7H92) lida no ERP em 08/09/2026. É a
regra da casa para dublê de formato externo: entrada montada a partir da
constante testada não testa a constante — e foi lendo esta viagem que
apareceram as duas coisas que a regra ingênua erraria (a chegada de coleta em
Joinville e as CINCO repetições da chegada no destino).
"""
from __future__ import annotations

import pytest

from api.rastreio import aviso, macros, mensagem

DESTINO = "Sao Leopoldo/RS"          # como o cadastro do ERP escreve: SEM acento


def _mov(rotulo, em, onde):
    """Uma movimentação como `macros.recentes()` a devolve — nosso rótulo."""
    return {"rotulo": rotulo, "marco": True, "onde": onde, "em": em}


#: A VIAGEM REAL, do mais recente para o mais antigo (a ordem da consulta).
#: Copiada da `ocorrenciarastreamento` da placa BCU7H92 em 08/09/2026, com as
#: macros de risco (`DESBLOQUEAR VEICULO`) já fora — quem as tira é a lista
#: branca de `PUBLICAS`, e isso é assunto de `test_macros.py`.
VIAGEM_94540 = [
    _mov("Chegou no cliente", "2026-09-08T07:34:07", "São Leopoldo/RS"),
    _mov("Chegou no cliente", "2026-09-08T07:33:24", "São Leopoldo/RS"),
    _mov("Chegou no cliente", "2026-09-08T05:50:17", "São Leopoldo/RS"),
    _mov("Chegou no cliente", "2026-09-08T05:06:19", "São Leopoldo/RS"),
    _mov("Chegou no cliente", "2026-09-08T05:05:16", "São Leopoldo/RS"),
    _mov("Viagem retomada",   "2026-09-08T04:32:41", "Gravataí/RS"),
    _mov("Parada para descanso", "2026-09-07T18:46:19", "Gravataí/RS"),
    _mov("Parado no trânsito", "2026-09-07T17:08:58", "Osório/RS"),
    _mov("Viagem retomada",   "2026-09-07T16:03:27", "Terra De Areia/RS"),
    _mov("Viagem iniciada",   "2026-09-07T09:19:02", "Joinville/SC"),
    _mov("Chegou na base da transportadora", "2026-09-05T08:51:08",
         "Joinville/SC"),
]

#: O MESMO CAMINHÃO CARREGANDO, na manhã do embarque — a hora exata em que o
#: recurso mais pode errar. É a viagem 94540 às 07:02 de 05/09: ele saiu da
#: base (05:46), retomou (06:37) e CHEGOU NO CLIENTE de Joinville para pegar a
#: carga. Tudo o que a regra ingênua pede está aqui — uma chegada no topo, um
#: início de viagem antes dela. O que salva é só o LUGAR.
ANTES_DE_SAIR = [
    _mov("Chegou no cliente", "2026-09-05T07:02:50", "Joinville/SC"),
    _mov("Viagem retomada",   "2026-09-05T06:37:44", "Joinville/SC"),
    _mov("Parada para abastecer", "2026-09-05T06:13:52", "Joinville/SC"),
    _mov("Viagem iniciada",   "2026-09-05T05:46:46", "Joinville/SC"),
]


# --------------------------------------------------------------------------
# a regra
# --------------------------------------------------------------------------
def test_a_chegada_no_DESTINO_encerra():
    ch = macros.chegada_no_destino(VIAGEM_94540, DESTINO)
    assert ch and ch["rotulo"] == "Chegou no cliente"


def test_a_chegada_para_CARREGAR_nao_encerra():
    """O caso que quem opera levantou, e a razão de a regra olhar o LUGAR.

    Aqui há tudo o que a regra ingênua pede: uma `CHEGADA NO CLIENTE` recente e
    um `INICIO DE VIAGEM` antes dela. Só que ela aconteceu em Joinville, que é
    de onde a carga SAI. Encerrar aqui tiraria o acompanhamento no dia do
    embarque.
    """
    assert macros.chegada_no_destino(ANTES_DE_SAIR, DESTINO) is None


def test_o_ACENTO_do_cadastro_nao_pode_decidir_isso():
    """`SAO LEOPOLDO` (cadastro do ERP) e `SÃO LEOPOLDO` (hub) são a mesma
    cidade. Comparando o texto cru, a regra NUNCA dispararia — e a falha seria
    muda: ninguém reclama de uma mensagem que continua chegando."""
    assert macros.mesmo_lugar("São Leopoldo/RS", "Sao Leopoldo/RS")
    assert macros.chegada_no_destino(VIAGEM_94540, "SAO LEOPOLDO/RS")
    assert not macros.mesmo_lugar("Joinville/SC", "Sao Leopoldo/RS")


def test_quem_VOLTOU_A_RODAR_nao_chegou():
    """Um início de viagem MAIS RECENTE que a chegada diz que o caminhão saiu
    de novo — trocou de doca, seguiu para o próximo. A carga não chegou: ela
    passou por ali."""
    saiu = [_mov("Viagem retomada", "2026-09-08T08:10:00",
                 "São Leopoldo/RS")] + VIAGEM_94540
    assert macros.chegada_no_destino(saiu, DESTINO) is None


def test_sem_ter_ESTADO_EM_VIAGEM_a_chegada_nao_conta():
    """O pedido é literal: a chegada que interessa é a de quem já estava
    rodando. Sem nenhum início de viagem antes dela, não há como distinguir a
    entrega de um caminhão que amanheceu no cliente."""
    so_chegada = [_mov("Chegou no cliente", "2026-09-08T05:05:16",
                       "São Leopoldo/RS")]
    assert macros.chegada_no_destino(so_chegada, DESTINO) is None


def test_a_hora_e_a_da_PRIMEIRA_chegada_do_bloco():
    """O rastreador repete a macro enquanto o veículo fica parado: cinco vezes
    entre 05:05 e 07:34 nesta viagem. Dizer "chegou às 07:34" seria contar como
    chegada a última vez que o equipamento repetiu — duas horas e meia depois
    de o caminhão encostar, para quem estava esperando na doca."""
    ch = macros.chegada_no_destino(VIAGEM_94540, DESTINO)
    assert ch["em"] == "2026-09-08T05:05:16"


def test_sem_destino_conhecido_a_regra_CALA():
    """Preferir o silêncio mantém o comportamento antigo (avisar até a entrega
    ser lançada). Errar para o outro lado custa o acompanhamento de quem está
    esperando a carga."""
    assert macros.chegada_no_destino(VIAGEM_94540, None) is None
    assert macros.chegada_no_destino(VIAGEM_94540, "") is None


def test_lugar_desconhecido_na_macro_nao_vale_por_destino():
    """Cidade vazia não casa com nada — nem com o destino."""
    mudo = [_mov("Chegou no cliente", "2026-09-08T05:05:16", None),
            _mov("Viagem iniciada", "2026-09-07T09:19:02", "Joinville/SC")]
    assert macros.chegada_no_destino(mudo, DESTINO) is None


def test_os_ROTULOS_que_a_regra_compara_sao_os_que_a_leitura_PRODUZ(monkeypatch):
    """String escrita à mão que descreve o código, conferida CONTRA o código.

    A regra compara rótulos NOSSOS; se a redação de `PUBLICAS` mudar e as
    constantes não acompanharem, ela para de disparar sem erro nenhum. Aqui a
    conferência é por execução: o que `recentes()` devolve tem de ser o que
    `chegada_no_destino` procura.
    """
    from datetime import datetime

    from api import db

    def falso(sql, params=None):
        return [{"macro": "CHEGADA NO CLIENTE",
                 "quando": datetime.fromisoformat("2026-09-08T05:05:16"),
                 "cidade": "SÃO LEOPOLDO", "uf": "RS"},
                {"macro": "INICIO DE VIAGEM",
                 "quando": datetime.fromisoformat("2026-09-07T09:19:02"),
                 "cidade": "JOINVILLE", "uf": "SC"}]

    monkeypatch.setattr(db, "query", falso)
    lidas = macros.recentes("BCU7H92")
    assert macros.chegada_no_destino(lidas, DESTINO), (
        "os rótulos da regra não são os que a leitura produz")


# --------------------------------------------------------------------------
# a mensagem
# --------------------------------------------------------------------------
def _carga(**kw) -> dict:
    base = {"documento": "CT-e 94540", "origem": "Joinville/SC",
            "destino": DESTINO, "estado": "em_viagem",
            "estado_rotulo": "Em viagem", "entregue_em": None,
            "movimentacao": VIAGEM_94540[:6], "andamento": {},
            "chegada_no_cliente": macros.chegada_no_destino(VIAGEM_94540,
                                                            DESTINO)}
    base.update(kw)
    return base


def test_a_mensagem_de_chegada_DIZ_que_e_a_ultima():
    """Sumir sem avisar seria a quarta resposta que esta casa não permite: quem
    recebeu catorze avisos e não recebe o décimo quinto conclui que o recurso
    quebrou, e liga para a transportadora — o telefonema que o acompanhamento
    existe para poupar."""
    t = aviso._texto(_carga())
    assert "último aviso" in t
    assert "05:05" in t and "São Leopoldo/RS" in t


def test_a_mensagem_de_chegada_SAI_com_o_rastreador_mudo():
    """O guard do estado próprio na assinatura.

    Sem ele a chegada cairia no ramo de "em viagem", que exige posição fresca —
    e a última mensagem, justamente a que encerra, não sairia para quem
    estivesse sem posição naquele minuto. A inscrição ficaria viva, avisando
    para sempre.
    """
    sem_posicao = _carga(andamento={"posicao_velha_min": 300})
    assert "último aviso" in (aviso._texto(sem_posicao) or "")
    assert mensagem.assinatura([sem_posicao]) == "CT-e 94540|chegou"


def test_a_assinatura_da_chegada_e_DIFERENTE_da_de_viagem():
    """Se as duas assinassem igual, a mensagem que encerra nunca sairia — o
    ciclo a trataria como 'nada mudou'."""
    viajando = _carga(chegada_no_cliente=None,
                      andamento={"tem_posicao": True, "progresso_pct": 98,
                                 "falta_km": 3, "por_rota": True})
    assert mensagem.assinatura([_carga()]) != mensagem.assinatura([viajando])


def test_na_mensagem_de_VARIAS_cargas_a_chegada_tambem_aparece():
    """Quem acompanha cinco cargas recebe uma mensagem só. A que chegou tem de
    se distinguir ali dentro, senão o encerramento acontece sem aviso."""
    outra = _carga(documento="CT-e 94541", chegada_no_cliente=None,
                   andamento={"tem_posicao": True, "progresso_pct": 40,
                              "falta_km": 300, "por_rota": True})
    t = mensagem.montar_varias([_carga(), outra])
    assert "CHEGOU NO CLIENTE" in t and "Último aviso desta carga" in t


# --------------------------------------------------------------------------
# o encerramento
# --------------------------------------------------------------------------
@pytest.fixture
def cenario(monkeypatch):
    """O mesmo cenário de `test_aviso.py`, com os encerramentos à vista."""
    enviados, encerradas = [], []

    def _montar(inscricoes, carga):
        monkeypatch.setattr(aviso.assinatura, "ativas", lambda: inscricoes)
        monkeypatch.setattr(aviso.assinatura, "dentro_da_janela",
                            lambda ins, agora=None: True)
        monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: carga)
        monkeypatch.setattr(aviso.wa, "enviar",
                            lambda fone, texto, **k: (
                                enviados.append((fone, texto)) or {"ok": True}))
        monkeypatch.setattr(aviso.assinatura, "marcar_envio",
                            lambda i, t, **k: None)
        monkeypatch.setattr(aviso.assinatura, "encerrar",
                            lambda i, m: encerradas.append((i, m)))
        return enviados, encerradas
    return _montar


def _ins(**kw) -> dict:
    base = {"id": 7, "grupo": 1, "empresa": 1, "filial": 19, "numero": 94540,
            "serie": 1, "telefone": "5541984251704", "ultimo_texto": None,
            "ultima_assinatura": None, "ultimo_envio": None, "envios": 0}
    base.update(kw)
    return base


def test_a_chegada_ENCERRA_depois_de_mandar_a_ultima_mensagem(cenario):
    """A ORDEM é o recurso. Encerrar antes tiraria a inscrição da lista com a
    novidade ainda por contar — o cliente ficaria sem a mensagem que explica
    por que as mensagens pararam."""
    enviados, encerradas = cenario([_ins()], _carga())
    r = aviso.rodar()
    assert enviados, "a última mensagem tem de sair"
    assert "último aviso" in enviados[0][1]
    assert encerradas == [(7, "chegou")]
    assert r["encerradas"] == 1


def test_a_DESCARGA_tambem_encerra(cenario):
    """`dtiniciodescarga` é a mesma notícia por outra fonte: o veículo está na
    doca. Continuar avisando dali em diante é o mesmo estrago."""
    _, encerradas = cenario([_ins()], _carga(estado="descarregando",
                                             chegada_no_cliente=None))
    aviso.rodar()
    assert encerradas == [(7, "chegou")]


def test_quem_se_inscreve_DEPOIS_da_chegada_nao_fica_pendurado(cenario):
    """A inscrição cuja primeira mensagem já foi a de chegada tem a assinatura
    igual à do ciclo seguinte. Sem encerrar também no ramo que CALA, ela
    ficaria viva até expirar sozinha aos 15 dias — silenciosa, e contando como
    monitoramento ativo no painel. Número errado sem sintoma."""
    carga = _carga()
    assin = mensagem.assinatura([carga])
    enviados, encerradas = cenario([_ins(ultima_assinatura=assin)], carga)
    r = aviso.rodar()
    assert enviados == [] and r["iguais"] == 1
    assert encerradas == [(7, "chegou")]


def test_o_ENSAIO_nao_encerra_nada(cenario):
    """Conferir o texto não pode mexer no cadastro de ninguém."""
    _, encerradas = cenario([_ins()], _carga())
    aviso.rodar(ensaio=True)
    assert encerradas == []


def test_a_carga_EM_VIAGEM_continua_sendo_avisada(cenario):
    """A sabotagem do outro lado: se qualquer carga encerrasse, este guard
    ficaria verde por engano em tudo."""
    viajando = _carga(chegada_no_cliente=None,
                      andamento={"tem_posicao": True, "progresso_pct": 40,
                                 "falta_km": 300, "por_rota": True})
    enviados, encerradas = cenario([_ins()], viajando)
    aviso.rodar()
    assert enviados and encerradas == []


# --------------------------------------------------------------------------
# o painel
# --------------------------------------------------------------------------
def test_o_motivo_novo_TEM_ROTULO_e_entra_no_KPI():
    """Código sem tabela de domínio não vira rótulo inventado — e KPI que
    contava só `entregue` desabaria sozinho no dia em que o encerramento comum
    passou a ser a macro, sem nada ter piorado."""
    from api.rastreio import painel
    assert painel.MOTIVOS.get("chegou")
    assert painel._fim({"ativo": False, "cancelado_por": "chegou"})[0] == \
        "chegou"
    assert "'chegou'" in painel.RESUMO_SQL, "o KPI ignora o motivo novo"
