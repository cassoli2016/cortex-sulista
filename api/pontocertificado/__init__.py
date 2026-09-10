# -*- coding: utf-8 -*-
"""Ponto Certificado — o REP-P em nuvem, lido direto.

O Globus lê o mesmo fornecedor só pelo AFD, que não tem coordenada e cuja
importação é manual (mediana de 3 dias). Aqui a batida chega em 10 segundos,
com GPS, local e cerca. Ver `cliente` para o que foi medido e as armadilhas.
"""
from .cliente import (  # noqa: F401
    DENTRO, FORA, SEM_COORDENADA, NaoConfigurado, PontoCertificadoIndisponivel,
    cercas, configurado, credencial, data_dotnet, diagnostico,
    marcacoes_desde, marcacoes_por_periodo, normalizar, o_que_falta,
    situacao, versao_api,
)
