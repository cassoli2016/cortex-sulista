## O que muda

<!-- Uma ou duas frases: o que este PR faz e por quê. -->

## Texto para o bloco de versão

<!-- NÃO mexa em pyproject.toml, docs/versoes.yaml nem CHANGELOG.md: o número
     é dado por quem faz o merge. Escreva aqui o que MUDA PARA QUEM USA, na
     língua de quem usa (sem nome de função, sem jargão). Diga também se é
     "adicionado", "alterado", "corrigido", "removido" ou "seguranca". -->

## Como conferi

- [ ] Suíte completa local: `uv run pytest -q` (obrigatória se o PR cria TELA NOVA ou MIGRATION)
- [ ] `node --test "tests/frontend/*.test.js"` e `uv run python scripts/verificar_estrutura.py`
- [ ] Teste novo falha quando sabotei o que ele protege (diga o que sabotei):
- [ ] Olhei a tela com dado real no meu ambiente (se mexe em tela)

## Pontos de atenção

- [ ] Tem migration nova? Número: `____` — conferido como o próximo livre em `origin/main` hoje
- [ ] Migration só ACRESCENTA (sem `DROP`/`DELETE`/`TRUNCATE`/troca de tipo que perde dado)
- [ ] Dependência nova no `pyproject.toml`? Qual e por quê:
- [ ] Mexe em `index.html` só nos trechos necessários (sem reformatar bloco)
- [ ] Nenhum dado real no PR: sem print de tela com dado, sem planilha, sem CPF/placa/cliente/valor em teste, fixture ou comentário
- [ ] `git status` conferido antes de cada commit (nada de `data/`, `.env`, saída de depuração)

<!-- Regras completas: docs/DESENVOLVIMENTO.md. O repositório é PÚBLICO. -->
