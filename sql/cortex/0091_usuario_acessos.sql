-- Ajustes de acesso POR USUÁRIO, por cima do perfil (13/09/2026).
--
-- Pedido de quem opera: "ao cadastrar um usuário, informar a página inicial
-- dele; colocar permissões especiais por usuário, tirar acesso a determinadas
-- abas, dar acesso a telas específicas — para elevar o nível de segurança".
--
-- Até aqui a única pergunta de acesso era perfil × tela (0011_auth.sql), e
-- toda exceção virava um perfil novo com UMA pessoa dentro — o tipo de perfil
-- que ninguém revisa, porque o nome não diz que é exceção. Aqui a exceção tem
-- nome, dono e data, e mora ao lado da pessoa.
--
-- POR QUE TABELA E NÃO COLUNA. Ao contrário do vínculo de cliente (0053), que
-- é UM valor por login, ajuste é uma LISTA: "libera a tela X, tira a tela Y,
-- tira a aba Z". A chave primária (usuario_id, chave) garante que a mesma
-- tela não recebe duas ordens contraditórias para a mesma pessoa.
--
-- O QUE A CHAVE PODE SER. Uma tela de `auth.TELAS` ("fluxo", "dreexc"…) ou
-- uma aba bloqueável de `api/acessos.ABAS` ("dre.pano"…). Não há FK nem CHECK
-- de propósito, como em `perfil_telas`: as telas são registro do CÓDIGO, e
-- quem valida é o Python na gravação. Tela que um dia for aposentada deixa a
-- linha órfã e INERTE (o cálculo ignora chave desconhecida) — nunca amplia
-- acesso.
--
-- O EFEITO É 'liberar' OU 'tirar', e 'tirar' vence tudo (perfil e liberação):
-- em dúvida entre dois registros, o sistema fica do lado que dá MENOS acesso.
-- Aba só aceita 'tirar' — liberar aba de tela que a pessoa não tem não faz
-- sentido, e o Python recusa.
--
-- O ACESSO EFETIVO NÃO SE GRAVA: `sessao_atual()` o calcula a cada requisição
-- (perfil + ajustes), e é por isso que tirar uma tela vale no clique seguinte,
-- sem derrubar a sessão da pessoa.
--
-- ON DELETE CASCADE porque `usuario_excluir` faz DELETE FROM usuarios.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pagina_inicial text;

CREATE TABLE IF NOT EXISTS usuario_acessos(
    usuario_id integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    chave      text    NOT NULL,
    efeito     text    NOT NULL CHECK (efeito IN ('liberar', 'tirar')),
    criado_em  text    NOT NULL,
    criado_por text    NOT NULL DEFAULT '',
    PRIMARY KEY (usuario_id, chave)
);

COMMENT ON COLUMN usuarios.pagina_inicial IS
    'Tela que abre quando o usuário entra sem endereço (chave de VIEWS). NULL =
     a página inicial da casa (radar). Se a pessoa perder o acesso à tela
     escolhida, vale o radar — o que se calcula na leitura, não se corrige aqui.';
COMMENT ON TABLE usuario_acessos IS
    'Ajustes de acesso por usuário por cima do perfil: liberar ou tirar uma
     tela, tirar uma aba bloqueável. Tirar vence. Não vale para perfil
     administrador. Quem lê é api/acessos.py.';
