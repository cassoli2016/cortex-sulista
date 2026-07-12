# Central de Integrações — CÓRTEX

Subsistema que conecta o CÓRTEX a APIs de fornecedores externos e normaliza tudo para um
**modelo canônico único**. Projetado como **arquitetura de plugins**: o núcleo é estável;
adicionar um fornecedor novo = implementar uma interface + registrar. Zero alteração no core.

> Princípio: *open for extension, closed for modification*. A demanda cresce adicionando
> conectores, nunca reescrevendo o miolo.

---

## 1. Por que existe

Uma transportadora fala com dezenas de APIs: telemetria (Ruptela, Sascar, Cobli, Omnilink,
Autotrac, Samsara...), cartões de combustível/pedágio (Ticket Log, Sem Parar, ConectCar...),
fiscal (SEFAZ CT-e/NF-e/MDF-e), bancos (Open Finance), mapas/roteirização (Google, Maplink,
Qualp), seguradoras, gestão de risco (Buonny...). A Central traz tudo para um lugar só,
no mesmo formato, com a mesma governança de credenciais e a mesma observabilidade.

---

## 2. Arquitetura

```
  Fornecedor A ──┐  (pull: polling incremental)
  Fornecedor B ──┤   (push: webhook assinado)
  Fornecedor C ──┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ CONNECTOR (1 por fornecedor) implementa a interface Connector │
│   authenticate · fetch(cursor) · handle_webhook · normalize · │
│   health_check                                                │
└───────────────┬─────────────────────────────────────────────┘
                │ emite EVENTO CANÔNICO
                ▼
┌─────────────────────────────────────────────────────────────┐
│ EVENT BUS (Redis Streams)  → persiste bruto em int_raw_events │
│ resiliência: retry backoff · circuit breaker · idempotência · │
│ rate limit por conector · dead-letter queue                   │
└───────────────┬─────────────────────────────────────────────┘
                │ NORMALIZER mapeia → modelo canônico
                ▼
┌─────────────────────────────────────────────────────────────┐
│ PostgreSQL (verdade única) — alimenta os módulos:             │
│ tel_sinais · tc_posicoes · ts_eventos · fin_* · op_* ...      │
└─────────────────────────────────────────────────────────────┘
```

Worker dedicado (`integrations-worker`) roda o scheduler de polling e consome o event bus.
Webhooks chegam por um endpoint da API e são validados (assinatura HMAC) antes de entrar no bus.

---

## 3. Interface do conector (o contrato de extensão)

Todo conector implementa esta interface. É só isto que um fornecedor novo precisa.

```python
from typing import Protocol, Iterable
from dataclasses import dataclass
from datetime import datetime

@dataclass
class CanonicalEvent:
    tipo: str            # 'posicao'|'telemetria'|'seguranca'|'abastecimento'|
                         # 'pedagio'|'doc_fiscal'|'titulo_financeiro'
    fonte: str           # nome do conector
    chave_idem: str      # chave de idempotência (evita duplicar)
    ocorrido_em: datetime
    payload: dict        # já no formato canônico do tipo

class Connector(Protocol):
    name: str                       # identificador único, ex.: "ruptela"
    capabilities: list[str]         # tipos de evento que produz
    mode: str                       # 'pull' | 'push' | 'both'

    def authenticate(self) -> None: ...
    def fetch(self, cursor: str | None) -> tuple[Iterable[CanonicalEvent], str]:
        """Pull incremental. Retorna eventos + novo cursor."""
    def handle_webhook(self, headers: dict, body: bytes) -> Iterable[CanonicalEvent]:
        """Push. Valida assinatura e converte payload em eventos canônicos."""
    def normalize(self, raw: dict) -> CanonicalEvent:
        """Mapeia o schema do fornecedor para o canônico."""
    def health_check(self) -> dict:
        """Status do conector (auth ok, latência, última sync)."""
```

### Base class com resiliência embutida
```python
import hmac, hashlib, time

class BaseConnector:
    name: str = "base"
    capabilities: list[str] = []
    mode: str = "pull"
    rate_limit_rps: float = 5.0
    max_retries: int = 5

    def _retry(self, fn, *a, **kw):
        delay = 1.0
        for tentativa in range(self.max_retries):
            try:
                return fn(*a, **kw)
            except TransientError:
                if tentativa == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60)   # backoff exponencial com teto

    def verify_hmac(self, secret: str, body: bytes, assinatura: str) -> bool:
        calc = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc, assinatura)   # contra timing attack
```

---

## 4. Registry (descoberta de conectores)

Conectores se auto-registram. O core não conhece os fornecedores — só a interface.

```python
_REGISTRY: dict[str, type] = {}

def register(cls):                     # decorator
    _REGISTRY[cls.name] = cls
    return cls

def get_connector(name: str):
    return _REGISTRY[name]()

# Exemplo: um fornecedor novo é só isto + register
@register
class RuptelaConnector(BaseConnector):
    name = "ruptela"
    capabilities = ["telemetria", "posicao"]
    mode = "pull"
    # implementa fetch/normalize/...
```

Adicionar fornecedor = novo arquivo em `integrations/connectors/<nome>.py` com `@register`.
Nada mais no core muda. É isso que mantém o sistema "sempre pronto para a próxima demanda".

---

## 5. Modelo de dados (PostgreSQL)

```sql
int_conectores    (id, name, mode, capabilities[], ativo, criado_em)
int_credenciais   (id, conector_id, ref_cofre, escopo, expira_em)   -- só REFERÊNCIA ao cofre
int_sync_state    (conector_id, capability, cursor, ultima_sync, status)
int_raw_events    (id, conector, chave_idem UNIQUE, tipo, recebido_em, payload jsonb)
int_dead_letter   (id, conector, erro, tentativas, payload jsonb, criado_em)
int_webhook_log   (id, conector, assinatura_valida bool, recebido_em, status)
```

`chave_idem UNIQUE` garante **idempotência**: reenvio do mesmo evento não duplica.
`int_raw_events` é a trilha bruta (auditoria + reprocessamento). O normalizer lê daqui e grava
nos módulos. `int_sync_state` guarda o cursor para pull incremental por capacidade.

---

## 6. Resiliência (regras do hub)

- **Retry** com backoff exponencial + teto; só para erros transitórios.
- **Circuit breaker** por conector: após N falhas seguidas, abre e para de tentar por um tempo
  (não derruba o resto do hub por causa de um fornecedor fora do ar).
- **Rate limit** por conector (respeitar o limite do fornecedor; configurável em parametros.yaml).
- **Idempotência** via `chave_idem`.
- **Dead-letter queue**: evento que falha além do limite vai para `int_dead_letter` para análise
  e reprocessamento manual — nunca se perde silenciosamente.
- **Backpressure**: event bus (Redis Streams) desacopla ingestão de processamento.

---

## 7. Segurança (ver também docs/SEGURANCA.md)

- Credenciais de fornecedor **nunca** no banco/código — só **referência ao cofre**
  (Vault/SOPS). Escopo mínimo, rotação, expiração rastreada em `int_credenciais`.
- Webhook: validação obrigatória de **assinatura HMAC**; payload não confiável é tratado como
  dado (nunca como instrução — proteção contra injeção).
- Conector roda com menor privilégio; falha de um não acessa dado de outro.
- Todo tráfego de/para fornecedor logado em `int_webhook_log` / observabilidade.

---

## 8. Como adicionar um conector novo (checklist)

1. Criar `integrations/connectors/<fornecedor>.py` com classe `@register` herdando `BaseConnector`.
2. Implementar `authenticate`, `fetch`/`handle_webhook`, `normalize`, `health_check`.
3. Mapear o payload do fornecedor para o(s) `CanonicalEvent` correto(s).
4. Adicionar credencial no cofre + linha em `int_credenciais` (referência).
5. Registrar rate limit e modo em `config/parametros.yaml`.
6. Pronto — o scheduler/webhook receiver passam a operar o conector automaticamente.

Detalhe operacional e exemplos: skill `connector-builder`.
