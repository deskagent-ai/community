# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Agent loading and processing for DeskAgent.
"""

import json
import re
import sys

# winsound is Windows-only
try:
    import winsound
except ImportError:
    winsound = None

import ai_agent
from ai_agent import log
from .skills import load_config, notify
from . import interaction
from .core import publish_pending_input, update_tray_status, set_tray_idle
from .core.sse_manager import broadcast_global_event
from . import session_store

# Centralized parsing utilities
try:
    from utils.parsing import parse_frontmatter
except ImportError:
    # Fallback for standalone execution
    import re
    def parse_frontmatter(content: str) -> tuple[dict, str]:
        pattern = r'^---\s*\n(.*?)\n---\s*\n?(.*)$'
        match = re.match(pattern, content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1)), match.group(2)
            except json.JSONDecodeError:
                pass
        return {}, content


def _get_discovery_config(agent_name: str) -> dict:
    """Lazy wrapper for discovery.get_agent_config to avoid circular import."""
    from .services.discovery import get_agent_config
    return get_agent_config(agent_name)

# System logging for debugging
try:
    system_log = ai_agent.system_log
except AttributeError:
    system_log = lambda msg: print(msg)

# Path is set up by assistant/__init__.py
from paths import get_agents_dir, PROJECT_DIR, DESKAGENT_DIR


def _find_agent_file(agent_name: str):
    """Sucht Agent-Datei in User-Space zuerst, dann in deskagent/agents/.

    Prüft beide Verzeichnisse, damit Standard-Agents auch funktionieren
    wenn User eigene Agents hat.
    """
    import paths
    search_dirs = [
        paths.PROJECT_DIR / "agents",
        paths.DESKAGENT_DIR / "agents"
    ]
    for search_dir in search_dirs:
        candidate = search_dir / f"{agent_name}.md"
        if candidate.exists():
            return candidate
    return None


def _resolve_nested_placeholder(data: dict, path: str) -> str | None:
    """Resolve a dot-notation path in a nested dict.

    Example: _resolve_nested_placeholder({"labels": {"done": "IsDone"}}, "labels.done")
    Returns: "IsDone"

    Args:
        data: The root dict to search in
        path: Dot-notation path like "labels.done"

    Returns:
        Value as string, or None if path not found
    """
    parts = path.split(".")
    current = data

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None

    return str(current) if current is not None else None


def load_procedure(name: str) -> str:
    """Load procedure from agents/procedures/ folder.

    Procedures are reusable templates that can be included in agents
    using the {{PROCEDURE:name}} placeholder syntax.

    Search order:
    1. User agents/procedures/ (PROJECT_DIR/agents/procedures/)
    2. System agents/procedures/ (DESKAGENT_DIR/agents/procedures/)

    Args:
        name: Procedure name (filename without .md extension)

    Returns:
        Procedure content or error message if not found
    """
    import paths

    # Search paths: user first, then system
    search_paths = [
        paths.PROJECT_DIR / "agents" / "procedures" / f"{name}.md",
        paths.DESKAGENT_DIR / "agents" / "procedures" / f"{name}.md",
    ]

    for path in search_paths:
        if path.exists():
            try:
                return path.read_text(encoding='utf-8')
            except Exception as e:
                return f"[PROCEDURE ERROR: {name} - {e}]"

    return f"[PROCEDURE NOT FOUND: {name}]"


def get_agent_inputs(agent_name: str) -> list:
    """Get input definitions from agent frontmatter.

    Args:
        agent_name: Name of the agent

    Returns:
        List of input definitions, or empty list if none defined
    """
    agent_file = _find_agent_file(agent_name)
    log(f"[Agent] Looking for inputs in: {agent_file}")

    if not agent_file:
        log(f"[Agent] File not found for agent: {agent_name}")
        return []

    content = agent_file.read_text(encoding="utf-8")
    metadata, _ = parse_frontmatter(content)
    inputs = metadata.get("inputs", [])
    log(f"[Agent] Parsed frontmatter: {len(inputs)} inputs found")
    return inputs


def load_agent(agent_name: str, inputs: dict = None, extra_placeholders: dict = None, prefetched: dict = None) -> dict | None:
    """Lädt einen Agent aus agents/ Ordner (User-Space zuerst, dann deskagent/).

    Args:
        agent_name: Name of the agent
        inputs: Optional dict of user-provided input values
        extra_placeholders: Optional dict of custom placeholders to replace.
                           Keys are placeholder names (without {{}}), values are replacement strings.
                           Example: {"DONE_LABEL": "IsDone"} replaces {{DONE_LABEL}} with "IsDone"
        prefetched: Optional dict of pre-fetched data to inject.
                   Keys are result keys, values are formatted content.
                   Example: {"email": "Subject: ..."} replaces {{PREFETCH.email}}

    Returns:
        Agent dict with name, content, input_config, and inputs
    """
    agent_file = _find_agent_file(agent_name)
    if not agent_file:
        return None

    raw_content = agent_file.read_text(encoding="utf-8")

    # 1. Parse and strip JSON frontmatter
    metadata, content = parse_frontmatter(raw_content)
    input_config = metadata.get("inputs", [])

    # 2. Replace date + path placeholders (central function)
    from ai_agent.base import resolve_all_placeholders
    content = resolve_all_placeholders(content)

    # 3. Replace procedure includes
    procedure_pattern = r'\{\{PROCEDURE:([a-zA-Z0-9_-]+)\}\}'
    matches = re.findall(procedure_pattern, content)
    for proc_name in matches:
        proc_content = load_procedure(proc_name)
        content = content.replace(f'{{{{PROCEDURE:{proc_name}}}}}', proc_content)

    # 4. Replace input placeholders
    if inputs:
        log(f"[Agent] Processing {len(inputs)} input(s):")
        for field_name, value in inputs.items():
            placeholder = f"{{{{INPUT.{field_name}}}}}"
            if isinstance(value, list):
                # Format file list as markdown bullet list
                formatted = "\n".join(f"- {v}" for v in value)
                log(f"  {field_name} (list with {len(value)} items):")
                for v in value:
                    log(f"    - {v}")
            else:
                formatted = str(value)
                log(f"  {field_name}: {formatted[:100] if len(formatted) > 100 else formatted}")
            content = content.replace(placeholder, formatted)

    # 5. Replace prefetch placeholders (pre-fetched data from MCP tools)
    if prefetched:
        log(f"[Agent] Injecting {len(prefetched)} prefetched item(s):")
        for key, value in prefetched.items():
            placeholder = f"{{{{PREFETCH.{key}}}}}"
            if placeholder in content:
                content = content.replace(placeholder, str(value))
                log(f"  {{{{PREFETCH.{key}}}}}: {len(str(value))} chars")
            else:
                log(f"  {{{{PREFETCH.{key}}}}}: placeholder not found in content")

    # 6. Handle special _context input (Shift+Click additional context)
    # Appended at END for stronger AI attention + marked as important
    # NOTE: Using get() instead of pop() to preserve _context if load_agent is called multiple times
    if inputs and "_context" in inputs:
        context = inputs.get("_context")  # Don't remove - may be called multiple times
        if context and context.strip():
            log(f"[Agent] Appending user context ({len(context)} chars)")
            content += f"\n\n---\n\n## WICHTIG - Zusätzlicher Kontext vom Benutzer:\n\nDer Benutzer hat folgende wichtige Informationen bereitgestellt, die du bei der Ausführung berücksichtigen MUSST:\n\n{context}"

    # 7. Replace extra placeholders (custom values from watcher configs etc.)
    if extra_placeholders:
        log(f"[Agent] Processing {len(extra_placeholders)} extra placeholder(s):")
        for key, value in extra_placeholders.items():
            placeholder = f"{{{{{key}}}}}"  # {{KEY}}
            if placeholder in content:
                content = content.replace(placeholder, str(value))
                log(f"  {{{{{key}}}}} -> {value}")

    agent = {
        "name": agent_name,
        "content": content,
        "input_config": input_config,
        "inputs": inputs or {}
    }

    # Parse name from first line if it's a heading
    for line in content.split("\n"):
        if line.startswith("# Agent:"):
            agent["name"] = line.replace("# Agent:", "").strip()
            break

    return agent


def process_agent(agent_name: str, icon=None, on_chunk: callable = None, task_id: str = None, is_cancelled: callable = None, inputs: dict = None, dry_run: bool = False, test_folder: str = None, backend: str = None, prompt_override: str = None, extra_placeholders: dict = None, session_id: str = None, prefetched: dict = None, disable_anon: bool = False):
    """
    Führt einen Agent mit MCP-Tool-Zugriff aus.

    Args:
        agent_name: Name des Agents
        icon: Tray icon für Benachrichtigungen
        on_chunk: Callback für Streaming
        task_id: Task-ID für User-Bestätigungen (optional)
        is_cancelled: Callback that returns True if task should be cancelled
        inputs: Dict of user-provided input values (optional)
        dry_run: If True, simulate destructive operations (no actual moves/deletes)
        test_folder: Optional Outlook folder for test scenarios (e.g., "TestData")
        backend: Override AI backend (e.g., "gemini", "openai"). If None, uses agent config.
        prompt_override: If set, use this prompt instead of agent file content (for chat prompts).
                        Agent config (knowledge, allowed_mcp) is still loaded from agent_name.
        extra_placeholders: Dict of custom placeholders {NAME: value}. Replaces {{NAME}} in agent.
        session_id: SQLite session ID for parallel execution isolation.
        prefetched: Dict of pre-fetched data to inject into {{PREFETCH.key}} placeholders.
        disable_anon: If True, skip anonymization (Expert Mode override via context menu).

    Returns:
        (success, content, stats_dict) where stats_dict includes:
        - anonymization: {placeholder: original} if anonymization was applied
        - model: model name used
        - input_tokens: number of input tokens
        - output_tokens: number of output tokens
        - duration_seconds: processing time
        - dry_run: bool indicating if this was a dry-run
        - simulated_actions: list of simulated tool calls (if dry_run=True)
    """
    config = load_config()

    # Check if this is an alias agent (config entry with "agent" field referencing another .md)
    # Use discovery service to get merged config (frontmatter + agents.json)
    agent_config = _get_discovery_config(agent_name)
    agent_file_name = agent_config.get("agent", agent_name)  # Use referenced agent or self

    if agent_file_name != agent_name:
        log(f"[Agent] Loading alias agent: {agent_name} -> {agent_file_name}.md")
    else:
        log(f"[Agent] Loading agent: {agent_name}")

    agent = load_agent(agent_file_name, inputs, extra_placeholders, prefetched)

    if not agent:
        log(f"[Agent] ERROR: Agent '{agent_file_name}' nicht gefunden!")
        log(f"[Agent] Searched in: {PROJECT_DIR / 'agents'}, {DESKAGENT_DIR / 'agents'}")
        notify(f"Agent '{agent_file_name}' nicht gefunden!", "Fehler", icon)
        return False, f"Agent '{agent_file_name}' nicht gefunden", None

    # Determine effective prompt: prompt_override (for chat) or agent content
    effective_content = prompt_override if prompt_override else agent["content"]
    is_chat_mode = prompt_override is not None

    log(f"\n{'='*50}")
    if is_chat_mode:
        log(f"[Agent] Chat mode via agent '{agent_name}'...")
    else:
        log(f"[Agent] {agent['name']} startet...")
    if dry_run:
        log(f"[Agent] *** DRY-RUN MODE - No destructive operations ***")
    log(f"{'='*50}")
    notify(f"{'Chat' if is_chat_mode else 'Agent ' + agent['name']} läuft..." + (" (Vorschau)" if dry_run else ""), "DeskAgent", icon)

    # Update tray tooltip to show agent is running
    update_tray_status("läuft...", agent['name'])

    # Broadcast task_started for WebUI running badges
    broadcast_global_event("task_started", {
        "task_id": task_id or f"auto-{agent_name}",
        "name": agent_name,
        "type": "agent"
    })
    system_log(f"[Agent] Broadcast task_started: {agent_name}")

    # Log context breakdown
    log(f"[Agent] === Context Summary ===")
    log(f"[Agent]   Mode: {'chat (prompt_override)' if is_chat_mode else 'agent'}")
    log(f"[Agent]   Content: {len(effective_content)} chars")
    log(f"[Agent]   Task ID: {task_id or 'none'}")
    log(f"[Agent]   Dry-run: {dry_run}")
    log(f"[Agent]   Test folder: {test_folder or 'none'}")
    log(f"[Agent]   Backend override: {backend or 'none'}")
    log(f"[Agent] =========================")

    # AI Backend: use override if provided (resolved by AgentTask), else from agent config
    if backend:
        ai_backend = backend
        log(f"[Agent] Using backend override: {backend}")
    else:
        # agent_config already loaded from discovery service above
        ai_backend = agent_config.get("ai")

    # Initial prompt: use prompt_override for chat, agent content otherwise
    current_prompt = effective_content
    max_confirmations = 5  # Prevent infinite loops
    max_continuation_rounds = 20  # Prevent infinite continuation loops
    continuation_round = 0
    # [068] Accumulate anonymization mappings across confirmation/continuation rounds
    # Each call_agent() creates a fresh AnonymizationContext, losing previous mappings.
    # We accumulate here so PII display shows ALL entities from ALL rounds.
    accumulated_anon_mappings = {}
    total_processed = 0
    all_responses = []  # Collect all responses for continuation summary

    # [069] Create TaskContext BEFORE the multi-round loop so it persists
    # across confirmation/continuation rounds. This replaces the [068] workaround
    # of passing previous_anon_context as a parameter.
    import uuid
    if not task_id:
        name_part = (agent_name or "agent")[:20]
        task_id = f"{name_part}-{str(uuid.uuid4())[:4]}"

    # Resolve backend name for TaskContext
    _backend_name = ai_backend or ai_agent.get_default_backend(config)

    ctx = ai_agent.create_task_context(
        task_id=task_id,
        backend_name=_backend_name,
        dry_run_mode=dry_run,
        test_folder=test_folder,
        session_id=session_id
    )
    log(f"[Agent] TaskContext created for multi-round loop: task_id={task_id}")

    try:
        while continuation_round <= max_continuation_rounds:
            continuation_round += 1

            if continuation_round > 1:
                log(f"[Agent] === CONTINUATION ROUND {continuation_round} ===")

            for confirmation_round in range(max_confirmations + 1):
                # AI Agent mit Tool-Zugriff aufrufen
                log(f"[Info] Rufe AI Agent auf..." +
                    (f" (Backend: {ai_backend})" if ai_backend else "") +
                    (f" (Confirmation round: {confirmation_round + 1})" if confirmation_round > 0 else ""))

                result = ai_agent.call_agent(
                    current_prompt, config,
                    use_tools=True,
                    agent_name=ai_backend,
                    on_chunk=on_chunk,
                    task_name=agent_name,
                    task_type="agent",
                    is_cancelled=is_cancelled,
                    dry_run=dry_run,
                    test_folder=test_folder,
                    task_id=task_id,
                    session_id=session_id,
                    disable_anon=disable_anon,
                    task_context=ctx
                )

                # [069] anon_context is now persisted in ctx automatically via call_agent()
                # No need to manually track previous_anon_context

                # Check for cancellation first
                if result.cancelled:
                    log(f"[Agent] Task cancelled by user")
                    notify("Agent abgebrochen", "DeskAgent", icon)
                    set_tray_idle()  # Reset tray status
                    broadcast_global_event("task_ended", {
                        "task_id": task_id or f"auto-{agent_name}",
                        "name": agent_name,
                        "type": "agent",
                        "status": "cancelled"
                    })
                    stats = {
                        "model": result.model,
                        "duration_seconds": result.duration_seconds,
                        "cancelled": True
                    }
                    return False, "Cancelled by user", stats

                if not result.success:
                    log(f"[Fehler] {result.error}")
                    notify(f"Fehler: {result.error[:100] if result.error else 'Unbekannt'}", "Fehler", icon)
                    set_tray_idle()  # Reset tray status
                    broadcast_global_event("task_ended", {
                        "task_id": task_id or f"auto-{agent_name}",
                        "name": agent_name,
                        "type": "agent",
                        "status": "error"
                    })
                    stats = {
                        "model": result.model,
                        "duration_seconds": result.duration_seconds
                    }
                    return False, result.error or "Unbekannter Fehler", stats

                # Check for confirmation request in response
                # [060] Use raw_output for dialog detection (Gemini's _clean_gemini_response
                # strips markers from "thought" blocks, but raw_output preserves them)
                dialog_source = getattr(result, 'raw_output', None) or result.content
                system_log(f"[Agent] ========== CONFIRMATION CHECK ==========")
                system_log(f"[Agent] task_id = {task_id}")
                system_log(f"[Agent] response length = {len(result.content)} chars")
                system_log(f"[Agent] dialog_source length = {len(dialog_source)} chars (raw_output={'raw_output' in dir(result)})")
                system_log(f"[Agent] response preview: {result.content[:200]}...")
                system_log(f"[Agent] 'QUESTION_NEEDED' in dialog_source = {'QUESTION_NEEDED' in dialog_source}")
                system_log(f"[Agent] 'CONFIRMATION_NEEDED' in dialog_source = {'CONFIRMATION_NEEDED' in dialog_source}")

                confirm_data = interaction.parse_confirmation_request(dialog_source)
                system_log(f"[Agent] parse_confirmation_request returned: {confirm_data}")
                system_log(f"[Agent] confirm_data is truthy: {bool(confirm_data)}")
                system_log(f"[Agent] task_id is truthy: {bool(task_id)}")
                system_log(f"[Agent] Will show dialog: {bool(confirm_data and task_id)}")
                system_log(f"[Agent] ==========================================")

                if confirm_data and task_id:
                    system_log(f"[Agent] >>> SHOWING CONFIRMATION DIALOG <<<")
                    log(f"[Agent] Confirmation needed: {confirm_data.get('question', '?')}")

                    # [062] STEP 1: Extract anon_mappings FIRST (moved from below)
                    # Support both formats: nested {"mappings": {...}} and flat {"<X>": "Y"}
                    anon_mappings = None
                    if result.anonymization and isinstance(result.anonymization, dict):
                        anon_mappings = result.anonymization.get("mappings")
                        if anon_mappings is None:
                            # Fallback: flat format - check if keys look like placeholders
                            if any(k.startswith("<") for k in result.anonymization.keys()):
                                anon_mappings = result.anonymization
                        if anon_mappings:
                            log(f"[Agent] Passing {len(anon_mappings)} anonymization mappings to confirmation dialog")

                    # [062] STEP 2: De-anonymize confirm_data parsed from raw_output
                    # Plan-060 uses raw_output for dialog detection (Gemini thought-block
                    # cleanup strips markers), but raw_output is not de-anonymized
                    if anon_mappings:
                        from assistant.interaction import _deanonymize_value, _deanonymize_data
                        if confirm_data.get("data"):
                            confirm_data["data"] = _deanonymize_data(confirm_data["data"], anon_mappings)
                        if confirm_data.get("question"):
                            confirm_data["question"] = _deanonymize_value(confirm_data["question"], anon_mappings)
                        if confirm_data.get("preamble"):
                            confirm_data["preamble"] = _deanonymize_value(confirm_data["preamble"], anon_mappings)
                        log(f"[Agent] De-anonymized confirm_data with {len(anon_mappings)} mappings")

                    # FIX [051]: Store greeting (preamble) in task for sync polling clients
                    greeting = confirm_data.get("preamble", "")
                    if greeting:
                        try:
                            from assistant.core.state import update_task
                            update_task(task_id, greeting=greeting)
                            system_log(f"[Agent] Stored greeting in task ({len(greeting)} chars)")
                        except Exception as e:
                            system_log(f"[Agent] Could not store greeting: {e}")

                    # Store preamble (text before QUESTION/CONFIRMATION) as assistant turn for history
                    preamble = confirm_data.get("preamble", "")
                    if preamble:
                        try:
                            from assistant.core.state import add_turn_to_session
                            add_turn_to_session("assistant", preamble, task_id=task_id, session_id=session_id)
                            log(f"[Agent] Stored preamble as assistant turn ({len(preamble)} chars)")
                        except Exception as e:
                            log(f"[Agent] Could not store preamble turn: {e}")

                    # Get on_cancel settings from confirmation data
                    on_cancel = confirm_data.get("on_cancel", "abort")
                    on_cancel_message = confirm_data.get("on_cancel_message", "")

                    # Get dialog type and options for question dialogs
                    dialog_type = confirm_data.get("type", "")
                    options = confirm_data.get("options", [])

                    # Publish SSE event to notify UI about pending confirmation
                    system_log(f"[Agent] Publishing pending_input SSE event for task {task_id}")
                    publish_pending_input(
                        task_id,
                        confirm_data.get("question", "Bitte bestätigen"),
                        options=options,
                        data=confirm_data.get("data", {}),
                        editable_fields=confirm_data.get("editable_fields")
                    )

                    # Request user confirmation (blocks until user responds)
                    user_response = interaction.request_confirmation(
                        task_id,
                        confirm_data.get("question", "Bitte bestätigen"),
                        confirm_data.get("data", {}),
                        confirm_data.get("editable_fields"),
                        anon_mappings=anon_mappings,
                        on_cancel=on_cancel,
                        on_cancel_message=on_cancel_message,
                        dialog_type=dialog_type,
                        options=options
                    )

                    if not user_response.get("confirmed"):
                        # Check if we should continue despite cancellation
                        resp_on_cancel = user_response.get("on_cancel", "abort")
                        resp_on_cancel_message = user_response.get("on_cancel_message", "")

                        if resp_on_cancel == "continue" and resp_on_cancel_message:
                            # User cancelled but we should continue with alternative action
                            log(f"[Agent] User cancelled, continuing with alternative: {resp_on_cancel_message[:100]}...")

                            # Check if user provided notes for correction
                            user_data = user_response.get("data", {})
                            user_notes = user_data.get("_user_notes", "")

                            # Build continuation prompt with the cancel message, previous response, and optional user notes
                            # IMPORTANT: Agent content BEFORE ### Input: marker so it's NOT anonymized
                            # Only user data (notes, dialog data, previous response) goes AFTER ### Input:
                            if user_notes:
                                log(f"[Agent] User notes: {user_notes[:100]}...")
                                current_prompt = f"""{resp_on_cancel_message}
Bitte fahre mit der ursprünglichen Aufgabe fort (wichtig: nutze den Kontext aus deiner vorherigen Antwort!):
{agent["content"]}

### Input:
Der Benutzer hat folgende Notizen/Korrekturen angegeben:
{user_notes}

Die aktuellen Daten aus dem Dialog waren:
{json.dumps({k: v for k, v in user_data.items() if not k.startswith('_')}, ensure_ascii=False)}

Deine vorherige Antwort war:
---
{result.content}
---
### Output:
"""
                            else:
                                current_prompt = f"""{resp_on_cancel_message}
Bitte fahre mit der ursprünglichen Aufgabe fort (wichtig: nutze den Kontext aus deiner vorherigen Antwort!):
{agent["content"]}

### Input:
Deine vorherige Antwort war:
---
{result.content}
---
### Output:
"""
                            continue  # Next confirmation round with alternative action

                        # Otherwise abort
                        error_msg = user_response.get("error", "Vom Benutzer abgebrochen")
                        log(f"[Agent] Confirmation cancelled: {error_msg}")
                        notify("Abgebrochen", "Agent", icon)
                        set_tray_idle()  # Reset tray status
                        broadcast_global_event("task_ended", {
                            "task_id": task_id or f"auto-{agent_name}",
                            "name": agent_name,
                            "type": "agent",
                            "status": "cancelled"
                        })
                        return False, error_msg, None

                    # Continue with confirmed/edited data
                    log(f"[Agent] Confirmation received, continuing...")

                    # [063] Wait for frontend to reconnect SSE before starting Round 2
                    interaction.wait_for_round_ready(task_id, timeout=10.0)

                    confirmed_data = json.dumps(user_response.get("data", {}), ensure_ascii=False)
                    log(f"[Agent] Confirmed data: {confirmed_data}")

                    # Get session context for continuation (preserves names, emails, previous decisions)
                    session_context = ""
                    if session_id:
                        session_context = session_store.get_session_context(session_id)
                        if session_context:
                            log(f"[Agent] Session context loaded ({len(session_context)} chars)")

                    # Build continuation prompt WITH previous AI response AND session context
                    # This is critical for backends like Gemini that don't maintain conversation history
                    # IMPORTANT: Explicitly tell the model to EXECUTE the tool calls, not just say it's done!
                    # IMPORTANT: Agent content BEFORE ### Input: marker so it's NOT anonymized
                    # Only user data (confirmed data, previous response) goes AFTER ### Input:
                    context_prefix = f"## Vorheriger Konversationskontext\n\n{session_context}\n---\n\n" if session_context else ""
                    current_prompt = f"""{context_prefix}**WICHTIG: JETZT DIE ÄNDERUNGEN TATSÄCHLICH AUSFÜHREN!**

{"Nutze den Konversationskontext oben für korrekte Namen, E-Mail-Adressen und Details." if session_context else ""}
Du hast die Bestätigung erhalten. Führe nun die angekündigten Aktionen durch:
- Rufe die entsprechenden Tools auf (z.B. update_document, create_correspondent)
- Verwende die korrekten Daten aus dem Kontext (Namen, Adressen, Termine)
- Sage nicht nur dass du es machst - FÜHRE die Tool-Aufrufe tatsächlich aus!
- Zeige den Fortschritt pro Dokument/Aktion

**KRITISCH: Die folgenden Daten wurden bereits vom Benutzer bestaetigt und ggf. korrigiert. Diese Werte ERSETZEN alle vorher extrahierten Daten vollständig! Wenn die bestätigten Daten von deiner vorherigen Analyse abweichen, verwende IMMER die bestätigten Werte! Da diese Daten bereits vom Benutzer bestaetigt wurden, frage NICHT erneut danach!**

Ursprüngliche Aufgabe zur Referenz:
{agent["content"]}

### Input:
✅ VOM BENUTZER BESTÄTIGTE DATEN (diese haben Vorrang vor allem anderen):

{confirmed_data}

Deine vorherige Analyse (NUR als Kontext für die Aufgabe - bei Widersprüchen zu den bestätigten Daten oben gelten die bestätigten Daten!):
---
{result.content}
---
### Output:
"""

                    continue  # Next confirmation round with confirmed data

                # No confirmation needed - exit confirmation loop
                break

            # Confirmation loop complete - check for continuation request
            # Only check if not already parsed as QUESTION_NEEDED or CONFIRMATION_NEEDED
            continuation_data = None
            if not confirm_data:
                continuation_data = interaction.parse_continuation_request(result.content)

            if continuation_data:
                # Check if agent allows continuation
                if agent_config.get("allow_continuation", False):
                    log(f"[Agent] Continuation needed: {continuation_data.get('message')}")
                    log(f"[Agent] Remaining: {continuation_data.get('remaining', '?')}")
                    log(f"[Agent] Processed this round: {continuation_data.get('processed', '?')}")

                    # Track progress
                    if continuation_data.get("processed"):
                        total_processed += continuation_data["processed"]

                    # Store response for summary
                    all_responses.append(result.content)

                    # Build continuation prompt - re-run the original agent
                    current_prompt = f"""CONTINUATION - Fortsetzung der Batch-Verarbeitung

Vorherige Durchlaeufe: {continuation_round}
Bisher verarbeitet: {total_processed} Eintraege

Bitte fahre mit der naechsten Batch fort. Beginne dort, wo du aufgehoert hast.

---
Urspruengliche Aufgabe:
{agent["content"]}"""

                    # Stream a continuation notice to UI
                    if on_chunk:
                        on_chunk(f"\n\n---\n**Fortsetzung** (Runde {continuation_round + 1}): {continuation_data.get('message')}\n---\n\n")

                    continue  # Next continuation round
                else:
                    log(f"[Agent] Continuation requested but not allowed for agent {agent_name}")
                    log(f"[Agent] Set 'allow_continuation: true' in agent frontmatter to enable")

            # No continuation needed or not allowed - we're done with all loops
            break

        # Check if we hit the max continuation limit
        if continuation_round > max_continuation_rounds:
            log(f"[Agent] WARNING: Reached max continuation rounds ({max_continuation_rounds})")

        # Success (Windows only sound)
        if winsound:
            winsound.PlaySound(r"C:\Windows\Media\chimes.wav", winsound.SND_FILENAME)
        log(f"\n{'-'*50}")
        log(result.content[:500] + ("..." if len(result.content) > 500 else ""))
        log(f"{'-'*50}")
        # Use different notification for chat mode vs agent mode
        if is_chat_mode:
            notify("Chat fertig!", "Fertig", icon)
        else:
            notify(f"Agent {agent['name']} fertig!", "Fertig", icon)

        # Reset tray status to idle
        set_tray_idle()

        # Build stats dict with all available info
        stats = {
            "anonymization": result.anonymization,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "duration_seconds": result.duration_seconds,
            "cost_usd": result.cost_usd,
            "dry_run": dry_run
        }
        # Include simulated actions if available from result
        if hasattr(result, 'simulated_actions') and result.simulated_actions:
            stats["simulated_actions"] = result.simulated_actions

        # SDK Extended Mode: Include session ID for resume capability
        if hasattr(result, 'sdk_session_id') and result.sdk_session_id:
            stats["sdk_session_id"] = result.sdk_session_id
            stats["can_resume"] = getattr(result, 'can_resume', False)

        # Broadcast task_ended for WebUI running badges
        broadcast_global_event("task_ended", {
            "task_id": task_id or f"auto-{agent_name}",
            "name": agent_name,
            "type": "agent",
            "status": "done"
        })

        return True, result.content, stats

    finally:
        # [069] Task-level cleanup: clear TaskContext and PII data
        # This runs even on early returns (cancel, error) to prevent PII leaks
        try:
            _ctx = ai_agent.get_task_context_or_none()
            if _ctx and _ctx.anon_context:
                mapping_count = len(_ctx.anon_context.mappings)
                if mapping_count > 100:
                    log(f"[Agent] WARNING: Large PII mapping count ({mapping_count}) - potential memory growth")
                _ctx.anon_context.mappings.clear()
                _ctx.anon_context.reverse_mappings.clear()
                log(f"[Agent] PII mappings cleared ({mapping_count} entries)")
        except Exception as e:
            log(f"[Agent] Error clearing PII mappings: {e}")

        ai_agent.clear_dev_context(task_id)
        ai_agent.clear_task_context()
        log(f"[Agent] TaskContext cleared in finally block: task_id={task_id}")
