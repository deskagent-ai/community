# Knowledge System

Technical documentation of the Knowledge system in DeskAgent.

## Overview

The Knowledge system loads Markdown files from the `knowledge/` folder and inserts them into the system prompt of the AI backend. Agents can define via patterns which knowledge files are loaded.

```
knowledge/
├── company.md              # Company info
├── products.md             # Products & prices
├── mailstyle.md            # Email writing style
└── linkedin/               # Subfolder
    ├── style.md
    └── examples.md
```

## Architecture

### System Prompt Structure

```
┌────────────────────────────────────┐
│ 1. Base System Prompt              │  ← from config or DEFAULT
├────────────────────────────────────┤
│ 2. Security Templates              │  ← Prompt injection protection
├────────────────────────────────────┤
│ 3. System Templates                │  ← deskagent/templates/*.md
├────────────────────────────────────┤
│ 4. Knowledge Base                  │  ← knowledge/**/*.md (filtered)
├────────────────────────────────────┤
│ 5. Agent Instructions              │  ← agents/*.md
└────────────────────────────────────┘
```

### Core Function

**File:** `deskagent/scripts/ai_agent/base.py`

```python
def load_knowledge(pattern: str = None) -> str:
    """
    Loads knowledge files based on pattern.

    Args:
        pattern: Regex pattern, path reference, or empty

    Returns:
        Concatenated knowledge content
    """
```

## Pattern Syntax

### Regex Patterns

Patterns are applied as regex to the relative path (without `.md`):

| Pattern | Match string | Result |
|---------|--------------|--------|
| `company` | `company` | `knowledge/company.md` |
| `linkedin` | `linkedin/style`, `linkedin/examples` | All files in the subfolder |
| `linkedin/style` | `linkedin/style` | Only this specific file |
| `company\|products` | OR match | Both files |
| `^(?!linkedin)` | Negative lookahead | Everything except linkedin/* |

### Special Values

| Pattern | Behavior |
|---------|----------|
| `None` (not set) | Loads ALL `knowledge/**/*.md` |
| `""` (empty string) | Loads NOTHING (explicitly disabled) |

### Path References (@)

External files/folders can be referenced with `@`:

```
"@deskagent/docs/creating-agents.md"  # Single file
"@deskagent/documentation/"           # Folder (recursive)
"company|@external/docs/"             # Mixed
```

**Resolution order:**
1. Relative to `PROJECT_DIR` (workspace)
2. Relative to `DESKAGENT_DIR.parent`
3. Relative to `DESKAGENT_DIR`

## Configuration

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

### Recommendations

| Agent type | Recommended pattern |
|------------|---------------------|
| Email replies | `company\|products\|mailstyle` |
| Invoices/quotes | `company\|products` |
| Social media | `linkedin` or specific folder |
| Technical agents | `""` (no knowledge) |

## Caching

Knowledge is cached with a 5-minute TTL:

```python
def load_knowledge_cached(pattern: str = None) -> str:
    """Cached version of load_knowledge()"""

def invalidate_knowledge_cache():
    """Manually invalidate cache after changes"""
```

## Implementation Details

### Pattern Parsing

```python
# Pattern is split into parts
for part in pattern.split("|"):
    if part.startswith("@"):
        path_refs.append(part[1:])  # Path reference
    else:
        regex_parts.append(part)    # Regex part
```

### Subfolder Match

```python
for f in sorted(knowledge_dir.glob("**/*.md")):
    rel_path = f.relative_to(knowledge_dir)
    match_string = str(rel_path.with_suffix("")).replace("\\", "/")

    if regex and not regex.search(match_string):
        continue
```

### Output Format

Each loaded file is prefixed with a header:

```markdown
### company:
[Content of company.md]

### linkedin/style:
[Content of linkedin/style.md]
```

## Debugging

### Logging

With logging enabled, messages like the following appear:

```
[Base] Knowledge loaded: company (1234 chars)
[Base] Knowledge loaded: linkedin/style (567 chars)
[Base] Knowledge disabled (empty pattern)
[Base] Knowledge cache HIT (45s old)
```

### Test Calls

```python
# Test in the Python interpreter
from ai_agent.base import load_knowledge

# Load all
print(load_knowledge(None))

# Test pattern
print(load_knowledge("linkedin"))

# Load nothing
print(load_knowledge(""))  # → ""
```

## Related Documentation

- [Creating Agents](creating-agents.md) - Agent creation with knowledge
- [System Architecture](system-architecture.md) - Overall architecture
- [Config Reference](config-reference.md) - agents.json reference
