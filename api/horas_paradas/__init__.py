"""HORAS PARADAS — a estadia que se cobra, cliente a cliente.

O pedido (12/09/2026): "um controle de horas paradas; cada cliente recebe de
um jeito e tem suas particularidades", com a planilha semanal de uma cliente
de exemplo e o Monitoramento SAC do ERP como base.

A PLANILHA FOI O ORÁCULO, e a conferência dela contra o ERP decidiu a
arquitetura (a lição de `docs/LICOES.md`, "a planilha que a torre mantinha à
mão era a especificação", valendo de novo). Todas as cargas da semana, linha
a linha:

- os horários de chegada e saída são as ocorrências SAC 394–397, e batem com o
  ERP em todas as linhas que ninguém corrigiu à mão;
- a conta NÃO é a do relatório do ERP. Ele conta da JANELA, sempre; a
  planilha conta do que vier depois — janela ou chegada — e, numa operação em
  que a janela de carregamento do ERP é derivada da entrega, da chegada. Isso
  é regra DO CLIENTE (`regras.py`), e por isso vive no perfil dele;
- o freetime sai da regra única da casa (`api/freetime.py`), com EXCEÇÕES que
  a planilha pratica e o contrato do ERP não diz — e a exceção é declarada no
  perfil, com nome, e aparece na linha;
- um terço das cargas tinha horário corrigido à mão (chegada, janela de
  descarga). Com a regra certa e esses ajustes, o motor reproduz todas as
  linhas ao centavo; só com o ERP, a semana sairia cerca de 5% menor. (Os
  números da planilha não entram aqui: o repositório é público, e medição de
  dado de cliente se registra pela forma.) O ajuste manual é
  parte do processo, e por isso tem tabela, motivo, autor e a foto do ERP.

Módulos:
    regras     a conta, pura (sem banco) — testável contra a planilha
    fonte      a leitura do ERP (Monitoramento SAC), por cliente
    cadastro   perfis (regra + layout) e ajustes, no banco da casa
    servico    junta tudo num período
    planilha   o .xlsx no layout do cliente
"""
