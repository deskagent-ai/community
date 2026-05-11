# DeskAgent Developer Documentation

This document provides an overview of all technical documentation and serves as a navigation guide.

## Documentation Index

### Core Architecture

| Document | Description |
|----------|-------------|
| [doc-folder-structure.md](doc-folder-structure.md) | Directory layout, paths.py, DESKAGENT_DIR vs SHARED_DIR vs WORKSPACE_DIR |
| [doc-startup-and-directories.md](doc-startup-and-directories.md) | CLI parameters, multi-instance setup, port configuration |
| [doc-config-reference.md](doc-config-reference.md) | Configuration files: system.json, backends.json, apis.json |

### Agent Development

| Document | Description |
|----------|-------------|
| [doc-creating-agents.md](doc-creating-agents.md) | Complete guide for creating agents from simple to complex workflows |
| [doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md) | All frontmatter options: ai, allowed_mcp, knowledge, inputs, voice_hotkey, etc. |
| [doc-knowledge-system.md](doc-knowledge-system.md) | How knowledge files are loaded, pattern matching, system prompt structure |
| [doc-prompt-optimization-guide.md](doc-prompt-optimization-guide.md) | Analyzing prompt_latest.txt, reducing token usage, optimization tips |

### MCP (Model Context Protocol)

| Document | Description |
|----------|-------------|
| [doc-mcp-tools.md](doc-mcp-tools.md) | Reference for all MCP tools: outlook, billomat, filesystem, pdf, etc. |
| [doc-creating-mcp-servers.md](doc-creating-mcp-servers.md) | How to create custom MCP servers, templates, HIGH_RISK_TOOLS |

### UI & Sessions

| Document | Description |
|----------|-------------|
| [doc-ui-agent-lifecycle.md](doc-ui-agent-lifecycle.md) | Task vs Session, UI components, agent execution flow |
| [doc-session-management.md](doc-session-management.md) | Session lifecycle, SQLite storage, reactivation, multi-turn conversations |
| [doc-quick-access.md](doc-quick-access.md) | Quick Access overlay window, running states, dialog auto-open |

### Extensibility

| Document | Description |
|----------|-------------|
| [doc-pluginsystem.md](doc-pluginsystem.md) | Plugin structure, plugin.json manifest, namespace prefixes |

---

## Additional Documentation (docs/)

Located in `docs/` folder for development-specific topics:

| Document | Description |
|----------|-------------|
| [doc-build-distribution.md](../docs/doc-build-distribution.md) | Nuitka build, hybrid architecture, distribution structure |
| [doc-release-process.md](../docs/doc-release-process.md) | Version management, build scripts, Firebase deployment |
| [doc-quality-issues.md](../docs/doc-quality-issues.md) | Known issues, race conditions, memory leaks, planned fixes |

---

## Quick Navigation by Task

### "I want to create a new agent"
1. Start with [doc-creating-agents.md](doc-creating-agents.md)
2. Reference [doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md) for all options
3. Check [doc-mcp-tools.md](doc-mcp-tools.md) for available tools

### "I want to add a new MCP server"
1. Read [doc-creating-mcp-servers.md](doc-creating-mcp-servers.md)
2. Check existing servers in `deskagent/mcp/` for examples

### "I want to understand the UI"
1. [doc-ui-agent-lifecycle.md](doc-ui-agent-lifecycle.md) for component terminology
2. [doc-session-management.md](doc-session-management.md) for persistence
3. [doc-quick-access.md](doc-quick-access.md) for the overlay window

### "I want to configure DeskAgent"
1. [doc-config-reference.md](doc-config-reference.md) for all settings
2. [doc-folder-structure.md](doc-folder-structure.md) for where files go
3. [doc-startup-and-directories.md](doc-startup-and-directories.md) for CLI options

### "I want to build/release"
1. [doc-build-distribution.md](../docs/doc-build-distribution.md) for build process
2. [doc-release-process.md](../docs/doc-release-process.md) for versioning and deployment
