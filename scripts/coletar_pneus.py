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

# ---------------------------------------------------------------------------
# REPLICACAO PARA O BANCO PROPRIO. A coleta acima atualiza o instantaneo; estes
# dois passos levam o retrato e a historia para as tabelas `pne_*`, que sao o
# que sobra no dia em que a Prolog for desligada.
#
# A ORDEM IMPORTA e nao e detalhe: semear PRIMEIRO, porque o historico so grava
# evento de pneu que ja existe no banco — pneu novo que apareceu nesta coleta
# precisa estar la antes do movimento dele chegar.
#
# NENHUM DOS DOIS DERRUBA A TAREFA. A coleta do instantaneo ja terminou e ja
# foi gravada; falhar aqui e perder a replicacao do dia, nao a coleta. E a
# semeadura nao gasta cota nenhuma — ela le o arquivo que acabou de ser escrito.
try:
    from api.pneus import replica, historico

    rs = replica.semear()
    print(f"  replica: {rs.get('pneus')} pneu(s) · +{rs.get('novos')} novo(s) · "
          f"{rs.get('vidas')} vida(s) · {rs.get('inspecoes')} inspecao(oes)")

    rh = historico.sincronizar()
    marca = "" if rh.get("ok") else "  [PAROU: %s]" % (rh.get("erro") or "")[:60]
    print(f"  historico: +{rh.get('eventos_novos')} evento(s) em "
          f"{rh.get('requisicoes')} requisicao(oes) · recuado ate "
          f"{rh.get('cursor')}{marca}")
    if rh.get("pneus_nao_encontrados"):
        print(f"  ATENCAO: {rh['pneus_nao_encontrados']} pneu(s) do movimento "
              f"nao existem no banco — a semeadura ficou para tras")
except Exception as exc:  # noqa: BLE001
    print(f"  replicacao falhou ({type(exc).__name__}) — o instantaneo acima "
          f"foi gravado assim mesmo")
