# -*- coding: utf-8 -*-
"""O escopo do portal do cliente — guards de SEGURANÇA, antes de produto.

A tela `cliop` é a primeira desta casa em que "quem pode abrir" e "o que
aparece" são perguntas DIFERENTES. O RBAC por tela responde a primeira; estes
testes cobram a segunda, que não tem rede embaixo: não há RLS no banco (o AVA é
réplica somente-leitura de um ERP de terceiro), então o único lugar onde o
escopo existe é `api/portal_cliente.escopo()`.

O QUE ESTES TESTES IMPEDEM:

- que uma sessão SEM vínculo veja qualquer coisa (o modo de falha caro é o
  filtro que não filtra: `strpos(..., '') = 1` casa com TODAS as linhas);
- que ADMIN vire curinga — ser admin responde "que telas", não "de quem é a
  operação", e um admin sem vínculo abrindo a carteira inteira seria a única
  sessão do sistema capaz de fazer isso;
- que o cliente vire PARÂMETRO da requisição em vez de vir da sessão;
- que o payload copie o registro do ERP (uma coluna nova do fornecedor viraria
  vazamento sozinha, sem ninguém rever nada);
- que o freetime ambíguo seja desempatado no escuro.
"""
from __future__ import annotations

import pytest

from api import portal_cliente as pc
from api import queries

RAIZ = "61156113"


@pytest.fixture(autouse=True)
def cache_limpo():
    """O `cached` da casa guarda por (módulo, função, args).

    Sem limpar, o segundo teste que chamasse a mesma função com os mesmos
    argumentos leria a resposta do PRIMEIRO — e passaria por acaso, medindo o
    cache em vez do código. Verde que nunca ficaria vermelho não confere nada.
    """
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


# --------------------------------------------------------------- o escopo

@pytest.mark.parametrize("sess", [
    None,
    {},
    {"cliente_cnpj_raiz": None},
    {"cliente_cnpj_raiz": ""},
    {"cliente_cnpj_raiz": "   "},
    {"cliente_cnpj_raiz": "611561"},          # curta demais
    {"cliente_cnpj_raiz": "61156113000175"},  # CNPJ inteiro não é raiz
    {"cliente_cnpj_raiz": "abcdefgh"},
    {"cliente_cnpj_raiz": "6115611a"},
])
def test_sem_vinculo_valido_o_escopo_RECUSA(sess):
    """Fail-closed: não existe caminho que devolva vazio e siga adiante."""
    with pytest.raises(pc.SemEscopo):
        pc.escopo(sess)


def test_ADMIN_sem_vinculo_tambem_recusa():
    """Admin não é curinga aqui.

    Se fosse, a única sessão do CÓRTEX capaz de ler a operação de todos os
    clientes de uma vez seria justamente a mais fácil de conseguir.
    """
    with pytest.raises(pc.SemEscopo):
        pc.escopo({"admin": True, "telas": ["cliop"], "email": "a@b.c"})


def test_com_vinculo_valido_devolve_a_raiz():
    assert pc.escopo({"cliente_cnpj_raiz": RAIZ}) == RAIZ
    assert pc.escopo({"cliente_cnpj_raiz": " " + RAIZ + " "}) == RAIZ


def test_o_escopo_LEVANTA_em_vez_de_devolver_vazio():
    """O tipo de retorno é a garantia.

    Uma função que devolve `None`/`""` para "sem vínculo" entrega a decisão a
    quem chamou, e basta um `if raiz:` esquecido para o filtro sumir. Levantar
    não tem essa borda — e este teste existe para que trocar por um retorno
    vazio seja uma mudança que ALGUÉM precisa justificar.
    """
    try:
        pc.escopo({})
    except pc.SemEscopo:
        return
    pytest.fail("escopo() devolveu em vez de levantar")


# --------------------------------------------------- o filtro do SQL

def test_o_filtro_cobre_os_TRES_papeis_do_cliente():
    """Tomador, pagador e destinatário.

    Medido em 12 meses da Maxion: 7.227 CT-es em que ela é tomadora/pagadora e
    58 em que é SÓ destinatária — outro paga o frete e ela recebe a carga.
    Esses 58 são carga dela tanto quanto os outros.
    """
    f = pc.FILTRO_CLIENTE
    assert "cnpjcpfcodigotomadorservico" in f
    assert "cnpjcpfcodigopagadorfrete" in f
    assert "c.destinatario" in f


def test_o_filtro_casa_no_INICIO_do_cnpj():
    """`strpos(...) = 1`: raiz é prefixo.

    Sem o `= 1`, a raiz casaria no MEIO de outro CNPJ e o portal de um cliente
    mostraria carga de outro — com o filtro parecendo estar lá.
    """
    assert pc.FILTRO_CLIENTE.count("= 1") == 3


def test_toda_consulta_do_modulo_exige_a_raiz():
    """Nenhuma SQL do módulo roda sem `%(raiz)s`."""
    for nome in ("AGORA_SQL", "PERM_SQL", "HIST_SQL", "FREETIME_SQL_TODAS"):
        assert "%(raiz)s" in getattr(pc, nome), nome


# --------------------------------------------------- estado vem do EVENTO

def _linha(**ev):
    base = {"t_cheg_carga": None, "t_saiu_carga": None, "t_viagem": None,
            "t_cheg_desc": None, "t_fim_desc": None, "t_finalizada": None}
    base.update(ev)
    return base


def test_o_marco_e_o_evento_mais_avancado_registrado():
    r = _linha(t_cheg_carga="2026-09-01 08:00", t_saiu_carga="2026-09-01 10:00",
               t_viagem="2026-09-01 11:00")
    cod, rotulo, quando = pc._marco(r)
    assert cod == 400 and rotulo == "Em viagem" and quando == "2026-09-01 11:00"


def test_carga_sem_evento_nenhum_nao_inventa_estado():
    cod, rotulo, _ = pc._marco(_linha())
    assert cod == 0 and rotulo == "Sem registro"


def test_o_TERMINAL_e_fim_de_descarga_e_NAO_viagem_finalizada():
    """O 401 quase não é apontado, e fechar por ele nunca fecharia nada.

    Medido em 05/09/2026: numa janela de 45 dias com 738 cargas da Maxion, 671
    tinham 397 (fim de descarga) e UMA tinha 401. Se o terminal fosse o 401, a
    carga descarregada continuaria "a caminho" no portal do cliente para
    sempre — o pior tipo de defeito, porque a tela segue funcionando.
    """
    assert pc.TERMINAL == 397
    descarregada = _linha(t_cheg_desc="2026-09-01 14:00", t_fim_desc="2026-09-01 16:00")
    assert not pc.em_curso(descarregada)
    a_caminho = _linha(t_saiu_carga="2026-09-01 10:00", t_viagem="2026-09-01 11:00")
    assert pc.em_curso(a_caminho)


def test_carga_sem_evento_nao_conta_como_em_curso():
    assert not pc.em_curso(_linha())


def test_os_rotulos_dos_marcos_vem_da_tabela_de_dominio():
    """Código sem tabela de domínio não vira rótulo inventado.

    Estes oito códigos existem em `public.ocorrencia` do ERP e os rótulos são
    os de lá. Se alguém acrescentar um código aqui, tem de tê-lo lido no banco.
    """
    assert set(pc.MARCOS) == {394, 395, 396, 397, 398, 399, 400, 401}
    assert set(pc.ORDEM) == set(pc.MARCOS)
    assert pc.ORDEM.index(394) < pc.ORDEM.index(395) < pc.ORDEM.index(400)
    assert pc.ORDEM.index(396) < pc.ORDEM.index(397) < pc.ORDEM.index(401)


# --------------------------------------------------- freetime: faixa, não chute

def test_freetime_ambiguo_vira_FAIXA_e_nao_um_numero(monkeypatch):
    """Quatro contratos, mesma vigência, freetimes diferentes por mercadoria.

    É o caso real da Maxion (05/09/2026): a linha genérica dá 3h de descarga e
    as de ESCADAS/RODAS/CONJUNTOS dão 6,5h, todas com `dtinicio` 01/08/2024.
    Um `DISTINCT ON ... ORDER BY dtinicio` desempata AO ACASO — a mesma tela
    diria 38,6% ou 70% de aderência sem nada mudar no código.
    """
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        {"ft_carga_h": 3.0, "ft_descarga_h": 3.0, "mercadoria": "(genérico)"},
        {"ft_carga_h": 3.0, "ft_descarga_h": 6.5, "mercadoria": "ESCADAS"},
        {"ft_carga_h": 3.0, "ft_descarga_h": 6.5, "mercadoria": "RODAS"},
        {"ft_carga_h": 3.0, "ft_descarga_h": 6.5, "mercadoria": "CONJUNTOS"},
    ])
    ft = pc._freetime(RAIZ)
    assert ft["contratos"] == 4
    assert ft["descarga_piso"] == 3.0 and ft["descarga_teto"] == 6.5
    assert ft["ambiguo"] is True


def test_freetime_unico_NAO_finge_faixa(monkeypatch):
    """Com um contrato só não há zona cinzenta — inventar dúvida também mente."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        {"ft_carga_h": 3.0, "ft_descarga_h": 3.0, "mercadoria": "(genérico)"}])
    ft = pc._freetime(RAIZ)
    assert ft["ambiguo"] is False
    assert ft["descarga_piso"] == ft["descarga_teto"] == 3.0


def test_sem_contrato_o_freetime_e_nd_e_NAO_zero(monkeypatch):
    """Freetime zero significaria que toda hora parada é excedente."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [])
    ft = pc._freetime(RAIZ)
    assert ft["contratos"] == 0
    assert ft["descarga_piso"] is None and ft["carga_piso"] is None


def test_sem_regua_a_tela_nao_classifica_nada():
    """Sem piso/teto não há faixa — e n/d, nunca 100% de aderência."""
    f = pc._faixas([1.0, 2.0, 9.0], None, None)
    assert f["dentro"] is None and f["fora"] is None and f["n"] == 3


def test_as_tres_faixas_somam_o_universo():
    f = pc._faixas([1.0, 2.9, 3.1, 5.0, 6.4, 7.0, 20.0], 3.0, 6.5)
    assert f["dentro"] + f["zona"] + f["fora"] == f["n"] == 7
    assert f["dentro"] == 2      # 1.0 e 2.9
    assert f["fora"] == 2        # 7.0 e 20.0
    assert f["zona"] == 3        # 3.1, 5.0, 6.4


def test_o_limite_e_inclusivo_no_piso_e_no_teto():
    """Exatamente 3h está DENTRO; exatamente 6,5h ainda não é excedente."""
    f = pc._faixas([3.0, 6.5], 3.0, 6.5)
    assert f["dentro"] == 1 and f["fora"] == 0 and f["zona"] == 1


# --------------------------------------------------- a régua física

def test_permanencia_acima_de_24h_vira_nd_CONTADO(monkeypatch):
    """Fora da régua não é zero e não é silêncio.

    Zero puxaria a mediana para baixo; descartar calado esconderia um problema
    de apontamento. Vira `fora_da_regua`, que a tela mostra em cinza.
    """
    linhas = [{"h_carga": 2.0, "h_descarga": 4.0},
              {"h_carga": 30.0, "h_descarga": 99.0},   # apontamento atravessando dias
              {"h_carga": None, "h_descarga": 5.0}]
    monkeypatch.setattr(pc.db, "query", lambda sql, *a, **k: linhas)
    monkeypatch.setattr(pc, "_freetime", lambda raiz: {
        "contratos": 1, "carga_piso": 3.0, "carga_teto": 3.0,
        "descarga_piso": 3.0, "descarga_teto": 6.5, "ambiguo": False})
    d = pc.get_permanencia(RAIZ, "2026-08-01", "2026-08-31")
    assert d["carga"]["fora_da_regua"] == 1
    assert d["descarga"]["fora_da_regua"] == 1
    assert d["carga"]["n"] == 1        # só a de 2.0
    assert d["descarga"]["n"] == 2     # 4.0 e 5.0
    assert pc.CAP_H == 24.0


# --------------------------------------------------- o payload

def test_o_payload_da_carga_e_lista_EXPLICITA(monkeypatch):
    """Nunca `dict(row)`.

    O padrão vem do rastreio público: cópia do registro do ERP faz de uma
    coluna nova do fornecedor um vazamento no dia em que alguém a criar.
    """
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [{
        "coleta": 20114, "emissao": "2026-09-04",
        "origem": "CRUZEIRO", "uf_origem": "SP",
        "destino": "RESENDE", "uf_destino": "RJ",
        "placa": "BCW8A71",
        "t_cheg_carga": "2026-09-04 08:00", "t_saiu_carga": "2026-09-04 10:00",
        "t_viagem": "2026-09-04 11:00", "t_cheg_desc": None,
        "t_fim_desc": None, "t_finalizada": None,
        # colunas que o ERP pode ganhar a qualquer momento:
        "valorfrete": 8123.45, "motorista": "FULANO DE TAL",
        "cnpjcpfcodigotomadorservico": "61156113000175",
    }])
    d = pc.get_agora(RAIZ, 45)
    assert d["em_curso"] == 1
    carga = d["cargas"][0]
    assert set(carga) == {"coleta", "emissao", "origem", "uf_origem", "destino",
                          "uf_destino", "placa", "marco", "marco_cod", "marco_em"}
    texto = repr(carga)
    assert "8123" not in texto and "FULANO" not in texto
    assert "61156113000175" not in texto


def test_a_serie_mensal_e_GERADA_e_nao_colhida(monkeypatch):
    """`GROUP BY` não devolve o mês sem carga — abril emendaria em agosto."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        {"mes": "2026-09", "origem": "CRUZEIRO", "uf_origem": "SP",
         "destino": "RESENDE", "uf_destino": "RJ", "cargas": 10}])
    d = pc.get_historico(RAIZ, 6)
    assert len(d["meses"]) == 6
    assert sum(1 for m in d["meses"] if m["cargas"] == 0) == 5
    assert d["meses"][-1]["parcial"] is True
    assert all(m["parcial"] is False for m in d["meses"][:-1])


def test_o_topN_de_rotas_leva_contador(monkeypatch):
    """Sem contador, a soma da tabela vira o total da operação."""
    linhas = [{"mes": "2026-09", "origem": "C%d" % i, "uf_origem": "SP",
               "destino": "D", "uf_destino": "RJ", "cargas": 100 - i}
              for i in range(15)]
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: linhas)
    d = pc.get_historico(RAIZ, 12)
    assert d["rotas_mostradas"] == 10 and d["rotas_total"] == 15
    assert d["cargas_nas_rotas_mostradas"] < d["cargas_total"]
