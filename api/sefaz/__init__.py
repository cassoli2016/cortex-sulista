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

Com a contabilidade na mesma caixa (acima), nem a ciência é automática por
enquanto: sem o XML completo a casa fica com o resumo, o que é uma perda REAL —
mas menor que dois sistemas assumindo ciência da mesma nota.

O AMBIENTE
----------

Distribuição de DFe **não tem homologação com dado real** — o ambiente 2
responde, e responde vazio. Provar este caminho é em produção, e não há risco
nisso porque a consulta é LEITURA. O que exige cuidado é a manifestação, que
por isso nasce desligada e sob pedido.
"""
