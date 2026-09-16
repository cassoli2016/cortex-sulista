# -*- coding: utf-8 -*-
"""O canal entre o setor de agregados e o proprietário.

O QUE ESTE ARQUIVO PROTEGE: que a fila continue sendo fila (assunto de lista
fechada, dono, estado e ordem pelo mais parado) e que o escopo não escorra —
ler a conversa de outro dono é, aqui, ler quanto a Sulista deve a ele.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.agregado import conversas as conv
from tests.agregado.conftest import cadastrar

COD, FONE = "12345678000190", "5541999990001"
OUTRO_COD, OUTRO_FONE = "99988877766", "5541999990002"


@pytest.fixture
def dono(esq):
    cadastrar(esq, COD, FONE, nome="Transportes Fulano")
    return {"proprietario_codigo": COD, "nome": "Transportes Fulano"}


def test_a_lista_de_assuntos_tem_dois_lados(esq, dono):
    """`quem_abre` é o que faz a lista ter dois lados sem ter duas tabelas."""
    do_dono = {a["chave"] for a in conv.assuntos("agregado", esq)}
    do_setor = {a["chave"] for a in conv.assuntos("setor", esq)}
    assert "acerto" in do_dono and "recado" not in do_dono
    assert "recado" in do_setor and "acerto" not in do_setor
    # `documento` é de AMBOS: aparece nos dois
    assert "documento" in do_dono and "documento" in do_setor
    # e o texto de ajuda vai junto — é ele que resolve metade dos pedidos
    assert all(a["ajuda"] for a in conv.assuntos("agregado", esq))


def test_assunto_fora_da_lista_e_recusado_no_servidor(esq, dono):
    """A tela só oferece o que pode, mas quem garante é o servidor: assunto
    livre chegando pelo corpo do pedido é o mesmo que não ter lista."""
    with pytest.raises(conv.Recusa):
        conv.abrir(dono, "reclamacao_geral", "texto", esq)
    with pytest.raises(conv.Recusa):
        conv.abrir(dono, "recado", "assunto que é do setor, não dele", esq)


def test_abrir_cria_a_linha_do_tempo_com_a_abertura(esq, dono):
    r = conv.abrir(dono, "acerto", "O acerto 8801 não caiu na conta.", esq)
    d = conv.ler(dono, r["id"], esq)
    assert d["conversa"]["assunto_rotulo"] == "Acerto e pagamento"
    assert [m["papel"] for m in d["mensagens"]] == ["sistema", "agregado"]
    assert d["mensagens"][0]["evento"] == "abertura"


def test_dois_pedidos_do_mesmo_assunto_viram_um_so(esq, dono):
    """Duas filas sobre o mesmo assunto é como o setor responde uma e a outra
    envelhece — a recusa ENSINA onde continuar."""
    conv.abrir(dono, "acerto", "primeiro", esq)
    with pytest.raises(conv.Recusa) as exc:
        conv.abrir(dono, "acerto", "segundo", esq)
    assert "já tem um pedido aberto" in str(exc.value)


def test_o_teto_de_pedidos_abertos(esq, dono):
    for chave in ("acerto", "viagem", "desconto", "abastecimento", "documento"):
        conv.abrir(dono, chave, "texto de " + chave, esq)
    with pytest.raises(conv.Recusa) as exc:
        conv.abrir(dono, "outro", "mais um", esq)
    assert str(conv.MAX_ABERTAS) in str(exc.value)


def test_a_conversa_de_outro_dono_nao_se_le_nem_se_responde(esq, dono):
    """O dono entra no WHERE junto do id: não existe aqui busca por id seguida
    de conferência — o `if` é a linha que alguém apaga."""
    r = conv.abrir(dono, "acerto", "meu pedido", esq)
    cadastrar(esq, OUTRO_COD, OUTRO_FONE, nome="Outro Dono")
    alheio = {"proprietario_codigo": OUTRO_COD, "nome": "Outro Dono"}
    for acao in (lambda: conv.ler(alheio, r["id"], esq),
                 lambda: conv.responder(alheio, r["id"], "oi", esq)):
        with pytest.raises(conv.Recusa) as exc:
            acao()
        # A MESMA recusa de "não existe": distinguir as duas transformaria a
        # rota num contador de conversas alheias.
        assert str(exc.value) == "Conversa não encontrada."


def test_o_setor_responde_pega_a_conversa_e_a_bola_volta_para_o_dono(esq, dono):
    r = conv.abrir(dono, "acerto", "cadê o pagamento?", esq)
    caixa = conv.caixa(esquema=esq)
    assert caixa["conversas"][0]["nao_lidas"] == 1
    assert caixa["conversas"][0]["status"] == "aberta"
    conv.responder_setor(r["id"], "Vence sexta.", autor_nome="Fernanda", esquema=esq)
    minhas = conv.minhas(dono, esq)["conversas"][0]
    assert minhas["status"] == "aguardando_agregado"
    assert minhas["nao_lidas"] == 1 and minhas["atendente"] == "Fernanda"
    # atribuir no ato é o que faz "em atendimento" significar alguma coisa
    assert conv.caixa(esquema=esq)["conversas"][0]["atendente"] == "Fernanda"


def test_ler_zera_o_nao_lido_do_lado_que_leu(esq, dono):
    r = conv.abrir(dono, "acerto", "pergunta", esq)
    conv.responder_setor(r["id"], "resposta", autor_nome="Fernanda", esquema=esq)
    assert conv.minhas(dono, esq)["nao_lidas"] == 1
    conv.ler(dono, r["id"], esq)
    assert conv.minhas(dono, esq)["nao_lidas"] == 0
    # e o lado do setor continua com o dele próprio
    assert conv.caixa(esquema=esq)["conversas"][0]["nao_lidas"] == 0


def test_o_dono_responde_e_o_pedido_volta_para_o_setor(esq, dono):
    r = conv.abrir(dono, "acerto", "pergunta", esq)
    conv.responder_setor(r["id"], "resposta", autor_nome="Fernanda", esquema=esq)
    conv.responder(dono, r["id"], "obrigado, mas falta a parcela 2", esq)
    assert conv.minhas(dono, esq)["conversas"][0]["status"] == "em_atendimento"


def test_pedido_encerrado_nao_se_reabre_escrevendo(esq, dono):
    """Reabrir é EXPLÍCITO, e não efeito de escrever: sem isso a fila deixa de
    ter fim."""
    r = conv.abrir(dono, "acerto", "pergunta", esq)
    conv.mudar_status(r["id"], "resolvida", autor_nome="Fernanda", esquema=esq)
    with pytest.raises(conv.Recusa):
        conv.responder(dono, r["id"], "voltei", esq)


def test_a_caixa_ordena_pelo_mais_parado_e_diz_o_que_esta_parado(esq, dono):
    """É a diferença entre uma FILA e uma caixa de e-mail: numa caixa por data,
    quem escreveu há três semanas nunca mais é visto."""
    velho = conv.abrir(dono, "acerto", "de três semanas atrás", esq)
    novo = conv.abrir(dono, "viagem", "de agora", esq)
    pglocal.executar(
        "UPDATE agr_conversas SET ultima_em = now() - interval '21 days' "
        "WHERE id = %(id)s", {"id": velho["id"]}, esq)
    caixa = conv.caixa(esquema=esq)
    assert [c["id"] for c in caixa["conversas"]] == [velho["id"], novo["id"]]
    assert caixa["conversas"][0]["parada_dias"] >= 20
    assert caixa["paradas"] == 1 and caixa["vivas"] == 2
    assert conv.contagem(esq)["paradas"] == 1


def test_mudar_o_estado_vira_mensagem_de_sistema_na_mesma_linha_do_tempo(esq, dono):
    r = conv.abrir(dono, "acerto", "pergunta", esq)
    conv.mudar_status(r["id"], "em_atendimento", autor_nome="Fernanda", esquema=esq)
    conv.mudar_status(r["id"], "resolvida", autor_nome="Fernanda", esquema=esq)
    msgs = conv.ler_setor(r["id"], esq)["mensagens"]
    eventos = [m["evento"] for m in msgs if m["evento"]]
    assert eventos == ["abertura", "status", "status"]
    assert "encerrou" in msgs[-1]["texto"]
    # devolver à fila tira o dono
    conv.mudar_status(r["id"], "aberta", autor_nome="Fernanda", esquema=esq)
    assert conv.caixa("aberta", esquema=esq)["conversas"][0]["atendente"] == ""


def test_o_setor_abre_conversa_pelo_id_opaco_e_ela_nasce_esperando_o_dono(esq, dono):
    ident = pglocal.um("SELECT id FROM agr_vinculos", {}, esq)["id"]
    r = conv.abrir_setor(ident, "recado", "Documentação 2026",
                         "Precisamos do CRLV atualizado.", autor_nome="Fernanda",
                         esquema=esq)
    minhas = conv.minhas(dono, esq)["conversas"][0]
    assert minhas["origem"] == "setor" and minhas["status"] == "aguardando_agregado"
    assert minhas["nao_lidas"] == 1
    assert conv.ler_setor(r["id"], esq)["conversa"]["atendente"] == "Fernanda"
    with pytest.raises(conv.Recusa):
        conv.abrir_setor(9999, "recado", "t", "texto", esquema=esq)


def test_o_telefone_do_aviso_sai_do_vinculo_e_o_texto_nao_leva_conteudo(esq, dono):
    """WhatsApp é lido em tela de bloqueio, e 3 dos 63 donos dividem o número
    com outro cadastro: o aviso diz que existe resposta, nunca qual."""
    r = conv.abrir(dono, "acerto", "pergunta", esq)
    fone, nome = conv.telefone_de(r["id"], esq)
    assert fone == FONE and nome == "Transportes Fulano"
    assert "acerto" not in conv.AVISO.lower() and "R$" not in conv.AVISO
    assert "app" in conv.AVISO.lower()


def test_o_documento_do_dono_nao_sai_em_payload_nenhum(esq, dono):
    r = conv.abrir(dono, "acerto", "pergunta", esq)
    conv.responder_setor(r["id"], "resposta", autor_nome="Fernanda", esquema=esq)
    for payload in (conv.minhas(dono, esq), conv.caixa(esquema=esq),
                    conv.ler(dono, r["id"], esq), conv.ler_setor(r["id"], esq)):
        assert COD not in str(payload), payload


def test_a_rota_do_painel_exige_a_tela_e_nao_e_publica():
    """O canal do setor é do PAINEL; o do app é de quem está fora da casa. Os
    dois prefixos são vizinhos (`/api/agregados/` × `/api/agregado/`) e não
    podem se confundir."""
    from api import auth
    assert set(dict(auth.ROTA_TELAS)["/api/agregados/canal"]) == {"agrcanal"}
    assert not auth._rota_publica("/api/agregados/canal/conversas")
    assert auth._rota_publica("/api/agregado/conversas")
    assert auth.TELAS["agrcanal"] == ("Canal do Agregado", "Operação")
