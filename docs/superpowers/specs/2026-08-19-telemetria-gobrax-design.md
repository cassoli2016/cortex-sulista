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

### 2.2 O que a medição contra a API real mostrou (19/08/2026)

O token autentica como `Authorization: Bearer <token>`. A partir daí, cinco
fatos que o desenho não previa:

**1. O `driversOverview` NÃO serve para calcular a premiação.** Ele devolve
`Reward` = 0 para todos os 87 motoristas, e — mais importante — **não devolve a
média de consumo**. O prêmio é calculado localmente por
`premio = max(0, km/meta − km/media) × preco_litro × pct_premiacao`, e `media`
(km/l por motorista) é o insumo central. A coleta atual guarda `km`, `media`,
`nota` e `indicators` por motorista; a API oficial cobre só `TotalKM` e `Score`.
Migrar como estava planejado zeraria o prêmio de todo mundo, porque `calcular()`
descarta quem tem `media <= 0`.

**2. `startDate` tem de ser diferente de `endDate`.** Pedir um único mês
(`03-2026` a `03-2026`) devolve HTTP 400 "Datas fornecidas inválidas"; é preciso
passar o mês seguinte como fim. O formato é `MM-YYYY` e nenhum outro é aceito.

**3. As APIs são lentas, e há teto de período.** `driversOverview` de dois meses
levou 18,5 s; de doze meses estourou o timeout de 60 s. `vehicle-statistics` da
frota inteira levou **73,4 s**.

**4. `vehicle-statistics` aceita a frota inteira numa chamada** — sem
`vehicleIdentification` devolveu 74 veículos, 73 deles com km/l.

**5. `vehicle-performance` EXIGE placa.** Sem `vehicleIdentification` responde
404 "Veículo não identificado", e cada chamada leva ~17 s. Para a frota, são
~74 chamadas — mais de 20 minutos em série.

**Consequência de arquitetura:** nenhuma das telas novas pode consultar a API ao
vivo no carregamento. Todas precisam de coleta em segundo plano com resultado
gravado localmente, no mesmo modelo que a Premiação já usa (snapshot + botão de
atualizar). Uma tela que demora 73 s para abrir não é uma tela.

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

**A troca direta foi decidida pelo usuário em 19/08/2026 e depois INVIABILIZADA
pela medição (§2.2):** a API não devolve a média de consumo, que é o insumo do
cálculo do prêmio. A migração da fonte fica SUSPENSA aguardando decisão nova.
As três telas novas não dependem disso e seguem.

Caminho possível, se a migração for retomada: `TotalKM` viria do
`driversOverview`, e a média teria de ser reconstruída a partir do
`consumptionAverage` por veículo (vehicle-statistics) rateado pelo vínculo
motorista-veículo (vehicle-performance). Isso introduz rateio onde hoje há
medição direta — é degradação de precisão num número que vira dinheiro no bolso
do motorista, e por isso não é recomendado sem uma razão forte.

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
| ~~Volume de chamadas~~ | MEDIDO em 19/08 | statistics aceita a frota (73 s); performance exige placa (~17 s × 74). Ambas exigem coleta em segundo plano |
| ~~Token não testado~~ | RESOLVIDO | Autentica como `Bearer`; o token exposto no chat em 19/08 precisa ser rotacionado |
| Limite de período | MEDIDO | 12 meses estoura timeout; coletar mês a mês, com `endDate` sempre no mês seguinte |
| Divergência da premiação | CONFIRMADA | A API zera o prêmio e não traz a média; migração suspensa |
| Rastro com muitos pontos | Médio | Amostragem por tempo; a Torre já lida com isso |

## 10. Pendente antes do plano

Nada aqui foi medido contra a API real — o `GOBRAX_TOKEN` ainda não está
disponível. Nas três entregas anteriores desta bancada, a validação prévia
derrubou premissas do design em todas as vezes. **O plano de implementação só
deve ser escrito depois de medir**: formato exato do header, se aceita lote de
placas, limite de período, volume de resposta com a frota real, e a conferência
do `driversOverview` contra os meses já coletados.
