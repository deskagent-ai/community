# Agent: Translate Documentation

Translate DeskAgent documentation from English to German.

## Your Knowledge

The full English documentation is loaded in your knowledge context. Use it as reference.

## Translation Rules

1. **Keep in English:**
   - Code blocks and inline code
   - File paths and URLs
   - Technical terms: API, MCP, JSON, XML, PDF, SEPA, IBAN, OAuth, SDK, CLI
   - Product names: DeskAgent, Outlook, Billomat, Lexware, UserEcho, ecoDMS, Paperless, Claude, Gemini

2. **Translate naturally:**
   - Use formal German ("Sie" not "du")
   - Common translations:
     - Extension → Erweiterung
     - Guide → Anleitung
     - Quick Start → Schnellstart
     - Troubleshooting → Fehlerbehebung
     - Getting Started → Erste Schritte

3. **Preserve structure:**
   - Same heading hierarchy
   - Same link targets (relative paths unchanged!)
   - Same admonition types (!!! note, !!! tip, !!! warning)
   - Same table structure

## Process

### Step 1: Detect Changes

Use `fs_get_file_info()` to compare modification times:

```python
# For each file in en/
en_info = fs_get_file_info("deskagent/documentation/en/index.md")
de_info = fs_get_file_info("deskagent/documentation/de/index.md")

# Compare:
# - de_info is None → NEW (needs translation)
# - en_info.modified > de_info.modified → CHANGED (needs update)
# - en_info.modified <= de_info.modified → OK (skip)
```

### Step 2: Show Status

Display a status table:

```
📊 Dokumentations-Status:

| Datei | Status | EN geändert | DE geändert |
|-------|--------|-------------|-------------|
| index.md | ⚠️ CHANGED | 03.01.2026 | 01.01.2026 |
| overview.md | ✅ OK | 01.01.2026 | 02.01.2026 |
| quickstart.md | 🆕 NEW | 03.01.2026 | - |
| guides/billing.md | ✅ OK | 01.01.2026 | 01.01.2026 |

Zusammenfassung:
- 🆕 Neu zu übersetzen: 5 Dateien
- ⚠️ Aktualisierung nötig: 3 Dateien
- ✅ Aktuell: 12 Dateien
```

### Step 3: Ask User

```
Was möchten Sie tun?
1. Alle neuen und geänderten übersetzen (8 Dateien)
2. Nur neue übersetzen (5 Dateien)
3. Bestimmte Dateien auswählen
4. Abbrechen
```

### Step 4: Translate

For selected files:
1. Read EN content (from knowledge or filesystem)
2. Translate following rules
3. Write to DE with same relative path
4. Report progress

### Step 5: Final Report

```
✅ Übersetzung abgeschlossen!

| Datei | Status |
|-------|--------|
| index.md | ✓ Übersetzt |
| quickstart.md | ✓ Übersetzt |
| guides/billing.md | ✓ Aktualisiert |

- Neu übersetzt: 5 Dateien
- Aktualisiert: 3 Dateien
- Übersprungen: 12 Dateien
```

## Start

1. List all .md files in `deskagent/documentation/en/` recursively
2. For each file, check if DE version exists and compare dates
3. Show the status table
4. Ask what the user wants to translate
5. Execute translation for selected files
