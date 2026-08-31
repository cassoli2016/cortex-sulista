# -*- coding: utf-8 -*-
"""Gravação da fatura de tag: idempotência, recusa e tarifa observada.

Usa a fixture `esquema_pg` (schema por teste), que é o padrão da casa para
módulo que escreve no banco local. As páginas vêm do fixture sintético do
`test_fatura_semparar` — a fatura real não entra no repositório, que é público.
"""
from __future__ import annotations

import pytest

from api.pedagio import fatura_tag as ft
from api.pedagio import semparar as sp

from .test_fatura_semparar import DETALHE, LINHA_FALTANTE, paginas


@pytest.fixture()
def gravar(monkeypatch, esquema_pg):
    """Importa páginas sintéticas sem passar por um PDF de verdade."""
    def _importar(pgs, nome="fatura.pdf", usuario="teste"):
        monkeypatch.setattr(sp, "ler",
                            lambda n, b: dict(sp.interpretar(pgs),
                                              **{"cabecalho": dict(
                                                  sp.interpretar(pgs)["cabecalho"],
                                                  arquivo_nome=n, paginas=len(pgs),
                                                  arquivo_sha256="x" * 64)}))
        return ft.importar(nome, b"pdf-falso", usuario, esquema=esquema_pg)
    return _importar


def test_importa_e_grava_as_travessias(gravar, esquema_pg):
    out = gravar(paginas())
    assert out["numero_fatura"] == "12345678901"
    assert out["competencia"] == "2026-08"
    assert out["travessias"] == 15     # 13 de tag + 2 de vale
    assert out["placas"] == 2

    fats = ft.faturas(esquema=esquema_pg)
    assert len(fats) == 1
    assert fats[0]["travessias_tag"] == 13 and fats[0]["travessias_vale"] == 2
    # os totais IMPRESSOS ficam guardados: sem eles, uma travessia perdida numa
    # reimportação futura não teria contra o que ser conferida
    assert fats[0]["total_passagens"] == 345.30
    # 345,30 de pedágio + 29,90 de plano − 10,00 de vale − 15,00 de crédito
    # + 20,00 de encargo. Os cinco somam o total, e é essa soma que a
    # conferência exige — ver `test_a_soma_das_secoes_e_o_total_da_fatura`.
    assert fats[0]["total_fatura"] == 370.20


def test_reimportar_a_MESMA_fatura_substitui_e_nao_duplica(gravar, esquema_pg):
    """A unidade de idempotência é a FATURA, não a travessia.

    A travessia não tem chave natural — o vale imprime pares débito/crédito com
    todos os campos iguais menos o D/C —, e um UNIQUE com coluna anulável não
    restringiria nada (no Postgres NULL nunca colide com NULL). Foi assim que a
    RasterJOR quase duplicou 55 mil linhas.
    """
    a = gravar(paginas())
    b = gravar(paginas())
    assert a["fatura_id"] == b["fatura_id"]
    assert len(ft.faturas(esquema=esquema_pg)) == 1

    from api import pglocal
    n = pglocal.um("SELECT count(*)::int AS c, sum(valor)::float8 AS s "
                   "FROM ped_travessias", esquema=esquema_pg)
    assert n["c"] == 15, "reimportar duplicou travessia"
    assert round(n["s"], 2) == round(345.30 + 30.00 + 20.00, 2)


def test_fatura_que_NAO_FECHA_e_recusada_e_nao_grava_nada(gravar, esquema_pg):
    """Recusa, não aviso: meio milhão importado pela metade produz número
    plausível e errado, que é o defeito mais caro desta casa."""
    quebrada = paginas(DETALHE.replace(LINHA_FALTANTE + "\n", ""))
    with pytest.raises(ft.ImportacaoRecusada) as exc:
        gravar(quebrada)
    assert "não fecha" in str(exc.value)
    assert any("Passagens" in a for a in exc.value.conferencia["achados"])
    # e o banco continua limpo — a recusa acontece ANTES de qualquer escrita
    assert ft.faturas(esquema=esquema_pg) == []


def test_a_tarifa_observada_e_a_MODA_e_nao_a_media(gravar, esquema_pg):
    """Garuva NORTE tem seis travessias de 5 eixos: quatro a R$ 28,50 e duas a
    R$ 1,50.

    A média daria R$ 3,80 por eixo, um valor que NUNCA foi cobrado de ninguém —
    e bastariam duas leituras espúrias para deslocá-la sem nada denunciar. A
    moda devolve R$ 5,70, e o segundo valor mais frequente vira a tarifa
    ANTERIOR de graça.
    """
    gravar(paginas())
    tar = {(t["rodovia"], t["sentido"]): t
           for t in ft.tarifa_observada(esquema=esquema_pg)}
    norte = tar[("BR101", "NORTE")]
    assert norte["n"] == 6
    assert norte["tarifa_eixo"] == 5.70          # 28,50 / 5 eixos, 4 de 6 vezes
    assert norte["tarifa_anterior"] == 0.30      # 1,50 / 5 eixos
    assert round(norte["pct_moda"], 1) == 66.7
    # o SUL tem duas categorias diferentes (6 e 61) e a mesma tarifa por eixo:
    # é a prova, no dado, de que 61 são 7 eixos
    sul = tar[("BR101", "SUL")]
    assert sul["tarifa_eixo"] == 5.70 and sul["eixos"] == [6, 7]


def test_praca_com_poucas_observacoes_sai_como_nd_com_o_percentual(gravar, esquema_pg):
    """Uma travessia só não estabelece tarifa: pode ser categoria errada, eixo
    suspenso ou o próprio dia do reajuste. O número não é afirmado, mas a praça
    continua na lista com o percentual à mostra — esconder seria pior."""
    gravar(paginas())
    so_uma = [t for t in ft.tarifa_observada(esquema=esquema_pg)
              if t["rodovia"] == "BR277"]
    assert len(so_uma) == 1
    assert so_uma[0]["firme"] is False
    assert so_uma[0]["tarifa_eixo"] is None
    assert so_uma[0]["n"] == 1 and so_uma[0]["pct_moda"] == 100.0

    # E a praça de FREE FLOW não aparece em lista nenhuma: a fatura a nomeia
    # sem rodovia + km ("FREE FLOW, BR116, AEROPORTO KM219+165"), então não há
    # como casá-la com o cadastro. Ficar de fora é a resposta certa; entrar com
    # rodovia adivinhada compararia a tarifa contra a praça errada.
    assert not [t for t in ft.tarifa_observada(esquema=esquema_pg)
                if t["rodovia"] == "BR116"]


# ── as rotas ────────────────────────────────────────────────────────────────
#
# O projeto não tem harness de TestClient com autenticação, então aqui se
# garante o que mais quebra: a rota existir e cair na tela certa do RBAC.
# `AuthMiddleware` é fail-closed — rota fora de `ROTA_TELAS` devolve 403 para
# não-administrador, e ninguém percebe até alguém sem perfil de admin abrir.

def test_as_rotas_do_tag_existem_e_caem_na_tela_de_pedagio():
    from api import auth
    import api.main as main

    caminhos = {getattr(r, "path", "") for r in main.app.routes}
    for rota in ("/api/operacao/pedagio/tag",
                 "/api/operacao/pedagio/tag/importar"):
        assert rota in caminhos, f"{rota} não registrada"
        telas = [t for p, t in auth.ROTA_TELAS if rota.startswith(p)]
        assert telas, f"{rota} fora de ROTA_TELAS (403 para não-admin)"
        assert "pedagio" in telas[0]


def test_o_upload_cabe_na_fatura_real():
    """O limite não pode ser menor que uma fatura de verdade.

    As sete lidas vão de 24 a 31 MB. Um teto de 12 MB (o das planilhas de
    antecipação) recusaria TODAS elas com "arquivo acima do limite" — e a
    mensagem mandaria procurar defeito no arquivo, não no teto.
    """
    import api.main as main
    assert main._PED_FATURA_MAX_BYTES >= 40 * 1024 * 1024
