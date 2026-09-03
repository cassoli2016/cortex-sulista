-- 0042 · O espelho da 3S: veículos e última posição.
--
-- POR QUE ESTE ESPELHO EXISTE, medido em 03/09/2026: das 142 carretas que o
-- ERP dava como "nunca comunicaram", 77 tinham reportado à 3S naquele mesmo
-- dia — com hora, ignição, satélites e endereço. Elas nunca estiveram mudas; o
-- cano do ERP é que não as traz. Ler direto da 3S recupera 80 carretas sem
-- ninguém tocar em equipamento.
--
-- SÓ A ÚLTIMA POSIÇÃO, e não o histórico. O histórico de posição é caro (a 3S
-- tem `HistoricoPosicao` próprio, sob demanda) e o CÓRTEX não precisa dele: o
-- painel pergunta "comunicou?" e a curva de evolução já é guardada em
-- `com_status_diario`. Espelhar milhões de pontos para responder uma pergunta
-- de uma linha seria pagar caro por nada.
--
-- `visto_em` / `sumiu_em` porque a API devolve o ABERTO — quem sai da conta
-- simplesmente para de aparecer, sem aviso. Sem esse par, o veículo removido
-- ficaria no espelho para sempre, contando como frota. O fechamento é ancorado
-- no INÍCIO da coleta completa: veículo não visto numa coleta que rodou
-- inteira sumiu; numa coleta que falhou no meio, não se conclui nada.

CREATE TABLE IF NOT EXISTS tress_veiculo (
  placa            text        PRIMARY KEY,
  frota            text,
  modelo           text,
  tipo             text,               -- Carreta | Caminhão | Passeio
  id_equipamento   text,
  id_veiculo       text,
  num_serie        text,
  chassi           text,
  visto_em         timestamp   NOT NULL,
  sumiu_em         timestamp
);

COMMENT ON TABLE tress_veiculo IS
  'Espelho do cadastro de veículos na conta da 3S (ListaVeiculos). '
  'sumiu_em preenchido = saiu da conta.';

CREATE TABLE IF NOT EXISTS tress_posicao (
  placa            text        PRIMARY KEY REFERENCES tress_veiculo(placa) ON DELETE CASCADE,
  id_posicao       text,
  dt               timestamp   NOT NULL,   -- quando a POSIÇÃO ocorreu
  latitude         numeric(12, 7),
  longitude        numeric(12, 7),
  velocidade       integer,
  ignicao          text,
  satelites        integer,
  uf               text,
  cidade           text,
  bairro           text,
  endereco         text,
  coletado_em      timestamp   NOT NULL    -- quando NÓS lemos
);

COMMENT ON TABLE tress_posicao IS
  'Última posição conhecida de cada veículo na 3S. `dt` é a hora da posição; '
  '`coletado_em` é a hora da leitura — a diferença entre as duas é o atraso '
  'do fornecedor, e confundi-las faria dado velho parecer fresco.';

CREATE INDEX IF NOT EXISTS ix_tress_posicao_dt ON tress_posicao (dt DESC);
CREATE INDEX IF NOT EXISTS ix_tress_veiculo_vivo
  ON tress_veiculo (placa) WHERE sumiu_em IS NULL;
