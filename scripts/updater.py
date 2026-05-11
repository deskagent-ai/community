# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
DeskAgent Updater
Handles version checking and updates including new dependencies.
"""

import json
import os
import sys
import subprocess
import hashlib
import shutil
import urllib.request
import urllib.error
import time
from pathlib import Path
from typing import Optional, Callable

# Import system_log for debugging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# === Cache to avoid spamming logs with repeated failures ===
_failure_cache = {
    "firebase_failed": False,
    "firebase_fail_time": 0,
    "git_available": None,
    "ssl_error_logged": False,
}
_CACHE_TTL = 300  # 5 minutes before retrying


def get_file_hash(filepath: Path) -> str:
    """Calculate MD5 hash of a file."""
    if not filepath.exists():
        return ""
    return hashlib.md5(filepath.read_bytes()).hexdigest()


def run_command(cmd: list, cwd: str = None, capture: bool = False, silent: bool = False) -> tuple[int, str]:
    """Run a command and return exit code and output.

    Args:
        cmd: Command and arguments
        cwd: Working directory
        capture: Whether to return stdout
        silent: If True, don't log failures (for expected failures like missing git)
    """
    try:
        # Always capture output for logging
        kwargs = {"cwd": cwd, "capture_output": True, "text": True, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(cmd, **kwargs)

        # Log errors if any (unless silent mode)
        if result.returncode != 0 and not silent:
            cmd_str = " ".join(cmd)
            system_log(f"[Update] Command failed: {cmd_str}")
            if result.stderr:
                system_log(f"[Update] STDERR: {result.stderr.strip()}")
            if result.stdout:
                system_log(f"[Update] STDOUT: {result.stdout.strip()}")

        return result.returncode, result.stdout if capture else ""
    except Exception as e:
        # Only log once per error type to avoid spam
        error_key = f"cmd_error_{cmd[0] if cmd else 'unknown'}"
        if not _failure_cache.get(error_key) and not silent:
            system_log(f"[Update] Command exception ({cmd[0] if cmd else 'unknown'}): {e}")
            _failure_cache[error_key] = True
        return 1, str(e)


def get_paths() -> dict:
    """Get all relevant paths."""
    # Use DESKAGENT_DIR from paths module - works correctly in both dev and compiled mode
    try:
        from paths import DESKAGENT_DIR
        deskagent_dir = DESKAGENT_DIR
    except ImportError:
        # Fallback for edge cases
        deskagent_dir = Path(__file__).parent.parent

    script_dir = deskagent_dir / "scripts"
    install_dir = deskagent_dir.parent      # Install root
    repo_dir = install_dir / ".repo"

    return {
        "script_dir": script_dir,
        "deskagent_dir": deskagent_dir,
        "install_dir": install_dir,
        "repo_dir": repo_dir,
        "version_file": deskagent_dir / "version.json",
        "requirements_file": deskagent_dir / "requirements.txt",
        "is_customer_install": repo_dir.exists(),
    }


def find_git() -> Optional[str]:
    """Find git executable (embedded or system). Cached to avoid repeated lookups."""
    global _failure_cache

    # Return cached result if available
    if _failure_cache["git_available"] is not None:
        return _failure_cache["git_available"] if _failure_cache["git_available"] else None

    paths = get_paths()
    embedded_git = paths["install_dir"] / "git" / "cmd" / "git.exe"
    if embedded_git.exists():
        _failure_cache["git_available"] = str(embedded_git)
        return str(embedded_git)

    # Check for system git silently (don't log failures)
    try:
        cmd = ["where", "git"] if sys.platform == "win32" else ["which", "git"]
        kwargs = {"capture_output": True, "text": True, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(cmd, **kwargs)
        if result.returncode == 0:
            _failure_cache["git_available"] = "git"
            return "git"
    except Exception:
        pass

    # Git not found - cache the failure
    _failure_cache["git_available"] = False
    return None


def find_python() -> str:
    """Find python executable (embedded or system)."""
    paths = get_paths()
    embedded_python = paths["install_dir"] / "python" / "python.exe"
    return str(embedded_python) if embedded_python.exists() else sys.executable


# === Firebase Release Metadata ===
#
# AGPL/Community-Edition note:
#   The release-feed URL and GitHub repo are read exclusively from
#   `system.json` (`app.releases_url` and `app.github_repo`). If both
#   are empty, the updater silently skips the version check
#   (`get_firebase_releases()` returns None) - no network call, no
#   crash. Operators who want auto-update should populate these in
#   their `system.json`.

_DEFAULT_RELEASES_URL = ""
_DEFAULT_GITHUB_REPO = ""


def _get_app_config() -> dict:
    """Load app config section from system.json."""
    try:
        from config import load_config
        config = load_config()
        return config.get("app", {})
    except Exception:
        return {}


def _get_releases_url() -> str:
    """Get releases URL from config or default (may be '' for OSS builds)."""
    return _get_app_config().get("releases_url", _DEFAULT_RELEASES_URL) or _DEFAULT_RELEASES_URL


def _get_github_repo() -> str:
    """Get GitHub repo from config or default (may be '' for OSS builds)."""
    return _get_app_config().get("github_repo", _DEFAULT_GITHUB_REPO) or _DEFAULT_GITHUB_REPO


def get_firebase_releases() -> Optional[dict]:
    """
    Fetch release metadata from Firebase.

    Returns:
        Dict with 'latest', 'base_url', and 'versions' list, or None if failed
        or if no `app.releases_url` is configured (OSS / Community Edition).
    """
    global _failure_cache

    releases_url = _get_releases_url()
    if not releases_url:
        # AGPL/Community: no release feed configured -> skip update check
        # silently, log once for diagnostics.
        if not _failure_cache["firebase_failed"]:
            system_log("[Update] No app.releases_url configured - skipping update check")
        _failure_cache["firebase_failed"] = True
        _failure_cache["firebase_fail_time"] = time.time()
        return None

    # Check if we recently failed (avoid log spam)
    if _failure_cache["firebase_failed"]:
        if time.time() - _failure_cache["firebase_fail_time"] < _CACHE_TTL:
            return None  # Still in cooldown, skip silently
        # Reset cache after TTL
        _failure_cache["firebase_failed"] = False

    try:
        req = urllib.request.Request(
            releases_url,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"}
        )

        # Try with SSL verification first
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except urllib.error.URLError as ssl_err:
            if "CERTIFICATE_VERIFY_FAILED" in str(ssl_err):
                # SSL error - try without verification (safe for read-only update check)
                if not _failure_cache["ssl_error_logged"]:
                    system_log("[Update] SSL certificate error - trying without verification")
                    _failure_cache["ssl_error_logged"] = True

                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                    return json.loads(response.read().decode("utf-8-sig"))
            raise

    except Exception as e:
        # Only log once per cooldown period
        if not _failure_cache["firebase_failed"]:
            system_log(f"[Update] Firebase unavailable: {e}")
        _failure_cache["firebase_failed"] = True
        _failure_cache["firebase_fail_time"] = time.time()
        return None


def get_firebase_versions(limit: int = 10) -> list:
    """
    Get available versions from Firebase releases.json.

    Args:
        limit: Maximum number of versions to return

    Returns:
        List of version dicts with version, date, notes, windows, macos URLs
    """
    releases = get_firebase_releases()
    if not releases:
        return []

    versions = releases.get("versions", [])[:limit]
    # base_url comes from the releases.json itself; if missing, use empty
    # string so the caller can decide how to handle it. (We previously
    # hardcoded files.realvirtual.io here, which is firma-specific.)
    base_url = releases.get("base_url", "")

    # Enrich with full URLs
    for v in versions:
        if v.get("windows"):
            v["windows_url"] = f"{base_url}/{v['windows']}"
        if v.get("macos"):
            v["macos_url"] = f"{base_url}/{v['macos']}"
        if v.get("windows_archive"):
            v["windows_archive_url"] = f"{base_url}/{v['windows_archive']}"
        if v.get("macos_archive"):
            v["macos_archive_url"] = f"{base_url}/{v['macos_archive']}"

    return versions


def get_firebase_release_notes(version: str = None) -> dict:
    """
    Get release notes from Firebase.

    Args:
        version: Version string or None for latest

    Returns:
        Dict with version info and notes
    """
    releases = get_firebase_releases()
    if not releases:
        return {"error": "Could not fetch releases"}

    versions = releases.get("versions", [])
    if not versions:
        return {"error": "No versions found"}

    # Find specific version or get latest
    if version:
        for v in versions:
            if v.get("version") == version:
                return {
                    "version": v.get("version"),
                    "date": v.get("date"),
                    "notes": v.get("notes", ""),
                    "windows": v.get("windows"),
                    "macos": v.get("macos"),
                }
        return {"error": f"Version {version} not found"}
    else:
        # Return latest
        latest = versions[0] if versions else None
        if latest:
            return {
                "version": latest.get("version"),
                "date": latest.get("date"),
                "notes": latest.get("notes", ""),
                "windows": latest.get("windows"),
                "macos": latest.get("macos"),
            }
        return {"error": "No versions found"}


# === Version Checking ===

def get_local_version() -> dict:
    """Get local version info from version.json, including commit message from git tag."""
    paths = get_paths()
    result = {"version": "unknown", "build": 0}

    if paths["version_file"].exists():
        try:
            result = json.loads(paths["version_file"].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Try to get commit message for current version tag
    try:
        version = result.get("version", "unknown")
        if version != "unknown":
            git_exe = find_git()
            if git_exe:
                tag = f"v{version}"
                # For dev environment, use aiassistant root; for customer, use .repo
                if paths.get("is_customer_install"):
                    repo_dir = str(paths["repo_dir"])
                else:
                    # Dev environment: try aiassistant root first
                    repo_dir = str(paths["root"])

                # Get commit message for tag
                code, msg = run_command(
                    [git_exe, "log", "-1", "--format=%s", tag],
                    cwd=repo_dir,
                    capture=True
                )
                if code == 0 and msg:
                    result["commit_message"] = msg.strip()
    except Exception:
        pass  # Silently fail - commit message is optional

    return result


def get_remote_version(branch: str = "main") -> Optional[dict]:
    """
    Get latest version from git tags (works with private repos).

    Args:
        branch: Branch to check (main or staging) - currently unused, kept for API compatibility

    Returns:
        Version dict or None if failed
    """
    # First try git tags (works with private repos if credentials are cached)
    versions = get_available_versions(limit=1)
    if versions:
        latest = versions[0]
        return {
            "version": latest["version"],
            "build": 0,  # Build number not available from tags
            "_branch": branch,
            "_source": "git_tags"
        }

    # Fallback: try raw GitHub URL (public repos or with token)
    github_repo = _get_github_repo()
    url = f"https://raw.githubusercontent.com/{github_repo}/{branch}/deskagent/version.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            data["_branch"] = branch
            data["_source"] = "github_raw"
            return data
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare version strings.

    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
    """
    def parse(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    p1, p2 = parse(v1), parse(v2)
    if p1 < p2:
        return -1
    elif p1 > p2:
        return 1
    return 0


def get_release_notes(version: str = None) -> dict:
    """
    Fetch release notes.

    Primary source: Firebase releases.json
    Fallback: GitHub Releases API

    Args:
        version: Version string (e.g. "0.5.8") or None for latest

    Returns:
        Dict with release info: version, date, notes, windows_url, macos_url
    """
    # Try Firebase first
    firebase_notes = get_firebase_release_notes(version)
    if firebase_notes and "error" not in firebase_notes:
        releases = get_firebase_releases()
        base_url = releases.get("base_url", "") if releases else ""
        return {
            "version": firebase_notes.get("version"),
            "tag": f"v{firebase_notes.get('version', '')}",
            "name": f"v{firebase_notes.get('version', '')}",
            "body": firebase_notes.get("notes", ""),
            "published_at": firebase_notes.get("date", ""),
            "windows_url": f"{base_url}/{firebase_notes['windows']}" if firebase_notes.get("windows") else None,
            "macos_url": f"{base_url}/{firebase_notes['macos']}" if firebase_notes.get("macos") else None,
            "source": "firebase",
        }

    # Fallback to GitHub API
    system_log("[Update] Firebase release notes unavailable, falling back to GitHub API")
    try:
        # Fetch releases from GitHub API
        github_repo = _get_github_repo()
        api_url = f"https://api.github.com/repos/{github_repo}/releases"
        req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github.v3+json"})

        with urllib.request.urlopen(req, timeout=10) as response:
            releases = json.loads(response.read().decode("utf-8"))

            if not releases:
                return {"error": "No releases found"}

            # Find specific version or get latest
            target_release = None
            if version:
                tag = f"v{version}" if not version.startswith("v") else version
                for r in releases:
                    if r.get("tag_name") == tag:
                        target_release = r
                        break
            else:
                # Get latest (first non-prerelease, or first overall)
                for r in releases:
                    if not r.get("prerelease"):
                        target_release = r
                        break
                if not target_release and releases:
                    target_release = releases[0]

            if not target_release:
                return {"error": f"Release {version} not found"}

            return {
                "version": target_release.get("tag_name", "").lstrip("v"),
                "tag": target_release.get("tag_name"),
                "name": target_release.get("name", ""),
                "body": target_release.get("body", ""),
                "published_at": target_release.get("published_at", ""),
                "url": target_release.get("html_url", ""),
                "author": target_release.get("author", {}).get("login", ""),
                "source": "github",
            }
    except Exception as e:
        return {"error": str(e)}


def get_available_versions(limit: int = 10, include_messages: bool = True) -> list:
    """
    Get list of available versions from Firebase releases.json.

    Args:
        limit: Maximum number of versions to return
        include_messages: Whether to include release notes (unused, kept for API compatibility)

    Returns:
        List of version dicts sorted by version (newest first), or empty list if unavailable
    """
    firebase_versions = get_firebase_versions(limit)
    if not firebase_versions:
        # Firebase unavailable - return empty list (no git fallback for customers)
        return []

    # Transform to expected format
    versions = []
    for v in firebase_versions:
        versions.append({
            "version": v.get("version", ""),
            "tag": f"v{v.get('version', '')}",
            "date": v.get("date", ""),
            "message": v.get("notes", "").split("\n")[0] if v.get("notes") else "",  # First line as summary
            "notes": v.get("notes", ""),
            "windows_url": v.get("windows_url"),
            "macos_url": v.get("macos_url"),
            "windows_archive_url": v.get("windows_archive_url"),  # For versioned downloads/downgrades
            "macos_archive_url": v.get("macos_archive_url"),
            "source": "firebase",
        })

    if versions and not _failure_cache.get("versions_logged"):
        system_log(f"[Update] Got {len(versions)} versions from Firebase")
        _failure_cache["versions_logged"] = True

    return versions




def install_version(version: str, progress_callback: Callable[[int, int, str], None] = None) -> dict:
    """
    Install a specific version (downgrade or upgrade) from remote repository.

    Args:
        version: Version string (e.g. "0.5.1") or tag (e.g. "v0.5.1")
        progress_callback: Optional function(step, total, message)

    Returns:
        Dict with success status and details
    """
    system_log(f"[Update] Starting install_version: {version}")

    def report(step, total, msg):
        if progress_callback:
            progress_callback(step, total, msg)
        # Use system_log for background logging
        system_log(f"[Update] [{step}/{total}] {msg}")

    paths = get_paths()
    git_exe = find_git()
    python_exe = find_python()

    system_log(f"[Update] Git: {git_exe}, Python: {python_exe}")
    system_log(f"[Update] Is customer install: {paths['is_customer_install']}")

    if not git_exe:
        system_log("[Update] ERROR: Git not found")
        return {"success": False, "error": "Git not found"}

    # Ensure tag format
    tag = version if version.startswith("v") else f"v{version}"
    github_repo = _get_github_repo()
    remote_url = f"https://github.com/{github_repo}.git"

    requirements_file = paths["requirements_file"]
    old_hash = get_file_hash(requirements_file)

    if paths["is_customer_install"]:
        # Customer installation - update from remote deskagent repo
        total = 4
        repo_dir = str(paths["repo_dir"])

        report(1, total, f"Fetching {tag} from github.com/{github_repo}...")
        fetch_code, fetch_output = run_command([git_exe, "fetch", "origin", "--tags"], cwd=repo_dir, capture=True)
        if fetch_code != 0:
            system_log(f"[Update] WARNING: Fetch may have failed (code {fetch_code})")

        # Log available tags for debugging
        _, tags_output = run_command([git_exe, "tag", "-l"], cwd=repo_dir, capture=True)
        if tags_output:
            available_tags = [t for t in tags_output.strip().split("\n") if t.startswith("v")]
            system_log(f"[Update] Available tags in repo: {', '.join(available_tags[-10:])}")  # Last 10

        report(2, total, f"Switching to version {tag}...")
        code, output = run_command([git_exe, "checkout", tag], cwd=repo_dir, capture=True)
        if code != 0:
            # Try to get more context about why checkout failed
            system_log(f"[Update] ERROR: Checkout {tag} failed (code {code})")
            if output:
                system_log(f"[Update] Checkout output: {output.strip()}")

            # Check if tag exists locally
            tag_check_code, _ = run_command([git_exe, "rev-parse", tag], cwd=repo_dir, capture=True)
            if tag_check_code != 0:
                system_log(f"[Update] Tag {tag} does not exist in local repo (even after fetch)")
            else:
                system_log(f"[Update] Tag {tag} exists but checkout still failed")

            return {"success": False, "error": f"Version {tag} not found on remote"}

        report(3, total, "Copying files to installation folder...")
        src = paths["repo_dir"] / "deskagent"
        if src.exists():
            try:
                if paths["deskagent_dir"].exists():
                    # Check if deskagent.pid exists - indicates app might be running
                    try:
                        from assistant.state import get_pid_file
                        pid_file = get_pid_file()
                    except ImportError:
                        pid_file = paths["deskagent_dir"] / "deskagent.pid"
                    if pid_file.exists():
                        system_log("[Update] WARNING: deskagent.pid exists - application may be running!")
                        system_log("[Update] Files may be locked, update might fail or be incomplete")

                    # Try to remove old directory (some files may be locked)
                    removed_count = 0
                    failed_count = 0
                    for item in paths["deskagent_dir"].rglob("*"):
                        if item.is_file():
                            try:
                                item.unlink()
                                removed_count += 1
                            except PermissionError:
                                failed_count += 1

                    if failed_count > 0:
                        system_log(f"[Update] WARNING: Could not remove {failed_count} files (likely locked)")
                        system_log(f"[Update] Successfully removed {removed_count} files")

                    # Remove empty directories
                    shutil.rmtree(paths["deskagent_dir"], ignore_errors=True)

                shutil.copytree(src, paths["deskagent_dir"])
                system_log(f"[Update] Files copied from {src} to {paths['deskagent_dir']}")
            except Exception as e:
                system_log(f"[Update] ERROR copying files: {e}")
                return {"success": False, "error": f"Failed to copy files: {e}"}

        report(4, total, "Checking for new dependencies...")
        new_hash = get_file_hash(requirements_file)
        deps_updated = False

        if old_hash != new_hash:
            code, _ = run_command([
                python_exe, "-m", "pip", "install", "-r", str(requirements_file),
                "--no-warn-script-location", "-q"
            ])
            deps_updated = code == 0

        return {
            "success": True,
            "message": f"Version {tag} installed. Restart required.",
            "version": version.lstrip("v"),
            "dependencies_updated": deps_updated,
            "restart_required": True,
        }
    else:
        # Developer installation - use deskagent-release repo
        deskagent_release = Path("e:/deskagent-release")
        if not deskagent_release.exists() or not (deskagent_release / ".git").exists():
            return {
                "success": False,
                "error": f"deskagent-release repo not found at e:/deskagent-release. Clone it first with: git clone https://github.com/{_get_github_repo()} e:/deskagent-release",
            }

        total = 3
        repo_dir = str(deskagent_release)

        report(1, total, f"Fetching {tag} from github.com/{_get_github_repo()}...")
        fetch_code, _ = run_command([git_exe, "fetch", "origin", "--tags"], cwd=repo_dir, capture=True)
        if fetch_code != 0:
            system_log(f"[Update] WARNING: Fetch may have failed (code {fetch_code})")

        # Log available tags for debugging
        _, tags_output = run_command([git_exe, "tag", "-l"], cwd=repo_dir, capture=True)
        if tags_output:
            available_tags = [t for t in tags_output.strip().split("\n") if t.startswith("v")]
            system_log(f"[Update] Available tags in deskagent-release: {', '.join(available_tags[-10:])}")

        report(2, total, f"Switching deskagent-release to version {tag}...")
        code, output = run_command([git_exe, "checkout", tag], cwd=repo_dir, capture=True)
        if code != 0:
            system_log(f"[Update] ERROR: Checkout {tag} failed in deskagent-release")
            if output:
                system_log(f"[Update] Checkout output: {output.strip()}")
            return {"success": False, "error": f"Version {tag} not found on remote"}

        report(3, total, "Done. Restart deskagent-release/deskagent/start.bat to use this version.")

        return {
            "success": True,
            "message": f"Version {tag} installed in deskagent-release. Restart to apply.",
            "version": version.lstrip("v"),
            "restart_required": True,
        }


def check_for_updates(branch: str = "main") -> dict:
    """
    Check if updates are available.

    Args:
        branch: Branch to check against (main or staging)

    Returns:
        Dict with version info and update_available flag
    """
    local = get_local_version()
    remote = get_remote_version(branch)

    result = {
        "local_version": local.get("version", "unknown"),
        "local_build": local.get("build", 0),
        "remote_version": None,
        "remote_build": None,
        "update_available": False,
        "error": None,
        "branch": branch,
    }

    if remote is None:
        result["error"] = "Could not fetch remote version"
        return result

    result["remote_version"] = remote.get("version", "unknown")
    result["remote_build"] = remote.get("build", 0)

    # Compare versions only (build numbers are internal)
    cmp = compare_versions(
        local.get("version", "0.0.0"),
        remote.get("version", "0.0.0")
    )
    if cmp < 0:
        result["update_available"] = True

    return result


# === Update Process ===

def run_update(progress_callback: Callable[[int, int, str], None] = None) -> dict:
    """
    Run the update process.

    Args:
        progress_callback: Optional function(step, total, message)

    Returns:
        Dict with success status and details
    """
    def report(step, total, msg):
        if progress_callback:
            progress_callback(step, total, msg)
        # Use system_log for background logging
        system_log(f"[Update] [{step}/{total}] {msg}")

    paths = get_paths()
    git_exe = find_git()
    python_exe = find_python()

    if not git_exe:
        return {"success": False, "error": "Git not found"}

    requirements_file = paths["requirements_file"]
    old_hash = get_file_hash(requirements_file)

    if paths["is_customer_install"]:
        # Customer installation
        total = 4

        report(1, total, "Checking for updates...")

        report(2, total, "Downloading updates...")
        code, _ = run_command(
            [git_exe, "-c", "credential.helper=", "pull", "origin", "main"],
            cwd=str(paths["repo_dir"])
        )
        if code != 0:
            return {"success": False, "error": "Git pull failed"}

        report(3, total, "Installing updates...")
        src = paths["repo_dir"] / "deskagent"
        if src.exists():
            if paths["deskagent_dir"].exists():
                shutil.rmtree(paths["deskagent_dir"], ignore_errors=True)
            shutil.copytree(src, paths["deskagent_dir"])

        report(4, total, "Checking dependencies...")
        new_hash = get_file_hash(requirements_file)
        deps_updated = False

        if old_hash != new_hash:
            code, _ = run_command([
                python_exe, "-m", "pip", "install", "-r", str(requirements_file),
                "--no-warn-script-location", "-q"
            ])
            deps_updated = code == 0

        return {
            "success": True,
            "message": "Update complete",
            "dependencies_updated": deps_updated,
            "restart_required": True,
        }

    else:
        # Developer installation
        total = 2

        report(1, total, "Pulling latest changes...")
        code, _ = run_command([git_exe, "pull"], cwd=str(paths["install_dir"]))
        if code != 0:
            return {"success": False, "error": "Git pull failed"}

        report(2, total, "Checking dependencies...")
        new_hash = get_file_hash(requirements_file)

        return {
            "success": True,
            "message": "Update complete",
            "dependencies_changed": old_hash != new_hash,
            "restart_required": True,
        }


def restart_app():
    """Restart the application after update."""
    paths = get_paths()

    if paths["is_customer_install"]:
        start_bat = paths["install_dir"] / "start-deskagent.bat"
    else:
        start_bat = paths["deskagent_dir"] / "start.bat"

    if start_bat.exists():
        if sys.platform == "win32":
            os.startfile(str(start_bat))
        else:
            subprocess.Popen([str(start_bat)], shell=True)


# === CLI Entry Point ===

def main():
    """CLI entry point.

    Note: This function uses print() for user-facing CLI output since
    it's designed to be run as a standalone update command.
    """
    print()
    print("=" * 60)
    print("  DeskAgent - Update")
    print("=" * 60)
    print()

    # Check first
    check = check_for_updates()
    print(f"Local version:  {check['local_version']} (build {check['local_build']})")

    if check["error"]:
        print(f"Remote version: {check['error']}")
    else:
        print(f"Remote version: {check['remote_version']} (build {check['remote_build']})")

    print()

    if not check["update_available"] and not check["error"]:
        print("Already up to date!")
        return 0

    # Run update
    result = run_update()

    print()
    if result["success"]:
        print("=" * 60)
        print("  Update Complete!")
        print("=" * 60)
        print()
        print("  Run deskagent/start.bat to launch DeskAgent.")
    else:
        print("=" * 60)
        print(f"  Update Failed: {result.get('error', 'Unknown error')}")
        print("=" * 60)

    print()
    return 0 if result["success"] else 1


if __name__ == "__main__":
    try:
        exit_code = main()
        if sys.stdin.isatty():
            input("Press Enter to close...")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nAborted.")  # CLI output
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")  # CLI output
        system_log(f"[Update] Fatal error: {e}")
        if sys.stdin.isatty():
            input("Press Enter to close...")
        sys.exit(1)
