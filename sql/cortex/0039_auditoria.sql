-- 0039 · Auditoria de USO: quem entrou, por quanto tempo e em que telas.
--
-- O `audit_log` responde "quem MEXEU no sistema" — toda escrita passa por ele
-- desde o começo. O que ele não responde é "quem USA o sistema": 391 logins
-- para 11 logouts mostram que ninguém sai pelo botão, então tempo de sessão
-- medido por login→logout teria 3% de amostra e mentiria com cara de número.
--
-- Daí duas tabelas, e não uma coluna a mais no audit_log: a trilha de ações é
-- append-only e imutável por natureza (é prova do que aconteceu), enquanto a
-- sessão é uma linha VIVA, que recebe "visto por último" enquanto a pessoa
-- trabalha. Misturar as duas naturezas na mesma tabela estragaria as duas.
--
-- O QUE NÃO SE GRAVA, de propósito: parâmetro de consulta, filtro, conteúdo de
-- tela, corpo de requisição. Só a CHAVE da tela (`home`, `dre`) e o horário.
-- Auditoria de uso existe para dimensionar e achar tela morta, não para
-- reconstituir o que cada pessoa leu.

-- Uma linha por SESSÃO (um login). `fim` só é preenchido quando a saída é
-- EXPLÍCITA (botão sair, troca de senha, sessão derrubada). Sessão abandonada
-- fica com `fim` nulo para sempre, e isso é correto: a duração dela é até o
-- `visto_em`, que é o último instante em que se sabe que a pessoa estava lá.
--
-- "Está aberta agora?" NÃO É COLUNA. É `fim IS NULL AND visto_em > agora - N`,
-- calculado na leitura — status gravado precisa de rotina para virar, e no dia
-- em que ela não roda a tela mente (regra da casa).
CREATE TABLE IF NOT EXISTS aud_sessoes(
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id integer REFERENCES usuarios(id) ON DELETE SET NULL,
    email      text    NOT NULL,      -- guardado à parte: usuário excluído não apaga a história
    inicio     text    NOT NULL,
    visto_em   text    NOT NULL,      -- último sinal de vida (heartbeat da navegação)
    fim        text,                  -- só em saída explícita
    fim_motivo text,                  -- logout | troca_senha | derrubada
    ip         text    NOT NULL DEFAULT '',
    agente     text    NOT NULL DEFAULT ''   -- user-agent CURTO (navegador/SO), não a string inteira
);
CREATE INDEX IF NOT EXISTS ix_aud_sessoes_inicio ON aud_sessoes(inicio);
CREATE INDEX IF NOT EXISTS ix_aud_sessoes_email ON aud_sessoes(email, inicio);
-- as sessões ainda de pé, que é a pergunta mais frequente da tela
CREATE INDEX IF NOT EXISTS ix_aud_sessoes_abertas ON aud_sessoes(visto_em) WHERE fim IS NULL;

-- Telas abertas, AGREGADAS por (sessão, tela). Uma linha por tela por sessão,
-- com o contador de aberturas — não uma linha por clique. Quem navega entre
-- duas telas trinta vezes numa tarde gera 2 linhas, não 30, e as perguntas que
-- a tela faz ("quais telas se usa", "quais ninguém abre", "quantas pessoas
-- distintas") são as mesmas com um centésimo do volume.
CREATE TABLE IF NOT EXISTS aud_telas(
    sessao_id  integer NOT NULL REFERENCES aud_sessoes(id) ON DELETE CASCADE,
    tela       text    NOT NULL,
    aberturas  integer NOT NULL DEFAULT 1,
    primeira   text    NOT NULL,
    ultima     text    NOT NULL,
    PRIMARY KEY(sessao_id, tela)
);
CREATE INDEX IF NOT EXISTS ix_aud_telas_tela ON aud_telas(tela, ultima);
