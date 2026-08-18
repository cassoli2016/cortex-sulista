#!/usr/bin/env python3
"""Confere config/antt_coeficientes.yaml contra a calculadora oficial da ANTT.

Rodar SEMPRE que uma resolução nova entrar no YAML. A calculadora oficial
(calculadorafrete.antt.gov.br) é o único oráculo que aceitamos: texto de
resolução transcrito à mão já errou três dos doze tipos de carga — os que têm
linhas ausentes na tabela, cuja lista de valores foi lida como se cobrisse
eixos consecutivos.

    uv run python scripts/validar_coeficientes_antt.py

Consulta só a tabela VIGENTE hoje; vigências passadas não são consultáveis pela
calculadora. Para elas, a guarda é o teste do reajuste percentual na suíte.
"""
from __future__ import annotations

import http.cookiejar
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.antt.piso import calcular_piso  # noqa: E402

URL = "https://calculadorafrete.antt.gov.br/"

# ids do select "Tipo de Carga" da calculadora oficial
IDS = {"granel_solido": 1, "granel_liquido": 2, "frigorificada": 3,
       "conteinerizada": 4, "carga_geral": 5, "neogranel": 6,
       "perigosa_granel_solido": 7, "perigosa_granel_liquido": 8,
       "perigosa_frigorificada": 9, "perigosa_conteinerizada": 10,
       "perigosa_carga_geral": 11, "granel_pressurizada": 12}

# combinações escolhidas para cobrir: eixo mínimo, eixo máximo, eixo que cai na
# regra do imediatamente inferior, e um tipo perigoso.
CASOS = [("carga_geral", 5, 500), ("granel_solido", 6, 1200),
         ("frigorificada", 7, 300), ("perigosa_carga_geral", 9, 850),
         ("conteinerizada", 3, 250), ("conteinerizada", 9, 700),
         ("perigosa_conteinerizada", 5, 180), ("granel_pressurizada", 7, 320),
         ("granel_pressurizada", 2, 150), ("frigorificada", 4, 600)]

_cj = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_op.addheaders = [("User-Agent", "Mozilla/5.0"), ("Referer", URL)]


def _token() -> str:
    html = _op.open(URL, timeout=40).read().decode("utf-8", "ignore")
    return re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html).group(1)


def consultar(tipo: str, eixos: int, km: int) -> float | None:
    for _ in range(4):
        try:
            dados = {"__RequestVerificationToken": _token(),
                     "Filtro.IdTipoCarga": str(IDS[tipo]),
                     "Filtro.NumeroEixos": str(eixos),
                     "Filtro.Distancia": str(km),
                     "Filtro.CargaLotacao": "true",
                     "Filtro.AltoDesempenho": "false",
                     "Filtro.RetornoVazio": "false"}
            req = urllib.request.Request(
                URL, data=urllib.parse.urlencode(dados).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "X-Requested-With": "XMLHttpRequest"})
            html = _op.open(req, timeout=40).read().decode("utf-8", "ignore")
            achados = re.findall(r"R\$\s*([\d.]+,\d{2})",
                                 re.sub(r"<[^>]+>", " ", html))
            if achados:
                return float(achados[0].replace(".", "").replace(",", "."))
        except Exception:  # noqa: BLE001 — rede instável não é falha de dado
            pass
        time.sleep(4)
    return None


def main() -> int:
    hoje = date.today()
    print(f"Conferindo o YAML contra a calculadora oficial (vigência de {hoje})\n")
    falhas = 0
    for tipo, eixos, km in CASOS:
        oficial = consultar(tipo, eixos, km)
        meu = calcular_piso(km=float(km), tipo_carga=tipo, eixos=eixos,
                            quando=hoje)["piso"]
        if oficial is None:
            print(f"?? {tipo:24s} {eixos}e {km:5d}km | calculadora não respondeu")
            falhas += 1
        elif meu is None or abs(oficial - meu) > 0.02:
            print(f"XX {tipo:24s} {eixos}e {km:5d}km | oficial={oficial} "
                  f"| cortex={meu}")
            falhas += 1
        else:
            print(f"OK {tipo:24s} {eixos}e {km:5d}km | {oficial}")
        time.sleep(2)
    print(f"\n{len(CASOS) - falhas}/{len(CASOS)} conferem")
    if falhas:
        print("\nDivergência = o YAML está errado, não a calculadora. "
              "Corrija config/antt_coeficientes.yaml.")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
