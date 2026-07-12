---
type: Service
title: Borda / Acesso (Cloudflare Tunnel + Access)
description: Camada de borda zero-trust — acesso externo sem porta aberta, com SSO + MFA e WAF.
resource: docs/ARQUITETURA.md §2
tags: [seguranca, borda, cloudflare, zero-trust, servico]
timestamp: 2026-07-11
---

# Definition

**Cloudflare Tunnel + Access** na borda:
- Acesso externo **sem porta aberta** (tunnel).
- **SSO + MFA** (Access) e **WAF**.

# Notes

- Modelo zero-trust — detalhes em `docs/SEGURANCA.md`.
- No compose local o serviço é `cloudflared`.
