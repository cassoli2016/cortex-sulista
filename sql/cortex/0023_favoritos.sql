-- Favoritos de tela, por usuário.
--
-- POR QUE NO BANCO E NÃO NO NAVEGADOR
-- ==================================
-- O drawer já tem "Suas mais usadas", que sai do `localStorage` e é derivada
-- de comportamento — ninguém escolhe, ela se forma sozinha. Favorito é o
-- oposto: é ESCOLHA, e escolha que a pessoa fez uma vez tem de valer no
-- celular e no computador. Guardar em `localStorage` faria o favorito do
-- desktop não existir no telefone, que é justamente onde o acesso rápido mais
-- importa.
--
-- O RBAC NÃO É APLICADO AQUI, E SIM NA LEITURA
-- ============================================
-- A linha do favorito FICA quando o acesso à tela é revogado — ela só deixa
-- de aparecer. Apagar seria destruir a escolha de quem, semana que vem, pode
-- recuperar o acesso e esperaria encontrar tudo como deixou. Filtrar na
-- leitura custa nada e é reversível; apagar não.

CREATE TABLE IF NOT EXISTS usuario_favoritos(
    usuario_id  integer NOT NULL
                REFERENCES usuarios(id) ON DELETE CASCADE,
    -- o ID da tela (`home`, `fluxo`, `prem`...), o mesmo de `auth.TELAS`.
    -- Sem FK porque o catálogo de telas vive no CÓDIGO, não em tabela: uma FK
    -- aqui exigiria manter as duas listas em sincronia e quebraria o deploy
    -- que acrescenta tela nova antes de alguém rodar migration.
    tela        text    NOT NULL,
    -- ordem escolhida por quem favoritou. A ordem importa: o favorito existe
    -- para encurtar caminho, e caminho curto é o que está no topo.
    ordem       integer NOT NULL DEFAULT 0,
    criado_em   text    NOT NULL,
    PRIMARY KEY (usuario_id, tela)
);

-- a consulta é sempre "os favoritos DESTE usuário, na ordem" — é a única que
-- existe, e roda a cada carregamento de página
CREATE INDEX IF NOT EXISTS ix_usuario_favoritos
    ON usuario_favoritos(usuario_id, ordem);
