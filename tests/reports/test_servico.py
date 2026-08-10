"""Validação do report, nome do anexo e montagem do corpo da issue.

Tudo aqui é função pura: o serviço recebe o payload já desserializado, o
usuário vindo da SESSÃO (nunca do cliente) e um relógio explícito, para o
nome do anexo não depender da hora em que a suíte roda.
"""
from __future__ import annotations

import base64
from datetime import datetime

import pytest

from api.reports import servico as srv

USUARIO = {"nome": "Cristian Cassoli", "email": "cristian@sulista.com.br",
           "perfil": "Diretoria"}
QUANDO = datetime(2026, 8, 10, 14, 32, 5)


def _b64(n_bytes: int) -> str:
    return base64.b64encode(b"x" * n_bytes).decode()


def _payload(**troca) -> dict:
    base = {
        "tipo": "bug",
        "gravidade": "alta",
        "titulo": "Saldo do Fluxo de Caixa não bate com o extrato",
        "descricao": "Abri o Fluxo, filtrei a filial 1 e o saldo veio R$ 2 mil menor.",
        "contexto": {
            "tela": "fluxo",
            "tela_nome": "Fluxo de Caixa e Bancos",
            "filtros": "filial=1&dt_de=2026-08-01",
            "url": "https://cortex.sulista.com.br/#fluxo",
            "versao": "CX-08/08/2026-v0.2.0",
            "navegador": "Mozilla/5.0 (Windows NT 10.0) Chrome/128",
            "tela_px": "1920x1080 @1x",
            "erros": [],
        },
        "anexos": [],
    }
    base.update(troca)
    return base


# ------------------------------------------------------------------ validação

def test_aceita_o_payload_minimo():
    assert srv.validar(_payload()) is None


def test_recusa_titulo_vazio():
    assert srv.validar(_payload(titulo="   ")) == "Escreva um título."


def test_recusa_titulo_acima_de_120_caracteres():
    assert srv.validar(_payload(titulo="a" * 121)) is not None


def test_recusa_descricao_vazia():
    assert srv.validar(_payload(descricao="")) == "Escreva a descrição."


def test_recusa_tipo_desconhecido():
    assert srv.validar(_payload(tipo="duvida")) is not None


def test_recusa_gravidade_desconhecida():
    assert srv.validar(_payload(gravidade="urgentissimo")) is not None


def test_recusa_mais_de_cinco_anexos():
    seis = [{"nome": f"a{i}.png", "b64": _b64(10)} for i in range(6)]
    assert srv.validar(_payload(anexos=seis)) is not None


def test_recusa_anexo_com_extensao_fora_da_allowlist():
    mau = [{"nome": "instalador.exe", "b64": _b64(10)}]
    assert "exe" in (srv.validar(_payload(anexos=mau)) or "")


def test_recusa_anexo_individual_acima_de_8mb():
    grande = [{"nome": "print.png", "b64": _b64(srv.ANEXO_MAX_BYTES + 1024)}]
    assert srv.validar(_payload(anexos=grande)) is not None


def test_recusa_anexos_somando_acima_de_15mb():
    # cada um cabe sozinho no limite individual; juntos estouram o total
    tres = [{"nome": f"p{i}.png", "b64": _b64(6 * 1024 * 1024)} for i in range(3)]
    assert srv.validar(_payload(anexos=tres)) is not None


# --------------------------------------------------------------- nome do anexo

def test_caminho_do_anexo_usa_a_data_e_o_slug_do_titulo():
    caminho = srv.caminho_anexo("Saldo não bate", 0, "print.png", QUANDO)
    assert caminho == "anexos/2026/08/20260810-143205-saldo-nao-bate-1.png"


def test_caminho_do_anexo_ignora_o_nome_vindo_do_cliente():
    # nome de arquivo do cliente é caminho em potencial; só a extensão é usada
    caminho = srv.caminho_anexo("Teste", 0, "../../../etc/passwd.png", QUANDO)
    assert ".." not in caminho
    assert caminho.startswith("anexos/2026/08/")
    assert caminho.endswith(".png")


def test_caminho_do_anexo_normaliza_a_extensao_para_minuscula():
    assert srv.caminho_anexo("Teste", 1, "FOTO.PNG", QUANDO).endswith("-2.png")


# ----------------------------------------------------------- corpo e rótulos

def test_titulo_da_issue_diz_o_tipo():
    assert srv.titulo_issue(_payload()) == (
        "[Bug] Saldo do Fluxo de Caixa não bate com o extrato")
    assert srv.titulo_issue(_payload(tipo="melhoria")).startswith("[Melhoria] ")


def test_titulo_da_issue_nao_carrega_quebra_de_linha():
    assert "\n" not in srv.titulo_issue(_payload(titulo="quebra\naqui"))


def test_rotulos_trazem_tipo_prioridade_tela_e_a_marca():
    assert srv.rotulos(_payload()) == [
        "bug", "prioridade:alta", "tela:fluxo", "cortex-report"]


def test_corpo_traz_descricao_tela_filtros_e_quem_reportou():
    corpo = srv.montar_corpo(_payload(), USUARIO, [], QUANDO)
    assert "o saldo veio R$ 2 mil menor" in corpo
    assert "Fluxo de Caixa e Bancos" in corpo
    assert "filial=1" in corpo
    assert "Cristian Cassoli" in corpo
    assert "cristian@sulista.com.br" in corpo
    assert "CX-08/08/2026-v0.2.0" in corpo


def test_corpo_lista_anexo_como_link_e_nunca_como_imagem_inline():
    # o proxy de imagem do GitHub não autentica em repo privado: `![](...)`
    # renderizaria quadrado quebrado, então o anexo entra como link clicável
    links = [("print-da-tela.png", "https://github.com/o/r/blob/main/a.png?raw=1")]
    corpo = srv.montar_corpo(_payload(), USUARIO, links, QUANDO)
    assert "[print-da-tela.png](https://github.com/o/r/blob/main/a.png?raw=1)" in corpo
    assert "![" not in corpo


def test_corpo_omite_a_secao_de_erros_quando_nao_houve_erro():
    assert "Erros de JavaScript" not in srv.montar_corpo(_payload(), USUARIO, [], QUANDO)


def test_corpo_traz_os_erros_de_javascript_quando_houve():
    ctx = dict(_payload()["contexto"], erros=["TypeError: x is not a function"])
    corpo = srv.montar_corpo(_payload(contexto=ctx), USUARIO, [], QUANDO)
    assert "Erros de JavaScript" in corpo
    assert "TypeError: x is not a function" in corpo


def test_corpo_termina_com_a_marca_que_identifica_o_report():
    assert srv.montar_corpo(_payload(), USUARIO, [], QUANDO).rstrip().endswith(
        "<!-- cortex-report v1 -->")


# ------------------------------------------------------------------ orquestra

class ClienteFalso:
    """Dublê do cliente GitHub — registra a ordem real das chamadas."""

    def __init__(self, falha_issue: bool = False):
        self.chamadas: list[str] = []
        self.anexos: list[tuple[str, str]] = []
        self.falha_issue = falha_issue

    def subir_anexo(self, caminho: str, b64: str) -> str:
        self.chamadas.append("anexo")
        self.anexos.append((caminho, b64))
        return f"https://github.com/o/r/blob/main/{caminho}?raw=1"

    def criar_issue(self, titulo: str, corpo: str, rotulos: list[str]) -> tuple[int, str]:
        self.chamadas.append("issue")
        if self.falha_issue:
            raise RuntimeError("GitHub fora do ar")
        self.corpo = corpo
        return 12, "https://github.com/o/r/issues/12"


def test_registrar_sobe_os_anexos_antes_de_criar_a_issue():
    # invertido, a issue nasceria sem link de anexo — o defeito que o usuário vê
    cli = ClienteFalso()
    srv.registrar(_payload(anexos=[{"nome": "print.png", "b64": _b64(10)}]),
                  USUARIO, cli, QUANDO)
    assert cli.chamadas == ["anexo", "issue"]


def test_registrar_devolve_o_numero_e_a_url_da_issue():
    assert srv.registrar(_payload(), USUARIO, ClienteFalso(), QUANDO) == {
        "numero": 12, "url": "https://github.com/o/r/issues/12"}


def test_registrar_poe_o_link_do_anexo_no_corpo_da_issue():
    cli = ClienteFalso()
    srv.registrar(_payload(anexos=[{"nome": "print.png", "b64": _b64(10)}]),
                  USUARIO, cli, QUANDO)
    assert "anexos/2026/08/" in cli.corpo


def test_registrar_recusa_payload_invalido_sem_chamar_o_github():
    cli = ClienteFalso()
    with pytest.raises(ValueError):
        srv.registrar(_payload(titulo=""), USUARIO, cli, QUANDO)
    assert cli.chamadas == []
