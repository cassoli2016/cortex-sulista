-- Relatorio por e-mail SO EM DIA UTIL (12/09/2026).
--
-- Pedido de quem opera: o e-mail da inadimplencia sai as 13h "exceto finais
-- de semana". A agenda do WhatsApp ja tinha esta coluna (0017) e a regra de
-- tempo ja sabia pula-la (`api/agendamento.marcado_para`); faltava o e-mail
-- guarda-la.
--
-- PADRAO FALSE, e nao o 1 do WhatsApp: os agendamentos que ja existem saem
-- todo dia hoje, e uma migration que os fizesse parar no sabado mudaria o
-- que alguem decidiu sem ninguem decidir de novo.
--
-- Feriado NAO entra: a casa nao tem calendario de feriados (ver
-- `api/extrato/comparacao.py`), e "dia util" aqui e segunda a sexta.
ALTER TABLE correio_agenda
    ADD COLUMN IF NOT EXISTS dias_uteis boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN correio_agenda.dias_uteis IS
    'So vale em frequencia diaria: segunda a sexta. Sem feriado -- a casa nao
     tem calendario de feriados.';
