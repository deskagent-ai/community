# AI Backend Reference

Complete reference of all available AI backends in DeskAgent.

## Overview

DeskAgent supports several AI backends with different strengths and pricing.

| Backend | Model | Type | Price/1M Tokens | Use Case |
|---------|-------|------|-----------------|----------|
| **claude_sdk** | Claude Opus 4.6 (default) | Agent SDK + MCP | $15/$75 | **Recommended** - Best MCP integration |
| **gemini** | Gemini 2.5 Pro | API | $1.25/$10 | Cheap alternative with good quality |
| **gemini_flash** | Gemini 2.5 Flash | API | $0.30/$2.50 | Fast and very cheap |
| **gemini_3** | Gemini 3.1 Pro Preview | API | $2/$12 | **New** - Better tool handling, structured outputs |
| **gemini_3_flash** | Gemini 3.1 Flash Preview | API | $0.50/$3 | **New** - Fast Gemini 3 model |
| **openai** | GPT-5 (configurable) | API | $1.25/$10 | OpenAI standard model |
| **mistral** | Mistral Large | API | $2/$6 | European provider |
| **qwen** | Qwen | Ollama (local) | free | Offline, no API costs |
| **claude** | Claude (CLI) | CLI | $3/$15 | Legacy, uses CLI instead of SDK |

> **Note:** `claude_sdk` requires the optional `claude-agent-sdk` extra. Install via `pip install "deskagent[claude-sdk]"`. The wrapper degrades gracefully if the SDK is not installed.

---

## Backend Details

### Claude Agent SDK (`claude_sdk`)

**Recommended for production use**

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

**Advantages:**
- Best MCP tool integration (native support)
- Reliable multi-step tool calling
- Session management and context caching
- Prompt caching saves cost on repeated prompts

**Disadvantages:**
- Default model (`claude-opus-4-6`) is significantly more expensive than Gemini ($15/$75 vs $1.25/$10)
- Switch to Sonnet via `"model": "claude-sonnet-4-5-20250929"` for $3/$15 pricing
- Only Anthropic models available
- Requires optional `[claude-sdk]` extra (bundles proprietary `claude` binary)

**Permission Modes:**
- `"default"` - Ask before every tool call (for UI-based workflows)
- `"acceptEdits"` - Auto-approve only for file edits
- `"bypassPermissions"` - **Auto-approve everything** (for unattended agents)

**SDK Mode (Extended Features):**
- `"extended"` (default) - Extended features:
  - **Sessions:** Session ID for resume capability
  - **AskUserQuestion:** Native SDK dialogs
  - **Structured Outputs:** JSON schema validated responses
- `"legacy"` - Old behavior without new features

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "api_key": "...",
    "sdk_mode": "legacy"  // only if old behavior is desired
  }
}
```

**When to use:**
- Critical business processes (email, invoices, SEPA)
- Agents with many MCP tools
- When reliability matters more than cost

---

### Gemini 2.5 Pro (`gemini`)

**Best price/performance for most use cases**

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

**Advantages:**
- **60% cheaper** than Claude ($1.25/$10)
- Good MCP tool support (via `tool_bridge`)
- Multimodal (text, images, PDFs)
- Thinking mode for complex reasoning

**Disadvantages:**
- Sometimes unstable tool calls in very complex workflows
- Higher risk of "Malformed Function Call" errors

**When to use:**
- Email replies (`reply_email_gemini`)
- Document analysis
- Cost-optimized workflows
- High volumes (e.g. daily check with many emails)

---

### Gemini 2.5 Flash (`gemini_flash`)

**Fastest and cheapest option**

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

**Advantages:**
- **90% cheaper** than Claude ($0.30/$2.50)
- Very fast (< 1s latency)
- Good for simple tasks

**Disadvantages:**
- Weaker at complex reasoning
- Less reliable for multi-tool workflows

**When to use:**
- Newsletter classification
- Simple email categorization
- Document tagging
- Test workflows

---

### Gemini 3 Pro (`gemini_3`)

**New - Improved tool integration**

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

**New features (Gemini 3 vs 2.5):**
- **Structured Outputs with Tools** - Combines function calling with JSON Schema
- **Better tool reasoning** - Fewer malformed function calls
- **Multi-step agentic capabilities** - More complex workflows
- **Thought Signatures** - Gemini 3 requires `thought_signature` in function_call parts on the continuation call. DeskAgent stores original part objects to forward these automatically.

**Advantages:**
- More reliable tool handling than Gemini 2.5
- Structured outputs ideal for dialogs (QUESTION_NEEDED, CONFIRMATION_NEEDED)
- Still cheaper than Claude ($2/$12 vs $3/$15)

**Disadvantages:**
- **Preview status** - May still change
- 60% more expensive than Gemini 2.5 ($2 vs $1.25 input)

**When to use:**
- Agents with complex MCP workflows (e.g. `ask_sap`, `create_invoice_from_email`)
- When Gemini 2.5 produces too many tool errors
- Structured outputs (forms, validation)

**Migration from Gemini 2.5:**
```markdown
<!-- In agent frontmatter -->
---
{
  "ai": "gemini_3",  # ← Just change backend
  "allowed_mcp": "billomat|outlook"
}
---
```

---

### Gemini 3 Flash (`gemini_3_flash`)

**Fast Gemini 3 model**

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

**When to use:**
- When Gemini 2.5 Flash is too weak
- When fast structured outputs are needed
- When cost optimization is important

---

### OpenAI (`openai`)

```json
{
  "openai": {
    "type": "openai_api",
    "api_key": "sk-...",
    "model": "gpt-5",
    "anonymize": true
  }
}
```

**When to use:**
- When specific OpenAI features are required
- Benchmark comparisons

**Note:** Gemini 2.5 and Claude SDK offer better price/performance for most DeskAgent use cases.

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

**When to use:**
- When GDPR compliance matters (EU provider)
- Cheaper than Claude, stronger than Gemini on some tasks

---

### Qwen (`qwen`)

**Completely offline**

```json
{
  "qwen": {
    "type": "qwen_agent",
    "model": "qwen2.5:32b",
    "base_url": "http://localhost:11434"
  }
}
```

**Advantages:**
- Completely free
- Offline operation (no internet connection needed)
- Privacy (nothing leaves the PC)

**Disadvantages:**
- Weaker than cloud models
- Requires strong GPU (32B model ~20GB VRAM)
- Slower than API models

**When to use:**
- Development/testing without API costs
- High privacy requirements
- No internet available

---

## Cost Comparison

**Example: Reply to an email (3K input + 500 output tokens)**

| Backend | Input cost | Output cost | Total | Relative |
|---------|-----------|-------------|-------|----------|
| **gemini_flash** | $0.0009 | $0.00125 | **$0.00215** | 1x |
| **gemini** | $0.00375 | $0.005 | **$0.00875** | 4x |
| **gemini_3_flash** | $0.0015 | $0.0015 | **$0.003** | 1.4x |
| **gemini_3** | $0.006 | $0.006 | **$0.012** | 5.6x |
| **claude_sdk** (Opus 4.6, default) | $0.045 | $0.0375 | **$0.0825** | 38x |
| **claude_sdk** (Sonnet 4.5) | $0.009 | $0.0075 | **$0.0165** | 7.7x |

**For 1000 emails/month:**
- **Gemini Flash**: $2.15
- **Gemini 2.5 Pro**: $8.75
- **Gemini 3 Flash**: $3.00
- **Gemini 3 Pro**: $12.00
- **Claude SDK (Sonnet 4.5)**: $16.50
- **Claude SDK (Opus 4.6 default)**: $82.50

---

## Backend Selection Matrix

| Use case | Recommendation | Alternative |
|----------|----------------|-------------|
| **Reply to email** | `gemini` | `gemini_flash` (cheaper) |
| **Create invoices** | `claude_sdk` | `gemini_3` (cheaper) |
| **SEPA transfers** | `claude_sdk` | - (critical!) |
| **Support tickets** | `gemini` | `gemini_3` |
| **Filter newsletters** | `gemini_flash` | `gemini_3_flash` |
| **Complex SAP queries** | `gemini_3` | `claude_sdk` |
| **Document analysis** | `gemini` | `gemini_3` |
| **Daily check (100+ mails)** | `gemini_flash` | `gemini` |
| **Development/testing** | `qwen` | `gemini_flash` |

---

## Global AI Override

In Settings > Preferences a global override can be set, forcing all agents to use a particular backend. Useful when an AI service is unavailable or for cost control.

**Resolution priority:**
1. Per-call override (API `body.backend`) - highest
2. **Global AI Override** (`system.json` > `global_ai_override`) - NEW
3. Agent frontmatter (`ai: "gemini"`)
4. `default_ai` from backends.json
5. First available backend - fallback

**Set:** Settings > Preferences > AI model dropdown
**API:** `POST /config/backend_override` with `{"backend": "gemini"}` or `{"backend": "auto"}`

---

## Configuration Options

### Common Options (all backends)

```json
{
  "backend_name": {
    "type": "...",
    "api_key": "...",
    "anonymize": true,           // Enable anonymization
    "timeout": 300,              // API timeout in seconds
    "max_tokens": 8192,          // Max output tokens
    "temperature": 0.7,          // Creativity (0.0 - 1.0)
    "max_iterations": 30,        // Max tool-call loops
    "pricing": {
      "input": 2.0,              // $/1M input tokens
      "output": 12.0             // $/1M output tokens
    }
  }
}
```

### Gemini-Specific Options

```json
{
  "gemini": {
    "type": "gemini_adk",
    "model": "gemini-2.5-pro",     // Or gemini-3.1-pro-preview
    "thinking_budget": 8192,       // Thinking tokens (auto for 2.5+/3.0)
    "max_iterations": 30           // Important for tool-heavy agents
  }
}
```

**Thinking budget:**
- `0` - No thinking (only Gemini 2.0/1.5)
- `8192` - **Auto default for Gemini 2.5+/3.0** (required!)
- Higher - More internal reasoning (more expensive)

### Claude SDK-Specific Options

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "permission_mode": "bypassPermissions",  // Important for unattended!
    "admin_api_key": "sk-ant-admin01-...",  // For extended features
    "use_anonymization_proxy": true,        // MCP tool anonymization
    "mcp_transport": "sse"                  // MCP transport mode
  }
}
```

**MCP Transport Mode (`mcp_transport`):**

| Value | Description | Anonymization | Stability |
|-------|-------------|---------------|-----------|
| `"inprocess"` | **In-process SDK** (no network) | Yes | Very stable |
| `"streamable-http"` | HTTP proxy | Yes | Stable |
| `"sse"` | SSE proxy (deprecated) | Yes | Stable |
| `"stdio"` | Direct subprocess (default) | Yes (if `anonymize: true`) | Stable |

**Recommended: `inprocess`**

The `inprocess` transport runs MCP tools directly in the SDK process - no network, no proxy, no subprocesses. This completely eliminates all "MCP proxy: failed" errors.

```json
{
  "claude_sdk": {
    "type": "claude_agent_sdk",
    "mcp_transport": "inprocess",
    "anonymize": true
  }
}
```

**Advantages of `inprocess`:**
- **No network errors** - Tools run directly in the same process
- **Fastest startup** - No HTTP server or subprocess start
- **Simple debugging** - One process instead of multiple
- **Full anonymization** - Same PII protection as other transports

**When to use other transports:**
- `"stdio"`: For debugging or when `inprocess` causes problems
- `"streamable-http"` / `"sse"`: For special proxy requirements

**Note:** `inprocess` requires claude-agent-sdk >= 0.1.27. If not available, falls back to `stdio`.

---

## Best Practices

### 1. Choose Backend per Agent

**Not:** One backend globally for all agents
**But:** Backend per agent in frontmatter

```markdown
---
{
  "ai": "gemini_flash",  # ← Cheap backend for newsletters
  "allowed_mcp": "outlook"
}
---
# Agent: Cleanup Newsletters
```

### 2. Cost Monitoring

- Claude SDK/API log token usage automatically
- Gemini ADK shows cost in log: `[Gemini] Cost: $0.0087`
- Check `.logs/system.log` for total cost

### 3. Fallback Strategies

**Option A: Retry with another backend**
```markdown
<!-- If gemini fails, switch to claude_sdk -->
"ai": "gemini",
"fallback_ai": "claude_sdk"  # ← Not implemented, TODO
```

**Option B: Manual escalation**
- Gemini Flash for initial classification
- On uncertainty → escalate to Gemini 2.5/3
- Critical tasks directly with Claude SDK

### 4. Preview Models in Production

**Caution with `gemini-3.*-*-preview`:**
- Can change without warning
- Pricing can change (currently preview pricing)
- For production: wait for GA release (stable model names)

### 5. Enable Anonymization

**Always set `"anonymize": true`!**
```json
{
  "gemini": {
    "anonymize": true  // ← Removes PII before API call
  }
}
```

Protects against:
- PII leaks (names, emails, IBANs)
- Prompt injection via email content
- GDPR violations

---

## Migration Between Backends

### Gemini 2.5 → Gemini 3

**Changes:**
1. Adjust backend name in frontmatter
2. **Done!** (code is compatible)

```diff
---
{
- "ai": "gemini",
+ "ai": "gemini_3",
  "allowed_mcp": "billomat|outlook"
}
---
```

**To note:**
- Cost increases by 60% ($1.25 → $2 input)
- Better tool reliability
- Thinking budget is set automatically

### Claude SDK → Gemini 3

**Changes:**
1. Change backend name
2. `permission_mode` is dropped (not relevant for API)
3. Possibly increase `max_iterations` (Gemini sometimes needs more loops)

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

**Risks:**
- Tool calls may be invoked differently
- Test before production use!

---

## Troubleshooting

### "Budget 0 is invalid" Error (Gemini)

**Cause:** Gemini 2.5+ requires thinking mode

**Fix:** Automatic - code sets `thinking_budget=8192` for Gemini 2.5+/3.0

If manually desired:
```json
{
  "gemini": {
    "thinking_budget": 8192  // Set explicitly
  }
}
```

### "MALFORMED_FUNCTION_CALL" (Gemini)

**Cause:** Model generates invalid tool arguments

**Fix:**
1. Retry logic (automatic, up to 3x)
2. Text-only fallback after 3 retries
3. If frequent → switch to `gemini_3` or `claude_sdk`

### Empty Responses After Tool Calls

**Cause:** Model "forgets" to respond after many tool calls

**Fix:** Automatic - code requests summary after STOP

If frequent:
- Reduce `max_iterations` (e.g. 20 instead of 30)
- Split task into smaller agents

### API Timeout

**Fix:**
```json
{
  "timeout": 600  // 10 minutes instead of 5
}
```

---

## Further Resources

- **[doc-config-reference.md](doc-config-reference.md)** - Full config options
- **[doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md)** - Agent `ai` field
- **[doc-anonymization.md](doc-anonymization.md)** - Anonymization details
- **Gemini 3 Docs:** https://ai.google.dev/gemini-api/docs/gemini-3
- **Claude SDK Docs:** https://docs.anthropic.com/en/docs/agents
