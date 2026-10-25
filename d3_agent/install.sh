#!/usr/bin/env bash
# Instala d3_agent en el Double 3 desde tu equipo (Mac o Ubuntu). Requiere el developer mode activo.
#
#   D3_SSH=double@<D3_IP> ./d3_agent/install.sh
#
# Genera un token nuevo, lo guarda en el robot (/etc/d3_agent/token, permisos 600) y en tu .env local.
# No instala paquetes con apt: el disco del D3 tiene ~1 GB libre y no se puede restaurar de fábrica.
set -euo pipefail

: "${D3_SSH:?Define D3_SSH=double@<D3_IP>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TOKEN="${D3_TOKEN:-}"
if [[ -z "$TOKEN" || "$TOKEN" == "changeme" ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
fi

echo ">> Verificando Python y herramientas en el robot"
ssh "$D3_SSH" 'python3 --version; command -v gst-launch-1.0 arecord aplay || true; df -h / | tail -1'

echo ">> Copiando d3_agent"
ssh "$D3_SSH" 'sudo mkdir -p /opt/d3_agent /etc/d3_agent && sudo chown -R "$USER" /opt/d3_agent'
scp -q "$HERE/d3_agent.py" "$D3_SSH:/opt/d3_agent/"
scp -q -r "$HERE/pages" "$D3_SSH:/opt/d3_agent/"
scp -q "$HERE/d3-agent.service" "$D3_SSH:/tmp/d3-agent.service"

echo ">> Guardando token y activando el servicio"
printf '%s' "$TOKEN" | ssh "$D3_SSH" 'sudo tee /etc/d3_agent/token >/dev/null && sudo chmod 600 /etc/d3_agent/token && sudo chown double /etc/d3_agent/token'
ssh "$D3_SSH" 'sudo mv /tmp/d3-agent.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now d3-agent && sleep 1 && systemctl --no-pager status d3-agent | head -5'

echo ">> Abriendo el puerto 22022 en el firewall (si ufw está activo)"
ssh "$D3_SSH" 'if sudo ufw status | grep -q "Status: active"; then sudo ufw allow 22022/tcp; fi' || true

ENV_FILE="$ROOT/.env"
touch "$ENV_FILE"
if grep -q '^D3_TOKEN=' "$ENV_FILE"; then
  sed -i.bak "s/^D3_TOKEN=.*/D3_TOKEN=$TOKEN/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
else
  echo "D3_TOKEN=$TOKEN" >> "$ENV_FILE"
fi
echo ">> Listo. Token guardado en $ENV_FILE (ignorado por git)."
