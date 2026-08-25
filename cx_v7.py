import functools, http.server, json, socketserver, threading, urllib.parse
from playwright.sync_api import sync_playwright
from api.milkrun.servico import get_milkrun
import api.queries as q; q._RESP_CACHE.clear()
def payload(qs):
    p = urllib.parse.parse_qs(qs); g = lambda k, d='': (p.get(k) or [d])[0]
    return json.loads(json.dumps(get_milkrun(g('de') or '2026-08-24', g('ate') or '2026-08-24',
        '02162259', g('situacao'), g('fornecedor'), g('placa')), default=str))
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory="api/static")
srv = socketserver.TCPServer(("127.0.0.1",0), h); porta=srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
def rota(r):
    u=r.request.url
    if "milkrun" in u: body=payload(urllib.parse.urlparse(u).query)
    elif "/auth/me" in u: body={"usuario":"mwm","admin":False,"telas":["milkrun"],"perfil":"C"}
    else: body={}
    r.fulfill(status=200, content_type="application/json", body=json.dumps(body))
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1500,"height":1200})
    erros=[]; pg.on("pageerror", lambda e: erros.append(repr(e)))
    pg.route("**/api/**", rota); pg.goto(f"http://127.0.0.1:{porta}/index.html"); pg.wait_for_timeout(1800)
    erros.clear()
    def carrega(de,ate):
        pg.evaluate("""([a,b])=>{document.querySelectorAll('.view').forEach(v=>v.classList.remove('on'));
            document.getElementById('view-milkrun').classList.add('on');
            document.getElementById('fMilkDe').value=a; document.getElementById('fMilkAte').value=b;}""",[de,ate])
        pg.evaluate("loadMilkrun()"); pg.wait_for_timeout(2500)
    carrega('2026-08-24','2026-08-24')
    r=pg.evaluate("""()=>({
      altura:document.getElementById('content').scrollHeight,
      grupos:document.querySelectorAll('.milk-grupo').length,
      recolhidos:document.querySelectorAll('.milk-grupo.rec').length,
      colunas:[...document.querySelectorAll('.milk-grupo thead th')].map(t=>t.textContent.trim()),
      cards:[...document.querySelectorAll('#kpis-milkrun .kpi .label')].map(l=>l.textContent.replace(/\u24d8/,'').trim()),
      tem_manual: document.getElementById('view-milkrun').textContent.toLowerCase().includes('manual')})""")
    open('cx_o.txt','w',encoding='utf-8').write(json.dumps(r, ensure_ascii=False, indent=1))
    # expandir uma
    pg.evaluate("()=>{const g=document.querySelector('.milk-grupo'); if(g) milkToggle(g.id.replace('milk-g-',''));}")
    pg.wait_for_timeout(400)
    print("apos expandir 1:", pg.evaluate("document.querySelectorAll('.milk-grupo:not(.rec)').length"), "aberto(s)")
    print("erros:", erros or "nenhum")
    pg.locator("#view-milkrun").screenshot(path="cx_mr.png", timeout=40000)
    b.close()
srv.shutdown()
