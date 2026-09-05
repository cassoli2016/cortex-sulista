# -*- coding: utf-8 -*-
"""ESCREVER movimento de pneu no CÓRTEX.

O QUE ESTES GUARDS PROTEGEM. Ler a Prolog replica; escrever aqui substitui. E o
que separa um módulo próprio de um caderno são as validações: um cadastro que
aceita o que for digitado produz um dado que ninguém consegue confiar depois —
e é desse dado que sai o CPK, que decide compra.

Os erros que eles travam não são hipóteses:

- **Posição que não existe naquele veículo.** "3DE" numa carreta de dois eixos
  entra e fica, e a partir dali o inventário mente.
- **Dois pneus na mesma posição.** É o erro que NÃO se descobre: o inventário
  fecha, e o CPK divide por um km que só um dos dois rodou.
- **Movimento a partir do estado errado.** Montar um pneu sucateado, remover um
  que está no estoque: aceitar isso faz o estado do parque virar ficção.
- **Hodômetro e sulco fora da faixa física.** Já apareceram 1 km e 7,3 milhões
  vindos do fornecedor; do teclado aparecem também.
- **Motivo de sucata em texto livre.** Vira dez grafias da mesma coisa e nenhum
  agrupamento funciona — e é o agrupamento que responde por que os pneus estão
  morrendo.

E UM ERRO MEU, que a primeira versão cometeu: montar a sigla da posição a
partir da estrutura do diagrama produzia `2DE` para um cavalo, quando o parque
usa `TDE`. Implemento numera o eixo, tração usa letra. Código sem tabela de
domínio não vira rótulo inventado — o vocabulário passou a sair da observação.
"""
from __future__ import annotations

import pytest

from api.pneus import movimento as mv


@pytest.fixture
def banco(esquema_pg, monkeypatch):
    """Um parque pequeno e completo no schema do teste."""
    from api import pglocal
    original = pglocal.get_conn
    monkeypatch.setattr(pglocal, "get_conn",
                        lambda **k: original(esquema=esquema_pg))
    monkeypatch.setattr(pglocal, "query",
                        lambda sql, params=None, **k: _query(
                            original, esquema_pg, sql, params))
    monkeypatch.setattr(mv, "_auditar", lambda *a, **k: None)

    with original(esquema=esquema_pg) as c, c.cursor() as cur:
        cur.execute("INSERT INTO pne_diagrama (nome, tem_motor, eixos, posicoes,"
                    " prolog_id) VALUES ('TOCO', true, 2, %s, '1') RETURNING id",
                    ('[{"eixo":1,"tipo":"D","pneus":2},'
                     ' {"eixo":2,"tipo":"T","pneus":4}]',))
        diag = cur.fetchone()["id"]
        cur.execute("INSERT INTO pne_veiculo (placa, diagrama_id, estepes) "
                    "VALUES ('AAA1A11',%s,1), ('BBB2B22',%s,1)", (diag, diag))
        # o veículo IRMÃO dá o vocabulário observado
        cur.execute("INSERT INTO pne_modelo (marca, modelo) VALUES ('M','X') "
                    "RETURNING id")
        modelo = cur.fetchone()["id"]
        for serie, placa, pos, st in (("REF1", "BBB2B22", "DD", "rodando"),
                                      ("REF2", "BBB2B22", "DE", "rodando"),
                                      ("REF3", "BBB2B22", "TDE", "rodando"),
                                      ("REF4", "BBB2B22", "TDI", "rodando"),
                                      ("REF5", "BBB2B22", "TEE", "rodando"),
                                      ("REF6", "BBB2B22", "TEI", "rodando"),
                                      ("REF7", "BBB2B22", "ES1", "rodando")):
            cur.execute("INSERT INTO pne_pneu (serie, modelo_id, status, "
                        "placa_atual, posicao_atual) VALUES (%s,%s,%s,%s,%s)",
                        (serie, modelo, st, placa, pos))
        cur.execute("INSERT INTO pne_pneu (serie, modelo_id, status) "
                    "VALUES ('NOVO',%s,'estoque') RETURNING id", (modelo,))
        novo = cur.fetchone()["id"]
        cur.execute("INSERT INTO pne_pneu (serie, modelo_id, status) "
                    "VALUES ('MORTO',%s,'sucata') RETURNING id", (modelo,))
        morto = cur.fetchone()["id"]
        cur.execute("INSERT INTO pne_pneu (serie, modelo_id, status, "
                    "placa_atual, posicao_atual) VALUES "
                    "('EMUSO',%s,'rodando','AAA1A11','DD') RETURNING id",
                    (modelo,))
        em_uso = cur.fetchone()["id"]
        cur.execute("INSERT INTO pne_motivo (especie, prolog_id, rotulo) "
                    "VALUES ('descarte','9','DANO NO FLANCO') RETURNING id")
        motivo = cur.fetchone()["id"]
        cur.execute("INSERT INTO pne_motivo (especie, prolog_id, rotulo, ativo)"
                    " VALUES ('descarte','8','ANTIGO', false) RETURNING id")
        inativo = cur.fetchone()["id"]

    return {"novo": novo, "morto": morto, "em_uso": em_uso,
            "motivo": motivo, "motivo_inativo": inativo, "esquema": esquema_pg,
            "abrir": original}


def _query(abrir, esquema, sql, params):
    with abrir(esquema=esquema) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _status(banco, pneu_id):
    linhas = _query(banco["abrir"], banco["esquema"],
                    "SELECT status, placa_atual, posicao_atual FROM pne_pneu "
                    "WHERE id = %s", (pneu_id,))
    return linhas[0]


# --------------------------------------------------------------------------
# o vocabulário de posições
# --------------------------------------------------------------------------
def test_as_posicoes_saem_da_OBSERVACAO_e_nao_de_uma_regra_de_formacao(banco):
    """O erro da primeira versão: montar a sigla a partir da estrutura do
    diagrama produzia `2DE` para um cavalo, e o parque usa `TDE`. Implemento
    numera o eixo, tração usa letra — e não há tabela de domínio para isso."""
    d = mv.posicoes_do_veiculo("AAA1A11")
    assert "TDE" in d["posicoes"] and "DD" in d["posicoes"]
    assert "2DE" not in d["posicoes"], "voltou a inventar a sigla"
    assert d["diagrama"] == "TOCO"


def test_o_diagrama_CONFERE_a_contagem(banco):
    """Ele não gera a sigla, mas diz quantos pneus de eixo o veículo tem — e a
    contagem observada tem de bater."""
    d = mv.posicoes_do_veiculo("AAA1A11")
    assert d["de_eixo"] == d["esperados"] == 6
    assert d["estepes"] == 1 and "aviso" not in d


def test_veiculo_sem_referencia_DIZ_o_motivo(banco):
    d = mv.posicoes_do_veiculo("ZZZ9Z99")
    assert d["posicoes"] == [] and d["motivo"]


# --------------------------------------------------------------------------
# instalar
# --------------------------------------------------------------------------
def test_instalar_grava_o_evento_e_muda_o_estado(banco):
    r = mv.instalar(banco["novo"], "AAA1A11", "TDE", km=350000, usuario="ana")
    assert r["ok"]
    p = _status(banco, banco["novo"])
    assert (p["status"], p["placa_atual"], p["posicao_atual"]) == \
        ("rodando", "AAA1A11", "TDE")


def test_posicao_que_NAO_existe_no_veiculo_e_recusada(banco):
    with pytest.raises(mv.MovimentoInvalido) as e:
        mv.instalar(banco["novo"], "AAA1A11", "9XY", km=350000)
    assert "não existe" in str(e.value)
    assert _status(banco, banco["novo"])["status"] == "estoque"


def test_posicao_JA_OCUPADA_e_recusada(banco):
    """O erro que não se descobre: o inventário fecha e o CPK divide por um km
    que só um dos dois pneus rodou."""
    with pytest.raises(mv.MovimentoInvalido) as e:
        mv.instalar(banco["novo"], "AAA1A11", "DD", km=350000)
    assert "já está com o pneu" in str(e.value)


def test_pneu_SUCATEADO_nao_volta_a_rodar(banco):
    with pytest.raises(mv.MovimentoInvalido) as e:
        mv.instalar(banco["morto"], "AAA1A11", "TDE", km=350000)
    assert "sucata" in str(e.value)


def test_veiculo_sem_diagrama_e_recusado_DIZENDO(banco):
    with pytest.raises(mv.MovimentoInvalido) as e:
        mv.instalar(banco["novo"], "ZZZ9Z99", "TDE", km=350000)
    assert "não sabemos as posições" in str(e.value).lower()


# --------------------------------------------------------------------------
# hodômetro e sulco: faixa física
# --------------------------------------------------------------------------
@pytest.mark.parametrize("km", [1, 134, 7359990, 0, -5, "abc"])
def test_hodometro_fora_da_faixa_e_recusado(banco, km):
    with pytest.raises(mv.MovimentoInvalido):
        mv.instalar(banco["novo"], "AAA1A11", "TDE", km=km)


def test_hodometro_em_branco_e_ACEITO(banco):
    """Nem toda montagem acontece com alguém olhando o painel. Exigir o km
    faria a pessoa inventar um número, que é pior que não ter."""
    assert mv.instalar(banco["novo"], "AAA1A11", "TDE")["ok"]


@pytest.mark.parametrize("sulco", [-1, 31, 100])
def test_sulco_fora_da_faixa_fisica_e_recusado(banco, sulco):
    """Um sulco errado vira uma taxa de desgaste errada, que vira uma data de
    troca, que vira um pedido de compra."""
    with pytest.raises(mv.MovimentoInvalido):
        mv.inspecionar(banco["em_uso"], [sulco, 8, 8, 8])


# --------------------------------------------------------------------------
# remover e sucatear
# --------------------------------------------------------------------------
def test_remover_devolve_ao_estoque_e_libera_a_posicao(banco):
    r = mv.remover(banco["em_uso"], km=360000, motivo="rodízio")
    assert r["ok"] and r["posicao"] == "DD"
    p = _status(banco, banco["em_uso"])
    assert p["status"] == "estoque" and p["placa_atual"] is None
    # e agora a posição aceita outro pneu
    assert mv.instalar(banco["novo"], "AAA1A11", "DD")["ok"]


def test_remover_pneu_que_NAO_esta_rodando_e_recusado(banco):
    with pytest.raises(mv.MovimentoInvalido):
        mv.remover(banco["novo"])


def test_sucatear_exige_motivo_DA_TABELA(banco):
    """Motivo digitado vira dez grafias da mesma coisa e nenhum agrupamento
    funciona — e é o agrupamento que responde por que os pneus estão morrendo."""
    r = mv.sucatear(banco["em_uso"], banco["motivo"])
    assert r["motivo"] == "DANO NO FLANCO"
    assert _status(banco, banco["em_uso"])["status"] == "sucata"


def test_motivo_INEXISTENTE_ou_INATIVO_e_recusado(banco):
    for mid in (999999, banco["motivo_inativo"]):
        with pytest.raises(mv.MovimentoInvalido) as e:
            mv.sucatear(banco["em_uso"], mid)
        assert "inválido ou inativo" in str(e.value)


# --------------------------------------------------------------------------
# a marca de origem
# --------------------------------------------------------------------------
def test_o_que_a_casa_escreve_tem_origem_CORTEX(banco):
    """A coluna existe para que se saiba qual pedaço da história é importado e
    qual é nosso — e para que a coleta da Prolog nunca sobrescreva o digitado
    aqui."""
    mv.instalar(banco["novo"], "AAA1A11", "TDE", usuario="ana")
    linhas = _query(banco["abrir"], banco["esquema"],
                    "SELECT origem, usuario, tipo FROM pne_evento "
                    "WHERE pneu_id = %s", (banco["novo"],))
    assert linhas[0]["origem"] == "cortex"
    assert linhas[0]["usuario"] == "ana" and linhas[0]["tipo"] == "instalacao"


def test_a_inspecao_propria_tambem_e_CORTEX(banco):
    mv.inspecionar(banco["em_uso"], [8.0, 8.1, 8.2, 8.3], pressao=110,
                   km=350000, usuario="ana")
    linhas = _query(banco["abrir"], banco["esquema"],
                    "SELECT origem, sulcos_mm, placa, km_veiculo FROM "
                    "pne_inspecao WHERE pneu_id = %s", (banco["em_uso"],))
    assert linhas[0]["origem"] == "cortex"
    assert linhas[0]["placa"] == "AAA1A11"
    assert linhas[0]["km_veiculo"] == 350000
