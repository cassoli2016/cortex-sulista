"""Limites de crédito rotativo (cheque empresa) — data/credito.json.

Por que isto existe: a tela de Antecipação dizia "sobram R$ 3,15 mi
descobertos, busque outra fonte" sem dizer QUAL fonte nem QUANTO ela cobre.
A resposta real é finita — R$ 485 mil de limite somado — e cara.

O número que mudou a leitura: o cheque empresa custa de **12,90% a 16,20% ao
mês**, contra ~2% da antecipação de recebíveis. É de **seis a oito vezes**
mais caro. Isso inverte a prioridade: antecipar não é o último recurso antes
do limite, é o primeiro — e o limite é o que sobra quando não há recebível
lançado no portal.

Arquivo JSON e não banco porque são três linhas que mudam de vez em quando e
precisam ser CONFERIDAS por quem opera: a taxa do Itaú foi atualizada em
20/08 e o limite do Santander vence em 25/10. Valor mascarado num cofre
tornaria impossível saber se está certo (mesma decisão do email_config.json).

Ordem de uso: sempre da taxa MENOR para a maior. Consumir o limite mais caro
primeiro é queimar dinheiro sem motivo, e é o que acontece quando ninguém
olha a taxa na hora do aperto.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CAMINHO = ROOT / "data" / "credito.json"

# Posição informada pela diretoria em 24/08/2026. Serve de padrão até alguém
# gravar pela tela — sem isto a tela nasceria vazia e o número não apareceria
# em lugar nenhum, que é exatamente o problema que ela resolve.
PADRAO: list[dict] = [
    {"banco": "Itaú", "tipo": "Cheque empresa", "limite": 310000.0,
     "taxa_mes": 15.69, "vencimento": None, "atualizado_em": "2026-08-20",
     "ativo": True},
    {"banco": "Santander", "tipo": "Limite Cheque Empresa", "limite": 145000.0,
     "taxa_mes": 16.20, "vencimento": "2026-10-25", "atualizado_em": "2026-08-24",
     "ativo": True},
    {"banco": "Sicredi", "tipo": "Cheque especial", "limite": 30000.0,
     "taxa_mes": 12.90, "vencimento": None, "atualizado_em": "2026-08-24",
     "ativo": True},
]


def _carregar() -> list[dict] | None:
    try:
        dados = json.loads(CAMINHO.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def ler() -> list[dict]:
    """Linhas ativas, da taxa MENOR para a maior — é a ordem de uso."""
    linhas = _carregar()
    if linhas is None:
        linhas = [dict(x) for x in PADRAO]
    return sorted([l for l in linhas if l.get("ativo", True)],
                  key=lambda l: float(l.get("taxa_mes") or 0))


def gravar(linhas: list[dict]) -> list[dict]:
    limpo = []
    for l in linhas or []:
        banco = str(l.get("banco") or "").strip()
        if not banco:
            raise ValueError("Informe o banco.")
        try:
            limite = float(l.get("limite") or 0)
            taxa = float(l.get("taxa_mes") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Limite ou taxa inválidos em {banco}.") from None
        if limite < 0:
            raise ValueError(f"Limite negativo em {banco}.")
        # Taxa de cheque especial vive entre 5% e 20% a.m. no Brasil. Fora
        # disso é quase sempre confusão entre taxa MENSAL e ANUAL — e essa
        # troca faz o custo do buraco errar por um fator de 12.
        if not (0 < taxa < 30):
            raise ValueError(
                f"Taxa de {taxa}% a.m. em {banco} está fora do razoável. "
                "Confira se não é a taxa ANUAL.")
        limpo.append({
            "banco": banco,
            "tipo": str(l.get("tipo") or "Cheque especial").strip(),
            "limite": round(limite, 2),
            "taxa_mes": round(taxa, 4),
            "vencimento": (str(l.get("vencimento")).strip()[:10]
                           if l.get("vencimento") else None),
            "atualizado_em": datetime.now().strftime("%Y-%m-%d"),
            "ativo": bool(l.get("ativo", True)),
        })
    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO.write_text(json.dumps(limpo, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return ler()


def resumo(hoje: date | None = None) -> dict:
    """Total disponível, custo mensal se usado por inteiro e o que vence."""
    hoje = hoje or date.today()
    linhas = ler()
    total = round(sum(l["limite"] for l in linhas), 2)
    # Custo ponderado: usar o limite inteiro custa a soma de limite x taxa, e
    # a taxa efetiva do conjunto é essa soma dividida pelo total. A media
    # simples das taxas mentiria — o Sicredi (mais barato) e o menor limite.
    custo_mes = round(sum(l["limite"] * l["taxa_mes"] / 100 for l in linhas), 2)
    taxa_efetiva = round(100 * custo_mes / total, 2) if total else 0.0

    vencendo = []
    for l in linhas:
        if not l.get("vencimento"):
            continue
        try:
            d = date.fromisoformat(l["vencimento"])
        except ValueError:
            continue
        dias = (d - hoje).days
        if dias <= 90:
            vencendo.append({**l, "dias_para_vencer": dias})

    return {
        "linhas": linhas,
        "total": total,
        "custo_mes_total": custo_mes,
        "taxa_efetiva": taxa_efetiva,
        "taxa_min": min((l["taxa_mes"] for l in linhas), default=0.0),
        "taxa_max": max((l["taxa_mes"] for l in linhas), default=0.0),
        "vencendo": sorted(vencendo, key=lambda x: x["dias_para_vencer"]),
    }


def cobrir(valor: float, hoje: date | None = None) -> dict:
    """Quanto do buraco o limite cobre, por qual banco e a que custo.

    Consome da taxa menor para a maior. Devolve `descoberto` quando o limite
    acaba antes do buraco — é o número que não tem solução dentro de casa.
    """
    resto = max(0.0, float(valor or 0))
    usos, custo = [], 0.0
    for l in ler():
        if resto <= 0.005:
            break
        usa = min(resto, l["limite"])
        c = usa * l["taxa_mes"] / 100
        usos.append({"banco": l["banco"], "taxa_mes": l["taxa_mes"],
                     "usado": round(usa, 2), "custo_mes": round(c, 2)})
        custo += c
        resto -= usa
    return {
        "necessario": round(float(valor or 0), 2),
        "coberto": round(float(valor or 0) - resto, 2),
        "descoberto": round(resto, 2),
        "custo_mes": round(custo, 2),
        "usos": usos,
    }
