# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Routes for Audio Transcription (OpenAI Whisper).

Provides voice-to-text transcription via OpenAI's Whisper API.
Only available when OpenAI API key is configured.
"""

import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

router = APIRouter()


def is_voice_available() -> tuple[bool, str | None]:
    """
    Check if voice transcription is available.

    Returns:
        (available: bool, reason: str | None)
        - (True, None) if voice input is available
        - (False, reason) if not available, with reason string

    Reasons:
        - "disabled_in_config": voice_input.enabled = false
        - "openai_not_configured": OpenAI API key missing or invalid
    """
    from ..skills import load_config

    config = load_config()

    # Check system config for voice_input.enabled (default: true)
    voice_config = config.get("voice_input", {})
    enabled = voice_config.get("enabled", True)

    if not enabled:
        return (False, "disabled_in_config")

    # Check OpenAI API key
    openai_config = config.get("ai_backends", {}).get("openai", {})
    api_key = openai_config.get("api_key", "")

    if not api_key or api_key.startswith("YOUR_") or len(api_key) < 10:
        return (False, "openai_not_configured")

    return (True, None)


def build_whisper_prompt() -> str | None:
    """
    Build Whisper prompt from knowledge base or config.

    Priority:
    1. knowledge/whisper_keywords.md (if exists)
    2. Extract from knowledge/company.md and knowledge/products.md
    3. voice_input.prompt from config

    Returns:
        Prompt string or None
    """
    from ..skills import load_config
    from pathlib import Path
    import sys

    # Path is set up by assistant/__init__.py
    from paths import PROJECT_DIR

    knowledge_dir = PROJECT_DIR / "knowledge"

    # 1. Check for dedicated whisper_keywords.md
    whisper_file = knowledge_dir / "whisper_keywords.md"
    if whisper_file.exists():
        try:
            content = whisper_file.read_text(encoding="utf-8").strip()
            # Remove markdown headers and extract plain text
            lines = [line.strip() for line in content.split("\n")
                     if line.strip() and not line.startswith("#")]
            return " ".join(lines)
        except Exception:
            pass

    # 2. Auto-extract from company.md and products.md
    keywords = []

    company_file = knowledge_dir / "company.md"
    if company_file.exists():
        try:
            content = company_file.read_text(encoding="utf-8")
            # Extract company names (simple heuristic: capitalized words)
            import re
            # Find lines with company/product names
            for line in content.split("\n"):
                if "GmbH" in line or "AG" in line or "Inc" in line:
                    # Extract company name
                    match = re.search(r'([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\s+(?:GmbH|AG|Inc))', line)
                    if match:
                        keywords.append(match.group(1))
        except Exception:
            pass

    products_file = knowledge_dir / "products.md"
    if products_file.exists():
        try:
            content = products_file.read_text(encoding="utf-8")
            # Extract product names from headers or lists
            import re
            for line in content.split("\n"):
                # Extract from markdown headers
                if line.startswith("#"):
                    product = line.lstrip("#").strip()
                    if product and len(product) < 50:  # Reasonable product name length
                        keywords.append(product)
        except Exception:
            pass

    if keywords:
        # Deduplicate and limit
        unique_keywords = list(dict.fromkeys(keywords))[:20]  # Max 20 keywords
        return ", ".join(unique_keywords)

    # 3. Fallback to config
    config = load_config()
    voice_config = config.get("voice_input", {})
    return voice_config.get("prompt", None)


@router.get("/transcribe/status")
async def get_transcription_status():
    """
    Check if voice transcription is available.

    Returns availability status based on:
    - voice_input.enabled in system.json (default: true)
    - OpenAI API key configured in backends.json
    """
    from ..skills import load_config

    available, reason = is_voice_available()

    if not available:
        return {"available": False, "reason": reason}

    # Return config options for frontend
    config = load_config()
    voice_config = config.get("voice_input", {})

    return {
        "available": True,
        "reason": None,
        "auto_submit": voice_config.get("auto_submit", True),
        "hotkey": voice_config.get("hotkey", "Ctrl+M")
    }


@router.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Transcribe audio using OpenAI Whisper API.

    Accepts audio file (webm, wav, mp3, etc.) and returns transcribed text.
    Requires:
    - voice_input.enabled in system.json (default: true)
    - OpenAI API key configured in backends.json
    """
    from ai_agent import log
    from ..skills import load_config

    # Check availability using centralized function
    available, reason = is_voice_available()
    if not available:
        error_messages = {
            "disabled_in_config": "Voice input is disabled in system configuration",
            "openai_not_configured": "OpenAI API key not configured"
        }
        raise HTTPException(
            status_code=400,
            detail=error_messages.get(reason, "Voice input not available")
        )

    config = load_config()
    voice_config = config.get("voice_input", {})
    # Language: "auto" or empty = auto-detect, otherwise use specified language
    language = voice_config.get("language", "auto")

    # Build prompt from knowledge base or config
    prompt = build_whisper_prompt()

    # Get API key
    openai_config = config.get("ai_backends", {}).get("openai", {})
    api_key = openai_config.get("api_key", "")

    # Import OpenAI
    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openai package not installed. Run: pip install openai"
        )

    # Read audio content
    audio_content = await audio.read()
    if len(audio_content) < 1000:
        raise HTTPException(
            status_code=400,
            detail="Audio file too short or empty"
        )

    log(f"[Transcribe] Received audio: {len(audio_content)} bytes, type: {audio.content_type}")

    # Determine file suffix from content type
    content_type = audio.content_type or ""
    if "webm" in content_type:
        suffix = ".webm"
    elif "wav" in content_type:
        suffix = ".wav"
    elif "mp3" in content_type or "mpeg" in content_type:
        suffix = ".mp3"
    elif "ogg" in content_type:
        suffix = ".ogg"
    else:
        suffix = ".webm"  # Default for browser recordings

    # Save to temp file (Whisper API needs a file)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_content)
        tmp_path = tmp.name

    try:
        # Call OpenAI Whisper API
        client = OpenAI(api_key=api_key)

        # Get audio duration for cost tracking
        try:
            import soundfile as sf
            audio_info = sf.info(tmp_path)
            audio_duration_seconds = audio_info.duration
        except Exception:
            # Fallback: estimate from file size (rough approximation)
            # Assume 16kHz, 16-bit mono WAV = ~32KB per second
            audio_duration_seconds = len(audio_content) / 32000

        with open(tmp_path, "rb") as audio_file:
            # Build API call parameters
            api_params = {
                "model": "whisper-1",
                "file": audio_file,
            }

            # Language: "auto" or empty = let Whisper auto-detect
            # Otherwise pass specified language code (de, en, etc.)
            if language and language.lower() != "auto":
                api_params["language"] = language

            # Add optional prompt for better recognition (keywords, context)
            if prompt:
                api_params["prompt"] = prompt

            transcript = client.audio.transcriptions.create(**api_params)

        text = transcript.text.strip()
        log(f"[Transcribe] Result: {len(text)} chars - '{text[:50]}...'")

        # Track cost (Whisper: $0.006 per minute = $0.0001 per second)
        audio_minutes = audio_duration_seconds / 60.0
        cost_usd = audio_minutes * 0.006

        try:
            from ..cost_tracker import add_cost
            add_cost(
                cost_usd=cost_usd,
                audio_seconds=audio_duration_seconds,
                model="whisper-1",
                task_type="transcription",
                backend="whisper"
            )
            log(f"[Transcribe] Cost tracked: ${cost_usd:.6f} ({audio_duration_seconds:.1f}s)")
        except Exception as e:
            log(f"[Transcribe] Cost tracking failed: {e}")

        return {"text": text, "success": True}

    except Exception as e:
        log(f"[Transcribe] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temp file
        Path(tmp_path).unlink(missing_ok=True)
