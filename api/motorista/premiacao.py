# -*- coding: utf-8 -*-
"""O prêmio DELE: a nota do ciclo, os três pilares e quanto isso vale.

═══════════════════════════════════════════════════════════════════════════
A EXCEÇÃO DE DINHEIRO, POR ESCRITO
═══════════════════════════════════════════════════════════════════════════
O contrato deste módulo (`api/motorista/__init__.py`) diz que a ÚNICA exceção
de dinheiro no app é o valor da multa. Esta é a SEGUNDA, decidida por quem
opera em 18/09/2026: **o valor do prêmio do próprio motorista**.

A razão é a mesma da multa: não é dinheiro da empresa, é o dele — vai no
holerite, e ele já discute esse número na conversa com a gestão. Esconder
faria o app valer menos que o papel que ele recebe.

E a razão de ser SÓ o dele continua valendo para tudo: não existe rota aqui
que devolva o prêmio de outra pessoa. A única comparação é a POSIÇÃO no ciclo
(“12º de 81”), que cabe pelo mesmo motivo da posição na Gobrax — a premiação
já é pública entre eles —, e ela não leva nome de colega nenhum.

═══════════════════════════════════════════════════════════════════════════
PRÉVIA × PAGO, QUE É A DECISÃO QUE MAIS PESA AQUI
═══════════════════════════════════════════════════════════════════════════
Número de premiação errado na mão do premiado é discussão de salário
(`docs/APP_MOTORISTA.md`, item 9 da fase 2). O ciclo ABERTO ainda se move: a
Gobrax reprocessa um mês, o ERP registra ocorrência com três semanas de
atraso, alguém arruma o de-para. Por isso a tela tem DOIS estados, e eles são
ditos em letras:

- **prévia** — ciclo aberto. O valor pode mudar até o fechamento, e a linha
  diz isso. Quem opera escolheu mostrar (18/09/2026): acompanhar o próprio
  número durante o ciclo é o que faz a régua mudar comportamento; saber só no
  fim é saber tarde demais para reagir.
- **pago** — ciclo fechado. Aí é a FOTOGRAFIA do fechamento, o mesmo número
  que foi para a folha, e ele não muda mais.

═══════════════════════════════════════════════════════════════════════════
O QUE NÃO SAI DAQUI
═══════════════════════════════════════════════════════════════════════════
**A MEDIDA DISCIPLINAR SUGERIDA NÃO ENTRA NO APP** (decisão de quem opera,
18/09/2026). Ele vê os FATOS — quais ocorrências entraram no ciclo e quantos
pontos cada uma tirou —, porque são dele e ele precisa saber o que aconteceu.
O NÍVEL sugerido (N1 a N4) não: medida é rito trabalhista, quem aplica é o RH,
e um app que dá a notícia antes da conversa inverte a ordem e cria o conflito
que a régua existe para evitar.

Também não saem: CPF (a chave é o código do cadastro), nome de colega, nota de
colega, e a tabela de valores da casa — só o valor base que forma o prêmio
DELE.

═══════════════════════════════════════════════════════════════════════════
POR QUE ESTE MÓDULO NÃO TEM CONTA NENHUMA
═══════════════════════════════════════════════════════════════════════════
Ele não calcula: chama `premiacao.ranking` e `premiacao.fechamento`, as MESMAS
funções que a tela do painel usa, e recorta a linha de quem está logado. Duas
implementações da mesma régua divergem em silêncio — é a lição do freetime —,
e aqui a divergência apareceria como "o app diz 88 e a gestão diz 86", que é a
discussão de salário que se quer evitar.

O custo disso é montar o ciclo inteiro para ler uma linha. Medido: 0,14 s para
83 motoristas, e com o cache de 5 minutos o segundo motorista que abrir o app
não paga nada.
"""
from __future__ import annotations

import logging

from api import pglocal
from api.queries import VELHA_ATE, cached
from api.premiacao import ciclo as ciclo_mod, fechamento, ranking

log = logging.getLogger("cortex.motorista.premiacao")

ESQUEMA: str | None = None

#: Rótulos dos pilares no app. O motorista não fala "pilar Gobrax": ele fala
#: "como eu dirijo", "o que anotaram de mim" e "o que o rastreamento viu".
PILARES = {
    "gobrax": ("Condução", "peso_gobrax",
               "a nota da telemetria no mês — como você dirigiu"),
    "conduta": ("Comportamento", "peso_conduta",
                "as ocorrências registradas no seu nome"),
    "gr": ("Gerenciamento de risco", "peso_gr",
           "os alertas do rastreamento nas suas viagens"),
}


def _esq():
    return ESQUEMA


@cached(ttl=300, velha_ate=VELHA_ATE)
def _ciclo_montado(ciclo: str) -> dict:
    """O ciclo inteiro, uma vez a cada cinco minutos para a frota toda.

    A leitura velha carimbada (até 2 h) vale aqui porque a menor faixa que
    esta tela publica é um CICLO de um mês: um número de vinte minutos atrás
    não muda nada do que está escrito, e tela em branco no celular do
    motorista é pior do que um número com idade dita.

    A JANELA É A DA CASA (`VELHA_ATE`), nunca um número escrito aqui:
    janela própria seria uma decisão que ninguém tomou — a do `viagem.py` já
    foi de 6 h, escolhida sozinha, e uma viagem cabe inteira em seis horas.
    """
    return ranking.montar(ciclo)


def _pagamento(ciclo: str, pronto: dict) -> dict:
    return fechamento.pagamento(ciclo, ranking_pronto=pronto)


def _historico(codigo: str) -> list[dict]:
    """O que já foi PAGO a ele, ciclo a ciclo — direto das fotografias.

    Sai do fechamento e não de um recálculo: histórico que se recalcula muda
    de valor depois de pago, que é exatamente o que o fechamento existe para
    impedir. Ciclo aberto não entra aqui (ele está no topo da tela, como
    prévia).
    """
    try:
        linhas = pglocal.query(
            "SELECT ciclo, nota, valor FROM prm_fechamento_linha"
            " WHERE motorista = %s ORDER BY ciclo DESC LIMIT 6",
            (codigo,), esquema=_esq())
    except Exception as exc:  # noqa: BLE001
        log.warning("motorista: historico de premio indisponivel (%s)",
                    type(exc).__name__)
        return []
    return [{"ciclo": r["ciclo"], "rotulo": ciclo_mod.rotulo(r["ciclo"]),
             "nota": float(r["nota"]) if r["nota"] is not None else None,
             "valor": float(r["valor"]) if r["valor"] is not None else None}
            for r in linhas]


def _posicao(linhas: list[dict], codigo: str) -> tuple[int | None, int]:
    """A posição DELE entre quem tem nota, do melhor para o pior.

    Quem está sem nota não entra no denominador: ele não está em último lugar,
    está fora da conta — e "81º de 81" diria uma coisa que não aconteceu.
    """
    com_nota = [x for x in linhas if x["nota"] is not None]
    ordenado = sorted(com_nota, key=lambda x: -x["nota"])
    for i, x in enumerate(ordenado, start=1):
        if x["motorista"] == codigo:
            return i, len(ordenado)
    return None, len(ordenado)


def meu(sessao: dict) -> dict:
    """O prêmio de QUEM ESTÁ LOGADO. Sem parâmetro de motorista, como o resto
    do módulo: um argumento que a rota pudesse preencher com o que veio do
    navegador seria a diferença entre um app e um buscador da folha alheia."""
    codigo = str(sessao.get("motorista_codigo") or "")
    alvo = ciclo_mod.atual()

    try:
        r = _ciclo_montado(alvo)
    except Exception as exc:  # noqa: BLE001
        log.warning("motorista: ciclo da premiacao indisponivel (%s)",
                    type(exc).__name__)
        return {"tem_dado": False, "fora_do_escopo": False,
                "motivo": "Não consegui ler a premiação agora. Tente de novo "
                          "daqui a pouco.", "fonte": "Gestão de Motoristas"}

    linha = next((x for x in r["linhas"] if x["motorista"] == codigo), None)
    if linha is None:
        # NÃO É FALHA: a régua é dos motoristas PRÓPRIOS, e boa parte de quem
        # usa este app é agregado. `fora_do_escopo` faz a tela NÃO desenhar o
        # cartão — aba que abre e diz "sem dados" para quem nunca vai ter dado
        # ensina a pessoa a não confiar no resto da tela.
        return {"tem_dado": False, "fora_do_escopo": True,
                "motivo": "A premiação por ciclo é dos motoristas próprios.",
                "fonte": "Gestão de Motoristas"}

    pag = _pagamento(alvo, r)
    minha_pag = next((x for x in pag["linhas"] if x["motorista"] == codigo), {})
    fechado = bool(pag.get("fechado"))
    pos, de = _posicao(r["linhas"], codigo)

    valores = (r.get("parametros") or {}).get(linha["tipo"]) or {}
    pilares = []
    for chave, (rotulo, peso_chave, explica) in PILARES.items():
        pilares.append({
            "chave": chave, "rotulo": rotulo, "explica": explica,
            "nota": linha.get(chave),
            "peso": valores.get(peso_chave),
            "entrou": chave in (linha.get("pilares") or []),
        })

    return {
        "tem_dado": True, "fora_do_escopo": False,
        "ciclo": alvo, "rotulo": r["rotulo"], "fechado": fechado,
        # PRÉVIA É O ESTADO PADRÃO, e a tela é obrigada a dizer: até o ciclo
        # fechar, tudo aqui ainda se move.
        "previa": not fechado,
        "nota": linha["nota"], "status": linha["status"],
        "categoria": linha["categoria"], "reputacao": linha["reputacao"],
        "ciclos_limpos": linha["ciclos_limpos"],
        "pilares": pilares,
        "ausentes": linha["ausentes"],
        "posicao": pos, "de": de,
        "premio": {
            "valor": minha_pag.get("valor"),
            "base": minha_pag.get("base"),
            "pct": minha_pag.get("pct"),
            "motivo": minha_pag.get("motivo") or "",
        },
        # OS FATOS, SEM O VEREDITO: quais ocorrências entraram e quanto cada
        # uma tirou. O nível de medida sugerido fica no painel, com quem
        # aplica — ver o cabeçalho deste arquivo.
        "desvios": [{"nome": d["nome"], "grav": d["grav"], "pts": d["pts"],
                     "data": d["data"]} for d in (linha.get("desvios") or [])],
        "meritos": linha.get("meritos") or 0,
        "historico": _historico(codigo),
        "fonte": "Gestão de Motoristas · " + (
            "fotografia do fechamento" if fechado else "cálculo do ciclo em curso"),
    }
