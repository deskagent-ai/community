# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
PII Anonymizer using Microsoft Presidio
========================================
GDPR-compliant anonymization for external AI services.

Architecture:
All presidio/spacy calls go through anonymizer_service.py subprocess.
This ensures dev and compiled builds behave identically.

The service handles spacy model loading and presidio analysis.

AGPL / Community Edition note:
- This module imports cleanly even when presidio / spacy are NOT installed.
- All presidio imports are lazy (inside functions) and only executed
  after `is_available()` returned True.
- `is_available()` queries the anonymizer subprocess; if the subprocess or
  spacy is missing, it returns False and the public functions degrade
  gracefully:
    - `anonymize()` / `anonymize_with_context()` return the input text
      unchanged with an empty `AnonymizationContext`.
    - `deanonymize()` is presidio-free and always works.
    - `should_anonymize()` returns False.
- The required public surface (`AnonymizationContext`, `is_available`,
  `anonymize`, `deanonymize`, `should_anonymize`, `anonymize_with_context`)
  is available without `pip install deskagent[anonymizer]`.
"""

import re
import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict
from pathlib import Path
from .logging import log

# Lazy flags
_service_available = None
_spacy_models_checked = False

# Cached anonymizer config
_anonymizer_config_cache = None


def _load_anonymizer_config() -> dict:
    """
    Load and merge anonymizer config from both system and user locations.

    Loads and merges:
    1. deskagent/config/anonymizer.json (system defaults)
    2. config/anonymizer.json (customer overrides)

    Returns merged config with combined whitelists.
    """
    global _anonymizer_config_cache
    if _anonymizer_config_cache is not None:
        return _anonymizer_config_cache

    merged = {"whitelist": [], "known_persons": [], "known_companies": [], "confidence_threshold": 0.75}

    try:
        from paths import DESKAGENT_DIR, PROJECT_DIR

        # 1. Load system defaults (deskagent/config/anonymizer.json)
        system_file = DESKAGENT_DIR / "config" / "anonymizer.json"
        if system_file.exists():
            try:
                system_config = json.loads(system_file.read_text(encoding="utf-8"))
                merged["whitelist"].extend(system_config.get("whitelist", []))
                merged["known_persons"].extend(system_config.get("known_persons", []))
                merged["known_companies"].extend(system_config.get("known_companies", []))
                # confidence_threshold from system config (can be overridden by user)
                if "confidence_threshold" in system_config:
                    merged["confidence_threshold"] = system_config["confidence_threshold"]
            except Exception as e:
                log(f"[Anonymizer] Error loading system config: {e}")

        # 2. Load customer overrides (config/anonymizer.json)
        user_file = PROJECT_DIR / "config" / "anonymizer.json"
        if user_file.exists():
            try:
                user_config = json.loads(user_file.read_text(encoding="utf-8"))
                merged["whitelist"].extend(user_config.get("whitelist", []))
                merged["known_persons"].extend(user_config.get("known_persons", []))
                merged["known_companies"].extend(user_config.get("known_companies", []))
                # User can override confidence_threshold
                if "confidence_threshold" in user_config:
                    merged["confidence_threshold"] = user_config["confidence_threshold"]
            except Exception as e:
                log(f"[Anonymizer] Error loading user config: {e}")

        # Deduplicate lists
        merged["whitelist"] = list(dict.fromkeys(merged["whitelist"]))
        merged["known_persons"] = list(dict.fromkeys(merged["known_persons"]))
        merged["known_companies"] = list(dict.fromkeys(merged["known_companies"]))

    except ImportError:
        # Fallback if paths module not available
        pass

    _anonymizer_config_cache = merged
    return _anonymizer_config_cache


def _get_merged_whitelist(system_config: dict) -> list:
    """
    Get merged whitelist from anonymizer config AND system config.

    Combines:
    - anonymizer.json whitelist (system + user merged)
    - system.json anonymization.whitelist (legacy/backward compat)

    Returns deduplicated list.
    """
    whitelist = set()

    # Load from anonymizer.json (merged system + user)
    anon_config = _load_anonymizer_config()
    whitelist.update(anon_config.get("whitelist", []))

    # Also load from system config (backward compatibility)
    sys_anon = system_config.get("anonymization", {})
    whitelist.update(sys_anon.get("whitelist", []))

    return list(whitelist)


def _get_embedded_python() -> Path:
    """Get path to embedded Python for proxy mode."""
    try:
        from paths import get_embedded_python
        return get_embedded_python()
    except ImportError:
        import sys
        return Path(sys.executable)


def _get_service_path() -> Path:
    """Get path to anonymizer_service.py."""
    # Compiled build: __file__ is embedded, use DESKAGENT_DIR
    try:
        from paths import DESKAGENT_DIR
        service_path = DESKAGENT_DIR / "scripts" / "ai_agent" / "anonymizer_service.py"
        if service_path.exists():
            return service_path
    except ImportError:
        pass
    # Dev fallback: .py file next to this module
    return Path(__file__).parent / "anonymizer_service.py"


def _call_service_subprocess(text: str, lang: str = "de", pii_types: list = None,
                              placeholder_format: str = "<{entity_type}_{index}>",
                              confidence_threshold: float = 0.75) -> Tuple[str, Dict]:
    """
    Call anonymizer service via subprocess (one-shot mode).

    Args:
        text: Text to anonymize
        lang: Language code
        pii_types: List of PII types to detect
        placeholder_format: Format string for placeholders

    Returns:
        Tuple of (anonymized_text, mappings dict)
    """
    python_path = _get_embedded_python()
    service_path = _get_service_path()

    if not service_path.exists():
        log(f"[Anonymizer] Service not found: {service_path}")
        return text, {}

    try:
        # Prepare input as JSON
        input_data = {
            "text": text,
            "lang": lang,
            "pii_types": pii_types,
            "placeholder_format": placeholder_format,
            "confidence_threshold": confidence_threshold
        }

        result = subprocess.run(
            [str(python_path), str(service_path), "--anonymize", "--json"],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            output = json.loads(result.stdout)
            return output.get("anonymized", text), output.get("mappings", {})
        else:
            log(f"[Anonymizer] Service error: {result.stderr}")
            return text, {}

    except subprocess.TimeoutExpired:
        log("[Anonymizer] Service timeout")
        return text, {}
    except json.JSONDecodeError as e:
        log(f"[Anonymizer] Invalid JSON response: {e}")
        return text, {}
    except Exception as e:
        log(f"[Anonymizer] Service call failed: {e}")
        return text, {}


def _check_models_via_service() -> dict:
    """Check available spacy models via service subprocess."""
    python_path = _get_embedded_python()
    service_path = _get_service_path()

    if not service_path.exists():
        return {"available": [], "missing": ["de_core_news_lg", "en_core_web_lg"], "spacy_installed": False}

    try:
        result = subprocess.run(
            [str(python_path), str(service_path), "--check-models"],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL  # Prevent WinError 6 on Windows without console
        )

        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"available": [], "missing": ["de_core_news_lg", "en_core_web_lg"], "spacy_installed": False}

    except Exception as e:
        log(f"[Anonymizer] Model check failed: {e}")
        return {"available": [], "missing": [], "spacy_installed": False}


def ensure_spacy_models(models: list = None) -> bool:
    """
    Check if spaCy models are available via service.

    Args:
        models: Ignored (service handles model selection)

    Returns:
        True if models are available
    """
    global _spacy_models_checked

    if _spacy_models_checked:
        return True

    model_info = _check_models_via_service()
    available = model_info.get("available", [])

    if available:
        log(f"[spaCy] Models available: {available}")
        _spacy_models_checked = True
        return True
    else:
        missing = model_info.get("missing", [])
        log(f"[spaCy] Models missing: {missing}")
        _spacy_models_checked = True
        return False


# Legacy compatibility - not used anymore but kept for API stability
def _legacy_ensure_spacy_models(models: list = None) -> bool:
    """Legacy function - kept for reference but not called."""
    global _spacy_models_checked

    if _spacy_models_checked:
        return True

    if models is None:
        models = [
            ("de_core_news_lg", "de_core_news_md"),
            ("en_core_web_lg", "en_core_web_md"),
        ]

    try:
        import spacy
        import subprocess
        import sys

        all_available = True

        for model_spec in models:
            # Handle tuple (preferred, fallback) or string
            if isinstance(model_spec, tuple):
                preferred, fallback = model_spec
            else:
                preferred, fallback = model_spec, None

            # Check if preferred model is available
            if spacy.util.is_package(preferred):
                log(f"[spaCy] Model {preferred} available")
                continue

            # Check fallback
            if fallback and spacy.util.is_package(fallback):
                log(f"[spaCy] Model {fallback} available (fallback)")
                continue

            # Need to download - try preferred first
            log(f"[spaCy] Downloading model: {preferred}")
            try:
                run_kwargs = {
                    "capture_output": True,
                    "text": True,
                    "timeout": 300,  # 5 minute timeout
                    "stdin": subprocess.DEVNULL
                }
                if sys.platform == "win32":
                    run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                result = subprocess.run(
                    [sys.executable, "-m", "spacy", "download", preferred],
                    **run_kwargs
                )
                if result.returncode == 0:
                    log(f"[spaCy] Successfully downloaded {preferred}")
                    continue
                else:
                    log(f"[spaCy] Failed to download {preferred}: {result.stderr}")
            except subprocess.TimeoutExpired:
                log(f"[spaCy] Timeout downloading {preferred}")
            except Exception as e:
                log(f"[spaCy] Error downloading {preferred}: {e}")

            # Try fallback if available
            if fallback:
                log(f"[spaCy] Trying fallback model: {fallback}")
                try:
                    fallback_kwargs = {
                        "capture_output": True,
                        "text": True,
                        "timeout": 300,
                        "stdin": subprocess.DEVNULL
                    }
                    if sys.platform == "win32":
                        fallback_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    result = subprocess.run(
                        [sys.executable, "-m", "spacy", "download", fallback],
                        **fallback_kwargs
                    )
                    if result.returncode == 0:
                        log(f"[spaCy] Successfully downloaded {fallback}")
                        continue
                    else:
                        log(f"[spaCy] Failed to download {fallback}: {result.stderr}")
                except Exception as e:
                    log(f"[spaCy] Error downloading {fallback}: {e}")

            # Neither model available
            all_available = False
            log(f"[spaCy] No model available for {preferred}")

        _spacy_models_checked = True
        return all_available

    except ImportError:
        # spaCy not available directly - check via proxy
        log("[spaCy] Not installed directly, checking via embedded Python...")
        _use_proxy = True

        model_info = _check_models_via_service()
        if model_info.get("spacy_installed"):
            available = model_info.get("available", [])
            log(f"[spaCy] Models via proxy: {available}")
            _spacy_models_checked = True
            return len(available) > 0
        else:
            log("[spaCy] Not installed in embedded Python either")
            _spacy_models_checked = True
            return False

    except Exception as e:
        log(f"[spaCy] Error checking models: {e}")
        _spacy_models_checked = True
        return False


@dataclass
class AnonymizationContext:
    """Stores mapping for reversing anonymization."""
    mappings: dict = field(default_factory=dict)  # {placeholder: original_value}
    reverse_mappings: dict = field(default_factory=dict)  # {original_value: placeholder}
    counters: dict = field(default_factory=dict)  # {entity_type: count}


def is_available() -> bool:
    """Check if anonymization service is available."""
    global _service_available

    if _service_available is None:
        service_path = _get_service_path()
        if service_path.exists():
            # Verify service can run
            model_info = _check_models_via_service()
            if model_info.get("spacy_installed"):
                _service_available = True
                log("[Anonymizer] Service available")
            else:
                _service_available = False
                log("[Anonymizer] spacy not installed - anonymization disabled")
        else:
            _service_available = False
            log("[Anonymizer] Service not found - anonymization disabled")

    return _service_available


def _add_custom_recognizers(analyzer, config: dict = None):
    """Add custom recognizers for improved detection."""
    from presidio_analyzer import PatternRecognizer, Pattern

    # European company registration numbers
    company_reg_recognizer = PatternRecognizer(
        supported_entity="COMPANY_ID",
        name="company_registration_recognizer",
        patterns=[
            # Germany: HRB/HRA + number
            Pattern(name="de_hrb", regex=r"\bHR[AB]\s*\d+\b", score=0.95),
            # Austria: FN + number + letter
            Pattern(name="at_fn", regex=r"\bFN\s*\d+[a-z]?\b", score=0.95),
            # Switzerland: CHE-xxx.xxx.xxx (UID)
            Pattern(name="ch_uid", regex=r"\bCHE[-.]?\d{3}[.-]?\d{3}[.-]?\d{3}\b", score=0.95),
            # UK: Company number (8 digits, sometimes with prefix)
            Pattern(name="uk_company", regex=r"\b(?:SC|NI|OC|SO|NC)?\d{8}\b", score=0.7),
            # France: SIREN (9 digits) / SIRET (14 digits)
            Pattern(name="fr_siren", regex=r"\bSIREN\s*\d{3}\s*\d{3}\s*\d{3}\b", score=0.9),
            Pattern(name="fr_siret", regex=r"\bSIRET\s*\d{3}\s*\d{3}\s*\d{3}\s*\d{5}\b", score=0.9),
            # Netherlands: KvK number (8 digits)
            Pattern(name="nl_kvk", regex=r"\bKvK\s*\d{8}\b", score=0.9),
            # Belgium: BCE/KBO number (10 digits with dots)
            Pattern(name="be_bce", regex=r"\b(?:BCE|KBO)\s*\d{4}[.-]?\d{3}[.-]?\d{3}\b", score=0.9),
            # Spain: CIF/NIF
            Pattern(name="es_cif", regex=r"\b[A-Z]\d{7}[A-Z0-9]\b", score=0.6),
            # Italy: Partita IVA (11 digits with IT prefix)
            Pattern(name="it_piva", regex=r"\bIT\d{11}\b", score=0.9),
            # Poland: KRS (10 digits)
            Pattern(name="pl_krs", regex=r"\bKRS\s*\d{10}\b", score=0.9),
            # Sweden: Org.nr (10 digits with dash)
            Pattern(name="se_orgnr", regex=r"\b\d{6}[-]?\d{4}\b", score=0.5),  # Low score - generic
        ],
        supported_language="de"
    )
    analyzer.registry.add_recognizer(company_reg_recognizer)
    log("[Anonymizer] Added European company registration recognizers")

    # German company patterns (GmbH, AG, etc.)
    german_company_recognizer = PatternRecognizer(
        supported_entity="ORGANIZATION",
        name="german_company_recognizer",
        patterns=[
            Pattern(name="gmbh", regex=r"\b[\w\s]+\s+(GmbH|AG|KG|OHG|e\.V\.|UG|SE)\b", score=0.85),
        ],
        supported_language="de"
    )
    analyzer.registry.add_recognizer(german_company_recognizer)

    # German IBAN with context words
    iban_recognizer = PatternRecognizer(
        supported_entity="IBAN_CODE",
        name="german_iban_recognizer",
        patterns=[
            Pattern(name="de_iban", regex=r"\bDE\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b", score=0.95),
            Pattern(name="at_iban", regex=r"\bAT\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b", score=0.95),
            Pattern(name="ch_iban", regex=r"\bCH\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{1}\b", score=0.95),
        ],
        context=["IBAN", "Konto", "Bankverbindung", "Kontonummer", "überweisen", "Überweisung"],
        supported_language="de"
    )
    analyzer.registry.add_recognizer(iban_recognizer)

    # German phone numbers with context
    phone_recognizer = PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        name="german_phone_recognizer",
        patterns=[
            # German format: +49 xxx xxxxxxx or 0xxx xxxxxxx
            Pattern(name="de_phone_intl", regex=r"\+49[\s]?\d{2,4}[\s/-]?\d{3,8}", score=0.85),
            Pattern(name="de_phone_local", regex=r"\b0\d{2,4}[\s/-]?\d{3,8}\b", score=0.7),
            # Mobile: 01xx xxxxxxx
            Pattern(name="de_mobile", regex=r"\b01[567]\d[\s/-]?\d{7,8}\b", score=0.85),
        ],
        context=["Tel", "Telefon", "Fax", "Mobil", "Handy", "anrufen", "📞"],
        supported_language="de"
    )
    analyzer.registry.add_recognizer(phone_recognizer)
    log("[Anonymizer] Added German IBAN and phone recognizers")

    # German addresses (street + number, PLZ)
    address_recognizer = PatternRecognizer(
        supported_entity="ADDRESS",
        name="german_address_recognizer",
        patterns=[
            # Full address: Straße Nr, PLZ Stadt (e.g., "Finkenweg 38, 76547 Sinzheim")
            Pattern(
                name="de_full_address",
                regex=r"\b[A-ZÄÖÜ][a-zäöüß]+(?:straße|str\.|weg|gasse|platz|allee|ring|damm|ufer|berg|tal)\s+\d+[a-z]?\s*,?\s*\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b",
                score=0.95
            ),
            # Street + number (e.g., "Finkenweg 38")
            Pattern(
                name="de_street",
                regex=r"\b[A-ZÄÖÜ][a-zäöüß]+(?:straße|str\.|weg|gasse|platz|allee|ring|damm|ufer|berg|tal)\s+\d+[a-z]?\b",
                score=0.85
            ),
            # PLZ + City (e.g., "76547 Sinzheim")
            Pattern(
                name="de_plz_city",
                regex=r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b",
                score=0.8
            ),
            # Just PLZ (5 digits, German postal code)
            Pattern(
                name="de_plz",
                regex=r"\b\d{5}\b",
                score=0.6  # Lower score - could be other numbers
            ),
        ],
        context=["Adresse", "Straße", "Str.", "PLZ", "Postleitzahl", "wohnhaft", "Anschrift"],
        supported_language="de"
    )
    analyzer.registry.add_recognizer(address_recognizer)
    log("[Anonymizer] Added German address recognizer")

    # Known persons from config (deny list for names spaCy misses)
    if config:
        anon_config = config.get("anonymization", {})
        known_persons = anon_config.get("known_persons", [])
        if known_persons:
            known_persons_recognizer = PatternRecognizer(
                supported_entity="PERSON",
                name="known_persons_recognizer",
                deny_list=known_persons,
                deny_list_score=1.0,  # Highest confidence for known entities
                supported_language="de"
            )
            analyzer.registry.add_recognizer(known_persons_recognizer)
            log(f"[Anonymizer] Added known persons: {known_persons}")

        known_companies = anon_config.get("known_companies", [])
        if known_companies:
            known_companies_recognizer = PatternRecognizer(
                supported_entity="ORGANIZATION",
                name="known_companies_recognizer",
                deny_list=known_companies,
                deny_list_score=1.0,  # Highest confidence for known entities
                supported_language="de"
            )
            analyzer.registry.add_recognizer(known_companies_recognizer)
            log(f"[Anonymizer] Added known companies: {known_companies}")


def _get_analyzer(language: str = "de", config: dict = None):
    """Get or create Presidio analyzer (lazy initialization)."""
    global _analyzer
    if _analyzer is None:
        from presidio_analyzer import AnalyzerEngine

        # Try to use spaCy with German model, fall back to default
        try:
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            import spacy

            # Build models list in correct format for Presidio
            models_list = []

            # Check for German models
            if spacy.util.is_package("de_core_news_lg"):
                models_list.append({"lang_code": "de", "model_name": "de_core_news_lg"})
            elif spacy.util.is_package("de_core_news_md"):
                models_list.append({"lang_code": "de", "model_name": "de_core_news_md"})
            elif spacy.util.is_package("de_core_news_sm"):
                models_list.append({"lang_code": "de", "model_name": "de_core_news_sm"})

            # Check for English models
            if spacy.util.is_package("en_core_web_lg"):
                models_list.append({"lang_code": "en", "model_name": "en_core_web_lg"})
            elif spacy.util.is_package("en_core_web_md"):
                models_list.append({"lang_code": "en", "model_name": "en_core_web_md"})
            elif spacy.util.is_package("en_core_web_sm"):
                models_list.append({"lang_code": "en", "model_name": "en_core_web_sm"})

            if models_list:
                configuration = {
                    "nlp_engine_name": "spacy",
                    "models": models_list,
                    "ner_model_configuration": {
                        "labels_to_ignore": ["MISC"]  # Suppress warning for unmapped spaCy entity
                    }
                }
                provider = NlpEngineProvider(nlp_configuration=configuration)
                nlp_engine = provider.create_engine()

                # Get supported languages from our models
                supported_languages = [m["lang_code"] for m in models_list]

                _analyzer = AnalyzerEngine(
                    nlp_engine=nlp_engine,
                    supported_languages=supported_languages
                )
                log(f"[Anonymizer] Using spaCy models: {[m['model_name'] for m in models_list]}")
            else:
                _analyzer = AnalyzerEngine()
                log("[Anonymizer] Using default Presidio analyzer (English only)")
        except Exception as e:
            log(f"[Anonymizer] SpaCy setup failed, using default: {e}")
            _analyzer = AnalyzerEngine()

        # Add custom recognizers
        _add_custom_recognizers(_analyzer, config)

    return _analyzer


def _get_anonymizer():
    """Get or create Presidio anonymizer."""
    global _anonymizer
    if _anonymizer is None:
        from presidio_anonymizer import AnonymizerEngine
        _anonymizer = AnonymizerEngine()
    return _anonymizer


def resolve_anonymization_setting(
    config: dict,
    agent_config: dict,
    task_config: dict,
    task_name: str,
    task_type: str,
    backend_name: str,
    disable_anon: bool = False
) -> tuple[bool, str]:
    """
    Central decision whether anonymization should be active.

    This is the SINGLE source of truth for anonymization decisions.
    All backends should read agent_config["use_anonymization_proxy"] after this runs.

    Priority:
    0. Expert Override: disable_anon=True -> OFF (highest priority)
    1. Agent-Frontmatter explicitly false -> OFF
    2. Agent-Frontmatter explicitly true + global enabled -> ON
    3. Global UI-Setting disabled -> OFF
    4. Backend-Default (backends.json)

    Args:
        config: Full configuration with anonymization.enabled setting
        agent_config: Backend config from backends.json
        task_config: Agent/skill frontmatter config
        task_name: Name of skill or agent
        task_type: "skill" or "agent"
        backend_name: Name of AI backend
        disable_anon: If True, skip anonymization (Expert Mode override via context menu)

    Returns:
        tuple: (use_anonymization: bool, source: str)
        source is one of: "expert-override", "agent-off", "agent-on", "global-off",
                          "backend", "backend-off", "presidio-unavailable"
    """
    # 0. Expert Override: disable_anon from context menu (highest priority)
    if disable_anon:
        log(f"[Anon] Expert override: Anonymization DISABLED for {task_name}")
        return False, "expert-override"

    # Check if Presidio is available at all
    if not is_available():
        return False, "presidio-unavailable"

    # 1. Agent-Frontmatter explicitly set?
    agent_setting = task_config.get("anonymize")
    if agent_setting is False:
        return False, "agent-off"

    # 2. Global UI-Setting check
    global_enabled = config.get("anonymization", {}).get("enabled", False)

    # Agent explicitly ON, but global OFF -> still OFF (global wins)
    # OR: Agent explicitly ON and global ON -> ON
    if agent_setting is True:
        if global_enabled:
            return True, "agent-on"
        else:
            return False, "global-off"

    # 3. No explicit Agent-Setting -> Global decides
    if not global_enabled:
        return False, "global-off"

    # 4. Global ON, no Agent-Setting -> Backend-Default
    backend_setting = agent_config.get("anonymize", False)
    if backend_setting:
        return True, "backend"

    return False, "backend-off"


def should_anonymize(config: dict, task_name: str, task_type: str, backend_name: str) -> bool:
    """
    DEPRECATED: Use resolve_anonymization_setting() instead.

    Kept for backward compatibility with existing code.
    This function does NOT have access to agent_config or task_config,
    so it uses simplified logic based only on the full config.

    Args:
        config: Full configuration
        task_name: Name of skill or agent
        task_type: "skill" or "agent"
        backend_name: Name of AI backend

    Returns:
        True if anonymization should be applied
    """
    # Check if Presidio is available
    if not is_available():
        return False

    # Check global switch
    anon_config = config.get("anonymization", {})
    if not anon_config.get("enabled", False):
        return False

    # Get backend config
    backends = config.get("ai_backends", {})
    backend_config = backends.get(backend_name, {})

    # Default: cloud backends should anonymize, local don't
    backend_type = backend_config.get("type", "")
    local_backends = ["ollama", "ollama_native", "qwen_agent"]
    default_anonymize = backend_type not in local_backends

    # Backend-level setting (or default based on type)
    # Also check legacy "requires_anonymization" for backwards compatibility
    backend_anonymize = backend_config.get(
        "anonymize",
        backend_config.get("requires_anonymization", default_anonymize)
    )

    # Get task-specific setting
    tasks_key = f"{task_type}s"  # "skills" or "agents"
    tasks_config = config.get(tasks_key, {})
    task_config = tasks_config.get(task_name, {})

    # Task can override: explicit false disables, explicit true enables
    if "anonymize" in task_config:
        return task_config["anonymize"]

    # Otherwise use backend default
    return backend_anonymize


# URL pattern for anonymization (matches http/https URLs)
_URL_PATTERN = re.compile(
    r'https?://[^\s<>\[\]()\'\"]+|www\.[^\s<>\[\]()\'\"]+',
    re.IGNORECASE
)

# Email pattern for anonymization (must run BEFORE domain anonymization)
_EMAIL_PATTERN = re.compile(
    r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b',
    re.IGNORECASE
)

# German address pattern (street + number + optional postal code)
# Matches: "Finkenweg 38, 76547" or "Musterstraße 12" or "Am Markt 5, 12345 Berlin"
_GERMAN_ADDRESS_PATTERN = re.compile(
    r'\b[A-ZÄÖÜ][a-zäöüß]+(?:straße|strasse|str\.|weg|platz|gasse|allee|ring|damm|ufer|park|hof|berg|tal)\s+\d+[a-z]?'
    r'(?:\s*,?\s*\d{5}(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)?',
    re.IGNORECASE
)

# Email header name pattern (From:, To:, Cc: lines with names)
# Matches: "From: Weiß Patrick" or "From: Patrick Weiß" or "Von: Müller Hans"
_EMAIL_HEADER_NAME_PATTERN = re.compile(
    r'(?:^|\n)(?:From|To|Cc|Von|An|Kopie):\s*([A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ][a-zäöüß]+)',
    re.MULTILINE
)

# Domain pattern for anonymization (matches bare domains like example.com)
# Must have at least one subdomain part and a TLD
_COMMON_TLDS = (
    # Generic TLDs
    "com|org|net|edu|gov|mil|int|"
    # Tech/startup TLDs
    "io|dev|app|tech|ai|cloud|software|digital|online|site|web|"
    # Business TLDs
    "biz|info|co|company|solutions|services|consulting|"
    # Country TLDs (Europe)
    "de|at|ch|uk|fr|it|es|nl|be|pl|se|no|dk|fi|ie|pt|gr|cz|hu|ro|"
    # Country TLDs (Other)
    "us|ca|au|nz|jp|cn|kr|in|br|mx|ru|za|"
    # New gTLDs
    "shop|store|blog|news|media|agency|studio|design|"
    "pro|expert|guru|support|help|center|systems|network"
)
# Pattern: optional subdomains + main domain + .tld
# Examples: example.com, forum.example.com, docs.example.com
_DOMAIN_PATTERN = re.compile(
    rf'\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.(?:{_COMMON_TLDS})\b',
    re.IGNORECASE
)

# System URLs that should NOT be anonymized (Microsoft services, etc.)
# These are infrastructure URLs, not personal/company websites
_SYSTEM_URL_DOMAINS = {
    # Microsoft services
    "outlook.office365.com",
    "outlook.office.com",
    "outlook.live.com",
    "teams.microsoft.com",
    "login.microsoftonline.com",
    "graph.microsoft.com",
    "sharepoint.com",
    "onedrive.live.com",
    "office.com",
    "microsoft.com",
    "live.com",
    "azure.com",
    # Google services
    "google.com",
    "gmail.com",
    "calendar.google.com",
    "drive.google.com",
    "docs.google.com",
    "meet.google.com",
    # Other common services
    "zoom.us",
    "slack.com",
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    # API/webhook endpoints (not personal)
    "webhook.office.com",
    "webhooks.office.com",
}


def _is_safe_url(url: str) -> bool:
    """Check if URL belongs to a system domain that shouldn't be anonymized."""
    url_lower = url.lower()
    for domain in _SYSTEM_URL_DOMAINS:
        # Check if domain appears in URL (handles subdomains)
        if domain in url_lower:
            return True
    return False


def _extract_link_ref_values(text: str) -> set[str]:
    """
    Extract all link_ref values from JSON text.

    Finds patterns like "link_ref": "a3f2b1c8" and returns the values.
    These values should NEVER be anonymized - they're used by the link
    placeholder system.

    Args:
        text: Text that may contain JSON with link_ref fields

    Returns:
        Set of link_ref values found in the text
    """
    # Pattern: "link_ref": "value" or 'link_ref': 'value'
    pattern = r'"link_ref"\s*:\s*"([^"]+)"|\'link_ref\'\s*:\s*\'([^\']+)\''
    matches = re.findall(pattern, text)
    # findall returns tuples for groups, flatten and filter empty
    return {m for group in matches for m in group if m}


def _anonymize_urls(text: str, context: AnonymizationContext, placeholder_format: str,
                    whitelist: list = None) -> str:
    """
    Anonymize URLs in text (company websites, social media profiles).

    Args:
        text: Input text
        context: Anonymization context to update
        placeholder_format: Format string for placeholders
        whitelist: List of domains to never anonymize (e.g., company domains)

    Returns:
        Text with URLs replaced by placeholders
    """
    # Find all URLs
    urls = list(_URL_PATTERN.finditer(text))
    if not urls:
        return text

    # Build whitelist set for fast lookup
    whitelist_lower = {w.lower() for w in (whitelist or [])}

    # Process in reverse order to preserve positions
    anonymized = text
    for match in reversed(urls):
        url = match.group()
        url_lower = url.lower()

        # Skip safe system URLs (Microsoft, Google, etc.)
        if _is_safe_url(url):
            continue

        # Skip URLs containing whitelisted domains (e.g., company domains)
        if any(domain in url_lower for domain in whitelist_lower):
            continue

        # Check if we already have a mapping
        if url in context.reverse_mappings:
            placeholder = context.reverse_mappings[url]
        else:
            counter = context.counters.get("URL", 0) + 1
            context.counters["URL"] = counter
            placeholder = placeholder_format.format(entity_type="URL", index=counter)
            context.mappings[placeholder] = url
            context.reverse_mappings[url] = placeholder

        anonymized = anonymized[:match.start()] + placeholder + anonymized[match.end():]

    return anonymized


def _anonymize_emails(text: str, context: AnonymizationContext, placeholder_format: str,
                      whitelist: list = None) -> str:
    """
    Anonymize email addresses in text.

    Must run BEFORE domain anonymization to prevent partial email anonymization
    (e.g., p.weiss@example.com becoming p.weiss@[DOMAIN-1]).

    Args:
        text: Input text
        context: Anonymization context to update
        placeholder_format: Format string for placeholders
        whitelist: List of emails/terms to never anonymize

    Returns:
        Text with emails replaced by placeholders
    """
    emails = list(_EMAIL_PATTERN.finditer(text))
    if not emails:
        return text

    whitelist_lower = {w.lower() for w in (whitelist or [])}
    anonymized = text

    for match in reversed(emails):
        email = match.group()

        # Skip whitelisted emails
        if email.lower() in whitelist_lower:
            continue

        # Check if we already have a mapping
        if email in context.reverse_mappings:
            placeholder = context.reverse_mappings[email]
        else:
            counter = context.counters.get("EMAIL", 0) + 1
            context.counters["EMAIL"] = counter
            placeholder = placeholder_format.format(entity_type="EMAIL", index=counter)
            context.mappings[placeholder] = email
            context.reverse_mappings[email] = placeholder

        anonymized = anonymized[:match.start()] + placeholder + anonymized[match.end():]

    return anonymized


def _anonymize_addresses(text: str, context: AnonymizationContext, placeholder_format: str,
                         whitelist: list = None) -> str:
    """
    Anonymize German addresses in text (Presidio misses these).

    Matches patterns like:
    - "Finkenweg 38, 76547"
    - "Musterstraße 12"
    - "Am Markt 5, 12345 Berlin"

    Args:
        text: Input text
        context: Anonymization context to update
        placeholder_format: Format string for placeholders
        whitelist: List of addresses to never anonymize

    Returns:
        Text with addresses replaced by placeholders
    """
    addresses = list(_GERMAN_ADDRESS_PATTERN.finditer(text))
    if not addresses:
        return text

    whitelist_lower = {w.lower() for w in (whitelist or [])}
    anonymized = text

    for match in reversed(addresses):
        address = match.group()

        # Skip whitelisted addresses
        if address.lower() in whitelist_lower:
            continue

        # Check if we already have a mapping
        if address in context.reverse_mappings:
            placeholder = context.reverse_mappings[address]
        else:
            counter = context.counters.get("ADDRESS", 0) + 1
            context.counters["ADDRESS"] = counter
            placeholder = placeholder_format.format(entity_type="ADDRESS", index=counter)
            context.mappings[placeholder] = address
            context.reverse_mappings[address] = placeholder

        anonymized = anonymized[:match.start()] + placeholder + anonymized[match.end():]

    return anonymized


def _anonymize_email_header_names(text: str, context: AnonymizationContext, placeholder_format: str,
                                   whitelist: list = None) -> str:
    """
    Anonymize names in email headers (From:, To:, Von:, etc.).

    Presidio often misses German names with special characters (ß, ü, etc.)
    in email header format like "From: Weiß Patrick".

    Args:
        text: Input text
        context: Anonymization context to update
        placeholder_format: Format string for placeholders
        whitelist: List of names to never anonymize

    Returns:
        Text with header names replaced by placeholders
    """
    matches = list(_EMAIL_HEADER_NAME_PATTERN.finditer(text))
    if not matches:
        return text

    whitelist_lower = {w.lower() for w in (whitelist or [])}
    anonymized = text

    for match in reversed(matches):
        name = match.group(1)  # Get the captured name group

        # Skip whitelisted names
        if name.lower() in whitelist_lower:
            continue

        # Check if we already have a mapping for this name
        if name in context.reverse_mappings:
            placeholder = context.reverse_mappings[name]
        else:
            counter = context.counters.get("PERSON", 0) + 1
            context.counters["PERSON"] = counter
            placeholder = placeholder_format.format(entity_type="PERSON", index=counter)
            context.mappings[placeholder] = name
            context.reverse_mappings[name] = placeholder

        # Replace just the name part, keeping the header prefix
        name_start = match.start(1)
        name_end = match.end(1)
        anonymized = anonymized[:name_start] + placeholder + anonymized[name_end:]

    return anonymized


def _anonymize_domains(text: str, context: AnonymizationContext, placeholder_format: str,
                       whitelist: list = None) -> str:
    """
    Anonymize bare domain names in text (e.g., company.com, forum.example.com).

    Must run AFTER URL anonymization to avoid matching domains inside URLs.

    Args:
        text: Input text
        context: Anonymization context to update
        placeholder_format: Format string for placeholders
        whitelist: List of domains/terms to never anonymize

    Returns:
        Text with domains replaced by placeholders
    """
    # Find all domains
    domains = list(_DOMAIN_PATTERN.finditer(text))
    if not domains:
        return text

    # Build lowercase whitelist for efficient lookup
    whitelist_lower = {w.lower() for w in (whitelist or [])}

    # Process in reverse order to preserve positions
    anonymized = text
    for match in reversed(domains):
        domain = match.group()

        # Skip whitelisted domains (company's own domains, etc.)
        if domain.lower() in whitelist_lower:
            continue

        # Skip system URL domains (Microsoft, Google, etc.) - these are inside URLs
        # that were intentionally not anonymized by _anonymize_urls
        domain_lower = domain.lower()
        if any(sys_domain in domain_lower or domain_lower in sys_domain
               for sys_domain in _SYSTEM_URL_DOMAINS):
            continue

        # Skip if already inside a placeholder (e.g., from URL anonymization)
        if '[' in text[max(0, match.start()-20):match.start()]:
            continue

        # Check if we already have a mapping
        if domain in context.reverse_mappings:
            placeholder = context.reverse_mappings[domain]
        else:
            counter = context.counters.get("DOMAIN", 0) + 1
            context.counters["DOMAIN"] = counter
            placeholder = placeholder_format.format(entity_type="DOMAIN", index=counter)
            context.mappings[placeholder] = domain
            context.reverse_mappings[domain] = placeholder

        anonymized = anonymized[:match.start()] + placeholder + anonymized[match.end():]

    return anonymized


def _second_pass_replacement(text: str, context: AnonymizationContext) -> str:
    """
    Second pass: Replace any remaining occurrences of mapped values.

    Presidio detects entities based on context, so the same name might be detected
    in "Hallo Thomas," but not in a standalone "Thomas" signature. This function
    ensures ALL occurrences of detected values are consistently replaced.

    Args:
        text: Text after first-pass anonymization
        context: Context with reverse_mappings (original -> placeholder)

    Returns:
        Text with all remaining occurrences replaced
    """
    if not context.reverse_mappings:
        return text

    result = text

    # Sort by length (longest first) to avoid partial replacements
    # e.g., "John Smith" should be replaced before "John"
    sorted_mappings = sorted(
        context.reverse_mappings.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )

    for original, placeholder in sorted_mappings:
        # Skip very short values (< 3 chars) to avoid false replacements
        if len(original) < 3:
            continue

        # Skip if original contains placeholder markers (already processed)
        if '[' in original or ']' in original:
            continue

        # Use word boundary matching to avoid partial word replacements
        # e.g., don't replace "Thomas" inside "Thomasstraße"
        pattern = re.compile(re.escape(original), re.IGNORECASE)

        # Find and replace remaining occurrences
        result = pattern.sub(placeholder, result)

    return result


# Common false positives to skip (lowercase for comparison)
_FALSE_POSITIVE_WORDS = {
    # Generic English words often misdetected
    "hello", "asset", "minimum", "standard", "upgrade", "parallel",
    "grace", "period", "training", "support", "demo", "forum",
    # German greetings/words often misdetected
    "hochachtungsvoll", "formell", "informell", "lieber", "ehrlich",
    "erstelle", "angefangener", "grüße",
    # German verbs/nouns often misdetected as names
    "zeige", "zeigen", "entwurf", "entwurf-text", "entwurfstext",
    "antwort-entwurf", "antwort", "antworten",
    "behalte", "nutze", "prüfen", "verwende",
    # German common words misdetected as ORGANIZATION
    "nicht", "eine", "einer", "sofort", "jetzt", "hier", "dort",
    "hast", "hast du", "haben", "wird", "werden", "kann", "können",
    "absolut", "absolut!", "immer", "bestätigung",
    # Technical/business terms often misdetected
    "api", "modelzoo", "release", "notes", "upload", "link",
    "digital twins", "roi-modell", "rbv", "agentenbasierte systeme",
    "kmu-segment", "deskagent", "professional",
    "webhook", "chat-modus", "startmethode", "kontextbasiert", "kontextbasierter",
    "zeitgesteuert", "prompt-fenster", "teams-kanal",
    # German words misdetected as locations
    "postfach", "inbox", "ordner", "betreff", "datum",
    "kundenrechnungen", "newsletter-absendern", "support-tickets",
    # Spanish email header words (misdetected when processing Spanish emails)
    "mensaje", "asunto", "enviado", "enviados", "recibido", "recibidos",
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
    "tel", "teléfono", "correo", "electrónico", "fecha",
    # French email header words
    "objet", "envoyé", "reçu", "destinataire",
    # Product names (should NOT be anonymized)
    "paperless", "billomat", "lexware", "outlook", "microsoft",
    # Academic terms
    "wiwi fakultät", "fakultät", "masterarbeit",
    # German compound words often misdetected
    "absendermailadressen", "empfängeradressen", "rechnungsnummer",
    # === DeskAgent Technical Terms (Agent Instructions) ===
    # Email folder names (CamelCase triggers false PERSON detection)
    "todelete", "tooffer", "topay", "done", "doneinvoices", "invoices",
    "todone", "toarchive", "archive", "newsletter", "newsletters",
    # Email actions and types
    "phishing", "spam", "follow-up", "follow-ups", "followup", "followups",
    "classifier", "classifiers", "supervisor",
    # Agent workflow terms
    "batch_email_actions", "entry_id", "flag_type", "followup",
    "classify_spam", "classify_newsletters", "classify_invoices",
    "classify_offers", "classify_followups", "process_invoices",
    # Priority/conflict terms
    "prioritaet", "priorität", "konfliktaufloesung", "konfliktauflösung",
    "parallele", "parallel", "klassifizierung",
    # Status terms
    "draft", "open", "paid", "overdue", "canceled",
    # === MCP response JSON keys (must not be anonymized) ===
    # These are technical field names in tool responses
    "link_ref", "web_link", "entry_id", "message_id", "event_id",
    "ticket_id", "document_id", "invoice_id", "contact_id", "conversation_id",
    "folder_id", "attachment_id", "session_id", "task_id",
    # === Agent prompt terms (falsely detected) ===
    # German table/document headers
    "kundenübersicht", "header-zeile", "remaining", "monthly total",
    # German instruction words
    "wichtig", "aufgabe", "eingaben", "ausgabe", "format",
    # Common test words
    "test", "testing", "beispiel", "example",
}

# CamelCase technical terms that should never be anonymized
# (checked case-sensitively because they're specifically CamelCase folder names)
_CAMELCASE_WHITELIST = {
    "ToDelete", "ToOffer", "ToPay", "ToDone", "ToArchive",
    "DoneInvoices", "Invoices", "Newsletter", "Newsletters",
    "Follow-up", "Follow-ups", "Phishing", "Spam",
}


# Greeting patterns that get incorrectly included in person names
_GREETING_PREFIXES = {"hi", "hello", "dear", "hallo", "liebe", "lieber", "sehr geehrte", "sehr geehrter"}

# Per-entity confidence thresholds (higher = stricter, fewer false positives)
_ENTITY_THRESHOLDS = {
    "PERSON": 0.5,           # Be conservative with names
    "EMAIL_ADDRESS": 0.9,    # Regex is reliable
    "PHONE_NUMBER": 0.6,     # Custom patterns are reliable
    "LOCATION": 0.6,         # Moderate threshold
    "ORGANIZATION": 0.75,    # ORG often has false positives (but not too strict - GmbH/AG are valid)
    "IBAN_CODE": 0.9,        # Regex is reliable
    "COMPANY_ID": 0.8,       # Custom patterns are reliable
    "URL": 0.9,              # Regex is reliable
    "ADDRESS": 0.7,          # German address patterns
}


def _is_false_positive(text: str, entity_type: str, score: float, min_score: float = 0.5,
                       whitelist: list = None) -> bool:
    """
    Check if a detected entity is likely a false positive.

    Args:
        text: The detected text
        entity_type: Type of entity (PERSON, LOCATION, etc.)
        score: Confidence score from analyzer
        min_score: Minimum confidence threshold (overridden by per-entity thresholds)
        whitelist: List of terms to never anonymize

    Returns:
        True if this should be skipped (false positive)
    """
    # Use per-entity threshold if available, otherwise default
    threshold = _ENTITY_THRESHOLDS.get(entity_type, min_score)
    if score < threshold:
        return True

    # Skip very short matches
    if len(text) < 3:
        return True

    # Skip entities with newlines/tabs (corrupted detections)
    if '\n' in text or '\t' in text or '\r' in text:
        return True

    # Skip text that looks like a placeholder (recursive detection)
    if '[' in text or ']' in text:
        return True

    # Skip text matching placeholder patterns (e.g., "DOMAIN-1", "URL-2", "PERSON-3")
    # This prevents re-anonymization of already anonymized placeholders
    if re.match(r'^(DOMAIN|URL|PERSON|EMAIL|PHONE|LOCATION|ORGANIZATION)-\d+$', text, re.IGNORECASE):
        return True

    # Skip whitelisted terms (company names, products, domains)
    if whitelist:
        text_lower = text.lower()
        for w in whitelist:
            if text_lower == w.lower():
                return True

    # Skip text starting with emoji (e.g., "🛠️ Professional")
    if text and ord(text[0]) > 0x1F000:
        return True

    # Skip URLs
    if text.startswith(("http://", "https://", "www.")):
        return True

    # Skip Outlook EntryIDs (long hex strings, 50+ chars, only 0-9 and A-F)
    if len(text) > 50 and re.match(r'^[0-9A-Fa-f]+$', text):
        return True

    # Skip link_ref values (8-char hex strings from SHA256 hash)
    # These are used by the link placeholder system: {{LINK:a3f2b1c8}}
    if len(text) == 8 and re.match(r'^[0-9a-fA-F]+$', text):
        return True

    # Skip Outlook/Graph message IDs (Base64-encoded, start with AAQkA, AAMkA, etc.)
    # These are typically 100+ chars and contain only Base64 characters
    # Also skip shorter fragments that still match the pattern
    if re.match(r'^AA[A-Za-z][A-Za-z0-9_+/=-]{10,}$', text):
        return True
    # Also catch partial IDs that start with AAMk or AAQk
    if text.startswith(('AAMk', 'AAQk', 'AQMk')) and len(text) > 10:
        return True

    # Skip common false positive words (case-insensitive)
    if text.lower() in _FALSE_POSITIVE_WORDS:
        return True

    # Skip CamelCase technical terms (case-sensitive for exact matches)
    if text in _CAMELCASE_WHITELIST:
        return True

    # Skip text containing markdown formatting characters
    # Examples: "User:**", "**User:", "*word*", "User:** nein"
    if '*' in text or text.endswith(':') or text.startswith(':'):
        return True

    # Skip text with colons followed by special chars (markdown/formatting)
    # Examples: "User:** Suche", "Zeitgesteuert:*"
    if ':*' in text or ':**' in text:
        return True

    # Skip conversation markers (User:, Assistant:, etc.)
    # Examples: "User:", "User:** nein", "Assistant:"
    text_lower = text.lower()
    if text_lower.startswith(('user:', 'user**', 'assistant:', 'system:')):
        return True

    # Skip German compound words with hyphens (almost never real names)
    # Examples: "Chat-Modus", "Prompt-Fenster", "Newsletter-Absendern"
    if '-' in text and entity_type in ("PERSON", "LOCATION", "ORGANIZATION"):
        # If it looks like a compound word (lowercase parts connected by hyphen)
        parts = text.split('-')
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
            # Real names with hyphens are usually "First-Name Last" or "Company-Name GmbH"
            # Skip if it looks like a technical term (no typical name patterns)
            has_name_pattern = any(p[0].isupper() and p[1:].islower() and len(p) > 3 for p in parts)
            if not has_name_pattern:
                return True

    # Skip "Hi Name" / "Hello Name" patterns (greeting + name detected as single entity)
    if entity_type == "PERSON":
        text_lower = text.lower()
        for greeting in _GREETING_PREFIXES:
            if text_lower.startswith(greeting + " "):
                return True

    # Skip single words that look like generic terms (no spaces, all lowercase except first)
    if entity_type == "PERSON" and " " not in text:
        # Real names usually have multiple words or are capitalized properly
        # Skip single lowercase words or title-case generic words
        if text.islower():
            return True

    # Skip phrases that are clearly not person names (contain adverbs or common words)
    if entity_type == "PERSON" and " " in text:
        words = text.lower().split()
        # Phrases starting with comparison words are not names
        comparison_starters = {"more", "most", "less", "very", "quite", "rather", "somewhat", "increasingly"}
        if words[0] in comparison_starters:
            return True
        # Phrases containing adverbs (ending in "ly") are typically not names
        if any(word.endswith("ly") and len(word) > 4 for word in words):
            return True

    return False


def _filter_overlapping_entities(results: list) -> list:
    """
    Filter out overlapping entities to prevent recursive placeholders.

    When entities overlap, keep the one with:
    1. Higher confidence score
    2. If equal score, longer span
    3. If equal length, the earlier one

    Args:
        results: List of Presidio RecognizerResult objects

    Returns:
        Filtered list with no overlapping entities
    """
    if not results:
        return results

    # Sort by start position, then by length (longer first), then by score (higher first)
    sorted_results = sorted(
        results,
        key=lambda x: (x.start, -(x.end - x.start), -x.score)
    )

    filtered = []
    for result in sorted_results:
        # Check if this entity overlaps with any already accepted entity
        overlaps = False
        for accepted in filtered:
            # Check for overlap: not (end1 <= start2 or end2 <= start1)
            if not (result.end <= accepted.start or accepted.end <= result.start):
                overlaps = True
                break

        if not overlaps:
            filtered.append(result)

    return filtered


def _extract_counter_from_placeholder(placeholder: str) -> tuple:
    """Extract entity type and counter from placeholder like '<PERSON_54>'."""
    match = re.match(r'<([A-Z_]+)_(\d+)>', placeholder)
    if match:
        return match.group(1), int(match.group(2))
    return None, 0


def _strip_greeting_prefix(text: str) -> str:
    """Strip greeting prefixes like 'Dear ', 'Hi ' from detected names."""
    text_lower = text.lower()
    for greeting in _GREETING_PREFIXES:
        if text_lower.startswith(greeting + " "):
            return text[len(greeting) + 1:]
    return text


def _normalize_name(name: str) -> str:
    """Normalize name for deduplication (strip titles, lowercase)."""
    prefixes = ['dr.', 'dr', 'prof.', 'prof', 'mr.', 'mr', 'mrs.', 'mrs', 'ms.', 'ms']
    name_lower = name.lower().strip()
    for prefix in prefixes:
        if name_lower.startswith(prefix + ' '):
            name_lower = name_lower[len(prefix) + 1:]
    return name_lower


def _find_existing_mapping(original: str, context: AnonymizationContext) -> str | None:
    """Find existing mapping for name (including partial matches)."""
    normalized = _normalize_name(original)

    # Exact match
    if original in context.reverse_mappings:
        return context.reverse_mappings[original]

    # Normalized/partial match
    for existing, placeholder in context.reverse_mappings.items():
        existing_norm = _normalize_name(existing)
        if existing_norm == normalized:
            return placeholder
        # Partial match (one contains the other)
        if normalized in existing_norm or existing_norm in normalized:
            return placeholder
    return None


def _filter_service_results(text: str, service_mappings: dict, context: AnonymizationContext,
                            whitelist: list = None) -> tuple[str, dict]:
    """
    Filter service mappings through false-positive detection.
    Returns (filtered_text, filtered_mappings).
    """
    filtered_mappings = {}
    filtered_text = text

    for placeholder, original in service_mappings.items():
        entity_type, index = _extract_counter_from_placeholder(placeholder)

        # Bug 6 fix: Prevent double-anonymization - skip entities whose original
        # value matches an existing placeholder name pattern (e.g., "EMAIL_1", "URL_6")
        # This happens when Presidio NER detects tokens inside <...> placeholders
        # that were already created by the custom anonymization step
        stripped_orig = original.strip()
        if re.match(r'^[A-Z][A-Z_]*_\d+$', stripped_orig):
            filtered_text = filtered_text.replace(placeholder, original)
            continue
        # Also skip entities containing partial/broken placeholder references
        # (e.g., "electrónico de <EMAIL_4" or "DOMAIN_1>/in")
        if re.search(r'<[A-Z_]+_\d+', original) or re.search(r'[A-Z_]+_\d+>', original):
            filtered_text = filtered_text.replace(placeholder, original)
            continue

        # Bug 4 fix: Skip entities that are too long (likely full sentences)
        word_count = len(original.split())
        if word_count >= 5:
            filtered_text = filtered_text.replace(placeholder, original)
            continue

        # Bug 4 fix: Skip ORGANIZATION that looks like a sentence
        if entity_type == "ORGANIZATION":
            lower = original.lower()
            sentence_indicators = [' is ', ' are ', ' the ', ' with ', ' for ', ' to ', ' and ', ' that ']
            if any(ind in lower for ind in sentence_indicators):
                filtered_text = filtered_text.replace(placeholder, original)
                continue

        # Bug 2 fix: Strip greeting prefix from PERSON entities
        if entity_type == "PERSON":
            stripped = _strip_greeting_prefix(original)
            if stripped != original:
                # Greeting was stripped - update the text to have greeting + placeholder for name only
                # Replace the full placeholder with "Dear <PERSON_X>" pattern
                greeting = original[:len(original) - len(stripped)].strip()
                filtered_text = filtered_text.replace(placeholder, f"{greeting} {placeholder}")
                original = stripped  # Use stripped name in mapping

        # Apply existing false positive check (uses _is_false_positive from same file)
        if entity_type and _is_false_positive(original, entity_type, 0.8, whitelist=whitelist):
            filtered_text = filtered_text.replace(placeholder, original)
            continue

        # Bug 3 fix: Deduplication - check if this value already has a mapping
        existing = _find_existing_mapping(original, context)
        if existing:
            # Reuse existing placeholder instead of creating new one
            filtered_text = filtered_text.replace(placeholder, existing)
            continue

        # Bug 5 fix: Placeholder conflict detection - check if placeholder already used with DIFFERENT value
        # This happens because each subprocess call starts with fresh counters
        if placeholder in context.mappings:
            if context.mappings[placeholder] != original:
                # Placeholder conflict! Renumber this entity to avoid overwriting
                if entity_type:
                    new_counter = context.counters.get(entity_type, 0) + 1
                    context.counters[entity_type] = new_counter
                    new_placeholder = f"<{entity_type}_{new_counter}>"
                    filtered_text = filtered_text.replace(placeholder, new_placeholder)
                    placeholder = new_placeholder
            else:
                # Same placeholder, same value - skip (already mapped)
                continue

        # Valid entity - keep it
        filtered_mappings[placeholder] = original

        # Bug 1 fix: Sync counter
        if entity_type and index:
            context.counters[entity_type] = max(context.counters.get(entity_type, 0), index)

    return filtered_text, filtered_mappings


def anonymize(text: str, config: dict, existing_context: AnonymizationContext = None) -> Tuple[str, AnonymizationContext]:
    """
    Anonymize PII in text.

    Args:
        text: Input text with PII
        config: Configuration with anonymization settings
        existing_context: Optional existing context to reuse (for continuation rounds).
                         When provided, known PII values get the SAME placeholders as before,
                         preventing data corruption across confirmation/question dialog rounds.

    Returns:
        Tuple of (anonymized_text, context for de-anonymization)
    """
    if existing_context is not None:
        # Reuse existing context - preserves mappings from previous round
        context = AnonymizationContext()
        context.mappings = dict(existing_context.mappings)
        context.reverse_mappings = dict(existing_context.reverse_mappings)
        context.counters = dict(existing_context.counters)
        log(f"[Anonymizer] Reusing existing context ({len(context.mappings)} mappings, counters: {dict(context.counters)})")
    else:
        context = AnonymizationContext()

    if not text or not text.strip():
        return text, context

    anon_config = config.get("anonymization", {})
    pii_types = anon_config.get("pii_types", [
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION"
    ])
    language = anon_config.get("language", "de")
    placeholder_format = anon_config.get("placeholder_format", "<{entity_type}_{index}>")
    log_anonymization = anon_config.get("log_anonymization", False)

    # Load merged whitelist from anonymizer.json (system + user) AND system.json (legacy)
    whitelist = _get_merged_whitelist(config)

    # Load confidence threshold from anonymizer.json (system + user merged)
    anon_json_config = _load_anonymizer_config()
    confidence_threshold = anon_json_config.get("confidence_threshold", 0.75)

    # Extract link_ref values and add to whitelist - these must NEVER be anonymized
    # They're used by the link placeholder system: {{LINK:a3f2b1c8}}
    link_ref_values = _extract_link_ref_values(text)
    if link_ref_values:
        whitelist = list(whitelist) + list(link_ref_values)

    anonymized = text

    # URL anonymization (doesn't require Presidio)
    if "URL" in pii_types:
        anonymized = _anonymize_urls(anonymized, context, placeholder_format, whitelist=whitelist)
        # Anonymize emails BEFORE domains (prevents partial anonymization like p.weiss@[DOMAIN-1])
        anonymized = _anonymize_emails(anonymized, context, placeholder_format, whitelist=whitelist)
        # Anonymize German addresses (Presidio misses these: "Finkenweg 38, 76547")
        anonymized = _anonymize_addresses(anonymized, context, placeholder_format, whitelist=whitelist)
        # Anonymize names in email headers (From: Weiß Patrick - Presidio misses German ß/ü)
        anonymized = _anonymize_email_header_names(anonymized, context, placeholder_format, whitelist=whitelist)
        # Also anonymize bare domains (e.g., company.com) after URLs and emails
        anonymized = _anonymize_domains(anonymized, context, placeholder_format, whitelist=whitelist)

    # Pre-replace known values from existing context BEFORE calling Presidio
    # This prevents Presidio from re-detecting already-known entities with
    # wrong counters or entity types (e.g., phone getting PHONE_NUMBER_2 instead of _1)
    if existing_context and context.reverse_mappings:
        # Sort by length descending to prevent partial replacements
        sorted_mappings = sorted(context.reverse_mappings.items(), key=lambda x: len(x[0]), reverse=True)
        for original_value, placeholder in sorted_mappings:
            if original_value in anonymized:
                anonymized = anonymized.replace(original_value, placeholder)

    # Presidio-based PII detection
    if not is_available():
        if context.mappings:
            return anonymized, context
        return text, context

    # Filter out URL from Presidio types (handled separately)
    presidio_types = [t for t in pii_types if t != "URL"]

    try:
        # Always use service subprocess (same behavior in dev and compiled)
        service_result, service_mappings = _call_service_subprocess(
            anonymized, language, presidio_types, placeholder_format, confidence_threshold
        )

        # Filter service results for false positives, greetings, duplicates
        filtered_text, filtered_mappings = _filter_service_results(
            service_result, service_mappings, context, whitelist=whitelist
        )

        # Merge filtered mappings into context
        for placeholder, original in filtered_mappings.items():
            if original not in context.reverse_mappings:
                context.mappings[placeholder] = original
                context.reverse_mappings[original] = placeholder
            elif placeholder not in context.mappings:
                # Value already known with different placeholder (e.g., renumbered
                # due to Presidio subprocess counter conflict). Add the new
                # placeholder too so de-anonymization of tool args works.
                context.mappings[placeholder] = original

        anonymized = filtered_text

        if not context.mappings:
            if log_anonymization:
                log("[Anonymizer] No PII detected")
            return text, context

        # Second pass: Replace any remaining occurrences of mapped values
        # This catches cases where the same name appears multiple times
        # but was only detected in some contexts by Presidio
        anonymized = _second_pass_replacement(anonymized, context)

        # Safety net: verify all placeholders in text have mappings
        # Catches any remaining orphaned placeholders from counter conflicts
        orphan_pattern = re.compile(r'<([A-Z_]+_\d+)>')
        for match in orphan_pattern.finditer(anonymized):
            token = f"<{match.group(1)}>"
            if token not in context.mappings:
                log(f"[Anonymizer] WARNING: Orphaned placeholder {token} in text (no mapping)")

        if log_anonymization and context.mappings:
            log(f"[Anonymizer] Anonymized {len(context.mappings)} PII entities:")
            for placeholder, original in context.mappings.items():
                # Truncate long values for logging
                display = original[:30] + "..." if len(original) > 30 else original
                log(f"[Anonymizer]   {placeholder} <- '{display}'")

        return anonymized, context

    except Exception as e:
        log(f"[Anonymizer] Error during anonymization: {e}")
        return text, context


def anonymize_with_context(
    text: str,
    config: dict,
    context: AnonymizationContext
) -> Tuple[str, AnonymizationContext]:
    """
    Anonymize PII in text using an existing context.

    This allows accumulating mappings across multiple texts (e.g., tool results).
    Same PII values will get the same placeholder across all texts.

    Args:
        text: Input text with PII
        config: Configuration with anonymization settings
        context: Existing context to accumulate mappings

    Returns:
        Tuple of (anonymized_text, updated context)
    """
    if not text or not text.strip():
        return text, context

    anon_config = config.get("anonymization", {})
    pii_types = anon_config.get("pii_types", [
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION"
    ])
    language = anon_config.get("language", "de")
    placeholder_format = anon_config.get("placeholder_format", "<{entity_type}_{index}>")
    log_anonymization = anon_config.get("log_anonymization", False)

    # Load merged whitelist from anonymizer.json (system + user) AND system.json (legacy)
    whitelist = _get_merged_whitelist(config)

    # Load confidence threshold from anonymizer.json (system + user merged)
    anon_json_config = _load_anonymizer_config()
    confidence_threshold = anon_json_config.get("confidence_threshold", 0.75)

    anonymized = text
    new_mappings = 0

    # URL anonymization (doesn't require Presidio)
    if "URL" in pii_types:
        old_count = len(context.mappings)
        anonymized = _anonymize_urls(anonymized, context, placeholder_format, whitelist=whitelist)
        # Anonymize emails BEFORE domains
        anonymized = _anonymize_emails(anonymized, context, placeholder_format, whitelist=whitelist)
        # Anonymize German addresses
        anonymized = _anonymize_addresses(anonymized, context, placeholder_format, whitelist=whitelist)
        # Anonymize names in email headers (From: Weiß Patrick)
        anonymized = _anonymize_email_header_names(anonymized, context, placeholder_format, whitelist=whitelist)
        # Also anonymize bare domains - skip whitelisted
        anonymized = _anonymize_domains(anonymized, context, placeholder_format, whitelist=whitelist)
        new_mappings += len(context.mappings) - old_count

    # Presidio-based PII detection
    if not is_available():
        return anonymized, context

    # Filter out URL from Presidio types (handled separately)
    presidio_types = [t for t in pii_types if t != "URL"]

    try:
        # Always use service subprocess (same behavior in dev and compiled)
        service_result, service_mappings = _call_service_subprocess(
            anonymized, language, presidio_types, placeholder_format, confidence_threshold
        )

        # Filter service results for false positives, greetings, duplicates
        filtered_text, filtered_mappings = _filter_service_results(
            service_result, service_mappings, context, whitelist=whitelist
        )

        # Merge filtered mappings into context
        for placeholder, original in filtered_mappings.items():
            if original not in context.reverse_mappings:
                context.mappings[placeholder] = original
                context.reverse_mappings[original] = placeholder
                new_mappings += 1
            elif placeholder not in context.mappings:
                # Value already known with different placeholder (renumbered)
                context.mappings[placeholder] = original
                new_mappings += 1

        anonymized = filtered_text

        # Second pass: Replace any remaining occurrences of mapped values
        # This catches cases where the same name appears multiple times
        # but was only detected in some contexts by Presidio
        anonymized = _second_pass_replacement(anonymized, context)

        if log_anonymization and new_mappings > 0:
            log(f"[Anonymizer] Added {new_mappings} new PII entities (total: {len(context.mappings)})")

        return anonymized, context

    except Exception as e:
        log(f"[Anonymizer] Error during anonymization: {e}")
        return text, context


def deanonymize(text: str, context: AnonymizationContext) -> str:
    """
    Restore original PII values in text.

    Args:
        text: Anonymized text with placeholders
        context: Context from anonymization step

    Returns:
        Text with original PII values restored
    """
    if not context.mappings:
        return text

    result = text
    for placeholder, original in context.mappings.items():
        result = result.replace(placeholder, original)

    return result


def get_used_mappings(text: str, context: AnonymizationContext) -> dict:
    """
    Get only the mappings that were actually used (appear in the text).

    Args:
        text: Text that may contain placeholders
        context: Context with all mappings

    Returns:
        Dict of only the mappings whose placeholders appear in the text
    """
    if not context.mappings:
        return {}

    used = {}
    for placeholder, original in context.mappings.items():
        if placeholder in text:
            used[placeholder] = original

    return used
