-- Controle de pneus — o módulo PRÓPRIO da casa.
--
-- POR QUE ISTO EXISTE. Hoje o controle de pneu vive na Prolog (SaaS), e o
-- CÓRTEX só LÊ: um instantâneo de 6 MB em `data/pneus/pneus-atual.json`,
-- sobrescrito a cada coleta. Instantâneo é FOTOGRAFIA — 5.013 dos 8.572 pneus
-- já estão em DISPOSAL e não há como saber quando foram sucateados, de qual
-- veículo saíram, nem quanto rodaram antes. O histórico existe na Prolog e
-- some no dia em que o contrato acabar.
--
-- A decisão é migrar: enquanto a Prolog roda, ela ALIMENTA este banco todo
-- dia; quando for desligada, o CÓRTEX segue sozinho, porque a memória já está
-- aqui. Por isso o modelo abaixo é NOSSO, não um espelho do deles — cada
-- tabela guarda o `prolog_id` só para a sincronização ser idempotente, e
-- nenhuma consulta depende dele.
--
-- O EVENTO É A VERDADE, o estado atual é projeção. É o mesmo padrão da
-- auditoria de uso (`audit_log` append-only + `aud_sessoes` linha viva):
-- `pne_evento` é imutável e conta a história; `pne_pneu` carrega o estado de
-- agora porque tela não pode reprojetar 8.572 históricos a cada abertura. O
-- conferidor cobra que os dois digam a mesma coisa — estado que só se grava,
-- sem ninguém conferir contra a origem, mente no primeiro evento perdido.

-- ---------------------------------------------------------------- catálogo
-- Marca, modelo, medida e desenho vêm juntos DE PROPÓSITO. Na Prolog são
-- quatro cadastros separados e o nosso instantâneo veio com `medida` vazia em
-- 8.572 de 8.572 — porque a medida mora noutro endpoint que nunca buscamos.
-- Um pneu sem medida não se compara com outro: 295/80R22.5 e 275/80R22.5 têm
-- vida e preço diferentes.
CREATE TABLE IF NOT EXISTS pne_modelo (
  id             SERIAL PRIMARY KEY,
  marca          TEXT NOT NULL,
  modelo         TEXT NOT NULL,
  medida         TEXT,
  desenho        TEXT,
  -- Sulco de pneu NOVO, em milímetros. É o denominador do desgaste: sem ele,
  -- "restam 6 mm" não diz se o pneu está no começo ou no fim.
  sulco_novo_mm  NUMERIC(5,2),
  -- Quantas vidas o fabricante admite (nova + N recapagens).
  vidas_max      SMALLINT,
  ativo          BOOLEAN NOT NULL DEFAULT TRUE,
  prolog_id      TEXT,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (marca, modelo, medida, desenho)
);
CREATE INDEX IF NOT EXISTS pne_modelo_prolog ON pne_modelo (prolog_id);

-- Desenho de posições por tipo de veículo. A Prolog tem 44 deles, com `axles`
-- e `hasEngine`. Sem isto não existe "posição 3 do eixo 2": existiria um campo
-- de texto livre onde cada pessoa escreve de um jeito.
CREATE TABLE IF NOT EXISTS pne_diagrama (
  id             SERIAL PRIMARY KEY,
  nome           TEXT NOT NULL UNIQUE,
  tem_motor      BOOLEAN NOT NULL,
  eixos          SMALLINT NOT NULL,
  -- As posições, como o diagrama as define: [{eixo, lado, ordem, rotulo}].
  -- JSONB porque a forma varia por diagrama e normalizar isso em tabela daria
  -- 44 linhas-mãe e centenas de filhas para responder uma pergunta que sempre
  -- vem inteira ("quais posições este veículo tem").
  posicoes       JSONB NOT NULL DEFAULT '[]'::jsonb,
  prolog_id      TEXT,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Qual diagrama cada veículo usa. A chave é a PLACA, como manda a casa:
-- `numerofrota` tem 46% de cobertura real e em 943 cadastros é a própria placa
-- copiada no campo.
CREATE TABLE IF NOT EXISTS pne_veiculo (
  placa          TEXT PRIMARY KEY,
  diagrama_id    INTEGER REFERENCES pne_diagrama(id),
  filial         TEXT,
  prolog_id      TEXT,
  atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pne_veiculo_prolog ON pne_veiculo (prolog_id);

-- ------------------------------------------------------------------- pneu
-- A CARCAÇA. Ela sobrevive às vidas: um pneu novo que foi recapado três vezes
-- continua sendo a MESMA carcaça, e é por isso que custo por km só faz sentido
-- por vida, nunca no total sem dizer de qual.
CREATE TABLE IF NOT EXISTS pne_pneu (
  id             SERIAL PRIMARY KEY,
  -- Número de fogo: a marcação gravada na carcaça, como a operação a chama.
  numero_fogo    TEXT,
  -- Série do fabricante e DOT (semana/ano de fabricação). O DOT é o que
  -- permite dizer a IDADE da carcaça, e idade é motivo de sucata sozinha.
  serie          TEXT,
  dot            TEXT,
  modelo_id      INTEGER REFERENCES pne_modelo(id),
  filial         TEXT,
  -- ESTADO ATUAL, projeção dos eventos. `pne_evento` é quem manda; isto está
  -- aqui para a tela não reprojetar 8.572 históricos a cada abertura.
  status         TEXT NOT NULL DEFAULT 'estoque'
                 CHECK (status IN ('estoque','rodando','analise','recapagem',
                                   'conserto','sucata')),
  vida_atual     SMALLINT NOT NULL DEFAULT 0,
  placa_atual    TEXT,
  posicao_atual  TEXT,
  -- Custo de AQUISIÇÃO da carcaça (a primeira vida). O custo de cada recapagem
  -- fica em `pne_vida`, porque somá-los aqui perderia justamente a conta que
  -- decide: quanto custou o quilômetro de CADA vida.
  custo_aquisicao NUMERIC(12,2),
  nf_entrada     TEXT,
  prolog_id      TEXT UNIQUE,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
  atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pne_pneu_status ON pne_pneu (status);
CREATE INDEX IF NOT EXISTS pne_pneu_placa ON pne_pneu (placa_atual);
CREATE INDEX IF NOT EXISTS pne_pneu_fogo ON pne_pneu (numero_fogo);

-- Cada VIDA da carcaça: 0 = nova, 1..n = recapagens. O km e o custo ficam por
-- vida porque é assim que o CPK se calcula — misturar as vidas num total
-- premia a carcaça velha que rodou muito barato há três anos.
CREATE TABLE IF NOT EXISTS pne_vida (
  id             SERIAL PRIMARY KEY,
  pneu_id        INTEGER NOT NULL REFERENCES pne_pneu(id) ON DELETE CASCADE,
  numero         SMALLINT NOT NULL,
  inicio         DATE,
  fim            DATE,
  custo          NUMERIC(12,2),
  recapadora     TEXT,
  banda          TEXT,
  -- km RODADO nesta vida. Não é desnormalização de conveniência: o km vem da
  -- soma dos trechos entre instalação e remoção (`pne_evento.km_veiculo`), e
  -- recalculá-lo a cada leitura custaria varrer a história inteira. O
  -- conferidor cobra que ele bata com os eventos.
  km             NUMERIC(12,1),
  prolog_id      TEXT,
  UNIQUE (pneu_id, numero)
);
CREATE INDEX IF NOT EXISTS pne_vida_pneu ON pne_vida (pneu_id);

-- ----------------------------------------------------------------- eventos
-- A MOVIMENTAÇÃO. Append-only: evento não se edita nem se apaga, porque é a
-- única prova de onde o pneu esteve. Correção entra como evento novo.
CREATE TABLE IF NOT EXISTS pne_evento (
  id             BIGSERIAL PRIMARY KEY,
  pneu_id        INTEGER NOT NULL REFERENCES pne_pneu(id) ON DELETE CASCADE,
  tipo           TEXT NOT NULL
                 CHECK (tipo IN ('instalacao','remocao','rodizio',
                                 'envio_recapagem','retorno_recapagem',
                                 'envio_conserto','retorno_conserto',
                                 'transferencia','sucata','restauracao',
                                 'inventario')),
  ocorrido_em    TIMESTAMPTZ NOT NULL,
  placa          TEXT,
  posicao        TEXT,
  -- Odômetro do VEÍCULO no momento. É daqui que sai o km da vida: a diferença
  -- entre a instalação e a remoção. Nulo quando ninguém anotou — e nulo tem de
  -- aparecer como lacuna, nunca virar zero.
  km_veiculo     NUMERIC(12,1),
  vida           SMALLINT,
  motivo         TEXT,
  observacao     TEXT,
  -- De onde veio o evento. Enquanto a Prolog roda, quase tudo é 'prolog';
  -- depois do desligamento, tudo é 'cortex'. Sem esta coluna não dá para
  -- saber, no futuro, qual pedaço da história é importado e qual é nosso.
  origem         TEXT NOT NULL DEFAULT 'cortex'
                 CHECK (origem IN ('prolog','cortex')),
  usuario        TEXT,
  prolog_id      TEXT,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (origem, prolog_id)
);
CREATE INDEX IF NOT EXISTS pne_evento_pneu ON pne_evento (pneu_id, ocorrido_em);
CREATE INDEX IF NOT EXISTS pne_evento_quando ON pne_evento (ocorrido_em);
CREATE INDEX IF NOT EXISTS pne_evento_placa ON pne_evento (placa, ocorrido_em);

-- --------------------------------------------------------------- inspeção
-- Sulco e pressão medidos. Três sulcos porque o desgaste IRREGULAR é o
-- diagnóstico: interno gasto e externo cheio é alinhamento, os dois ombros
-- gastos é pressão baixa. Guardar só o menor esconde a causa.
CREATE TABLE IF NOT EXISTS pne_inspecao (
  id             BIGSERIAL PRIMARY KEY,
  pneu_id        INTEGER NOT NULL REFERENCES pne_pneu(id) ON DELETE CASCADE,
  medido_em      TIMESTAMPTZ NOT NULL,
  sulco_int_mm   NUMERIC(5,2),
  sulco_cen_mm   NUMERIC(5,2),
  sulco_ext_mm   NUMERIC(5,2),
  pressao_psi    NUMERIC(6,2),
  pressao_rec_psi NUMERIC(6,2),
  placa          TEXT,
  posicao        TEXT,
  origem         TEXT NOT NULL DEFAULT 'cortex'
                 CHECK (origem IN ('prolog','cortex')),
  usuario        TEXT,
  prolog_id      TEXT,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (origem, prolog_id)
);
CREATE INDEX IF NOT EXISTS pne_inspecao_pneu ON pne_inspecao (pneu_id, medido_em);

-- ------------------------------------------------------------ sincronização
-- Onde cada rota da Prolog parou. A cota deles é de ~10 requisições por
-- janela e uma volta completa nos pneus custa 86 — sincronização "de uma vez"
-- não existe aqui, então cada execução avança o que a cota permitir e grava
-- onde parou. Mesmo padrão da coleta que já roda.
CREATE TABLE IF NOT EXISTS pne_sync (
  rota           TEXT PRIMARY KEY,
  cursor         TEXT,
  janela_ate     TIMESTAMPTZ,
  ultima_em      TIMESTAMPTZ,
  ultimo_ok_em   TIMESTAMPTZ,
  registros      INTEGER NOT NULL DEFAULT 0,
  -- A falha se DECLARA. Sincronização que para em silêncio é a pior de todas:
  -- o banco fica velho e a tela continua confiante.
  ultimo_erro    TEXT,
  atualizado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
