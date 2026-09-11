"""O filtro de tipo de mercadoria vale para a TELA INTEIRA.

Pedido de quem opera em 10/09/2026, junto com a validação do freetime, e as
duas coisas são a mesma pergunta: o contrato dá freetime diferente por tipo de
carga, então "quanto tempo minha carga fica parada" tem respostas muito
diferentes por tipo de carga. Medido na IOCHPE MAXION, 90 dias:

    toda a operação      50,4% das descargas dentro do freetime
    só CHASSI            83,5%

A média das duas não descreve nenhuma. Sem o filtro, a tela respondia 50,4% e
ninguém tinha como perguntar de qual carga estava falando.

O QUE ESTES GUARDS PROTEGEM não é a existência do campo — é a regra da casa de
que **todo KPI obedece a TODOS os filtros**. Filtro que a consulta ignora é
pior que filtro nenhum: a tela mostra "ESPUMA" no seletor, devolve a operação
inteira, e quem filtrou acredita no resultado. Essa classe de defeito não tem
sintoma — só um número plausível e errado.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from api import portal_cliente as pc
from api import freetime as ft
from api import queries


@pytest.fixture(autouse=True)
def cache_limpo():
    """O `cached` guarda por (módulo, função, args): sem limpar, um teste leria
    a resposta do anterior e passaria medindo o cache em vez do código."""
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


AS_TRES = [("AGORA_SQL", pc.AGORA_SQL), ("PERM_SQL", pc.PERM_SQL),
           ("HIST_SQL", pc.HIST_SQL)]


# ────────────────────────────────────────── o filtro alcança as três consultas

def test_TODA_consulta_da_tela_tem_lugar_para_o_filtro():
    """As três, não a que motivou o pedido.

    A Permanência foi o pedido; Agora e Histórico são a mesma tela, e a régua
    da casa é que o filtro escolhido governa tudo o que está na frente de quem
    escolheu. Deixar uma de fora faria a tela mostrar "ESPUMA" no alto e o
    histórico da operação inteira embaixo.
    """
    for nome, sql in AS_TRES:
        assert pc.MARCA_MERC in sql, (
            "%s não tem lugar para o filtro de mercadoria" % nome)


def test_a_varredura_ACHA_as_consultas_no_disco():
    """A lista acima é escrita à mão, e lista escrita à mão erra em silêncio.

    Uma consulta NOVA da tela nasceria sem a marca e sem ninguém notar — o
    guard acima só confere o que alguém lembrou de listar. Esta varredura sai
    do DISCO: toda constante de módulo que é SQL contra `coleta` tem de ter o
    lugar do filtro. E ela reprova o resultado VAZIO, porque varredura que não
    acha nada passa por vacuidade.
    """
    fonte = pathlib.Path(pc.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    consultas = {}
    for no in arvore.body:
        if not isinstance(no, ast.Assign) or not isinstance(no.value, (ast.Constant, ast.BinOp)):
            continue
        alvo = no.targets[0]
        if not isinstance(alvo, ast.Name) or not alvo.id.isupper():
            continue
        try:
            texto = ast.unparse(no.value)
        except Exception:  # noqa: BLE001
            continue
        # As consultas da tela leem a operação do cliente e por isso todas
        # passam pelo FILTRO_CLIENTE — é essa a marca de "consulta da tela",
        # e não o nome da constante.
        if "FILTRO_CLIENTE" in texto and "FROM coleta" in texto:
            consultas[alvo.id] = texto

    assert len(consultas) >= 3, (
        "a varredura achou %d consultas da tela — ela parou de enxergar o "
        "arquivo, e um guard que não acha nada aprova tudo" % len(consultas))
    sem = [n for n, t in consultas.items() if "FILTRO_MERC" not in t]
    # MERC_SQL é a consulta que MONTA a lista do filtro: ela olha a operação
    # inteira de propósito, senão o seletor só ofereceria o que já está
    # selecionado. É a única exceção, e ela é nomeada.
    sem = [n for n in sem if n != "MERC_SQL"]
    assert not sem, "consulta da tela sem lugar para o filtro: %s" % sem


def test_a_consulta_RECUSA_nascer_sem_lugar_para_o_filtro():
    """O `assert` de `_sql`, e por que ele é um `assert` e não um `if`.

    A marca é um COMENTÁRIO SQL: perdê-la não quebra a consulta por conta
    própria — ela rodaria, responderia e ignoraria o filtro. Falhar aqui, alto,
    é a única forma de o defeito ter sintoma.
    """
    with pytest.raises(AssertionError):
        pc._sql("SELECT 1 FROM coleta", "ESPUMA")
    # e sem filtro escolhido a recusa é a MESMA: não é o valor que decide, é a
    # consulta estar apta a recebê-lo
    with pytest.raises(AssertionError):
        pc._sql("SELECT 1 FROM coleta", None)


def test_escolhida_a_mercadoria_a_clausula_ENTRA_no_SQL():
    for nome, sql in AS_TRES:
        com = pc._sql(sql, "ESPUMA PARA BANCOS")
        assert "%(merc)s" in com, "%s não recebeu o filtro" % nome
        assert ft.sql_normalizar("c.mercadorias") in com, (
            "%s filtra pelo texto cru — 'PEÇAS' e 'PECAS' viram cargas "
            "diferentes" % nome)


def test_sem_escolha_a_clausula_NAO_entra():
    """"Todas" é ausência de cláusula, não `= ''`.

    Com `= ''` a tela responderia as coletas sem mercadoria preenchida, que é
    o oposto de "todas" — e um oposto plausível, porque devolveria linhas.
    """
    for nome, sql in AS_TRES:
        sem = pc._sql(sql, None)
        assert "%(merc)s" not in sem, "%s filtra sem ninguém ter filtrado" % nome
        assert pc.MARCA_MERC not in sem, "%s ficou com a marca crua" % nome


# ────────────────────────────────────────── o filtro atravessa a rota

def test_a_rota_leva_o_filtro_para_AS_TRES_abas(monkeypatch):
    """Rota que aceita o parâmetro e não o repassa é o mesmo defeito, uma
    camada acima — e mais difícil de ver, porque o SQL está certo."""
    from api import main

    vistos = {}

    def _reg(nome):
        def _f(raiz, *a, **k):
            vistos[nome] = (a[-1] if a else k.get("merc"))
            return {"fonte": "dublê"}
        return _f

    monkeypatch.setattr(pc, "get_agora", _reg("agora"))
    monkeypatch.setattr(pc, "get_permanencia", _reg("permanencia"))
    monkeypatch.setattr(pc, "get_historico", _reg("historico"))
    monkeypatch.setattr(pc, "nome_do_cliente", lambda r: "DUBLÊ")
    monkeypatch.setattr(pc, "alvo", lambda sessao, raiz: ("11222333", True))

    class _Req:
        class state:  # noqa: N801
            sessao = {"id": 1}

    for aba in ("agora", "permanencia", "historico"):
        main.portal_cliente_dados(_Req(), aba=aba, merc="ESPUMA PARA BANCOS")
    assert vistos == {a: "ESPUMA PARA BANCOS"
                      for a in ("agora", "permanencia", "historico")}, vistos


def test_a_ROTA_declara_o_parametro_para_o_FastAPI():
    """O teste acima chama a função; o navegador fala com a ROTA.

    O FastAPI DESCARTA query param que a assinatura não declara — sem erro,
    sem log, sem nada. A tela mandaria `?merc=ESPUMA`, o servidor responderia
    200 com a operação inteira, e a função interna estaria perfeitamente
    correta o tempo todo. Já aconteceu nesta casa (crônica do `ped`/`ctecp`),
    e por isso a declaração tem guard próprio.
    """
    import inspect
    from api import main

    rota = next(r for r in main.app.routes
                if getattr(r, "path", "") == "/api/portal/cliente")
    params = inspect.signature(rota.endpoint).parameters
    assert "merc" in params, (
        "a rota não declara `merc` — o FastAPI vai descartar o filtro que a "
        "tela manda, em silêncio")
    assert params["merc"].default is None, (
        "sem filtro escolhido a rota tem de receber None, que é 'todas'")


# ────────────────────────────────────────── o catálogo que popula a lista

def test_o_catalogo_agrupa_as_GRAFIAS_e_rotula_pela_mais_frequente(monkeypatch):
    """Uma opção por mercadoria, não uma por jeito de escrevê-la.

    "PEÇAS E PARTES AUTOMOTIVAS" (20 cargas) e "PECAS E PARTES AUTOMOTIVAS"
    (6) são a mesma carga da LEAR. Duas opções na lista, cada uma com parte do
    volume, fariam quem filtra escolher a errada e ler metade da operação
    como se fosse a operação.

    O rótulo é a grafia MAIS FREQUENTE — mostrar a normalizada ("PECA E PARTE
    AUTOMOTIVA") seria mostrar um texto que ninguém escreveu.
    """
    bruto = [
        {"chave": ft.normalizar("PEÇAS E PARTES AUTOMOTIVAS"),
         "rotulo": "PEÇAS E PARTES AUTOMOTIVAS", "cargas": 20},
        {"chave": ft.normalizar("PECAS E PARTES AUTOMOTIVAS"),
         "rotulo": "PECAS E PARTES AUTOMOTIVAS", "cargas": 6},
        {"chave": ft.normalizar("CHASSI"), "rotulo": "CHASSI", "cargas": 1551},
    ]
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: bruto)
    itens = pc.get_mercadorias("11222333")["mercadorias"]
    assert [i["rotulo"] for i in itens] == ["CHASSI", "PEÇAS E PARTES AUTOMOTIVAS"]
    assert [i["cargas"] for i in itens] == [1551, 26], (
        "as grafias não somaram: a lista mostra parte da operação como se "
        "fosse o todo")


def test_a_lista_falhar_NAO_derruba_a_tela(monkeypatch):
    """O filtro é acréscimo; as cargas são o dado.

    Sem esta rede, um erro na lista de mercadorias apagaria a aba Agora
    inteira — e quem abriu a tela queria ver as cargas, não o seletor.
    """
    def _explode(raiz, dias=365):
        raise RuntimeError("ERP fora do ar")

    monkeypatch.setattr(pc, "get_mercadorias", _explode)
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [])
    d = pc.get_agora("11222333", 45)
    assert d["mercadorias"] == []
    assert d["em_curso"] == 0 and "cargas" in d


def test_o_payload_ECOA_o_filtro_que_respondeu(monkeypatch):
    """A tela precisa saber contra o que o número foi medido.

    Sem o eco, uma resposta servida de cache responderia por um filtro que já
    mudou, e nada na tela diria isso.
    """
    monkeypatch.setattr(pc.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(pc, "get_mercadorias", lambda raiz, dias=365: {"mercadorias": []})
    monkeypatch.setattr(pc, "_freetime", lambda raiz: {
        "contratos": 0, "linhas": [], "carga_piso": None, "carga_teto": None,
        "descarga_piso": None, "descarga_teto": None, "ambiguo": False})
    assert pc.get_agora("11222333", 45, "RODAS")["mercadoria"] == "RODAS"
    assert pc.get_historico("11222333", 12, "RODAS")["mercadoria"] == "RODAS"
    perm = pc.get_permanencia("11222333", "2026-08-01", "2026-08-31", "RODAS")
    assert perm["mercadoria"] == "RODAS"
