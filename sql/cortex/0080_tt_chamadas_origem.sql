-- 0080 · TomTom — o consumo POR QUEM CHAMA.
--
-- POR QUE ISTO EXISTE
-- ===================
-- Em 11/09/2026 o produto de trânsito da TomTom estava SEM CRÉDITOS
-- (`InsufficientFunds`), e a pergunta que decidia o que fazer — "quem gasta?" —
-- não tinha resposta. `tt_chamadas` conta por dia e por RECURSO: diz que o
-- `fluxo` fez 14.554 chamadas em 07/09 e 7.440 até as 10h do dia 11, mas não diz
-- se foi a Torre aberta numa mesa, o painel de TV girando sozinho, ou a varredura
-- que cada reinício da API dispara com o cache vazio (o AutoDeploy reinicia
-- várias vezes por dia). A previsão escrita no código era ~5.000/dia vindas da
-- TV; o medido foi o dobro, e sem esta tabela a diferença não tem dono.
--
-- ELA SÓ ACRESCENTA. `tt_chamadas` continua sendo o total do dia por recurso,
-- com o mesmo significado de sempre — a Saúde e o consumo diário seguem lendo
-- de lá. Esta é a quebra por origem, gravada na mesma passada.
--
-- `varreduras` é quantas vezes a origem PEDIU; `chamadas`, quantas saíram para
-- a TomTom; `barradas`, quantas vezes o freio de falta de crédito recusou sem
-- sair para a rede; `apos_reinicio`, quantas varreduras aconteceram com o cache
-- vazio de um processo que acabou de subir.
CREATE TABLE IF NOT EXISTS tt_chamadas_origem (
    dia            date        NOT NULL,
    recurso        text        NOT NULL,   -- fluxo | incidentes | rota | geocode
    origem         text        NOT NULL,   -- torre | tv | radar | eta | geocode
    varreduras     integer     NOT NULL DEFAULT 0,
    chamadas       integer     NOT NULL DEFAULT 0,
    erros          integer     NOT NULL DEFAULT 0,
    barradas       integer     NOT NULL DEFAULT 0,
    apos_reinicio  integer     NOT NULL DEFAULT 0,
    ultima_em      timestamp,
    PRIMARY KEY (dia, recurso, origem)
);
