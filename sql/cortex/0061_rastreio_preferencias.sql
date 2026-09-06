-- Quem recebe o aviso escolhe QUANDO e COM QUE FREQUENCIA.
--
-- O PEDIDO veio de quem usa: "poderíamos colocar os horários que a pessoa
-- deseja receber e durante qual período". Ele é legítimo e barato, mas mexe no
-- lugar mais sensível deste módulo — a única mensagem da casa que sai sozinha
-- para o telefone de alguém que não é usuário do sistema —, então as regras
-- ficam escritas aqui e não só no código.
--
-- 1. A JANELA DO CLIENTE NUNCA AMPLIA A DA CASA, só restringe. A configuração
--    geral (`data/whatsapp_config.json`, hoje 06:00–20:00) existe para a
--    empresa não disparar mensagem de madrugada — e é o WhatsApp que lê
--    denúncia de usuário, não nós. Se a página deixasse alguém pedir 03:00, a
--    proteção da casa passaria a depender do que um desconhecido digitou num
--    formulário aberto à internet. Por isso o que vale no envio é a
--    INTERSEÇÃO, calculada na hora: janela da casa ∩ janela do cliente.
--
-- 2. NULO SIGNIFICA "SEGUE A CASA", não "sem restrição". É a regra da casa
--    para campo de regra opcional, e aqui ela tem consequência prática: quando
--    a janela geral mudar, quem não escolheu nada acompanha sozinho, sem
--    precisar de rotina para atualizar linha nenhuma.
--
-- 3. A PREFERENCIA E DO TELEFONE, NAO DA CARGA, e isto é consequência de uma
--    decisão anterior: as cargas de um mesmo número saem numa mensagem só
--    (`mensagem.montar_varias`). Guardar uma janela por carga criaria o caso
--    sem resposta — duas cargas, duas janelas, uma mensagem. Então a coluna
--    mora na inscrição por conveniência de leitura, mas a escrita atualiza
--    TODAS as inscrições ativas do telefone, e o envio lê a do grupo.

ALTER TABLE rst_inscricao ADD COLUMN IF NOT EXISTS janela_inicio TEXT;
ALTER TABLE rst_inscricao ADD COLUMN IF NOT EXISTS janela_fim    TEXT;
ALTER TABLE rst_inscricao ADD COLUMN IF NOT EXISTS cadencia      TEXT;

COMMENT ON COLUMN rst_inscricao.janela_inicio IS
    'Hora (HH:MM) a partir da qual este telefone aceita receber. NULO = segue a
     janela geral da casa, e é o padrão. O que vale no envio é a INTERSEÇÃO com
     a janela geral: a escolha do cliente só RESTRINGE — uma página aberta à
     internet não pode ampliar a proteção que existe para o número da empresa
     não ser denunciado.';

COMMENT ON COLUMN rst_inscricao.janela_fim IS
    'Hora (HH:MM) até a qual este telefone aceita receber. NULO = segue a casa.
     Ver `janela_inicio`.';

COMMENT ON COLUMN rst_inscricao.cadencia IS
    'Quanta coisa é notícia para este telefone: "tudo" (padrão — qualquer
     mudança material, no máximo uma mensagem por hora), "menos" (a mesma
     régua, com no mínimo três horas entre mensagens) ou "marcos" (só mudança
     de ESTADO da viagem: chegou, está em descarga, foi entregue, ou paramos de
     enxergar o veículo). NULO = "tudo". A cadência NÃO afrouxa nenhum freio:
     ela só torna a régua de "o que mudou" mais exigente.';
