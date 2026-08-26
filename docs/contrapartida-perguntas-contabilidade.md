# CT-e de contrapartida do agregado — definições pendentes

**Para:** Contabilidade
**De:** Controladoria / CÓRTEX
**Data:** 26/08/2026 · **atualizado com as respostas recebidas**

---

## 0. Situação das respostas

| # | Pergunta | Resposta |
|---|---|---|
| 0 | Há dispensa de emissão pelo subcontratado? | *aguardando* |
| 1 | Subcontratação, redespacho ou prestação normal? | **Prestação normal** ⚠️ |
| 2 | Valor cobrado do cliente ou pago ao agregado? | *aguardando* |
| 3 | Um documento por CT-e ou por viagem? | **Um por CT-e** |
| 4 | Tratamento e CST do ICMS | *aguardando* |
| 5 | Série e numeração por agregado | **Série 900 aprovada** (provisória) |
| 6 | Os 17 com IE "ISENTO" emitem? | em análise |
| 7 | Documentos de valor simbólico entram? | **Não, por ora** |
| 8 | Passivo de R$ 108,7 mi | encaminhado ao Jurídico |

⚠️ **A resposta 1 precisa ser reconciliada — ver seção 2-A.** Testamos
"prestação normal" contra a SEFAZ e ela é incompatível com a premissa deste
trabalho.

---

## 2-A. URGENTE — "prestação normal" não permite emitir contra a Sulista

Levamos a resposta "prestação normal" ao ambiente de teste da SEFAZ. O órgão
**recusou** o documento, por duas regras próprias de validação:

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

**Pedimos a reconfirmação da resposta 1** entre **subcontratação** e
**redespacho**, ciente destas restrições. Não é divergência de opinião nossa:
são as regras de validação do próprio órgão, observadas em teste.

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

## 2. A pergunta que vem antes de todas

> **Na subcontratação, o subcontratado está dispensado de emitir o CT-e,
> ficando a prestação amparada pelo documento do subcontratante?**

Pedimos que esta seja verificada **primeiro**, e antes de responder as demais.

Se a dispensa se aplicar ao nosso caso, **não há fila nenhuma a emitir**: os
cerca de 3.100 documentos por mês simplesmente não existem como obrigação, e o
trabalho vira conferência, não emissão. Todas as perguntas seguintes deixam de
fazer sentido.

Se não se aplicar, seguem as demais.

---

## 3. Definições necessárias

### 3.1 Enquadramento da operação

**Subcontratação, redespacho ou prestação normal?**

A resposta define o CFOP e a natureza da operação declarada no documento.

*Observação, não sugestão:* a própria Sulista, quando é **ela** a contratada
por outra transportadora, emite esses documentos com **CFOP 6351 — prestação
de serviço de transporte para execução de serviço da mesma natureza**,
classificados como subcontratação, com a transportadora contratante como
tomadora. O documento do agregado contra nós é o espelho exato desse caso.
Registramos isso como precedente interno, não como opinião fiscal.

### 3.2 Valor da prestação

**O documento do agregado vale o que a Sulista cobrou do cliente, ou o que a
Sulista paga ao agregado?**

Os dois números existem e são bem diferentes. No documento usado como piloto:

| Base | Valor |
|---|---|
| Prestação cobrada do cliente | R$ 1.494,02 |
| Frete pago ao agregado | R$ 1.066,32 |

O valor pago corresponde a cerca de **71%** do cobrado. Como se trata de base
de cálculo de ICMS, a escolha não é do sistema.

### 3.3 Um documento por CT-e nosso, ou por viagem? — RESPONDIDO: por CT-e

**A resposta torna a pergunta 3.2 mais urgente do que parecia.**

Medimos: **3.159 dos 6.594** CT-e do trimestre — **48%, quase metade** —
compartilham a viagem com pelo menos um outro documento. E o valor pago ao
agregado é lançado **por viagem**, não por CT-e.

Portanto, se a resposta de 3.2 for "valor pago ao agregado", metade da fila
precisa de um **critério de rateio** desse valor entre os documentos da mesma
viagem — por peso? por valor da mercadoria? em partes iguais? Hoje o sistema
**interrompe** nesses casos, de propósito.

Se a resposta de 3.2 for "valor cobrado do cliente", o problema desaparece:
cada CT-e já tem o seu próprio valor.

Dividir sem critério definido seria inventar base de cálculo, e por isso o
sistema prefere parar.

Números de referência do trimestre: **6.594 CT-e** de agregado PJ
correspondendo a **3.834 viagens** — média de 1,7 documento por viagem. Com a
decisão "um por CT-e", a fila fica no número maior: **os 6.594**.

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

## 4. Três pontos que não travam a emissão, mas mudam os números

### 4.1 Inscrição estadual "ISENTO" — 17 de 53 agregados

O CT-e é documento de ICMS e pressupõe emitente inscrito. **17 dos 53**
agregados PJ estão com o texto "ISENTO" no campo de inscrição estadual.

Ou o cadastro está desatualizado, ou esses 17 **não emitem CT-e** — e nesse
caso a fila real é de **36 agregados, não 53**. Sugerimos conferência no
SINTEGRA antes de tratar como pendência de cadastro.

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

Restam **três** definições. As demais estão respondidas ou encaminhadas.

| # | O que ainda falta | Por que trava |
|---|---|---|
| 0 | Há dispensa de emissão pelo subcontratado? | Se houver, **não há fila nenhuma** |
| 1 | **Subcontratação ou redespacho?** | "Prestação normal" está descartada pelos fatos (seção 2-A) |
| 2 | Valor cobrado do cliente ou pago ao agregado? | Base de ICMS — e define se metade da fila precisa de critério de rateio |
| 4 | Tratamento e CST do ICMS | Cálculo do imposto |

**A ordem importa.** A pergunta 0 pode encerrar o assunto; a 1 define se o
documento é emitido contra a Sulista ou contra o cliente. As demais só fazem
sentido depois dessas duas.
