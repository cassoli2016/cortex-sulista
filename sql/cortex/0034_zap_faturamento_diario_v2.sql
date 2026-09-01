-- O resumo diário de faturamento ganhou previsão de fechamento, ritmo
-- necessário, pontos de atenção e os semáforos em emoji (pedido do dono em
-- 01/09/2026: "algo robusto que caiba em uma mensagem", com "setas pra cima
-- verde, para baixo vermelha, bolhas amarelas"). A mensagem mostra SEMPRE o
-- fechamento do dia ANTERIOR, e no dia 1º vira o fechamento do MÊS anterior
-- (segundo pedido do mesmo dia) — daí os títulos serem variáveis.
--
-- POR QUE UPDATE, e não ON CONFLICT DO NOTHING como os outros seeds: o
-- pedido É a mensagem nova — manter o corpo antigo seria ignorá-lo. O texto
-- continua editável na tela (Gestão › WhatsApp › Modelos) depois disto.
--
-- O QUE NÃO ESTÁ AQUI, DE PROPÓSITO: o destinatário e a rotina das 07:00.
-- Este repositório é PÚBLICO — número de telefone não entra em arquivo
-- versionado. A rotina é criada no banco, com o destinatário de quem opera.
--
-- LIMITE DO "LEIA MAIS": o WhatsApp recolhe mensagens muito longas. O corpo
-- renderizado fica em ~600 caracteres / 17 linhas, com folga.

UPDATE zap_modelos
   SET corpo = E'📊 *FATURAMENTO SULISTA* — {{data}}

💰 Dia: {{faturado_dia}}
🎯 Meta: {{meta_dia}}
{{farol_dia}} Atingido: {{atingimento_dia}}

📆 *{{titulo_mes}}*
💵 {{acumulado_mes}} de {{meta_mes}}
{{farol_mes}} Atingido: *{{atingimento_mes}}* · falta {{falta_mes}}

🔮 *{{titulo_previsao}}*
{{farol_previsao}} {{previsao_mes}} ({{previsao_vs_meta}})
🏁 {{linha_ritmo}}

{{pontos_atencao}}

🔗 {{link_painel}}',
       descricao = 'Resumo diário para a diretoria: dia × meta, mês até '
                   'aqui, previsão de fechamento no ritmo atual, ritmo '
                   'necessário e pontos de atenção. Os números saem da '
                   'Visão Geral; sem emissão no mês a rotina silencia em '
                   'vez de mandar R$ 0,00.',
       atualizado_em = now(),
       atualizado_por = 'sistema (v0.197.0)'
 WHERE chave = 'faturamento-diario';
