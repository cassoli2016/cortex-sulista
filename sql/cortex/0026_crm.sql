-- CRM comercial — contas, contatos, oportunidades por LANE, atividades,
-- interações e contratos. Escrita do CÓRTEX, banco local.
--
-- O CÓRTEX já tinha uma tela de CRM: leitura de três tabelas do AVA
-- (`sulista.gestaocomercial`, `pipelineprojetos`, `pipelineprojetos_repactuacoes`).
-- Ela CONTINUA, intocada, numa sub-aba — é o registro histórico do que o time
-- comercial preencheu no ERP, e apagá-lo para "migrar" produziria duas verdades
-- sobre o mesmo lead sem que ninguém tivesse pedido. Aqui não se copia nada de
-- lá: o CRM novo nasce vazio, e o vínculo entre os dois mundos é o
-- `crm_contas.ava_agrupamento` — o grupo econômico do ERP, que é por onde entra
-- a RECEITA REAL.
--
-- Cinco decisões estruturam o schema inteiro, e cada uma custou uma escolha:
--
-- 1. NÃO EXISTE COLUNA "É CLIENTE". Prospect, cliente ativo e ex-cliente são
--    derivados do faturamento real do AVA na leitura: sem `ava_agrupamento` é
--    prospect; com vínculo e viagem recente é ativo; com vínculo e nada há N
--    dias é carteira parada — que é exatamente o registro que ninguém cobra
--    quando o status está gravado como "cliente" desde 2024. É a mesma regra
--    do `ges_acoes`, que não tem status "atrasada", e do marcador de manutenção
--    preventiva parado em 77.534 km com o odômetro em 531.970.
--
-- 2. A UNIDADE DO NEGÓCIO É A LANE, NÃO A OPORTUNIDADE. Em FTL ninguém vende
--    "R$ 400 mil/mês": vende Joinville→Betim, carreta de 6 eixos, 22 viagens no
--    mês, R$ 4.800 a viagem. É na lane que existe km, e portanto R$/km, piso
--    mínimo da ANTT e margem contra o CKM. Uma oportunidade com valor global
--    não responde "esse frete paga o piso?" — que é a pergunta que pode tornar
--    o negócio ilegal, não só ruim.
--
-- 3. TAREFA E INTERAÇÃO SÃO TABELAS DIFERENTES. `crm_atividades` é o
--    COMPROMISSO futuro (ligar dia 12), mutável, com atraso derivado.
--    `crm_interacoes` é o que ACONTECEU, append-only. Numa tabela só, editar o
--    registro de uma visita para virar "tarefa concluída" apaga a prova de que
--    a visita houve — e o histórico do relacionamento é o ativo do CRM.
--
-- 4. VIGÊNCIA DE CONTRATO TAMBÉM É DERIVADA. Grava-se `inicio`, `fim` e
--    `cancelado_em`; "vigente", "vence em 40 dias" e "vencido" saem da data de
--    hoje. Status de vigência gravado é a mesma armadilha do item 1, com a
--    diferença de que aqui o custo é um contrato que renovou sozinho por
--    inércia.
--
-- 5. O PAR (usuario_id, nome) SE REPETE, e é de propósito — é a convenção da
--    casa desde `ges_acoes`. Id quando a pessoa tem login (é o que monta "minha
--    carteira" e manda a cobrança ao e-mail certo), nome quando não tem, e o
--    nome gravado JUNTO do id para sobreviver a `ON DELETE SET NULL`.


-- ------------------------------------------------------------------ contas --
-- A empresa. Prospect e cliente moram na MESMA tabela porque são a mesma
-- empresa em momentos diferentes — separá-los obrigaria a "converter" o
-- registro no fechamento, que é onde se perde o histórico de prospecção
-- justamente da conta que deu certo.
--
-- `ava_agrupamento` é o `agrupamentocliente.codigo` do ERP, que é o GRUPO
-- ECONÔMICO — não o CNPJ. É a chave que o CÓRTEX inteiro já usa para cliente
-- (DRE por Cliente, Consulta de Cliente, meta de faturamento), e casar por
-- outra coisa aqui criaria um quarto recorte de receita numa casa que já tem
-- três. `ava_nome` guarda a descrição junto, pelo mesmo motivo do par
-- id/nome: o AVA é réplica de terceiro e pode sumir com o código.
CREATE TABLE IF NOT EXISTS crm_contas(
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome             text    NOT NULL,
    nome_fantasia    text    NOT NULL DEFAULT '',
    cnpj             text    NOT NULL DEFAULT '',
    ava_agrupamento  integer,
    ava_nome         text    NOT NULL DEFAULT '',
    segmento         text    NOT NULL DEFAULT '',
    origem           text    NOT NULL DEFAULT '',
    cidade           text    NOT NULL DEFAULT '',
    uf               text    NOT NULL DEFAULT '',
    site             text    NOT NULL DEFAULT '',
    dono_id          integer REFERENCES usuarios(id) ON DELETE SET NULL,
    dono_nome        text    NOT NULL DEFAULT '',
    observacoes      text    NOT NULL DEFAULT '',
    arquivada        integer NOT NULL DEFAULT 0,
    criado_por       text    NOT NULL DEFAULT '',
    criado_em        text    NOT NULL DEFAULT '',
    alterado_por     text    NOT NULL DEFAULT '',
    alterado_em      text    NOT NULL DEFAULT '',
    CONSTRAINT crm_contas_dono_ck
        CHECK (dono_id IS NOT NULL OR dono_nome <> ''),
    CONSTRAINT crm_contas_uf_ck
        CHECK (uf = '' OR uf ~ '^[A-Z]{2}$'),
    CONSTRAINT crm_contas_arquivada_ck
        CHECK (arquivada IN (0, 1))
);

-- Uma conta por grupo econômico do ERP. UNIQUE PARCIAL porque prospect tem
-- `ava_agrupamento` NULL e no Postgres NULL nunca colide com NULL — sem o
-- `WHERE`, o índice não restringiria nada e duas contas poderiam apontar para
-- o mesmo cliente, cada uma com metade das oportunidades. É a mesma armadilha
-- que duplicou 55 mil linhas de inconformidade da RasterJOR.
CREATE UNIQUE INDEX IF NOT EXISTS ux_crm_contas_ava
    ON crm_contas(ava_agrupamento) WHERE ava_agrupamento IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_crm_contas_nome ON crm_contas(lower(nome));
CREATE INDEX IF NOT EXISTS ix_crm_contas_dono ON crm_contas(dono_id);

COMMENT ON TABLE crm_contas IS
    'Empresa do CRM — prospect e cliente na mesma tabela. NÃO existe coluna de
     situação: prospect/ativo/parado é derivado do faturamento real do AVA via
     ava_agrupamento. Status gravado envelhece sozinho e mente.';
COMMENT ON COLUMN crm_contas.ava_agrupamento IS
    'agrupamentocliente.codigo do ERP (grupo econômico) — a chave por onde
     entra a receita real. NULL enquanto a conta for só prospect.';
COMMENT ON COLUMN crm_contas.arquivada IS
    'Tira da lista sem apagar. Excluir conta apagaria em cascata o histórico de
     interações, que é o ativo do CRM.';


-- ---------------------------------------------------------------- contatos --
-- PII: e-mail e telefone de pessoa física. Ficam aqui porque um CRM sem
-- telefone do comprador não é um CRM — mas NÃO saem para a Claude API nem para
-- o snapshot do Copiloto (regra CLAUDE.md §8.3), e a tela mostra o telefone só
-- na ficha, nunca em lista aberta.
--
-- `telefone` é gravado NORMALIZADO pelo validador do WhatsApp
-- (`api/whatsapp/numeros.py`), e isso não é formatação: é o que garante que o
-- número cadastrado aqui seja o mesmo que o envio aceita. Duas noções de
-- "telefone válido" na casa dão número que o cadastro aceita e o disparo
-- recusa — descoberto na hora em que a mensagem não chega.
CREATE TABLE IF NOT EXISTS crm_contatos(
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id     integer NOT NULL REFERENCES crm_contas(id) ON DELETE CASCADE,
    nome         text    NOT NULL,
    cargo        text    NOT NULL DEFAULT '',
    papel        text    NOT NULL DEFAULT 'operacional',
    email        text    NOT NULL DEFAULT '',
    telefone     text    NOT NULL DEFAULT '',
    principal    integer NOT NULL DEFAULT 0,
    ativo        integer NOT NULL DEFAULT 1,
    observacoes  text    NOT NULL DEFAULT '',
    criado_por   text    NOT NULL DEFAULT '',
    criado_em    text    NOT NULL DEFAULT '',
    alterado_por text    NOT NULL DEFAULT '',
    alterado_em  text    NOT NULL DEFAULT '',
    CONSTRAINT crm_contatos_papel_ck
        CHECK (papel IN ('decisor', 'influenciador', 'operacional',
                         'financeiro', 'comprador')),
    CONSTRAINT crm_contatos_principal_ck CHECK (principal IN (0, 1)),
    CONSTRAINT crm_contatos_ativo_ck     CHECK (ativo IN (0, 1))
);

CREATE INDEX IF NOT EXISTS ix_crm_contatos_conta ON crm_contatos(conta_id, ativo);

COMMENT ON COLUMN crm_contatos.papel IS
    'Quem decide, quem influencia, quem opera. Existe porque follow-up com o
     operacional não fecha contrato e follow-up só com o decisor não sobrevive
     à troca de diretoria — a tela cobra ter ao menos um decisor mapeado.';
COMMENT ON COLUMN crm_contatos.telefone IS
    'NORMALIZADO por api/whatsapp/numeros.py. Guardar como a pessoa digitou
     faria o cadastro aceitar número que o envio recusa.';


-- ----------------------------------------------------------- oportunidades --
-- O negócio em andamento. `codigo` é a referência HUMANA (OPO-2026-014), pelo
-- mesmo motivo do `codigo` de `ges_reunioes`: é assim que a oportunidade é
-- citada em e-mail e em reunião, e "a #43" não sobrevive a uma restauração de
-- backup que reordene ids.
--
-- `receita_mensal_manual` existe e é EXCEÇÃO, não a regra. A receita normal é a
-- soma das lanes (`valor_viagem × viagens_mes`), calculada na leitura; o campo
-- manual só é lido quando a oportunidade AINDA não tem lane, que é o estado
-- legítimo de uma oportunidade recém-aberta em qualificação. Gravar a soma
-- criaria um total que discorda das próprias linhas no dia em que alguém
-- editar uma lane — o defeito clássico de total desnormalizado.
--
-- `probabilidade` é separada do estágio de propósito: o estágio dá o padrão
-- (é o que a casa usa quando ninguém opinou), mas o vendedor que sabe que
-- aquela proposta está parada há 40 dias precisa poder dizer 20% numa
-- oportunidade em "negociação". Previsão ponderada com probabilidade fixa por
-- estágio é previsão do PROCESSO, não do negócio.
CREATE TABLE IF NOT EXISTS crm_oportunidades(
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id              integer NOT NULL REFERENCES crm_contas(id) ON DELETE CASCADE,
    ano                   integer NOT NULL,
    sequencia             integer NOT NULL,
    codigo                text    NOT NULL,
    titulo                text    NOT NULL,
    tipo                  text    NOT NULL DEFAULT 'contrato',
    estagio               text    NOT NULL DEFAULT 'qualificacao',
    probabilidade         integer,
    receita_mensal_manual numeric(14,2),
    meses_contrato        integer,
    dono_id               integer REFERENCES usuarios(id) ON DELETE SET NULL,
    dono_nome             text    NOT NULL DEFAULT '',
    abertura              date    NOT NULL,
    previsao_fechamento   date,
    fechada_em            date,
    motivo_perda          text    NOT NULL DEFAULT '',
    perda_detalhe         text    NOT NULL DEFAULT '',
    concorrente           text    NOT NULL DEFAULT '',
    observacoes           text    NOT NULL DEFAULT '',
    criado_por            text    NOT NULL DEFAULT '',
    criado_em             text    NOT NULL DEFAULT '',
    alterado_por          text    NOT NULL DEFAULT '',
    alterado_em           text    NOT NULL DEFAULT '',
    CONSTRAINT crm_opo_seq_uk UNIQUE (ano, sequencia),
    CONSTRAINT crm_opo_dono_ck
        CHECK (dono_id IS NOT NULL OR dono_nome <> ''),
    CONSTRAINT crm_opo_tipo_ck
        CHECK (tipo IN ('spot', 'contrato', 'renovacao', 'expansao', 'bid')),
    CONSTRAINT crm_opo_estagio_ck
        CHECK (estagio IN ('qualificacao', 'levantamento', 'proposta',
                           'negociacao', 'ganha', 'perdida')),
    CONSTRAINT crm_opo_prob_ck
        CHECK (probabilidade IS NULL OR probabilidade BETWEEN 0 AND 100),
    CONSTRAINT crm_opo_meses_ck
        CHECK (meses_contrato IS NULL OR meses_contrato BETWEEN 1 AND 120),
    -- Perda sem motivo é a perda que não ensina nada. O CHECK obriga a escolha
    -- no único momento em que alguém ainda lembra por que perdeu.
    CONSTRAINT crm_opo_perda_ck
        CHECK (estagio <> 'perdida' OR motivo_perda <> ''),
    CONSTRAINT crm_opo_motivo_ck
        CHECK (motivo_perda IN ('', 'preco', 'prazo', 'capacidade',
                                'concorrente', 'sem_orcamento', 'sem_retorno',
                                'requisito_tecnico', 'area_nao_atendida',
                                'nao_qualificado', 'outro')),
    -- Fechada (ganha/perdida) exige data, e aberta não pode ter: é dela que
    -- sai o tempo de ciclo, e um dos dois lados errado faz a média mentir sem
    -- que nada pareça errado.
    CONSTRAINT crm_opo_fechada_ck
        CHECK ((estagio IN ('ganha', 'perdida')) = (fechada_em IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ix_crm_opo_conta   ON crm_oportunidades(conta_id);
CREATE INDEX IF NOT EXISTS ix_crm_opo_estagio ON crm_oportunidades(estagio, previsao_fechamento);
CREATE INDEX IF NOT EXISTS ix_crm_opo_dono    ON crm_oportunidades(dono_id, estagio);

COMMENT ON TABLE crm_oportunidades IS
    'Negócio em andamento. A receita NÃO é gravada: sai da soma das lanes
     (crm_lanes). receita_mensal_manual só vale enquanto não houver lane.';
COMMENT ON COLUMN crm_oportunidades.fechada_em IS
    'Carimbo do fechamento — é dele que sai o tempo de ciclo. Volta a NULL se a
     oportunidade for reaberta, como concluida_em de ges_acoes.';
COMMENT ON COLUMN crm_oportunidades.motivo_perda IS
    'Obrigatório quando perdida (CHECK). Perda sem motivo catalogado não vira
     aprendizado nenhum — e é o único dado que diz se o problema é preço ou
     capacidade.';


-- ------------------------------------------------------------------- lanes --
-- A UNIDADE REAL DO FTL: um par origem→destino com veículo, volume e preço.
--
-- A mesma tabela serve a oportunidade (preço PROPOSTO) e ao contrato (preço
-- VIGENTE), com CHECK de "exatamente um dos dois". São o mesmo conceito em dois
-- momentos, e duas tabelas idênticas produziriam duas implementações do cálculo
-- de R$/km e do piso da ANTT — que é justamente o número que não pode divergir
-- entre a proposta e o contrato assinado.
--
-- NADA DERIVADO É GRAVADO: R$/km, receita/mês, piso mínimo e margem saem do
-- serviço na leitura. O piso da ANTT em especial NÃO PODE ser gravado — ele
-- depende da tabela vigente NA DATA, que muda duas vezes por ano, e um piso
-- congelado em março reprovaria em agosto um frete correto (ou o contrário,
-- que é pior).
--
-- `eixos` e `tipo_carga` existem só para alimentar o cálculo do piso
-- (`api/antt/piso.py`). Sem eles o piso não é zero: é "não calculável", e a
-- tela diz isso — acusar de irregular com base em desconhecido é pior do que
-- não medir.
CREATE TABLE IF NOT EXISTS crm_lanes(
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    oportunidade_id  integer REFERENCES crm_oportunidades(id) ON DELETE CASCADE,
    contrato_id      integer,
    origem_cidade    text    NOT NULL DEFAULT '',
    origem_uf        text    NOT NULL DEFAULT '',
    destino_cidade   text    NOT NULL DEFAULT '',
    destino_uf       text    NOT NULL DEFAULT '',
    km               numeric(10,1),
    km_vazio         numeric(10,1),
    tipo_veiculo     text    NOT NULL DEFAULT '',
    eixos            integer,
    tipo_carga       text    NOT NULL DEFAULT '',
    viagens_mes      numeric(8,1),
    valor_viagem     numeric(14,2),
    pedagio          numeric(14,2),
    observacoes      text    NOT NULL DEFAULT '',
    ordem            integer NOT NULL DEFAULT 0,
    CONSTRAINT crm_lanes_dono_ck
        CHECK ((oportunidade_id IS NULL) <> (contrato_id IS NULL)),
    CONSTRAINT crm_lanes_eixos_ck
        CHECK (eixos IS NULL OR eixos BETWEEN 2 AND 9),
    CONSTRAINT crm_lanes_km_ck
        CHECK (km IS NULL OR (km > 0 AND km <= 6000)),
    CONSTRAINT crm_lanes_kmv_ck
        CHECK (km_vazio IS NULL OR (km_vazio >= 0 AND km_vazio <= 6000)),
    CONSTRAINT crm_lanes_viagens_ck
        CHECK (viagens_mes IS NULL OR (viagens_mes > 0 AND viagens_mes <= 2000)),
    CONSTRAINT crm_lanes_uf_ck
        CHECK ((origem_uf = '' OR origem_uf ~ '^[A-Z]{2}$')
           AND (destino_uf = '' OR destino_uf ~ '^[A-Z]{2}$'))
);

CREATE INDEX IF NOT EXISTS ix_crm_lanes_opo ON crm_lanes(oportunidade_id, ordem);
CREATE INDEX IF NOT EXISTS ix_crm_lanes_ctr ON crm_lanes(contrato_id, ordem);

COMMENT ON TABLE crm_lanes IS
    'Origem→destino com veículo, volume e preço — a unidade do FTL. Serve à
     oportunidade (preço proposto) e ao contrato (preço vigente); CHECK garante
     exatamente um dono. R$/km, piso ANTT e margem são DERIVADOS na leitura.';
COMMENT ON COLUMN crm_lanes.km IS
    'Teto de 6.000 km por viagem: acima disso a leitura é que está furada, não
     a rota. Mesma régua física do combustível (0,8–6,0 km/l) e da jornada
     (1.500 km/dia) — validar faixa impede o dado espúrio de virar gráfico.';
COMMENT ON COLUMN crm_lanes.eixos IS
    'Só para o piso da ANTT (Res. 5.867/2020). NULL não é zero: é piso "não
     calculável", e a tela diz isso em vez de aprovar o frete calado.';


-- -------------------------------------------------------------- atividades --
-- O COMPROMISSO: o que alguém vai fazer, até quando. Mutável.
--
-- NÃO EXISTE STATUS "ATRASADA" — atraso é `quando < hoje AND status='aberta'`,
-- derivado a cada leitura, exatamente como em `ges_acoes`. Escrever aqui a
-- terceira cópia dessa regra seria a terceira chance de alguém "otimizar" para
-- um status gravado que só está certo enquanto uma rotina roda.
CREATE TABLE IF NOT EXISTS crm_atividades(
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id         integer REFERENCES crm_contas(id) ON DELETE CASCADE,
    oportunidade_id  integer REFERENCES crm_oportunidades(id) ON DELETE CASCADE,
    contato_id       integer REFERENCES crm_contatos(id) ON DELETE SET NULL,
    tipo             text    NOT NULL DEFAULT 'ligacao',
    assunto          text    NOT NULL,
    detalhe          text    NOT NULL DEFAULT '',
    quando           date    NOT NULL,
    hora             text    NOT NULL DEFAULT '',
    responsavel_id   integer REFERENCES usuarios(id) ON DELETE SET NULL,
    responsavel_nome text    NOT NULL DEFAULT '',
    status           text    NOT NULL DEFAULT 'aberta',
    concluida_em     text,
    criado_por       text    NOT NULL DEFAULT '',
    criado_em        text    NOT NULL DEFAULT '',
    alterado_por     text    NOT NULL DEFAULT '',
    alterado_em      text    NOT NULL DEFAULT '',
    CONSTRAINT crm_ativ_quem_ck
        CHECK (responsavel_id IS NOT NULL OR responsavel_nome <> ''),
    CONSTRAINT crm_ativ_alvo_ck
        CHECK (conta_id IS NOT NULL OR oportunidade_id IS NOT NULL),
    CONSTRAINT crm_ativ_tipo_ck
        CHECK (tipo IN ('ligacao', 'visita', 'reuniao', 'email', 'whatsapp',
                        'proposta', 'cotacao', 'outro')),
    CONSTRAINT crm_ativ_status_ck
        CHECK (status IN ('aberta', 'concluida', 'cancelada')),
    CONSTRAINT crm_ativ_concl_ck
        CHECK ((status = 'concluida') = (concluida_em IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ix_crm_ativ_agenda ON crm_atividades(status, quando);
CREATE INDEX IF NOT EXISTS ix_crm_ativ_resp   ON crm_atividades(responsavel_id, status, quando);
CREATE INDEX IF NOT EXISTS ix_crm_ativ_conta  ON crm_atividades(conta_id);
CREATE INDEX IF NOT EXISTS ix_crm_ativ_opo    ON crm_atividades(oportunidade_id);

COMMENT ON TABLE crm_atividades IS
    'Compromisso futuro (ligar, visitar, mandar proposta). NÃO existe status
     "atrasada": atraso é quando < hoje AND status = aberta, derivado na
     leitura. Mesma regra de ges_acoes.';


-- --------------------------------------------------------------- interações --
-- O QUE ACONTECEU. Append-only, como `ges_andamentos` — interação editável
-- deixa de ser prova de que o contato houve, e é esse histórico que responde
-- "há quanto tempo ninguém fala com esse cliente", que é a pergunta que o CRM
-- existe para responder.
--
-- `zap_envio_id` liga a interação à trilha do WhatsApp da casa (`zap_envios`).
-- SEM chave estrangeira, de propósito: `zap_envios` é a trilha de auditoria do
-- que saiu para fora da empresa e não pode ganhar uma dependência que impeça
-- sua própria manutenção; e a interação continua verdadeira mesmo que a linha
-- da trilha seja arquivada. O que se guarda é a referência, não a integridade.
CREATE TABLE IF NOT EXISTS crm_interacoes(
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id         integer NOT NULL REFERENCES crm_contas(id) ON DELETE CASCADE,
    oportunidade_id  integer REFERENCES crm_oportunidades(id) ON DELETE SET NULL,
    contato_id       integer REFERENCES crm_contatos(id) ON DELETE SET NULL,
    canal            text    NOT NULL DEFAULT 'ligacao',
    sentido          text    NOT NULL DEFAULT 'saida',
    ts               text    NOT NULL,
    usuario          text    NOT NULL DEFAULT '',
    resumo           text    NOT NULL DEFAULT '',
    zap_envio_id     integer,
    automatica       integer NOT NULL DEFAULT 0,
    CONSTRAINT crm_inter_canal_ck
        CHECK (canal IN ('ligacao', 'visita', 'reuniao', 'email', 'whatsapp',
                         'proposta', 'outro')),
    CONSTRAINT crm_inter_sentido_ck
        CHECK (sentido IN ('entrada', 'saida')),
    CONSTRAINT crm_inter_auto_ck CHECK (automatica IN (0, 1))
);

CREATE INDEX IF NOT EXISTS ix_crm_inter_conta ON crm_interacoes(conta_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_crm_inter_opo   ON crm_interacoes(oportunidade_id, ts DESC);

COMMENT ON TABLE crm_interacoes IS
    'Histórico do relacionamento, append-only. É daqui que sai "há quanto tempo
     ninguém fala com este cliente" — a pergunta central do CRM.';
COMMENT ON COLUMN crm_interacoes.automatica IS
    'Registrada pelo sistema (envio de WhatsApp/e-mail pelo CÓRTEX) e não
     digitada por alguém. Distinguir importa: uma conta com 40 interações
     automáticas e nenhuma humana está sendo notificada, não atendida.';


-- --------------------------------------------------------------- contratos --
-- Vigência, reajuste e a tabela de preço (via `crm_lanes.contrato_id`).
--
-- NÃO EXISTE COLUNA DE STATUS. Vigente, a vencer e vencido saem de `inicio`,
-- `fim` e da data de hoje; o único fato gravado é `cancelado_em`, porque
-- rescisão é um evento, não uma passagem do tempo. A regra do item 4 do
-- cabeçalho, e o custo de errá-la é um contrato que renova sozinho por inércia
-- enquanto a tela diz "vigente" porque alguém marcou isso em 2024.
--
-- `mes_reajuste` + `ultimo_reajuste` respondem "o reajuste deste ano já foi
-- aplicado?" sem gravar a resposta — que é o mesmo padrão. Um contrato cujo
-- mês de reajuste já passou sem `ultimo_reajuste` naquele ciclo é dinheiro
-- parado na mesa, e é isso que a tela mostra.
CREATE TABLE IF NOT EXISTS crm_contratos(
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id             integer NOT NULL REFERENCES crm_contas(id) ON DELETE CASCADE,
    oportunidade_id      integer REFERENCES crm_oportunidades(id) ON DELETE SET NULL,
    ano                  integer NOT NULL,
    sequencia            integer NOT NULL,
    codigo               text    NOT NULL,
    objeto               text    NOT NULL,
    inicio               date    NOT NULL,
    fim                  date,
    renovacao_automatica integer NOT NULL DEFAULT 0,
    aviso_previo_dias    integer,
    indice_reajuste      text    NOT NULL DEFAULT 'negociado',
    mes_reajuste         integer,
    ultimo_reajuste      date,
    percentual_ultimo    numeric(6,2),
    prazo_pagamento_dias integer,
    dono_id              integer REFERENCES usuarios(id) ON DELETE SET NULL,
    dono_nome            text    NOT NULL DEFAULT '',
    cancelado_em         date,
    cancelado_motivo     text    NOT NULL DEFAULT '',
    observacoes          text    NOT NULL DEFAULT '',
    criado_por           text    NOT NULL DEFAULT '',
    criado_em            text    NOT NULL DEFAULT '',
    alterado_por         text    NOT NULL DEFAULT '',
    alterado_em          text    NOT NULL DEFAULT '',
    CONSTRAINT crm_ctr_seq_uk UNIQUE (ano, sequencia),
    -- Valores em MINÚSCULA, sem exceção. `IPCA` seria mais bonito de ler no
    -- banco e é justamente a armadilha: o validador da casa normaliza a
    -- escolha para minúscula (`api/validacao.escolha`), então um domínio de
    -- caixa mista recusa o valor que a própria tela mandou. O rótulo bonito
    -- vive em `ROTULO_INDICE`, que é onde ele serve para alguma coisa.
    CONSTRAINT crm_ctr_indice_ck
        CHECK (indice_reajuste IN ('ipca', 'igpm', 'inpc', 'diesel',
                                   'negociado', 'sem_reajuste')),
    CONSTRAINT crm_ctr_mes_ck
        CHECK (mes_reajuste IS NULL OR mes_reajuste BETWEEN 1 AND 12),
    CONSTRAINT crm_ctr_fim_ck
        CHECK (fim IS NULL OR fim >= inicio),
    CONSTRAINT crm_ctr_renov_ck CHECK (renovacao_automatica IN (0, 1)),
    CONSTRAINT crm_ctr_cancel_ck
        CHECK (cancelado_em IS NULL OR cancelado_motivo <> '')
);

CREATE INDEX IF NOT EXISTS ix_crm_ctr_conta ON crm_contratos(conta_id);
CREATE INDEX IF NOT EXISTS ix_crm_ctr_fim   ON crm_contratos(fim);

COMMENT ON TABLE crm_contratos IS
    'Contrato com vigência e regra de reajuste. NÃO tem coluna de status:
     vigente/a vencer/vencido é derivado de inicio, fim e hoje. Só a rescisão
     (cancelado_em) é fato gravado, porque é evento e não passagem do tempo.';
COMMENT ON COLUMN crm_contratos.mes_reajuste IS
    'Mês do reajuste anual. Junto de ultimo_reajuste responde "o reajuste deste
     ciclo já saiu?" sem gravar a resposta — reajuste esquecido é o dinheiro
     que fica na mesa sem ninguém ver.';

-- A FK do contrato nas lanes entra DEPOIS de `crm_contratos` existir: a tabela
-- é criada antes por causa da ordem de leitura (lane é conceito de negócio,
-- contrato é o papel), e um `REFERENCES` para tabela inexistente aborta a
-- migration inteira. `DO $$` porque `ADD CONSTRAINT` não tem `IF NOT EXISTS`
-- no Postgres 16, e a migration precisa ser idempotente como todas as outras.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'crm_lanes_contrato_fk') THEN
        ALTER TABLE crm_lanes
            ADD CONSTRAINT crm_lanes_contrato_fk
            FOREIGN KEY (contrato_id) REFERENCES crm_contratos(id)
            ON DELETE CASCADE;
    END IF;
END $$;
