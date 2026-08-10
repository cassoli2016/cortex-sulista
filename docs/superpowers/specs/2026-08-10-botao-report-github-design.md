# Botão de Report → issue no GitHub

**Data:** 10/08/2026
**Estado:** aprovado pelo usuário em 10/08/2026

## Problema

Quem usa o CÓRTEX não tem como avisar de um defeito ou pedir uma melhoria sem sair do
painel. O relato chega por mensagem solta, sem tela, sem filtro, sem versão — e a maior
parte do tempo de correção vai embora reconstruindo o cenário.

## Objetivo

Um botão sempre presente no canto inferior direito que abre um formulário curto (bug ou
melhoria), captura print e anexos, coleta sozinho o contexto técnico e registra tudo como
**issue no GitHub**.

## Decisão estruturante: repositório separado e privado

`cassoli2016/cortex-sulista` é **público**. Print de tela do CÓRTEX carrega faturamento,
nome de cliente, placa e PII — não pode ir para issue pública.

As issues e os anexos vão para **`cassoli2016/cortex-sulista-reports`, privado**. O repo de
código continua público e intocado. O repo de reports precisa existir antes do primeiro
envio (criação é pré-requisito de operação, não de código).

## Fluxo

```
[FAB] → modal → usuário escreve, captura print, anexa
      → POST /api/report (JSON único, ≤ 15 MB)
      → backend sobe anexos (Contents API) → cria issue (Issues API)
      → modal mostra "#12 registrado"
```

## Componentes

### 1. Botão flutuante (`api/static/index.html`)

- `#btnReport`, `position:fixed; right:20px; bottom:20px; z-index:150` — abaixo do modal
  (180) e do login (200), acima de todo conteúdo.
- Círculo de 52px, fundo `--n0`, borda `--n200`, sombra `--shadow`, com
  `/static/icon-192.png` (o símbolo "S") em 30px. A logo horizontal (478×106) não é usada:
  em botão circular fica ilegível.
- Hover/foco expande para pílula com o rótulo "Reportar". A transição respeita o bloco
  global de `prefers-reduced-motion` já existente no arquivo.
- Mobile (≤880px): `bottom: calc(72px + env(safe-area-inset-bottom))` — a `.bottomnav` é
  fixa, tem `min-height:48px` mais `6px` de padding em cima e embaixo, e ocuparia o mesmo
  canto.
- Oculto em: `body.tvfull`, `body.tvmode`, `@media print` (junto do bloco que já esconde
  sidebar e bottomnav) e enquanto o `#loginOverlay` estiver visível.
- `aria-label="Reportar problema ou sugerir melhoria"`.
- Só é inserido no DOM se `GET /api/report/config` responder `ativo:true`. Sem token
  configurado o recurso não existe para o usuário — mesmo padrão de GOBRAX e VAPID, que
  nascem desligados sem erro.

### 2. Modal do formulário

Reusa `abrirModal(html, trava)` com **`trava=true`**: clique fora e Esc não fecham, porque
o modal guarda texto digitado e um print que custou dois cliques para obter. Fecha pelo
botão Cancelar.

| Campo | Regra |
|---|---|
| Tipo | Dois chips, `bug` ou `melhoria`. Obrigatório, sem default |
| Gravidade | 3 níveis; rótulo muda pelo tipo (bug: *Trava meu trabalho / Atrapalha / Pode esperar*; melhoria: *Muito importante / Seria bom / Ideia solta*). Mapeia para `alta`/`media`/`baixa` |
| Título | Obrigatório, 1–120 caracteres |
| Descrição | Obrigatória, 1–8000 caracteres. Placeholder muda pelo tipo |
| Print | Botão "Capturar tela"; também aceita colar (Ctrl+V) e arrastar arquivo |
| Anexos | Até 5 arquivos, 8 MB cada, **15 MB somados** (print incluído) |
| "O que vai junto" | `<details>` expansível com o conteúdo exato do contexto coletado |

O bloco "O que vai junto" não é enfeite: o envio inclui print, e-mail e filtros. Quem
manda tem que poder ver o que está mandando antes de clicar.

Rodapé: "Enviar report" (vira "Enviando…" e desabilita — também é o que evita issue
duplicada por clique repetido) e "Cancelar". Erro inline em `.m-err`, padrão do arquivo.

### 3. Captura de tela

`navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'browser'}, preferCurrentTab:true})`,
depois `<video>` + `canvas.drawImage` + `toBlob`. **Não** usa `ImageCapture`: não existe em
Safari nem Firefox, e o caminho por `<video>` funciona em todos.

- O modal é escondido (`.aberto` removido) antes da captura e reexibido depois, senão ele
  aparece na foto. Dois `requestAnimationFrame` mais 150 ms antes de desenhar o frame,
  para o repaint acontecer.
- As tracks são paradas (`track.stop()`) sempre, inclusive em erro — senão o navegador
  fica com o indicador de compartilhamento aceso.
- Imagem reduzida para no máximo 1920px de largura; PNG, ou JPEG 0,85 se passar de 2 MB.
- **Contexto seguro é exigência do navegador**: funciona em `localhost` e no acesso HTTPS
  via Cloudflare Tunnel. Em HTTP puro por IP, `getDisplayMedia` é `undefined` — o botão de
  captura sai desabilitado com o aviso "seu navegador não permite capturar a tela aqui;
  use Print Screen e cole (Ctrl+V) ou anexe o arquivo".

### 4. Contexto coletado automaticamente

| Dado | Origem |
|---|---|
| Tela | `location.hash` + `VIEWS[view]` |
| Filtros ativos | `qsView(viewKey(view))` — a mesma função que monta a query da tela |
| Usuário | `USER.nome`, `USER.email`, `USER.perfil` |
| Versão | `GET /api/versao` (rótulo `CX-DD/MM/AAAA-vX.Y.Z`) |
| Ambiente | `navigator.userAgent`, `screen.width×height`, `devicePixelRatio` |
| Erros de JS | buffer circular das 10 últimas ocorrências |

O buffer de erros é alimentado por `window.addEventListener('error')`,
`'unhandledrejection'` e pelo **wrapper de `fetch` que já existe** (respostas ≥ 400).
Estender o wrapper existente, nunca criar um segundo: `_fetch0` é usado de propósito no
boot e no login para escapar do tratamento de 401, e um wrapper novo o sequestraria.
Guarda método, URL e status — **nunca o corpo da resposta**, que traria dado de negócio
para dentro de um campo que ninguém revisa.

### 5. Backend — `api/reports/`

Estrutura espelhando `api/extrato/`:

- `github.py` — cliente `httpx` (já é dependência). `subir_anexo(caminho, b64) -> url` via
  `PUT /repos/{repo}/contents/{caminho}`; `criar_issue(titulo, corpo, labels) -> (numero, url)`
  via `POST /repos/{repo}/issues`. Timeout de 30 s. Nenhuma função loga o token, e a
  mensagem de erro devolvida ao front nunca ecoa cabeçalho de requisição.
- `servico.py` — valida o payload, monta o markdown, orquestra anexos e issue.

Endpoints em `api/main.py`:

- `GET /api/report/config` → `{"ativo": bool, "repo": str}`. `ativo` é `GITHUB_TOKEN` e
  `REPORT_REPO` presentes no ambiente.
- `POST /api/report` → JSON único com anexos em base64.
  - Rejeita pelo header `content-length` acima de 15 MB **antes** de materializar o corpo,
    e confere de novo o tamanho real depois — `Content-Length` pode faltar ou mentir. É o
    mesmo par de defesas do `extrato_importar`.
  - Base64 já é o formato que a Contents API do GitHub consome: o que o navegador manda vai
    direto, sem decodificar e recodificar.
  - Nome de arquivo é reescrito pelo servidor: `AAAAMMDD-HHMMSS-<slug-do-titulo>-<i>.<ext>`,
    em `anexos/AAAA/MM/`. A extensão vem de uma allowlist (png, jpg, jpeg, gif, webp, pdf,
    csv, txt, log, xlsx, docx); qualquer outra é recusada.
  - Registra em `audit_log` (toda escrita entra no audit, regra do projeto).
  - Falha do GitHub → 502 com mensagem legível; o modal mantém o formulário preenchido e
    oferece "Tentar de novo".

**Atômico por escolha:** anexos sobem antes da issue. Se a issue falhar, ficam blobs órfãos
no repo de reports — barato e invisível. A ordem inversa (issue antes) deixaria issue sem
anexo, que é o defeito que o usuário vê.

**Sem fila de pendências.** Falha de rede não guarda nada em disco: o texto e o print
continuam no modal e o usuário reenvia. Fila persistente exigiria estado, expiração e uma
tela de gerenciamento — complexidade que um painel de rede interna não paga.

### 6. Formato da issue

Título: `[Bug] <titulo>` ou `[Melhoria] <titulo>`.

Labels: `bug`|`melhoria`, `prioridade:alta|media|baixa`, `tela:<hash>`, `cortex-report`.
Label inexistente é criada pela própria API de issues, então não há passo de setup.

Corpo em markdown: relato, tabela de "onde" (tela, filtros, URL), lista de anexos, tabela
de ambiente (versão, navegador, resolução, usuário, data/hora) e bloco de erros de JS
quando houver. Fecha com `<!-- cortex-report v1 -->`, marca que permite achar e migrar os
reports depois.

**Anexo em repo privado não renderiza inline.** A issue traz links clicáveis
(`[print-da-tela.png](https://github.com/…/blob/main/anexos/…?raw=1)`) e não imagens
embutidas: o proxy de imagem do GitHub não autentica em repositório privado, e `![](…)`
mostraria um quadrado quebrado. Um clique abre a imagem para quem tem acesso ao repo.

### 7. Configuração (`.env`)

```
GITHUB_TOKEN=            # PAT fine-grained: Contents write + Issues write, SÓ no repo de reports
REPORT_REPO=cassoli2016/cortex-sulista-reports
```

Entram no `.env.example` com essa explicação e sem valor. O token é gerado e colado pelo
usuário direto no `.env` — credencial não passa por conversa.

## Segurança

- Endpoint protegido pelo `AuthMiddleware`, que já cobre todo `/api/*`. Reportar não é
  privilégio de tela: todo usuário logado pode.
  **Corrigido durante a implementação** — o middleware é *fail-closed*: rota `/api/*` fora
  de `ROTA_TELAS` devolve 403 para quem não é admin. Só ficar de fora do mapa não bastava;
  a rota entrou em `auth._ROTAS_SEM_TELA` (ao lado de `/api/push/`), com teste que trava
  essa liberação. Sem isso o botão apareceria para todos e funcionaria só para o admin.
- Token só no servidor. O navegador nunca vê `GITHUB_TOKEN`.
- Print e e-mail do usuário só existem dentro de repositório privado.
- Extensão de anexo por allowlist; nome de arquivo sempre reescrito pelo servidor (nome
  vindo do cliente é caminho em potencial: `../`).

## Testes

- `tests/test_reports.py` — montagem do markdown, validações (título vazio, tipo inválido,
  extensão fora da allowlist, excesso de anexos, payload acima de 15 MB), e o caminho feliz
  com o cliente do GitHub trocado por dublê. Nenhum teste toca a rede.
- `tests/test_ui_report.py` (Playwright, já no `.venv`) — o FAB some sem config e aparece
  com ela; o modal valida campo obrigatório; o envio usa `page.route` para simular
  `/api/report`; em 390px de largura o FAB não sobrepõe a `.bottomnav`.
- `scripts/verificar_estrutura.py` roda depois da mexida no HTML, como manda o CLAUDE.md.

## Entrega (regra 5.1 do CLAUDE.md)

Recurso novo retrocompatível: `0.2.0` → **`0.3.0`** em `pyproject.toml`, bloco em
`docs/versoes.yaml`, `CHANGELOG.md` regerado por `scripts/gerar_changelog.py`, e o botão
descrito em `docs/manual.yaml` — é recurso global, não tela, então entra como termo de
glossário.

## Fora de escopo

- Tela no painel listando reports enviados (o GitHub já é essa tela).
- Reenvio automático e fila offline.
- Notificação por e-mail ou push quando a issue é respondida.
- Vínculo entre conta do painel e conta do GitHub: a issue é aberta por um token de
  serviço, e quem reportou aparece no corpo.
