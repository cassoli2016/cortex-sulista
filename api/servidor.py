"""CÓRTEX — saúde do servidor (infra desta máquina).

Coleta métricas do host (CPU, memória, disco, rede, uptime) e o estado dos
serviços do CÓRTEX (API, banco ERP, túnel Cloudflare, Ollama) e das tarefas
agendadas. Área administrativa — a rota vive sob /api/gestao (só admin).

Tudo é best-effort: cada bloco é isolado em try/except para que a falha de uma
métrica (ex.: psutil ausente) não derrube o painel inteiro.
"""
from __future__ import annotations

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
    """Estado das tarefas agendadas do CÓRTEX (best-effort via schtasks)."""
    out: list[dict] = []
    for nome in _TAREFAS:
        estado = "nao_registrada"
        try:
            r = subprocess.run(
                ["schtasks", "/query", "/tn", nome, "/fo", "list"],
                capture_output=True, text=True, timeout=6)
            if r.returncode == 0:
                estado = "desconhecido"
                for linha in r.stdout.splitlines():
                    ln = linha.strip().lower()
                    if ln.startswith("status") or ln.startswith("estado"):
                        estado = linha.split(":", 1)[1].strip() or "desconhecido"
                        break
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            estado = "indisponivel"
        out.append({"nome": nome, "estado": estado})
    return out


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
        dados["servicos"] = _servicos()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: servicos falhou: %s", exc)
        dados["servicos"] = []
    try:
        dados["tarefas"] = _tarefas()
    except Exception as exc:  # noqa: BLE001
        dados["tarefas"] = []
    return dados
