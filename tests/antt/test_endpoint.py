"""Contrato do endpoint e registro no RBAC."""
from __future__ import annotations

from api.auth import ROTA_TELAS, TELAS


def test_tela_registrada_no_rbac():
    assert TELAS["anpiso"] == ("Piso Mínimo de Frete", "ANTT")


def test_rota_mapeada_para_a_tela():
    achado = [telas for prefixo, telas in ROTA_TELAS
              if prefixo == "/api/operacao/antt/piso"]
    assert achado and achado[0] == frozenset({"anpiso"})


def test_rota_do_piso_vem_antes_de_prefixo_mais_generico():
    # fail-closed: prefixo mais específico primeiro, senão outra rota captura
    posicoes = {p: i for i, (p, _) in enumerate(ROTA_TELAS)}
    alvo = posicoes["/api/operacao/antt/piso"]
    for prefixo, i in posicoes.items():
        if prefixo != "/api/operacao/antt/piso" and \
                "/api/operacao/antt/piso".startswith(prefixo):
            assert alvo < i, f"{prefixo} captura a rota do piso antes dela"


def test_endpoint_existe_e_aceita_os_filtros_da_tela():
    from api.main import app
    rota = [r for r in app.routes
            if getattr(r, "path", None) == "/api/operacao/antt/piso"]
    assert rota, "endpoint não registrado no app"
    params = set(rota[0].dependant.query_params and
                 [p.name for p in rota[0].dependant.query_params] or [])
    assert {"filial", "dt_de", "dt_ate", "modalidade", "transportador"} <= params
