# Football TikTok Telegram Bot V2

Diese Version erstellt aus einem längeren Video einen eigenständigeren Fußball-Edit.

## Funktionen

- Auswahl: 30 / 60 / 90 Sekunden / maximal
- mehrere Ausschnitte aus verschiedenen Stellen des Videos
- automatisches 9:16 TikTok-Format
- eigener Hook am Anfang
- schnelle Szenenwechsel
- leichter Zoom
- kurzer Slow-Motion-Part
- zusätzliche Texteinblendung
- Export als MP4/H.264

## Wichtiger Hinweis

Der Bot ist für kreative Bearbeitung gedacht. Er entfernt keine Wasserzeichen und versucht nicht,
TikToks Erkennungs- oder Moderationssysteme zu umgehen.

Auch ein stark bearbeiteter Clip kann von TikTok als nicht original eingestuft werden.
Außerdem brauchst du die erforderlichen Rechte am verwendeten Ausgangsmaterial.

## Einrichtung

### 1. Bot bei Telegram erstellen

Öffne **@BotFather** und sende:

```text
/newbot
```

BotFather gibt dir anschließend einen Token.

### 2. `.env` erstellen

Kopiere `.env.example` nach `.env` und ersetze den Platzhalter:

```env
BOT_TOKEN=123456789:DEIN_TOKEN
DEFAULT_HOOK=WHAT A MOMENT 🤯⚽
```

### 3. FFmpeg installieren

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

macOS:

```bash
brew install ffmpeg
```

Windows:
Installiere FFmpeg und füge es zum PATH hinzu.

### 4. Python-Pakete installieren

```bash
pip install -r requirements.txt
```

### 5. Starten

```bash
python bot.py
```

## Benutzung

1. Video an den Bot schicken.
2. Optional den Hook als Caption schreiben.
3. 30 / 60 / 90 Sekunden oder Maximal auswählen.
4. Fertigen Edit zurückbekommen.
