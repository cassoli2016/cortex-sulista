-- RNTRC dos transportadores contratados — primeiro store migrado do SQLite.
--
-- Guarda SÓ os transportadores que a Sulista contrata (222 hoje), não a base
-- nacional de 1,16 milhão: o casamento é por número de registro.
--
-- `rntrc` é a chave NORMALIZADA (só dígitos, sem zeros à esquerda). O AVA
-- guarda 8 dígitos e a ANTT publica 9; normalizar só um lado cria falso "não
-- encontrado", que num módulo de compliance acusa quem está em ordem.
--
-- As datas continuam TEXT nesta passada, como no SQLite: `data_situacao` vem
-- da ANTT no formato brasileiro ('01/07/2026') e tipá-la é assunto de uma
-- segunda passada, com o dado antigo ainda disponível para conferir.

CREATE TABLE IF NOT EXISTS rntrc_transportador(
    rntrc         text PRIMARY KEY,
    nome          text,
    situacao      text NOT NULL,
    categoria     text,
    uf            text,
    municipio     text,
    data_situacao text
);

CREATE TABLE IF NOT EXISTS rntrc_sync(
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competencia text    NOT NULL,
    quando      text    NOT NULL,
    linhas      integer NOT NULL
);

COMMENT ON TABLE rntrc_transportador IS
    'Situação do RNTRC dos transportadores contratados. Substituída inteira a
     cada sync — ver api/antt/armazenamento.py.';
COMMENT ON TABLE rntrc_sync IS
    'Trilha das sincronizações: de quando é a base que a tela está mostrando.';
