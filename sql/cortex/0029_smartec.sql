-- Smartec — infrações, licenças e documentação da frota.
--
-- POR QUE TRAZER PARA CÁ o que o ERP já importa: porque ele importa um pedaço.
-- O AVA tem a integração (`integracao.cadastrointegracao` id=3, tipo 32) com UM
-- processo habilitado, o 8 "Importar Infração", e ela funciona — mas medido em
-- 31/08/2026, das 212 multas em aberto na Smartec, 64 estavam no ERP SEM VALOR
-- e 28 a Smartec dá como PAGAS com `dtliquidacao` vazia no ERP em todas as 28.
-- O "pagas em 0" da tela de Multas nunca foi a operação não pagar: era a baixa
-- não voltar. E os outros onze recursos da API o ERP não lê de forma alguma.
--
-- A CHAVE É O RENAVAM, e ela é sólida: o `codigorenavam` do AVA está
-- preenchido em 99,7% dos veículos ativos e bate com a Smartec em 301 de 301,
-- sem uma divergência. A placa fica junto para exibição — quem identifica
-- veículo na tela é a placa —, mas quem junta é o renavam.
--
-- A COLETA É IDEMPOTENTE POR CHAVE NATURAL. Recoletar é o caso NORMAL: a API
-- devolve o estado corrente a cada chamada e o boleto muda de situação ao
-- longo do mês. Toda gravação é ON CONFLICT DO UPDATE.

-- ==========================================================================
-- INFRAÇÕES (multas e notificações)
-- ==========================================================================
-- `identificador` é o GUID da Smartec (IDENTIFICADOR_SMARTEC) e é a chave.
-- O AIT seria o candidato natural, e NÃO serve: no ERP há 45 AITs repetidos em
-- 3.510 registros. Um mesmo auto pode reaparecer com órgão diferente, e existe
-- AIT_ORIGINARIA para o caso da autuação que gera outra.
--
-- `visto_em` É O CAMPO QUE FAZ ESTA TABELA DIZER A VERDADE, e o motivo não é
-- óbvio: a API devolve **somente o que está em aberto**. Uma multa paga, ou
-- cuja defesa foi provida, simplesmente PARA DE APARECER — não vem marcada
-- como resolvida, some. Sem registrar em que coleta cada linha foi vista pela
-- última vez, a tabela viraria um acumulado que só cresce, e o painel diria
-- "212 multas em aberto" para sempre. Com ele, "em aberto" é
-- `visto_em = (a última coleta bem-sucedida)`, e o que sumiu vira histórico
-- com data — que é justamente o que o ERP não tem.
CREATE TABLE IF NOT EXISTS smt_infracoes(
    identificador       text PRIMARY KEY,
    especie             text NOT NULL DEFAULT 'multa',
    placa               text NOT NULL DEFAULT '',
    renavam             text NOT NULL DEFAULT '',
    ait                 text NOT NULL DEFAULT '',
    ait_sne             text NOT NULL DEFAULT '',
    ait_detran          text NOT NULL DEFAULT '',
    renainf             text NOT NULL DEFAULT '',
    ait_originaria      text NOT NULL DEFAULT '',
    renainf_originaria  text NOT NULL DEFAULT '',
    data_infracao       date,
    hora                text NOT NULL DEFAULT '',
    local_infracao      text NOT NULL DEFAULT '',
    valor_a_pagar       numeric(14,2),
    valor_com_desconto  numeric(14,2),
    valor_desconto      numeric(14,2),
    codigo_municipio    text NOT NULL DEFAULT '',
    municipio           text NOT NULL DEFAULT '',
    uf                  text NOT NULL DEFAULT '',
    descricao           text NOT NULL DEFAULT '',
    codigo_infracao     text NOT NULL DEFAULT '',
    desdobramento       text NOT NULL DEFAULT '',
    pontuacao           integer,
    codigo_orgao        text NOT NULL DEFAULT '',
    orgao               text NOT NULL DEFAULT '',
    orgao_adesao_sne    integer,
    vencimento          date,
    data_pesquisa       date,
    -- PRAZO PARA INDICAR CONDUTOR — só existe na NOTIFICAÇÃO, e é o campo que
    -- torna essa espécie acionável: passado o prazo, a autuação por "não
    -- indicar condutor" (art. 257 §8º) entra por cima, e ela é 61 das 212
    -- multas em aberto desta frota. Coluna PRÓPRIA e não `vencimento`, porque
    -- são prazos de coisas diferentes: um é para pagar, o outro para indicar.
    prazo_indicacao     date,
    url_penalidade      text NOT NULL DEFAULT '',
    url_boleto          text NOT NULL DEFAULT '',
    codigo_boleto       integer,
    situacao_boleto     text NOT NULL DEFAULT '',
    descricao_boleto    text NOT NULL DEFAULT '',
    boleto_valor        numeric(14,2),
    linha_digitavel     text NOT NULL DEFAULT '',
    boleto_vencimento   date,
    boleto_cedente      text NOT NULL DEFAULT '',
    boleto_desconto_pct numeric(8,2),
    confirmacao_pagamento integer,
    motorista_nome      text NOT NULL DEFAULT '',
    motorista_matricula text NOT NULL DEFAULT '',
    primeiro_visto_em   timestamptz NOT NULL DEFAULT now(),
    visto_em            timestamptz NOT NULL DEFAULT now(),
    sumiu_em            timestamptz
);

COMMENT ON COLUMN smt_infracoes.especie IS
    'multa = MULTAS SNE DETRAN (já é penalidade, tem boleto);
     notificacao = NOTIFICACOES SNE DETRAN (autuação, ainda cabe indicação de
     condutor e defesa prévia). São estágios diferentes do mesmo auto e a tela
     NÃO pode somá-los: contar os dois juntos conta a mesma infração duas
     vezes, e a ação de cada um é outra.';

COMMENT ON COLUMN smt_infracoes.visto_em IS
    'Última coleta em que a Smartec ainda devolveu esta linha. A API só
     devolve o que está EM ABERTO, então isto é o que distingue "em aberto"
     de "resolvida" — ver o cabeçalho do arquivo.';

COMMENT ON COLUMN smt_infracoes.sumiu_em IS
    'Quando a linha deixou de vir na coleta. NULL = ainda em aberto. Não
     significa "paga": pode ser pagamento, defesa provida ou baixa do órgão —
     a Smartec não diz qual, e inventar o motivo seria afirmar o que a fonte
     não disse.';

COMMENT ON COLUMN smt_infracoes.motorista_nome IS
    'Vem da Smartec e NÃO é sempre uma pessoa: os valores medidos incluem
     "AGREGADO", "MOTORISTA", "NIC" e "RECURSO", que são estados do processo
     de indicação, não nomes. Só 2 de 212 traziam nome real. Tratar como
     condutor identificado faria a tela mentir.';

CREATE INDEX IF NOT EXISTS ix_smt_infracoes_renavam ON smt_infracoes(renavam);
CREATE INDEX IF NOT EXISTS ix_smt_infracoes_placa   ON smt_infracoes(placa);
CREATE INDEX IF NOT EXISTS ix_smt_infracoes_data    ON smt_infracoes(data_infracao);
CREATE INDEX IF NOT EXISTS ix_smt_infracoes_aberto  ON smt_infracoes(sumiu_em)
    WHERE sumiu_em IS NULL;

-- ==========================================================================
-- VEÍCULOS cadastrados na Smartec
-- ==========================================================================
-- É o DENOMINADOR. Sem ele, "96 veículos com multa" não se lê: 96 de quantos?
-- Medido em 31/08/2026 são 303 cadastrados na Smartec contra 1.449 ativos no
-- AVA — e a diferença não é falha, é que a Smartec cobre a frota PRÓPRIA
-- (301 dos 309 de tipofrota=1). Os 8 que faltam são o achado acionável.
CREATE TABLE IF NOT EXISTS smt_veiculos(
    renavam         text PRIMARY KEY,
    placa           text NOT NULL DEFAULT '',
    frota           text NOT NULL DEFAULT '',
    prefixo         text NOT NULL DEFAULT '',
    chassi          text NOT NULL DEFAULT '',
    tipo            text NOT NULL DEFAULT '',
    marca           text NOT NULL DEFAULT '',
    ano_modelo      integer,
    ano_fabricacao  integer,
    cor             text NOT NULL DEFAULT '',
    uf              text NOT NULL DEFAULT '',
    visto_em        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_smt_veiculos_placa ON smt_veiculos(placa);

-- ==========================================================================
-- LICENÇAS — vencimentos de documentação por veículo
-- ==========================================================================
-- Cronotacógrafo, EMTU, CSV, CIV e CIPP/CTPP numa linha por veículo, como o
-- RESUMO da Smartec entrega. CIV, CIPP e EMTU vêm vazios NESTA conta (a API
-- responde "NENHUM DADO ENCONTRADO" nos endpoints dedicados), e as colunas
-- ficam mesmo assim: campo vazio que a tela DIZ estar vazio é informação;
-- coluna ausente faz o próximo achar que o dado não existe na fonte.
CREATE TABLE IF NOT EXISTS smt_licencas(
    renavam         text PRIMARY KEY,
    placa           text NOT NULL DEFAULT '',
    frota           text NOT NULL DEFAULT '',
    cronotacografo  date,
    emtu            date,
    csv             date,
    pp_civ          date,
    pp_cipp_ctpp    date,
    visto_em        timestamptz NOT NULL DEFAULT now()
);

-- ==========================================================================
-- LICENCIAMENTO — mês do calendário e taxa em aberto
-- ==========================================================================
-- `mes` vem do CALENDARIO (uma chamada para a frota toda) e `valor_taxa` do
-- VALOR (uma chamada POR VEÍCULO). São cadências diferentes de propósito: o
-- calendário muda uma vez por ano, o valor muda quando se paga.
CREATE TABLE IF NOT EXISTS smt_licenciamento(
    renavam          text PRIMARY KEY,
    placa            text NOT NULL DEFAULT '',
    uf               text NOT NULL DEFAULT '',
    tipo             text NOT NULL DEFAULT '',
    mes              integer,
    valor_taxa       numeric(14,2),
    guia             text NOT NULL DEFAULT '',
    linha_digitavel  text NOT NULL DEFAULT '',
    guia_vencimento  date,
    cedente          text NOT NULL DEFAULT '',
    ipva_valor       numeric(14,2),
    data_pesquisa    date,
    visto_em         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN smt_licenciamento.valor_taxa IS
    'Taxa de licenciamento em aberto. NÃO inclui IPVA nem DPVAT — a própria
     Smartec diz isso na doc do endpoint. Somar com o IPVA para anunciar "o
     custo de licenciar" precisa dizer que são duas fontes.';

-- ==========================================================================
-- RESTRIÇÕES E BLOQUEIOS
-- ==========================================================================
-- O texto cru fica guardado porque este é um dado JURÍDICO: "ALIENACAO
-- FIDUCIARIA" e "NADA CONSTA" são o que a fonte afirma, e resumir isso numa
-- flag booleana perderia justamente a distinção que importa numa discussão.
CREATE TABLE IF NOT EXISTS smt_restricoes(
    renavam           text PRIMARY KEY,
    placa             text NOT NULL DEFAULT '',
    resumo            text NOT NULL DEFAULT '',
    comunicacao_venda text NOT NULL DEFAULT '',
    agente_financeiro text NOT NULL DEFAULT '',
    detalhe           jsonb,
    tem_restricao     boolean NOT NULL DEFAULT false,
    data_pesquisa     date,
    visto_em          timestamptz NOT NULL DEFAULT now()
);

-- ==========================================================================
-- ACESSOS AOS ÓRGÃOS (SNE e ANTT) — por CNPJ
-- ==========================================================================
-- ESTA É A TABELA QUE VIRA ALARME, e ela quase não entrou.
-- `data_expiracao` é o vencimento do e-CNPJ que dá acesso ao SENATRAN. Sem
-- ele, a Smartec para de trazer notificação, não se pede boleto pelo SNE e não
-- se indica condutor — ou seja, o produto inteiro degrada em silêncio, e o
-- sintoma é "parou de chegar multa", que se lê como boa notícia.
-- Medido em 31/08/2026: um dos dois CNPJs expira em 28/09/2026.
CREATE TABLE IF NOT EXISTS smt_acessos(
    servico         text NOT NULL,
    cnpj            text NOT NULL,
    empresa         text NOT NULL DEFAULT '',
    codigo          integer,
    situacao        text NOT NULL DEFAULT '',
    observacao      text NOT NULL DEFAULT '',
    data_expiracao  date,
    atualizado_em   timestamptz,
    visto_em        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (servico, cnpj)
);

COMMENT ON TABLE smt_acessos IS
    'Vencimento do acesso da empresa a SNE e ANTT. É a dependência silenciosa
     de toda esta integração: expirado, o dado para de chegar sem erro nenhum.';

-- ==========================================================================
-- AUTUAÇÕES DA ANTT
-- ==========================================================================
-- Separada de `smt_infracoes` porque NÃO é a mesma coisa: a ANTT autua a
-- TRANSPORTADORA por infração de transporte (vale-pedágio, RNTRC, excesso),
-- não o condutor por infração de trânsito. Não tem pontuação em CNH, tem
-- processo administrativo e situação de defesa. Juntar as duas numa tabela só
-- porque ambas se chamam "multa" faria somar coisas de naturezas diferentes.
CREATE TABLE IF NOT EXISTS smt_antt(
    ait              text PRIMARY KEY,
    processo         text NOT NULL DEFAULT '',
    data_infracao    date,
    codigo           text NOT NULL DEFAULT '',
    tipo             text NOT NULL DEFAULT '',
    descricao        text NOT NULL DEFAULT '',
    placa            text NOT NULL DEFAULT '',
    situacao         text NOT NULL DEFAULT '',
    impeditiva       integer,
    data_notificacao date,
    local_infracao   text NOT NULL DEFAULT '',
    valor            numeric(14,2),
    vencimento       date,
    detalhe          jsonb,
    visto_em         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_smt_antt_placa ON smt_antt(placa);

-- ==========================================================================
-- CATÁLOGOS de referência
-- ==========================================================================
-- O catálogo do CTB traz VALOR e PONTOS de cada infração, e é isso que o
-- CÓRTEX não tinha: a `infracaotransito` do ERP vem com valor ZERADO
-- justamente nas duas infrações mais frequentes da casa. Com este catálogo,
-- a multa recente que ainda não tem valor lançado ganha uma referência
-- DECLARADA como referência — nunca somada ao valor real como se fosse ele.
CREATE TABLE IF NOT EXISTS smt_infracoes_ctb(
    codigo          text NOT NULL,
    desdobramento   text NOT NULL DEFAULT '',
    infracao        text NOT NULL DEFAULT '',
    responsavel     text NOT NULL DEFAULT '',
    valor           numeric(14,2),
    orgao           text NOT NULL DEFAULT '',
    artigo          text NOT NULL DEFAULT '',
    pontos          integer,
    gravidade       text NOT NULL DEFAULT '',
    atualizado_em   date,
    visto_em        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (codigo, desdobramento)
);

CREATE TABLE IF NOT EXISTS smt_orgaos(
    codigo            text PRIMARY KEY,
    orgao             text NOT NULL DEFAULT '',
    uf                text NOT NULL DEFAULT '',
    observacao        text NOT NULL DEFAULT '',
    adeso_sne         integer,
    indicacao_online  integer,
    visto_em          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN smt_orgaos.adeso_sne IS
    'Só órgão adeso ao SNE aceita boleto e indicação eletrônica. Uma multa de
     órgão não adeso não é "erro do sistema" quando o boleto não sai — é o
     órgão. Sem esta coluna a tela não consegue dizer a diferença.';

-- ==========================================================================
-- CNH e exame toxicológico
-- ==========================================================================
-- Chaveada por CPF, que é como a casa junta pessoa (mesma escolha de
-- `jor_motoristas`). Depende do condutor estar CADASTRADO na Smartec — sem
-- cadastro a API não devolve nada, e isso é instalação incompleta, não falha.
CREATE TABLE IF NOT EXISTS smt_cnh(
    cpf                    text PRIMARY KEY,
    nome                   text NOT NULL DEFAULT '',
    registro               text NOT NULL DEFAULT '',
    categoria              text NOT NULL DEFAULT '',
    validade               date,
    situacao               text NOT NULL DEFAULT '',
    toxicologico_validade  date,
    toxicologico_situacao  text NOT NULL DEFAULT '',
    pontos                 integer,
    detalhe                jsonb,
    data_pesquisa          date,
    visto_em               timestamptz NOT NULL DEFAULT now()
);

-- ==========================================================================
-- TRILHA DE COLETA
-- ==========================================================================
-- Toda passagem entra aqui, INCLUSIVE a que falhou e a que não trouxe nada.
-- É a lição da RasterJOR, que ficou 136 dias parada porque não havia trilha:
-- alarme só existe onde há registro de passagem. "Não trouxe nada" precisa
-- ser distinguível de "não rodou", e sem esta tabela os dois são o mesmo
-- silêncio.
CREATE TABLE IF NOT EXISTS smt_carga(
    id          bigserial PRIMARY KEY,
    recurso     text NOT NULL,
    inicio      timestamptz NOT NULL DEFAULT now(),
    fim         timestamptz,
    status      text NOT NULL DEFAULT 'executando',
    itens       integer NOT NULL DEFAULT 0,
    chamadas    integer NOT NULL DEFAULT 0,
    mensagem    text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_smt_carga_recurso ON smt_carga(recurso, inicio DESC);

COMMENT ON COLUMN smt_carga.status IS
    'ok | vazio | erro. "vazio" é separado de "ok" de propósito: coleta que
     não trouxe nada pode ser a verdade (não há multa) ou pode ser a
     integração morrendo — e é a SEQUÊNCIA de vazios que denuncia, não um.';
