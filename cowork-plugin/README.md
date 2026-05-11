# DeskAgent - Cowork Plugin

Business productivity tools for Claude Desktop and Claude Cowork.

DeskAgent acts as an MCP Hub providing 15+ business tool servers through a single connection:
Outlook, Gmail, invoicing (Billomat/Lexware), DMS (Paperless/ecoDMS), SEPA payments, PDF, Excel, and more.

## Prerequisites

- **DeskAgent** must be installed and running on your machine
- Download from [deskagent.de](https://deskagent.de) or build from [source](https://github.com/realvirtual/deskagent)
- The MCP Hub must be enabled (Settings > Claude Integration > Enable MCP Hub)

## Setup

### Option 1: Automatic (recommended)

Use the DeskAgent setup tool from within Claude:

```
Use the desk_setup_claude_desktop tool to configure the connection.
```

This will automatically configure the auth token and connection settings.

### Option 2: Manual

1. Open DeskAgent Settings > Claude Integration
2. Copy the Auth Token
3. Replace `<configure-your-auth-token>` in `.mcp.json` with your token

## Available Commands

Commands are generated from DeskAgent agents. Use them as slash commands:

| Command | Description |
|---------|-------------|
| `/reply-email` | Draft professional email replies |
| `/create-offer` | Create offers from contact data |
| `/daily-check` | Daily overview: calendar, invoices, follow-ups |
| `/invoices-to-sepa` | Create SEPA payment files from invoices |
| `/mailsort` | Sort and categorize emails |
| ... | See `commands/` folder for all available commands |

## Available Skills

Skills provide domain knowledge that Claude uses automatically:

| Skill | Description |
|-------|-------------|
| `agent-development` | How to create new DeskAgent agents |
| `mcp-tools` | Reference for all available MCP tools |
| ... | See `skills/` folder for all available skills |

## MCP Tools

All DeskAgent MCP tools are available through the hub connection:

- **Outlook/Gmail**: Read, reply, move, flag emails; calendar events
- **Billomat/Lexware**: Customers, offers, invoices
- **SEPA**: Create payment XML files
- **Filesystem**: Read/write files, PDF processing
- **Paperless/ecoDMS**: Document management
- **Excel**: Read and write spreadsheets
- **Clipboard**: System clipboard access
- **Browser**: Web automation

## Creating New Agents

Claude can create new DeskAgent agents directly. Ask Claude:

> "Create a DeskAgent agent that checks for unpaid invoices every Friday"

Claude knows the agent format (via the `agent-development` skill) and can write `.md` files
to your `agents/` folder using the filesystem MCP tools.

## License

AGPL-3.0 - See [LICENSE](https://github.com/realvirtual/deskagent/blob/main/LICENSE)
