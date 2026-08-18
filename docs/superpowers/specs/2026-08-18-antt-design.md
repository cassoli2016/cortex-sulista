# Integração ANTT — design

Data: 18/08/2026
Status: aguardando revisão

## 1. Objetivo

Trazer para o CÓRTEX as informações da ANTT que mudam decisão na Sulista, num
grupo próprio de menu, com ganchos nas telas onde a decisão acontece.

Quatro frentes, quatro telas, quatro fases independentes. Cada fase entrega
sozinha, versiona e vai para produção antes da seguinte começar.

## 2. O que a ANTT publica de verdade (verificado em 18/08/2026)

Levantamento feito contra as fontes reais, não contra suposição:

| Frente | Fonte | Veredito |
|---|---|---|
| Piso mínimo | Res. 6.076/2026 + 6.084/2026 (Anexo II) | Fórmula pública. Sem API oficial. Calculamos localmente. |
| RNTRC | `dados.antt.gov.br` dataset `rntrc`, CSV mensal, 158 MB | CNPJ completo para PJ. CPF mascarado para TAC. |
| Autuações | `sifama-autos-de-infracao-cargas` | AGREGADO. Não serve. Ver §6. |
| Mercado | `rntrc-veiculos`, `praca-de-pedagio`, `vale-pedagio-obrigatorio` | Agregado. Serve só de contexto. |

### 2.1 Achados que restringem o desenho

**O CSV do RNTRC tem CNPJ, não tem CPF utilizável.** Amostra de julho/2026
(754.185 registros): 585.758 ATIVO, 168.427 PENDENTE; 536.465 TAC, 217.192 ETC,
528 CTC. Campos: `nome_transportador, numero_rntrc, data_primeiro_cadastro,
situacao_rntrc, cpfcnpjtransportador, categoria_transportador, cep, municipio,
uf, equiparado, data_situacao_rntrc`. O documento do TAC vem no formato
`NNN.***.***-NN`. Consequência: **PJ casa por CNPJ com exatidão; TAC só casa por
nome + UF, o que é heurística**. TAC é 71% da base.

**Autuação por empresa não é dado aberto.** O CSV do SIFAMA tem
`escopo_autuacao;mes;uf;amparo_legal;codigo_infracao;descricao_infracao;quantidade_autos`
— sem CNPJ, sem placa, sem valor. O dado por empresa existe apenas na Área do
Autuado, atrás de login com procuração. **Não integramos**: guardar credencial de
terceiro no painel viola a Cláusula 5.1 da política de segurança.

**A tabela de coeficientes muda duas vezes por ano.** Res. 6.076 (jan/26) e 6.084
(jul/26, +3,54% IPCA no CC). Um acerto de março tem que ser conferido contra a
tabela vigente na data da viagem — senão todo período fechado se reescreve a cada
reajuste.

## 3. Arquitetura

Segue o padrão dos módulos novos: **AVA continua read-only; dado nosso em SQLite
local**, como Orçamento, Previsão e Extrato.

```
api/antt/
  armazenamento.py   data/antt.db (WAL, conexão curta) — base RNTRC + autos
  coeficientes.py    config/antt_coeficientes.yaml, resolvido por vigência
  eixos.py           config/antt_eixos.yaml — tipo+carroceria+bitrem → eixos
  piso.py            função pura: piso = (km × CCD) + CC
  rntrc.py           ingestão do CSV mensal em streaming
  autos.py           CRUD dos autos + relógio de prazos
  sql.py             AVA: viagens de agregado (reusa a base de Agregados)
  servico.py         orquestra
```

Endpoints em `api/main.py`: `/api/antt/piso`, `/api/antt/rntrc`, `/api/antt/autos`,
`/api/antt/mercado`, `POST /api/antt/sync`.

Menu: grupo **ANTT** entre "Recursos Humanos" e "Painéis TV". Views `anpiso`,
`anrntrc`, `anauto`, `anmerc`. Todas entram também na gaveta mobile.

Ganchos (o lado "híbrido" da decisão): badge de RNTRC e coluna "vs piso" em
**Operação › Agregados e Terceiros**; piso legal na linha de compra do
**Make vs Buy**; aba ANTT em **Frota › Multas**.

## 4. Fase 1 — Piso Mínimo de Frete (compra)

Confere o que a Sulista **paga** ao agregado/terceiro. É onde existe exposição
legal direta: a autuada seria a Sulista por pagar abaixo do piso.

### 4.1 Fonte

`programacaoembarque` — a mesma base canônica já validada em Agregados
(`_agr_base()` em `api/queries.py`), com `semaforo = 1`, não cancelada,
`veiculo.utilizacaoveiculo IN ('AGR','TER')`. Ela já traz tudo:

- `kmfretecompra` → distância (cobertura ~100%)
- `valorfretecompra` → o valor pago, que é o que se compara ao piso
- `veiculo` (placa) → tipo, carroceria, bitrem, tipo de carga
- `tipo = 3` → deslocamento vazio
- `cnpjcpfcodigoveiculo` → transportador (liga com a Fase 2)

O piso é **uma coluna nova sobre uma base já validada**, não uma query nova.
`acertoviagemagregado` é o fechamento financeiro e entra só como contexto.

### 4.2 Cálculo

```
eixos   = mapa(descricao_tipo, descricao_carroceria, bitrem)      # YAML
carga   = mapa(descricao_tipocargaveiculo) → 12 classes ANTT      # YAML
tabela  = A (composição veicular) | B (só unidade de tração)
CCD, CC = coeficientes vigentes na data da viagem (dtemissao)
piso    = (kmfretecompra × CCD) + CC
gap     = valorfretecompra − piso
```

Deslocamento vazio (`tipo = 3`): piso = `0,92 × CCD × km`, e **só quando o
pagamento é obrigatório** — contêiner e frota dedicada/fidelizada por razão
sanitária ou certificação. Fora disso a viagem é marcada `isento`, não `abaixo`.

As tabelas cobrem 12 tipos de carga e eixos 2, 3, 4, 5, 6, 7 e 9; nem toda
combinação existe (célula vazia = não usada no mercado). Tabelas C e D valem para
alto desempenho e ficam disponíveis no YAML, sem uso automático na v1.

### 4.3 Estados — a regra de nunca inventar número

| Estado | Quando | Exibição |
|---|---|---|
| `calculado` | eixos e carga resolvidos | piso e gap |
| `sem_eixos` | mapa não resolve o veículo | `—`, entra na cobertura |
| `sem_carga` | tipo de carga não mapeado | `—`, entra na cobertura |
| `sem_km` | `kmfretecompra = 0` | `—`, entra na cobertura |
| `isento` | vazio sem obrigação de pagamento | `—`, fora do denominador |

O KPI de aderência sempre declara a cobertura: "conferido em X de Y viagens".
Mesmo tratamento que as multas sem condutor receberam.

### 4.4 Tela

- **KPIs**: viagens conferidas (com cobertura), valor pago no período, viagens
  abaixo do piso, exposição em R$ (soma dos gaps negativos), % de aderência.
- **Tabela**: transportador expansível (padrão `forn-row`/`forn-det`) → viagens
  com placa, rota, km, eixos, carga, pago, piso, gap e badge.
- **Gráficos**: aderência mensal (12 meses) e top transportadores por exposição.
- **Filtros**: período, filial, modalidade (AGR/TER), transportador, e um toggle
  "só abaixo do piso".

### 4.5 Configuração

`config/antt_coeficientes.yaml` — por vigência:

```yaml
vigencias:
  - resolucao: "6.076/2026"
    inicio: 2026-01-20
    fim: 2026-07-19
    tabelas:
      A:
        carga_geral:   {2: {ccd: 3.1234, cc: 234.56}, 3: {ccd: ..., cc: ...}}
        granel_solido: {...}
  - resolucao: "6.084/2026"
    inicio: 2026-07-20
    fim: null
```

`config/antt_eixos.yaml` — mapa revisável pelo usuário, com um `default` explícito
e a lista dos veículos não resolvidos exposta na própria tela, para virar fila de
cadastro em vez de erro silencioso.

## 5. Fase 2 — RNTRC

### 5.1 Ingestão

Baixa o CSV da competência corrente em **streaming** (sem gravar os 158 MB em
disco), decodifica latin-1, e grava em `data/antt.db`:

- **PJ (ETC/CTC)**: CNPJ só com dígitos, nome, RNTRC, situação, categoria, UF,
  município, data da situação, equiparado.
- **TAC**: nome normalizado, UF, RNTRC, situação. **O CPF não é gravado nem
  exibido, nem mascarado** — política de PII.

Tabelas: `rntrc_transportador` (índice por CNPJ e por nome normalizado) e
`rntrc_sync` (competência, linhas lidas, linhas gravadas, resultado).

Disparo: botão "Atualizar base" na tela, padrão da Premiação. A verificação
automática roda na subida da API e a cada 24 h, comparando a competência gravada
em `rntrc_sync` com a mais recente publicada no CKAN — sem cron externo e sem
depender do Task Scheduler do servidor. Fonte aberta CC-BY, sem credencial.

Enquanto nunca houve sincronização, a tela mostra estado vazio com o botão, não
zeros: base ausente não é o mesmo que nenhum irregular.

Regra herdada da Premiação, que já custou um mês de dados: **sincronização vazia
ou com erro nunca sobrescreve a base boa**.

### 5.2 Casamento

- PJ: CNPJ normalizado, exato.
- TAC: nome normalizado + UF. Resultado ambíguo (mais de um candidato) é marcado
  como `ambiguo`, nunca resolvido no chute.
- Ausente da base: `nao_encontrado` — que não é o mesmo que irregular, e a tela
  precisa dizer isso.

### 5.3 Tela

- **KPIs**: terceiros contratados no período, com RNTRC ativo, pendentes, não
  encontrados, e **valor pago a transportador irregular** no período.
- **Tabela**: transportador, CNPJ, RNTRC, categoria, situação, data da situação,
  viagens e R$ no período, badge.
- **Aba "Base RNTRC"**: consulta livre por CNPJ ou nome, com a competência da
  base carregada e o botão de atualizar.
- **Gancho**: badge na tela Agregados e Terceiros.

## 6. Fase 3 — Autos de infração ANTT (registro próprio)

Como o dado por empresa não existe em fonte aberta, o CÓRTEX passa a ser o lugar
onde a Sulista **registra** os autos que chegam por carta ou pelo Portal, com
controle de prazo. O problema real que isso resolve: perder o prazo de defesa
custa o valor cheio da multa.

Tabela `antt_auto` (SQLite): número do auto, sistema (SIFAMA/RADAR), data da
infração, data da ciência, placa, condutor, código e descrição da infração,
valor, status (`aberto | defesa | recurso_1 | recurso_2 | pago | cancelado`),
prazo, responsável, observação.

Relógio de prazos: defesa prévia em 30 dias da ciência, com semáforo (vencido,
≤ 7 dias, em dia). O status é do usuário; o prazo é calculado.

- **KPIs**: autos abertos, R$ em risco, prazos vencendo em 7 dias, autos perdidos
  por decurso de prazo.
- **Tela**: tabela filtrável por status e formulário de cadastro/edição.
- **Gancho**: aba "ANTT" em Frota › Multas.

Extensão possível, fora da v1: alerta no resumo diário via `api/push.py`.

## 7. Fase 4 — Mercado e Pedágio

A mais fraca das quatro, e vale dizer com todas as letras: como todos os datasets
são agregados, ela é contexto de mercado, não operação.

Datasets: `rntrc-veiculos` (perfil da frota nacional por categoria/UF/ano),
`praca-de-pedagio` e `volume-trafego-praca-pedagio`, `vale-pedagio-obrigatorio`.

Tela informativa: composição do mercado (ETC/CTC/TAC), perfil de frota, e praças
de pedágio nas UFs onde a Sulista roda. Entregar por último.

## 8. Transversais

- **RBAC**: as quatro telas entram em `papel_modulo`. Atenção ao gotcha conhecido
  do seed, que concede tela a perfil sem usuário.
- **Versionamento**: cada fase bumpa SemVer, atualiza `docs/versoes.yaml` (que
  gera o CHANGELOG), a versão na UI e o CLAUDE.md.
- **Mobile**: cada tela entra na gaveta, sem precisar pedir.
- **Testes**: `piso.py` é função pura e nasce por TDD. Casos obrigatórios: cada
  tabela, vazio a 92%, isenção do vazio não obrigatório, veículo sem eixos, e
  viagem antiga conferida contra a resolução vigente à época.
- **Segurança**: nenhuma credencial nova; nenhum CPF gravado ou exibido.

## 9. Riscos

| Risco | Impacto | Tratamento |
|---|---|---|
| Eixos não existem no AVA | Alto — sem eixo não há piso | Mapa YAML revisável; não resolvido vira fila visível, não erro mudo |
| Tipo de carga não mapeia nas 12 classes | Alto | Mesmo tratamento; default explícito por carroceria |
| TAC casa por nome | Médio | Marcar `ambiguo`; nunca afirmar irregularidade de TAC sem conferência humana |
| CSV de 158 MB por mês | Médio | Streaming, sem arquivo em disco; sync vazia não sobrescreve |
| Layout do CSV mudar | Médio | Validar cabeçalho antes de gravar; abortar com mensagem |
| Reajuste semestral | Alto se ignorado | Vigência por data no YAML; cálculo sempre histórico |

## 10. Ordem de entrega

1. Piso Mínimo (compra) — maior valor financeiro e legal
2. RNTRC — compliance dos contratados
3. Autos ANTT — controle de prazo
4. Mercado e Pedágio — contexto
