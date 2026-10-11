#!/usr/bin/env bash
# Richtet Elaras Charakterbogen als Dienst auf dem Raspberry Pi ein.
# Aufruf (im Projektordner auf dem Pi):   bash deploy/install-pi.sh [PORT]
# Der Dienst startet danach automatisch bei jedem Hochfahren des Pi.
# Das Skript kann beliebig oft erneut ausgefuehrt werden (z. B. mit anderem Port).
set -euo pipefail

PORT="${1:-8080}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
NAME=elara-sheet
SERVICE=/etc/systemd/system/$NAME.service

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "Port muss eine Zahl zwischen 1024 und 65535 sein." >&2; exit 1
fi
if [ "$RUN_USER" = "root" ]; then
  echo "Bitte als normaler Benutzer ausfuehren (nicht mit sudo) -- das Skript fragt selbst nach sudo." >&2; exit 1
fi
command -v python3 >/dev/null || { echo "python3 fehlt (sudo apt install python3)." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' || { echo "Python 3.7 oder neuer wird benoetigt." >&2; exit 1; }
[ -f "$APP_DIR/server.py" ] || { echo "server.py nicht gefunden in $APP_DIR" >&2; exit 1; }
[ -f "$APP_DIR/elara_granger_character_sheet.html" ] || { echo "elara_granger_character_sheet.html nicht gefunden in $APP_DIR" >&2; exit 1; }

# Einen evtl. schon vorhandenen (oder in der Neustart-Schleife haengenden) Dienst anhalten,
# damit die Port-Pruefung nicht den eigenen Dienst als "belegt" meldet.
if systemctl list-unit-files "$NAME.service" >/dev/null 2>&1 && [ -f "$SERVICE" ]; then
  sudo systemctl stop "$NAME.service" 2>/dev/null || true
fi

# Ist der Port frei? Sonst gleich mit klarer Meldung abbrechen.
if ! python3 - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
then
  echo "Port $PORT ist auf diesem Pi bereits belegt:" >&2
  (sudo ss -ltnp 2>/dev/null | grep -E ":$PORT\s" >&2) || true
  echo "Bitte einen anderen Port waehlen, zum Beispiel:  bash deploy/install-pi.sh $((PORT + 10))" >&2
  exit 1
fi

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
Environment=PYTHONUNBUFFERED=1
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
sudo systemctl enable "$NAME.service" >/dev/null 2>&1
sudo systemctl restart "$NAME.service"

# Pruefen, ob der Bogen wirklich antwortet (bis zu 10 Sekunden warten).
OK=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if python3 - "$PORT" <<'PY' 2>/dev/null
import sys, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # lokal, ohne Proxy
with opener.open("http://127.0.0.1:%s/api/health" % sys.argv[1], timeout=2) as r:
    sys.exit(0 if r.status == 200 else 1)
PY
  then OK=1; break; fi
  sleep 1
done

if [ "$OK" != 1 ]; then
  echo >&2
  echo "FEHLER: Der Dienst ist nicht gestartet. Die letzten Meldungen:" >&2
  sudo journalctl -u "$NAME.service" -n 15 --no-pager >&2 || true
  exit 1
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Fertig, der Dienst laeuft. Der Bogen ist im Netzwerk erreichbar unter:"
[ -n "$IP" ] && echo "  http://$IP:$PORT/"
echo "  http://$(hostname).local:$PORT/"
