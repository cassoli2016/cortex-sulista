"""Reusa as fixtures de frontend para o e2e da tela do piso.

base_url sobe um http.server sobre api/, e pagina abre o Chromium com as rotas
/api/** interceptadas — o mesmo arranjo dos demais testes de UI da casa.
"""
from tests.frontend.conftest import base_url, pagina  # noqa: F401
