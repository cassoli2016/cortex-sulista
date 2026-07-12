# Arquitetura — CÓRTEX (PostgreSQL-only)

## 1. Princípio: um único banco

PostgreSQL é a **única** fonte da verdade. Três capacidades, um motor:
- **PostgreSQL 16** — dados transacionais e operacionais (RLS por módulo).
- **TimescaleDB** (extensão) — séries temporais de alta cadência: telemetria, posições,
  eventos de segurança, eventos de jornada. Hypertables + compressão + políticas de retenção
  + downsampling (continuous aggregates) para os dashboards.
- **pgvector** (extensão) — embeddings da base de conhecimento para RAG.

Nada de BigQuery. Todo o analítico roda em views materializadas e continuous aggregates
do próprio Postgres, atualizados por job agendado.

## 2. Camadas

| Camada | Tecnologia | Responsabilidade |
|---|---|---|
| Borda | Cloudflare Tunnel + Access | Acesso externo sem porta; SSO + MFA; WAF |
| Frontend | Next.js + camada de dashboards | UI modular, RBAC no roteador, render dos painéis |
| API | FastAPI + Pydantic | Regras de negócio, RBAC, audit, orquestração |
| Tempo real | LISTEN/NOTIFY + Redis pub/sub → WebSocket | Torres ao vivo (posição, alertas) |
| Orquestração IA | LangGraph | Classifica → roteia → consolida |
| IA local | Ollama (Gemma) + gateway | Inferência local, RAG, embeddings |
| Dados | PostgreSQL + TimescaleDB + pgvector | Verdade única |
| Cache/fila | Redis | Sessão, cache, fila de jobs |
| Integrações | Worker + Redis Streams | Hub de conectores de fornecedores (ver §8) |
| Observabilidade | Prometheus + Grafana + Loki | Métricas, logs, alertas |

## 3. Telemetria em TimescaleDB

```sql
-- Sinais de telemetria como hypertable
CREATE TABLE tel_sinais (
  ts          timestamptz NOT NULL,
  veiculo_id  int NOT NULL,
  km_l        numeric, rpm int, velocidade numeric,
  eco_ativo   bool, embalo bool, freio_motor bool,
  combustivel_pct numeric, payload jsonb
);
SELECT create_hypertable('tel_sinais', 'ts');

-- Continuous aggregate p/ o dashboard de consumo (downsample horário)
CREATE MATERIALIZED VIEW vw_consumo_veiculo
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS hora, veiculo_id,
       avg(km_l) AS km_l_medio,
       avg((eco_ativo)::int) AS pct_eco
FROM tel_sinais GROUP BY hora, veiculo_id;

-- Retenção: detalhe 90 dias, agregado fica
SELECT add_retention_policy('tel_sinais', INTERVAL '90 days');
SELECT add_compression_policy('tel_sinais', INTERVAL '7 days');
```

Mesma estratégia para `tc_posicoes` (torre de controle), `ts_eventos` (torre de segurança)
e `jor_eventos` (jornada).

## 4. Modelo de dados (núcleo)

```sql
-- Financeiro
fin_titulos       (id, tipo, cliente_id, fornecedor_id, valor, emissao, vencimento, baixa, status, cte_id)
fin_adiantamentos (id, motorista_id|fornecedor_id, valor, data, viagem_id, status)
fin_dre           (id, competencia, conta, grupo, valor, centro_custo)

-- Comercial / Operacional
com_clientes      (id, nome, cnpj, segmento, score, limite_credito, filial_id)
op_viagens        (id, cliente_id, veiculo_id, motorista_id, rota_id, km_carregado, km_total,
                   receita_frete, cte_id, modo[proprio|agregado], status)
op_rotas          (id, origem_uf, destino_uf, distancia_km, pedagio_estimado)

-- Programação
prog_cargas       (id, cliente_id, origem, destino, janela_coleta, janela_entrega, peso, status)
prog_alocacao     (id, carga_id, veiculo_id, motorista_id, status)

-- Torres / Telemetria (hypertables)
tc_posicoes       (ts, viagem_id, veiculo_id, lat, lng, velocidade, status, eta)
tc_ocorrencias    (id, viagem_id, tipo, severidade, abertura, fechamento)
ts_eventos        (ts, motorista_id, veiculo_id, tipo[freada|aceleracao|excesso|fadiga], severidade)
tel_sinais        (ts, veiculo_id, km_l, rpm, eco_ativo, ...)  -- ver §3
tel_dtc           (id, veiculo_id, codigo, descricao, ts, ativo)

-- Frota / Jornada
fro_veiculos      (id, placa, tipo, ano, valor_compra, valor_residual, vida_km, status)
fro_manutencao    (id, veiculo_id, tipo[prev|corr], custo, data, km)
jor_eventos       (ts, motorista_id, tipo[direcao|parada|descanso|refeicao], duracao)
jor_jornadas      (id, motorista_id, data, horas_direcao, horas_descanso, violacoes jsonb)

-- Suprimentos
sup_agregados     (id, fornecedor_id, rkm_acordado, rotas[])
sup_fornecedores  (id, nome, cnpj, tipo, avaliacao)

-- Gestão
ges_metas         (id, area, indicador, meta, periodo, responsavel)
ges_okr           (id, objetivo, key_result, baseline, atual, meta, prazo, dono)
ges_atas          (id, reuniao, data, participantes[], pauta, decisoes)
ges_acoes         (id, ata_id|okr_id, o_que, quem, quando, status, prioridade)  -- 5W2H

-- Governança
usuarios, papeis, papel_modulo, audit_log
```

Views materializadas: `vw_fluxo_caixa`, `vw_dre_mensal`, `vw_ckm_viagem`, `vw_rkm_cliente`,
`vw_resultado_viagem`, `vw_viagens_ativas`, `vw_sinistralidade`, `vw_compliance_jornada`.

## 5. Tempo real (torres)

Ingestão grava no Postgres → trigger emite `NOTIFY` (ou publica no Redis) → backend repassa
por WebSocket para o painel da torre. Sem polling pesado. O histórico fica nas hypertables.

## 6. Gateway de IA

- Roteia Gemma local ↔ Claude API por sensibilidade/complexidade (PII nunca sai).
- Guardrail de PII antes de qualquer saída externa.
- RAG sobre pgvector (políticas, contratos, manuais, atas, decisões) com tags de escopo.
- Cache semântico + rate limit + log de custo por área.

## 7. Implantação local

`docker compose`: postgres(timescaledb), redis, ollama, api, web, gateway, cloudflared,
prometheus, grafana, loki. Backups `pg_dump` criptografados diários, restauração testada.
GPU para Ollama se disponível.

## 8. Central de Integrações

Hub de conectores que traz APIs de fornecedores para o modelo canônico do CÓRTEX.
Arquitetura de plugins: núcleo estável, fornecedor novo = novo conector + register.

```
Fornecedores → Connector (interface padrão) → Event Bus (Redis Streams)
   → int_raw_events (bruto/auditoria) → Normalizer → módulos no PostgreSQL
```

- Worker dedicado `integrations-worker`: scheduler de polling + consumidor do event bus.
- Webhooks entram pela API, validados por HMAC, antes do bus.
- Resiliência: retry/backoff, circuit breaker, rate limit, idempotência, dead-letter.
- Tabelas: int_conectores, int_credenciais (ref. cofre), int_sync_state, int_raw_events,
  int_dead_letter, int_webhook_log.

Especificação completa, interface e exemplos: docs/INTEGRACOES.md e skill connector-builder.
