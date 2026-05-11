# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Prompt Builder Module
=====================
Builds system prompts for AI agents from configuration, knowledge, and templates.

This module is the single source of truth for system prompt generation.
All backends should use these functions to ensure consistent prompts.

Public Functions:
- build_system_prompt(config, knowledge_pattern, config) - Build complete system prompt
- build_system_prompt_parts(config, knowledge_pattern, config) - Build with static/dynamic separation

Constants:
- DEFAULT_SYSTEM_PROMPT - Default prompt when none is configured
"""

import datetime
from typing import Optional

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "build_system_prompt",
    "build_system_prompt_parts",
]


# Generic fallback system prompt used when neither agent_config nor
# branding.assistant_intro provides a value. Kept generic for the AGPL /
# Community Edition - operators can override via
# `system.json -> branding.assistant_intro`.
_GENERIC_FALLBACK = """Du bist ein hilfreicher Assistent.
Verwende die verfügbaren Tools um Aufgaben zu erledigen.
Frage nach wenn du unsicher bist.

**SPRACHE:** Antworte IMMER auf Deutsch, außer der User schreibt explizit auf Englisch.
Alle Erklärungen, Zusammenfassungen und Ausgaben müssen auf Deutsch sein.

WICHTIG: Arbeite NUR mit explizit bereitgestellten Daten. Erfinde NIEMALS fehlende Informationen.
Wenn Daten unvollständig oder abgeschnitten sind, weise darauf hin statt zu raten oder zu ergänzen."""


def _load_assistant_intro_from_config() -> str:
    """Read branding.assistant_intro from system.json, '' on failure."""
    try:
        from assistant.config import get_config
        config = get_config()
        branding = config.get("branding", {}) or {}
        return branding.get("assistant_intro") or ""
    except Exception:
        return ""


# Backwards-compatible re-export.
# `DEFAULT_SYSTEM_PROMPT` is loaded once at import time from
# `branding.assistant_intro` (system.json) and falls back to the generic
# string above. Keeping the constant available is required for tests
# (e.g. `test_base.py:10`, :211) and downstream imports.
DEFAULT_SYSTEM_PROMPT = _load_assistant_intro_from_config() or _GENERIC_FALLBACK


def get_system_prompt() -> str:
    """Read assistant_intro from branding config, fallback to DEFAULT_SYSTEM_PROMPT.

    Unlike `DEFAULT_SYSTEM_PROMPT` (which is a snapshot at import time),
    this function re-reads the config every call so config edits take
    effect without restart.

    Returns:
        Custom intro from branding config, or the default system prompt
    """
    intro = _load_assistant_intro_from_config()
    if intro:
        return intro
    return DEFAULT_SYSTEM_PROMPT


def build_system_prompt(agent_config: dict, knowledge_pattern: str = None, config: dict = None) -> str:
    """
    Build the complete system prompt for an AI agent.

    This is the single source of truth for system prompt generation.
    All backends should use this function.

    NOTE: Agent markdown content is NOT included here - it comes via the user prompt
    from agents.py::load_agent() which handles procedures, inputs, and placeholders.

    Args:
        agent_config: Agent-specific configuration dict
        knowledge_pattern: Optional regex pattern to filter knowledge files
                          (e.g., "company|products"). If None, pattern from
                          agent_config["knowledge"] is used.
        config: Optional main config dict (for security settings)

    Returns:
        Complete system prompt with:
        1. Base prompt (from config or default)
        2. Security warning (if enabled)
        3. System templates (dialogs format, etc.)
        4. Knowledge (prices, products, etc.)
        5. Agent instructions (from config JSON)
        6. Current date/time (at the END for caching optimization)
    """
    static_part, dynamic_part = build_system_prompt_parts(agent_config, knowledge_pattern, config)
    return static_part + dynamic_part


def build_system_prompt_parts(agent_config: dict, knowledge_pattern: str = None, config: dict = None) -> tuple:
    """
    Build the system prompt in two parts: static (cacheable) and dynamic.

    This separation enables prompt caching optimizations:
    - Static part: Knowledge, templates, instructions (rarely changes)
    - Dynamic part: Current date/time (changes daily)

    For Gemini Context Caching: Cache the static part, append dynamic part at runtime.
    For Claude SDK: SDK handles caching internally.

    Args:
        agent_config: Agent-specific configuration dict
        knowledge_pattern: Optional regex pattern to filter knowledge files
        config: Optional main config dict (for security settings)

    Returns:
        Tuple of (static_part, dynamic_part)
        - static_part: Cacheable content (knowledge, templates, instructions)
        - dynamic_part: Non-cacheable content (current date/time)
    """
    # Lazy imports to avoid circular dependencies
    from .logging import log
    from .knowledge_loader import load_knowledge_cached
    from .template_loader import load_templates, set_template_stats_skipped
    from .token_utils import estimate_tokens
    from .config_resolver import _resolve_path_placeholders

    # Get base system prompt from config or use default
    base_prompt = agent_config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)

    # Start with base prompt (STATIC)
    system_prompt = base_prompt

    # Add anonymization instructions if anonymization is enabled (STATIC)
    if config:
        anon_config = config.get("anonymization", {})
        if anon_config.get("enabled", False):
            placeholder_format = anon_config.get("placeholder_format", "<{entity_type}_{index}>")
            # Determine placeholder style from format
            if placeholder_format.startswith("["):
                example_person = "[PERSON-1]"
                example_email = "[EMAIL-1]"
                example_address = "[ADDRESS-1]"
            else:
                example_person = "<PERSON_1>"
                example_email = "<EMAIL_1>"
                example_address = "<ADDRESS_1>"

            # Generate ALL examples using consistent format
            if placeholder_format.startswith("["):
                example_domain = "[DOMAIN-1]"
                example_phone = "[PHONE-1]"
                example_org = "[ORG-1]"
            else:
                example_domain = "<DOMAIN_1>"
                example_phone = "<PHONE_1>"
                example_org = "<ORGANIZATION_1>"

            system_prompt += f"""

## Datenschutz-Anonymisierung

Der Eingabetext enthält anonymisierte personenbezogene Daten (PII). Platzhalter wie:
- **{example_person}** = Name einer Person (z.B. "Max Müller")
- **{example_email}** = E-Mail-Adresse (z.B. "max@example.com")
- **{example_address}** = Adresse (z.B. "Musterstraße 12, 12345 Berlin")
- **{example_domain}** = Domain (z.B. "example.com")
- **{example_phone}** = Telefonnummer
- **{example_org}** = Organisation/Firma

**KRITISCH - Regeln für Platzhalter:**
1. **NUR VORHANDENE PLATZHALTER VERWENDEN:** Nutze ausschließlich Platzhalter die bereits im Text existieren
2. **NIEMALS NEUE PLATZHALTER ERSTELLEN:** Wenn du einen Namen/E-Mail ohne Platzhalter siehst, verwende ihn wie er ist - das System anonymisiert automatisch
3. **KEIN EIGENES TAGGING:** Erstelle KEINE neuen Platzhalter wie [PERSON-X] oder <PERSON_X> für Daten die du siehst
4. Behandle vorhandene Platzhalter so, als wären sie die echten Daten
5. Verwende vorhandene Platzhalter in Tool-Aufrufen - sie werden automatisch durch echte Werte ersetzt

**Beispiel - RICHTIG:**
- Input: "E-Mail von {example_person} an support@firma.de"
- Output: "Die E-Mail von {example_person} wurde an support@firma.de gesendet"

**Beispiel - FALSCH:**
- Input: "E-Mail von Max Müller an support@firma.de"
- Output: "Die E-Mail von [PERSON-1] wurde an [EMAIL-1] gesendet" ← NIEMALS so!
- Richtig: "Die E-Mail von Max Müller wurde an support@firma.de gesendet" ← System anonymisiert automatisch"""

    # Add security warning if prompt injection protection is enabled (STATIC)
    if config:
        security_config = config.get("security", {})
        if security_config.get("prompt_injection_protection", True):
            try:
                from ai_agent.input_sanitizer import get_injection_warning
                system_prompt += f"\n\n{get_injection_warning()}"
            except ImportError:
                pass  # Sanitizer not available

    # Get knowledge pattern from config if not explicitly passed
    if knowledge_pattern is None:
        knowledge_pattern = agent_config.get("knowledge")

    # Add knowledge EARLY (prices, products etc.) - STATIC
    # Reasoning: LLMs have "Primacy & Recency Effect" - beginning and end
    # get stronger attention weights. Knowledge (products, prices, company info)
    # should be early for better retention and fewer hallucinations.
    agent_name = agent_config.get("name", "unknown")
    knowledge = load_knowledge_cached(knowledge_pattern, agent_name)
    if knowledge:
        system_prompt += f"\n\n## Wissensbasis\n{knowledge}"

    # Add system templates (dialogs format, etc.) - STATIC
    # Templates define FORMAT (how to respond), not CONTENT - can be later
    # Skip for auto-running agents that should never ask questions
    if agent_config.get("skip_dialogs"):
        log("[Base] skip_dialogs=True - skipping dialog templates (auto-running agent)")
        set_template_stats_skipped()
    else:
        templates = load_templates()
        if templates:
            system_prompt += f"\n\n{templates}"
            log(f"[Base] System templates added to prompt ({len(templates)} chars)")
        else:
            log("[Base] WARNING: No system templates loaded!")

    # NOTE: Agent markdown is NOT loaded here anymore!
    # Agent content comes via the user prompt (from agents.py::load_agent())
    # which properly handles procedures, inputs, and all placeholders.

    # Add agent-specific instructions (from config) - STATIC
    instructions = agent_config.get("instructions")
    if instructions:
        system_prompt += f"\n\n## Agent-Anweisungen\n\n{instructions}"
        log(f"[Base] Agent instructions added to prompt ({len(instructions)} chars)")

    # Add workspace paths for file operations - STATIC
    try:
        from paths import get_exports_dir, get_temp_dir
        exports_dir = str(get_exports_dir()).replace("\\", "/")
        temp_dir = str(get_temp_dir()).replace("\\", "/")
        system_prompt += f"""

## Arbeitsverzeichnisse

Speichere Dateien in den folgenden Standard-Verzeichnissen:
- **Exports** (PDFs, Reports, Downloads): `{exports_dir}`
- **Temp** (temporäre Dateien): `{temp_dir}`

Verwende IMMER das Exports-Verzeichnis für Dateien die der Benutzer behalten soll."""
    except ImportError:
        pass  # paths module not available

    # Add security restrictions (allowed_tools, filesystem) - STATIC
    security_info = _build_security_restrictions(agent_config, _resolve_path_placeholders)
    if security_info:
        system_prompt += f"\n\n{security_info}"

    # === STATIC PART COMPLETE ===
    static_part = system_prompt

    # === DYNAMIC PART (changes daily - NOT cached) ===
    # Date/time context at the END for optimal caching
    # LLMs have "Recency Effect" - end of prompt gets good attention
    now = datetime.datetime.now()
    weekdays_de = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    weekday = weekdays_de[now.weekday()]
    dynamic_part = f"""

## Aktuelles Datum

- **Heute:** {now.strftime("%d.%m.%Y")} ({weekday})
- **Jahr:** {now.year}
- **ISO-Datum:** {now.strftime("%Y-%m-%d")}
- **Uhrzeit:** {now.strftime("%H:%M")}

Beachte: Bei relativen Zeitangaben wie "letzte 7 Tage" oder "letzter Monat" berechne die Daten basierend auf dem heutigen Datum."""

    log(f"[Base] System prompt built: {estimate_tokens(static_part)} static + {estimate_tokens(dynamic_part)} dynamic tokens")
    log(f"[Base] Date context (dynamic): {now.strftime('%Y-%m-%d %H:%M')}")

    return static_part, dynamic_part


def _build_security_restrictions(agent_config: dict, resolve_path_func: callable = None) -> str:
    """
    Build security restrictions section for system prompt.

    Includes:
    - allowed_tools whitelist
    - blocked_tools blacklist
    - filesystem read/write restrictions

    Args:
        agent_config: Agent configuration with optional security settings
        resolve_path_func: Optional function to resolve path placeholders

    Returns:
        Formatted security restrictions or empty string
    """
    sections = []

    # 1. Tool whitelist
    allowed_tools = agent_config.get("allowed_tools")
    if allowed_tools:
        tools_list = ", ".join(f"`{t}`" for t in allowed_tools)
        sections.append(f"""### Verfügbare Tools

Du hast nur Zugriff auf folgende Tools: {tools_list}

Andere Tools sind für diesen Agent nicht verfügbar.""")

    # 1b. Tool blacklist
    blocked_tools = agent_config.get("blocked_tools")
    if blocked_tools:
        blocked_list = ", ".join(f"`{t}`" for t in blocked_tools)
        sections.append(f"""### Verbotene Tools

Folgende Tools darfst du NIEMALS verwenden: {blocked_list}

Diese Tools sind für diesen Agent gesperrt.""")

    # 2. Filesystem restrictions
    filesystem = agent_config.get("filesystem")
    if filesystem:
        fs_parts = []

        read_paths = filesystem.get("read", [])
        write_paths = filesystem.get("write", [])

        if read_paths:
            # Resolve placeholders for display
            if resolve_path_func:
                resolved_read = [resolve_path_func(p) for p in read_paths]
            else:
                resolved_read = read_paths
            read_list = "\n".join(f"  - `{p}`" for p in resolved_read)
            fs_parts.append(f"**Lesen erlaubt:**\n{read_list}")
        else:
            fs_parts.append("**Lesen:** Keine Pfade erlaubt")

        if write_paths:
            # Resolve placeholders for display
            if resolve_path_func:
                resolved_write = [resolve_path_func(p) for p in write_paths]
            else:
                resolved_write = write_paths
            write_list = "\n".join(f"  - `{p}`" for p in resolved_write)
            fs_parts.append(f"**Schreiben erlaubt:**\n{write_list}")
        else:
            fs_parts.append("**Schreiben:** Keine Pfade erlaubt")

        sections.append(f"""### Dateisystem-Beschränkungen

{chr(10).join(fs_parts)}

Zugriffe auf andere Pfade werden blockiert.""")

    if not sections:
        return ""

    return "## Sicherheitseinschränkungen\n\n" + "\n\n".join(sections)
