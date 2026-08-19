# Telemetria Gobrax — design

Data: 19/08/2026
Status: aguardando revisão

## 1. Objetivo

Trazer para o CÓRTEX os dados da plataforma Gobrax por API oficial, num grupo de
menu chamado **Telemetria**, e mover a Premiação para dentro dele — trocando a
coleta atual, feita por login, pela API pública.

## 2. As APIs (documentação lida em 19/08/2026)

| API | Endpoint | Dados |
|---|---|---|
| OVERVIEW | `GET /api/v2/driversOverview` | por motorista/mês: `Reward`, `TotalKM`, `Score` |
| STATISTIC | `GET /api/v1/vehicle-statistics` | `averageSpeed`, `consumptionAverage` (km/l), `odometer`, `totalConsumption`, `totalMileage`, `totalBreaking`, `totalBreakingOnHighSpeed` |
| PERFORMANCE | `GET /api/v1/vehicle-performance` | `cruiseControl`, `ecoRoll`, `economicRange` (duration, percentage, score) + `drivers[]` vinculados |
| ODOMETER | `GET /api/v2/vehicle-odometer` | `odometer`, `lastUpdated` |
| POSITIONS (trilha) | `GET /api/v2/positions[/{placa}]` | histórico de `date, lat, lon, speed` |

Host: `https://gateway-v3.gobrax.com.br:8889` (a de última posição fica em
`http://gateway-v3.gobrax.com.br:8888`). Autenticação por API Key no header
`Authorization`.

**Fora do escopo, por decisão de 19/08/2026:** `DRIVERS` (POST/DELETE de
motorista) e `vehicle-event` (POST de vínculo). São APIs de ESCRITA, e o CÓRTEX
é um sistema de leitura — passar a escrever em plataforma externa é mudança de
natureza, não de escopo.

### 2.1 O que muda em relação ao acesso atual

O `api/premiacao/gobrax.py` de hoje fala com `gateway-v3-waf.gobrax.com.br`,
autenticando por login no Kratos com e-mail e senha. Esse caminho já custou um
mês de dados (a coleta oscilou e zerou julho) e bate em 403 por rate limit ao
repetir logins. As APIs públicas são outro host, outra porta e outra
autenticação — o token novo não serve para o código atual, e o fluxo Kratos
desaparece com a migração.

## 3. Estrutura

Grupo **Telemetria** no menu, com quatro telas:

| Tela | View | Fonte |
|---|---|---|
| Premiação | `prem` (movida de Frota) | driversOverview |
| Consumo e Estatísticas | `telcon` | vehicle-statistics |
| Condução Econômica | `telcond` | vehicle-performance |
| Hodômetro e Rastro | `telhod` | vehicle-odometer + positions |

```
api/gobrax/
  cliente.py        API Key no header, urllib puro (o venv não tem requests),
                    normalização dos três formatos de data, retry e rate limit
  estatisticas.py   vehicle-statistics
  performance.py    vehicle-performance
  odometro.py       vehicle-odometer + positions
  overview.py       driversOverview
api/premiacao/      continua; passa a consumir api/gobrax/overview
```

Hoje `api/premiacao/gobrax.py` mistura autenticação, HTTP e regra de premiação.
Como quatro telas vão falar com a mesma plataforma, o cliente vira um só.

**Três formatos de data numa fonte só** — `2021-02-10 00:00:00`,
`2023-08-10T00:00:00-0300` e `05-2024`. A conversão fica no cliente, num ponto
único; nenhuma tela ou serviço monta string de data à mão.

## 4. Premiação migrada

`driversOverview` sem `documentNumbers` devolve todos os motoristas de uma vez —
uma chamada por período, contra as ~86 de hoje. Cálculo, snapshots, backfill e
tela permanecem; troca só a coleta.

**Decisão do usuário (19/08/2026): troca direta, sem fonte dupla.** O risco foi
apresentado e assumido: se a API devolver número diferente do que a plataforma
web mostra, isso aparece no valor pago ao motorista. Mitigação que não altera a
arquitetura: na implementação, comparar uma vez os meses já coletados
(março/2026 = 11 motoristas, R$ 8.548) contra o que a API devolve, como teste de
aceitação. Divergência para o usuário decidir ANTES de subir.

**PII:** a resposta traz `DocumentNumber` (CPF). Serve para casar com o cadastro
e é descartado em seguida — não entra em SQLite nem em payload de API, como já
fazem Jornada, Combustível e a própria Premiação.

Regra herdada e mantida: **coleta vazia nunca sobrescreve snapshot com dados.**

## 5. Consumo e Estatísticas (`telcon`)

KPIs: km/l da frota pela telemetria, km rodado, litros, frenagens por mil km, e
frenagens em alta velocidade.

O que justifica a tela é o **cruzamento com a tela de Combustível**, que calcula
km/l pelos abastecimentos lançados no AVA. São duas medições independentes do
mesmo consumo: onde divergirem há desvio, bomba descalibrada ou abastecimento
não lançado. A tabela por veículo mostra as duas e o delta.

A comparação só vale onde as duas fontes cobrem o mesmo período e o mesmo
veículo; veículo sem telemetria ou sem abastecimento no período mostra `—` e
entra na cobertura declarada, nunca num delta inventado.

## 6. Condução Econômica (`telcond`)

Indicadores de `vehicle-performance` por veículo, com os motoristas vinculados
no período. Ranking por motorista, com percentual e score de cada indicador.

É o detalhe por trás da nota da Premiação: hoje o motorista vê que pontuou pouco
e não sabe em quê. A tela liga o score ao comportamento que o gerou.

## 7. Hodômetro e Rastro (`telhod`)

Odômetro por veículo com a data da última leitura, e a trilha no mapa (Leaflet,
o mesmo da Torre de Controle).

Dois ganchos com telas existentes:
- **Manutenção Preventiva** hoje depende do km lançado no AVA; o odômetro da
  telemetria é medição direta.
- **Comunicação Rastreadora** trata de veículo que parou de comunicar;
  `lastUpdated` velho é exatamente esse sintoma, visto por outro ângulo.

## 8. Transversais

- **RBAC**: as telas entram em `papel_modulo`. A Premiação hoje é do perfil
  Frota; as três novas seguem o mesmo perfil, mais Diretoria — que é o único
  com usuário real, lição da v19/`extb`.
- **Versionamento**: cada entrega bumpa SemVer, atualiza `docs/versoes.yaml`,
  o CHANGELOG, a versão na UI e o CLAUDE.md.
- **Mobile**: cada tela entra na gaveta.
- **Segurança**: `GOBRAX_TOKEN` só em variável de ambiente, nunca em log, em
  payload ou em mensagem de erro. Nenhum CPF gravado ou exibido.
- **Testes**: o cliente é testado com respostas simuladas; os serviços de
  cálculo são puros e nascem por TDD; cada tela ganha teste de browser contra o
  `index.html` real.

## 9. Riscos

| Risco | Impacto | Tratamento |
|---|---|---|
| Volume de chamadas por veículo | Alto — decide se a coleta é ao vivo ou em cache | MEDIR antes de planejar: descobrir se `vehicleIdentification` aceita lista |
| Token não testado | Bloqueia tudo | Validar assim que entrar no `.env`, com o nome corrigido |
| Limite de período das APIs | Médio | Medir; pode obrigar a paginar por mês |
| Divergência da premiação | Alto — afeta valor pago | Comparação com os meses já coletados como teste de aceitação |
| Rastro com muitos pontos | Médio | Amostragem por tempo; a Torre já lida com isso |

## 10. Pendente antes do plano

Nada aqui foi medido contra a API real — o `GOBRAX_TOKEN` ainda não está
disponível. Nas três entregas anteriores desta bancada, a validação prévia
derrubou premissas do design em todas as vezes. **O plano de implementação só
deve ser escrito depois de medir**: formato exato do header, se aceita lote de
placas, limite de período, volume de resposta com a frota real, e a conferência
do `driversOverview` contra os meses já coletados.
