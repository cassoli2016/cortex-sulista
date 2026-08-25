"""Coleta os pneus da Prolog e grava o instantaneo (tarefa agendada).

    uv run python scripts/coletar_pneus.py            # tudo
    uv run python scripts/coletar_pneus.py INSTALLED  # so os rodando

Existe porque a coleta completa custa ~86 requisicoes e a API tem cota: a tela
le o instantaneo, nao a API.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.pneus import cliente as cli
from api.pneus import coleta

alvos = [a.upper() for a in sys.argv[1:] if a.upper() in cli.STATUS] or None
print(f"coletando {alvos or 'todos os status'} das filiais "
      f"{cli.filiais_configuradas()}...")
try:
    r = coleta.coletar(status=alvos)
except cli.PrologNaoConfigurado as exc:
    print("NAO CONFIGURADO:", exc)
    raise SystemExit(1)
except cli.PrologIndisponivel as exc:
    print("FALHOU:", exc)
    raise SystemExit(2)

k = r["kpis"]
# As chaves do retorno mudaram quando a coleta virou retomavel e este resumo
# ficou para tras: quebrava com KeyError DEPOIS de coletar, entao o instantaneo
# era gravado e a tarefa terminava em erro assim mesmo — o pior dos dois mundos,
# porque o log dizia "falhou" sobre um trabalho que deu certo.
print(f"OK em {r['segundos']}s · {r['paginas_lidas']} pagina(s) lida(s)"
      + ("  [PAROU POR COTA]" if r["parou_por_cota"] else ""))
print(f"  acumulado {r['acumulado']} de {r['total_na_api']} · "
      f"+{r['novos']} novo(s) · cursor em {r['cursor']} · "
      f"{r['voltas']} volta(s) completa(s)")
print(f"  {k['total']} pneus · {k['rodando']} rodando · "
      f"{k['abaixo_legal']} abaixo do legal ({k['abaixo_legal_direcional']} direcional)")
print(f"  sulco medido em {k['sulco_cobertura']} de {k['rodando']} · "
      f"CPK em {k['cpk_cobertura']} de {k['total']}")
print(f"  por situacao: {k['por_status']}")
