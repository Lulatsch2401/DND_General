#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kleiner Server fuer Elaras Charakterbogen (z. B. auf einem Raspberry Pi).

- liefert den Bogen (elara_granger_character_sheet.html) im Netzwerk aus
- speichert den Stand zentral in data/state.json, damit alle Geraete
  dasselbe sehen und jede Aenderung erhalten bleibt

Braucht nur die Python-Standardbibliothek (Python 3.7+), keine Zusatzpakete.

Start:   python3 server.py            (Port 8080, erreichbar im ganzen Netzwerk)
Optionen: python3 server.py --port 9000 --host 0.0.0.0 --data-dir /pfad/zu/daten

Der Server hat bewusst KEINE Anmeldung -- er ist fuer das private Heimnetz
gedacht und sollte nicht per Portfreigabe ins Internet gestellt werden.
"""
import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_FILE = os.path.join(BASE_DIR, "elara_granger_character_sheet.html")

MAX_BODY_BYTES = 2 * 1024 * 1024      # 2 MB reichen fuer den Bogen bei Weitem
MAX_FIELDS = 5000                      # Obergrenze fuer Felder im Stand
MAX_VALUE_CHARS = 200000               # Obergrenze je Textfeld
BACKUPS_TO_KEEP = 14                   # Tages-Sicherungen, die aufbewahrt werden


class StateStore(object):
    """Haelt den Stand im Speicher und schreibt ihn atomar auf die Platte."""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, "state.json")
        self.backup_dir = os.path.join(data_dir, "backups")
        self.lock = threading.Lock()
        self.version = 0
        self.saved_at = None
        self.state = None
        os.makedirs(self.backup_dir, exist_ok=True)
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            self.version = int(doc.get("version", 0))
            self.saved_at = doc.get("savedAt")
            self.state = doc.get("state")
        except (ValueError, OSError) as exc:
            # Kaputte Datei nicht ueberschreiben, sondern beiseitelegen.
            broken = self.path + ".defekt-%d" % int(time.time())
            try:
                shutil.copy2(self.path, broken)
            except OSError:
                pass
            sys.stderr.write("WARNUNG: %s nicht lesbar (%s); Kopie: %s\n" % (self.path, exc, broken))

    def snapshot(self):
        with self.lock:
            return {"version": self.version, "savedAt": self.saved_at, "state": self.state}

    def current_version(self):
        with self.lock:
            return self.version

    def save(self, base_version, state):
        """Speichert, wenn base_version noch aktuell ist.

        Rueckgabe: (True, snapshot) bei Erfolg, (False, snapshot) bei Konflikt
        (ein anderes Geraet hat inzwischen gespeichert).
        """
        with self.lock:
            if base_version != self.version:
                return False, {"version": self.version, "savedAt": self.saved_at, "state": self.state}
            self._backup_once_per_day()
            new_version = self.version + 1
            saved_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            doc = {"version": new_version, "savedAt": saved_at, "state": state}
            self._write_atomic(doc)
            self.version, self.saved_at, self.state = new_version, saved_at, state
            return True, {"version": new_version, "savedAt": saved_at}

    def _write_atomic(self, doc):
        fd, tmp = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _backup_once_per_day(self):
        """Legt vor der ersten Aenderung eines Tages eine Kopie des alten Stands ab."""
        if not os.path.exists(self.path):
            return
        target = os.path.join(self.backup_dir, "state-%s.json" % time.strftime("%Y-%m-%d"))
        if os.path.exists(target):
            return
        try:
            shutil.copy2(self.path, target)
            backups = sorted(f for f in os.listdir(self.backup_dir) if f.startswith("state-") and f.endswith(".json"))
            for old in backups[:-BACKUPS_TO_KEEP]:
                os.unlink(os.path.join(self.backup_dir, old))
        except OSError as exc:
            sys.stderr.write("WARNUNG: Sicherung fehlgeschlagen: %s\n" % exc)


def validate_state(state):
    """Der Stand ist ein flaches Objekt: Feldname -> Text oder Haekchen."""
    if not isinstance(state, dict):
        return "state muss ein Objekt sein"
    if len(state) > MAX_FIELDS:
        return "zu viele Felder"
    for key, value in state.items():
        if not isinstance(key, str) or len(key) > 200:
            return "ungueltiger Feldname"
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            if len(value) > MAX_VALUE_CHARS:
                return "Feld %s ist zu lang" % key
            continue
        return "Feld %s hat einen ungueltigen Typ" % key
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "ElaraSheet/1.0"
    protocol_version = "HTTP/1.1"
    store = None  # wird in main() gesetzt

    # ---------- Hilfen ----------
    def _send(self, status, body=b"", content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _reject(self, status, message):
        """Ablehnen, bevor der Anfragetext gelesen wurde -- Verbindung danach schliessen."""
        self.close_connection = True
        self._send(status, json.dumps({"error": message}, ensure_ascii=False).encode("utf-8"),
                   extra={"Connection": "close"})

    def _same_origin(self):
        """Schreibzugriffe nur von der eigenen Seite, nicht von fremden Webseiten."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlsplit(origin).netloc == host

    def log_message(self, fmt, *args):
        # Die Abfragen "hat sich etwas geaendert?" kommen alle paar Sekunden --
        # die sollen das Protokoll nicht fluten.
        if len(args) >= 2 and str(args[1]) in ("204", "304"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- Routen ----------
    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self._serve_sheet()
        if path == "/api/state":
            query = parse_qs(url.query)
            try:
                known = int(query.get("v", ["-1"])[0])
            except ValueError:
                known = -1
            if known == self.store.current_version():
                return self._send(204)
            return self._json(200, self.store.snapshot())
        if path == "/api/health":
            return self._json(200, {"ok": True, "version": self.store.current_version()})
        if path == "/favicon.ico":
            return self._send(204)
        return self._json(404, {"error": "nicht gefunden"})

    do_HEAD = do_GET

    def do_PUT(self):
        if urlsplit(self.path).path != "/api/state":
            return self._reject(404, "nicht gefunden")
        if not self._same_origin():
            return self._reject(403, "fremde Herkunft")
        if "application/json" not in (self.headers.get("Content-Type") or "").lower():
            return self._reject(415, "Content-Type muss application/json sein")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._reject(411, "Content-Length fehlt")
        if length < 0 or length > MAX_BODY_BYTES:
            return self._reject(413, "Anfrage zu gross")
        try:
            doc = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "kein gueltiges JSON"})
        if not isinstance(doc, dict):
            return self._json(400, {"error": "Objekt erwartet"})
        base_version = doc.get("baseVersion")
        if isinstance(base_version, bool) or not isinstance(base_version, int):
            return self._json(400, {"error": "baseVersion fehlt"})
        problem = validate_state(doc.get("state"))
        if problem:
            return self._json(400, {"error": problem})
        try:
            ok, result = self.store.save(base_version, doc["state"])
        except OSError as exc:
            sys.stderr.write("FEHLER beim Speichern: %s\n" % exc)
            return self._json(500, {"error": "Speichern fehlgeschlagen"})
        return self._json(200 if ok else 409, result)

    do_POST = do_PUT

    def _serve_sheet(self):
        # Bei jeder Anfrage frisch von der Platte lesen: eine geaenderte
        # Bogen-Datei ist nach einem Neuladen der Seite sofort sichtbar.
        try:
            with open(SHEET_FILE, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send(500, "Bogen-Datei fehlt: %s" % os.path.basename(SHEET_FILE), "text/plain; charset=utf-8")
        self._send(200, body, "text/html; charset=utf-8",
                   {"Referrer-Policy": "no-referrer", "X-Frame-Options": "SAMEORIGIN"})


def local_addresses():
    """Adressen, unter denen der Pi im Netzwerk erreichbar ist (ohne etwas zu senden)."""
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    return found


def main():
    parser = argparse.ArgumentParser(description="Server fuer Elaras Charakterbogen")
    parser.add_argument("--host", default=os.environ.get("ELARA_HOST", "0.0.0.0"),
                        help="Adresse, auf der gelauscht wird (Standard: 0.0.0.0 = ganzes Netzwerk)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ELARA_PORT", "8080")),
                        help="Port (Standard: 8080)")
    parser.add_argument("--data-dir", default=os.environ.get("ELARA_DATA_DIR", os.path.join(BASE_DIR, "data")),
                        help="Ordner fuer den gespeicherten Stand (Standard: ./data)")
    args = parser.parse_args()

    if not os.path.exists(SHEET_FILE):
        sys.exit("Bogen-Datei nicht gefunden: %s" % SHEET_FILE)

    Handler.store = StateStore(os.path.abspath(args.data_dir))
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    print("Elaras Charakterbogen laeuft.")
    print("  Stand:   %s (Version %d)" % (Handler.store.path, Handler.store.version))
    print("  Lokal:   http://localhost:%d/" % args.port)
    if args.host in ("0.0.0.0", ""):
        for addr in local_addresses():
            print("  Netzwerk: http://%s:%d/" % (addr, args.port))
        print("  oder:    http://%s.local:%d/" % (socket.gethostname(), args.port))
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
