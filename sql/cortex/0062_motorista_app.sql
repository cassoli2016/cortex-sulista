-- 0062 · App do Motorista, fase 1-bis: o acesso mestre e o vínculo da multa.
--
-- Duas coisas independentes, na mesma migration porque nascem do mesmo pedido
-- (06/09/2026 → 07/09/2026): o app passa a mostrar multas, indicadores da
-- Gobrax, ocorrências, produtividade e jornada DO MOTORISTA — e quem administra
-- precisa conseguir abrir a tela de qualquer um deles para conferir se o que
-- está ali é verdade.
--
-- ==========================================================================
-- 1. O ACESSO MESTRE
-- ==========================================================================
-- O PROBLEMA REAL: as cinco telas novas dizem coisas sobre UMA pessoa, e o
-- único jeito de saber se elas dizem a verdade é abrir a de alguém que se
-- conhece e conferir contra o ERP. Sem isso, o app vira um lugar onde números
-- errados vivem escondidos — cada motorista vê só o dele, e ninguém vê o
-- conjunto. Quem opera pediu isto por escrito, e a razão é essa.
--
-- POR QUE UMA COLUNA NA SESSÃO, E NÃO UM SEGUNDO TIPO DE SESSÃO. Uma sessão
-- mestre é a sessão de um motorista — as mesmas rotas, as mesmas consultas, o
-- mesmo escopo. O que muda é COMO ela foi aberta e o que a tela tem obrigação
-- de dizer. Duplicar o caminho de sessão para carregar um booleano criaria
-- dois porteiros para manter, e o dia em que um ganhasse uma conferência que o
-- outro não tem seria o dia do buraco.
--
-- O QUE A COLUNA MUDA, DE VERDADE, e é por isso que ela não é decorativa:
--
--   1. **A tarja.** `/api/motorista/eu` devolve `mestre: true` e a página é
--      OBRIGADA a desenhar a faixa "você está vendo como FULANO". Sem ela,
--      quem administra esquece em que conta está — e um print de tela vira
--      "o app mostrou isso para o motorista", que é falso.
--   2. **O prazo.** 30 dias deslizantes é o que faz o motorista não desistir
--      do app; para um acesso de administração é o contrário — é uma porta
--      aberta num aparelho que ninguém lembra que está logado. Sessão mestre
--      vence em horas, e o prazo vive em `api/motorista/sessao.py`.
--   3. **A trilha.** `audit_log` grava `motorista_mestre_entrou` com o alvo.
--      A entrada normal e a mestre não podem parecer a mesma coisa depois.
--
-- O QUE ELA NÃO MUDA: o escopo. Uma sessão mestre lê a operação DAQUELE
-- motorista, e nada além — é a mesma função `viagem.minha(sessao)`, o mesmo
-- `sessao.exigir()`. Ela não é um perfil de administração dentro do app; é o
-- app de outra pessoa, aberto por quem tem a chave, com aviso na tela.
ALTER TABLE mot_sessoes ADD COLUMN IF NOT EXISTS mestre boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN mot_sessoes.mestre IS
    'Sessão aberta pelo código mestre, não pelo código do WhatsApp. A tela é
     obrigada a dizer isso (tarja) e o prazo é de horas, não de 30 dias.
     O ESCOPO É O MESMO: a operação daquele motorista, e nada além.';

CREATE INDEX IF NOT EXISTS mot_sessoes_mestre ON mot_sessoes(criada_em DESC)
    WHERE mestre;

-- ------------------------------------------------------ o freio do código mestre
--
-- O código mestre é UM segredo, longo e da casa, guardado no cofre (nunca no
-- repo, nunca nesta tabela). Mas um segredo que se pode tentar sem custo é um
-- segredo que se descobre com tempo — e a rota é pública para o middleware,
-- como todo o `/api/motorista/*`.
--
-- Esta tabela é o TETO POR ENDEREÇO, e é a mesma escolha de `mot_codigos`: a
-- linha é a TENTATIVA, não o acesso. Ela nasce quando alguém tenta e serve
-- para uma pergunta só — "quantas tentativas saíram deste IP na última hora?".
--
-- O CÓDIGO TENTADO NÃO ENTRA AQUI. Nem em hash: hash de tentativa errada é
-- inútil, e hash de tentativa CERTA é o próprio segredo guardado num lugar a
-- mais. O que se guarda é se foi aceita, para a Saúde do Servidor conseguir
-- distinguir "ninguém usa" de "alguém está tentando".
CREATE TABLE IF NOT EXISTS mot_mestre_tentativas(
    id      bigserial PRIMARY KEY,
    ip      text NOT NULL DEFAULT '',
    quando  timestamptz NOT NULL DEFAULT now(),
    aceita  boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS mot_mestre_tentativas_ip
    ON mot_mestre_tentativas(quando DESC, ip);

COMMENT ON TABLE mot_mestre_tentativas IS
    'Tentativas de uso do código mestre. Guarda IP, instante e se foi aceita —
     NUNCA o código tentado, nem em hash. É o teto por endereço e é o que
     permite à Saúde do Servidor distinguir "ninguém usa" de "estão tentando".';

-- ==========================================================================
-- 2. DE QUEM ERA O VOLANTE QUANDO A MULTA ACONTECEU
-- ==========================================================================
-- `smt_infracao_viagem` (0033) já responde "de quem era a CARGA": o casamento
-- por continência (a janela da viagem contém o instante da infração) roda na
-- coleta, contra o AVA, e guarda cliente e rota.
--
-- O MOTORISTA ESTAVA NA MESMA LINHA DA MESMA CONSULTA e era descartado. Ele
-- entra agora porque o app do motorista precisa da pergunta invertida: não
-- "quem era o cliente desta multa", mas "quais multas aconteceram enquanto EU
-- dirigia". Medido em 07/09/2026 sobre os 80 vínculos ativos: **156 infrações
-- casadas, 39 motoristas** — de 639 infrações em doze meses.
--
-- POR QUE AQUI E NÃO NA LEITURA. A alternativa era o app perguntar ao AVA a
-- cada abertura de tela: as viagens da placa, a janela, o cruzamento. Isso
-- põe o ERP — réplica de produção de terceiro, que já teve manhã ruim — no
-- caminho de uma tela de celular, e faz o mesmo trabalho uma vez por leitor.
-- Casando na coleta, a tela abre só com o banco local.
--
-- ISTO É HIPÓTESE, E A TELA DIZ ISSO. `candidatas > 1` já marca o empate de
-- janelas sobrepostas; e mesmo com uma candidata só, "a viagem estava com o
-- Fulano" não é "o Fulano cometeu a infração" — o veículo pode ter sido
-- movido no pátio, o auto pode ser de leitura de radar da carreta, e a
-- indicação de condutor tem processo próprio no órgão. O app mostra como "o
-- que apareceu na sua viagem" e diz o que fazer se não foi ele.
ALTER TABLE smt_infracao_viagem
    ADD COLUMN IF NOT EXISTS motorista_codigo text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS smt_infracao_viagem_motorista
    ON smt_infracao_viagem(motorista_codigo)
    WHERE motorista_codigo <> '';

COMMENT ON COLUMN smt_infracao_viagem.motorista_codigo IS
    'O `programacaoembarque.motorista` (= cadastro.codigo do ERP) da viagem
     que continha o instante da infração. É HIPÓTESE derivada da janela, como
     o cliente e a rota ao lado — não é indicação de condutor, que tem
     processo próprio no órgão. Vazio = não casou com viagem nenhuma.';
