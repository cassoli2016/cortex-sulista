# Segurança — CÓRTEX

O portal centraliza dado financeiro e estratégico e fica exposto externamente.
Segurança não é módulo — é propriedade de todas as camadas. Modelo: **zero trust**.

## 1. Acesso externo sem expor o servidor

**Recomendado: Cloudflare Tunnel + Cloudflare Access.**
- O servidor local **não abre porta nenhuma** para a internet. O container `cloudflared`
  cria um túnel de saída até a borda da Cloudflare. Não há IP público para atacar/escanear.
- Cloudflare Access faz a autenticação na borda (SSO corporativo + MFA obrigatório) **antes**
  de a requisição chegar ao servidor. Quem não passou no Access nem toca na aplicação.
- WAF, rate limiting e proteção DDoS ficam na borda, de graça.

**Alternativa: WireGuard (VPN).** Usuários entram na rede privada antes de acessar o portal.
Mais controle, menos conveniência (exige cliente VPN). Bom para acesso só-interno + poucos externos.

> Evitar: abrir 443 direto no roteador com port-forward. É o caminho mais fácil para ser varrido
> e explorado. Se for inevitável, no mínimo reverse proxy (Caddy) + fail2ban + WAF (Coraza/ModSecurity).

## 2. Autenticação e sessão

- SSO (OIDC) como fonte de identidade; **MFA obrigatório** para todos.
- Tokens JWT de vida curta (15 min) + refresh token rotativo guardado server-side (Redis).
- Sessão revogável: logout/bloqueio invalida na hora (lista de revogação no Redis).
- Senhas (se houver login local de fallback): Argon2id, política mínima + checagem de vazamento.

## 3. Autorização — RBAC + Row-Level Security

Dois níveis, ambos obrigatórios:

**Nível 1 — Papel × Módulo** (`papel_modulo`): define quais módulos cada papel acessa e com
qual permissão (`read` / `write` / `approve`).

```
Papéis sugeridos:
  ceo            → read em todos os módulos + analytics
  controller     → read/write financeiro, analytics; read demais
  fin_analista   → read/write financeiro
  comercial      → read/write comercial; read operacional
  op_gestor      → read/write operacional, frota, suprimentos
  seg_gestor     → read/write pessoas_seg
  auditor        → read em tudo + acesso ao audit_log (sem write)
```

**Nível 2 — Row-Level Security (Postgres):** mesmo dentro de um módulo, o usuário só vê as
linhas do seu escopo (ex.: comercial de uma filial não vê clientes de outra). Implementado
com `RLS POLICY` usando o `current_setting('app.user_scope')` setado por requisição.

```sql
ALTER TABLE com_clientes ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_clientes_filial ON com_clientes
  USING (filial_id = ANY (current_setting('app.user_filiais')::int[]));
```

**O agente herda o RBAC do usuário.** O contexto do agente recebe o mesmo escopo; ele consulta
o banco com a mesma identidade. Não existe "agente admin" respondendo a usuário restrito.

## 4. Proteção do dado sensível na camada de IA

- **PII e financeiro nunca saem para a Claude API.** O gateway tem um guardrail que classifica
  o payload; se houver dado sensível, força processamento **100% local no Gemma**.
- Saídas da IA passam por filtro de vazamento (não devolver segredo/PII fora de escopo).
- RAG: o vetor store também respeita escopo — documentos têm tags de módulo/filial e só são
  recuperados se o usuário tem permissão.
- Prompt injection: conteúdo vindo de dados (e-mails, descrições) é tratado como **não confiável**;
  instruções embutidas em dados não viram comandos. Separação clara entre "instrução do sistema"
  e "conteúdo a analisar".

## 5. Auditoria e rastreabilidade

- `audit_log` imutável (append-only) registra: quem, o quê, quando, de onde (IP/device),
  resultado, e — para respostas de IA — a query/fonte que originou cada número.
- Toda **escrita** exige confirmação humana explícita e fica logada.
- Logs centralizados (Loki), retenção mínima e alertas de anomalia (acesso fora de horário,
  volume atípico de leitura, tentativa de acesso fora de escopo).

## 6. Dados em trânsito e em repouso

- TLS 1.3 ponta a ponta (borda → app → banco).
- Postgres com criptografia em repouso (disco) + colunas sensíveis cifradas a nível de app
  quando aplicável (ex.: dados bancários).
- Segredos em cofre (Vault / Doppler / SOPS); `.env` **nunca** versionado — só `.env.example`.
- Backups criptografados, testados periodicamente (backup que não restaura não é backup).

## 7. LGPD

- Mapeamento do dado pessoal (motoristas, contatos de cliente) e base legal de cada uso.
- Minimização: só coleta/exibe o necessário; anonimização em relatórios agregados.
- Direitos do titular: trilha para acesso/correção/eliminação.
- IA **local** como controle-chave: dado pessoal não trafega para terceiros por padrão.

## 7.1 Credenciais de terceiros e webhooks (Central de Integrações)

- Credenciais de fornecedor **nunca** no banco ou código — apenas **referência ao cofre**
  (Vault/SOPS) em `int_credenciais`. Escopo mínimo, rotação e expiração rastreadas.
- Cada conector tem credencial isolada; comprometer um fornecedor não expõe os demais.
- **Webhooks**: validação obrigatória de assinatura **HMAC** (comparação constante, anti-timing)
  antes de qualquer processamento. Payload de webhook é dado NÃO confiável — nunca vira instrução
  (proteção contra injeção).
- Todo evento entra com `chave_idem` única (idempotência) e fica em `int_raw_events` (trilha).
  Falha persistente vai para `int_dead_letter` — nada se perde silenciosamente.
- Tráfego com fornecedores logado (`int_webhook_log`) e monitorado (latência, circuit breaker).

## 8. Hardening operacional

- Imagens Docker mínimas, sem root, escaneadas (Trivy) no CI.
- Dependências com `pip-audit` / `npm audit` no pipeline; merge bloqueado com CVE crítico.
- Princípio do menor privilégio em TODA credencial. O usuário Postgres da aplicação tem
  acesso só ao necessário; RLS + GRANTs por schema/módulo. Telemetria (hypertables) com
  role separada de ingestão (insert-only) distinta da role de leitura analítica.
- Atualizações de segurança automatizadas no host; firewall local (ufw) negando tudo menos o túnel.
- Plano de resposta a incidente documentado e ensaiado.

## 9. Checklist de go-live

- [ ] Túnel Cloudflare ativo, nenhuma porta pública aberta (confirmar com scan externo).
- [ ] MFA imposto para 100% dos usuários.
- [ ] RBAC + RLS testados com usuário de cada papel (testes negativos inclusos).
- [ ] Guardrail de PII validado (tentar vazar dado sensível para Claude API deve falhar).
- [ ] audit_log gravando e imutável.
- [ ] Backup criptografado restaurado com sucesso em ambiente limpo.
- [ ] Segredos fora do repositório; rotação configurada.
- [ ] Conectores: credenciais no cofre, webhooks validando HMAC, dead-letter monitorada.
