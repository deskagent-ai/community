# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""File watcher service for automatic agent refresh.

Watches agent directories and config files for changes,
then clears the cache and broadcasts a refresh event.
"""

import threading
from pathlib import Path
from typing import List, Optional

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None  # Placeholder for type hints


# Only define AgentFileHandler if watchdog is available
# This prevents NameError when FileSystemEventHandler doesn't exist
if WATCHDOG_AVAILABLE:
    class AgentFileHandler(FileSystemEventHandler):
        """Handle file system events for agent files."""

        def __init__(self, debounce_seconds: float = 0.5):
            """Initialize handler with debounce timer.

            Args:
                debounce_seconds: Time to wait before triggering refresh
            """
            super().__init__()
            self._debounce_timer: Optional[threading.Timer] = None
            self._debounce_seconds = debounce_seconds
            self._lock = threading.Lock()

        def _should_handle(self, event: "FileSystemEvent") -> bool:
            """Check if event should trigger a refresh."""
            if event.is_directory:
                return False
            src_path = str(event.src_path)
            # Watch for .md agent files and agents.json config
            return src_path.endswith('.md') or src_path.endswith('agents.json')

        def on_any_event(self, event: "FileSystemEvent"):
            """Handle any file system event with debouncing."""
            if not self._should_handle(event):
                return

            with self._lock:
                # Cancel existing timer if any
                if self._debounce_timer:
                    self._debounce_timer.cancel()

                # Start new timer
                self._debounce_timer = threading.Timer(
                    self._debounce_seconds,
                    self._trigger_refresh,
                    args=[event.src_path]
                )
                self._debounce_timer.start()

        def _trigger_refresh(self, changed_path: str):
            """Clear cache and broadcast refresh event."""
            try:
                from ai_agent import system_log
                system_log(f"[FileWatcher] File changed: {changed_path}")
            except ImportError:
                pass

            try:
                from .discovery import clear_cache
                clear_cache(broadcast=True)
            except ImportError as e:
                try:
                    from ai_agent import system_log
                    system_log(f"[FileWatcher] Error clearing cache: {e}")
                except ImportError:
                    pass
else:
    AgentFileHandler = None  # Placeholder when watchdog not available


# Global observer instance
_observer: Optional["Observer"] = None
_lock = threading.Lock()


def start_file_watcher(paths: List[Path]) -> bool:
    """Start watching agent directories for changes.

    Args:
        paths: List of directories to watch

    Returns:
        True if watcher started successfully, False otherwise
    """
    global _observer

    if not WATCHDOG_AVAILABLE:
        try:
            from ai_agent import system_log
            system_log("[FileWatcher] watchdog not available, skipping file watcher")
        except ImportError:
            pass
        return False

    with _lock:
        if _observer is not None:
            return True  # Already running

        _observer = Observer()
        handler = AgentFileHandler()

        watch_count = 0
        for path in paths:
            if path.exists() and path.is_dir():
                _observer.schedule(handler, str(path), recursive=False)
                watch_count += 1
                try:
                    from ai_agent import system_log
                    system_log(f"[FileWatcher] Watching: {path}")
                except ImportError:
                    pass

        if watch_count == 0:
            _observer = None
            return False

        _observer.start()
        try:
            from ai_agent import system_log
            system_log(f"[FileWatcher] Started watching {watch_count} directories")
        except ImportError:
            pass
        return True


def stop_file_watcher():
    """Stop the file watcher."""
    global _observer

    with _lock:
        if _observer is None:
            return

        try:
            from ai_agent import system_log
            system_log("[FileWatcher] Stopping file watcher...")
        except ImportError:
            pass

        _observer.stop()
        _observer.join(timeout=5.0)
        _observer = None


def is_file_watcher_running() -> bool:
    """Check if file watcher is currently running."""
    with _lock:
        return _observer is not None and _observer.is_alive()
