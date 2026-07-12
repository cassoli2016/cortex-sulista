---
type: Concept
title: Parâmetros de negócio (config/parametros.yaml)
description: Valores de negócio versionados e auditáveis — CKM benchmarks, jornada, alertas, scoring, telemetria e rate-limit por conector. NADA hardcoded no código.
resource: config/parametros.yaml
tags: [parametros, config, ckm, jornada, alertas, integracoes]
timestamp: 2026-07-11
---

# Definition

Fonte única dos parâmetros de negócio. **Nenhum destes valores deve estar hardcoded no código** — tudo que é regra de negócio vive aqui.

```yaml
operacao:
  modalidade: FTL
  frota: mista          # propria | agregada | mista
  timezone: America/Sao_Paulo

combustivel:
  preco_diesel: 6.00    # R$/litro
  km_por_litro_alvo: 2.4
  pct_arla: 0.05

ckm_benchmark:          # R$/km — faixas de sanidade
  combustivel: [2.30, 2.70]
  motorista:   [0.55, 0.75]
  manutencao:  [0.40, 0.55]
  pneu_cpk:    [0.20, 0.30]
  pedagio:     [0.25, 0.40]
  depreciacao: [0.40, 0.60]
  ckm_cheio:   [5.00, 5.50]

alertas:
  retorno_vazio_max: 0.20
  concentracao_cliente_max: 0.30
  consumo_z_limite: 1.5          # desvios p/ flag de veículo fora da curva

jornada:                          # Lei 13.103/2015
  direcao_continua_max_min: 330   # 5h30
  parada_minima_min: 30
  intervalo_intra_min: 60
  descanso_inter_h: 11
  descanso_semanal_h: 35
  direcao_diaria_max_h: 10        # 8h + 2h extra

scoring_cliente:
  pesos: {margem: 0.35, pagto: 0.30, volume: 0.20, conc: 0.15}

metas:
  ciclo_okr: trimestral
  farol_tolerancia_amarelo: 0.20  # atraso vs tempo decorrido

telemetria:
  retencao_detalhe_dias: 90
  compressao_apos_dias: 7

integracoes:
  event_bus: redis_streams
  retry_max: 5
  retry_backoff_teto_s: 60
  circuit_breaker_falhas: 5
  circuit_breaker_pausa_s: 120
  dead_letter: true
  conectores:                     # rate limit (req/s) e modo por fornecedor
    ruptela:      {rate_rps: 5,  mode: pull}
    sascar:       {rate_rps: 5,  mode: pull}
    cobli:        {rate_rps: 5,  mode: pull}
    ticket_log:   {rate_rps: 3,  mode: both}   # combustível
    sem_parar:    {rate_rps: 3,  mode: push}   # pedágio
    sefaz_cte:    {rate_rps: 2,  mode: pull}   # fiscal
    open_finance: {rate_rps: 2,  mode: pull}   # bancos
    maplink:      {rate_rps: 5,  mode: pull}   # roteirização

ia:
  modelo_local: gemma2:9b
  rotear_pii_para_externo: false   # NUNCA mudar p/ true sem revisão de segurança
```

# Notes

- `alertas.retorno_vazio_max: 0.20` é o limiar da métrica [retorno_vazio](../metrics/retorno_vazio.md) (alerta > 20%).
- `ckm_benchmark` define as faixas de sanidade do [ckm_bruto](../metrics/ckm_bruto.md)/[ckm_produtivo](../metrics/ckm_produtivo.md); `ckm_cheio [5.00, 5.50]` é o CKM com fixo+depreciação usado no make-vs-buy de longo prazo.
- `jornada.*` são os limites da Lei 13.103/2015 aplicados em [jor_jornadas](../tables/jor_jornadas.md) e na view [vw_compliance_jornada](../views/vw_compliance_jornada.md).
- `scoring_cliente.pesos` alimenta a skill `scoring-cliente` (margem 0.35, pagamento 0.30, volume 0.20, concentração 0.15).
- `ia.rotear_pii_para_externo: false` é um controle de segurança — ver [modelo_seguranca](modelo_seguranca.md); NUNCA mudar para `true` sem revisão.
- `integracoes.conectores` lista os 8 fornecedores previstos com rate-limit (req/s) e modo pull/push/both — insumo do [connector_registry](../services/connector_registry.md) e do [integrations_worker](../services/integrations_worker.md).
