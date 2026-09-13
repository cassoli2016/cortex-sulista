-- O calendario de feriados da casa (12/09/2026).
--
-- Ate aqui "dia util" era "segunda a sexta": o e-mail da inadimplencia das 13h
-- e a agenda do WhatsApp sairiam num 7 de setembro. O desenho inteiro esta em
-- `api/calendario.py`; o que importa para o esquema:
--
-- FOLGA E COLUNA PROPRIA, e nao consequencia do tipo. A web (BrasilAPI) chama
-- de feriado nacional o Carnaval e o Corpus Christi, que pela lei federal sao
-- ponto facultativo. Eles entram com `folga = false`, e quem opera liga aqui se
-- a casa nao trabalha -- `folga_por` guarda quem decidiu, e a proxima busca na
-- web NAO desfaz a decisao.
--
-- `uf` e `municipio` sao NOT NULL DEFAULT '' para a chave unica funcionar: com
-- NULL, o Postgres deixa entrar a mesma data duas vezes.
CREATE TABLE IF NOT EXISTS cal_feriados(
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    data        date    NOT NULL,
    nome        text    NOT NULL,
    tipo        text    NOT NULL CHECK (tipo IN ('nacional', 'facultativo',
                        'comemorativa', 'a_conferir', 'estadual', 'municipal',
                        'empresa')),
    uf          text    NOT NULL DEFAULT '',
    municipio   text    NOT NULL DEFAULT '',
    folga       boolean NOT NULL,
    -- 'brasilapi' (web) | 'lei' (a lista federal cobrindo o que a web nao
    -- trouxe) | 'manual' (estadual, municipal, da empresa)
    fonte       text    NOT NULL,
    coletado_em timestamptz NOT NULL DEFAULT now(),
    criado_por  text,
    folga_por   text,
    folga_em    timestamptz,
    UNIQUE (data, tipo, uf, municipio)
);

CREATE INDEX IF NOT EXISTS ix_cal_feriados_folga ON cal_feriados(data) WHERE folga;

-- A busca na web, por ANO. `ok_em` nulo e "nunca buscou com sucesso": nesse
-- ano vale a lista da lei. A falha grava `erro` SEM apagar o ultimo sucesso.
CREATE TABLE IF NOT EXISTS cal_feriados_coleta(
    ano          integer PRIMARY KEY,
    fonte        text    NOT NULL,
    ok_em        timestamptz,
    itens        integer NOT NULL DEFAULT 0,
    divergencias text[]  NOT NULL DEFAULT '{}',
    erro         text,
    erro_em      timestamptz
);
