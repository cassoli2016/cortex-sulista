---
type: Index
title: CÓRTEX Knowledge Base
description: Referência central de todo o conhecimento do CÓRTEX — cérebro de gestão da transportadora (frota mista, FTL). Base PostgreSQL única (+ TimescaleDB + pgvector).
timestamp: 2026-07-11
---

# CÓRTEX — Knowledge Base

> Mapa de conhecimento do projeto. Cada link aponta para um conceito documentado
> (`.md` com frontmatter `type:`). Adicione conceitos com `/mega-brain:ingest`
> ou popule automaticamente com `/mega-brain:migrate`.
> Contexto-mestre do projeto: `../CLAUDE.md`. Fonte do schema: `../sql/schema.sql`.

## Tables / Data

### Governança / Acesso
- [filiais](tables/filiais.md) — unidades/filiais; âncora do escopo de RLS
- [usuarios](tables/usuarios.md) — usuários do portal (auth + RBAC)
- [papeis](tables/papeis.md) — papéis de RBAC (ceo, controller, ...)
- [usuario_papel](tables/usuario_papel.md) — junção usuário × papel
- [usuario_filial](tables/usuario_filial.md) — junção usuário × filial (escopo RLS)
- [papel_modulo](tables/papel_modulo.md) — permissões papel × módulo (read/write/approve)
- [audit_log](tables/audit_log.md) — trilha de auditoria de todas as ações

### Cadastros base
- [com_clientes](tables/com_clientes.md) — clientes/embarcadores (score, crédito); RLS
- [rh_motoristas](tables/rh_motoristas.md) — motoristas (CNH, admissão); RLS, PII
- [fro_veiculos](tables/fro_veiculos.md) — ativos da frota; RLS
- [op_rotas](tables/op_rotas.md) — rotas (origem/destino UF, distância, pedágio)
- [sup_fornecedores](tables/sup_fornecedores.md) — fornecedores (posto/oficina/agregado)
- [sup_agregados](tables/sup_agregados.md) — agregados (RKM acordado, rotas)
- [sup_contratos](tables/sup_contratos.md) — contratos de fornecedores

### Operacional / Programação / Frota
- [op_viagens](tables/op_viagens.md) — viagens (FTL); base de RKM/CKM/resultado; RLS
- [op_cargas](tables/op_cargas.md) — cargas por viagem (peso, NF)
- [prog_cargas](tables/prog_cargas.md) — cargas a programar (janelas tstzrange)
- [prog_alocacao](tables/prog_alocacao.md) — alocação carga × veículo × motorista
- [prog_disponibilidade](tables/prog_disponibilidade.md) — (in)disponibilidade de veículos
- [fro_manutencao](tables/fro_manutencao.md) — manutenção preventiva/corretiva
- [fro_pneus](tables/fro_pneus.md) — controle de pneus

### Financeiro
- [fin_titulos](tables/fin_titulos.md) — títulos a receber/pagar; base do caixa; RLS
- [fin_adiantamentos](tables/fin_adiantamentos.md) — adiantamentos a motoristas/fornecedores
- [fin_lancamentos](tables/fin_lancamentos.md) — lançamentos por conta/centro de custo
- [fin_dre](tables/fin_dre.md) — base da DRE por competência/grupo

### Gestão
- [ges_metas](tables/ges_metas.md) — metas/indicadores por área
- [ges_okr](tables/ges_okr.md) — OKRs (objetivo + key result)
- [ges_atas](tables/ges_atas.md) — atas de reunião
- [ges_acoes](tables/ges_acoes.md) — planos de ação 5W2H

### Séries temporais (TimescaleDB)
- [tel_sinais](tables/tel_sinais.md) — hypertable de telemetria CAN/J1939
- [tel_dtc](tables/tel_dtc.md) — hypertable de códigos de falha DTC
- [tc_posicoes](tables/tc_posicoes.md) — hypertable de posições em tempo real
- [tc_ocorrencias](tables/tc_ocorrencias.md) — ocorrências operacionais por viagem
- [ts_eventos](tables/ts_eventos.md) — hypertable de eventos de risco
- [ts_scores](tables/ts_scores.md) — score de risco por motorista/período
- [jor_eventos](tables/jor_eventos.md) — hypertable de eventos de jornada
- [jor_jornadas](tables/jor_jornadas.md) — jornada diária consolidada (Lei 13.103)

### Central de Integrações
- [int_conectores](tables/int_conectores.md) — registro de conectores
- [int_credenciais](tables/int_credenciais.md) — referência ao cofre (nunca o segredo)
- [int_sync_state](tables/int_sync_state.md) — estado de sync por conector/capability
- [int_raw_events](tables/int_raw_events.md) — trilha bruta de eventos (idempotência)
- [int_dead_letter](tables/int_dead_letter.md) — dead-letter queue
- [int_webhook_log](tables/int_webhook_log.md) — log de webhooks (HMAC)

### RAG
- [kb_documentos](tables/kb_documentos.md) — base de conhecimento (pgvector, embedding 768)

### Views analíticas
- [vw_rkm_cliente](views/vw_rkm_cliente.md) — RKM mensal por cliente (materializada)
- [vw_ckm_viagem](views/vw_ckm_viagem.md) — CKM bruto/produtivo e retorno vazio por viagem
- [vw_resultado_viagem](views/vw_resultado_viagem.md) — resultado por viagem
- [vw_fluxo_caixa](views/vw_fluxo_caixa.md) — fluxo de caixa por vencimento
- [vw_dre_mensal](views/vw_dre_mensal.md) — DRE por competência/grupo
- [vw_compliance_jornada](views/vw_compliance_jornada.md) — compliance de jornada
- [vw_viagens_ativas](views/vw_viagens_ativas.md) — viagens ativas + última posição (tempo real)
- [vw_sinistralidade](views/vw_sinistralidade.md) — sinistralidade mensal
- [vw_consumo_veiculo](views/vw_consumo_veiculo.md) — consumo por veículo (continuous aggregate 1h)

## Metrics
- [rkm](metrics/rkm.md) — receita/km = receita_frete / km_carregado
- [ckm_bruto](metrics/ckm_bruto.md) — custo_total / km_total
- [ckm_produtivo](metrics/ckm_produtivo.md) — custo_total / km_carregado
- [retorno_vazio](metrics/retorno_vazio.md) — (km_total − km_carregado) / km_total; alerta > 20%
- [margem_contribuicao_km](metrics/margem_contribuicao_km.md) — RKM − CKM_variavel
- [resultado_viagem](metrics/resultado_viagem.md) — (RKM·km_carreg) − (CKM_var·km_total) − fixo
- [spread_make_vs_buy](metrics/spread_make_vs_buy.md) — CKM_proprio − rkm_pago_agregado

## APIs
- [connector_interface](apis/connector_interface.md) — interface Connector (authenticate/fetch/handle_webhook/normalize/health_check)
- [canonical_event](apis/canonical_event.md) — modelo canônico de evento (CanonicalEvent)
- [webhook_receiver](apis/webhook_receiver.md) — endpoint de webhook (push) validado por HMAC
<!-- auth/JWT + endpoints REST FastAPI: documentar com /mega-brain:ingest quando houver spec. -->

## Services
- [integrations_worker](services/integrations_worker.md) — worker de integrações (scheduler de polling + consumidor do bus)
- [event_bus](services/event_bus.md) — event bus Redis Streams (desacopla ingestão/processamento)
- [normalizer](services/normalizer.md) — mapeia evento canônico → tabelas dos módulos
- [connector_registry](services/connector_registry.md) — auto-descoberta de conectores (@register)
- [gemma_gateway](services/gemma_gateway.md) — gateway de IA (Gemma/Claude, guardrail PII, RAG, cache)
- [langgraph_orquestracao](services/langgraph_orquestracao.md) — orquestração IA (classifica→roteia→consolida)
- [realtime_torres](services/realtime_torres.md) — tempo real das torres (LISTEN/NOTIFY → WebSocket)
- [cloudflare_edge](services/cloudflare_edge.md) — borda zero-trust (Tunnel + Access + WAF)
- [observabilidade](services/observabilidade.md) — Prometheus + Grafana + Loki
- [infra_topologia](services/infra_topologia.md) — topologia docker-compose (TimescaleDB + Ollama + Cloudflared + worker)

## Concepts
- [parametros_negocio](concepts/parametros_negocio.md) — parâmetros de negócio (CKM, jornada, alertas, rate-limit por conector)
- [plano_de_contas](concepts/plano_de_contas.md) — plano de contas de referência (grupo casa com fin_dre.grupo)
- [modelo_seguranca](concepts/modelo_seguranca.md) — modelo zero-trust (RBAC+RLS, guardrail PII, LGPD, HMAC)

## Runbooks
- [setup_dev](runbooks/setup_dev.md) — arranque dev: subir infra + aplicar schema (migrations 0001–0006)
- [go_live](runbooks/go_live.md) — checklist de segurança antes de expor o portal
