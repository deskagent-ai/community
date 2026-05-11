# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Playwright-based E2E tests for DeskAgent WebUI.

Run with:
    pytest tests/test_ui/test_webui.py -v

    # With custom port:
    pytest tests/test_ui/ --base-url=http://localhost:5005

Requirements:
    - DeskAgent server running: python -m assistant --port 8765
    - Playwright browsers: playwright install chromium
"""

import re

import pytest
from playwright.sync_api import Page, expect


# === Basic Page Load Tests ===

class TestPageLoad:
    """Tests for basic page loading."""

    def test_homepage_loads(self, page: Page, base_url: str):
        """Test that the homepage loads successfully."""
        page.goto(base_url)
        expect(page).to_have_title("DeskAgent")

    def test_header_elements_visible(self, page: Page, base_url: str):
        """Test that header elements are visible."""
        page.goto(base_url)

        # Logo should be visible
        logo = page.locator(".app-logo")
        expect(logo).to_be_visible()

        # Connection badge should show online
        connection_badge = page.locator("#connectionBadge")
        expect(connection_badge).to_be_visible()

    def test_tile_grid_visible(self, page: Page, base_url: str):
        """Test that the tile grid is visible on homepage."""
        page.goto(base_url)

        tile_grid = page.locator("#tileGrid")
        expect(tile_grid).to_be_visible()

    def test_cost_display_visible(self, page: Page, base_url: str):
        """Test that cost display is visible in header."""
        page.goto(base_url)

        cost_display = page.locator("#totalCostDisplay")
        expect(cost_display).to_be_visible()
        expect(cost_display).to_contain_text("$")


# === Settings Panel Tests ===

class TestSettingsPanel:
    """Tests for the settings panel."""

    def test_settings_opens(self, page: Page, base_url: str):
        """Test that settings panel opens when clicking settings icon."""
        page.goto(base_url)

        # Click settings button
        page.click("[onclick='openSettings()']")

        # Settings panel should be visible
        settings_panel = page.locator("#settingsPanel")
        expect(settings_panel).to_be_visible()

    def test_settings_closes(self, page: Page, base_url: str):
        """Test that settings panel closes."""
        page.goto(base_url)

        # Open settings
        page.click("[onclick='openSettings()']")
        expect(page.locator("#settingsPanel")).to_be_visible()

        # Close settings (use specific selector for settings close button)
        page.click("#settingsPanel .close-btn")

        # Settings should be hidden
        expect(page.locator("#settingsPanel")).to_be_hidden()

    def test_settings_tabs_exist(self, page: Page, base_url: str):
        """Test that all settings tabs exist."""
        page.goto(base_url)
        page.click("[onclick='openSettings()']")

        # Check for expected tabs
        expect(page.locator("#settingsTabLicense")).to_be_visible()
        expect(page.locator("#settingsTabUpdate")).to_be_visible()
        expect(page.locator("#settingsTabPreferences")).to_be_visible()
        expect(page.locator("#settingsTabSupport")).to_be_visible()
        expect(page.locator("#settingsTabApi")).to_be_visible()

    def test_settings_tab_switching(self, page: Page, base_url: str):
        """Test that clicking tabs switches content."""
        page.goto(base_url)
        page.click("[onclick='openSettings()']")

        # Click on API tab
        page.click("#settingsTabApi")

        # API tab should be active
        expect(page.locator("#settingsTabApi")).to_have_class(re.compile(r"active"))


# === Category Filter Tests ===

class TestCategoryFilter:
    """Tests for the category filter dropdown."""

    def test_category_dropdown_exists(self, page: Page, base_url: str):
        """Test that category dropdown exists."""
        page.goto(base_url)

        dropdown = page.locator("#categoryDropdown")
        expect(dropdown).to_be_visible()

    def test_category_menu_opens(self, page: Page, base_url: str):
        """Test that category menu opens on click."""
        page.goto(base_url)

        # Click to open menu
        page.click("#categoryDropdown .header-badge")

        # Menu should be visible
        menu = page.locator("#categoryMenu")
        expect(menu).to_be_visible()

    def test_all_category_selected_by_default(self, page: Page, base_url: str):
        """Test that 'Alle' category is selected by default."""
        page.goto(base_url)

        label = page.locator("#categoryLabel")
        expect(label).to_have_text("Alle")


# === Tile Interaction Tests ===

class TestTileInteraction:
    """Tests for tile interactions."""

    def test_tiles_are_clickable(self, page: Page, base_url: str):
        """Test that tiles exist and are clickable."""
        page.goto(base_url)

        # Get first tile
        tiles = page.locator(".tile")

        # Should have at least one tile
        expect(tiles.first).to_be_visible()

    def test_chat_tile_opens_input(self, page: Page, base_url: str):
        """Test that clicking a chat tile shows input area."""
        page.goto(base_url)

        # Find and click a chat tile (type=chat)
        chat_tile = page.locator(".tile[data-type='chat']").first

        if chat_tile.count() > 0:
            chat_tile.click()

            # Input panel should appear
            input_panel = page.locator("#inputPanel")
            expect(input_panel).to_be_visible()

    def test_shift_click_agent_shows_context_dialog(self, page: Page, base_url: str):
        """Test that Shift+Click on agent tile shows context input dialog."""
        page.goto(base_url)
        page.wait_for_load_state("domcontentloaded")

        # Find an agent tile
        agent_tile = page.locator(".tile.agent").first

        if agent_tile.count() == 0:
            pytest.skip("No agent tiles found")

        # Shift+Click the tile
        agent_tile.click(modifiers=["Shift"])

        # Dialog should appear with context textarea
        dialog = page.locator("#inputDialogOverlay")
        expect(dialog).to_be_visible(timeout=2000)

        # Should have _context field
        context_field = page.locator("[data-field='_context'] textarea")
        expect(context_field).to_be_visible()

        # Close dialog
        page.click(".btn-cancel")

    def test_shift_click_shows_context_plus_existing_inputs(self, page: Page, base_url: str):
        """Test that Shift+Click shows context field plus any existing agent inputs."""
        page.goto(base_url)
        page.wait_for_load_state("domcontentloaded")

        # Find an agent tile that has inputs defined (look for upload badge)
        agent_with_inputs = page.locator(".tile.agent:has(.tile-badge)")

        if agent_with_inputs.count() == 0:
            pytest.skip("No agent tiles with inputs found")

        # Shift+Click the tile
        agent_with_inputs.first.click(modifiers=["Shift"])

        # Dialog should appear
        dialog = page.locator("#inputDialogOverlay")
        expect(dialog).to_be_visible(timeout=2000)

        # Should have _context field (prepended)
        context_field = page.locator("[data-field='_context']")
        expect(context_field).to_be_visible()

        # Should have more than one input field (context + original inputs)
        input_fields = page.locator(".input-field")
        assert input_fields.count() > 1

        # Close dialog
        page.click(".btn-cancel")


# === API Endpoints Tests ===

class TestAPIEndpoints:
    """Tests for API endpoint responses."""

    def test_costs_endpoint(self, page: Page, base_url: str):
        """Test that costs endpoint returns data."""
        response = page.request.get(f"{base_url}/costs")
        assert response.ok
        data = response.json()
        assert "total_usd" in data


# === Loading State Tests ===

class TestLoadingStates:
    """Tests for loading states."""

    def test_loading_panel_hidden_initially(self, page: Page, base_url: str):
        """Test that loading panel is hidden on page load."""
        page.goto(base_url)

        loading_panel = page.locator("#loadingPanel")
        # Loading panel exists but should not be in active state
        expect(loading_panel).not_to_have_class(re.compile(r"active"))


# === System Panel Tests ===

class TestSystemPanel:
    """Tests for the system panel (DevTools overlay)."""

    def test_system_panel_hidden_initially(self, page: Page, base_url: str):
        """Test that system panel is hidden by default."""
        page.goto(base_url)

        system_panel = page.locator("#systemPanel")
        expect(system_panel).to_have_class(re.compile(r"hidden"))


# === Responsive Design Tests ===

class TestResponsiveDesign:
    """Tests for responsive design behavior."""

    def test_mobile_viewport(self, browser, base_url: str):
        """Test that page works on mobile viewport."""
        context = browser.new_context(
            viewport={"width": 375, "height": 667}
        )
        page = context.new_page()
        page.goto(base_url)

        # Page should load
        expect(page.locator(".app-header")).to_be_visible()

        context.close()

    def test_tablet_viewport(self, browser, base_url: str):
        """Test that page works on tablet viewport."""
        context = browser.new_context(
            viewport={"width": 768, "height": 1024}
        )
        page = context.new_page()
        page.goto(base_url)

        # Page should load
        expect(page.locator(".app-header")).to_be_visible()

        context.close()


# === Screenshot Tests (for visual regression) ===

class TestScreenshots:
    """Screenshot tests for visual verification."""

    def test_screenshot_homepage(self, page: Page, base_url: str, tmp_path):
        """Take a screenshot of the homepage."""
        page.goto(base_url)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)  # Wait for tiles to render

        screenshot_path = tmp_path / "homepage.png"
        page.screenshot(path=str(screenshot_path))

        assert screenshot_path.exists()

    def test_screenshot_settings(self, page: Page, base_url: str, tmp_path):
        """Take a screenshot of settings panel."""
        page.goto(base_url)
        page.click("[onclick='openSettings()']")
        page.wait_for_timeout(300)  # Wait for animation

        screenshot_path = tmp_path / "settings.png"
        page.screenshot(path=str(screenshot_path))

        assert screenshot_path.exists()


# === Agent Execution Tests ===

class TestAgentExecution:
    """Tests for actual agent execution through the UI.

    These tests run real agents and verify the full flow:
    UI click → API call → Agent execution → Response display
    """

    @pytest.mark.slow
    def test_run_test_mcp_agent(self, page: Page, base_url: str):
        """Test running the test_mcp agent and verifying output.

        This is an integration test that:
        1. Clicks the test_mcp agent tile
        2. Waits for loading panel to appear
        3. Waits for task completion (up to 60s)
        4. Verifies output panel shows results
        """
        page.goto(base_url)
        page.wait_for_load_state("domcontentloaded")

        # Find and click the test_mcp agent tile
        test_mcp_tile = page.locator(".tile.agent[onclick*='test_mcp']")

        # Skip if test_mcp agent doesn't exist in this config
        if test_mcp_tile.count() == 0:
            pytest.skip("test_mcp agent not found in tile grid")

        test_mcp_tile.click()

        # Loading panel should appear (uses 'visible' class)
        loading_panel = page.locator("#loadingPanel")
        expect(loading_panel).to_have_class(re.compile(r"visible"), timeout=5000)

        # Wait for task to complete (loading panel becomes hidden or result appears)
        # This can take up to 60 seconds for real AI calls
        page.wait_for_function(
            """() => {
                const loading = document.querySelector('#loadingPanel');
                const result = document.querySelector('#resultPanel');
                return !loading.classList.contains('visible') ||
                       (result && result.classList.contains('visible'));
            }""",
            timeout=60000
        )

        # Result panel should be visible with content
        result_panel = page.locator("#resultPanel")
        expect(result_panel).to_have_class(re.compile(r"visible"), timeout=5000)

        # Result content should have some text
        result_content = page.locator("#resultContent")
        expect(result_content).not_to_be_empty()

        # Verify we got a response (should contain clipboard or email info)
        content_text = result_content.inner_text()
        assert len(content_text) > 50, f"Output too short: {len(content_text)} chars"

    @pytest.mark.slow
    def test_agent_click_starts_loading(self, page: Page, base_url: str):
        """Test that clicking an agent tile starts the loading process.

        This is a simpler test that just verifies the UI responds to agent clicks
        without waiting for full completion (which is tested in test_run_test_mcp_agent).
        """
        page.goto(base_url)
        page.wait_for_load_state("domcontentloaded")

        # Close any existing result panel first
        page.evaluate("document.getElementById('resultPanel')?.classList.remove('visible')")
        page.wait_for_timeout(500)

        # Find the test_mcp agent tile specifically
        agent_tile = page.locator(".tile.agent[onclick*='test_mcp']")

        if agent_tile.count() == 0:
            pytest.skip("test_mcp agent not found")

        agent_tile.click()

        # Loading panel should appear (uses 'visible' class)
        loading_panel = page.locator("#loadingPanel")
        expect(loading_panel).to_have_class(re.compile(r"visible"), timeout=5000)


# === Quick Access Mode Tests ===

class TestQuickAccessMode:
    """Tests for Quick Access tile-only mode (compact 280x500 window)."""

    def test_quickaccess_mode_detected(self, browser, base_url: str):
        """Test that quickaccess URL param adds body class."""
        context = browser.new_context(viewport={"width": 280, "height": 500})
        page = context.new_page()
        page.goto(f"{base_url}/?quickaccess=1")
        page.wait_for_load_state("domcontentloaded")

        # Body should have quick-access-mode class
        expect(page.locator("body")).to_have_class(re.compile(r"quick-access-mode"))
        context.close()

    def test_narrow_window_triggers_quickaccess(self, browser, base_url: str):
        """Test that narrow window (< 300px) triggers Quick Access mode."""
        context = browser.new_context(viewport={"width": 280, "height": 500})
        page = context.new_page()
        page.goto(base_url)  # No quickaccess param
        page.wait_for_load_state("domcontentloaded")

        # Should still detect Quick Access mode from window width
        expect(page.locator("body")).to_have_class(re.compile(r"quick-access-mode"))
        context.close()

    def test_result_panel_hidden_in_quickaccess(self, browser, base_url: str):
        """Test that result panel stays hidden in Quick Access mode."""
        context = browser.new_context(viewport={"width": 280, "height": 500})
        page = context.new_page()
        page.goto(f"{base_url}/?quickaccess=1")
        page.wait_for_load_state("domcontentloaded")

        # Find test_mcp agent
        agent_tile = page.locator(".tile.agent[onclick*='test_mcp']")
        if agent_tile.count() == 0:
            context.close()
            pytest.skip("test_mcp agent not found")

        agent_tile.click()

        # Wait a moment for task to start
        page.wait_for_timeout(1000)

        # Result panel should be hidden via CSS even if it has visible class
        result_panel = page.locator("#resultPanel")
        expect(result_panel).to_be_hidden()
        context.close()

    def test_tiles_visible_during_execution(self, browser, base_url: str):
        """Test that other tiles remain visible (dimmed) during agent execution."""
        context = browser.new_context(viewport={"width": 280, "height": 500})
        page = context.new_page()
        page.goto(f"{base_url}/?quickaccess=1")
        page.wait_for_load_state("domcontentloaded")

        # Find test_mcp agent
        agent_tile = page.locator(".tile.agent[onclick*='test_mcp']")
        if agent_tile.count() == 0:
            context.close()
            pytest.skip("test_mcp agent not found")

        agent_tile.click()
        page.wait_for_timeout(500)

        # Tile grid should have has-pinned class
        tile_grid = page.locator("#tileGrid")
        expect(tile_grid).to_have_class(re.compile(r"has-pinned"))

        # Non-pinned tiles should still be visible (dimmed)
        other_tiles = page.locator(".tile:not(.pinned)")
        if other_tiles.count() > 0:
            expect(other_tiles.first).to_be_visible()

        context.close()

    @pytest.mark.slow
    def test_chat_button_appears_after_completion(self, browser, base_url: str):
        """Test that Open Chat button appears on completed tile."""
        context = browser.new_context(viewport={"width": 280, "height": 500})
        page = context.new_page()
        page.goto(f"{base_url}/?quickaccess=1")
        page.wait_for_load_state("domcontentloaded")

        # Find test_mcp agent
        agent_tile = page.locator(".tile.agent[onclick*='test_mcp']")
        if agent_tile.count() == 0:
            context.close()
            pytest.skip("test_mcp agent not found")

        agent_tile.click()

        # Wait for completion (up to 60s for real AI call)
        page.wait_for_function(
            """() => {
                const tile = document.querySelector('.tile.pinned');
                return tile && tile.classList.contains('qa-complete');
            }""",
            timeout=60000
        )

        # Chat button should be visible
        chat_btn = page.locator(".tile.pinned .qa-chat-btn")
        expect(chat_btn).to_be_visible()

        context.close()
