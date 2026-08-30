# Reconciliação — o CÓRTEX conferido contra ele mesmo

> Critério 2 do `1.0.0` (ver seção 5.1 do `CLAUDE.md`): *a divergência de cada
> número que decide dinheiro conhecida, explicada e com dono, em vez de
> descoberta na reunião.*

## O que este documento é, e o que ele não é

Ele **não julga** se um número está certo contra o mundo real — isso é
auditoria, e não é o que o painel promete. Ele responde outra pergunta, que é a
que quebra confiança no dia a dia: **o mesmo conceito dá o mesmo número em
todas as telas?**

Divergência aqui é sempre uma de duas coisas, e as duas exigem ação:

1. **bug** — duas regras para o mesmo conceito;
2. **recorte diferente de propósito** — e então a tela precisa **dizer isso**,
   senão o usuário compara dois números que nunca deveriam bater.

## Como se verifica

```bash
uv run --no-sync python scripts/conferir_numeros.py
```

Sai `0` quando não há divergência e `1` quando há. O script fala com o AVA e
leva alguns minutos.

**Ele nasceu de um defeito real:** a Visão Geral e o Fluxo Consolidado mostravam
**R$ 914 mil de diferença** para o mesmo saldo bancário — cada tela com a sua
regra, e ninguém percebeu por meses. As conferências abaixo são a varredura do
resto dessa família.

## O que é conferido

| # | Conferência | O que quebraria sem ela |
|---|---|---|
| 1 | Saldo inicial: Visão Geral × Fluxo Consolidado × Antecipação | o defeito de R$ 914 mil, de novo |
| 2 | Saldo por banco soma o total | um banco fora da soma |
| 3 | A receber em aberto: KPI × aging | o aging contando o que o KPI não conta |
| 4 | A pagar: aging × total | idem |
| 5 | Fluxo consolidado: a cascata encadeia nos 27 períodos | saldo final de um período ≠ inicial do seguinte |
| 6 | Resultado = entradas − saídas | a cascata mentindo dentro do período |
| 7 | Antecipação: documentos somam a operação | título fora da operação |
| 8 | Antecipação: resumo por sacado soma a operação | sacado fora do resumo |
| 9 | Total a antecipar × soma das operações | o KPI e a lista discordando |
| 10 | Km total = carregado + vazio | a base de todo CKM e retorno vazio |
| 11 | Km por modalidade × total | modalidade fora da soma |
| 12 | OC em aberto: faixas × KPI (contagem e valor) | faixa fora do total |
| 13 | Previsão: futura + vencida + sem data = total | entrega sem faixa |
| 14 | DRE: receita líquida = bruta − deduções | a cascata da DRE não fechando |
| 15 | DRE: lucro bruto = receita líquida + CSP | idem |
| 16 | DRE: CSP = fixo + variável + créditos | idem |
| 17 | DRE: deduções = soma dos impostos | imposto fora da dedução |
| 18 | DRE: total da linha = soma dos meses | mês fora do total |
| 19 | DRE: linha = soma dos agrupadores | agrupador fora da linha |
| 20 | **Atingimento = realizado ÷ meta** | ver "a armadilha da meta", abaixo |
| 21 | **Realizado = soma da série diária** | o cartão e o gráfico da mesma tela contando histórias diferentes |
| 22 | **Meta acumulada = soma das metas até hoje** | idem |
| 23 | **A mensagem de WhatsApp × a Visão Geral** | número saindo da empresa diferente do que a tela mostra |
| 24 | A pagar vencido: Fluxo Consolidado × aging | duas definições de "vencido" |

## As três receitas (critério 3 do `1.0.0`)

São **três recortes distintos de propósito**, e é isso que a tela precisa
dizer. Medição de **30/08/2026**:

| recorte | valor | o que é |
|---|---|---|
| Faturas emitidas no mês | R$ 11.892.660,85 | o que foi faturado, por data de **emissão** |
| Frete das viagens (CT-e) | R$ 10.998.976,10 | o frete das viagens do mês |
| Realizado da régua da meta | R$ 11.337.232,16 | CT-e + KMM + NFS-e, que é a base da meta |
| *(referência)* Receita bruta da DRE | R$ 11.359.446,61 | por **competência** |

Distâncias: faturas × DRE **4,5%**, faturas × régua da meta **4,7%**. Os quatro
ficam dentro de ~8% entre si — diferença explicável pelo recorte, não por
regra divergente.

**Cada tela diz o seu recorte no ⓘ do card.** Onde há três receitas parecidas
na mesma resposta, é obrigatório.

### A armadilha da meta

O único erro desta família que quase saiu para a diretoria: **misturar o
numerador de uma régua com o denominador de outra** deu **96% de atingimento
onde o real era 91,3%** — faltava um milhão, e a mensagem dizia que a meta
estava quase batida.

O par que fecha é `realizado_acumulado ÷ meta_acumulada`. O provedor do
WhatsApp lê o `atingimento_mes` **pronto** em vez de recalcular, e a
conferência 20 existe para garantir que ninguém volte a recalculá-lo com o
numerador errado.

## Estado em 30/08/2026

**NENHUMA DIVERGÊNCIA.** As 24 conferências passam.

Não há, hoje, divergência a adjudicar — logo não há linha esperando veredito
nem dono. **Este documento não é uma lista de pendências; é o registro de que
a conferência existe, do que ela cobre e de onde ela já falhou.** No dia em que
o script acusar algo, a divergência entra aqui com veredito (bug ou recorte) e
dono.

## Por que isto não é um documento escrito à mão

Documento sobre número que muda toda semana apodrece. O que sobrevive é o
**script rodando**; este texto explica só o que ele não consegue dizer sozinho
— por que uma diferença é aceita.

É a mesma ideia da tela `#doc`, que extrai a procedência do próprio
`index.html` em vez de manter texto paralelo.

`tests/reconciliacao/test_conferidor.py` protege as duas pontas:

- a **lógica** do comparador (divergência de um centavo já é achado; `None`
  vira achado e não passa batido);
- a **cobertura**: as conferências desta tabela têm de continuar existindo. Sem
  isso, alguém remove uma checagem e o documento passa a mentir em silêncio.

## Duas formas de falhar que já aconteceram aqui

**1. O conferidor que se cala.** Na primeira versão, o bloco da DRE lia um campo
que não existe (`valor` em vez de `total`) e **sumiu inteiro sem uma linha de
aviso**. Conferidor que se cala é pior que nenhum, porque dá a sensação de que
está tudo conferido.

**2. A conferência que passa por vacuidade.** Ao acrescentar as receitas
(30/08/2026), li os campos de `get_overview()` — que é o painel **financeiro** e
não tem nenhum deles. Todos vieram `None`, o atingimento comparou `"0,0%"` com
`"0,0%"` e o bloco ficou **verde sem medir nada**. Hoje campo ausente é
**falha**, não silêncio.

A lição vale para qualquer verificação: **teste que não pode falhar não é
teste**. Antes de confiar num verde, confirmar que ele chegaria a ficar
vermelho.
