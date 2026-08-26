# CT-e de contrapartida do agregado — definições pendentes

**Para:** Contabilidade
**De:** Controladoria / CÓRTEX
**Data:** 26/08/2026 · **atualizado com as respostas recebidas**

---

## 0. Situação das respostas

| # | Pergunta | Resposta |
|---|---|---|
| 0 | Há dispensa de emissão pelo subcontratado? | **Não há — o agregado emite** |
| 1 | Subcontratação, redespacho ou prestação normal? | **Subcontratação** |
| 2 | Valor cobrado do cliente ou pago ao agregado? | **Pago ao agregado** ⚠️ ver 3.2 |
| 3 | Um documento por CT-e ou por viagem? | **Um por CT-e** |
| 4 | Tratamento e CST do ICMS | *aguardando* |
| 5 | Série e numeração por agregado | **Série 900 aprovada** (provisória) |
| 6 | Os 17 com IE "ISENTO" emitem? | em análise |
| 7 | Documentos de valor simbólico entram? | **Não, por ora** |
| 8 | Passivo de R$ 108,7 mi | encaminhado ao Jurídico |

⚠️ **A resposta 2 trouxe duas perguntas novas — seção 3.2.** "O valor pago a
ele (frete mínimo)" pode significar duas coisas que **divergem em 89% das
viagens**, e a escolha por "valor pago" reabre a necessidade de um critério de
rateio para metade da fila.

Também segue pendente a **CST e o tratamento do ICMS** (seção 3.4), e o
levantamento cadastral dos **17 sem inscrição estadual**, que responde por 29%
da fila (seção 4.1).

O anexo, no fim, registra o que foi testado até chegar ao enquadramento
definido.

---

## 1. Do que se trata

Quando a Sulista emite um CT-e usando o veículo de um **agregado pessoa
jurídica**, existe — ou deveria existir — um CT-e emitido **pelo agregado
contra a Sulista**, referente à prestação que ele nos vendeu.

Hoje **nenhum é emitido**. Não é um problema de sistema: o cadastro está
completo e a parte técnica está pronta e testada. O que falta são definições
fiscais, que não cabe ao sistema arbitrar.

Este documento lista o que precisamos que a contabilidade defina, na ordem em
que as respostas destravam o trabalho.

---

## 2. Dispensa de emissão — RESPONDIDO: não há

Foi verificado se, na subcontratação, o subcontratado estaria dispensado de
emitir o CT-e, ficando a prestação amparada pelo documento do subcontratante.

**Não é o caso: o agregado emite.** A fila de cerca de 3.100 documentos por mês
é obrigação real, e o trabalho é de emissão.

---

## 3. Definições necessárias

### 3.1 Enquadramento da operação — RESPONDIDO: subcontratação

Define o CFOP e a natureza da operação declarada no documento. Os testes na
SEFAZ confirmaram que é a única classificação compatível com a operação real
(seção 2-A).

*Precedente interno que sustenta a definição:* a própria Sulista, quando é **ela** a contratada
por outra transportadora, emite esses documentos com **CFOP 6351 — prestação
de serviço de transporte para execução de serviço da mesma natureza**,
classificados como subcontratação, com a transportadora contratante como
tomadora. O documento do agregado contra nós é o espelho exato desse caso.
Registramos isso como precedente interno, não como opinião fiscal.

### 3.2 Valor da prestação — RESPONDIDO: valor pago ao agregado

**Resposta recebida:** *"O valor pago a ele (frete mínimo)."*

Registramos a definição. Ela levanta **duas questões** que precisam de retorno
antes da emissão em produção.

#### Questão A — "frete mínimo" é qual dos dois números?

O parêntese admite duas leituras, e elas **não coincidem**:

1. **O valor efetivamente pago** ao agregado (`frete de compra` no sistema); ou
2. **O piso mínimo legal da ANTT** (Lei 13.703/2018), que o CÓRTEX já calcula
   por viagem.

Medimos os dois no trimestre, nas viagens de agregado:

| | Valor |
|---|---|
| Pago aos agregados | **R$ 14,7 milhões** |
| Piso mínimo ANTT das mesmas viagens | **R$ 18,7 milhões** |
| Pago em relação ao piso | **78,6%** |
| Viagens pagas **abaixo** do piso | **5.081 de 5.735 conferidas (89%)** |

Ou seja: **o que é pago não é o frete mínimo** na grande maioria dos casos — é
menos. Os dois nomes não descrevem o mesmo número.

A escolha tem consequência direta:

- **Se for o valor efetivamente pago:** os documentos passarão a registrar
  formalmente, um a um, um frete abaixo do mínimo legal — em 89% das viagens.
  É um registro auditável de algo que hoje só existe no financeiro interno.
- **Se for o piso da ANTT:** o valor do documento não baterá com o que o
  financeiro efetivamente pagou (R$ 18,7 mi contra R$ 14,7 mi), e essa
  diferença precisará de tratamento.

**Não escolhemos por conta própria.** Pedimos que a contabilidade indique qual
dos dois, ciente da divergência.

#### Questão B — critério de rateio: RESPONDIDO, proporcional ao valor cobrado

**Definido em 26/08/2026.** Como o pagamento é lançado **por viagem** e o
documento é **por CT-e**, os **3.159 de 6.594 CT-e (48%)** que dividem viagem
precisavam de um critério. Ficou: **cada documento recebe a mesma fatia que
teve no valor cobrado dos clientes naquela viagem**.

Exemplo real já emitido em teste: viagem com **8 documentos** e R$ 1.591,50
pagos ao agregado. O CT-e em questão respondeu por R$ 189,48 dos R$ 6.540,32
cobrados na viagem — 2,90% — e saiu com **R$ 46,11**. Autorizado pela SEFAZ.

Registramos duas observações:

- **Os outros critérios não foram implementados**, de propósito. Todos os
  quatro fecham a soma, então nenhum "erra" numa conferência — o que muda é
  quanto imposto cada documento carrega. Num caso de 3 CT-e numa viagem de
  R$ 3.398,36, o mesmo documento valeria R$ 201,70 por peso e R$ 1.132,79 em
  partes iguais: **5,6 vezes**. Trocar o critério tem de ser decisão, não
  conveniência.
- **O arredondamento é por documento.** A soma das fatias pode diferir do
  valor da viagem em alguns centavos, porque cada CT-e é um documento
  independente e não um lote que precise fechar.

Casos em que o sistema ainda **para**: viagem com prestação total zero (não há
como calcular proporção) e CT-e com prestação zero dentro de uma viagem com
outros (receberia R$ 0,00, e documento fiscal de valor zero não é prestação).

### 3.3 Um documento por CT-e nosso, ou por viagem? — RESPONDIDO: por CT-e

No trimestre, **6.594 CT-e** de agregado PJ corresponderam a **3.834 viagens**
— 1,7 documento por viagem. Com a decisão "um por CT-e", a fila fica no número
maior: **os 6.594**.

É a combinação desta decisão com a da seção 3.2 (valor pago ao agregado) que
cria a necessidade do critério de rateio — ver Questão B.

### 3.3-B Achado novo: o CFOP não é um só — e o principal é o 6932

Com a subcontratação definida, testamos a emissão em trechos reais e a SEFAZ
recusou um deles: **"524 — CFOP inválido, informar 5932 ou 6932"**.

O motivo é uma característica desta operação que não aparece nos nossos
próprios CT-e: **o agregado é inscrito em um estado e roda em todos**. Quando a
viagem **começa fora do estado onde o agregado é inscrito**, o CFOP passa
obrigatoriamente para a família 932.

Nos documentos da Sulista isso nunca ocorre, porque a filial que emite é sempre
a da origem da carga. Com o agregado como emitente, passa a ser **a maioria**:

| Situação | CFOP | Documentos no trimestre |
|---|---|---|
| Começa **fora** da UF do agregado, cruzando divisa | **6932** | **3.694 (58%)** |
| Começa na UF do agregado, cruzando divisa | 6351 | 1.931 (30%) |
| Começa e termina na UF do agregado | 5351 | 724 (11%) |
| Começa fora da UF do agregado, sem cruzar divisa | 5932 | 17 (0,3%) |

O sistema já aplica a regra automaticamente, e os dois casos principais foram
autorizados pela SEFAZ em homologação. **Registramos para conhecimento e
confirmação** — não é uma pergunta em aberto, é a regra do próprio órgão, mas
tem efeito na escrituração e convém que a contabilidade esteja ciente.

### 3.4 Tratamento do ICMS

**Qual o tratamento e a CST aplicáveis**, considerando que boa parte dos
agregados é optante do Simples Nacional?

No cadastro, **94 das 203 placas** de agregado PJ pertencem a proprietários
marcados como optantes. O piloto foi emitido como optante do Simples, mas o
ambiente de teste **não valida acerto fiscal** — ele aceitou o documento, não
o enquadramento.

### 3.5 Série e numeração — nossa sugestão

Foi-nos pedido que sugeríssemos. Propomos:

> **Série 900, exclusiva, numeração começando em 1 para cada agregado.**

Razões:

- **Elimina o risco de duplicidade.** Se um agregado já emite CT-e por conta
  própria — pelo contador dele, por outro sistema — estará usando série 1 ou
  outra baixa. Número repetido dentro da mesma série é rejeitado pela SEFAZ, e
  o erro apareceria documento a documento, no meio de um lote de milhares.
  Uma série alta e reservada afasta a colisão de vez, sem depender de
  levantar, agregado a agregado, o que cada um já usou.
- **Torna a origem auditável.** Olhando a série se sabe, sem consultar
  ninguém, que aquele documento foi emitido pela Sulista em nome do agregado —
  e não pelo próprio agregado. Isso importa numa fiscalização e importa na
  conciliação.
- **A numeração é por agregado**, e não uma sequência única: cada emitente tem
  a sua, e o sistema já controla isso separadamente, inclusive mantendo as
  numerações de teste e de produção apartadas.

**Aprovada em 26/08/2026**, em caráter provisório para os testes. Já em uso: o
primeiro documento da série 900 foi autorizado pela SEFAZ em homologação.

Fica pendente apenas confirmar, antes da produção, se **há exigência de série
específica** em algum contrato ou regime especial.

---

## 4. Cadastro e escopo

### 4.1 Inscrição estadual "ISENTO" — passou a ser o caminho crítico

**Este item saiu do rodapé.** Com as definições fiscais praticamente fechadas,
ele é hoje **o maior bloqueio da fila** — e não é fiscal, é cadastral.

Levantamos a prontidão de tudo o que a emissão exige, nos agregados com
movimento no trimestre:

| Verificação | Resultado |
|---|---|
| RNTRC cadastrado | **47 de 47** — nenhum pendente |
| CEP cadastrado | **47 de 47** — nenhum pendente |
| Notas fiscais com chave (últimos 30 dias) | **2.372 de 2.372** — nenhum pendente |
| **Inscrição estadual válida** | **30 de 47 — faltam 17** |

O CT-e é documento de ICMS e pressupõe emitente inscrito. Os **17 agregados**
com inscrição ausente ou marcada como "ISENTO" respondem por
**1.872 dos 6.375 CT-e do trimestre — 29% da fila**.

Os outros 30 agregados estão **prontos para emitir**: são cerca de
**4.500 documentos** no trimestre, somando **R$ 13,4 milhões** de prestação.

Precisamos saber, para cada um dos 17: **o cadastro está desatualizado** (e
basta corrigir a inscrição) **ou ele é de fato não inscrito** — caso em que não
emite CT-e e sai da fila. Sugerimos conferência no SINTEGRA.

### 4.2 Documentos de valor simbólico

Há agregados cujos CT-e do período somam **menos de R$ 1,00** (um deles, quatro
documentos somando R$ 0,04). Valores assim costumam indicar anulação ou
complemento, não prestação.

**Esses documentos puxam contrapartida?**

### 4.3 Passivo acumulado — decisão jurídica

Desde 2022 são **34.188 CT-e** de agregado PJ, somando **R$ 108,7 milhões** de
prestação, sem o documento correspondente do agregado.

**Isto não se resolve emitindo:** o CT-e não admite emissão retroativa, porque
a SEFAZ recusa data de emissão fora da janela permitida. É matéria para
contabilidade e jurídico decidirem em conjunto, não fila de trabalho.

---

## 5. O que já está pronto e testado

Para que fique claro que não há dependência técnica:

- Em **26/08/2026**, a SEFAZ de São Paulo **autorizou** um CT-e de
  contrapartida emitido em nome de um agregado, em **ambiente de homologação**
  (protocolo 135260006358665).
- Homologação é o ambiente de teste da SEFAZ: o documento **não tem valor
  fiscal**, não é escriturado e não gera obrigação para nenhuma das partes.
- **A emissão em produção está bloqueada no sistema** até que as definições
  deste documento sejam respondidas. É um bloqueio deliberado: um documento
  autorizado com enquadramento errado não se apaga — cancela-se, dentro de
  prazo, com justificativa, e repercute na escrituração dos dois lados.
- Toda emissão fica registrada com autor, data, ambiente, número, chave e
  retorno da SEFAZ.

---

## 6. Restrição de prazo

O certificado digital do agregado usado como piloto **vence em 02/10/2026**.
Não é impedimento para responder este documento, mas se a definição vier depois
dessa data, o primeiro teste em produção aguardará a renovação do certificado.

---

## 7. Resumo — o que pedimos

| O que falta | Com quem | Efeito |
|---|---|---|
| **"Frete mínimo" é o valor pago ou o piso da ANTT?** | Contabilidade | Os dois divergem em **89% das viagens** (R$ 14,7 mi × R$ 18,7 mi) |
| **Critério de rateio** do valor da viagem entre os CT-e | Contabilidade | **48% da fila** fica retida sem ele |
| **CST e tratamento do ICMS** | Contabilidade | Última definição fiscal |
| **Os 17 sem inscrição estadual**: cadastro ou realmente não inscritos? | Cadastro / SINTEGRA | **29% da fila** |

**O que já é possível fazer:** os CT-e que são o **único documento da viagem**
(52% da fila) não dependem do critério de rateio. Dos 47 agregados com
movimento, 30 estão com cadastro completo. Definida a CST e a Questão A, esse
subconjunto pode entrar em produção sem esperar o resto.

---

## 8. Anexo — por que a classificação ficou em subcontratação

*Seção mantida como registro do que foi testado. A definição já está tomada:
subcontratação.*

A primeira resposta recebida foi "prestação normal". Levamos ao ambiente de
teste da SEFAZ antes de implementar, e o órgão **recusou**, por duas regras
próprias de validação:

| O que tentamos | Resposta da SEFAZ |
|---|---|
| Prestação normal, **Sulista como tomadora** | **Recusado (746)** — "Tipo de Serviço inválido para o tomador informado" |
| Prestação normal, **vinculando ao CT-e da Sulista** | **Recusado (747)** — "Documentos anteriores informados para Tipo de Serviço Normal" |
| Prestação normal, tomador = remetente da carga | Autorizado |
| Prestação normal, tomador = destinatário da carga | Autorizado |
| **Subcontratação, Sulista como tomadora, com vínculo** | **Autorizado** |

Em linguagem direta: **na prestação normal, o tomador tem obrigatoriamente de
ser uma das partes da carga** — remetente, expedidor, recebedor ou
destinatário. A Sulista não é nenhuma delas.

As consequências de manter "prestação normal" são duas, e ambas contrariam o
que se pretendia:

1. **O documento sairia contra o cliente, não contra a Sulista.** Mas quem
   contratou e quem paga o agregado é a Sulista — o dinheiro e o documento
   apontariam para lados diferentes.
2. **Nada ligaria esse documento ao nosso CT-e.** O campo que faz o vínculo
   eletrônico é recusado em prestação normal. Sem ele não existe
   "contrapartida": existe uma prestação avulsa.

A única combinação que a SEFAZ autorizou **e** descreve a operação real
(agregado presta para a Sulista, referenciando o nosso CT-e) foi
**subcontratação**.

### Quem é o tomador não está em dúvida — e isso estreita a escolha

Foi levantado se não daria para identificar o tomador pelo CT-e original.
Não diretamente: o tomador do **nosso** CT-e é quem contratou **a Sulista** —
no documento-piloto, o remetente da carga. O documento do agregado precisa
dizer quem contratou **o agregado**. São elos diferentes da mesma cadeia.

Mas o ponto por trás da pergunta procede: **quem contratou o agregado não é
matéria de interpretação, e o próprio ERP registra.** Em 90 dias, em
**5.987 dos 6.596** CT-e (91%), o pagamento da viagem sai da Sulista para o
**dono do veículo** — o agregado. Quem contrata e quem paga é a Sulista, não o
cliente.

Disso decorre, sem opinião fiscal nenhuma:

1. O tomador do documento do agregado **é a Sulista** — é o que os pagamentos
   mostram;
2. a SEFAZ só aceita a Sulista nessa posição em **subcontratação ou
   redespacho** (seção acima);
3. logo, **prestação normal fica descartada pelos fatos**, não por preferência
   nossa.

Resta escolher entre as duas. Um dado que talvez ajude: o redespacho pressupõe
carga já em trânsito, entregue a outro transportador para completar o percurso.
Nos CT-e de agregado, **apenas 28 de 6.365** (0,4%) registram documento de
transporte anterior — em praticamente todos, o agregado faz o percurso inteiro,
não um trecho de cadeia já iniciada.

Com esses elementos, a classificação foi definida como **subcontratação** — o
que os testes já haviam mostrado ser a única compatível com a operação.

---
