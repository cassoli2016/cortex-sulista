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

from datetime import datetime, timedelta

import pytest

from api import portal_cliente as pc
from api import queries

RAIZ = "11222333"


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
    {"cliente_cnpj_raiz": "11222333000199"},  # CNPJ inteiro não é raiz
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

def _agora_menos(horas: float) -> str:
    """Um horário RELATIVO ao relógio, no formato que a consulta devolve.

    Data fixa aqui acusa a pessoa errada: `em_curso()` compara a chegada com
    `datetime.now()` para saber se a folga de descarga já venceu, e um literal
    de setembro de 2026 vira "venceu há meses" no dia seguinte ao commit. A
    regra da casa — dublê com data acompanha o relógio que o código lê.
    """
    return (datetime.now() - timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M")


def _linha(**ev):
    """Uma linha CRUA do `AGORA_SQL`, com TODAS as colunas que ele devolve.

    A lista completa é de propósito. Dublê que traz só os campos de que o
    teste do momento precisa esconde a coluna nova: quando `destinatario_nome`
    e as duas janelas entraram na consulta, o código que as lê passou a
    estourar `KeyError` contra o dublê antigo — o que foi sorte. O modo de
    falha caro é o inverso: o dublê que traz um campo a mais, ou um valor que
    o ERP nunca produz, e aprova código que quebra em produção.

    É por isso que `mdfe_encerrado=1` vem com `mdfe_em` preenchido por padrão:
    medido em 09/09/2026, os 7.060 manifestos na situação 7 têm todos
    `dtencerramento`. Encerrado sem hora não existe no ERP, e um dublê que o
    fabrica testa um caminho que a realidade não percorre.
    """
    base = {"coleta": 1, "emissao": "2026-09-01",
            "origem": "C", "uf_origem": "SP", "destino": "D", "uf_destino": "RJ",
            "destinatario_nome": "DESTINO X", "placa": "AAA1A11",
            "janela_carga": None, "janela_entrega": None,
            "t_cheg_carga": None, "t_aguard_carga": None, "t_saiu_carga": None,
            "t_viagem": None, "t_cheg_desc": None, "t_aguard_desc": None,
            "t_fim_desc": None, "t_finalizada": None,
            "mdfe_encerrado": 0, "mdfe_autorizado": 0, "mdfe_em": None}
    base.update(ev)
    if base["mdfe_encerrado"] and base["mdfe_em"] is None:
        base["mdfe_em"] = _agora_menos(1)
    return base


def test_o_marco_e_o_evento_mais_avancado_registrado():
    r = _linha(t_cheg_carga="2026-09-01 08:00", t_saiu_carga="2026-09-01 10:00",
               t_viagem="2026-09-01 11:00")
    cod, rotulo, quando = pc._marco(r)
    assert cod == 400 and rotulo == "Em viagem" and quando == "2026-09-01 11:00"


def test_carga_sem_evento_nenhum_nao_inventa_estado():
    cod, rotulo, _ = pc._marco(_linha())
    # "Programada", e nao "sem registro" nem "sem apontamento": a COLETA existe,
    # tem janela de carregamento e destinatário, e está na tela dizendo isso.
    # O que falta é a operação ter apontado por onde ela passou — o que é
    # processo nosso, e não a ausência de um compromisso com quem espera.
    assert cod == pc.PROGRAMADA and rotulo == "Programada"


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


def test_carga_sem_apontamento_CONTA_como_em_curso():
    """A inversão de 05/09/2026, e a que mais muda o painel.

    Antes a carga sem evento nem aparecia: a consulta partia de
    `coleta_ocorrencia`. No dia da medição o cliente tinha 5 coletas e ZERO
    eventos SAC — uma delas com manifesto ABERTO, viajando naquele instante —
    e a operação do dia inteira estava invisível, sem nada acusar.

    A coleta existe e o manifesto não fechou: isso é carga no ar cujo trajeto
    ninguém apontou, não carga que não existe.
    """
    assert pc.em_curso(_linha())


def test_o_MANIFESTO_ENCERRADO_diz_que_CHEGOU_e_nao_que_ACABOU():
    """A correção de 09/09/2026, e a que mais muda o painel depois daquela.

    A regra anterior fechava a carga no encerramento do MDF-e, apoiada numa
    medição de COBERTURA que continua verdadeira: o encerramento é
    superconjunto do fim de descarga. O que faltou medir foi QUANDO — e o
    quando invertia a conclusão (45 dias, 724 cargas encerradas):

        encerramento − chegada apontada (396) ... mediana +0,04 h
        fim de descarga (397) − encerramento ... mediana +3,10 h, p90 +9,33 h

    O manifesto encerra quando o veículo CHEGA, não quando a carga é entregue.
    Fechar por ele apagava do painel as ~3 h de pátio — o veículo parado
    esperando doca, que é o assunto do cliente e o que a aba ao lado mede.

    Este teste sabota os dois lados: recém-chegada segue na tela; chegada há
    muito tempo sem apontamento de fim sai pelo relógio.
    """
    chegou_agora = _linha(t_viagem=_agora_menos(6), mdfe_encerrado=1,
                          mdfe_em=_agora_menos(1))
    assert pc.em_curso(chegou_agora), "carga no pátio do cliente sumiu do painel"
    _, rotulo, _, fonte = pc._estado(chegou_agora)
    assert rotulo == pc.MARCOS[396] and fonte == "manifesto"

    velha = _linha(t_viagem=_agora_menos(48), mdfe_encerrado=1,
                   mdfe_em=_agora_menos(pc.FOLGA_DESCARGA_H + 2))
    assert not pc.em_curso(velha), "carga sem fim de descarga ficaria eterna"


def test_o_FIM_DE_DESCARGA_fecha_na_hora_venha_manifesto_ou_nao():
    """O 397 é o terminal, e ele não espera relógio nenhum.

    A folga existe só para a carga que chegou e NUNCA recebe o apontamento de
    fim (11,5% das encerradas). Onde o apontamento veio, ele manda na hora —
    senão a carga entregue ficaria até 12 h a mais na tela do cliente, que é o
    defeito antigo com outro sinal.
    """
    assert pc.TERMINAL == 397
    for mdfe in (0, 1):
        r = _linha(t_cheg_desc=_agora_menos(3), t_fim_desc=_agora_menos(1),
                   mdfe_encerrado=mdfe)
        assert not pc.em_curso(r), mdfe


def test_sem_manifesto_a_CHEGADA_tambem_conta_a_folga():
    """A folga não é privilégio de quem tem manifesto.

    Sem MDF-e, o 396 é o único sinal de chegada — e o mesmo raciocínio vale:
    recém-chegada está no pátio; chegada há dois dias sem ninguém apontar o
    fim não está parada há dois dias, está sem apontamento.
    """
    assert pc.em_curso(_linha(t_cheg_desc=_agora_menos(2), mdfe_encerrado=0))
    assert not pc.em_curso(
        _linha(t_cheg_desc=_agora_menos(pc.FOLGA_DESCARGA_H + 1), mdfe_encerrado=0))


def test_o_MANIFESTO_AUTORIZADO_poe_na_estrada_a_carga_que_ninguem_apontou():
    """A outra ponta da mesma regra, e a que devolveu carga ao painel.

    Autorizar o MDF-e é ato fiscal OBRIGATÓRIO na saída; apontar o trajeto é
    rotina que ninguém multa. Uma carga com manifesto autorizado e nenhum
    apontamento está na estrada — foi o caso real de 09/09/2026, em que a
    planilha da torre dava a carga como em viagem e o portal não a tinha.

    SEM HORÁRIO, de propósito: o que a SEFAZ autoriza é a viagem, não o
    instante em que o veículo cruzou o portão.
    """
    r = _linha(mdfe_autorizado=1)
    cod, rotulo, quando, fonte = pc._estado(r)
    assert (cod, rotulo, fonte) == (400, pc.MARCOS[400], "manifesto")
    assert quando == "", "hora de autorização não é hora de saída"
    assert pc.em_curso(r)


def test_a_consulta_agrega_o_manifesto_ANTES_de_juntar():
    """Coleta pode estar em vários CT-es e o CT-e em vários MDF-es.

    Join cru multiplicaria a carga e o "em curso" viraria contagem inflada e
    plausível — o modo de falha que a casa já documentou. E o agregado tem de
    ser um CTE, não um LATERAL por linha: medido, o LATERAL levava 9,45 s numa
    janela de 45 dias, contra 0,98 s assim. Painel de parede recarrega a cada
    60 segundos.
    """
    assert "mdf AS (" in pc.AGORA_SQL
    assert "LEFT JOIN LATERAL" not in pc.AGORA_SQL
    assert "GROUP BY 1,2,3,4,5,6,7)" in pc.AGORA_SQL


def test_a_janela_do_manifesto_e_MAIOR_que_a_das_cargas():
    """O manifesto que fecha uma carga do começo da janela pode ter sido
    emitido antes dela. Cortar os dois no mesmo dia deixaria carga velha
    eternamente em curso na BORDA do período."""
    assert "%(dias)s + 30" in pc.AGORA_SQL


def test_a_espinha_e_a_COLETA_e_o_apontamento_e_detalhe():
    """`FROM coleta` com `LEFT JOIN ev`, nunca o contrário.

    Invertido, carga sem apontamento desaparece — e é justamente a de hoje,
    a que mais importa numa parede.
    """
    corpo = pc.AGORA_SQL
    assert "FROM coleta c" in corpo
    assert "LEFT JOIN ev ON" in corpo
    # a inversao literal: o `ev` nao pode voltar a ser a tabela de partida
    # a ordem no texto prova a inversao: a coleta vem antes, o evento depois
    assert corpo.index("FROM coleta c") < corpo.index("LEFT JOIN ev ON")


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
    """Vários contratos, mesma vigência, freetimes diferentes por mercadoria.

    É o caso real de um cliente com quatro linhas ativas e o MESMO `dtinicio`:
    uma genérica e outras com tolerância maior, por tipo de carga. Um
    `DISTINCT ON ... ORDER BY dtinicio` desempata AO ACASO — a mesma tela
    diria perto de 39% ou perto de 70% de aderência sem nada mudar no código.

    Os valores abaixo são de DUBLÊ, não os contratados: o que o teste afirma é
    a forma (várias linhas ativas empatadas) e o comportamento (vira faixa, não
    número), e nenhum dos dois depende do número real. Este repositório é
    público e cláusula de cliente não entra nele.
    """
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        {"ft_carga_h": 2.0, "ft_descarga_h": 2.0, "mercadoria": "(genérico)"},
        {"ft_carga_h": 2.0, "ft_descarga_h": 5.0, "mercadoria": "MERCADORIA A"},
        {"ft_carga_h": 2.0, "ft_descarga_h": 5.0, "mercadoria": "MERCADORIA B"},
        {"ft_carga_h": 2.0, "ft_descarga_h": 5.0, "mercadoria": "MERCADORIA C"},
    ])
    ft = pc._freetime(RAIZ)
    assert ft["contratos"] == 4
    assert ft["descarga_piso"] == 2.0 and ft["descarga_teto"] == 5.0
    assert ft["ambiguo"] is True


def test_freetime_unico_NAO_finge_faixa(monkeypatch):
    """Com um contrato só não há zona cinzenta — inventar dúvida também mente."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        {"ft_carga_h": 2.0, "ft_descarga_h": 2.0, "mercadoria": "(genérico)"}])
    ft = pc._freetime(RAIZ)
    assert ft["ambiguo"] is False
    assert ft["descarga_piso"] == ft["descarga_teto"] == 2.0


def test_sem_contrato_o_freetime_e_nd_e_NAO_zero(monkeypatch):
    """Freetime zero significaria que toda hora parada é excedente."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [])
    ft = pc._freetime(RAIZ)
    assert ft["contratos"] == 0
    assert ft["descarga_piso"] is None and ft["carga_piso"] is None


def _p(h, origem, ft):
    """Uma permanência já resolvida, como `get_permanencia` a monta."""
    return {"_h": h, "_origem": origem, "ft_descarga_h": ft}


def test_sem_regua_a_tela_nao_classifica_nada():
    """Sem contrato não há faixa — e n/d, nunca 100% de aderência.

    Um zero em "excedente" se lê como "ninguém passou do freetime", que é uma
    afirmação sobre um contrato que não existe.
    """
    linhas = [_p(1.0, pc._ft.SEM_CLAUSULA, None),
              _p(2.0, pc._ft.SEM_CLAUSULA, None),
              _p(9.0, pc._ft.SEM_CLAUSULA, None)]
    f = pc._faixas(linhas, "ft_descarga_h", None, None)
    assert f["dentro"] is None and f["fora"] is None and f["n"] == 3
    assert f["sem_regua"] == 3


def test_com_a_clausula_resolvida_a_resposta_e_BINARIA():
    """Esta é a mudança de 10/09/2026, e é o ponto da entrega.

    Sabendo qual cláusula vale para esta carga, a permanência está dentro do
    que o contrato dá ou não está. Não há terceira resposta — e a zona
    cinzenta que existia antes era consequência de não saber a mercadoria,
    não de uma dúvida do contrato.

    As duas linhas aqui têm freetimes DIFERENTES de propósito: é isso que uma
    régua única (piso/teto) não conseguia fazer. 4h é excedente sob 3h e é
    aderente sob 6,5h — e as duas coisas são verdade ao mesmo tempo, para
    cargas diferentes, no mesmo cliente.
    """
    linhas = [_p(4.0, pc._ft.GENERICO, 3.0),      # excedente sob a genérica
              _p(4.0, pc._ft.MERCADORIA, 6.5)]    # aderente sob RODAS
    f = pc._faixas(linhas, "ft_descarga_h", 3.0, 6.5)
    assert (f["dentro"], f["fora"], f["zona"]) == (1, 1, 0)
    assert f["origens"] == {"mercadoria": 1, "generico": 1, "sem_clausula": 0}


def test_a_zona_cinzenta_sobra_SO_para_quem_nao_tem_clausula():
    """A dúvida não some por decreto: ela encolhe até onde de fato está.

    Mercadoria sem cláusula própria e contrato sem genérica — é a LEAR, onde
    "DIVERSOS" (203 cargas em 90 dias) não casa com linha nenhuma. Aí a régua
    volta a ser a faixa do contrato inteiro, e o meio dela é dúvida legítima:
    a tela diz "depende da mercadoria" em vez de escolher um lado.
    """
    linhas = [_p(2.0, pc._ft.SEM_CLAUSULA, None),   # abaixo do piso
              _p(4.0, pc._ft.SEM_CLAUSULA, None),   # no meio: dúvida
              _p(9.0, pc._ft.SEM_CLAUSULA, None)]   # acima do teto
    f = pc._faixas(linhas, "ft_descarga_h", 3.0, 5.0)
    assert (f["dentro"], f["zona"], f["fora"]) == (1, 1, 1)


def test_as_faixas_SOMAM_o_universo_medido():
    """Quatro contagens, e elas fecham. `sem_regua` existe para isso.

    Sem a quarta, a linha que não pôde ser classificada sumiria da soma e os
    percentuais das outras três diriam respeito a um total que a tela não
    mostra — a forma mais silenciosa de um painel mentir.
    """
    linhas = [_p(1.0, pc._ft.MERCADORIA, 3.0), _p(9.0, pc._ft.GENERICO, 3.0),
              _p(4.0, pc._ft.SEM_CLAUSULA, None)]
    f = pc._faixas(linhas, "ft_descarga_h", 3.0, 5.0)
    assert f["dentro"] + f["zona"] + f["fora"] + f["sem_regua"] == f["n"] == 3


def test_o_limite_e_inclusivo_no_piso_e_no_teto():
    """O freetime está DENTRO: a hora contratada é hora dada, não excedida.

    Vale nos dois modos — contra a cláusula resolvida e contra a faixa. Valores
    de dublê: o que se afirma é a fronteira, não a hora contratada.
    """
    exato = pc._faixas([_p(3.0, pc._ft.MERCADORIA, 3.0)], "ft_descarga_h", 3.0, 5.0)
    assert exato["dentro"] == 1 and exato["fora"] == 0
    faixa = pc._faixas([_p(2.0, pc._ft.SEM_CLAUSULA, None),
                        _p(5.0, pc._ft.SEM_CLAUSULA, None)],
                       "ft_descarga_h", 2.0, 5.0)
    assert faixa["dentro"] == 1 and faixa["fora"] == 0 and faixa["zona"] == 1


# --------------------------------------------------- a régua física

def test_permanencia_acima_de_24h_vira_nd_CONTADO(monkeypatch):
    """Fora da régua não é zero e não é silêncio.

    Zero puxaria a mediana para baixo; descartar calado esconderia um problema
    de apontamento. Vira `fora_da_regua`, que a tela mostra em cinza.
    """
    linhas = [{"h_carga": 2.0, "h_descarga": 4.0, "mercadoria": "RODAS"},
              {"h_carga": 30.0, "h_descarga": 99.0,   # apontamento atravessando dias
               "mercadoria": "RODAS"},
              {"h_carga": None, "h_descarga": 5.0, "mercadoria": ""}]
    monkeypatch.setattr(pc.db, "query", lambda sql, *a, **k: linhas)
    monkeypatch.setattr(pc, "_freetime", lambda raiz: {
        "contratos": 1, "carga_piso": 2.0, "carga_teto": 2.0,
        "descarga_piso": 2.0, "descarga_teto": 5.0, "ambiguo": False,
        "linhas": [{"mercadoria": "", "ft_carga_h": 2.0, "ft_descarga_h": 5.0}]})
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
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [_linha(
        coleta=20114,
        t_cheg_carga=_agora_menos(6), t_saiu_carga=_agora_menos(4),
        t_viagem=_agora_menos(3),
        # colunas que o ERP pode ganhar a qualquer momento:
        valorfrete=8123.45, motorista="FULANO DE TAL",
        cnpjcpfcodigotomadorservico="11222333000199",
    )])
    d = pc.get_agora(RAIZ, 45)
    assert d["em_curso"] == 1
    carga = d["cargas"][0]
    # O conjunto é EXATO de propósito: acrescentar campo aqui tem de ser uma
    # decisão, não um efeito colateral de mexer na consulta. `pos` entrou em
    # 05/09/2026 com o mapa do painel de TV, e entrou montado campo a campo
    # como todo o resto.
    assert set(carga) == {"coleta", "emissao", "origem", "uf_origem", "destino",
                          "uf_destino", "destinatario", "placa",
                          "marco", "marco_cod", "marco_em", "marco_fonte",
                          "janela_carga", "janela_entrega",
                          "chegada", "chegada_fonte", "desvio_h",
                          "pos", "eta", "eta_amostras"}
    texto = repr(carga)
    assert "8123" not in texto and "FULANO" not in texto
    assert "11222333000199" not in texto


def test_a_posicao_diz_de_onde_veio_e_que_idade_tem(monkeypatch):
    """Regra de `api/posicoes`, que o mapa não pode perder no caminho.

    Mapa que mistura fontes sem dizer qual é qual transforma "a Gobrax está
    fora" em "a frota sumiu". E posição velha não some do mapa: aparece
    marcada, porque sumir com ela faz o veículo desaparecer, que é pior.
    """
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        _linha(placa="BCW8A71", t_viagem=_agora_menos(3))])
    from api import posicoes
    monkeypatch.setattr(posicoes, "atuais", lambda *a, **k: {"posicoes": {
        "BCW8A71": {"lat": -22.5, "lon": -44.9, "velocidade": 62,
                    "fonte": "erp", "idade_min": 4.3}}})
    d = pc.get_agora(RAIZ, 45)
    pos = d["cargas"][0]["pos"]
    assert set(pos) == {"lat", "lon", "velocidade", "fonte", "idade_min", "velha"}
    assert pos["fonte"] == "erp" and pos["idade_min"] == 4.3
    assert pos["velha"] is False
    assert d["posicao"]["com_posicao"] == 1 and d["posicao"]["veiculos"] == 1


def test_posicao_VELHA_nao_some_do_mapa(monkeypatch):
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        _linha(t_viagem=_agora_menos(3))])
    from api import posicoes
    monkeypatch.setattr(posicoes, "atuais", lambda *a, **k: {"posicoes": {
        "AAA1A11": {"lat": -22.5, "lon": -44.9, "velocidade": 0,
                    "fonte": "gobrax", "idade_min": 2127.8}}})
    d = pc.get_agora(RAIZ, 45)
    pos = d["cargas"][0]["pos"]
    assert pos is not None and pos["velha"] is True
    assert d["posicao"]["com_posicao"] == 1
    assert d["posicao"]["frescas"] == 0      # contada, e fora da conta de fresca


def test_falha_da_POSICAO_nao_derruba_as_cargas(monkeypatch):
    """O mapa é acréscimo; a carga é o dado."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        _linha(t_viagem=_agora_menos(3))])
    from api import posicoes

    def _explode(*a, **k):
        raise RuntimeError("rastreamento fora")
    monkeypatch.setattr(posicoes, "atuais", _explode)
    d = pc.get_agora(RAIZ, 45)
    assert d["em_curso"] == 1
    assert d["cargas"][0]["pos"] is None
    assert d["posicao"]["com_posicao"] == 0


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


# ============================================================ os dois leitores

def test_quem_tem_VINCULO_nao_escolhe_nem_pedindo():
    """A trava. É a propriedade que separa um portal de um buscador.

    Um usuário de cliente pode mandar o `raiz` que quiser — inclusive o de um
    concorrente que ele conheça — e continua no CNPJ dele. Se esta prova cair,
    a tela vira consulta livre da operação alheia com o RBAC achando tudo
    normal: a tela é a mesma e ele tem acesso a ela.
    """
    cli = {"cliente_cnpj_raiz": RAIZ}
    for pedida in (None, "", "44555666", "77888999", "abcdefgh", "   "):
        assert pc.alvo(cli, pedida) == (RAIZ, True), pedida


def test_gente_da_casa_escolhe_e_nao_nasce_travada():
    casa = {"admin": True, "telas": ["cliop"]}
    assert pc.alvo(casa, "44555666") == ("44555666", False)


def test_gente_da_casa_sem_escolha_PEDE_escolha_em_vez_de_recusar():
    """Não é 403: quem abriu a tela tem direito a ela, só não disse de quem."""
    with pytest.raises(pc.PrecisaEscolher):
        pc.alvo({"admin": True}, None)
    with pytest.raises(pc.PrecisaEscolher):
        pc.alvo({}, "nao-e-raiz")


def test_o_vinculo_e_consultado_ANTES_do_parametro():
    """A ordem É a segurança, e por isso ela é cobrada aqui.

    Escrita ao contrário — usar `pedida` e cair no vínculo quando ela falta —
    a mesma função deixaria um usuário de cliente ler outro cliente. O teste
    acima já pega o comportamento; este pega a INTENÇÃO no texto, para que
    inverter a ordem exija apagar uma prova que diz por que ela existe.
    """
    import inspect
    corpo = inspect.getsource(pc.alvo)
    assert corpo.index("escopo(sess)") < corpo.index("pedida or")


def test_a_lista_de_clientes_NAO_recebe_raiz():
    """A única função não escopada do módulo, e ela não aceita raiz nenhuma.

    É o que impede alguém de, mais adiante, "reusar" a lista dentro de um
    caminho de cliente sem perceber que acabou de tirar o escopo.
    """
    import inspect
    assert "raiz" not in inspect.signature(pc.get_clientes).parameters


def test_a_lista_agrega_por_RAIZ_e_rotula_pela_razao_social(monkeypatch):
    """Quatro filiais viram UMA linha, com o nome da EMPRESA.

    O fantasia do ERP traz a filial no nome ("CLIENTE DUBLÊ - FILIAL"):
    agregado por raiz, rotular por ele faria quem escolhe ler "Resende" e
    achar que Cruzeiro ficou de fora.
    """
    assert "GROUP BY 1" in pc.CLIENTES_SQL
    assert "substr(cast(c.cnpjcpfcodigopagadorfrete AS text), 1, 8)" in pc.CLIENTES_SQL
    i_razao = pc.CLIENTES_SQL.index("razaosocial")
    i_fantasia = pc.CLIENTES_SQL.index("nomefantasia")
    assert i_razao < i_fantasia, "razão social tem de vir antes do fantasia"

    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [
        {"raiz": "11222333", "nome": "CLIENTE DUBLÊ S.A.", "cargas": 6826}])
    d = pc.get_clientes(365)
    assert d["clientes"][0]["raiz"] == "11222333"


def test_o_nome_do_cliente_e_ROTULO_e_nunca_derruba_a_tela(monkeypatch):
    """Nome é enfeite; número é o dado. Falha no nome não pode levar o painel."""
    def _explode(*a, **k):
        raise RuntimeError("ERP fora")
    monkeypatch.setattr(pc.db, "query", _explode)
    assert pc.nome_do_cliente(RAIZ) == ""



# ================================================ previsão de chegada (ETA)

def _rotas_dubles():
    return {"CRUZEIRO/SP|RESENDE/RJ": (1.75, 1609),
            "CRUZEIRO/SP|SETE LAGOAS/MG": (14.75, 245)}


def _r(**kw):
    base = {"origem": "CRUZEIRO", "uf_origem": "SP", "destino": "RESENDE",
            "uf_destino": "RJ", "t_saiu_carga": "2026-09-06 08:00",
            "t_viagem": "2026-09-06 08:30"}
    base.update(kw)
    return base


def test_a_previsao_conta_da_SAIDA_e_nao_do_em_viagem():
    """O histórico mede de `dtsaida` a `dtchegada`.

    Contar do "em viagem" daria previsão mais curta para a mesma estrada, e
    duas cargas lado a lado chegariam em horas diferentes conforme qual evento
    a operação apontou primeiro.
    """
    d = pc._eta(_r(), 400, _rotas_dubles())
    assert d["eta"] == "2026-09-06 09:45"        # 08:00 + 1,75 h
    # sem a saída, cai no "em viagem" — melhor uma previsão do que nenhuma
    d2 = pc._eta(_r(t_saiu_carga=None), 400, _rotas_dubles())
    assert d2["eta"] == "2026-09-06 10:15"       # 08:30 + 1,75 h


def test_so_tem_previsao_quem_JA_SAIU():
    """Antes de sair não há de onde contar."""
    rotas = _rotas_dubles()
    for cod in (394, 398, 396, 399, 397, 401, 0):
        assert pc._eta(_r(), cod, rotas)["eta"] is None, cod
    for cod in (395, 400):
        assert pc._eta(_r(), cod, rotas)["eta"] is not None, cod


def test_rota_sem_amostra_NAO_ganha_previsao():
    """A régua é a do próprio módulo de ciclos (`N_MIN`), e não uma segunda
    inventada aqui: duas réguas para a mesma pergunta discordam um dia."""
    d = pc._eta(_r(destino="CIDADE QUE NAO RODA"), 400, _rotas_dubles())
    assert d == {"eta": None, "eta_amostras": None}


def test_a_previsao_diz_de_quantas_viagens_ela_saiu():
    """Número sem lastro numa parede vira promessa."""
    d = pc._eta(_r(), 400, _rotas_dubles())
    assert d["eta_amostras"] == 1609


def test_a_previsao_e_ACRESCIMO_e_nao_derruba_o_painel(monkeypatch):
    """Sem ciclos, a carga continua na tela dizendo onde está."""
    from api import programacao_ciclos

    def _explode():
        raise RuntimeError("ciclos fora")
    monkeypatch.setattr(programacao_ciclos, "get_ciclos", _explode)
    assert pc._eta_por_rota() == {}


def test_a_fonte_NAO_nomeia_fornecedor(monkeypatch):
    """O payload chega ao navegador do cliente: fornecedor é assunto nosso."""
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(pc, "_eta_por_rota", lambda: {})
    for fn, args in ((pc.get_agora, (RAIZ, 45)),
                     (pc.get_historico, (RAIZ, 12))):
        queries._RESP_CACHE.clear()
        fonte = fn(*args)["fonte"].lower()
        for nome in ("gobrax", "erp", "ava", "smartec", "tomtom"):
            assert nome not in fonte, (fn.__name__, nome, fonte)


def test_a_carga_PROGRAMADA_aparece_com_a_janela_e_segue_contada(monkeypatch):
    """A decisão de 06/09/2026, revertida em 09/09/2026 — e por quê.

    A carga sem apontamento saiu da tela porque o portal só sabia dizer "não
    sabemos por onde anda", que é processo nosso e não informação do cliente.
    Ela volta porque a linha passou a dizer outra coisa: a janela de
    carregamento e o destinatário, que são compromisso assumido com quem
    espera a carga. O que mudou não foi a opinião sobre esconder — foi o que
    a tela tem a mostrar.

    O contador segue saindo à parte, e com o MESMO nome de campo, porque a
    tela e a parede já o leem: `sem_apontamento` continua medindo o buraco de
    apontamento por dentro.
    """
    linhas = [
        _linha(coleta=1, placa="", janela_carga="2026-09-06 18:00"),
        _linha(coleta=2, t_viagem=_agora_menos(3)),
    ]
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: linhas)
    monkeypatch.setattr(pc, "_eta_por_rota", lambda: {})
    from api import posicoes
    monkeypatch.setattr(posicoes, "atuais", lambda *a, **k: {"posicoes": {}})
    d = pc.get_agora(RAIZ, 45)
    assert d["em_curso"] == 2, "a carga programada voltou à tela"
    assert d["sem_apontamento"] == 1, "e continua contada à parte"
    assert [c["coleta"] for c in d["cargas"]] == [1, 2]
    prog = d["cargas"][0]
    assert prog["marco"] == "Programada"
    assert prog["marco_fonte"] == "programação"
    assert prog["janela_carga"] == "2026-09-06 18:00"


# ======================================== as tres listas de marcos, e o SQL
#
# O DEFEITO QUE ESTA SECAO EXISTE PARA NAO TER MAIS. Ate 09/09/2026 o 398
# (aguardando carregamento) e o 399 (aguardando descarga) estavam em `MARCOS`
# e em `ORDEM`, o `AGORA_SQL` lia `IN (394,395,396,397,400,401)` e `_marco()`
# nao tinha coluna para eles. Dois estados declarados em dois lugares e
# inalcancaveis em dois outros -- e um deles era "aguardando descarga", que e
# exatamente o estado que doi num cliente industrial.
#
# Nao havia sintoma: a tela funcionava, os outros seis estados apareciam, e o
# unico jeito de notar era ler as quatro listas lado a lado. E o tipo de
# defeito que so a ausencia denuncia, entao ele ganha guard proprio.


def test_as_tres_listas_de_marcos_concordam():
    """`MARCOS`, `ORDEM` e `COLUNA` descrevem o MESMO conjunto.

    Cada uma responde uma pergunta (como se chama, em que ordem vem, de que
    coluna sai) e as tres precisam falar dos mesmos codigos. Divergirem nao da
    erro: da estado que nunca aparece.
    """
    assert set(pc.MARCOS) == set(pc.ORDEM) == set(pc.COLUNA), (
        "MARCOS-ORDEM: %s | ORDEM-MARCOS: %s | COLUNA-MARCOS: %s" % (
            set(pc.MARCOS) - set(pc.ORDEM),
            set(pc.ORDEM) - set(pc.MARCOS),
            set(pc.COLUNA) - set(pc.MARCOS)))
    assert len(pc.ORDEM) == len(set(pc.ORDEM)), "codigo repetido em ORDEM"
    assert len(set(pc.COLUNA.values())) == len(pc.COLUNA), "duas colunas iguais"


def test_a_consulta_LE_todos_os_marcos_declarados():
    """A causa raiz do 398/399 mudos, e ela mora no SQL.

    Declarar o marco em Python nao o traz do banco. Este guard le o `IN (...)`
    da propria consulta e cobra codigo por codigo -- e um marco novo que entre
    em `MARCOS` sem entrar no filtro reprova aqui, com o numero no erro.
    """
    import re
    m = re.search(r"WHERE ocorrencia IN \(([0-9,\s]+)\)", pc.AGORA_SQL)
    assert m, "nao achei o filtro de ocorrencias no AGORA_SQL"
    lidos = {int(x) for x in m.group(1).split(",")}
    assert lidos == set(pc.MARCOS), (
        "declarados e nao lidos: %s" % (set(pc.MARCOS) - lidos))


def test_cada_marco_declarado_tem_a_COLUNA_na_consulta():
    """A outra ponta: o SQL le o evento e nao publica a coluna.

    Ler `399` no `IN` e esquecer o `AS t_aguard_desc` no SELECT devolveria o
    mesmo estado mudo por outro caminho.
    """
    faltam = [c for c in pc.COLUNA.values() if ("AS " + c) not in pc.AGORA_SQL]
    assert not faltam, "colunas declaradas e ausentes do SELECT: %s" % faltam


def test_todo_marco_declarado_e_ALCANCAVEL():
    """Cada marco tem de ser alcancavel a partir da linha crua.

    Guard parametrizado sobre a lista INTEIRA, e nao sobre um caso escolhido:
    e assim que o 398 e o 399 voltariam a sumir sem ninguem ver. Cada codigo
    aqui e um guard, e sabotar um so provaria o mecanismo, nao os outros.
    """
    for cod in pc.ORDEM:
        r = _linha(**{pc.COLUNA[cod]: "2026-09-01 08:00"})
        obtido, rotulo, quando = pc._marco(r)
        assert obtido == cod, (cod, obtido)
        assert rotulo == pc.MARCOS[cod]
        assert quando == "2026-09-01 08:00"


# ================================================ a janela e a chegada real


def test_a_consulta_usa_a_JANELA_e_nao_a_previsao_de_entrega():
    """A coluna certa, e o guard que impede a volta da errada.

    `dtprevisaoentrega` esta NULL em todas as cargas desta operacao -- foi ela
    que fez a regua de pontualidade medir 8,7% de cobertura em 05/09/2026 e a
    conclusao "nao da para publicar". A janela de verdade e
    `dtprevisaochegadaviagem`. Trocar de volta nao daria erro nenhum: daria
    uma coluna vazia, que e o defeito mais caro desta tela.
    """
    assert pc.JANELA_DE_ENTREGA == "dtprevisaochegadaviagem"
    assert ("c." + pc.JANELA_DE_ENTREGA) in pc.AGORA_SQL
    # a forma QUALIFICADA, que e a que le a coluna: o nome cru aparece no
    # comentario que explica por que ela nao serve, e proibir a mencao
    # obrigaria a apagar justamente a explicacao.
    assert "c.dtprevisaoentrega" not in pc.AGORA_SQL
    assert "AS janela_entrega" in pc.AGORA_SQL and "AS janela_carga" in pc.AGORA_SQL


def test_a_consulta_ordena_pela_LINHA_DO_TEMPO_da_operacao():
    """A ordem do dia, nao a do ultimo apontamento.

    Ordenar pelo evento mais recente poe no topo quem acabou de ser apontado
    -- ordem sem significado para quem espera a carga, e que embaralha a lista
    a cada recarga da parede.
    """
    assert "ORDER BY coalesce(c.dtprevisaochegadaviagem, c.dtcoletar" in pc.AGORA_SQL


def test_a_chegada_sai_do_apontamento_e_o_manifesto_e_reserva():
    """Duas fontes para a mesma hora, e a tela diz qual foi.

    Um horario de manifesto e da portaria fiscal, nao da doca -- medido, os
    dois ficam a 2,4 min um do outro, mas quem le tem direito de saber.
    """
    r = _linha(t_cheg_desc="2026-09-09 06:16", janela_entrega="2026-09-09 07:00",
               mdfe_encerrado=1, mdfe_em="2026-09-09 06:18")
    d = pc._chegada(r)
    assert d["chegada"] == "2026-09-09 06:16" and d["chegada_fonte"] == "apontamento"

    so_manifesto = _linha(janela_entrega="2026-09-09 07:00",
                          mdfe_encerrado=1, mdfe_em="2026-09-09 06:18")
    d2 = pc._chegada(so_manifesto)
    assert d2["chegada"] == "2026-09-09 06:18" and d2["chegada_fonte"] == "manifesto"

    assert pc._chegada(_linha())["chegada"] is None


def test_o_desvio_e_a_CONTA_e_nunca_um_veredito():
    """Sai o numero de horas, com sinal. Nao sai "no prazo" nem percentual.

    A decisao e de quem opera (09/09/2026) e foi tomada com a regua na mesa:
    ela cobre 89,6% das cargas e discrimina de verdade. O que a segura nao e a
    cobertura, e a PROCEDENCIA -- a janela e digitada pelo nosso proprio
    programador, e publicar um percentual num painel que o cliente le
    transforma a nossa previsao em compromisso contratual, que ele passa a
    cobrar.
    """
    adiantada = pc._chegada(_linha(t_cheg_desc="2026-09-09 06:16",
                                   janela_entrega="2026-09-09 07:00"))
    assert adiantada["desvio_h"] == -0.73

    atrasada = pc._chegada(_linha(t_cheg_desc="2026-09-09 08:55",
                                  janela_entrega="2026-09-09 07:00"))
    assert atrasada["desvio_h"] == 1.92

    # sem janela nao ha desvio: n/d, nunca zero, que se leria como "no ponto"
    assert pc._chegada(_linha(t_cheg_desc="2026-09-09 08:55"))["desvio_h"] is None

    # e o payload NAO carrega veredito nenhum
    assert set(adiantada) == {"chegada", "chegada_fonte", "desvio_h"}


def test_o_modulo_nao_publica_percentual_de_pontualidade():
    """Guard da decisao. Para publicar o KPI e preciso apagar esta prova --
    que e justamente o momento de reler por que ela existe."""
    import inspect
    fonte = inspect.getsource(pc._chegada)
    assert "no_prazo" not in fonte and "pontualidade" not in fonte


# ==================================================== agrupado por destino


def test_as_cargas_se_agrupam_por_QUEM_RECEBE():
    """Rota nao distingue duas docas na mesma cidade; destinatario sim.

    Uma rota "ORIGEM -> CIDADE" reune numa barra so a montadora e a planta do
    proprio cliente na mesma cidade, que tem docas e janelas diferentes.
    """
    cargas = [
        {"destinatario": "DESTINO A", "marco_cod": 400},
        {"destinatario": "DESTINO A", "marco_cod": 396},
        {"destinatario": "DESTINO A", "marco_cod": pc.PROGRAMADA},
        {"destinatario": "DESTINO B", "marco_cod": 395},
    ]
    d = pc._por_destinatario(cargas)
    assert [x["destinatario"] for x in d] == ["DESTINO A", "DESTINO B"]
    a = d[0]
    assert (a["cargas"], a["em_viagem"], a["no_destino"], a["programadas"]) == (3, 1, 1, 1)
    assert d[1]["na_origem"] == 1


def test_destinatario_sem_cadastro_nao_faz_a_carga_sumir():
    """`LEFT JOIN cadastro`, e o rotulo vazio vira uma linha propria.

    `JOIN` cru tiraria da operacao a carga cujo destinatario nao esta no
    cadastro -- some sem erro, que e o modo de falha caro desta tela.
    """
    assert "LEFT JOIN cadastro cdd" in pc.AGORA_SQL
    d = pc._por_destinatario([{"destinatario": None, "marco_cod": 400}])
    assert d[0]["cargas"] == 1 and d[0]["destinatario"]
