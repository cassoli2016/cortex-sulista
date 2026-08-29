"""Gestão — atas de reunião, planos de ação (5W2H) e acompanhamento.

Três módulos, separados pela pergunta que respondem:

- `atas`      — o REGISTRO: o que foi reunido, quem esteve, o que se decidiu.
- `acoes`     — o COMPROMISSO: quem faz o quê até quando, e o histórico disso.
- `painel`    — a COBRANÇA: o que está atrasado, de quem, e há quanto tempo.

A separação não é estética. A ata é um documento que congela — depois de
publicada, ela descreve um fato passado e quase não muda. A ação é um registro
VIVO, que muda de status, de percentual e de prazo, e cujo valor está no
histórico. Misturar os dois no mesmo módulo faria a regra de imutabilidade da
ata brigar com a de mutabilidade da ação em toda função.

O SCHEMA É REDIRECIONADO NUM LUGAR SÓ: `comum.ESQUEMA`. A convenção da casa é
o módulo expor o próprio `ESQUEMA` (ver docs/MIGRACAO_POSTGRES.md), mas aqui
são três módulos sobre as MESMAS tabelas — três variáveis seriam três chances
de um teste redirecionar duas e gravar a terceira no schema de produção. Quem
procurar `ESQUEMA` em `acoes.py` não o encontra: está em `comum`, e é de lá que
sai o `_esq()` que todos usam.

O painel é o terceiro porque ele não escreve: só lê, agrega e ordena por
urgência. É a única parte que precisa ser rápida, e é a que mais vai mudar.
"""
