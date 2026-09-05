-- Portal do cliente: o vínculo que diz DE QUEM é a operação que um usuário vê.
--
-- Até aqui o CÓRTEX tinha uma pergunta de acesso só: QUE TELA você abre
-- (perfil × tela, 0011_auth.sql). Todo usuário era gente da casa, e quem podia
-- abrir a tela podia ver a tela inteira. A tela `cliop` ("Minha Operação")
-- introduz a segunda pergunta — QUAIS LINHAS são suas — porque quem loga nela
-- é gente do CLIENTE, e a operação do vizinho não é dela.
--
-- POR QUE UMA COLUNA EM `usuarios` E NÃO UMA TABELA DE VÍNCULOS. O escopo é
-- uma propriedade do usuário, não um relacionamento com cardinalidade: um
-- login pertence a UMA empresa. Tabela ao lado permitiria duas linhas para o
-- mesmo usuário — quer dizer, um login vendo duas operações — e é exatamente
-- isso que não pode existir sem alguém decidir que pode. Grupo econômico
-- (a Maxion Montich é outra raiz de CNPJ) fica de fora por decisão de 05/09/2026;
-- se um dia entrar, entra como tabela e com a regra escrita, não por acidente
-- de modelagem.
--
-- POR QUE A RAIZ (8 dígitos) E NÃO O CNPJ INTEIRO. O ERP cadastra UMA LINHA
-- POR FILIAL — a Iochpe-Maxion S.A. tem quatro (Cruzeiro/SP, Resende/RJ,
-- Contagem/MG e Limeira/SP), com CNPJs que só diferem no sufixo. Guardar o
-- CNPJ completo faria o usuário de Cruzeiro não enxergar a carga que chegou em
-- Resende, que é a mesma empresa. A raiz é o que identifica a EMPRESA; o
-- sufixo identifica o endereço. É a mesma escolha que `api/antecipacoes/registro.py`
-- já fez pelo mesmo motivo, e está aqui de propósito: são duas telas lendo o
-- mesmo cliente e elas têm de concordar sobre quem ele é.
--
-- NULL É O ESTADO NORMAL, e é o estado SEGURO. Todo usuário da casa tem NULL
-- aqui: não há operação de cliente que seja a deles. Quem lê esta coluna trata
-- NULL como "não tem escopo" e RECUSA (403), nunca como "vê tudo" — a regra
-- mora em `api/portal_cliente.escopo()` e tem guard próprio. O default de
-- coluna nova em tabela com gente dentro é o caso que decide a segurança da
-- tela inteira: se NULL virasse curinga, criar a coluna teria aberto a
-- operação de todo cliente para todo funcionário no mesmo instante.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS cliente_cnpj_raiz text;

-- O CHECK é a rede: a raiz é OITO DÍGITOS, sem pontuação e sem sufixo de
-- filial. Sem ele, um cadastro com o CNPJ inteiro (14 dígitos) não casaria
-- com filial nenhuma e a tela apareceria VAZIA — falha muda, do tipo que o
-- cliente reporta como "o portal não funciona" e que ninguém reproduz.
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_cliente_raiz_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_cliente_raiz_ck
    CHECK (cliente_cnpj_raiz IS NULL OR cliente_cnpj_raiz ~ '^[0-9]{8}$');

COMMENT ON COLUMN usuarios.cliente_cnpj_raiz IS
    'Raiz do CNPJ (8 dígitos) do cliente cuja operação este login enxerga na
     tela `cliop`. NULL = usuário da casa, SEM escopo de cliente — e quem lê
     recusa, nunca libera. Raiz, não CNPJ inteiro, porque o ERP cadastra uma
     linha por filial e as quatro plantas da Iochpe-Maxion são a mesma empresa.';
