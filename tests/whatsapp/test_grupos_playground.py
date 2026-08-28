"""Grupos como destino, e o playground da API do fornecedor.

DUAS COISAS AQUI FORAM DESCOBERTAS OLHANDO A API DE VERDADE, e as duas
contradiziam a suposição razoável:

1. **O id de grupo desta conta é `120363421141267015-group`** — não `@g.us`
   nem `<criador>-<timestamp>`. Reconhecer só os formatos documentados fazia o
   grupo real cair na porta do TELEFONE e sair recusado com "DDD 12 não
   existe", mandando conferir DDD onde não há DDD nenhum.
2. **O sufixo é OBRIGATÓRIO.** Guardar só os dígitos, que é o mais limpo,
   devolve `HTTP 400: Phone is wrong`. O canônico é o que a API aceita, não o
   que é bonito.

E o playground tem uma regra que não pode ceder: **não existe URL livre**. Um
proxy genérico daria acesso a `/send-text` sem o limite diário, sem a janela de
horário e sem a trilha — o jeito de perder o número, embrulhado como ferramenta
de diagnóstico.
"""
from __future__ import annotations

import pytest

from api.whatsapp import numeros as n
from api.whatsapp import playground as pg


# --------------------------------------------------------------- reconhecer

def test_os_tres_formatos_de_grupo_convergem_para_o_canonico():
    canonico = "120363421141267015-group"
    for entrada in ("120363421141267015-group", "120363421141267015@g.us",
                    "120363421141267015"):
        assert n.destino(entrada) == (n.TIPO_GRUPO, canonico), entrada


def test_o_formato_antigo_fica_como_esta():
    """`5547999998888-1616969528` já é um id completo; acrescentar `-group` a
    ele seria inventar."""
    assert n.destino("5547999998888-1616969528") == \
        (n.TIPO_GRUPO, "5547999998888-1616969528")


def test_grupo_e_testado_ANTES_do_telefone():
    """Um id novo tem 18 dígitos e passaria pela porta do telefone como "número
    com dígitos demais", saindo com a mensagem errada."""
    tipo, _ = n.destino("120363421141267015")
    assert tipo == n.TIPO_GRUPO


def test_normalizar_continua_recusando_grupo():
    """`normalizar` é telefone. Quem aceita os dois é `destino`."""
    with pytest.raises(n.TelefoneInvalido):
        n.normalizar("120363421141267015-group")


def test_telefone_continua_telefone():
    assert n.destino("(47) 99999-8888") == (n.TIPO_TELEFONE, "5547999998888")


def test_id_de_grupo_NAO_e_formatado_como_telefone():
    """Máscara de telefone num id de grupo produz `(12) 03630-19502650977`, que
    parece um número e não é o de ninguém."""
    assert n.formatar("120363421141267015-group") == "120363421141267015-group"


def test_o_mesmo_grupo_em_formatos_diferentes_conta_UMA_vez():
    """Senão o freio mediria formato de digitação em vez de conversa."""
    fora = n.separar("120363421141267015-group, 120363421141267015@g.us")
    assert len(fora) == 1


def test_grupo_e_telefone_convivem_no_mesmo_campo():
    fora = n.separar("(47) 99999-8888, 120363421141267015-group")
    assert len(fora) == 2


# ---------------------------------------------------------------- playground

def test_endpoint_fora_do_catalogo_e_recusado():
    """A garantia central: não há URL livre."""
    with pytest.raises(pg.ChamadaRecusada, match="não está no catálogo"):
        pg.preparar("qualquer-coisa", {})


def test_ENVIO_e_recusado_apontando_o_caminho_certo():
    """Listado para se saber que existe; bloqueado porque pularia o limite
    diário, a janela e a trilha."""
    with pytest.raises(pg.ChamadaRecusada) as exc:
        pg.preparar("send-text", {})
    assert "Enviar mensagem" in str(exc.value)
    assert "limite" in str(exc.value)


def test_parametro_de_caminho_e_obrigatorio():
    with pytest.raises(pg.ChamadaRecusada, match="Informe"):
        pg.preparar("group-metadata", {})


def test_parametro_de_caminho_nao_deixa_escapar_para_outro_endpoint():
    """`../` num segmento alcançaria endpoint fora do catálogo — inclusive o
    de envio."""
    for veneno in ("../send-text", "a/b", "x?y=1", "..%2Fsend-text"):
        with pytest.raises(pg.ChamadaRecusada, match="caractere"):
            pg.preparar("group-metadata", {"id": veneno})


def test_query_so_aceita_numero():
    with pytest.raises(pg.ChamadaRecusada, match="número"):
        pg.preparar("groups", {"page": "1&x=2"})


def test_monta_o_caminho_com_os_padroes_do_catalogo():
    assert pg.preparar("groups", {}) == ("GET", "/groups?page=1&pageSize=50")
    assert pg.preparar("groups", {"page": "3", "pageSize": "10"}) == \
        ("GET", "/groups?page=3&pageSize=10")
    assert pg.preparar("group-metadata", {"id": "120363421141267015-group"}) == \
        ("GET", "/group-metadata/120363421141267015-group")


def test_leitura_simples_nao_precisa_de_parametro():
    assert pg.preparar("status", {}) == ("GET", "/status")
    assert pg.preparar("queue-clear", {}) == ("DELETE", "/queue")


def test_todo_endpoint_declara_risco_e_explica_o_que_faz():
    """`risco` decide cor, confirmação e bloqueio na tela. Quem acrescentar um
    endpoint tem de declarar o que ele faz — não há padrão silencioso."""
    for e in pg.CATALOGO:
        assert e["risco"] in (pg.LEITURA, pg.ESCRITA, pg.ENVIO), e["id"]
        assert e["nome"] and e["descricao"], e["id"]
        assert e["metodo"] in ("GET", "POST", "DELETE"), e["id"]
        assert e["caminho"].startswith("/"), e["id"]


def test_os_endpoints_que_derrubam_o_numero_sao_ESCRITA():
    """`/disconnect` e `/restart` tiram o WhatsApp da empresa do ar; limpar a
    fila descarta mensagem que ainda não saiu. Nenhum pode ser 'leitura'."""
    for ident in ("disconnect", "restart", "queue-clear"):
        assert pg.POR_ID[ident]["risco"] == pg.ESCRITA, ident
