#!/usr/bin/env bash
# Richtet Elaras Charakterbogen als Dienst auf dem Raspberry Pi ein.
# Aufruf (im Projektordner auf dem Pi):   bash deploy/install-pi.sh [PORT]
# Der Dienst startet danach automatisch bei jedem Hochfahren des Pi.
set -euo pipefail

PORT="${1:-8080}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
SERVICE=/etc/systemd/system/elara-sheet.service

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "Port muss eine Zahl zwischen 1024 und 65535 sein." >&2; exit 1
fi
if [ "$RUN_USER" = "root" ]; then
  echo "Bitte als normaler Benutzer ausfuehren (nicht mit sudo) -- das Skript fragt selbst nach sudo." >&2; exit 1
fi
command -v python3 >/dev/null || { echo "python3 fehlt (sudo apt install python3)." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' || { echo "Python 3.7 oder neuer wird benoetigt." >&2; exit 1; }
[ -f "$APP_DIR/server.py" ] || { echo "server.py nicht gefunden in $APP_DIR" >&2; exit 1; }

mkdir -p "$APP_DIR/data"

echo "Richte Dienst ein: Ordner $APP_DIR, Benutzer $RUN_USER, Port $PORT"
sudo tee "$SERVICE" >/dev/null <<UNIT
[Unit]
Description=Elara Granger Charakterbogen
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/env python3 "$APP_DIR/server.py" --host 0.0.0.0 --port $PORT --data-dir "$APP_DIR/data"
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now elara-sheet.service
sleep 1
sudo systemctl --no-pager --lines=0 status elara-sheet.service || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Fertig. Der Bogen ist im Netzwerk erreichbar unter:"
[ -n "$IP" ] && echo "  http://$IP:$PORT/"
echo "  http://$(hostname).local:$PORT/"
