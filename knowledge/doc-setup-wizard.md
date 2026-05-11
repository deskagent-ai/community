# Setup Wizard

The Setup Wizard is shown on the first start of DeskAgent and helps configure the AI backends.

## When is the Wizard shown?

The wizard appears automatically when `config/backends.json` does not exist. After completion, this file is created and the wizard is no longer shown.

## Configuration Steps

### Step 1: Claude AI (Anthropic)

**If Claude Code CLI is installed:**
- The wizard detects the installation automatically
- Shows "Claude Code found - no API key required"
- Uses the Claude subscription (cheaper than API)

**If Claude Code CLI is not installed:**
- Enter Anthropic API key (starts with `sk-ant-`)
- Create key at: https://console.anthropic.com/settings/keys

Claude offers the highest quality for complex agents, banking, and demanding tasks.

### Step 2: Google Gemini

- Enter Gemini API key (starts with `AIza`)
- Create key at: https://aistudio.google.com/apikey
- Good price-performance ratio with free tier

### Step 3: OpenAI

- Enter OpenAI API key (starts with `sk-`)
- Create key at: https://platform.openai.com/api-keys
- Required for Whisper speech recognition (voice-to-text)
- Optional if voice features are not used

### Step 4: Privacy

This step allows the installation of language models for **anonymization** of sensitive data.

**What is installed?**
- `de_core_news_lg` - German language model (~500MB)
- `en_core_web_lg` - English language model (~500MB)

**What are the models for?**
- Detection of personal data (names, emails, addresses, phone numbers)
- Automatic anonymization before sending to AI backends
- Works with the `anonymize: true` flag in agent configurations

**Options:**
- **"Install privacy models"** - Downloads the models (~1GB, may take several minutes)
- **"Skip"** - Anonymization stays disabled, can be installed manually later

**Manual installation (if skipped):**
```bash
python -m spacy download de_core_news_lg
python -m spacy download en_core_web_lg
```

## Skipping

Each step can be skipped. The configuration can be adjusted manually later in `config/backends.json`.

## Result

After completion, `config/backends.json` is created with the configured backends:

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

## Priority

The backends are set as `default_ai` in this order:
1. Claude SDK (if configured)
2. Gemini (if Claude is not configured)

## Run Wizard Again

To show the wizard again:
1. Delete or rename `config/backends.json`
2. Restart DeskAgent or open http://localhost:8765/

## Technical Details

| Component | Path |
|-----------|------|
| Frontend | `deskagent/scripts/templates/setup.html` |
| Backend | `deskagent/scripts/assistant/routes/ui.py` |
| Result | `config/backends.json` |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/setup` | GET | Show wizard HTML |
| `/api/setup/check-claude` | GET | Check Claude CLI availability |
| `/api/setup/check-spacy` | GET | Check spaCy models status |
| `/api/setup/install-spacy` | POST | Download spaCy models |
| `/api/setup` | POST | Save configuration |

### Wizard Flow

```
Welcome (License) → Claude → Gemini → OpenAI → Privacy → Done
     Page 0          Page 1   Page 2   Page 3   Page 4   Page 5
```
