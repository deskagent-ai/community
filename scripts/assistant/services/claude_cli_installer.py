# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Claude CLI Installer
=====================
Downloads portable Node.js and installs Claude Code CLI.

This enables the Claude Agent SDK to work on systems without Node.js installed.
The installation is portable (no admin rights needed) and stored in DESKAGENT_DIR/node.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import AsyncGenerator
import urllib.request

# Node.js LTS version to download
NODE_VERSION = "v20.11.0"

# Download URLs for each platform
NODE_URLS = {
    "win32": f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-win-x64.zip",
    "darwin": f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-darwin-x64.tar.gz",
    "linux": f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-linux-x64.tar.xz"
}

# Expected archive sizes for validation (approximate, in bytes)
NODE_SIZES = {
    "win32": 30_000_000,  # ~30MB
    "darwin": 40_000_000,  # ~40MB
    "linux": 25_000_000,   # ~25MB
}


def get_node_dir() -> Path:
    """Get directory for portable Node.js installation.

    Uses config directory (e.g. %APPDATA%/DeskAgent/node) instead of
    DESKAGENT_DIR to keep source/install directories clean.
    """
    from paths import get_config_dir
    return get_config_dir() / "node"


def get_node_bin_dir() -> Path:
    """Get the bin directory where node/npm executables are located."""
    node_dir = get_node_dir()

    if sys.platform == "win32":
        return node_dir / f"node-{NODE_VERSION}-win-x64"
    elif sys.platform == "darwin":
        return node_dir / f"node-{NODE_VERSION}-darwin-x64" / "bin"
    else:  # linux
        return node_dir / f"node-{NODE_VERSION}-linux-x64" / "bin"


def get_npm_path() -> Path:
    """Get path to npm executable."""
    bin_dir = get_node_bin_dir()

    if sys.platform == "win32":
        return bin_dir / "npm.cmd"
    else:
        return bin_dir / "npm"


def get_claude_cli_path() -> Path | None:
    """
    Get path to installed Claude CLI.

    Checks:
    1. Our portable installation
    2. System PATH (shutil.which)

    Returns:
        Path to claude CLI if found, None otherwise
    """
    # Check portable installation first
    bin_dir = get_node_bin_dir()

    if sys.platform == "win32":
        cli_path = bin_dir / "claude.cmd"
    else:
        cli_path = bin_dir / "claude"

    if cli_path.exists():
        return cli_path

    # Check system PATH
    system_cli = shutil.which("claude")
    if system_cli:
        return Path(system_cli)

    return None


def is_nodejs_installed() -> bool:
    """Check if portable Node.js is installed."""
    npm_path = get_npm_path()
    return npm_path.exists()


def is_claude_cli_installed() -> bool:
    """Check if Claude CLI is installed (portable or system)."""
    return get_claude_cli_path() is not None


async def download_nodejs() -> AsyncGenerator[dict, None]:
    """
    Download and extract portable Node.js.

    Yields progress updates as dicts:
        {"step": "nodejs", "status": "downloading", "progress": 0-100}
        {"step": "nodejs", "status": "extracting"}
        {"step": "nodejs", "status": "complete"}
        {"step": "nodejs", "status": "error", "message": "..."}
    """
    node_dir = get_node_dir()

    # Check if already installed
    if is_nodejs_installed():
        yield {"step": "nodejs", "status": "complete", "message": "Already installed"}
        return

    url = NODE_URLS.get(sys.platform)
    if not url:
        yield {"step": "nodejs", "status": "error", "message": f"Unsupported platform: {sys.platform}"}
        return

    try:
        # Create temp file for download
        suffix = ".zip" if sys.platform == "win32" else ".tar.gz"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        yield {"step": "nodejs", "status": "downloading", "progress": 0}

        # Download with progress tracking
        def report_progress(block_num, block_size, total_size):
            if total_size > 0:
                progress = min(100, int(block_num * block_size * 100 / total_size))
                # Note: We can't yield from here, so progress is approximate

        urllib.request.urlretrieve(url, temp_path, reporthook=report_progress)

        yield {"step": "nodejs", "status": "downloading", "progress": 100}

        # Validate download size
        file_size = os.path.getsize(temp_path)
        expected_min = NODE_SIZES.get(sys.platform, 0) * 0.8  # Allow 20% variance
        if file_size < expected_min:
            os.unlink(temp_path)
            yield {"step": "nodejs", "status": "error", "message": f"Download incomplete: {file_size} bytes"}
            return

        yield {"step": "nodejs", "status": "extracting"}

        # Extract
        node_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == "win32":
            with zipfile.ZipFile(temp_path, 'r') as zf:
                zf.extractall(node_dir)
        else:
            # Use tar for macOS/Linux
            import tarfile
            with tarfile.open(temp_path, 'r:*') as tf:
                tf.extractall(node_dir)

        # Cleanup temp file
        os.unlink(temp_path)

        # Verify extraction
        if not is_nodejs_installed():
            yield {"step": "nodejs", "status": "error", "message": "Extraction failed - npm not found"}
            return

        yield {"step": "nodejs", "status": "complete"}

    except urllib.error.URLError as e:
        yield {"step": "nodejs", "status": "error", "message": f"Download failed: {e.reason}"}
    except Exception as e:
        yield {"step": "nodejs", "status": "error", "message": str(e)}


async def install_claude_cli() -> AsyncGenerator[dict, None]:
    """
    Install Claude Code CLI using npm.

    Requires Node.js to be installed first (call download_nodejs).

    Yields progress updates as dicts:
        {"step": "cli", "status": "installing"}
        {"step": "cli", "status": "complete", "path": "/path/to/claude"}
        {"step": "cli", "status": "error", "message": "..."}
    """
    # Check Node.js is installed
    if not is_nodejs_installed():
        yield {"step": "cli", "status": "error", "message": "Node.js not installed"}
        return

    # Check if already installed
    existing_cli = get_claude_cli_path()
    if existing_cli:
        yield {"step": "cli", "status": "complete", "path": str(existing_cli), "message": "Already installed"}
        return

    npm_path = get_npm_path()
    bin_dir = get_node_bin_dir()

    yield {"step": "cli", "status": "installing"}

    try:
        # Set up environment with our Node.js in PATH
        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

        # Run npm install in a thread to not block async loop
        def run_npm():
            # Use --prefix to install in our node directory
            cmd = [
                str(npm_path),
                "install",
                "-g",
                "@anthropic-ai/claude-code"
            ]

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,  # Prevent WinError 6 on Windows without console
                cwd=str(bin_dir.parent)  # Run from node directory
            )

            return result

        # Run in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_npm)

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown npm error"
            yield {"step": "cli", "status": "error", "message": f"npm install failed: {error_msg[:200]}"}
            return

        # Verify installation
        cli_path = get_claude_cli_path()
        if not cli_path:
            yield {"step": "cli", "status": "error", "message": "Installation completed but claude CLI not found"}
            return

        yield {"step": "cli", "status": "complete", "path": str(cli_path)}

    except Exception as e:
        yield {"step": "cli", "status": "error", "message": str(e)}


async def install_cli() -> AsyncGenerator[dict, None]:
    """
    Full installation: Node.js + Claude CLI.

    Convenience function that runs both steps.

    Yields progress updates for both steps.
    """
    # Step 1: Download Node.js
    async for progress in download_nodejs():
        yield progress
        if progress.get("status") == "error":
            return

    # Step 2: Install Claude CLI
    async for progress in install_claude_cli():
        yield progress


def cleanup_installation():
    """
    Remove portable Node.js installation.

    Use this if installation is corrupted or to free disk space.
    """
    node_dir = get_node_dir()
    if node_dir.exists():
        shutil.rmtree(node_dir, ignore_errors=True)


# For testing
if __name__ == "__main__":
    async def test():
        print(f"Node.js dir: {get_node_dir()}")
        print(f"Node.js installed: {is_nodejs_installed()}")
        print(f"Claude CLI installed: {is_claude_cli_installed()}")
        print(f"Claude CLI path: {get_claude_cli_path()}")

        print("\nStarting installation...")
        async for progress in install_cli():
            print(f"  {progress}")

        print(f"\nClaude CLI path: {get_claude_cli_path()}")

    asyncio.run(test())
