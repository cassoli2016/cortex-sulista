# -*- coding: utf-8 -*-
"""Portal de Cargas — o hub do cliente (menu proprio desde 17/09/2026).

O PEDIDO: um lugar onde o cliente acompanha as cargas dele, baixa as notas e
os CT-e, ve o peso transportado e fala com a Sulista — para parar de ligar
perguntando status e pedindo comprovante.

A BASE JA EXISTIA, e este pacote nao a reescreve: `api/portal_cliente.py` e
a "Minha Operacao" (tela `cliop`), com o vinculo de cliente no cadastro do
usuario, a trava no servidor e a leitura de estado (SAC + MDF-e + macros do
rastreador). O que mora AQUI e o que faltava a ela:

- `documentos` — CT-e, NF-e, peso e canhoto de cada carga, e o download
  que so entrega a chave que pertence a uma carga do cliente.

O ESCOPO E O MESMO DA MINHA OPERACAO, por decisao de quem opera (17/09/2026):
a raiz do CNPJ como tomador, pagador do frete ou destinatario, e a mesma
funcao (`portal_cliente.alvo`) decide de quem e a requisicao. Duas regras de
"quem ve o que" para o mesmo cliente discordariam por construcao — e aqui a
discordancia nao e um numero errado, e documento fiscal de uma empresa na
tela de outra.
"""
