# Design — Versões protegidas do Orçamento: aprovar, exportar e histórico de regeração

> Data: 2026-07-27 · Origem: brainstorming com o usuário · Status: **aprovado** para
> desenvolvimento. Estende o módulo Orçamento (specs 2026-07-26 e 2026-07-27).

## Decisões do usuário (brainstorming)

Selecionadas: **congelar versões (aprovar)** + **exportar (CSV/Excel)** +
**histórico do Regerar**. Backup automático do arquivo ficou de fora por escolha —
fica registrado que `data/orcamento.db` vive só no disco da produção e o export
manual é o seguro do usuário.

## 1. Aprovar (congelar) versões

- `orc_versao` ganha **`aprovado_em` TEXT** e **`aprovado_por` TEXT** (migração
  PRAGMA + ALTER no padrão das colunas `meses_base`/`metodo`). O campo `status`
  já existe (`rascunho` default) e passa a ter o domínio efetivo
  `rascunho | aprovado | arquivada`.
- **Imutabilidade**: com `status != 'rascunho'`:
  - `armazenamento.ajustar()` levanta `ValueError` ("Versão aprovada/arquivada é
    imutável — reabra antes de ajustar.");
  - `servico.gerar(versao_id=...)` levanta `ValueError` equivalente para regerar.
  - Endpoints traduzem para **422** com a mensagem.
- Endpoints novos (mesmo prefixo RBAC `/api/controladoria/orcamento`):
  - `POST /api/controladoria/orcamento/aprovar` body `{"versao_id": N}` →
    status='aprovado', aprovado_em=agora local "YYYY-MM-DD HH:MM",
    aprovado_por=nome da sessão (mesma fonte do gerar). Aprovar versão
    `arquivada` → 422 (arquivada não vira oficial; gere/regenere uma rascunho).
  - `POST /api/controladoria/orcamento/reabrir` body `{"versao_id": N}` →
    status='rascunho', limpa aprovado_em/aprovado_por. Só de `aprovado` → 422
    para `arquivada` (arquivada é registro histórico, nunca reabre).
- **Tela (Montagem)**: botão **"Aprovar versão"** quando rascunho; quando
  aprovada: badge verde "aprovada por {quem} em {quando}" no cabeçalho do card,
  botão vira **"Reabrir"**, células da grade `disabled` (title: "versão aprovada
  — reabra para ajustar") e botão Regerar `disabled` (title idem). Seletor de
  versões marca "(aprovada)" / "(arquivo)" no rótulo.
- **Fluxo de Caixa**: `provisao_do_ano` passa a escolher a versão **aprovada
  mais recente do ano**; sem aprovada, a **rascunho mais recente** (comportamento
  atual); `arquivada` nunca. O ⓘ já mostra o rótulo — acrescenta "(aprovada)"
  quando for o caso.

## 2. Exportar CSV (abre direto no Excel pt-BR)

- `GET /api/controladoria/orcamento/exportar?versao_id=N` → `text/csv` com:
  - **BOM UTF-8**, separador **`;`**, decimal **vírgula** (Excel pt-BR abre sem
    assistente);
  - Bloco de cabeçalho (linhas `chave;valor`): rótulo, ano, método, base
    (meses_base formatada), fator de tendência, status (+aprovado por/em quando
    houver), criado em/por, exportado em;
  - Linha em branco; depois o cabeçalho de colunas:
    `conta;nome;linha_dre;origem;meses_com_dado;jan;...;dez;total;ajustadas`
    — valores = **valor efetivo** (coalesce do ajuste); `total` = soma dos 12;
    `ajustadas` = lista dos meses com ajuste manual (ex.: "3,7") ou vazio.
  - Nome do arquivo: `Content-Disposition: attachment; filename="orcamento-{ano}-v{id}.csv"`.
  - Versão inexistente → 404. Nomes de conta via `NOME_CONTA_SQL` (AVA); com o
    ERP fora, a coluna `nome` sai vazia e o export NÃO falha (try/except → nomes {}).
- **Tela**: botão **"Exportar CSV"** na barra da Montagem (link direto para o
  endpoint com a versão selecionada — download nativo do navegador). Disponível
  para qualquer status (exportar aprovada/arquivada é o caso de uso principal).

## 3. Histórico do Regerar — snapshot como versão

- Ao regerar uma versão `rascunho`, ANTES de recalcular o serviço cria uma
  **cópia integral** (cabeçalho + todas as linhas com baseline E ajustes) com:
  - `rotulo = "{rotulo original} (antes de regerar {DD/MM HH:MM})"`,
  - `status = 'arquivada'`, mesmo ano/método/fator/meses_base da versão no
    momento do snapshot;
  - implementação em `armazenamento.arquivar_copia(path, versao_id, rotulo_novo)
    -> int` (INSERT ... SELECT dentro de uma transação única).
- A resposta do regerar inclui `"arquivada_id"` e a mensagem da tela diz
  "estado anterior arquivado como versão N".
- Arquivadas aparecem no seletor **depois** das demais (ordenação: aprovadas e
  rascunhos por id desc, depois arquivadas por id desc), com "(arquivo)" no
  rótulo. Imutáveis (regra do §1). Comparação/restauração = trocar de versão no
  seletor e/ou exportar — sem UI de diff nova.

## 4. Erros e casos de borda

| Situação | Comportamento |
|---|---|
| Ajustar/regerar versão aprovada ou arquivada | 422 "versão imutável — reabra antes" (reabrir só para aprovada) |
| Aprovar versão arquivada | 422 |
| Reabrir versão arquivada | 422 |
| Aprovar/reabrir versão inexistente | 404 |
| Exportar com ERP fora | CSV sem a coluna nome preenchida, sem erro |
| Regerar cria snapshot mas a recoleta FALHA depois | O snapshot arquivado permanece (inofensivo — é uma cópia fiel); a versão original continua intacta pelo fallback existente |
| Fluxo com só arquivadas no ano | Sem série (como se não houvesse versão) |

## 5. Testes

- Imutabilidade: ajustar/regerar aprovada e arquivada → ValueError/422; reabrir
  → volta a aceitar ajuste.
- Aprovação: quem/quando gravados; reabrir limpa; arquivada não aprova nem reabre.
- Snapshot pré-regeração: cópia fiel (baseline + valor_ajustado + metodo +
  meses_base); versão original re-derivada normalmente; `arquivada_id` na resposta.
- Export: BOM presente, `;`, vírgula decimal, total = soma, coluna ajustadas,
  404 inexistente, nomes vazios sem erro com ERP fora (stub).
- Fluxo: aprovada preferida sobre rascunho mais novo; arquivada ignorada.
- Suíte atual (224) verde; estrutural 33/33.

## Critérios de aceite

1. Aprovar → células e Regerar bloqueados na tela com motivo; badge com quem/quando;
   reabrir desbloqueia.
2. Regerar uma rascunho cria "(antes de regerar ...)" arquivada, visível no seletor
   e exportável; a regerada segue editável.
3. Exportar baixa CSV que abre no Excel pt-BR com valores corretos (vírgula) e
   total conferindo.
4. Fluxo usa a aprovada mais recente quando existe (ⓘ diz "(aprovada)").
5. pytest + estrutural verdes; método espelho/semestre e telas existentes sem
   regressão.

## Fora do escopo

- Backup automático do `orcamento.db` (decisão do usuário).
- Diff visual entre versões; workflow multi-aprovador; trilha em `audit_log`
  (dívida transversal já registrada).
