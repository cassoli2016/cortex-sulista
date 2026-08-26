# api/milkrun/respostas.py
"""Respostas CALCULADAS para as perguntas de sempre.

POR QUE ISTO EXISTE
===================
Um A/B entre gemma4 e qwen2.5:7b (scripts/ab_modelo_milkrun.py, 26/08/2026)
mostrou um padrao limpo:

  - toda dimensao que eu PRE-CALCULEI, os dois modelos acertaram;
  - toda dimensao que deixei o modelo apurar, os dois erraram.

E o erro nao e "nao sei": e resposta confiante, especifica e errada. Perguntado
onde o veiculo ficou mais tempo parado, o gemma4 respondeu "MARTINREA-HONSEL,
212,5 minutos" com coleta, placa e data formatadas - sendo que o certo era
METALURGICA RIOSULENSE com 307,4, valor que estava no contexto DUAS vezes (no
detalhe e no agregado). O qwen, perguntado do maior ATRASO, devolveu a maior
PERMANENCIA.

Para "maior", "top N" e "quantos", o numero E a resposta. Nao ha nada para o
modelo interpretar, e deixa-lo escolher so acrescenta uma chance de errar.
Entao aqui essas perguntas sao atendidas por codigo: reconhecimento de intencao
por palavra-chave (deterministico, sem modelo) e a resposta montada do proprio
contexto.

O QUE NAO ENTRA AQUI
--------------------
Pergunta aberta ("como foi o dia?", "por que essa coleta demorou?") continua
indo para o modelo. Este modulo NAO tenta cobrir tudo - cobrir demais viraria
um chatbot de arvore de decisao, que e pior que um modelo para o que e aberto.
Quando nao reconhece, devolve None e o fluxo segue normal.
"""
from __future__ import annotations

import re
import unicodedata

# quantos itens uma resposta de ranking traz quando o usuario nao diz
TOP_PADRAO = 5


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return t.encode("ascii", "ignore").decode()


def _min(v: float | None) -> str:
    if v is None:
        return "n/d"
    v = float(v)
    if v < 60:
        return f"{v:.0f} min"
    h, r = divmod(int(round(v)), 60)
    return f"{h}h{r:02d}" if r else f"{h}h"


def _quantos(t: str) -> int:
    """"top 3", "os 10 maiores" -> 3, 10. Sem numero, TOP_PADRAO."""
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 30:
            return n
    return TOP_PADRAO


def _sem_dado(ctx: dict, campo: str) -> str | None:
    """Mensagem util quando o periodo nao tem o que medir.

    Vale mais que "nao consta": no recorte de HOJE as paradas ainda estao
    pendentes e nao tem permanencia nem atraso medidos, e quem le precisa
    saber que basta abrir o periodo - nao que a tela nao tem o dado.
    """
    if ctx.get(campo):
        return None
    per = ctx.get("periodo") or {}
    return (f"Nenhuma parada concluída no período de {per.get('de')} a "
            f"{per.get('ate')} — as pendentes ainda não têm "
            "chegada e saída registradas pelo rastreador, então não há "
            "permanência nem atraso para medir. Amplie o período no filtro "
            "da tela para ver os dias já fechados.")


def _linha_atraso(x: dict) -> str:
    return (f"coleta {x['coleta']} · placa {x['placa']} · {x['local']} · "
            f"{_min(x['atraso_min'])} de atraso")


def _piores_atrasos(ctx: dict, n: int) -> str:
    aviso = _sem_dado(ctx, "pontos_com_atraso_medido")
    if aviso:
        return aviso
    piores = (ctx.get("piores_atrasos") or [])[:n]
    if not piores:
        return "Nenhuma parada com atraso no período."
    if n == 1 or len(piores) == 1:
        x = piores[0]
        return ("Maior atraso do período: " + _linha_atraso(x)
                + f" (previsto {x.get('previsto')}, chegada {x.get('chegada')}).")
    corpo = "\n".join(f"{i}. {_linha_atraso(x)}" for i, x in enumerate(piores, 1))
    return f"Maiores atrasos do período:\n{corpo}"


def _rank_permanencia(ctx: dict, n: int, chave: str) -> str:
    aviso = _sem_dado(ctx, "pontos_com_permanencia_medida")
    if aviso:
        return aviso
    campo = ("ranking_fornecedores_por_permanencia" if chave == "local"
             else "ranking_placas_por_permanencia")
    rk = (ctx.get(campo) or [])[:n]
    if not rk:
        return "Sem paradas medidas no período."
    rotulo = "fornecedores" if chave == "local" else "placas"
    corpo = "\n".join(
        f"{i}. {x[chave]} · mediana {_min(x['permanencia_mediana_min'])} · "
        f"média {_min(x['permanencia_media_min'])} · "
        f"{x['paradas_com_medida']} "
        f"{'parada' if x['paradas_com_medida'] == 1 else 'paradas'}"
        for i, x in enumerate(rk, 1))
    return (f"Top {len(rk)} {rotulo} por tempo parado:\n{corpo}\n\n"
            "Mediana e média vão juntas de propósito: uma parada muito longa "
            "puxa a média e não move a mediana.")


def _maior_permanencia(ctx: dict) -> str:
    aviso = _sem_dado(ctx, "pontos_com_permanencia_medida")
    if aviso:
        return aviso
    melhor = None
    for c in ctx.get("coletas", []):
        for p in c.get("pontos", []):
            v = p.get("permanencia_min")
            if v is not None and (melhor is None or v > melhor[0]):
                melhor = (v, c, p)
    if not melhor:
        # O DETALHE pode ter sido podado (periodo grande) enquanto o agregado,
        # que nunca e podado, ainda tem o numero. Dizer "sem paradas medidas"
        # aqui seria negar dado que esta no proprio contexto - o erro que este
        # modulo existe para nao cometer.
        rk = ctx.get("ranking_fornecedores_por_permanencia") or []
        if rk:
            topo = max(rk, key=lambda x: x.get("permanencia_max_min") or 0)
            return (f"Maior permanência do período: "
                    f"{_min(topo.get('permanencia_max_min'))} em "
                    f"{topo['local']}. (O detalhe ponto a ponto deste período "
                    "foi reduzido, então coleta e placa não estão à mão; o "
                    "número vem do agregado, que cobre todas as paradas.)")
        return "Sem paradas medidas no período."
    v, c, p = melhor
    txt = (f"Maior permanência do período: {_min(v)} em {p['local']} "
           f"(coleta {c['coleta']}, placa {c['placa']}, "
           f"chegada {p.get('chegada')}, saída {p.get('saida')}).")
    if ctx.get("detalhe_podado"):
        txt += ("\n\nAtenção: o período é grande e o detalhe ponto a ponto foi "
                "reduzido às paradas notáveis. Este é o maior entre os "
                "detalhados; o ranking por fornecedor cobre todos.")
    return txt


def _resumo(ctx: dict) -> str:
    k = ctx.get("kpis") or {}
    per = ctx.get("periodo") or {}
    linhas = [f"Período {per.get('de')} a {per.get('ate')}:",
              f"· {k.get('solicitacoes')} solicitações, {k.get('pontos')} paradas",
              f"· concluídas {k.get('concluidos')} · pendentes {k.get('pendentes')}"
              f" · frustradas {k.get('frustrados')}"]
    if k.get("pct_realizado") is not None:
        linhas.append(f"· {k['pct_realizado']}% realizado (sobre o que já "
                      "deveria estar resolvido)")
    if k.get("vencidas"):
        linhas.append(f"· {k['vencidas']} pendentes com horário já vencido")
    if k.get("permanencia_mediana") is not None:
        linhas.append(f"· permanência mediana {_min(k['permanencia_mediana'])}")
    return "\n".join(linhas)


# Ordem IMPORTA: "maior atraso" tem de casar antes de "maior tempo", senao a
# pergunta de atraso cairia no ranking de permanencia - que e exatamente a
# confusao que o qwen cometeu sozinho.
_INTENCOES = [
    ("atraso", re.compile(r"atras|atrasad|fora do (horario|prazo)|"
                          r"nao cumpriu|descumpr")),
    # "por placa", "quais placas", "ranking de placas" = ranking.
    # "o veiculo ficou mais tempo parado" NAO e: e o maximo, e casava aqui
    # antes por conter "veiculo" e "tempo" a menos de 30 caracteres.
    ("perm_placa", re.compile(r"(por|quais|ranking de|top \d* ?)\s*placas?|"
                              r"placas?.{0,20}(que |mais )?(fica|para|permanec)")),
    ("perm_top", re.compile(r"(top|maiores|ranking|piores|quais).{0,40}"
                            r"(parad|permanenc|tempo)|"
                            r"fornecedor.{0,30}(parad|permanenc|tempo)|"
                            r"(parad|permanenc|tempo).{0,30}fornecedor")),
    ("perm_max", re.compile(r"(mais|maior).{0,25}(tempo|parad|permanenc)|"
                            r"(permanenc|parou).{0,20}(mais|maior)")),
    ("resumo", re.compile(r"resum|panorama|visao geral|como (foi|esta|ta) "
                          r"(o dia|o periodo|a operacao)")),
]


def responder(pergunta: str, ctx: dict) -> str | None:
    """Resposta calculada, ou None quando a pergunta nao e uma das de sempre.

    Devolver None e o caminho NORMAL, nao uma falha: pergunta aberta e o que o
    modelo faz bem, e forcar tudo por regra viraria arvore de decisao.
    """
    t = _norm(pergunta)
    if not t.strip():
        return None
    n = _quantos(t)
    for nome, rx in _INTENCOES:
        if not rx.search(t):
            continue
        if nome == "atraso":
            # "top 5 atrasos" pede lista; "qual coleta atrasou mais" pede uma
            pede_lista = bool(re.search(r"top|maiores|ranking|piores|lista", t))
            return _piores_atrasos(ctx, n if pede_lista else 1)
        if nome == "perm_placa":
            return _rank_permanencia(ctx, n, "placa")
        if nome == "perm_top":
            return _rank_permanencia(ctx, n, "local")
        if nome == "perm_max":
            return _maior_permanencia(ctx)
        if nome == "resumo":
            return _resumo(ctx)
    return None
