# -*- coding: utf-8 -*-
"""A página inicial é de TODO usuário logado, e a coleta nunca sobe em teste."""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from api import auth, main
from api.radar import agendador

# TestClient FORA de `with`: sem lifespan, sem startup.
cliente = TestClient(main.app)


def test_a_pagina_inicial_e_de_todo_usuario_logado():
    assert "radar" in auth.TELAS_TODO_LOGADO
    assert "radar" in auth.TELAS_FORA_DO_RBAC
    assert "radar" not in auth.TELAS, "não é concedida por perfil — é de todos"
    assert auth.rota_sem_tela("/api/radar"), (
        "o middleware é fail-closed: sem isto a página inicial daria 403 a "
        "quem não é administrador")


def test_todo_usuario_logado_pode_favoritar_a_pagina_inicial():
    assert "radar" in auth.telas_favoritaveis({"id": 7, "admin": False, "telas": []})


def test_a_rota_exige_sessao():
    """Dado público, mas o painel não é página pública."""
    assert cliente.get("/api/radar").status_code == 401


def test_o_front_libera_as_MESMAS_telas_de_todo_logado_que_o_servidor():
    """`podeVer()` tem a sua lista escrita à mão. Era só `sup` lá, e a `apps`
    — de todo logado no servidor — sumia do menu de quem não é administrador,
    sem erro nenhum. Lista duplicada se confere contra a original."""
    import re
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    m = re.search(r"function podeVer\(v\)\{[^\n]*?if\(([^)]*)\) return !!USER;", html)
    assert m, "podeVer mudou de forma — reveja este teste"
    no_front = set(re.findall(r"v==='(\w+)'", m.group(1)))
    assert no_front == set(auth.TELAS_TODO_LOGADO)


def test_o_duble_do_e2e_tem_as_MESMAS_chaves_da_rota(esquema_pg, rede, tomtom, relogio,
                                                    monkeypatch):
    """O e2e da tela lê `tests/frontend/radar_payload.json`. Se a rota ganhar
    ou perder chave e o dublê não acompanhar, a tela passa a ser testada contra
    um formato que o servidor já não manda."""
    import json
    from pathlib import Path
    from api.radar import coleta, painel, rodovias
    monkeypatch.setattr(rodovias, "ativo", lambda: True)
    coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom)
    real = painel.painel(esquema_pg)
    duble = json.loads((Path(__file__).resolve().parents[1] / "frontend"
                        / "radar_payload.json").read_text(encoding="utf-8"))

    def chaves(d, prefixo=""):
        saida = set()
        for k, v in d.items():
            saida.add(prefixo + k)
            if isinstance(v, dict) and k not in ("coleta", "noticias"):
                saida |= chaves(v, prefixo + k + ".")
        return saida
    assert chaves(real) == chaves(duble)
    assert set(real["coleta"]) == set(duble["coleta"])
    assert set(real["noticias"]) == set(duble["noticias"])


def _vivas() -> set[str]:
    return {t.name for t in threading.enumerate()}


def test_a_coleta_NAO_sobe_numa_rodada_de_teste(monkeypatch):
    """O gate REAL, sem dublê. Não há credencial a dublar para cima (as fontes
    são públicas): com `RADAR_COLETA` fora do ambiente, sobra só o gate de
    `sob_teste()` segurando a thread — é ele que se mede."""
    monkeypatch.delenv("RADAR_COLETA", raising=False)
    monkeypatch.setattr(agendador, "_iniciado", False)
    antes = _vivas()
    agendador.iniciar()
    assert "radar-coleta" not in (_vivas() - antes)


def test_com_o_gate_desligado_a_thread_SOBE_com_o_nome_da_lista(monkeypatch):
    """O contrapeso: sem ele o teste de cima passaria com `iniciar()` vazia."""
    solta = threading.Event()
    monkeypatch.delenv("RADAR_COLETA", raising=False)
    monkeypatch.setattr(agendador, "sob_teste", lambda: False)
    monkeypatch.setattr(agendador, "_laco", lambda: solta.wait(5))
    monkeypatch.setattr(agendador, "_iniciado", False)
    try:
        agendador.iniciar()
        assert "radar-coleta" in _vivas()
    finally:
        solta.set()
        for t in threading.enumerate():
            if t.name == "radar-coleta":
                t.join(5)


def test_RADAR_COLETA_0_desliga_mesmo_fora_de_teste(monkeypatch):
    monkeypatch.setenv("RADAR_COLETA", "0")
    monkeypatch.setattr(agendador, "sob_teste", lambda: False)
    monkeypatch.setattr(agendador, "_iniciado", False)
    antes = _vivas()
    agendador.iniciar()
    assert "radar-coleta" not in (_vivas() - antes)


def test_um_ciclo_que_falha_NUNCA_levanta(monkeypatch):
    from api.radar import coleta

    def _explode(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(coleta, "coletar", _explode)
    assert agendador._um_ciclo() is None
