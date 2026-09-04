# -*- coding: utf-8 -*-
"""Avaliação de Desempenho — a matriz nine box.

Os guards daqui protegem três coisas, e as três são sobre GENTE, o que muda a
consequência de errar:

1. **Quem não foi avaliado não é caixa 1.** Ausência de avaliação não é
   desempenho baixo. Numa DRE essa confusão custa um número torto; aqui ela
   coloca uma pessoa no canto de "plano de ação, e se não virar é conversa de
   desligamento" porque o gestor dela não abriu a tela.

2. **Mapa vazio é ver NINGUÉM.** O caminho oposto — cair para "vê todos" —
   abriria a folha inteira, com nome, cargo e área, para quem só devia ver a
   própria equipe. É um defeito que continua funcionando, e por isso ninguém
   descobre.

3. **Ciclo fechado não aceita escrita.** A avaliação é a foto que explica as
   decisões tomadas em cima dela; reescrevível, ela deixa de explicar.
"""
from __future__ import annotations

import pytest

from api import desempenho as de

PESSOA = {"codintfunc": 101, "chapa": "0001", "nome": "MARIA SILVA",
          "cargo": "ANALISTA FISCAL", "area": "ADMINISTRATIVO",
          "secao": "CONTABILIDADE"}


@pytest.fixture
def ciclo(esquema_pg):
    return de.criar_ciclo("teste", "2026-01-01", "2026-06-30", "rh@x.com",
                          esquema=esquema_pg)


# ---------------------------------------------------------- a aritmética
def test_a_caixa_sai_das_duas_notas():
    """A caixa 1 é o canto de baixo à esquerda e a 9 o de cima à direita — a
    leitura natural da matriz desenhada."""
    assert de.caixa(1, 1) == 1 and de.caixa(3, 3) == 9
    assert de.caixa(3, 1) == 3, "desempenho alto e potencial baixo é Especialista"
    assert de.caixa(1, 3) == 7, "desempenho baixo e potencial alto é Enigma"
    assert de.CAIXAS[7]["nome"] == "Enigma"
    assert de.CAIXAS[3]["nome"] == "Especialista"


def test_nota_fora_da_escala_nao_vira_caixa():
    for d, p in ((0, 1), (4, 1), (1, 0), (1, 4)):
        with pytest.raises(ValueError):
            de.caixa(d, p)


def test_toda_caixa_diz_o_que_FAZER():
    """Matriz que classifica sem dizer o que fazer devolve a decisão inteira
    para quem já não sabia o que fazer."""
    for n, c in de.CAIXAS.items():
        assert c["nome"] and len(c["conduta"]) > 40, n
        assert c["cor"] in ("bom", "atencao", "ruim"), n


# --------------------------------------------------------------- gravar
def test_a_justificativa_e_OBRIGATORIA(ciclo, esquema_pg):
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    with pytest.raises(ValueError, match="justificativa"):
        de.avaliar(ciclo["id"], PESSOA, 2, 2, "ok", "chefe@x.com",
                   esquema=esquema_pg)


def test_ciclo_FECHADO_nao_aceita_nota(ciclo, esquema_pg):
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.avaliar(ciclo["id"], PESSOA, 2, 2, "entregou o combinado no semestre",
               "chefe@x.com", esquema=esquema_pg)
    de.mudar_estado(ciclo["id"], "fechado", "rh@x.com", esquema=esquema_pg)
    with pytest.raises(ValueError, match="aberto"):
        de.avaliar(ciclo["id"], PESSOA, 3, 3, "mudei de ideia sobre a nota",
                   "chefe@x.com", esquema=esquema_pg)


def test_ciclo_em_RASCUNHO_tambem_nao(ciclo, esquema_pg):
    with pytest.raises(ValueError, match="aberto"):
        de.avaliar(ciclo["id"], PESSOA, 2, 2, "o ciclo nem começou ainda",
                   "chefe@x.com", esquema=esquema_pg)


def test_reavaliar_REFRESCA_a_foto(ciclo, esquema_pg):
    """O cargo muda entre a primeira nota e a segunda, e a lista mostraria o
    cargo velho ao lado da nota nova."""
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.avaliar(ciclo["id"], PESSOA, 1, 1, "primeiro semestre foi difícil",
               "chefe@x.com", esquema=esquema_pg)
    r = de.avaliar(ciclo["id"], {**PESSOA, "cargo": "COORDENADORA FISCAL"},
                   3, 3, "assumiu a coordenação e entregou", "chefe@x.com",
                   esquema=esquema_pg)
    assert r["cargo"] == "COORDENADORA FISCAL"
    assert r["desempenho"] == 3 and r["potencial"] == 3
    assert len(de.avaliacoes(ciclo["id"], esquema=esquema_pg)) == 1, \
        "reavaliar criou uma segunda linha para a mesma pessoa"


def test_UM_ciclo_aberto_de_cada_vez(esquema_pg):
    """Dois abertos fariam a mesma pessoa aparecer em duas listas de pendência,
    e a matriz teria de escolher um sem dizer qual."""
    a = de.criar_ciclo("1sem", "2026-01-01", "2026-06-30", "rh@x.com",
                       esquema=esquema_pg)
    b = de.criar_ciclo("2sem", "2026-07-01", "2026-12-31", "rh@x.com",
                       esquema=esquema_pg)
    de.mudar_estado(a["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.mudar_estado(b["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    abertos = [c for c in de.ciclos(esquema=esquema_pg) if c["estado"] == "aberto"]
    assert len(abertos) == 1 and abertos[0]["id"] == b["id"]


def test_ciclo_com_periodo_invertido_nao_entra(esquema_pg):
    with pytest.raises(ValueError):
        de.criar_ciclo("torto", "2026-12-31", "2026-01-01", "rh@x.com",
                       esquema=esquema_pg)


# ---------------------------------------------------------------- escopo
def test_mapa_vazio_e_ver_NINGUEM(esquema_pg, monkeypatch):
    """O contrário — cair para "vê todos" — abriria a folha inteira por
    esquecimento de cadastro."""
    monkeypatch.setattr(de, "_q", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("consultou a folha sem escopo nenhum")))
    d = de.equipe("gestor@x.com", ver_tudo=False, esquema=esquema_pg)
    assert d["linhas"] == [] and d["sem_escopo"] is True


def test_o_escopo_vira_filtro_na_consulta(esquema_pg, monkeypatch):
    de.mapear("gestor@x.com", "area", "Administrativo", "rh@x.com",
              esquema=esquema_pg)
    vistas = {}

    def _falso(sql, binds=None):
        vistas["sql"], vistas["binds"] = sql, binds or {}
        return []

    monkeypatch.setattr(de, "_q", _falso)
    de.equipe("gestor@x.com", esquema=esquema_pg)
    assert "descarea" in vistas["sql"] and "situacaofunc = 'A'" in vistas["sql"]
    # NORMALIZADO na comparação: o cadastro tem "ADMINISTRATIVO" e
    # "Administrativo", e sem UPPER/TRIM o gestor não veria a própria equipe.
    assert vistas["binds"]["e0"] == "ADMINISTRATIVO"
    assert "UPPER(TRIM(" in vistas["sql"]


def test_ver_tudo_nao_passa_pelo_mapa(esquema_pg, monkeypatch):
    vistas = {}
    monkeypatch.setattr(de, "_q",
                        lambda sql, binds=None: vistas.update(sql=sql) or [])
    de.equipe("rh@x.com", ver_tudo=True, esquema=esquema_pg)
    # `descarea` aparece na LISTA de colunas mesmo vendo tudo; o que não pode
    # existir é o FILTRO — e ele é o único lugar com `UPPER(TRIM(`.
    assert "UPPER(TRIM(" not in vistas["sql"], vistas["sql"]


# ---------------------------------------------------------------- matriz
def _folha(monkeypatch, pessoas):
    monkeypatch.setattr(de, "_q", lambda *a, **k: [
        {"codintfunc": p["codintfunc"], "chapafunc": p["chapa"],
         "nomefunc": p["nome"], "cargo": p["cargo"], "area": p["area"],
         "secao": p["secao"], "admissao": None} for p in pessoas])


def test_quem_NAO_foi_avaliado_fica_FORA_da_matriz(ciclo, esquema_pg,
                                                   monkeypatch):
    """Ausência de avaliação não é desempenho baixo — e aqui essa confusão
    põe uma pessoa no canto de "conversa de desligamento" porque o gestor dela
    não abriu a tela."""
    outra = {**PESSOA, "codintfunc": 102, "nome": "JOAO SOUZA"}
    _folha(monkeypatch, [PESSOA, outra])
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.avaliar(ciclo["id"], PESSOA, 2, 2, "entregou o combinado no semestre",
               "chefe@x.com", esquema=esquema_pg)
    m = de.matriz(ciclo["id"], "rh@x.com", ver_tudo=True, esquema=esquema_pg)
    dentro = {p["nome"] for c in m["caixas"] for p in c["pessoas"]}
    assert dentro == {"MARIA SILVA"}
    assert [p["nome"] for p in m["pendentes"]] == ["JOAO SOUZA"]
    caixa1 = next(c for c in m["caixas"] if c["n"] == 1)
    assert caixa1["quantos"] == 0, "não avaliado caiu na caixa 1"


def test_a_cobertura_vem_SEMPRE_junto(ciclo, esquema_pg, monkeypatch):
    """Uma matriz com 1 de 4 avaliados e uma com 4 de 4 se parecem na tela."""
    gente = [{**PESSOA, "codintfunc": 100 + i, "nome": "P%d" % i}
             for i in range(4)]
    _folha(monkeypatch, gente)
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.avaliar(ciclo["id"], gente[0], 2, 2, "entregou o combinado no semestre",
               "chefe@x.com", esquema=esquema_pg)
    k = de.matriz(ciclo["id"], "rh@x.com", True, esquema=esquema_pg)["kpis"]
    assert k == {"pessoas": 4, "avaliados": 1, "pendentes": 3, "cobertura": 25.0}


def test_o_percentual_da_caixa_e_sobre_os_AVALIADOS(ciclo, esquema_pg,
                                                    monkeypatch):
    """Sobre o quadro inteiro ele diria 25% onde a leitura é "todo mundo que
    foi avaliado está aqui" — e a diferença muda a conversa."""
    gente = [{**PESSOA, "codintfunc": 100 + i, "nome": "P%d" % i}
             for i in range(4)]
    _folha(monkeypatch, gente)
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.avaliar(ciclo["id"], gente[0], 2, 2, "entregou o combinado no semestre",
               "chefe@x.com", esquema=esquema_pg)
    m = de.matriz(ciclo["id"], "rh@x.com", True, esquema=esquema_pg)
    c5 = next(c for c in m["caixas"] if c["n"] == 5)
    assert c5["quantos"] == 1 and c5["pct"] == 100.0


def test_a_matriz_de_um_gestor_so_traz_a_equipe_dele(ciclo, esquema_pg,
                                                     monkeypatch):
    de.mapear("gestor@x.com", "area", "ADMINISTRATIVO", "rh@x.com",
              esquema=esquema_pg)
    _folha(monkeypatch, [PESSOA])
    m = de.matriz(ciclo["id"], "gestor@x.com", ver_tudo=False,
                  esquema=esquema_pg)
    assert m["kpis"]["pessoas"] == 1
    assert m["sem_escopo"] is False and "ADMINISTRATIVO" in m["alcance"]


def test_gestor_sem_mapa_ve_matriz_VAZIA_e_a_tela_diz(ciclo, esquema_pg,
                                                      monkeypatch):
    monkeypatch.setattr(de, "_q", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("consultou a folha sem escopo nenhum")))
    m = de.matriz(ciclo["id"], "ninguem@x.com", ver_tudo=False,
                  esquema=esquema_pg)
    assert m["sem_escopo"] is True and m["kpis"]["pessoas"] == 0


# -------------------------------------------------------------- snapshot
def test_o_snapshot_do_copiloto_nao_leva_NOME_de_ninguem(ciclo, esquema_pg,
                                                         monkeypatch):
    """Uma matriz de desempenho com nomes dentro de um chat é exatamente o que
    a regra de PII da casa existe para impedir — e é o que permite o fallback
    externo do Copiloto."""
    de.mudar_estado(ciclo["id"], "aberto", "rh@x.com", esquema=esquema_pg)
    de.avaliar(ciclo["id"], PESSOA, 3, 3, "entregou acima em tudo no semestre",
               "chefe@x.com", esquema=esquema_pg)
    s = de.snapshot(esquema=esquema_pg)
    texto = repr(s)
    assert "MARIA" not in texto and "0001" not in texto
    assert "chefe@x.com" not in texto and "ANALISTA" not in texto
    assert s["por_caixa"] == {"Estrela": 1} and s["avaliados"] == 1


def test_a_tela_e_a_rota_estao_no_rbac():
    from api import auth
    assert auth.TELAS["des"][1] == "Recursos Humanos"
    # `desrh` é permissão, não tela de menu — como o `dreexc`
    assert "desrh" in auth.TELAS_SEM_MENU
    rotas = dict(auth.ROTA_TELAS)
    # ADMINISTRAR exige `desrh`; avaliar basta `des`
    assert rotas["/api/desempenho/ciclos/gravar"] == frozenset({"desrh"})
    assert rotas["/api/desempenho/gestores/mapear"] == frozenset({"desrh"})
    assert "des" in rotas["/api/desempenho/avaliar"]
    # a mais ESPECÍFICA antes da genérica, senão o prefixo engole
    ordem = [p for p, _ in auth.ROTA_TELAS if p.startswith("/api/desempenho")]
    assert ordem.index("/api/desempenho/ciclos/gravar") < ordem.index("/api/desempenho/ciclos")
    assert ordem.index("/api/desempenho/gestores/mapear") < ordem.index("/api/desempenho/gestores")


def test_os_nomes_das_caixas_batem_entre_o_modulo_e_a_TELA():
    """Nome de caixa que diverge entre a matriz e a lista faz a mesma pessoa
    parecer duas coisas na mesma tela."""
    import pathlib
    import re
    html = pathlib.Path("api/static/index.html").read_text(encoding="utf-8")
    bloco = re.search(r"const DESCAIXA = \{(.+?)\};", html, re.S)
    assert bloco, "a tela não declara os nomes das caixas"
    nomes = dict(re.findall(r"(\d):'([^']+)'", bloco.group(1)))
    assert {int(k): v for k, v in nomes.items()} == \
        {n: c["nome"] for n, c in de.CAIXAS.items()}
