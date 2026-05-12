# Prompt Optimization for DeskAgent

This guide shows how to analyze and optimize agent prompts.

## Analyze Prompt Log

On every agent call, the full prompt is stored in `workspace/.logs/prompt_latest.txt`.

**Example header:**
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

**Notes:**
- For `claude_sdk`, MCP server names are shown (e.g. `MCP:proxy`, `MCP:outlook`), since the tools are loaded dynamically by the SDK.
- The TEMPLATES section shows loaded templates and provides an optimization tip when `dialogs.md` is loaded.
- For agents with `skip_dialogs: true`, the section shows "Status: SKIPPED" and the saved tokens.

## Understanding Token Distribution

| Area | Typical share | Source |
|------|---------------|--------|
| Base Prompt | ~200 tokens | `DEFAULT_SYSTEM_PROMPT` in base.py |
| Date context | ~100 tokens | Automatically generated |
| Security warning | ~150 tokens | `input_sanitizer.py` |
| **Knowledge** | 30-80% | `knowledge/*.md` files |
| Templates (dialogs) | ~1,400 tokens | `templates/dialogs.md` (skippable with `skip_dialogs`) |
| Working directories | ~50 tokens | Automatically generated |
| Agent instructions | variable | `instructions` in agents.json |

## Common Problems

### 1. Knowledge Overload

**Problem:** All knowledge files are loaded, although only some are relevant.

**Symptom:** System prompt > 10K tokens, 70%+ of which is knowledge.

**Solution:** Set `knowledge` pattern in `agents.json`:

```json
{
  "deskagent_support": {
    "ai": "gemini",
    "knowledge": "deskagent_faq|deskagent_pricing"
  }
}
```

**Pattern syntax:**

| Pattern | Result |
|---------|--------|
| `""` (empty) | Loads NOTHING |
| `"company"` | Loads only `company.md` |
| `"company\|products"` | Loads `company.md` and `products.md` |
| `null` / missing | Loads ALL |

### 2. Redundant Knowledge Files

**Problem:** Multiple files contain the same information.

**Example:**
- `deskagent_faq.md` contains pricing
- `deskagent_pricing.md` also contains pricing
- `demo_guide.md` summarizes both

**Solution:**
- Consolidate files, or
- Load only the relevant ones per agent

### 3. Irrelevant Templates

**Problem:** Dialog templates are loaded even though the agent does not use dialogs.

**Symptom:** ~1,400 tokens for QUESTION_NEEDED/CONFIRMATION_NEEDED even though `Auto-Send: True`.

**Solution:** `skip_dialogs: true` in the agent frontmatter:

```markdown
---
{
  "ai": "gemini",
  "skip_dialogs": true
}
---
```

### 4. Missing Agent Instructions

**Problem:** The prompt says "use tools" but not which or how.

**Solution:** `instructions` in `agents.json` or in the agent markdown:

```json
{
  "email_support": {
    "ai": "gemini",
    "instructions": "Beantworte E-Mails freundlich. Nutze gmail_create_reply_draft() für Antworten."
  }
}
```

## Optimization Checklist

### Before Optimization

1. Run agent
2. Open `prompt_latest.txt`
3. Analyze token distribution

### Optimization Steps

- [ ] **Filter knowledge** - Load only relevant files
- [ ] **skip_dialogs** - When no user dialogs are needed
- [ ] **instructions** - Clear instructions for the agent
- [ ] **allowed_mcp** - Load only required MCP servers
- [ ] **allowed_tools** - Expose only required tools

### After Optimization

1. Run agent again
2. Check token reduction in `prompt_latest.txt`
3. Test response quality

## Example: Before/After Optimization

### Before (11.5K tokens)

```json
{
  "deskagent_support": {
    "ai": "claude_sdk"
  }
}
```

- Loads all 9 knowledge files (~9K tokens)
- Loads dialog templates (~600 tokens)
- No specific instructions

### After (4.5K tokens, -60%)

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

- Loads only 3 relevant knowledge files (~3K tokens)
- No dialog templates
- Clear instructions
- Only Gmail tools available

## Token Saving Tips

| Measure | Saving |
|---------|--------|
| Reduce knowledge to 2-3 files | 3-6K tokens |
| `skip_dialogs: true` | ~1,400 tokens |
| Short, precise instructions | better than long knowledge |
| Remove redundancies in knowledge | 20-40% |

## Cost Impact

For Gemini ($1.25/1M input tokens):

| Prompt size | Cost per call |
|-------------|---------------|
| 15K tokens | $0.019 |
| 8K tokens | $0.010 |
| 4K tokens | $0.005 |

**50% fewer tokens = 50% lower cost** for the input portion.

## Further Documentation

- [doc-creating-agents.md](doc-creating-agents.md) - Agent creation
- [doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md) - All frontmatter fields (incl. agent-as-tool)
