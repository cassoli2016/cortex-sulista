---
name: programacao-cargas
description: Aloca cargas a veículos/motoristas disponíveis respeitando janelas, jornada (Lei 13.103) e tipo de carga; minimiza ociosidade e retorno vazio; aponta gargalos. Use para montar e otimizar a programação operacional.
---

# Skill: Programação de Cargas

Encaixa carga → veículo → motorista com restrições e objetivo de eficiência.

## Restrições (hard)
- Janela: coleta/entrega da carga ⊆ disponibilidade do veículo.
- Jornada: motorista não pode estourar limites da Lei 13.103 na rota (checar skill jornada-motorista).
- Compatibilidade: tipo de carga × tipo de veículo (baú, graneleiro, frigorífico...).

## Objetivo (soft, minimizar)
- Ociosidade de frota e **retorno vazio** (casar carga de volta na mesma região).

## Heurística de alocação (greedy + casamento de retorno)
```python
def alocar(cargas: list[dict], veiculos: list[dict]) -> dict:
    cargas = sorted(cargas, key=lambda c: c["janela_coleta"])
    alocacoes, sem_veiculo = [], []
    for c in cargas:
        cand = [v for v in veiculos
                if v["disponivel"]
                and compativel(v["tipo"], c["tipo_carga"])
                and cabe_na_janela(v, c)
                and jornada_ok(v["motorista"], c["rota"])]
        if not cand:
            sem_veiculo.append(c); continue
        # prioriza veículo que reduz retorno vazio (já está perto da origem)
        v = min(cand, key=lambda v: dist(v["pos_atual"], c["origem"]))
        alocacoes.append({"carga": c["id"], "veiculo": v["id"]})
        v["disponivel"] = False
    ociosos = [v["id"] for v in veiculos if v["disponivel"]]
    return {"alocacoes": alocacoes, "sem_veiculo": [c["id"] for c in sem_veiculo],
            "veiculos_ociosos": ociosos}
```

## Saída acionável
- Cargas sem veículo (precisa agregado? -> skill make-vs-buy).
- Veículos ociosos (buscar carga de retorno).
- Conflitos de janela a resolver.

## Fontes
prog_cargas, prog_alocacao, prog_disponibilidade, fro_veiculos, jor_jornadas, op_rotas.
