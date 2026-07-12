---
name: connector-builder
description: Guia para criar um novo conector de fornecedor na Central de Integrações, seguindo a interface padrão (authenticate, fetch, handle_webhook, normalize, health_check) com resiliência e idempotência. Use sempre que for integrar uma API externa nova (telemetria, combustível, pedágio, fiscal, banco, mapas).
---

# Skill: Construção de Conector (Central de Integrações)

Adicionar um fornecedor é implementar uma interface e registrar. O core não muda.
Arquitetura completa: docs/INTEGRACOES.md.

## Passo a passo

1. Crie `integrations/connectors/<fornecedor>.py`.
2. Herde de `BaseConnector`, defina `name`, `capabilities`, `mode`, `rate_limit_rps`.
3. Implemente os métodos e o `normalize` (mapeia payload → CanonicalEvent).
4. Decore com `@register`.
5. Credencial no cofre + linha em `int_credenciais`; rate limit em parametros.yaml.

## Modelo de conector PULL (polling incremental)

```python
from integrations.base import BaseConnector, CanonicalEvent, register
from datetime import datetime

@register
class ExemploTelemetriaConnector(BaseConnector):
    name = "exemplo_telemetria"
    capabilities = ["telemetria", "posicao"]
    mode = "pull"
    rate_limit_rps = 5.0

    def authenticate(self):
        self.token = self._retry(self._login)   # _login chama a API do fornecedor

    def fetch(self, cursor):
        # cursor = timestamp/ID da última sync. Pull incremental.
        raw_list, novo_cursor = self._retry(self._get_since, cursor)
        eventos = [self.normalize(r) for r in raw_list]
        return eventos, novo_cursor

    def normalize(self, raw):
        return CanonicalEvent(
            tipo="telemetria",
            fonte=self.name,
            chave_idem=f"{self.name}:{raw['device']}:{raw['ts']}",  # idempotência
            ocorrido_em=datetime.fromisoformat(raw["ts"]),
            payload={                       # já no formato canônico de 'telemetria'
                "veiculo_ref": raw["device"],
                "km_l": raw.get("fuel_eff"),
                "rpm": raw.get("rpm"),
                "velocidade": raw.get("speed"),
                "eco_ativo": raw.get("eco", False),
            },
        )

    def health_check(self):
        return {"conector": self.name, "auth": bool(getattr(self, "token", None))}
```

## Modelo de conector PUSH (webhook)

```python
@register
class ExemploWebhookConnector(BaseConnector):
    name = "exemplo_pedagio"
    capabilities = ["pedagio"]
    mode = "push"

    def handle_webhook(self, headers, body):
        secret = self._cred("webhook_secret")          # vem do cofre
        if not self.verify_hmac(secret, body, headers.get("X-Signature", "")):
            raise SecurityError("assinatura de webhook inválida")
        import json
        data = json.loads(body)
        return [self.normalize(item) for item in data["transacoes"]]

    def normalize(self, raw):
        return CanonicalEvent(
            tipo="pedagio", fonte=self.name,
            chave_idem=f"{self.name}:{raw['id']}",
            ocorrido_em=datetime.fromisoformat(raw["data"]),
            payload={"veiculo_ref": raw["placa"], "valor": raw["valor"],
                     "praca": raw["praca"]},
        )
```

## Mapa de tipos canônicos → destino no Postgres

| tipo canônico | vai para | módulo |
|---|---|---|
| `posicao` | tc_posicoes | torre_controle |
| `telemetria` | tel_sinais | telemetria |
| `seguranca` | ts_eventos | torre_seguranca |
| `abastecimento` | fin_lancamentos + op (custo combustível) | financeiro/operacional |
| `pedagio` | fin_lancamentos (custo) | financeiro/operacional |
| `doc_fiscal` | op_cargas / com_fretes (CT-e, NF-e, MDF-e) | operacional/comercial |
| `titulo_financeiro` | fin_titulos (Open Finance) | financeiro |

## Regras inegociáveis
- `chave_idem` sempre presente e estável → idempotência.
- Credencial só por referência ao cofre; nunca hardcode.
- Webhook sempre valida HMAC antes de processar.
- Erro transitório → retry com backoff; estourou → dead-letter, nunca perde evento.
- Conector novo NÃO altera o core — só adiciona arquivo + register.

## Resolução de referências
`veiculo_ref`/`placa` do fornecedor é resolvido para `fro_veiculos.id` no normalizer/loader
(tabela de-para por conector). Mesma lógica para motorista e cliente.
