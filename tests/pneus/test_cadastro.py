# -*- coding: utf-8 -*-
"""As tabelas de DOMÍNIO da Prolog no banco da casa.

POR QUE ELAS IMPORTAM MAIS QUE PARECEM. O instantâneo diz o estado dos pneus
hoje; estas dizem o que as coisas SIGNIFICAM. Sem elas o nosso banco guarda
códigos que só a Prolog sabe ler — e o objetivo declarado é que um dia ela não
esteja mais lá.

Duas lacunas concretas que elas fecham:

- `pne_diagrama` estava VAZIA. Sem ela não há como afirmar que a posição `3DE`
  existe naquele veículo, e um módulo próprio que registra montagem aceitaria
  qualquer coisa digitada.
- `pne_evento.motivo` está 100% nulo. A regra da casa é que código sem tabela
  de domínio não vira rótulo inventado — com a tabela replicada, o rótulo passa
  a ter de onde vir.

E DOIS ERROS MEUS, na primeira versão, que os guards abaixo travam:

1. Os dois endpoints dividiam a MESMA transação. O segundo respondeu HTTP 400 e
   o rollback levou junto os 18 motivos que o primeiro já tinha gravado.
2. O campo chama `reasonName`. Eu lia `description`, `name` e `reason` — três
   nomes plausíveis, nenhum certo — e a tabela entrava vazia sem erro nenhum.
"""
from __future__ import annotations

import pytest

from api.pneus import cadastro

DIAGRAMA = {
    "id": 1, "name": "TOCO", "hasEngine": True,
    "axles": [
        {"axlePosition": 1, "axleType": "D", "axleKind": "DIRECTIONAL",
         "tireQuantity": 2, "canBeSuspended": False},
        {"axlePosition": 2, "axleType": "T", "axleKind": "MOTORIZED",
         "tireQuantity": 4, "canBeSuspended": False},
    ]}

MOTIVO = {"id": 1071, "reasonName": "SEPARAÇÃO DE LONAS/CINTAS",
          "isActive": True}


@pytest.fixture
def conn_teste(esquema_pg, monkeypatch):
    """Aponta o módulo para o schema do teste.

    A ORIGINAL É CAPTURADA ANTES do `setattr`: `cadastro.pglocal` É o módulo
    `pglocal`, então uma lambda que chame `pglocal.get_conn` depois da troca
    chama a si mesma — recursão infinita, e o erro que aparece é "maximum
    recursion depth", que não lembra em nada o que aconteceu.
    """
    from api import pglocal
    original = pglocal.get_conn
    monkeypatch.setattr(pglocal, "get_conn",
                        lambda **k: original(esquema=esquema_pg))
    return esquema_pg, original


class _Cli:
    """Dublê que responde por caminho e pode falhar num deles."""

    def __init__(self, falhar=()):
        self.falhar = falhar
        self.chamou = []

    def get(self, caminho, params=None):
        self.chamou.append(caminho)
        if caminho in self.falhar:
            raise RuntimeError("HTTP 400")
        if "diagrams" in caminho:
            return [DIAGRAMA]
        return [MOTIVO]


# --------------------------------------------------------------------------
# o diagrama
# --------------------------------------------------------------------------
def test_o_diagrama_guarda_a_ESTRUTURA_do_eixo(conn_teste):
    """Não basta o nome: quantos eixos, de que tipo, com quantos pneus e se
    podem ser suspensos. É disso que uma validação de posição e uma regra de
    rodízio vão precisar depois."""
    esquema_pg, abrir = conn_teste
    assert cadastro._diagramas(_Cli()) == 1

    with abrir(esquema=esquema_pg) as c, c.cursor() as cur:
        cur.execute("SELECT nome, tem_motor, eixos, posicoes FROM pne_diagrama")
        d = cur.fetchone()
    assert d["nome"] == "TOCO" and d["tem_motor"] and d["eixos"] == 2
    assert sum(p["pneus"] for p in d["posicoes"]) == 6
    assert [p["tipo"] for p in d["posicoes"]] == ["D", "T"]
    assert [p["funcao"] for p in d["posicoes"]] == ["DIRECTIONAL", "MOTORIZED"]


def test_recoletar_o_diagrama_NAO_duplica(conn_teste):
    esquema_pg, abrir = conn_teste
    cadastro._diagramas(_Cli())
    cadastro._diagramas(_Cli())
    with abrir(esquema=esquema_pg) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM pne_diagrama")
        assert cur.fetchone()["n"] == 1


# --------------------------------------------------------------------------
# o motivo
# --------------------------------------------------------------------------
def test_o_rotulo_do_motivo_vem_de_reasonName(conn_teste):
    """O guard do campo errado. Ler três nomes plausíveis e nenhum certo faz a
    tabela entrar VAZIA — sem erro, sem sintoma, e a lacuna só aparece meses
    depois quando alguém procura o motivo de uma sucata."""
    esquema_pg, abrir = conn_teste
    assert cadastro._motivos(_Cli()) == 1
    with abrir(esquema=esquema_pg) as c, c.cursor() as cur:
        cur.execute("SELECT especie, rotulo, ativo FROM pne_motivo")
        m = cur.fetchone()
    assert m["rotulo"] == "SEPARAÇÃO DE LONAS/CINTAS"
    assert m["especie"] == "descarte" and m["ativo"] is True


def test_motivo_sem_rotulo_NAO_vira_linha_vazia(conn_teste):
    class _Vazio(_Cli):
        def get(self, caminho, params=None):
            return [{"id": 1, "reasonName": "  "}, {"reasonName": "sem id"}]

    assert cadastro._motivos(_Vazio()) == 0


# --------------------------------------------------------------------------
# a falha de um não desfaz o outro
# --------------------------------------------------------------------------
def test_um_endpoint_FORA_DO_AR_nao_zera_o_outro(conn_teste, monkeypatch):
    """O erro da primeira versão: os dois passos no mesmo `try`, o 400 do
    segundo apagando o resultado do primeiro. O fornecedor tem endpoints com
    maturidades diferentes, e um deles fora do ar não pode zerar a coleta."""
    monkeypatch.setattr(cadastro.cliente, "pronto", lambda: True)
    monkeypatch.setattr(cadastro.cliente, "Cliente",
                        lambda *a, **k: _Cli(falhar={"/api/v3/tire-relocations/disposal-reasons"}))
    monkeypatch.setattr(cadastro, "_gravar_estado", lambda *a, **k: None)

    r = cadastro.sincronizar()
    assert r["diagramas"] == 1, "a falha do segundo passo desfez o primeiro"
    assert r["motivos"] == 0
    # E A FALHA SE DECLARA em vez de virar sucesso silencioso.
    assert r["ok"] is False and "motivos" in r["erro"]


def test_sem_credencial_a_coleta_RECUSA_sem_levantar(monkeypatch):
    monkeypatch.setattr(cadastro.cliente, "pronto", lambda: False)
    r = cadastro.sincronizar()
    assert r["ok"] is False and r["erro"]
