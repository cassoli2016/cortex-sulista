-- Cadastro de usuário mais encorpado: telefone, cargo, setor, ramal e foto de
-- perfil. Tudo OPCIONAL — a base em produção já tem gente cadastrada e nenhum
-- desses campos pode virar impedimento para entrar no sistema.
--
-- TELEFONE É GUARDADO NORMALIZADO (`5547999998888`, só dígitos com DDI), pelo
-- mesmo motivo que a trilha do WhatsApp guarda: se `(47) 99999-8888` e
-- `5547999998888` virassem duas grafias do mesmo telefone, qualquer contagem
-- ou comparação futura mediria formato de digitação, não pessoa. Quem valida e
-- normaliza é `api/whatsapp/numeros.py` — a mesma função que decide o que a
-- Z-API aceita, para não existirem duas noções de "telefone válido" na casa.
-- A tela reformata na exibição.
--
-- A FOTO FICA EM TABELA SEPARADA, e isso não é organização: `sessao_atual()`
-- faz `SELECT u.*` a CADA requisição autenticada para validar o cookie. Uma
-- coluna `bytea` em `usuarios` colocaria os bytes da imagem em toda chamada de
-- API do painel — dezenas por tela — para desenhar um avatar de 34px que o
-- navegador já tem em cache. Em tabela ao lado, a foto só sai do banco quando
-- alguém pede a foto.
--
-- ON DELETE CASCADE porque `usuario_excluir` faz `DELETE FROM usuarios`: sem
-- isso, excluir usuário passaria a falhar por violação de chave estrangeira —
-- e o defeito só apareceria no dia em que alguém fosse excluir alguém.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefone text;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS cargo    text;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS setor    text;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ramal    text;

CREATE TABLE IF NOT EXISTS usuario_fotos(
    usuario_id    integer PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    mime          text    NOT NULL,
    largura       integer NOT NULL,
    altura        integer NOT NULL,
    bytes         bytea   NOT NULL,
    atualizado_em text    NOT NULL
);

COMMENT ON COLUMN usuarios.telefone IS
    'Telefone normalizado (DDI+DDD+número, só dígitos), como api/whatsapp/numeros.py
     produz. NULL = não informado. A tela formata na exibição.';
COMMENT ON TABLE usuario_fotos IS
    'Foto de perfil, uma por usuário. Separada de `usuarios` porque a validação
     de sessão lê a linha do usuário a cada requisição e não pode arrastar a
     imagem junto. `atualizado_em` é o ETag servido em GET /api/auth/foto/{id}.';
