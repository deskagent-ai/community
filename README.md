# DeskAgent

> Open source AI desktop assistant with deep MCP integration.
> AGPL-3.0 — fully self-hostable.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![GitHub Discussions](https://img.shields.io/badge/discuss-on%20github-orange.svg)](https://github.com/deskagent-ai/community/discussions)

## What is DeskAgent?

DeskAgent is a desktop AI assistant that connects multiple LLM backends
(Claude, Gemini, OpenAI, local Ollama) with a rich set of MCP servers
covering email, calendars, document management, accounting, payments,
PDFs, Excel, and more. Workflows are defined as agents and skills in
plain Markdown files with frontmatter — no UI clicking, no DSL.

It runs locally as a FastAPI server with a browser-based UI, and can
also act as an MCP hub for Claude Desktop and Claude Code.

## Features

- **Multi-backend LLM**: Claude (API + Agent SDK), Gemini, OpenAI,
  Mistral, local Qwen/Ollama. Switch per agent.
- **MCP servers** included: Outlook, Gmail, IMAP, Microsoft Graph,
  Billomat, Lexware, ecoDMS, Paperless-ngx, SEPA, PDF, Excel,
  Browser, Filesystem, Datastore, Telegram, UserEcho, Instagram,
  LinkedIn, Clipboard, Charts.
- **Agents and skills** defined as Markdown files; hot-reloadable.
- **Voice input** via Whisper (optional extra).
- **Knowledge base** loaded into agents on demand.
- **Scheduler and watchers** for hands-free automation.
- **Optional DSGVO/PII anonymization** via Microsoft Presidio
  (`pip install deskagent[anonymizer]`).
- **Plugin system** with a documented API and Plugin Exception in the
  license.

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
