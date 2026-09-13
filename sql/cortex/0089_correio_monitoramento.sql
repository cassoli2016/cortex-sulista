-- Monitoramento de cliente por e-mail (12/09/2026).
--
-- A torre mantem uma planilha por cliente, uma aba por dia, e a manda anexada
-- de duas em duas horas: frota, placas, janela de carregamento e de entrega,
-- chegada e saida no cliente, carencia, horas paradas, pedido, CVA e a
-- situacao. O CORTEX ja sabe tudo isso pelo ERP (o portal do cliente le a
-- mesma coisa) - esta tabela guarda so a REGRA de envio.
--
-- SEPARADA de `correio_agenda` porque a pergunta e outra: la e "que relatorio,
-- que dia, que hora"; aqui e "de QUAL cliente, quais mercadorias, de quanto em
-- quanto tempo, entre que horas". Uma frequencia a mais la obrigaria a agenda
-- de relatorios a ganhar cliente e mercadoria, que nenhum outro relatorio usa.
--
-- 0089 e nao 0084: em 12/09/2026 tres outras frentes tinham uma 0084 nao
-- commitada nas suas worktrees. Buraco na sequencia e mais barato que colisao.
CREATE TABLE IF NOT EXISTS correio_monitoramento(
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- RAIZ do CNPJ, o mesmo escopo do portal do cliente (`api/portal_cliente`):
    -- o documento, e nao o agrupamento do ERP, que ja deixou uma planta de fora.
    cliente_raiz    text    NOT NULL CHECK (cliente_raiz ~ '^[0-9]{8}$'),
    -- So ROTULO, gravado na hora de salvar: a lista da tela nao pode depender
    -- do ERP responder para dizer de quem e cada linha.
    cliente_nome    text    NOT NULL DEFAULT '',
    -- Mercadorias NORMALIZADAS (`api/freetime.canonizar`). Vazio = todas. E o
    -- mesmo filtro da tela Minha Operacao: quem recebe a planilha de escadas e
    -- conjuntos nao e quem recebe a de chassi.
    mercadorias     text[]  NOT NULL DEFAULT '{}',
    destinatarios   text    NOT NULL,
    -- Para onde vai a RESPOSTA do cliente. Sem isto ele responde ao remetente
    -- do CORTEX, que nao e caixa de ninguem, e a pergunta se perde.
    responder_para  text    NOT NULL DEFAULT '',
    intervalo_min   integer NOT NULL DEFAULT 120
                    CHECK (intervalo_min IN (60, 120, 180, 240, 360)),
    hora_inicio     text    NOT NULL DEFAULT '06:00',
    hora_fim        text    NOT NULL DEFAULT '22:00',
    -- ISO: 1=segunda ... 7=domingo, como texto ('123456').
    dias_semana     text    NOT NULL DEFAULT '123456',
    anexar_planilha boolean NOT NULL DEFAULT true,
    ativo           boolean NOT NULL DEFAULT false,
    ultima_execucao text,
    ultimo_resultado text,
    criado_por      text,
    criado_em       text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    alterado_por    text,
    alterado_em     text
);

COMMENT ON COLUMN correio_monitoramento.ativo IS
    'PADRAO FALSE. Este e-mail sai para FORA da empresa, para o cliente:
     ausencia de decisao nunca pode significar mandar.';
COMMENT ON COLUMN correio_monitoramento.ultima_execucao IS
    'Marca a PASSAGEM da rotina em cada rodada, gravada mesmo quando nao houve
     envio (sem carga no dia, ERP fora). Sem isto a rotina reenviaria a cada
     disparo da tarefa, de 15 em 15 minutos.';
