"""Conversão de competência para caixa com deslocamento DSO/DPO fracionário.

Módulo 100% puro (sem import de armazenamento em provisao_caixa).
Apenas provisao_do_ano toca SQLite local.

Algoritmo:
- DSO (dias de venda em atraso) e DPO (dias de pagamento em atraso) são
  convertidos para meses fracionários: dias / DIAS_MES
- A fração inteira determina o mês de desembarque; a fração decimal distribui
  o valor entre esse mês e o próximo
- Exemplo: 49 dias = 1.6097 meses → 39.03% em M+1, 60.97% em M+2
- Desembarques além de dezembro entram no transbordo (próximo ano)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import armazenamento as arm

DSO_PADRAO = 49.0
DPO_PADRAO = 79.0
DIAS_MES = 30.44


def provisao_caixa(
    entradas: dict[int, float],
    saidas: dict[int, float],
    dso: float,
    dpo: float,
) -> dict:
    """Calcula provisão de caixa com deslocamento DSO/DPO.

    Args:
        entradas: {mes: valor_positivo, ...}
        saidas: {mes: valor_negativo, ...}
        dso: dias de venda em atraso (deslocamento de entradas)
        dpo: dias de pagamento em atraso (deslocamento de saídas)

    Returns:
        {
            "meses": [{"mes": 1..12, "entradas": e, "saidas": s, "geracao": e+s}, ...],
            "transbordo": {"entradas": x, "saidas": y}
        }
        12 meses sempre presentes; valores com 2 casas decimais (arredondamento apenas na exposição).

    Algoritmo de conservação de massa:
    - Cada parcela é decidida separadamente: 1ª parcela (1-f) vai à série se mes_caixa<=12,
      senão ao transbordo; 2ª parcela (f) vai à série se mes_caixa+1<=12, senão ao transbordo.
    - Assim (1-f)+f=1 sempre, nunca duplica nem some.
    - Acumulação em float cheio; round apenas na montagem da resposta.
    """
    # Prazo negativo é inválido (dia de venda/pagamento não existe antes da
    # emissão): cai no fallback padrão em vez de truncar em direção a zero e
    # criar/sumir massa em silêncio (revisão final, I1 — mesma classe do bug
    # crítico da Task 3, mas na entrada em vez de na distribuição).
    if dso < 0:
        dso = DSO_PADRAO
    if dpo < 0:
        dpo = DPO_PADRAO

    # Converter dias para meses fracionários
    dso_meses = dso / DIAS_MES
    dpo_meses = dpo / DIAS_MES

    # Inicializar 12 meses + transbordo (acumulação em float cheio)
    meses_dados: dict[int, dict] = {
        m: {"entradas": 0.0, "saidas": 0.0} for m in range(1, 13)
    }
    transbordo_entradas = 0.0
    transbordo_saidas = 0.0

    # Processar entradas com deslocamento DSO
    for mes_competencia, valor_entrada in entradas.items():
        mes_caixa = mes_competencia + int(dso_meses)
        fracao = dso_meses - int(dso_meses)

        # 1ª parcela (peso 1-f): va à série se mes_caixa <= 12, senão ao transbordo
        parcela1 = valor_entrada * (1 - fracao)
        if mes_caixa <= 12:
            meses_dados[mes_caixa]["entradas"] += parcela1
        else:
            transbordo_entradas += parcela1

        # 2ª parcela (peso f): vai à série se mes_caixa+1 <= 12, senão ao transbordo
        if fracao > 0:
            parcela2 = valor_entrada * fracao
            if mes_caixa + 1 <= 12:
                meses_dados[mes_caixa + 1]["entradas"] += parcela2
            else:
                transbordo_entradas += parcela2

    # Processar saídas com deslocamento DPO
    for mes_competencia, valor_saida in saidas.items():
        mes_caixa = mes_competencia + int(dpo_meses)
        fracao = dpo_meses - int(dpo_meses)

        # 1ª parcela (peso 1-f): vai à série se mes_caixa <= 12, senão ao transbordo
        parcela1 = valor_saida * (1 - fracao)
        if mes_caixa <= 12:
            meses_dados[mes_caixa]["saidas"] += parcela1
        else:
            transbordo_saidas += parcela1

        # 2ª parcela (peso f): vai à série se mes_caixa+1 <= 12, senão ao transbordo
        if fracao > 0:
            parcela2 = valor_saida * fracao
            if mes_caixa + 1 <= 12:
                meses_dados[mes_caixa + 1]["saidas"] += parcela2
            else:
                transbordo_saidas += parcela2

    # Arredondar apenas na montagem da resposta (exposição final)
    meses_lista = [
        {
            "mes": m,
            "entradas": round(meses_dados[m]["entradas"], 2),
            "saidas": round(meses_dados[m]["saidas"], 2),
            "geracao": round(meses_dados[m]["entradas"] + meses_dados[m]["saidas"], 2),
        }
        for m in range(1, 13)
    ]

    return {
        "meses": meses_lista,
        "transbordo": {
            "entradas": round(transbordo_entradas, 2),
            "saidas": round(transbordo_saidas, 2),
        },
    }


def provisao_do_ano(
    ano: int,
    dso: float | None,
    dpo: float | None,
    hoje: date,
    db_path: Path | None = None,
) -> dict | None:
    """Lê versão mais recente do ano no SQLite e monta provisão de caixa.

    Args:
        ano: ano do orçamento
        dso: dias de venda em atraso (None → usa DSO_PADRAO)
        dpo: dias de pagamento em atraso (None → usa DPO_PADRAO)
        hoje: data de referência para filtrar meses >= hoje.month
        db_path: caminho do DB (default: arm.DB_PATH)

    Returns:
        {
            "versao": {"id": ..., "rotulo": ..., "metodo": ..., "meses_base": ...},
            "dso": valor_usado,
            "dpo": valor_usado,
            "dso_fonte": "medido" | "padrao",
            "meses": [só meses >= hoje.month],
            "transbordo": {...}
        }
        ou None se nenhuma versão encontrada para o ano.
    """
    if db_path is None:
        db_path = arm.DB_PATH
    # Migra o schema (coluna `metodo`/`meses_base`) ANTES de ler a versão.
    # Sem isso, um orcamento.db criado antes desta branch não tem a coluna
    # `metodo`: `versao["metodo"]` levanta KeyError, engolido pelo
    # `except Exception` do fluxo — a série tracejada some em silêncio até
    # alguém abrir a tela de Orçamento (só ali `gerar()` roda init_db).
    # M1 da revisão final.
    arm.init_db(db_path)

    # Buscar versão mais recente do ano
    versoes = arm.listar_versoes(db_path, ano=ano)
    if not versoes:
        return None

    versao = versoes[0]  # Mais recente primeiro
    versao_id = versao["id"]

    # Determinar DSO/DPO usados e fonte. Prazo negativo é inválido (I1): trata
    # como se não tivesse sido informado, cai no mesmo fallback padrão.
    dso_valido = dso is not None and dso >= 0
    dpo_valido = dpo is not None and dpo >= 0
    dso_usado = dso if dso_valido else DSO_PADRAO
    dpo_usado = dpo if dpo_valido else DPO_PADRAO
    # Se qualquer um caiu no fallback, marca tudo como padrao
    fonte_final = "padrao" if not (dso_valido and dpo_valido) else "medido"

    # Ler linhas e agrupar por mês
    linhas = arm.ler_linhas(db_path, versao_id)
    entradas: dict[int, float] = {}
    saidas: dict[int, float] = {}

    for linha in linhas:
        valor_efetivo = linha["valor_efetivo"]
        mes = linha["mes"]

        if valor_efetivo > 0:
            entradas[mes] = entradas.get(mes, 0.0) + valor_efetivo
        elif valor_efetivo < 0:
            saidas[mes] = saidas.get(mes, 0.0) + valor_efetivo

    # Chamar provisao_caixa
    provisao = provisao_caixa(entradas, saidas, dso_usado, dpo_usado)

    # Filtrar meses >= hoje.month
    meses_filtrados = [m for m in provisao["meses"] if m["mes"] >= hoje.month]

    return {
        "versao": {
            "id": versao_id,
            "rotulo": versao["rotulo"],
            "metodo": versao["metodo"],
            # meses_base (JSON de 'YYYY-MM's) para a tela derivar a faixa da
            # base SEMPRE do dado gravado, nunca do texto do rótulo — que fica
            # estale depois de regerar (M4 da revisão final).
            "meses_base": versao.get("meses_base"),
        },
        "dso": dso_usado,
        "dpo": dpo_usado,
        "dso_fonte": fonte_final,
        "meses": meses_filtrados,
        "transbordo": provisao["transbordo"],
    }
