"""Parâmetros e pesos da premiação, versionados por competência.

POR QUE VERSIONADO E NÃO EDITADO NO LUGAR
=========================================
Premiação decide dinheiro de gente, e a pergunta "por que eu recebi isso em
março?" sempre aparece — normalmente meses depois, quando quem configurou já
mudou o peso três vezes. Editar por cima deixa essa pergunta sem resposta.

Cada mudança cria uma VERSÃO com `vigente_de` (competência). O cálculo de uma
competência usa a última versão vigente ATÉ ela. Configurar agosto não mexe em
julho, e não é preciso lembrar de nada para isso valer.

O que protege o passado de verdade é o SNAPSHOT do cálculo, que já guarda o
resultado por motorista. A versão explica COMO se chegou nele.

OS EIXOS SÃO UM CATÁLOGO NO CÓDIGO, os pesos são dado
=====================================================
Eixo é código: alguém precisa escrever a consulta que mede diesel. Peso é
política: muda com a diretoria, não com o software. Por isso o catálogo vive
aqui e o número vive no banco.

Eixo com peso ZERO não é o mesmo que eixo DESLIGADO. Zero é uma escolha
("mediu, não vale nota"); desligado é "não entra na conta e nem aparece". A
diferença importa ao ligar um eixo aos poucos — liga, olha o efeito, desliga
se estiver ruim, sem perder o número que já tinha sido combinado.
"""
from __future__ import annotations

from datetime import datetime

from .. import pglocal

ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


# ── catálogo de eixos ────────────────────────────────────────────────────────
EIXOS: dict[str, dict] = {
    "diesel": {
        "rotulo": "Economia de diesel",
        "fonte": "CTA Plus (bomba) · Gobrax (conferência)",
        "medida": "km/l do motorista contra a média do MESMO veículo no mês",
        "porque": "2,8 km/l é bom ou ruim? Depende de veículo, rota e carga. "
                  "Comparar contra o próprio veículo neutraliza o que o "
                  "motorista não controla.",
        "peso": 25,
    },
    "conducao": {
        "rotulo": "Condução",
        "fonte": "Gobrax vehicle-performance",
        "medida": "motor ligado parado e faixa verde (Gobrax), uso de ECO e "
                  "embalo, frenagem brusca por 1.000 km",
        "porque": "É o comportamento que gera economia e reduz sinistro, "
                  "medido antes de virar consequência.",
        "peso": 15,
    },
    "produtividade": {
        "rotulo": "Produtividade",
        "fonte": "ERP viagens · RasterJOR jornada",
        "medida": "km carregado por jornada trabalhada",
        "porque": "Por jornada e não em valor absoluto: quem roda 8.000 km "
                  "não pode ser comparado com quem roda 1.200.",
        "peso": 20,
    },
    "efetividade": {
        "rotulo": "Efetividade no serviço",
        "fonte": "ERP ocorrências de motorista",
        "medida": "atraso de janela, recusa e coleta não realizada por 1.000 km",
        "porque": "É o que o cliente sente. Separado de conduta porque a "
                  "correção é outra: processo, não disciplina.",
        "peso": 15,
    },
    "conduta": {
        "rotulo": "Conduta e segurança",
        "fonte": "ERP ocorrências · multas",
        "medida": "pontos de demérito ponderados por gravidade, menos méritos",
        "porque": "Único eixo que pode SOMAR: existe mérito no cadastro "
                  "(elogio de cliente, ajuda à operação).",
        "peso": 15,
    },
    "jornada": {
        "rotulo": "Conformidade de jornada",
        "fonte": "RasterJOR",
        "medida": "inconformidades de TEMPO por jornada (Lei 13.103)",
        "porque": "Direção noturna fica de fora: é trabalho legal com "
                  "adicional, não violação.",
        "peso": 10,
    },
}

# ── catálogo de parâmetros ───────────────────────────────────────────────────
PARAMS: dict[str, dict] = {
    "valor_por_km": {
        "rotulo": "Valor por km", "unidade": "R$", "padrao": 0.10,
        "min": 0.0, "max": 10.0,
        "ajuda": "Base do prêmio. O valor final é km × este valor × nota/100."},
    "nota_minima": {
        "rotulo": "Nota mínima para receber", "unidade": "pontos",
        "padrao": 70.0, "min": 0.0, "max": 100.0,
        "ajuda": "Abaixo disto a linha aparece na lista com o motivo, e fica "
                 "fora do total — não some."},
    # ── régua de condução (Gobrax) ──────────────────────────────────────
    # Os padrões saem da frota REAL medida em 30/08/2026 sobre 98 placas, não
    # de número redondo: motor ligado parado tem p25 9,2% / mediana 12,7% /
    # p75 16,7% / máximo 60,4%. O alvo fica no quartil de cima e o teto acima
    # do p75, onde começa a cauda que realmente destoa.
    "idle_alvo": {
        "rotulo": "Motor ligado parado — alvo", "unidade": "%", "padrao": 10.0,
        "min": 0.0, "max": 100.0,
        "ajuda": "Neste percentual ou abaixo, nota cheia no indicador. O padrão "
                 "de 10% fica no quartil superior da frota (p25 = 9,2%)."},
    "idle_teto": {
        "rotulo": "Motor ligado parado — teto", "unidade": "%", "padrao": 25.0,
        "min": 0.0, "max": 100.0,
        "ajuda": "Neste percentual ou acima, nota zero. Entre alvo e teto a "
                 "nota cai linearmente. O padrão de 25% fica acima do p75 da "
                 "frota (16,7%), onde começa a cauda que destoa."},
    # FAIXA VERDE É PISO, NÃO GRADAÇÃO: a metade central da frota vai de 93,8%
    # a 98,8% — cinco pontos. Graduar aí daria a mesma nota para todo mundo.
    "verde_piso": {
        "rotulo": "Faixa verde — piso", "unidade": "%", "padrao": 85.0,
        "min": 0.0, "max": 100.0,
        "ajuda": "Acima disto não pontua nem penaliza: metade da frota está "
                 "entre 93,8% e 98,8% e premiar diferença aí seria premiar "
                 "ruído. Abaixo, desconta — porque aí é desvio de verdade."},
    "verde_desconto_max": {
        "rotulo": "Faixa verde — desconto máximo", "unidade": "pontos",
        "padrao": 20.0, "min": 0.0, "max": 100.0,
        "ajuda": "Desconto na nota de condução quando a faixa verde chega a "
                 "zero. Entre o piso e zero o desconto cresce linearmente."},
    "km_minimo": {
        "rotulo": "Km mínimo no mês", "unidade": "km", "padrao": 1500.0,
        "min": 0.0, "max": 100000.0,
        "ajuda": "Piso de materialidade. Quem rodou pouco tem indicador "
                 "instável e não entra no ranking."},
    "jornadas_minimas": {
        "rotulo": "Jornadas mínimas no mês", "unidade": "jornadas",
        "padrao": 8.0, "min": 0.0, "max": 31.0,
        "ajuda": "Mesmo motivo do km mínimo, pelo lado da jornada."},
    "teto_por_motorista": {
        "rotulo": "Teto por motorista", "unidade": "R$", "padrao": 0.0,
        "min": 0.0, "max": 100000.0,
        "ajuda": "Zero = sem teto. Existe para um mês atípico não virar um "
                 "pagamento que ninguém aprovou."},
    "janela_conduta_meses": {
        "rotulo": "Janela da conduta", "unidade": "meses", "padrao": 12.0,
        "min": 1.0, "max": 60.0,
        "ajuda": "Ocorrência prescreve: uma de janeiro não pode pesar igual "
                 "no prêmio de dezembro."},
    "dias_apuracao": {
        "rotulo": "Carência para apurar", "unidade": "dias", "padrao": 10.0,
        "min": 0.0, "max": 90.0,
        "ajuda": "Dias APÓS o fim da competência antes de considerá-la "
                 "fechada. Ocorrência, multa e abastecimento continuam "
                 "chegando depois do dia 1º — sem esta carência, um snapshot "
                 "tirado cedo congela um mês incompleto e nunca mais é "
                 "recoletado."},
    "abastecimentos_minimos": {
        "rotulo": "Abastecimentos mínimos", "unidade": "abast.",
        "padrao": 3.0, "min": 0.0, "max": 50.0,
        "ajuda": "Abaixo disto o eixo de diesel não é medível para o "
                 "motorista e SAI do cálculo dele — não vira nota zero."},
}


def defaults() -> dict:
    return {k: v["padrao"] for k, v in PARAMS.items()}


# ── versões ──────────────────────────────────────────────────────────────────
def _competencia_valida(c: str) -> str:
    c = (c or "").strip()
    if len(c) != 7 or c[4] != "-" or not (c[:4] + c[5:]).isdigit():
        raise ValueError("Competência inválida — use AAAA-MM.")
    if not (1 <= int(c[5:]) <= 12):
        raise ValueError("Mês inválido na competência.")
    return c


def versoes(esquema: str | None = None) -> list[dict]:
    return [dict(r) for r in pglocal.query(
        """SELECT id, vigente_de, regra, nota, criado_em, criado_por
             FROM prem_versoes ORDER BY vigente_de DESC""",
        esquema=_esq(esquema))]


def versao_de(competencia: str, esquema: str | None = None) -> dict | None:
    """A versão que VALE para esta competência: a última vigente até ela.

    `<=` e não `=`: configurar uma vez em janeiro tem de valer para fevereiro,
    março e o resto do ano. Exigir uma versão por mês faria a premiação parar
    de calcular no primeiro mês em que alguém esquecesse.
    """
    r = pglocal.um(
        """SELECT id, vigente_de, regra, nota, criado_em, criado_por
             FROM prem_versoes WHERE vigente_de <= %s
            ORDER BY vigente_de DESC LIMIT 1""",
        (_competencia_valida(competencia),), esquema=_esq(esquema))
    return dict(r) if r else None


def ler(competencia: str, esquema: str | None = None) -> dict:
    """Parâmetros e eixos vigentes para a competência.

    Sem versão nenhuma, devolve os PADRÕES marcados como tal. A tela precisa
    abrir e mostrar de onde vem cada número; travar por falta de configuração
    esconderia justamente a configuração que falta fazer.
    """
    v = versao_de(competencia, esquema)
    if not v:
        return {"competencia": competencia, "versao": None, "padrao": True,
                "params": defaults(),
                "eixos": {k: {"peso": float(e["peso"]), "ativo": 1}
                          for k, e in EIXOS.items()}}
    esq = _esq(esquema)
    p = {r["chave"]: float(r["valor"]) for r in pglocal.query(
        "SELECT chave, valor FROM prem_parametros WHERE versao_id=%s",
        (v["id"],), esquema=esq)}
    e = {r["eixo"]: {"peso": float(r["peso"]), "ativo": int(r["ativo"])}
         for r in pglocal.query(
             "SELECT eixo, peso, ativo FROM prem_eixos WHERE versao_id=%s",
             (v["id"],), esquema=esq)}
    # PARÂMETRO NOVO NO CÓDIGO cai no padrão em vez de sumir: um deploy que
    # acrescenta parâmetro não pode fazer versões antigas pararem de calcular.
    params = {**defaults(), **p}
    eixos = {k: e.get(k) or {"peso": float(v0["peso"]), "ativo": 1}
             for k, v0 in EIXOS.items()}
    return {"competencia": competencia, "versao": v, "padrao": False,
            "params": params, "eixos": eixos}


def _valida(params: dict, eixos: dict) -> None:
    for chave, meta in PARAMS.items():
        if chave not in params:
            continue
        try:
            v = float(params[chave])
        except (TypeError, ValueError):
            raise ValueError(f"'{meta['rotulo']}' precisa ser um número.") from None
        if not (meta["min"] <= v <= meta["max"]):
            raise ValueError(
                f"'{meta['rotulo']}' precisa estar entre {meta['min']:g} e "
                f"{meta['max']:g}.")
    if params.get("valor_por_km", 0) <= 0:
        raise ValueError("O valor por km tem de ser maior que zero.")
    ativos = [k for k, e in eixos.items() if int(e.get("ativo", 1))]
    if not ativos:
        raise ValueError("Ao menos um eixo precisa estar ativo.")
    soma = sum(float(eixos[k].get("peso") or 0) for k in ativos)
    if soma <= 0:
        raise ValueError("A soma dos pesos dos eixos ativos tem de ser maior "
                         "que zero.")


def salvar(competencia: str, params: dict, eixos: dict, *, autor: str = "",
           nota: str = "", esquema: str | None = None) -> dict:
    """Grava a versão que passa a valer a partir da competência.

    Salvar de novo na MESMA competência atualiza aquela versão, em vez de
    criar uma segunda vigente no mesmo mês — duas versões para o mesmo mês
    seriam duas respostas para a mesma pergunta. O que impede isso de
    reescrever pagamento é o snapshot, que congela o resultado.
    """
    comp = _competencia_valida(competencia)
    _valida(params, eixos)
    agora = datetime.now().isoformat(timespec="seconds")
    esq = _esq(esquema)
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        r = cur.execute("SELECT id FROM prem_versoes WHERE vigente_de=%s",
                        (comp,)).fetchone()
        if r:
            vid = r["id"]
            cur.execute("UPDATE prem_versoes SET nota=%s, criado_em=%s,"
                        " criado_por=%s WHERE id=%s", (nota, agora, autor, vid))
            cur.execute("DELETE FROM prem_parametros WHERE versao_id=%s", (vid,))
            cur.execute("DELETE FROM prem_eixos WHERE versao_id=%s", (vid,))
        else:
            vid = cur.execute(
                """INSERT INTO prem_versoes (vigente_de, regra, nota,
                                             criado_em, criado_por)
                   VALUES (%s,'eixos',%s,%s,%s) RETURNING id""",
                (comp, nota, agora, autor)).fetchone()["id"]
        for chave in PARAMS:
            if chave in params:
                cur.execute("INSERT INTO prem_parametros (versao_id, chave,"
                            " valor) VALUES (%s,%s,%s)",
                            (vid, chave, float(params[chave])))
        for eixo in EIXOS:
            e = eixos.get(eixo) or {}
            cur.execute("INSERT INTO prem_eixos (versao_id, eixo, peso, ativo)"
                        " VALUES (%s,%s,%s,%s)",
                        (vid, eixo, float(e.get("peso") or 0),
                         1 if int(e.get("ativo", 1)) else 0))
        cx.commit()
    return ler(comp, esquema)


def catalogo() -> dict:
    """O que a tela precisa para se desenhar sozinha."""
    return {"eixos": EIXOS, "params": PARAMS}
