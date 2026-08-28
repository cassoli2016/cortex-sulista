"""As integrações de fornecedor na tela de Saúde do Servidor.

A regra que estes testes guardam é a mesma da Prolog, agora valendo para a
Gobrax e a Monkey: a Saúde NÃO chama a API do fornecedor — ela mede a idade do
instantâneo que as telas mostram. E integração sem credencial é `info`, não
falha: o recurso não existe nesta instalação, e vermelho todo dia treina o
operador a ignorar alarme.

Tudo aqui é função pura sobre o diagnóstico. Nada de rede, banco ou relógio do
sistema além do que `_idade_min` lê.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from api import servidor as sv


def _agora(minutos_atras: int) -> str:
    return (datetime.now() - timedelta(minutes=minutos_atras)).strftime(
        "%Y-%m-%d %H:%M:%S")


def diag_gobrax(**kw) -> dict:
    d = {"configurado": True, "premiacao_configurada": True,
         "colecoes": {"estatisticas": {"competencia": "2026-08",
                                       "quando": _agora(10), "registros": 107},
                      "odometro": {"competencia": "2026-08",
                                   "quando": _agora(10), "registros": 107}}}
    d.update(kw)
    return d


def diag_monkey(**kw) -> dict:
    d = {"configurado": True, "modo_auth": "token", "seller_id": True,
         "ambiente": "prod", "coletado_em": _agora(30), "titulos": 42,
         "valor_saldo": 1234567.89}
    d.update(kw)
    return d


# ------------------------------------------------------------------ formato

def test_idade_ilegivel_nao_vira_agora():
    """Carimbo que ninguém consegue ler não pode sair verde como recém-feito."""
    assert sv._ha_quanto(None) == "em data ilegível"
    assert sv._ha_quanto(0) == "agora"
    assert sv._ha_quanto(45) == "há 45 min"
    assert sv._ha_quanto(200) == "há 3 h"
    assert sv._ha_quanto(4400) == "há 3 dias"


def test_competencia_sai_no_formato_de_quem_le():
    """A competência é guardada como '2026-08' porque assim ordena; a tela é
    lida por gente."""
    assert sv._competencia_br("2026-08") == "08/2026"
    assert sv._competencia_br("") == "—"


# -------------------------------------------------------------------- Gobrax

def test_gobrax_sem_token_e_info_e_diz_onde_configurar():
    s = sv._servico_gobrax(diag_gobrax(configurado=False))
    assert s["status"] == "info"
    assert "Gestão › Integrações" in s["detalhe"]


def test_gobrax_configurada_sem_coleta_e_alerta():
    s = sv._servico_gobrax(diag_gobrax(colecoes={}))
    assert s["status"] == "alerta"
    assert "nenhuma coleta" in s["detalhe"]


def test_gobrax_fresca_e_ok_com_a_competencia_e_o_tamanho():
    s = sv._servico_gobrax(diag_gobrax())
    assert s["status"] == "ok"
    assert "08/2026" in s["detalhe"]
    assert "107 veículos" in s["detalhe"]


def test_manda_a_colecao_mais_atrasada():
    """Estatística e odômetro se cruzam na Torre: uma fresca ao lado de outra
    parada é pior que as duas velhas, porque o cruzamento mente sem parecer."""
    d = diag_gobrax()
    d["colecoes"]["odometro"]["quando"] = _agora(600)   # 10 h
    s = sv._servico_gobrax(d)
    assert s["status"] == "alerta"
    assert "há 10 h" in s["detalhe"]


def test_coleta_parada_por_mais_de_duas_janelas_e_alerta():
    """A tarefa roda de 3 em 3 h. Foi assim que o cache ficou cinco dias
    parado sem ninguém perceber."""
    d = diag_gobrax()
    for c in d["colecoes"].values():
        c["quando"] = _agora(400)
    assert sv._servico_gobrax(d)["status"] == "alerta"
    for c in d["colecoes"].values():
        c["quando"] = _agora(380)
    assert sv._servico_gobrax(d)["status"] == "ok"


def test_uma_colecao_ausente_e_nomeada():
    d = diag_gobrax()
    del d["colecoes"]["odometro"]
    s = sv._servico_gobrax(d)
    assert "sem coleta de odômetro" in s["detalhe"]


def test_premiacao_sem_login_alerta_mesmo_com_telemetria_fresca():
    """São DUAS credenciais no mesmo fornecedor: o token move a telemetria, o
    login do portal move a premiação. Uma de pé com a outra caída é o caso que
    passava despercebido."""
    s = sv._servico_gobrax(diag_gobrax(premiacao_configurada=False))
    assert s["status"] == "alerta"
    assert "GOBRAX_EMAIL" in s["detalhe"]
    assert "nota × km" in s["detalhe"]


# -------------------------------------------------------------------- Monkey

def test_monkey_sem_credencial_e_info():
    s = sv._servico_monkey(diag_monkey(configurado=False, modo_auth="nenhuma"))
    assert s["status"] == "info"
    assert "falta credencial" in s["detalhe"]


def test_monkey_com_credencial_e_sem_seller_diz_qual_falta():
    """Credencial sem sellerId não faz chamada nenhuma — e o {id} da URL não
    tem como ser adivinhado daqui."""
    s = sv._servico_monkey(diag_monkey(configurado=False, modo_auth="token"))
    assert "MONKEY_SELLER_ID" in s["detalhe"]


def test_monkey_configurada_sem_coleta_diz_que_a_tupy_segue_por_planilha():
    s = sv._servico_monkey(diag_monkey(coletado_em=None))
    assert s["status"] == "alerta"
    assert "planilha" in s["detalhe"]


def test_monkey_em_producao_e_recente_e_ok():
    s = sv._servico_monkey(diag_monkey())
    assert s["status"] == "ok"
    assert "42 títulos" in s["detalhe"]
    assert "R$ 1.234.567,89" in s["detalhe"]


def test_homologacao_e_alerta_porque_os_titulos_sao_de_teste():
    """A tela de Antecipações não tem como saber sozinha que está olhando o
    ambiente de teste."""
    s = sv._servico_monkey(diag_monkey(ambiente="hmg"))
    assert s["status"] == "alerta"
    assert "HOMOLOGAÇÃO" in s["detalhe"]


def test_posicao_de_mais_de_um_dia_e_alerta():
    s = sv._servico_monkey(diag_monkey(coletado_em=_agora(1500)))
    assert s["status"] == "alerta"


def test_diagnostico_da_monkey_nao_conta_a_planilha_como_coleta():
    """`ultimo_envio('tupy')` traz também o envio feito por PLANILHA. Contá-lo
    faria a Saúde dizer que a API coletou quando ninguém coletou."""
    from api.monkey import servico as mk

    class RegistroFake:
        @staticmethod
        def ultimo_envio(portal):
            return {"ts": "2026-08-27 09:00:00", "origem": "planilha",
                    "titulos": 9, "valor_saldo": 1.0}

    original = mk.registro
    try:
        mk.registro = RegistroFake
        assert mk.diagnostico()["coletado_em"] is None
    finally:
        mk.registro = original


# ------------------------------------------------ banco de escrita (local)
#
# Terceiro banco da tela, ao lado do ERP e do Oracle da folha. A diferença de
# severidade é a regra: não configurado é instalação que não migrou nada
# (info); configurado e fora do ar é tela sem dado (erro).


def diag_pg(**kw) -> dict:
    d = {"configurado": True, "conectado": True, "onde": "127.0.0.1:5432/cortex",
         "erro": None, "ms": 4, "versao_schema": 2}
    d.update(kw)
    return d


def test_banco_local_ausente_e_info_nao_falha():
    """Quem ainda não migrou nada segue com os SQLite e está inteiro."""
    s = sv._servico_pglocal(diag_pg(configurado=False, conectado=False))
    assert s["status"] == "info"
    assert "SQLite" in s["detalhe"]


def test_banco_local_configurado_e_fora_do_ar_e_erro():
    """Depois do primeiro store migrado, sem este banco a tela fica sem dado —
    e isso não pode sair em cinza."""
    s = sv._servico_pglocal(diag_pg(conectado=False, erro="OperationalError"))
    assert s["status"] == "erro"
    assert "OperationalError" in s["detalhe"]


def test_banco_local_no_ar_diz_onde_e_em_que_versao():
    s = sv._servico_pglocal(diag_pg())
    assert s["status"] == "ok"
    assert "127.0.0.1:5432/cortex" in s["detalhe"]
    assert "schema v2" in s["detalhe"]


def test_banco_sem_migration_aplicada_e_alerta():
    """Conectar não basta: banco vazio responde SELECT e não tem tabela
    nenhuma — o que a tela precisa dizer é que falta aplicar."""
    s = sv._servico_pglocal(diag_pg(versao_schema=None))
    assert s["status"] == "alerta"
    assert "migration" in s["detalhe"]


# ---------------------------------------------------------- Z-API (WhatsApp)
#
# A Z-API é a única integração cujo estado NÃO existe como posição gravada: a
# Gobrax e a Monkey deixam um instantâneo em disco e a Saúde mede a idade dele;
# aqui a pergunta ("o aparelho está pareado?") só a API do fornecedor responde.
# O cache de 60 s do `cliente.estado()` é o que torna isso viável numa tela que
# recarrega a cada 5 s — sem ele seriam ~17 mil chamadas por dia.


def diag_zapi(**kw) -> dict:
    d = {"configurado": True, "ativo": True, "client_token": True,
         "limite_dia": 60, "janela": "08:00–20:00", "dentro_da_janela": True,
         "conectado": True, "celular": True, "erro": "", "hoje": 12,
         "ultimo": _agora(20), "falhas": 0}
    d.update(kw)
    return d


def test_zapi_sem_credencial_e_info():
    """Integração não instalada não é falha — vermelho todo dia treina o
    operador a ignorar alarme."""
    s = sv._servico_whatsapp(diag_zapi(configurado=False))
    assert s["status"] == "info"
    assert "instância e token" in s["detalhe"]


def test_zapi_configurada_mas_desligada_e_info():
    """Configurar não é autorizar a disparar: o interruptor desligado é um
    estado deliberado, não um defeito."""
    s = sv._servico_whatsapp(diag_zapi(ativo=False))
    assert s["status"] == "info"
    assert "DESLIGADO" in s["detalhe"]


def test_zapi_desconectada_e_ALERTA_e_explica_a_fila():
    """O ponto todo do cartão. Com o aparelho fora, a Z-API aceita as mensagens
    (HTTP 200) e as empilha até 1.000, disparando tudo quando ele voltar. Um
    cinza discreto aqui deixaria a cobrança de terça chegar no sábado à noite,
    em lote."""
    s = sv._servico_whatsapp(diag_zapi(conectado=False,
                                       erro="You are not connected."))
    assert s["status"] == "alerta"
    assert "fila" in s["detalhe"]
    assert "You are not connected." in s["detalhe"]


def test_zapi_conectada_mostra_quanto_do_limite_ja_foi():
    """É o número que decide se a próxima mensagem sai."""
    s = sv._servico_whatsapp(diag_zapi(hoje=41, limite_dia=60))
    assert s["status"] == "ok"
    assert "41 de 60 destinatários hoje" in s["detalhe"]


def test_zapi_pareada_com_o_celular_offline_e_alerta():
    """Instância conectada e aparelho sem internet é o estado que ninguém olha
    e que faz a mensagem parar na fila do mesmo jeito."""
    s = sv._servico_whatsapp(diag_zapi(celular=False))
    assert s["status"] == "alerta"
    assert "sem internet" in s["detalhe"]


def test_zapi_fora_da_janela_diz_isso_sem_virar_alarme():
    """Às 22h o envio está suspenso de propósito — é configuração, não
    problema."""
    s = sv._servico_whatsapp(diag_zapi(dentro_da_janela=False))
    assert s["status"] == "ok"
    assert "fora da janela de envio" in s["detalhe"]
