"""E-mail de boas-vindas ao CÓRTEX, enviado ao cadastrar um usuário.

SENHA POR E-MAIL É O PONTO FRACO DESTE DESENHO, e vale dizer isso por escrito
em vez de deixar implícito: o e-mail fica na caixa de entrada, é encaminhável e
sobrevive a backup. O padrão mais forte seria um LINK DE PRIMEIRO ACESSO com
validade curta, que não carrega segredo reutilizável. Como a senha provisória
foi o que se pediu, ela vem com as quatro defesas que a tornam aceitável:

1. **Ela é GERADA AQUI, não digitada pelo administrador.** Senha provisória
   escolhida por gente vira "Mudar@123" em toda a empresa, e aí o e-mail deixa
   de ser o elo fraco — o elo fraco passa a ser o padrão que todo mundo sabe.
   `segredos.choice` sobre um alfabeto sem caractere ambíguo (O/0, l/1/I), que
   é o que faz alguém digitar errado e pedir outra.
2. **A troca no primeiro acesso já é obrigatória** (`deve_trocar_senha=1`, que
   o cadastro já grava e a tela já cobra). A senha do e-mail serve uma vez.
3. **Ela NUNCA entra na trilha de auditoria nem no log.** O que se registra é
   que o e-mail saiu, para quem e quando — nunca o segredo. Um audit_log com
   senhas seria pior que o e-mail.
4. **O e-mail diz que ela é provisória** e o que fazer se não foi você quem
   pediu o acesso.

O OVERVIEW LISTA SÓ O QUE AQUELE USUÁRIO ABRE. Mandar as 65 telas para quem
tem 8 é uma promessa quebrada no primeiro clique — e é o tipo de detalhe que
faz alguém achar que o sistema está com defeito quando está só com perfil.
"""
from __future__ import annotations

import secrets
from datetime import datetime

from . import config as cfg
from . import envio

# ── senha provisória ─────────────────────────────────────────────────────────
# Sem O/0, l/1/I: ambiguidade em senha lida de e-mail e digitada à mão é o que
# gera o chamado "não funciona" que na verdade é um zero lido como ó.
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
_SIMBOLOS = "!@#$%&*-+="
SENHA_TAM = 14


def gerar_senha(tam: int = SENHA_TAM) -> str:
    """Senha provisória forte, sem caractere ambíguo.

    `secrets`, não `random`: o segundo é previsível a partir do estado interno
    e não tem nada que fazer perto de credencial.
    """
    corpo = "".join(secrets.choice(_ALFABETO) for _ in range(tam - 2))
    return corpo + secrets.choice(_SIMBOLOS) + secrets.choice("23456789")


# ── o que este usuário vê ────────────────────────────────────────────────────
def telas_do_usuario(telas: list[str] | None, admin: bool) -> list[tuple[str, list[str]]]:
    """Os grupos e telas que ESTE usuário abre, na ordem do menu.

    Administrador vê tudo, e é dito como tal em vez de listado — 65 telas num
    e-mail não é boas-vindas, é intimidação.
    """
    from api import auth
    permitidas = set(telas or [])
    grupos: dict[str, list[str]] = {}
    for chave, (rotulo, grupo) in auth.TELAS.items():
        if not admin and chave not in permitidas:
            continue
        grupos.setdefault(grupo, []).append(rotulo)
    return [(g, sorted(t)) for g, t in sorted(grupos.items(),
                                              key=lambda x: (-len(x[1]), x[0]))]


# ── o texto ──────────────────────────────────────────────────────────────────
_INTRO = (
    "O CÓRTEX é o painel de gestão da Sulista: ele reúne, num lugar só, os "
    "números de operação, frota, financeiro, controladoria e pessoas que hoje "
    "ficam espalhados entre o ERP, as planilhas e os portais dos fornecedores."
)

_COMO_LER = [
    ("Todo número diz de onde veio",
     "Passe o mouse no ⓘ ao lado do título de cada cartão: ele mostra a tabela "
     "e a regra que geraram aquele valor. Se um número parecer estranho, é ali "
     "que começa a conferência."),
    ("Recorte parcial aparece hachurado",
     "Barra listrada é período incompleto — mês corrente, ou mês cortado pelo "
     "filtro. Ela não está caindo: está pela metade."),
    ("Os filtros valem para a tela inteira",
     "Quando um cartão não segue o filtro, ele diz isso no próprio cartão. "
     "Nenhum número muda de recorte em silêncio."),
    ("O Copiloto responde em português",
     "Dá para perguntar \"como está o caixa?\" ou \"quais clientes caíram este "
     "mês?\" e ele responde sobre os dados do painel, citando as telas."),
]


def montar(nome: str, email: str, senha: str, url: str,
           telas: list[str] | None = None, admin: bool = False,
           perfil: str = "", teste: bool = False) -> tuple[str, str, str]:
    """Devolve (assunto, corpo_texto, corpo_html).

    O HTML SAI DO LAYOUT COMPARTILHADO (`correio.painel`), não de marcação
    própria. A primeira versão deste arquivo tinha HTML só dele e nasceu com
    uma faixa escura no topo — exatamente o que a casa não faz — porque a
    regra vivia no outro módulo. Com um layout só, a regra vale para o
    próximo e-mail sem ninguém precisar lembrar dela.
    """
    from . import painel as p

    grupos = telas_do_usuario(telas, admin)
    marca = "[TESTE] " if teste else ""
    assunto = f"{marca}Bem-vindo ao CÓRTEX — seu acesso está pronto"
    primeiro = (nome or "").strip().split(" ")[0] or "você"

    # ── texto puro: cliente que não renderiza HTML ainda precisa ENTRAR ──────
    linhas = [
        f"Olá, {primeiro}.", "", _INTRO, "",
        "SEU ACESSO", f"  Endereço: {url}", f"  Usuário:  {email}",
        f"  Senha provisória: {senha}", "",
        "A senha acima é provisória e o sistema vai pedir a troca no primeiro",
        "acesso. Ela serve uma vez.", "",
    ]
    if perfil:
        linhas += [f"SEU PERFIL: {perfil}", ""]
    if admin:
        linhas += ["VOCÊ TEM ACESSO A TODAS AS TELAS DO PAINEL.", ""]
    elif grupos:
        linhas += ["O QUE VOCÊ ABRE"]
        for g, ts in grupos:
            linhas.append(f"  {g}: " + ", ".join(ts))
        linhas.append("")
    linhas += ["COMO LER O PAINEL"]
    for t, d in _COMO_LER:
        linhas += [f"  {t}", f"    {d}"]
    linhas += ["",
               "Se não foi você quem pediu este acesso, avise a área de TI e",
               "não use a senha acima.", "",
               "— CÓRTEX · Sulista Transportes"]
    texto = chr(10).join(linhas)

    # ── HTML, todo em blocos do layout compartilhado ────────────────────────
    blocos = [p.cabecalho(f"Bem-vindo, {primeiro}.",
                          "Seu acesso ao painel de gestão da Sulista")]
    if teste:
        blocos.append(p.paragrafo(
            "Este é um e-mail de teste. A senha abaixo é um exemplo e não dá "
            "acesso a nada.", destaque=True))
    blocos.append(p.paragrafo(_INTRO))
    blocos.append(p.campos(
        [("Endereço", p.Html(f'<a href="{p._esc(url)}" style="color:{p.LARANJA};'
                             f'text-decoration:none;font-weight:700">'
                             f'{p._esc(url)}</a>')),
         ("Usuário", email),
         ("Senha provisória", senha)],
        titulo="Seu acesso", mono=(1, 2)))
    blocos.append(p.paragrafo(
        "A senha acima é provisória: o sistema pede a troca no primeiro acesso "
        "e ela deixa de valer. Não a reaproveite em outro serviço.",
        destaque=True))

    blocos.append(p.secao("O que você abre", perfil or ""))
    if admin:
        blocos.append(p.paragrafo(
            "Seu perfil abre todas as telas do painel, incluindo a área de "
            "Administração."))
    elif not grupos:
        blocos.append(p.paragrafo(
            "Seu perfil ainda não tem telas liberadas. Fale com quem cadastrou "
            "seu acesso antes do primeiro login.", destaque=True))
    else:
        blocos.append(p.tabela(["Área", "Telas"],
                               [[g, ", ".join(ts)] for g, ts in grupos]))

    blocos.append(p.secao("Como ler o painel"))
    for t, d in _COMO_LER:
        blocos.append(p.paragrafo(f"{t} — {d}"))

    blocos.append(p.botao("Entrar no CÓRTEX", url))
    blocos.append(p.paragrafo(
        "Se não foi você quem pediu este acesso, avise a área de TI e não use "
        "a senha deste e-mail."))
    html = p.documento(assunto, blocos, origem="cadastro de usuário")
    return assunto, texto, html


# ── envio ────────────────────────────────────────────────────────────────────
def enviar_boas_vindas(email: str, nome: str, senha: str, url: str, *,
                       telas: list[str] | None = None, admin: bool = False,
                       perfil: str = "", autor: str = "",
                       teste: bool = False) -> dict:
    """Manda o e-mail. Nunca levanta — devolve `{'ok', 'erro'}`.

    NÃO PODE DERRUBAR O CADASTRO. O usuário já foi criado quando isto roda; se
    o e-mail falhar, quem cadastrou precisa saber para entregar a senha por
    outro caminho — mas o cadastro em si está feito, e desfazê-lo por causa do
    e-mail seria trocar um problema pequeno por um grande.
    """
    if not cfg.configurado():
        return {"ok": False, "erro": "O envio de e-mail não está configurado "
                                     "(Gestão › Correio)."}
    if not (url or "").strip():
        return {"ok": False, "erro": "Falta o endereço do painel (CORTEX_URL, "
                                     "em Gestão › Integrações). Sem ele o "
                                     "e-mail não diz onde entrar."}
    assunto, texto, html = montar(nome, email, senha, url.strip(),
                                  telas=telas, admin=admin, perfil=perfil,
                                  teste=teste)
    # `registrar=True` grava QUE saiu, para quem e quando. A senha não vai
    # junto — trilha com segredo dentro é pior que o e-mail.
    return envio.enviar([email], assunto, texto, corpo_html=html,
                        usuario=autor, origem="boas_vindas")
