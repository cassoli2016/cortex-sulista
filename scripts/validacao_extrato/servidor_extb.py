"""Sobe a app com auth e extrato ISOLADOS em SQLite temporário.

Nunca toca `data/auth.db` nem `data/extrato.db` do usuário — a validação da tela
precisa criar usuário e importar extrato, e fazer isso na base real seria
alterar o ambiente de quem está usando o painel.

Uso: uv run python servidor_extb.py <dir_tmp> <porta>
"""
from __future__ import annotations

import sys
from pathlib import Path

TMP = Path(sys.argv[1])
PORTA = int(sys.argv[2]) if len(sys.argv) > 2 else 8099
TMP.mkdir(parents=True, exist_ok=True)

# raiz do projeto = dois niveis acima de scripts/validacao_extrato/
RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# redireciona os bancos locais ANTES de importar a app
from api import auth
auth.DB_PATH = TMP / "auth_teste.db"
auth.init_db()

from api.extrato import armazenamento as arm
arm.DB_PATH = TMP / "extrato_teste.db"
arm.init_db(arm.DB_PATH)

# usuários de teste: um com a tela extb (perfil Financeiro), um sem (perfil Frota)
import sqlite3


SENHA = "Teste@12345"
# e-mail é o login neste schema (não "usuario")
USUARIOS = (("fin@teste.local", "Financeiro"), ("frota@teste.local", "Frota"))


def _cria_usuarios() -> None:
    with sqlite3.connect(auth.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        perfis = {r["nome"]: r["id"] for r in c.execute("SELECT id, nome FROM perfis")}
        print("perfis:", sorted(perfis), flush=True)
        for email, perfil in USUARIOS:
            pid = perfis.get(perfil)
            if pid is None:
                print(f"AVISO: perfil {perfil} inexistente", flush=True)
                continue
            # deve_trocar_senha=0 para o login não cair na tela de troca
            c.execute(
                "INSERT OR REPLACE INTO usuarios(nome, email, senha_hash, perfil_id, ativo,"
                " deve_trocar_senha, criado_em) VALUES(?,?,?,?,1,0,?)",
                (email.split("@")[0].upper(), email, auth._ph.hash(SENHA), pid, auth._agora()))
        c.commit()
        for r in c.execute("SELECT u.email, u.perfil_id, p.nome FROM usuarios u "
                           "JOIN perfis p ON p.id=u.perfil_id"):
            telas = {t[0] for t in c.execute(
                "SELECT tela FROM perfil_telas WHERE perfil_id=?", (r["perfil_id"],))}
            print(f"  {r['email']:22} perfil={r['nome']:14} "
                  f"extb={'SIM' if 'extb' in telas else 'NAO'}", flush=True)


_cria_usuarios()

from api.main import app  # noqa: E402
import uvicorn  # noqa: E402

print(f"servindo em http://127.0.0.1:{PORTA}  (auth={auth.DB_PATH.name}, extrato={arm.DB_PATH.name})",
      flush=True)
uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning")
