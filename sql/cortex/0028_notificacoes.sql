-- Notificações: o que o CÓRTEX tem a dizer a UMA pessoa.
--
-- O QUE ESTA TABELA GUARDA, E O QUE ELA DELIBERADAMENTE NÃO GUARDA
-- ===============================================================
-- Ela guarda **o que a pessoa já viu**, e só isso. A notificação em si NÃO é
-- gravada: ela é DERIVADA a cada leitura, do estado que já existe no sistema.
--
-- O boas-vindas é o primeiro caso e ilustra a regra: ele existe enquanto a
-- pessoa não o dispensou, e some quando ela dispensa. Não há linha nenhuma
-- dizendo "fulano tem um boas-vindas pendente" — haveria uma rotina para criar
-- essa linha, e no dia em que ela não rodasse o usuário novo entraria sem
-- receber nada, sem ninguém saber. É a mesma escolha do atraso de ação da
-- Gestão, da vigência de contrato do CRM e do "cliente ativo" lido do
-- faturamento: estado que envelhece sozinho se CALCULA, não se grava.
--
-- POR QUE NO SERVIDOR E NÃO NO NAVEGADOR
-- ======================================
-- `localStorage` seria uma linha de código e estaria errado: é por navegador,
-- não por pessoa. O boas-vindas reapareceria no celular, no outro computador e
-- depois de limpar o cache — e sumiria para sempre se a pessoa lesse num
-- navegador anônimo. "Já vi isso" é fato sobre a PESSOA.
--
-- A CHAVE É TEXTO, E É ISSO QUE FAZ A TABELA SERVIR PARA O PRÓXIMO CASO
-- ====================================================================
-- `chave` identifica a notificação de forma estável e legível
-- (`boas_vindas`, e amanhã o que for). Um id numérico exigiria uma tabela de
-- catálogo para nada; e uma coluna booleana por tipo (`viu_boas_vindas`)
-- obrigaria uma migration a cada notificação nova, que é exatamente o que se
-- quer evitar num lugar por onde vão passar muitas.
--
-- A chave é ÚNICA POR USUÁRIO: dispensar duas vezes não cria duas linhas, e o
-- `ON CONFLICT DO NOTHING` da escrita depende disso. Sem o UNIQUE, um clique
-- duplo no botão deixaria duas linhas e a contagem de não lidas continuaria
-- certa por acaso — até alguém precisar contar dispensas.

CREATE TABLE IF NOT EXISTS not_lidas (
    id          serial PRIMARY KEY,
    usuario_id  integer     NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    chave       text        NOT NULL,
    lida_em     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT not_lidas_chave_ck CHECK (btrim(chave) <> ''),
    CONSTRAINT not_lidas_unica UNIQUE (usuario_id, chave)
);

-- `ON DELETE CASCADE` porque a marca não sobrevive à pessoa: sem ele, excluir
-- usuário passa a falhar por chave estrangeira — e isso só aparece no dia da
-- exclusão, que é tarde. Mesma lição da tabela de fotos.

-- A consulta que roda a CADA carga da tela é "o que este usuário já leu".
CREATE INDEX IF NOT EXISTS not_lidas_usuario_ix
    ON not_lidas (usuario_id);
