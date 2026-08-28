-- Regras de envio POR MODELO. Um aviso de ocorrência para o motorista e uma
-- cobrança não têm o mesmo horário, o mesmo tom nem o mesmo risco — e até aqui
-- os dois obedeciam a uma configuração única.
--
-- NULL SIGNIFICA "HERDA A REGRA GERAL", e não "zero". É a diferença que faz
-- este desenho funcionar: o modelo declara só o que quer mudar, e tudo o mais
-- continua saindo da tela de Regras de envio. Sem isso, cada modelo novo
-- nasceria com uma cópia congelada da configuração do dia em que foi criado, e
-- mudar a regra geral deixaria de valer para quem já existe.
--
-- A EXCEÇÃO É `assinatura`, que tem TRÊS estados: NULL herda a geral, texto
-- substitui, e string VAZIA quer dizer "não assinar" — um aviso interno para o
-- motorista não precisa da assinatura comercial no fim.
--
-- O `limite_dia` DAQUI NÃO CRIA COTA, e essa é a regra que protege o número: o
-- teto continua sendo o do NÚMERO, valendo para tudo somado, e o do modelo só
-- pode APERTAR (o envio aplica os dois, e o menor manda). O WhatsApp não sabe
-- o que é um modelo — ele vê uma linha telefônica falando com N desconhecidos
-- por dia. Dez modelos com 60 cada não são 600 disparos permitidos: são 600
-- motivos para perder a conta.
--
-- Já a `janela` PODE ser maior que a geral, e isso é decisão consciente de quem
-- edita: alerta de ocorrência às 3h da manhã é legítimo para um motorista e é
-- reclamação certa para um cliente. A tela avisa ao ampliar.

ALTER TABLE zap_modelos ADD COLUMN IF NOT EXISTS limite_dia     integer;
ALTER TABLE zap_modelos ADD COLUMN IF NOT EXISTS janela_inicio  text;
ALTER TABLE zap_modelos ADD COLUMN IF NOT EXISTS janela_fim     text;
ALTER TABLE zap_modelos ADD COLUMN IF NOT EXISTS assinatura     text;
ALTER TABLE zap_modelos ADD COLUMN IF NOT EXISTS instancia      text;
ALTER TABLE zap_modelos ADD COLUMN IF NOT EXISTS intervalo_seg  integer;

-- O sub-limite pergunta "quantos destinatários distintos ESTE modelo alcançou
-- hoje, por este aparelho". Sem índice seria uma varredura a cada mensagem.
CREATE INDEX IF NOT EXISTS ix_zap_envios_modelo
    ON zap_envios(modelo, instancia, telefone, ts);

COMMENT ON COLUMN zap_modelos.limite_dia IS
    'Sub-limite de destinatários distintos por dia. NULL herda o geral. NUNCA
     cria cota: o teto do número vale por cima, e o menor dos dois manda.';
COMMENT ON COLUMN zap_modelos.assinatura IS
    'NULL herda a geral; texto substitui; string VAZIA envia sem assinatura.';
COMMENT ON COLUMN zap_modelos.instancia IS
    'Número preferido para este modelo (principal/backup). NULL = sem
     preferência. É sugestão: quem envia ainda pode escolher outro.';
