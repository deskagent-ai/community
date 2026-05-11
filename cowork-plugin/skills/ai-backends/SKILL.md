# AI Backend Reference

Vollständige Referenz aller verfügbaren AI-Backends in DeskAgent.

## Übersicht

DeskAgent unterstützt mehrere AI-Backends mit unterschiedlichen Stärken und Preisen.

| Backend | Model | Typ | Preis/1M Tokens | Use Case |
|---------|-------|-----|-----------------|----------|
| **claude_sdk** | Claude 3.5 Sonnet v2 | Agent SDK + MCP | $3/$15 | **Empfohlen** - Beste MCP-Integration |
| **gemini** | Gemini 2.5 Pro | API | $1.25/$10 | Günstige Alternative mit guter Qualität |
| **gemini_flash** | Gemini 2.5 Flash | API | $0.30/$2.50 | Schnell und sehr günstig |
| **gemini_3** | Gemini 3.1 Pro Preview | API | $2/$12 | **Neu** - Besseres Tool-Handling, Structured Outputs |
| **gemini_3_flash** | Gemini 3.1 Flash Preview | API | $0.50/$3 | **Neu** - Schnelles Gemini 3 Modell |
| **openai** | GPT-4o | API | $2.50/$10 | OpenAI Standard-Modell |
| **mistral** | Mistral Large | API | $2/$6 | Europäischer Anbieter |
| **qwen** | Qwen | Ollama (lokal) | kostenlos | Offline, keine API-Kosten |
| **claude** | Claude 3.5 Sonnet | CLI | $3/$15 | Legacy, nutzt CLI statt SDK |

---

## Backend Details

### Claude Agent SDK (`claude_sdk`)

**✅ Empfohlen für Produktiv-Einsatz**

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "api_key": "sk-ant-api03-...",
    "admin_api_key": "sk-ant-admin01-...",
    "permission_mode": "bypassPermissions",
    "anonymize": true
  }
}
```

**Vorteile:**
- Beste MCP-Tool-Integration (native Unterstützung)
- Zuverlässige Multi-Step Tool Calling
- Session-Management und Context-Caching
- Prompt Caching spart Kosten bei wiederholten Prompts

**Nachteile:**
- Teurer als Gemini ($3/$15 vs $1.25/$10)
- Nur Anthropic-Modelle verfügbar

**Permission Modes:**
- `"default"` - Frage vor jedem Tool-Call (für UI-basierte Workflows)
- `"acceptEdits"` - Auto-Approve nur für File-Edits
- `"bypassPermissions"` - **Auto-Approve alles** (für unattended Agents)

**SDK Mode (Extended Features):**
- `"extended"` (default) - Erweiterte Features:
  - **Sessions:** Session-ID für Resume-Capability
  - **AskUserQuestion:** Native SDK-Dialoge
  - **Structured Outputs:** JSON-Schema-validierte Responses
- `"legacy"` - Altes Verhalten ohne neue Features

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "api_key": "...",
    "sdk_mode": "legacy"  // nur wenn altes Verhalten gewünscht
  }
}
```

**Wann verwenden:**
- Kritische Business-Prozesse (E-Mail, Rechnungen, SEPA)
- Agents mit vielen MCP-Tools
- Wenn Zuverlässigkeit wichtiger ist als Kosten

---

### Gemini 2.5 Pro (`gemini`)

**✅ Beste Preis/Leistung für die meisten Use Cases**

```json
{
  "gemini": {
    "type": "gemini_adk",
    "api_key": "AIza...",
    "model": "gemini-2.5-pro",
    "anonymize": true,
    "pricing": { "input": 1.25, "output": 10 }
  }
}
```

**Vorteile:**
- **60% günstiger** als Claude ($1.25/$10)
- Gute MCP-Tool-Unterstützung (via `tool_bridge`)
- Multimodal (Text, Bilder, PDFs)
- Thinking Mode für komplexes Reasoning

**Nachteile:**
- Manchmal instabile Tool Calls bei sehr komplexen Workflows
- Höheres Risiko für "Malformed Function Call" Fehler

**Wann verwenden:**
- E-Mail-Antworten (`reply_email_gemini`)
- Dokumenten-Analyse
- Kostenoptimierte Workflows
- Hohe Volumes (z.B. Daily Check mit vielen E-Mails)

---

### Gemini 2.5 Flash (`gemini_flash`)

**✅ Schnellste und günstigste Option**

```json
{
  "gemini_flash": {
    "type": "gemini_adk",
    "api_key": "AIza...",
    "model": "gemini-2.5-flash",
    "anonymize": true,
    "pricing": { "input": 0.30, "output": 2.50 }
  }
}
```

**Vorteile:**
- **90% günstiger** als Claude ($0.30/$2.50)
- Sehr schnell (< 1s Latenz)
- Gut für einfache Tasks

**Nachteile:**
- Schwächer bei komplexem Reasoning
- Weniger zuverlässig bei Multi-Tool Workflows

**Wann verwenden:**
- Newsletter-Klassifizierung
- Einfache E-Mail-Kategorisierung
- Dokumenten-Tagging
- Test-Workflows

---

### Gemini 3 Pro (`gemini_3`) 🆕

**✅ Neu - Verbesserte Tool-Integration**

```json
{
  "gemini_3": {
    "type": "gemini_adk",
    "api_key": "AIza...",
    "model": "gemini-3.1-pro-preview",
    "anonymize": true,
    "pricing": { "input": 2.00, "output": 12.00 }
  }
}
```

**Neue Features (Gemini 3 vs 2.5):**
- **Structured Outputs with Tools** - Kombiniert Function Calling mit JSON Schema
- **Bessere Tool-Reasoning** - Weniger malformed function calls
- **Multi-Step Agentic Capabilities** - Komplexere Workflows
- **Thought Signatures** - Gemini 3 erfordert `thought_signature` in function_call Parts beim Continuation-Call. DeskAgent speichert originale Part-Objekte, um diese automatisch mitzunehmen.

**Vorteile:**
- Zuverlässigeres Tool-Handling als Gemini 2.5
- Structured Outputs ideal für Dialoge (QUESTION_NEEDED, CONFIRMATION_NEEDED)
- Immer noch günstiger als Claude ($2/$12 vs $3/$15)

**Nachteile:**
- **Preview-Status** - Kann sich noch ändern
- 60% teurer als Gemini 2.5 ($2 vs $1.25 Input)

**Wann verwenden:**
- Agents mit komplexen MCP-Workflows (z.B. `ask_sap`, `create_invoice_from_email`)
- Wenn Gemini 2.5 zu viele Tool-Fehler produziert
- Strukturierte Outputs (Formulare, Validierung)

**Migration von Gemini 2.5:**
```markdown
<!-- In Agent Frontmatter -->
---
{
  "ai": "gemini_3",  # ← Einfach Backend ändern
  "allowed_mcp": "billomat|outlook"
}
---
```

---

### Gemini 3 Flash (`gemini_3_flash`) 🆕

**✅ Schnelles Gemini 3 Modell**

```json
{
  "gemini_3_flash": {
    "type": "gemini_adk",
    "api_key": "AIza...",
    "model": "gemini-3.1-flash-preview",
    "anonymize": true,
    "pricing": { "input": 0.50, "output": 3.00 }
  }
}
```

**Wann verwenden:**
- Wenn Gemini 2.5 Flash zu schwach ist
- Schnelle Structured Outputs benötigt werden
- Kostenoptimierung wichtig ist

---

### OpenAI (`openai`)

```json
{
  "openai": {
    "type": "openai_api",
    "api_key": "sk-...",
    "model": "gpt-4o",
    "anonymize": true
  }
}
```

**Wann verwenden:**
- Wenn spezifische OpenAI-Features benötigt werden
- Benchmark-Vergleiche

**Hinweis:** Gemini 2.5 und Claude SDK bieten bessere Preis/Leistung für die meisten DeskAgent Use Cases.

---

### Mistral (`mistral`)

```json
{
  "mistral": {
    "type": "openai_api",
    "base_url": "https://api.mistral.ai/v1",
    "api_key": "...",
    "model": "mistral-large-latest",
    "anonymize": true,
    "pricing": { "input": 2, "output": 6 }
  }
}
```

**Wann verwenden:**
- DSGVO-Compliance wichtig (EU-Anbieter)
- Günstiger als Claude, stärker als Gemini bei manchen Tasks

---

### Qwen (`qwen`)

**✅ Komplett Offline**

```json
{
  "qwen": {
    "type": "qwen_agent",
    "model": "qwen2.5:32b",
    "base_url": "http://localhost:11434"
  }
}
```

**Vorteile:**
- Komplett kostenlos
- Offline-Betrieb (keine Internet-Verbindung nötig)
- Datenschutz (nichts verlässt den PC)

**Nachteile:**
- Schwächer als Cloud-Modelle
- Benötigt starke GPU (32B Modell ~ 20GB VRAM)
- Langsamer als API-Modelle

**Wann verwenden:**
- Entwicklung/Testing ohne API-Kosten
- Hohe Datenschutz-Anforderungen
- Kein Internet verfügbar

---

## Kostenvergleich

**Beispiel: E-Mail beantworten (3K Input + 500 Output Tokens)**

| Backend | Input Cost | Output Cost | Total | Relativ |
|---------|-----------|-------------|-------|---------|
| **gemini_flash** | $0.0009 | $0.00125 | **$0.00215** | 1x |
| **gemini** | $0.00375 | $0.005 | **$0.00875** | 4x |
| **gemini_3_flash** | $0.0015 | $0.0015 | **$0.003** | 1.4x |
| **gemini_3** | $0.006 | $0.006 | **$0.012** | 5.6x |
| **claude_sdk** | $0.009 | $0.0075 | **$0.0165** | 7.7x |

**Bei 1000 E-Mails/Monat:**
- **Gemini Flash**: $2.15
- **Gemini 2.5 Pro**: $8.75
- **Gemini 3 Flash**: $3.00
- **Gemini 3 Pro**: $12.00
- **Claude SDK**: $16.50

---

## Backend-Auswahl Matrix

| Use Case | Empfehlung | Alternative |
|----------|-----------|-------------|
| **E-Mail beantworten** | `gemini` | `gemini_flash` (günstiger) |
| **Rechnungen erstellen** | `claude_sdk` | `gemini_3` (günstiger) |
| **SEPA-Überweisungen** | `claude_sdk` | - (kritisch!) |
| **Support-Tickets** | `gemini` | `gemini_3` |
| **Newsletter filtern** | `gemini_flash` | `gemini_3_flash` |
| **Komplexe SAP-Abfragen** | `gemini_3` | `claude_sdk` |
| **Dokumenten-Analyse** | `gemini` | `gemini_3` |
| **Daily Check (100+ Mails)** | `gemini_flash` | `gemini` |
| **Development/Testing** | `qwen` | `gemini_flash` |

---

## Global AI Override

In Settings > Preferences kann ein globaler Override gesetzt werden, der alle Agents zwingt, ein bestimmtes Backend zu nutzen. Nützlich wenn ein AI-Service nicht verfügbar ist oder man Kosten kontrollieren will.

**Resolution-Priorität:**
1. Per-Call Override (API `body.backend`) - höchste
2. **Global AI Override** (`system.json` > `global_ai_override`) - NEU
3. Agent-Frontmatter (`ai: "gemini"`)
4. `default_ai` aus backends.json
5. Erster verfügbarer Backend - Fallback

**Setzen:** Settings > Preferences > KI-Modell Dropdown
**API:** `POST /config/backend_override` mit `{"backend": "gemini"}` oder `{"backend": "auto"}`

---

## Konfigurationsoptionen

### Gemeinsame Optionen (alle Backends)

```json
{
  "backend_name": {
    "type": "...",
    "api_key": "...",
    "anonymize": true,           // Aktiviere Anonymisierung
    "timeout": 300,              // API Timeout in Sekunden
    "max_tokens": 8192,          // Max Output Tokens
    "temperature": 0.7,          // Kreativität (0.0 - 1.0)
    "max_iterations": 30,        // Max Tool-Call Loops
    "pricing": {
      "input": 2.0,              // $/1M Input Tokens
      "output": 12.0             // $/1M Output Tokens
    }
  }
}
```

### Gemini-spezifische Optionen

```json
{
  "gemini": {
    "type": "gemini_adk",
    "model": "gemini-2.5-pro",     // Oder gemini-3.1-pro-preview
    "thinking_budget": 8192,       // Thinking Tokens (auto für 2.5+/3.0)
    "max_iterations": 30           // Wichtig für Tool-Heavy Agents
  }
}
```

**Thinking Budget:**
- `0` - Kein Thinking (nur Gemini 2.0/1.5)
- `8192` - **Auto-Default für Gemini 2.5+/3.0** (required!)
- Höher - Mehr internes Reasoning (teurer)

### Claude SDK-spezifische Optionen

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "permission_mode": "bypassPermissions",  // Wichtig für unattended!
    "admin_api_key": "sk-ant-admin01-...",  // Für erweiterte Features
    "use_anonymization_proxy": true,        // MCP-Tool Anonymization
    "mcp_transport": "sse"                  // MCP Transport Mode
  }
}
```

**MCP Transport Mode (`mcp_transport`):**

| Wert | Beschreibung | Anonymisierung | Stabilität |
|------|--------------|----------------|------------|
| `"inprocess"` | **In-Process SDK** (kein Netzwerk) | ✅ Ja | ⭐⭐⭐ Sehr stabil |
| `"streamable-http"` | HTTP Proxy | ✅ Ja | ⭐⭐ Stabil |
| `"sse"` | SSE Proxy (deprecated) | ✅ Ja | ⭐⭐ Stabil |
| `"stdio"` | Direkte subprocess (default) | ✅ Ja (wenn `anonymize: true`) | ⭐⭐ Stabil |

**✅ Empfohlen: `inprocess`**

Der `inprocess` Transport fuehrt MCP-Tools direkt im SDK-Prozess aus - ohne Netzwerk, ohne Proxy, ohne Subprozesse. Dies eliminiert alle "MCP proxy: failed" Fehler komplett.

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "mcp_transport": "inprocess",
    "anonymize": true
  }
}
```

**Vorteile von `inprocess`:**
- **Keine Netzwerkfehler** - Tools laufen direkt im gleichen Prozess
- **Schnellster Startup** - Kein HTTP-Server oder Subprocess-Start
- **Einfaches Debugging** - Ein Prozess statt mehrere
- **Vollstaendige Anonymisierung** - Gleiche PII-Protection wie andere Transports

**Wann andere Transports verwenden:**
- `"stdio"`: Zum Debugging oder wenn `inprocess` Probleme macht
- `"streamable-http"` / `"sse"`: Bei speziellen Proxy-Anforderungen

**Hinweis:** `inprocess` erfordert claude-agent-sdk >= 0.1.27. Falls nicht verfuegbar, Fallback auf `stdio`.

---

## Best Practices

### 1. Backend per Agent wählen

**Nicht:** Ein Backend global für alle Agents
**Sondern:** Backend pro Agent im Frontmatter

```markdown
---
{
  "ai": "gemini_flash",  # ← Günstiges Backend für Newsletter
  "allowed_mcp": "outlook"
}
---
# Agent: Cleanup Newsletters
```

### 2. Kosten-Monitoring

- Claude SDK/API loggen Token-Usage automatisch
- Gemini ADK zeigt Kosten im Log: `[Gemini] Cost: $0.0087`
- Prüfe `.logs/system.log` für Gesamt-Kosten

### 3. Fallback-Strategien

**Option A: Retry mit anderem Backend**
```markdown
<!-- Wenn gemini fehlschlägt, switch zu claude_sdk -->
"ai": "gemini",
"fallback_ai": "claude_sdk"  # ← Nicht implementiert, TODO
```

**Option B: Manuelle Escalation**
- Gemini Flash für erste Klassifizierung
- Bei Unsicherheit → Escalate zu Gemini 2.5/3
- Kritische Tasks direkt mit Claude SDK

### 4. Preview-Modelle in Produktion

**⚠️ Vorsicht bei `gemini-3.*-*-preview`:**
- Können sich ohne Vorwarnung ändern
- Pricing kann sich ändern (aktuell Preview-Pricing)
- Für Produktion: Warte auf GA-Release (stable model names)

### 5. Anonymisierung aktivieren

**Immer `"anonymize": true` setzen!**
```json
{
  "gemini": {
    "anonymize": true  // ← Entfernt PII vor API-Call
  }
}
```

Schützt vor:
- PII-Leaks (Namen, E-Mails, IBANs)
- Prompt Injection über E-Mail-Inhalte
- DSGVO-Verstöße

---

## Migration zwischen Backends

### Gemini 2.5 → Gemini 3

**Änderungen:**
1. Backend-Name im Frontmatter anpassen
2. **Fertig!** (Code ist kompatibel)

```diff
---
{
- "ai": "gemini",
+ "ai": "gemini_3",
  "allowed_mcp": "billomat|outlook"
}
---
```

**Was zu beachten:**
- Kosten steigen um 60% ($1.25 → $2 Input)
- Bessere Tool-Reliability
- Thinking Budget wird automatisch gesetzt

### Claude SDK → Gemini 3

**Änderungen:**
1. Backend-Name ändern
2. `permission_mode` entfällt (nicht relevant für API)
3. Evtl. `max_iterations` erhöhen (Gemini braucht manchmal mehr Loops)

```diff
---
{
- "ai": "claude_sdk",
+ "ai": "gemini_3",
+ "max_iterations": 50,
  "allowed_mcp": "billomat|outlook"
}
---
```

**Risiken:**
- Tool-Calls können unterschiedlich aufgerufen werden
- Testen vor Produktiv-Einsatz!

---

## Troubleshooting

### "Budget 0 is invalid" Error (Gemini)

**Ursache:** Gemini 2.5+ braucht Thinking Mode

**Fix:** Automatisch - Code setzt `thinking_budget=8192` für Gemini 2.5+/3.0

Wenn manuell gewünscht:
```json
{
  "gemini": {
    "thinking_budget": 8192  // Explizit setzen
  }
}
```

### "MALFORMED_FUNCTION_CALL" (Gemini)

**Ursache:** Model generiert invalide Tool-Argumente

**Fix:**
1. Retry-Logic (automatisch, bis zu 3x)
2. Text-only Fallback nach 3 Retries
3. Wenn häufig → Switch zu `gemini_3` oder `claude_sdk`

### Leere Responses nach Tool Calls

**Ursache:** Model "vergisst" zu antworten nach vielen Tool-Calls

**Fix:** Automatisch - Code fordert Summary an nach STOP

Wenn häufig:
- `max_iterations` reduzieren (z.B. 20 statt 30)
- Task in kleinere Agents aufteilen

### API Timeout

**Fix:**
```json
{
  "timeout": 600  // 10 Minuten statt 5
}
```

---

## Weitere Ressourcen

- **[doc-config-reference.md](doc-config-reference.md)** - Vollständige Config-Optionen
- **[doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md)** - Agent `ai` Field
- **[doc-anonymization.md](doc-anonymization.md)** - Anonymisierung Details
- **Gemini 3 Docs:** https://ai.google.dev/gemini-api/docs/gemini-3
- **Claude SDK Docs:** https://docs.anthropic.com/en/docs/agents
