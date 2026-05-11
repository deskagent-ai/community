#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Cowork Plugin Generator
========================
Generates a Cowork Plugin from DeskAgent agents and knowledge files.

Reads agents/*.md, converts them to Cowork commands (minimal transformation),
and maps knowledge/*.md to Cowork skills.

Usage:
    python generate_cowork_plugin.py
    python generate_cowork_plugin.py --agents-dir agents --user-agents-dir ../agents
    python generate_cowork_plugin.py --clean
"""

import argparse
import json
import re
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> tuple[dict | None, str]:
    """Parse JSON frontmatter from markdown content.

    Args:
        content: Full markdown file content.

    Returns:
        Tuple of (frontmatter_dict, body_without_frontmatter).
        If no frontmatter found, returns (None, original_content).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if not match:
        return None, content

    try:
        frontmatter = json.loads(match.group(1))
        body = match.group(2)
        return frontmatter, body
    except json.JSONDecodeError:
        return None, content


# ---------------------------------------------------------------------------
# Placeholder replacement
# ---------------------------------------------------------------------------

def resolve_procedures(body: str, procedure_dirs: list[Path]) -> str:
    """Replace {{PROCEDURE:name}} placeholders with procedure file content.

    Args:
        body: Markdown body text.
        procedure_dirs: List of directories to search for procedures (in order).

    Returns:
        Body with procedures inlined.
    """
    def _replace_procedure(m: re.Match) -> str:
        name = m.group(1)
        for proc_dir in procedure_dirs:
            proc_file = proc_dir / f"{name}.md"
            if proc_file.is_file():
                return proc_file.read_text(encoding="utf-8").strip()
        return f"<!-- Procedure '{name}' not found -->"

    return re.sub(r"\{\{PROCEDURE:(\w+)\}\}", _replace_procedure, body)


def transform_placeholders(body: str) -> str:
    """Replace DeskAgent-specific placeholders for Cowork context.

    Cowork commands run inside Claude Desktop/Cowork where:
    - Claude already knows the date (no need for {{TODAY}})
    - There are no DeskAgent path variables
    - Prefetch data must be fetched via MCP tools instead

    Args:
        body: Markdown body text (after frontmatter removal).

    Returns:
        Transformed body.
    """
    # Replace PREFETCH placeholders with instruction to fetch via tool
    body = re.sub(
        r"\{\{PREFETCH\.email\}\}",
        "(Use the appropriate email MCP tool to fetch the selected email first.)",
        body,
    )
    body = re.sub(
        r"\{\{PREFETCH\.emails\}\}",
        "(Use the appropriate email MCP tool to fetch the selected emails first.)",
        body,
    )
    body = re.sub(
        r"\{\{PREFETCH\.clipboard\}\}",
        "(Use clipboard_get_clipboard() to read the clipboard content first.)",
        body,
    )
    # Catch any remaining PREFETCH
    body = re.sub(
        r"\{\{PREFETCH\.\w+\}\}",
        "(Fetch the data using the appropriate MCP tool first.)",
        body,
    )

    # Remove date placeholders (Claude knows the date)
    body = re.sub(r"\{\{TODAY\}\}", "", body)
    body = re.sub(r"\{\{DATE\}\}", "", body)
    body = re.sub(r"\{\{DATE_ISO\}\}", "", body)
    body = re.sub(r"\{\{YEAR\}\}", "", body)

    # Remove path placeholders (not applicable in Cowork context)
    body = re.sub(r"\{\{EXPORTS_DIR\}\}", "exports/", body)
    body = re.sub(r"\{\{TEMP_DIR\}\}", ".temp/", body)
    body = re.sub(r"\{\{LOGS_DIR\}\}", ".logs/", body)
    body = re.sub(r"\{\{WORKSPACE_DIR\}\}", "workspace/", body)
    body = re.sub(r"\{\{KNOWLEDGE_DIR\}\}", "knowledge/", body)
    body = re.sub(r"\{\{CUSTOM_KNOWLEDGE_DIR\}\}", "knowledge/", body)
    body = re.sub(r"\{\{AGENTS_DIR\}\}", "agents/", body)
    body = re.sub(r"\{\{CONFIG_DIR\}\}", "config/", body)
    body = re.sub(r"\{\{PROJECT_DIR\}\}", "", body)
    body = re.sub(r"\{\{DESKAGENT_DIR\}\}", "deskagent/", body)

    # Remove username placeholder
    body = re.sub(r"\{\{USERNAME\}\}", "", body)

    # Remove INPUT placeholders (Cowork passes inputs differently)
    # Keep them as-is since Cowork commands may also support inputs
    # body = re.sub(r"\{\{INPUT\.\w+\}\}", "", body)

    # Clean up double blank lines that may result from removals
    body = re.sub(r"\n{3,}", "\n\n", body)

    return body


# ---------------------------------------------------------------------------
# Agent to Command conversion
# ---------------------------------------------------------------------------

def agent_name_to_kebab(filename: str) -> str:
    """Convert agent filename to kebab-case command name.

    Args:
        filename: Agent filename like 'reply_email.md' or 'daily_check.md'.

    Returns:
        Kebab-case name like 'reply-email' or 'daily-check'.
    """
    name = Path(filename).stem
    return name.replace("_", "-")


def convert_agent_to_command(
    agent_path: Path,
    procedure_dirs: list[Path],
) -> tuple[str, str] | None:
    """Convert a DeskAgent agent .md file to a Cowork command .md file.

    Args:
        agent_path: Path to the agent markdown file.
        procedure_dirs: Directories to search for procedures.

    Returns:
        Tuple of (command_filename, command_content) or None if agent should be skipped.
    """
    content = agent_path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(content)

    # Skip agents without frontmatter
    if frontmatter is None:
        return None

    # Skip disabled agents
    if frontmatter.get("enabled") is False:
        return None

    # Skip hidden agents (internal-only)
    if frontmatter.get("hidden") is True:
        return None

    # Resolve procedures first (before other placeholder transforms)
    body = resolve_procedures(body, procedure_dirs)

    # Transform placeholders
    body = transform_placeholders(body)

    # Build command filename
    command_name = agent_name_to_kebab(agent_path.name)
    command_filename = f"{command_name}.md"

    # The body already has the agent content without frontmatter
    command_content = body.strip() + "\n"

    return command_filename, command_content


# ---------------------------------------------------------------------------
# Knowledge to Skill conversion
# ---------------------------------------------------------------------------

def knowledge_to_skill_name(filename: str) -> str:
    """Convert knowledge filename to skill directory name.

    Args:
        filename: Knowledge filename like 'doc-products.md' or 'doc-mcp-tools.md'.

    Returns:
        Skill name like 'products' or 'mcp-tools'.
    """
    name = Path(filename).stem
    # Remove common prefixes
    for prefix in ("doc-", "doc_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def convert_knowledge_to_skill(knowledge_path: Path) -> tuple[str, str]:
    """Convert a knowledge .md file to a Cowork skill.

    Args:
        knowledge_path: Path to the knowledge markdown file.

    Returns:
        Tuple of (skill_name, skill_content).
    """
    content = knowledge_path.read_text(encoding="utf-8")
    skill_name = knowledge_to_skill_name(knowledge_path.name)
    return skill_name, content


# ---------------------------------------------------------------------------
# Agent Builder skill generation
# ---------------------------------------------------------------------------

def generate_agent_builder_skill(
    frontmatter_ref_path: Path,
    agents_dir: Path,
) -> str:
    """Generate the agent-development SKILL.md content.

    This skill teaches Claude how to create new DeskAgent agents.

    Args:
        frontmatter_ref_path: Path to doc-agent-frontmatter-reference.md.
        agents_dir: Path to agents directory (for reading example agents).

    Returns:
        Skill markdown content.
    """
    # Read frontmatter reference
    frontmatter_ref = ""
    if frontmatter_ref_path.is_file():
        frontmatter_ref = frontmatter_ref_path.read_text(encoding="utf-8")

    # Read example agents for compact examples
    examples = []
    example_files = ["reply_email.md", "daily_check.md", "create_offer.md"]
    for fname in example_files:
        fpath = agents_dir / fname
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            # Only include first ~40 lines for compactness
            lines = content.split("\n")
            truncated = "\n".join(lines[:40])
            if len(lines) > 40:
                truncated += "\n... (truncated)"
            examples.append((fname, truncated))

    # Build skill content
    skill = """# DeskAgent Agent Development

This skill teaches you how to create new DeskAgent agents.

DeskAgent agents are Markdown files with JSON frontmatter. They define automated workflows
that use MCP tools (Outlook, Billomat, Filesystem, etc.) to perform business tasks.

## How It Works

1. Agents live in the `agents/` directory as `.md` files
2. DeskAgent's discovery system automatically loads new agents on refresh
3. Each agent has JSON frontmatter (between `---` delimiters) for configuration
4. The markdown body contains the prompt/instructions for the AI

## Creating a New Agent

To create a new agent, write a `.md` file to the `agents/` directory using `fs_write_file()`.

### Minimal Example

```markdown
---
{
  "category": "kommunikation",
  "description": "Summarizes flagged emails",
  "icon": "summarize",
  "allowed_mcp": "outlook",
  "knowledge": "",
  "enabled": true
}
---

# Agent: Summarize Flagged Emails

1. Use `outlook_get_flagged_emails()` to fetch all flagged emails
2. For each email, extract the key points
3. Present a summary table with sender, subject, and key action items
```

### Important Frontmatter Fields

| Field | Description | Example |
|-------|-------------|---------|
| `category` | UI category | `"kommunikation"`, `"finance"`, `"sales"`, `"system"` |
| `description` | Short description (1 sentence) | `"Creates SEPA files from invoices"` |
| `icon` | Material Icon name | `"reply"`, `"receipt_long"`, `"payments"` |
| `ai` | AI backend | `"claude_sdk"` (default), `"gemini"`, `"openai"` |
| `allowed_mcp` | Allowed MCP servers (pipe-separated) | `"outlook\\|billomat\\|filesystem"` |
| `knowledge` | Knowledge pattern | `"company\\|products"`, `""` (none) |
| `tool_mode` | Security mode | `"full"` (default), `"read_only"`, `"write_safe"` |
| `prefetch` | Pre-load data | `["selected_email"]`, `["clipboard"]` |
| `enabled` | Active | `true` (default) |

### Available MCP Servers

| Server | Tools |
|--------|-------|
| `outlook` | Email (read, reply, move, flag), Calendar |
| `msgraph` | Microsoft Graph API (server-side email, calendar) |
| `gmail` | Gmail and Google Calendar |
| `billomat` | Customers, offers, invoices |
| `lexware` | Lexware Office API |
| `sepa` | SEPA XML payment files |
| `filesystem` | File read/write, PDF reading |
| `pdf` | PDF editing |
| `excel` | Excel read/write |
| `clipboard` | System clipboard |
| `paperless` | Paperless-ngx DMS |
| `ecodms` | ecoDMS archive |
| `userecho` | Support tickets |
| `browser` | Browser automation |
| `datastore` | SQLite data storage |
| `desk` | DeskAgent system control |

### Available Placeholders

Use these in agent prompts (replaced at runtime):

| Placeholder | Description |
|-------------|-------------|
| `{{TODAY}}` | Current date (DD.MM.YYYY) |
| `{{YEAR}}` | Current year |
| `{{EXPORTS_DIR}}` | Export directory |
| `{{TEMP_DIR}}` | Temp directory |
| `{{PREFETCH.email}}` | Pre-loaded email (with `prefetch: ["selected_email"]`) |
| `{{PREFETCH.clipboard}}` | Pre-loaded clipboard |
| `{{INPUT.name}}` | User input from pre-inputs dialog |
| `{{PROCEDURE:name}}` | Embedded procedure from `agents/procedures/` |

"""

    # Add frontmatter reference (condensed)
    if frontmatter_ref:
        skill += "## Full Frontmatter Reference\n\n"
        skill += "Below is the complete reference for all agent frontmatter options.\n\n"
        skill += frontmatter_ref
        skill += "\n\n"

    # Add example agents
    if examples:
        skill += "## Example Agents\n\n"
        for fname, content in examples:
            skill += f"### {fname}\n\n"
            skill += f"```markdown\n{content}\n```\n\n"

    return skill


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate_plugin(args: argparse.Namespace) -> None:
    """Generate the Cowork plugin from agents and knowledge.

    Args:
        args: Parsed command line arguments.
    """
    output_dir = Path(args.output_dir).resolve()
    commands_dir = output_dir / "commands"
    skills_dir = output_dir / "skills"

    # Resolve agent directories
    agents_dir = Path(args.agents_dir).resolve()
    user_agents_dir = Path(args.user_agents_dir).resolve() if args.user_agents_dir else None

    # Resolve knowledge directories
    knowledge_dir = Path(args.knowledge_dir).resolve()
    user_knowledge_dir = Path(args.user_knowledge_dir).resolve() if args.user_knowledge_dir else None

    # Resolve procedure directories (user first, then system)
    procedure_dirs: list[Path] = []
    if user_agents_dir:
        user_proc = user_agents_dir / "procedures"
        if user_proc.is_dir():
            procedure_dirs.append(user_proc)
    # Also check sibling of system agents dir
    parent_agents = agents_dir.parent.parent / "agents" / "procedures"
    if parent_agents.is_dir():
        procedure_dirs.append(parent_agents)
    system_proc = agents_dir / "procedures"
    if system_proc.is_dir():
        procedure_dirs.append(system_proc)

    # Clean output directories if requested
    if args.clean:
        if commands_dir.exists():
            shutil.rmtree(commands_dir)
            print(f"Cleaned: {commands_dir}")
        if skills_dir.exists():
            shutil.rmtree(skills_dir)
            print(f"Cleaned: {skills_dir}")

    commands_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Generate commands from agents
    # -----------------------------------------------------------------------
    print("\n--- Generating Commands ---")

    # Collect agents (system + user, user overrides system by filename)
    agent_files: dict[str, Path] = {}

    if agents_dir.is_dir():
        for f in sorted(agents_dir.glob("*.md")):
            agent_files[f.name] = f

    if user_agents_dir and user_agents_dir.is_dir():
        for f in sorted(user_agents_dir.glob("*.md")):
            agent_files[f.name] = f  # user overrides system

    commands_generated = 0
    commands_skipped = 0

    for filename, agent_path in sorted(agent_files.items()):
        result = convert_agent_to_command(agent_path, procedure_dirs)
        if result is None:
            commands_skipped += 1
            print(f"  SKIP: {filename}")
            continue

        command_filename, command_content = result
        command_path = commands_dir / command_filename
        command_path.write_text(command_content, encoding="utf-8")
        commands_generated += 1
        print(f"  OK:   {filename} -> commands/{command_filename}")

    print(f"\nCommands: {commands_generated} generated, {commands_skipped} skipped")

    # -----------------------------------------------------------------------
    # Generate skills from knowledge
    # -----------------------------------------------------------------------
    print("\n--- Generating Skills ---")

    # Collect knowledge files (system + user, user overrides)
    knowledge_files: dict[str, Path] = {}

    if knowledge_dir.is_dir():
        for f in sorted(knowledge_dir.glob("*.md")):
            knowledge_files[f.name] = f

    if user_knowledge_dir and user_knowledge_dir.is_dir():
        for f in sorted(user_knowledge_dir.glob("*.md")):
            knowledge_files[f.name] = f  # user overrides system

    skills_generated = 0

    for filename, knowledge_path in sorted(knowledge_files.items()):
        skill_name, skill_content = convert_knowledge_to_skill(knowledge_path)
        skill_dir = skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill_content, encoding="utf-8")
        skills_generated += 1
        print(f"  OK:   {filename} -> skills/{skill_name}/SKILL.md")

    print(f"\nSkills: {skills_generated} generated")

    # -----------------------------------------------------------------------
    # Generate agent-builder skill
    # -----------------------------------------------------------------------
    print("\n--- Generating Agent Builder Skill ---")

    frontmatter_ref_path = knowledge_dir / "doc-agent-frontmatter-reference.md"
    builder_content = generate_agent_builder_skill(frontmatter_ref_path, agents_dir)

    builder_dir = skills_dir / "agent-development"
    builder_dir.mkdir(parents=True, exist_ok=True)
    builder_path = builder_dir / "SKILL.md"
    builder_path.write_text(builder_content, encoding="utf-8")
    print(f"  OK:   skills/agent-development/SKILL.md")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Cowork Plugin generated at: {output_dir}")
    print(f"  Commands: {commands_generated}")
    print(f"  Skills:   {skills_generated + 1}")  # +1 for agent-builder
    print(f"{'='*50}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Cowork Plugin from DeskAgent agents and knowledge",
    )
    parser.add_argument(
        "--agents-dir",
        default="deskagent/agents",
        help="System agents directory (default: deskagent/agents)",
    )
    parser.add_argument(
        "--user-agents-dir",
        default=None,
        help="User agents directory (optional, overrides system agents)",
    )
    parser.add_argument(
        "--knowledge-dir",
        default="deskagent/knowledge",
        help="System knowledge directory (default: deskagent/knowledge)",
    )
    parser.add_argument(
        "--user-knowledge-dir",
        default=None,
        help="User knowledge directory (optional, overrides system knowledge)",
    )
    parser.add_argument(
        "--output-dir",
        default="deskagent/cowork-plugin",
        help="Output plugin directory (default: deskagent/cowork-plugin)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean commands/ and skills/ before generating",
    )

    args = parser.parse_args()
    generate_plugin(args)


if __name__ == "__main__":
    main()
