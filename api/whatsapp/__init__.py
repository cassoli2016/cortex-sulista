"""Envio de mensagens de WhatsApp pela Z-API.

Organizado como o `api/correio` (o irmão mais velho, que manda e-mail):

    numeros.py   normaliza e valida telefone brasileiro
    config.py    ajustes que não são segredo (limites, assinatura, ativo)
    cliente.py   HTTP contra a Z-API
    registro.py  trilha em PostgreSQL (`zap_envios`)
    envio.py     a regra: valida, freia, envia, registra — e NUNCA levanta
    servico.py   diagnóstico para a tela de Saúde do Servidor

A diferença de fundo entre este módulo e o correio, e a razão de tanto código
para "mandar uma mensagem": e-mail é um protocolo aberto e ninguém perde a
conta por mandar e-mail demais. **Aqui o canal é o WhatsApp de um número real
da empresa, e ele pode ser BANIDO** — a própria Z-API documenta que basta um
padrão de disparo errado. Um banimento não é "a integração parou": é o número
comercial da Sulista fora do ar, com os clientes que já conversavam nele.

Por isso o freio (`envio.limite`) não é configuração opcional nem enfeite: é a
funcionalidade principal deste módulo.
"""
