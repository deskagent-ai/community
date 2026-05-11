# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Playwright fixtures for UI tests.

This file provides browser fixtures for E2E testing.

Usage:
    # Default (port 8765):
    pytest tests/test_ui/ -v

    # Custom port:
    pytest tests/test_ui/ -v --base-url=http://localhost:5005

    # With visible browser:
    pytest tests/test_ui/ -v --headed

    # Slow motion for debugging:
    pytest tests/test_ui/ -v --headed --slowmo=500
"""

import os

import pytest


def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line(
        "markers", "e2e: mark test as end-to-end test (requires running server)"
    )


@pytest.fixture(scope="session")
def browser_type_launch_args(request):
    """Browser launch arguments.

    Respects CLI flags:
      --headed: Show browser window
      --slowmo: Add delay between actions (in ms)
    """
    # Check CLI options - don't override if they're set
    headless = not request.config.getoption("--headed", default=False)
    slowmo = request.config.getoption("--slowmo", default=0)

    return {
        "headless": headless,
        "slow_mo": slowmo,
    }


@pytest.fixture(scope="session")
def browser_context_args():
    """Default browser context arguments."""
    return {
        "viewport": {"width": 1280, "height": 800},
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
    }


@pytest.fixture(scope="session")
def base_url(request):
    """
    Base URL for tests.
    Priority: --base-url > DESKAGENT_URL env var > default (8765)
    """
    # Check for --base-url CLI option first
    cli_url = request.config.getoption("--base-url", default=None)
    if cli_url:
        return cli_url
    # Fall back to environment variable
    return os.environ.get("DESKAGENT_URL", "http://localhost:8765")


# Skip UI tests if server is not running
def pytest_collection_modifyitems(config, items):
    """Skip UI tests if --skip-e2e is passed."""
    if config.getoption("--skip-e2e", default=False):
        skip_e2e = pytest.mark.skip(reason="--skip-e2e option provided")
        for item in items:
            if "test_ui" in str(item.fspath):
                item.add_marker(skip_e2e)


def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--skip-e2e",
        action="store_true",
        default=False,
        help="Skip E2E/UI tests"
    )
    parser.addoption(
        "--e2e-only",
        action="store_true",
        default=False,
        help="Run only E2E/UI tests"
    )
