"""CÓRTEX — saúde do servidor (infra desta máquina).

Coleta métricas do host (CPU, memória, disco, rede, uptime) e o estado dos
serviços do CÓRTEX (API, banco ERP, túnel Cloudflare, Ollama) e das tarefas
agendadas. Área administrativa — a rota vive sob /api/gestao (só admin).

Tudo é best-effort: cada bloco é isolado em try/except para que a falha de uma
métrica (ex.: psutil ausente) não derrube o painel inteiro.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

from . import db

log = logging.getLogger("cortex.servidor")

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None

# Tarefas agendadas do CÓRTEX nesta máquina (README / registrar-tarefas.ps1).
_TAREFAS = ["Cortex Sulista - API", "Cortex Sulista - AutoDeploy", "Cortex Sulista - Tunnel"]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def _host() -> dict:
    boot = psutil.boot_time() if psutil else None
    return {
        "hostname": socket.gethostname(),
        "so": platform.system(),
        "so_versao": platform.version(),
        "plataforma": platform.platform(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "boot": _iso(boot) if boot else None,
        "uptime_seg": int(time.time() - boot) if boot else None,
        "processos": len(psutil.pids()) if psutil else None,
    }


def _cpu() -> dict:
    if not psutil:
        return {}
    # uma amostra curta com percpu já serve de base para o total (média)
    por_nucleo = psutil.cpu_percent(interval=0.3, percpu=True)
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.current) if f else None
    except Exception:  # noqa: BLE001
        pass
    return {
        "logico": psutil.cpu_count(logical=True),
        "fisico": psutil.cpu_count(logical=False),
        "percent": round(sum(por_nucleo) / len(por_nucleo), 1) if por_nucleo else None,
        "por_nucleo": [round(x, 1) for x in por_nucleo],
        "freq_mhz": freq,
    }


def _memoria() -> dict:
    if not psutil:
        return {}
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "ram": {"total": vm.total, "usado": vm.total - vm.available,
                "disponivel": vm.available, "percent": vm.percent},
        "swap": {"total": sw.total, "usado": sw.used, "percent": sw.percent},
    }


def _discos() -> list[dict]:
    if not psutil:
        return []
    out = []
    for p in psutil.disk_partitions(all=False):
        # ignora unidades removíveis/CD vazias que estouram exceção
        if "cdrom" in (p.opts or "") or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append({
            "montagem": p.mountpoint, "dispositivo": p.device, "fs": p.fstype,
            "total": u.total, "usado": u.used, "livre": u.free, "percent": u.percent,
        })
    return out


def _num(x: str):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _gpu() -> list[dict]:
    """GPUs via nvidia-smi (best-effort). Vazio se nvidia-smi ausente ou sem GPU
    NVIDIA (ex.: placa AMD/Intel ou host sem GPU) — nunca derruba o painel."""
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
             "temperature.gpu,power.draw,power.limit",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6)
        if r.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    out: list[dict] = []
    for linha in r.stdout.strip().splitlines():
        p = [c.strip() for c in linha.split(",")]
        if len(p) < 7:
            continue
        mu, mt = _num(p[2]), _num(p[3])
        out.append({
            "nome": p[0],
            "util_percent": _num(p[1]),
            "mem_usado_mb": mu, "mem_total_mb": mt,
            "mem_percent": round(100 * mu / mt, 1) if (mu is not None and mt) else None,
            "temp_c": _num(p[4]),
            "potencia_w": _num(p[5]), "potencia_limite_w": _num(p[6]),
        })
    return out


def _rede() -> dict:
    if not psutil:
        return {}
    io = psutil.net_io_counters()
    return {"enviado": io.bytes_sent, "recebido": io.bytes_recv,
            "pac_enviados": io.packets_sent, "pac_recebidos": io.packets_recv}


def _processo_cloudflared() -> int:
    if not psutil:
        return 0
    n = 0
    for pr in psutil.process_iter(["name"]):
        try:
            if (pr.info["name"] or "").lower().startswith("cloudflared"):
                n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return n


def _servicos() -> list[dict]:
    servicos: list[dict] = []

    # API (este próprio processo)
    api = {"nome": "API (uvicorn)", "status": "ok", "detalhe": "porta 8010"}
    if psutil:
        try:
            p = psutil.Process(os.getpid())
            rss = p.memory_info().rss
            api["detalhe"] = f"porta 8010 · PID {p.pid} · RAM {rss // (1024 * 1024)} MB"
        except Exception:  # noqa: BLE001
            pass
    servicos.append(api)

    # Banco ERP (latência do SELECT 1)
    t0 = time.perf_counter()
    try:
        db.query("SELECT 1 AS ok")
        ms = round((time.perf_counter() - t0) * 1000)
        servicos.append({"nome": "Banco ERP (PostgreSQL)", "status": "ok",
                         "detalhe": f"conectado · {ms} ms"})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Banco ERP (PostgreSQL)", "status": "erro",
                         "detalhe": "sem conexão"})
        log.warning("saude: banco inacessível: %s", exc)

    # Túnel Cloudflare
    n = _processo_cloudflared()
    servicos.append({
        "nome": "Túnel Cloudflare", "status": "ok" if n else "alerta",
        "detalhe": f"{n} conector(es) ativo(s)" if n else "cloudflared não está rodando"})

    # Copiloto (Ollama local) — best-effort
    try:
        from . import copiloto
        st = copiloto.ollama_status()
        servicos.append({
            "nome": "Copiloto (Ollama)",
            "status": "ok" if st.get("ok") else "info",
            "detalhe": f"modelo {st['modelo']}" if st.get("ok") else "Ollama local indisponível"})
    except Exception:  # noqa: BLE001
        servicos.append({"nome": "Copiloto (Ollama)", "status": "info",
                         "detalhe": "indisponível"})

    return servicos


def _tarefas() -> list[dict]:
    """Estado + última/próxima execução das tarefas agendadas do CÓRTEX.

    Usa Get-ScheduledTaskInfo (dados estruturados, independentes de idioma) em
    vez de parsear o texto localizado do schtasks. Best-effort: sem PowerShell
    (ex.: dev no Mac) devolve só os nomes."""
    nomes = ",".join("'" + t.replace("'", "''") + "'" for t in _TAREFAS)
    ps = (
        "$ns=@(" + nomes + ");"
        "$out=foreach($n in $ns){try{"
        "$t=Get-ScheduledTask -TaskName $n -ErrorAction Stop;$i=$t|Get-ScheduledTaskInfo;"
        "[pscustomobject]@{nome=$n;estado=[string]$t.State;"
        "ultima=if($i.LastRunTime -and $i.LastRunTime.Year -gt 1999){$i.LastRunTime.ToString('o')}else{''};"
        "proxima=if($i.NextRunTime){$i.NextRunTime.ToString('o')}else{''};"
        "resultado=$i.LastTaskResult}"
        "}catch{[pscustomobject]@{nome=$n;estado='nao_registrada';ultima='';proxima='';resultado=$null}}};"
        "$out|ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout) if r.stdout.strip() else []
        if isinstance(data, dict):
            data = [data]
        return [{"nome": d.get("nome"), "estado": d.get("estado") or "desconhecido",
                 "ultima": d.get("ultima") or None, "proxima": d.get("proxima") or None,
                 "resultado": d.get("resultado")} for d in data]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return [{"nome": n, "estado": "indisponivel", "ultima": None, "proxima": None}
                for n in _TAREFAS]


def coletar() -> dict:
    """Snapshot completo da saúde do servidor. Nunca levanta exceção."""
    dados: dict = {"coletado_em": _iso(time.time()), "psutil": bool(psutil)}
    for chave, fn in (("host", _host), ("cpu", _cpu), ("memoria", _memoria),
                      ("rede", _rede)):
        try:
            dados[chave] = fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("saude: bloco %s falhou: %s", chave, exc)
            dados[chave] = {}
    try:
        dados["discos"] = _discos()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: discos falhou: %s", exc)
        dados["discos"] = []
    try:
        dados["gpus"] = _gpu()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: gpu falhou: %s", exc)
        dados["gpus"] = []
    try:
        dados["servicos"] = _servicos()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: servicos falhou: %s", exc)
        dados["servicos"] = []
    try:
        dados["tarefas"] = _tarefas()
    except Exception as exc:  # noqa: BLE001
        dados["tarefas"] = []
    return dados
