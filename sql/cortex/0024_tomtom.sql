-- Consumo da API da TomTom, por dia.
--
-- POR QUE CONTAR: nenhuma resposta da TomTom traz cabeçalho de limite --
-- medido em 30/08/2026, nas três famílias de endpoint. O teto do plano só
-- aparece no painel deles. Sem poder VER o limite, o mínimo honesto é ver o
-- GASTO: quantas chamadas o CÓRTEX fez hoje, e desde quando.
--
-- Em memória seria mais barato e erraria justo quando importa: o contador
-- zeraria a cada reinício da API, e é depois de um reinício que ninguém sabe
-- quanto já foi consumido no dia.
CREATE TABLE IF NOT EXISTS tt_chamadas (
    dia        date        NOT NULL,
    recurso    text        NOT NULL,   -- fluxo | incidentes | rota
    chamadas   integer     NOT NULL DEFAULT 0,
    erros      integer     NOT NULL DEFAULT 0,
    ultima_em  timestamp,
    PRIMARY KEY (dia, recurso)
);
