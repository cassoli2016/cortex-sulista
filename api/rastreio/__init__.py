"""Rastreio público de carga — "Onde está minha carga?".

A ÚNICA TELA DESTA CASA SEM LOGIN, e por isso a única em que a pergunta de
segurança vem antes da de produto. Todo o resto do CÓRTEX é fail-closed: rota
`/api/*` sem mapeamento é 403, e ainda há o Cloudflare Access por cima. Aqui a
porta fica aberta de propósito, então quem decide o que passa por ela é este
módulo.

O QUE NÃO SE BUSCA AQUI, e por quê
==================================
**Placa e número de frota ficam de fora.** Uma página pública que aceita placa
e devolve onde o caminhão está agora não é rastreamento de carga: é ferramenta
de roubo de carga. Quem quiser interceptar não precisa de mais nada além da
placa, que está pintada na porta do veículo.

**CNPJ sozinho fica de fora.** Buscar por CNPJ devolveria todas as cargas
daquela empresa — bastaria digitar o CNPJ de um cliente para mapear a operação
dele, ou o de um concorrente para mapear a carteira dele.

O que passa é DOCUMENTO EM MÃOS: o número do CT-e ou o da nota fiscal, que
quem despachou e quem recebe já têm. Quem não tem o documento não é parte na
carga — e um número sequencial sozinho não basta, porque o segundo campo (os
quatro primeiros dígitos do CNPJ) impede varrer 1160750, 1160751, 1160752…

O QUE NÃO SAI DAQUI
===================
Valor do frete, telefone, CPF, CNPJ completo, coordenada exata. A posição sai
como CIDADE e PROGRESSO — responde "onde está e quando chega", que é o que
quem espera a carga quer saber, sem entregar coordenada de rodovia a quem
estiver só olhando.

O QUE PASSOU A SAIR, E SOB QUE CONDIÇÕES (05/09/2026)
=====================================================
Cliente, pagador do frete, placa do cavalo, placa da carreta e nome do
motorista entraram no DETALHE da carga, a pedido de quem opera: quem espera na
doca precisa saber que placa e que motorista liberar na portaria, e hoje pede
isso por telefone.

Isso reverte, em parte, a linha "nome de motorista" que estava aqui — e as
condições em que ela cai valem mais que a reversão:

- **Só no DETALHE de UMA carga**, que reprova o segundo fator (documento + 4
  dígitos do CNPJ) ou apresenta o token assinado do link. Nunca na lista da
  busca, que é apenas o seletor de qual carga abrir.
- **Nunca na mensagem de WhatsApp.** Ela é texto encaminhável, aparece na tela
  de bloqueio e vive anos num grupo — os guards de `mensagem` e `aviso`
  continuam proibindo placa e motorista, e é de propósito que o bloco se chama
  `transporte`: quem escrever mensagem nova não o alcança por descuido.
- **A placa continua fora da BUSCA.** Aceitar placa como ENTRADA é o que faria
  desta página um localizador de caminhão por placa; essa regra não mudou, e é
  outra da que caiu.

O que se ganha em troca do risco é assimétrico a nosso favor: quem já tem o
documento e o CNPJ da carga é parte nela, e para essa pessoa a placa não é
descoberta — ela vai conferi-la no portão daqui a pouco.
"""
