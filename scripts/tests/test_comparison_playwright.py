# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Automated UI Test for Backend Comparison Feature using Playwright.

Tests the split view comparison dialog using Playwright's internal browser.
Run with: python -m pytest deskagent/scripts/tests/test_comparison_playwright.py -v

Or run directly: python deskagent/scripts/tests/test_comparison_playwright.py

Requirements:
- DeskAgent running on localhost:8765
- Playwright installed: pip install playwright && playwright install
"""

import asyncio
import sys
import io
import time
from pathlib import Path

import pytest

# Add deskagent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from playwright.async_api import async_playwright, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Check if DeskAgent is running
def _check_deskagent_running():
    """Check if DeskAgent is accessible."""
    import urllib.request
    try:
        # Use /costs endpoint (lightweight JSON API)
        urllib.request.urlopen("http://localhost:8765/costs", timeout=2)
        return True
    except Exception:
        return False

DESKAGENT_RUNNING = _check_deskagent_running() if PLAYWRIGHT_AVAILABLE else False

# Skip all tests in this module if playwright is not available or DeskAgent not running
pytestmark = [
    pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed"),
    pytest.mark.skipif(not DESKAGENT_RUNNING, reason="DeskAgent not running on localhost:8765"),
    pytest.mark.integration,  # Mark as integration test
]


# =============================================================================
# Test Configuration
# =============================================================================

DESKAGENT_URL = "http://localhost:8765"
TEST_AGENT = "demo_summarize"  # Simple agent for testing
SCREENSHOT_DIR = Path(__file__).parent.parent.parent.parent.parent / "workspace" / ".temp" / "screenshots"


# =============================================================================
# Test Functions
# =============================================================================

async def wait_for_all_backends_complete(page, num_backends: int, timeout: float = 180.0):
    """
    Wait for all backend columns to finish (success or error).

    Returns dict with results per backend.
    """
    start_time = time.time()
    results = {}

    print(f"\n  Waiting for {num_backends} backends to complete (max {timeout}s)...")

    while time.time() - start_time < timeout:
        columns = await page.query_selector_all(".comparison-column")

        completed = 0
        for col in columns:
            backend = await col.get_attribute("data-backend")
            if backend in results:
                completed += 1
                continue

            # Check for success indicator (green checkmark or content)
            success_indicator = await col.query_selector(".comparison-status-indicator.success")
            error_indicator = await col.query_selector(".comparison-status-indicator.error")
            has_content = await col.query_selector(".comparison-output")
            has_error = await col.query_selector(".comparison-error")

            if success_indicator or has_content:
                results[backend] = {"status": "success", "time": time.time() - start_time}
                print(f"  ✓ {backend} completed successfully ({results[backend]['time']:.1f}s)")
                completed += 1
            elif error_indicator or has_error:
                error_el = await col.query_selector(".comparison-error")
                error_text = await error_el.inner_text() if error_el else "Unknown error"
                results[backend] = {"status": "error", "error": error_text, "time": time.time() - start_time}
                print(f"  ✗ {backend} failed: {error_text} ({results[backend]['time']:.1f}s)")
                completed += 1

        if completed >= num_backends:
            print(f"\n  All {num_backends} backends finished in {time.time() - start_time:.1f}s")
            break

        # Progress update every 10 seconds
        elapsed = time.time() - start_time
        if int(elapsed) % 10 == 0 and int(elapsed) > 0:
            loading = await page.query_selector_all(".comparison-loading")
            print(f"  ... {elapsed:.0f}s elapsed, {len(loading)} still loading")

        await asyncio.sleep(1)

    return results


@pytest.mark.asyncio
async def test_comparison_full_workflow():
    """
    Full UI test for the comparison feature:
    1. Open DeskAgent
    2. Ctrl+Shift+Click on agent to open comparison dialog
    3. Verify dialog covers full window
    4. Select backends and start comparison
    5. Wait for ALL backends to complete
    6. Verify results and take screenshots
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("ERROR: Playwright not available")
        return False

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Launch browser (headless=False to see what's happening)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        try:
            # Step 1: Navigate to DeskAgent
            print("\n[1/7] Opening DeskAgent...")
            await page.goto(DESKAGENT_URL, wait_until="networkidle")
            await page.screenshot(path=str(SCREENSHOT_DIR / "01_deskagent_loaded.png"))
            print("✓ DeskAgent loaded")

            # Step 2: Find an agent tile
            print("\n[2/7] Finding agent tile...")
            await page.wait_for_selector(".tile.agent", timeout=10000)

            # Get first agent tile
            agent_tiles = await page.query_selector_all(".tile.agent")
            if not agent_tiles:
                print("✗ No agent tiles found")
                return False

            agent_tile = agent_tiles[0]
            print(f"✓ Found {len(agent_tiles)} agent tiles")

            # Step 3: Ctrl+Shift+Click to open comparison dialog
            print("\n[3/7] Opening comparison dialog (Ctrl+Shift+Click)...")
            await agent_tile.click(modifiers=["Control", "Shift"])

            await page.wait_for_selector(".comparison-dialog, .modal-overlay", timeout=5000)
            await asyncio.sleep(0.5)
            await page.screenshot(path=str(SCREENSHOT_DIR / "02_comparison_dialog.png"))
            print("✓ Comparison dialog opened")

            # Step 4: Check backend selection
            print("\n[4/7] Checking backend selection...")
            backend_checkboxes = await page.query_selector_all('input[name="backend"]')
            num_backends = len(backend_checkboxes)

            if backend_checkboxes:
                print(f"✓ Found {num_backends} backends")

                dry_run_checkbox = await page.query_selector("#comparisonDryRun")
                if dry_run_checkbox:
                    is_checked = await dry_run_checkbox.is_checked()
                    print(f"✓ Dry-run checkbox (checked: {is_checked})")

                # Start comparison
                print("\n[5/7] Starting comparison...")
                compare_button = await page.query_selector('button:has-text("Vergleichen")')
                if compare_button:
                    await compare_button.click()
                    await asyncio.sleep(1)
                    await page.screenshot(path=str(SCREENSHOT_DIR / "03_split_view_start.png"))
                    print("✓ Comparison started")
                else:
                    print("✗ Compare button not found")
                    return False
            else:
                print("✓ Direct split view (single backend)")
                num_backends = 1

            # Step 5: Verify overlay covers full window
            print("\n[6/7] Verifying split view...")
            overlay = await page.query_selector(".comparison-overlay")

            if not overlay:
                print("✗ Comparison overlay not found")
                await page.screenshot(path=str(SCREENSHOT_DIR / "error_no_overlay.png"))
                return False

            box = await overlay.bounding_box()
            viewport = page.viewport_size

            if box:
                width_ratio = box["width"] / viewport["width"]
                height_ratio = box["height"] / viewport["height"]
                print(f"✓ Overlay: {box['width']}x{box['height']} ({width_ratio:.0%} x {height_ratio:.0%})")

                if width_ratio >= 0.95 and height_ratio >= 0.95:
                    print("✓ Full window coverage")

            columns = await page.query_selector_all(".comparison-column")
            print(f"✓ {len(columns)} comparison columns")

            dry_run_badge = await page.query_selector(".comparison-dry-run-badge")
            if dry_run_badge:
                print("✓ Dry-run badge visible")

            # Step 6: WAIT FOR ALL BACKENDS TO COMPLETE
            print("\n[7/7] Waiting for backends to complete...")
            results = await wait_for_all_backends_complete(page, num_backends, timeout=180.0)

            # Final screenshot
            await page.screenshot(path=str(SCREENSHOT_DIR / "04_final_results.png"))

            # Summary
            success_count = sum(1 for r in results.values() if r.get("status") == "success")
            error_count = sum(1 for r in results.values() if r.get("status") == "error")

            print(f"\n=== RESULTS ===")
            print(f"  Success: {success_count}/{num_backends}")
            print(f"  Errors:  {error_count}/{num_backends}")

            for backend, result in results.items():
                status = "✓" if result["status"] == "success" else "✗"
                print(f"  {status} {backend}: {result['status']} ({result['time']:.1f}s)")
                if result.get("error"):
                    print(f"      Error: {result['error']}")

            print(f"\n✓ Screenshots: {SCREENSHOT_DIR}")

            # Test passes if at least one backend succeeded
            return success_count > 0

        except Exception as e:
            print(f"\n✗ Error: {e}")
            await page.screenshot(path=str(SCREENSHOT_DIR / "error.png"))
            raise

        finally:
            close_btn = await page.query_selector(".comparison-close-btn")
            if close_btn:
                await close_btn.click()
            await browser.close()


@pytest.mark.asyncio
async def test_context_menu_has_preview_option():
    """Test that right-click context menu has Preview option."""
    if not PLAYWRIGHT_AVAILABLE:
        print("ERROR: Playwright not available")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            print("\n[1/3] Opening DeskAgent...")
            await page.goto(DESKAGENT_URL, wait_until="networkidle")

            print("\n[2/3] Right-clicking on agent tile...")
            await page.wait_for_selector(".tile.agent", timeout=10000)
            agent_tile = await page.query_selector(".tile.agent")

            if agent_tile:
                await agent_tile.click(button="right")
                await asyncio.sleep(0.5)

                print("\n[3/3] Checking context menu...")
                context_menu = await page.query_selector(".context-menu")

                if context_menu:
                    # Check for Vorschau option
                    preview_item = await page.query_selector('.context-menu-item[data-action="preview"]')
                    if preview_item:
                        text = await preview_item.inner_text()
                        print(f"✓ Preview option found: {text}")
                        await page.screenshot(path=str(SCREENSHOT_DIR / "context_menu.png"))
                        return True
                    else:
                        print("✗ Preview option not found in context menu")
                        menu_html = await context_menu.inner_html()
                        print(f"  Menu content: {menu_html[:500]}...")
                else:
                    print("✗ Context menu not found")

            return False

        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_sse_connection():
    """Test that SSE streaming works correctly."""
    if not PLAYWRIGHT_AVAILABLE:
        print("ERROR: Playwright not available")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Capture console messages
        console_messages = []
        page.on("console", lambda msg: console_messages.append(msg.text))

        try:
            print("\n[1/4] Opening DeskAgent...")
            await page.goto(DESKAGENT_URL, wait_until="networkidle")

            print("\n[2/4] Triggering comparison...")
            await page.wait_for_selector(".tile.agent", timeout=10000)
            agent_tile = await page.query_selector(".tile.agent")

            if agent_tile:
                await agent_tile.click(modifiers=["Control", "Shift"])
                await asyncio.sleep(1)

                # Start comparison
                compare_button = await page.query_selector('button:has-text("Vergleichen")')
                if compare_button:
                    await compare_button.click()
                    await asyncio.sleep(2)

            print("\n[3/4] Checking SSE messages in console...")
            sse_messages = [m for m in console_messages if "SSE" in m or "Comparison" in m or "Task" in m]
            for msg in sse_messages[-10:]:  # Last 10 messages
                print(f"  {msg}")

            print("\n[4/4] Waiting for streaming (15s)...")
            await asyncio.sleep(15)

            # Check for content
            content = await page.query_selector_all(".comparison-output")
            errors = await page.query_selector_all(".comparison-error")

            print(f"\n  Results: {len(content)} content, {len(errors)} errors")

            if len(content) > 0:
                print("✓ SSE streaming working - content received")
                return True
            elif len(errors) > 0:
                print("⚠ SSE streaming had errors")
                # Get error messages
                for i, err in enumerate(errors):
                    text = await err.inner_text()
                    print(f"  Error {i+1}: {text}")
                return False
            else:
                print("? No content or errors yet - still loading")
                return None

        finally:
            await browser.close()


# =============================================================================
# Main
# =============================================================================

async def main():
    """Run all tests."""
    print("=" * 60)
    print("DeskAgent Comparison UI Tests (Playwright)")
    print("=" * 60)

    results = {}

    # Test 1: Context menu
    print("\n" + "=" * 60)
    print("TEST 1: Context Menu Preview Option")
    print("=" * 60)
    results["context_menu"] = await test_context_menu_has_preview_option()

    # Test 2: Full workflow
    print("\n" + "=" * 60)
    print("TEST 2: Full Comparison Workflow")
    print("=" * 60)
    results["full_workflow"] = await test_comparison_full_workflow()

    # Test 3: SSE connection
    print("\n" + "=" * 60)
    print("TEST 3: SSE Streaming")
    print("=" * 60)
    results["sse_streaming"] = await test_sse_connection()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = "✓ PASS" if result else ("? UNKNOWN" if result is None else "✗ FAIL")
        print(f"  {name}: {status}")

    print(f"\nScreenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    # Fix Windows console encoding only when running directly
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    asyncio.run(main())
