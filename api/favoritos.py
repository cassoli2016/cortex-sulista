"""Favoritos de tela, por usuário.

O QUE ISTO É, E O QUE NÃO É
===========================
O drawer já tem **"Suas mais usadas"**, que sai do `localStorage` e é derivada
de comportamento: ninguém escolhe, ela se forma sozinha. Favorito é o oposto —
é **escolha explícita**, e por isso mora no banco e segue a pessoa entre o
computador e o celular. As duas coisas convivem: uma responde "onde você mais
vai" e a outra "onde você quer ir com um toque".

O RBAC É APLICADO NA LEITURA, NUNCA NA GRAVAÇÃO
===============================================
Favorito de tela cujo acesso foi revogado **não é apagado — deixa de
aparecer**. Apagar destruiria a escolha de quem pode recuperar o acesso na
semana seguinte e esperaria encontrar tudo como deixou. Filtrar na leitura
custa nada e é reversível.

E o filtro é **obrigatório**: sem ele, um favorito antigo viraria um atalho
para uma tela que a pessoa não pode mais ver — que é vazamento de navegação,
mesmo que a rota barre depois. A tela nem deve ser oferecida.
"""
from __future__ import annotations

from datetime import datetime

from . import pglocal

ESQUEMA: str | None = None

# Teto por usuário. Não é limitação técnica: é a razão de o favorito existir.
# Uma lista de trinta atalhos não encurta caminho nenhum — vira outro menu,
# com o agravante de estar fora de ordem alfabética e sem agrupamento.
LIMITE = 12


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def listar(usuario_id: int, telas_permitidas: set[str] | None = None,
           esquema: str | None = None) -> list[str]:
    """Os favoritos do usuário, na ordem escolhida, FILTRADOS pelo RBAC.

    `telas_permitidas=None` devolve tudo — usar só onde não há usuário logado
    (teste, migração). Toda chamada vinda de rota passa o conjunto real.
    """
    linhas = pglocal.query(
        "SELECT tela FROM usuario_favoritos WHERE usuario_id = %s "
        "ORDER BY ordem, tela", (usuario_id,), esquema=_esq(esquema))
    telas = [l["tela"] for l in linhas]
    if telas_permitidas is None:
        return telas
    return [t for t in telas if t in telas_permitidas]


def alternar(usuario_id: int, tela: str, telas_permitidas: set[str],
             esquema: str | None = None) -> dict:
    """Liga ou desliga o favorito. Devolve o estado NOVO.

    RECUSA tela a que o usuário não tem acesso — e a recusa é dita, não
    silenciosa: quem chamou está com uma tela que não devia ter oferecido, e
    engolir isso esconderia o defeito.
    """
    tela = (tela or "").strip()
    if not tela:
        raise ValueError("Informe a tela.")
    if tela not in telas_permitidas:
        raise PermissionError(
            f"Sem acesso à tela '{tela}' — ela não pode ser favoritada.")

    esq = _esq(esquema)
    ja = pglocal.um(
        "SELECT 1 AS x FROM usuario_favoritos "
        "WHERE usuario_id = %s AND tela = %s", (usuario_id, tela), esquema=esq)
    if ja:
        pglocal.executar(
            "DELETE FROM usuario_favoritos WHERE usuario_id = %s AND tela = %s",
            (usuario_id, tela), esquema=esq)
        return {"tela": tela, "favorito": False}

    atuais = listar(usuario_id, None, esq)
    if len(atuais) >= LIMITE:
        raise ValueError(
            f"Você já tem {LIMITE} favoritos, que é o máximo. Tire um antes "
            "de acrescentar — uma lista maior que isso deixa de ser atalho.")

    # o novo entra no FIM: quem acabou de favoritar sabe onde procurar, e
    # empurrar os outros para baixo mexeria numa ordem que a pessoa arrumou
    proxima = pglocal.um(
        "SELECT coalesce(max(ordem), -1) + 1 AS n FROM usuario_favoritos "
        "WHERE usuario_id = %s", (usuario_id,), esquema=esq)
    pglocal.executar(
        "INSERT INTO usuario_favoritos(usuario_id, tela, ordem, criado_em) "
        "VALUES (%s, %s, %s, %s)",
        (usuario_id, tela, (proxima or {}).get("n") or 0,
         datetime.now().isoformat(timespec="seconds")), esquema=esq)
    return {"tela": tela, "favorito": True}


def reordenar(usuario_id: int, telas: list[str], telas_permitidas: set[str],
              esquema: str | None = None) -> list[str]:
    """Grava a ordem que a pessoa arrastou.

    Só reordena o que JÁ é favorito: a lista que chega da tela pode estar
    velha (outra aba, outro aparelho), e tratá-la como verdade absoluta
    apagaria um favorito criado no celular há um minuto.
    """
    esq = _esq(esquema)
    atuais = set(listar(usuario_id, None, esq))
    ordenadas = [t for t in telas if t in atuais]
    # o que a tela não mandou fica no fim, na ordem que já tinha — some da
    # ordenação, não da lista
    resto = [t for t in listar(usuario_id, None, esq) if t not in ordenadas]
    for i, tela in enumerate(ordenadas + resto):
        pglocal.executar(
            "UPDATE usuario_favoritos SET ordem = %s "
            "WHERE usuario_id = %s AND tela = %s", (i, usuario_id, tela),
            esquema=esq)
    return listar(usuario_id, telas_permitidas, esq)
