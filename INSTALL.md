# DeskAgent

KI-gestützter Desktop-Assistent mit MCP-Tool-Integration.

**Dokumentation:** https://doc.deskagent.de

## Features

- **WebUI** - Browser-Interface mit Tiles für Skills, Agents und Chats
- **Multi-Backend AI** - Claude, Gemini, Ollama (lokal)
- **E-Mail-Integration** - Outlook-Anbindung für E-Mail-Workflows
- **Billomat-Integration** - Kunden, Angebote, Rechnungen
- **Skills** - Schnelle Textverarbeitung per Hotkey
- **Agents** - Komplexe mehrstufige Workflows
- **Anonymisierung** - DSGVO-konforme PII-Anonymisierung

## Installation

1. **AIAssistant-Setup.exe** ausführen
2. Installationsordner wählen
3. GitHub-Repository wird automatisch geklont
4. `config/apis.json` mit deinen API-Keys bearbeiten (siehe Konfiguration)
5. `deskagent\start.bat` ausführen

## Voraussetzungen

- Windows 10/11 (64-bit)
- Microsoft Outlook (für E-Mail-Features)
- API-Keys: Billomat, optional Gemini

## Starten

Doppelklick auf `deskagent\start.bat`.

Die WebUI öffnet sich automatisch unter http://localhost:8765/

## Konfiguration

Die Konfiguration ist in mehrere Dateien aufgeteilt:

```
deskagent/config/          # Defaults (mit Produkt ausgeliefert)
├── system.json            # UI, Logging, Allgemeine Settings
├── backends.json          # AI Backend-Definitionen
├── apis.json              # API-Key-Templates (leer)
└── agents.json            # Demo-Agents und Basis-Skills

config/                    # User-Overrides (deine Anpassungen)
├── system.json            # Deine Settings (context, theme, etc.)
├── backends.json          # Backend-Anpassungen
├── apis.json              # Deine API-Keys (*)
└── agents.json            # Deine Agents und Skills
```

(*) `config/apis.json` enthält sensible Daten und wird nicht committet.

### API-Keys einrichten

Erstelle `config/apis.json`:

```json
{
  "billomat": {
    "id": "meine-firma",
    "api_key": "DEIN_BILLOMAT_KEY",
    "app_id": "...",
    "app_secret": "..."
  },
  "userecho": {
    "subdomain": "mein-helpdesk",
    "api_key": "DEIN_USERECHO_KEY"
  },
  "ai_backends": {
    "gemini": {
      "api_key": "DEIN_GEMINI_KEY"
    },
    "claude_api": {
      "api_key": "DEIN_CLAUDE_KEY"
    }
  }
}
```

### Allgemeine Settings anpassen

Erstelle `config/system.json`:

```json
{
  "context": "Meine Firma GmbH",
  "content_mode": "custom",
  "ui": {
    "theme": "dark",
    "use_webview": true
  }
}
```

### Content Mode

Der `content_mode` steuert welche Agents/Skills angezeigt werden:

| Mode | Beschreibung |
|------|--------------|
| `custom` | Nur User-Inhalte (Standard). Falls leer, Fallback zu Demo. |
| `demo` | Nur Demo-Inhalte aus `deskagent/agents/`, `deskagent/skills/` |
| `both` | User + Demo kombiniert. User hat Priorität bei Namenskonflikten. |

**Namenskonflikte bei `both`:**

Wenn ein User-Agent denselben Namen wie ein Demo-Agent hat:
- Nur die **User-Version** wird angezeigt
- In der UI erscheint ein Badge `[überschreibt Demo]`
- Die Demo-Version bleibt im Hintergrund verfügbar

Beispiel:
```
agents/reply_email.md       ← User-Version wird verwendet
deskagent/agents/reply_email.md  ← Demo wird ausgeblendet
```

## Verschlüsselung (Enterprise)

Für Unternehmen können API-Keys verschlüsselt werden:

```batch
# 1. Admin generiert Company Key
python -m scripts.encryption --generate-key
# → DESK-xK9mP4qL7...

# 2. Admin verschlüsselt apis.json
python -m scripts.encryption --encrypt config/apis.json --key DESK-xK9mP...
# → config/apis.enc

# 3. Mitarbeiter setzt Key auf seinem Rechner (einmalig)
python -m scripts.encryption --set-key DESK-xK9mP...

# DeskAgent lädt automatisch apis.enc statt apis.json
```

**Vorteile:**
- API-Keys nicht im Klartext sichtbar
- Alle Rechner nutzen denselben verschlüsselten File
- Key wird im Windows Credential Manager gespeichert

## Anpassen

| Ordner | Inhalt |
|--------|--------|
| `agents/` | Deine Agent-Definitionen (mehrstufige Workflows) |
| `skills/` | Deine Skill-Definitionen (Hotkey-Aktionen) |
| `knowledge/` | Deine Wissensbasis (Firma, Produkte, FAQ) |
| `mcp/` | Custom MCP-Server (optional) |

Passe die Dateien in diesen Ordnern an dein Unternehmen an.

## Netzwerk-Share (Enterprise)

Für Teams können die Inhalte auf einem Netzwerk-Share liegen:

```
Lokal (C:\DeskAgent\)               Netzwerk (\\server\share\team\)
├── deskagent/                       ├── config/        ← Geteilte Config
│   ├── scripts/                     ├── agents/        ← Team-Agents
│   └── mcp/                         ├── skills/        ← Team-Skills
├── shared_path.txt ──────────────►  ├── knowledge/     ← Team-Wissen
├── data/          (lokal)           └── mcp/           ← Custom MCPs
└── logs/          (lokal)
```

**Einrichtung:**

1. Erstelle `shared_path.txt` (neben deskagent/, nicht darin!):
   ```
   # Pfad zum Team-Ordner
   \\server\share\team\aiassistant
   ```

2. Oder setze Umgebungsvariable:
   ```batch
   set DESKAGENT_SHARED_DIR=\\server\share\team\aiassistant
   ```

**Lokale Daten** (data/, logs/, .temp/) bleiben immer lokal.

## Updates

Führe `deskagent\update.bat` aus, um die neueste Version zu laden.

## Autostart

- `deskagent\autostart-install.bat` - In Windows-Autostart eintragen
- `deskagent\autostart-remove.bat` - Aus Autostart entfernen

## Support

Bei Problemen: ask@deskagent.de
