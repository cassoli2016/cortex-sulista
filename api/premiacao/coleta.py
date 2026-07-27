"""Coleta mensal da API Gobrax v3 → snapshot em disco (spec §2/§3).

`coletar_mes` recebe um `cliente` já pronto (injeção — ver `api/premiacao/gobrax.py`
e o `FakeCliente` dos testes); esta função NUNCA instancia `ClienteGobrax`, então
não há chamada de rede real aqui nem nos testes.

Fluxo por mês:
  1. `/vehicles` → mapa veículo→motorista atual (`currentDriver`) e lista de TODOS
     os veículos (o `analysis` casa motorista↔veículo por telemetria, não só pelo
     vínculo atual — por isso `vehicles=` leva sempre todos).
  2. `/drivers` → CPF cru por driverId; é mascarado (`_mask_doc`) antes de entrar
     no snapshot — o valor cru nunca é gravado em disco.
  3. `/web/v2/performance/drivers/analysis`, em lotes de 10 motoristas (`_lotes`),
     com `time.sleep(0.3)` ENTRE lotes (não após o último).

O snapshot é dado bruto: motorista sem consumo (`consumptionAverage` 0/None) entra
com `media: None` — quem decide excluir/contar é o cálculo (Task 1), não a coleta.
"""
from __future__ import annotations

import calendar
import json
import time
from datetime import datetime
from pathlib import Path

from api.queries import _mask_doc

ROOT = Path(__file__).resolve().parent.parent.parent
SNAP_DIR = ROOT / "data" / "premiacao"

CHUNK = 10

MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _label_mes(mes: str) -> str:
    y, m = mes.split("-")
    return f"{MESES[int(m)]} / {y}"


def _lotes(seq, n=10):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _period(mes: str, agora: datetime) -> tuple[str, str, bool]:
    """(periodStart, periodEnd, parcial) em ISO UTC 'Z' — mês corrente é parcial e
    termina em `agora`; mês fechado termina no último dia às 23:59:59Z."""
    y, m = map(int, mes.split("-"))
    start = f"{y:04d}-{m:02d}-01T00:00:00Z"
    if mes == agora.strftime("%Y-%m"):
        end = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
        return start, end, True
    last = calendar.monthrange(y, m)[1]
    end = f"{y:04d}-{m:02d}-{last:02d}T23:59:59Z"
    return start, end, False


def coletar_mes(cliente, mes: str, customer: int = 1, agora=None) -> dict:
    agora = agora or datetime.now()
    period_start, period_end, parcial = _period(mes, agora)

    resp_vehicles = cliente.get("/vehicles", {"customers": customer, "operation": "true"})
    clientes = (resp_vehicles or {}).get("customers") or [{}]
    veiculos = (clientes[0] or {}).get("vehicles") or []

    todos_ids: list[int] = []
    nomes: dict[int, str] = {}
    veic_por_motorista: dict[int, list[dict]] = {}
    com_motorista = 0
    for v in veiculos:
        vid = v.get("id")
        if vid is not None:
            todos_ids.append(vid)
        modelo = v.get("truckModel") or v.get("model") or v.get("brand") or ""
        cd = v.get("currentDriver") or {}
        did = cd.get("driverId")
        if did is not None:
            did = int(did)
            com_motorista += 1
            nomes[did] = cd.get("driverName", "")
            veic_por_motorista.setdefault(did, []).append(
                {"plate": v.get("plate", ""), "model": modelo})

    resp_drivers = cliente.get("/drivers", {"customers": customer})
    docs = {int(d["id"]): (d.get("documentNumber") or "")
            for d in (resp_drivers or {}).get("drivers") or [] if d.get("id") is not None}

    driver_ids = list(nomes.keys())
    vehicles_param = ",".join(str(i) for i in todos_ids)

    performances: dict[int, dict] = {}
    lotes = list(_lotes(driver_ids, CHUNK))
    for i, lote in enumerate(lotes):
        params = {
            "drivers": ",".join(str(i) for i in lote),
            "vehicles": vehicles_param,
            "startDate": period_start,
            "endDate": period_end,
        }
        resp = cliente.get("/web/v2/performance/drivers/analysis", params)
        for p in ((resp or {}).get("data") or {}).get("performances") or []:
            did = p.get("driverId")
            if did is not None:
                performances[int(did)] = p
        if i < len(lotes) - 1:
            time.sleep(0.3)

    drivers: list[dict] = []
    for did in driver_ids:
        p = performances.get(did, {})
        stats = p.get("stats") or {}
        scores = p.get("scores") or {}
        consumo = stats.get("consumptionAverage")
        media = float(consumo) if consumo else None
        drivers.append({
            "driverId": did,
            "driverName": nomes.get(did, ""),
            "documento": _mask_doc(docs.get(did)),
            "vehicles": veic_por_motorista.get(did, []),
            "nota": scores.get("generalScore"),
            "media": media,
            "km": stats.get("totalMileage"),
            "indicators": {
                "scores": scores,
                "percentages": p.get("percentages") or {},
                "extra": {k: v for k, v in stats.items()
                          if k not in ("totalMileage", "consumptionAverage")},
            },
        })

    return {
        "source": "gobrax-v3",
        "customerId": customer,
        "month": mes,
        "periodStart": period_start,
        "periodEnd": period_end,
        "coletado_em": agora.strftime("%Y-%m-%d %H:%M"),
        "parcial": parcial,
        "frota_telemetria": {"veiculos": len(veiculos), "com_motorista": com_motorista},
        "drivers": drivers,
    }


def gravar_snapshot(snap: dict, dir_path=None) -> Path:
    dir_path = Path(dir_path or SNAP_DIR)
    dir_path.mkdir(parents=True, exist_ok=True)
    caminho = dir_path / f"premiacao-{snap['month']}.json"
    caminho.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    _reescrever_index(dir_path)
    return caminho


def _reescrever_index(dir_path: Path) -> None:
    index = []
    for arq in sorted(dir_path.glob("premiacao-*.json")):
        try:
            snap = json.loads(arq.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        mes = snap.get("month")
        if not mes:
            continue
        index.append({
            "month": mes,
            "label": _label_mes(mes),
            "drivers": len(snap.get("drivers") or []),
            "parcial": bool(snap.get("parcial")),
        })
    index.sort(key=lambda i: i["month"], reverse=True)
    (dir_path / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def ler_snapshot(mes: str, dir_path=None) -> dict | None:
    dir_path = Path(dir_path or SNAP_DIR)
    caminho = dir_path / f"premiacao-{mes}.json"
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def ler_index(dir_path=None) -> list[dict]:
    dir_path = Path(dir_path or SNAP_DIR)
    caminho = dir_path / "index.json"
    if not caminho.exists():
        return []
    return json.loads(caminho.read_text(encoding="utf-8"))
