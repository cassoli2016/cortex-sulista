"""Coleta mensal da API Gobrax v3 → snapshot em disco (spec §2/§3).

`coletar_mes` recebe um `cliente` já pronto (injeção — ver `api/premiacao/gobrax.py`
e o `FakeCliente` dos testes); esta função NUNCA instancia `ClienteGobrax`, então
não há chamada de rede real aqui nem nos testes.

Fluxo por mês:
  1. `/vehicles` → mapa veículo→motorista atual (`currentDriver`) e lista de TODOS
     os veículos (o `analysis` casa motorista↔veículo por telemetria, não só pelo
     vínculo atual — por isso `vehicles=` leva sempre todos).
  2. `/drivers` → TODOS os motoristas cadastrados do cliente (nome + CPF, mascarado
     com `_mask_doc` antes de entrar no snapshot — o valor cru nunca vai a disco).
  3. `/web/v2/performance/drivers/analysis` para TODOS os cadastrados, em lotes de
     10 (`_lotes`), com `time.sleep(0.3)` ENTRE lotes (não após o último).

Consultar só quem tem `currentDriver` perdia motorista: os vínculos do piloto mudam
de dia para dia, e quem dirigiu no começo do mês sem estar vinculado AGORA sumia do
ranking (aconteceu de verdade: a coleta trouxe 3 motoristas num mês em que 5 tinham
rodado). O `analysis` casa por telemetria, então consultar todos resolve.

O snapshot guarda só motorista com ATIVIDADE no mês (media ou km > 0) — com ~86
cadastrados e um piloto pequeno, guardar todo mundo viraria ruído. Motorista com km
mas sem média entra com `media: None` (o cálculo o exclui do ranking e conta).
"""
from __future__ import annotations

import base64
import calendar
import io
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
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


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _norm(nome: str) -> str:
    """Normaliza nome para casar /drivers ("3781 - ROBSON ...") com o
    exportDriverHistory ("Luis antonio rodrigues"): tira o prefixo numérico,
    põe em maiúsculas e colapsa espaços."""
    s = re.sub(r"^\s*\d+\s*-\s*", "", nome or "")
    return " ".join(s.strip().upper().split())


def _xlsx_rows(b64: str) -> list[list[str]]:
    """Lê a 1ª planilha de um XLSX (base64) só com a stdlib — o
    exportDriverHistory devolve {"XLSX": <base64>}."""
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(b64)))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        t = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in t.findall(f"{_XLSX_NS}si"):
            shared.append("".join(x.text or "" for x in si.iter(f"{_XLSX_NS}t")))
    t = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in t.iter(f"{_XLSX_NS}row"):
        cells: list[str] = []
        for c in row.findall(f"{_XLSX_NS}c"):
            v = c.find(f"{_XLSX_NS}v")
            val = ""
            if v is not None and v.text is not None:
                val = shared[int(v.text)] if c.get("t") == "s" else v.text
            cells.append(val)
        rows.append(cells)
    return rows


def fetch_bonds(cliente, vinfo: dict[int, dict]) -> dict[str, list[dict]]:
    """Histórico de vínculos motorista↔veículo (`/vehicles/exportDriverHistory`,
    um export por veículo, 6 em paralelo como no coletor validado do MVP).

    Devolve {nome_normalizado: [{plate, model, ini, fim}]} — o export só traz o
    NOME do motorista (formato "Luis antonio rodrigues", sem código), então o
    casamento com /drivers é por `_norm`. Colunas confirmadas em produção:
    Motorista · Data inicial · Data final · Vínculo feito por · Status.
    Um export que falhe não derruba a coleta (vínculo é enriquecimento; a média
    vem do analysis por telemetria de qualquer jeito)."""
    def um(item):
        vid, info = item
        out = []
        try:
            resp = cliente.get("/vehicles/exportDriverHistory", {"vehicleId": vid})
            b64 = resp.get("XLSX") if isinstance(resp, dict) else None
            if not b64:
                return out
            for r in _xlsx_rows(b64)[1:]:  # pula o cabeçalho
                if len(r) >= 3 and r[0]:
                    out.append({"driver": _norm(r[0]), "plate": info.get("plate", ""),
                                "model": info.get("model", ""),
                                "ini": r[1] or "", "fim": r[2] or ""})
        except Exception:  # noqa: BLE001 -- enriquecimento, nunca fatal
            pass
        return out

    bonds: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(um, list(vinfo.items())):
            for b in res:
                bonds.setdefault(b["driver"], []).append(b)
    return bonds


def vinculos_no_periodo(bonds: dict[str, list[dict]], nome: str,
                        start_iso: str, end_iso: str) -> list[dict]:
    """Vínculos do motorista que SOBREPÕEM o período — cada um vira
    {plate, model, vinculo_de, vinculo_ate} (vinculo_ate vazio = em aberto).
    Datas do export são 'YYYY-MM-DD HH:MM:SS' (comparação lexicográfica ok)."""
    ms = start_iso.replace("T", " ").replace("Z", "")
    me = end_iso.replace("T", " ").replace("Z", "")
    out: list[dict] = []
    vistos: set[tuple] = set()
    for b in bonds.get(_norm(nome), []):
        fim = b["fim"] or "9999-12-31 23:59:59"
        if b["ini"] <= me and fim >= ms:
            chave = (b["plate"], b["ini"], b["fim"])
            if chave in vistos:
                continue
            vistos.add(chave)
            out.append({"plate": b["plate"], "model": b["model"],
                        "vinculo_de": b["ini"], "vinculo_ate": b["fim"]})
    out.sort(key=lambda v: v["vinculo_de"])
    return out


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


def coletar_mes(cliente, mes: str, customer: int = 1, agora=None,
                bonds: dict[str, list[dict]] | None = None) -> dict:
    agora = agora or datetime.now()
    period_start, period_end, parcial = _period(mes, agora)

    resp_vehicles = cliente.get("/vehicles", {"customers": customer, "operation": "true"})
    if not isinstance(resp_vehicles, dict) or resp_vehicles.get("customers") is None:
        raise ValueError(
            "Resposta da Gobrax sem a estrutura esperada em /vehicles (campo 'customers' ausente).")
    clientes = resp_vehicles["customers"]
    primeiro = clientes[0] if clientes else {}
    veiculos = (primeiro or {}).get("vehicles") or []

    todos_ids: list[int] = []
    vinfo: dict[int, dict] = {}
    veic_atual: dict[int, list[dict]] = {}   # fallback quando o histórico não casa
    nomes_atual: dict[int, str] = {}
    for v in veiculos:
        vid = v.get("id")
        modelo = v.get("truckModel") or v.get("model") or v.get("brand") or ""
        if vid is not None:
            todos_ids.append(vid)
            vinfo[vid] = {"plate": v.get("plate", ""), "model": modelo}
        cd = v.get("currentDriver") or {}
        did = cd.get("driverId")
        if did is not None:
            did = int(did)
            nomes_atual[did] = cd.get("driverName", "")
            veic_atual.setdefault(did, []).append(
                {"plate": v.get("plate", ""), "model": modelo,
                 "vinculo_de": str(cd.get("startDate") or ""), "vinculo_ate": ""})

    resp_drivers = cliente.get("/drivers", {"customers": customer})
    if not isinstance(resp_drivers, dict) or resp_drivers.get("drivers") is None:
        raise ValueError(
            "Resposta da Gobrax sem a estrutura esperada em /drivers (campo 'drivers' ausente).")
    docs: dict[int, str] = {}
    nomes: dict[int, str] = {}
    for d in resp_drivers["drivers"]:
        if d.get("id") is None:
            continue
        did = int(d["id"])
        docs[did] = d.get("documentNumber") or ""
        nomes[did] = nomes_atual.get(did) or d.get("name") or ""

    # TODOS os cadastrados: consultar só quem tem currentDriver perdia motorista
    # (os vínculos do piloto mudam de dia para dia — chegou a haver 0 vínculos
    # com 98 veículos na plataforma). O analysis casa por telemetria.
    driver_ids = sorted(nomes.keys())
    vehicles_param = ",".join(str(i) for i in todos_ids)

    if bonds is None:
        bonds = fetch_bonds(cliente, vinfo)

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
        if not isinstance(resp, dict) or resp.get("data") is None:
            raise ValueError(
                "Resposta da Gobrax sem a estrutura esperada em "
                "/web/v2/performance/drivers/analysis (campo 'data' ausente).")
        for p in (resp["data"] or {}).get("performances") or []:
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
        km = stats.get("totalMileage")
        # só entra quem teve ATIVIDADE no mês — com ~86 cadastrados e um piloto
        # pequeno, guardar todo mundo viraria ruído; km sem média fica (o
        # cálculo o exclui do ranking e conta em sem_media)
        if not media and not km:
            continue
        drivers.append({
            "driverId": did,
            "driverName": nomes.get(did, ""),
            "documento": _mask_doc(docs.get(did)),
            "vehicles": (vinculos_no_periodo(bonds, nomes.get(did, ""),
                                             period_start, period_end)
                         or veic_atual.get(did, [])),
            "nota": scores.get("generalScore"),
            "media": media,
            "km": km,
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
        "frota_telemetria": {"veiculos": len(veiculos), "com_motorista": len(drivers),
                             "cadastrados": len(nomes)},
        "drivers": drivers,
    }


def _escrever_atomico(caminho: Path, conteudo: str) -> None:
    """Grava via arquivo temporário no MESMO diretório + `os.replace` (M1):
    `os.replace` é atômico em POSIX e NTFS, então um leitor concorrente
    (`ler_snapshot`/`ler_index`, que não pegam lock nenhum) nunca vê um
    arquivo truncado a meio de escrita — antes o `write_text` direto causava
    `JSONDecodeError` real sob leitura concorrente (medido na revisão final)."""
    dir_path = caminho.parent
    fd, tmp_nome = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=dir_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(conteudo)
        os.replace(tmp_nome, caminho)
    except BaseException:
        Path(tmp_nome).unlink(missing_ok=True)
        raise


def gravar_snapshot(snap: dict, dir_path=None) -> Path:
    dir_path = Path(dir_path or SNAP_DIR)
    dir_path.mkdir(parents=True, exist_ok=True)
    caminho = dir_path / f"premiacao-{snap['month']}.json"
    _escrever_atomico(caminho, json.dumps(snap, ensure_ascii=False, indent=2))
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
    _escrever_atomico(dir_path / "index.json", json.dumps(index, ensure_ascii=False, indent=2))


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
