"""Coleta mensal da API Gobrax v3 → snapshot em disco (spec §2/§3).

`coletar_mes` recebe um `cliente` já pronto (injeção — ver `api/gobrax/cliente.py`
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


class ColetaVazia(Exception):
    """A coleta não trouxe motorista nenhum. Nunca vira snapshot: já aconteceu
    de uma coleta vazia sobrescrever um mês inteiro de dados bons."""


def coletar_mes(mes: str, cliente=None, agora=None, coletor=None) -> dict:
    """Snapshot do mês a partir do driversOverview.

    Substitui a coleta por login (Kratos + /vehicles + exportDriverHistory),
    que dependia de ~98 exports XLSX e batia em rate limit. A API pública
    devolve todos os motoristas numa chamada.
    """
    from api.gobrax import overview

    agora = agora or datetime.now()
    linhas = (coletor or overview.coletar)(mes, cliente=cliente)
    if not linhas:
        raise ColetaVazia(f"driversOverview não trouxe motoristas para {mes}")
    return {
        "month": mes,
        "source": "gobrax-api-overview",
        "regra_fonte": "nota_km",
        "coletado_em": agora.isoformat(timespec="seconds"),
        "parcial": mes == agora.strftime("%Y-%m"),
        "drivers": linhas,
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
