#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
DeskAgent - Main Entry Point
=============================
Compiled with Nuitka for distribution.

This is the single entry point for the compiled application.
It ensures proper path setup before importing the assistant module.
"""
import sys
import os

def _fix_nofollow_namespace_packages(site_packages_dir):
    """Fix imports for packages excluded via --nofollow-import-to in Nuitka.

    Nuitka's MetaPathBasedLoader intercepts imports BEFORE Python's standard
    PathFinder. For excluded packages (NOFOLLOW_PACKAGES), this can block
    runtime resolution from embedded Python's site-packages.

    This pre-registers namespace packages in sys.modules so subpackage
    imports can find them. Note: the actual reliable fix is the importlib
    fallback in gemini_adk.py - this is a best-effort early registration.

    See: https://github.com/Nuitka/Nuitka/issues/1077
    """
    nofollow_namespaces = ['google']

    for pkg_name in nofollow_namespaces:
        pkg_dir = os.path.join(site_packages_dir, pkg_name)
        if not os.path.isdir(pkg_dir):
            continue

        if pkg_name in sys.modules:
            existing_path = getattr(sys.modules[pkg_name], '__path__', None)
            if existing_path is not None and pkg_dir not in list(existing_path):
                sys.modules[pkg_name].__path__.append(pkg_dir)
        else:
            try:
                pkg_init = os.path.join(pkg_dir, '__init__.py')
                if os.path.isfile(pkg_init):
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        pkg_name, pkg_init,
                        submodule_search_locations=[pkg_dir]
                    )
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[pkg_name] = mod
                        spec.loader.exec_module(mod)
                else:
                    import types as _types
                    mod = _types.ModuleType(pkg_name)
                    mod.__path__ = [pkg_dir]
                    mod.__package__ = pkg_name
                    sys.modules[pkg_name] = mod
            except Exception:
                pass


def _is_macos_app_bundle():
    """Check if running from a macOS .app bundle."""
    if sys.platform != 'darwin':
        return False
    exe_dir = os.path.dirname(os.path.realpath(sys.executable))
    return os.path.basename(exe_dir) == "MacOS" and os.path.basename(os.path.dirname(exe_dir)) == "Contents"


def _get_embedded_python_paths(base_dir):
    """Get embedded Python Lib and site-packages paths for the current platform.

    Windows: base_dir/python/Lib/site-packages
    macOS/Linux venv: base_dir/python/lib/python3.X/site-packages

    Returns (python_lib, python_site_packages) or (None, None) if not found.
    """
    if sys.platform == 'win32':
        python_lib = os.path.join(base_dir, 'python', 'Lib')
        python_site_packages = os.path.join(python_lib, 'site-packages')
        return python_lib, python_site_packages

    # macOS/Linux: venv layout python/lib/python3.X/site-packages
    python_dir = os.path.join(base_dir, 'python')
    lib_dir = os.path.join(python_dir, 'lib')
    if os.path.isdir(lib_dir):
        # Find python3.X directory
        try:
            for entry in os.listdir(lib_dir):
                if entry.startswith('python3'):
                    python_lib = os.path.join(lib_dir, entry)
                    python_site_packages = os.path.join(python_lib, 'site-packages')
                    if os.path.isdir(python_site_packages):
                        return python_lib, python_site_packages
        except OSError:
            pass

    return None, None


def setup_paths():
    """Ensure scripts directory and required paths are in sys.path."""
    is_compiled = getattr(sys, 'frozen', False) or '__compiled__' in dir()

    # Get the base directory (where deskagent data files live)
    if is_compiled:
        if _is_macos_app_bundle():
            # macOS App Bundle: executable is in Contents/MacOS/
            # but data files (scripts, python, mcp) are in Contents/Resources/
            exe_dir = os.path.dirname(os.path.realpath(sys.executable))
            base_dir = os.path.join(os.path.dirname(exe_dir), 'Resources')
            scripts_dir = os.path.join(base_dir, 'scripts')
            print(f"[Paths] macOS App Bundle detected")
            print(f"[Paths]   executable: {sys.executable}")
            print(f"[Paths]   base_dir (Resources): {base_dir}")
            print(f"[Paths]   scripts_dir: {scripts_dir}")
        else:
            # Windows/Linux: exe sits in deskagent/ alongside python/, scripts/, etc.
            base_dir = os.path.dirname(sys.executable)
            scripts_dir = base_dir
    else:
        # Running as Python script (dev mode)
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(scripts_dir)  # deskagent/

    # Add scripts directory to path if not already there
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # CRITICAL: Add embedded Python's Lib and site-packages to sys.path
    # This enables imports of email.mime, xml.dom, msal, google.genai, etc.
    python_lib, python_site_packages = _get_embedded_python_paths(base_dir)

    if is_compiled:
        print(f"[Paths] Embedded Python lookup in: {base_dir}")
        print(f"[Paths]   python_lib: {python_lib} (exists: {python_lib and os.path.isdir(python_lib)})")
        print(f"[Paths]   site-packages: {python_site_packages} (exists: {python_site_packages and os.path.isdir(python_site_packages)})")

    # Insert at position 0 so our Lib is found BEFORE python312.zip
    # Order: site-packages first (msal, google-genai), then Lib (email.mime, xml.dom)
    if python_lib and os.path.isdir(python_lib) and python_lib not in sys.path:
        sys.path.insert(0, python_lib)
    if python_site_packages and os.path.isdir(python_site_packages) and python_site_packages not in sys.path:
        sys.path.insert(0, python_site_packages)

    if is_compiled and python_site_packages and os.path.isdir(python_site_packages):
        # Log a few key packages for diagnostics
        for pkg in ['google', 'anthropic', 'mcp', 'spacy']:
            pkg_path = os.path.join(python_site_packages, pkg)
            print(f"[Paths]   {pkg}: {'FOUND' if os.path.isdir(pkg_path) else 'MISSING'}")

    # CRITICAL: Clear cached email/xml modules so they're reimported from our Lib
    # Nuitka's python312.zip has incomplete stdlib (no email.mime, xml.dom)
    # Without this, the cached incomplete modules block access to our complete ones
    for mod_name in list(sys.modules.keys()):
        if mod_name in ('email', 'xml') or mod_name.startswith(('email.', 'xml.')):
            del sys.modules[mod_name]

    # CRITICAL: Fix imports for packages excluded from Nuitka compilation.
    # Nuitka's MetaPathBasedLoader blocks runtime import of excluded subpackages
    # (like google.genai) even when they exist in embedded Python's site-packages.
    if python_site_packages and os.path.isdir(python_site_packages):
        _fix_nofollow_namespace_packages(python_site_packages)

    # Set PYTHONPATH environment variable for subprocesses (MCPs)
    os.environ['PYTHONPATH'] = scripts_dir

    return scripts_dir


def main():
    """Main entry point for DeskAgent."""
    # Setup paths first
    scripts_dir = setup_paths()

    # Import platform module to initialize platform-specific features
    try:
        from assistant.platform import init_platform, is_compiled
        init_platform()

        if is_compiled():
            print("[DeskAgent] Running as compiled binary")
    except ImportError:
        # Platform module not available (development mode)
        pass

    # Import and run the main assistant
    from assistant import main as assistant_main
    assistant_main()


if __name__ == "__main__":
    main()
