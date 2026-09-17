# -*- coding: utf-8 -*-
"""Portal de Cargas › Documentos e Peso (`pcdoc`), medido no navegador.

O que se confere aqui e o que so a TELA pode errar:
- o cliente VINCULADO nao ve seletor de cliente (quem decide e o servidor);
- os indicadores e as cargas saem do payload, com peso em t/kg;
- a carga abre o detalhe com o CT-e e as notas, e os botoes so aparecem onde
  ha arquivo — CT-e sem XML diz "arquivo indisponivel", sem botao;
- o download vira ARQUIVO quando da certo e AVISO quando o servidor recusa
  (a recusa legivel nao pode abrir como pagina crua numa aba).
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CH_CTE_XML = "3" * 44
CH_CTE_SEM = "5" * 44
CH_NFE = "4" * 44

CORPO = {
    "travado": True, "cliente_raiz": "11222333", "cliente_nome": "CLIENTE TESTE",
    "janela_max_dias": 93, "periodo": {"de": "2026-08-19", "ate": "2026-09-17"},
    "kpis": {"cargas": 2, "sem_cte": 1, "peso_kg": 23710.0, "ctes": 2,
             "ctes_com_xml": 1, "notas": 1, "notas_com_xml": 1, "canhotos": 1},
    "cargas": [
        {"coleta": 501, "emissao": "2026-09-10", "origem": "JOINVILLE", "uf_origem": "SC",
         "destino": "SAO PAULO", "uf_destino": "SP", "destinatario": "PLANTA SP",
         "ref_cliente": None, "peso_kg": 23710.0, "notas": 1, "canhoto": False,
         "ctes": [
             {"numero": 9001, "serie": 1, "emissao": "2026-09-10 10:00", "chave": CH_CTE_XML,
              "protocolo": "135000", "cancelado": False, "peso_kg": 23710.0, "tem_xml": True,
              "canhoto_em": "2026-09-12 08:00",
              "notas": [{"numero": 77, "chave": CH_NFE, "peso_kg": 23710.0, "tem_xml": True}]},
             {"numero": 9002, "serie": 1, "emissao": "2026-09-10 11:00", "chave": CH_CTE_SEM,
              "protocolo": "135001", "cancelado": False, "peso_kg": None, "tem_xml": False,
              "canhoto_em": None, "notas": []},
         ]},
        {"coleta": 502, "emissao": "2026-09-16", "origem": "JOINVILLE", "uf_origem": "SC",
         "destino": "CURITIBA", "uf_destino": "PR", "destinatario": "PLANTA PR",
         "ref_cliente": None, "peso_kg": None, "notas": 0, "canhoto": None, "ctes": []},
    ],
}


def _abre(pagina, corpo=CORPO, doc_status=200):
    pg, base = pagina
    pedidos = []

    def rota(r):
        u = r.request.url
        if "/api/auth/me" in u:
            r.fulfill(status=200, content_type="application/json", body=json.dumps(USUARIO))
        elif "/api/portal/cargas/documentos" in u:
            pedidos.append(u)
            r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
        elif "/api/portal/cargas/canhoto" in u:
            pedidos.append(u)
            if doc_status == 200:
                r.fulfill(status=200, content_type="application/pdf", body="%PDF-1.4",
                          headers={"Content-Disposition": 'attachment; filename="canhoto-x.pdf"'})
            else:
                r.fulfill(status=409, content_type="application/json", body=json.dumps(
                    {"erro": "sem_canhoto",
                     "mensagem": "Falta o acesso ao Drive onde o ERP guarda os canhotos."}))
        elif "/api/portal/cargas/documento" in u:
            pedidos.append(u)
            if doc_status == 200:
                r.fulfill(status=200, content_type="application/xml", body="<nfeProc/>",
                          headers={"Content-Disposition": f'attachment; filename="NFe-{CH_NFE}.xml"'})
            else:
                r.fulfill(status=doc_status, content_type="application/json", body=json.dumps(
                    {"erro": "sem_arquivo", "mensagem": "O XML desta nota não está guardado no sistema."}))
        else:
            r.fulfill(status=200, content_type="application/json", body="{}")
    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.goto(base + "/static/index.html#pcdoc")
    pg.wait_for_selector("#pcdoc-lista tr.pcdoc-carga")
    return pg, pedidos


def test_cliente_vinculado_ve_indicadores_e_cargas_sem_seletor(pagina):
    pg, _ = _abre(pagina)
    m = pg.evaluate("""() => ({
      seletor_oculto: document.getElementById('pcdoc-seletor').hidden,
      kpis: [...document.querySelectorAll('#kpis-pcdoc .kpi')].map(k => k.textContent.replace(/\\s+/g,' ')),
      linhas: document.querySelectorAll('#pcdoc-lista tr.pcdoc-carga').length,
      primeira: document.querySelector('#pcdoc-lista tr.pcdoc-carga').textContent.replace(/\\s+/g,' ')
    })""")
    assert m["seletor_oculto"] is True
    assert m["linhas"] == 2
    texto = " | ".join(m["kpis"])
    assert "23,7 t" in texto and "Peso transportado" in texto, texto
    assert "PLANTA SP" in m["primeira"] and "23,7 t" in m["primeira"], m["primeira"]


def test_a_carga_abre_o_detalhe_e_so_ha_botao_onde_ha_arquivo(pagina):
    pg, _ = _abre(pagina)
    pg.click('#pcdoc-lista tr.pcdoc-carga[data-c="501"]')
    det = pg.evaluate("""() => {
      const d = document.querySelector('#pcdoc-lista tr.pcdoc-det');
      return {texto: d.textContent.replace(/\\s+/g,' '),
              botoes: [...d.querySelectorAll('button')].map(
                  b => b.dataset.chave.slice(0,1) + ':' + (b.dataset.f || b.textContent.trim()))};
    }""")
    # CT-e com XML: XML e PDF; nota: XML e PDF; CT-e sem XML: nenhum botao
    # o CT-e 9001 tem XML e canhoto; o 9002 nao tem nenhum dos dois
    assert sorted(det["botoes"]) == sorted(
        ["3:xml", "3:pdf", "3:Baixar canhoto", "4:xml", "4:pdf"]), det["botoes"]
    assert "arquivo indisponível" in det["texto"]
    assert "canhoto anexado em 2026-09-12" in det["texto"]


def test_o_download_vira_arquivo_quando_da_certo(pagina):
    pg, pedidos = _abre(pagina)
    pg.click('#pcdoc-lista tr.pcdoc-carga[data-c="501"]')
    with pg.expect_download() as info:
        pg.click(f'#pcdoc-lista button[data-chave="{CH_NFE}"][data-f="xml"]')
    assert info.value.suggested_filename == f"NFe-{CH_NFE}.xml"
    baixado = [u for u in pedidos if "/documento?" in u]
    assert baixado and "raiz=" not in baixado[0], "cliente vinculado nao manda raiz"


def test_a_recusa_do_servidor_vira_AVISO_e_nao_pagina_crua(pagina):
    pg, _ = _abre(pagina, doc_status=409)
    pg.click('#pcdoc-lista tr.pcdoc-carga[data-c="501"]')
    pg.click(f'#pcdoc-lista button[data-chave="{CH_NFE}"][data-f="pdf"]')
    pg.wait_for_timeout(600)
    aviso = pg.evaluate("() => (document.getElementById('banner')||{}).textContent || ''")
    assert "não está guardado" in aviso, aviso


def test_gente_da_casa_sem_escolha_ve_o_seletor_e_nenhum_numero(pagina):
    corpo = {"escolher": True, "travado": False,
             "clientes": [{"raiz": "11222333", "nome": "CLIENTE TESTE", "cargas": 12}]}
    pg, base = pagina

    def rota(r):
        u = r.request.url
        corpo_r = USUARIO if "/api/auth/me" in u else (corpo if "/api/portal/cargas" in u else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo_r))
    pg.route("**/api/**", rota)
    pg.goto(base + "/static/index.html#pcdoc")
    pg.wait_for_selector("#fPcdocCliente option[value='11222333']", state="attached")
    m = pg.evaluate("""() => ({seletor: !document.getElementById('pcdoc-seletor').hidden,
                               kpis: document.getElementById('kpis-pcdoc').textContent.trim()})""")
    assert m["seletor"] is True and m["kpis"] == ""


def test_o_canhoto_baixa_e_so_aparece_onde_foi_anexado(pagina):
    """O botao segue o REGISTRO do ERP: CT-e sem canhoto nao ganha botao, para
    ninguem pedir um arquivo que nao existe."""
    pg, pedidos = _abre(pagina)
    pg.click('#pcdoc-lista tr.pcdoc-carga[data-c="501"]')
    with pg.expect_download() as info:
        pg.click(f'#pcdoc-lista button[data-chave="{CH_CTE_XML}"]:not([data-f])')
    assert info.value.suggested_filename == "canhoto-x.pdf"
    assert [u for u in pedidos if "/canhoto?" in u]
    sem = pg.locator(f'#pcdoc-lista button[data-chave="{CH_CTE_SEM}"]:not([data-f])')
    assert sem.count() == 0


def test_sem_acesso_ao_Drive_a_tela_DIZ_o_motivo(pagina):
    """Instalacao incompleta nao e erro: a recusa legivel chega como aviso, com
    o caminho de conserto (Integracoes > Canhotos)."""
    pg, _ = _abre(pagina, doc_status=409)
    pg.click('#pcdoc-lista tr.pcdoc-carga[data-c="501"]')
    pg.click(f'#pcdoc-lista button[data-chave="{CH_CTE_XML}"]:not([data-f])')
    pg.wait_for_timeout(600)
    aviso = pg.evaluate("() => (document.getElementById('banner')||{}).textContent || ''")
    assert "Drive" in aviso, aviso
