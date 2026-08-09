"""Regera o CHANGELOG.md a partir de docs/versoes.yaml.

Rodar sempre que mexer no YAML — test_changelog_esta_em_dia_com_o_yaml falha se
os dois divergirem, para o repositório nunca ficar dizendo uma coisa e o painel
outra.

    uv run python scripts/gerar_changelog.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import documentacao  # noqa: E402

alvo = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
alvo.write_text(documentacao.changelog_md(), encoding="utf-8")
print(f"CHANGELOG.md regerado ({len(documentacao.versoes())} versões)")
