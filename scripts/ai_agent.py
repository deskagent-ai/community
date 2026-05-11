# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Agent - Legacy Modul für AI-Aufrufe
======================================
HINWEIS: Dieses Modul ist veraltet.
Die modernen Implementierungen befinden sich im Package:
    deskagent/scripts/ai_agent/

Aktuelle Backends (im ai_agent/ Package):
- claude_agent_sdk: Claude Agent SDK (empfohlen)
- claude_api: Anthropic API direkt
- gemini_adk: Google Gemini API
- openai_api: OpenAI GPT API
- ollama_native: Ollama (lokal)
- qwen_agent: Qwen via Ollama

Dieses Legacy-Modul unterstützt nur:
- claude_cli: Claude Code CLI
- ollama: Ollama REST API
"""

import json
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable

try:
    import requests
except ImportError:
    requests = None

# Import centralized path management
try:
    from paths import DESKAGENT_DIR
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from paths import DESKAGENT_DIR

PROJECT_DIR = DESKAGENT_DIR  # For backward compatibility

# Logging-Funktion (wird von außen gesetzt)
_log_func: Optional[Callable[[str], None]] = None
_console_logging: bool = True  # Standard: aktiviert


def set_logger(log_func: Callable[[str], None]):
    """Setzt die Logging-Funktion."""
    global _log_func
    _log_func = log_func


def set_console_logging(enabled: bool):
    """Aktiviert/deaktiviert Console-Logging."""
    global _console_logging
    _console_logging = enabled


def log(message: str):
    """Gibt Nachricht aus, wenn Logger gesetzt und console_logging aktiv."""
    if _log_func and _console_logging:
        _log_func(message)


@dataclass
class AgentResponse:
    """Antwort vom AI Agent."""
    success: bool
    content: str
    error: Optional[str] = None
    raw_output: Optional[str] = None


def get_agent_config(config: dict, agent_name: str = None) -> dict:
    """
    Holt die Konfiguration für einen bestimmten AI-Backend.

    Args:
        config: Die Haupt-Konfiguration aus config.json
        agent_name: Name des Backends (z.B. "claude", "qwen") oder None für Default

    Returns:
        Agent-Konfiguration als dict
    """
    # Multi-Backend-Konfiguration
    agents = config.get("ai_backends", {})

    if agents:
        default_name = config.get("default_ai", "claude")
        name = agent_name or default_name
        return agents.get(name, agents.get(default_name, {}))
    else:
        # Fallback auf altes Format
        return config.get("ai_agent", {})


def call_agent(prompt: str, config: dict, use_tools: bool = False, agent_name: str = None, continue_conversation: bool = False) -> AgentResponse:
    """
    Ruft den konfigurierten AI Agent auf.

    Args:
        prompt: Der Prompt für den Agent
        config: Die Konfiguration aus config.json
        use_tools: Wenn True, läuft Claude mit MCP-Tool-Zugriff
        agent_name: Optional - Name des AI-Backends (z.B. "claude", "qwen")
        continue_conversation: Wenn True, führe letzte Conversation fort (nur Claude CLI)

    Returns:
        AgentResponse mit Ergebnis oder Fehler
    """
    # Console-Logging aus Config setzen
    set_console_logging(config.get("console_logging", True))

    agent_config = get_agent_config(config, agent_name)
    agent_type = agent_config.get("type", "claude_cli")

    log(f"[AI Agent] Type: {agent_type}" + (f" ({agent_name})" if agent_name else "") + (" (continue)" if continue_conversation else ""))

    if agent_type == "claude_cli":
        return _call_claude_cli(prompt, config, agent_config, use_tools, continue_conversation)
    elif agent_type == "anthropic_api":
        return _call_anthropic_api(prompt, config, agent_config)
    elif agent_type == "openai":
        return _call_openai(prompt, config, agent_config)
    elif agent_type == "ollama":
        return _call_ollama(prompt, config, agent_config)
    else:
        return AgentResponse(
            success=False,
            content="",
            error=f"Unbekannter Agent-Typ: {agent_type}"
        )


def _call_claude_cli(prompt: str, config: dict, agent_config: dict, use_tools: bool = False, continue_conversation: bool = False) -> AgentResponse:
    """Ruft Claude Code CLI auf.

    Args:
        prompt: Der Prompt
        config: Haupt-Konfiguration
        agent_config: Agent-spezifische Konfiguration
        use_tools: Wenn True, nutze -p Flag für MCP-Tool-Zugriff
        continue_conversation: Wenn True, führe letzte Conversation fort
    """
    # Fallback auf alte config-Struktur für Kompatibilität
    claude_path = agent_config.get("path") or config.get("claude_path", "claude")
    timeout = agent_config.get("timeout") or config.get("timeout", 120)

    log(f"[AI Agent] Claude CLI: {claude_path}")
    log(f"[AI Agent] Timeout: {timeout}s")
    log(f"[AI Agent] Tools enabled: {use_tools}")
    log(f"[AI Agent] Continue conversation: {continue_conversation}")

    try:
        if use_tools:
            # Mit Tool-Zugriff: -p Flag, Claude kann MCP-Tools nutzen
            # --dangerously-skip-permissions: Keine interaktive Bestätigung für Tools
            # --allowedTools: Explizit erlaubte MCP-Tools
            # --mcp-config: Expliziter Pfad zur MCP-Konfiguration
            allowed_tools = "mcp__outlook__*,mcp__billomat__*"
            mcp_config = str(PROJECT_DIR / ".mcp.json")

            log(f"[AI Agent] MCP Config: {mcp_config}")
            log(f"[AI Agent] Prompt length: {len(prompt)}")

            # Prompt über stdin senden statt -p (vermeidet Escaping-Probleme)
            cmd = [
                claude_path,
                "--output-format", "text",
                "--dangerously-skip-permissions",
                "--allowedTools", allowed_tools,
                "--mcp-config", mcp_config
            ]
            if continue_conversation:
                cmd.append("--continue")
            log(f"[AI Agent] Command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                shell=True
            )
        else:
            # Ohne Tools: stdin, nur Text-Verarbeitung
            cmd = [claude_path]
            if continue_conversation:
                cmd.append("--continue")
            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                shell=True
            )

        log(f"[AI Agent] Return code: {result.returncode}")
        log(f"[AI Agent] Stdout length: {len(result.stdout) if result.stdout else 0}")

        if result.stderr:
            log(f"[AI Agent] Stderr: {result.stderr[:200]}")

        if result.returncode != 0:
            return AgentResponse(
                success=False,
                content="",
                error=result.stderr[:200] if result.stderr else "Non-zero return code",
                raw_output=result.stdout
            )

        if not result.stdout or not result.stdout.strip():
            return AgentResponse(
                success=False,
                content="",
                error="Leere Antwort vom Agent"
            )

        return AgentResponse(
            success=True,
            content=result.stdout.strip(),
            raw_output=result.stdout
        )

    except subprocess.TimeoutExpired:
        return AgentResponse(
            success=False,
            content="",
            error=f"Timeout nach {timeout}s"
        )
    except Exception as e:
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


def _call_anthropic_api(prompt: str, config: dict, agent_config: dict) -> AgentResponse:
    """Legacy-Stub für Anthropic API.

    HINWEIS: Verwende stattdessen das moderne ai_agent/ Package:
        from ai_agent import call_agent
        call_agent(prompt, config, agent_name="claude_api")
    """
    return AgentResponse(
        success=False,
        content="",
        error="Verwende ai_agent.call_agent() mit agent_name='claude_api'"
    )


def _call_openai(prompt: str, config: dict, agent_config: dict) -> AgentResponse:
    """Legacy-Stub für OpenAI API.

    HINWEIS: Verwende stattdessen das moderne ai_agent/ Package:
        from ai_agent import call_agent
        call_agent(prompt, config, agent_name="openai")
    """
    return AgentResponse(
        success=False,
        content="",
        error="Verwende ai_agent.call_agent() mit agent_name='openai'"
    )


def _call_ollama(prompt: str, config: dict, agent_config: dict) -> AgentResponse:
    """Ruft Ollama REST API auf (lokal oder remote)."""
    if not requests:
        return AgentResponse(
            success=False,
            content="",
            error="requests Modul nicht installiert. Installiere mit: pip install requests"
        )

    base_url = agent_config.get("base_url", "http://localhost:11434")
    model = agent_config.get("model", "qwen2.5:32b")
    timeout = agent_config.get("timeout", 180)

    log(f"[AI Agent] Ollama URL: {base_url}")
    log(f"[AI Agent] Model: {model}")
    log(f"[AI Agent] Timeout: {timeout}s")
    log(f"[AI Agent] Prompt length: {len(prompt)}")

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=timeout
        )

        log(f"[AI Agent] HTTP Status: {response.status_code}")

        if response.ok:
            data = response.json()
            content = data.get("response", "")

            if not content or not content.strip():
                return AgentResponse(
                    success=False,
                    content="",
                    error="Leere Antwort von Ollama"
                )

            log(f"[AI Agent] Response length: {len(content)}")
            return AgentResponse(
                success=True,
                content=content.strip(),
                raw_output=content
            )
        else:
            error_text = response.text[:200] if response.text else f"HTTP {response.status_code}"
            return AgentResponse(
                success=False,
                content="",
                error=f"Ollama Fehler: {error_text}"
            )

    except requests.exceptions.Timeout:
        return AgentResponse(
            success=False,
            content="",
            error=f"Timeout nach {timeout}s"
        )
    except requests.exceptions.ConnectionError as e:
        return AgentResponse(
            success=False,
            content="",
            error=f"Verbindung zu Ollama fehlgeschlagen: {base_url}"
        )
    except Exception as e:
        return AgentResponse(
            success=False,
            content="",
            error=str(e)
        )


def extract_json(response: str) -> Optional[dict]:
    """
    Extrahiert JSON aus einer Agent-Antwort.
    Behandelt Markdown-Codeblocks und Text drumherum.

    Args:
        response: Die rohe Antwort vom Agent

    Returns:
        Parsed JSON als dict oder None bei Fehler
    """
    text = response.strip()

    # Entferne Markdown-Codeblocks
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()

    # Suche JSON-Objekt falls noch Text drumherum
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
