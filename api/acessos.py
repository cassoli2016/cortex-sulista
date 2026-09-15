"""Ajustes de acesso POR USUÁRIO, por cima do perfil (13/09/2026).

Pedido de quem opera: "ao cadastrar um usuário, informar a página inicial
dele; colocar permissões especiais por usuário, tirar acesso a determinadas
abas, dar acesso a telas específicas — para elevar o nível de segurança".

O PERFIL CONTINUA SENDO A REGRA; O AJUSTE É A EXCEÇÃO COM NOME. Antes daqui,
toda exceção virava um perfil novo com uma pessoa só dentro, e perfil de uma
pessoa não se distingue de perfil de verdade na lista — ninguém o revisa.

TRÊS DECISÕES de quem opera, com as alternativas na mesa:

1. **"Tirar" vence tudo** — o perfil e a liberação. Entre dois registros que
   discordam, o sistema fica do lado que dá MENOS acesso.
2. **Administrador vê tudo.** Ajuste não se aplica a perfil administrador: a
   ficha mostra os ajustes guardados, mas o cálculo os ignora enquanto o perfil
   for admin. (Tirar tela de admin seria segurança de faz de conta: ele abre a
   Gestão e devolve.)
3. **Aba só se tira onde o SERVIDOR consegue recusar.** Em ~3 de cada 4 abas o
   dado chega ao navegador junto com a tela inteira (é o mesmo payload, só
   desenhado em outro painel); esconder o botão ali não impede ninguém de ler o
   número nas ferramentas do navegador, e chamar isso de "tirar acesso" daria
   uma segurança que não existe. Por isso `ABAS` lista só as abas cuja rota de
   dados é DELA — tirar a aba recusa a rota (403) no `AuthMiddleware`. As
   outras aparecem na Gestão como "não bloqueável: os dados vêm com a tela".

O ACESSO EFETIVO É CALCULADO, NUNCA GRAVADO. `auth.sessao_atual()` já relê o
perfil a cada requisição; os ajustes entram no mesmo cálculo, e por isso tirar
uma tela vale no clique seguinte, sem derrubar a sessão de ninguém.

Este módulo não importa `api.auth` no topo (é o `auth` que o importa); o que
ele precisa do registro de telas chega por parâmetro.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

EFEITOS = ("liberar", "tirar")

#: Teto de ajustes por pessoa. Com ~95 telas e dezenas de abas bloqueáveis,
#: 400 cabe tudo; o teto existe para um payload errado não virar milhares de
#: linhas.
MAX_AJUSTES = 400

# ─────────────────────────────────────────────── ABAS BLOQUEÁVEIS ──────────
#
# Cada entrada é UMA unidade de bloqueio: uma aba (ou um par de abas da mesma
# tela que dividem a mesma rota) cuja rota de dados é EXCLUSIVA dela.
#
#   "tela.unidade": {
#       "tela":     chave de auth.TELAS a que a aba pertence,
#       "rotulo":   como aparece na Gestão,
#       "abas":     (("grupo data-abas", "chave data-aba"), ...) — o que a tela esconde,
#       "rotas":    prefixos que o servidor recusa (e tudo abaixo deles),
#       "exatas":   rotas recusadas SÓ quando exatas (a Projeção lê
#                   /api/financeiro/projecao, e /projecao/detalhe é de outra aba),
#       "leitores": funções da página que BUSCAM o dado — perguntam abaOculta()
#                   antes, senão o 403 vira barra de erro numa aba que a pessoa
#                   nem vê,
#       "acoes":    as outras funções da página que citam a rota (botões),
#   }
#
# FICARAM DE FORA, com o motivo (varredura de 13/09/2026): as 7 abas novas do
# CRM (um só Promise.all — bloquear uma apaga as sete), a Minha Operação
# (mesma rota da base, muda só a query, e a TV do cliente usa), o Portal Tupy
# (é a aba padrão e o erro vira banner na tela), Decidir/Plano do Fluxo
# Consolidado (o cartão de premissas de outra aba sai dele), a Condução da
# frota (outras abas reusam o cache), Ordens sem nota (alimenta indicadores de
# outras abas), as abas do WMS carregadas no Promise.all da base e todas as que
# só desenham o payload da tela.
#
# REGRA PARA ENTRAR AQUI, conferida por `tests/test_acessos_abas.py`:
#   - cada rota existe no app e cada aba existe no index.html;
#   - cada rota só é referenciada no index.html dentro dos carregadores
#     desta unidade — rota que outra tela também lê NÃO é bloqueável por aba
#     (tirar a aba derrubaria a outra tela);
#   - a tela da unidade é a mesma a que a rota pertence em ROTA_TELAS.
def _u(tela, rotulo, abas, rotas=(), exatas=(), leitores=(), acoes=()):
    return {"tela": tela, "rotulo": rotulo, "abas": tuple(abas), "rotas": tuple(rotas),
            "exatas": tuple(exatas), "leitores": tuple(leitores), "acoes": tuple(acoes)}


ABAS: dict[str, dict] = {
    # ── Controladoria · DRE (as quatro abas que buscam ao abrir) ──
    "dre.atk": _u("dre", "Onde atacar", [("dre", "atk")],
                  ["/api/dre/alavancas"], leitores=["loadDreAtk"]),
    "dre.pano": _u("dre", "Conta a conta", [("dre", "pano")],
                   ["/api/dre/panorama"], leitores=["loadDrePano"]),
    "dre.par": _u("dre", "Parecer", [("dre", "par")],
                  ["/api/dre/parecer"], leitores=["loadDrePar"], acoes=["dreParNarrar"]),
    "dre.exc": _u("dre", "Excluídos", [("dre", "exc")],
                  ["/api/dre/exclusoes", "/api/dre/lancamentos"], leitores=["loadDreExc"],
                  acoes=["dreExcBuscar", "dreExcMarcar", "dreExcRemover"]),
    # ── Financeiro ──
    "fluxcon.plano": _u("fluxcon", "Projeção", [("fluxcon", "plano")],
                        ["/api/financeiro/dda"], exatas=["/api/financeiro/projecao"],
                        leitores=["loadProjecao"], acoes=["ddaDetalhe", "ddaImportar"]),
    "antport.eleg": _u("antport", "Elegíveis fora de portal", [("antport", "eleg")],
                       ["/api/financeiro/antecipacao/elegiveis"], leitores=["loadElegiveis"]),
    # ── Operação ──
    "prog.cic": _u("prog", "Ciclos", [("prog", "cic")],
                   ["/api/operacao/programacao/ciclos"], leitores=["loadProgCiclos"]),
    "jorn.diarias": _u("jorn", "Diárias e auditoria das diárias",
                       [("jorn", "diaria"), ("jorn", "audit")], ["/api/jornada/diarias"],
                       leitores=["carregarDiarias", "carregarAuditDiarias"]),
    "pedagio.tag": _u("pedagio", "Tag (fatura)", [("ped", "tag")],
                      ["/api/operacao/pedagio/tag"], leitores=["loadPedTag"],
                      acoes=["pedTagEnviarUma"]),
    "pedagio.aud": _u("pedagio", "Auditoria", [("ped", "aud")],
                      ["/api/operacao/pedagio/auditoria"], leitores=["loadPedAud"]),
    # A REGRA DE COBRANÇA de cada cliente move dinheiro (13/09/2026, pedido de
    # quem opera). Junto da aba vai o CADASTRO de cliente (`/perfis/novo`,
    # `/clientes`): nascer um perfil também é decidir como se cobra. A lista
    # de perfis (GET `/perfis`) fica fora de propósito — é dela que a aba das
    # cargas precisa.
    "hp.regras": _u("hp", "Regras do cliente (e cadastro de cliente)", [("hp", "regras")],
                    ["/api/operacao/horas-paradas/catalogo",
                     "/api/operacao/horas-paradas/perfis/salvar",
                     "/api/operacao/horas-paradas/perfis/novo",
                     "/api/operacao/horas-paradas/clientes"],
                    leitores=["hpRegrasAbrir"],
                    acoes=["hpSalvar", "hpNovoPerfil", "hpCriarPerfil"]),
    # ── Frota ──
    "man.compras": _u("man", "Compras da OS e recompra de peça",
                      [("man", "comp"), ("man", "rec")], ["/api/frota/compras-os"],
                      leitores=["loadComprasOs"]),
    "mul.erp": _u("mul", "Histórico e responsáveis (ERP)", [("smt", "hist"), ("smt", "resp")],
                  ["/api/frota/multas"], leitores=["loadMulErp"]),
    "pneus.cpk": _u("pneus", "CPK e km", [("pneus", "cpk")],
                    ["/api/frota/pneus/rendimento"], leitores=["pnCpkCarregar"]),
    "pneus.troca": _u("pneus", "Previsão de troca", [("pneus", "troca")],
                      ["/api/frota/pneus/troca"], leitores=["pnTrocaCarregar"]),
    "pneus.registrar": _u("pneus", "Registrar", [("pneus", "registrar")],
                          ["/api/frota/pneus/motivos", "/api/frota/pneus/recentes",
                           "/api/frota/pneus/ficha", "/api/frota/pneus/posicoes",
                           "/api/frota/pneus/movimento"],
                          leitores=["pnRegAbrir", "pnRegRecentes"],
                          acoes=["pnRegBuscar", "pnRegPosicoes", "pnRegGravar"]),
    # ── Telemetria ──
    "telcon.evo": _u("telcon", "Evolução mensal", [("telcon", "evo")],
                     ["/api/telemetria/consumo/evolucao"], leitores=["telconEvolucao"]),
    "telcon.com": _u("telcon", "Comunicação", [("telcon", "com")],
                     ["/api/telemetria/comunicacao"], leitores=["loadTelconComunicacao"]),
    "telcond.mot": _u("telcond", "Por motorista", [("telcond", "mot")],
                      ["/api/telemetria/motoristas"], leitores=["loadTelcondMotoristas"]),
    "prem.cfg": _u("prem", "Configuração", [("prem", "cfg")],
                   ["/api/premiacao/config", "/api/premiacao/recoletar",
                    "/api/premiacao/ocorrencias"], leitores=["premCfgCarregar"],
                   acoes=["premCfgSalvar", "premRecoletar", "premOcoSalvar", "premOcoSync"]),
    # ── RH ──
    "ferias.custo": _u("ferias", "Custo e passivo, e agendadas",
                       [("ferias", "custo"), ("ferias", "agenda")], ["/api/rh/ferias/custo"],
                       leitores=["loadFeriasCusto"]),
    "rhmot.mural": _u("rhmot", "Comunicados", [("rhmot", "mural")],
                      ["/api/rh/motorista/mural"], leitores=["loadRhmotMural"],
                      acoes=["rhmotPublicar", "rhmotFaltam", "rhmotEncerrar"]),
    "folha.estrutura": _u("folha", "Estrutura e evolução", [("folha", "nat"), ("folha", "evo")],
                          ["/api/rh/folha-estrutura"], leitores=["carregarFolhaEstrutura"]),
    "freq.dia": _u("freq", "O dia", [("freq", "dia")],
                   ["/api/rh/frequencia/dia"], leitores=["loadFreqDia"]),
    "freq.batidas": _u("freq", "Batidas", [("freq", "batidas")],
                       ["/api/rh/frequencia/batidas", "/api/rh/frequencia/cercas"],
                       leitores=["loadFreqBatidas", "loadFreqCercas"]),
    "des.mat": _u("des", "Matriz", [("des", "mat")],
                  ["/api/desempenho/matriz"], leitores=["loadDesMatriz"]),
    "des.ava": _u("des", "Avaliar", [("des", "ava")],
                  ["/api/desempenho/equipe", "/api/desempenho/avaliar"],
                  leitores=["loadDesEquipe"], acoes=["desGravar"]),
    # ── TMS ──
    "ctecp.transmitidos": _u("ctecp", "Transmitidos e documentos",
                             [("cp", "transmitidos"), ("cp", "documentos")],
                             ["/api/fiscal/contrapartida/transmitidos"],
                             leitores=["loadCtetx"], acoes=["cpCancelar"]),
    "ctecp.implantacao": _u("ctecp", "Implantação", [("cp", "implantacao")],
                            ["/api/fiscal/contrapartida/validacao"], leitores=["cpValidarTudo"]),
    # ── WMS ──
    "wmsest.kdx": _u("wmsest", "Kardex", [("wmsest", "kdx")],
                     ["/api/wms/estoque/kardex"], leitores=["wmsEstKardex"]),
    # ── Suporte ──
    "supfila.config": _u("supfila", "Configuração", [("supfila", "config")],
                         ["/api/suporte/atendimento/config"], leitores=["supConfigCarregar"],
                         acoes=["supConfigSalvar"]),
}


def aba_da_rota(path: str) -> str | None:
    """A unidade de aba bloqueável a que esta rota pertence, ou None."""
    for chave, u in ABAS.items():
        if path in u.get("exatas", ()):
            return chave
        for prefixo in u.get("rotas", ()):
            if path == prefixo or path.startswith(prefixo + "/"):
                return chave
    return None


def ocultas(abas_tiradas: list[str]) -> list[list[str]]:
    """Os pares [grupo, aba] que a tela esconde, para as unidades tiradas."""
    return [[g, k] for chave in abas_tiradas if chave in ABAS
            for g, k in ABAS[chave]["abas"]]


# ───────────────────────────────────────────────────────── o cálculo ───────

def efetivas(telas_perfil, ajustes, admin: bool, todas) -> tuple[list[str], list[str]]:
    """(telas efetivas, unidades de aba tiradas) de uma pessoa.

    `todas` é a lista ordenada de `auth.TELAS`; `ajustes` são pares
    (chave, efeito). Chave desconhecida é IGNORADA — tela aposentada deixa a
    linha inerte, e inerte quer dizer que ela nunca amplia acesso.
    """
    todas = list(todas)
    if admin:
        return todas, []
    conhecidas = set(todas)
    liberar = {c for c, e in ajustes if e == "liberar" and c in conhecidas}
    tirar = {c for c, e in ajustes if e == "tirar"}
    do_perfil = set(telas_perfil)
    telas = [t for t in todas if (t in do_perfil or t in liberar) and t not in tirar]
    visiveis = set(telas)
    abas = [c for c, e in ajustes
            if e == "tirar" and c in ABAS and ABAS[c]["tela"] in visiveis]
    return telas, sorted(abas)


def validar(bruto, todas) -> tuple[list[tuple[str, str]] | None, str | None]:
    """Normaliza a lista de ajustes que veio da tela. Recusa, dizendo o motivo:
    chave que não é tela nem aba bloqueável, efeito desconhecido, aba com
    "liberar" e chave repetida."""
    if not isinstance(bruto, list):
        return None, "Os ajustes de acesso vieram num formato inválido."
    if len(bruto) > MAX_AJUSTES:
        return None, f"São no máximo {MAX_AJUSTES} ajustes por usuário."
    conhecidas = set(todas)
    vistos: set[str] = set()
    saida: list[tuple[str, str]] = []
    for item in bruto:
        if not isinstance(item, dict):
            return None, "Os ajustes de acesso vieram num formato inválido."
        chave = str(item.get("chave") or "").strip()
        efeito = str(item.get("efeito") or "").strip()
        if efeito not in EFEITOS:
            return None, f"Ajuste com efeito desconhecido: {efeito or '(vazio)'}."
        if chave in ABAS:
            if efeito != "tirar":
                return None, ("Aba só se tira: quem tem a tela já vê as abas dela. "
                              f"Ajuste recusado: {ABAS[chave]['rotulo']}.")
        elif chave not in conhecidas:
            return None, f"'{chave}' não é uma tela nem uma aba bloqueável."
        if chave in vistos:
            return None, f"'{chave}' aparece duas vezes nos ajustes."
        vistos.add(chave)
        saida.append((chave, efeito))
    return saida, None


def pagina_efetiva(pagina: str | None, telas, admin: bool) -> str | None:
    """A página inicial que VALE agora, ou None (= a da casa, o radar).

    Estado que envelhece se calcula: se a pessoa perdeu a tela escolhida, a
    escolha continua gravada (volta a valer se a tela voltar), mas não abre.
    """
    from api import auth   # tardio: o auth importa este módulo
    p = (pagina or "").strip()
    if not p or not pagina_escolhivel(p):
        return None
    if p in auth.TELAS_TODO_LOGADO:
        return p
    if p in ("gestao", "srv"):
        return p if admin else None
    alvo = "jorn" if p == "jornf" else p
    return p if (admin or alvo in set(telas)) else None


def pagina_escolhivel(pagina: str) -> bool:
    """A chave pode ser página inicial de ALGUÉM? (não diz se desta pessoa)."""
    from api import auth
    return (pagina in auth.TELAS and pagina not in auth.TELAS_SEM_MENU) \
        or pagina in auth.TELAS_FORA_DO_RBAC


def diff(antes, depois) -> str:
    """Texto da trilha: o que entrou e o que saiu. Vazio = nada mudou."""
    a, d = set(antes), set(depois)
    partes = [f"+{e} {c}" for c, e in sorted(d - a)] + [f"-{e} {c}" for c, e in sorted(a - d)]
    return ", ".join(partes)


# ─────────────────────────────────────────────────────────── o banco ───────

_TEM: dict = {}


def tem_estrutura(c) -> bool:
    """A migration 0091 já rodou neste banco?

    Memoiza SÓ o sim. Entre o código chegar e a migration rodar há uma janela
    (ver `auth.tem_coluna_vinculo`); nela, `sessao_atual` roda a cada
    requisição e não pode derrubar o login de todo mundo por causa de uma
    tabela que ainda não existe — sem ela, ninguém tem ajuste, e o acesso é o
    do perfil, como sempre foi.
    """
    if _TEM.get("ok"):
        return True
    try:
        ok = bool(c.execute(
            "SELECT to_regclass('usuario_acessos') IS NOT NULL AS ok").fetchone()["ok"])
    except Exception:  # noqa: BLE001
        return False
    if ok:
        _TEM["ok"] = True
    return ok


def ajustes_de(c, usuario_id: int) -> list[tuple[str, str]]:
    if not tem_estrutura(c):
        return []
    return [(r["chave"], r["efeito"]) for r in c.execute(
        "SELECT chave, efeito FROM usuario_acessos WHERE usuario_id=%s ORDER BY chave",
        (usuario_id,)).fetchall()]


def todos_os_ajustes(c) -> dict[int, list[tuple[str, str]]]:
    if not tem_estrutura(c):
        return {}
    saida: dict[int, list[tuple[str, str]]] = {}
    for r in c.execute("SELECT usuario_id, chave, efeito FROM usuario_acessos "
                       "ORDER BY usuario_id, chave").fetchall():
        saida.setdefault(r["usuario_id"], []).append((r["chave"], r["efeito"]))
    return saida


def gravar(c, usuario_id: int, ajustes, autor: str, agora: str) -> None:
    """Troca TODOS os ajustes da pessoa pelos de `ajustes` (lista completa)."""
    c.execute("DELETE FROM usuario_acessos WHERE usuario_id=%s", (usuario_id,))
    for chave, efeito in ajustes:
        c.execute("INSERT INTO usuario_acessos(usuario_id, chave, efeito, criado_em, criado_por)"
                  " VALUES(%s,%s,%s,%s,%s)", (usuario_id, chave, efeito, agora, autor))


def detalhar(telas_perfil, ajustes, admin: bool, todas) -> dict:
    """O acesso de UMA pessoa, tela a tela e com a ORIGEM de cada uma — para o
    relatório de permissões da Gestão (pedido de quem opera, 15/09/2026).

    SAI DO MESMO `efetivas()` QUE A SESSÃO USA, e esse é o ponto: um relatório
    que refizesse a regra por conta própria poderia afirmar um acesso que o
    servidor recusa, ou esconder um que ele concede — e relatório de permissão
    que discorda do sistema é pior que relatório nenhum, porque é nele que a
    auditoria confia. Aqui só se EXPLICA de onde veio cada tela.

    Origem: `perfil` (o perfil dá — liberar o que o perfil já dá é redundante
    e continua sendo "perfil"), `liberada` (ajuste da pessoa) ou
    `administrador`. `tiradas` são as telas que o perfil ou uma liberação
    dariam e um ajuste tira; "tirar" o que a pessoa nem teria é inerte e não
    aparece. Admin ignora os ajustes: `ajustes_ignorados` diz quantos estão
    guardados, que é o que a ficha mostra.
    """
    todas = list(todas)
    ajustes = list(ajustes)
    telas, abas = efetivas(telas_perfil, ajustes, admin, todas)
    if admin:
        return {"telas": [{"chave": t, "origem": "administrador"} for t in telas],
                "tiradas": [], "abas_tiradas": [], "ajustes_ignorados": len(ajustes)}
    do_perfil = set(telas_perfil)
    liberar = {c for c, e in ajustes if e == "liberar"}
    tirar = {c for c, e in ajustes if e == "tirar"}
    return {
        "telas": [{"chave": t, "origem": "perfil" if t in do_perfil else "liberada"}
                  for t in telas],
        "tiradas": [t for t in todas if t in tirar and (t in do_perfil or t in liberar)],
        "abas_tiradas": abas,
        "ajustes_ignorados": 0}


def catalogo_abas(telas_registro: dict) -> list[dict]:
    """As abas bloqueáveis para a Gestão, com o rótulo e o grupo da tela."""
    saida = []
    for chave, u in ABAS.items():
        rot, grp = telas_registro.get(u["tela"], (u["tela"], ""))
        saida.append({"chave": chave, "tela": u["tela"], "tela_rotulo": rot,
                      "grupo": grp, "rotulo": u["rotulo"]})
    return saida
