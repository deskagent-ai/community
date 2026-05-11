# DeskAgent - AI Desktop Assistant

## Overview

DeskAgent is an AI-powered desktop assistant that automates office work. It runs locally on Windows and connects to your existing tools - email, invoicing, support systems.

**Core Concept:** You speak naturally → AI understands → Tools execute → You review before anything is sent.

## Target Users

| User | Use Cases |
|------|-----------|
| **Freelancers** | Invoice from time logs, inbox management, payment tracking |
| **Small Business** | Supplier invoices, SEPA transfers, document archiving |
| **Support Teams** | Ticket queues, draft responses, escalation |
| **Admin Staff** | Email management, calendar, document organization |

## Features

### Email Automation
- Smart sorting, flagging, folder organization
- Quick reply drafts with AI
- PDF attachment processing
- Multi-account support (Outlook, Gmail, M365)

### Invoice & Quote Generation
- Create quotes from email inquiries
- Generate invoices from time logs
- Payment tracking (open, paid, overdue)
- PDF export
- **Systems:** Billomat, Lexware Office

### Document Management
- Upload with auto-classification
- OCR full-text search
- Bulk tagging
- **Systems:** Paperless-ngx, ecoDMS

### Support Tickets
- Queue overview
- AI-drafted responses using your FAQ
- Status management
- **System:** UserEcho

### Calendar & Scheduling
- Daily/upcoming events view
- Create appointments via natural language
- Teams meeting links
- Availability check
- **Systems:** Outlook Calendar, Google Calendar, Microsoft Graph

### Banking & Payments
- SEPA transfer XML (pain.001)
- Batch payments
- CAMT.052 bank statement import
- Invoice-payment matching
- IBAN validation

### Voice Input (Whisper)
- Hotkey-activated recording
- Multi-language (auto-detect or set)
- Dictation mode (insert text anywhere)
- Agent trigger hotkey

### Teams Integration
- Read/send chat and channel messages
- Webhook notifications as "DeskAgent" bot
- Auto-response on channel mentions

## Pre-built Agents

| Agent | Function |
|-------|----------|
| Daily Check | Sort emails, flag urgent, clear newsletters |
| Create Offer | Email inquiry → formal quote |
| Check Payments | Match bank statements to invoices |
| Invoice Processing | Create invoices from emails/time logs |
| Email Reply | Draft professional responses |
| Archive Documents | Save to DMS with classification |

## Custom Agents

Markdown files define agent behavior:
```markdown
---
{ "ai": "gemini", "allowed_mcp": "outlook|billomat" }
---
# Agent: My Workflow
Instructions in natural language...
```

**Features:**
- No coding required
- Per-agent AI backend selection
- Extension filtering (allowed_mcp)
- Tool whitelisting (allowed_tools)
- Input forms (file/text collection before run)
- Placeholders: `{{TODAY}}`, `{{YEAR}}`, `{{TEMP_DIR}}`

## Integrations

### Email
| System | Features | Requirements |
|--------|----------|--------------|
| **Outlook (local)** | Full access, attachments, multi-mailbox | Outlook installed + running |
| **Microsoft 365 (Graph)** | Server-side search, no Outlook needed | M365 account, device code auth |
| **Gmail** | Native Google API, labels, attachments | Google OAuth2 |

### Billing
| System | Features |
|--------|----------|
| **Billomat** | Customers, quotes, invoices, articles, PDF export |
| **Lexware Office** | Contacts, quotes, invoices, credit notes |

### Documents
| System | Features |
|--------|----------|
| **Paperless-ngx** | OCR, full-text search, auto-tagging, bulk edit |
| **ecoDMS** | Classification, version control, thumbnails |

### Other
- **UserEcho** - Support tickets
- **Microsoft Teams** - Chat, channels, webhooks
- **SEPA** - Bank transfers (pain.001), statements (CAMT.052)
- **PDF** - Extract pages, merge, split, read text

## AI Backends

| Backend | Type | Pricing (per 1M tokens) | Best For |
|---------|------|-------------------------|----------|
| **Claude** (Anthropic) | Cloud | $3 / $15 | Complex tasks, customer content |
| **Gemini** (Google) | Cloud | $1.25 / $10 | Routine tasks, budget (60% cheaper) |
| **GPT-4o** (OpenAI) | Cloud | $2.50 / $10 | Alternative, Whisper voice |
| **Ollama** | Local | Free | Privacy, offline |

**Typical Task Costs:**
- Email reply: $0.01-0.05
- Invoice creation: $0.02-0.08
- Daily email check: $0.05-0.15

**Monthly Estimates:** $5-50 depending on usage.

## Security

- **Local Execution** - Data stays on your PC
- **PII Anonymization** - Mask names, emails, IBANs before AI
- **Extension Filtering** - Agents access only allowed services
- **Tool Whitelisting** - Restrict specific actions
- **Prompt Injection Protection** - Sanitize external content
- **GDPR Compliant** - No cloud storage of documents

## Technical

### System Requirements
- Windows 10/11
- 8 GB RAM (16 GB for Ollama)
- 2 GB storage
- Outlook (optional, for local email)
- AI API key (or Ollama for free/offline)

### Configuration Files
| File | Purpose |
|------|---------|
| `backends.json` | AI provider keys |
| `apis.json` | External service credentials |
| `system.json` | UI, voice, logging |
| `agents.json` | Agent definitions |

### Logs
- `workspace/.logs/system.log` - System activity
- `workspace/.logs/agent_latest.txt` - Last agent run

### Authentication
| Service | Method |
|---------|--------|
| Outlook | Windows COM (automatic) |
| Microsoft Graph | Device Code OAuth |
| Gmail | OAuth2 Browser Flow |
| Billomat, Lexware, UserEcho | API Key |
| Paperless | Token or credentials |

## Pricing

### DeskAgent License
- **Trial:** 14 days, full features, no credit card
- **Monthly:** EUR 90/month (cancel anytime)
- **Annual:** EUR 918/year (save 15%)

### AI Costs (separate, pay-as-you-go)
Pay directly to AI provider. See "AI Backends" section above.

### Included
All integrations, voice input, custom agents, SEPA, PDF processing, updates, email support.

### You Provide
AI API key, your existing tool subscriptions (M365, Billomat, etc.)

## Getting Started

1. Download from [deskagent.de](https://deskagent.de)
2. Run installer (includes Python + dependencies)
3. Add AI key in setup wizard
4. Start automating

**Get API Keys:**
- Anthropic: [console.anthropic.com](https://console.anthropic.com/)
- Google: [aistudio.google.com](https://aistudio.google.com/)
- OpenAI: [platform.openai.com](https://platform.openai.com/)

## FAQ

**Does Outlook need to be running?**
For local features, yes. Use Microsoft Graph or Gmail for no-Outlook access.

**Can DeskAgent send emails automatically?**
By default it creates drafts. Auto-send can be enabled per agent.

**Can I use it offline?**
Yes, with Ollama (local AI). Quality is lower but free and private.

**Where are my files stored?**
Locally on your PC. Only AI prompts go to cloud providers.

## Support

- **Email:** support@deskagent.de
- **Docs:** [doc.deskagent.de](https://doc.deskagent.de)
