"""Quando uma competência pode ser apurada, e a recoleta de um período.

O PROBLEMA QUE ISTO RESOLVE
==========================
Hoje o snapshot tem dois estados: `parcial` (mês em curso) e fechado. Isso
trata o mês corrente com o cuidado devido — e trata o dia 1º do mês seguinte
como se tudo já estivesse lá, o que é falso.

Depois que a competência termina, dado continua chegando por dias:

- **ocorrência de motorista** é lançada por quem apurou, não no ato;
- **multa** chega do órgão semanas depois;
- **abastecimento** do posto externo entra por integração com atraso;
- e há o ajuste normal — alguém corrige a placa, reclassifica a ocorrência,
  estorna um lançamento.

Um snapshot tirado no dia 1º CONGELA um mês incompleto e nunca mais é
recoletado, porque `parcial` já é falso. O número fica errado para sempre e
nada acusa. A carência conserta isso.

TRÊS ESTADOS, não dois
======================
- **em curso** — a competência ainda não terminou;
- **em carência** — terminou, mas está dentro dos N dias de ajuste: o dado
  ainda se move, e por isso a recoleta CONTINUA acontecendo;
- **apurável** — passou a carência: o que está lá é o que há.

`dias_apuracao` é parâmetro da versão, como todo o resto — o prazo de
fechamento da operação não é constante de software.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from . import config


def _fim_da_competencia(competencia: str) -> date:
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    return date(ano, mes, monthrange(ano, mes)[1])


def dias_apuracao(competencia: str, esquema: str | None = None) -> int:
    """O prazo configurado PARA AQUELA COMPETÊNCIA.

    Lido da versão vigente, não de uma constante: mudar o prazo de 10 para 15
    dias não pode reabrir meses que já foram apurados sob o prazo antigo.
    """
    try:
        return int(float(config.ler(competencia, esquema)["params"]
                         .get("dias_apuracao", 10)))
    except Exception:  # noqa: BLE001
        return 10


def estado(competencia: str, *, hoje: date | None = None,
           esquema: str | None = None) -> dict:
    """Em que ponto do ciclo esta competência está, e o que isso permite."""
    hoje = hoje or date.today()
    fim = _fim_da_competencia(competencia)
    prazo = dias_apuracao(competencia, esquema)
    libera = fim + timedelta(days=prazo)

    if hoje <= fim:
        return {"competencia": competencia, "estado": "em_curso",
                "dias_apuracao": prazo,
                "libera_em": libera.isoformat(), "faltam": None,
                "apuravel": False,
                "motivo": "A competência ainda não terminou — o que existe "
                          "hoje é parcial."}
    if hoje < libera:
        faltam = (libera - hoje).days
        return {"competencia": competencia, "estado": "em_carencia",
                "dias_apuracao": prazo,
                "libera_em": libera.isoformat(), "faltam": faltam,
                "apuravel": False,
                "motivo": (f"A competência fechou, mas está nos {prazo} dias de "
                           f"ajuste: ocorrência, multa e abastecimento ainda "
                           f"chegam. Faltam {faltam} dia(s) para apurar.")}
    return {"competencia": competencia, "estado": "apuravel",
            "dias_apuracao": prazo,
            "libera_em": libera.isoformat(), "faltam": 0, "apuravel": True,
            "motivo": f"Passou a carência de {prazo} dias — o dado está estável."}


def precisa_recoletar(competencia: str, snap: dict | None, *,
                      hoje: date | None = None,
                      esquema: str | None = None) -> bool:
    """Enquanto o dado se move, recoleta. Depois, para.

    A REGRA QUE FALTAVA: um snapshot tirado DENTRO da carência tem de ser
    refeito quando ela terminar. Sem isso o número do mês fica valendo o que
    era no dia 1º — e ninguém descobre, porque não há erro nenhum, só um
    número menor do que devia.
    """
    if snap is None:
        return True
    e = estado(competencia, hoje=hoje, esquema=esquema)
    if not e["apuravel"]:
        return True          # em curso ou em carência: o dado ainda muda
    col = _quando(snap.get("coletado_em"))
    if col is None:
        return True
    # apurável: só recoleta se a última coleta foi ANTES de a carência acabar
    return col.date() < date.fromisoformat(e["libera_em"])


def _quando(valor) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).replace(
            tzinfo=None)
    except ValueError:
        return None


# ── recoleta de um período ───────────────────────────────────────────────────
def competencias(de: str, ate: str) -> list[str]:
    """As competências do intervalo, inclusive nas duas pontas."""
    for c in (de, ate):
        if len(c) != 7 or c[4] != "-":
            raise ValueError("Competência inválida — use AAAA-MM.")
    if de > ate:
        de, ate = ate, de
    ano, mes = int(de[:4]), int(de[5:7])
    fim_ano, fim_mes = int(ate[:4]), int(ate[5:7])
    if not (1 <= mes <= 12 and 1 <= fim_mes <= 12):
        raise ValueError("Mês inválido na competência.")
    saida = []
    while (ano, mes) <= (fim_ano, fim_mes):
        saida.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
        if len(saida) > 60:
            raise ValueError("Período grande demais — no máximo 60 meses.")
    return saida


# Recoletar é CARO: cada competência é uma volta na API da Gobrax. O teto
# existe para um erro de digitação (2020 em vez de 2026) não virar cinquenta
# chamadas — e ele RECUSA em vez de truncar, porque truncar em silêncio
# devolveria um resultado que parece completo e não é.
MAX_COMPETENCIAS = 24


def recoletar(de: str, ate: str, *, autor: str = "",
              hoje: date | None = None, esquema: str | None = None) -> dict:
    """Refaz a coleta das competências do período.

    NÃO É O MESMO QUE "atualizar tudo": ali a decisão de recoletar é do
    sistema; aqui é de quem pediu. Serve para o caso real — alguém corrigiu
    uma placa, reclassificou uma ocorrência, lançou a multa que faltava — e
    precisa que o número reflita isso sem esperar o ciclo.

    Cada competência recoletada FICA REGISTRADA com quem pediu: recoleta que
    muda valor de prêmio sem deixar rastro é a forma mais fácil de perder a
    confiança na premiação.
    """
    from . import servico
    comps = competencias(de, ate)
    if len(comps) > MAX_COMPETENCIAS:
        raise ValueError(
            f"São {len(comps)} competências e o máximo é {MAX_COMPETENCIAS}. "
            "Recoletar é uma volta na API da Gobrax por mês — recorte o "
            "período.")
    agora = datetime.now()
    feitas: list[dict] = []
    for c in comps:
        e = estado(c, hoje=hoje or agora.date(), esquema=esquema)
        try:
            r = servico.obter(c, force=True, agora=agora)
            ok, erro = True, ""
            motoristas = len((r or {}).get("motoristas") or [])
        except Exception as exc:  # noqa: BLE001
            # UMA competência que falha NÃO derruba as outras: recoletar seis
            # meses e perder tudo porque o quarto deu timeout seria pior que
            # não ter o botão.
            ok, erro, motoristas = False, type(exc).__name__, 0
        feitas.append({"competencia": c, "ok": ok, "erro": erro,
                       "motoristas": motoristas, "estado": e["estado"],
                       "apuravel": e["apuravel"]})
    return {"de": comps[0], "ate": comps[-1], "competencias": feitas,
            "ok": all(f["ok"] for f in feitas),
            "autor": autor,
            "quando": agora.isoformat(timespec="seconds")}
