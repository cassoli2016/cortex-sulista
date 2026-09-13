# -*- coding: utf-8 -*-
"""O WMS nos testes escreve SEMPRE num schema descartável.

`comum.ESQUEMA` é o ponto único que todos os arquivos do módulo leem — um
lugar só para esquecer. E nenhum teste daqui usa `TestClient`: ele dispara o
startup, que aplica migration no schema de PRODUÇÃO (visto em 31/08/2026).
"""
from __future__ import annotations

import pytest

from api.wms import cadastro, comum

CNPJ_DEP = "84693183000168"       # um depositante qualquer, com cara de CNPJ real
USUARIO = "teste@sulista.local"


@pytest.fixture
def wms(esquema_pg):
    antes = comum.ESQUEMA
    comum.ESQUEMA = esquema_pg
    try:
        yield esquema_pg
    finally:
        comum.ESQUEMA = antes


@pytest.fixture
def armazem(wms):
    """Um armazém pronto para operar: 2 ruas × 2 prédios × 1 nível × 2
    posições de porta-palete, uma doca, uma expedição e uma avaria; um
    depositante e dois produtos (um que controla lote e validade)."""
    a = cadastro.criar_armazem({"codigo": "JVE1", "nome": "Armazém Joinville"}, USUARIO)
    cadastro.gerar_enderecos(a["id"], {"ruas": "A-B", "predio_de": 1, "predio_ate": 2,
                                       "nivel_de": 1, "nivel_ate": 1,
                                       "posicao_de": 1, "posicao_ate": 2}, USUARIO)
    ids = {}
    for cod, tipo in (("DOCA1", "doca"), ("EXP1", "expedicao"), ("AVARIA", "avaria")):
        ids[cod] = cadastro.criar_endereco(a["id"], {"codigo": cod, "tipo": tipo}, USUARIO)["id"]
    cadastro.criar_depositante({"cnpj": CNPJ_DEP, "razao_social": "SCHULZ S/A"}, USUARIO)
    p1 = cadastro.criar_produto({"depositante_cnpj": CNPJ_DEP, "codigo": "961.0301-0",
                                 "descricao": "RACK METALICO", "unidade": "PC"}, USUARIO)["id"]
    p2 = cadastro.criar_produto({"depositante_cnpj": CNPJ_DEP, "codigo": "OLEO-20L",
                                 "descricao": "OLEO LUBRIFICANTE 20L", "unidade": "BD",
                                 "controla_lote": True, "controla_validade": True},
                                USUARIO)["id"]
    enderecos = {e["codigo"]: e["id"] for e in
                 cadastro.listar_enderecos(a["id"])["enderecos"]}
    return {"id": a["id"], "doca": ids["DOCA1"], "exp": ids["EXP1"], "avaria": ids["AVARIA"],
            "p1": p1, "p2": p2, "end": enderecos, "esquema": wms}
