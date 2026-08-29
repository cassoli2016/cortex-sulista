"""Jornada do motorista — o detalhe que a RasterJOR alimenta no AVA.

O QUE JÁ EXISTIA e continua onde está: `queries.get_jornada()` monta o painel
de compliance por motorista a partir do CABEÇALHO diário (`jornada`), com as
flags que o próprio ERP apura. Isso não se refaz aqui.

O QUE ESTE PACOTE ACRESCENTA é o que só o detalhe da Raster responde:

- `espera`     — onde o motorista espera, por CLIENTE, cruzando o GPS do evento
                 com as cercas de `cadastro_poligono`.
- `composicao` — para onde vai o dia: direção, espera, refeição, descanso e
                 abastecimento, e o ciclo de direção/descanso da Lei 13.103.

═══════════════════════════════════════════════════════════════════════════
O MODELO DE DADOS, decodificado contra o banco em 29/08/2026
═══════════════════════════════════════════════════════════════════════════

Três tabelas parecem a mesma coisa e não são:

- `jornada`            — CABEÇALHO por jornada. Uma linha por (motorista,
                         sequência), com os totais já apurados pelo ERP.
- `jornada_registro`   — os EVENTOS daquela jornada. `sequencia` é a jornada
                         (casa com `jornada.sequencia`) e `sequenciajornada` é
                         a ordem do evento dentro dela. Tempos arredondados ao
                         minuto. **É a tabela certa para ler o detalhe.**
- `jornadamotorista`   — o mesmo evento no formato bruto do rastreador:
                         `sequencia` é um autoincremento global e
                         `sequenciajornada` vem NULO. Não dá para ligar ao
                         cabeçalho sem reconstruir a jornada. Serve para
                         auditoria de origem, não para painel.

`tipojornada` NÃO TEM TABELA DE DOMÍNIO no ERP. Os rótulos abaixo não foram
adivinhados: saíram de somar o tempo por tipo dentro de cada jornada e comparar
com as colunas NOMEADAS do cabeçalho, sobre 2.756 jornadas fechadas em 90 dias.
Onde diz 100%, é igualdade exata em todas as amostras.

    tipo 3  → tempodescanso            (100%)
    tipo 4  → tempointervalorefeicao   (100%)
    tipo 5  → tempoespera              (100%)
    tipo 10 → tempoabastecimento       (100%)
    tipo 2 + tipo 6 → tempodirecao     (100% somados; nenhum sozinho passa
                                        de 15%, então são duas modalidades de
                                        direção e não direção × outra coisa)
    tipo 8  → primeiro evento da jornada, sempre (início — média 19 min)
    tipo 7  → último evento da jornada, sempre, duração zero (fim)
    tipo 9  → repouso longo dentro da viagem (média 5h27). NÃO é
              `temporepouso`: essa coluna mede o intervalo ENTRE jornadas
              (média 22h30) e não sai de evento nenhum.

`tempojornada` NÃO É SOMA DE EVENTOS. Testadas oito combinações de tipos, a
melhor reproduz o valor do cabeçalho em 40% das jornadas. O ERP aplica regra
própria (arredondamento e deduções legais). **Quem precisar do total da jornada
lê o cabeçalho** — recalcular daria um número que não bate com a folha.

DUAS COLUNAS QUE PARECEM ÚTEIS E NÃO SÃO, medidas antes de virar cartão:
`tipoinclusao` é 2 em 100% dos eventos (não separa automático de manual) e
`justificativa` está NULA em 262.870 de 262.870. Coluna constante não vira
tela — só faria o leitor achar que há informação ali.
"""
