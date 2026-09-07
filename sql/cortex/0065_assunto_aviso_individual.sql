-- 0065 · "Comunicado do RH" vira "Aviso individual": dois nomes iguais para
-- duas coisas diferentes é o mesmo que não ter nome.
--
-- O assunto `comunicado` nasceu no 0063, quando o mural ainda não existia e
-- ele era o ÚNICO jeito de o RH avisar alguém pedindo ciência. Com o mural
-- (0064) passaram a existir dois caminhos, e o rótulo idêntico fazia a tela do
-- motorista mostrar "Convenção coletiva 2026" DUAS VEZES — uma em
-- "Comunicados da empresa" e outra em "Seus pedidos e comunicados" — sem nada
-- que dissesse por que ele estava vendo o mesmo aviso em dois lugares.
--
-- OS DOIS CONTINUAM EXISTINDO, porque respondem a perguntas diferentes:
--
--   mural (0064)          um aviso, TODOS os motoristas, sem resposta, e o
--                         que se mede é a fração de ciência
--   aviso individual      um aviso para UMA pessoa, dentro de uma CONVERSA:
--   (este assunto)        tem dono, tem estado, e ela pode responder ali
--                         mesmo. É o caminho de convocação, advertência e
--                         pendência de documento — coisas que o mural não faz
--                         porque não são de todo mundo.
--
-- O que muda é só o RÓTULO e o texto de ajuda. A CHAVE fica: `comunicado` é
-- FK em `mot_conversas.assunto`, e trocá-la levaria junto o histórico de quem
-- já deu ciência — que é justamente a prova que esse assunto existe para
-- guardar.
UPDATE mot_assuntos
   SET rotulo = 'Aviso individual',
       ajuda  = 'Aviso para UM motorista, com confirmação de leitura — '
                'convocação, pendência de documento, orientação. Para avisar '
                'TODOS de uma vez, use a aba Comunicados.'
 WHERE chave = 'comunicado';
