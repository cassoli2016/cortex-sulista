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


def main() -> int:
    from api.gobrax import estatisticas, odometro
    from api.gobrax.cliente import (GobraxIndisponivel, GobraxNaoConfigurado,
                                    configurado)

    if not configurado():
        log.error("token da Gobrax nao configurado — nada a coletar")
        return 1

    houve_erro = False
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

    log.info("coleta encerrada%s", " com falhas" if houve_erro else " sem falhas")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log.exception("falha inesperada: %s", exc)
        sys.exit(1)
