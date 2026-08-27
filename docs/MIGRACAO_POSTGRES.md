# Migração dos bancos locais para PostgreSQL

> Estado: **CONCLUÍDA** em 27/08/2026 — os dez bancos de estado migrados, do
> `antt` (223 linhas) ao `auth` (o do login). O que ficou de fora ficou de
> propósito: cache reconstruível e segredo em arquivo (seção 1).

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
| 2 | ~~`push`~~ · ~~`correio`~~ · ~~`previsao`~~ · ~~`antecipacoes`~~ · ~~`extrato`~~ · ~~`orcamento`~~ · ~~`contrapartida`~~ | 0,5–1,5 dia cada | **7 de 7** |
| 3 | ~~`auth`~~ — por último, apesar de ser o mais importante | 1–2 dias | **feito** |
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

### Duas regras que os stores 2 e 3 acrescentaram

**Toda tabela leva o prefixo do módulo.** `email.db` e `antecipacoes.db` têm,
os dois, uma tabela `envios` — no schema único elas disputariam o mesmo nome. A
colisão apareceu ao escrever a migration do correio, antes de qualquer dado se
perder, e a regra passou a valer para trás: `subs`/`meta` viraram
`push_subs`/`push_meta` no mesmo dia. É a convenção que o `CLAUDE.md` já manda
para o banco grande (`fin_*`, `com_*`, `op_*`). Nome que já é inequívoco fica
como está (`rntrc_*`), o que importa é não disputar.

**Nada de DDL no import.** `api/push.py` chamava `init_db()` no nível do
módulo: com SQLite, criar o arquivo custava nada. Com Postgres, um DDL no
import faz a API inteira falhar na subida se o banco estiver fora do ar — por
causa do módulo de notificação, que é o mais acessório de todos. As tabelas
nascem na primeira escrita, e toda leitura antes disso responde vazio.

### Como o teste redireciona (a manopla que substitui o `DB_PATH`)

O módulo migrado expõe `ESQUEMA: str | None = None`, e o teste faz
`monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)` — exatamente o idioma
que já existia com `DB_PATH`. O argumento `esquema=` continua valendo e vence,
para quem precisa de dois schemas na mesma linha.

É o que torna barato o resto da Fase 2: `orcamento` tem 104 referências a
`tmp_path`/`DB_PATH` nos testes, e sem a manopla cada uma delas viraria uma
edição.

### O que os stores 4 e 5 acrescentaram

**Id que é referenciado não pode "levar a ordem".** Nos outros stores, coluna
`IDENTITY` foi resolvida inserindo na ordem da origem e deixando o Postgres
numerar. Não serve para `ant_envios`: `ant_titulos.envio_id` APONTA para ele.
O script guarda o de-para `id_antigo → id_novo` e traduz cada título — sem
isso, a posição de cada portal apontaria para o envio errado, e o total da
tela continuaria batendo, que é o pior tipo de erro.

**Renomear parâmetro é seguro; mudar a POSIÇÃO não é.** Em `previsao`, o
primeiro argumento era `path` e virou `esquema` — na mesma posição, com as
chamadas passando `arm.ESQUEMA` no lugar de `arm.DB_PATH`. Tirar o parâmetro
faria uma chamada posicional antiga mandar o mês para o lugar do schema, sem
erro nenhum e com resultado vazio.

**Cuidado com o alias `arm`.** Uma troca de `arm.DB_PATH` por `arm.ESQUEMA` em
`api/main.py` pegou 16 linhas do ORÇAMENTO, que ainda é SQLite — no mesmo
arquivo, `arm` é o armazenamento de três módulos diferentes conforme o import
local de cada endpoint. Conferir o `git diff` antes de commitar pegou; um
`sed` confiante não teria pegado.

**Teste que lê o banco cru precisa migrar junto.** Três testes (previsão e
Monkey) abriam o `.db` com `sqlite3` para conferir o que FOI GRAVADO, em vez
de confiar no retorno da função. É a asserção certa — e por isso ela também
tem de falar Postgres.

### O que o `extrato` acrescentou (store 6)

**A ordem da Fase 2 é uma sugestão, não um contrato.** `contrapartida` era o
próximo da lista e foi pulado: a outra sessão estava com os cinco últimos
commits dentro de `api/contrapartida/`, que é onde moram as três tabelas desse
store. Disputar um módulo FISCAL arquivo a arquivo, com certificado e
autorização da SEFAZ no meio, não vale o risco. Volta quando a frente sair de
lá.

**Argumento padrão avaliado no import é uma armadilha silenciosa.**
`def painel(..., path=arm.DB_PATH)` amarra o valor no momento do `def`: um
`monkeypatch` posterior em `arm.DB_PATH` não teria efeito nenhum, e o teste
escreveria no banco de PRODUÇÃO achando que estava isolado. Os quatro padrões
viraram `None`, resolvido em tempo de chamada.

**Parâmetro que carrega schema não pode se chamar `path`.** Renomeado em
`servico.py` e nos testes junto com a mudança de valor — nome errado que
"funciona" custa uma hora de quem vier depois.

**Código morto de migração antiga não atravessa.** `_remigra_chaves` recalculava
chaves no formato `fitid:<id>` a cada `init_db`. A base foi conferida com ZERO
delas, então a função ficou para trás e a guarda passou para o script de carga,
que se recusa a migrar se encontrar uma. O teste que a protegia foi removido —
com o porquê escrito no lugar dele, e o que ele também cobria (reimport não
duplicar) segue coberto por outro.

### O que o `orcamento` acrescentou (store 7, o maior)

**`init_db()` a cada escrita precisava ficar barato.** Ele é chamado em toda
gravação — é o que garante que a primeira escrita de uma instalação crie as
tabelas — e reaplicava a checagem de migrations toda vez: duas idas ao banco só
para descobrir que não havia nada a fazer. A suíte do orçamento passou de 2 para
mais de 10 minutos. `api/migracoes.py` passou a lembrar, POR PROCESSO, quais
schemas já estão na última versão. É seguro porque migration nova só chega com
deploy, e deploy reinicia a API. `apagar_esquema()` esquece junto, senão um
schema de teste recriado com o mesmo nome nasceria sem tabela nenhuma.

**`executemany` manda uma linha por vez.** Numa regeração são 21.696 linhas, ou
seja 21.696 idas ao banco. `gravar_baseline` passou a montar UM insert com
várias tuplas, em lotes de 1.000: **3.600 linhas em 0,21 s** medidos.

**Nem toda lentidão é do banco novo.** Os testes do plano levavam ~12 s cada e
eu atribuí ao insert; o profiler mostrou `api/db.py` — eles consultam o AVA
REMOTO de verdade. Um deles chega a estourar o timeout de 60 s quando a máquina
está disputada. É teste que depende de rede, o que a suíte do extrato já
tinha evitado de propósito — fica anotado como dívida, não é dívida desta
migração.

### O número da migration é um recurso disputado

Descoberto em produção no mesmo dia em que a cadeia nasceu: outra frente aplicou
`0009_correio_agenda.sql` enquanto eu ia numerar o `0009` de contrapartida. O
runner comparava só o NÚMERO e teria pulado a minha **em silêncio** — sem erro,
sem log, com as tabelas simplesmente não existindo. O sintoma apareceria semanas
depois, noutra máquina, como "tabela não existe".

`pendentes()` passou a comparar número **e** nome do arquivo:

| no banco | no repositório | resultado |
|---|---|---|
| ausente | `0010_x.sql` | pendente, aplica |
| `0010_x.sql` | `0010_x.sql` | feito, pula |
| `0010_x.sql` | `0010_y.sql` | **`NumeroJaUsado`** — para e manda renumerar |
| `0009_z.sql` | (não está no disco) | normal: migration de outra frente ainda não commitada |

A última linha importa tanto quanto a terceira: enquanto o arquivo do correio
não for commitado, produção tem uma migration registrada que o repositório não
descreve. Isso não pode travar o deploy de quem não tem nada a ver com aquilo.

E um teste barato que pega a colisão no COMMIT em vez de no deploy: nenhum
número repetido em `sql/cortex/`.

### Os dois últimos (stores 8 e 9)

**Contrapartida ficou por último da Fase 2 por causa de gente, não de código.**
A outra frente estava com os cinco últimos commits dentro de
`api/contrapartida/`; entrei quando os arquivos que eu precisava tocar estavam
parados havia horas, e avisei antes. Num módulo fiscal, disputar arquivo é pior
que esperar.

**Os testes de contrapartida escreviam no banco de PRODUÇÃO.** Não era regressão
da migração — era assim com o `.db` real também: nenhum deles redirecionava o
banco, então `config_grava` e o cadastro gravavam na base de verdade. Ficou
visível porque um teste passou a depender do estado que o outro deixou. Num
módulo onde `lote_config` guarda o interruptor que libera emissão em produção e
`emissao` guarda a numeração dos documentos, isso é sério. Agora há um
`conftest.py` **autouse** no diretório: teste novo nasce isolado sem ninguém
precisar lembrar.

**Rotina de migração antiga não atravessa.** `_migrar_procuracao` copiava a
tabela `procuracao` (nome anterior de `autorizacao`) a cada conexão. Ficou para
trás, e o script de carga se recusa a rodar se a origem ainda tiver a tabela
antiga — autorização perdida é justamente o registro que permite emitir em nome
de alguém.

**`init_db()` no import derruba a API inteira** — de novo, agora no `auth`. Era
o mesmo caso do `push`, e aqui com consequência maior: com o banco fora do ar, a
API não subiria e não haveria nem tela de erro para explicar. A chamada foi para
o `startup` de `api/main.py`, dentro de `try/except`: a aplicação sobe, o erro
vai para o log e a Saúde mostra o banco em vermelho, que é onde se olha.

**`executemany` é do cursor, `execute` é dos dois.** Foi o que permitiu converter
os ~160 comandos do `auth` sem mudar a forma de nenhum: `with _conn() as c:
c.execute(...).fetchone()` funciona igual no psycopg. Só os cinco `executemany`
precisaram de um atalho.

**O login foi conferido de ponta a ponta antes de subir**: setup → senha errada
(401) → senha certa (200) → `/api/auth/me` com as 62 telas → e os três eventos
na trilha (`setup_admin`, `login_falha`, `login_ok`).

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
