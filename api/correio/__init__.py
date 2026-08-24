"""Envio de e-mail do CÓRTEX.

O pacote se chama `correio` e NÃO `email` de propósito: `api/email/` não
quebraria o import da stdlib (Python 3 usa import absoluto), mas deixaria
duas coisas com o mesmo nome no mesmo projeto — e é `email.message` da
stdlib que este módulo usa para montar a mensagem.
"""
