# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Agent Scheduler
===============
Time-based scheduling for automated agent execution.
Supports simple interval syntax: "30m", "1h", "6h", "1d", "weekly".

Configuration in triggers.json:
{
  "daily_check": {
    "type": "schedule",
    "name": "Daily Email Check",
    "enabled": true,
    "interval": "1d",
    "at": "08:00",
    "agent": "daily_check",
    "inputs": {}
  }
}

Interval formats:
- "30m" = every 30 minutes
- "1h" = every hour
- "6h" = every 6 hours
- "1d" = daily (use "at" for specific time)
- "weekly" = weekly (use "at" for day and time, e.g. "Mon 09:00")
"""

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Path is set up by assistant/__init__.py
from paths import get_data_dir, PROJECT_DIR

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass


# =============================================================================
# Configuration
# =============================================================================

def _load_triggers_config() -> dict:
    """Load triggers.json config."""
    config_file = PROJECT_DIR / "config" / "triggers.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            system_log(f"[Scheduler] Error loading triggers.json: {e}")
    return {}


def _get_schedule_configs() -> List[dict]:
    """Get all schedule triggers from config."""
    config = _load_triggers_config()
    schedules = []

    for trigger_id, trigger_config in config.items():
        if trigger_id.startswith("_"):
            continue
        if trigger_config.get("type") != "schedule":
            continue
        trigger_config["id"] = trigger_id
        schedules.append(trigger_config)

    return schedules


# =============================================================================
# Interval Parsing
# =============================================================================

def _parse_interval(interval: str) -> Optional[int]:
    """Parse interval string to seconds.

    Supported formats:
    - "30m" = 30 minutes = 1800 seconds
    - "1h" = 1 hour = 3600 seconds
    - "6h" = 6 hours = 21600 seconds
    - "1d" = 1 day = 86400 seconds
    - "weekly" = 7 days = 604800 seconds
    """
    if not interval:
        return None

    interval = interval.lower().strip()

    # Weekly special case
    if interval == "weekly":
        return 7 * 24 * 60 * 60

    # Parse number + unit
    match = re.match(r'^(\d+)\s*(m|min|h|hour|d|day)s?$', interval)
    if not match:
        system_log(f"[Scheduler] Invalid interval format: {interval}")
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit in ('m', 'min'):
        return value * 60
    elif unit in ('h', 'hour'):
        return value * 60 * 60
    elif unit in ('d', 'day'):
        return value * 24 * 60 * 60

    return None


def _parse_time(time_str: str) -> Optional[tuple]:
    """Parse time string to (hour, minute) tuple.

    Formats:
    - "08:00" = 8:00 AM
    - "14:30" = 2:30 PM
    - "Mon 09:00" = Monday 9:00 AM (returns (9, 0, 'Mon'))
    """
    if not time_str:
        return None

    time_str = time_str.strip()

    # Check for weekday prefix
    weekday = None
    weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    for wd in weekdays:
        if time_str.lower().startswith(wd):
            weekday = wd.capitalize()[:3]
            time_str = time_str[3:].strip()
            break

    # Parse HH:MM
    match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    if weekday:
        return (hour, minute, weekday)
    return (hour, minute)


def _calculate_next_run(interval_seconds: int, at_time: Optional[tuple], last_run: Optional[datetime]) -> datetime:
    """Calculate next run time based on interval and optional fixed time."""
    now = datetime.now()

    # If no fixed time, just add interval to last run (or now)
    if not at_time:
        if last_run:
            next_run = last_run + timedelta(seconds=interval_seconds)
            # If next run is in the past, calculate from now
            if next_run <= now:
                next_run = now + timedelta(seconds=interval_seconds)
        else:
            next_run = now + timedelta(seconds=interval_seconds)
        return next_run

    # Fixed time scheduling
    hour, minute = at_time[0], at_time[1]
    weekday = at_time[2] if len(at_time) > 2 else None

    # Create target time for today
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if weekday:
        # Weekly scheduling
        weekday_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
        target_weekday = weekday_map.get(weekday, 0)
        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and target <= now):
            days_ahead += 7
        target = target + timedelta(days=days_ahead)
    else:
        # Daily scheduling
        if target <= now:
            target = target + timedelta(days=1)

    return target


# =============================================================================
# State Management
# =============================================================================

@dataclass
class ScheduleState:
    """State for a scheduled task."""
    schedule_id: str
    last_run: Optional[str]
    next_run: Optional[str]
    run_count: int
    last_result: Optional[str]
    errors: List[dict]

    @classmethod
    def default(cls, schedule_id: str) -> "ScheduleState":
        return cls(
            schedule_id=schedule_id,
            last_run=None,
            next_run=None,
            run_count=0,
            last_result=None,
            errors=[]
        )

    def to_dict(self) -> dict:
        return {
            "schedule_id": self.schedule_id,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "last_result": self.last_result,
            "errors": self.errors
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleState":
        return cls(
            schedule_id=data.get("schedule_id", "unknown"),
            last_run=data.get("last_run"),
            next_run=data.get("next_run"),
            run_count=data.get("run_count", 0),
            last_result=data.get("last_result"),
            errors=data.get("errors", [])
        )


def _get_state_file(schedule_id: str) -> Path:
    """Get state file path for a schedule."""
    return get_data_dir() / f"schedule_{schedule_id}_state.json"


def _load_state(schedule_id: str) -> ScheduleState:
    """Load schedule state from file."""
    state_file = _get_state_file(schedule_id)
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return ScheduleState.from_dict(data)
        except (json.JSONDecodeError, IOError):
            pass
    return ScheduleState.default(schedule_id)


def _save_state(state: ScheduleState):
    """Save schedule state to file."""
    state_file = _get_state_file(state.schedule_id)
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except IOError as e:
        system_log(f"[Scheduler] Error saving state: {e}")


# =============================================================================
# Schedule Instance
# =============================================================================

class ScheduleInstance:
    """A single scheduled task instance."""

    def __init__(self, config: dict):
        self.config = config
        self.schedule_id = config.get("id", "unknown")
        self.agent = config.get("agent")
        self.inputs = config.get("inputs", {})
        self.state = _load_state(self.schedule_id)
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._lock = threading.Lock()

        # Parse interval
        self.interval_seconds = _parse_interval(config.get("interval", "1d"))
        self.at_time = _parse_time(config.get("at"))

        if not self.interval_seconds:
            system_log(f"[Scheduler] Invalid interval for {self.schedule_id}")

    def start(self) -> bool:
        """Start the scheduler thread."""
        if not self.interval_seconds:
            return False

        if self._thread and self._thread.is_alive():
            return False

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name=f"Scheduler-{self.schedule_id}"
        )
        self._thread.start()
        system_log(f"[Scheduler] Started: {self.schedule_id} (interval: {self.config.get('interval')})")
        return True

    def stop(self) -> bool:
        """Stop the scheduler thread."""
        if self._stop_event:
            self._stop_event.set()
            system_log(f"[Scheduler] Stop signal sent: {self.schedule_id}")
            return True
        return False

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._thread is not None and self._thread.is_alive()

    def run_now(self) -> dict:
        """Force immediate execution."""
        try:
            self._execute_agent()
            return {"status": "ok", "message": "Agent executed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_status(self) -> dict:
        """Get scheduler status."""
        # Calculate time until next run
        next_run_in = None
        if self.state.next_run:
            try:
                next_dt = datetime.fromisoformat(self.state.next_run)
                delta = (next_dt - datetime.now()).total_seconds()
                next_run_in = max(0, int(delta))
            except (ValueError, TypeError):
                pass

        return {
            "id": self.schedule_id,
            "name": self.config.get("name", self.schedule_id),
            "agent": self.agent,
            "enabled": self.config.get("enabled", False),
            "running": self.is_running(),
            "interval": self.config.get("interval"),
            "at": self.config.get("at"),
            "last_run": self.state.last_run,
            "next_run": self.state.next_run,
            "next_run_in": next_run_in,
            "run_count": self.state.run_count,
            "last_result": self.state.last_result,
            "errors": self.state.errors[:5]
        }

    def _scheduler_loop(self):
        """Main scheduler loop."""
        system_log(f"[Scheduler] Thread started: {self.schedule_id}")

        # Calculate initial next run
        last_run_dt = None
        if self.state.last_run:
            try:
                last_run_dt = datetime.fromisoformat(self.state.last_run)
            except (ValueError, TypeError):
                pass

        next_run = _calculate_next_run(self.interval_seconds, self.at_time, last_run_dt)

        with self._lock:
            self.state.next_run = next_run.isoformat()
            _save_state(self.state)

        system_log(f"[Scheduler] {self.schedule_id} next run: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        while not self._stop_event.is_set():
            now = datetime.now()

            # Check if it's time to run
            if now >= next_run:
                if self.config.get("enabled", False):
                    try:
                        self._execute_agent()
                    except Exception as e:
                        self._log_error(str(e))

                # Calculate next run
                with self._lock:
                    last_run_dt = datetime.fromisoformat(self.state.last_run) if self.state.last_run else now
                    next_run = _calculate_next_run(self.interval_seconds, self.at_time, last_run_dt)
                    self.state.next_run = next_run.isoformat()
                    _save_state(self.state)

                system_log(f"[Scheduler] {self.schedule_id} next run: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

            # Sleep for 1 minute (check frequently but not too often)
            self._stop_event.wait(timeout=60)

        system_log(f"[Scheduler] Thread stopped: {self.schedule_id}")

    def _execute_agent(self):
        """Execute the configured agent."""
        if not self.agent:
            system_log(f"[Scheduler] No agent configured for {self.schedule_id}")
            return

        system_log(f"[Scheduler] Executing agent: {self.agent}")

        try:
            # Import agent runner
            from .core.agent_task import run_agent_task

            # Prepare inputs as JSON string
            inputs_json = json.dumps(self.inputs) if self.inputs else ""

            # Run agent (async in background)
            def run_async():
                try:
                    result = run_agent_task(
                        agent_name=self.agent,
                        task=f"Scheduled run: {self.config.get('name', self.schedule_id)}",
                        inputs=inputs_json,
                        initial_prompt=f"Scheduled execution ({self.config.get('interval')})"
                    )

                    with self._lock:
                        self.state.last_result = "success" if result else "no_result"
                        self.state.run_count += 1
                        self.state.last_run = datetime.now().isoformat()
                        _save_state(self.state)

                    system_log(f"[Scheduler] Agent {self.agent} completed")

                except Exception as e:
                    self._log_error(f"Agent execution failed: {e}")

            threading.Thread(target=run_async, daemon=True).start()

            # Update last_run immediately (execution started)
            with self._lock:
                self.state.last_run = datetime.now().isoformat()
                _save_state(self.state)

        except ImportError as e:
            self._log_error(f"Import error: {e}")

    def _log_error(self, error: str):
        """Log an error."""
        with self._lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "error": error
            }
            self.state.errors.insert(0, entry)
            self.state.errors = self.state.errors[:20]
            self.state.last_result = f"error: {error[:50]}"
            _save_state(self.state)
        system_log(f"[Scheduler] Error: {error}")


# =============================================================================
# Global Scheduler Manager
# =============================================================================

_schedules: Dict[str, ScheduleInstance] = {}
_manager_lock = threading.Lock()


def start_all_schedules() -> int:
    """Start all enabled schedules. Returns count of started schedules."""
    global _schedules

    configs = _get_schedule_configs()
    started = 0

    with _manager_lock:
        for config in configs:
            schedule_id = config.get("id")
            if not schedule_id:
                continue

            if not config.get("enabled", False):
                continue

            # Create new instance if not exists
            if schedule_id not in _schedules:
                _schedules[schedule_id] = ScheduleInstance(config)

            # Start if not running
            if not _schedules[schedule_id].is_running():
                if _schedules[schedule_id].start():
                    started += 1

    return started


def stop_all_schedules() -> int:
    """Stop all running schedules. Returns count of stopped schedules."""
    stopped = 0

    with _manager_lock:
        for schedule in _schedules.values():
            if schedule.is_running():
                if schedule.stop():
                    stopped += 1

    return stopped


def reload_config():
    """Reload configuration and restart schedules."""
    stop_all_schedules()

    with _manager_lock:
        _schedules.clear()

    time.sleep(1)
    return start_all_schedules()


def get_schedule(schedule_id: str) -> Optional[ScheduleInstance]:
    """Get a specific schedule instance."""
    with _manager_lock:
        return _schedules.get(schedule_id)


def get_all_statuses() -> List[dict]:
    """Get status of all schedules."""
    configs = _get_schedule_configs()
    statuses = []

    with _manager_lock:
        for config in configs:
            schedule_id = config.get("id")
            if not schedule_id:
                continue

            if schedule_id in _schedules:
                statuses.append(_schedules[schedule_id].get_status())
            else:
                # Return config-only status for non-running schedules
                statuses.append({
                    "id": schedule_id,
                    "name": config.get("name", schedule_id),
                    "agent": config.get("agent"),
                    "enabled": config.get("enabled", False),
                    "running": False,
                    "interval": config.get("interval"),
                    "at": config.get("at"),
                    "last_run": None,
                    "next_run": None
                })

    return statuses


def is_any_enabled() -> bool:
    """Check if any schedule is enabled."""
    configs = _get_schedule_configs()
    return any(c.get("enabled", False) for c in configs)
