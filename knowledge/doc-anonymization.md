# Anonymization System

DeskAgent includes a GDPR-compliant PII anonymization system that protects sensitive data when using external AI services.

!!! note "Optional dependency (Community / AGPL edition)"
    The anonymizer relies on Microsoft Presidio + spaCy (~500MB of language
    models) and is therefore an **optional** install:

    ```bash
    pip install "deskagent[anonymizer]"
    python -m spacy download de_core_news_lg
    python -m spacy download en_core_web_lg
    ```

    Without this extra installed, anonymization degrades gracefully and is
    effectively disabled (see `scripts/ai_agent/anonymizer.py`).

## Overview

When agents process emails, documents, or other content, personal identifiable information (PII) is automatically anonymized before being sent to AI providers like Gemini, Claude, or OpenAI. The AI receives placeholders instead of real data, and responses are de-anonymized before being shown to the user.

**Flow:**
```
User Content → Anonymize PII → AI Provider → De-anonymize → User sees result
```

## What Gets Anonymized

| Type | Example | Placeholder |
|------|---------|-------------|
| Person names | "Max Mustermann" | `<PERSON_1>` |
| Email addresses | "info@example.com" | `<EMAIL_1>` |
| Phone numbers | "+49 123 456789" | `<PHONE_1>` |
| Locations | "Munich, Germany" | `<LOCATION_1>` |
| Domains | "example.com" | `[DOMAIN-1]` |
| URLs | "https://example.com/page" | `[URL-1]` |

## Configuration

### Config Files

Anonymization uses a two-tier configuration:

| File | Purpose |
|------|---------|
| `deskagent/config/anonymizer.json` | System defaults (tools, AI providers) |
| `config/anonymizer.json` | Customer-specific (company, products) |

Both files are merged at runtime - customer config extends system defaults.

### anonymizer.json Structure

```json
{
  "whitelist": [
    "meinefirma.de",
    "DeskAgent",
    "Unity"
  ],
  "known_persons": [],
  "known_companies": ["Meine Firma GmbH"]
}
```

### Fields

| Field | Description |
|-------|-------------|
| `whitelist` | Terms that should NEVER be anonymized (domains, products, brands) |
| `known_persons` | Names to always detect as persons (supplements NER) |
| `known_companies` | Company names to always detect |

### System Settings (system.json)

```json
"anonymization": {
  "enabled": true,
  "log_anonymization": true
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | false | Master switch for anonymization (off by default in Community Edition) |
| `log_anonymization` | false | Log detected entities to system.log |

## Whitelist

The whitelist prevents false positives where product names, company names, or technical terms get incorrectly anonymized.

**Example Problem:**
- "meinefirma.de" detected as domain → `[DOMAIN-1]`
- AI doesn't know what product you're talking about

**Solution:** Add to whitelist → stays as "meinefirma.de"

### What to Whitelist

| Category | Examples |
|----------|----------|
| Own domains | `meinefirma.de`, `deskagent.app` |
| Product names | `DeskAgent`, `Unity`, `OPC UA` |
| Company names | `Meine Firma GmbH`, `Siemens` |
| Partner names | `Beckhoff`, `KUKA`, `ABB` |
| Tool names | `Billomat`, `Lexware`, `Paperless` |
| Technical terms | `Digital Twin`, `Virtual Commissioning` |

### System vs Customer Whitelist

**System whitelist** (`deskagent/config/anonymizer.json`):
- DeskAgent-related terms
- Integrated tool names (Billomat, Outlook, etc.)
- AI provider names (Claude, Gemini, etc.)
- Generic technical terms

**Customer whitelist** (`config/anonymizer.json`):
- Company domains and names
- Product names
- Partner and vendor names
- Industry-specific terms

## Agent Configuration

Agents can control anonymization via frontmatter:

```yaml
---
{
  "anonymize": true,
  "use_anonymization_proxy": true
}
---
```

| Option | Description |
|--------|-------------|
| `anonymize: true` | Enable PII anonymization for this agent |
| `use_anonymization_proxy: true` | Route MCP calls through anonymizing proxy |

When `anonymize: true` is set in the backend config, agents automatically use the anonymization proxy.

## How It Works

### Detection

PII detection uses Microsoft Presidio with spaCy NER models:
- `de_core_news_lg` for German
- `en_core_web_lg` for English

Additional pattern-based detection for:
- Email addresses (regex)
- Phone numbers (regex)
- URLs and domains (regex)
- German company patterns (GmbH, AG, etc.)

### False Positive Prevention

The system includes extensive false positive detection:

1. **Whitelist check** - Skip whitelisted terms
2. **Placeholder pattern** - Skip `DOMAIN-1`, `PERSON_2` etc.
3. **Technical terms** - Skip CamelCase folder names
4. **German words** - Skip common words misdetected as names
5. **Short matches** - Skip < 3 character matches
6. **Markdown artifacts** - Skip `**text**`, `text:` etc.

### Proxy Mode

When `use_anonymization_proxy: true`, MCP tool calls are routed through an anonymizing proxy:

1. Tool input is anonymized before calling the real MCP
2. Tool output is scanned for new PII
3. Responses are de-anonymized before returning to AI

This ensures PII protection even when tools return additional data.

## Troubleshooting

### Check What's Being Anonymized

Enable logging in `system.json`:
```json
"anonymization": {
  "log_anonymization": true
}
```

Check `workspace/.logs/system.log` for:
```
[Anonymizer] Anonymized 3 PII entities:
[Anonymizer]   <PERSON_1> <- 'John Smith'
[Anonymizer]   <EMAIL_1> <- 'john@example.com'
```

### Term Being Incorrectly Anonymized

Add to `config/anonymizer.json` whitelist:
```json
{
  "whitelist": [
    "YourProductName",
    "yourcompany.com"
  ]
}
```

### Term NOT Being Anonymized (Should Be)

Add to `known_persons` or `known_companies`:
```json
{
  "known_persons": ["Unusual Name"],
  "known_companies": ["Obscure Corp"]
}
```

### Placeholder Appearing in Output

If you see `<PERSON_1>` in the final output, de-anonymization failed. Check:
1. Mapping exists in context
2. No typo in placeholder (AI might have modified it)
3. Log shows de-anon mappings available

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Execution                       │
├─────────────────────────────────────────────────────────┤
│  User Prompt                                             │
│       ↓                                                  │
│  anonymize() ─── Presidio NER + Patterns                │
│       ↓                                                  │
│  Anonymized Prompt ─── <PERSON_1>, [DOMAIN-1]           │
│       ↓                                                  │
│  AI Provider (Gemini/Claude/OpenAI)                     │
│       ↓                                                  │
│  AI Response (with placeholders)                        │
│       ↓                                                  │
│  de_anonymize() ─── Replace placeholders                │
│       ↓                                                  │
│  Final Response (real names restored)                   │
└─────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `deskagent/scripts/ai_agent/anonymizer.py` | Main anonymization logic (degrades gracefully if presidio missing) |
| `deskagent/scripts/ai_agent/anonymizer_service.py` | Presidio subprocess |
| `deskagent/config/anonymizer.json` | System defaults |
| `config/anonymizer.json` | Customer overrides |
| `pyproject.toml` | `[anonymizer]` optional extra declaration |
