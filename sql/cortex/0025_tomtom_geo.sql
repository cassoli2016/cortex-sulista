-- Coordenada de um lugar, resolvida uma vez e guardada para sempre.
--
-- POR QUE CACHE PERMANENTE, sem TTL: cidade não se move. O que envelhece numa
-- geocodificação é a precisão de um ENDEREÇO (número novo, loteamento), e aqui
-- a consulta é "CIDADE/UF" — o centro dela é o mesmo daqui a dez anos.
--
-- POR QUE ISTO EXISTE: 13 das 70 viagens em trânsito não têm
-- `coleta.latitudedestino` no ERP e por isso ficavam SEM ETA nenhum. São 10
-- cidades distintas; geocodificá-las custa 10 chamadas UMA VEZ, e as mesmas
-- cidades se repetem viagem após viagem.
--
-- `achou = false` também é gravado, e de propósito: sem isso, um destino que a
-- TomTom não resolve seria consultado de novo a cada varredura, para receber a
-- mesma resposta e gastar a mesma cota.
CREATE TABLE IF NOT EXISTS tt_geocode (
    consulta   text        PRIMARY KEY,   -- normalizada: MAIÚSCULA, sem espaço duplo
    lat        double precision,
    lon        double precision,
    achou      boolean     NOT NULL DEFAULT true,
    rotulo     text,                       -- o que a TomTom entendeu, para conferência
    obtido_em  timestamp   NOT NULL DEFAULT now()
);
