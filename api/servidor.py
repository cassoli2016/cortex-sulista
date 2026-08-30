"""CÓRTEX — saúde do servidor (infra desta máquina).

Coleta métricas do host (CPU, memória, disco, rede, uptime) e o estado dos
serviços do CÓRTEX (API, banco ERP, túnel Cloudflare, Ollama), das integrações
de fornecedor (Prolog, Gobrax, Monkey) e das tarefas agendadas.

INTEGRAÇÃO NÃO SE CONSULTA DAQUI. Prolog tem cota, Gobrax leva 73 s por volta
e esta tela recarrega de 5 em 5 s: o que se mede é a IDADE DO INSTANTÂNEO que
as telas mostram. E integração sem credencial é `info`, não falha — o recurso
não existe nesta instalação, e pintar isso de vermelho todo dia treina o
operador a ignorar alarme. Área administrativa — a rota vive sob /api/gestao (só admin).

Tudo é best-effort: cada bloco é isolado em try/except para que a falha de uma
métrica (ex.: psutil ausente) não derrube o painel inteiro.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db

log = logging.getLogger("cortex.servidor")

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None

# Tarefas agendadas do CÓRTEX nesta máquina (README / registrar-tarefas.ps1).
# A coleta da Gobrax entrou aqui depois de ficar CINCO DIAS parada sem ninguem
# notar: nao havia tarefa, e as funcoes de sincronizacao so rodavam quando
# alguem abria uma tela com `force`. Tarefa que nao aparece na Saude e tarefa
# que pode morrer em silencio.
# Tarefa nova aqui NAO e opcional: a tela lista exatamente estes nomes, e
# uma coleta agendada que ninguem ve parar envelhece o painel calada.
_TAREFAS = ["Cortex Sulista - API", "Cortex Sulista - AutoDeploy",
            "Cortex Sulista - Tunnel", "Cortex Sulista - Telemetria",
            "Cortex Sulista - Pneus", "Cortex Sulista - Backup",
            "Cortex Sulista - Jornada"]


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


def _idade_min(iso: str) -> int | None:
    """Minutos desde o carimbo ISO. Devolve None se ilegivel — data estranha
    nao pode derrubar a tela de saude, que e justamente onde se olha quando
    algo esta errado."""
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int((datetime.now() - datetime.strptime(iso, fmt)).total_seconds() // 60)
        except (ValueError, TypeError):
            continue
    return None


def _competencia_br(competencia: str) -> str:
    """'2026-08' -> '08/2026'. A competência é guardada no formato que ordena
    (alfabético = cronológico); quem lê a tela espera o formato daqui."""
    ano, _, mes = (competencia or "").partition("-")
    return f"{mes}/{ano}" if mes else (competencia or "—")


def _ha_quanto(idade: int | None) -> str:
    """"há 12 min", "há 3 h", "há 2 dias" — a idade como quem opera a lê.

    `None` é carimbo ilegível, não "agora": tratar os dois como a mesma coisa
    pintaria de verde uma coleta cuja data ninguém consegue ler.
    """
    if idade is None:
        return "em data ilegível"
    if idade < 2:
        return "agora"
    if idade < 120:
        return f"há {idade} min"
    if idade < 2880:
        return f"há {round(idade / 60)} h"
    return f"há {round(idade / 1440)} dias"


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


def _servico_pglocal(d: dict) -> dict:
    """Linha do banco de escrita do CÓRTEX (PostgreSQL local).

    Não configurado é `info`, não falha: a instalação que ainda não migrou nada
    segue com os SQLite de `data/` e está inteira. Configurado e FORA é `erro`
    de verdade — desde o primeiro store migrado, tela sem este banco é tela sem
    dado (ver docs/MIGRACAO_POSTGRES.md).
    """
    nome = "Banco do CÓRTEX (PostgreSQL local)"
    if not d["configurado"]:
        return {"nome": nome, "status": "info",
                "detalhe": "não configurado nesta instalação — "
                           "os módulos seguem no SQLite de data/"}
    if not d["conectado"]:
        return {"nome": nome, "status": "erro",
                "detalhe": f"sem conexão com {d['onde']} ({d['erro']}) — "
                           "as telas que já migraram ficam sem dado"}
    versao = (f"schema v{d['versao_schema']}" if d["versao_schema"]
              else "schema ainda sem migration aplicada")
    return {"nome": nome, "status": "ok" if d["versao_schema"] else "alerta",
            "detalhe": f"conectado · {d['onde']} · {d['ms']} ms · {versao}"}


def _servico_jornada() -> dict:
    """A coleta da jornada está chegando?

    ISTO MUDOU DE NATUREZA quando a integração veio para dentro. Antes a
    rotina que alimentava `sulista.rasterjor_*` era externa e esta linha só
    podia DENUNCIAR; hoje o CÓRTEX é quem coleta, grava em `jor_*` e registra
    cada passagem em `jor_carga` — inclusive a que falhou e a que não trouxe
    nada. Então aqui o alarme aponta para um conserto que existe deste lado.

    A linha continua existindo pelo mesmo motivo de sempre: o sintoma de uma
    parada é uma tela de jornada VAZIA, que se lê como "ninguém rodou" em vez
    de "parou de chegar". Foi assim que quatro meses e meio passaram sem
    ninguém notar.
    """
    nome = "Jornada (RasterJOR)"
    try:
        from .jornada.leitura import defasagem
        d = defasagem()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: rasterjor: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "camada indisponível"}
    if d.get("erro"):
        return {"nome": nome, "status": "info", "detalhe": d["erro"]}
    # Sem credencial NÃO é falha: é instalação que ainda não ligou a coleta.
    if not d.get("coleta_configurada"):
        return {"nome": nome, "status": "info",
                "detalhe": (d.get("coleta_falta")
                            or "coleta não configurada") +
                           (f" · {d['jornadas']:,} jornadas do histórico"
                            .replace(",", ".") if d.get("jornadas") else "")}
    # VERMELHO É "NÃO ESTÁ CHEGANDO", e só isso: dado parado, ou a última
    # tentativa de algum recurso tendo falhado. A contagem de falhas em 48 h
    # NÃO decide a cor — recusa por limite de taxa é resposta normal do
    # fornecedor (dois cliques seguidos em "Coletar agora" já produzem uma), e
    # deixar a Saúde vermelha por dois dias por causa disso ensina todo mundo
    # a ignorar o vermelho. Ela entra como DETALHE, que é onde é útil.
    if d.get("parada"):
        return {"nome": nome, "status": "erro",
                "detalhe": f"sem dado novo há {d['dias']} dias · último "
                           f"{d.get('ultimo_dado') or '—'}"}
    falhando = d.get("recursos_falhando") or []
    if falhando:
        return {"nome": nome, "status": "erro",
                "detalhe": ("última coleta de " + ", ".join(falhando)
                            + " falhou · último dado "
                            + (d.get("ultimo_dado") or "—"))}
    resto = (f" · {d['falhas_48h']} recusa(s) do fornecedor em 48 h, já "
             f"superadas" if d.get("falhas_48h") else "")
    return {"nome": nome, "status": "ok",
            "detalhe": (f"{d['jornadas']:,} jornadas · último dado "
                        f"{d.get('ultimo_dado') or '—'}").replace(",", ".")
                       + resto}


def _servico_premiacao() -> dict:
    """A configuração da premiação está completa?

    O sinal que importa é o TIPO DE OCORRÊNCIA NÃO CLASSIFICADO: ele não entra
    na conta, e uma premiação calculada com tipos pendentes está incompleta
    sem que nada acuse. Isso não pode ser descoberto depois de pagar.

    `info` e não `alerta`: pendência de classificação é trabalho a fazer, não
    sistema quebrado — e marcar vermelho no que não está quebrado ensina a
    ignorar o vermelho.
    """
    nome = "Premiação (configuração)"
    try:
        from api.premiacao import classificacao, config
        pend = classificacao.pendentes()
        vs = config.versoes()
    except Exception as exc:  # noqa: BLE001
        return {"nome": nome, "status": "info",
                "detalhe": ("tabelas ausentes — rode scripts/migrar_schema.py"
                            if pglocal.sem_tabela(exc) else type(exc).__name__)}
    if not vs:
        return {"nome": nome, "status": "info",
                "detalhe": "nenhuma versão de parâmetros gravada — a tela usa "
                           "os padrões do sistema"}
    base = f"{len(vs)} versão(ões) · vigente desde {vs[0]['vigente_de']}"
    if pend:
        return {"nome": nome, "status": "alerta",
                "detalhe": f"{pend} tipo(s) de ocorrência sem classificação — "
                           f"eles ficam FORA da conta · {base}"}
    return {"nome": nome, "status": "ok", "detalhe": base}


def _servico_gestao() -> dict:
    """Módulo de Gestão — atas e planos de ação.

    Não é integração externa: o que pode dar errado aqui é a migration não ter
    sido aplicada nesta instalação, e o sintoma disso seria a tela abrir VAZIA,
    que se lê como "ainda não usaram" em vez de "está quebrado". A linha existe
    para separar as duas coisas.

    O número de ATRASADAS vai junto porque é o único sinal do módulo que pede
    ação de alguém — e quem abre a Saúde já está olhando o que precisa de
    atenção.
    """
    nome = "Gestão (atas e planos de ação)"
    try:
        from . import pglocal
        if not pglocal.configurado():
            return {"nome": nome, "status": "info",
                    "detalhe": "banco local não configurado nesta instalação"}
        r = pglocal.um(
            "SELECT (SELECT count(*) FROM ges_reunioes)::int AS atas,"
            "       (SELECT count(*) FROM ges_acoes)::int    AS acoes,"
            "       (SELECT count(*) FROM ges_acoes"
            "         WHERE status IN ('aberta','em_andamento')"
            "           AND prazo < current_date)::int       AS atrasadas")
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"nome": nome, "status": "erro",
                    "detalhe": "tabelas ausentes — rode "
                               "scripts/migrar_schema.py (migration 0020)"}
        log.warning("saude: gestao: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "módulo indisponível"}
    if not r["acoes"]:
        return {"nome": nome, "status": "info",
                "detalhe": f"pronto para uso · {r['atas']} ata(s), "
                           f"nenhuma ação cadastrada ainda"}
    return {"nome": nome,
            "status": "alerta" if r["atrasadas"] else "ok",
            "detalhe": (f"{r['atas']} ata(s) · {r['acoes']} ação(ões) · "
                        + (f"{r['atrasadas']} atrasada(s)" if r["atrasadas"]
                           else "nenhuma atrasada"))}


def _servico_gobrax(d: dict) -> dict:
    """Linha da Gobrax na Saúde, a partir do diagnóstico do CACHE.

    Estatística e odômetro andam juntas na Torre, então o que sai aqui é a MAIS
    ATRASADA das duas: uma fresca ao lado de outra parada é pior que as duas
    velhas, porque o cruzamento passa a mentir sem parecer.
    """
    from .gobrax.armazenamento import COLECOES, COLECOES_DIARIAS
    nome = "Gobrax (telemetria)"
    # a premiação usa OUTRA credencial (login do portal, não o token): sem ela
    # a nota × km congela sem que a telemetria acuse nada
    falta_prem = ("" if d["premiacao_configurada"]
                  else " · premiação sem login no .env (GOBRAX_EMAIL/"
                       "GOBRAX_SENHA) — a nota × km não atualiza")
    if not d["configurado"]:
        return {"nome": nome, "status": "info",
                "detalhe": "não configurada — falta o token, em "
                           "Gestão › Integrações"}
    atrasada, idade = None, None
    for colecao, _rot in COLECOES:
        c = (d["colecoes"] or {}).get(colecao)
        if not c:
            continue
        i = _idade_min(c["quando"])
        if atrasada is None or (i or 0) > (idade or 0):
            atrasada, idade = c, i
    if atrasada is None:
        return {"nome": nome, "status": "alerta",
                "detalhe": "configurada, mas nenhuma coleta ainda" + falta_prem}
    ausentes = [rot for colecao, rot in COLECOES
                if not (d["colecoes"] or {}).get(colecao)]
    sem = (" · sem coleta de " + " e ".join(ausentes)) if ausentes else ""
    # a tarefa agendada roda de 3 em 3 h; passar de duas janelas é coleta
    # parada — e aí a Torre envelhece calada, que foi como se perdeu 5 dias
    velha = idade is None or idade > 390

    # OS INDICADORES DE CONDUÇÃO TÊM LIMIAR PRÓPRIO porque têm cadência
    # própria: uma chamada por placa, varrida uma vez ao dia. Cobrá-los pelo
    # relógio do par de 3 h acenderia o alarme todo dia com tudo funcionando.
    # 30 h dá folga para a varredura atrasar uma execução sem virar alarme.
    diario = ""
    for colecao, rot in COLECOES_DIARIAS:
        c = (d.get("diarias") or {}).get(colecao)
        if not c:
            diario = f" · sem coleta de {rot} ainda"
            continue
        i = _idade_min(c["quando"])
        if i is None or i > 30 * 60:
            velha = True
            diario = (f" · {rot} parado há {_ha_quanto(i)}"
                      if i is not None else f" · {rot} sem data")
        else:
            diario = f" · {rot}: {c['registros']} veículos, {_ha_quanto(i)}"
    return {"nome": nome, "status": "alerta" if (velha or falta_prem) else "ok",
            "detalhe": f"competência {_competencia_br(atrasada['competencia'])}"
                       f" · {atrasada['registros']} veículos · atualizado "
                       f"{_ha_quanto(idade)}{sem}{diario}{falta_prem}"}


def _servico_monkey(d: dict) -> dict:
    """Linha da Monkey. Mede a POSIÇÃO GRAVADA, não a API: é ela que a tela de
    Antecipações mostra, e uma volta em /receivables pagina o portal inteiro."""
    nome = "Monkey (antecipação Tupy)"
    if not d["configurado"]:
        falta = ("credencial" if d["modo_auth"] == "nenhuma"
                 else "o sellerId da Sulista (MONKEY_SELLER_ID)")
        return {"nome": nome, "status": "info",
                "detalhe": f"não configurada — falta {falta}"}
    if not d["coletado_em"]:
        return {"nome": nome, "status": "alerta",
                "detalhe": "configurada, mas nenhuma coleta ainda — a Tupy "
                           "segue entrando por planilha"}
    idade = _idade_min(str(d["coletado_em"]).replace("T", " ")[:19])
    # HOMOLOGAÇÃO não é produção: os títulos são de teste, e a tela de
    # Antecipações não tem como saber disso sozinha
    hmg = d["ambiente"] != "prod"
    velha = idade is None or idade > 1440
    valor = f"{d['valor_saldo']:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return {"nome": nome, "status": "alerta" if (hmg or velha) else "ok",
            "detalhe": f"{d['titulos']} títulos · R$ {valor} · coletado "
                       f"{_ha_quanto(idade)}"
                       + (" · ambiente de HOMOLOGAÇÃO, os títulos são de teste"
                          if hmg else "")}


def _servico_whatsapp(d: dict) -> dict:
    """Linha da Z-API. É a única integração cujo estado só existe na API do
    fornecedor — não há posição gravada para medir, como na Monkey. Por isso o
    `cliente.estado()` tem cache de 60 s: sem ele, o refresh de 5 s desta tela
    faria ~17 mil chamadas por dia à Z-API só para desenhar um cartão.

    DESCONECTADO É ALERTA DE VERDADE, e não informação: enquanto o aparelho
    está fora, a Z-API aceita as mensagens (HTTP 200) e as empilha até 1.000,
    disparando tudo de uma vez quando ele voltar. Uma cobrança de terça
    chegando no sábado à noite, em lote, é o pior resultado possível.
    """
    nome = "Z-API (WhatsApp)"
    if not d["configurado"]:
        return {"nome": nome, "status": "info",
                "detalhe": "não configurada — falta instância e token"}
    if not d["ativo"]:
        return {"nome": nome, "status": "info",
                "detalhe": "configurada, mas o envio está DESLIGADO em "
                           "Gestão › WhatsApp"}
    if not d["conectado"]:
        motivo = d.get("erro") or "instância desconectada"
        return {"nome": nome, "status": "alerta",
                "detalhe": f"{motivo} — nada sai, e o que for mandado ficaria "
                           "na fila da Z-API"}
    partes = [f"conectado · {d['hoje']} de {d['limite_dia']} destinatários hoje"]
    if not d.get("celular"):
        partes.append("o celular pareado está sem internet")
    if not d["dentro_da_janela"]:
        partes.append(f"fora da janela de envio ({d['janela']})")
    # O RESERVA É DETALHE, NÃO SEGUNDA LINHA DE ESTADO. Reserva desconectado é
    # o estado normal de um reserva (pareado e parado): dar a ele o mesmo peso
    # faria a Saúde acusar problema onde não há, e alerta que sempre aparece
    # deixa de ser lido. O que a linha precisa dizer é se existe reserva e se
    # ele está pronto — e a cota dele é própria, porque o limite é por número.
    reserva = d.get("reserva")
    if reserva is not None:
        partes.append(
            f"reserva {'pronto' if reserva['conectado'] else 'não conectado'}"
            f" · {reserva['hoje']} de {d['limite_dia']} hoje")
    return {"nome": nome,
            "status": "alerta" if not d.get("celular") else "ok",
            "detalhe": " · ".join(partes)}


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

    # Banco da FOLHA (Oracle GLOBUS). Não configurado != fora do ar: sem as
    # variáveis de ambiente o recurso simplesmente não existe nesta instalação,
    # e pintar isso de vermelho todo dia treinaria o operador a ignorar alarme.
    try:
        from . import db_folha
        if not db_folha.configured():
            servicos.append({"nome": "Banco da Folha (Oracle)", "status": "info",
                             "detalhe": "não configurado nesta instalação"})
        else:
            t0 = time.perf_counter()
            try:
                db_folha.ping()
                ms = round((time.perf_counter() - t0) * 1000)
                servicos.append({"nome": "Banco da Folha (Oracle)", "status": "ok",
                                 "detalhe": f"conectado · {ms} ms"})
            except Exception as exc:  # noqa: BLE001
                servicos.append({"nome": "Banco da Folha (Oracle)", "status": "erro",
                                 "detalhe": "sem conexão — RH e Custo de Folha ficam sem dado"})
                log.warning("saude: oracle inacessivel: %s", exc)
    except Exception:  # noqa: BLE001
        servicos.append({"nome": "Banco da Folha (Oracle)", "status": "info",
                         "detalhe": "driver indisponível"})

    # BANCO DE ESCRITA DO CÓRTEX (PostgreSQL local). É o destino dos dez SQLite
    # de data/, migrados um por vez. Fica ao lado dos outros dois bancos porque
    # é o terceiro: ERP (réplica de terceiro), Folha (Oracle) e este, o da casa.
    try:
        from . import pglocal
        servicos.append(_servico_pglocal(pglocal.diagnostico()))
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Banco do CÓRTEX (PostgreSQL local)",
                         "status": "info", "detalhe": "camada indisponível"})
        log.warning("saude: pglocal: %s", exc)

    # Gestão: mora no banco local, então vem logo depois dele. A tela vazia por
    # migration faltando é indistinguível de tela vazia por falta de uso — esta
    # linha é o que separa as duas.
    servicos.append(_servico_gestao())
    servicos.append(_servico_premiacao())

    # Jornada: vem do AVA, não do banco local — mas a pergunta é a mesma
    # (o dado está chegando?), então fica ao lado.
    servicos.append(_servico_jornada())

    # PROLOG (pneus). Integração externa com COTA: a coleta é agendada e
    # retomável, então o que interessa aqui não é "responde?" — é se o
    # instantâneo está fresco e o quanto do parque já foi varrido. Chamar a API
    # daqui gastaria requisição da mesma cota que a coleta precisa.
    try:
        from .pneus import servico as pneus_srv
        d = pneus_srv.diagnostico()
        if not d["pronto"]:
            falta = ("credencial" if d["modo_auth"] == "nenhuma"
                     else "ids das filiais (PROLOG_FILIAIS)")
            servicos.append({"nome": "Prolog (pneus)", "status": "info",
                             "detalhe": f"não configurada — falta {falta}"})
        elif not d["coletado_em"]:
            servicos.append({"nome": "Prolog (pneus)", "status": "alerta",
                             "detalhe": "configurada, mas nenhuma coleta ainda"})
        else:
            idade = _idade_min(d["coletado_em"])
            lidos, total = d["lidos"], d["total_na_api"]
            cob = f"{lidos} de {total}" if total else f"{lidos}"
            quando = _ha_quanto(idade)
            # a coleta anda de 20 em 20 min; passar de 90 min sem avancar
            # significa tarefa parada, e ai o numero da tela envelhece calado
            servicos.append({
                "nome": "Prolog (pneus)",
                "status": "ok" if (idade or 0) < 90 else "alerta",
                "detalhe": f"{cob} pneus · atualizado {quando} · "
                           f"{d['voltas']} volta(s) completa(s)"})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Prolog (pneus)", "status": "info",
                         "detalhe": "integração indisponível"})
        log.warning("saude: prolog: %s", exc)

    for nome, modulo, monta in (
            ("Gobrax (telemetria)", "gobrax.armazenamento", _servico_gobrax),
            ("Monkey (antecipação Tupy)", "monkey.servico", _servico_monkey),
            ("Z-API (WhatsApp)", "whatsapp.servico", _servico_whatsapp)):
        try:
            mod = importlib.import_module("." + modulo, __package__)
            servicos.append(monta(mod.diagnostico()))
        except Exception as exc:  # noqa: BLE001
            # integração que explode no diagnóstico não pode derrubar a tela
            # onde se olha justamente quando algo está errado
            servicos.append({"nome": nome, "status": "info",
                             "detalhe": "integração indisponível"})
            log.warning("saude: %s: %s", modulo, exc)

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


# ── CACHE DAS TAREFAS AGENDADAS ──────────────────────────────────────────────
#
# Consultar as tarefas custa 3,6 s: são sete chamadas ao agendador do Windows
# dentro de UM processo PowerShell, que ainda precisa subir. A Saúde recarrega
# a cada 5 s — ou seja, sem cache o servidor passava 72% do tempo perguntando
# ao Windows uma coisa que muda quando alguém roda um instalador.
#
# Foi isso que fez a tela PARAR DE CARREGAR: com a resposta em 4,8 s contra
# recarga de 5 s, quase toda resposta chegava depois de a próxima requisição
# ter começado, e o guard de sequência do front a descartava. A tela ficava em
# branco para sempre — não por erro, por corrida perdida.
#
# 60 s é o mesmo TTL do estado da Z-API, e pela mesma razão: diagnóstico cujo
# custo é externo não pode ser refeito a cada pintura de cartão. O atraso
# máximo para uma tarefa recém-instalada aparecer é um minuto, o que é
# aceitável num cartão de monitoramento — e o payload diz a idade da leitura.
_TAREFAS_TTL = 60.0
_tarefas_cache: tuple[float, list[dict]] | None = None


def _tarefas(forcar: bool = False) -> list[dict]:
    """Estado + última/próxima execução das tarefas agendadas do CÓRTEX.

    Usa Get-ScheduledTaskInfo (dados estruturados, independentes de idioma) em
    vez de parsear o texto localizado do schtasks. Best-effort: sem PowerShell
    (ex.: dev no Mac) devolve só os nomes."""
    global _tarefas_cache
    agora = time.monotonic()
    if not forcar and _tarefas_cache and (agora - _tarefas_cache[0]) < _TAREFAS_TTL:
        return _tarefas_cache[1]
    r = _tarefas_consultar()
    _tarefas_cache = (agora, r)
    return r


def _tarefas_consultar() -> list[dict]:
    """A consulta de verdade. Separada para o cache não misturar as duas."""
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


# Nome de exibição -> arquivo. O que a base guarda importa mais que o nome do
# arquivo: "telemetria.db" não diz nada para quem opera; "cache da Gobrax" diz.
#
# SÓ AS VIVAS ENTRAM AQUI. Depois da migração de 27/08/2026 sobrou uma: o cache
# da Gobrax, que fica FORA do PostgreSQL de propósito porque é reconstruível.
# As migradas são resumidas em uma linha (ver `_migradas`), e a razão é a mesma
# do resto desta tela: um cartão com oito linhas dizendo "isto não está em uso"
# ensina a pular o cartão inteiro — inclusive a linha que decide alguma coisa.
BASES_VIVAS = [
    ("Telemetria (cache Gobrax)", "telemetria.db"),
]

# Bases migradas para o PostgreSQL em 27/08/2026 e ARQUIVADAS em 30/08/2026,
# depois que a restauração do backup foi testada de verdade
# (scripts/testar_restauracao.py) — os arquivos saíram de `data/` para
# `data/arquivo/sqlite-migrados-2026-08-30/`.
#
# A LISTA FICA, e não é resíduo. Ela serve a duas coisas vivas:
#   1. o ROLLBACK. Devolver um `.db` para `data/` o faz reaparecer no cartão na
#      hora, porque a varredura é da PASTA e não de uma lista fixa. Sem esta
#      lista ele voltaria como "banco não declarado" — alarme errado para uma
#      volta deliberada.
#   2. distinguir o conhecido do DESCONHECIDO: `.db` que não está aqui é módulo
#      novo escrevendo em SQLite contra a regra da casa, e isso é alerta.
# Ver docs/MIGRACAO_POSTGRES.md.
MIGRADAS = {"antt.db", "push.db", "email.db", "previsao.db", "antecipacoes.db",
            "extrato.db", "orcamento.db", "contrapartida.db", "auth.db"}

# Nada pode ser escrito num `.db` migrado a partir daqui. É o sensor que
# transforma oito linhas mortas numa útil: se um deles voltar a ser gravado,
# código novo voltou a escrever em SQLite contra a regra da casa, e hoje isso
# passaria despercebido — o dado iria para o arquivo errado e o PostgreSQL
# ficaria para trás sem ninguém acusar.
LIMITE_MIGRACAO = datetime(2026, 8, 28)


def _dir_dados() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def _bases_locais() -> list[dict]:
    """Bases SQLite AINDA VIVAS: existência, tamanho, integridade.

    `PRAGMA quick_check` em vez de `integrity_check`: o completo varre o
    arquivo inteiro e a tela recarrega a cada 5 s — num banco de 1,7 MB seria
    desperdício, e num maior travaria a Saúde.

    Arquivo AUSENTE não é erro: a base nasce no primeiro uso do recurso. É
    'não usado ainda', e dizer isso evita alarme sobre função que ninguém
    ligou.
    """
    import sqlite3

    raiz = _dir_dados()
    fora: list[dict] = []
    for rotulo, arquivo in BASES_VIVAS:
        caminho = raiz / arquivo
        item = {"nome": rotulo, "arquivo": arquivo}
        if not caminho.exists():
            fora.append({**item, "status": "info", "bytes": 0,
                         "detalhe": "não usada ainda"})
            continue
        try:
            tam = caminho.stat().st_size
            mod = _iso(caminho.stat().st_mtime)
            con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=2)
            try:
                ok = con.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                con.close()
            gravavel = os.access(caminho, os.W_OK)
            if ok != "ok":
                st, det = "erro", f"integridade: {ok}"
            elif not gravavel:
                # somente-leitura numa base de escrita quebra o recurso inteiro
                # e a tela que usa ela falharia sozinha, sem ninguém ligar os
                # pontos
                st, det = "erro", "sem permissão de escrita"
            else:
                st, det = "ok", f"íntegra · escrita em {mod}"
            fora.append({**item, "status": st, "bytes": tam,
                         "modificado_em": mod, "detalhe": det})
        except Exception as exc:  # noqa: BLE001
            fora.append({**item, "status": "erro", "bytes": 0,
                         "detalhe": f"não pôde ser lida ({type(exc).__name__})"})
    return fora


def _migradas() -> dict | None:
    """Uma linha para os arquivos da migração — e um sensor dentro dela.

    O que ela responde não é "estão saudáveis?" (ninguém os usa), é **"ainda
    estão aí, ocupando espaço, e continuam intocados?"**. Por isso traz
    quantidade, tamanho e a data da migração: são os três números de que
    alguém precisa para decidir apagá-los, e a decisão é a única coisa
    pendente sobre eles.

    DOIS ALERTAS DE VERDADE moram aqui:

    - **Arquivo migrado ESCRITO de novo** — código novo voltou a gravar em
      SQLite, contra a regra do CLAUDE.md. O dado foi para o lugar errado e o
      PostgreSQL ficou para trás.
    - **`.db` que ninguém declarou** — a varredura é do diretório, não de uma
      lista, justamente para pegar o arquivo que apareceu sem passar por aqui.
      Uma lista fixa só enxerga o que já se sabia.

    Devolve `None` quando não sobrou nenhum — que é o estado desde 30/08/2026,
    com os arquivos movidos para `data/arquivo/`. A linha some da tela em vez
    de dizer "0 arquivos", e VOLTA sozinha se algum `.db` retornar à pasta.
    """
    raiz = _dir_dados()
    if not raiz.exists():
        return None
    vivas = {a for _, a in BASES_VIVAS}
    arquivos, bytes_, reescritos, estranhos = 0, 0, [], []
    for caminho in sorted(raiz.glob("*.db")):
        nome = caminho.name
        if nome in vivas:
            continue
        try:
            st = caminho.stat()
        except OSError:
            continue
        if nome not in MIGRADAS:
            estranhos.append(nome)
            continue
        arquivos += 1
        bytes_ += st.st_size
        if datetime.fromtimestamp(st.st_mtime) >= LIMITE_MIGRACAO:
            reescritos.append(nome)

    if not arquivos and not estranhos:
        return None

    base = {"arquivos": arquivos, "bytes": bytes_,
            "migrada_em": "27/08/2026",
            "reescritos": reescritos, "nao_declarados": estranhos}
    if reescritos:
        return {**base, "status": "alerta",
                "detalhe": ("gravado de novo depois da migração: "
                            + ", ".join(reescritos)
                            + " — código novo voltou a escrever em SQLite, e "
                              "esse dado NÃO está no PostgreSQL")}
    if estranhos:
        return {**base, "status": "alerta",
                "detalhe": ("banco SQLite não declarado em data/: "
                            + ", ".join(estranhos)
                            + " — módulo novo deve escrever no PostgreSQL "
                              "(api/pglocal.py)")}
    return {**base, "status": "info",
            "detalhe": ("da migração de 27/08/2026 de volta em data/ · o "
                        "arquivamento de 30/08/2026 os tirou daqui, então "
                        "alguém os devolveu — se foi rollback, está certo; se "
                        "não, é código gravando onde não devia")}


def _deploy_saude(tarefas: list[dict]) -> dict:
    """Saúde do AutoDeploy: alerta se a tarefa não roda há muito (deveria a cada
    2 min) ou perdeu o gatilho (sem próxima execução). Evita repetir o deploy
    travado silenciosamente."""
    import re
    t = next((x for x in tarefas if "autodeploy" in (x.get("nome", "").lower())), None)
    if not t:
        return {"status": "desconhecido", "detalhe": "tarefa AutoDeploy não encontrada"}
    ultima, proxima = t.get("ultima"), t.get("proxima")
    status, det = "ok", "em dia"
    if not ultima:
        return {"status": "alerta", "detalhe": "AutoDeploy nunca executou",
                "ultima": None, "proxima": proxima}
    try:
        s = re.sub(r"(\.\d{6})\d+", r"\1", ultima)   # PS ToString('o') gera 7 casas
        dt = datetime.fromisoformat(s)
        mins = int((datetime.now(dt.tzinfo) - dt).total_seconds() // 60)
        det = f"última execução há {mins} min"
        if mins > 6:
            status, det = "alerta", f"sem rodar há {mins} min (deveria ser a cada 2 min)"
    except Exception:  # noqa: BLE001
        det = "não foi possível ler a última execução"
    if status == "ok" and not proxima:
        status, det = "alerta", "sem próxima execução agendada (gatilho perdido?)"
    return {"status": status, "detalhe": det, "ultima": ultima, "proxima": proxima}


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
        dados["bases"] = _bases_locais()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: bases locais falhou: %s", exc)
        dados["bases"] = []
    try:
        dados["migradas"] = _migradas()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: resumo das migradas falhou: %s", exc)
        dados["migradas"] = None
    try:
        dados["tarefas"] = _tarefas()
    except Exception as exc:  # noqa: BLE001
        dados["tarefas"] = []
    try:
        dados["deploy"] = _deploy_saude(dados.get("tarefas", []))
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: deploy falhou: %s", exc)
        dados["deploy"] = {}
    return dados
