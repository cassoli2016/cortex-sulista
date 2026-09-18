-- Gestão de Motoristas (GMA) — o CADASTRO e a IDENTIDADE do motorista próprio.
--
-- POR QUE ESTA TABELA EXISTE. O modelo de premiação novo (17/09/2026) precisa
-- responder, por motorista e por ciclo: que nota ele tirou na Gobrax, quantas
-- ocorrências teve no ERP, como foi no gerenciamento de risco, e quanto vai
-- receber. São QUATRO fontes, e cada uma chama a mesma pessoa de um jeito:
--
--   folha (Globus/Oracle)  cpfcnpj            -> CPF, 11 dígitos
--   ERP  ocorrências       cnpjcpfcodigo      -> CPF, 11 dígitos (medido: 719/719)
--   ERP  programação       motorista          -> CPF, 11 dígitos (medido: 26.795/26.795)
--   GR   (RasterIntegra)   cpf_motorista      -> CPF com ZEROS À ESQUERDA, 14 dígitos
--   Gobrax                 driverName         -> NOME (a API não devolve documento)
--
-- O CPF é a única chave que atravessa quatro das cinco, e por isso é a chave
-- daqui. O 14 dígitos do GR não é CNPJ: é o CPF preenchido com zeros, e
-- comparado cru ele não casa com NADA — o cruzamento dava zero em 100% das
-- viagens até alguém olhar o tamanho do campo (18/09/2026). A regra é sempre
-- "os 11 dígitos finais", e ela vive em `api/premiacao/identidade.py`.
--
-- A GOBRAX FICA DE FORA DESSA CHAVE, e é o único caso: ela casa por NOME
-- normalizado, com a guarda que a casa já usa — nome que casa com mais de uma
-- pessoa não casa com ninguém. O `driver_id` dela é guardado quando o
-- casamento acontece, para a próxima leitura não depender do nome.
--
-- O QUE É DA FOLHA E O QUE É DA CASA. A folha manda em quem EXISTE e está
-- ativo, na admissão e na lotação — ela é a fonte oficial disso e a decisão de
-- quem opera (18/09/2026) foi essa. Mas ela NÃO SABE dizer quem é rodoviário e
-- quem é manobrista: medido no mesmo dia, as funções ativas são MOT CARRETEIRO
-- (82), MOTORISTA TRUCK (17), MOTORISTA DE ENT (2) e MOTORISTA BITREM (1) —
-- nenhuma de manobra. Como o TIPO decide quanto a pessoa recebe, ele é campo
-- desta tabela: o CÓRTEX SUGERE pela operação (quem tem viagem na programação
-- do ciclo é rodoviário; 73 dos 83 têm) e quem opera confirma ou troca. O que
-- foi decidido à mão (`tipo_origem='manual'`) nunca é sobrescrito pela
-- sincronização — a mesma regra de `prem_ocorrencia_classe`.
--
-- CPF É PII E NÃO SAI DAQUI. Ele é a chave no banco local, como já acontece em
-- `gr_viagem_fim.cpf_motorista` (0035). A tela e as rotas usam o CÓDIGO DO
-- CADASTRO do ERP (`cadastro_codigo`), que é o que o resto da casa já usa para
-- falar de motorista (`mot_vinculos.motorista_codigo`), e nunca o CPF na URL.

CREATE TABLE IF NOT EXISTS prm_motorista (
    cpf              text PRIMARY KEY,
    nome             text NOT NULL,
    -- O código do cadastro do ERP: é ele que aparece em tela e em rota.
    cadastro_codigo  text,
    -- A chapa da folha, para quem for conferir no Globus.
    chapa            text,
    -- RODOVIARIO | MANOBRA. Decide a tabela de valor base do prêmio.
    tipo             text NOT NULL DEFAULT 'RODOVIARIO',
    -- 'sugerido' = o CÓRTEX deduziu da operação; 'manual' = alguém decidiu.
    tipo_origem      text NOT NULL DEFAULT 'sugerido',
    -- A filial da premiação (MTZ, JOI, SBC, CRZ, PSA...), da lotação da folha.
    filial           text,
    filial_origem    text NOT NULL DEFAULT 'folha',
    -- Competência de admissão ('AAAA-MM'): a escada de tempo de casa sai daqui.
    admissao         text,
    -- A função como a folha escreve (truncada em ~16 caracteres pelo Globus).
    funcao           text,
    ativo            integer NOT NULL DEFAULT 1,
    -- O id do motorista na Gobrax, quando o nome casou alguma vez.
    gobrax_driver_id integer,
    sincronizado_em  text,
    atualizado_em    text,
    atualizado_por   text,
    CONSTRAINT prm_motorista_cpf CHECK (cpf ~ '^[0-9]{11}$'),
    CONSTRAINT prm_motorista_tipo CHECK (tipo IN ('RODOVIARIO', 'MANOBRA')),
    CONSTRAINT prm_motorista_tipo_origem CHECK (tipo_origem IN ('sugerido', 'manual')),
    CONSTRAINT prm_motorista_filial_origem CHECK (filial_origem IN ('folha', 'manual')),
    CONSTRAINT prm_motorista_admissao CHECK (admissao IS NULL OR admissao ~ '^[0-9]{4}-[0-9]{2}$')
);

CREATE INDEX IF NOT EXISTS prm_motorista_ativo ON prm_motorista(ativo, tipo);
CREATE INDEX IF NOT EXISTS prm_motorista_cadastro ON prm_motorista(cadastro_codigo);

COMMENT ON TABLE prm_motorista IS
    'Quem é motorista próprio, de que tipo, de que filial e desde quando.
     A folha do Globus manda em existência, situação, admissão e lotação; o
     tipo (rodoviário × manobrista) é decisão de quem opera, porque a folha não
     tem essa função. CPF é a chave porque é o que atravessa folha, ERP e GR —
     e não sai em URL nem em tela.';

COMMENT ON COLUMN prm_motorista.tipo_origem IS
    'sugerido = deduzido da operação (teve viagem no ciclo); manual = alguém
     decidiu na tela. A sincronização com a folha NUNCA sobrescreve manual —
     a mesma regra que protege a classificação de ocorrências.';

COMMENT ON COLUMN prm_motorista.gobrax_driver_id IS
    'Guardado quando o nome normalizado casou com um motorista da Gobrax. Nome
     ambíguo (que casa com mais de uma pessoa) não casa com ninguém, e este
     campo fica nulo — é a guarda que já vale em api/motorista/desempenho.py.';

-- A TRILHA DA SINCRONIZAÇÃO. Uma linha por passagem, inclusive a que não mudou
-- nada e a que falhou: sem isso, "o cadastro está velho" e "a folha está fora
-- do ar" ficam iguais — e o segundo é o que tem conserto.
CREATE TABLE IF NOT EXISTS prm_motorista_carga (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    iniciado_em   text NOT NULL,
    terminado_em  text,
    fonte         text NOT NULL DEFAULT 'folha',
    lidos         integer NOT NULL DEFAULT 0,
    novos         integer NOT NULL DEFAULT 0,
    atualizados   integer NOT NULL DEFAULT 0,
    desligados    integer NOT NULL DEFAULT 0,
    erro          text
);

CREATE INDEX IF NOT EXISTS prm_motorista_carga_ts ON prm_motorista_carga(iniciado_em DESC);

COMMENT ON TABLE prm_motorista_carga IS
    'Toda passagem da sincronização com a folha, inclusive a que falhou. É daqui
     que a Saúde do Servidor descobre que o cadastro parou de ser atualizado.';
