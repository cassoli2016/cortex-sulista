---
name: dashboard-builder
description: Padrão e especificação para criar QUALQUER painel ou dashboard do CÓRTEX (torre de controle, torre de segurança, telemetria, programação, jornada, financeiro/DRE, metas/OKR). Use SEMPRE antes de construir uma tela de painel — define anatomia, componentes, design system e o spec de cada perfil.
---

# Skill: Construção de Dashboards e Painéis

Toda tela de painel do CÓRTEX segue este padrão. Consistência é regra — o CEO aprende a
ler um painel e lê todos.

## 1. Anatomia (top-down, leitura em camadas)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. LINHA DE STATUS  · 3-6 KPIs · valor · meta · ▲/▼ · semáforo │
├─────────────────────────────────────────────────────────────┤
│ 2. SÉRIE PRINCIPAL  · tendência do número-rei vs meta/período  │
├──────────────────────────────┬──────────────────────────────┤
│ 3. DECOMPOSIÇÃO              │ 4. TABELA ACIONÁVEL            │
│    quebra por dimensão       │    linhas por prioridade/risco │
│    (rota/cliente/veículo)    │    + ação sugerida             │
├──────────────────────────────┴──────────────────────────────┤
│ 5. ALERTAS · o que exige ação AGORA                           │
└─────────────────────────────────────────────────────────────┘
```

Regras universais:
- Todo número-chave traz **comparação** (vs meta E vs período anterior).
- Todo painel mostra **fonte do dado + timestamp** ("dados de PostgreSQL · atualizado há 2 min").
- Gráfico com rótulo direto; sem legenda quando der pra rotular na linha.
- Semáforo objetivo: verde = na meta, amarelo = atenção, vermelho = ação.

## 2. Design system (tokens)
```
amarelo #FFD31C (marca/destaque) · ink #1E1E1E (texto) · cinza #6B7280 (secundário)
verde #16A34A (ok) · vermelho #DC2626 (alerta) · âmbar #F59E0B (atenção) · fonte Inter
```

## 3. Tempo real vs analítico
- **Tempo real** (torres): WebSocket alimentado por LISTEN/NOTIFY do Postgres. Atualiza sozinho.
- **Analítico** (financeiro, metas): consulta view materializada / continuous aggregate, com
  seletor de período. Nunca varrer hypertable bruta no front.

## 4. Especificação por perfil

### Torre de Controle (tempo real, operacional)
- KPIs: viagens ativas · % no prazo · atraso médio · ocorrências abertas · veículos em risco.
- Mapa ao vivo com posição/status (verde rodando, âmbar atraso, vermelho ocorrência).
- Tabela de viagens ativas ordenada por risco (atraso vs janela), com ETA e ação.
- Fontes: tc_posicoes, tc_ocorrencias, vw_viagens_ativas.

### Torre de Segurança (tempo real, risco)
- KPIs: score médio da frota · eventos críticos hoje · sinistralidade (acid./Mkm) · motoristas em risco.
- Heatmap de risco (motorista × tipo de evento) e ranking pior→melhor.
- Feed de eventos críticos ao vivo; tabela de motoristas por score com plano de ação.
- Fontes: ts_eventos, ts_scores, vw_sinistralidade.

### Telemetria avançada (analítico + insight)
- KPIs: km/l da frota vs alvo · % ECO · % embalo · DTCs ativos.
- Série de consumo por período; ranking de eficiência por veículo/motorista.
- **Insight em linguagem natural** gerado pelo agente telemetria ("Veículo ABC1234 está 12%
  abaixo do alvo de km/l — correlação com baixo uso de freio-motor em descidas na BR-376").
- Fontes: vw_consumo_veiculo, tel_dtc.

### Programação de cargas
- KPIs: cargas programadas · sem veículo · veículos ociosos · retorno vazio previsto.
- Quadro kanban/gantt: cargas × veículos × janelas; conflitos em vermelho.
- Fontes: prog_cargas, prog_alocacao, prog_disponibilidade.

### Jornada
- KPIs: motoristas em compliance · em atenção · em violação · próximas violações previstas.
- Semáforo por motorista (horas dirigidas vs limite); linha do tempo do dia.
- Fontes: vw_compliance_jornada, jor_jornadas.

### Financeiro / DRE
- KPIs: saldo projetado · primeiro gap de caixa · EBITDA · margem · inadimplência.
- Caixa projetado (linha com banda de cenário) · DRE em cascata (waterfall) · aging de recebíveis.
- Fontes: vw_fluxo_caixa, vw_dre_mensal, fin_titulos.

### Metas / KPIs / OKRs
- Cada OKR: objetivo + key results (atual vs meta) + % progresso + prazo + dono + farol.
- Visão de portfólio (todos os OKRs) e drill por área.
- Fontes: ges_okr, ges_metas.

## 5. Stack de implementação
Front em Next.js + Recharts (ou similar) com os tokens acima. Cada painel é um componente que
recebe dados de um endpoint FastAPI (analítico) ou de um canal WebSocket (tempo real).
Nunca embutir regra de negócio no front — vem da API/skills.
