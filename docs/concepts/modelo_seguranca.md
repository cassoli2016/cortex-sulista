---
type: Concept
title: Modelo de segurança (zero-trust)
description: Modelo zero-trust do CÓRTEX — acesso externo sem porta aberta, RBAC + RLS, guardrail de PII na IA, auditoria imutável, LGPD e credenciais de terceiros por cofre.
resource: docs/SEGURANCA.md
tags: [seguranca, zero-trust, rbac, rls, pii, lgpd, hmac]
timestamp: 2026-07-11
---

# Definition

Segurança não é módulo — é propriedade de todas as camadas. Modelo: **zero trust**.

## 1. Acesso externo sem expor o servidor
- **Recomendado:** Cloudflare Tunnel + Cloudflare Access. O servidor **não abre porta nenhuma**; `cloudflared` cria túnel de saída até a borda. Access autentica na borda (SSO corporativo + **MFA obrigatório**) antes de a requisição chegar à app. WAF, rate limiting e DDoS na borda. Ver [cloudflare_edge](../services/cloudflare_edge.md).
- **Alternativa:** WireGuard (VPN) para acesso só-interno + poucos externos.
- **Evitar:** abrir 443 direto com port-forward.

## 2. Autenticação e sessão
- SSO (OIDC) como fonte de identidade; **MFA obrigatório** para todos.
- JWT de vida curta (**15 min**) + refresh token rotativo guardado server-side (Redis).
- Sessão revogável na hora (lista de revogação no Redis).
- Login local de fallback (se houver): Argon2id + checagem de vazamento.

## 3. Autorização — RBAC + Row-Level Security (dois níveis, ambos obrigatórios)
- **Nível 1 — Papel × Módulo** ([papel_modulo](../tables/papel_modulo.md)): `read` / `write` / `approve` por módulo. Papéis: `ceo`, `controller`, `fin_analista`, `comercial`, `op_gestor`, `seg_gestor`, `auditor`.
- **Nível 2 — RLS (Postgres):** o usuário só vê as linhas do seu escopo via `RLS POLICY` usando `current_setting('app.user_filiais')`.

```sql
ALTER TABLE com_clientes ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_clientes_filial ON com_clientes
  USING (filial_id = ANY (current_setting('app.user_filiais')::int[]));
```

- **O agente herda o RBAC do usuário** — mesmo escopo, mesma identidade. Não existe "agente admin".

## 4. Proteção do dado sensível na camada de IA
- **PII e financeiro nunca saem para a Claude API.** O [gemma_gateway](../services/gemma_gateway.md) classifica o payload; se houver dado sensível, força processamento **100% local no Gemma**.
- Saídas da IA passam por filtro de vazamento; RAG respeita escopo (tags de módulo/filial em [kb_documentos](../tables/kb_documentos.md)).
- Prompt injection: conteúdo vindo de dados é **não confiável** — instrução ≠ conteúdo a analisar.

## 5. Auditoria e rastreabilidade
- [audit_log](../tables/audit_log.md) imutável (append-only): quem, o quê, quando, de onde, resultado — e a query/fonte de cada número de IA.
- Toda **escrita** exige confirmação humana explícita e fica logada.
- Logs centralizados (Loki), alertas de anomalia — ver [observabilidade](../services/observabilidade.md).

## 6. Dados em trânsito e repouso
- TLS 1.3 ponta a ponta; Postgres cifrado em repouso + colunas sensíveis cifradas no app.
- Segredos em cofre (Vault / Doppler / SOPS); `.env` **nunca** versionado (só `.env.example`).
- Backups criptografados e testados.

## 7. LGPD
- Mapeamento de dado pessoal (motoristas, contatos), minimização e anonimização em agregados.
- Direitos do titular (acesso/correção/eliminação); IA **local** como controle-chave.

## 7.1 Credenciais de terceiros e webhooks
- Credencial de fornecedor **nunca** no banco/código — só **referência ao cofre** em [int_credenciais](../tables/int_credenciais.md). Escopo mínimo, rotação e expiração rastreadas; credencial isolada por conector.
- **Webhooks:** validação obrigatória de assinatura **HMAC** (comparação constante) antes de processar — ver [webhook_receiver](../apis/webhook_receiver.md). Payload é dado não confiável.
- Idempotência (`chave_idem`) em [int_raw_events](../tables/int_raw_events.md); falha persistente → [int_dead_letter](../tables/int_dead_letter.md).

## 8. Hardening operacional
- Imagens Docker mínimas, sem root, escaneadas (Trivy) no CI; `pip-audit`/`npm audit`, merge bloqueado com CVE crítico.
- Menor privilégio em toda credencial; role de ingestão de telemetria (insert-only) separada da role de leitura analítica.
- Firewall local (ufw) negando tudo menos o túnel; plano de resposta a incidente ensaiado.

# Notes

- As 5 regras que nenhum agente viola estão em `CLAUDE.md §8`.
- O checklist de go-live derivado deste modelo está em [go_live](../runbooks/go_live.md).
- O flag `ia.rotear_pii_para_externo: false` vive em [parametros_negocio](parametros_negocio.md) e nunca deve virar `true` sem revisão de segurança.
