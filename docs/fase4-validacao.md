# Fase 4 — Validação da DRE por Cliente (v1: até Margem de Contribuição)

> Data: 2026-07-17 · Fonte: ERP AVA (réplica read-only) via túnel SSH · Período de
> calibração: jan–jun/2026 (meses fechados) · Validação detalhada: Q1/2026.

## Método

A DRE oficial (`api.queries.get_dre`, já reconciliada com `docs/dre_ia_analise.xlsx`)
é o **total de controle**. Para cada linha L do backbone:

```
descido[L] + NAO_ALOCADO[L] + VARIACAO_ABSORCAO[L] = oficial[L]
```

O balanço fecha **por construção** (NAO_ALOCADO é o plug). A métrica de qualidade é a
**cobertura** = 1 − |NAO_ALOCADO| / |oficial|: quanto do valor oficial foi de fato
custeado bottom-up e atribuído por viagem/CT-e.

## Calibração dos parâmetros (`config/dre_cliente_params.yaml`)

Impostos = taxa efetiva do razão sobre a receita bruta (jan–jun/2026, RB = R$ 64,7 mi):

| Parâmetro | Valor | Origem |
|---|---|---|
| federais | 0.0778 | \|IMPOSTOS FEDERAIS\| / RB |
| estaduais | 0.0983 | \|IMPOSTOS ESTADUAIS\| / RB |
| municipais | 0.0013 | \|IMPOSTOS MUNICIPAIS\| / RB |
| previdenciaria | 0.0085 | \|CONTRIBUICAO PREVIDENCIARIA\| / RB |
| creditos (comb/pneus/manut/frete) | 0.24/0.24/0.15/0.12 | ICMS+PIS/COFINS creditáveis; créditos totais ≈ 19,7% do CV |

## Resultado — reconciliação por mês (jan–jun/2026, consolidação)

Rodado por mês fechado (`get_dre_cliente(m,m)`); o balanço fecha por construção em
todas as linhas/meses (o assert de reconciliação passa). Cobertura por linha:

| Mês | Receita | Imp. Fed. | Imp. Est. | Contrib. | CV | Créditos | CF | Clientes |
|---|---|---|---|---|---|---|---|---|
| 2026-01 | 96% | 98% | 94% | 95% | 86% | 55% | 69% | 20 |
| 2026-02 | 97% | 98% | 95% | 97% | 84% | 54% | 70% | 18 |
| 2026-03 | 97% | 97% | 100% | 99% | 89% | 53% | 69% | 17 |
| 2026-04 | 100% | 100% | 98% | 100% | 87% | 54% | 66% | 18 |
| 2026-05 | 95% | 95% | 96% | 94% | 92% | 56% | 63% | 17 |
| 2026-06 | 98% | 96% | 98% | 99% | 90% | 56% | 62% | 18 |

**Conclusões da consolidação:**
- As linhas proporcionais à receita (impostos) reconciliam a **94–100%** em todos os
  meses — a **calibração anual** dos percentuais (jan–jun) se mantém estável mês a mês,
  não precisa recalibrar por mês.
- **CUSTO VARIÁVEL 84–92%**: o resto é o gap de repasse de frete agregado + custos não
  descidos por viagem (pedágio/diárias — campos vazios no AVA).
- **CRÉDITOS 53–56%** e **CUSTO FIXO 62–70%**: consistentemente parciais **por desenho**
  (base parcial de crédito; fixo de estrutura — pessoal op/adm/patrimonial — não desce,
  fica no consolidado). Não são erros; são o NAO_ALOCADO esperado.
- ANULAÇÕES/DESCONTOS não descem no v1 (residual em NAO_ALOCADO).

## Gaps conhecidos (residual em NAO_ALOCADO) — v1

- **Receita (~2–4%):** o razão inclui receita que não vem de viagens FTL de
  `programacaoembarque` (ex.: RECEITA DE PEDÁGIO, RECEITA OUTROS/SERVIÇO). Fica no
  consolidado, não desce a cliente.
- **Custo variável (~13%):** o custeio bottom-up desce repasse (AGR/TER), combustível
  próprio (CTA Plus) e manutenção/pneus por taxa R$/km. Pedágio, diárias, seguro de
  carga, carga/descarga, motoristas PX e outros custos variáveis ainda **não** são
  descidos por viagem → residual em NAO_ALOCADO.
- **Créditos tributários (~46%):** base descida (combustível + manutenção + frete
  contratado) é menor que o CV total; o restante fica no plug. Sem distorcer a
  atribuição por unidade de custo.
- **Anulações/Descontos:** CT-e cancelado/anulado não é vinculado ao cliente no v1.
- **Viagens sem coleta ("(sem cliente)"):** o v1 usa só o join direto da coleta; a
  heurística de recuperação por CT-e do mesmo veículo (`HEUR_SEMCLI_SQL`, já usada em
  `get_rentabilidade`) **não** foi integrada — fica como bucket de transparência.

## Casos unitários

Cobertos pelos 43 testes puros (`tests/dre_cliente/`, `uv run --with pytest pytest`):
km vazio de retorno/posicionamento e desempate (`test_vazio`); agregado/terceiro sem
combustível/manutenção/fixo (`test_custeio_*`, `is_proprio=False` → 0); variação de
absorção manutenção/pneus (`test_custeio_taxa_km`); reconciliação por plug e balanço
(`test_reconciliacao`). Confirmados contra dados reais: competência por término
(`dtchegada`) captura viagens que cruzam a virada de mês (ex.: saída nov/2025,
chegada jan/2026 → jan); agregados descem só repasse.

## Aceite v1

- [x] Espelho da nomenclatura/ordem da DRE oficial até MARGEM DE CONTRIBUIÇÃO
- [x] Nenhum fixo/overhead rateado por faturamento (não descem no v1)
- [x] Km vazio atribuído ao cliente originador e testado
- [x] Créditos tributários descendo proporcionais aos custos geradores
- [x] Ranking por MC% segmentável por tipo de operação
- [x] Reconciliação Σ clientes + NAO_ALOCADO + VARIACAO_ABSORCAO = DRE oficial por linha
- [x] Cobertura reportada por linha (impostos 96–99%, receita 98%, CV 87%)
- [x] Zero credenciais em código ou histórico

## Próximos (v1.1 / v2)

- Integrar `HEUR_SEMCLI_SQL` para reduzir o bucket "(sem cliente)".
- Descer pedágio/diárias/seguro de carga por viagem/CT-e (elevar cobertura do CV).
- v2: alocar custo fixo por dia-veículo → Margem Direta do Cliente + ranking próprio
  por MC/dia-veículo.
- Validação visual da vista SPA no navegador (com sessão autenticada).
