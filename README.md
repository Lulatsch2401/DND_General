# Elara Granger – Charakterbogen

Editierbarer D&D-Charakterbogen (Regeln von 2014) für Elara Granger, Waldelfen-Druidin im Kreis des Mondes.

Der Bogen läuft auf zwei Arten:

- **Auf dem Raspberry Pi (empfohlen):** `server.py` liefert den Bogen im Heimnetz aus und speichert den Stand zentral. Jedes Gerät im Netzwerk sieht denselben Stand, Änderungen werden automatisch gespeichert.
- **Als einzelne Datei:** `elara_granger_character_sheet.html` direkt im Browser öffnen. Gespeichert wird dann über „Stand herunterladen" und „Stand laden".

## Auf dem Raspberry Pi einrichten

Voraussetzung ist Raspberry Pi OS mit Python 3.7 oder neuer (ist vorinstalliert). Zusatzpakete sind nicht nötig.

1. Den Projektordner auf den Pi bringen, zum Beispiel mit `git clone https://github.com/Lulatsch2401/DND_General.git` oder per Kopieren.
2. Im Projektordner den Dienst einrichten:

   ```bash
   cd DND_General
   bash deploy/install-pi.sh
   ```

   Das Skript fragt einmal nach dem sudo-Passwort, legt den Dienst `elara-sheet` an und startet ihn. Ein anderer Port als 8080 geht mit `bash deploy/install-pi.sh 9000`.
3. Die Adresse öffnen, die das Skript am Ende ausgibt, zum Beispiel `http://raspberrypi.local:8080/`.

Der Dienst startet bei jedem Hochfahren des Pi von selbst.

## Erst ausprobieren, ohne Dienst

```bash
python3 server.py
```

Das funktioniert genauso auf dem Mac. Beenden mit Strg+C.

## Aktualisieren

Neue Version des Bogens auf den Pi holen (zum Beispiel `git pull`) und die Seite im Browser neu laden. Die Bogen-Datei wird bei jedem Seitenaufruf frisch gelesen. Nur wenn sich `server.py` geändert hat, den Dienst neu starten:

```bash
sudo systemctl restart elara-sheet
```

Der gespeicherte Stand bleibt dabei erhalten. Neue Felder des Bogens erscheinen mit ihren Vorgabewerten; bereits gespeicherte Felder behalten den gespeicherten Wert.

## Wo der Stand liegt

| Was | Ort |
|---|---|
| Aktueller Stand | `data/state.json` |
| Tägliche Sicherungen (die letzten 14 Tage mit Änderungen) | `data/backups/` |

Der Ordner `data/` wird von Git ignoriert. Um einen alten Stand zurückzuholen: Dienst stoppen, die gewünschte Datei aus `data/backups/` nach `data/state.json` kopieren, Dienst starten. Zusätzlich lässt sich der Stand im Bogen über „Sicherung herunterladen" als Datei sichern und über „Stand importieren" wieder einspielen.

## Gleichzeitiges Bearbeiten

Jedes offene Gerät gleicht sich alle zwei Sekunden mit dem Server ab. Ändern zwei Geräte gleichzeitig verschiedene Felder, bleiben beide Änderungen erhalten. Beim selben Feld gewinnt die spätere Eingabe. Ist der Pi kurz nicht erreichbar, bleibt die Eingabe im Browser stehen und wird nachgereicht.

## Sicherheit

Der Server hat keine Anmeldung: Wer im selben Netzwerk ist, kann den Bogen lesen und ändern. Er ist für das private Heimnetz gedacht. Bitte keine Portfreigabe ins Internet einrichten.

## Nützliche Befehle

```bash
sudo systemctl status elara-sheet     # läuft der Dienst?
journalctl -u elara-sheet -f          # Protokoll mitlesen
sudo systemctl stop elara-sheet       # anhalten
sudo systemctl disable --now elara-sheet   # dauerhaft abschalten
```
