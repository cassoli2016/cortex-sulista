"""O espelho no GitHub com um cliente dublê que copia o corpo real da API."""
from __future__ import annotations

from datetime import datetime, timezone

from api import pglocal
from api.reports.github import ErroGitHub
from api.suporte import chamados, espelho
from tests.suporte.conftest import PAYLOAD


class GitHubDublê:
    def __init__(self, falhar: bool = False):
        self.falhar = falhar
        self.issues: dict[int, dict] = {}
        self._coms: dict[int, list] = {}
        self.anexos: list = []
        self._n = 41
        self._c = 1000

    def subir_anexo(self, caminho, b64):
        self.anexos.append(caminho)
        return f"https://github.com/o/r/blob/main/{caminho}?raw=1"

    def criar_issue(self, titulo, corpo, rotulos):
        if self.falhar:
            raise ErroGitHub("GitHub respondeu 401: Bad credentials")
        self._n += 1
        self.issues[self._n] = {"number": self._n, "title": titulo, "body": corpo, "labels": [{"name": r} for r in rotulos],
                                "state": "open", "closed_at": None, "html_url": f"https://github.com/o/r/issues/{self._n}"}
        self._coms[self._n] = []
        return self._n, self.issues[self._n]["html_url"]

    def comentar(self, numero, corpo):
        if self.falhar:
            raise ErroGitHub("GitHub respondeu 403: rate limit")
        self._c += 1
        self._coms[numero].append({"id": self._c, "body": corpo, "user": {"login": "cortex-bot"},
                                         "created_at": datetime.now(timezone.utc).isoformat()})
        return self._c

    def alterar_issue(self, numero, *, state=None, labels=None, state_reason=None):
        i = self.issues[numero]
        if state:
            i["state"] = state
            i["closed_at"] = datetime.now(timezone.utc).isoformat() if state == "closed" else None
        if labels is not None:
            i["labels"] = [{"name": r} for r in labels]
        return i

    def comentarios(self, numero, since=None):
        return list(self._coms.get(numero, []))

    def issue(self, numero):
        return dict(self.issues[numero])

    # o que um humano faz lá na bancada
    def humano_comenta(self, numero, texto, login="dev"):
        self._c += 1
        self._coms[numero].append({"id": self._c, "body": texto, "user": {"login": login},
                                         "created_at": datetime.now(timezone.utc).isoformat()})
        return self._c

    def humano_fecha(self, numero):
        self.issues[numero]["state"] = "closed"
        self.issues[numero]["closed_at"] = datetime.now(timezone.utc).isoformat()
        self.issues[numero]["closed_by"] = {"login": "dev"}


def test_abertura_cria_issue_uma_vez_com_anexo_e_marcador(sup):
    gh = GitHubDublê()
    d = chamados.criar(sup["ana"], PAYLOAD)
    r = espelho.espelhar_abertura(d["id"], cliente=gh)
    assert r["ok"] and r["numero"] == 42
    issue = gh.issues[42]
    assert issue["title"].startswith(f"[{d['codigo']}] [Bug]") and "cortex-sup chamado:" in issue["body"]
    assert "O saldo da tela" in issue["body"] and "anexo-1.png" in issue["body"] and len(gh.anexos) == 1
    assert {l["name"] for l in issue["labels"]} >= {"cortex-report", "bug", "prioridade:alta", "tela:fluxo", "status:aberto"}
    c = chamados.obter(d["id"], suporte=True)
    assert c["github_numero"] == 42 and c["anexos"][0]["github_url"].endswith("?raw=1")
    assert espelho.espelhar_abertura(d["id"], cliente=gh)["ja_existia"] and len(gh.issues) == 1
    trilha = pglocal.query("SELECT resultado FROM sup_avisos WHERE chamado_id=%s AND canal='github'", (d["id"],), esquema=sup["esquema"])
    assert trilha[0]["resultado"] == "enviado"


def test_falha_do_github_nao_derruba_o_chamado(sup):
    gh = GitHubDublê(falhar=True)
    d = chamados.criar(sup["ana"], PAYLOAD)
    r = espelho.espelhar_abertura(d["id"], cliente=gh)
    assert r["ok"] is False and "401" in r["motivo"]
    c = chamados.obter(d["id"], suporte=True)
    assert c["github_numero"] is None and "401" in c["github_erro"] and "ghp_" not in c["github_erro"]
    assert chamados.obter(d["id"], usuario_id=sup["ana"]["id"]) is not None
    trilha = pglocal.query("SELECT resultado, detalhe FROM sup_avisos WHERE chamado_id=%s AND canal='github'", (d["id"],), esquema=sup["esquema"])
    assert trilha[0]["resultado"] == "recusado"


def test_sem_configuracao_e_sem_canal_e_tudo_funciona(sup, monkeypatch):
    from api.reports import github as ghmod
    monkeypatch.setattr(ghmod, "do_ambiente", lambda: None)
    d = chamados.criar(sup["ana"], PAYLOAD)
    r = espelho.espelhar_abertura(d["id"])
    assert r["ok"] is False and "desligado" in r["motivo"]
    trilha = pglocal.query("SELECT resultado FROM sup_avisos WHERE chamado_id=%s AND canal='github'", (d["id"],), esquema=sup["esquema"])
    assert trilha[0]["resultado"] == "sem_canal"
    assert espelho.sincronizar(forcar=True)["pulou"]


def test_mensagens_e_status_vao_para_a_issue_uma_vez(sup):
    gh = GitHubDublê()
    d = chamados.criar(sup["ana"], PAYLOAD)
    espelho.espelhar_abertura(d["id"], cliente=gh)
    r = chamados.responder(d["id"], sup["beto"], "suporte", "Estou vendo.")
    assert espelho.espelhar_mensagem(r["mensagem_id"], cliente=gh)["ok"]
    assert espelho.espelhar_mensagem(r["mensagem_id"], cliente=gh)["ok"] is False        # já espelhada
    assert len(gh._coms[42]) == 1 and "cortex-sup msg:" in gh._coms[42][0]["body"]
    assert "Beto Suporte · suporte" in gh._coms[42][0]["body"]
    chamados.mudar_status(d["id"], sup["beto"], "suporte", "resolvido", texto="feito")
    assert espelho.espelhar_status(d["id"], cliente=gh)["ok"]
    assert gh.issues[42]["state"] == "closed" and "status:resolvido" in {l["name"] for l in gh.issues[42]["labels"]}
    # reintento manual é idempotente
    t = espelho.espelhar_tudo(d["id"], cliente=gh)
    assert t["issue"]["ja_existia"] and len(gh.issues) == 1


def test_sincronizar_importa_comentario_humano_ignora_eco_e_fecha_uma_vez(sup, monkeypatch):
    from api.suporte import avisos
    monkeypatch.setattr(avisos, "avisar", lambda *a, **k: [])
    gh = GitHubDublê()
    espelho._ULTIMA_SYNC["em"] = None
    d = chamados.criar(sup["ana"], PAYLOAD)
    espelho.espelhar_abertura(d["id"], cliente=gh)
    r = chamados.responder(d["id"], sup["beto"], "suporte", "nossa")
    espelho.espelhar_mensagem(r["mensagem_id"], cliente=gh)          # eco: tem marcador
    gh.humano_comenta(42, "Reproduzi aqui, corrigindo.", login="dev")
    res = espelho.sincronizar(cliente=gh, forcar=True)
    assert res["importados"] == 1 and res["estados"] == 0, res
    c = chamados.obter(d["id"], suporte=True)
    imp = [m for m in c["mensagens_lista"] if m["origem"] == "github"]
    assert len(imp) == 1 and imp[0]["autor_nome"] == "dev" and imp[0]["papel"] == "suporte"
    # de novo: nada duplica (UNIQUE em github_comment_id)
    assert espelho.sincronizar(cliente=gh, forcar=True)["importados"] == 0
    # TTL: sem forçar, pula
    assert espelho.sincronizar(cliente=gh)["pulou"]
    # fechada lá → resolvida aqui, uma vez
    gh.humano_fecha(42)
    assert espelho.sincronizar(cliente=gh, forcar=True)["estados"] == 1
    assert chamados.obter(d["id"], suporte=True)["status"] == "resolvido"
    assert espelho.sincronizar(cliente=gh, forcar=True)["estados"] == 0
