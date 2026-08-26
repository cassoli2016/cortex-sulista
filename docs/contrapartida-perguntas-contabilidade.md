# CT-e de contrapartida do agregado — definições pendentes

**Para:** Contabilidade
**De:** Controladoria / CÓRTEX
**Data:** 26/08/2026

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

### 3.3 Um documento por CT-e nosso, ou por viagem?

Os dois não são a mesma coisa. Em 90 dias, **6.578 CT-e** emitidos com veículo
de agregado PJ corresponderam a **3.834 viagens** — média de **1,7 documento
por viagem**.

Além disso, **o valor pago ao agregado é por viagem**, não por CT-e. Se a
definição for "um documento por CT-e", precisamos saber **como ratear** o valor
da viagem entre os documentos.

Hoje o sistema **interrompe** o processo nesses casos, em vez de dividir por
conta própria — dividir sem critério definido seria inventar base de cálculo.

O impacto é grande: por viagem, a fila é cerca de **45% menor** do que por CT-e.

### 3.4 Tratamento do ICMS

**Qual o tratamento e a CST aplicáveis**, considerando que boa parte dos
agregados é optante do Simples Nacional?

No cadastro, **94 das 203 placas** de agregado PJ pertencem a proprietários
marcados como optantes. O piloto foi emitido como optante do Simples, mas o
ambiente de teste **não valida acerto fiscal** — ele aceitou o documento, não
o enquadramento.

### 3.5 Série e numeração

**Qual série cada agregado deve usar, e a partir de qual número?**

Se algum deles já emitiu CT-e por outro meio, número repetido é rejeitado por
duplicidade. Precisamos confirmar, agregado a agregado, se há numeração em uso.

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

| # | Pergunta | Efeito da resposta |
|---|---|---|
| 0 | Há dispensa de emissão pelo subcontratado? | Se sim, **não há fila** |
| 1 | Subcontratação, redespacho ou prestação normal? | CFOP e natureza |
| 2 | Valor cobrado do cliente ou valor pago ao agregado? | Base de ICMS |
| 3 | Um documento por CT-e ou por viagem? | Tamanho da fila (±45%) |
| 4 | Tratamento e CST do ICMS | Cálculo do imposto |
| 5 | Série e numeração por agregado | Evita rejeição por duplicidade |
| 6 | Os 17 com IE "ISENTO" emitem? | Fila de 53 ou de 36 |
| 7 | Documentos de valor simbólico entram? | Escopo |
| 8 | O que fazer com o passivo de R$ 108,7 mi? | Jurídico |
