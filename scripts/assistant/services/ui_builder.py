# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""UI tile and theme generation for DeskAgent web interface.

Extracted from routes/ui.py to decouple UI building logic from HTTP routes.
This module handles:
- Icon mapping and resolution
- Icon placeholder rendering (:icon_name: syntax)
- Tile HTML generation (skills, agents, chats)
- Style building for tiles
- Main web UI HTML generation
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

# Path is set up by assistant/__init__.py
from paths import (
    get_state_dir,
    get_all_skills_with_source,
    get_all_agents_with_source,
    get_content_mode,
)

from ..skills import load_skill, load_config
# Note: load_agent imported lazily in functions to avoid circular import
from .discovery import get_agent_config, get_skill_config, load_categories, check_agent_prerequisites
from .mcp_hints import get_mcp_hint

# Import i18n functions
try:
    from config import load_translations, get_localized
except ImportError:
    from config import load_translations, get_localized


def _load_agent(agent_name: str):
    """Lazy wrapper for agents.load_agent to avoid circular import."""
    from ..agents import load_agent
    return load_agent(agent_name)


def _load_ui_preferences() -> dict:
    """Load UI preferences directly to avoid circular imports with routes.system."""
    prefs_file = get_state_dir() / "preferences.json"
    if prefs_file.exists():
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

# Import workflow manager (fallback for different run contexts)
workflow_manager = None
try:
    from workflows import manager as workflow_manager
except ImportError:
    try:
        from scripts.workflows import manager as workflow_manager
    except ImportError as e:
        # Log import error - workflows tile won't show but app runs
        try:
            from ai_agent import system_log
            system_log(f"[UIBuilder] Could not import workflows: {e}")
        except Exception:
            pass

def get_templates_dir() -> Path:
    """Get templates directory - evaluated at runtime to support --shared-dir reload."""
    import paths
    return paths.DESKAGENT_DIR / "scripts" / "templates"


# =============================================================================
# Simple Mode Helper
# =============================================================================

def _get_simple_mode_preference() -> bool:
    """Get simple mode preference from workspace/.state/preferences.json.

    Returns:
        True if simple mode is enabled, False otherwise (default)
    """
    prefs_file = get_state_dir() / "preferences.json"
    if prefs_file.exists():
        try:
            import json as json_module
            with open(prefs_file, "r", encoding="utf-8") as f:
                prefs = json_module.load(f)
                return prefs.get("ui", {}).get("simple_mode", False)
        except Exception:
            pass
    return False


def _get_effective_anonymization(task_meta: dict, backend_config: dict, config: dict = None) -> bool:
    """Get effective anonymization status for UI display.

    Uses the central anonymization decision logic.

    Priority:
    1. Agent-Frontmatter explicitly false -> OFF
    2. Agent-Frontmatter explicitly true + global enabled -> ON
    3. Global UI-Setting disabled -> OFF
    4. Backend-Default (backends.json)

    Args:
        task_meta: Agent or skill config from discovery
        backend_config: AI backend config from backends.json
        config: Full config (optional, will be loaded if not provided)

    Returns:
        True if anonymization is active
    """
    # Load config if not provided
    if config is None:
        config = load_config()

    # Use central decision function
    try:
        from ai_agent.anonymizer import resolve_anonymization_setting
        result, _source = resolve_anonymization_setting(
            config, backend_config, task_meta, "", "", ""
        )
        return result
    except ImportError:
        # Fallback to simple logic if import fails
        # Task-level explicit override (highest priority)
        if "anonymize" in task_meta:
            return task_meta["anonymize"]
        if "use_anonymization_proxy" in task_meta:
            return task_meta["use_anonymization_proxy"]

        # Backend default
        return backend_config.get("anonymize", False)


# =============================================================================
# Icon Mapping
# =============================================================================

# Material Icons mapping for automatic icon selection
ICON_MAP = {
    # Skills
    "mail_reply": "reply",
    "mail_reply_api": "reply_all",
    "mail_friendly": "sentiment_satisfied",
    "summarize": "summarize",
    "translate": "translate",
    "grammar": "spellcheck",
    "linkedin": "share",
    "billomat_customer": "person_add",
    # Agents
    "reply_email": "forward_to_inbox",
    "reply_email_api": "markunread",
    "reply_email_ollama": "drafts",
    "create_offer": "request_quote",
    "create_invoice": "receipt_long",
    "add_knowledge": "library_add",
    "daily_check": "checklist",
    # Defaults
    "skill_default": "auto_fix_high",
    "agent_default": "smart_toy"
}


def get_icon(item_id: str, meta: dict, is_agent: bool = False) -> str:
    """Get Material Icon name from config or auto-mapping.

    Args:
        item_id: The skill or agent ID
        meta: Metadata dict that may contain an 'icon' key
        is_agent: Whether this is an agent (affects default icon)

    Returns:
        Material icon name string
    """
    if meta.get("icon"):
        return meta["icon"]
    if item_id in ICON_MAP:
        return ICON_MAP[item_id]
    return ICON_MAP["agent_default"] if is_agent else ICON_MAP["skill_default"]


def render_icon_placeholders(text: str, for_tooltip: bool = False) -> str:
    """Render :icon_name: placeholders as Material Icons.

    Supports the :icon_name: syntax (like Slack/Discord) where icon_name
    is a valid Material Icon name (e.g., :mail:, :edit_note:, :receipt:).

    Args:
        text: Text containing :icon_name: placeholders
        for_tooltip: If True, removes icons entirely (tooltips can't render HTML)

    Returns:
        Text with placeholders replaced by Material Icon HTML spans,
        or plain text without icons if for_tooltip=True

    Example:
        render_icon_placeholders(":mail: E-Mail")
        # Returns: '<span class="material-icons io-icon">mail</span> E-Mail'

        render_icon_placeholders(":mail: E-Mail", for_tooltip=True)
        # Returns: 'E-Mail'
    """
    if not text:
        return text

    def replace_icon(match):
        if for_tooltip:
            return ""  # Remove icon for tooltips
        icon_name = match.group(1)
        return f'<span class="material-icons io-icon">{icon_name}</span>'

    # Replace :word: patterns (underscores allowed for icons like edit_note)
    result = re.sub(r':(\w+):', replace_icon, text)

    # Clean up extra spaces from removed icons
    if for_tooltip:
        result = re.sub(r'\s+', ' ', result).strip()

    return result


# =============================================================================
# Tile Building
# =============================================================================

def build_tile_style(meta: dict, is_agent: bool, ui_config: dict) -> str:
    """Build inline style from meta color settings.

    Args:
        meta: Skill/agent metadata with optional color settings
        is_agent: Whether this is an agent (affects default colors)
        ui_config: UI configuration with default colors

    Returns:
        CSS inline style string
    """
    default_skill_color = ui_config.get("skill_color", "")
    default_skill_text = ui_config.get("skill_text", "")
    default_agent_color = ui_config.get("agent_color", "")
    default_agent_text = ui_config.get("agent_text", "")
    default_agent_border = ui_config.get("agent_border", "")

    styles = []
    if is_agent:
        if meta.get("color") or default_agent_color:
            styles.append(f"background: {meta.get('color', default_agent_color)}")
        if meta.get("text_color") or default_agent_text:
            styles.append(f"color: {meta.get('text_color', default_agent_text)}")
        if meta.get("border_color") or default_agent_border:
            styles.append(f"border-color: {meta.get('border_color', default_agent_border)}")
    else:
        if meta.get("color") or default_skill_color:
            styles.append(f"background: {meta.get('color', default_skill_color)}")
        if meta.get("text_color") or default_skill_text:
            styles.append(f"color: {meta.get('text_color', default_skill_text)}")
    return "; ".join(styles) if styles else ""


def build_tile(item: dict, tile_type: str) -> str:
    """Build HTML for a skill or agent tile.

    Args:
        item: Tile data dict with id, name, icon, style, etc.
        tile_type: Either "skill" or "agent"

    Returns:
        HTML string for the tile
    """
    style_attr = f' style="{item["style"]}"' if item["style"] else ""
    hotkey_html = f'<span class="tile-hotkey">{item["hotkey"]}</span>' if item["hotkey"] else ""

    # Prerequisites check (MCPs + backend)
    prereq_ready = item.get("prereq_ready", True)
    prereq_missing = item.get("prereq_missing", [])
    prereq_missing_backend = item.get("prereq_missing_backend")
    prereq_fallback_backend = item.get("prereq_fallback_backend")

    # Check for special actions
    action = item.get("action", "")
    if action == "open_chat":
        # Chat agents use openChat() and get chat styling
        onclick = f"openChat('{item['id']}', '{item['ai_backend']}')"
        tile_type = "chat"  # Apply chat CSS class
    elif tile_type == "skill":
        onclick = f"runSkill(this, event, '{item['id']}')"
    elif not prereq_ready and (prereq_missing or prereq_missing_backend):
        # Show prerequisites dialog instead of running agent
        onclick = f"showPrerequisiteWarning('{item['id']}')"
    else:
        onclick = f"runAgent(this, event, '{item['id']}')"

    # Build tooltip (strip icon placeholders since tooltips can't render HTML)
    desc = item.get("description", "")
    source = item.get("source", "user")
    overrides_standard = item.get("overrides_standard", False)
    desc_line = f'{desc}&#10;&#10;' if desc else ""
    is_standard = source == "standard"
    path_prefix = "deskagent/" if is_standard else ""
    file_path = f'{path_prefix}{tile_type}s/{item["id"]}.md'
    source_info = ""  # No suffix for standard agents
    override_info = " [überschreibt Standard]" if overrides_standard else ""
    input_text = render_icon_placeholders(item["input"], for_tooltip=True)
    output_text = render_icon_placeholders(item["output"], for_tooltip=True)
    # Show allowed MCP servers (or "Alle" if not restricted)
    allowed_mcp = item.get("allowed_mcp", "")
    tools_info = allowed_mcp if allowed_mcp else "Alle"
    # Show config sources chain (e.g., "deskagent/config → config/ → Frontmatter")
    config_sources = item.get("config_sources", [])
    config_info = " → ".join(config_sources) if config_sources else "nur .md"
    # Show anonymization status
    use_anon = item.get("use_anonymization", False)
    anon_info = "Aktiv" if use_anon else "Aus"

    # Build prerequisites info for tooltip
    prereq_tooltip = ""
    if not prereq_ready and (prereq_missing or prereq_missing_backend):
        prereq_lines = ["&#10;⚠️ Setup erforderlich:"]
        # Missing backend
        if prereq_missing_backend:
            prereq_lines.append(f"  • AI Backend '{prereq_missing_backend}' nicht konfiguriert")
        # Missing MCPs
        for mcp_name in prereq_missing:
            hint = get_mcp_hint(mcp_name)
            if hint:
                prereq_lines.append(f"  • {hint['name']}: {hint.get('requirement', 'Konfiguration fehlt')}")
            else:
                prereq_lines.append(f"  • {mcp_name}: Konfiguration fehlt")
        prereq_tooltip = "&#10;".join(prereq_lines)

    tooltip = f'{desc_line}{input_text} → {output_text}&#10;&#10;📄 {file_path}{source_info}{override_info}&#10;🤖 AI: {item["ai_backend"]} ({item["ai_model"]})&#10;🔧 Tools: {tools_info}&#10;🔐 Anonymisierung: {anon_info}&#10;⚙️ Config: {config_info}{prereq_tooltip}'

    # Badge HTML - can have multiple badges
    # Standard badge: top right (for standard agents)
    # New/Override badge: top left (mutually exclusive)
    # Prereq badge: bottom left (independent, always shown if needed)
    is_new = item.get("is_new", False)

    # Standard badge (always shown for standard agents, positioned on right)
    standard_badge_html = '<span class="tile-badge demo-badge">Standard</span>' if is_standard else ""

    # Top-left badge (mutually exclusive: new > override)
    top_left_badge_html = ""
    if is_new:
        top_left_badge_html = '<span class="new-badge">New</span>'
    elif overrides_standard:
        top_left_badge_html = '<span class="tile-badge override-badge">Override</span>'

    # Bottom-left badge (prerequisites - independent, always shown if needed)
    prereq_badge_html = ""
    if not prereq_ready and (prereq_missing or prereq_missing_backend):
        missing_items = []
        if prereq_missing_backend:
            missing_items.append(f"Backend: {prereq_missing_backend}")
        missing_items.extend(prereq_missing)
        missing_list = ", ".join(missing_items)
        prereq_badge_html = f'<span class="tile-badge prereq-badge" title="Setup erforderlich: {missing_list}">⚠ Setup</span>'

    # Combine badges
    badge_html = top_left_badge_html + prereq_badge_html + standard_badge_html

    # Input badge for agents with pre-inputs
    input_badge_html = ""
    if tile_type == "agent" and item.get("has_inputs"):
        input_badge_html = '<span class="material-icons input-badge">upload_file</span>'

    # Supervisor badge for agents that can orchestrate other agents (use deskagent MCP)
    supervisor_badge_html = ""
    if tile_type == "agent" and item.get("is_supervisor"):
        supervisor_badge_html = '<span class="material-icons supervisor-badge" title="Supervisor Agent">hub</span>'

    # Category attribute
    category = item.get("category", "")
    category_attr = f' data-category="{category}"' if category else ""

    # Fallback backend attribute (for showing warning toast when agent starts)
    fallback_attr = f' data-fallback-backend="{prereq_fallback_backend}"' if prereq_fallback_backend else ""

    # Hidden attribute (for tiles marked as hidden in config)
    hidden_attr = ' data-hidden="true"' if item.get("is_hidden") else ""

    # Tile ID for running-badge updates
    tile_id = f'tile-{item["id"]}'

    # Menu button for agents only (skills don't have context menu)
    menu_btn_html = ""
    if tile_type == "agent":
        menu_btn_html = f'''<button class="tile-menu-btn" onclick="event.stopPropagation(); showAgentContextMenu(event, this.parentElement, '{item["id"]}')" title="Optionen">
            <span class="material-icons">more_vert</span>
        </button>'''

    return f'''<div class="tile {tile_type}" id="{tile_id}" onclick="{onclick}" title="{tooltip}"{style_attr}{category_attr}{fallback_attr}{hidden_attr}>
        <span class="material-icons tile-icon">{item["icon"]}</span>
        <span class="tile-name">{item["name"]}</span>
        {hotkey_html}
        {badge_html}
        {input_badge_html}
        {supervisor_badge_html}
        {menu_btn_html}
    </div>'''


def build_chat_tile(chat: dict) -> str:
    """Build HTML for a chat tile.

    Args:
        chat: Chat configuration dict with id, name, backend, etc.

    Returns:
        HTML string for the chat tile
    """
    tile_id = f'tile-{chat["id"]}'
    tooltip = f'{chat["description"]}&#10;&#10;🤖 Backend: {chat["backend"]}&#10;📊 Model: {chat["model"]}'
    return f'''<div class="tile chat" id="{tile_id}" onclick="openChat('{chat['id']}', '{chat['backend']}')" title="{tooltip}">
        <span class="material-icons tile-icon">{chat["icon"]}</span>
        <span class="tile-name">{chat["name"]}</span>
    </div>'''


# =============================================================================
# Main UI Builder
# =============================================================================

def _get_dev_tabs_html() -> tuple:
    """Generate developer mode tabs and content HTML.

    Returns:
        Tuple of (dev_tabs, dev_tab_content, settings_dev_tabs, settings_dev_tab_content)
    """
    # Developer Tabs (Tests, Logs with Prompt sub-tab)
    # Only ONE location: Settings Dialog. System Panel has no dev tabs.
    settings_dev_tabs = '''
        <button class="settings-tab" onclick="switchSettingsTab('tests')" id="settingsTabTests">
            <span class="material-icons">science</span> Tests
        </button>
        <button class="settings-tab" onclick="switchSettingsTab('logs')" id="settingsTabLogs">
            <span class="material-icons">article</span> Logs
        </button>
    '''

    settings_dev_tab_content = '''
        <!-- Tests Tab -->
        <div class="settings-tab-content hidden" id="settingsContentTests">
            <div class="test-controls">
                <button class="settings-btn" onclick="runTests('unit')" id="btnUnit">
                    <span class="material-icons">check_circle</span> Unit Tests
                </button>
                <button class="settings-btn" onclick="runTests('integration')" id="btnIntegration">
                    <span class="material-icons">api</span> Integration
                </button>
                <button class="settings-btn primary" onclick="runTests('all')" id="btnAll">
                    <span class="material-icons">select_all</span> All Tests
                </button>
            </div>
            <div class="test-status" id="testStatus"></div>
            <div class="test-progress hidden" id="testProgress">
                <div class="progress-bar"><div class="progress-fill" id="testProgressFill"></div></div>
                <span id="testProgressText">Running...</span>
            </div>
            <div class="test-results" id="testResults">
                <div class="test-summary hidden" id="testSummary">
                    <span class="passed" id="testPassed">0 passed</span>
                    <span class="failed" id="testFailed">0 failed</span>
                    <span class="skipped" id="testSkipped">0 skipped</span>
                    <span class="duration" id="testDuration">0s</span>
                </div>
                <pre class="test-output" id="testOutput"></pre>
            </div>
        </div>
        <!-- Logs Tab - Sub-Tabs Layout (includes Prompt) -->
        <div class="settings-tab-content hidden" id="settingsContentLogs">
            <div class="logs-subtabs-container">
                <div class="logs-subtabs">
                    <button class="logs-subtab active" onclick="switchLogsSubTab('system')" id="logsSubtabSystem">
                        <span class="material-icons">terminal</span> System
                    </button>
                    <button class="logs-subtab" onclick="switchLogsSubTab('agent')" id="logsSubtabAgent">
                        <span class="material-icons">smart_toy</span> Agent
                    </button>
                    <button class="logs-subtab" onclick="switchLogsSubTab('anon')" id="logsSubtabAnon">
                        <span class="material-icons">security</span> Anonymization
                    </button>
                    <button class="logs-subtab" onclick="switchLogsSubTab('context')" id="logsSubtabContext">
                        <span class="material-icons">code</span> Prompt
                    </button>
                    <button class="settings-btn-small logs-refresh-btn" onclick="refreshLogs()" title="Refresh">
                        <span class="material-icons">refresh</span>
                    </button>
                </div>
                <div class="logs-subtab-content" id="logsContentSystem">
                    <pre class="logs-output" id="logsSystemOutput">Loading...</pre>
                </div>
                <div class="logs-subtab-content hidden" id="logsContentAgent">
                    <pre class="logs-output" id="logsAgentOutput">Loading...</pre>
                </div>
                <div class="logs-subtab-content hidden" id="logsContentAnon">
                    <pre class="logs-output" id="logsAnonOutput">Loading...</pre>
                </div>
                <div class="logs-subtab-content hidden" id="logsContentContext">
                    <div class="context-info">
                        <div class="context-stats" id="contextStats">
                            <span class="context-stat"><strong>System:</strong> <span id="ctxSystemTokens">-</span></span>
                            <span class="context-stat"><strong>User:</strong> <span id="ctxUserTokens">-</span></span>
                            <span class="context-stat"><strong>Tools:</strong> <span id="ctxToolTokens">-</span></span>
                            <span class="context-stat"><strong>Total:</strong> <span id="ctxTotalTokens">-</span></span>
                        </div>
                    </div>
                    <div class="context-sections">
                        <details class="context-section" open>
                            <summary><span class="material-icons">settings</span> System Prompt</summary>
                            <pre class="context-content" id="ctxSystemPrompt">Run an agent to capture context.</pre>
                        </details>
                        <details class="context-section" open>
                            <summary><span class="material-icons">person</span> User Prompt</summary>
                            <pre class="context-content" id="ctxUserPrompt">-</pre>
                        </details>
                        <details class="context-section" id="ctxAnonymizationSection" style="display: none;">
                            <summary><span class="material-icons">security</span> Anonymization <span id="ctxAnonymizationCount" class="context-badge">0</span></summary>
                            <div class="context-content" id="ctxAnonymization" style="font-family: monospace; font-size: 12px;">-</div>
                        </details>
                    </div>
                </div>
            </div>
        </div>
    '''

    # System Panel has no developer tabs (all dev features are in Settings Dialog)
    dev_tabs = ''
    dev_tab_content = ''

    return (dev_tabs, dev_tab_content, settings_dev_tabs, settings_dev_tab_content)


def _build_skill_list(config: dict) -> List[dict]:
    """Build list of skill data for tile generation.

    Args:
        config: Full application config

    Returns:
        List of skill dicts with tile data
    """
    # Use discovery service for merged config (frontmatter + agents.json skills section)
    ui_config = config.get("ui", {})
    ai_backends = config.get("ai_backends", {})
    default_ai = config.get("default_ai", "claude")
    language = config.get("language", "de")

    skills = []
    for skill_info in get_all_skills_with_source():
        skill_name = skill_info["name"]
        source = skill_info["source"]
        overrides_standard = skill_info.get("overrides_standard", False)
        # Use discovery service to get merged config (frontmatter has priority)
        meta = get_skill_config(skill_name)
        if not meta:
            meta = {"input": "📋 Clipboard", "output": "📋 Clipboard"}
        if not meta.get("enabled", True) or meta.get("hide_ui", False) or meta.get("hidden", False):
            continue
        skill = load_skill(skill_name)
        ai_backend = meta.get("ai", default_ai)
        ai_config = ai_backends.get(ai_backend, {})
        ai_model = ai_config.get("model", ai_config.get("type", "unknown"))
        skills.append({
            "id": skill_name,
            "name": skill["name"] if skill else skill_name,
            "description": get_localized(meta, "description", language) or meta.get("description", ""),
            "input": get_localized(meta, "input", language) or meta.get("input", "📋 Clipboard"),
            "output": get_localized(meta, "output", language) or meta.get("output", "📋 Clipboard"),
            "icon": get_icon(skill_name, meta, is_agent=False),
            "hotkey": meta.get("hotkey", ""),
            "order": meta.get("order", 999),
            "ai_backend": ai_backend,
            "ai_model": ai_model,
            "style": build_tile_style(meta, is_agent=False, ui_config=ui_config),
            "source": source,
            "overrides_standard": overrides_standard,
            "is_new": meta.get("_is_new", False),
            "category": meta.get("category", ""),
            "allowed_mcp": meta.get("allowed_mcp", ""),
            "config_sources": meta.get("_config_sources", []),
            "use_anonymization": _get_effective_anonymization(meta, ai_config)
        })
    return skills


def _build_agent_list(config: dict) -> List[dict]:
    """Build list of agent data for tile generation.

    Supports two types of agent definitions:
    1. Direct: agents.json entry matches .md filename (e.g., "daily_check" -> daily_check.md)
    2. Alias: agents.json entry has "agent" field pointing to another .md file
       (e.g., "daily_check_office365" with "agent": "daily_check" uses daily_check.md)

    Args:
        config: Full application config

    Returns:
        List of agent dicts with tile data
    """
    # Use discovery service for merged config (frontmatter + agents.json)
    ui_config = config.get("ui", {})
    ai_backends = config.get("ai_backends", {})
    default_ai = config.get("default_ai", "claude")
    language = config.get("language", "de")

    agents = []
    seen_ids = set()  # Track which agent IDs we've added

    # 1. First pass: Add agents from .md files (direct mapping)
    for agent_info in get_all_agents_with_source():
        agent_name = agent_info["name"]
        source = agent_info["source"]
        overrides_standard = agent_info.get("overrides_standard", False)
        # Use discovery service to get merged config (frontmatter has priority)
        meta = get_agent_config(agent_name)
        if not meta:
            meta = {"input": "🔧 MCP Tools", "output": "✅ Aktion"}
        if not meta.get("enabled", True) or meta.get("hide_ui", False):
            continue
        is_hidden = meta.get("hidden", False)
        agent = _load_agent(agent_name)
        has_inputs = bool(agent and agent.get("input_config"))
        ai_backend = meta.get("ai", default_ai)
        ai_config = ai_backends.get(ai_backend, {})
        ai_model = ai_config.get("model", ai_config.get("type", "unknown"))
        # Check if this is a supervisor agent (uses deskagent MCP to orchestrate other agents)
        allowed_mcp = meta.get("allowed_mcp") or ""
        is_supervisor = "deskagent" in allowed_mcp
        # Check prerequisites (MCP configuration + backend availability)
        prereq_status = check_agent_prerequisites(meta, ai_backends)
        agents.append({
            "id": agent_name,
            "name": meta.get("name", agent["name"] if agent else agent_name),
            "description": get_localized(meta, "description", language) or meta.get("description", ""),
            "input": get_localized(meta, "input", language) or meta.get("input", "🔧 MCP Tools"),
            "output": get_localized(meta, "output", language) or meta.get("output", "✅ Aktion"),
            "icon": get_icon(agent_name, meta, is_agent=True),
            "hotkey": meta.get("hotkey", ""),
            "order": meta.get("order", 999),
            "ai_backend": ai_backend,
            "ai_model": ai_model,
            "style": build_tile_style(meta, is_agent=True, ui_config=ui_config),
            "source": source,
            "overrides_standard": overrides_standard,
            "has_inputs": has_inputs,
            "is_supervisor": is_supervisor,
            "is_new": meta.get("_is_new", False),
            "category": meta.get("category", ""),
            "action": meta.get("action", ""),
            "allowed_mcp": allowed_mcp,
            "config_sources": meta.get("_config_sources", []),
            "use_anonymization": _get_effective_anonymization(meta, ai_config),
            "prereq_ready": prereq_status["ready"],
            "prereq_missing": prereq_status["missing_mcps"],
            "prereq_missing_backend": prereq_status.get("missing_backend"),
            "prereq_fallback_backend": prereq_status.get("fallback_backend"),
            "is_hidden": is_hidden
        })
        seen_ids.add(agent_name)

    # 2. Second pass: Add alias agents (entries with "agent" field referencing another .md)
    # These are defined in agents.json only (no .md file), so use legacy config
    AGENT_META = config.get("agents", {})
    for config_name, meta in AGENT_META.items():
        # Skip if already added, disabled, or hidden from UI
        if config_name in seen_ids:
            continue
        if not meta.get("enabled", True) or meta.get("hide_ui", False):
            continue
        is_hidden = meta.get("hidden", False)

        # Check if this is an alias (has "agent" field pointing to another agent)
        referenced_agent = meta.get("agent")
        if not referenced_agent:
            continue  # Not an alias, skip (might be orphan config without .md)

        # Load the referenced agent's .md file
        agent = _load_agent(referenced_agent)
        if not agent:
            continue  # Referenced agent doesn't exist

        has_inputs = bool(agent.get("input_config"))
        ai_backend = meta.get("ai", default_ai)
        ai_config = ai_backends.get(ai_backend, {})
        ai_model = ai_config.get("model", ai_config.get("type", "unknown"))
        # Check if this is a supervisor agent
        allowed_mcp = meta.get("allowed_mcp") or ""
        is_supervisor = "deskagent" in allowed_mcp
        # Check prerequisites (MCP configuration + backend availability)
        prereq_status = check_agent_prerequisites(meta, ai_backends)

        agents.append({
            "id": config_name,  # Use config key as ID
            "name": meta.get("name", agent.get("name", config_name)),
            "description": get_localized(meta, "description", language) or meta.get("description", ""),
            "input": get_localized(meta, "input", language) or meta.get("input", "🔧 MCP Tools"),
            "output": get_localized(meta, "output", language) or meta.get("output", "✅ Aktion"),
            "icon": get_icon(config_name, meta, is_agent=True),
            "hotkey": meta.get("hotkey", ""),
            "order": meta.get("order", 999),
            "ai_backend": ai_backend,
            "ai_model": ai_model,
            "style": build_tile_style(meta, is_agent=True, ui_config=ui_config),
            "source": "standard",  # Alias configs are typically standard
            "overrides_standard": False,
            "has_inputs": has_inputs,
            "is_supervisor": is_supervisor,
            "category": meta.get("category", ""),
            "action": meta.get("action", ""),
            "agent_ref": referenced_agent,  # Store reference for tooltip
            "allowed_mcp": allowed_mcp,
            "config_sources": ["agents.json (alias)"],  # Alias agents come from JSON only
            "use_anonymization": _get_effective_anonymization(meta, ai_config),
            "prereq_ready": prereq_status["ready"],
            "prereq_missing": prereq_status["missing_mcps"],
            "prereq_missing_backend": prereq_status.get("missing_backend"),
            "prereq_fallback_backend": prereq_status.get("fallback_backend"),
            "is_hidden": is_hidden
        })
        seen_ids.add(config_name)

    return agents


def _build_chat_list(config: dict) -> List[dict]:
    """Build list of chat data for tile generation.

    Args:
        config: Full application config

    Returns:
        List of chat dicts with tile data
    """
    ai_backends = config.get("ai_backends", {})
    default_ai = config.get("default_ai", "claude")

    chats = []
    CHAT_META = config.get("chats", {})
    for chat_id, meta in CHAT_META.items():
        if not meta.get("enabled", True) or meta.get("hide_ui", False):
            continue
        backend = meta.get("backend", default_ai)
        ai_config = ai_backends.get(backend, {})
        ai_model = ai_config.get("model", ai_config.get("type", "unknown"))
        chats.append({
            "id": chat_id,
            "name": meta.get("name", chat_id),
            "description": meta.get("description", f"Chat with {backend}"),
            "icon": meta.get("icon", "chat"),
            "backend": backend,
            "model": ai_model
        })
    return chats


def _build_workflow_list(config: dict) -> List[dict]:
    """Build list of workflow data for tile generation.

    Discovers workflows from deskagent/workflows/ and user's workflows/.

    Args:
        config: Full application config

    Returns:
        List of workflow dicts with tile data
    """
    if workflow_manager is None:
        return []

    ui_config = config.get("ui", {})
    workflows = []

    try:
        workflow_manager.discover()
        # Get trigger status for all workflows
        trigger_status = workflow_manager.get_trigger_status()

        for wf in workflow_manager.list_all():
            wf_id = wf["id"]
            trigger_info = trigger_status.get(wf_id, {})
            workflows.append({
                "id": wf_id,
                "name": wf["name"],
                "description": wf.get("description", ""),
                "icon": wf.get("icon", "account_tree"),
                "category": wf.get("category", "workflow"),
                "order": 100,  # After agents
                "style": build_tile_style({"category": "workflow"}, is_agent=True, ui_config=ui_config),
                "has_trigger": trigger_info.get("has_trigger", False),
                "trigger_enabled": trigger_info.get("enabled", False),
                "trigger_name": trigger_info.get("trigger_name", ""),
                "trigger_type": trigger_info.get("trigger_type", ""),
            })
    except Exception as e:
        # If workflow discovery fails, return empty list
        print(f"[UI] Workflow discovery failed: {e}")

    return workflows


def build_workflow_tile(wf: dict) -> str:
    """Build HTML for a single workflow tile.

    Args:
        wf: Workflow data dict

    Returns:
        HTML string for the workflow tile
    """
    icon = wf.get("icon", "account_tree")
    name = wf.get("name", wf["id"])
    description = wf.get("description", "")
    style = wf.get("style", "")

    # Trigger status classes and tooltip
    has_trigger = wf.get("has_trigger", False)
    trigger_enabled = wf.get("trigger_enabled", False)
    trigger_name = wf.get("trigger_name", "")

    # Build CSS classes
    classes = ["tile", "workflow-tile"]
    if has_trigger and not trigger_enabled:
        classes.append("trigger-disabled")
    elif has_trigger and trigger_enabled:
        classes.append("trigger-enabled")

    # Build tooltip
    if has_trigger:
        if trigger_enabled:
            title = f"Trigger aktiv: {trigger_name}"
        else:
            title = f"Trigger inaktiv: {trigger_name}"
    else:
        title = "Kein Trigger konfiguriert"

    class_str = " ".join(classes)

    return f'''<div class="{class_str}" id="workflow-{wf['id']}" data-workflow-id="{wf['id']}" data-category="{wf.get('category', 'workflow')}" onclick="startWorkflow('{wf['id']}')" style="{style}" title="{title}">
        <span class="material-icons tile-icon">account_tree</span>
        <span class="material-icons tile-icon-small">{icon}</span>
        <div class="tile-content">
            <div class="tile-title">{name}</div>
            <div class="tile-description">{description}</div>
        </div>
        <span class="tile-badge workflow-label">Workflow</span>
    </div>'''


def build_web_ui() -> str:
    """Build the complete web UI HTML.

    Loads configuration, builds skill/agent/chat tiles,
    and populates the HTML template.

    Returns:
        Complete HTML string for the web UI
    """
    config = load_config()
    ui_config = config.get("ui", {})

    # Build tile lists
    skills = _build_skill_list(config)
    agents = _build_agent_list(config)
    chats = _build_chat_list(config)
    workflows = _build_workflow_list(config)

    # Sort and build tiles
    skills.sort(key=lambda x: (x["order"], x["id"]))
    agents.sort(key=lambda x: (x["order"], x["id"]))
    skill_tiles = "\n".join([build_tile(s, "skill") for s in skills])
    agent_tiles = "\n".join([build_tile(a, "agent") for a in agents])
    chat_tiles = "\n".join([build_chat_tile(c) for c in chats])
    workflow_tiles = "\n".join([build_workflow_tile(w) for w in workflows])

    # Developer mode content
    dev_header_icon = ""
    if config.get("developer_mode", False):
        dev_tabs, dev_tab_content, settings_dev_tabs, settings_dev_tab_content = _get_dev_tabs_html()
    else:
        dev_tabs = dev_tab_content = settings_dev_tabs = settings_dev_tab_content = ""

    # Load and populate template
    template_path = get_templates_dir() / "webui.html"
    html = template_path.read_text(encoding="utf-8")

    # Theme and UI settings - check preferences first
    prefs = _load_ui_preferences()
    theme = prefs.get("ui", {}).get("theme") or ui_config.get("theme", "light")
    html = html.replace("{{THEME}}", theme)
    app_title = ui_config.get("title", config.get("name", "DeskAgent"))
    app_icon = ui_config.get("icon", "icon.ico")
    accent_color = ui_config.get("accent_color", "#2196f3")

    html = html.replace("{{APP_TITLE}}", app_title)
    html = html.replace("{{APP_ICON}}", app_icon)
    html = html.replace("{{ACCENT_COLOR}}", accent_color)
    html = html.replace("{{SKILL_TILES}}", skill_tiles)
    html = html.replace("{{AGENT_TILES}}", agent_tiles)
    html = html.replace("{{CHAT_TILES}}", chat_tiles)
    html = html.replace("{{WORKFLOW_TILES}}", workflow_tiles)

    # Category filter
    categories = load_categories()
    category_items_html = ""
    for cat_id, cat_info in sorted(categories.items(), key=lambda x: x[1].get("order", 999)):
        icon = cat_info.get("icon", "folder")
        label = cat_info.get("label", cat_id)
        category_items_html += f'''<div class="dropdown-item" data-category="{cat_id}" onclick="filterByCategory('{cat_id}')">
                    <span class="material-icons dropdown-icon">{icon}</span>
                    <span>{label}</span>
                </div>\n'''
    html = html.replace("{{CATEGORY_ITEMS}}", category_items_html)
    html = html.replace("{{CATEGORY_DATA}}", json.dumps(categories).replace('"', '&quot;'))

    # Hamburger menu category items (same categories, different HTML structure)
    hamburger_category_items_html = ""
    for cat_id, cat_info in sorted(categories.items(), key=lambda x: x[1].get("order", 999)):
        icon = cat_info.get("icon", "folder")
        label = cat_info.get("label", cat_id)
        hamburger_category_items_html += f'''<div class="hamburger-subitem" data-category="{cat_id}" onclick="filterByCategory('{cat_id}'); closeHamburgerMenu();">
                    <span class="material-icons">{icon}</span>
                    <span>{label}</span>
                </div>\n'''
    html = html.replace("{{HAMBURGER_CATEGORY_ITEMS}}", hamburger_category_items_html)

    # Developer tabs
    html = html.replace("{{DEV_HEADER_ICON}}", dev_header_icon)
    html = html.replace("{{DEV_TABS}}", dev_tabs)
    html = html.replace("{{DEV_TAB_CONTENT}}", dev_tab_content)
    html = html.replace("{{SETTINGS_DEV_TABS}}", settings_dev_tabs)
    html = html.replace("{{SETTINGS_DEV_TAB_CONTENT}}", settings_dev_tab_content)

    # Anonymization status
    anon_config = config.get("anonymization", {})
    anon_enabled = anon_config.get("enabled", False)
    if anon_enabled:
        html = html.replace("{{ANON_CLASS}}", "online")
        html = html.replace("{{ANON_ICON}}", "lock")
        html = html.replace("{{ANON_TEXT}}", "Anonymization")
    else:
        html = html.replace("{{ANON_CLASS}}", "anon-off")
        html = html.replace("{{ANON_ICON}}", "lock_open")
        html = html.replace("{{ANON_TEXT}}", "No Anonymization")

    # Content mode
    content_mode = get_content_mode()
    mode_labels = {"custom": "Custom", "both": "Both", "standard": "Standard"}
    show_selector = ui_config.get("show_content_mode_selector", True)
    html = html.replace("{{CONTENT_MODE_HIDDEN}}", "" if show_selector else "hidden")
    html = html.replace("{{CONTENT_MODE_LABEL}}", mode_labels.get(content_mode, "Both"))
    html = html.replace("{{CUSTOM_ACTIVE}}", "active" if content_mode == "custom" else "")
    html = html.replace("{{BOTH_ACTIVE}}", "active" if content_mode == "both" else "")
    html = html.replace("{{STANDARD_ACTIVE}}", "active" if content_mode == "standard" else "")

    # Simple mode (for non-technical users)
    simple_mode = _get_simple_mode_preference()
    html = html.replace("{{SIMPLE_MODE_CLASS}}", "simple-mode" if simple_mode else "")
    # When in simple mode, show "Expert" button (to switch to expert mode)
    # When in expert mode, show "Simple" button (to switch to simple mode)
    html = html.replace("{{SIMPLE_MODE_ICON}}", "auto_awesome" if simple_mode else "tune")
    html = html.replace("{{SIMPLE_MODE_LABEL}}", "Expert" if simple_mode else "Simple")
    html = html.replace("{{SIMPLE_MODE_TOOLTIP}}",
        "Zu Expert-Modus wechseln (mehr Optionen)" if simple_mode else "Zu Simple-Modus wechseln (vereinfachte Ansicht)")

    # Edit agent config (for Ctrl+Click feature)
    edit_agent = config.get("edit_agent", "create_agent")
    html = html.replace("{{EDIT_AGENT}}", edit_agent)

    # Browser logging level (minimal, normal, verbose)
    browser_log_level = ui_config.get("browser_logging", "normal")
    html = html.replace("{{BROWSER_LOG_LEVEL}}", browser_log_level)

    # Branding variables from config (XSS-safe: html.escape all user-configurable values)
    import html as html_lib
    app_config = config.get("app", {})
    branding_config = config.get("branding", {})
    html = html.replace("{{BRANDING_COPYRIGHT}}", html_lib.escape(app_config.get("copyright", "")))
    html = html.replace("{{BRANDING_DOC_URL}}", html_lib.escape(app_config.get("doc_url", "https://doc.deskagent.de")))
    html = html.replace("{{BRANDING_LICENSE_URL}}", html_lib.escape(app_config.get("license_url", "")))
    html = html.replace("{{BRANDING_LICENSES_URL}}", html_lib.escape(app_config.get("licenses_url", "")))
    html = html.replace("{{BRANDING_PRIVACY_URL}}", html_lib.escape(app_config.get("privacy_url", "")))
    html = html.replace("{{BRANDING_ORDER_URL}}", html_lib.escape(app_config.get("order_url", "")))
    html = html.replace("{{BRANDING_SUPPORT_EMAIL}}", html_lib.escape(app_config.get("support_email", "")))
    html = html.replace("{{BRANDING_PORTAL_URL}}", html_lib.escape(app_config.get("portal_url", "")))
    html = html.replace("{{BRANDING_LICENSE_API_URL}}", html_lib.escape(app_config.get("license_api_url", "")))
    html = html.replace("{{BRANDING_COMPANY}}", html_lib.escape(branding_config.get("company_name", "")))

    # Version info
    import paths
    version_file = paths.DESKAGENT_DIR / "version.json"
    version_str = "?"
    if version_file.exists():
        try:
            with open(version_file, "r") as f:
                version_info = json.load(f)
                version_str = version_info.get("version", "?")
                build = version_info.get("build", 0)
                if build > 0:
                    version_str = f"{version_str}-b{build}"
        except Exception:
            pass
    html = html.replace("{{VERSION}}", version_str)

    # Language and translations (i18n)
    # Use prefs already loaded above for theme
    language = prefs.get("ui", {}).get("language") or config.get("language", "de")
    translations = load_translations(language)
    html = html.replace("{{LANGUAGE}}", language)
    html = html.replace("{{TRANSLATIONS}}", json.dumps(translations, ensure_ascii=False))

    # UI state preferences (history pinned, etc.)
    ui_prefs = prefs.get("ui", {})
    # Handle both boolean True and string "true" (backwards compatibility)
    history_pinned = "true" if ui_prefs.get("history_pinned") in [True, "true"] else "false"
    html = html.replace("{{HISTORY_PINNED}}", history_pinned)

    return html


def build_preprompt_ui(agent_name: str) -> str:
    """Build a Pre-Prompt UI for Quick Access mode.

    This generates an HTML page that looks like the normal input dialog,
    with a context input field, voice recording button, and submit/cancel buttons.
    Used when opening a preprompt overlay window from Quick Access mode.

    Args:
        agent_name: Name of the agent to run after context input

    Returns:
        Complete HTML string for the preprompt UI
    """
    import html as html_lib

    config = load_config()
    ui_config = config.get("ui", {})

    # Load preferences and translations
    prefs = _load_ui_preferences()
    theme = prefs.get("ui", {}).get("theme") or ui_config.get("theme", "light")
    language = prefs.get("ui", {}).get("language") or config.get("language", "de")
    translations = load_translations(language)

    # Get localized strings
    def t(key: str, default: str = "") -> str:
        parts = key.split(".")
        value = translations
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part, {})
            else:
                return default
        return value if isinstance(value, str) else default

    escaped_agent = html_lib.escape(agent_name)
    label = t("agent.additional_context", "Additional context")
    placeholder = t("agent.context_placeholder", "Important information for the agent...")
    cancel = t("dialog.cancel", "Cancel")
    start = t("agent.start", "Start Agent")
    accent_color = ui_config.get("accent_color", "#2196f3")

    # Voice-related translations
    voice_click_to_record = t("voice.click_to_record", "Click to record")
    voice_recording = t("voice.recording", "Recording...")
    voice_processing = t("voice.processing", "Processing...")

    # Theme-specific colors
    if theme == "dark":
        bg_primary = "#1a1a2e"
        bg_secondary = "#16213e"
        bg_tertiary = "#0f3460"
        text_primary = "#eee"
        text_secondary = "#aaa"
        border_color = "#333"
    else:
        bg_primary = "#ffffff"
        bg_secondary = "#f7f7f8"
        bg_tertiary = "#ececec"
        text_primary = "#343541"
        text_secondary = "#6e6e80"
        border_color = "#e5e5e6"

    html = f'''<!DOCTYPE html>
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pre-Prompt: {escaped_agent}</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            padding: 16px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: {bg_secondary};
            color: {text_primary};
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .input-dialog {{
            background: {bg_primary};
            border-radius: 12px;
            width: 100%;
            max-width: 420px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }}
        .input-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 16px 20px;
            border-bottom: 1px solid {border_color};
            background: {bg_secondary};
        }}
        .input-header .material-icons {{
            color: {accent_color};
            font-size: 24px;
        }}
        .input-header h3 {{
            margin: 0;
            font-size: 16px;
            font-weight: 600;
            flex: 1;
            color: {text_primary};
        }}
        .input-close {{
            background: none;
            border: none;
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
            color: {text_secondary};
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .input-close:hover {{
            background: {bg_tertiary};
            color: {text_primary};
        }}
        .input-fields {{
            padding: 20px;
        }}
        .input-field {{
            position: relative;
        }}
        .input-field label {{
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: {text_secondary};
            margin-bottom: 8px;
        }}
        .input-field textarea {{
            width: 100%;
            padding: 12px;
            padding-right: 44px;
            border: 1px solid {border_color};
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: none;
            background: {bg_secondary};
            color: {text_primary};
            min-height: 120px;
        }}
        .input-field textarea:focus {{
            outline: none;
            border-color: {accent_color};
        }}
        .input-field textarea::placeholder {{
            color: {text_secondary};
        }}
        .input-buttons {{
            display: flex;
            gap: 12px;
            padding: 16px 20px;
            border-top: 1px solid {border_color};
            background: {bg_secondary};
            justify-content: flex-end;
        }}
        .btn-cancel, .btn-confirm {{
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            border: none;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .btn-cancel {{
            background: {bg_tertiary};
            color: {text_primary};
        }}
        .btn-cancel:hover {{
            background: {border_color};
        }}
        .btn-confirm {{
            background: {accent_color};
            color: white;
        }}
        .btn-confirm:hover {{
            filter: brightness(1.1);
        }}
        .input-field-voice-btn {{
            position: absolute;
            right: 8px;
            bottom: 8px;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            border: none;
            background: {bg_tertiary};
            color: {text_secondary};
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .input-field-voice-btn:hover {{
            background: {accent_color};
            color: white;
        }}
        .input-field-voice-btn.recording {{
            background: #e53935;
            color: white;
            animation: pulse 1s ease-in-out infinite;
        }}
        .input-field-voice-btn.processing {{
            background: {accent_color};
            color: white;
            opacity: 0.7;
        }}
        .input-field-voice-btn .material-icons {{
            font-size: 18px;
        }}
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.1); }}
        }}
        .material-icons {{
            font-family: 'Material Icons';
            font-size: 18px;
            vertical-align: middle;
        }}
    </style>
</head>
<body>
    <div class="input-dialog">
        <div class="input-fields">
            <div class="input-field" data-field="_context" data-type="text">
                <label>{label}</label>
                <textarea id="prepromptContext" name="_context" rows="6" placeholder="{placeholder}"></textarea>
                <button type="button" class="input-field-voice-btn" id="voiceBtn" title="{voice_click_to_record}">
                    <span class="material-icons">mic</span>
                </button>
            </div>
        </div>
        <div class="input-buttons">
            <button class="btn-cancel" onclick="cancelPreprompt()">
                {cancel}
            </button>
            <button class="btn-confirm" onclick="submitPreprompt()">
                <span class="material-icons" style="font-size:16px;">play_arrow</span>
                {start}
            </button>
        </div>
    </div>

    <script>
        const API = '';
        const agentName = '{escaped_agent}';

        // Voice recording state
        let voiceAvailable = false;
        let isRecording = false;
        let mediaRecorder = null;
        let audioChunks = [];

        // Check if voice is available
        async function checkVoiceAvailability() {{
            try {{
                // Check if browser supports getUserMedia
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
                    return false;
                }}
                // Check if transcription endpoint exists
                const res = await fetch('/api/voice/status');
                if (res.ok) {{
                    const data = await res.json();
                    return data.available === true;
                }}
            }} catch (e) {{
                console.log('Voice not available:', e);
            }}
            return false;
        }}

        // Initialize voice button
        async function initVoice() {{
            voiceAvailable = await checkVoiceAvailability();
            const voiceBtn = document.getElementById('voiceBtn');
            if (voiceAvailable && voiceBtn) {{
                voiceBtn.style.display = 'flex';
                voiceBtn.addEventListener('click', toggleRecording);
            }}
        }}

        // Toggle voice recording
        async function toggleRecording() {{
            if (isRecording) {{
                stopRecording();
            }} else {{
                await startRecording();
            }}
        }}

        // Start recording
        async function startRecording() {{
            try {{
                const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];

                mediaRecorder.ondataavailable = (e) => {{
                    if (e.data.size > 0) audioChunks.push(e.data);
                }};

                mediaRecorder.onstop = async () => {{
                    stream.getTracks().forEach(track => track.stop());
                    if (audioChunks.length > 0) {{
                        await processRecording();
                    }}
                }};

                mediaRecorder.start();
                isRecording = true;
                updateVoiceButton();
            }} catch (e) {{
                console.error('Failed to start recording:', e);
                alert('Microphone access denied');
            }}
        }}

        // Stop recording
        function stopRecording() {{
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {{
                mediaRecorder.stop();
            }}
            isRecording = false;
            updateVoiceButton('processing');
        }}

        // Process and transcribe recording
        async function processRecording() {{
            try {{
                const audioBlob = new Blob(audioChunks, {{ type: 'audio/webm' }});
                const formData = new FormData();
                formData.append('audio', audioBlob, 'recording.webm');

                const res = await fetch('/api/voice/transcribe', {{
                    method: 'POST',
                    body: formData
                }});

                if (res.ok) {{
                    const data = await res.json();
                    if (data.text) {{
                        const textarea = document.getElementById('prepromptContext');
                        const current = textarea.value;
                        textarea.value = current ? current + ' ' + data.text : data.text;
                        textarea.focus();
                    }}
                }}
            }} catch (e) {{
                console.error('Transcription failed:', e);
            }}
            updateVoiceButton();
        }}

        // Update voice button appearance
        function updateVoiceButton(state) {{
            const voiceBtn = document.getElementById('voiceBtn');
            if (!voiceBtn) return;

            voiceBtn.classList.remove('recording', 'processing');
            const icon = voiceBtn.querySelector('.material-icons');
            if (!icon) return;

            if (state === 'processing') {{
                voiceBtn.classList.add('processing');
                icon.textContent = 'hourglass_empty';
                voiceBtn.title = '{voice_processing}';
            }} else if (isRecording) {{
                voiceBtn.classList.add('recording');
                icon.textContent = 'stop';
                voiceBtn.title = '{voice_recording}';
            }} else {{
                icon.textContent = 'mic';
                voiceBtn.title = '{voice_click_to_record}';
            }}
        }}

        // Submit handler
        async function submitPreprompt() {{
            const context = document.getElementById('prepromptContext').value.trim();

            let url = API + '/agent/' + encodeURIComponent(agentName);
            if (context) {{
                url += '?_context=' + encodeURIComponent(context);
            }}

            try {{
                await fetch(url);
                window.close();
                if (window.opener) {{
                    window.opener.postMessage({{ type: 'preprompt-submitted', agent: agentName }}, '*');
                }}
            }} catch (e) {{
                console.error('Failed to start agent:', e);
                alert('Failed to start agent: ' + e.message);
            }}
        }}

        // Cancel handler
        function cancelPreprompt() {{
            if (isRecording) {{
                mediaRecorder.stop();
                isRecording = false;
            }}
            window.close();
        }}

        // Keyboard shortcuts
        document.getElementById('prepromptContext').addEventListener('keydown', function(e) {{
            if ((e.ctrlKey || e.shiftKey) && e.key === 'Enter') {{
                e.preventDefault();
                submitPreprompt();
            }}
            if (e.key === 'Escape') {{
                cancelPreprompt();
            }}
        }});

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            document.getElementById('prepromptContext').focus();
            initVoice();
        }});
    </script>
</body>
</html>'''

    return html
