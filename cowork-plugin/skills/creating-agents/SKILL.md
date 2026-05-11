# Agent-Erstellung Guide

Vollständige Anleitung zur Erstellung von DeskAgent Agents - von einfachen bis zu komplexen Multi-Step Workflows.

> **Siehe auch:**
> - [doc-agent-frontmatter-reference.md](../deskagent/knowledge/doc-agent-frontmatter-reference.md) - Alle Frontmatter-Optionen
> - [doc-mcp-tools.md](../deskagent/knowledge/doc-mcp-tools.md) - Verfügbare MCP-Tools

---

## Grundstruktur

Agents sind Markdown-Dateien mit JSON-Frontmatter:

```markdown
---
{
  "category": "kommunikation",
  "description": "Kurzbeschreibung (1 Satz)",
  "icon": "reply",
  "ai": "gemini",
  "allowed_mcp": "outlook|clipboard"
}
---

# Agent: E-Mail beantworten

[Agent-Prompt hier...]
```

**Speicherort:** `agents/mein_agent.md` (User-Ordner)

---

## Frontmatter - Wichtigste Optionen

### Minimale Konfiguration

```json
{
  "category": "chat",
  "description": "Was der Agent tut"
}
```

### Typische Konfiguration

```json
{
  "category": "finance",
  "description": "Erstellt Rechnungen aus E-Mails",
  "icon": "receipt_long",
  "input": ":mail: E-Mail mit Anhang",
  "output": ":receipt: Billomat-Rechnung",

  "ai": "gemini",
  "allowed_mcp": "outlook|billomat|pdf",
  "knowledge": "company|products",

  "order": 50,
  "enabled": true
}
```

### Kategorien

| ID | Label | Typische Verwendung |
|----|-------|---------------------|
| `chat` | Chat | Allgemeine Assistenz |
| `kommunikation` | Kommunikation | E-Mail, Support |
| `finance` | Finanzen | Rechnungen, SEPA, DMS |
| `sales` | Vertrieb | Angebote, CRM |
| `system` | System | Wartung, Tests |

---

## Agent-Prompt Struktur

### Empfohlenes Pattern

```markdown
# Agent: [Klarer Titel]

[1-2 Sätze: Was der Agent tut und wann er verwendet wird]

## Ablauf

### Schritt 1: Daten abrufen
- Tool X aufrufen
- Ergebnis prüfen

### Schritt 2: Verarbeiten
[Anweisungen]

### Schritt 3: Ausgabe
[Was wird produziert]

## Wichtig

[Sicherheitsregeln, Edge Cases]
```

### Struktur-Varianten

**Für einfache Agents:**
```markdown
# Agent: PDF zusammenfassen

Lies die PDF und erstelle eine Zusammenfassung.

## Ablauf
1. PDF mit `fs_read_pdf()` laden
2. Wichtige Punkte extrahieren
3. Zusammenfassung ausgeben

✅ Zusammenfassung erstellt!
```

**Für komplexe Workflows:**
```markdown
# Agent: Rechnungen prüfen

## Kontext
[Domain-Wissen, Hintergrund]

## Input
{{INPUT.dateien}}

## Ablauf (STRENGE REIHENFOLGE!)

### Phase 1: Analyse
[Nur lesende Operationen]

### Phase 2: Bestätigung
CONFIRMATION_NEEDED: {...}

### Phase 3: Ausführung
[Schreibende Operationen nach User-OK]

## Fehlerbehandlung
[Was bei Problemen passieren soll]
```

---

## User-Dialoge (Rückfragen)

Für interaktive Agents, die User-Input benötigen.

### QUESTION_NEEDED - Auswahl

Zeigt Buttons zur Auswahl:

```markdown
QUESTION_NEEDED: {
  "question": "Für welchen Zeitraum soll ich exportieren?",
  "options": [
    {"value": "2025", "label": "Jahr 2025"},
    {"value": "Q4_2024", "label": "Q4 2024"},
    {"value": "dezember", "label": "Dezember 2024"}
  ],
  "allow_custom": true,
  "placeholder": "z.B. 01.10.2024 - 31.12.2024"
}
```

**Felder:**
| Feld | Beschreibung |
|------|--------------|
| `question` | Die angezeigte Frage |
| `options` | Array mit `value` (intern) und `label` (angezeigt) |
| `allow_custom` | User kann eigenen Text eingeben (optional) |
| `placeholder` | Hinweis für Custom-Input (optional) |

**Typische Anwendungen:**
- Ja/Nein-Fragen
- Zeitraum-Auswahl
- Modus-Auswahl (z.B. "Neu" vs. "Anhängen")

### CONFIRMATION_NEEDED - Daten bestätigen

Zeigt editierbares Formular:

```markdown
CONFIRMATION_NEEDED: {
  "question": "Sind die Kundendaten korrekt?",
  "data": {
    "firma": "Max Müller GmbH",
    "email": "info@mueller.de",
    "betrag": "1500"
  },
  "editable_fields": ["email", "betrag"],
  "on_cancel": "abort",
  "on_cancel_message": "Was soll geändert werden?"
}
```

**Felder:**
| Feld | Beschreibung |
|------|--------------|
| `question` | Überschrift |
| `data` | Anzuzeigende Felder |
| `editable_fields` | Welche Felder editierbar sind |
| `on_cancel` | `"abort"` oder `"continue"` |
| `on_cancel_message` | Frage bei Abbruch (optional) |

**Typische Anwendungen:**
- Kontaktdaten vor Anlage prüfen
- Rechnungsdaten bestätigen
- Klassifizierung vor Ausführung

### CONTINUATION_NEEDED - Batch-Fortsetzung

Für Agents die viele Elemente verarbeiten:

```markdown
CONTINUATION_NEEDED: {
  "message": "10 von 83 Dokumenten verarbeitet",
  "remaining": 73,
  "processed": 10
}
```

**Voraussetzung:** `"allow_continuation": true` im Frontmatter

**Verhalten:**
- System startet Agent automatisch erneut
- Max 20 Fortsetzungen (Sicherheit)
- Jeder Durchlauf wird in UI gestreamt

### Dialog-Workflow Pattern

```markdown
## Ablauf

### Schritt 1: Recherche
[Daten sammeln - nur lesende Tools]

### Schritt 2: Bestätigung anfordern

CONFIRMATION_NEEDED: {
  "question": "Stimmen diese Daten?",
  "data": { ... },
  "editable_fields": [...]
}

**STOP - Warte auf User-Antwort!**

### Schritt 3: Verarbeitung
[Erst NACH Bestätigung ausführen]

✅ Fertig!
```

**WICHTIG:** Nach Dialog-Markern IMMER warten! Keine Tool-Calls parallel!

---

## Pre-Inputs Dialog

Für Agents die vorab Dateien oder Parameter brauchen.

### Datei-Upload

```json
{
  "inputs": [
    {
      "name": "files",
      "type": "file",
      "label": "Dateien auswählen",
      "required": true,
      "multiple": true,
      "accept": ".pdf,.csv",
      "folders": true
    }
  ]
}
```

### Text-Eingabe

```json
{
  "inputs": [
    {
      "name": "beschreibung",
      "type": "text",
      "label": "Beschreibung",
      "placeholder": "Optional...",
      "multiline": true,
      "rows": 4
    }
  ]
}
```

### Select-Dropdown

```json
{
  "inputs": [
    {
      "name": "konto",
      "type": "select",
      "label": "Konto auswählen",
      "required": true,
      "options": [
        {"value": "privat", "label": "Privatkonto"},
        {"value": "firma", "label": "Firmenkonto"}
      ],
      "default": "firma"
    }
  ]
}
```

### Verwendung im Prompt

```markdown
## Ausgewählte Dateien
{{INPUT.files}}

## Konto
{{INPUT.konto}}

## Beschreibung
{{INPUT.beschreibung}}
```

---

## Platzhalter

### Datum

| Platzhalter | Beispiel | Format |
|-------------|----------|--------|
| `{{TODAY}}` | 12.01.2026 | DD.MM.YYYY |
| `{{DATE}}` | 12.01.2026 | Alias für TODAY |
| `{{YEAR}}` | 2026 | YYYY |
| `{{DATE_ISO}}` | 2026-01-12 | YYYY-MM-DD |

### Pfade

| Platzhalter | Beschreibung |
|-------------|--------------|
| `{{EXPORTS_DIR}}` | workspace/exports/ |
| `{{TEMP_DIR}}` | workspace/.temp/ |
| `{{LOGS_DIR}}` | workspace/.logs/ |
| `{{WORKSPACE_DIR}}` | workspace/ |
| `{{KNOWLEDGE_DIR}}` | Knowledge-Verzeichnis (mit Fallback) |
| `{{CUSTOM_KNOWLEDGE_DIR}}` | User Knowledge (immer `knowledge/`) |
| `{{AGENTS_DIR}}` | agents/ |
| `{{CONFIG_DIR}}` | config/ |
| `{{PROJECT_DIR}}` | Projekt-Root |
| `{{DESKAGENT_DIR}}` | deskagent/ |

> **Vollständige Referenz:** Siehe [doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md#pfad-platzhalter)

### Beispiel

```markdown
Speichere die Datei in `{{TEMP_DIR}}/export_{{DATE_ISO}}.pdf`
```

---

## Procedures (Wiederverwendbare Bausteine)

Für Code der in mehreren Agents verwendet wird.

### Procedure verwenden

```markdown
## Zahlungserkennung
{{PROCEDURE:detect_paid}}

## Upload-Workflow
{{PROCEDURE:paperless_upload}}
```

### Procedure erstellen

Datei: `agents/procedures/meine_procedure.md`

```markdown
### Meine Procedure

1. Schritt eins
2. Schritt zwei

Unterstützt alle Platzhalter: {{TODAY}}, {{TEMP_DIR}}
```

**Suchpfad:**
1. `agents/procedures/` (User - Priorität)
2. `deskagent/agents/procedures/` (System - Fallback)

### Verfügbare System-Procedures

| Procedure | Beschreibung |
|-----------|--------------|
| `detect_paid` | Erkennt bereits bezahlte Rechnungen (Kreditkarte, PayPal, Lastschrift) |
| `paperless_upload` | Standard-Workflow für Paperless-Upload |

---

## Tool-Aufrufe - Patterns

### Sofort aufrufen (einfache Agents)

```markdown
**WICHTIG:** Rufe die Tools SOFORT auf! Keine Pläne beschreiben!

1. Lies die E-Mail mit `outlook_get_selected_email()`
2. Analysiere den Inhalt
3. Erstelle den Entwurf
```

### Strenge Reihenfolge (komplexe Agents)

```markdown
## Ablauf (STRENGE REIHENFOLGE!)

### Schritt 1: Daten abrufen
Rufe PARALLEL auf:
- `outlook_get_recent_emails()`
- `outlook_get_calendar_events()`

### Schritt 2: WARTEN
**Warte bis BEIDE Ergebnisse da sind!**

### Schritt 3: Verarbeiten
ERST JETZT mit den ECHTEN Daten weiterarbeiten.
```

### Parallele Calls (Performance)

```markdown
Rufe **gleichzeitig** auf (sind unabhängig):
- `billomat_search_clients()`
- `clipboard_get()`
- `outlook_get_selected_email()`
```

### Sequenzielle Calls (Abhängigkeiten)

```markdown
1. Zuerst Kunde suchen:
   `billomat_search_clients("Müller")`

2. WARTEN auf Ergebnis

3. Dann mit client_id:
   `billomat_get_client(client_id)`
```

---

## Security - MCP/Tool Einschränkungen

### Layer 1: MCP-Server begrenzen

```json
"allowed_mcp": "outlook|billomat"
```

Nur diese MCP-Server werden geladen.

### Layer 2: Tool-Whitelist

```json
"allowed_tools": ["fs_read_file", "fs_list_directory"]
```

Nur diese spezifischen Tools erlauben.

### Layer 3: Tool-Blacklist

```json
"blocked_tools": ["fs_delete_file", "fs_write_file"]
```

Diese Tools explizit sperren.

### Phasen-Pattern für kritische Operationen

```markdown
## Phase 1: Analyse (NUR LESEN!)

**VERBOTEN:**
- Schreibende Operationen
- Löschen
- Verschieben

**ERLAUBT:**
- Alle lesenden Tools
- Planung erstellen

## >>> WARTE AUF USER-BESTÄTIGUNG <<<

## Phase 2: Ausführung

[Erst nach Bestätigung schreibende Operationen]
```

---

## Knowledge-Pattern

### Selektiv laden

```json
"knowledge": "company|products"
```

Nur `company.md` und `products.md` laden.

### Unterordner

```json
"knowledge": "linkedin"
```

Alle Dateien in `knowledge/linkedin/` laden.

### Alles außer...

```json
"knowledge": "^(?!linkedin)"
```

Alles laden AUSSER `linkedin/`.

### Nichts laden (Performance)

```json
"knowledge": ""
```

Keine Knowledge-Dateien laden.

### Externe Dateien

```json
"knowledge": "@deskagent/documentation/en/"
```

Dateien außerhalb von `knowledge/` laden.

---

## Agent-as-Tool

Macht einen Agent als strukturiertes MCP-Tool verfügbar.

```json
{
  "ai": "gemini",
  "tool": {
    "name": "classify_email",
    "description": "Klassifiziert eine E-Mail nach Typ",
    "parameters": {
      "email_content": {
        "type": "string",
        "description": "Der E-Mail-Inhalt",
        "required": true
      }
    },
    "returns": {
      "type": "object",
      "properties": {
        "category": {"type": "string"},
        "priority": {"type": "integer"}
      }
    }
  }
}
```

**Vorteile:**
- Strukturierte Parameter statt generischem `desk_run_agent()`
- Pflichtparameter werden validiert
- Ideal für Supervisor-Pattern (Claude orchestriert, Gemini verarbeitet)

---

## Abschlussmeldung - PFLICHT!

Jeder Agent MUSS mit einer Abschlussmeldung enden:

```markdown
✅ E-Mail-Entwurf erstellt!
✅ Angebot für Müller GmbH ist fertig.
✅ 3 Rechnungen exportiert und im Exports-Ordner bereit.
✅ Prüfung abgeschlossen! 15 OK, 2 fehlend.
```

**REGEL:** Ohne ✅ ist der Agent nicht fertig!

**KEINE Folgefrage!** Nicht fragen "Kann ich noch helfen?" - der User meldet sich.

---

## Fehlerbehandlung

### Standard-Pattern

```markdown
## Fehlerbehandlung

- **Kein Kunde gefunden:** Extrahierte Daten anzeigen und fragen
- **PDF nicht lesbar:** Hinweis dass Scan sein könnte
- **API-Fehler:** Fehlermeldung anzeigen und alternativen Weg vorschlagen
- **Mehrdeutige Daten:** Optionen auflisten und User wählen lassen
```

### Graceful Degradation

```markdown
Falls ein Service nicht antwortet:
1. Im Report vermerken
2. Mit verfügbaren Daten weitermachen
3. User am Ende informieren was gefehlt hat
```

---

## Häufige Fehler & Lösungen

| Problem | Fehler | Lösung |
|---------|--------|--------|
| User sieht nur Text | Dialog ohne Marker | QUESTION_NEEDED/CONFIRMATION_NEEDED verwenden |
| Tools parallel aufrufen | Daten noch nicht da | Strenge Reihenfolge: Abrufen → Warten → Verarbeiten |
| Direkt schreiben | Keine Bestätigung | Phase 1 (Analyse) → Confirm → Phase 2 (Ausführung) |
| Input nicht verwendet | {{INPUT.name}} fehlt | Alle Inputs im Prompt referenzieren |
| Kein Abschluss | User unsicher ob fertig | ✅ Abschlussmeldung PFLICHT |
| Security-Problem | Zu breite MCP-Erlaubnis | `allowed_mcp` so restriktiv wie möglich |

---

## Vollständiges Template

```markdown
---
{
  "category": "kommunikation",
  "description": "Beantwortet E-Mails professionell",
  "icon": "reply",
  "input": ":mail: E-Mail",
  "output": ":edit: Entwurf",

  "ai": "gemini",
  "allowed_mcp": "outlook|clipboard",
  "knowledge": "company|products",

  "order": 50,
  "enabled": true
}
---

# Agent: E-Mail beantworten

Du bist ein professioneller E-Mail-Assistent.

## Ablauf

### Schritt 1: E-Mail lesen
Rufe `outlook_get_selected_email()` auf.

### Schritt 2: Analysieren
- Absender und Anliegen identifizieren
- Tonfall erkennen (formal/informal)

### Schritt 3: Entwurf erstellen
- Professionelle Antwort formulieren
- In Zwischenablage kopieren

## Regeln

- Freundlich aber professionell
- Auf Deutsch antworten, außer Original ist Englisch
- Keine erfundenen Fakten

## Output

Kopiere den Entwurf mit `clipboard_set()`.

✅ E-Mail-Entwurf erstellt und in Zwischenablage kopiert!
```

---

## Checkliste für neue Agents

- [ ] Frontmatter mit category, description, icon
- [ ] AI-Backend gewählt (`ai`)
- [ ] MCP-Server eingeschränkt (`allowed_mcp`)
- [ ] Knowledge-Pattern gesetzt (falls nicht alles nötig)
- [ ] Klare Ablauf-Struktur
- [ ] User-Dialoge mit QUESTION/CONFIRMATION_NEEDED
- [ ] Fehlerbehandlung definiert
- [ ] ✅ Abschlussmeldung am Ende
- [ ] Getestet mit realen Daten
