"""Coleta a telemetria da Gobrax e grava no cache local.

Roda pelo Agendador do Windows (tarefa "Cortex Sulista - Telemetria"). Existe
porque a coleta NÃO tinha quem a disparasse: as funções `sincronizar()` só
rodavam quando alguém abria uma tela com `force`, e o cache ficou cinco dias
parado sem ninguém perceber — a Torre mostrava telemetria de 19/08 ao lado de
posições ao vivo.

Não chama o endpoint HTTP de propósito: a API pode estar reiniciando (o
AutoDeploy a derruba a cada deploy) e a coleta perderia a janela. Fala direto
com o módulo, como o AutoDeploy fala direto com o git.

Duas competências por execução: a do mês corrente e a do mês anterior. O mês
anterior porque a Gobrax fecha dados com atraso — rodar só o corrente deixaria
o último dia do mês passado incompleto para sempre, já que ninguém volta lá.

Nunca levanta: o Agendador registra o código de saída, e uma exceção não
tratada viraria "0x1" sem explicação no log. Sai com 0 mesmo em falha de rede
(a coleta anterior continua válida) e com 1 só quando a configuração está
errada — que é o que exige alguém agir.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG = ROOT / "logs" / "telemetria.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger("telemetria")


def competencias(hoje: date) -> list[str]:
    """Mês corrente e o anterior, do mais recente para o mais antigo."""
    atual = f"{hoje.year:04d}-{hoje.month:02d}"
    if hoje.month == 1:
        ant = f"{hoje.year - 1:04d}-12"
    else:
        ant = f"{hoje.year:04d}-{hoje.month - 1:02d}"
    return [atual, ant]


def _ja_coletou_hoje(colecao: str, horas: int = 20) -> bool:
    """A trava da varredura diaria, lida do proprio cache.

    Menos de `horas` desde a ultima coleta = pula. Guardar a decisao no cache
    (e nao num arquivo de carimbo) faz a trava sobreviver a qualquer coisa que
    apague estado solto, e mantem UMA fonte da verdade sobre quando a coleta
    aconteceu -- a mesma que a Saude le.
    """
    from datetime import datetime
    from api.gobrax import armazenamento
    u = armazenamento.ultima(colecao)
    if not u or not u.get("quando"):
        return False
    try:
        q = datetime.fromisoformat(str(u["quando"]).replace("T", " ")[:19])
    except ValueError:
        return False
    return (datetime.now() - q).total_seconds() < horas * 3600


def main() -> int:
    from api.gobrax import estatisticas, odometro
    from api.gobrax.cliente import (GobraxIndisponivel, GobraxNaoConfigurado,
                                    configurado)

    if not configurado():
        log.error("token da Gobrax nao configurado — nada a coletar")
        return 1

    # --backfill AAAA-MM: coleta UM mes antigo (estatisticas + odometro +
    # performance) para alongar o historico da evolucao mensal. Mes a mes de
    # proposito — janela de 12 meses estoura o timeout da API (medido, ver
    # api/gobrax/cliente.py). Rodar uma vez por mes desejado e pronto:
    # a gravacao e idempotente (substitui a competencia inteira).
    import sys as _sys
    if "--backfill" in _sys.argv:
        comp = _sys.argv[_sys.argv.index("--backfill") + 1]
        import re as _re
        if not _re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", comp):
            log.error("--backfill exige AAAA-MM (veio %r)", comp)
            return 1
        from api.gobrax import performance as _perf
        ok = True
        for nome, mod in (("estatisticas", estatisticas),
                          ("odometro", odometro), ("performance", _perf)):
            try:
                r = mod.sincronizar(comp)
                log.info("backfill %s %s: %s registro(s)", nome, comp, r["gravadas"])
            except Exception as exc:  # noqa: BLE001
                log.warning("backfill %s %s falhou (%s: %s)", nome, comp,
                            type(exc).__name__, exc)
                ok = False
        return 0 if ok else 1

    houve_erro = False

    # COMUNICACAO: uma chamada so, 0,5 s, e entra no ciclo de 3 h porque o
    # alarme e "esta calado AGORA" -- um retrato de ontem responderia outra
    # pergunta. Fora do laco de competencias porque e um retrato do instante,
    # nao um acumulado mensal.
    try:
        from api.gobrax import comunicacao
        r = comunicacao.sincronizar()
        log.info("comunicacao: %s veiculo(s) com posicao", r["gravadas"])
    except GobraxIndisponivel as exc:
        log.warning("comunicacao: Gobrax indisponivel (%s)", exc)
        houve_erro = True
    except Exception as exc:  # noqa: BLE001
        log.warning("comunicacao: falhou (%s: %s)", type(exc).__name__, exc)
        houve_erro = True

    for comp in competencias(date.today()):
        for nome, mod in (("estatisticas", estatisticas), ("odometro", odometro)):
            try:
                r = mod.sincronizar(comp)
                log.info("%s %s: %s registro(s)", nome, comp, r["gravadas"])
            except GobraxNaoConfigurado:
                log.error("%s %s: token invalido", nome, comp)
                return 1
            except GobraxIndisponivel as exc:
                # rede/instabilidade do fornecedor: a coleta anterior continua
                # valendo e a proxima execucao tenta de novo
                log.warning("%s %s: Gobrax indisponivel (%s)", nome, comp, exc)
                houve_erro = True
            except Exception as exc:  # noqa: BLE001
                log.warning("%s %s: falhou (%s: %s)", nome, comp,
                            type(exc).__name__, exc)
                houve_erro = True

    # ── indicadores de conducao: UMA VEZ POR DIA ─────────────────────────
    # Nao entra no laco acima porque tem custo diferente: uma chamada POR
    # PLACA (108 contra 1). De 3 em 3 h seriam ~860 requisicoes diarias ao
    # fornecedor para um acumulado mensal que mal se move nesse intervalo.
    #
    # A trava e o PROPRIO CACHE, nao um relogio a parte: se a ultima coleta
    # tem menos de 20 h, pula. Assim a tarefa continua sendo uma so, sem
    # instalador novo no Agendador, e uma execucao perdida se recupera na
    # seguinte em vez de esperar 24 h exatas.
    if not _ja_coletou_hoje("performance"):
        from api.gobrax import performance
        for comp in competencias(date.today()):
            try:
                r = performance.sincronizar(comp)
                log.info("performance %s: %s veiculo(s)", comp, r["gravadas"])
            except GobraxIndisponivel as exc:
                log.warning("performance %s: Gobrax indisponivel (%s)", comp, exc)
                houve_erro = True
            except Exception as exc:  # noqa: BLE001
                log.warning("performance %s: falhou (%s: %s)", comp,
                            type(exc).__name__, exc)
                houve_erro = True
    else:
        log.info("performance: coletada ha menos de 20 h — pulando")

    log.info("coleta encerrada%s", " com falhas" if houve_erro else " sem falhas")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log.exception("falha inesperada: %s", exc)
        sys.exit(1)
