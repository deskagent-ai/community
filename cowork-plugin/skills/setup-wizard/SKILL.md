# Setup Wizard

Der Setup Wizard wird beim ersten Start von DeskAgent angezeigt und hilft bei der Konfiguration der AI-Backends.

## Wann wird der Wizard angezeigt?

Der Wizard erscheint automatisch wenn `config/backends.json` nicht existiert. Nach Abschluss wird diese Datei erstellt und der Wizard nicht mehr angezeigt.

## Konfigurationsschritte

### Schritt 1: Claude AI (Anthropic)

**Wenn Claude Code CLI installiert ist:**
- Der Wizard erkennt automatisch die Installation
- Zeigt "Claude Code gefunden - kein API Key noetig"
- Nutzt die Claude Subscription (guenstiger als API)

**Wenn Claude Code CLI nicht installiert ist:**
- Anthropic API Key eingeben (beginnt mit `sk-ant-`)
- Key erstellen unter: https://console.anthropic.com/settings/keys

Claude bietet die hoechste Qualitaet fuer komplexe Agents, Banking und anspruchsvolle Aufgaben.

### Schritt 2: Google Gemini

- Gemini API Key eingeben (beginnt mit `AIza`)
- Key erstellen unter: https://aistudio.google.com/apikey
- Gutes Preis-Leistungs-Verhaeltnis mit kostenlosem Kontingent

### Schritt 3: OpenAI

- OpenAI API Key eingeben (beginnt mit `sk-`)
- Key erstellen unter: https://platform.openai.com/api-keys
- Wird fuer Whisper Spracherkennung (Voice-to-Text) benoetigt
- Optional wenn Voice-Features nicht genutzt werden

### Schritt 4: Datenschutz (Privacy)

Dieser Schritt ermoeglicht die Installation von Sprachmodellen fuer die **Anonymisierung** sensibler Daten.

**Was wird installiert?**
- `de_core_news_lg` - Deutsches Sprachmodell (~500MB)
- `en_core_web_lg` - Englisches Sprachmodell (~500MB)

**Wozu dienen die Modelle?**
- Erkennung von personenbezogenen Daten (Namen, E-Mails, Adressen, Telefonnummern)
- Automatische Anonymisierung vor dem Senden an AI-Backends
- Funktioniert mit dem `anonymize: true` Flag in Agent-Konfigurationen

**Optionen:**
- **"Datenschutz-Modelle installieren"** - Laedt die Modelle herunter (~1GB, kann einige Minuten dauern)
- **"Ueberspringen"** - Anonymisierung bleibt deaktiviert, kann spaeter manuell installiert werden

**Manuelle Installation (falls uebersprungen):**
```bash
python -m spacy download de_core_news_lg
python -m spacy download en_core_web_lg
```

## Ueberspringen

Jeder Schritt kann uebersprungen werden. Die Konfiguration kann spaeter manuell in `config/backends.json` angepasst werden.

## Ergebnis

Nach Abschluss wird `config/backends.json` mit den konfigurierten Backends erstellt:

```json
{
  "default_ai": "claude_sdk",
  "ai_backends": {
    "claude_sdk": {
      "type": "claude_agent_sdk",
      "permission_mode": "bypassPermissions",
      "anonymize": true
    },
    "gemini": {
      "type": "gemini_adk",
      "api_key": "AIza...",
      "model": "gemini-2.5-pro",
      "anonymize": true
    },
    "openai": {
      "type": "openai_api",
      "api_key": "sk-...",
      "model": "gpt-4o",
      "anonymize": true
    }
  }
}
```

## Prioritaet

Die Backends werden in dieser Reihenfolge als `default_ai` gesetzt:
1. Claude SDK (wenn konfiguriert)
2. Gemini (wenn Claude nicht konfiguriert)

## Wizard erneut ausfuehren

Um den Wizard erneut anzuzeigen:
1. `config/backends.json` loeschen oder umbenennen
2. DeskAgent neu starten oder http://localhost:8765/ oeffnen

## Technische Details

| Komponente | Pfad |
|------------|------|
| Frontend | `deskagent/scripts/templates/setup.html` |
| Backend | `deskagent/scripts/assistant/routes/ui.py` |
| Ergebnis | `config/backends.json` |

### API Endpoints

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/setup` | GET | Wizard HTML anzeigen |
| `/api/setup/check-claude` | GET | Claude CLI Verfuegbarkeit pruefen |
| `/api/setup/check-spacy` | GET | spaCy Models Status pruefen |
| `/api/setup/install-spacy` | POST | spaCy Models herunterladen |
| `/api/setup` | POST | Konfiguration speichern |

### Wizard-Ablauf

```
Welcome (Lizenz) → Claude → Gemini → OpenAI → Datenschutz → Fertig
     Page 0         Page 1   Page 2   Page 3    Page 4      Page 5
```
