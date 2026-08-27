"""Parser das planilhas de antecipação dos portais dos clientes.

Os testes usam o arquivo REAL recebido (PORTAL MAXION 24.08.2026.xls) quando
ele está no repositório, e caem em skip quando não está — o arquivo carrega
CNPJ e valores de cliente e pode não acompanhar o checkout.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from api.antecipacoes import leitor, modelos, valores as vl
from api.antecipacoes import registro as reg

ARQUIVO = (Path(__file__).resolve().parent.parent.parent
           / "antecipacoes" / "PORTAL MAXION 24.08.2026.xls")


# --------------------------------------------------------------------------
# Conversão de célula — é aqui que a planilha engana
# --------------------------------------------------------------------------

def test_nota_fiscal_nao_vira_ponto_zero():
    """O Excel entrega a NF 100226 como float 100226.0; concatenada num
    identificador, '100226.0' nunca casaria com o número no ERP."""
    assert vl.texto(100226.0) == "100226"


@pytest.mark.parametrize("bruto,esperado", [
    (2060.23, 2060.23),
    ("2.060,23", 2060.23),          # pt-BR, como vem na coluna Saldo
    ("2,060.23", 2060.23),          # en-US
    ("1.234", 1234.0),              # ponto em grupo de 3 e MILHAR, nao decimal
    ("31.348,08", 31348.08),
    ("", None),
    ("n/d", None),
])
def test_numero_aceita_as_duas_convencoes(bruto, esperado):
    assert vl.numero(bruto) == esperado


def test_serial_do_excel_vira_data():
    """A coluna Vencimento vem como serial (46267), a Emissão como texto."""
    assert vl.data(46267) == date(2026, 9, 2)
    assert vl.data("05/06/2026") == date(2026, 6, 5)


def test_serial_implausivel_e_descartado():
    """Número que caiu na coluna errada não pode virar uma data de 1902 —
    devolver nada é melhor que devolver um vencimento inventado."""
    assert vl.data(3) is None
    assert vl.data(999999) is None


def test_booleano_ausente_nao_e_falso():
    """Célula vazia em 'Antecipável' não pode marcar o título como recusado."""
    assert vl.booleano("Sim") is True
    assert vl.booleano("Não") is False
    assert vl.booleano("") is None


def test_cnpj_perde_a_mascara():
    assert vl.cnpj("76.104.397/0020-96") == "76104397002096"


# --------------------------------------------------------------------------
# Detecção de modelo
# --------------------------------------------------------------------------

def test_detecta_pelo_cabecalho_e_nao_pelo_nome_do_arquivo():
    cab = ["Situação", "Nro. Título", "Nota Fiscal", "Emissão", "Vencimento",
           "Nominal", "Saldo", "Antecipável", "CPF/CNPJ Favorecido",
           "Nome Favorecido", "CPF/CNPJ Pagador", "Nome Pagador",
           "Chave Identificador", "Id Portal"]
    m, nota = modelos.escolher(cab)
    assert m is not None and m.nome == "maxion" and nota == 1.0


def test_cabecalho_com_grafia_diferente_ainda_casa():
    """'NRO TITULO' sem acento e sem ponto é o mesmo campo."""
    assert modelos.normalizar("Nro. Título") == modelos.normalizar("NRO TITULO")


def test_cabecalho_de_outra_coisa_nao_casa():
    m, nota = modelos.escolher(["Data", "Histórico", "Débito", "Crédito", "Saldo"])
    assert m is None and nota == 0.0


def test_todo_modelo_produz_os_campos_canonicos():
    """Modelo novo que esqueça um campo é pego aqui, e não em produção com o
    arquivo do cliente na mão."""
    for m in modelos.MODELOS:
        faltando = [c for c in modelos.CANONICOS if c not in m.colunas]
        assert not faltando, f"{m.nome} não mapeia {faltando}"


# --------------------------------------------------------------------------
# Formato do arquivo
# --------------------------------------------------------------------------

def test_html_disfarcado_de_xls_tem_mensagem_propria():
    """Portal que exporta HTML com extensão .xls é comum; a mensagem do xlrd
    nesse caso não ajuda ninguém."""
    html = b"<html><body><table><tr><td>x</td></tr></table></body></html>"
    with pytest.raises(leitor.ArquivoInvalido, match="p.gina HTML"):
        leitor.celulas("relatorio.xls", html)


def test_arquivo_vazio():
    with pytest.raises(leitor.ArquivoInvalido, match="vazio"):
        leitor.celulas("x.xls", b"")


def test_formato_desconhecido():
    with pytest.raises(leitor.ArquivoInvalido, match="Formato"):
        leitor.celulas("foto.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)


def test_csv_com_ponto_e_virgula():
    csv = ("Situação;Nro. Título;Nota Fiscal;Emissão;Vencimento;Nominal;Saldo;"
           "Antecipável;CPF/CNPJ Favorecido;Nome Favorecido;CPF/CNPJ Pagador;"
           "Nome Pagador;Chave Identificador;Id Portal\n"
           "Em Aberto;T1;100226;05/06/2026;02/09/2026;2060,23;2.060,23;Sim;"
           "76.104.397/0020-96;SULISTA;61.156.113/0001-75;MAXION;K1;1\n")
    d = leitor.ler("p.csv", csv.encode("utf-8"))
    assert d["portal"] == "maxion"
    t = d["titulos"][0]
    assert t["valor_nominal"] == 2060.23
    assert t["vencimento"] == date(2026, 9, 2)
    assert t["cnpj_sacado"] == "61156113000175"


def test_linha_de_total_no_rodape_nao_vira_titulo():
    """O arquivo da Maxion fecha com uma linha só com o total na coluna
    Nominal. Somada como título dobraria o valor."""
    csv = ("Situação;Nro. Título;Nota Fiscal;Emissão;Vencimento;Nominal;Saldo;"
           "Antecipável;CPF/CNPJ Favorecido;Nome Favorecido;CPF/CNPJ Pagador;"
           "Nome Pagador;Chave Identificador;Id Portal\n"
           "Em Aberto;T1;100;05/06/2026;02/09/2026;100,00;100,00;Sim;"
           "1;A;2;B;K1;1\n"
           "Em Aberto;T2;101;05/06/2026;02/09/2026;50,00;50,00;Sim;"
           "1;A;2;B;K2;2\n"
           ";;;;;150,00;;;;;;;;\n")
    d = leitor.ler("p.csv", csv.encode("utf-8"))
    assert len(d["titulos"]) == 2
    assert d["total_declarado"] == 150.0
    assert d["total_calculado"] == 150.0
    assert d["divergencia"] is None


def test_planilha_que_nao_fecha_acusa_divergencia():
    """Importar calado um arquivo que não bate é o jeito mais rápido de pôr
    número errado na tela."""
    csv = ("Situação;Nro. Título;Nota Fiscal;Emissão;Vencimento;Nominal;Saldo;"
           "Antecipável;CPF/CNPJ Favorecido;Nome Favorecido;CPF/CNPJ Pagador;"
           "Nome Pagador;Chave Identificador;Id Portal\n"
           "Em Aberto;T1;100;05/06/2026;02/09/2026;100,00;100,00;Sim;"
           "1;A;2;B;K1;1\n"
           ";;;;;180,00;;;;;;;;\n")
    d = leitor.ler("p.csv", csv.encode("utf-8"))
    assert d["divergencia"] == -80.0


def test_linha_ilegivel_nao_derruba_a_importacao():
    """Um título com data quebrada não pode impedir os outros — mas não pode
    sumir calado."""
    csv = ("Situação;Nro. Título;Nota Fiscal;Emissão;Vencimento;Nominal;Saldo;"
           "Antecipável;CPF/CNPJ Favorecido;Nome Favorecido;CPF/CNPJ Pagador;"
           "Nome Pagador;Chave Identificador;Id Portal\n"
           "Em Aberto;T1;100;05/06/2026;02/09/2026;100,00;100,00;Sim;"
           "1;A;2;B;K1;1\n"
           "Em Aberto;T2;101;05/06/2026;data ruim;50,00;50,00;Sim;"
           "1;A;2;B;K2;2\n")
    d = leitor.ler("p.csv", csv.encode("utf-8"))
    assert len(d["titulos"]) == 1
    assert len(d["rejeitadas"]) == 1
    assert d["rejeitadas"][0]["motivo"] == "vencimento ilegível"


def test_saldo_ausente_assume_titulo_integro():
    """O portal só preenche Saldo quando houve pagamento parcial; assumir zero
    zeraria a antecipação inteira."""
    csv = ("Nro. Título;Nota Fiscal;Vencimento;Nominal;Saldo;CPF/CNPJ Pagador\n"
           "T1;100;02/09/2026;100,00;;2\n")
    d = leitor.ler("p.csv", csv.encode("utf-8"))
    assert d["titulos"][0]["valor_saldo"] == 100.0


# --------------------------------------------------------------------------
# Arquivo real
# --------------------------------------------------------------------------

@pytest.mark.skipif(not ARQUIVO.exists(), reason="planilha real não disponível")
def test_arquivo_real_da_maxion_fecha_com_o_total_do_rodape():
    d = leitor.ler(ARQUIVO.name, ARQUIVO.read_bytes())
    assert d["portal"] == "maxion"
    assert d["confianca"] == 1.0
    assert d["rejeitadas"] == []
    assert d["divergencia"] is None, "a soma dos títulos tem de bater com o rodapé"
    assert len(d["titulos"]) == 226


@pytest.mark.skipif(not ARQUIVO.exists(), reason="planilha real não disponível")
def test_resumo_separa_as_filiais_cedentes():
    """O arquivo tem títulos de três CNPJs NOSSOS; somar tudo junto esconderia
    de qual filial é o recebível."""
    d = leitor.ler(ARQUIVO.name, ARQUIVO.read_bytes())
    r = leitor.resumir(d)
    assert len(r["cedentes"]) == 3
    assert r["prazo_medio_dias"] > 0
    assert r["valor_saldo"] == pytest.approx(929086.0, abs=0.01)


# --------------------------------------------------------------------------
# Elegibilidade
# --------------------------------------------------------------------------

@pytest.fixture
def _base(esquema_pg, monkeypatch):
    """Um SCHEMA exclusivo do teste, no lugar do arquivo em tmp_path — o
    registro migrou para o PostgreSQL em 27/08/2026."""
    monkeypatch.setattr(reg, "ESQUEMA", esquema_pg)
    return esquema_pg


def test_elegibilidade_e_por_raiz_do_cnpj(_base):
    """O portal manda o CNPJ da matriz (0001-75) e o ERP fatura por quatro
    filiais do mesmo grupo — casar os 14 dígitos deixaria três de fora."""
    reg.definir_sacado("61.156.113/0001-75", nome="Maxion", elegivel=True)
    assert reg.raizes_elegiveis() == {"61156113"}
    # as outras filiais da Maxion no ERP casam pela raiz
    for filial in ("61156113000507", "61156113000680", "61156113000760"):
        assert filial[:8] in reg.raizes_elegiveis()


def test_desligar_a_mao_sobrevive_a_nova_importacao(_base):
    """Convênio encerrado não pode voltar sozinho a cada arquivo novo."""
    lido = {"arquivo": "x.xls", "portal": "maxion", "portal_rotulo": "Maxion",
            "titulos": [], "total_declarado": None, "divergencia": None,
            "rejeitadas": []}
    resumo = {"titulos": 0, "valor_nominal": 0.0, "valor_saldo": 0.0,
              "sacados": [{"cnpj": "61156113000175", "nome": "Maxion"}]}
    reg.gravar_envio(lido, resumo)
    assert reg.cnpjs_elegiveis() == {"61156113000175"}

    reg.definir_sacado("61156113000175", elegivel=False)
    reg.gravar_envio(lido, resumo)
    assert reg.cnpjs_elegiveis() == set()


def test_sem_cnpj_nao_grava(_base):
    with pytest.raises(ValueError, match="CNPJ"):
        reg.definir_sacado("")


# --------------------------------------------------------------------------
# Rotas. O projeto não tem harness de TestClient com autenticação (ver
# tests/test_main_extrato.py), então aqui se garante o que mais quebra:
# a rota existir e cair na tela certa do RBAC. AuthMiddleware é fail-closed —
# rota fora de ROTA_TELAS devolve 403 para não-admin, e ninguém percebe.
# --------------------------------------------------------------------------

def test_rotas_registradas_e_com_rbac():
    from api import auth
    import api.main as main

    caminhos = {getattr(r, "path", "") for r in main.app.routes}
    for rota in ("/api/financeiro/antecipacoes",
                 "/api/financeiro/antecipacoes/importar",
                 "/api/financeiro/antecipacoes/sacado"):
        assert rota in caminhos, f"{rota} não registrada"
        telas = [t for p, t in auth.ROTA_TELAS if rota.startswith(p)]
        assert telas, f"{rota} fora de ROTA_TELAS (403 para não-admin)"
        assert "antport" in telas[0]


def test_tela_nova_existe_no_rbac():
    from api import auth
    assert "antport" in auth.TELAS


def test_rota_de_antecipacao_nao_foi_capturada_pela_de_antecipacoes():
    """'/api/financeiro/antecipacao' e '/api/financeiro/antecipacoes' são
    prefixos parecidos; casar errado tiraria a tela de Antecipação de quem só
    tem ela."""
    from api import auth
    telas = [t for p, t in auth.ROTA_TELAS
             if "/api/financeiro/antecipacao".startswith(p)]
    assert telas and telas[0] == frozenset({"antec"})


# --------------------------------------------------------------------------
# Duplicidade e convivência de portais. O usuário importou o mesmo arquivo
# duas vezes e perguntou se aquilo geraria número dobrado — não gerava (só o
# último envio era lido), mas a investigação achou o defeito real: com mais de
# um portal, só o último aparecia.
# --------------------------------------------------------------------------

def _envio(portal="maxion", arquivo="x.xls", titulos=2, valor=100.0):
    lido = {"arquivo": arquivo, "portal": portal, "portal_rotulo": portal.title(),
            "total_declarado": None, "divergencia": None, "rejeitadas": [],
            "titulos": [{"titulo": f"T{i}", "documento": str(i), "emissao": None,
                         "vencimento": date(2026, 9, 2), "valor_nominal": valor,
                         "valor_saldo": valor, "antecipavel": True,
                         "situacao": "Em Aberto", "cnpj_cedente": "1",
                         "nome_cedente": "SULISTA", "cnpj_sacado": "2",
                         "nome_sacado": portal, "chave": f"K{i}",
                         "id_portal": str(i)} for i in range(titulos)]}
    resumo = {"titulos": titulos, "valor_nominal": valor * titulos,
              "valor_saldo": valor * titulos,
              "sacados": [{"cnpj": "2", "nome": portal}]}
    return lido, resumo


def test_arquivo_identico_nao_cria_envio_novo(_base):
    lido, resumo = _envio()
    id1, novo = reg.gravar_envio(lido, resumo, dados=b"conteudo")
    id2, repetido = reg.gravar_envio(lido, resumo, dados=b"conteudo")
    assert novo is False and repetido is True
    assert id1 == id2
    assert len(reg.envios()) == 1
    assert len(reg.titulos_vigentes()) == 2, "não pode acumular cópias"


def test_arquivo_novo_do_mesmo_portal_substitui_o_anterior(_base):
    lido, resumo = _envio(arquivo="dia1.xls")
    reg.gravar_envio(lido, resumo, dados=b"dia1")
    lido2, resumo2 = _envio(arquivo="dia2.xls", titulos=3)
    reg.gravar_envio(lido2, resumo2, dados=b"dia2")

    vig = reg.posicao_atual()
    assert len(vig) == 1 and vig[0]["arquivo"] == "dia2.xls"
    assert len(reg.titulos_vigentes()) == 3, "os títulos do dia 1 saem de cena"
    # a trilha do envio antigo fica: é como se sabe de quando o dado é
    assert len(reg.envios()) == 2


def test_portais_diferentes_coexistem(_base):
    """Maxion, Tupy e Adient são três posições simultâneas. Antes, importar
    uma fazia as outras sumirem da tela."""
    for p, n in (("maxion", 2), ("tupy", 3), ("adient", 4)):
        lido, resumo = _envio(portal=p, arquivo=f"{p}.xls", titulos=n)
        reg.gravar_envio(lido, resumo, dados=p.encode())

    vig = reg.posicao_atual()
    assert {v["portal"] for v in vig} == {"maxion", "tupy", "adient"}
    assert len(reg.titulos_vigentes()) == 9


def test_reimportar_um_portal_nao_derruba_os_outros(_base):
    for p in ("maxion", "adient"):
        lido, resumo = _envio(portal=p, arquivo=f"{p}.xls")
        reg.gravar_envio(lido, resumo, dados=p.encode())
    lido, resumo = _envio(portal="maxion", arquivo="maxion-novo.xls", titulos=5)
    reg.gravar_envio(lido, resumo, dados=b"maxion-novo")

    vig = {v["portal"]: v for v in reg.posicao_atual()}
    assert len(vig) == 2
    assert vig["maxion"]["arquivo"] == "maxion-novo.xls"
    assert vig["adient"]["arquivo"] == "adient.xls", "o outro portal fica intacto"
    assert len(reg.titulos_vigentes()) == 7   # 5 da maxion + 2 do adient
