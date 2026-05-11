# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
License Manager for DeskAgent.

Handles license validation, session management, and heartbeat with the license API.
"""

import hashlib
import hmac
import json
import socket
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): print(msg)

def _get_config_dir() -> Path:
    """Get config directory - lazy to support --shared-dir reload."""
    try:
        import paths
        return paths.get_config_dir()
    except (ImportError, AttributeError):
        return Path(__file__).parent.parent.parent.parent.parent / "config"


class LicenseManager:
    """
    Singleton manager for license state and session lifecycle.

    Handles:
    - Hardware ID generation (Windows MachineGuid or fallback)
    - Session management (start, heartbeat, end)
    - Credential persistence to config/license.json
    - Auto-resume on startup
    - Grace period for offline operation (48h default, 8h warning)
    """

    _instance: Optional["LicenseManager"] = None
    _lock = threading.Lock()

    # Default license API base URL.
    # OSS / Community-Edition: empty string -> read exclusively from
    # system.json `app.license_api_url`. If that is also empty, the
    # NullLicenseProvider takes over (AGPL self-host mode).
    _DEFAULT_API_BASE = ""
    HEARTBEAT_INTERVAL = 300  # 5 minutes

    # Grace Period Configuration (in hours)
    # Allows offline operation when license server is unreachable
    GRACE_PERIOD_HOURS = 48  # Max offline time before blocking
    WARNING_HOURS = 8  # Show warning when this many hours remaining

    def __init__(self):
        self._session_lock = threading.Lock()
        self._session_id: Optional[str] = None
        self._auth_type: Optional[str] = None
        self._edition: Optional[str] = None
        self._product: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._email: Optional[str] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._hardware_id: str = self._generate_hardware_id()
        # Note: _license_file is now a property to support --shared-dir reload

        # Grace period state
        self._last_valid_check: Optional[datetime] = None
        self._grace_mode: bool = False
        self._connection_error: bool = False

    @property
    def API_BASE(self) -> str:
        """License API base URL - reads from app config, falls back to default.

        If both config and default are empty (AGPL/Community mode), returns ''.
        Callers should check whether the URL is non-empty before making
        network calls.
        """
        try:
            from config import load_config
            config = load_config()
            url = config.get("app", {}).get("license_api_url", "")
            if url:
                return url
        except Exception:
            pass
        return self._DEFAULT_API_BASE

    @property
    def _license_file(self) -> Path:
        """License file path - lazy to support --shared-dir reload."""
        return _get_config_dir() / "license.json"

    @classmethod
    def get_instance(cls) -> "LicenseManager":
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _generate_hardware_id(self) -> str:
        """
        Generate a stable hardware ID for session recovery.

        Priority:
        1. Windows: HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid
        2. Fallback: hostname + MAC address hash
        """
        if sys.platform == 'win32':
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                )
                machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                winreg.CloseKey(key)
                if machine_guid:
                    return machine_guid
            except Exception as e:
                system_log(f"[License] Could not read MachineGuid: {e}")

        # Fallback: hostname + MAC
        try:
            mac = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff)
                          for i in range(0, 8*6, 8)][::-1])
            return f"{socket.gethostname()}-{mac}"
        except Exception:
            return socket.gethostname()

    def _sign_timestamp(self, timestamp: str) -> str:
        """
        Generate HMAC signature for a timestamp to prevent manipulation.

        Uses hardware_id as secret key, ensuring the signature is device-bound.
        If someone copies license.json to another device, the signature won't verify.
        """
        secret = self._hardware_id.encode('utf-8')
        message = timestamp.encode('utf-8')
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def _verify_timestamp_signature(self, timestamp: str, signature: str) -> bool:
        """
        Verify HMAC signature of a timestamp.

        Returns True if signature is valid for this device.
        """
        expected = self._sign_timestamp(timestamp)
        return hmac.compare_digest(expected, signature)

    def _get_version(self) -> str:
        """Get DeskAgent version."""
        try:
            from paths import DESKAGENT_DIR
            version_file = DESKAGENT_DIR / "version.json"
            if version_file.exists():
                data = json.loads(version_file.read_text())
                return data.get("version", "1.0.0")
        except Exception:
            pass
        return "1.0.0"

    def start_session(
        self,
        code: str = None,
        invoice_number: str = None,
        zip_code: str = None,
        email: str = None
    ) -> dict:
        """
        Start a license session with Code OR Invoice+ZIP.

        Args:
            code: Activation code (SUB-XXXX-...)
            invoice_number: Invoice number (e.g., RE-2025-0123)
            zip_code: ZIP code or email for invoice auth
            email: User email (optional for code auth)

        Returns:
            dict with success/error and session info
        """
        # Build request payload
        # Email is required by server - use provided email or zip_code as fallback
        effective_email = email or zip_code
        if not effective_email or '@' not in effective_email:
            return {"success": False, "error": "Email address is required"}

        payload = {
            "hostname": socket.gethostname(),
            "hardware_id": self._hardware_id,
            "client_version": self._get_version(),
            "email": effective_email
        }

        if code:
            payload["code"] = code
        elif invoice_number and zip_code:
            payload["invoice_number"] = invoice_number
            payload["zip_code"] = zip_code
        else:
            return {"success": False, "error": "Invalid credentials - provide code or invoice+zip"}

        try:
            system_log(f"[License] Starting session with payload: {payload}")
            response = requests.post(
                f"{self.API_BASE}/session/start",
                json=payload,
                timeout=30
            )

            # Check response status and content
            system_log(f"[License] Response status: {response.status_code}")
            if response.status_code != 200:
                error_text = response.text[:200] if response.text else "Empty response"
                system_log(f"[License] API error: {error_text}")

                # Try to extract detailed error message from JSON response
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message") or error_data.get("error") or f"Server error ({response.status_code})"
                except Exception:
                    error_msg = f"Server error ({response.status_code})"

                return {"success": False, "error": error_msg}

            # Try to parse JSON
            try:
                data = response.json()
            except Exception as e:
                system_log(f"[License] JSON parse error: {e}, response: {response.text[:200]}")
                return {"success": False, "error": "Invalid response from license server"}

            if data.get("success"):
                with self._session_lock:
                    self._session_id = data.get("session_id")
                    self._auth_type = data.get("auth_type")
                    self._edition = data.get("edition")
                    self._product = data.get("product")
                    self._email = email or zip_code  # zip_code is often email for invoice auth
                    # Update grace period state - successful connection
                    self._last_valid_check = datetime.now()
                    self._grace_mode = False
                    self._connection_error = False

                    expires_str = data.get("expires_at")
                    if expires_str:
                        try:
                            self._expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                        except Exception:
                            self._expires_at = None

                # Save credentials for auto-resume (includes last_valid_check)
                self._save_credentials(code, invoice_number, zip_code, email)
                self._save_last_valid_check()

                # Start heartbeat thread
                self._start_heartbeat()

                resumed = data.get("resumed", False)
                system_log(f"[License] Session started (edition={self._edition}, resumed={resumed})")

                return {
                    "success": True,
                    "session_id": self._session_id,
                    "edition": self._edition,
                    "product": self._product,
                    "auth_type": self._auth_type,
                    "expires_at": data.get("expires_at"),
                    "resumed": resumed
                }
            else:
                error = data.get("error", "Unknown error")
                system_log(f"[License] Session start failed: {error}")
                return {"success": False, "error": error}

        except requests.exceptions.Timeout:
            system_log("[License] Session start timeout")
            return {"success": False, "error": "Connection timeout"}
        except requests.exceptions.ConnectionError:
            system_log("[License] Session start connection error")
            return {"success": False, "error": "Could not connect to license server"}
        except Exception as e:
            system_log(f"[License] Session start error: {e}")
            return {"success": False, "error": str(e)}

    def _start_heartbeat(self):
        """Start the background heartbeat thread."""
        self._heartbeat_stop.clear()

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return  # Already running

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="LicenseHeartbeat"
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        """Send heartbeat every 5 minutes."""
        while not self._heartbeat_stop.wait(self.HEARTBEAT_INTERVAL):
            if not self._session_id:
                break
            self._send_heartbeat()

    def _send_heartbeat(self):
        """Send a single heartbeat and track connection status for grace period."""
        if not self._session_id:
            return

        try:
            response = requests.post(
                f"{self.API_BASE}/session/heartbeat",
                json={"session_id": self._session_id},
                timeout=10
            )
            if response.status_code == 200:
                # Success - update last valid check and exit grace mode
                with self._session_lock:
                    self._last_valid_check = datetime.now()
                    self._grace_mode = False
                    self._connection_error = False
                self._save_last_valid_check()
                system_log("[License] Heartbeat OK")
            else:
                system_log(f"[License] Heartbeat failed: {response.status_code}")
                self._enter_grace_mode("Server returned error")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            system_log(f"[License] Heartbeat connection error: {e}")
            self._enter_grace_mode(str(e))
        except Exception as e:
            system_log(f"[License] Heartbeat error: {e}")
            self._enter_grace_mode(str(e))

    def end_session(self):
        """End the current license session."""
        self._heartbeat_stop.set()

        session_id = self._session_id
        if not session_id:
            return

        try:
            system_log("[License] Ending session...")
            requests.post(
                f"{self.API_BASE}/session/end",
                json={"session_id": session_id},
                timeout=10
            )
        except Exception as e:
            system_log(f"[License] End session error: {e}")
        finally:
            with self._session_lock:
                self._session_id = None

    def _enter_grace_mode(self, reason: str):
        """Enter grace mode when server is unreachable."""
        with self._session_lock:
            if not self._grace_mode:
                system_log(f"[License] Entering grace mode: {reason}")
            self._grace_mode = True
            self._connection_error = True

    def _save_last_valid_check(self):
        """Save last_valid_check timestamp with HMAC signature to license.json."""
        try:
            creds = self._load_credentials() or {}
            if self._last_valid_check:
                timestamp = self._last_valid_check.isoformat()
                creds["last_valid_check"] = timestamp
                creds["last_valid_check_sig"] = self._sign_timestamp(timestamp)
            else:
                creds["last_valid_check"] = None
                creds["last_valid_check_sig"] = None
            self._license_file.parent.mkdir(parents=True, exist_ok=True)
            self._license_file.write_text(json.dumps(creds, indent=2))
        except Exception as e:
            system_log(f"[License] Failed to save last_valid_check: {e}")

    def _load_last_valid_check(self) -> Optional[datetime]:
        """
        Load last_valid_check from license.json with signature verification.

        Returns None if:
        - No timestamp stored
        - Signature is missing or invalid (manipulation detected)
        - Timestamp is in the future (clock manipulation)
        """
        try:
            creds = self._load_credentials()
            if not creds or not creds.get("last_valid_check"):
                return None

            timestamp = creds.get("last_valid_check")
            signature = creds.get("last_valid_check_sig")

            # Verify signature to prevent manipulation
            if not signature or not self._verify_timestamp_signature(timestamp, signature):
                system_log("[License] WARNING: Invalid timestamp signature - possible manipulation!")
                return None

            # Parse and validate timestamp
            dt = datetime.fromisoformat(timestamp)

            # Reject future timestamps (clock manipulation)
            if dt > datetime.now():
                system_log("[License] WARNING: Future timestamp detected - possible manipulation!")
                return None

            return dt

        except Exception as e:
            system_log(f"[License] Failed to load last_valid_check: {e}")
        return None

    def _check_grace_period(self) -> dict:
        """
        Check if within grace period when server is unreachable.

        Returns:
            {
                "valid": bool,  # True if still allowed to operate
                "grace_mode": bool,
                "grace_remaining_hours": float | None,
                "show_warning": bool,  # True if < WARNING_HOURS remaining
                "message": str
            }
        """
        last_check = self._last_valid_check or self._load_last_valid_check()

        if not last_check:
            # Never successfully validated - require connection
            return {
                "valid": False,
                "grace_mode": False,
                "grace_remaining_hours": None,
                "show_warning": False,
                "message": "Initial connection to license server required"
            }

        elapsed = datetime.now() - last_check
        elapsed_hours = elapsed.total_seconds() / 3600
        remaining_hours = self.GRACE_PERIOD_HOURS - elapsed_hours

        if remaining_hours > 0:
            # Still within grace period
            show_warning = remaining_hours <= self.WARNING_HOURS
            message = f"Offline mode active ({remaining_hours:.1f}h remaining)"
            if show_warning:
                message = f"Warning: Only {remaining_hours:.1f}h offline time remaining"

            return {
                "valid": True,
                "grace_mode": True,
                "grace_remaining_hours": remaining_hours,
                "show_warning": show_warning,
                "message": message
            }
        else:
            # Grace period expired
            return {
                "valid": False,
                "grace_mode": True,
                "grace_remaining_hours": 0,
                "show_warning": True,
                "message": "Offline time expired. Please check your internet connection."
            }

    def is_licensed(self) -> bool:
        """
        Check if there's an active license session.

        Considers grace period: If server is unreachable but we're within
        the grace period, still returns True.
        """
        if self._session_id is not None:
            if not self._grace_mode:
                return True
            # In grace mode - check if still within grace period
            grace_status = self._check_grace_period()
            return grace_status.get("valid", False)
        return False

    def get_license_status(self) -> dict:
        """Get current license status for API response, including grace period info."""
        with self._session_lock:
            status = {
                "licensed": self.is_licensed(),
                "edition": self._edition,
                "product": self._product,
                "auth_type": self._auth_type,
                "email": self._email,
                "expires_at": self._expires_at.isoformat() if self._expires_at else None,
                "device_id": self._hardware_id[:12] + "..." if len(self._hardware_id) > 12 else self._hardware_id,
                # Truncate hardware_id on the wire to prevent leaking the full
                # MachineGuid through /license/status (privacy hardening).
                "hardware_id": self._hardware_id[:12] + "..." if len(self._hardware_id) > 12 else self._hardware_id,
                "hostname": socket.gethostname(),
                # Grace period fields
                "grace_mode": self._grace_mode,
                "connection_error": self._connection_error,
            }

            # Add grace period details if in grace mode
            if self._grace_mode:
                grace_status = self._check_grace_period()
                status["grace_remaining_hours"] = grace_status.get("grace_remaining_hours")
                status["grace_show_warning"] = grace_status.get("show_warning", False)
                status["grace_message"] = grace_status.get("message")
            else:
                status["grace_remaining_hours"] = None
                status["grace_show_warning"] = False
                status["grace_message"] = None

            return status

    def _save_credentials(self, code: str, invoice: str, zip_code: str, email: str):
        """Save credentials to config/license.json for auto-resume."""
        try:
            data = {
                "auth_method": "code" if code else "invoice",
                "code": code,
                "invoice_number": invoice,
                "zip_code": zip_code,
                "email": email,
                "hardware_id": self._hardware_id
            }
            # Remove None values
            data = {k: v for k, v in data.items() if v is not None}

            self._license_file.parent.mkdir(parents=True, exist_ok=True)
            self._license_file.write_text(json.dumps(data, indent=2))
            system_log(f"[License] Credentials saved to {self._license_file}")
        except Exception as e:
            system_log(f"[License] Failed to save credentials: {e}")

    def _load_credentials(self) -> Optional[dict]:
        """Load saved credentials from config/license.json."""
        try:
            if not self._license_file.exists():
                return None
            data = json.loads(self._license_file.read_text())
            return data
        except Exception as e:
            system_log(f"[License] Failed to load credentials: {e}")
            return None

    def clear_credentials(self):
        """Clear saved credentials."""
        try:
            if self._license_file.exists():
                self._license_file.unlink()
                system_log("[License] Credentials cleared")
        except Exception as e:
            system_log(f"[License] Failed to clear credentials: {e}")

    def auto_resume(self) -> bool:
        """
        Try to resume session with saved credentials.
        Called at startup.

        If server is unreachable but we have valid credentials and are within
        the grace period, enters grace mode and allows operation.

        Returns:
            True if session was resumed successfully (or grace mode active)
        """
        creds = self._load_credentials()
        if not creds:
            system_log("[License] No saved credentials found")
            return False

        # Load last valid check for grace period
        self._last_valid_check = self._load_last_valid_check()

        system_log("[License] Attempting auto-resume...")

        result = self.start_session(
            code=creds.get("code"),
            invoice_number=creds.get("invoice_number"),
            zip_code=creds.get("zip_code"),
            email=creds.get("email")
        )

        if result.get("success"):
            return True

        # Connection failed - check if we can use grace period
        error = result.get("error", "")
        if "connect" in error.lower() or "timeout" in error.lower():
            grace_status = self._check_grace_period()
            if grace_status.get("valid"):
                # Enter grace mode - restore session state from saved credentials
                with self._session_lock:
                    self._grace_mode = True
                    self._connection_error = True
                    self._session_id = "grace-mode-session"  # Placeholder to indicate active state
                    self._edition = creds.get("edition", "DESKAGENT")
                    self._product = creds.get("product", "DeskAgent")
                    self._email = creds.get("email")
                system_log(f"[License] Grace mode active: {grace_status.get('message')}")
                # Start heartbeat to retry connection
                self._start_heartbeat()
                return True
            else:
                system_log(f"[License] Grace period expired: {grace_status.get('message')}")

        return False

    def get_saved_credentials(self) -> dict:
        """
        Get saved credentials for UI display.
        Returns full code for re-activation.
        """
        creds = self._load_credentials()
        if not creds:
            return {}

        result = {
            "auth_method": creds.get("auth_method"),
            "invoice_number": creds.get("invoice_number"),
            "zip_code": creds.get("zip_code"),
            "email": creds.get("email"),
            "code": creds.get("code")  # Full code for form pre-fill
        }

        # Remove None values
        return {k: v for k, v in result.items() if v is not None}


# =============================================================================
# NullLicenseProvider (AGPL / Community Edition)
# =============================================================================
#
# When DeskAgent runs in AGPL self-host mode (no `config/license.json` AND
# no `app.license_api_url` configured in `system.json`), the
# NullLicenseProvider is used instead of the network-based LicenseManager.
#
# The provider is fully offline:
# - is_licensed() always returns True
# - check_agent() always returns {allowed: True}
# - activate/deactivate are no-ops
#
# This makes DeskAgent runnable without any contact to a license server,
# which is the default for community / pip-installed builds.
# =============================================================================

def _has_license_file() -> bool:
    """Check whether a config/license.json exists on disk."""
    try:
        return (_get_config_dir() / "license.json").exists()
    except Exception:
        return False


def _get_configured_license_api_url() -> str:
    """Read app.license_api_url from system.json, return '' if missing."""
    try:
        from config import load_config
        config = load_config()
        return (config.get("app", {}) or {}).get("license_api_url", "") or ""
    except Exception:
        return ""


def is_agpl_mode() -> bool:
    """Return True if DeskAgent is running in AGPL / Community mode.

    Conditions for AGPL mode (any of):
    - No `config/license.json` AND no `app.license_api_url` configured
    - `app.license_api_url` is explicitly empty string

    Rationale: Empty license_api_url means the operator did not configure
    a license server, which is the OSS/Community default. We then fall back
    to the NullLicenseProvider so the app starts cleanly without network.
    """
    if not _get_configured_license_api_url():
        return True
    if not _has_license_file():
        # No license file *and* an API URL is configured -> still AGPL
        # mode until the user activates a license. This keeps the app
        # usable on first launch.
        return True
    return False


class NullLicenseProvider:
    """No-op license provider for AGPL / Community Edition.

    Provides the same surface as LicenseManager for the routes layer,
    but never contacts any server and never blocks any agent.
    """

    PRODUCT_NAME = "DeskAgent Community"
    EDITION = "agpl"

    def __init__(self):
        self._hardware_id = "community"

    @staticmethod
    def get_license_status() -> dict:
        """Return the full 14-field license status schema in AGPL mode."""
        return {
            "licensed": True,
            "edition": NullLicenseProvider.EDITION,
            "product": NullLicenseProvider.PRODUCT_NAME,
            "auth_type": None,
            "email": None,
            "expires_at": None,
            "device_id": "community",
            "hardware_id": "community",
            "hostname": socket.gethostname(),
            "grace_mode": False,
            "grace_remaining_hours": None,
            "grace_show_warning": False,
            "grace_message": None,
            "connection_error": False,
        }

    @staticmethod
    def is_licensed() -> bool:
        return True

    @staticmethod
    def check_agent(agent_name: Optional[str] = None) -> dict:
        """All agents are allowed in AGPL mode."""
        return {"allowed": True}

    @staticmethod
    def get_saved_credentials() -> dict:
        return {}

    @staticmethod
    def activate(*_args, **_kwargs) -> dict:
        return {"success": False, "reason": "agpl_mode"}

    @staticmethod
    def deactivate() -> dict:
        return {"success": True}
