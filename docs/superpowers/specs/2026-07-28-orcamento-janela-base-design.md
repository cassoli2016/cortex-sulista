# Design — Janela base escolhível no método sazonal (trimestre / semestre / personalizada)

> Data: 2026-07-28 · Origem: brainstorming com o usuário · Status: **aprovado**.
> Estende o método "semestre × sazonalidade" (spec 2026-07-27). O método passa a
> se chamar na UI **"Média do período × sazonalidade"**; o valor interno
> `metodo='semestre'` NÃO muda (compatibilidade com versões gravadas).

## Decisões do usuário

- Escolher **quais meses** compõem a base do orçamento (não só "últimos 6").
- Suporte a **trimestre** (3 meses) além do semestre.
- **Aprovada a mudança do Regerar**: no método sazonal, regerar passa a usar a
  **janela GRAVADA** na versão (`meses_base`), recalculando com os dados atuais
  da MESMA janela — não rola mais para "os últimos 6 do momento". Janela nova =
  versão nova. O espelho continua rolando os últimos 12 (comportamento próprio).

## 1. Regra

- Janela **contígua** de meses **fechados**: `base_de`..`base_ate` ('AAAA-MM').
- `nivel_conta = soma(valores da conta na janela) / len(janela)` —
  `derivar_semestre` JÁ divide por `len(meses_base)`; nenhuma mudança na
  derivação pura.
- Validações (violação → ValueError pt-BR → 422 no endpoint):
  - formato AAAA-MM em ambos; `base_de <= base_ate`;
  - `base_ate` ≤ último mês fechado (mês corrente/futuro → erro);
  - comprimento **entre 3 e 12** meses ("a base precisa de 3 a 12 meses");
  - mês da janela sem lançamento algum → bloqueio com a lista (regra
    `meses_faltando` existente).
- Ausentes no body → **últimos 6 meses fechados** (comportamento atual; API
  compatível).
- `meses_base` gravado = a janela → badge da grade, rótulo derivado e **meses
  circulares** do acompanhamento saem automaticamente dela (motor existente).
  Ex.: base fev–abr/26 → só fev–abr circulares; mai–jun já comparáveis hoje.
- Índices sazonais: inalterados (24 meses fechados por linha).

## 2. Regerar (mudança de comportamento)

- `gerar(versao_id=...)` com `metodo='semestre'`: a janela vem de
  `json.loads(versao.meses_base)` (a gravada), NUNCA de `meses_fechados(hoje, 6)`.
  Re-valida `meses_faltando` sobre ela (reclassificações podem ter mudado o
  histórico). `meses_base` regravado idêntico; snapshot pré-regeração e
  imutabilidade continuam como estão.
- Versão sazonal antiga sem `meses_base` (não existe em produção, mas por
  segurança): cai nos últimos 6, comportamento anterior.
- Espelho: intocado (rola os últimos 12).

## 3. API

`POST /api/controladoria/orcamento/gerar` ganha `base_de` e `base_ate`
(opcionais; só fazem sentido com `metodo='semestre'` — presentes com
`metodo='espelho'` → 422 "a janela base é do método sazonal"). Ao regerar
(`versao_id` presente), `base_de/base_ate` são IGNORADOS como o `metodo` já é.

## 4. Tela (Montagem)

- Rótulo do método no select: **"Média do período × sazonalidade"** (o value
  segue `semestre`).
- Quando o método sazonal está ativo, aparece o seletor **Base**
  (`id="fOrcBase"`): `Últimos 6 meses (semestre)` (default) ·
  `Últimos 3 meses (trimestre)` · `Personalizado…`.
- `Personalizado…` revela dois selects (`fOrcBaseDe`, `fOrcBaseAte`) com os
  **últimos 18 meses fechados** (rótulos "jul/26"…), default = últimos 6.
- O front SEMPRE envia `base_de/base_ate` calculados do preset escolhido
  (últimos 6, últimos 3 ou o range manual) — a aritmética de meses fechados já
  existe no front (`_orcRotuloBase6` usa a mesma).
- Rótulo sugerido da versão usa a faixa real: "Orçamento {ano} — base
  {fev–abr/26}" (helper existente `_orcRotuloSemestre`).
- Validação client-side leve (de > até → banner) — a API é a autoridade.
- O hint do Regerar muda para: "regerar mantém o método E a janela da versão".

## 5. Erros e casos de borda

| Situação | Comportamento |
|---|---|
| base_ate no mês corrente/futuro | 422 "a base só pode conter meses fechados" |
| janela < 3 ou > 12 meses | 422 "a base precisa de 3 a 12 meses" |
| base_de > base_ate | 422 |
| base_* com metodo espelho | 422 |
| base_* junto de versao_id (regerar) | ignorados (como o metodo) |
| mês da janela sem lançamento | bloqueio com a lista (existente) |
| janela cobrindo meses do ano orçado | viram circulares (motor existente) |

## 6. Testes

- Serviço: janela de 3 (nível = soma/3); janela personalizada gera meses_base
  correto e circulares corretos; todas as validações do §5; regerar usa a janela
  gravada (gera com fev–abr, avança o relógio, regera → mesma janela, não
  últimos 6); espelho intocado (regressão).
- Front: presets calculam as janelas certas (validação via fixture).
- Suíte atual (256) verde; estrutural.

## Critérios de aceite

1. Gerar com "Últimos 3 meses": versão com meses_base = abr–jun/26 (hoje),
   badge "base abr–jun/26", circulares = 4,5,6 — e a cascata orçado×realizado
   já compara jan–mar? NÃO: jan–mar ficam fora da base mas SÃO meses fechados
   não circulares → comparam! (verificar no acompanhamento: com base trimestral,
   jan–mar aparecem no acumulado imediatamente).
2. Personalizado fev–abr: badge e rótulo "fev–abr/26"; mai–jun comparáveis.
3. Regerar mantém a janela; espelho segue igual.
4. Validações do §5 respondem 422 com mensagens claras.
5. pytest + estrutural verdes.

## Fora do escopo

- Meses não contíguos; pesos por mês; janela no método espelho; mudar o value
  interno `metodo`.
