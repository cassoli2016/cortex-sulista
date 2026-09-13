# -*- coding: utf-8 -*-
"""WMS — o armazém da Sulista (grupo WMS do menu).

O DESENHO EM UMA FRASE: o saldo é a soma do kardex, o banco recusa saldo
negativo e kardex editado, o estado gravado é só decisão humana (abrir,
fechar, liberar, expedir, cancelar) e tudo que envelhece sozinho — mercadoria
parada na doca, pedido em separação, validade vencendo — se calcula na leitura.

O ERP entra por UMA porta (`erp.py`) e só para BUSCAR: a nota do cliente com
os itens (`coleta_notafiscal_item`, 1,48 milhão de linhas) e o cadastro de
clientes. O módulo WMS do próprio Avacorp existe e está vazio — medido em
12/09/2026 —, então nada aqui o espelha. Sem o ERP o armazém continua
operando: recebimento e pedido também nascem à mão.

Mapa dos arquivos:
  comum.py       domínios, transação com as mensagens do banco traduzidas
  erp.py         a ÚNICA leitura do Avacorp
  cadastro.py    armazéns, endereços, depositantes, produtos
  estoque.py     saldo, kardex, transferência, ajuste, bloqueio
  recebimento.py nota → conferência cega → entrada na doca
  expedicao.py   pedido → separação FEFO → expedição
  inventario.py  contagem cega por endereço → ajuste
  painel.py      a leitura do armazém (tela, Saúde e Copiloto)
  rotas.py       /api/wms/*
"""
