# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Shared test fixtures and configuration.

Includes fixtures for:
- Live/sample configurations
- Mock LLM backend for cost-free testing
- Anonymization test data
- Temporary directories
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# === Pytest Configuration ===

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests that make real API calls (costs money!) - skip with '-m \"not integration\"'"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "mock: marks tests that use mock LLM (no API costs)"
    )
    config.addinivalue_line(
        "markers", "record: marks tests that record real API responses for snapshots"
    )

# Add scripts directory to path for imports
SCRIPTS_DIR = Path(__file__).parent.parent
PROJECT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))


# === Configuration Fixtures ===

@pytest.fixture(scope="module")
def live_config():
    """
    Load real configuration for integration tests.
    Loads from workspace config/*.json files.
    """
    config = {}

    # Try workspace config directory
    workspace_dir = PROJECT_DIR.parent
    config_dir = workspace_dir / "config"

    # Load system.json
    system_file = config_dir / "system.json"
    if system_file.exists():
        config.update(json.loads(system_file.read_text(encoding="utf-8")))

    # Load backends.json
    backends_file = config_dir / "backends.json"
    if backends_file.exists():
        backends_config = json.loads(backends_file.read_text(encoding="utf-8"))
        config["ai_backends"] = backends_config.get("ai_backends", {})
        if "default_ai" in backends_config:
            config["default_ai"] = backends_config["default_ai"]

    # Fallback to legacy config.json in deskagent/
    if not config.get("ai_backends"):
        legacy_file = PROJECT_DIR / "config.json"
        if legacy_file.exists():
            config = json.loads(legacy_file.read_text(encoding="utf-8"))

    if not config.get("ai_backends"):
        pytest.skip("No backend configuration found")

    return config


@pytest.fixture
def sample_config():
    """Sample config.json for testing."""
    return {
        "default_ai": "claude",
        "ai_backends": {
            "claude": {
                "type": "claude_cli",
                "timeout": 120
            },
            "qwen": {
                "type": "qwen_agent",
                "model": "qwen2.5:7b"
            },
            "gemini": {
                "type": "gemini_adk",
                "api_key": "test-key",
                "model": "gemini-2.5-pro"
            }
        },
        "anonymization": {
            "enabled": True,
            "language": "de",
            "pii_types": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "URL"],
            "placeholder_format": "<{entity_type}_{index}>"
        },
        "skills": {
            "mail_reply": {
                "ai": "claude",
                "anonymize": True
            }
        },
        "agents": {
            "create_offer": {
                "ai": "claude",
                "anonymize": True
            }
        }
    }


@pytest.fixture
def minimal_config():
    """Minimal config for testing defaults."""
    return {
        "timeout": 120
    }


# === AI Agent Response Fixtures ===

@pytest.fixture
def json_response_plain():
    """Plain JSON response from LLM."""
    return '{"action": "reply", "content": "Hello!"}'


@pytest.fixture
def json_response_markdown():
    """JSON response wrapped in markdown code block."""
    return '''Here is the response:

```json
{"action": "reply", "content": "Hello!"}
```

That's the result.'''


@pytest.fixture
def json_response_with_text():
    """JSON embedded in text without markdown."""
    return 'The result is {"action": "reply", "content": "Hello!"} as requested.'


# === Anonymization Fixtures ===

@pytest.fixture
def text_with_pii():
    """Sample text containing PII for anonymization tests."""
    return """
Von: Max Mustermann <max.mustermann@example.com>
Betreff: Anfrage

Hallo,
ich bin Max Mustermann von der Firma ABC GmbH.
Meine Telefonnummer ist +49 123 456789.
Unsere Website ist https://abc-company.example.com

Mit freundlichen Grüßen
Max Mustermann
"""


@pytest.fixture
def text_with_safe_urls():
    """Text with URLs that should NOT be anonymized."""
    return """
Bitte schauen Sie auf https://doc.example.com für die Dokumentation.
Mehr Infos auf https://github.com/example-org/project
"""


# === Skill Fixtures ===

@pytest.fixture
def sample_skill_content():
    """Sample skill file content."""
    return """name: Mail Reply
use_knowledge: true

Du bist ein professioneller Assistent.
Beantworte die E-Mail höflich und prägnant.
"""


# === MCP Mock Fixtures ===

@pytest.fixture
def mock_outlook_com(mocker):
    """Mock win32com.client.Dispatch for Outlook."""
    mock_dispatch = mocker.patch("win32com.client.Dispatch")

    # Create mock Outlook application
    mock_app = MagicMock()
    mock_namespace = MagicMock()
    mock_inbox = MagicMock()

    # Setup the chain
    mock_dispatch.return_value = mock_app
    mock_app.GetNamespace.return_value = mock_namespace
    mock_namespace.GetDefaultFolder.return_value = mock_inbox

    return {
        "dispatch": mock_dispatch,
        "app": mock_app,
        "namespace": mock_namespace,
        "inbox": mock_inbox
    }


@pytest.fixture
def mock_http_responses(mocker):
    """Mock HTTP responses for Billomat API tests."""
    import responses

    @responses.activate
    def setup_responses():
        # Add mock responses for Billomat API
        responses.add(
            responses.GET,
            "https://test.billomat.net/api/clients",
            json={"clients": {"client": []}},
            status=200
        )

    return responses


# === Temp Directory Fixtures ===

@pytest.fixture
def temp_knowledge_dir(tmp_path):
    """Create a temporary knowledge directory with sample files."""
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()

    # Create sample knowledge files
    (knowledge_dir / "company.md").write_text(
        "# Company Info\nExample GmbH is a software company.",
        encoding="utf-8"
    )
    (knowledge_dir / "products.md").write_text(
        "# Products\n- Professional Edition: €1,098",
        encoding="utf-8"
    )

    return knowledge_dir


@pytest.fixture
def temp_skills_dir(tmp_path, sample_skill_content):
    """Create a temporary skills directory with sample files."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create sample skill file
    (skills_dir / "mail_reply.md").write_text(
        sample_skill_content,
        encoding="utf-8"
    )

    return skills_dir


@pytest.fixture
def temp_templates_dir(tmp_path):
    """Create a temporary templates directory with sample files."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    # Create sample template file
    (templates_dir / "dialogs.md").write_text(
        "# User-Dialoge\n\n## QUESTION_NEEDED\nFormat for user questions.",
        encoding="utf-8"
    )

    return templates_dir


# === Cost Tracker Fixtures ===

@pytest.fixture
def temp_costs_file(tmp_path):
    """Create a temporary costs file."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    costs_file = data_dir / "api_costs.json"
    return costs_file


@pytest.fixture
def sample_costs_data():
    """Sample cost tracking data."""
    return {
        "total_usd": 1.5,
        "total_input_tokens": 10000,
        "total_output_tokens": 5000,
        "task_count": 5,
        "by_model": {
            "claude-sonnet-4": {
                "cost_usd": 1.0,
                "input_tokens": 8000,
                "output_tokens": 4000,
                "task_count": 3
            }
        },
        "by_date": {
            "2024-12-20": {
                "cost_usd": 0.5,
                "input_tokens": 2000,
                "output_tokens": 1000,
                "task_count": 2
            }
        },
        "last_updated": "2024-12-20T10:00:00"
    }


# =============================================================================
# Mock LLM Fixtures (for cost-free testing)
# =============================================================================

@pytest.fixture
def mock_config():
    """
    Configuration with mock mode enabled.

    All AI backends are configured but mock_mode intercepts calls.
    Tests can run against any backend without API costs.
    """
    return {
        "default_ai": "gemini",
        "mock_mode": {
            "enabled": True
        },
        "ai_backends": {
            "claude_api": {
                "type": "claude_api",
                "api_key": "mock-key",
                "model": "claude-sonnet-4-20250514"
            },
            "claude_sdk": {
                "type": "claude_agent_sdk",
                "model": "claude-sonnet-4-20250514"
            },
            "claude_cli": {
                "type": "claude_cli",
                "timeout": 120
            },
            "gemini": {
                "type": "gemini_adk",
                "api_key": "mock-key",
                "model": "gemini-2.5-pro"
            },
            "gemini_flash": {
                "type": "gemini_adk",
                "api_key": "mock-key",
                "model": "gemini-2.5-flash"
            },
            "gemini_3": {
                "type": "gemini_adk",
                "api_key": "mock-key",
                "model": "gemini-3.1-pro-preview"
            },
            "gemini_3_flash": {
                "type": "gemini_adk",
                "api_key": "mock-key",
                "model": "gemini-3.1-flash-preview"
            },
            "openai": {
                "type": "openai_api",
                "api_key": "mock-key",
                "model": "gpt-4o"
            },
            "ollama": {
                "type": "ollama_native",
                "model": "llama3"
            },
            "qwen": {
                "type": "qwen_agent",
                "model": "qwen2.5:7b"
            }
        },
        "anonymization": {
            "enabled": True,
            "language": "de",
            "pii_types": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"],
            "placeholder_format": "<{entity_type}_{index}>"
        }
    }


@pytest.fixture
def mock_tracker():
    """
    Shared MockTracker for assertions in tests.

    Usage:
        def test_something(mock_config, mock_tracker):
            result = call_agent(prompt="Hello", config=mock_config, ...)
            mock_tracker.assert_prompt_contains("Hello")
            mock_tracker.assert_tool_called("outlook_get_email")
    """
    from ai_agent.mock_llm import MockTracker
    tracker = MockTracker()
    yield tracker
    tracker.reset()  # Cleanup after test


@pytest.fixture
def mock_backend(mock_config, mock_tracker):
    """
    Ready-to-use MockLLMBackend instance.

    Usage:
        def test_mock_call(mock_backend):
            response = mock_backend.call(prompt="Hello", agent_name="test")
            assert response.success
            assert response.cost_usd == 0
    """
    from ai_agent.mock_llm import MockLLMBackend
    backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)
    yield backend
    backend.reset()


@pytest.fixture
def temp_mock_dir(tmp_path):
    """
    Temporary directory for mock LLM responses.

    Creates the directory structure:
    - tmp/mocks/llm/
    - tmp/mocks/scenarios/
    """
    mocks_dir = tmp_path / "mocks"
    llm_dir = mocks_dir / "llm"
    scenarios_dir = mocks_dir / "scenarios"

    llm_dir.mkdir(parents=True)
    scenarios_dir.mkdir(parents=True)

    return {
        "root": mocks_dir,
        "llm": llm_dir,
        "scenarios": scenarios_dir
    }


@pytest.fixture
def mock_llm_responses(temp_mock_dir):
    """
    Create sample mock LLM response files.

    Returns the path to the llm directory.
    """
    llm_dir = temp_mock_dir["llm"]

    # Default responses
    default_mocks = {
        "_meta": {
            "description": "Default mock LLM responses for testing",
            "version": "1.0"
        },
        "responses": [
            {
                "id": "greeting",
                "match": {
                    "prompt": {"$contains": "hello"}
                },
                "response": {
                    "content": "Hello! How can I help you today?",
                    "model": "mock-claude",
                    "input_tokens": 10,
                    "output_tokens": 15
                }
            },
            {
                "id": "email-reply",
                "match": {
                    "prompt": {"$contains": "email"},
                    "agent": "reply_email"
                },
                "response": {
                    "content": "I'll help you reply to that email.",
                    "tool_calls": [
                        {"name": "outlook_get_selected_email", "arguments": {}}
                    ],
                    "model": "mock-claude"
                }
            },
            {
                "id": "default",
                "match": {"$default": True},
                "response": {
                    "content": "[Mock] Request processed successfully.",
                    "model": "mock-default"
                }
            }
        ]
    }

    (llm_dir / "default.json").write_text(
        json.dumps(default_mocks, indent=2),
        encoding="utf-8"
    )

    return llm_dir
