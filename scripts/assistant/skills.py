# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Skill loading and processing for DeskAgent.
"""

import json
import sys
import time
from pathlib import Path

# winsound is Windows-only
try:
    import winsound
except ImportError:
    winsound = None

import ai_agent
from .clipboard import get_clipboard, set_clipboard

# Path is set up by assistant/__init__.py
from paths import (
    PROJECT_DIR,
    get_skills_dir,
    get_knowledge_dir,
    get_context_dir,
    load_config as load_config_from_paths,
)

CONTEXT_DIR = get_context_dir()

# Skill context settings
CONTEXT_TIMEOUT_SECONDS = 600  # 10 minutes - context expires after this
MAX_CONTEXT_ENTRIES = 20  # Keep last N interactions per skill


def load_config():
    """Lädt Konfiguration aus modularen config/*.json Dateien."""
    return load_config_from_paths()


def load_knowledge():
    """Lädt alle Knowledge-Dateien (User-Space oder Demo-Fallback)."""
    knowledge = ""
    knowledge_dir = get_knowledge_dir()
    if knowledge_dir.exists():
        for f in knowledge_dir.glob("*.md"):
            knowledge += f"\n\n### {f.name}:\n{f.read_text(encoding='utf-8')}"
    return knowledge


def _find_skill_file(skill_name: str):
    """Sucht Skill-Datei in User-Space zuerst, dann in deskagent/skills/.

    Prüft beide Verzeichnisse, damit System-Skills (grammar, summarize, translate)
    auch funktionieren wenn User eigene Skills hat.
    """
    import paths
    search_dirs = [
        get_skills_dir(),
        paths.DESKAGENT_DIR / "skills"
    ]
    for search_dir in search_dirs:
        candidate = search_dir / f"{skill_name}.md"
        if candidate.exists():
            return candidate
    return None


def load_skill(skill_name: str) -> dict | None:
    """Lädt einen Skill aus skills/ Ordner (User-Space zuerst, dann deskagent/)."""
    skill_file = _find_skill_file(skill_name)
    if not skill_file:
        return None

    content = skill_file.read_text(encoding="utf-8")
    skill = {
        "name": skill_name,
        "use_knowledge": True,
        "content": content
    }

    for line in content.split("\n"):
        if line.startswith("name:"):
            skill["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("use_knowledge:"):
            skill["use_knowledge"] = "true" in line.lower()

    return skill


def notify(message: str, title: str = "DeskAgent", icon=None):
    """Benachrichtigung auf Console UND Tray."""
    ai_agent.log(f"[{title}] {message}")
    if icon:
        icon.notify(message, title)


# === SKILL CONTEXT MANAGEMENT ===

def _get_context_file(skill_name: str) -> Path:
    """Get the context file path for a skill."""
    CONTEXT_DIR.mkdir(exist_ok=True)
    return CONTEXT_DIR / f"{skill_name}.json"


def load_skill_context(skill_name: str) -> list:
    """
    Load conversation context for a skill.
    Returns list of {input, output, timestamp} entries.
    Automatically clears expired context.
    """
    context_file = _get_context_file(skill_name)
    if not context_file.exists():
        return []

    try:
        data = json.loads(context_file.read_text(encoding="utf-8"))
        entries = data.get("entries", [])

        # Check if context has expired
        if entries:
            last_timestamp = entries[-1].get("timestamp", 0)
            if time.time() - last_timestamp > CONTEXT_TIMEOUT_SECONDS:
                ai_agent.log(f"[Context] Skill '{skill_name}' context expired, clearing")
                clear_skill_context(skill_name)
                return []

        return entries
    except Exception as e:
        ai_agent.log(f"[Context] Error loading context for '{skill_name}': {e}")
        return []


def save_skill_context(skill_name: str, input_text: str, output_text: str):
    """
    Save an interaction to the skill context.
    Keeps only the last MAX_CONTEXT_ENTRIES entries.
    """
    context_file = _get_context_file(skill_name)
    entries = load_skill_context(skill_name)

    # Add new entry
    entries.append({
        "input": input_text[:500],  # Truncate to save space
        "output": output_text[:500],
        "timestamp": time.time()
    })

    # Keep only last N entries
    entries = entries[-MAX_CONTEXT_ENTRIES:]

    try:
        context_file.write_text(
            json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        ai_agent.log(f"[Context] Saved context for '{skill_name}' ({len(entries)} entries)")
    except Exception as e:
        ai_agent.log(f"[Context] Error saving context for '{skill_name}': {e}")


def clear_skill_context(skill_name: str) -> bool:
    """Clear the context for a specific skill."""
    context_file = _get_context_file(skill_name)
    if context_file.exists():
        context_file.unlink()
        ai_agent.log(f"[Context] Cleared context for '{skill_name}'")
        return True
    return False


def clear_all_skill_contexts() -> int:
    """Clear all skill contexts. Returns number of cleared files."""
    if not CONTEXT_DIR.exists():
        return 0

    count = 0
    for f in CONTEXT_DIR.glob("*.json"):
        f.unlink()
        count += 1

    if count:
        ai_agent.log(f"[Context] Cleared all skill contexts ({count} files)")
    return count


def get_active_skill_contexts() -> dict:
    """Get info about all active (non-expired) skill contexts."""
    if not CONTEXT_DIR.exists():
        return {}

    result = {}
    now = time.time()

    for f in CONTEXT_DIR.glob("*.json"):
        skill_name = f.stem
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            if entries:
                last_ts = entries[-1].get("timestamp", 0)
                age_seconds = now - last_ts
                if age_seconds <= CONTEXT_TIMEOUT_SECONDS:
                    result[skill_name] = {
                        "entries": len(entries),
                        "age_seconds": int(age_seconds),
                        "expires_in": int(CONTEXT_TIMEOUT_SECONDS - age_seconds)
                    }
        except (KeyError, TypeError, ValueError):
            pass

    return result


def format_context_for_prompt(entries: list) -> str:
    """Format context entries as a prompt section."""
    if not entries:
        return ""

    lines = ["### Vorherige Interaktionen (für Stil-Konsistenz):"]
    for i, entry in enumerate(entries, 1):
        lines.append(f"\n**{i}. Input:** {entry['input']}")
        lines.append(f"**{i}. Output:** {entry['output']}")

    lines.append("\nBitte behalte den gleichen Stil und Ton wie in den vorherigen Ausgaben bei, es sei denn es wird explizit anders gewünscht.")
    return "\n".join(lines)


def process_skill(skill_name: str, hints: str = "", icon=None, on_chunk: callable = None):
    """Führt einen Skill mit Clipboard-Inhalt aus. Gibt (success, content) zurück."""
    config = load_config()
    ai_agent.log(f"[Skill] Loading skill: {skill_name}")
    skill = load_skill(skill_name)

    if not skill:
        ai_agent.log(f"[Skill] ERROR: Skill '{skill_name}' nicht gefunden!")
        notify(f"Skill '{skill_name}' nicht gefunden!", "Fehler", icon)
        return False, f"Skill '{skill_name}' nicht gefunden", None

    # Clipboard lesen
    text = get_clipboard()
    if not text.strip():
        ai_agent.log(f"[Skill] ERROR: Kein Text in Zwischenablage!")
        notify("Kein Text in Zwischenablage!", "Fehler", icon)
        return False, "Kein Text in Zwischenablage", None

    ai_agent.log(f"\n{'='*50}")
    ai_agent.log(f"[{skill['name']}] Verarbeite {len(text)} Zeichen...")
    ai_agent.log(f"{'='*50}")
    notify(f"Verarbeite mit {skill['name']}...", "DeskAgent", icon)

    # Skill-Kontext laden (vorherige Interaktionen)
    skill_context_entries = load_skill_context(skill_name)
    skill_context_section = format_context_for_prompt(skill_context_entries)
    if skill_context_entries:
        ai_agent.log(f"[Context] Loaded {len(skill_context_entries)} previous interactions")

    # Knowledge laden
    knowledge = ""
    if skill.get("use_knowledge", True):
        knowledge = load_knowledge()
        if knowledge:
            ai_agent.log("[Info] Knowledge geladen")

    # Prompt erstellen
    context = config.get("context", "")
    knowledge_section = f"\n### Kontext & Wissen:\n{context}\n{knowledge}" if knowledge else ""
    hints_section = f"\n### Zusätzliche Hinweise:\n{hints}" if hints else ""

    prompt = f"""{skill['content']}
{knowledge_section}
{hints_section}
{skill_context_section}

### Input:
{text}

### Output:"""

    # Log context breakdown
    ai_agent.log(f"[Skill] === Context Summary ===")
    ai_agent.log(f"[Skill]   Skill content: {len(skill['content'])} chars")
    ai_agent.log(f"[Skill]   Knowledge: {len(knowledge)} chars")
    ai_agent.log(f"[Skill]   Skill context: {len(skill_context_section)} chars ({len(skill_context_entries)} entries)")
    ai_agent.log(f"[Skill]   Input text: {len(text)} chars")
    ai_agent.log(f"[Skill]   Total prompt: {len(prompt)} chars")
    ai_agent.log(f"[Skill] =========================")

    # AI Backend: check global override first, then skill config
    global_override = config.get("global_ai_override")
    if global_override and global_override != "auto":
        ai_backend = global_override
        ai_agent.log(f"[Skill] Global AI override active: {global_override}")
    else:
        # Use discovery service for merged config (frontmatter + agents.json)
        try:
            from .services.discovery import get_skill_config
            skill_config = get_skill_config(skill_name) or {}
        except ImportError:
            skill_config = config.get("skills", {}).get(skill_name, {})
        ai_backend = skill_config.get("ai")

    # [069] Create TaskContext for skill execution (consistent with process_agent)
    import uuid
    _backend_name = ai_backend or ai_agent.get_default_backend(config)
    _task_id = f"{skill_name}-{str(uuid.uuid4())[:4]}"

    ctx = ai_agent.create_task_context(
        task_id=_task_id,
        backend_name=_backend_name
    )
    ai_agent.log(f"[Skill] TaskContext created: task_id={_task_id}")

    try:
        # AI Agent aufrufen
        ai_agent.log(f"[Info] Rufe AI Agent auf..." + (f" (Backend: {ai_backend})" if ai_backend else ""))
        result = ai_agent.call_agent(
            prompt, config,
            agent_name=ai_backend,
            on_chunk=on_chunk,
            task_name=skill_name,
            task_type="skill",
            task_context=ctx
        )
    finally:
        # [069] Cleanup: clear PII mappings and TaskContext
        try:
            if ctx.anon_context and ctx.anon_context.mappings:
                mapping_count = len(ctx.anon_context.mappings)
                ctx.anon_context.mappings.clear()
                ctx.anon_context.reverse_mappings.clear()
                ai_agent.log(f"[Skill] PII mappings cleared ({mapping_count} entries)")
        except Exception as e:
            ai_agent.log(f"[Skill] Error clearing PII mappings: {e}")

        ai_agent.clear_task_context()
        ai_agent.log(f"[Skill] TaskContext cleared: task_id={_task_id}")

    if result.success:
        set_clipboard(result.content)
        # Kontext speichern für nächsten Aufruf
        save_skill_context(skill_name, text, result.content)
        # Erfolgs-Signal: Chimes (Windows only)
        if winsound:
            winsound.PlaySound(r"C:\Windows\Media\chimes.wav", winsound.SND_FILENAME)
        ai_agent.log(f"\n{'-'*50}")
        ai_agent.log(result.content[:500] + ("..." if len(result.content) > 500 else ""))
        ai_agent.log(f"{'-'*50}")
        notify("Ergebnis in Zwischenablage!", "Fertig", icon)
        # Return with anonymization info if present
        return True, result.content, result.anonymization
    else:
        ai_agent.log(f"[Fehler] {result.error}")
        notify(f"Fehler: {result.error[:100] if result.error else 'Unbekannt'}", "Fehler", icon)
        return False, result.error or "Unbekannter Fehler", None
