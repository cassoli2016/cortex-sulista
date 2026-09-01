-- 0033 · Smartec: a infração casada com a VIAGEM que o veículo fazia na hora.
--
-- A pergunta que esta tabela responde é "de quem era a carga quando a multa
-- aconteceu?" — o cliente da viagem entra na conversa de repasse e de
-- orientação de rota. O casamento é feito CONTRA O AVA na hora da coleta
-- (api/smartec/viagem.py), nunca na leitura do painel: a tela continua
-- abrindo em milissegundos só com o banco local, e o AVA fora do ar degrada
-- para "vínculo de ontem", não para tela quebrada.
--
-- Tabela PRÓPRIA em vez de colunas em smt_infracoes por duas razões: o
-- gravador das infrações é ON CONFLICT DO UPDATE sobre o payload da Smartec,
-- e colunas nossas no meio do payload alheio seriam sobrescritas por engano
-- na próxima recarga; e o vínculo é HIPÓTESE derivada (janela de viagem que
-- contém o instante), não dado do fornecedor — merece procedência separada.
CREATE TABLE IF NOT EXISTS smt_infracao_viagem(
    identificador   text PRIMARY KEY,     -- o mesmo de smt_infracoes
    cliente         text,                 -- agrupamento do pagador do frete
    rota            text,                 -- "origem/UF → destino/UF"
    dt_saida        date,
    dt_chegada      date,
    -- quantas viagens da placa continham o instante: 1 = casamento firme;
    -- >1 = janelas sobrepostas no ERP e a de menor duração foi a escolhida —
    -- a tela mostra como hipótese, não como veredito.
    candidatas      integer NOT NULL DEFAULT 1,
    casada_em       timestamptz NOT NULL DEFAULT now()
);
