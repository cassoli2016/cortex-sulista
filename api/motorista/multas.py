# -*- coding: utf-8 -*-
"""As multas que apareceram nas viagens DELE — e o que isso não prova.

═══════════════════════════════════════════════════════════════════════════
DE ONDE VEM, E POR QUE NÃO VEM DO CAMPO QUE TEM O NOME CERTO
═══════════════════════════════════════════════════════════════════════════
`smt_infracoes.motorista_nome` existe, vem da Smartec, e É INÚTIL para esta
tela: medido em 31/08/2026, dos 212 registros em aberto apenas DOIS traziam
nome de gente — o resto vinha com "AGREGADO", "MOTORISTA", "NIC" e "RECURSO",
que são estados do processo de indicação de condutor, não pessoas. Ler esse
campo como condutor faria a tela mentir com a cara mais séria possível, porque
o nome da coluna promete exatamente o que ela não entrega.

O vínculo real sai do cruzamento que a coleta da Smartec já faz contra o AVA
(`api/smartec/viagem.py`): a infração tem placa e instante; a
`programacaoembarque` tem placa, janela e motorista. A infração cujo instante
cai dentro da janela de uma viagem pertence — como HIPÓTESE — a quem estava
dirigindo aquela viagem. Desde a migration 0062 esse motorista fica gravado em
`smt_infracao_viagem.motorista_codigo`, então esta tela lê SÓ o banco local:
o ERP não entra no caminho de um celular em 4G de rodovia.

Medido em 07/09/2026 sobre os 80 vínculos ativos: 639 infrações em doze meses,
**156 casadas a 39 motoristas**.

═══════════════════════════════════════════════════════════════════════════
A FRASE QUE NÃO PODE SUMIR DA TELA
═══════════════════════════════════════════════════════════════════════════
"A viagem estava com o Fulano" NÃO É "o Fulano cometeu a infração". O veículo
pode ter sido movido no pátio por outra pessoa, o auto pode vir de leitura da
carreta, a janela do ERP pode estar mal lançada — e a indicação de condutor é
processo do órgão, com prazo e formulário, não dedução nossa.

Por isso cada item sai com `hipotese: true` e o payload carrega
`ATRIBUICAO`, que a página desenha. Uma tela que apresentasse isto como
veredito transformaria uma heurística nossa em acusação — e o leitor é a
pessoa acusada. Heurística escondida vira verdade do sistema; esta se declara.

`candidatas > 1` é o caso ainda mais frouxo: duas viagens da mesma placa
continham o instante (chegada lançada depois da saída seguinte, que acontece
no ERP). Vence a janela mais curta, e o item vai marcado `disputada`.

═══════════════════════════════════════════════════════════════════════════
O QUE SAI, E POR QUE O VALOR SAI
═══════════════════════════════════════════════════════════════════════════
A regra do app é "nada de dinheiro da empresa" — frete, custo, CKM, resultado.
Valor de multa não é nenhum deles: é o número que está no auto, no boleto e na
conversa que ele vai ter com a torre, e escondê-lo faria a tela ser menos útil
que o papel que ele já recebe. Vai com a pontuação pelo mesmo motivo — ponto na
CNH é dele, não da empresa. Decidido por quem opera em 07/09/2026.

**As duas espécies NÃO SE SOMAM.** `multa` (já é penalidade, tem boleto) e
`notificacao` (autuação, ainda cabe indicação e defesa) são estágios do MESMO
auto: somá-los conta a mesma infração duas vezes e a ação de cada uma é outra.
Os totais saem separados, como na tela `mul`.

O PRAZO DE INDICAÇÃO é o único campo desta tela que é acionável HOJE: passado
o prazo, entra por cima a autuação do art. 257 §8º ("não indicar condutor"),
que já é 61 das 212 multas em aberto desta frota. Ele vira destaque quando
falta pouco, e some quando não há.
"""
from __future__ import annotations

import logging
from datetime import date

from .. import pglocal

log = logging.getLogger("cortex.motorista.multas")

#: Janela da lista. Doze meses é o que a `mul` usa e é o que casa com o ciclo
#: de um auto (autuação → penalidade → cobrança), que passa dos seis meses.
DIAS = 365

#: Quantos dias antes do fim do prazo de indicação o item vira destaque. Sete
#: porque é o que dá tempo de a pessoa falar com a torre e a torre protocolar;
#: um alerta que acende no último dia não é alerta, é registro do prejuízo.
PRAZO_ALERTA_DIAS = 7

#: A PROCEDÊNCIA, em uma frase, junto do payload — não escrita na página.
#: Texto na página é texto que diverge do que o servidor faz no dia em que
#: alguém mexer só num dos dois lados.
ATRIBUICAO = (
    "Estas infrações apareceram nas placas e nos horários das SUAS viagens. "
    "Isso não é indicação de condutor: se alguma não foi você, fale com a "
    "torre — a indicação tem prazo e é feita pela empresa."
)

_SQL = """
SELECT i.identificador, i.especie, i.placa,
       i.data_infracao, i.hora,
       -- `desdobramento` NÃO entra: é um código do órgão ("2") sem tabela de
       -- domínio nossa, e código sem domínio não vira rótulo inventado nem
       -- número solto na tela de quem não tem como decifrá-lo.
       i.descricao, i.codigo_infracao,
       i.municipio, i.uf, i.local_infracao,
       i.valor_a_pagar, i.valor_com_desconto, i.pontuacao,
       i.vencimento, i.prazo_indicacao,
       (i.sumiu_em IS NULL) AS em_aberto,
       v.rota, v.candidatas
  FROM smt_infracao_viagem v
  JOIN smt_infracoes i ON i.identificador = v.identificador
 WHERE v.motorista_codigo = %(mot)s
   AND i.data_infracao >= current_date - %(dias)s
 ORDER BY i.data_infracao DESC, i.hora DESC
"""


def _esq(esquema: str | None = None) -> str | None:
    """O schema em vigor, lido NA CHAMADA e nunca na importação — ver o mesmo
    comentário em `sessao._esq`: `from . import ESQUEMA` no topo COPIA o valor
    e o teste que redireciona não alcançaria a cópia."""
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _f(v) -> float | None:
    """Decimal do banco vira float NO LIMITE DO MÓDULO.

    Decimal não serializa, e a explosão não acontece aqui: acontece dentro do
    `JSONResponse.render()`, DEPOIS do try/except da rota — 500 em text/plain
    que o Cloudflare troca pela página dele, sem pista nenhuma de onde veio.
    """
    return None if v is None else float(v)


def _d(v) -> str | None:
    return v.isoformat() if isinstance(v, date) else (v or None)


#: O que o órgão manda quando não sabe. Visto no dado real ("NAO INFORMADO" no
#: município, com a UF preenchida). Mostrar o literal do fornecedor como se
#: fosse o nome de uma cidade é o mesmo defeito de "código sem tabela de
#: domínio virando rótulo": o campo tem valor, e o valor não é informação.
_VAZIO_DO_ORGAO = {"NAO INFORMADO", "NÃO INFORMADO", "NAO INFORMADA",
                   "SEM INFORMACAO", "N/D", "-"}


def _onde(municipio, uf) -> str:
    cid = (municipio or "").strip()
    if cid.upper() in _VAZIO_DO_ORGAO:
        cid = ""
    return " · ".join(p for p in [cid, (uf or "").strip()] if p)


def minhas(sessao: dict, esquema: str | None = None) -> dict:
    """As infrações das viagens de QUEM ESTÁ LOGADO.

    O código sai da SESSÃO, nunca do pedido — não há parâmetro de motorista
    aqui, e é de propósito: um argumento que a rota pudesse preencher com o
    que veio do navegador seria a diferença entre um app e um buscador da
    operação alheia.
    """
    hoje = date.today()
    linhas = pglocal.query(_SQL, {"mot": str(sessao["motorista_codigo"]),
                                  "dias": DIAS}, _esq(esquema))

    itens, abertas, notificacoes, pontos, valor = [], 0, 0, 0, 0.0
    for l in linhas:
        prazo = l["prazo_indicacao"]
        faltam = (prazo - hoje).days if prazo else None
        item = {
            "id": l["identificador"],
            "especie": l["especie"],
            "placa": l["placa"] or "",
            "data": _d(l["data_infracao"]),
            "hora": (l["hora"] or "")[:5],
            "descricao": l["descricao"] or "",
            "onde": _onde(l["municipio"], l["uf"]),
            "local": l["local_infracao"] or "",
            "valor": _f(l["valor_a_pagar"]),
            "valor_com_desconto": _f(l["valor_com_desconto"]),
            "pontos": l["pontuacao"],
            "vencimento": _d(l["vencimento"]),
            "prazo_indicacao": _d(prazo),
            "prazo_faltam": faltam,
            # O destaque só existe enquanto o prazo AINDA CORRE. Prazo vencido
            # não é "urgente", é passado — e pintar de vermelho o que não tem
            # mais ação treina a pessoa a ignorar a cor.
            "prazo_urgente": bool(faltam is not None and 0 <= faltam <= PRAZO_ALERTA_DIAS),
            "em_aberto": bool(l["em_aberto"]),
            "rota": l["rota"] or "",
            # HIPÓTESE, SEMPRE — não há caminho aqui que devolva `false`. O
            # campo existe para a página não ter de saber disso por fora.
            "hipotese": True,
            "disputada": (l["candidatas"] or 1) > 1,
        }
        itens.append(item)
        if item["em_aberto"]:
            if item["especie"] == "notificacao":
                notificacoes += 1
            else:
                abertas += 1
                valor += item["valor"] or 0.0
                # PONTO SÓ CONTA NA PENALIDADE. Somar a pontuação das
                # NOTIFICAÇÕES junto inflava o número em três vezes no primeiro
                # motorista medido (47 pontos, dos quais 12 de notificação em
                # aberto) — e uma notificação é a autuação, o estágio em que
                # ainda cabe defesa e indicação. Contar as duas é a mesma
                # armadilha de somar as espécies: conta o mesmo auto duas
                # vezes, num campo que assusta.
                pontos += item["pontos"] or 0

    return {
        "itens": itens,
        "resumo": {
            # As duas espécies SEPARADAS: somá-las conta o mesmo auto duas
            # vezes, e a ação de cada uma é outra (pagar × indicar/defender).
            "multas_abertas": abertas,
            "notificacoes_abertas": notificacoes,
            "valor_aberto": round(valor, 2),
            "pontos": pontos,
            "total_12m": len(itens),
            "com_prazo_urgente": sum(1 for i in itens if i["prazo_urgente"]),
        },
        # A RESSALVA DO PONTO, junto do número e não escrita na página: ponto
        # só migra para a CNH de alguém DEPOIS da indicação de condutor, que é
        # processo do órgão. O campo `motorista_nome` da Smartec mostra que a
        # frota está cheia de "NIC" e "AGREGADO" em vez de nome — ou seja, boa
        # parte destes pontos não chegou (e pode nunca chegar) a uma CNH.
        "pontos_ressalva": ("Pontos das multas já em penalidade. Eles só entram "
                            "numa CNH depois da indicação de condutor, que é "
                            "feita pela empresa junto ao órgão."),
        "janela_dias": DIAS,
        "atribuicao": ATRIBUICAO,
        "fonte": "Smartec (SNE/DETRAN) × viagem da placa no instante da infração",
    }
