"""O envio e as sete recusas que protegem o número da Sulista.

Cada teste aqui corresponde a uma forma de perder o WhatsApp comercial da
empresa — não a uma validação de formulário. A documentação da própria Z-API
diz que o fator nº 1 de banimento é a quantidade de DESTINATÁRIOS DISTINTOS
alcançados numa janela curta, com relato de bloqueio a partir de 10 números
novos. Banimento não é "a integração caiu": é o número comercial fora do ar,
com o histórico das conversas dentro dele.

Todos usam `esquema_pg`: o freio LÊ a trilha para decidir, então testá-lo sem
banco testaria outra coisa.
"""
from __future__ import annotations

import pytest

from api.whatsapp import cliente, envio, registro
from tests.whatsapp.conftest import gravar_config, http_falso


@pytest.fixture(autouse=True)
def trilha(esquema_pg, monkeypatch):
    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    return esquema_pg


# ------------------------------------------------------------------- sucesso

def test_envio_normal_grava_o_id_da_mensagem():
    """O `messageId` é o único jeito de casar uma linha da nossa trilha com o
    que aparece no painel da Z-API quando algo é contestado."""
    gravar_config()
    r = envio.enviar("(47) 99999-8888", "Bom dia", usuario="ana@sulista",
                     http=http_falso())
    assert r["ok"] is True
    assert r["telefone"] == "5547999998888"
    linha = registro.listar(1)[0]
    assert linha["ok"] == 1
    assert linha["message_id"] == "D241XXXX732339502B68"
    # gravado NORMALIZADO: é o que faz o contador de destinatários funcionar
    assert linha["telefone"] == "5547999998888"


def test_o_texto_que_sai_leva_a_assinatura():
    """Mensagem de um número que o destinatário não tem salvo, sem dizer quem
    é, é o perfil que as pessoas denunciam — e denúncia derruba o número."""
    gravar_config(assinatura="Sulista Transportes")
    http = http_falso()
    envio.enviar("47999998888", "Sua carga saiu.", http=http)
    corpo = http.chamadas[-1]["dados"].decode()
    assert "Sulista Transportes" in corpo


def test_assinatura_nao_e_repetida_se_ja_estiver_no_texto():
    gravar_config(assinatura="Sulista Transportes")
    texto = envio.montar_texto("Aviso da Sulista Transportes")
    assert texto.count("Sulista Transportes") == 1


# ------------------------------------------------------------------- recusas

def test_numero_invalido_nao_chega_a_chamar_a_zapi():
    gravar_config()
    http = http_falso()
    r = envio.enviar("(20) 99999-8888", "oi", http=http)
    assert r["ok"] is False and "DDD 20" in r["erro"]
    assert http.chamadas == []


def test_integracao_desligada_recusa_e_REGISTRA():
    """Configurar não é autorizar. E a recusa entra na trilha: é o registro
    dela que responde 'por que a régua de cobrança não mandou nada ontem'."""
    gravar_config(ativo=False)
    r = envio.enviar("47999998888", "oi", http=http_falso())
    assert r["ok"] is False and "DESLIGADO" in r["erro"]
    assert registro.listar(1)[0]["ok"] == 0


def test_fora_da_janela_recusa():
    """A janela existe porque mensagem de empresa às 3 da manhã vira
    reclamação, e é a denúncia do usuário que o WhatsApp lê."""
    gravar_config(janela_inicio="03:00", janela_fim="03:01")
    r = envio.enviar("47999998888", "oi", http=http_falso())
    assert r["ok"] is False
    assert "janela" in r["erro"] and "03:00" in r["erro"]


def test_instancia_desconectada_NAO_manda(monkeypatch):
    """A recusa menos óbvia e a mais cara. Com o celular fora, a Z-API responde
    200 e ENFILEIRA até mil mensagens, disparando tudo quando o aparelho
    voltar — a cobrança de terça chegando no sábado à noite, em lote. Reportar
    'enviado com sucesso' aí seria mentira duas vezes."""
    gravar_config()
    http = http_falso(conectado=False)
    r = envio.enviar("47999998888", "oi", http=http)
    assert r["ok"] is False and "não está conectada" in r["erro"]
    assert "fila" in r["erro"]
    assert not any(c["url"].endswith("/send-text") for c in http.chamadas)


def test_limite_diario_para_o_disparo():
    gravar_config(limite_dia=3)
    http = http_falso()
    for i in range(3):
        assert envio.enviar(f"4799999000{i}", "oi", http=http)["ok"] is True
    r = envio.enviar("47999990009", "oi", http=http)
    assert r["ok"] is False
    assert "Limite diário" in r["erro"] and "meia-noite" in r["erro"]


def test_continuar_conversa_ja_aberta_NAO_gasta_o_limite():
    """O limite conta destinatários NOVOS. Responder alguém com quem já se
    falou hoje é o caso de menor risco que existe — bloqueá-lo faria o freio
    atrapalhar exatamente o uso legítimo."""
    gravar_config(limite_dia=1)
    http = http_falso()
    assert envio.enviar("47999990001", "primeira", http=http)["ok"] is True
    # o limite já está estourado para números novos...
    assert envio.enviar("47999990002", "outro", http=http)["ok"] is False
    # ...mas a conversa aberta continua
    assert envio.enviar("47999990001", "segunda", http=http)["ok"] is True


def test_tentativa_recusada_nao_consome_a_cota_do_dia():
    """Se a recusa contasse, uma sequência de erros de configuração comeria o
    limite e travaria o envio de verdade depois."""
    gravar_config(limite_dia=2)
    http = http_falso(conectado=False)
    for i in range(5):
        envio.enviar(f"4799999100{i}", "oi", http=http)
    assert registro.contar_destinatarios_hoje() == 0


# ----------------------------------------------------- o contrato de nunca cair

def test_falha_inesperada_nao_levanta_para_quem_chamou():
    """Uma rotina agendada que estoura exceção morre inteira por causa de um
    número na quinta linha da lista."""
    gravar_config()

    def explode():
        raise RuntimeError("a biblioteca mudou de ideia")

    r = envio.enviar("47999998888", "oi", http=http_falso(ao_enviar=explode))
    assert r["ok"] is False
    assert "RuntimeError" in r["erro"] or "Não foi possível" in r["erro"]


def test_erro_da_zapi_nunca_carrega_o_token_para_a_trilha():
    """A mensagem de erro vai para a tela, para o log E para o banco. Se o
    token entrasse aí, ele viraria linha permanente da trilha."""
    from tests.whatsapp.conftest import TOKEN
    gravar_config()
    r = envio.enviar("47999998888", "oi",
                     http=http_falso(envio_status=401, envio_corpo={}))
    assert r["ok"] is False
    assert TOKEN not in r["erro"]
    assert TOKEN not in registro.listar(1)[0]["erro"]


# ------------------------------------------------------------------ em lote

def test_lote_reavalia_o_limite_a_cada_destinatario():
    """Uma lista de 200 números tem de parar no limite com a explicação, não
    passar direto porque a checagem foi feita uma vez no começo."""
    gravar_config(limite_dia=2)
    r = envio.enviar_varios(
        ["47999990001", "47999990002", "47999990003", "47999990004"],
        "aviso", http=http_falso())
    assert r["enviados"] == 2 and r["falhas"] == 2
    assert "Limite diário" in r["resultados"][-1]["erro"]


def test_lote_ignora_repeticao_do_mesmo_numero_em_formatos_diferentes():
    gravar_config()
    r = envio.enviar_varios("47 99999-8888, (47)99999-8888, 5547999998888",
                            "oi", http=http_falso())
    assert len(r["resultados"]) == 1
