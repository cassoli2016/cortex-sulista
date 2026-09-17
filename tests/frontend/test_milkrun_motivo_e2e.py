"""O MOTIVO de uma coleta sem rastro, na linha da parada (17/09/2026).

A operacao marca a parada como coletada no ERP e o rastreamento nao confirma:
a tela mostra "coletado" SEM horas, porque nao mostra nada digitado (decisao de
quem opera, mantida no mesmo dia). Faltava dizer POR QUE — na MWM eram 92 de
493 coletadas em 30 dias, e o conserto de cada uma e diferente (coordenada do
fornecedor, agendamento, placa da solicitacao). O motivo vem pronto do
servidor (`deteccao.motivo_sem_rastro`); aqui se confere que ele CHEGA a linha
certa, com a explicacao no tooltip, e que nenhuma hora aparece junto.
"""
from __future__ import annotations

import json
import os

USUARIO = {"nome": "T", "email": "t@s.local", "admin": True,
           "perfil": "Administrador", "telas": []}

MOTIVO = {"codigo": "coordenada", "texto": "a 520 m do ponto",
          "detalhe": "O mais perto que chegou foi 520 m do ponto do cadastro "
                     "(a cerca tem 300 m)."}


def _pt(seq, estado, **k):
    base = {"coleta": 901, "sequencia": seq, "previsto": "2026-09-10T08:00:00",
            "placa": "ABC1D23", "ponto": f"FORN {seq}", "cidade": "SAO PAULO",
            "uf": "SP", "lat": -23.55, "lng": -46.63, "destino": None,
            "chegada": None, "saida": None, "permanencia_min": None,
            "distancia_m": None, "visitas_no_dia": 0, "coletada": False,
            "frustrada": False, "motivo": None, "estado": estado,
            "rotulo": estado, "atraso_min": None}
    return {**base, **k}


PONTOS = [
    _pt(1, "concluido", coletada=True, chegada="2026-09-10T08:05:00",
        saida="2026-09-10T08:40:00", permanencia_min=35, distancia_m=40,
        pontualidade="no prazo", atraso_min=5),
    _pt(2, "concluido", coletada=True, rotulo="coletado (sem rastro)",
        motivo=MOTIVO),
    _pt(3, "aguardando"),
]
CORPO = {
    "kpis": {"pontos": 3, "concluidos": 2, "pendentes": 1},
    "por_data": [{"data": "2026-09-10", "solicitacoes": 1, "pontos": 3}],
    "coletas": [{"coleta": 901, "situacao": "em andamento", "cancelada": False,
                 "placa": "ABC1D23", "motorista": None, "pontos": PONTOS,
                 "total": 3, "concluidos": 2, "frustrados": 0, "pendentes": 1,
                 "no_local": 0, "primeiro": "2026-09-10T08:00:00",
                 "ultimo": "2026-09-10T08:00:00", "data": "2026-09-10",
                 "paradas_total": 3, "milkrun": True, "mesmo_local": False}],
    "veiculos_pos": {}, "fornecedores": [], "tipos": [],
}

LINHAS = """() => [...document.querySelectorAll('#milk-g-901 tbody tr')].map(tr => {
  const td = tr.querySelectorAll('td');
  const m = tr.querySelector('.milk-motivo');
  return {chegada: td[3].textContent.trim(), saida: td[4].textContent.trim(),
          situacao: td[7].textContent.replace(/\s+/g, ' ').trim(),
          motivo: m ? m.textContent.trim() : null,
          dica: m ? m.getAttribute('title') : null};
})"""


def test_o_motivo_vai_na_linha_da_coletada_sem_rastro_e_so_nela(pagina):
    pg, base = pagina

    def rota(r):
        u = r.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            CORPO if "/api/operacao/milkrun" in u else {})
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(base + "/static/index.html#milkrun")
    pg.wait_for_selector("#milk-g-901 tbody tr", state="attached", timeout=20000)
    pg.evaluate("() => milkToggle(901)")
    linhas = pg.evaluate(LINHAS)
    assert len(linhas) == 3, linhas

    rastreada, sem_rastro, pendente = linhas
    assert rastreada["motivo"] is None and rastreada["chegada"].startswith("08:05")
    assert pendente["motivo"] is None

    assert sem_rastro["motivo"] == "a 520 m do ponto"
    assert "cadastro" in sem_rastro["dica"]
    assert "coletado" in sem_rastro["situacao"]
    # e NENHUMA hora: a tela nao mostra digitado, nem para explicar
    assert sem_rastro["chegada"] == "—" and sem_rastro["saida"] == "—", sem_rastro

    foto = os.environ.get("FOTO_MILK")
    if foto:
        pg.locator("#milk-g-901").screenshot(path=foto)
