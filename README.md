# DeskAgent

> **Your tireless helper. 100% Open Source under AGPL-3.0.**
> A local-first AI desktop assistant with deep MCP integration.
> Self-hosted, GDPR-friendly, no cloud lock-in.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![GitHub Discussions](https://img.shields.io/badge/discuss-on%20github-orange.svg)](https://github.com/deskagent-ai/community/discussions)

## What is DeskAgent?

DeskAgent automates repetitive desk work with plain-text instructions or
your voice. It plugs multiple LLM backends (Claude, Gemini, OpenAI,
Mistral, local Qwen/Ollama) into a rich set of MCP servers covering
email, calendars, document management, accounting, payments, PDFs,
Excel, browser automation, and more.

Workflows are defined as **Markdown agents and skills** with a small
frontmatter — no UI clicking, no DSL, no vendor lock-in. Drop a `.md`
file into `agents/`, and DeskAgent picks it up. Edit it with any text
editor. Share it via Git.

DeskAgent runs as a local FastAPI server with a browser-based UI on
your own machine. It can also act as an **MCP hub** for Claude Desktop
and Claude Code, so the same agents and skills are available from
those clients.

## Why DeskAgent?

| | |
|---|---|
| 🔒 **Local-first** | Your data stays on your machine. No mandatory cloud, no telemetry. |
| 🇪🇺 **GDPR-friendly** | Optional PII anonymization layer (Microsoft Presidio) routes only redacted text to LLM providers. |
| 🔌 **MCP-native** | 22+ built-in MCP servers. Also exposes itself as an MCP hub for Claude Desktop and Claude Code. |
| 🧩 **Pluggable** | Skills, agents, MCP servers, and full plugins as drop-in folders. Plugin Exception in the license. |
| 🪶 **Plain Markdown** | Agents are Markdown with frontmatter. Read them, share them, version them. |
| 🆓 **No subscription** | AGPL-3.0 source. Self-host forever. Commercial license available on request. |

## Who is it for?

- **Freelancers & consultants** drowning in invoices, time tracking, and email replies
- **Small businesses** that want one place for email, accounting, DMS, and SEPA payments
- **Support teams** automating ticket triage and first-response drafts
- **Power users** who want to drive Outlook/Gmail/Excel/PDF from natural language
- **Developers** building local AI workflows on top of MCP

## Features

- **Multi-backend LLM**: Claude (API + Agent SDK), Gemini, OpenAI,
  Mistral, local Qwen/Ollama. Switch per agent.
## What DeskAgent can do for you

| Workflow | What it does |
|----------|--------------|
| 📧 **Email management** | Read, sort, draft replies, flag follow-ups across Outlook, Gmail, IMAP, and Microsoft Graph |
| 🧾 **Quotes & invoices** | Create offers and invoices in Billomat or Lexware from contacts, time logs, or e-mail bodies |
| 🎫 **Support tickets** | Triage and draft answers for UserEcho tickets |
| 💸 **SEPA transfers** | Turn invoice PDFs into pain.001 XML SEPA-credit-transfer batches |
| 📂 **Document archive** | OCR + auto-tagging for ecoDMS and Paperless-ngx |
| 🎤 **Voice input** | Whisper-powered hotkey dictation (optional extra) |
| 📅 **Calendar & meetings** | Read availability, create events, set up Teams meetings via Graph |
| 📊 **Excel & PDF** | Read/write spreadsheets, extract data from PDFs, render charts |
| 🌐 **Browser automation** | Drive Chrome via the Chrome DevTools Protocol from agents |

## Use DeskAgent from Claude Desktop and Claude Code

DeskAgent doubles as an **MCP hub**: it exposes all of its 22+ built-in
MCP servers through a single connection that Claude Desktop and
Claude Code can talk to. You configure DeskAgent once, and from then
on Claude has access to Outlook, Gmail, Billomat, Lexware, SEPA,
ecoDMS, Paperless, Excel, PDF, your browser, your filesystem — all
through standard MCP.

Why this matters:

- **One connection, many tools.** No need to configure 20 separate MCP
  servers in Claude Desktop. Hook up DeskAgent once.
- **The same agents from anywhere.** Workflows defined as Markdown
  agents are usable from the DeskAgent WebUI, Claude Desktop, and
  Claude Code. Write a recipe once, trigger it from whichever client
  you happen to be in.
- **Local-first.** All MCP calls stay on your machine. Claude only
  sees the redacted text DeskAgent decides to share.
- **Voice into Claude Code.** Hotkey + Whisper transcription, then
  DeskAgent forwards the task to Claude Code in the right project.

See [knowledge/doc-mcp-tools.md](knowledge/doc-mcp-tools.md) for the
full tool catalog and [knowledge/doc-setup-wizard.md](knowledge/doc-setup-wizard.md)
for the Claude Desktop / Claude Code hook-up.

## Highlights

- **Multi-backend LLM** — Claude (API + Agent SDK), Gemini, OpenAI, Mistral, local Qwen/Ollama. Pick a different backend per agent.
- **22+ MCP servers** included — Outlook, Gmail, IMAP, Microsoft Graph, Billomat, Lexware, ecoDMS, Paperless-ngx, SEPA, PDF, Excel, Browser, Filesystem, Datastore, Charts, Telegram, UserEcho, Instagram, LinkedIn, Clipboard. Bring your own via the plugin API.
- **Hot-reloadable** Markdown agents and skills.
- **Local knowledge base** loaded into agents on demand.
- **Scheduler and email watchers** for unattended workflows.
- **Optional PII anonymization** via Microsoft Presidio (`pip install deskagent[anonymizer]`) — sensitive data is redacted before it reaches the LLM and re-inserted in the response.
- **Plugin system** with a documented API and a Plugin Exception in the license so proprietary plugins are explicitly allowed.
- **Streamdeck integration** out of the box.

## Quick start

```bash
git clone https://github.com/deskagent-ai/community.git deskagent
cd deskagent

# macOS / Linux
./setup-unix.sh

# Windows
setup-python.bat

# Run
./start.sh    # macOS / Linux
start.bat     # Windows
```

WebUI opens at http://localhost:8765/.

Configure backends and API keys in `config/system.json` and
`config/backends.json` (templates are provided on first run).

## Documentation

All documentation lives in this repository. There is no separate
documentation site.

For developers and integrators:

- [knowledge/doc-overview.md](knowledge/doc-overview.md) — high-level architecture
- [knowledge/doc-folder-structure.md](knowledge/doc-folder-structure.md) — folder layout
- [knowledge/doc-startup-and-directories.md](knowledge/doc-startup-and-directories.md) — startup, CLI flags, multi-instance
- [knowledge/doc-config-reference.md](knowledge/doc-config-reference.md) — configuration reference
- [knowledge/doc-ai-backends.md](knowledge/doc-ai-backends.md) — LLM backend reference
- [knowledge/doc-mcp-tools.md](knowledge/doc-mcp-tools.md) — every MCP tool, all parameters
- [knowledge/doc-creating-mcp-servers.md](knowledge/doc-creating-mcp-servers.md) — build your own MCP server
- [knowledge/doc-creating-agents.md](knowledge/doc-creating-agents.md) — build your own agent
- [knowledge/doc-agent-frontmatter-reference.md](knowledge/doc-agent-frontmatter-reference.md) — agent frontmatter fields
- [knowledge/doc-pluginsystem.md](knowledge/doc-pluginsystem.md) — plugin system
- [knowledge/doc-anonymization.md](knowledge/doc-anonymization.md) — DSGVO anonymization
- [knowledge/doc-licensing.md](knowledge/doc-licensing.md) — licensing details, including the AGPL Section 13 Notice

## How to install

| Option | For whom | How |
|--------|----------|-----|
| **Source (this repo)** | Developers, self-hosters, AGPL-friendly users | `git clone` + `start.bat` / `start.sh` (see Quick start) |
| **Pre-built installer** | Business users wanting a signed installer, auto-updater, and an AGPL-free Commercial License | https://deskagent.de |

The pre-built installer ships exactly the same code as this repository
plus a Commercial License that removes the AGPL-3.0 obligations and
includes priority support.

## License

DeskAgent is licensed under the [GNU Affero General Public License v3.0](LICENSE)
with a [Plugin Exception](LICENSE) (see the bottom of the LICENSE file).

**Short version:**

- You may use, modify, and self-host DeskAgent freely.
- You may run it as a network service for other users — including
  customers — provided you make the modified source code available
  to those users (AGPL Section 13).
- You may write proprietary plugins that talk to DeskAgent through the
  documented plugin API; the Plugin Exception makes this explicit.
- If you want to run a modified version, ship binaries, or operate a
  SaaS without the AGPL source-disclosure obligation, you can purchase
  a Commercial License from realvirtual GmbH.

**Need an AGPL-free Commercial License?**
Contact info@realvirtual.io.

## Naming and forks

The name "DeskAgent" is a generic descriptive term and is not registered
as a trademark. You are legally free to fork and redistribute, including
under the same name. As a courtesy and to avoid user confusion, please
consider using a distinct name for your fork (e.g. "MyForkName, based on
DeskAgent"). This is a request, not a legal requirement.

## Contributing

Pull requests, bug reports, MCP servers, and agent definitions are
welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

By opening a pull request you confirm the contribution terms described
in [CONTRIBUTING.md](CONTRIBUTING.md) (inline statement, no separate
agreement to sign).

## Security

Please do not open public issues for security vulnerabilities. See
[SECURITY.md](SECURITY.md) for the disclosure process.

## Commercial distribution and support

For signed installers, auto-updater, AGPL-free Commercial License, and
priority support, contact **info@realvirtual.io**.

---

Built by [realvirtual GmbH](https://realvirtual.io). © 2026.
