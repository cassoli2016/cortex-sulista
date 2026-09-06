-- O guard que impedia mensagem repetida estava desarmado pela própria
-- mensagem.
--
-- O QUE ACONTECEU (medido em 06/09/2026, na trilha `zap_envios`): o telefone
-- inscrito na carga CT-e 94540 recebeu 14 mensagens em pouco mais de um dia,
-- e as seis últimas — ao longo de quatro horas — diziam exatamente a mesma
-- coisa: `2%`, `faltam 648 km de 662 km`, mesma origem, mesmo destino. O que
-- mudava entre uma e outra era `🕐 Atualizado há 3 min` virando `há 4 min`, e
-- o trânsito ganhando `(~1 min de atraso)`.
--
-- A CAUSA: `aviso.rodar()` decidia reenviar comparando o TEXTO RENDERIZADO com
-- `ultimo_texto`. O texto carrega o frescor da posição, que muda a cada ciclo
-- por construção — então a comparação quase nunca casava. A proteção que o
-- módulo documenta como sua razão de existir ("caminhão parado geraria a mesma
-- frase 24 vezes por dia, a pessoa bloqueia o número, e o estrago é a
-- reputação do número que atende todos os outros clientes") estava desarmada
-- pela linha que o próprio módulo acrescenta.
--
-- POR QUE O TESTE NÃO PEGOU, e esta é a lição que vale mais que a coluna: o
-- guard `test_mensagem_IGUAL_a_anterior_nao_e_reenviada` fabricava o
-- `ultimo_texto` chamando `aviso._texto(carga)` sobre a MESMA carga — dois
-- textos idênticos byte a byte, comparação casando, teste verde. Dublê montado
-- a partir do código que ele testa não testa esse código: a mesma armadilha do
-- cartão de janelas do ERP, agora com o relógio no lugar da constante.
--
-- A CORREÇÃO: quem decide o reenvio deixa de ser o texto e passa a ser uma
-- ASSINATURA DO QUE MUDOU — estado, faixa de progresso, faixa de km que falta,
-- estado do trânsito. O texto continua trazendo o frescor; ele só perde o voto.
-- A assinatura mora aqui porque é estado que sobrevive ao processo, e não se
-- deriva do texto: derivá-la de volta exigiria reinterpretar a redação, que é
-- a parte que muda toda semana.

-- NUMERADA 0060 E NAO 0059, e o motivo fica escrito porque o buraco na
-- sequencia confunde quem ler depois: o banco de producao ja tinha o numero 59
-- registrado em `schema_versao` como `0059_de_outra_frente.sql` — um DUBLE DE
-- TESTE (`tests/test_pglocal.py`) que vazou para o schema de producao em
-- 06/09/2026 15:11:59, junto com `0108_nao_commitada.sql`. Nenhum dos dois
-- existe no repositorio. O runner recusou o 0059 como manda o desenho dele; o
-- vazamento e outro assunto, e esta reportado.

ALTER TABLE rst_inscricao ADD COLUMN IF NOT EXISTS ultima_assinatura TEXT;

COMMENT ON COLUMN rst_inscricao.ultima_assinatura IS
    'O QUE foi dito, reduzido ao que MUDA a decisão de quem espera a carga:
     estado, faixa de progresso, faixa de km restante, estado do trânsito.
     É esta coluna — nunca `ultimo_texto` — que decide se a próxima mensagem
     sai. Montada por `rastreio.mensagem.assinatura()`, que EXCLUI de propósito
     o frescor da posição e o atraso em minutos do trânsito: eles mudam a cada
     ciclo sem que nada tenha mudado para o cliente, e foi por eles que 14
     mensagens iguais saíram em 06/09/2026.';

COMMENT ON COLUMN rst_inscricao.ultimo_texto IS
    'A última mensagem enviada, para quem atende saber o que o cliente recebeu.
     NÃO decide mais o reenvio — quem decide é `ultima_assinatura`.';
