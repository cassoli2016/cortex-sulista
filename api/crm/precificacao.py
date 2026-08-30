"""Precificação da lane: R$/km, piso mínimo da ANTT e margem contra o CKM.

É a razão de o CRM viver dentro do CÓRTEX. Um CRM genérico registra "R$ 4.800
por viagem" e não sabe dizer se esse preço é legal nem se dá lucro; aqui os
dois números já existem na casa, e a cotação passa a responder as duas
perguntas na hora em que o vendedor digita o valor — que é o único momento em
que ainda dá para mudar.

TRÊS CUIDADOS, e cada um vem de um erro que a casa já cometeu:

1. **NADA é gravado.** O piso da ANTT depende da tabela vigente NA DATA da
   viagem, e ela muda duas vezes por ano. Um piso congelado no dia da proposta
   reprovaria em agosto um frete correto, ou — pior — aprovaria em silêncio um
   frete que passou a estar abaixo do mínimo legal.

2. **O CKM é UM SÓ para todas as lanes, e isso é dito, não escondido.** O razão
   contábil é consolidado: não existe CKM por rota nesta casa. Uma coluna "CKM
   da lane" repetindo R$ 12,60 em vinte linhas passaria a impressão de cálculo
   por rota — foi exatamente o que a tela de Make vs Buy fez e teve de desfazer.
   O que varia por lane, e portanto merece coluna, é a MARGEM (R$/km − CKM),
   porque o R$/km é da lane.

3. **Ausência não é zero.** Lane sem km, sem eixos ou sem tipo de carga não tem
   piso "R$ 0,00": tem piso NÃO CALCULÁVEL, e a tela diz isso. Aprovar um frete
   porque o piso desconhecido virou zero é o oposto do que esta conferência
   existe para fazer.
"""
from __future__ import annotations

from datetime import date

from ..antt.piso import avaliar, calcular_piso

# Explicação dos estados que `api/antt/piso.py` devolve, em português de quem
# opera. Sem isto a tela mostraria "sem_eixos" para um vendedor.
MOTIVO_SEM_PISO = {
    "sem_km": "informe a distância da rota",
    "sem_eixos": "informe o veículo (é dele que saem os eixos)",
    "sem_carga": "informe o tipo de carga da tabela ANTT",
    "sem_tabela": "não há coeficiente ANTT para esta combinação de carga e eixos",
    "sem_valor": "informe o valor da viagem",
    "isento": "retorno vazio sem pagamento obrigatório — não há piso",
}


def _f(v) -> float | None:
    """`Decimal` do psycopg vira float; None continua None.

    None e 0.0 têm de continuar distinguíveis por todo este módulo: 0 é um
    preço (ruim, mas um preço) e None é campo em branco, e tratar os dois igual
    faria a lane não preenchida aparecer como frete de graça.
    """
    return None if v is None else float(v)


def avaliar_lane(lane: dict, *, ckm_marginal: float | None = None,
                 ckm_cheio: float | None = None,
                 quando: date | None = None) -> dict:
    """Os derivados de uma lane. Não altera a lane; devolve um dicionário novo.

    `quando` é a data da tabela ANTT a usar — hoje, por padrão. Fica como
    parâmetro porque a conferência de um contrato antigo tem de usar a tabela
    vigente na época, senão todo período fechado se reescreve a cada reajuste
    da ANTT (é a regra de `api/antt/coeficientes.py`).
    """
    dia = quando or date.today()
    km = _f(lane.get("km"))
    km_vazio = _f(lane.get("km_vazio")) or 0.0
    viagens = _f(lane.get("viagens_mes"))
    valor = _f(lane.get("valor_viagem"))
    pedagio = _f(lane.get("pedagio")) or 0.0
    eixos = lane.get("eixos")
    carga = (lane.get("tipo_carga") or "").strip()

    out: dict = {
        "km_total_viagem": (km + km_vazio) if km is not None else None,
        "receita_mes": (valor * viagens) if (valor is not None and viagens) else None,
        "km_mes": ((km + km_vazio) * viagens) if (km is not None and viagens) else None,
    }

    # R$/km CARREGADO (o RKM do glossário), que é o número comparável ao CKM
    # produtivo e ao que se paga a agregado. O denominador é o km carregado, não
    # o total: usar o total daria um R$/km menor e faria toda lane parecer mais
    # barata do que é.
    out["rkm"] = (valor / km) if (valor is not None and km) else None

    # E o R$/km sobre o km TOTAL, que é o que o caminhão de fato roda. A
    # diferença entre os dois É o custo do retorno vazio, e mostrá-los lado a
    # lado é o que impede a lane de 400 km de ida com 400 de volta vazia de
    # parecer tão boa quanto a que tem carga nos dois sentidos.
    out["rkm_total"] = (valor / (km + km_vazio)) if (
        valor is not None and km is not None and (km + km_vazio) > 0) else None
    out["retorno_vazio"] = (km_vazio / (km + km_vazio)) if (
        km is not None and (km + km_vazio) > 0) else None

    # ------------------------------------------------------------ piso ANTT --
    p = calcular_piso(km or 0.0, carga or None, eixos, dia)
    p = avaliar(valor or 0.0, p)
    out["piso"] = {
        "estado": p["estado"],
        "valor": p.get("piso"),
        "ccd": p.get("ccd"),
        "cc": p.get("cc"),
        "resolucao": p.get("resolucao"),
        "gap": p.get("gap"),
        "abaixo": bool(p.get("abaixo")),
        "motivo": MOTIVO_SEM_PISO.get(p["estado"]) if p["estado"] != "calculado" else None,
    }
    # Piso por km, para o vendedor comparar com o R$/km que ele digitou sem ter
    # de dividir de cabeça. O rótulo do eixo nomeia a unidade final — mesma
    # regra que tirou o "MIL KM ×1000" da Análise de KM.
    out["piso"]["por_km"] = (p["piso"] / km) if (p.get("piso") and km) else None

    # O pedágio NÃO entra no piso e é dito: a Res. 5.867/2020 remunera
    # deslocamento e carga/descarga, e o pedágio é repasse. Somá-lo ao valor da
    # viagem antes de comparar com o piso aprovaria frete abaixo do mínimo
    # legal usando dinheiro que é do pedágio.
    out["pedagio_mes"] = (pedagio * viagens) if (pedagio and viagens) else None

    # ------------------------------------------------------------- margem --
    # A MARGEM varia por lane porque o R$/km varia; o CKM é o mesmo para todas
    # e por isso vai no rodapé da tela, não numa coluna. Sobre o km TOTAL, que
    # é o que consome combustível e motorista — comparar receita de km
    # carregado contra custo de km carregado esconde o vazio.
    out["ckm_marginal"] = ckm_marginal
    out["ckm_cheio"] = ckm_cheio
    rkm_t = out["rkm_total"]
    out["margem_km"] = (rkm_t - ckm_marginal) if (
        rkm_t is not None and ckm_marginal) else None
    out["margem_km_cheio"] = (rkm_t - ckm_cheio) if (
        rkm_t is not None and ckm_cheio) else None
    out["margem_mes"] = (out["margem_km"] * out["km_mes"]) if (
        out.get("margem_km") is not None and out.get("km_mes")) else None
    out["margem_pct"] = (out["margem_km"] / rkm_t) if (
        out.get("margem_km") is not None and rkm_t) else None

    # ------------------------------------------------------------ veredito --
    out["alerta"] = _alerta(out)
    return out


def _brl(v: float) -> str:
    """`4550.48` → `4.550,48`.

    A troca ingênua (`f"{v:,.2f}".replace(",", ".")`) produz `4.550.48`, com
    DOIS pontos e nenhuma vírgula — número que parece um IP e some da leitura.
    A conversão precisa trocar os dois separadores ao mesmo tempo, e por isso
    passa por um marcador intermediário.
    """
    return f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _alerta(d: dict) -> dict | None:
    """O que a lane exige de quem está cotando, em ordem de gravidade.

    Só UM alerta, o mais grave — três chips numa linha de tabela viram ruído e
    o leitor para de ler o primeiro. Abaixo do piso vem antes de margem
    negativa porque o primeiro é ilegal e o segundo é só ruim.
    """
    piso = d.get("piso") or {}
    if piso.get("abaixo"):
        gap = abs(piso.get("gap") or 0)
        return {"nivel": "alerta",
                "texto": f"abaixo do piso ANTT em R$ {_brl(gap)}",
                "detalhe": ("O piso mínimo da Lei 13.703/2018 é obrigatório. "
                            "Frete abaixo dele expõe a empresa a autuação e a "
                            "ação do transportador.")}
    m = d.get("margem_km")
    if m is not None and m < 0:
        return {"nivel": "alerta", "texto": "margem negativa",
                "detalhe": ("O R$/km sobre o km total está abaixo do custo "
                            "marginal da frota própria (variável + motorista). "
                            "Rodar esta lane com veículo próprio dá prejuízo "
                            "antes de qualquer custo fixo.")}
    rv = d.get("retorno_vazio")
    if rv is not None and rv > 0.30:
        return {"nivel": "aviso",
                "texto": f"retorno vazio {rv * 100:.0f}%",
                "detalhe": ("Acima de 30% o vazio come a margem. Vale procurar "
                            "carga de retorno antes de fechar o preço.")}
    if m is not None and d.get("margem_pct") is not None and d["margem_pct"] < 0.10:
        return {"nivel": "aviso", "texto": "margem apertada",
                "detalhe": ("Menos de 10% sobre o custo marginal — não cobre o "
                            "rateio de fixo e depreciação.")}
    return None


def resumir(lanes: list[dict]) -> dict:
    """Totais da oportunidade a partir das lanes já avaliadas.

    A receita da oportunidade é ESTA soma, calculada na leitura — não há coluna
    `receita_mensal` gravada em `crm_oportunidades`, justamente para que o total
    nunca discorde das linhas que o compõem.

    `lanes_sem_preco` existe porque o total de uma oportunidade com três lanes
    cotadas e duas em branco não é o valor do negócio, e apresentá-lo como se
    fosse é a mesma armadilha do "ROB R$ 0 em verde" do CRM antigo: parecia
    pipeline sem valor, era lacuna de cadastro.
    """
    receita = 0.0
    km_mes = 0.0
    margem = 0.0
    tem_receita = tem_margem = False
    sem_preco = 0
    abaixo_piso = 0
    sem_piso = 0
    for ln in lanes:
        d = ln.get("calc") or {}
        if d.get("receita_mes") is None:
            sem_preco += 1
        else:
            receita += d["receita_mes"]
            tem_receita = True
        if d.get("km_mes"):
            km_mes += d["km_mes"]
        if d.get("margem_mes") is not None:
            margem += d["margem_mes"]
            tem_margem = True
        piso = d.get("piso") or {}
        if piso.get("abaixo"):
            abaixo_piso += 1
        elif piso.get("estado") not in ("calculado", "isento"):
            sem_piso += 1
    return {
        "lanes": len(lanes),
        "receita_mes": receita if tem_receita else None,
        "km_mes": km_mes or None,
        "margem_mes": margem if tem_margem else None,
        "margem_pct": (margem / receita) if (tem_margem and receita) else None,
        "rkm_medio": (receita / km_mes) if (tem_receita and km_mes) else None,
        "lanes_sem_preco": sem_preco,
        "lanes_abaixo_piso": abaixo_piso,
        "lanes_sem_piso": sem_piso,
    }


def referencia_ckm(comp_de: str | None = None,
                   comp_ate: str | None = None) -> dict:
    """O CKM da casa, lido de onde ele já é calculado — nunca recalculado aqui.

    Reusa `queries.get_make_vs_buy`, que é a fonte do CKM no CÓRTEX. Uma segunda
    implementação daria um quinto número de custo por km numa casa que já
    precisa explicar três de receita, e a divergência apareceria numa reunião,
    não num teste.

    Falha do AVA devolve `disponivel: False` COM o motivo, e a tela mostra a
    lane sem margem em vez de esconder a lane: a cotação continua útil sem o
    CKM (o piso da ANTT não depende dele), e derrubar a tela inteira porque o
    razão não respondeu seria trocar uma informação a menos por nenhuma.
    """
    from datetime import date as _d
    hoje = _d.today()
    # Janela padrão: os 6 meses fechados anteriores. O mês corrente NÃO entra —
    # a competência aberta recebe o rateio de fixos incompleto e derruba o CKM
    # artificialmente (medido na Make vs Buy: R$ 26 caindo para R$ 15 em jul/26).
    fim = hoje.replace(day=1)
    ini = fim
    for _ in range(6):
        ini = (ini.replace(day=1) - __import__("datetime").timedelta(days=1)).replace(day=1)
    de = comp_de or ini.strftime("%Y-%m")
    ate = comp_ate or (fim - __import__("datetime").timedelta(days=1)).strftime("%Y-%m")
    try:
        from .. import queries
        mvb = queries.get_make_vs_buy(de, ate)
        r = mvb.get("resumo") or {}
        return {
            "disponivel": r.get("ckm_marginal") is not None,
            "ckm_marginal": r.get("ckm_marginal"),
            "ckm_cheio": r.get("ckm_cheio"),
            "rs_km_agregado": r.get("rs_km_agregado"),
            "competencia_de": de, "competencia_ate": ate,
            "fonte": ("razão contábil consolidado × km da programação de "
                      "embarque · Make vs Buy · consolidado da frota, NÃO por rota"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "ckm_marginal": None, "ckm_cheio": None,
                "competencia_de": de, "competencia_ate": ate,
                "erro": type(exc).__name__,
                "fonte": "indisponível — o razão do AVA não respondeu"}
