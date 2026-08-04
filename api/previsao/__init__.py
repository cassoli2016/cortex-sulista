"""Previsão de fechamento do mês — fachada pública."""
from api.queries import cached
from api.previsao.servico import get_previsao as _get_previsao

get_previsao_fechamento = cached(ttl=300)(_get_previsao)
