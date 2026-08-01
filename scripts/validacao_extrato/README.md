# Validação da tela Extrato Bancário

Verificação ponta a ponta da tela `#extb` no navegador — o que a suíte de testes
não cobre (o projeto não tem harness ASGI/DOM). Rodou 18/18 em 2026-08-01.

## Como rodar

```bash
# 1) gera o OFX de teste (conta REAL do ERP + valores REAIS de contacorrente_saldo)
uv run python scripts/validacao_extrato/gera_ofx_teste.py

# 2) sobe a app com auth E extrato em SQLite temporário
#    (NUNCA toca data/auth.db nem data/extrato.db)
uv run python scripts/validacao_extrato/servidor_extb.py /tmp/extb-teste 8099

# 3) roda a validação (18 itens) e grava screenshots
uv run --with playwright python scripts/validacao_extrato/valida_extb.py \
    http://127.0.0.1:8099 /tmp/extb-teste
```

Exige o túnel SSH do ERP ativo (porta local 15432) — o cruzamento lê
`contacorrente_saldo` de verdade.

## O cenário

O OFX usa a conta Itaú 341/0098/539349 e os valores reais de julho/2026, com um
erro de R$ 3.533,69 injetado de propósito no dia 06/07:

| Dia | Esperado |
|---|---|
| 01, 02, 03/07 | **OK** — o saldo derivado de uma única âncora (LEDGERBAL de 03/07) reproduz os saldos do ERP ao centavo |
| 06/07 | **DIVERGE** com R$ 3.533,69 |

Se os três primeiros dias não baterem ao centavo, a aritmética do saldo derivado
regrediu — é o cálculo mais delicado do módulo.

## O que os 18 itens cobrem

Login e carga da tela · importação de OFX com pedido de vínculo · os 4 estados na
tela · o valor exato da divergência · origem visível na coluna Diferença · dia OK
sem resíduo · expansão da linha · prompt de vínculo **cancelado** não pode dizer
que vinculou · desfazer · reimportar idempotente · botão Atualizar · RBAC (link
visível para quem tem a tela, oculto para quem não tem, API em 403) · mobile
390×844 sem rolagem horizontal · link na gaveta · console sem erro de aplicação.

Usuários criados pelo harness: `fin@teste.local` (perfil Financeiro, tem a tela)
e `frota@teste.local` (perfil Frota, não tem). Senha `Teste@12345`.
