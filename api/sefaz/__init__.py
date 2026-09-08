# -*- coding: utf-8 -*-
"""A caixa de entrada da SEFAZ — os documentos fiscais que chegam à Sulista.

O QUE ESTE MÓDULO RECOLHE
=========================

O serviço nacional de **Distribuição de DFe** (`NFeDistribuicaoDFe`) entrega ao
destinatário tudo que foi emitido CONTRA o CNPJ dele: NF-e de fornecedor, CT-e
onde ele é tomador, e os eventos desses documentos (cancelamento, carta de
correção). É a única fonte que não depende de o fornecedor mandar o XML por
e-mail — e é por isso que ela existe.

TRÊS FATOS DO PROTOCOLO QUE DECIDEM O DESENHO
---------------------------------------------

1. **O NSU é o estado inteiro.** Um contador por destinatário: pede-se "o que
   veio depois do NSU X" e a SEFAZ devolve o próximo lote (até 50 documentos).
   Ele é gravado a CADA lote, não no fim da varredura — cair no meio de uma
   varredura de 4.000 documentos e ter de recomeçar do zero é o que o freio de
   consumo indevido pune.

2. **Buraco no NSU é NORMAL.** A sequência é global do ambiente nacional, não
   sua: a SEFAZ pula os NSU que não lhe dizem respeito. Tratar buraco como
   perda faria a recolha ficar tentando reler para sempre.

3. **O resumo vem antes do documento.** Para NF-e de entrada a SEFAZ devolve
   só o `resNFe` (chave, emitente, valor, situação) enquanto o destinatário não
   manifestar **ciência da operação**. O XML completo (`procNFe`) só vem
   depois. Então o mesmo NSU chega duas vezes com conteúdo diferente, e a
   segunda é um upgrade — nunca uma duplicata, e nunca um retrocesso
   (`gravar()` não deixa resumo sobrescrever documento completo).

NÃO SOMOS O ÚNICO CONSUMIDOR DESTA CAIXA
----------------------------------------

**A contabilidade já baixa a distribuição de DFe da Sulista** (confirmado por
quem opera em 07/09/2026). Foi o que a SEFAZ disse antes de alguém contar: a
primeira consulta a partir do NSU zero voltou

    656 · Consumo Indevido (Deve ser utilizado o ultNSU nas solicitacoes
          subsequentes) — ultNSU 1.144.010

O NSU é do CNPJ, não do consumidor: uma sequência em 1,1 milhão é o rastro de
alguém que vem lendo há tempo. Duas consequências, e a segunda é a que morde:

1. **Ler em paralelo é seguro** — cada consumidor guarda o próprio ponteiro, e
   a SEFAZ serve o mesmo NSU a quem pedir. O que ela pune é o PADRÃO de
   consulta (do zero, ou repetida sem resultado), não a companhia.

2. **MANIFESTAR EM PARALELO NÃO É.** O evento é do documento, não do
   consumidor: se a contabilidade já manifesta ciência, a nossa vira evento
   duplicado e a SEFAZ rejeita o segundo — e, pior, quem manifesta ASSUME a
   ciência com prazo legal correndo. Enquanto não estiver combinado quem
   manifesta, a ciência automática fica DESLIGADA aqui.

E UM FATO QUE DECIDE A POLÍTICA
-------------------------------

**Manifestar é ESCREVER na SEFAZ**, com efeito legal e prazo. A ciência
(210210) é "eu vi" e não afirma nada sobre a operação — é o que destrava o XML
e PODERIA ser automática. Confirmação (210200), desconhecimento (210220) e
operação não realizada (210240) AFIRMAM, têm consequência fiscal e não se
automatizam: exigem alguém pedindo, e a trilha guarda quem foi
(`dfe_manifestacao`).

**DECISÃO DE QUEM OPERA, 07/09/2026: a manifestação fica para um segundo
momento.** Nada neste módulo escreve na SEFAZ — a recolha é só leitura, e é
assim que ela vai para produção.

O que isso custa, dito na cara: **a casa fica com o RESUMO, não com o XML.**
`resNFe` traz chave, emitente, valor e situação — dá para conferir a nota
contra a ordem de compra e para saber que ela existe. Não dá para a guarda
fiscal de cinco anos, que é do documento autorizado. Enquanto a manifestação
não vier para cá (ou a contabilidade não repassar o XML), essa metade continua
com eles.

A tela DIZ isso em cada documento, em vez de deixar parecer que a nota inteira
está guardada: `completo = false` não é um detalhe técnico, é a diferença entre
ter e não ter a obrigação cumprida.

ESTE MODULO NAO DEPENDE DO ERP
------------------------------

**A recolha e do CORTEX, e funciona sem o AVA.** Isso e decisao de arquitetura
de quem opera (07/09/2026), e nao consequencia de como o codigo saiu: o modulo
e do TMS Cortex, e vai ser usado independente do ERP.

A fronteira, entao, e literal e tem guard:

    api/sefaz/distribuicao.py   fala com a SEFAZ           -- sem ERP
    api/sefaz/leitura.py        le o XML                   -- sem ERP
    api/sefaz/armazenamento.py  grava no banco DA CASA     -- sem ERP
    api/sefaz/busca.py          procura documento          -- sem ERP
    api/sefaz/impressao.py      DANFE/DACTE/DAMDFE         -- sem ERP
    api/sefaz/painel.py         o que a tela mostra        -- sem ERP
    -----------------------------------------------------------------
    api/sefaz/conciliacao.py    o UNICO que le o ERP, e e OPCIONAL

`tests/sefaz/test_independencia.py` cobra isso: nenhum arquivo do nucleo
importa `api.db` nem nomeia tabela do AVA. Apagar `conciliacao.py` inteiro tem
de deixar a recolha funcionando -- e o teste apaga, na pratica, derrubando o
ERP e conferindo que a tela continua de pe.

POR QUE ISSO IMPORTA, ALEM DA ARQUITETURA: o reaproveitamento entre o CORTEX e
o TMS Sulista e por COPIA, nunca por import (memoria `tms-sulista-projeto-
separado`). Um modulo que so funciona com o AVA por perto nao se copia -- ele
se reescreve, e reescrever e onde as sete correcoes da `erpbrasil.edoc` se
perdem.

O AMBIENTE
----------

Distribuição de DFe **não tem homologação com dado real** — o ambiente 2
responde, e responde vazio. Provar este caminho é em produção, e não há risco
nisso porque a consulta é LEITURA. O que exige cuidado é a manifestação, que
por isso nasce desligada e sob pedido.
"""
