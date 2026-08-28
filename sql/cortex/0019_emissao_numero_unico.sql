-- Numero de CT-e nao se repete: o banco passa a garantir.
--
-- O QUE ESTAVA ABERTO
-- -------------------
-- `proximo_numero` fazia `SELECT max(numero)` numa transacao curta, devolvia, e
-- o `INSERT` acontecia em OUTRA transacao, depois de uma chamada SOAP a SEFAZ
-- que leva segundos. Entre as duas nao havia lock, nao havia sequence e nao
-- havia restricao: duas execucoes simultaneas liam o mesmo maximo e escolhiam
-- o mesmo numero.
--
-- E o erro nao pararia em "numero repetido". O codigo numerico da chave (cNF)
-- NAO e aleatorio - a biblioteca o calcula como soma dos campos anteriores -,
-- entao o mesmo emitente, serie, numero e mes produzem a MESMA chave de 44
-- digitos, bit a bit. Nao ha entropia para escapar: numero colidido e chave
-- colidida, garantida. O melhor caso e a rejeicao 539 (duplicidade); o pior e
-- os dois documentos serem autorizados por caminhos diferentes.
--
-- POR QUE UM INDICE E NAO UM LOCK
-- -------------------------------
-- Um advisory lock teria de ser segurado da escolha do numero ate a gravacao
-- do retorno - ou seja, com uma transacao aberta durante a chamada a SEFAZ,
-- que pode levar 30 segundos e pode pendurar. Trocaria uma corrida por uma
-- conexao presa.
--
-- O indice serializa no unico ponto que importa e nao custa nada: quem chega
-- depois leva erro de chave duplicada AO RESERVAR - antes de montar, antes de
-- assinar e antes de falar com a SEFAZ -, e simplesmente pega o proximo numero.
-- Ver `emissao.reservar_numero`.
--
-- O QUE O INDICE NAO COBRE, DE PROPOSITO
-- --------------------------------------
-- CANCELAMENTO reusa serie e numero: o evento entra como linha propria com
-- cStat "CANC:<codigo>" na mesma numeracao do documento que derruba. Incluir
-- essas linhas faria todo cancelamento falhar. Dai o indice ser PARCIAL.
--
-- Conferido nas 207 linhas em producao em 28/08/2026: zero violacoes.

CREATE UNIQUE INDEX IF NOT EXISTS ux_emissao_numero
    ON emissao (ambiente, cnpj_emitente, serie, numero)
 WHERE cstat IS NULL OR cstat NOT LIKE 'CANC:%';

COMMENT ON INDEX ux_emissao_numero IS
    'Impede dois documentos com o mesmo numero no mesmo emitente, serie e
     ambiente. E a serializacao da numeracao: a reserva colide AQUI, antes de
     montar e antes de falar com a SEFAZ. Parcial porque o evento de
     cancelamento reusa a numeracao do documento que derruba.';

COMMENT ON COLUMN emissao.cstat IS
    'Retorno da SEFAZ. NULO tem significado: o numero foi RESERVADO e nao ha
     retorno. Ou a reserva esta em voo agora, ou a transmissao falhou depois de
     o documento ter partido - e nesse caso ele PODE ter sido autorizado sem
     que soubessemos. Numero assim nunca e reaproveitado, e a tela de
     transmitidos os mostra a parte para alguem conferir no portal.';
