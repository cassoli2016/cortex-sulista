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
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import db, pglocal
from .sob_teste import sob_teste

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
            "Cortex Sulista - Jornada", "Cortex Sulista - Ngrok",
            "Cortex Sulista - Smartec", "Cortex Sulista - WhatsApp agendado",
            "Cortex Sulista - Gerenciamento de Risco",
            "Cortex Sulista - Monkey",
            # Registrada em 08/09/2026, 07:01 (log do instalador). Entra aqui
            # SO agora, e nao junto com o codigo: tarefa listada antes de
            # existir vira vermelho permanente na Saude, e alarme que grita a
            # toa ensina a ignorar alarme.
            "Cortex Sulista - DFe SEFAZ"]
# Fora da lista DE PROPÓSITO (instalador existe, registro não comprovado
# nesta máquina): 'CTe Contrapartida' (aguarda a decisão fiscal) e
# 'Relatorios por e-mail'. Entrar aqui sem estar registrada viraria um
# vermelho permanente — e alarme que grita à toa ensina a ignorar alarme.


# ── MEDIÇÃO CARA NÃO ESPERA O PEDIDO ─────────────────────────────────────────
#
# POR QUE ISTO EXISTE, com a medição (07/09/2026). A Saúde do Servidor levava
# 78 s para carregar a PRIMEIRA vez e a tela ficava em branco. A causa foi
# medida bloco a bloco, num processo novo, sem aquecer nada:
#
#     agrupador (mapa contábil)   47,7 s     ← uma consulta ao ERP
#     tarefas agendadas            6,9 s     ← sete perguntas ao Windows
#     serviços (os 31 cartões)     0,8 s
#     todo o resto                 < 1 s
#
# A consulta do mapa foi corrigida no `agrupador_gerencial` (47 s → 4,5 s) e
# isso levou a coleta fria de 78 s para 13,7 s. **Não bastou**, e a casa já
# sabia por quê: o comentário do `_TAREFAS_TTL` conta que a Saúde parou de
# carregar quando a resposta passou de 4,8 s contra uma recarga encadeada de
# 5 s — quase toda resposta chegava depois de a próxima ter começado, e o guard
# de sequência do front a descartava. Em branco para sempre, sem erro nenhum.
#
# TTL SOZINHO NÃO RESOLVE ISSO, e é a lição desta rodada. O cache poupa a
# SEGUNDA leitura; quem paga a primeira é sempre alguém — e o AutoDeploy
# reinicia a API a cada push, então "a primeira" acontece várias vezes por dia,
# sempre na cara de quem abriu a tela.
#
# Então a medição cara sai do caminho do pedido: a coleta devolve na hora o que
# tem, e a medição corre numa thread. Três estados, e o cartão DIZ qual é —
# "medindo" não é o mesmo que "não sei", e nenhum dos dois é "está ruim":
#
#   fresco  — dentro do TTL, é o número
#   velho   — passou do TTL: serve a ÚLTIMA LEITURA BOA com a idade à mostra
#             (a mesma regra do `cached(velha_ate=)` das telas: número velho
#             servido calado é pior que tela vazia, porque ninguém desconfia)
#   medindo — nunca mediu nesta instância: o cartão diz isso, e não some
#
# O cartão não SOME enquanto mede, de propósito: ausência não tem sintoma, e um
# cartão que desaparece por um minuto ensina que a conferência não existe.
#
# UMA medição por vez, por chave. A tela repinta de 5 em 5 s; sem a trava, uma
# medição de 5 s viraria doze PowerShell simultâneos ou doze varreduras do
# razão — pior que esperar. `daemon=True` porque monitoramento nunca segura o
# desligamento do processo.
class _EmFundo:
    """Cache com TTL que nunca faz o pedido esperar pela medição.

    NÃO SOBE THREAD SOB PYTEST (`em_fundo=None` decide por `sob_teste()`).
    O que ela mede lê o ERP de PRODUÇÃO e abre PowerShell, e nesta bancada as
    credenciais são as de verdade: uma rodada de testes que encostasse em
    `coletar()` deixaria threads vivas medindo a casa depois de o teste ter
    acabado — a forma exata do defeito de 06/09/2026 (a thread de um processo
    de teste escrevendo no log da API de produção).

    Sob teste, `ler()` devolve "medindo" e não mede; quem quer medir de fato
    pede `esperar=True`, e quem quer exercitar a THREAD constrói com
    `em_fundo=True`, explicitamente e à vista.
    """

    def __init__(self, nome: str, ttl: float, fn, em_fundo: bool | None = None):
        self.nome, self.ttl, self.fn = nome, ttl, fn
        self.em_fundo = (not sob_teste()) if em_fundo is None else em_fundo
        self._valor = None
        self._em = 0.0          # monotonic da última leitura BOA
        self._medindo = False
        self._trava = threading.Lock()

    def _medir(self) -> None:
        try:
            v = self.fn()
        except Exception as exc:  # noqa: BLE001
            # Falhar não apaga o que já se sabia: a leitura velha continua
            # servindo, com a idade à mostra. O TIPO da exceção, nunca o texto
            # cru — a conninfo do AVA passa por aqui.
            log.warning("saude: medição '%s' falhou: %s", self.nome,
                        type(exc).__name__)
        else:
            with self._trava:
                self._valor, self._em = v, time.monotonic()
        finally:
            with self._trava:
                self._medindo = False

    def ler(self, esperar: bool = False) -> tuple[object | None, str, int | None]:
        """(valor, estado, idade em segundos). `esperar=True` mede na hora —
        é para o conferidor de linha de comando, não para a tela."""
        if esperar:
            self._medir_agora()
        with self._trava:
            valor, em, medindo = self._valor, self._em, self._medindo
            precisa = valor is None or (time.monotonic() - em) >= self.ttl
            if precisa and not medindo and self.em_fundo:
                self._medindo = True
                # O NOME VAI LITERAL AQUI, e nao por constante: a varredura
                # de `tests/test_agendadores_sob_teste.py` le o FONTE
                # procurando `name="..."` -- por constante ela registra a
                # thread como SEM NOME, e thread sem nome nao entra em
                # varredura nenhuma. (Um `name=` montado com `%` era pior
                # ainda: registrava `saude-%s`, nome que nao existe em thread
                # viva nenhuma. Guard que nomeia errado o alvo nunca fica
                # vermelho -- este arquivo ja custou isso com "aviso-carga"
                # contra "rastreio-aviso".)
                threading.Thread(target=self._medir, daemon=True,
                                 name="saude-em-fundo").start()
        if valor is None:
            return None, "medindo", None
        # A DECISAO SAI DO FLOAT, o rotulo do inteiro. Comparar `int(idade)`
        # com o TTL fazia 0,9 s contar como fresco num cache de 0,5 s -- e com
        # TTL de 60 s todo o primeiro minuto de atraso ficava invisivel. Razao
        # e percentual saem da unidade de ORIGEM; arredondar antes de comparar
        # move o numero de lado da fronteira. Pego pelo teste, nao pela leitura.
        decorrido = time.monotonic() - em
        return valor, ("fresco" if decorrido < self.ttl else "velho"), int(decorrido)

    def _medir_agora(self) -> None:
        with self._trava:
            self._medindo = True
        self._medir()


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
    algo esta errado.

    `fromisoformat` PRIMEIRO, e nao so os tres formatos fixos: coluna
    `timestamptz` do PostgreSQL sai como '2026-09-06T12:00:00.123456+00:00', e
    nenhum dos `strptime` abaixo casa com fuso nem com microssegundo. O cartao
    do app do motorista dizia "ultima entrada em data ilegivel" desde que
    nasceu, por isto — defeito MUDO, porque a funcao tinha rede e a rede
    escondia a causa. Os formatos fixos ficam para quem grava texto sem fuso
    (a maior parte da casa).

    Carimbo COM fuso se compara com um agora COM fuso: misturar os dois levanta
    `TypeError`, que aqui viraria "ilegivel" de novo — a mesma mentira com
    outra causa.
    """
    from datetime import datetime, timezone
    try:
        quando = datetime.fromisoformat(str(iso))
    except (ValueError, TypeError):
        quando = None
    if quando is not None:
        agora = (datetime.now(timezone.utc) if quando.tzinfo
                 else datetime.now())
        return int((agora - quando).total_seconds() // 60)
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


def _processo_ngrok() -> int:
    if not psutil:
        return 0
    n = 0
    for pr in psutil.process_iter(["name"]):
        try:
            if (pr.info["name"] or "").lower().startswith("ngrok"):
                n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return n


# O ngrok é a porta SECUNDÁRIA para a internet, ao lado do túnel Cloudflare.
# O que este cartão vigia NÃO é "está no ar" — é se ela está no ar COM PORTÃO.
#
# A diferença é o motivo de a linha existir: nesta porta o Cloudflare Access
# NÃO se aplica, então túnel ligado sem `basic_auth`/`oauth` no ngrok.yml
# significa o CÓRTEX alcançável da internet com apenas o login do app na
# frente. É a única leitura desta linha que pede ação hoje, e é ela que
# justifica o cartão — mesma regra da linha dos `.db` migrados, que é sensor e
# não enfeite.
#
# Desligado é `info`, nunca falha: a porta é opcional e ficar fechada é o
# estado NORMAL dela, como o WhatsApp reserva pareado e parado. Pintar isso de
# vermelho ensinaria a ignorar o vermelho.
#
# 30 s de TTL: a API do agente é local e barata, mas a Saúde repinta de 5 em
# 5 s — abrir socket e ler YAML doze vezes por minuto para desenhar um cartão
# é custo sem retorno. Mesma razão do cache das tarefas agendadas.
_NGROK_TTL = 30.0
_ngrok_cache: tuple[float, dict] | None = None


def _ngrok_portao(tunel: str = "cortex") -> str | None:
    """Qual portão o ngrok.yml declara para o túnel.

    Lido do ARQUIVO porque a API local do agente não devolve isso: em
    /api/tunnels o bloco `config` traz só `addr` e `inspect` (medido). Ou seja
    não há como provar o portão sem sair para a internet, e sair daqui é
    justamente o que o cabeçalho deste módulo proíbe. Então o cartão diz
    "declarado", não "provado" — afirmar o que não se mediu seria pior.

    Devolve o nome do portão, "" se o túnel existe sem nenhum, ou None se nem
    o arquivo/túnel existe.
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    caminho = Path(base) / "ngrok" / "ngrok.yml"
    if not caminho.is_file():
        return None
    try:
        import yaml  # local: o módulo não pode falhar ao importar por causa disto
        cfg = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    t = ((cfg.get("tunnels") or {}).get(tunel) or {})
    if not t:
        return None
    if t.get("oauth"):
        return "OAuth"
    if t.get("basic_auth"):
        return "usuário e senha"
    return ""


def _ngrok_consultar() -> dict:
    """Estado do agente ngrok: processo, túnel publicado e portão."""
    d: dict = {"processos": _processo_ngrok(), "portao": _ngrok_portao(),
               "url": None, "inspetor": None}
    try:
        import urllib.request
        with urllib.request.urlopen(
                "http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
            corpo = json.loads(r.read().decode("utf-8"))
        for t in (corpo.get("tunnels") or []):
            if t.get("name") == "cortex" or not d["url"]:
                d["url"] = t.get("public_url")
                d["inspetor"] = (t.get("config") or {}).get("inspect")
                if t.get("name") == "cortex":
                    break
    except Exception:  # noqa: BLE001
        pass  # agente fora do ar é estado, não erro a propagar
    return d


def _ngrok(forcar: bool = False) -> dict:
    global _ngrok_cache
    agora = time.monotonic()
    if not forcar and _ngrok_cache and (agora - _ngrok_cache[0]) < _NGROK_TTL:
        return _ngrok_cache[1]
    r = _ngrok_consultar()
    _ngrok_cache = (agora, r)
    return r


def _servico_ngrok() -> dict | None:
    """Cartão do túnel ngrok. `None` quando não há ngrok nesta instalação.

    Devolver None em vez de uma linha "não instalado" é deliberado: cartão que
    nunca muda ensina a pular o cartão, e junto com ele os que decidem algo.
    """
    d = _ngrok()
    if not d["processos"] and d["portao"] is None:
        return None

    nome = "Túnel ngrok (porta secundária)"
    if not d["processos"]:
        return {"nome": nome, "status": "info",
                "detalhe": "configurado e desligado — o acesso externo está "
                           "só pelo túnel Cloudflare"}

    url = d["url"] or "URL ainda não publicada"
    if d["portao"] is None or d["portao"] == "":
        return {"nome": nome, "status": "alerta",
                "detalhe": f"NO AR SEM PORTÃO · {url} · aqui o Cloudflare "
                           "Access não vale: quem tiver a URL chega no login "
                           "do CÓRTEX sem MFA"}

    det = f"no ar · {url} · portão declarado: {d['portao']}"
    # `inspect` vem da API, então isto é medido, não declarado. Ligado, o
    # inspetor em 127.0.0.1:4040 grava corpo de requisição e resposta —
    # faturamento, PII de motorista e o cookie de sessão — numa tela sem senha.
    if d["inspetor"]:
        return {"nome": nome, "status": "alerta",
                "detalhe": det + " · INSPETOR LIGADO: 127.0.0.1:4040 está "
                                 "gravando corpo de requisição e resposta"}
    return {"nome": nome, "status": "ok", "detalhe": det}


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


def _servico_auditoria(d: dict) -> dict:
    """A trilha de auditoria esta viva?

    Vale a linha porque a falha aqui e MUDA: a coleta nunca levanta (auditoria
    que impede de entrar vira auditoria desligada), entao o dia em que ela
    parar de gravar nao aparece em lugar nenhum — a tela de Auditoria so ficaria
    mais vazia a cada semana, e ninguem sabe de cor quantos acessos deveria ter.

    Funcao PURA sobre o diagnostico.
    """
    nome = "Auditoria de uso (trilha)"
    if not d.get("ok"):
        return {"nome": nome, "status": "erro",
                "detalhe": "nao foi possivel ler a trilha (%s) — a tela de "
                           "Auditoria fica sem dado" % (d.get("erro") or "erro")}
    partes = ["%s sessao(oes) registrada(s)" % f"{d['sessoes']:,}".replace(",", "."),
              "%s acao(oes) na trilha" % f"{d['acoes']:,}".replace(",", ".")]
    if d.get("abertas"):
        partes.append("%d no painel agora" % d["abertas"])
    if d.get("ultimo_acesso"):
        partes.append("ultimo acesso em " + str(d["ultimo_acesso"])[:16])
    # Sem NENHUMA sessao a coleta pode estar quebrada ou o sistema recem-migrado.
    # `info` e nao alerta: nao da para separar as duas coisas daqui, e vermelho
    # que nao distingue treina o operador a ignorar.
    if not d["sessoes"]:
        return {"nome": nome, "status": "info",
                "detalhe": "nenhuma sessao registrada ainda — a coleta comeca "
                           "no proximo login"}
    return {"nome": nome, "status": "ok", "detalhe": " · ".join(partes)}


def _portal_cliente() -> dict:
    """Quantos logins de cliente existem, e a coluna que os sustenta existe?

    POR QUE ESTA LINHA EXISTE. O portal e a unica tela cujo dado depende de uma
    COLUNA DE CADASTRO estar preenchida: sem `cliente_cnpj_raiz`, a tela abre e
    recusa. Do lado de dentro isso e invisivel — ninguem da casa abre o portal,
    entao o unico jeito de descobrir que ele nunca funcionou seria o cliente
    reclamar. Aqui a instalacao se declara.

    A COLUNA AUSENTE E UM ESTADO DE VERDADE, nao um erro a esconder: o
    AutoDeploy NAO roda migration (conferido em 05/09/2026 no
    `scripts/autodeploy.ps1`), entao existe uma janela real entre o codigo
    chegar e alguem rodar o `migrar_schema.py`. Nessa janela a tela de Usuarios
    quebra, e este cartao e o que diz por que.
    """
    from . import auth as _auth

    nome = "Portal do cliente (Minha Operação)"
    try:
        with _auth._conn() as c:
            existe = c.execute(
                """SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'usuarios'
                      AND column_name = 'cliente_cnpj_raiz'""").fetchone()
            if not existe:
                return {"nome": nome, "status": "erro",
                        "detalhe": ("a coluna `usuarios.cliente_cnpj_raiz` não "
                                    "existe — falta aplicar a migration 0053 "
                                    "(uv run python scripts/migrar_schema.py); "
                                    "até lá a tela de Usuários também falha")}
            r = c.execute(
                """SELECT count(*) AS logins,
                          count(DISTINCT cliente_cnpj_raiz) AS clientes,
                          sum(CASE WHEN ativo = 1 THEN 1 ELSE 0 END) AS ativos
                     FROM usuarios WHERE cliente_cnpj_raiz IS NOT NULL""").fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: portal do cliente: %s", type(exc).__name__)
        return {"nome": nome, "status": "info", "detalhe": "conferência indisponível"}

    if not r or not r["logins"]:
        # SEM VINCULO NAO E FALHA, e instalacao incompleta — a mesma regra das
        # integracoes sem credencial. `info`, nunca vermelho: alarme que nao
        # distingue "quebrado" de "ainda nao usado" treina a ignorar alarme.
        return {"nome": nome, "status": "info",
                "detalhe": ("nenhum login de cliente cadastrado — gente da casa "
                            "com a tela no perfil já usa, escolhendo o cliente")}
    partes = ["%d login(s) em %d cliente(s)" % (r["logins"], r["clientes"])]
    if (r["ativos"] or 0) < r["logins"]:
        partes.append("%d inativo(s)" % (r["logins"] - (r["ativos"] or 0)))
def _servico_monitoramentos(d: dict) -> dict:
    """Os monitoramentos de carga da pagina publica estao sendo avisados?

    VALE A LINHA PORQUE A FALHA AQUI E MUDA, e de um jeito pior que a maioria:
    quem espera a carga NAO TEM CONTA e nao tem a quem reclamar dentro de casa.
    Se o aviso horario parar, ninguem aqui dentro descobre — a pessoa
    simplesmente para de receber mensagem e conclui que o sistema e ruim.

    O QUE ESTE CARTAO NAO CONSEGUE PROVAR, e diz em vez de fingir: nao existe
    registro de EXECUCAO do aviso, so registro de ENVIO. E o aviso nao reenvia
    mensagem identica a anterior, entao "nenhum envio na ultima hora" e o
    comportamento CORRETO de um caminhao parado. Por isso o alarme so acende
    com inscricao ativa E nenhum envio em 24 horas: nesse prazo o texto de uma
    carga em viagem muda por qualquer motivo — progresso, etapa, entrega —, e
    silencio de um dia inteiro nao tem explicacao inocente.

    Funcao PURA sobre o resumo.
    """
    nome = "Monitoramentos de carga (aviso ao cliente)"
    if not d:
        return {"nome": nome, "status": "info",
                "detalhe": "nao foi possivel ler os monitoramentos — a tela "
                           "Monitoramentos fica sem dado"}
    ativas, envios = d.get("ativas") or 0, d.get("envios") or 0
    idade = d.get("ultimo_envio_min")
    partes = ["%d acompanhando agora" % ativas,
              "%d carga(s) e %d telefone(s)" % (d.get("cargas_ativas") or 0,
                                                d.get("fones_ativos") or 0),
              "%d aviso(s) ja enviado(s)" % envios]
    if idade is not None:
        partes.append("ultimo aviso " + _ha_quanto(idade))
    # SEM INSCRICAO NAO HA O QUE MANDAR. `info`, nunca alarme: a pagina publica
    # pode passar dias sem ninguem pedir acompanhamento, e isso nao e defeito.
    if not ativas:
        return {"nome": nome, "status": "info",
                "detalhe": "ninguem acompanhando carga agora — nada a enviar"
                           + (" · %d aviso(s) no historico" % envios if envios else "")}
    if idade is None:
        return {"nome": nome, "status": "alerta",
                "detalhe": "%d inscricao(oes) ativa(s) e NENHUM aviso enviado "
                           "ate agora — conferir a tarefa horaria" % ativas}
    if idade > 24 * 60:
        return {"nome": nome, "status": "alerta",
                "detalhe": " · ".join(partes)
                           + " — mais de 24 h sem enviar com inscricao ativa; "
                             "conferir a tarefa horaria do aviso"}
    return {"nome": nome, "status": "ok", "detalhe": " · ".join(partes)}


def _app_motorista() -> dict:
    """O app do motorista existe do lado de FORA, e por isso ele precisa disto.

    Ninguem da casa abre `motorista.html`. Se o vinculo nao for cadastrado, se
    a migration nao rodar, ou se o codigo parar de chegar no WhatsApp, o unico
    sintoma e um motorista que nao consegue entrar — e ele nao abre chamado,
    ele liga para a torre, que e o telefonema que o app existe para tirar. O
    silencio, aqui, e o defeito.

    A TABELA AUSENTE E UM ESTADO DE VERDADE: o AutoDeploy NAO roda migration,
    entao ha uma janela real entre o codigo chegar e alguem rodar o
    `migrar_schema.py`. Nessa janela o app inteiro recusa, e este cartao diz
    por que — em vez de a Saude afirmar que esta tudo bem porque nada quebrou
    do lado de dentro.

    SEM VINCULO NAO E FALHA, E INSTALACAO INCOMPLETA (`info`, nunca vermelho):
    e a mesma regra da integracao sem credencial. Alarme que nao distingue
    "quebrado" de "ainda nao usado" treina todo mundo a ignorar alarme.
    """
    nome = "App do motorista"
    try:
        with pglocal.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = 'mot_vinculos'""")
            if not cur.fetchone():
                return {"nome": nome, "status": "info",
                        "detalhe": ("tabelas do app ainda não existem — falta "
                                    "aplicar a migration 0057 (uv run python "
                                    "scripts/migrar_schema.py)")}
            cur.execute(
                """SELECT (SELECT count(*) FROM mot_vinculos WHERE ativo) AS ativos,
                          (SELECT count(*) FROM mot_vinculos) AS total,
                          (SELECT count(*) FROM mot_sessoes
                            WHERE encerrada_em IS NULL
                              AND vista_em > now() - interval '7 days') AS vivas,
                          (SELECT count(*) FROM mot_codigos
                            WHERE criado_em > now() - interval '24 hours') AS pedidos,
                          (SELECT max(criada_em) FROM mot_sessoes) AS ultima,
                          -- ACESSO MESTRE: uso e tentativa, SEPARADOS. Um e
                          -- conferencia normal de quem administra; o outro e
                          -- alguem tentando o segredo. Somar os dois faria a
                          -- Saude nao conseguir distinguir "esta sendo usado"
                          -- de "esta sendo atacado".
                          (SELECT count(*) FROM mot_sessoes
                            WHERE mestre
                              AND criada_em > now() - interval '7 days') AS mestres,
                          (SELECT count(*) FROM mot_mestre_tentativas
                            WHERE NOT aceita
                              AND quando > now() - interval '24 hours') AS recusadas""")
            r = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: app do motorista: %s", type(exc).__name__)
        return {"nome": nome, "status": "info", "detalhe": "conferência indisponível"}

    if not r or not r["ativos"]:
        return {"nome": nome, "status": "info",
                "detalhe": ("nenhum motorista vinculado — sem vínculo o app "
                            "recusa todo mundo (uv run python "
                            "scripts/vincular_motoristas.py)")}
    partes = ["%d vinculado(s)" % r["ativos"]]
    if (r["total"] or 0) > r["ativos"]:
        partes.append("%d desligado(s)" % (r["total"] - r["ativos"]))
    partes.append("%d sessão(ões) na semana" % (r["vivas"] or 0))
    partes.append("%d código(s) em 24 h" % (r["pedidos"] or 0))
    if r["ultima"]:
        partes.append("última entrada %s" % _ha_quanto(
            _idade_min(r["ultima"].isoformat())))

    # O ACESSO MESTRE. **Não configurado NÃO é falha**, é instalação
    # incompleta — a mesma regra da integração sem credencial: alarme que não
    # distingue "quebrado" de "ainda não usado" treina todo mundo a ignorar
    # alarme. Mas o silêncio TAMBÉM é defeito aqui: sem esta linha, ninguém
    # descobre que ninguém consegue conferir o app até tentar.
    try:
        from api.motorista import mestre as _mm
        if _mm.configurado():
            partes.append("mestre configurado (%d uso(s) na semana)"
                          % (r["mestres"] or 0))
        else:
            partes.append("mestre NÃO configurado — sem %s no cofre não há "
                          "como conferir o app de um motorista" % _mm.CHAVE)
        if (r["recusadas"] or 0) >= _mm.MAX_TENTATIVAS_HORA:
            # Tentativa recusada NÃO é vermelho sozinha (erro de digitação
            # existe), mas passar do teto de uma hora inteira em 24 h merece
            # ser dito — é o único sinal de que alguém está tentando o segredo.
            partes.append("⚠ %d tentativa(s) recusada(s) em 24 h"
                          % r["recusadas"])
    except Exception as exc:  # noqa: BLE001
        log.info("saude: acesso mestre indisponivel (%s)", type(exc).__name__)

    # O CANAL DO RH. A FILA PARADA e o unico numero que diz se ele esta
    # funcionando — e o escopo do app previa exatamente a falha que ele mede:
    # "um canal que ninguem le". Aqui ela deixa de ser sensacao.
    #
    # AMARELO E NAO VERMELHO: conversa parada e trabalho atrasado de gente, nao
    # sistema quebrado. Vermelho aqui treinaria todo mundo a ignorar o cartao
    # do app do motorista, que e onde mora "o codigo parou de chegar".
    try:
        from api.motorista import conversas as _mc
        c = _mc.contagem()
        if c["total"]:
            partes.append("canal do RH: %d em aberto" % c["vivas"])
            if c["sem_dono"]:
                partes.append("%d sem dono" % c["sem_dono"])
            if c["paradas_3d"]:
                partes.append("⚠ %d parada(s) ha 3+ dias" % c["paradas_3d"])
        # O MURAL: comunicado vivo com ciencia pendente. Nao e alarme — e a
        # unica forma de "publicamos e ninguem confirmou" aparecer sem alguem
        # abrir a tela para procurar.
        from api.motorista import mural as _mu
        m = _mu.contagem()
        if m["vivos"]:
            partes.append("mural: %d comunicado(s) no ar, %d ciencia(s) "
                          "pendente(s)" % (m["vivos"], m["ciencias_pendentes"]))
    except Exception as exc:  # noqa: BLE001
        log.info("saude: canal do RH indisponivel (%s)", type(exc).__name__)

    return {"nome": nome, "status": "ok", "detalhe": " · ".join(partes)}


def _tarja(estado: str, idade: int | None) -> str:
    """O sufixo que diz a IDADE quando a leitura passou do prazo.

    Leitura velha servida calada é pior que tela vazia, porque ninguém
    desconfia dela — a mesma regra da tarja das telas."""
    if estado != "velho" or idade is None:
        return ""
    return " · leitura de %s atrás" % (
        "%d min" % (idade // 60) if idade >= 60 else "%d s" % idade)


def _brl_mi(v: float) -> str:
    """R$ curto, para caber num cartao: milhoes acima de 1 mi, milhares acima
    de mil. Cartao de monitoramento nao e demonstrativo — o centavo exato sai
    no conferidor."""
    a = abs(v)
    sinal = "-" if v < 0 else ""
    if a >= 1_000_000:
        n, u = a / 1_000_000, " mi"
    elif a >= 1_000:
        n, u = a / 1_000, " mil"
    else:
        n, u = a, ""
    # pt-BR: milhar com ponto, decimal com virgula
    return (f"{sinal}R$ " + f"{n:,.2f}".replace(",", "@").replace(".", ",")
            .replace("@", ".") + u)


# 300 s, o mesmo TTL da ACL dos segredos e pela mesma razao: o diagnostico
# custa ~3 s de AVA (cinco consultas, uma delas varre o razao de 12 meses) e a
# Saude repinta de 5 em 5 s. O mapa contabil e editado a mao pela Contabilidade,
# algumas vezes por mes — cinco minutos de atraso num cartao de monitoramento
# nao muda decisao nenhuma, e refazer a varredura a cada pintura muda.
_AGRUPADOR_TTL = 300.0

# 300 s pela mesma razão: a Saúde repinta de 5 em 5 s e a leitura varre o log
# inteiro. Custa 0,03 s, então não é o custo que manda aqui — é que refazer a
# varredura 60 vezes por minuto para um número que muda algumas vezes por dia
# é trabalho que não vira informação.
_JANELAS_TTL = 300.0


def _janelas_medir() -> dict:
    from . import erp_janelas
    return erp_janelas.medir()


_JANELAS = _EmFundo("janelas-erp", _JANELAS_TTL, _janelas_medir)


def _janelas_erp(forcar: bool = False):
    """(medição, estado, idade)."""
    return _JANELAS.ler(esperar=forcar)


def _servico_janelas_erp(d: dict | None, estado: str = "fresco",
                         idade: int | None = None) -> dict:
    """Quantas vezes o ERP teve dia ruim, e a que horas.

    POR QUE ESTE CARTÃO EXISTE. O ERP é réplica de produção de TERCEIRO,
    compartilhada com um Power BI que roda sem `statement_timeout`. Ele derrubou
    a manhã em 03/09/2026 e de novo em 06/09/2026, e nas duas vezes o assunto
    chegou como impressão — "o sistema estava lento hoje de manhã". Impressão
    não sustenta conversa com quem administra o ERP; "24 janelas em 6 dias, 96%
    dos cancelamentos entre 04h e 09h, a pior de 56 minutos" sustenta.

    NÃO ALARMA POR SER ANTIGO. Janela é fato do passado: uma de ontem não é um
    problema de agora, e pintar vermelho por ela treinaria a ignorar o cartão —
    que é o oposto do que ele existe para fazer. Só o que aconteceu nas últimas
    24 h muda a cor.

    Função PURA sobre a medição — o I/O é do `_janelas_erp()`.
    """
    nome = "Janelas ruins do ERP"
    if d is None:
        return {"nome": nome, "status": "info",
                "detalhe": "medindo (primeira leitura desta instância)"}
    if not d.get("legivel"):
        return {"nome": nome, "status": "info",
                "detalhe": d.get("motivo") or "sem log para medir"}

    janelas, ultima = d.get("janelas") or [], d.get("ultima")
    if not janelas:
        return {"nome": nome, "status": "ok",
                "detalhe": "nenhuma desde %s" % (d.get("desde") or "o início do log")}

    partes = ["%d janela(s) desde %s" % (len(janelas), (d.get("desde") or "?")[:16])]
    if ultima:
        # CADA JANELA SE DESCREVE PELO QUE ACONTECEU NELA. Escrever sempre "N
        # consultas canceladas" produzia "0 consulta(s) cancelada(s)" na janela
        # que a rede absorveu inteira — um zero que não é ausência de nada, é o
        # melhor desfecho possível, e lido como número solto não diz isso.
        #
        # E os dois números vão continuar convivendo: desde que 31 consultas
        # ganharam a rede, a degradação que antes virava timeout agora costuma
        # virar leitura velha. Contar só o cancelamento cegaria este cartão
        # justamente porque o portal melhorou.
        efeito = []
        if ultima["timeouts"]:
            efeito.append("%d consulta(s) cancelada(s)" % ultima["timeouts"])
        if ultima["resgates"]:
            efeito.append("%d leitura(s) velha(s) servida(s)" % ultima["resgates"])
        partes.append("última %s–%s (%d min%s)"
                      % (ultima["inicio"][5:], ultima["fim"], ultima["minutos"],
                         ", " + " e ".join(efeito) if efeito else ""))
    # A CONCENTRAÇÃO É O ACHADO. "O ERP é lento" não leva a lugar nenhum; "96%
    # dos cancelamentos caem entre 04h e 09h" aponta uma janela de carga com
    # dono e horário, e é isso que se leva para a conversa.
    if d.get("pct_manha") is not None:
        partes.append("%.0f%% dos cancelamentos entre 04h e 09h" % d["pct_manha"])
    if d.get("resgates"):
        partes.append("a rede segurou %d leitura(s) no período" % d["resgates"])
    return {"nome": nome,
            "status": "alerta" if d.get("janelas_24h") else "ok",
            "detalhe": " · ".join(partes)}


def _agrupador_medir() -> dict:
    from . import agrupador_gerencial as ag
    return ag.diagnostico()


_AGRUPADOR = _EmFundo("agrupador", _AGRUPADOR_TTL, _agrupador_medir)


def _agrupador(forcar: bool = False):
    """(diagnóstico, estado, idade). `forcar` mede na hora — é do conferidor."""
    return _AGRUPADOR.ler(esperar=forcar)


def _servico_agrupador(d: dict | None, estado: str = "fresco",
                       idade: int | None = None) -> dict:
    """O mapa conta -> linha da DRE (`sulista.agrupadorgerencial`) esta sao?

    E uma tabela do ERP, sem chave primaria e sem contrato de tipo, editada a
    mao pela Contabilidade direto no primario — e cinco telas dependem dela
    (DRE Gerencial, Contabilidade, Orcamento, Previsao, Custos). Em 02/09/2026
    ela foi recriada com `grupo` em varchar e com uma conta duplicada: as cinco
    telas morreram e o resultado ficou R$ 1,5 mi diferente do razao, as duas
    coisas em silencio. Este cartao e o fim do silencio.

    Funcao PURA sobre o diagnostico — o I/O e do `_agrupador()`.
    """
    nome = "Mapa contábil (agrupador gerencial)"
    # PRIMEIRA leitura ainda correndo. NÃO é "não sei" e não é "está ruim":
    # o cartão fica, dizendo o que está fazendo. Cartão que some por um minuto
    # ensina que a conferência não existe.
    if d is None:
        return {"nome": nome, "status": "info",
                "detalhe": "medindo (primeira leitura desta instância)"}
    if not d.get("legivel"):
        # O ERP CANCELOU a consulta é carga ALHEIA, não mapa quebrado: o portal
        # é compartilhado com um Power BI sem `statement_timeout`. Acusar o
        # cadastro aqui manda alguém procurar defeito onde não há.
        if d.get("erro") == "QueryCanceled":
            return {"nome": nome, "status": "alerta",
                    "detalhe": "o ERP cancelou a conferência (carga externa no "
                               "portal) — o mapa não foi medido agora"}
        # Nao e "numero torto": e cinco telas sem dado. Vermelho.
        return {"nome": nome, "status": "erro",
                "detalhe": "o mapa não pode ser lido (%s) — DRE Gerencial, "
                           "Contabilidade, Orçamento, Previsão e Custos ficam "
                           "sem dado" % (d.get("erro") or "erro desconhecido")}

    partes = [f"{d['linhas']} classificações em {d['contas']} contas"]
    achados: list[str] = []

    if d.get("grupo_invalido"):
        n = sum(x["linhas"] for x in d["grupo_invalido"])
        achados.append(f"{n} classificação(ões) com empresa não numérica "
                       "(a conta perde o agrupador em silêncio)")
    if d.get("duplicadas"):
        quais = ", ".join(f"{x['grupo']}|{x['reduzido']}" for x in d["duplicadas"][:3])
        achados.append(f"{len(d['duplicadas'])} conta(s) com mais de uma "
                       f"classificação ({quais}) — apagar a antiga no ERP")
    if d.get("orfaos"):
        achados.append(f"{len(d['orfaos'])} classificação(ões) apontando para "
                       "conta que não existe no plano")
    # Conta de BALANCO classificada como custo. Ate 03/09/2026 ela ENTRAVA na
    # DRE, porque a elegibilidade era "tem agrupador OU e conta de resultado" —
    # o Ticket Car (passivo) somava -1,07 mi dentro de CV-COMBUSTIVEL e fazia
    # julho/26 mostrar 299.951,18 onde o proprio ERP mostra 485.176,86.
    #
    # A DRE agora EXIGE conta de resultado e nao se deixa mais contaminar. Este
    # achado mudou de significado por causa disso: ele nao diz mais "o numero
    # esta errado", diz "o CADASTRO esta errado e a DRE esta se defendendo".
    # Continua valendo — classificacao errada e trabalho de alguem, e a conta
    # sem movimento hoje dispara sozinha no dia em que o ERP lancar nela.
    balanco = d.get("balanco") or []
    if balanco:
        com_valor = [x for x in balanco if abs(x["valor"]) > 0.005]
        achados.append(f"{len(balanco)} conta(s) de BALANÇO classificada(s) "
                       f"como custo, {len(com_valor)} com movimento "
                       f"({_brl_mi(d['balanco_valor'])} em {d['meses']} m) — a "
                       "DRE as IGNORA, mas o mapa da Contabilidade segue errado")
    if abs(d.get("divergencia", 0.0)) > 0.01:
        achados.append(f"o resultado por mapa e por estrutural divergem "
                       f"{_brl_mi(d['divergencia'])} em {d['meses_divergentes']} "
                       f"de {d['meses']} meses — é o tamanho do que o mapa "
                       "deixaria entrar se a DRE não filtrasse")

    if not achados:
        partes.append(f"os dois caminhos do resultado fecham em {d['meses']} meses")
        return {"nome": nome, "status": "ok",
                "detalhe": " · ".join(partes) + _tarja(estado, idade)}
    partes.extend(achados)
    partes.append("detalhe em scripts/conferir_agrupador.py")
    return {"nome": nome, "status": "alerta",
            "detalhe": " · ".join(partes) + _tarja(estado, idade)}


def _servico_pedagio_tag() -> dict:
    """A fatura da administradora de tag está sendo importada?

    ESTA LINHA NÃO É DE COLETA, É DE ROTINA HUMANA — e por isso a régua é
    outra. Ninguém pode consertar do lado de cá uma fatura que não chegou: ela
    é baixada do portal do fornecedor e enviada pela tela, uma vez por mês.

    O que a torna digna de um sensor é o mesmo motivo da jornada: o sintoma de
    uma parada é uma ABA VAZIA, que se lê como "esta tela não tem dado" em vez
    de "ninguém importa desde abril". E o gasto é grande — R$ 6,05 mi em 12
    meses, mais do que se cobra de pedágio no CT-e.

    Sem fatura nenhuma é `info`, não erro: é instalação que ainda não começou,
    e vermelho aí ensina a ignorar vermelho. O erro fica para o atraso REAL,
    contado a partir do fechamento da última fatura importada.
    """
    nome = "Pedágio — fatura do tag"
    try:
        from .pedagio import fatura_tag as _ft
        faturas = _ft.faturas()
    except Exception as exc:  # noqa: BLE001
        # Tabela ausente é migration pendente, não avaria: dizer "camada
        # indisponível" mandaria procurar defeito onde falta um `migrar_schema`.
        from . import pglocal as _pg
        if _pg.sem_tabela(exc):
            return {"nome": nome, "status": "info",
                    "detalhe": "migration 0030 ainda não aplicada neste banco"}
        log.warning("saude: pedagio tag: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "camada indisponível"}
    if not faturas:
        return {"nome": nome, "status": "info",
                "detalhe": "nenhuma fatura importada — o gasto do tag existe no "
                           "ERP como um título por mês, sem detalhe por placa"}
    ult = faturas[0]
    fech = ult.get("dt_fechamento")
    dias = (date.today() - fech).days if isinstance(fech, date) else None
    quantas = f"{len(faturas)} fatura(s) · última {ult.get('competencia') or '—'}"
    # A fatura fecha uma vez por mês; 45 dias dá duas semanas de folga sobre o
    # ciclo antes de acusar. Abaixo disso o alarme acenderia todo mês, no
    # intervalo normal entre o fechamento e alguém sentar para importar.
    if dias is not None and dias > 45:
        return {"nome": nome, "status": "erro",
                "detalhe": f"sem fatura nova há {dias} dias · {quantas}"}
    return {"nome": nome, "status": "ok",
            "detalhe": f"{quantas} · {ult.get('travessias_tag') or 0} travessias"}


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


def _servico_tress() -> dict:
    """A 3S está chegando? — e o cartão existe por causa de um silêncio caro.

    Antes da leitura direta, 77 carretas que reportavam à 3S todo dia
    apareciam no painel como "nunca comunicaram", porque o cano do ERP não as
    trazia. Ninguém viu isso por meses: a ausência de dado não faz barulho.
    O cartão vigia a leitura NOVA para que o mesmo silêncio não volte por
    outra porta.

    Vermelho é "não está chegando AGORA" — coleta parada há mais de 3 horas,
    numa cadência de 30 minutos. Contagem de tropeços não vira alarme.
    """
    nome = "3S (rastreamento das carretas)"
    try:
        from .tress import armazenamento as tarm
        from .tress import cliente as tcli
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: 3s: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "camada indisponível"}

    # SEM CREDENCIAL NÃO É FALHA: é instalação incompleta.
    if not tcli.configurado():
        return {"nome": nome, "status": "info",
                "detalhe": "sem credencial (Gestão › Integrações › 3S) — "
                           "a coleta fica desligada"}
    try:
        e = tarm.estado()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: 3s estado: %s", exc)
        return {"nome": nome, "status": "info",
                "detalhe": "banco local indisponível"}

    if not e.get("veiculos"):
        return {"nome": nome, "status": "info",
                "detalhe": "credencial cadastrada, nenhuma coleta ainda"}

    lido = e.get("lido_em")
    horas = ((datetime.now() - lido).total_seconds() / 3600) if lido else None
    detalhe = ("%d veículos na conta · %d com posição de hoje · última leitura "
               "%s" % (e["veiculos"], e.get("hoje") or 0,
                       lido.strftime("%d/%m %H:%M") if lido else "nunca"))
    if e.get("sumidos"):
        detalhe += " · %d saíram da conta" % e["sumidos"]
    if horas is None or horas > 3:
        return {"nome": nome, "status": "erro",
                "detalhe": "a coleta não roda há %s — %s" % (
                    ("%.0f h" % horas) if horas else "muito tempo", detalhe)}
    if not e.get("hoje"):
        return {"nome": nome, "status": "alerta",
                "detalhe": "a coleta roda, mas NENHUM veículo tem posição de "
                           "hoje — " + detalhe}
    return {"nome": nome, "status": "ok", "detalhe": detalhe}


def _servico_smartec() -> dict:
    """A Smartec está chegando — e o acesso ao SNE ainda vale?

    DUAS PERGUNTAS NUMA LINHA SÓ, e a segunda é a que justifica o cartão. O
    acesso ao SENATRAN é um e-CNPJ com validade: expirado, a Smartec para de
    trazer notificação, não se pede boleto pelo SNE e não se indica condutor.
    O sintoma é "parou de chegar multa", que se lê como boa notícia — e por
    isso ele precisa de alarme com ANTECEDÊNCIA, não no dia.

    O limiar é 30 dias porque renovar e-CNPJ não é imediato (há emissão,
    validação e primeiro acesso ao portal). Avisar no dia do vencimento
    avisaria tarde demais para servir de alguma coisa.

    Vermelho é "não está chegando", como nos outros: dado parado ou a ÚLTIMA
    passagem de algum recurso tendo falhado. Recusa isolada no histórico vai
    para o detalhe.
    """
    nome = "Smartec (infrações e licenças)"
    try:
        from .smartec import cliente as scli
        from .smartec import leitura as slei
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: smartec: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "camada indisponível"}

    # SEM TOKEN NÃO É FALHA, é instalação incompleta. Marcar vermelho aqui
    # ensinaria a ignorar o vermelho.
    if not scli.configurado():
        return {"nome": nome, "status": "info",
                "detalhe": "token não configurado (Gestão › Credenciais › "
                           "SMARTEC_TOKEN) — a coleta fica desligada"}
    try:
        e = slei.estado()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: smartec estado: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "banco local indisponível"}

    if not e.get("recursos"):
        return {"nome": nome, "status": "info",
                "detalhe": "token configurado, nenhuma coleta registrada ainda"}

    # O acesso ao SNE vem ANTES da checagem de coleta: ele pode estar válido
    # hoje e vencer amanhã, com a coleta perfeitamente em dia — é justamente
    # esse o caso que só este cartão pega.
    piores = [a for a in (e.get("acessos") or [])
              if a.get("servico") == "sne" and a.get("dias") is not None]
    pior = min(piores, key=lambda a: a["dias"]) if piores else None

    falhando = e.get("falhando") or []
    if falhando:
        quais = ", ".join(f["recurso"] for f in falhando)
        return {"nome": nome, "status": "erro",
                "detalhe": f"última coleta de {quais} falhou"}

    if pior and pior["dias"] < 0:
        return {"nome": nome, "status": "erro",
                "detalhe": f"acesso ao SNE EXPIRADO há {abs(pior['dias'])} dias "
                           f"(CNPJ …{str(pior.get('cnpj') or '')[-6:]}) — "
                           f"notificações param de chegar"}

    ultimo = e.get("ultima_coleta")
    idade = ""
    if ultimo is not None:
        try:
            from datetime import datetime, timezone
            agora = datetime.now(timezone.utc)
            horas = (agora - ultimo).total_seconds() / 3600.0
            idade = f" · última coleta há {horas:.0f} h"
            # Duas janelas de coleta perdidas (a rotina roda de 6 em 6 h).
            if horas > 26:
                return {"nome": nome, "status": "erro",
                        "detalhe": f"sem coleta há {horas / 24:.0f} dias"}
        except Exception:  # noqa: BLE001
            idade = ""

    if pior and pior["dias"] <= 30:
        return {"nome": nome, "status": "alerta",
                "detalhe": f"acesso ao SNE vence em {pior['dias']} dias "
                           f"(CNPJ …{str(pior.get('cnpj') or '')[-6:]}) — "
                           f"renovar o e-CNPJ{idade}"}

    n = sum(int(r.get("itens") or 0) for r in e["recursos"])
    extra = (f" · SNE ok por {pior['dias']} dias" if pior else
             " · sem cadastro no SNE")
    return {"nome": nome, "status": "ok",
            "detalhe": f"{len(e['recursos'])} recursos coletados{idade}{extra}"}


def _servico_xml_email() -> dict:
    """A caixa `xml@sulista.com.br` está sendo lida?

    O QUE ESTE CARTÃO MEDE, E O QUE ELE SE RECUSA A MEDIR
    ----------------------------------------------------

    Ele mede a **execução da coleta**, e não a chegada de e-mail. A diferença
    decide se o alarme presta: numa semana em que ninguém precisou mandar XML,
    a caixa fica vazia — e um cartão que medisse "a mensagem mais recente"
    ficaria vermelho acusando uma rotina que rodou de meia em meia hora sem uma
    falha. Alarme que acende sem haver problema ensina a ignorar alarme.

    Falta de credencial é `info`, não vermelho: é instalação incompleta, e a
    regra da casa é essa em toda integração. Vermelho fica para a coleta que
    RODA E FALHA — token vencido, permissão revogada, caixa renomeada.

    E há um número aqui que não é sobre saúde de integração nenhuma: as
    mensagens que chegaram e **não renderam documento**. Elas não são falha do
    CÓRTEX (o anexo era o PDF do DANFE, ou a pessoa colou o XML no corpo), mas
    são exatamente o caso em que quem mandou acha que mandou e a operação acha
    que não veio. Por isso aparecem aqui.
    """
    nome = "Caixa de XML (e-mail)"
    try:
        from .sefaz import caixa_email
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: caixa de xml: %s", type(exc).__name__)
        return {"nome": nome, "status": "info", "detalhe": "camada indisponível"}

    try:
        e = caixa_email.estado()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: caixa de xml estado: %s", type(exc).__name__)
        return {"nome": nome, "status": "info", "detalhe": "banco local indisponível"}

    arqs = e.get("arquivos") or {}
    guardados = arqs.get("email") or 0

    if not e["configurada"]:
        return {"nome": nome, "status": "info",
                "detalhe": "sem credencial (Administração › Integrações › "
                           "Caixa de XML) — falta: %s. O XML que chega por "
                           "e-mail não entra sozinho enquanto isso"
                           % ", ".join(e.get("falta") or ["credencial"])}

    if e.get("ultimo_erro") and not e.get("ultimo_sucesso"):
        return {"nome": nome, "status": "erro",
                "detalhe": "a coleta nunca terminou bem: %s" % e["ultimo_erro"]}

    if not e.get("ultima_coleta"):
        return {"nome": nome, "status": "info",
                "detalhe": "credencial no cofre, nenhuma coleta ainda — "
                           "a tarefa agendada roda de 30 em 30 minutos"}

    from datetime import datetime, timezone
    horas = None
    try:
        ultimo = datetime.fromisoformat(e["ultimo_sucesso"] or e["ultima_coleta"])
        horas = (datetime.now(timezone.utc) - ultimo).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        horas = None

    idade = " · última coleta há %.0f h" % horas if horas is not None else ""
    vazias = (" · %d mensagem(ns) chegou(aram) sem XML aproveitável"
              % e["vazias"]) if e.get("vazias") else ""

    if e.get("ultimo_erro"):
        return {"nome": nome, "status": "erro",
                "detalhe": "a última coleta falhou: %s%s" % (e["ultimo_erro"], idade)}
    # Quatro janelas perdidas com a tarefa de 30 min. Menos que isso é tropeço
    # de rede, e contagem de tropeço não é alarme.
    if horas is not None and horas > 2:
        return {"nome": nome, "status": "alerta",
                "detalhe": "sem coleta há %.0f h — a tarefa agendada roda de "
                           "30 em 30 min%s" % (horas, vazias)}
    return {"nome": nome, "status": "ok",
            "detalhe": "%s · %d documento(s) guardado(s) por esta porta%s%s"
                       % (e.get("caixa") or "caixa", guardados, idade, vazias)}


def _servico_cnh() -> dict:
    """A CNH e o exame toxicologico dos motoristas estao sendo conferidos?

    ESTE CARTAO NASCEU DE UMA AUSENCIA, e a ausencia era invisivel.

    Exame toxicologico vencido IMPEDE o motorista de dirigir (Lei 13.103), e a
    empresa responde por isso. Ate 08/09/2026 o CORTEX nao conferia nada
    disso: a tabela existia, o recurso existia no catalogo da Smartec, e nao
    havia coletor. Nao havia tela vermelha, nao havia log -- so a falta.

    O cartao mede DUAS coisas, e a separacao delas e o ponto:

      · a coleta rodou? (senao, ninguem perguntou);
      · o que ela trouxe? Medido em 25 condutores, a Smartec devolve o numero
        da CNH e o nome, e NADA do que importa -- vencimento, pontuacao e
        toxicologico vieram nulos em 24 de 24. Isso nao e falha do CORTEX nem
        da coleta: e produto nao habilitado na conta, e o conserto e uma
        conversa com o fornecedor.

    `alerta`, e nao `erro`: o sistema esta funcionando: quem nao esta
    entregando e o fornecedor. Vermelho aqui misturaria uma pendencia
    comercial com uma falha nossa, e quem olha o painel precisa saber para
    quem ligar.
    """
    nome = "CNH e toxicologico (Smartec)"
    try:
        from api.smartec import cliente as scli
        from api.smartec import leitura as slei
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: cnh: %s", type(exc).__name__)
        return {"nome": nome, "status": "info", "detalhe": "camada indisponivel"}

    if not scli.configurado():
        return {"nome": nome, "status": "info",
                "detalhe": "token da Smartec nao configurado"}
    try:
        e = slei.estado_cnh()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: cnh estado: %s", type(exc).__name__)
        return {"nome": nome, "status": "info",
                "detalhe": "banco local indisponivel"}

    if not e["consultados"]:
        return {"nome": nome, "status": "info",
                "detalhe": "nenhum condutor consultado ainda"}

    if e["veredito"].startswith("a Smartec responde"):
        return {"nome": nome, "status": "alerta",
                "detalhe": f"{e['consultados']} condutores consultados e "
                           f"ZERO com vencimento ou toxicologico - o modulo "
                           f"de CNH parece nao habilitado na conta da Smartec"}

    return {"nome": nome, "status": "ok",
            "detalhe": f"{e['com_validade']} de {e['consultados']} condutores "
                       f"com vencimento de CNH, {e['com_toxicologico']} com "
                       f"toxicologico"}


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


def _servico_desempenho() -> dict:
    """Avaliação de Desempenho — o ciclo aberto e a cobertura dele.

    A COBERTURA É O SINAL, não a contagem de avaliações. Um ciclo aberto com
    três notas dadas e um com o quadro inteiro avaliado têm o mesmo "ok" se o
    cartão só contar linhas — e é justamente o primeiro que precisa de alguém
    cobrando gestor.

    E ciclo NENHUM aberto não é falha: é instalação sem uso, ou o intervalo
    entre dois ciclos. Alarme vermelho aí treinaria a ignorar o cartão.
    """
    nome = "Avaliação de Desempenho (nine box)"
    try:
        from . import pglocal
        if not pglocal.configurado():
            return {"nome": nome, "status": "info",
                    "detalhe": "banco local não configurado nesta instalação"}
        r = pglocal.um(
            "SELECT (SELECT count(*) FROM des_ciclo)::int AS ciclos,"
            "       (SELECT count(*) FROM des_gestor)::int AS gestores,"
            "       (SELECT nome FROM des_ciclo WHERE estado='aberto'"
            "         ORDER BY inicio DESC LIMIT 1) AS aberto,"
            "       (SELECT count(*) FROM des_avaliacao a"
            "         JOIN des_ciclo c ON c.id=a.ciclo_id AND c.estado='aberto'"
            "         WHERE a.desempenho IS NOT NULL"
            "           AND a.potencial IS NOT NULL)::int AS avaliados")
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"nome": nome, "status": "erro",
                    "detalhe": "tabelas ausentes — rode "
                               "scripts/migrar_schema.py (migration 0045)"}
        log.warning("saude: desempenho: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "módulo indisponível"}
    if not r["aberto"]:
        return {"nome": nome, "status": "info",
                "detalhe": f"nenhum ciclo aberto · {r['ciclos']} ciclo(s) no "
                           f"histórico, {r['gestores']} gestor(es) mapeado(s)"}
    # SEM MAPA NINGUÉM VÊ NINGUÉM, e um ciclo aberto nessas condições é um
    # ciclo que não vai receber nota nenhuma.
    if not r["gestores"]:
        return {"nome": nome, "status": "alerta",
                "detalhe": f"ciclo “{r['aberto']}” aberto e NENHUM gestor "
                           f"mapeado — ninguém enxerga a própria equipe"}
    return {"nome": nome, "status": "ok",
            "detalhe": f"ciclo “{r['aberto']}” aberto · {r['avaliados']} "
                       f"avaliação(ões) · {r['gestores']} gestor(es) mapeado(s)"}


def _servico_crm() -> dict:
    """Módulo de CRM — contas, oportunidades, atividades e contratos.

    Como a Gestão, não é integração externa: o que pode dar errado é a
    migration não ter sido aplicada nesta instalação, e o sintoma seria a tela
    abrir VAZIA — que se lê como "ainda não usaram" em vez de "está quebrado".
    A linha existe para separar as duas coisas.

    O que vai como ALERTA é só o que pede ação de alguém e não é estado
    normal: lane cotada abaixo do piso mínimo da ANTT (que é ilegal, não
    apenas ruim) e reajuste de contrato com o ciclo vencido (dinheiro na mesa).
    Atividade atrasada NÃO acende aqui: ela é rotina de time comercial, tem
    cartão próprio na tela do CRM, e repeti-la na Saúde ensinaria a ignorar o
    vermelho — o mesmo erro do cartão que ficava vermelho por dois dias com a
    coleta da RasterJOR funcionando.

    A CONTAGEM DE LANES ABAIXO DO PISO É CALCULADA AQUI, e não lida do painel,
    porque `painel.tudo()` fala com o AVA (receita da carteira) e a Saúde
    recarrega a cada 5 s — seria uma consulta ao ERP a cada cinco segundos
    para desenhar uma linha. Aqui é só o banco local; o piso sai da tabela
    ANTT vigente, que é um YAML em memória.
    """
    nome = "CRM (funil comercial)"
    try:
        from . import pglocal
        if not pglocal.configurado():
            return {"nome": nome, "status": "info",
                    "detalhe": "banco local não configurado nesta instalação"}
        r = pglocal.um(
            "SELECT (SELECT count(*) FROM crm_contas WHERE arquivada=0)::int AS contas,"
            "       (SELECT count(*) FROM crm_oportunidades"
            "         WHERE estagio NOT IN ('ganha','perdida'))::int AS abertas,"
            "       (SELECT count(*) FROM crm_contratos"
            "         WHERE cancelado_em IS NULL"
            "           AND (fim IS NULL OR fim >= current_date))::int AS contratos,"
            "       (SELECT count(*) FROM crm_projetos"
            "         WHERE status IN ('nao_iniciado','implantacao','em_execucao')"
            "        )::int AS projetos,"
            "       (SELECT count(*) FROM crm_projetos"
            "         WHERE status IN ('nao_iniciado','implantacao','em_execucao')"
            "           AND deadline IS NOT NULL"
            "           AND deadline < current_date)::int AS proj_atrasados")
        lanes = pglocal.query(
            "SELECT l.km, l.eixos, l.tipo_carga, l.valor_viagem"
            "  FROM crm_lanes l"
            "  JOIN crm_oportunidades o ON o.id = l.oportunidade_id"
            " WHERE o.estagio NOT IN ('ganha','perdida')"
            "   AND l.km IS NOT NULL AND l.eixos IS NOT NULL"
            "   AND l.tipo_carga <> '' AND l.valor_viagem IS NOT NULL")
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"nome": nome, "status": "erro",
                    "detalhe": "tabelas ausentes — rode "
                               "scripts/migrar_schema.py (migration 0026)"}
        log.warning("saude: crm: %s", exc)
        return {"nome": nome, "status": "info", "detalhe": "módulo indisponível"}

    abaixo = 0
    try:
        from datetime import date as _d

        from .antt.piso import avaliar, calcular_piso
        hoje = _d.today()
        for l in lanes:
            p = avaliar(float(l["valor_viagem"]),
                        calcular_piso(float(l["km"]), l["tipo_carga"],
                                      l["eixos"], hoje))
            if p.get("abaixo"):
                abaixo += 1
    except Exception as exc:  # noqa: BLE001
        # Sem a tabela da ANTT o módulo continua funcionando: o que se perde é
        # a conferência do piso, e dizer isso é melhor que omitir a linha.
        log.warning("saude: crm piso: %s", exc)
        abaixo = None

    try:
        reaj = pglocal.query(
            "SELECT inicio, mes_reajuste, ultimo_reajuste FROM crm_contratos"
            " WHERE cancelado_em IS NULL AND mes_reajuste IS NOT NULL")
    except Exception:  # noqa: BLE001
        reaj = []
    pendentes = 0
    from datetime import date as _dd
    hj = _dd.today()
    for c in reaj:
        mes = int(c["mes_reajuste"])
        ciclo = _dd(hj.year if hj.month >= mes else hj.year - 1, mes, 1)
        if c["inicio"] and c["inicio"] >= ciclo:
            continue
        if c["ultimo_reajuste"] is None or c["ultimo_reajuste"] < ciclo:
            pendentes += 1

    if not r["contas"]:
        return {"nome": nome, "status": "info",
                "detalhe": "pronto para uso · nenhuma conta cadastrada ainda"}
    base = (f"{r['contas']} conta(s) · {r['abertas']} oportunidade(s) aberta(s) "
            f"· {r['contratos']} contrato(s) vigente(s) "
            f"· {r['projetos']} projeto(s) em andamento")
    problemas = []
    # Projeto com o prazo estourado é o cliente esperando uma implantação que
    # já deveria estar no ar — vermelho de verdade, não estado normal.
    if r["proj_atrasados"]:
        problemas.append(f"{r['proj_atrasados']} projeto(s) com prazo estourado")
    if abaixo:
        problemas.append(f"{abaixo} lane(s) cotada(s) abaixo do piso ANTT")
    if pendentes:
        problemas.append(f"{pendentes} reajuste(s) de contrato vencido(s)")
    if abaixo is None:
        base += " · piso ANTT não conferido (tabela de coeficientes indisponível)"
    if problemas:
        return {"nome": nome, "status": "alerta",
                "detalhe": " · ".join(problemas) + " · " + base}
    return {"nome": nome, "status": "ok", "detalhe": base}


def _servico_suporte_de(d: dict) -> dict:
    """Função pura sobre o diagnóstico do módulo — testável sem banco.

    ALERTA só para o que pede ação AGORA: SLA estourado, chamado com o suporte
    sem atendente, WhatsApp adiado vencido há mais de 4 h (a passagem roda a
    cada 15 min) ou a ÚLTIMA chamada ao GitHub recusada. Sem credencial do
    GitHub é `info` (instalação incompleta), nunca vermelho.
    """
    nome = "Suporte (chamados)"
    if not d.get("ok"):
        if d.get("sem_tabela"):
            return {"nome": nome, "status": "erro",
                    "detalhe": "tabelas ausentes — rode scripts/migrar_schema.py (migration 0037)"}
        return {"nome": nome, "status": "info", "detalhe": "módulo indisponível"}
    k = d.get("kpis") or {}
    gh = d.get("github_ultimo") or {}
    partes = [f"{k.get('abertos', 0)} aberto(s)", f"{k.get('com_suporte', 0)} com o suporte",
              f"{k.get('aguardando_usuario', 0)} aguardando usuário"]
    if d.get("ultimo_aviso_em"):
        partes.append("último aviso " + str(d["ultimo_aviso_em"])[:16].replace("T", " "))
    problemas = []
    if k.get("sla_estourados"):
        problemas.append(f"{k['sla_estourados']} fora do SLA")
    if k.get("sem_atendente"):
        problemas.append(f"{k['sem_atendente']} sem atendente")
    if d.get("adiados_vencidos"):
        problemas.append(f"{d['adiados_vencidos']} aviso(s) de WhatsApp parado(s) há mais de 4 h")
    if gh.get("resultado") == "recusado":
        problemas.append("espelho GitHub: a última chamada falhou — " + str(gh.get("detalhe") or "")[:80])
    elif gh.get("resultado") == "sem_canal":
        partes.append("espelho GitHub desligado")
    if problemas:
        return {"nome": nome, "status": "alerta", "detalhe": " · ".join(problemas + partes)}
    if not k.get("abertos"):
        return {"nome": nome, "status": "ok", "detalhe": "pronto para uso · nenhum chamado aberto"}
    return {"nome": nome, "status": "ok", "detalhe": " · ".join(partes)}


def _servico_suporte() -> dict:
    try:
        from . import pglocal
        if not pglocal.configurado():
            return {"nome": "Suporte (chamados)", "status": "info",
                    "detalhe": "banco local não configurado nesta instalação"}
        from .suporte import chamados
        return _servico_suporte_de(chamados.diagnostico())
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: suporte: %s", type(exc).__name__)
        return {"nome": "Suporte (chamados)", "status": "info", "detalhe": "módulo indisponível"}


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
    esp = d.get("espelho") or {}
    esp_txt = ""
    if esp.get("quando"):
        esp_txt = (f" · espelho {esp.get('gravados', 0):,} recebíveis"
                   .replace(",", ".")
                   + (" (última varredura FALHOU)" if esp.get("erro") else ""))
    return {"nome": nome, "status": "alerta" if (hmg or velha) else "ok",
            "detalhe": f"{d['titulos']} títulos em aberto · R$ {valor} · "
                       f"coletado {_ha_quanto(idade)}" + esp_txt
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
    # RAÍZES DE CERTIFICADO, e não é curiosidade: o padrão deste Windows tem
    # 45 (o que o armazém cacheou), e fornecedor com CA fora dessa lista falha
    # com "self-signed certificate in certificate chain" — mensagem que manda
    # procurar proxy onde não há nenhum. Foi assim com a TomTom, cujo
    # certificado é legítimo. Ter o número na tela responde a primeira
    # pergunta de qualquer erro de certificado.
    try:
        from . import tls as _tls
        d = _tls.diagnostico()
        api["detalhe"] += " · %s raízes TLS (%s)" % (d["raizes"], d["fonte"])
        if d["fonte"] != "certifi":
            api["status"] = "alerta"
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

    # AUDITORIA DE USO. Fica junto do banco da casa, que e onde ela grava.
    try:
        from . import auditoria as _aud
        servicos.append(_servico_auditoria(_aud.diagnostico()))
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Auditoria de uso (trilha)", "status": "info",
                         "detalhe": "camada indisponível"})
        log.warning("saude: auditoria: %s", exc)

    # PORTAL DO CLIENTE. Fica junto da auditoria porque a pergunta e da mesma
    # familia: quem esta entrando, e com que alcance.
    try:
        servicos.append(_portal_cliente())
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Portal do cliente (Minha Operação)",
                         "status": "info", "detalhe": "conferência indisponível"})
        log.warning("saude: portal do cliente: %s", exc)
    # MONITORAMENTOS DE CARGA. Fica junto da auditoria porque grava no mesmo
    # banco da casa — e porque a falha das duas é do mesmo tipo: muda.
    try:
        from .rastreio import painel as _mon
        servicos.append(_servico_monitoramentos(_mon.painel().get("resumo")))
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Monitoramentos de carga (aviso ao cliente)",
                         "status": "info", "detalhe": "camada indisponível"})
        log.warning("saude: monitoramentos: %s", exc)

    # APP DO MOTORISTA. Junto do portal do cliente porque a pergunta e a mesma
    # familia — quem entra de FORA da casa —, e porque nos dois o silencio e o
    # defeito: ninguem daqui abre essas telas para descobrir que quebraram.
    try:
        servicos.append(_app_motorista())
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "App do motorista", "status": "info",
                         "detalhe": "conferência indisponível"})
        log.warning("saude: app do motorista: %s", exc)

    # MAPA CONTÁBIL do ERP. Vem logo depois dos bancos porque é a mesma
    # pergunta um nível acima: o banco responde, mas o que ele responde ainda
    # serve? A tabela é de terceiro, sem chave nem contrato de tipo, e derrubou
    # cinco telas em 02/09/2026 sem que nada acusasse.
    try:
        servicos.append(_servico_agrupador(*_agrupador()))
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Mapa contábil (agrupador gerencial)",
                         "status": "info", "detalhe": "conferência indisponível"})
        log.warning("saude: agrupador gerencial: %s", exc)

    # O ERP como DEPENDÊNCIA, e não como banco: o cartão acima diz se o que ele
    # responde ainda serve; este diz com que frequência ele deixa de responder.
    # Duas manhãs derrubadas em quatro dias viraram "o sistema estava lento", e
    # impressão não sustenta conversa com quem administra o ERP.
    try:
        servicos.append(_servico_janelas_erp(*_janelas_erp()))
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Janelas ruins do ERP",
                         "status": "info", "detalhe": "medição indisponível"})
        log.warning("saude: janelas do erp: %s", exc)

    # Gestão: mora no banco local, então vem logo depois dele. A tela vazia por
    # migration faltando é indistinguível de tela vazia por falta de uso — esta
    # linha é o que separa as duas.
    servicos.append(_servico_gestao())
    servicos.append(_servico_desempenho())
    # CRM: mesma razão da Gestão — mora no banco local e a tela vazia por
    # migration faltando é indistinguível de tela vazia por falta de uso.
    servicos.append(_servico_crm())
    servicos.append(_servico_suporte())
    servicos.append(_servico_premiacao())

    # Jornada: vem do AVA, não do banco local — mas a pergunta é a mesma
    # (o dado está chegando?), então fica ao lado.
    servicos.append(_servico_jornada())

    # Smartec: infrações e licenças. O cartão vigia DUAS coisas — a coleta
    # e o vencimento do acesso ao SNE, que desliga a integração em silêncio.
    servicos.append(_servico_smartec())

    # CNH e toxicologico: cartao PROPRIO, separado do da Smartec, porque a
    # pergunta e outra e o dono do conserto e outro. A coleta de infracao pode
    # estar perfeita com a de CNH nao entregando nada -- e foi exatamente o
    # que se encontrou.
    servicos.append(_servico_cnh())

    # 3S: a leitura direta das carretas. O cartão nasceu com a integração
    # porque a falha dela é MUDA — some posição e o painel só fica pior.
    servicos.append(_servico_tress())

    # A CAIXA DE XML: a segunda porta da recolha. O cartao nasce com ela porque
    # a falha dela e MUDA -- o remetente manda, ninguem recebe, e a nota que
    # faltava continua faltando sem ninguem saber por que.
    servicos.append(_servico_xml_email())

    # Pedágio do tag: a fatura é BAIXADA e ENVIADA por gente, uma vez por mês.
    # O sensor existe porque a parada se disfarça de aba vazia — e o gasto é
    # maior que o pedágio cobrado do cliente no CT-e.
    servicos.append(_servico_pedagio_tag())

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

    # REPLICA DE PNEUS (banco próprio). A Prolog está sendo substituída: ela
    # alimenta as tabelas `pne_*` até ser desligada. Esta linha existe porque a
    # replicação é a única parte que pode parar SEM NINGUÉM PERCEBER — o painel
    # continua lendo o instantâneo e mostrando número fresco enquanto o banco
    # que vai sobreviver ao desligamento envelhece calado.
    try:
        from .pneus import replica as pneus_rep
        e = pneus_rep.estado()
        if e.get("erro"):
            servicos.append({"nome": "Réplica de pneus", "status": "info",
                             "detalhe": "banco da casa indisponível"})
        elif not e.get("pneus"):
            servicos.append({"nome": "Réplica de pneus", "status": "alerta",
                             "detalhe": "nenhum pneu replicado ainda"})
        else:
            falhas = [s for s in (e.get("sync") or []) if s.get("ultimo_erro")]
            det = (f"{e['pneus']} pneus · {e.get('eventos') or 0} evento(s)")
            if e.get("mais_antigo"):
                det += f" desde {str(e['mais_antigo'])[:10]}"
            if falhas:
                det += f" · {len(falhas)} rota(s) com erro na última passada"
            servicos.append({
                "nome": "Réplica de pneus",
                # Erro na última passada é INFORMAÇÃO, não alarme: a cota da
                # Prolog estoura por construção e se recompõe sozinha. O que
                # seria alarme é ficar sem evento nenhum.
                "status": "alerta" if not e.get("eventos") else "ok",
                "detalhe": det})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Réplica de pneus", "status": "info",
                         "detalhe": "não foi possível medir (%s)"
                                    % type(exc).__name__})

    # CPK E PREVISÃO DE TROCA: o que SOBREVIVE ao desligamento da Prolog.
    #
    # Cartão próprio, e não uma linha do anterior, porque ele mede outra coisa.
    # A réplica pergunta "o retrato está chegando?"; este pergunta "o número que
    # decide compra ainda sai?". Eles falham por motivos diferentes — o CPK sai
    # do banco da casa cruzado com o ERP, então ele cai quando o ERP cai, não
    # quando a cota da Prolog estoura.
    #
    # A CONFERÊNCIA É O QUE VIRA ALARME, não a existência do número: carreta
    # tem de rodar menos que cavalo, e o dia em que essa razão passar de 100%
    # o CPK inteiro está contando km duas vezes — com números perfeitamente
    # plausíveis, que é o que torna isso perigoso.
    try:
        from .pneus import cpk as pneus_cpk
        from .pneus import km as pneus_km
        d = pneus_cpk.obter()
        c = pneus_km.conferir()
        det = ("%d pneus avaliados · CPK mediano R$ %.4f/km · km confere em %s%%"
               % (d.get("avaliados") or 0, d.get("cpk_mediano") or 0,
                  c.get("razao_pct")))
        if d.get("sem_custo"):
            det += " · %d sem custo no cadastro" % d["sem_custo"]
        if d.get("leitura_velha"):
            det += " · LEITURA DE %s" % d.get("leitura_em")
        servicos.append({
            "nome": "Pneus — CPK e km",
            "status": ("alerta" if not c.get("ok") or not d.get("avaliados")
                       else "ok"),
            "detalhe": det})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Pneus — CPK e km", "status": "info",
                         "detalhe": "não foi possível calcular (%s)"
                                    % type(exc).__name__})

    # AS TABELAS DE DOMINIO, e este cartao existe por causa do PRAZO. Elas sao
    # o que a casa precisa ter ANTES de a Prolog sair: sem os diagramas nao ha
    # como validar posicao, e sem os motivos o `pne_evento.motivo` fica sendo um
    # codigo que so ela sabe ler. Nada aqui alarma no dia a dia — o alarme e
    # estar VAZIO, porque vazio quer dizer que a copia nunca aconteceu.
    try:
        from .pneus import cadastro as pneus_cad
        e = pneus_cad.estado()
        if e.get("erro"):
            servicos.append({"nome": "Pneus — tabelas de domínio",
                             "status": "info",
                             "detalhe": "banco da casa indisponível"})
        else:
            mot = sum((e.get("motivos") or {}).values())
            servicos.append({
                "nome": "Pneus — tabelas de domínio",
                "status": "alerta" if not e.get("diagramas") else "ok",
                "detalhe": ("%d diagrama(s) de eixo · %d motivo(s) de descarte"
                            % (e.get("diagramas") or 0, mot))})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Pneus — tabelas de domínio", "status": "info",
                         "detalhe": "não foi possível medir (%s)"
                                    % type(exc).__name__})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "Réplica de pneus", "status": "info",
                         "detalhe": "indisponível"})
        log.warning("saude: replica de pneus: %s", exc)

    # RasterIntegra (Gerenciamento de Risco): sem credencial e instalacao
    # incompleta (info); com credencial, prova de vida com cache de 10 min
    try:
        from api.rasterintegra import diagnostico as _gr_diag
        _d = _gr_diag.diagnostico()
        if not _d.get("configurado"):
            servicos.append({"nome": "RasterIntegra (ger. de risco)",
                             "status": "info",
                             "detalhe": "sem credencial — cadastrar em "
                                        "Gestão › Integrações (exclusiva do "
                                        "CÓRTEX, nunca a do ERP)"})
        elif _d.get("ok"):
            _c = _d.get("coleta")
            if _c is None:
                # banco local sem veredito: a prova de vida do webservice
                # continua valendo sozinha
                _txt, _st = "webservice respondendo", "ok"
            elif not _c.get("rodou"):
                _txt = ("webservice respondendo — aguardando a primeira "
                        "coleta (tarefa das 04:40)")
                _st = "info"
            elif _c.get("atrasada"):
                _txt = (f"webservice responde, mas a última coleta foi "
                        f"{_c.get('ultima')} — a tarefa das 04:40 não rodou")
                _st = "alerta"
            else:
                _txt = f"coletando — última carga {_c.get('ultima')}"
                _st = "ok"
            servicos.append({"nome": "RasterIntegra (ger. de risco)",
                             "status": _st, "detalhe": _txt})
        else:
            servicos.append({"nome": "RasterIntegra (ger. de risco)",
                             "status": "alerta",
                             "detalhe": _d.get("erro") or "sem resposta"})
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "RasterIntegra (ger. de risco)",
                         "status": "info", "detalhe": "diagnóstico indisponível"})
        log.warning("saude: rasterintegra: %s", exc)

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

    # TomTom — NÃO CONSULTA A API. Toda chamada gasta cota, e a Saúde recarrega
    # a cada 5 s: perguntar à TomTom para desenhar um cartão queimaria o limite
    # diário sem medir nada de útil. O que se mede é a CONFIGURAÇÃO, que é onde
    # os problemas desta integração moram — e o principal deles é silencioso:
    # a chave do mapa restrita por domínio funciona no navegador e devolve 403
    # no servidor, o que se lê como "chave errada".
    try:
        from .tomtom import cliente as tomtom
        if not tomtom.configurado():
            servicos.append({
                "nome": "TomTom (trânsito)", "status": "info",
                "detalhe": "não configurada — falta a chave de API "
                           "(Gestão › Integrações)"})
        elif tomtom.usando_a_chave_do_mapa():
            servicos.append({
                "nome": "TomTom (trânsito)", "status": "info",
                "detalhe": "usando a chave do MAPA na coleta — se ela estiver "
                           "restrita por domínio no painel da TomTom, o "
                           "servidor recebe 403; configure a chave da coleta"})
        else:
            servicos.append({"nome": "TomTom (trânsito)", "status": "ok",
                             "detalhe": "chave própria de servidor configurada"})
        # O CONSUMO, porque o LIMITE não é observável: nenhuma resposta da
        # TomTom traz cabeçalho de cota (medido nas três famílias de
        # endpoint), e o teto só existe no painel deles. Se não dá para ver o
        # limite, o mínimo honesto é ver o gasto.
        try:
            from .tomtom import coleta as _ttc
            c = _ttc.consumo(dias=1)
            if c.get("hoje") is not None:
                servicos[-1]["detalhe"] += " · %s chamada(s) hoje" % c["hoje"]
                if c.get("erros_hoje"):
                    servicos[-1]["detalhe"] += " · %s com erro" % c["erros_hoje"]
                    servicos[-1]["status"] = "alerta"
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        servicos.append({"nome": "TomTom (trânsito)", "status": "info",
                         "detalhe": "integração indisponível"})
        log.warning("saude: tomtom: %s", exc)

    # Túnel Cloudflare
    n = _processo_cloudflared()
    servicos.append({
        "nome": "Túnel Cloudflare", "status": "ok" if n else "alerta",
        "detalhe": f"{n} conector(es) ativo(s)" if n else "cloudflared não está rodando"})

    # Túnel ngrok — porta secundária, some do cartão quando não existe aqui
    try:
        ng = _servico_ngrok()
        if ng:
            servicos.append(ng)
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: ngrok falhou: %s", exc)

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


def _tarefas(forcar: bool = False) -> list[dict]:
    """Estado + última/próxima execução das tarefas agendadas do CÓRTEX.

    Usa Get-ScheduledTaskInfo (dados estruturados, independentes de idioma) em
    vez de parsear o texto localizado do schtasks. Best-effort: sem PowerShell
    (ex.: dev no Mac) devolve só os nomes."""
    return _TAREFAS_EM_FUNDO.ler(esperar=forcar)


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


_TAREFAS_EM_FUNDO = _EmFundo("tarefas", _TAREFAS_TTL, lambda: _tarefas_consultar())


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


_SEGREDOS_TTL = 300.0


def _segredos(forcar: bool = False) -> dict:
    """A proteção dos arquivos de segredo — MEDIDA, não afirmada.

    POR QUE ESTE CARTÃO EXISTE
    ==========================
    O CÓRTEX dizia, em cinco lugares do código e no próprio CLAUDE.md, que os
    arquivos de segredo nascem com permissão 0600. **No Windows isso não
    protege nada**: `chmod` só liga o atributo somente-leitura, e quem decide
    acesso é a ACL. O servidor é Windows.

    Ao conferir, o achado foi melhor do que o temido e pior do que parecia: os
    arquivos ESTÃO restritos a SYSTEM e ao dono — mas por HERANÇA da pasta do
    usuário, não porque alguém pediu. Proteção por acidente sobrevive até o dia
    em que o projeto mudar de lugar, e ninguém saberia.

    TTL DE 5 MINUTOS porque cada leitura de ACL abre um PowerShell, e a Saúde
    recarrega a cada 5 s: sem o cache seriam ~5 processos por segundo para
    desenhar um cartão que muda quando alguém salva uma credencial. Mesmo
    motivo do cache do agendador e do estado da Z-API.
    """
    return _SEGREDOS.ler(esperar=forcar)


def _segredos_medir() -> dict:
    from api import segredo_arquivo
    return segredo_arquivo.panorama()


_SEGREDOS = _EmFundo("segredos", _SEGREDOS_TTL, _segredos_medir)


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
    # `medindo` nomeia o que ainda está na PRIMEIRA leitura desta instância.
    # Sem ele a tela diria "não foi possível verificar" para uma medição que
    # está correndo agora — e isso é acusação, não informação.
    medindo: list[str] = []
    try:
        dados["segredos"], est, _i = _segredos()
        if est == "medindo":
            medindo.append("segredos")
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: segredos falhou: %s", exc)
        dados["segredos"] = None
    try:
        dados["migradas"] = _migradas()
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: resumo das migradas falhou: %s", exc)
        dados["migradas"] = None
    try:
        tarefas, est, _i = _tarefas()
        dados["tarefas"] = tarefas or []
        if est == "medindo":
            medindo.append("tarefas")
    except Exception as exc:  # noqa: BLE001
        dados["tarefas"] = []
    try:
        dados["deploy"] = ({"status": "info", "detalhe": "medindo o agendador"}
                           if "tarefas" in medindo
                           else _deploy_saude(dados.get("tarefas", [])))
    except Exception as exc:  # noqa: BLE001
        log.warning("saude: deploy falhou: %s", exc)
        dados["deploy"] = {}
    dados["medindo"] = medindo
    return dados
