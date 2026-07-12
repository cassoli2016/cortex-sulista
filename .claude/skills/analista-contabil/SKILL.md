---
name: analista-contabil
description: Classifica e ajusta lançamentos contábeis — conta correta do plano de contas, centro de custo correto, grupo de DRE, rateio de overhead, apropriação por competência e detecção de inconsistências. Use para revisar/corrigir fin_lancamentos, preparar a DRE e conciliar. Dado sensível — processamento local. Toda reclassificação é SUGESTÃO que exige aprovação humana + audit_log.
---

# Skill: Analista Contábil

Garante que cada lançamento caia na **conta certa**, no **centro de custo certo** e no **grupo de
DRE certo**, propõe ajustes (reclassificação, rateio, competência, provisão) e aponta erros.

> Princípio: a skill **propõe**, o contador **aprova**. Nenhuma reclassificação é aplicada sem
> confirmação humana; toda alteração vai para `audit_log`. Casos ambíguos → revisão humana.
> Dado financeiro é sensível → processamento 100% local (Gemma).

---

## 1. Plano de contas de referência (transportadora) e grupo de DRE

O `grupo` casa com o schema (`fin_dre.grupo`): `receita | custo_var | custo_motorista | fixo | adm | fin`.

| Conta | Descrição | grupo DRE |
|---|---|---|
| 3.1.1 | Receita de fretes (CT-e) | receita |
| 3.1.9 | Outras receitas operacionais | receita |
| 4.1.1 | Combustível (diesel) | custo_var |
| 4.1.2 | Arla 32 | custo_var |
| 4.1.3 | Pedágio | custo_var |
| 4.1.4 | Manutenção (peças + serviços) | custo_var |
| 4.1.5 | Pneus e recapagem | custo_var |
| 4.1.6 | Frete de terceiros / agregados | custo_var |
| 4.2.1 | Salários de motoristas | custo_motorista |
| 4.2.2 | Encargos sobre motoristas | custo_motorista |
| 4.2.3 | Diárias / pernoite | custo_motorista |
| 4.3.1 | Depreciação de frota | fixo |
| 4.3.2 | Seguros (casco, RCTR-C, RCF-DC) | fixo |
| 4.3.3 | Licenciamento / ANTT / IPVA | fixo |
| 4.3.4 | Telemetria / rastreamento | fixo |
| 5.1.x | Despesas administrativas (pessoal adm, ocupação, TI) | adm |
| 5.2.x | Despesas financeiras (juros, tarifas, IOF) | fin |
| 5.3.x | Receitas financeiras (rendimentos) | fin |
| 1.x / 2.x | Contas patrimoniais (não entram na DRE) | — |

Mantenha o plano real em `config/plano_contas.yaml` (a tabela acima é o seed de referência).

## 2. Centros de custo

| Centro | Quando | Derivação |
|---|---|---|
| `FROTA:<placa>` | custos ligados a um veículo | veículo do lançamento/abastecimento/manutenção |
| `ROTA:<id>` / `VIAGEM:<id>` | custos alocáveis a uma viagem | viagem vinculada |
| `FILIAL:<id>` | custos de estrutura da filial | filial |
| `ADM` | administrativo geral | fixo indireto |
| `COMERCIAL` | despesas comerciais | — |

Custo direto → centro específico. Custo indireto (overhead) → **rateio** (ver §5).

## 3. Classificação (roteamento do lançamento)

Ordem de decisão: origem/tipo canônico → fornecedor → natureza fiscal/CFOP → descrição.

```python
from dataclasses import dataclass

@dataclass
class Sugestao:
    conta: str
    centro_custo: str
    grupo: str
    confianca: float      # 0..1
    motivo: str

# tipo canônico vindo das integrações -> conta
POR_TIPO = {
    "abastecimento": ("4.1.1", "custo_var"),
    "pedagio":       ("4.1.3", "custo_var"),
    "doc_fiscal":    ("3.1.1", "receita"),      # CT-e de receita
    "titulo_financeiro": ("5.2.1", "fin"),      # tarifas/juros bancários
}
# tipo de fornecedor -> conta (sup_fornecedores.tipo)
POR_FORNECEDOR = {
    "posto":    ("4.1.1", "custo_var"),
    "oficina":  ("4.1.4", "custo_var"),
    "agregado": ("4.1.6", "custo_var"),
}

def classificar(lanc: dict, fornecedor: dict | None) -> Sugestao:
    # 1) origem/tipo canônico (mais confiável)
    if lanc.get("tipo_canonico") in POR_TIPO:
        conta, grupo = POR_TIPO[lanc["tipo_canonico"]]
        return Sugestao(conta, _centro(lanc), grupo, 0.9,
                        f"tipo canônico {lanc['tipo_canonico']}")
    # 2) tipo do fornecedor
    if fornecedor and fornecedor.get("tipo") in POR_FORNECEDOR:
        conta, grupo = POR_FORNECEDOR[fornecedor["tipo"]]
        return Sugestao(conta, _centro(lanc), grupo, 0.8,
                        f"fornecedor tipo {fornecedor['tipo']}")
    # 3) heurística por descrição (palavras-chave) — confiança menor
    conta, grupo, kw = _por_descricao(lanc.get("descricao", ""))
    if conta:
        return Sugestao(conta, _centro(lanc), grupo, 0.6, f"descrição: {kw}")
    # 4) não classificado -> conta transitória + revisão humana
    return Sugestao("9.9.9", _centro(lanc), "adm", 0.0, "A CLASSIFICAR - revisar")

def _centro(lanc: dict) -> str:
    if lanc.get("veiculo_placa"): return f"FROTA:{lanc['veiculo_placa']}"
    if lanc.get("viagem_id"):     return f"VIAGEM:{lanc['viagem_id']}"
    if lanc.get("filial_id"):     return f"FILIAL:{lanc['filial_id']}"
    return "ADM"

def _por_descricao(desc: str):
    d = desc.lower()
    mapa = [("diesel","4.1.1","custo_var"), ("arla","4.1.2","custo_var"),
            ("pedagio","4.1.3","custo_var"), ("pneu","4.1.5","custo_var"),
            ("seguro","4.3.2","fixo"), ("ipva","4.3.3","fixo"),
            ("salario","4.2.1","custo_motorista"), ("diaria","4.2.3","custo_motorista"),
            ("juros","5.2.1","fin"), ("tarifa","5.2.2","fin")]
    for kw, conta, grupo in mapa:
        if kw in d:
            return conta, grupo, kw
    return None, None, None
```

## 4. Detecção de inconsistências (o "olho" do contador)

```python
def inconsistencias(lanc: dict, fornecedor: dict | None, hist_stats: dict) -> list[str]:
    probs = []
    if not lanc.get("centro_custo") or lanc["centro_custo"] in ("", "ADM") and lanc.get("veiculo_placa"):
        probs.append("custo de veículo sem centro FROTA:<placa>")
    if lanc.get("conta") in (None, "", "9.9.9"):
        probs.append("conta genérica / a classificar")
    # incompatibilidade fornecedor x conta
    if fornecedor and fornecedor.get("tipo") == "posto" and not str(lanc.get("conta","")).startswith("4.1.1"):
        probs.append("fornecedor posto mas conta não é combustível")
    # regime de competência: data do doc vs competência do lançamento
    if lanc.get("competencia") and lanc.get("data_documento") and \
       lanc["competencia"][:7] != lanc["data_documento"][:7]:
        probs.append("competência difere do mês do documento (verificar apropriação)")
    # outlier de valor vs histórico da conta/centro
    m, dp = hist_stats.get("media",0), hist_stats.get("dp",0) or 1
    if abs(lanc.get("valor",0) - m) > 3*dp:
        probs.append("valor fora do padrão histórico da conta (possível erro)")
    return probs
```

## 5. Ajustes contábeis

**Rateio de overhead** (custo indireto → centros por direcionador):
```python
def ratear(valor_total, base_por_centro: dict, direcionador="km"):
    # base_por_centro: {centro: valor_do_direcionador}  ex.: km rodado por veículo
    total = sum(base_por_centro.values()) or 1
    return {c: round(valor_total * (b/total), 2) for c, b in base_por_centro.items()}
```
Direcionadores usuais: km rodado (por veículo), receita (por filial), nº de viagens.

**Apropriação por competência** (despesa antecipada, ex.: seguro anual pago à vista):
```python
def apropriar_competencia(valor, meses):
    parcela = round(valor / meses, 2)
    return [parcela]*(meses-1) + [round(valor - parcela*(meses-1), 2)]  # ajusta arredondamento
```
Aplicações: seguros, licenciamento anual, IPVA, manutenção contratada.

**Provisões**: 13º, férias+encargos, manutenção preventiva futura — reconhecer por competência,
não só no desembolso.

**Reclassificação / estorno**: gerar lançamento de ajuste (não apagar o original — rastreabilidade),
referenciando o lançamento de origem. Sempre com aprovação humana + audit_log.

## 6. Fluxo recomendado
1. Classificar lançamentos novos (§3) → gravar sugestão com `confianca`.
2. Confiança < 0,7 ou inconsistência (§4) → fila de revisão humana.
3. Contador aprova/corrige → aplica em `fin_lancamentos` + `audit_log`.
4. Fechamento: rateios (§5) + apropriações + provisões → alimenta `fin_dre`.
5. DRE e análise → skill `dre-analise`.

## 7. Fontes e limites
Fontes (PostgreSQL): `fin_lancamentos`, `fin_dre`, `fin_titulos`, `sup_fornecedores`,
`config/plano_contas.yaml`. A skill não emite obrigação fiscal nem substitui o contador
responsável; produz sugestões auditáveis para decisão contábil humana.
