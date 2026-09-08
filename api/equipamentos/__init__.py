# -*- coding: utf-8 -*-
"""Cadastro de EQUIPAMENTOS — o registro de frota que é do CÓRTEX.

Módulo do grupo TMS. Hoje o ERP (Avacorp) é a fonte principal; amanhã ele sai,
e o cadastro fica. A arquitetura inteira existe para tornar essa saída um
evento medível em vez de uma reescrita:

    erp.py            a única porta para o AVA — o arquivo que morre junto
    smartec.py        o registro do DENATRAN, pelas tabelas que a Smartec
                      (já contratada) enche todo dia
    campos.py         o catálogo de campos e QUEM ganha de quem
    consolidacao.py   a precedência: de várias fontes discordando, um cadastro
    coleta.py         junta as duas fontes e reconstrói o consolidado
    armazenamento.py  as três tabelas `eqp_*` no banco da casa
    leitura.py        o que a tela pergunta
"""
