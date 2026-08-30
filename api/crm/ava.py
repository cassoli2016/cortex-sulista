"""A ponte entre o CRM e a RECEITA REAL do ERP.

É o que torna este CRM diferente de um CRM genérico com os mesmos campos: a
conta não diz só o que o vendedor prometeu, diz o que o cliente de fato
faturou, de onde sai a única resposta honesta para "este cliente está ativo?".

Duas regras estruturam o módulo:

1. **O vínculo é o GRUPO ECONÔMICO (`agrupamentocliente.codigo`), não o CNPJ.**
   É a chave que o CÓRTEX inteiro já usa para cliente — DRE por Cliente,
   Consulta de Cliente, meta de faturamento. Casar por CNPJ aqui criaria um
   quarto recorte de receita numa casa que já tem três, e a lição do resumo de
   faturamento é exatamente essa: misturar o numerador de uma régua com o
   denominador de outra dá 96% de atingimento onde o real é 91,3%.

2. **NADA é gravado.** Situação da conta, dias sem viagem e receita dos últimos
   12 meses são lidos do AVA a cada leitura. Um `crm_contas.situacao` gravado
   diria "cliente ativo" para sempre sobre quem parou de rodar em 2024 — a
   mesma família de erro do marcador de manutenção preventiva parado em 77.534
   km com o odômetro em 531.970.

O AVA é PostgreSQL 9.3: sem `FILTER (WHERE …)`, todo agregado condicional é
`CASE WHEN`. O erro dessa versão aponta para o meio do agregado
(`syntax error at or near "("`), não para a versão.
"""
from __future__ import annotations

from .. import db
from ..queries import cached

# Janela de leitura. 730 dias e não 365 porque a pergunta que importa é "há
# quanto tempo NÃO roda", e uma janela de um ano devolveria NULL tanto para
# quem parou há 13 meses quanto para quem nunca foi cliente — dois estados
# opostos com a mesma cara. Além de dois anos, "parado há mais de 730 dias" já
# diz tudo o que há a dizer.
JANELA_DIAS = 730

# Corte de carteira parada. 90 dias é o padrão da casa para operação de
# lotação: cliente de contrato roda toda semana, e três meses sem uma viagem
# não é sazonalidade, é conta perdida ou prestes a ser. É SUGESTÃO da tela, não
# regra do banco — quem olha pode mudar o corte.
PARADA_DIAS = 90

# A dedução por DISTINCT ON repete a de `CLIF_VIAGENS_SQL` (Consulta de
# Cliente) de propósito: o JOIN com `coleta` multiplica linhas de
# `programacaoembarque`, e sem a deduplicação a receita do cliente sai inflada.
# Contar a mesma viagem duas vezes aqui faria a conta parecer mais ativa do que
# é, que é justamente o erro que este módulo existe para não cometer.
CARTEIRA_SQL = """
SELECT ag,
       max(data) AS ultima_viagem,
       min(data) AS primeira_viagem,
       sum(CASE WHEN data >= current_date - 365 THEN valorfrete ELSE 0 END)::float8
           AS receita_12m,
       sum(CASE WHEN data >= current_date - 90 THEN valorfrete ELSE 0 END)::float8
           AS receita_90d,
       sum(CASE WHEN data >= current_date - 365 THEN 1 ELSE 0 END)
           AS viagens_12m,
       sum(CASE WHEN data >= current_date - 365 THEN km ELSE 0 END)::float8
           AS km_12m
FROM (
  SELECT DISTINCT ON (p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero)
         av.codigo AS ag,
         coalesce(p.dtchegada, p.dtsaida, p.dtemissao)::date AS data,
         coalesce(p.valorfrete, 0) AS valorfrete,
         coalesce(p.kmfretecompra, 0) AS km
  FROM programacaoembarque p
  JOIN coleta co ON co.grupo = p.grupo AND co.empresa = p.empresa
    AND co.filial = p.filialdocumentoorigem
    AND co.unidade = p.unidadedocumentoorigem
    AND co.diferenciadornumero = p.diferenciadornumerodocumentoorigem
    AND co.numero = p.numerodocumentoorigem
  JOIN agrupamentocliente_cnpjcpfcodigo av
    ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
  WHERE av.codigo = ANY(%(ags)s)
    AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
    AND coalesce(p.dtchegada, p.dtsaida, p.dtemissao) >= current_date - %(janela)s
  ORDER BY p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero,
           coalesce(p.dtchegada, p.dtsaida, p.dtemissao) DESC
) x
GROUP BY ag
"""

AGRUPAMENTOS_SQL = """
SELECT codigo, trim(descricao) AS nome
FROM agrupamentocliente
WHERE coalesce(trim(descricao), '') <> ''
ORDER BY 2
"""

# Série mensal de UM cliente, para o gráfico da ficha. Mesma dedução, mesma
# fonte — a ficha não pode discordar da lista que a trouxe.
SERIE_SQL = """
SELECT to_char(data, 'YYYY-MM') AS mes,
       sum(valorfrete)::float8 AS receita,
       count(*) AS viagens,
       sum(km)::float8 AS km
FROM (
  SELECT DISTINCT ON (p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero)
         coalesce(p.dtchegada, p.dtsaida, p.dtemissao)::date AS data,
         coalesce(p.valorfrete, 0) AS valorfrete,
         coalesce(p.kmfretecompra, 0) AS km
  FROM programacaoembarque p
  JOIN coleta co ON co.grupo = p.grupo AND co.empresa = p.empresa
    AND co.filial = p.filialdocumentoorigem
    AND co.unidade = p.unidadedocumentoorigem
    AND co.diferenciadornumero = p.diferenciadornumerodocumentoorigem
    AND co.numero = p.numerodocumentoorigem
  JOIN agrupamentocliente_cnpjcpfcodigo av
    ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
  WHERE av.codigo = %(ag)s
    AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
    AND coalesce(p.dtchegada, p.dtsaida, p.dtemissao) >= current_date - 730
  ORDER BY p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero,
           coalesce(p.dtchegada, p.dtsaida, p.dtemissao) DESC
) x
GROUP BY 1
ORDER BY 1
"""

# Corredores (origem→destino) que o cliente JÁ roda. Alimenta a lane nova: o
# vendedor cotando uma expansão precisa ver que a rota já existe e a que preço,
# em vez de partir do zero e propor abaixo do que a casa já cobra.
ROTAS_SQL = """
SELECT origem, destino, count(*) AS viagens,
       sum(valorfrete)::float8 AS receita,
       sum(km)::float8 AS km
FROM (
  SELECT DISTINCT ON (p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero)
         coalesce(nullif(trim(p.cidadeorigem), ''), '?') || '/'
           || coalesce(p.uforigem, '?') AS origem,
         coalesce(nullif(trim(p.cidadedestino), ''), '?') || '/'
           || coalesce(p.ufdestino, '?') AS destino,
         coalesce(p.valorfrete, 0) AS valorfrete,
         coalesce(p.kmfretecompra, 0) AS km
  FROM programacaoembarque p
  JOIN coleta co ON co.grupo = p.grupo AND co.empresa = p.empresa
    AND co.filial = p.filialdocumentoorigem
    AND co.unidade = p.unidadedocumentoorigem
    AND co.diferenciadornumero = p.diferenciadornumerodocumentoorigem
    AND co.numero = p.numerodocumentoorigem
  JOIN agrupamentocliente_cnpjcpfcodigo av
    ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
  WHERE av.codigo = %(ag)s
    AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
    AND coalesce(p.dtchegada, p.dtsaida, p.dtemissao) >= current_date - 365
  ORDER BY p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero,
           coalesce(p.dtchegada, p.dtsaida, p.dtemissao) DESC
) x
GROUP BY 1, 2
ORDER BY 4 DESC
LIMIT 20
"""


@cached(ttl=900)
def agrupamentos() -> list[dict]:
    """Os grupos econômicos do ERP, para o seletor de vínculo da conta.

    São ~34 linhas de uma tabela só; o TTL longo é o mesmo de
    `get_clientes_lista`, e pela mesma razão — cadastro de cliente não muda
    durante a tarde.
    """
    return [{"codigo": r["codigo"], "nome": r["nome"]}
            for r in db.query(AGRUPAMENTOS_SQL, None)]


def carteira(codigos: list[int]) -> dict[int, dict]:
    """Receita real por grupo econômico, indexada pelo código.

    Uma consulta para TODAS as contas da lista, e não uma por conta: a lista de
    contas é a tela de abertura do CRM e trinta idas ao AVA para desenhá-la
    seriam trinta chances de a tela demorar — o AVA é remoto e a consulta passa
    por dois JOINs sobre a tabela mais movimentada do ERP.

    Código sem nenhuma viagem na janela simplesmente NÃO VOLTA no dicionário, e
    quem chama trata a ausência como "sem viagem em 2 anos". É de propósito:
    devolver zeros faria a conta parecer medida e valendo zero, quando o que há
    é ausência de movimento. Mesma regra do `n/d` em cinza da Análise de KM.

    A NORMALIZAÇÃO ACONTECE AQUI, ANTES DO CACHE, e é o motivo de haver duas
    funções: `cached` chaveia por `repr(args)`, então `[2,1]` e `[1,2]` seriam
    duas entradas para a mesma resposta — duas varreduras do ERP por causa da
    ordem em que a lista foi montada.
    """
    limpos = sorted({int(c) for c in codigos if c is not None})
    if not limpos:
        return {}
    return _carteira(tuple(limpos))


@cached(ttl=120)
def _carteira(codigos: tuple[int, ...]) -> dict[int, dict]:
    """A consulta em si, cacheada.

    CACHEADA porque a tela pede a carteira DUAS vezes por carga: o painel monta
    o funil e a carteira, e a aba de Contas lista as contas — as duas passando
    por `contas.listar`. Sem o TTL seriam duas varreduras da tabela mais
    movimentada do ERP para desenhar uma tela só. Dois minutos porque a receita
    do dia corrente ainda muda ao longo do dia.
    """
    linhas = db.query(CARTEIRA_SQL, {"ags": list(codigos),
                                     "janela": JANELA_DIAS})
    return {int(r["ag"]): {
        "ultima_viagem": r["ultima_viagem"].isoformat() if r["ultima_viagem"] else None,
        "primeira_viagem": r["primeira_viagem"].isoformat() if r["primeira_viagem"] else None,
        "receita_12m": r["receita_12m"] or 0.0,
        "receita_90d": r["receita_90d"] or 0.0,
        "viagens_12m": int(r["viagens_12m"] or 0),
        "km_12m": r["km_12m"] or 0.0,
    } for r in linhas}


def situacao(vinculo: int | None, dados: dict | None,
             parada_dias: int = PARADA_DIAS) -> dict:
    """A situação da conta, DERIVADA — nunca lida de uma coluna.

    Quatro estados, e cada um pede uma ação diferente de quem olha:

    - `prospect`   — sem vínculo com o ERP. Não é cliente ainda; o trabalho é
                     abrir a primeira oportunidade.
    - `ativo`      — rodou dentro da janela de corte. Trabalho é manter e
                     expandir.
    - `parado`     — tem vínculo e não roda há mais que o corte. É o estado que
                     um `situacao` gravado esconderia, e é o mais acionável dos
                     quatro.
    - `sem_historico` — vinculado e sem NENHUMA viagem em dois anos. Ou é
                     cadastro errado (vínculo apontando para o grupo errado) ou
                     é ex-cliente antigo; nos dois casos a ação é conferir o
                     vínculo, não ligar para vender.
    """
    if not vinculo:
        return {"situacao": "prospect", "dias_sem_viagem": None}
    if not dados or not dados.get("ultima_viagem"):
        return {"situacao": "sem_historico", "dias_sem_viagem": None}
    from datetime import date
    ultima = date.fromisoformat(dados["ultima_viagem"])
    dias = (date.today() - ultima).days
    return {"situacao": "ativo" if dias <= parada_dias else "parado",
            "dias_sem_viagem": dias}


@cached(ttl=300)
def serie_mensal(agrupamento: int) -> list[dict]:
    """Receita e viagens mês a mês, 24 meses, para o gráfico da ficha.

    ATENÇÃO ao ler isto: o `GROUP BY` não devolve o mês que não existe. Mês sem
    viagem nenhuma simplesmente não vem, e emendar dois meses distantes numa
    linha contínua faz parecer queda suave onde houve parada seca — foi assim
    que a jornada emendou abril em agosto sobre quatro meses de buraco. Quem
    desenha PREENCHE o intervalo (`preencher_meses`) antes de plotar.
    """
    return [{"mes": r["mes"], "receita": r["receita"] or 0.0,
             "viagens": int(r["viagens"] or 0), "km": r["km"] or 0.0}
            for r in db.query(SERIE_SQL, {"ag": int(agrupamento)})]


@cached(ttl=300)
def rotas(agrupamento: int) -> list[dict]:
    """Os corredores que o cliente já roda, por receita — top 20."""
    return [{"origem": r["origem"], "destino": r["destino"],
             "viagens": int(r["viagens"] or 0), "receita": r["receita"] or 0.0,
             "km": r["km"] or 0.0,
             "rkm": (r["receita"] / r["km"]) if (r["km"] or 0) > 0 else None}
            for r in db.query(ROTAS_SQL, {"ag": int(agrupamento)})]


def preencher_meses(serie: list[dict], meses: int = 24) -> list[dict]:
    """Completa o intervalo com os meses que a consulta não devolveu.

    O `GROUP BY` só traz mês com linha. Sem isto o gráfico emenda um mês de
    março num de agosto e desenha continuidade sobre cinco meses de nada — e
    quem olha lê "queda" onde houve "parou". O mês ausente entra com receita
    ZERO e a marca `sem_movimento`, porque aqui zero é a verdade: não houve
    viagem, diferente do caso em que a coleta é que falhou.
    """
    from datetime import date
    if meses <= 0:
        return []
    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    chaves: list[str] = []
    for _ in range(meses):
        chaves.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    chaves.reverse()
    por_mes = {s["mes"]: s for s in serie}
    return [por_mes.get(k, {"mes": k, "receita": 0.0, "viagens": 0, "km": 0.0,
                            "sem_movimento": True}) for k in chaves]
