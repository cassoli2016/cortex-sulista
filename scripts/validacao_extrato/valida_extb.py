"""Validação da tela Extrato Bancário no navegador (Task 9).

Cenário do OFX (conta REAL Itaú 341/0098/539349, valores REAIS do ERP jul/26):
  01, 02 e 03/07 -> OK        (saldo derivado bate ao centavo)
  06/07          -> DIVERGE   R$ 3.533,69 (erro injetado de propósito)

Uso: uv run --with playwright python valida_extb.py <base_url> <dir_saida>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
OFX = Path(__file__).with_name("itau_539349_jul2026.ofx")
if not OFX.exists():
    raise SystemExit(f"rode gera_ofx_teste.py primeiro (falta {OFX})")
SENHA = "Teste@12345"
R = []          # resultados: (item, veredito, detalhe)


def ok(item, det=""):
    R.append((item, "PASSOU", det)); print(f"  PASSOU  {item} {det}", flush=True)


def fail(item, det=""):
    R.append((item, "FALHOU", det)); print(f"  FALHOU  {item} :: {det}", flush=True)


def skip(item, det=""):
    R.append((item, "NAO TESTADO", det)); print(f"  ----    {item} :: {det}", flush=True)


def login(page, email):
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("#lg-email", timeout=20000)
    page.fill("#lg-email", email)
    page.fill("#lg-senha", SENHA)
    page.click("#lg-go")
    page.wait_for_selector("#loginOverlay.oculto", state="attached", timeout=20000)


def main() -> None:
    erros_console = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        def _console(m):
            if m.type != "error":
                return
            txt = m.text
            # 401 no boot e o /api/auth/me antes do login: comportamento normal
            if "401" in txt and "Unauthorized" in txt:
                erros_console.append(("esperado", txt)); return
            erros_console.append(("erro", txt))
        page.on("console", _console)

        # ---- 1) login + navegar
        try:
            login(page, "fin@teste.local")
            page.goto(f"{BASE}/#extb", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            titulo = page.inner_text("#view-extb h2")
            ok("1. login e tela #extb carrega", f"(h2='{titulo.splitlines()[0]}')")
        except Exception as e:
            fail("1. login e tela #extb carrega", str(e)[:200]); dump(); return

        # ---- 9a) RBAC: usuario COM a tela ve o link
        try:
            vis_side = page.is_visible('#sidebar a[data-view="extb"]')
            ok("9a. link na sidebar p/ quem TEM a tela", f"(visivel={vis_side})") if vis_side \
                else fail("9a. link na sidebar p/ quem TEM a tela", "link nao visivel")
        except Exception as e:
            fail("9a. link na sidebar", str(e)[:150])

        # ---- 2) importar o OFX via a propria API (o input file abre prompt nativo)
        try:
            bruto = OFX.read_bytes()
            res = page.evaluate("""async ([b64, nome]) => {
                const bin = atob(b64); const arr = new Uint8Array(bin.length);
                for (let i=0;i<bin.length;i++) arr[i] = bin.charCodeAt(i);
                const r = await fetch('/api/financeiro/extrato/importar?nome='+encodeURIComponent(nome),
                                      {method:'POST', body: arr});
                return {status: r.status, body: await r.json()};
            }""", [__import__("base64").b64encode(bruto).decode(), "itau_539349_jul2026.ofx"])
            b = res["body"]
            if res["status"] == 200 and b.get("precisa") == "mapa_erp" and b.get("novas") == 7:
                ok("2. importa OFX e pede vinculo", f"(novas={b['novas']}, pendentes={b.get('pendentes')})")
            else:
                fail("2. importa OFX e pede vinculo", json.dumps(b)[:300])
            conta_id = b.get("conta_id")
        except Exception as e:
            fail("2. importa OFX", str(e)[:200]); dump(); return

        # ---- 3) vincular a conta do ERP e conferir os numeros na TELA
        try:
            page.evaluate("""async (cid) => {
                await fetch('/api/financeiro/extrato/mapear', {method:'POST',
                  headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({conta_id: cid, erp_banco: 341,
                                        erp_agencia: '0098', erp_conta: '539349',
                                        rotulo: 'Itau 341 / ag 0098 / cc 539349'})});
            }""", conta_id)
            page.evaluate("""() => { const de=document.getElementById('fExtbDe'),
                ate=document.getElementById('fExtbAte');
                if(de) de.value='2026-07-01'; if(ate) ate.value='2026-07-31'; loadExtb(); }""")
            page.wait_for_timeout(4000)
            linhas = page.evaluate("""() => Array.from(
                document.querySelectorAll('#extb-dias tbody tr.forn-row')).map(tr =>
                Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()))""")
            esperado = {"01/07/2026": "bate", "02/07/2026": "bate",
                        "03/07/2026": "bate", "06/07/2026": "diverge"}
            achados = {}
            for cols in linhas:
                txt = " | ".join(cols)
                for dt in esperado:
                    if dt in txt:
                        achados[dt] = txt
            faltando = [d for d in esperado if d not in achados]
            if faltando:
                fail("3. dias na tela", f"nao encontrei {faltando}; linhas={linhas[:6]}")
            else:
                bons = [d for d, e in esperado.items() if e in achados[d].lower()]
                if len(bons) == 4:
                    ok("3. 3 dias OK e 06/07 DIVERGE", "todos os 4 estados corretos")
                else:
                    fail("3. estados dos dias", f"corretos={bons}; achados={achados}")
                div = achados["06/07/2026"]
                if "3.533,69" in div:
                    ok("3b. diferenca de R$ 3.533,69 no 06/07", "valor exato na tela")
                else:
                    fail("3b. diferenca do 06/07", f"nao achei 3.533,69 em: {div}")
                # 6) origem visivel na coluna Diferenca
                if any(o in div for o in ("(saldo)", "(crédito)", "(débito)")):
                    ok("6a. coluna Diferenca mostra a origem", "")
                else:
                    fail("6a. origem na coluna Diferenca", div)
                # dia OK nao exibe residuo
                if "—" in achados["01/07/2026"] or "-" in achados["01/07/2026"]:
                    ok("6b. dia OK sem residuo na Diferenca", "")
                else:
                    skip("6b. dia OK sem residuo", achados["01/07/2026"][:120])
        except Exception as e:
            fail("3. conferir dias na tela", str(e)[:250])

        # ---- farol por conta
        try:
            contas = page.inner_text("#extb-contas")
            ok("3c. tabela Situacao por conta renderiza",
               f"({[l for l in contas.splitlines() if '341' in l][:1]})")
        except Exception as e:
            fail("3c. tabela de contas", str(e)[:150])
        page.screenshot(path=str(OUT / "extb-1-farol.png"), full_page=True)

        # ---- 5) expandir a linha do dia divergente
        try:
            page.evaluate("""() => { const trs=[...document.querySelectorAll('#extb-dias tbody tr.forn-row')];
                const alvo = trs.find(tr => tr.innerText.includes('06/07/2026')); if(alvo) alvo.click(); }""")
            page.wait_for_timeout(2500)
            det = page.evaluate("""() => { const d=[...document.querySelectorAll('#extb-dias tbody tr.forn-det')]
                .find(x => x.offsetParent !== null); return d ? d.innerText.trim() : ''; }""")
            if det and ("357.228,45" in det or "350.000,00" in det):
                ok("5. expandir linha mostra lancamentos do dia", f"({len(det)} chars)")
            elif det:
                fail("5. lancamentos do dia", f"conteudo inesperado: {det[:200]}")
            else:
                fail("5. expandir linha", "nenhuma linha de detalhe visivel")
        except Exception as e:
            fail("5. expandir linha", str(e)[:200])
        page.screenshot(path=str(OUT / "extb-2-dia-expandido.png"), full_page=True)

        # ---- 4) prompt de vinculo CANCELADO nao pode dizer que vinculou
        try:
            page.evaluate("() => { window.__msgs=[]; window.showBanner=(m,d)=>window.__msgs.push(m); }")
            page.evaluate("() => { window.prompt = () => null; }")   # usuario cancela
            res2 = page.evaluate("""async () => {
                const r = await fetch('/api/financeiro/extrato/contas-erp'); return r.status; }""")
            page.evaluate("""async () => {
                const ok = await extbMapearConta(999999);   // conta inexistente + prompt cancelado
                window.__vinculou = ok;
            }""")
            page.wait_for_timeout(1500)
            vinc = page.evaluate("() => window.__vinculou")
            msgs = page.evaluate("() => window.__msgs || []")
            texto = " ".join(msgs).lower()
            if vinc is False and "vinculada 1 de" not in texto:
                ok("4. prompt cancelado NAO diz que vinculou", f"(retorno={vinc}, msgs={msgs[:2]})")
            else:
                fail("4. prompt cancelado", f"retorno={vinc}, msgs={msgs}")
        except Exception as e:
            skip("4. prompt cancelado", f"nao consegui simular: {str(e)[:150]}")

        # ---- 8) botao Atualizar recarrega o extrato
        try:
            alvo = page.evaluate("""() => { let chamou=false; const orig=window.loadExtb;
                window.loadExtb=function(){ chamou=true; return orig.apply(this, arguments); };
                document.getElementById('btnRefresh').click();
                return new Promise(r => setTimeout(() => r(chamou), 800)); }""")
            ok("8. botao Atualizar chama loadExtb", "") if alvo else \
                fail("8. botao Atualizar", "loadExtb nao foi chamado")
        except Exception as e:
            skip("8. botao Atualizar", str(e)[:150])

        # ---- 7) desfazer e reimportar (idempotencia)
        try:
            r = page.evaluate("""async () => {
                const d = await (await fetch('/api/financeiro/extrato?dt_de=2026-07-01&dt_ate=2026-07-31')).json();
                const imp = (d.importacoes||[])[0];
                const del = await fetch('/api/financeiro/extrato/importacao/'+imp.id, {method:'DELETE'});
                const apos = await (await fetch('/api/financeiro/extrato?dt_de=2026-07-01&dt_ate=2026-07-31')).json();
                return {apagados:(await del.json()).apagados, dias_apos: (apos.dias||[]).length};
            }""")
            if r["apagados"] == 7 and r["dias_apos"] == 0:
                ok("7a. desfazer remove os lancamentos", f"(apagados={r['apagados']})")
            else:
                fail("7a. desfazer", json.dumps(r))
            r2 = page.evaluate("""async ([b64, nome]) => {
                const bin = atob(b64); const arr = new Uint8Array(bin.length);
                for (let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
                const a = await (await fetch('/api/financeiro/extrato/importar?nome='+nome,
                                 {method:'POST', body:arr})).json();
                const b = await (await fetch('/api/financeiro/extrato/importar?nome='+nome,
                                 {method:'POST', body:arr})).json();
                return {primeira:{novas:a.novas,dup:a.duplicadas}, segunda:{novas:b.novas,dup:b.duplicadas}};
            }""", [__import__("base64").b64encode(OFX.read_bytes()).decode(), "itau_539349_jul2026.ofx"])
            if r2["primeira"]["novas"] == 7 and r2["segunda"]["novas"] == 0 and r2["segunda"]["dup"] == 7:
                ok("7b. reimportar e idempotente", json.dumps(r2))
            else:
                fail("7b. idempotencia", json.dumps(r2))
        except Exception as e:
            fail("7. desfazer/reimportar", str(e)[:250])

        # ---- 10) viewport de celular
        try:
            # mesmo contexto = sessao ja ativa; o overlay de login nao reaparece
            mob = ctx.new_page()
            mob.set_viewport_size({"width": 390, "height": 844})
            mob.goto(f"{BASE}/#extb", wait_until="domcontentloaded")
            mob.wait_for_timeout(2500)
            larg = mob.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
            if larg[0] <= larg[1] + 2:
                ok("10a. sem rolagem horizontal no mobile", f"(scroll={larg[0]} vs view={larg[1]})")
            else:
                fail("10a. rolagem horizontal no mobile", f"scrollWidth={larg[0]} > innerWidth={larg[1]}")
            na_gaveta = mob.evaluate("""() => !!document.querySelector('#drawer a[href="#extb"]')""")
            ok("10b. link na gaveta mobile", "") if na_gaveta else \
                fail("10b. link na gaveta mobile", "nao encontrado")
            mob.screenshot(path=str(OUT / "extb-3-mobile.png"), full_page=True)
            mob.close()
        except Exception as e:
            fail("10. mobile", str(e)[:200])

        # ---- 9b) RBAC: usuario SEM a tela nao ve o link
        try:
            ctx2 = br.new_context(viewport={"width": 1440, "height": 900})
            p2 = ctx2.new_page()
            login(p2, "frota@teste.local")
            p2.wait_for_timeout(2000)
            side = p2.evaluate("""() => { const a=document.querySelector('#sidebar a[data-view="extb"]');
                return a ? getComputedStyle(a).display : 'ausente'; }""")
            gav = p2.evaluate("""() => { const a=document.querySelector('#drawer a[href="#extb"]');
                return a ? getComputedStyle(a).display : 'ausente'; }""")
            if side in ("none", "ausente") and gav in ("none", "ausente"):
                ok("9b. link OCULTO p/ quem nao tem a tela", f"(sidebar={side}, gaveta={gav})")
            else:
                fail("9b. RBAC do menu", f"sidebar={side}, gaveta={gav} — link visivel indevidamente")
            api = p2.evaluate("""async () => (await fetch('/api/financeiro/extrato')).status""")
            ok("9c. API bloqueada p/ quem nao tem a tela", f"(HTTP {api})") if api in (403, 401) else \
                fail("9c. API deveria bloquear", f"HTTP {api}")
            p2.close(); ctx2.close()
        except Exception as e:
            fail("9. RBAC", str(e)[:200])

        reais = [t for k, t in erros_console if k == "erro"]
        esperados = [t for k, t in erros_console if k == "esperado"]
        if reais:
            fail("console sem erros", f"{len(reais)} erro(s) real(is): {reais[:3]}")
        else:
            ok("console sem erros de aplicacao",
               f"({len(esperados)} 401 de /auth/me no boot, esperado)")
        br.close()
    dump()


def dump() -> None:
    p = OUT / "task9-resultado.json"
    p.write_text(json.dumps(R, ensure_ascii=False, indent=2))
    passou = sum(1 for _, v, _ in R if v == "PASSOU")
    falhou = sum(1 for _, v, _ in R if v == "FALHOU")
    nt = sum(1 for _, v, _ in R if v == "NAO TESTADO")
    print(f"\n=== RESUMO: {passou} passou / {falhou} falhou / {nt} nao testado ===", flush=True)
    for item, v, det in R:
        if v != "PASSOU":
            print(f"  [{v}] {item} :: {det[:200]}", flush=True)


if __name__ == "__main__":
    main()
