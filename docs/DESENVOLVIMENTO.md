# Desenvolver no CÓRTEX

> Para quem escreve código no CÓRTEX **fora da máquina de produção**. Leia
> inteiro antes do primeiro commit. As regras técnicas da casa — como se faz
> uma tela, um gráfico, uma consulta ao ERP — estão no `CLAUDE.md`. Este
> arquivo trata do resto: o que você recebe de acesso, como montar o ambiente,
> o caminho do código até o ar e o que não se faz.
>
> Em vigor desde 12/09/2026.

---

## 0. Três fatos que explicam todas as regras abaixo

1. **A `main` É a produção.** Uma tarefa agendada na máquina de produção puxa
   `origin/main` a cada 2 minutos e reinicia a API. O que entra na `main` está
   no ar para a empresa inteira em até 2 minutos, sem mais nenhum portão.
2. **A migration entra sozinha no banco de produção.** Quando a API reinicia,
   `auth.init_db()` aplica todo `sql/cortex/NNNN_*.sql` pendente no banco da
   casa (`api/main.py`, `startup`). Ninguém confere antes: quem confere é o PR.
3. **O repositório é PÚBLICO.** Commit, PR, issue, comentário e anexo de PR
   ficam visíveis para qualquer pessoa na internet, e reescrever o histórico
   não tira o que já foi copiado.

---

## 1. O que você recebe — e o que não recebe

| Recebe | Não recebe |
|---|---|
| Acesso de colaborador no GitHub: branch própria e PR | Push na `main` (ela é protegida) nem o botão de merge |
| Usuário **só-leitura próprio** no AVA (o ERP), com tempo limite de consulta | O usuário do AVA que a produção usa |
| Conta no CÓRTEX de produção com perfil **sem administrador**, para conhecer as telas | Perfil administrador, a Gestão, o cofre de credenciais |
| — | O `.env` da produção e qualquer arquivo de `data/` da produção |
| — | Certificado A1, credencial de Z-API (WhatsApp), SMTP, Gobrax, SEFAZ, Microsoft Graph, Smartec, RasterJOR, Monkey |
| — | Acesso à máquina de produção (área de trabalho remota, pasta compartilhada) |

**Por que as credenciais de integração ficam de fora mesmo no seu ambiente:**
várias rotinas do CÓRTEX agem no mundo real assim que encontram uma credencial.
O WhatsApp manda mensagem para cliente e motorista, o correio manda e-mail
para a diretoria, e o certificado A1 emite e manifesta documento fiscal com
validade jurídica. Não existe "modo teste" dessas integrações aqui, por decisão
(`CLAUDE.md` §7). Num clone limpo nenhuma delas está configurada — é assim que
o seu ambiente fica. Vai trabalhar numa integração? Fale antes: o caminho é o
dublê do fornecedor (o FORMATO do corpo real, com valores fictícios), e a
conferência contra o fornecedor de verdade é feita na máquina de produção.

**O AVA é a réplica de produção de um ERP de terceiro, dividida com o Power BI
da empresa.** O seu usuário é só-leitura e tem tempo limite, mas uma consulta
pesada ainda deixa o painel de todo mundo lento. Enquanto explora: filtre por
período, use `LIMIT`, nunca `SELECT *` numa tabela de lançamento. E os dados lá
são reais — folha, salário, CPF, financeiro, clientes. O termo de
confidencialidade vale para eles: nada disso vai para commit, PR, issue,
print, planilha ou ferramenta externa, **inclusive assistente de IA na nuvem
com dado colado na conversa**.

---

## 2. Montar o ambiente (uma vez)

Pré-requisitos: Git, [uv](https://docs.astral.sh/uv/), Node 18+ (só para o
`node --test`) e **PostgreSQL 17** local — a mesma versão da produção.

```bash
git clone https://github.com/cassoli2016/cortex-sulista.git
cd cortex-sulista
uv sync --group test                 # SEM --group test ele desinstala pytest e playwright
uv run playwright install chromium   # na 1ª vez e a cada bump do playwright
```

**O banco da casa (onde o CÓRTEX escreve) é o SEU Postgres local** —
descartável, seu, sem nada da produção. Como superusuário da sua instância:

```sql
CREATE ROLE cortex LOGIN PASSWORD 'uma-senha-so-sua';
CREATE DATABASE cortex OWNER cortex;
```

**O `.env`** na raiz do clone (o `.gitignore` já o protege; nunca o force para
dentro de um commit). Ignore o `.env.example`: ele descreve a arquitetura
planejada original, com TimescaleDB e Redis que não existem. O seu é este:

```ini
# Banco da casa: o SEU Postgres local
CORTEX_PG_HOST=127.0.0.1
CORTEX_PG_PORT=5432
CORTEX_PG_DB=cortex
CORTEX_PG_USER=cortex
CORTEX_PG_PASSWORD=uma-senha-so-sua

# ERP (AVA): o SEU usuário só-leitura, recebido em particular
POSTGRES_HOST=<recebido>
POSTGRES_PORT=5432
POSTGRES_DB=<recebido>
POSTGRES_USER=<o seu usuário>
POSTGRES_PASSWORD=<a sua senha>

# Assina a sessão de login. Sem ele o CÓRTEX sorteia um a cada reinício e o
# --reload desloga você a cada arquivo salvo. Qualquer texto longo e aleatório.
APP_SECRET=<texto-longo-aleatorio-so-seu>
```

**E é só isso.** Não acrescente Z-API, SMTP, Gobrax, `GITHUB_TOKEN`, VAPID,
`MOTORISTA_CODIGO_MESTRE` nem nada de `data/` — veja a seção 1.

Subir:

```bash
uv run python scripts/migrar_schema.py            # cria as tabelas no SEU banco
uv run uvicorn api.main:app --reload --port 8010
```

Abra `http://127.0.0.1:8010`. O primeiro administrador **do seu banco local**
só pode ser criado pelo acesso local — é um admin da sua máquina, sem relação
nenhuma com a produção.

Conferir que tudo funciona:

```bash
uv run pytest -q                           # a suíte inteira: dezenas de minutos
node --test "tests/frontend/*.test.js"
uv run python scripts/verificar_estrutura.py
```

O teste que usa o banco (fixture `esquema_pg`) cria um schema próprio e o
apaga no fim — não mexe no seu schema `cortex`.

---

## 3. O caminho até a produção

```
git fetch → branch a partir de origin/main → commits → PR
  → CI "suite" verde + aprovação do responsável → merge (pelo responsável) → no ar em 2 min
```

1. **Uma branch por entrega, e curta.** Nome: `feat/<seu-nome>-<assunto>` ou
   `fix/<seu-nome>-<assunto>`. A tela inteira mora num arquivo só
   (`api/static/index.html`, 43 mil linhas): uma branch de semanas conflita
   com tudo o que entrou nesse meio tempo.
2. **Atualize a branch a partir da `main` todo dia — e SEMPRE com `git fetch`
   antes**: `git fetch origin && git rebase origin/main`. Depois de rebase, na
   SUA branch, `git push --force-with-lease`. Na branch de outra pessoa, nunca.
3. **Não mexa em `pyproject.toml` (a versão), `docs/versoes.yaml` nem
   `CHANGELOG.md`.** O número de versão é dado por quem faz o merge, na hora
   do merge. Com várias frentes, o número combinado antes é quase sempre o
   errado, e cada PR conflitaria na mesma linha (`CLAUDE.md` §1). No lugar
   disso, o modelo de PR pede o **texto** do bloco de versão: o que muda para
   quem USA, na língua de quem usa.
4. **Abra o PR** preenchendo o modelo. Use rascunho (draft) enquanto não
   estiver pronto.
5. **CI verde é obrigatório.** O job `suite` roda a suíte inteira com um
   Postgres descartável e leva dezenas de minutos: rode localmente antes, para
   não descobrir a falha lá.
6. **A aprovação do responsável é obrigatória** (`.github/CODEOWNERS`). Todo PR
   passa também por uma revisão automática do Claude. Responda a cada
   apontamento com a correção ou com o motivo para não corrigir.
7. **O merge é do responsável**, mesmo com tudo verde — é nessa hora que o
   número de versão é dado. Depois, a produção atualiza em até 2 minutos.

**Tela nova tem ONZE registros, não um** (`CLAUDE.md` §3), e os testes que
cobram cada um moram em arquivos que não falam do assunto. PR com tela nova ou
com migration roda a suíte **completa** antes de pedir revisão.

---

## 4. O que não se faz

**Git e GitHub**
- Push na `main`, `push --force` na `main`, apagar branch alheia.
- Commitar `.env`, qualquer coisa de `data/`, planilha, CSV, print, PDF, XML de
  nota ou dump de banco. **Rode `git status` antes de TODO commit**: uma saída
  de depuração redirecionada para um arquivo na raiz já publicou as contas
  bancárias da empresa neste repositório.
- Print ou dado real em PR, issue ou comentário. Precisa mostrar a tela? Use
  dado fictício, ou mande o print em particular para o responsável.

**Banco**
- **Editar migration que já está na `main`.** Ela já rodou na produção; mudar
  o arquivo não altera banco nenhum, só faz o repositório mentir sobre o banco.
  O conserto é uma migration NOVA.
- DDL destrutivo (`DROP`, `DELETE`, `TRUNCATE`, troca de tipo que perde dado)
  sem combinar antes — ele roda sozinho em produção (seção 0).
- **Número de migration**: o próximo livre em `origin/main` NO DIA DO PR. Se
  outro PR entrar antes com o mesmo número, renumere o seu.
  `tests/test_migracao_numero_unico.py` recusa dois arquivos com o mesmo
  número, e o runner recusaria de novo em produção.
- Tentar escrever no AVA (a conexão é só-leitura de propósito) ou abrir SQLite
  (há teste que reprova).

**Código**
- Dependência nova no `pyproject.toml` sem combinar — o deploy a instala em
  produção.
- Biblioteca por CDN, framework de front ou outra biblioteca de gráfico: é
  ECharts, vendorizado (`CLAUDE.md` §5).
- Reformatar, reordenar ou reescrever o `index.html` em bloco: toda branch
  aberta passaria a conflitar no arquivo inteiro. Edite só o trecho que
  precisa. Script que regrava arquivo usa `newline="\n"` (ver `.gitattributes`).
- Subir relógio ou thread no `startup` sem `lider.sou_o_agendador()` (ele roda
  uma vez POR WORKER), ou criar tarefa agendada sem combinar.
- Mexer sem combinar em `scripts/autodeploy.ps1`, `scripts/win/`, `.github/`,
  `api/auth.py`, no middleware de `api/main.py`, em `api/segredo_arquivo.py` ou
  em `api/credenciais.py`. É onde um erro derruba o acesso de todo mundo ou
  abre um segredo.

**Dados**
- Dado real (nome, CPF, placa, valor, cliente) em teste, fixture, seed,
  comentário ou mensagem de commit. Dublê de fornecedor copia o FORMATO real,
  com valores fictícios.

---

## 5. Claude Code (e outros assistentes) no seu clone

O `CLAUDE.md` é lido automaticamente e vale para você — com **uma exceção**: a
regra "commit e push no mesmo minuto, sem perguntar" é da máquina de produção,
onde um commit sem push trava o deploy. No seu clone não há deploy nenhum a
travar; o destino é sempre a sua branch e o PR.

Para o assistente não tentar empurrar na `main` por hábito, crie
`.claude/settings.local.json` (não é versionado):

```json
{
  "permissions": {
    "deny": [
      "Bash(git push origin main:*)",
      "Bash(git push --force:*)",
      "Bash(git push -f:*)"
    ]
  }
}
```

A trava de verdade é a proteção da `main` no GitHub; isto só evita a tentativa.
O `--force-with-lease` na sua branch, depois de um rebase, você mesmo roda.

---

## 6. Quando algo dá errado

- **Quebrou algo em produção depois do merge?** Avise o responsável NA HORA.
  O conserto é `git revert` do commit, feito por ele — nunca reescrever a
  `main`. Migration não se desfaz: o conserto é outra migration.
- **Viu dado real, segredo ou senha num commit ou PR (seu ou de outra
  pessoa)?** Avise na hora e não tente apagar sozinho: o segredo precisa ser
  TROCADO, porque apagar do histórico não tira o que já foi copiado.
- **Conflito no rebase**: resolva LENDO os dois lados. Nunca `--ours` ou
  `--theirs` no arquivo inteiro. Conflito que parece o `index.html` inteiro é
  quebra de linha, não trabalho alheio (`.gitattributes`).

---

## 7. Para o responsável: liberar um PR

O merge é feito pela sessão do Claude **na máquina de produção**, porque é lá
que moram as travas de versão da seção 1 do `CLAUDE.md`. O fluxo:

1. **"Revise o PR #N"** — `/code-review N` na sessão (precisa do GitHub CLI;
   ver seção 8). Leia o resumo, confira o CI `suite` verde no último commit do
   PR e aprove no GitHub (ou peça as correções no próprio PR).
2. **"Libere o PR #N"** — a sessão:
   - roda `git fetch` e confere a árvore limpa;
   - faz `git merge --no-ff --no-commit origin/<branch-do-PR>`;
   - dá o número de versão (um acima do topo do `origin`, comparado como
     tupla), escreve o bloco do `versoes.yaml` a partir do texto do PR e
     regenera o `CHANGELOG.md`;
   - confere que não sobrou marcador de conflito e roda os testes de versão e
     os do assunto do PR;
   - commita e empurra no MESMO comando da trava de versão.

   O GitHub marca o PR como mesclado sozinho, porque o último commit dele
   passa a estar na `main`. Um deploy só, já com o número certo.
3. **Depois de 2 minutos**: `GET /api/versao` mostra o número novo e a Saúde do
   Servidor segue verde. Se não, `git revert` e aviso ao desenvolvedor.

Suas sessões na máquina de produção continuam empurrando direto na `main`,
como administrador da regra de proteção — é o fluxo de sempre, e o risco dele
não muda.

---

## 8. Para o responsável: entrada e saída de um desenvolvedor

### Uma vez: proteger a `main` e instalar o GitHub CLI

GitHub → `cassoli2016/cortex-sulista` → **Settings → Branches → Add branch
protection rule**, padrão `main`:

- [x] Require a pull request before merging
  - [x] Require approvals: **1**
  - [x] Dismiss stale pull request approvals when new commits are pushed
  - [x] Require review from Code Owners
- [x] Require status checks to pass before merging → procure e marque **`suite`**
- [x] Require conversation resolution before merging
- [ ] Do not allow bypassing the above settings — **DESMARCADO**: é o que deixa
  você e as sessões da máquina de produção seguirem empurrando direto
- [ ] Allow force pushes — desmarcado
- [ ] Allow deletions — desmarcado

A verificação `suite` só aparece na lista depois de ter TERMINADO pelo menos
uma vez; ligue a regra depois do primeiro CI verde.

Na máquina de produção, para o Claude ler e revisar PRs:
`winget install --id GitHub.cli` e depois `gh auth login` (conta `cassoli2016`).

### Entrada

1. Termo de confidencialidade assinado (o acesso ao AVA mostra folha, CPF e
   financeiro).
2. Conta **individual** no GitHub, com autenticação em dois fatores. Settings
   → Collaborators → Add people.
3. Usuário no AVA, pedido à Avacorp: **um por desenvolvedor**, somente leitura
   (`default_transaction_read_only`), com `statement_timeout` (60 s, igual ao
   do CÓRTEX) e o IP de origem liberado no `pg_hba`. Senha entregue em
   particular, nunca por e-mail ou chat aberto.
4. Conta no CÓRTEX: Gestão › Usuários, perfil **sem administrador**.
5. Enviar este guia e o `CLAUDE.md`.

### Saída — no mesmo dia

1. Remover o colaborador no GitHub.
2. Pedir à Avacorp a remoção do usuário do AVA.
3. Desativar a conta no CÓRTEX.
4. Se a pessoa teve contato com qualquer segredo, trocá-lo.
