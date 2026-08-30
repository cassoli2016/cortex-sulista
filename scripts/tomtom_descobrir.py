# -*- coding: utf-8 -*-
"""Pergunta à TomTom o que a chave desta casa realmente libera.

POR QUE ISTO EXISTE
===================
A documentação de fornecedor envelhece e o comentário no código envelhece mais
rápido. Esta casa já tomou uma decisão errada por causa disso: o módulo da
Gobrax dizia "~17 s por chamada, varrer a frota seriam mais de 20 minutos", e
por isso a coleta em lote nunca foi feita — medido, era **0,79 s por placa**.
Vinte vezes errado, escrito com confiança, num comentário.

Então antes de escrever qualquer regra sobre limite, ETA ou modo caminhão,
este script CHAMA e imprime o que voltou. Três coisas em especial:

  - **o limite**, que só aparece nos CABEÇALHOS da resposta;
  - **se `travelMode=truck` é aceito** nesta conta — muda a rota de verdade
    (restrição de via, altura, peso), não só o tempo;
  - **se a chave funciona a partir do SERVIDOR** — a do mapa costuma estar
    restrita por domínio, e restrita ela devolve 403 aqui.

TUDO AQUI É LEITURA. Nenhum endpoint tocado muda estado do lado deles. A regra
da casa nasceu de um susto: `/api/v2/drivers` da Gobrax foi sondado achando que
era consulta e era ESCRITA — só não criou um motorista porque um campo
obrigatório faltava.

A CHAVE NUNCA É IMPRESSA. Toda saída passa pelo sanitizador do cliente.

Uso:
    uv run --no-sync python scripts/tomtom_descobrir.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db as _db  # noqa: E402,F401  (importa para carregar o .env)
from api import tls as _tls  # noqa: E402
from api.tomtom import cliente, transito  # noqa: E402

# Um ponto na BR-101 em Joinville e outro em Curitiba: é onde a operação anda,
# e trecho real responde diferente de um ponto no meio do nada.
JOINVILLE = (-26.3044, -48.8487)
CURITIBA = (-25.4284, -49.2733)


def _cab(r) -> dict:
    """Cabeçalhos que interessam: é neles que mora o limite."""
    fora = {}
    for k, v in (r.headers or {}).items():
        kl = k.lower()
        if any(t in kl for t in ("ratelimit", "rate-limit", "quota", "retry")):
            fora[k] = v
    return fora


def _bruto(caminho: str, params: dict) -> tuple[int, dict, str]:
    """Chama e devolve (status, cabeçalhos-de-limite, corpo). Sanitizado."""
    k = cliente.chave_servidor()
    url = "%s%s?%s" % (cliente.BASE, caminho,
                       urllib.parse.urlencode({**params, "key": k}))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cliente.TIMEOUT,
                                    context=_tls.contexto()) as r:
            return r.status, _cab(r), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        corpo = ""
        try:
            corpo = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return exc.code, _cab(exc), cliente._sanitizar(corpo)
    except Exception as exc:  # noqa: BLE001
        # O MOTIVO IMPORTA. A primeira versao devolvia so o nome da
        # excecao, e "URLError" nao distingue DNS de TLS de firewall --
        # foram tres diagnosticos ate imprimir o motivo e descobrir que
        # era a raiz da CA faltando. Passa pelo sanitizador porque o
        # motivo pode carregar a URL, e a URL e a credencial.
        motivo = cliente._sanitizar(getattr(exc, "reason", "") or exc)
        return 0, {}, "falhou: %s — %s" % (type(exc).__name__, motivo)


def secao(titulo: str) -> None:
    print("\n" + "═" * 68)
    print(titulo)
    print("═" * 68)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    if not cliente.configurado():
        print("Chave da TomTom não configurada.")
        print("Coloque em Gestão › Integrações › TomTom — o valor vai para o")
        print("cofre (data/credenciais.json), com ACL restrita, e NÃO para o")
        print("git nem para esta saída.")
        return 2

    print("chave da coleta: configurada", end="")
    if cliente.usando_a_chave_do_mapa():
        print("  ⚠  usando a do MAPA (pode estar restrita por domínio)")
    else:
        print("  (chave própria de servidor)")

    # ── 1. fluxo num ponto ──────────────────────────────────────────────────
    secao("1. Fluxo no trecho (traffic/services/4/flowSegmentData)")
    t = time.time()
    st, lim, corpo = _bruto(
        "/traffic/services/4/flowSegmentData/absolute/10/json",
        {"point": "%s,%s" % JOINVILLE, "unit": "KMPH"})
    print("HTTP %s em %.2fs" % (st, time.time() - t))
    if lim:
        print("limite (cabeçalhos):", lim)
    if st == 200:
        d = json.loads(corpo)
        print("campos devolvidos:", sorted((d.get("flowSegmentData") or {}).keys()))
        print("leitura da casa:", transito.do_payload(d))
    else:
        print(corpo[:400])

    # ── 2. incidentes numa caixa ────────────────────────────────────────────
    secao("2. Incidentes na área (traffic/services/5/incidentDetails)")
    t = time.time()
    st, lim, corpo = _bruto("/traffic/services/5/incidentDetails", {
        "bbox": "-49.4,-26.5,-48.7,-25.3",
        "fields": "{incidents{type,properties{iconCategory,magnitudeOfDelay,"
                  "events{description},delay,from,to,roadNumbers}}}",
        "language": cliente.IDIOMA, "timeValidityFilter": "present"})
    print("HTTP %s em %.2fs" % (st, time.time() - t))
    if lim:
        print("limite (cabeçalhos):", lim)
    if st == 200:
        d = json.loads(corpo)
        inc = d.get("incidents") or []
        print("incidentes na caixa Joinville–Curitiba:", len(inc))
        if inc:
            print("exemplo:", json.dumps(inc[0], ensure_ascii=False)[:400])
            cats = {}
            for i in inc:
                c = (i.get("properties") or {}).get("iconCategory")
                cats[c] = cats.get(c, 0) + 1
            print("por categoria:", cats)
    else:
        print(corpo[:400])

    # ── 3. rota com trânsito, carro e caminhão ──────────────────────────────
    for modo, extra in (("carro", {}), ("caminhão", {"travelMode": "truck"})):
        secao("3. ETA %s (routing/1/calculateRoute) — Joinville → Curitiba" % modo)
        t = time.time()
        st, lim, corpo = _bruto(
            "/routing/1/calculateRoute/%s,%s:%s,%s/json"
            % (JOINVILLE[0], JOINVILLE[1], CURITIBA[0], CURITIBA[1]),
            {"traffic": "true", "routeType": "fastest",
             "computeTravelTimeFor": "all", **extra})
        print("HTTP %s em %.2fs" % (st, time.time() - t))
        if lim:
            print("limite (cabeçalhos):", lim)
        if st == 200:
            d = json.loads(corpo)
            r = (d.get("routes") or [{}])[0]
            s = r.get("summary") or {}
            print("resumo:", {k: s.get(k) for k in (
                "lengthInMeters", "travelTimeInSeconds",
                "trafficDelayInSeconds", "noTrafficTravelTimeInSeconds",
                "historicTrafficTravelTimeInSeconds", "liveTrafficIncidentsTravelTimeInSeconds",
                "departureTime", "arrivalTime") if k in s})
        else:
            print(corpo[:400])
            if modo == "caminhão":
                print("→ modo caminhão indisponível nesta conta: a rota de "
                      "carro serve de aproximação, mas ignora restrição de "
                      "via, altura e peso — e isso precisa estar DITO na tela.")

    secao("Resumo")
    print("Anote acima: o limite de chamadas (cabeçalhos), se o modo caminhão")
    print("foi aceito e o tempo de resposta. São esses três que decidem se dá")
    print("para varrer a frota inteira ou só as rotas principais — e é a")
    print("decisão que o comentário errado da Gobrax atrasou por semanas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
