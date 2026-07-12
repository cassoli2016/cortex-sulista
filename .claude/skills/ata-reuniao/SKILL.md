---
name: ata-reuniao
description: Gera ata de reunião estruturada com decisões e plano de ação no formato 5W2H, com responsáveis e prazos. Use sempre que registrar uma reunião — o resultado vira ações rastreáveis em ges_acoes.
---

# Skill: Ata de Reunião + Plano de Ação (5W2H)

Reunião que não vira ação atribuída não tem efeito. Esta skill produz ata enxuta + ações.

## Estrutura da ata
```
Reunião: <título>            Data: <data>      Duração: <h>
Participantes: <lista>
Pauta: <itens>

Discussão (resumo objetivo por item)
Decisões (lista — o que ficou decidido, sem rodeio)
Plano de ação (tabela 5W2H abaixo)
```

## Plano de ação — 5W2H
| What (o quê) | Why (por quê) | Who (quem) | When (quando) | Where (onde) | How (como) | How much (quanto) |
|---|---|---|---|---|---|---|

Mínimo obrigatório por ação: **What + Who + When** (sem isso, não é ação, é intenção).

## Geração
```python
def montar_acoes(decisoes: list[dict]) -> list[dict]:
    acoes = []
    for d in decisoes:
        assert d.get("quem") and d.get("quando"), "ação precisa de responsável e prazo"
        acoes.append({"o_que": d["o_que"], "quem": d["quem"], "quando": d["quando"],
                      "por_que": d.get("por_que",""), "como": d.get("como",""),
                      "status": "aberta", "prioridade": d.get("prioridade","media")})
    return acoes
```

As ações entram em `ges_acoes` e passam a ser cobradas pelo agente `gestao` (o que está
atrasado, com quem, há quanto tempo). Liga ações a OKRs quando aplicável.

## Fontes
ges_atas, ges_acoes, ges_okr.
