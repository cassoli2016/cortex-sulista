"""Peças compartilhadas por `atas` e `acoes` — e só as compartilhadas.

Existe para que "quem é o responsável" tenha UMA resposta na casa. O par
(`usuario_id`, `nome`) aparece em participante de reunião e em responsável de
ação, e as duas regras têm de ser a mesma: id quando a pessoa tem login, nome
quando não tem, nunca nenhum dos dois. Duas implementações divergiriam no dia
em que uma delas aceitasse o registro sem dono — que é justamente o registro
que ninguém cobra.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import migracoes, pglocal

ESQUEMA: str | None = None

# Tetos de texto. Não são preciosismo: `o_que` vai para o assunto do e-mail de
# cobrança e para a coluna da tabela, e um parágrafo colado ali quebra os dois.
# Quem tem mais a dizer usa `como` e os andamentos, que são campos longos.
TITULO_MAX = 200
TEXTO_MAX = 20000
NOME_MAX = 120

STATUS_ACAO = ("aberta", "em_andamento", "concluida", "cancelada")
PRIORIDADES = ("baixa", "media", "alta", "critica")
STATUS_ATA = ("rascunho", "publicada")
TIPOS_REUNIAO = ("diretoria", "area", "projeto", "comite", "cliente", "outra")

# Rótulos em português para tela, e-mail e auditoria — num lugar só, senão a
# tela diz "em_andamento" em algum canto que ninguém revisou.
ROTULO_STATUS = {"aberta": "Aberta", "em_andamento": "Em andamento",
                 "concluida": "Concluída", "cancelada": "Cancelada"}
ROTULO_PRIORIDADE = {"baixa": "Baixa", "media": "Média",
                     "alta": "Alta", "critica": "Crítica"}
ROTULO_TIPO = {"diretoria": "Diretoria", "area": "Área", "projeto": "Projeto",
               "comite": "Comitê", "cliente": "Cliente", "outra": "Outra"}

# Áreas sugeridas no formulário. Lista ABERTA de propósito (o campo é texto
# livre): engessar em CHECK obrigaria migration para cada área nova, e o custo
# de uma grafia divergente aqui é um filtro com duas linhas parecidas, não um
# número errado.
AREAS = ("Financeiro", "Comercial", "Operação", "Frota", "Controladoria",
         "Suprimentos", "Recursos Humanos", "Tecnologia", "Diretoria",
         "Qualidade", "Jurídico")


class DadoInvalido(ValueError):
    """O que veio da tela não pode ser gravado, e a mensagem diz por quê."""


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hoje() -> date:
    return date.today()


def texto(valor, rotulo: str, *, maximo: int = TEXTO_MAX,
          obrigatorio: bool = False) -> str:
    """Normaliza e confere tamanho. Devolve '' para ausente, nunca None —
    coluna `text NOT NULL DEFAULT ''` não aceita None, e deixar o banco recusar
    daria 'erro de gravação' onde cabe uma frase que a pessoa entende."""
    s = ("" if valor is None else str(valor)).strip()
    if obrigatorio and not s:
        raise DadoInvalido(f"Informe {rotulo}.")
    if len(s) > maximo:
        raise DadoInvalido(
            f"{rotulo[0].upper()}{rotulo[1:]} tem {len(s)} caracteres e o "
            f"limite é {maximo}.")
    return s


def escolha(valor, permitidos: tuple[str, ...], rotulo: str,
            padrao: str | None = None) -> str:
    s = ("" if valor is None else str(valor)).strip().lower()
    if not s and padrao is not None:
        return padrao
    if s not in permitidos:
        raise DadoInvalido(
            f"{rotulo} deve ser um de: {', '.join(permitidos)}.")
    return s


def data_br(valor, rotulo: str, *, obrigatorio: bool = False) -> date | None:
    """Aceita ISO (o que o `<input type=date>` manda) e dd/mm/aaaa (o que
    alguém digita ao colar de uma planilha). Recusa o resto DIZENDO o formato —
    'data inválida' sozinho manda a pessoa adivinhar."""
    if isinstance(valor, date):
        return valor
    s = ("" if valor is None else str(valor)).strip()
    if not s:
        if obrigatorio:
            raise DadoInvalido(f"Informe {rotulo}.")
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise DadoInvalido(
        f"{rotulo[0].upper()}{rotulo[1:]} não é uma data — use aaaa-mm-dd "
        f"ou dd/mm/aaaa.")


def inteiro(valor, rotulo: str, *, minimo: int, maximo: int,
            padrao: int | None = None) -> int:
    if valor is None or valor == "":
        if padrao is None:
            raise DadoInvalido(f"Informe {rotulo}.")
        return padrao
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        raise DadoInvalido(f"{rotulo[0].upper()}{rotulo[1:]} deve ser um "
                           f"número inteiro.") from None
    if not (minimo <= n <= maximo):
        raise DadoInvalido(f"{rotulo[0].upper()}{rotulo[1:]} deve ficar entre "
                           f"{minimo} e {maximo}.")
    return n


def valor_br(valor, rotulo: str):
    """Dinheiro digitado por gente. Vazio devolve None (que é 'não estimado',
    diferente de zero).

    A REGRA É A MESMA DO `numBR()` do index.html, e ela existe porque
    `<input type="number">` DESCARTA a vírgula em vez de recusá-la: '1234,56'
    vira 123456, cem vezes o valor, sem erro. Aqui o campo chega como texto e
    é convertido com regra explícita — ponto em grupo de exatamente 3 dígitos
    é milhar (1.234 = mil duzentos e trinta e quatro), vírgula é decimal.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return round(float(valor), 2)
    s = str(valor).strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:                      # vírgula manda: ponto vira milhar
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:            # 1.234.567 — todos milhar
        s = s.replace(".", "")
    else:
        inteira, _, dec = s.partition(".")
        if dec and len(dec) == 3 and inteira.lstrip("-").isdigit():
            s = inteira + dec         # 1.234 é milhar, não 1,234
    try:
        return round(float(s), 2)
    except ValueError:
        raise DadoInvalido(f"{rotulo[0].upper()}{rotulo[1:]} não é um valor "
                           f"válido. Use 1.234,56.") from None


def iso(linha: dict, *campos: str) -> dict:
    """`date` do psycopg vira texto ISO, no lugar.

    Não é formatação: `JSONResponse` NÃO serializa `datetime.date` e a rota
    estoura com 500 — que o Cloudflare troca pela página de erro dele, então a
    tela recebe "erro interno da API" sem JSON nenhum. Um teste de rota pegou;
    os testes de serviço passavam porque nunca serializam.

    ISO e não dd/mm/aaaa porque é o que `<input type=date>` aceita de volta e
    o que o `fmtD()` do index.html sabe formatar.
    """
    for c in campos:
        v = linha.get(c)
        if isinstance(v, date):
            linha[c] = v.isoformat()
    return linha


def pessoa(usuario_id, nome, rotulo: str, esquema: str | None = None) -> tuple:
    """Resolve o par (id, nome) de responsável/participante.

    Confere que o usuário EXISTE — id de usuário apagado gravaria uma ação sem
    dono que ninguém veria, porque o LEFT JOIN devolve nome vazio e a tela
    mostra a linha em branco. E guarda o nome JUNTO do id: se o usuário for
    excluído depois, `ON DELETE SET NULL` zera o id e o nome é o que sobra
    para dizer de quem era a tarefa.
    """
    uid = None
    if usuario_id not in (None, "", 0, "0"):
        try:
            uid = int(usuario_id)
        except (TypeError, ValueError):
            raise DadoInvalido(f"{rotulo} inválido.") from None
    n = texto(nome, rotulo, maximo=NOME_MAX)
    if uid is not None:
        u = pglocal.um("SELECT nome FROM usuarios WHERE id=%s", (uid,),
                       esquema=_esq(esquema))
        if not u:
            raise DadoInvalido(f"O usuário escolhido como {rotulo.lower()} "
                               f"não existe mais.")
        return uid, (n or u["nome"])
    if not n:
        raise DadoInvalido(
            f"Informe {rotulo.lower()} — escolha um usuário do CÓRTEX ou "
            f"digite o nome de quem não tem acesso ao sistema.")
    return None, n


def usuarios_ativos(esquema: str | None = None) -> list[dict]:
    """Para o seletor de responsável e de participante.

    Só os ATIVOS: atribuir tarefa a quem saiu da empresa é o erro que o
    formulário deve tornar impossível, não o que ele deve permitir e reportar
    depois. Quem já é responsável e foi desativado continua aparecendo na ação
    (o nome está gravado), mas não entra em atribuição nova.
    """
    return pglocal.query(
        "SELECT id, nome, email, coalesce(cargo,'') AS cargo, "
        "       coalesce(setor,'') AS setor "
        "FROM usuarios WHERE ativo=1 ORDER BY nome",
        esquema=_esq(esquema))
