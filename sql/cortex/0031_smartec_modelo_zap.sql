-- Modelo de WhatsApp do aviso de prazo de indicação de condutor.
--
-- POR QUE UM SEED, e não "o usuário cria na tela": porque o texto deste aviso
-- carrega uma regra que não é óbvia para quem escreve a mensagem — que perder
-- o prazo não é perder o desconto, é ganhar OUTRA multa, a do art. 257 §8º,
-- que recai sobre a empresa. Um modelo em branco convidaria a escrever "você
-- tem 3 multas vencendo", que é verdadeiro e não explica a urgência.
--
-- O QUE NÃO ESTÁ AQUI, DE PROPÓSITO: o destinatário. Este repositório é
-- PÚBLICO — número de telefone não entra em arquivo versionado. A rotina que
-- usa este modelo é criada no banco, com o destinatário informado por quem
-- opera, e nasce DESLIGADA.
--
-- ON CONFLICT DO NOTHING: quem editar o texto na tela manda. Reaplicar a
-- migration num banco que já tem o modelo não pode desfazer a edição de
-- ninguém — seed é ponto de partida, não verdade permanente.

INSERT INTO zap_modelos (chave, nome, contexto, descricao, corpo, ativo,
                         criado_em, criado_por, atualizado_em, atualizado_por)
VALUES (
  'smartec-prazo-indicacao',
  'Smartec — prazo de indicar condutor',
  'smartec_prazo',
  'Disparo diário das notificações cujo prazo de indicação está vencendo. '
  'Silencia sozinho quando não há nenhuma — e RECUSA o envio quando a coleta '
  'da Smartec está parada, em vez de afirmar que não há prazo correndo.',
  E'🚨 *INDICAÇÃO DE CONDUTOR — VENCE HOJE ({{data}})*

⏰ *{{quantidade}} notificações* perdem hoje o prazo de indicar quem dirigia.

{{lista}}

💵 *Total em risco hoje: {{total}}*

❗ Sem indicação até hoje, entra por cima a multa por *não identificar o condutor* (art. 257 §8º) — e essa recai sobre a *empresa*.

{{proximos}}

👉 A indicação é feita no painel da Smartec.
📊 Detalhe em *Córtex › Multas — Smartec › Notificações*',
  1, now(), 'sistema', now(), 'sistema')
ON CONFLICT (chave) DO NOTHING;
