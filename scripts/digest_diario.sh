#!/usr/bin/env bash
# Digest diário do Cortex Sulista (LaunchAgent com.cortex.digest, 07:00).
# Com SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_PARA no .env → e-mail.
# Sem SMTP → notificação do macOS + arquivo em ~/cortex-digest.txt.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TXT="$(curl -s -m 300 http://127.0.0.1:8000/api/alertas/digest || true)"
if [ -z "$TXT" ]; then
  # API fora do ar: gera direto do módulo (usa o túnel)
  TXT="$(uv run python -c 'from api.alertas import digest_texto; print(digest_texto())' 2>/dev/null || echo 'CÓRTEX: não foi possível gerar o digest (API e túnel indisponíveis).')"
fi

echo "$TXT" > "$HOME/cortex-digest.txt"

# e-mail, se configurado no .env
if grep -q '^SMTP_HOST=' .env 2>/dev/null; then
  uv run python - <<'PY'
import os, smtplib, ssl
from email.mime.text import MIMEText
from pathlib import Path
for l in Path(".env").read_text().splitlines():
    if "=" in l and not l.strip().startswith("#"):
        k, _, v = l.partition("="); os.environ.setdefault(k.strip(), v.strip())
txt = Path.home().joinpath("cortex-digest.txt").read_text()
msg = MIMEText(txt, "plain", "utf-8")
msg["Subject"] = "Córtex Sulista — resumo diário"
msg["From"] = os.environ["SMTP_USER"]
msg["To"] = os.environ.get("SMTP_PARA", os.environ["SMTP_USER"])
with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
    s.starttls(context=ssl.create_default_context())
    s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
print("e-mail enviado")
PY
fi

# notificação do macOS com a 1ª linha crítica
RESUMO="$(echo "$TXT" | grep -m1 '\[CRÍTICO\]\|\[ATENÇÃO\]' || echo 'Sem pendências críticas hoje.')"
osascript -e "display notification \"${RESUMO//\"/}\" with title \"Córtex Sulista — resumo do dia\"" 2>/dev/null || true
