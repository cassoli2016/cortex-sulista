# Migração dos bancos locais para PostgreSQL

> Estado: **em andamento** — Fase 0 concluída, piloto `antt` no ar
> (222 transportadores lidos do PostgreSQL em 27/08/2026).
> Próximo: Fase 2, começando por `push` ou `correio`.

O CÓRTEX nasceu com dez bancos SQLite em `data/`. Este documento é o plano de
levá-los para um PostgreSQL local, **um por vez**, sem parar de entregar. Ele é
o registro de por que cada escolha foi feita — quem pegar a próxima fase lê
daqui, não da memória de ninguém.

---

## 1. O que existe hoje

Dez bancos SQLite, cerca de **25 mil linhas e 2,6 MB no total**. Volume não é o
assunto — o assunto é ter um lugar só, com backup de verdade.

| Banco | Linhas | `execute` no módulo dono | Natureza |
|---|---:|---:|---|
| `orcamento.db` | 21.696 | 27 | estado |
| `extrato.db` | 715 | 28 | estado |
| `previsao.db` | 598 | 10 | estado |
| `auth.db` | 536 | 167 | estado (crítico) |
| `telemetria.db` | 447 | 8 | **cache** |
| `antecipacoes.db` | 232 | 28 | estado |
| `antt.db` | 223 | 8 | estado |
| `contrapartida.db` | 178 | 11 | estado (fiscal) |
| `email.db` | 6 | 5 | estado |
| `push.db` | 1 | 10 | estado |

Três fatos que tornam a migração barata no código:

1. **Cada banco tem exatamente um `sqlite3.connect`**, num único módulo dono,
   com o schema declarado em código. Não há SQL de escrita espalhado pelo
   projeto.
2. **O dialeto Postgres já é o dialeto da casa**: o AVA (ERP) é PostgreSQL e
   `api/db.py` já usa psycopg com pool e `dict_row`. Há molde pronto.
3. **A máquina já roda dois PostgreSQL nativos** como serviço automático —
   17 na porta 5432 e 18 na 5433. Não entra Docker nesta história.

### O que NÃO migra

- **Cache reconstruível**: `data/pneus/pneus-atual.json` (6,1 MB),
  `data/dre_cliente/`, `data/premiacao/` e o próprio `telemetria.db`. Mover não
  dá nada — se sumir, a coleta refaz.
- **Segredo em arquivo**: `data/credenciais.json` (permissão 0600) e os
  certificados `.pfx`. Segredo em arquivo com permissão restrita é mais seguro
  que segredo em tabela, e o cofre já tem regra própria.

### A armadilha registrada

`migrations/versions/0001..0006` e `sql/blocks/` descrevem o schema **da
arquitetura** (`op_viagens`, `fin_titulos`, hypertables) e **nunca foram
usados**. Não é isso que se migra. Migrar é mover o que existe; redesenhar é
outro projeto. Fazer os dois no mesmo movimento é o jeito conhecido de perder o
fim de semana e não ter nem uma coisa nem outra.

---

## 2. Decisões de fundação (Fase 0)

**Instância**: PostgreSQL **17, porta 5432** — a que já é a padrão desta
máquina. A 18 (5433) fica de reserva para a troca de major, que é assunto de
outro dia.

Atenção ao par de números parecidos: o AVA também atende na **5432**, mas em
**outro host** (`204.216.142.149`). Mesmo número de porta, máquinas
diferentes — por isso as duas camadas têm variáveis de ambiente separadas
(`POSTGRES_*` para o ERP, `CORTEX_PG_*` para o banco da casa).

**Um banco, um schema**: banco `cortex`, schema `cortex`. Não um banco por
módulo: backup vira um comando só, e um dia se vai querer cruzar `audit_log`
com orçamento sem inventar ponte.

**Camada separada do ERP** (`api/pglocal.py` × `api/db.py`): um é réplica
somente-leitura de terceiro, o outro é o banco de escrita da casa. Unificar
faria uma troca de variável de ambiente mandar query do ERP para o banco
local — e o erro apareceria como "dado sumiu", não como erro de conexão.

**Conexão curta, sem pool, por enquanto.** É a mesma forma do SQLite de hoje
(`_conn()` abre e fecha). Pool entra quando o `auth` migrar, que é quem faz
muitas consultas pequenas por request — e aí com medição, não por suposição.

**Migrations em SQL numerado** (`sql/cortex/NNNN_*.sql`), aplicadas por
`scripts/migrar_schema.py` e registradas em `cortex.schema_versao`. Não se
reaproveitou o Alembic do repositório: ele está apontado para o schema da
arquitetura, com a tabela de versão dele, e enfiar duas cadeias no mesmo lugar
confunde na hora errada. O runner tem trinta linhas e faz o que precisa.

**Datas continuam TEXT na primeira passada.** `'AAAA-MM-DD HH:MM:SS'`, igual
hoje. Tipar `timestamp` é uma segunda passada por store: converter tipo de data
no mesmo movimento em que se troca de banco dobra a superfície de erro
justamente no trecho que não dá para conferir contra o dado antigo.

**Backup antes do primeiro store.** Enquanto era SQLite, backup era copiar um
arquivo. Agora é `pg_dump` agendado com restauração testada. Sem isso a
migração **piora** a segurança do dado, e piora calada.

### Criando o banco (uma vez, e só com superusuário)

A senha da aplicação é gerada e gravada em `.env` (`CORTEX_PG_PASSWORD`) — que
nunca é versionado. A criação da role exige o superusuário `postgres`, e o
`psql` a pede interativamente:

```
& "C:/Program Files/PostgreSQL/17/bin/psql.exe" -h 127.0.0.1 -p 5432 -U postgres
```

```sql
CREATE ROLE cortex LOGIN PASSWORD '<a senha do .env>';
CREATE DATABASE cortex OWNER cortex;
```

Depois, o schema:

```bash
uv run python scripts/migrar_schema.py           # aplica o que falta
uv run python scripts/migrar_antt.py             # carrega o antt.db
uv run python scripts/migrar_antt.py --conferir  # compara os dois lados
```

**ATENÇÃO À ORDEM.** A partir do momento em que `CORTEX_PG_PASSWORD` existe no
`.env`, os módulos já migrados param de usar SQLite e passam a exigir o
Postgres. Encher o `.env` antes de existir a role deixa a tela do RNTRC sem
dado — e a Saúde do Servidor acusa em vermelho, que é como se descobre.

---

## 3. Como fica um módulo migrado

O contrato público muda em uma coisa só: o parâmetro `path` (caminho do
arquivo `.db`) vira `esquema` (schema do Postgres). É o que mantém o teste
isolado — cada teste ganha um schema próprio, do mesmo jeito que ganhava um
arquivo próprio em `tmp_path`.

```python
# antes                                  # depois
arm.gravar_lote(linhas, "2026-07", base) arm.gravar_lote(linhas, "2026-07", esquema)
arm.situacao("007600540", base)          arm.situacao("007600540", esquema)
```

Tradução mecânica de dialeto:

| SQLite | PostgreSQL |
|---|---|
| `?` | `%s` |
| `:nome` | `%(nome)s` |
| `cursor.lastrowid` | `INSERT ... RETURNING id` |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `INSERT OR REPLACE` | `INSERT ... ON CONFLICT (...) DO UPDATE SET ...` |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `GENERATED ALWAYS AS IDENTITY` |
| `PRAGMA journal_mode/foreign_keys` | não existe — some |
| `sqlite3.Row` | `dict_row` (já é o padrão de `api/db.py`) |
| `ALTER TABLE` condicional no `_conn()` | migration numerada |

---

## 4. Sequência

| Fase | O quê | Custo | Estado |
|---|---|---|---|
| 0 | Banco, role, `api/pglocal.py`, runner de migration, backup, padrão de teste | ~1 dia | **feito** |
| 1 | Piloto: `antt` (223 linhas, 8 executes) | 2–4 h | **no ar** |
| 2 | `push` · `correio` · `previsao` · `antecipacoes` · `contrapartida` · `extrato` · `orcamento` | 0,5–1,5 dia cada | a fazer |
| 3 | `auth` — por último, apesar de ser o mais importante | 1–2 dias | a fazer |
| 4 | Cache (`telemetria`, e talvez os JSON) — só se aparecer motivo | — | provavelmente nunca |

**Por que o `auth` por último**, sendo o mais crítico: é o mais acoplado (167
`execute`) e o único cuja falha derruba o login. Quando chegar a vez dele, os
padrões já terão sido provados sete vezes em produção.

**Por que o `orcamento` é o mais caro da Fase 2**: além dos 27 `execute`, ele
carrega o `path=` **na assinatura pública** das funções, com 104 referências
nos testes. O refactor é mecânico, mas é largo.

Cada store da Fase 2 leva junto:
1. a migration `sql/cortex/NNNN_<store>.sql`;
2. um `scripts/migrar_<store>.py` idempotente, que lê o `.db` e escreve no
   Postgres **conferindo contagem linha a linha** e recusando-se a rodar se o
   destino já tiver dado diferente;
3. os testes reapontados para schema por teste;
4. o `.db` antigo **mantido em disco** até a fase seguinte fechar — é o
   desfazer mais barato que existe.

---

## 5. Riscos aceitos, com o olho aberto

**A conexão vira ponto de falha.** SQLite é arquivo: hoje, com o Postgres fora
do ar, o painel abre e só o ERP falha. Depois do `auth`, não abre. Mitigação: a
linha na Saúde do Servidor (já existe), mensagem de erro que diz o que fazer, e
o serviço do Postgres com partida automática — que já é como está.

**A suíte deixa de rodar em qualquer máquina.** Hoje cada teste cria um `.db` em
`tmp_path`: grátis, isolado, paralelo. Com Postgres é preciso um servidor vivo.
O padrão adotado: a fixture tenta conectar e, se não houver banco, **pula o
teste dizendo por quê** — nunca falha por ausência de infraestrutura, e nunca
finge que passou.

**Ordem de partida no Windows.** A tarefa agendada da API passa a depender do
serviço do Postgres. Os dois são automáticos; se um dia a API subir antes, a
primeira consulta falha e a Saúde acusa.

### O que a primeira execução ensinou

**Conectar e ler a versão do schema são duas perguntas diferentes.** O
diagnóstico fazia `SELECT max(versao) FROM schema_versao` para saber se o banco
respondia; num banco recém-criado a tabela não existe, o `UndefinedTable` subia
como falha de conexão e o runner se recusava a aplicar justamente a migration
que criaria a tabela. Hoje são dois passos: `SELECT 1` diz se conectou, e a
versão vem depois, podendo ser nula.

**A ordem entre `.env` e role é uma armadilha real, não teórica.** Com a senha
no `.env` e a role ainda inexistente, a tela do RNTRC ficou fora do ar — o
código já estava em produção. Em toda fase seguinte: criar a role e carregar o
dado ANTES de o módulo passar a apontar para cá.

**Backup agendado, não só escrito.** `scripts/instalar_tarefa_backup.ps1`
registra a tarefa "Cortex Sulista - Backup" (diária, 03:20, conta SISTEMA). Um
script de backup que ninguém roda é pior que não ter backup, porque parece que
tem. O dump foi conferido com `pg_restore -l`: as três tabelas estão lá.

---

## 6. O que se ganha — e o que não

Ganha-se **um lugar só para fazer backup**, join entre domínios hoje separados
por arquivo, escrita concorrente de verdade e o caminho para TimescaleDB e
pgvector que a arquitetura prevê.

Não se ganha desempenho. Para 25 mil linhas o SQLite não é gargalo nenhum, e
dizer o contrário seria vender a mudança por um motivo que não se sustenta. O
ganho é operacional e estratégico — e é justamente por isso que dá para ir
devagar, um store por vez, sem pressa e sem parar nada.
