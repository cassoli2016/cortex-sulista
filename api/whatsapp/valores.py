"""Quem preenche as variáveis de um modelo com os números de verdade.

Sem isto, um modelo de faturamento diário obrigaria alguém a digitar nove
valores todo dia, copiando da Visão Geral — que é justamente o tipo de tarefa
em que o erro passa despercebido (um dígito a menos no acumulado do mês e a
mensagem sai dizendo que a empresa faturou um décimo do que faturou).

A ARMADILHA DESTE MÓDULO, e a razão de ele existir separado: **o CÓRTEX tem
TRÊS recortes de receita que não são o mesmo número**, e a Visão Geral devolve
os três lado a lado —

    faturamento_mes        faturas emitidas          R$ 11,28 mi
    realizado_acumulado    a régua da META           R$ 10,73 mi
    receita_mes_cte        CT-e                      (outro corte ainda)

Misturar `faturamento_mes` com `meta_acumulada` produziria um atingimento de
96% onde o real é 91,3%: numerador de uma régua, denominador de outra. O par
que fecha é `realizado_acumulado / meta_acumulada` — é o mesmo que a Visão
Geral usa para o `atingimento_mes`, e é por isso que este módulo confere essa
conta em vez de recalcular por conta própria.

O DIA É O ÚLTIMO COM MOVIMENTO, não `hoje`: pela manhã o dia corrente tem
faturamento parcial e a série ainda traz zeros nos dias que não aconteceram.
Mandar "faturamos R$ 0 hoje" às 8h seria alarme falso diário.

E QUANDO ESSE DIA É O DE HOJE, A MENSAGEM DIZ QUE ESTÁ EM CURSO. Às 11h o dia
tinha 20% da meta — número correto e leitura desastrosa, porque faltavam nove
horas de faturamento. É a mesma regra que o painel aplica à barra do mês
corrente (hachurada, rotulada "parcial"); aqui não há hachura, então vai por
escrito no lugar em que a pessoa está olhando: o próprio atingimento.
"""
from __future__ import annotations

from datetime import date


def brl(valor) -> str:
    """R$ 1.234.567,89 — o formato que quem lê espera, sem depender de locale
    instalado no servidor (que no Windows desta bancada não está)."""
    try:
        n = float(valor or 0)
    except (TypeError, ValueError):
        return "R$ 0,00"
    inteiro, dec = f"{abs(n):,.2f}".split(".")
    inteiro = inteiro.replace(",", ".")
    return f"{'-' if n < 0 else ''}R$ {inteiro},{dec}"


def pct(valor) -> str:
    try:
        return f"{float(valor or 0) * 100:.1f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return "0,0%"


def _atingimento_dia(faturado: float, meta: float, em_curso: bool) -> str:
    """O atingimento do dia, dizendo quando o dia ainda não acabou.

    Sem a marca, o resumo das 11h anuncia 20% da meta — certo e desastroso,
    porque faltam nove horas de faturamento. Quem lê no celular não tem a
    hachura do painel para avisar; a frase precisa avisar sozinha.
    """
    if not meta:
        return "sem meta no dia"
    texto = pct(faturado / meta)
    return f"{texto} — dia ainda em curso" if em_curso else texto


def faturamento_diario(visao: dict | None = None) -> dict:
    """As variáveis do contexto `faturamento`, com os números do dia.

    `visao` é injetável para o teste não depender do ERP.
    """
    if visao is None:                       # pragma: no cover - caminho de produção
        from api import queries
        visao = queries.get_visao_geral()

    dias = visao.get("diario") or []
    # o último dia COM MOVIMENTO: os posteriores ainda não aconteceram, e um
    # deles é o dia corrente pela manhã, que sairia como "faturamos R$ 0"
    com_movimento = [d for d in dias if (d.get("realizado") or 0) > 0]
    dia = com_movimento[-1] if com_movimento else {}

    realizado = float(visao.get("realizado_acumulado") or 0)
    meta = float(visao.get("meta_acumulada") or 0)
    fat_dia = float(dia.get("realizado") or 0)
    meta_dia = float(dia.get("meta") or 0)

    hoje = date.today()
    numero_dia = int(dia.get("dia") or hoje.day)
    try:
        data = date(hoje.year, hoje.month, numero_dia).strftime("%d/%m/%Y")
    except ValueError:                      # pragma: no cover - dia fora do mês
        data = hoje.strftime("%d/%m/%Y")
    em_curso = numero_dia == hoje.day

    return {
        "data": data,
        "faturado_dia": brl(fat_dia),
        "meta_dia": brl(meta_dia),
        # dia sem meta (domingo, feriado) não é 0% de atingimento: é dia sem
        # meta a bater, e mostrar "0,0%" em vermelho seria acusar quem cumpriu
        "atingimento_dia": _atingimento_dia(fat_dia, meta_dia, em_curso),
        "acumulado_mes": brl(realizado),
        "meta_mes": brl(meta),
        # o atingimento vem PRONTO da Visão Geral: recalcular aqui abriria a
        # chance de usar o numerador de uma régua com o denominador de outra
        "atingimento_mes": pct(visao.get("atingimento_mes")),
        "falta_mes": brl(max(0.0, meta - realizado)),
        "mes_anterior": brl(visao.get("faturamento_mes_ant")),
    }


def smartec_prazo_indicacao(dados: dict | None = None) -> dict:
    """As variáveis do contexto `smartec_prazo`.

    DUAS COISAS QUE ESTA FUNÇÃO FAZ E QUE NÃO SÃO ÓBVIAS:

    1. **`_silencio` quando não há nada vencendo.** Não é erro, é a resposta
       certa: mandar "0 notificações vencem hoje" toda manhã transforma o aviso
       em ruído, e o dia em que houver três ninguém vai ler. Quem trata isso é
       `agenda.montar_texto`, que distingue os três estados — mandou, não
       mandou por falha, não havia o que mandar.

    2. **NENHUMA VARIÁVEL SAI VAZIA.** `montar_texto` recusa o envio se
       qualquer variável do modelo vier em branco — guarda certa, que existe
       para "Faturamento de hoje: R$ 0,00" não chegar à diretoria. Aqui isso
       morde num caso específico: quando só há notificações vencendo HOJE e
       nenhuma nos próximos dias, `proximos` ficaria vazio e o aviso inteiro
       seria engolido — justamente no dia mais urgente. Por isso `proximos` tem
       texto também quando não há próximos.

    `dados` é injetável para o teste não depender do banco.
    """
    if dados is None:                       # pragma: no cover - produção
        from api.smartec import leitura
        dados = leitura.prazo_indicacao_alerta(dias=2)

    if dados.get("erro"):
        # Não dá para SABER. Sobe como exceção para `montar_texto` registrar o
        # motivo e não enviar — silenciar aqui seria afirmar que não há prazo
        # correndo quando a verdade é que ninguém está olhando.
        raise ValueError(dados["erro"])
    if dados.get("silencio"):
        return {"_silencio": dados["silencio"]}

    hoje = dados.get("hoje") or []
    depois = dados.get("depois") or []

    linhas = []
    for x in hoje:
        pts = x.get("pontuacao")
        linhas.append("\U0001f69b *%s*" % (x.get("placa") or "?"))
        linhas.append("     %s" % (x.get("descricao") or "infração não descrita"))
        linhas.append("     \U0001f4c4 AIT %s · %s"
                      % (x.get("ait") or "?",
                         x.get("orgao") or "órgão não informado"))
        linhas.append("     \U0001f4b0 %s  ·  ⚠️ %s pontos"
                      % (brl(x.get("valor_a_pagar")),
                         pts if pts is not None else "?"))
        linhas.append("")
    lista = "\n".join(linhas).rstrip()

    if depois:
        por_dia: dict[int, list[str]] = {}
        for x in depois:
            por_dia.setdefault(int(x["dias"]), []).append(x.get("placa") or "?")
        partes = []
        for d in sorted(por_dia):
            quando = "Amanhã" if d == 1 else "Em %d dias" % d
            partes.append("%s vencem mais *%d*: %s"
                          % (quando, len(por_dia[d]), ", ".join(por_dia[d])))
        proximos = "\U0001f4c5 " + " · ".join(partes)
    else:
        # NUNCA vazio — ver a nota 2 no cabeçalho.
        proximos = "✅ Nenhuma outra vence nos próximos dias."

    return {
        "data": date.today().strftime("%d/%m/%Y"),
        "quantidade": str(len(hoje)),
        "lista": lista,
        "total": brl(dados.get("total_hoje")),
        "proximos": proximos,
    }


PROVEDORES = {"faturamento_diario": faturamento_diario,
              "smartec_prazo_indicacao": smartec_prazo_indicacao}


def obter(nome: str) -> dict:
    """Valores do provedor pedido. Nome desconhecido devolve vazio, e não
    exceção: a tela pergunta por um provedor que pode não existir para aquele
    contexto, e isso é resposta normal, não erro."""
    fn = PROVEDORES.get(str(nome or ""))
    return fn() if fn else {}
