"""A régua de condução da premiação: motor ligado parado e faixa verde.

POR QUE A RÉGUA É NOSSA
=======================
Cada indicador da Gobrax vem com um `score`, e seria mais fácil usá-lo. Medido
em 30/08/2026 sobre as 98 placas da competência: **seis dos catorze indicadores
vieram com nota 0 em TODOS os veículos** — "em movimento", "faixa verde",
"faixa econômica", "freio motor" e as pressões de pedal média e baixa. Régua
que zera a frota inteira não separa ninguém, e ninguém saberia explicar a um
motorista por que ele perdeu o prêmio. A nota deles continua guardada e é
mostrada ao lado, como conferência.

OS DOIS INDICADORES, E A DIFERENÇA ENTRE ELES
=============================================
Não recebem o mesmo tratamento, e isso saiu do dado, não de preferência:

- **Motor ligado parado (`idle`) GRADUA.** A metade central da frota vai de
  9,2% a 16,7%, com cauda até 60,4%. Há dispersão real: a régua linear entre
  alvo e teto distingue quem cuida de quem não cuida.
- **Faixa verde (`greenRange`) NÃO GRADUA — ela EXCEPCIONA.** A metade central
  vai de 93,8% a 98,8%: **cinco pontos**. Graduar aí daria praticamente a
  mesma nota para todo mundo e o critério não separaria ninguém — é a mesma
  armadilha da "coluna que repete o mesmo valor em todas as linhas". Então ela
  entra como PISO: acima dele não pontua nem penaliza; abaixo, penaliza, porque
  aí é desvio de verdade.

Se um dia a frota se espalhar em faixa verde, o piso vira régua graduada — mas
essa é uma mudança a fazer olhando o dado, não por simetria com o outro
indicador.

TUDO É PARÂMETRO DA VERSÃO
==========================
Alvo, teto e piso são `PARAMS` da competência, como o resto. Premiação decide
dinheiro e a pergunta "por que recebi isso em março?" sempre aparece — meses
depois, quando quem configurou já mudou o número três vezes. Congelar na versão
é o que faz essa pergunta ter resposta.
"""
from __future__ import annotations

# ── nota de motor ligado parado ─────────────────────────────────────────────
def nota_idle(pct: float | None, alvo: float, teto: float) -> float | None:
    """100 no alvo ou abaixo, 0 no teto ou acima, linear entre os dois.

    Linear e não escalonada de propósito: com degraus, um décimo de ponto
    percentual decide dez pontos de nota, e a diferença entre 14,9% e 15,1%
    viraria uma discussão que o dado não sustenta.

    `None` quando não há medida — e `None` NÃO é zero. Motorista sem
    telemetria no mês não é motorista que deixou o motor ligado o mês inteiro;
    quem decide o que fazer com a ausência é o motor de cálculo, que sabe se há
    outros eixos para compensar.
    """
    if pct is None:
        return None
    if teto <= alvo:
        raise ValueError("o teto de motor ligado parado tem de ser maior que o alvo")
    if pct <= alvo:
        return 100.0
    if pct >= teto:
        return 0.0
    return round(100.0 * (teto - pct) / (teto - alvo), 1)


# ── faixa verde: piso, não gradação ─────────────────────────────────────────
def penalidade_verde(pct: float | None, piso: float, maxima: float) -> float:
    """Quanto se desconta por rodar abaixo do piso de faixa verde.

    Zero acima do piso — e isso é deliberado: 93,8% a 98,8% é onde a metade da
    frota está, e premiar diferença dentro dessa faixa seria premiar ruído.

    Abaixo do piso o desconto cresce até `maxima` em 0%. Também linear, pelo
    mesmo motivo da nota de idle.
    """
    if pct is None or pct >= piso:
        return 0.0
    if piso <= 0:
        return 0.0
    return round(maxima * (piso - max(0.0, pct)) / piso, 1)


def avaliar(indicadores: dict, params: dict) -> dict:
    """A nota de condução do veículo/motorista, com a conta ABERTA.

    Devolve as parcelas, não só o total: quem pergunta "por que essa nota?"
    precisa ver de onde ela veio, e um número sozinho não responde isso.
    """
    idle = (indicadores or {}).get("idle") or {}
    verde = (indicadores or {}).get("greenRange") or {}
    p_idle = idle.get("pct") if isinstance(idle, dict) else None
    p_verde = verde.get("pct") if isinstance(verde, dict) else None

    n_idle = nota_idle(p_idle, params["idle_alvo"], params["idle_teto"])
    desc = penalidade_verde(p_verde, params["verde_piso"],
                            params["verde_desconto_max"])

    if n_idle is None:
        return {"nota": None, "idle_pct": None, "idle_nota": None,
                "verde_pct": p_verde, "verde_desconto": desc,
                "motivo": "sem medida de motor ligado parado na competência"}
    nota = max(0.0, round(n_idle - desc, 1))
    motivo = []
    if n_idle == 100.0:
        motivo.append(f"motor ligado parado em {p_idle:.1f}%, no alvo de "
                      f"{params['idle_alvo']:.0f}% ou abaixo")
    elif n_idle == 0.0:
        motivo.append(f"motor ligado parado em {p_idle:.1f}%, no teto de "
                      f"{params['idle_teto']:.0f}% ou acima")
    else:
        motivo.append(f"motor ligado parado em {p_idle:.1f}% (alvo "
                      f"{params['idle_alvo']:.0f}%, teto {params['idle_teto']:.0f}%)")
    if desc:
        motivo.append(f"faixa verde em {p_verde:.1f}%, abaixo do piso de "
                      f"{params['verde_piso']:.0f}% — desconto de {desc:.1f}")
    return {"nota": nota, "idle_pct": p_idle, "idle_nota": n_idle,
            "verde_pct": p_verde, "verde_desconto": desc,
            "motivo": " · ".join(motivo)}
