# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Browser Integration Consent Management.

Manages user consent for browser integration feature with persistent state.
Consent is stored in workspace/.state/browser_consent.json
"""

import json
from pathlib import Path

# Import system_log for logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# Centralized timestamp utilities
try:
    from utils.timestamp import get_timestamp_iso
except ImportError:
    from datetime import datetime
    def get_timestamp_iso(): return datetime.now().isoformat()


def get_consent_file() -> Path:
    """Get path to consent state file."""
    from paths import get_state_dir
    return get_state_dir() / "browser_consent.json"


def has_consent() -> bool:
    """
    Check if user has given consent for browser integration.

    Returns:
        True if consent was given, False otherwise
    """
    consent_file = get_consent_file()

    if not consent_file.exists():
        return False

    try:
        with open(consent_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('consent_given', False)
    except Exception:
        return False


def grant_consent() -> bool:
    """
    Grant consent for browser integration.

    Returns:
        True on success, False on error
    """
    consent_file = get_consent_file()

    data = {
        'consent_given': True,
        'timestamp': get_timestamp_iso(),
        'version': '1.0'
    }

    try:
        with open(consent_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        system_log(f"[Consent] Error saving consent: {e}")
        return False


def revoke_consent() -> bool:
    """
    Revoke consent for browser integration.

    Returns:
        True on success, False on error
    """
    consent_file = get_consent_file()

    data = {
        'consent_given': False,
        'timestamp': get_timestamp_iso(),
        'version': '1.0'
    }

    try:
        with open(consent_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        system_log(f"[Consent] Error revoking consent: {e}")
        return False


def decline_consent() -> bool:
    """
    Decline consent for browser integration.

    Unlike revoke, this marks as explicitly declined so the dialog
    won't show again on page reload.

    Returns:
        True on success, False on error
    """
    consent_file = get_consent_file()

    data = {
        'consent_given': False,
        'declined': True,
        'timestamp': get_timestamp_iso(),
        'version': '1.0'
    }

    try:
        with open(consent_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        system_log(f"[Consent] Error declining consent: {e}")
        return False


def is_browser_disabled_in_config() -> bool:
    """Check if browser is disabled via config (e.g., headless server)."""
    try:
        from config import load_config
        config = load_config()
        browser_config = config.get('browser', {})
        return browser_config.get('enabled') is False
    except Exception:
        return False


def get_consent_info() -> dict:
    """
    Get full consent information.

    Returns:
        Dict with consent_given, declined, disabled_by_config, timestamp, version
    """
    # Check if browser is disabled in config (headless server)
    if is_browser_disabled_in_config():
        return {
            'consent_given': False,
            'declined': True,  # Treat as declined so dialog doesn't show
            'disabled_by_config': True,
            'timestamp': None,
            'version': None
        }

    consent_file = get_consent_file()

    if not consent_file.exists():
        return {
            'consent_given': False,
            'timestamp': None,
            'version': None
        }

    try:
        with open(consent_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            'consent_given': False,
            'timestamp': None,
            'version': None
        }


if __name__ == "__main__":
    # Test consent management - using print() for CLI test output
    print("Testing browser consent management...")

    print(f"State dir: {get_state_dir()}")
    print(f"Consent file: {get_consent_file()}")

    print(f"\nInitial consent: {has_consent()}")

    print("\nGranting consent...")
    grant_consent()
    print(f"Has consent: {has_consent()}")
    print(f"Consent info: {get_consent_info()}")

    print("\nRevoking consent...")
    revoke_consent()
    print(f"Has consent: {has_consent()}")
    print(f"Consent info: {get_consent_info()}")
