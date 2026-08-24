# E-mail — Rotina bancária no AVA (para o analista financeiro)

> Rascunho para envio. Números apurados direto no banco do AVA em 21/08/2026.
> Caminhos de menu conferidos na própria tela do Avacorp.

---

**Assunto:** Rotina bancária no AVA — o que precisa ficar em dia para o painel refletir a realidade

**Para:** Analista Financeiro
**Cópia:** Contabilidade

---

Bom dia,

Colocamos no ar no CÓRTEX as telas de caixa, extrato e lançamentos bancários. Elas leem
**direto do AVA** — não digitamos nada por fora. Então tudo que estiver em dia no ERP
aparece no painel automaticamente, e o que não estiver simplesmente não aparece.

Levantei o que hoje está incompleto e queria alinhar com você a rotina para manter isso
atualizado. Nada aqui depende de projeto novo ou da Praxio: são telas que já existem no
AVA e que dão pra tocar no dia a dia.

## Onde estamos hoje

- **O extrato do banco só está sendo importado em 1 das 19 contas ativas** (Bradesco
  ag. 36455 / c/c 1239066). Contas com movimento pesado estão sem nenhum extrato
  importado — Itaú 539349 (21.347 lançamentos em 12 meses), Santander 130000265 (8.361),
  Caixa 5405 (4.107), e-Frete (3.494), SB Cash (1.223) e Sicredi 075455 (119).
- **A conciliação está parada desde 2023.** Foram 1.604 lançamentos conciliados em 2023
  e nenhum em 2024, 2025 ou 2026. Hoje são 27.470 pendentes, o mais antigo de 18/05/2023.
- **O balanço patrimonial está fechado até dezembro/2025**, 8 meses atrás.
- **O CNPJ/CPF do lançamento bancário vem preenchido em 49 de 93.204 lançamentos** (0,05%).

Sem isso, o painel mostra o que a Sulista **lançou**, mas não consegue confirmar contra o
que o banco **registrou** — que é o que dá confiança para usar o número numa decisão.

## A rotina que precisamos

### Diária (ou no mínimo semanal)

**1. Importar o extrato de cada conta.**
Menu → Financeiro → Contas Correntes → **Contas Bancárias** → selecionar a conta →
ação **"Importar Extrato"** (painel da direita).
Começando pelas 6 contas que entram no fluxo de caixa: Itaú 539349, Santander 130000265,
Caixa 5405, e-Frete, SB Cash 761043073 e Sicredi 075455. O Bradesco 1239066 já vem sendo
importado — vale manter.

**2. Conciliar o que foi importado.**
Menu → Financeiro → Contas Correntes → **Extrato Bancário - Conciliação** (ou
**Conciliação Múltipla**, quando for casar vários lançamentos de uma vez).
O filtro "Situação" abre em *Pendente*, que é justamente a fila do que falta.

> Sobre os 27.470 pendentes acumulados: não faz sentido você limpar isso sozinho de uma
> vez. Sugiro definirmos uma **data de corte** — conciliar dali pra frente na rotina, e
> tratarmos o anterior como histórico ou num mutirão à parte. Me diga o que acha viável.

### Mensal

**3. Fechamento contábil** (junto com a Contabilidade), hoje parado em dezembro/2025. É o
que alimenta o Balanço Patrimonial no painel — ativo, passivo, patrimônio líquido e
liquidez.

**4. Revisar o cadastro de contas.** Três contas ativas estão sem movimento há mais de 12
meses e podem ser inativadas: Caixa 33227 / 20021, BIC 160 / 141022276 e BIC 160 / 421022284.

### No dia a dia do lançamento

**5. Preencher o CNPJ/CPF do cliente ou fornecedor no lançamento** sempre que a origem for
identificável. É esse campo que permite responder direto "quanto recebemos deste cliente"
ou "quanto pagamos a este fornecedor". Hoje, sem ele, a busca no painel só funciona pelo
texto do histórico — o que pega boleto e TED (costumam trazer o nome), mas não pega PIX
nem tarifa.

## Dois pontos que preciso confirmar com você

- **PAMCARD**: tem 16.379 lançamentos em 12 meses, o 3º maior volume da empresa, mas está
  marcada no cadastro para **não entrar** no fluxo de caixa. Isso é proposital? Se não for,
  a projeção de caixa está sem uma saída relevante.
- **Contas operacionais** (e-Frete, REPOM, vale-pedágio): quer que apareçam junto das
  contas bancárias no painel, ou separadas?

## O que cada rotina destrava no painel

| Rotina | O que passa a funcionar no CÓRTEX |
|---|---|
| Importar extrato | Conferência do saldo e do movimento de cada conta contra o banco |
| Conciliar | Saldo bancário confiável; diferença aparece na hora, não no fechamento |
| Fechamento mensal | Balanço Patrimonial atualizado (hoje 8 meses defasado) |
| CNPJ/CPF no lançamento | Busca por cliente/fornecedor direto no extrato |

Se quiser, sento com você 30 minutos para passarmos junto pelas telas e ajustarmos o que
faz sentido na sua rotina — pode ser que alguma dessas etapas já tenha um jeito melhor de
ser feita do que o que estou propondo aqui.

Qualquer dúvida, é só chamar.

Abraço,
Cristian
