-- 0073 · O castigo da SEFAZ é MAIS LONGO quando se reincide, e o freio da casa
-- precisa saber disso.
--
-- O QUE FOI MEDIDO EM 08/09/2026
-- ==============================
--
-- Depois de rebobinar o ponteiro, a caixa da matriz serviu 2.000 documentos com
-- cStat 138 e sem reclamar. Rodei passadas em SEQUÊNCIA, sem intervalo, para
-- drenar mais rápido — e na quarta veio o 656 (consumo indevido).
--
-- O freio da casa esperava 65 minutos, que é o que a própria rejeição pede. A
-- tentativa seguinte, **80 minutos depois**, voltou 656 de novo. E a seguinte
-- também. O castigo não é de uma hora fixa: ele CRESCE com a reincidência, e
-- cada batida dentro do bloqueio o renova.
--
-- Isso torna o freio de intervalo fixo pior que inútil: de 20 em 20 minutos a
-- tarefa agendada bate na porta trancada, e a porta responde trancando por mais
-- tempo. A fila de 34 mil documentos nunca dreneria.
--
-- POR QUE UMA COLUNA, E NÃO UMA CONTA NA HORA
-- -------------------------------------------
-- Não há histórico de consultas: `dfe_caixa` guarda só a ÚLTIMA. Para saber que
-- este é o quarto 656 seguido é preciso ter contado os três anteriores — e um
-- contador que se apaga sozinho na primeira resposta boa é a forma mais barata
-- de guardar exatamente essa informação, e nada além dela.
ALTER TABLE dfe_caixa
  ADD COLUMN IF NOT EXISTS freios_seguidos smallint NOT NULL DEFAULT 0;

COMMENT ON COLUMN dfe_caixa.freios_seguidos IS
  'Quantos 656 seguidos esta caixa levou. Zera na primeira resposta que nao e '
  '656 (137 ou 138). A espera da proxima varredura dobra a cada um, com teto '
  '- ver INTERVALO_APOS_FREIO em api/sefaz/distribuicao.py';
