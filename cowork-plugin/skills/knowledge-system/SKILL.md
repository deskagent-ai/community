# Knowledge System

Technische Dokumentation des Knowledge-Systems in DeskAgent.

## Übersicht

Das Knowledge-System lädt Markdown-Dateien aus dem `knowledge/` Ordner und fügt sie in den System-Prompt des AI-Backends ein. Agents können über Pattern definieren, welche Knowledge-Dateien geladen werden.

```
knowledge/
├── company.md              # Firmeninfos
├── products.md             # Produkte & Preise
├── mailstyle.md            # E-Mail-Schreibstil
└── linkedin/               # Unterordner
    ├── style.md
    └── examples.md
```

## Architektur

### System-Prompt-Aufbau

```
┌────────────────────────────────────┐
│ 1. Base System Prompt              │  ← aus config oder DEFAULT
├────────────────────────────────────┤
│ 2. Security Templates              │  ← Prompt Injection Schutz
├────────────────────────────────────┤
│ 3. System Templates                │  ← deskagent/templates/*.md
├────────────────────────────────────┤
│ 4. Knowledge / Wissensbasis        │  ← knowledge/**/*.md (gefiltert)
├────────────────────────────────────┤
│ 5. Agent Instructions              │  ← agents/*.md
└────────────────────────────────────┘
```

### Kernfunktion

**Datei:** `deskagent/scripts/ai_agent/base.py`

```python
def load_knowledge(pattern: str = None) -> str:
    """
    Lädt Knowledge-Dateien basierend auf Pattern.

    Args:
        pattern: Regex-Pattern, Pfad-Referenz, oder leer

    Returns:
        Konkatenierter Knowledge-Inhalt
    """
```

## Pattern-Syntax

### Regex-Patterns

Patterns werden als Regex auf den relativen Pfad (ohne `.md`) angewendet:

| Pattern | Match-String | Ergebnis |
|---------|--------------|----------|
| `company` | `company` | `knowledge/company.md` |
| `linkedin` | `linkedin/style`, `linkedin/examples` | Alle Dateien im Unterordner |
| `linkedin/style` | `linkedin/style` | Nur diese spezifische Datei |
| `company\|products` | OR-Match | Beide Dateien |
| `^(?!linkedin)` | Negativ-Lookahead | Alles außer linkedin/* |

### Spezielle Werte

| Pattern | Verhalten |
|---------|-----------|
| `None` (nicht gesetzt) | Lädt ALLE `knowledge/**/*.md` |
| `""` (leerer String) | Lädt NICHTS (explizit deaktiviert) |

### Pfad-Referenzen (@)

Mit `@` können externe Dateien/Ordner referenziert werden:

```
"@deskagent/docs/creating-agents.md"  # Einzelne Datei
"@deskagent/documentation/"           # Ordner (rekursiv)
"company|@external/docs/"             # Gemischt
```

**Auflösungs-Reihenfolge:**
1. Relativ zu `PROJECT_DIR` (Workspace)
2. Relativ zu `DESKAGENT_DIR.parent`
3. Relativ zu `DESKAGENT_DIR`

## Konfiguration

### In agents.json

```json
{
  "reply_email": {
    "ai": "claude_sdk",
    "knowledge": "company|products|mailstyle"
  },
  "linkedin": {
    "ai": "claude_sdk",
    "knowledge": "linkedin"
  },
  "technical_agent": {
    "ai": "claude_sdk",
    "knowledge": ""
  }
}
```

### Empfehlungen

| Agent-Typ | Empfohlenes Pattern |
|-----------|---------------------|
| E-Mail-Antworten | `company\|products\|mailstyle` |
| Rechnungen/Angebote | `company\|products` |
| Social Media | `linkedin` oder spezifischer Ordner |
| Technische Agents | `""` (kein Knowledge) |

## Caching

Knowledge wird mit 5-Minuten TTL gecacht:

```python
def load_knowledge_cached(pattern: str = None) -> str:
    """Gecachte Version von load_knowledge()"""

def invalidate_knowledge_cache():
    """Cache manuell invalidieren nach Änderungen"""
```

## Implementierungsdetails

### Pattern-Parsing

```python
# Pattern wird in Teile aufgesplittet
for part in pattern.split("|"):
    if part.startswith("@"):
        path_refs.append(part[1:])  # Pfad-Referenz
    else:
        regex_parts.append(part)    # Regex-Teil
```

### Unterordner-Match

```python
for f in sorted(knowledge_dir.glob("**/*.md")):
    rel_path = f.relative_to(knowledge_dir)
    match_string = str(rel_path.with_suffix("")).replace("\\", "/")

    if regex and not regex.search(match_string):
        continue
```

### Output-Format

Jede geladene Datei wird mit Header versehen:

```markdown
### company:
[Inhalt von company.md]

### linkedin/style:
[Inhalt von linkedin/style.md]
```

## Debugging

### Logging

Bei aktiviertem Logging erscheinen Meldungen wie:

```
[Base] Knowledge loaded: company (1234 chars)
[Base] Knowledge loaded: linkedin/style (567 chars)
[Base] Knowledge disabled (empty pattern)
[Base] Knowledge cache HIT (45s old)
```

### Test-Aufrufe

```python
# Im Python-Interpreter testen
from ai_agent.base import load_knowledge

# Alle laden
print(load_knowledge(None))

# Pattern testen
print(load_knowledge("linkedin"))

# Nichts laden
print(load_knowledge(""))  # → ""
```

## Verwandte Dokumentation

- [Creating Agents](creating-agents.md) - Agent-Erstellung mit Knowledge
- [System Architecture](system-architecture.md) - Gesamtarchitektur
- [Config Reference](config-reference.md) - agents.json Referenz
