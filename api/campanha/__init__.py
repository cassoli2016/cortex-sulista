# -*- coding: utf-8 -*-
"""PROGRAMA DE DESEMPENHO — a campanha trimestral com sorteio.

Este docstring é o CONTRATO do módulo. As regras abaixo valem para tudo que
entrar aqui depois, e quem precisar quebrar uma delas quebra por escrito.

═══════════════════════════════════════════════════════════════════════════
O QUE ESTE MÓDULO É, E O QUE ELE NÃO É
═══════════════════════════════════════════════════════════════════════════
Ele NÃO é a premiação mensal (`api/premiacao/`). Aquela PAGA, todo ciclo, por
uma régua operacional que a mesa ajusta quando quer. Esta é um REGULAMENTO:
documento assinado, com vigência, público definido e um sorteio no fim.

As duas leem os MESMOS três pilares e chegam a notas DIFERENTES, de propósito —
os pesos do regulamento são 50/30/20 e os da régua operacional, 40/40/20. Por
isso a régua da campanha mora na tabela `cmp_campanha`: o peso que decide quem
concorre a um prêmio é o que está no papel que o motorista assinou, e ele não
pode mudar porque alguém mexeu na régua operacional em novembro.

O CÁLCULO DOS PILARES É O MESMO CÓDIGO (`api/premiacao/pilares.py`). Duas
implementações da mesma leitura divergiriam em silêncio, e aqui a divergência
apareceria como "a campanha diz 91 e a premiação diz 88" — com uma moto em
jogo.

═══════════════════════════════════════════════════════════════════════════
DOIS GRUPOS QUE NÃO SE MISTURAM
═══════════════════════════════════════════════════════════════════════════
FROTA e AGREGADO competem SEPARADOS (decisão de quem opera, 18/09/2026): cada
um tem o seu ranking e o seu sorteio. Quem é quem:

- **FROTA**: o motorista próprio do cadastro da premiação, que vem da folha.
- **AGREGADO**: quem rodou, no ciclo, veículo com `utilizacaoveiculo = 'AGR'`.
  Terceiro (`TER`) e locado (`LOC`) ficam de fora — o regulamento fala em
  "motoristas de frota e agregados".

═══════════════════════════════════════════════════════════════════════════
A CHAVE É OPACA, PORQUE A DO ERP É O CPF
═══════════════════════════════════════════════════════════════════════════
O código do motorista agregado em `programacaoembarque.motorista` **é o CPF**
— 11 dígitos em 279 de 279, medido em 18/09/2026. Publicar esse código na tela
seria publicar documento. Por isso quem sai daqui é `chave()`: um resumo
determinístico do CPF dentro da campanha, que serve para casar linha com linha
e não serve para descobrir de quem é.

═══════════════════════════════════════════════════════════════════════════
TELEMETRIA É CONDIÇÃO PARA DISPUTAR
═══════════════════════════════════════════════════════════════════════════
A Gobrax vale metade da nota e enxergava 34% dos agregados (43 de 127 em
agosto/2026). Quem não tem leitura PARTICIPA — vê a nota dele, os pilares que
entraram e o que falta — mas fica FORA do sorteio, e a tela diz isso desde o
primeiro dia. É a única forma de todos os que disputam serem medidos pela mesma
régua; renormalizar faria "90 pontos" significar coisas diferentes para pessoas
diferentes, com um prêmio sendo decidido pela diferença.

═══════════════════════════════════════════════════════════════════════════
O SORTEIO SE AUDITA, OU NÃO É SORTEIO
═══════════════════════════════════════════════════════════════════════════
O regulamento promete "conduzido de forma transparente e auditável", e isso não
é adjetivo: é a lista congelada ANTES (`cmp_foto`), a SEMENTE registrada, e o
resultado com suplente. Com a semente e a lista, qualquer pessoa refaz o
sorteio e chega no mesmo nome. Sem os três, "foi sorteado" é uma afirmação que
ninguém pode conferir depois.

E o que o sistema NÃO sabe, ele não afirma: documentação de MOPP, tacógrafo,
seguro e pendência financeira não estão em lugar nenhum que se possa consultar
daqui. O sistema exclui o que MEDE (categoria, telemetria, CNH vencida, vínculo)
e a gestão exclui o resto à mão, com motivo, na ata do sorteio.
"""
from __future__ import annotations

#: Schema do banco local. `None` = o padrão (`cortex`); os testes apontam para
#: um schema descartável — e o teste que esquecer de redirecionar ESTE escreve
#: em produção.
ESQUEMA: str | None = None

GRUPOS = ("FROTA", "AGREGADO")

#: Os rótulos do regulamento. Categoria aqui tem QUATRO faixas (a régua
#: operacional tem cinco, com DIAMANTE): são documentos diferentes, e copiar as
#: faixas de um para o outro é como as duas passam a discordar.
CATEGORIAS = ("ELITE", "OURO", "PRATA", "BRONZE")
