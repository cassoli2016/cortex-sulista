---
type: Runbook
title: Checklist de go-live (segurança)
description: Checklist obrigatório antes de expor o CÓRTEX — túnel sem porta aberta, MFA, RBAC+RLS testados, guardrail de PII, audit imutável, backup restaurado e conectores seguros.
resource: docs/SEGURANCA.md §9
tags: [runbook, go-live, seguranca, checklist]
timestamp: 2026-07-11
---

# Procedure

Nada é exposto antes de todos os itens abaixo estarem verificados:

- [ ] Túnel Cloudflare ativo, **nenhuma porta pública aberta** (confirmar com scan externo).
- [ ] **MFA imposto para 100% dos usuários.**
- [ ] RBAC + RLS testados com usuário de **cada papel** (testes negativos inclusos).
- [ ] Guardrail de PII validado (tentar vazar dado sensível para a Claude API **deve falhar**).
- [ ] `audit_log` gravando e imutável.
- [ ] Backup criptografado restaurado com sucesso em ambiente limpo.
- [ ] Segredos fora do repositório; rotação configurada.
- [ ] Conectores: credenciais no cofre, webhooks validando HMAC, dead-letter monitorada.

# Notes

- Deriva do [modelo_seguranca](../concepts/modelo_seguranca.md) (zero-trust) — cada item mapeia uma das seções §1–§8.
- "Backup que não restaura não é backup": o teste de restauração é obrigatório, não a existência do backup.
- RBAC via [papel_modulo](../tables/papel_modulo.md) + RLS por filial; auditoria em [audit_log](../tables/audit_log.md).
- Conectores: credenciais em [int_credenciais](../tables/int_credenciais.md) (só referência ao cofre), HMAC no [webhook_receiver](../apis/webhook_receiver.md), fila morta em [int_dead_letter](../tables/int_dead_letter.md).
