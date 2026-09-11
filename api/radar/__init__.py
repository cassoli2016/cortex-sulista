# -*- coding: utf-8 -*-
"""Radar do Transporte — a página inicial do CÓRTEX.

É a tela que TODO usuário logado vê ao entrar, e por isso ela só publica dado
PÚBLICO: preço do diesel da ANP, Brent, dólar do Banco Central e notícias. A
Visão Geral continua existindo, atrás do RBAC, para quem pode ver o número da
casa — a página inicial não pode depender de perfil, e dado de negócio na
página de todos seria vazamento pela porta da frente.

- `fontes.py`   — baixar e LER cada fornecedor (sem banco);
- `coleta.py`   — gravar no banco da casa (`rad_*`), idempotente, com cadência;
- `painel.py`   — o que a tela e o Copiloto leem, e o cartão da Saúde;
- `agendador.py` — a thread que coleta, só no líder e nunca sob pytest.
"""
