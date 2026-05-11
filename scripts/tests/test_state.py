# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.state module (PID file management).
"""

import os
import pytest
from pathlib import Path
from unittest import mock
from assistant.state import (
    get_pid_file,
    write_pid_file,
    remove_pid_file,
    get_running_pid,
    is_instance_running,
    acquire_instance_lock,
    release_instance_lock,
)


@pytest.fixture
def temp_pid_file(tmp_path, monkeypatch):
    """Mock DESKAGENT_DIR to use temp directory for PID file."""
    # Mock the DESKAGENT_DIR to point to temp dir
    mock_dir = tmp_path / "deskagent"
    mock_dir.mkdir()

    # Patch get_pid_file to return temp path
    def mock_get_pid_file():
        return mock_dir / "deskagent.pid"

    monkeypatch.setattr("assistant.state.get_pid_file", mock_get_pid_file)
    return mock_dir / "deskagent.pid"


def test_write_pid_file(temp_pid_file):
    """Test writing PID file."""
    write_pid_file()
    assert temp_pid_file.exists()
    pid = int(temp_pid_file.read_text().strip())
    assert pid == os.getpid()


def test_remove_pid_file(temp_pid_file):
    """Test removing PID file."""
    # Create PID file first
    write_pid_file()
    assert temp_pid_file.exists()

    # Remove it
    remove_pid_file()
    assert not temp_pid_file.exists()


def test_remove_pid_file_nonexistent(temp_pid_file):
    """Test removing PID file that doesn't exist (should not error)."""
    assert not temp_pid_file.exists()
    remove_pid_file()  # Should not raise


def test_get_running_pid_no_file(temp_pid_file):
    """Test get_running_pid when no PID file exists."""
    assert not temp_pid_file.exists()
    assert get_running_pid() is None


def test_get_running_pid_current_process(temp_pid_file):
    """Test get_running_pid with current process (should return PID)."""
    write_pid_file()
    running_pid = get_running_pid()
    assert running_pid == os.getpid()


def test_get_running_pid_stale_pid(temp_pid_file, monkeypatch):
    """Test get_running_pid with stale PID (process not running)."""
    # Write a PID that definitely doesn't exist (999999)
    temp_pid_file.write_text("999999")

    # Mock psutil.pid_exists to return False
    def mock_pid_exists(pid):
        return False

    monkeypatch.setattr("psutil.pid_exists", mock_pid_exists)

    # Should return None and clean up stale PID file
    assert get_running_pid() is None
    assert not temp_pid_file.exists()


def test_is_instance_running(temp_pid_file):
    """Test is_instance_running."""
    # No PID file -> not running
    assert not is_instance_running()

    # Write current PID -> is running
    write_pid_file()
    assert is_instance_running()

    # Remove PID file -> not running
    remove_pid_file()
    assert not is_instance_running()


def test_acquire_instance_lock_success(temp_pid_file):
    """Test acquiring instance lock when no other instance is running."""
    assert not temp_pid_file.exists()
    assert acquire_instance_lock() is True
    assert temp_pid_file.exists()


def test_acquire_instance_lock_already_locked(temp_pid_file):
    """Test acquiring instance lock when already locked."""
    # First lock should succeed
    assert acquire_instance_lock() is True

    # Second lock should fail
    assert acquire_instance_lock() is False


def test_release_instance_lock(temp_pid_file):
    """Test releasing instance lock."""
    acquire_instance_lock()
    assert temp_pid_file.exists()

    release_instance_lock()
    assert not temp_pid_file.exists()


def test_full_lifecycle(temp_pid_file):
    """Test full lifecycle: acquire -> check -> release."""
    # Start: no lock
    assert not is_instance_running()

    # Acquire lock
    assert acquire_instance_lock() is True
    assert is_instance_running()
    assert get_running_pid() == os.getpid()

    # Try to acquire again (should fail)
    assert acquire_instance_lock() is False

    # Release lock
    release_instance_lock()
    assert not is_instance_running()
    assert get_running_pid() is None

    # Can acquire again after release
    assert acquire_instance_lock() is True
