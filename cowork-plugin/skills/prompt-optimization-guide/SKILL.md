# Prompt-Optimierung für DeskAgent

Diese Anleitung zeigt, wie du Agent-Prompts analysieren und optimieren kannst.

## Prompt-Log analysieren

Bei jedem Agent-Aufruf wird der vollständige Prompt in `workspace/.logs/prompt_latest.txt` gespeichert.

**Beispiel-Header:**
```
================================================================================
PROMPT LOG
================================================================================

Timestamp:      2026-01-09 09:01:16
Agent:          claude_sdk
Model:          claude-sonnet-4
Context Limit:  200.0K tokens

----------------------------------------
TOKEN ESTIMATES
----------------------------------------
System Prompt:  11.5K tokens (40366 chars)
User Prompt:    313 tokens (1096 chars)
Total:          11.8K tokens (5.9% of limit)

----------------------------------------
AVAILABLE TOOLS (5)
----------------------------------------
  - db_add
  - db_contains
  - gmail_add_label
  - gmail_create_reply_draft
  - gmail_send_draft

----------------------------------------
TEMPLATES
----------------------------------------
Files:          1
Tokens:         1,400
  - dialogs: 1,400 tokens

TIP: Add 'skip_dialogs: true' in agent config to skip (~1,400 tokens)
```

**Hinweise:**
- Bei `claude_sdk` werden MCP-Server-Namen angezeigt (z.B. `MCP:proxy`, `MCP:outlook`), da die Tools dynamisch vom SDK geladen werden.
- Die TEMPLATES Sektion zeigt geladene Templates und gibt einen Optimierungs-Tipp wenn `dialogs.md` geladen ist.
- Bei Agents mit `skip_dialogs: true` zeigt die Sektion "Status: SKIPPED" und die gesparten Tokens.

## Token-Verteilung verstehen

| Bereich | Typischer Anteil | Quelle |
|---------|------------------|--------|
| Base Prompt | ~200 tokens | `DEFAULT_SYSTEM_PROMPT` in base.py |
| Datum-Kontext | ~100 tokens | Automatisch generiert |
| Security Warning | ~150 tokens | `input_sanitizer.py` |
| **Knowledge** | 30-80% | `knowledge/*.md` Dateien |
| Templates (Dialogs) | ~1,400 tokens | `templates/dialogs.md` (mit `skip_dialogs` überspringbar) |
| Arbeitsverzeichnisse | ~50 tokens | Automatisch generiert |
| Agent-Anweisungen | variabel | `instructions` in agents.json |

## Häufige Probleme

### 1. Knowledge-Überladung

**Problem:** Alle Knowledge-Dateien werden geladen, obwohl nur ein Teil relevant ist.

**Symptom:** System Prompt > 10K tokens, davon 70%+ Knowledge.

**Lösung:** `knowledge` Pattern in `agents.json` setzen:

```json
{
  "deskagent_support": {
    "ai": "gemini",
    "knowledge": "deskagent_faq|deskagent_pricing"
  }
}
```

**Pattern-Syntax:**

| Pattern | Ergebnis |
|---------|----------|
| `""` (leer) | Lädt NICHTS |
| `"company"` | Lädt nur `company.md` |
| `"company\|products"` | Lädt `company.md` und `products.md` |
| `null` / fehlt | Lädt ALLES |

### 2. Redundante Knowledge-Dateien

**Problem:** Mehrere Dateien enthalten dieselben Informationen.

**Beispiel:**
- `deskagent_faq.md` enthält Preise
- `deskagent_pricing.md` enthält auch Preise
- `demo_guide.md` fasst beides zusammen

**Lösung:**
- Dateien konsolidieren, oder
- Per Agent nur die relevanten laden

### 3. Irrelevante Templates

**Problem:** Dialog-Templates werden geladen obwohl der Agent keine Dialoge nutzt.

**Symptom:** ~1,400 tokens für QUESTION_NEEDED/CONFIRMATION_NEEDED obwohl `Auto-Send: True`.

**Lösung:** `skip_dialogs: true` im Agent-Frontmatter:

```markdown
---
{
  "ai": "gemini",
  "skip_dialogs": true
}
---
```

### 4. Fehlende Agent-Anweisungen

**Problem:** Der Prompt sagt "verwende Tools" aber nicht welche oder wie.

**Lösung:** `instructions` in `agents.json` oder im Agent-Markdown:

```json
{
  "email_support": {
    "ai": "gemini",
    "instructions": "Beantworte E-Mails freundlich. Nutze gmail_create_reply_draft() für Antworten."
  }
}
```

## Optimierungs-Checkliste

### Vor der Optimierung

1. Agent ausführen
2. `prompt_latest.txt` öffnen
3. Token-Verteilung analysieren

### Optimierungs-Schritte

- [ ] **Knowledge filtern** - Nur relevante Dateien laden
- [ ] **skip_dialogs** - Wenn keine User-Dialoge nötig
- [ ] **instructions** - Klare Anweisungen für den Agent
- [ ] **allowed_mcp** - Nur benötigte MCP-Server laden
- [ ] **allowed_tools** - Nur benötigte Tools freigeben

### Nach der Optimierung

1. Agent erneut ausführen
2. Token-Reduktion in `prompt_latest.txt` prüfen
3. Qualität der Antworten testen

## Beispiel: Vor/Nach Optimierung

### Vorher (11.5K tokens)

```json
{
  "deskagent_support": {
    "ai": "claude_sdk"
  }
}
```

- Lädt alle 9 Knowledge-Dateien (~9K tokens)
- Lädt Dialog-Templates (~600 tokens)
- Keine spezifischen Anweisungen

### Nachher (4.5K tokens, -60%)

```json
{
  "deskagent_support": {
    "ai": "gemini",
    "knowledge": "deskagent_faq|deskagent_pricing|deskagent_product",
    "skip_dialogs": true,
    "allowed_mcp": "gmail",
    "instructions": "Du beantwortest Anfragen an ask@deskagent.de. Antworte in der Sprache der Anfrage. Nutze gmail_create_reply_draft() für die Antwort. Verweise für Kauf auf deskagent.de."
  }
}
```

- Lädt nur 3 relevante Knowledge-Dateien (~3K tokens)
- Keine Dialog-Templates
- Klare Anweisungen
- Nur Gmail-Tools verfügbar

## Token-Spar-Tipps

| Maßnahme | Ersparnis |
|----------|-----------|
| Knowledge auf 2-3 Dateien reduzieren | 3-6K tokens |
| `skip_dialogs: true` | ~1,400 tokens |
| Kurze, präzise Instructions | besser als lange Knowledge |
| Redundanzen in Knowledge entfernen | 20-40% |

## Kosten-Auswirkung

Bei Gemini ($1.25/1M Input-Tokens):

| Prompt-Größe | Kosten pro Aufruf |
|--------------|-------------------|
| 15K tokens | $0.019 |
| 8K tokens | $0.010 |
| 4K tokens | $0.005 |

**50% weniger Tokens = 50% weniger Kosten** für den Input-Teil.

## Weiterführende Dokumentation

- [CLAUDE.md](../CLAUDE.md) - Vollständige Konfigurationsreferenz
- [docs/creating-agents.md](creating-agents.md) - Agent-Erstellung
- [docs/agent-as-tool-architecture.md](agent-as-tool-architecture.md) - Agent-Tools
