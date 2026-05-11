/**
 * WebUI UI Module
 * DOM manipulation, UI state, panels, loading, animations.
 * Depends on: webui-core.js (state variables)
 */

// =============================================================================
// Global Filter State
// =============================================================================
let currentSearchFilter = '';

// =============================================================================
// Toast Notifications
// =============================================================================

function showToast(message, duration = 3000) {
    const toast = document.createElement('div');
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: #333;
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        font-size: 14px;
        z-index: 10001;
        opacity: 0;
        transition: opacity 0.3s;
    `;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.style.opacity = '1');
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Alias for showSnackbar (used in some places)
function showSnackbar(message) {
    showToast(message);
}

/**
 * Show a notification with type-based styling
 * @param {string} message - The message to display (can include HTML if html=true)
 * @param {string} type - 'success', 'error', 'warning', or 'info'
 * @param {number} duration - How long to show (ms)
 * @param {boolean} html - If true, render message as HTML
 * @param {string} id - Optional ID to allow hiding the notification later
 */
function showNotification(message, type = 'info', duration = 3000, html = false, id = null) {
    const colors = {
        success: { bg: '#4CAF50', text: 'white' },
        error: { bg: '#f44336', text: 'white' },
        warning: { bg: '#ff9800', text: 'white' },
        info: { bg: '#2196F3', text: 'white' }
    };
    const style = colors[type] || colors.info;

    const toast = document.createElement('div');
    if (id) {
        toast.id = id;
    }
    if (html) {
        toast.innerHTML = message;
    } else {
        toast.textContent = message;
    }
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: ${style.bg};
        color: ${style.text};
        padding: 12px 24px;
        border-radius: 8px;
        font-size: 14px;
        z-index: 10001;
        opacity: 0;
        transition: opacity 0.3s;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    `;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.style.opacity = '1');
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * Hide a notification by its ID
 * @param {string} id - The notification ID to hide
 */
function hideNotification(id) {
    const toast = document.getElementById(id);
    if (toast) {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }
}

// =============================================================================
// Tile Management
// =============================================================================

function showTiles() {
    // Show tiles, hide result and processing overlay
    document.querySelector('.tile-grid')?.classList.remove('hidden');
    document.getElementById('resultPanel')?.classList.remove('visible');
    hideProcessingOverlay();
    hidePromptArea();

    // Unpin any pinned tile
    unpinTile();

    // Refresh badges for any running tasks
    updateAllBadges();

    // Rotate slogan when showing tiles (task completed)
    rotateSlogan();
}

function hideTiles() {
    // Quick Access mode: Don't hide tiles, they stay visible but dimmed
    if (isQuickAccessMode) {
        return;
    }
    document.querySelector('.tile-grid')?.classList.add('hidden');
}

function pinTile(tile) {
    if (pinnedTile === tile) return;  // Already pinned

    // #9 - Always cleanup first to prevent DOM desync
    if (pinnedTile) {
        unpinTile();  // Always cleanup first
    }

    pinnedTile = tile;
    tile.classList.add('pinned');

    // Add close button (remove any existing one first)
    const existingBtn = tile.querySelector('.pinned-close-btn');
    if (existingBtn) existingBtn.remove();

    const closeBtn = document.createElement('button');
    closeBtn.className = 'pinned-close-btn';
    closeBtn.innerHTML = '<span class="material-icons">close</span>';
    closeBtn.title = t('dialog.cancel');
    closeBtn.onclick = (e) => {
        e.stopPropagation();
        closeResult();
    };
    tile.appendChild(closeBtn);

    // Quick Access mode: Don't move tile, don't add minimize button - just track state with close button
    if (isQuickAccessMode) {
        return;  // Tile stays in grid, close button added above
    }

    // Store original background and parent for restoration
    tile._originalBackground = tile.style.background || '';
    tile._originalParent = tile.parentNode;
    tile._originalNextSibling = tile.nextSibling;

    // Add minimize button (bottom corner) - keeps task running in background
    const existingMinBtn = tile.querySelector('.pinned-minimize-btn');
    if (existingMinBtn) existingMinBtn.remove();

    const minimizeBtn = document.createElement('button');
    minimizeBtn.className = 'pinned-minimize-btn';
    minimizeBtn.innerHTML = '<span class="material-icons">minimize</span>';
    minimizeBtn.title = t('ui.minimize_to_background');
    minimizeBtn.onclick = (e) => {
        e.stopPropagation();
        minimizeToBackground();
    };
    tile.appendChild(minimizeBtn);

    // Move tile to body so it's visible even when tile-grid is hidden
    document.body.appendChild(tile);

    // Add has-pinned class to tile-grid to collapse it (pinned tile shows alone)
    const tileGrid = document.querySelector('.tile-grid');
    if (tileGrid) tileGrid.classList.add('has-pinned');
}

function unpinTile() {
    if (pinnedTile) {
        pinnedTile.classList.remove('pinned');
        // Remove Quick Access mode classes
        pinnedTile.classList.remove('qa-running', 'qa-success', 'qa-error', 'qa-complete');
        const qaBtn = pinnedTile.querySelector('.qa-chat-btn');
        if (qaBtn) qaBtn.remove();

        // Remove close button (added in both modes)
        const closeBtn = pinnedTile.querySelector('.pinned-close-btn');
        if (closeBtn) closeBtn.remove();

        // Quick Access mode: Just clear state, tile was never moved
        if (isQuickAccessMode) {
            pinnedTile = null;
            return;
        }

        // Remove has-pinned class from tile-grid
        const tileGrid = document.querySelector('.tile-grid');
        if (tileGrid) tileGrid.classList.remove('has-pinned');
        // Remove minimize button (only in normal mode)
        const minimizeBtn = pinnedTile.querySelector('.pinned-minimize-btn');
        if (minimizeBtn) minimizeBtn.remove();
        // Restore original background if we stored it
        if (pinnedTile._originalBackground !== undefined) {
            pinnedTile.style.background = pinnedTile._originalBackground;
        }
        // If this is a temporary session tile, remove it completely
        if (pinnedTile._isSessionTile) {
            pinnedTile.remove();
            pinnedTile = null;
            return;
        }
        // Move tile back to original position in tile-grid
        if (pinnedTile._originalParent) {
            if (pinnedTile._originalNextSibling) {
                pinnedTile._originalParent.insertBefore(pinnedTile, pinnedTile._originalNextSibling);
            } else {
                pinnedTile._originalParent.appendChild(pinnedTile);
            }
        }
        pinnedTile = null;
    }
}

/**
 * Create a temporary mini-tile for sessions that don't have a corresponding UI tile.
 * Used when continuing workflow sessions from history.
 */
function createSessionMiniTile(agentName, backend, sessionId) {
    // Format display name
    const displayName = agentName
        .replace('deskagent_', '')
        .replace(/_/g, ' ')
        .split(' ')
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');

    // Create tile element similar to regular tiles
    const tile = document.createElement('div');
    tile.className = 'tile agent session-tile';
    tile.id = 'session-tile-' + sessionId;
    tile._isSessionTile = true;  // Mark as temporary

    // Get backend color class
    const backendLower = backend.toLowerCase();
    let bgColor = 'var(--accent-color)';
    if (backendLower.includes('gemini')) bgColor = '#4285f4';
    else if (backendLower.includes('claude')) bgColor = '#cc785c';
    else if (backendLower.includes('openai')) bgColor = '#10a37f';

    tile.style.background = bgColor;
    tile.style.color = 'white';

    tile.innerHTML = `
        <span class="material-icons tile-icon">smart_toy</span>
        <span class="tile-name">${displayName}</span>
        <span class="backend-badge" style="background: rgba(255,255,255,0.2); color: white; font-size: 10px; padding: 2px 6px; border-radius: 3px; position: absolute; top: 8px; right: 8px;">${backend}</span>
    `;

    // Add to DOM (hidden, pinTile will position it)
    document.body.appendChild(tile);

    return tile;
}

/**
 * Create a temporary workflow mini-tile for history display.
 * Similar to createSessionMiniTile but styled for workflows.
 *
 * @param {string} workflowName - The workflow display name
 * @param {string} sessionId - Session ID for reference
 * @returns {HTMLElement} The created tile element
 */
function createWorkflowMiniTile(workflowName, sessionId) {
    // Remove any existing workflow tile
    const existing = document.querySelector('.session-tile.workflow-tile');
    if (existing) {
        existing.remove();
    }

    // Create tile element
    const tile = document.createElement('div');
    tile.className = 'tile workflow-tile session-tile';
    tile.id = 'workflow-tile-' + (sessionId || 'history');
    tile._isSessionTile = true;

    tile.innerHTML = `
        <span class="material-icons tile-icon">account_tree</span>
        <span class="tile-name">${escapeHtml(workflowName)}</span>
    `;

    // Add to DOM (hidden, pinTile will position it)
    document.body.appendChild(tile);

    return tile;
}

function getPinnedBackground(tile) {
    // Get computed gradient/background from tile for pin animation
    return getComputedStyle(tile).background || '';
}

/**
 * Minimize current task to background.
 * Dismisses the UI but keeps the task running.
 * User can resume via History panel.
 */
function minimizeToBackground() {
    // Get task info before dismissing
    const taskName = pinnedTile ? (pinnedTile.querySelector('.tile-title')?.textContent || 'Task') : 'Task';

    // Dismiss UI without cancelling task
    unpinTile();

    // Hide result panel
    const resultPanel = document.getElementById('resultPanel');
    if (resultPanel) {
        resultPanel.classList.remove('visible');
    }

    // Show tiles again
    showTiles();

    // Hide prompt area
    hidePromptArea();

    // [067] D5: isAppendMode removed - no task viewed after background
    if (typeof currentUserPrompt !== 'undefined') currentUserPrompt = null;
    if (typeof userPromptDisplayed !== 'undefined') userPromptDisplayed = false;

    // Show toast notification
    if (typeof showToast === 'function') {
        showToast(t('ui.task_running_background', {taskName: taskName}));
    }

    serverLog('Minimized task to background: ' + taskName);
}

// =============================================================================
// Prompt Area
// =============================================================================

function showPromptArea(inResultMode = false) {
    const promptArea = document.querySelector('.prompt-area');
    const promptInput = document.getElementById('promptInput');

    if (promptArea) {
        promptArea.classList.remove('hidden');

        if (inResultMode) {
            promptInput.placeholder = t('dialog.response_placeholder');
        } else {
            promptInput.placeholder = t('ui.ask_question');
        }
    }
}

function hidePromptArea() {
    const promptArea = document.querySelector('.prompt-area');
    if (promptArea) {
        promptArea.classList.add('hidden');
    }
}

// =============================================================================
// Unified Processing Overlay (Loading + Thinking modes)
// =============================================================================

// Processing state
let processingState = {
    mode: 'hidden',      // 'hidden' | 'loading' | 'thinking'
    startTime: null,
    toolCount: 0,
    timerInterval: null,
    messageInterval: null,
    messageIndex: 0
};

function formatTime(seconds) {
    if (seconds < 60) return seconds + 's';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
}

/**
 * Show processing overlay in specified mode
 * @param {'loading'|'thinking'} mode - Display mode
 * @param {string} status - Status text (e.g. agent name)
 */
function showProcessingOverlay(mode, status = '') {
    const overlay = document.getElementById('aiProcessingOverlay');
    if (!overlay) return;

    // Reset state
    processingState.mode = mode;
    processingState.startTime = Date.now();
    processingState.toolCount = 0;
    processingState.messageIndex = 0;

    // Update mode attribute (triggers CSS)
    overlay.dataset.mode = mode;

    // Reset UI elements
    const timerEl = document.getElementById('aiProcessingTimer');
    const statusEl = document.getElementById('aiProcessingStatus');
    const textEl = document.getElementById('aiProcessingText');
    const contextEl = document.getElementById('aiProcessingContext');
    const breakdownEl = document.getElementById('aiProcessingBreakdown');
    const toolsEl = document.getElementById('aiProcessingTools');
    const toolsCountEl = document.getElementById('aiProcessingToolsCount');

    if (timerEl) timerEl.textContent = '0s';
    if (statusEl) statusEl.textContent = status;
    const messages = getThinkingMessages();
    if (textEl) textEl.innerHTML = messages[0] + (mode === 'loading' ? '<span class="loading-dots"></span>' : '');
    if (contextEl) contextEl.style.display = 'none';
    if (breakdownEl) breakdownEl.style.display = 'none';
    if (toolsEl) toolsEl.style.display = 'none';
    if (toolsCountEl) toolsCountEl.textContent = '0';

    // For thinking mode, move overlay into result panel
    if (mode === 'thinking') {
        const resultPanel = document.getElementById('resultPanel');
        if (resultPanel && overlay.parentNode !== resultPanel) {
            resultPanel.insertBefore(overlay, resultPanel.firstChild);
        }
    } else {
        // For loading mode, ensure overlay is in main
        const main = document.querySelector('main');
        if (main && overlay.parentNode !== main) {
            // Insert before result panel
            const resultPanel = document.getElementById('resultPanel');
            if (resultPanel) {
                main.insertBefore(overlay, resultPanel);
            } else {
                main.appendChild(overlay);
            }
        }
    }

    // Start intervals
    startProcessingIntervals();

    // Handle UI state for loading mode
    if (mode === 'loading') {
        activeTaskCount++;
        // Quick Access mode: Keep tiles visible, only show overlay on pinned tile
        if (!isQuickAccessMode) {
            document.querySelector('.tile-grid')?.classList.add('hidden');
        }
        hidePromptArea();
    }
}

/**
 * Hide processing overlay
 */
function hideProcessingOverlay() {
    const overlay = document.getElementById('aiProcessingOverlay');
    if (overlay) {
        // [070] Log who hides thinking overlay (to system.log for debugging)
        if (overlay.dataset.mode === 'thinking') {
            const caller = new Error().stack.split('\n').slice(1, 4).join(' <- ');
            serverLog('[OVERLAY] Thinking overlay hidden! Caller: ' + caller);
        }
        overlay.dataset.mode = 'hidden';
    }

    // Stop intervals
    stopProcessingIntervals();

    // Update state
    if (processingState.mode === 'loading') {
        activeTaskCount = Math.max(0, activeTaskCount - 1);
    }
    processingState.mode = 'hidden';
}

function startProcessingIntervals() {
    stopProcessingIntervals(); // Clear existing

    processingState.timerInterval = setInterval(updateProcessingTimer, 1000);
    processingState.messageInterval = setInterval(rotateProcessingMessage, 3000);
}

function stopProcessingIntervals() {
    if (processingState.timerInterval) {
        clearInterval(processingState.timerInterval);
        processingState.timerInterval = null;
    }
    if (processingState.messageInterval) {
        clearInterval(processingState.messageInterval);
        processingState.messageInterval = null;
    }
}

function updateProcessingTimer() {
    if (!processingState.startTime) return;
    const elapsed = Math.floor((Date.now() - processingState.startTime) / 1000);
    const timerEl = document.getElementById('aiProcessingTimer');
    if (timerEl) timerEl.textContent = formatTime(elapsed);
}

function rotateProcessingMessage() {
    const messages = getThinkingMessages();
    processingState.messageIndex = (processingState.messageIndex + 1) % messages.length;
    const textEl = document.getElementById('aiProcessingText');
    if (textEl) {
        textEl.innerHTML = messages[processingState.messageIndex] +
            (processingState.mode === 'loading' ? '<span class="loading-dots"></span>' : '');
    }
}

/**
 * Update context display (works in both modes)
 */
function updateProcessingContext(contextStr, breakdownStr = '') {
    if (processingState.mode === 'hidden') return;

    const contextEl = document.getElementById('aiProcessingContext');
    const contextVal = document.getElementById('aiProcessingContextValue');
    const breakdownEl = document.getElementById('aiProcessingBreakdown');

    if (contextEl && contextVal && contextStr) {
        contextEl.style.display = 'flex';
        contextVal.textContent = contextStr;
    }

    if (breakdownEl && breakdownStr) {
        breakdownEl.style.display = 'block';
        breakdownEl.textContent = breakdownStr;
    }
}

/**
 * Increment tool counter (works in both modes)
 */
function incrementProcessingToolCount() {
    if (processingState.mode === 'hidden') return;

    processingState.toolCount++;
    const toolsEl = document.getElementById('aiProcessingTools');
    const countEl = document.getElementById('aiProcessingToolsCount');

    if (toolsEl && countEl) {
        toolsEl.style.display = 'flex';
        countEl.textContent = processingState.toolCount;
    }
}

// =============================================================================
// Backwards Compatibility Aliases
// =============================================================================

// Legacy: setLoading -> showProcessingOverlay('loading')
function setLoading(loading, name = '') {
    if (loading) {
        showProcessingOverlay('loading', name);
    } else {
        hideProcessingOverlay();
    }
}

// Legacy: showThinkingOverlay -> showProcessingOverlay('thinking')
function showThinkingOverlay(show, status = '') {
    if (show) {
        showProcessingOverlay('thinking', status);
    } else {
        hideProcessingOverlay();
    }
}

// Legacy timer references (for backwards compatibility with global vars)
function updateLoadingTimer() {
    updateProcessingTimer();
}

function updateThinkingTimer() {
    updateProcessingTimer();
}

// Legacy status update
function updateThinkingStatus(status, context = '') {
    const statusEl = document.getElementById('aiProcessingStatus');
    if (statusEl && status) statusEl.textContent = status;
    if (context) updateProcessingContext(context);
}

// Legacy context update
function updateThinkingContext(contextStr, breakdownStr = '') {
    updateProcessingContext(contextStr, breakdownStr);
}

// Legacy tool count
function updateThinkingToolCount(count) {
    processingState.toolCount = count;
    const toolsEl = document.getElementById('aiProcessingTools');
    const countEl = document.getElementById('aiProcessingToolsCount');
    if (toolsEl && countEl) {
        toolsEl.style.display = 'flex';
        countEl.textContent = count;
    }
}

function incrementThinkingToolCount() {
    incrementProcessingToolCount();
}

// Tool history for display
let toolHistory = [];
const MAX_TOOL_HISTORY = 5;

// Shorten tool name for display
function shortenToolName(toolName) {
    if (!toolName) return '';
    // Remove MCP prefix (e.g., "mcp__janitza_janitza__janitza_get_projects" → "get_projects")
    let name = toolName;
    if (name.includes('__')) {
        const parts = name.split('__');
        name = parts[parts.length - 1];
    }
    // Further shorten (e.g., "janitza_get_projects" → "get_projects")
    if (name.includes('_')) {
        const parts = name.split('_');
        if (parts.length > 2) {
            name = parts.slice(1).join('_');
        }
    }
    return name;
}

// Update tool call display with current tool name and details
function updateLoadingToolCall(toolName, status, duration, argsPreview, resultPreview) {
    const currentToolEl = document.getElementById('aiProcessingCurrentTool');
    const historyEl = document.getElementById('aiProcessingToolHistory');
    const displayName = shortenToolName(toolName);

    if (status === 'executing') {
        // Show current tool name with args preview
        if (currentToolEl) {
            let text = `→ ${displayName}`;
            if (argsPreview) {
                // Show short args preview
                const shortArgs = argsPreview.length > 40 ? argsPreview.slice(0, 40) + '...' : argsPreview;
                text += ` (${shortArgs})`;
            }
            currentToolEl.textContent = text;
            currentToolEl.title = argsPreview || '';
            currentToolEl.style.display = 'inline';
        }
    } else if (status === 'complete') {
        incrementProcessingToolCount();

        // Add to history
        const durationStr = duration ? `${duration.toFixed(1)}s` : '';
        toolHistory.unshift({ name: displayName, duration: durationStr, result: resultPreview });
        if (toolHistory.length > MAX_TOOL_HISTORY) {
            toolHistory.pop();
        }

        // Update history display
        if (historyEl) {
            historyEl.innerHTML = toolHistory.map(t =>
                `<span class="tool-history-item" title="${t.result || ''}">✓ ${t.name}${t.duration ? ' (' + t.duration + ')' : ''}</span>`
            ).join('');
            historyEl.style.display = 'block';
        }

        // Clear current tool
        if (currentToolEl) {
            currentToolEl.textContent = '';
        }
    }
}

// Reset tool history when starting new task
function resetToolHistory() {
    toolHistory = [];
    const historyEl = document.getElementById('aiProcessingToolHistory');
    if (historyEl) {
        historyEl.innerHTML = '';
        historyEl.style.display = 'none';
    }
}

/**
 * Reset processing tool counter (called when loading starts)
 */
function resetLoadingToolDisplay() {
    processingState.toolCount = 0;
    const countEl = document.getElementById('aiProcessingTools');
    if (countEl) countEl.style.display = 'none';
}

// =============================================================================
// Message Rotation (Loading & Thinking)
// =============================================================================

// Rotating fun messages for thinking overlay - uses translation keys
function getThinkingMessages() {
    return [
        t('thinking.thinking'),
        t('thinking.processing_data'),
        t('thinking.gathering_ideas'),
        t('thinking.almost_done'),
        t('thinking.working_hard'),
        t('thinking.magic_happening'),
        t('thinking.asking_ai_gods'),
        t('thinking.neurons_firing'),
        t('thinking.one_moment'),
        t('thinking.deep_in_thought'),
        t('thinking.calculating'),
        t('thinking.generating_brilliance'),
        t('thinking.hang_in_there'),
        t('thinking.ai_at_work'),
        t('thinking.getting_it_done')
    ];
}
// Keep a reference for backwards compatibility
let thinkingMessages = null;
let thinkingMessageIndex = 0;
let thinkingMessageInterval = null;
let loadingMessageInterval = null;

function rotateLoadingMessage() {
    const textEl = document.getElementById('aiProcessingText');
    if (textEl) {
        const messages = getThinkingMessages();
        thinkingMessageIndex = (thinkingMessageIndex + 1) % messages.length;
        textEl.innerHTML = messages[thinkingMessageIndex] + '<span class="loading-dots"></span>';
    }
}

function rotateThinkingMessage() {
    const textEl = document.getElementById('thinkingText');
    if (textEl) {
        const messages = getThinkingMessages();
        thinkingMessageIndex = (thinkingMessageIndex + 1) % messages.length;
        textEl.textContent = messages[thinkingMessageIndex];
    }
}

// Marketing slogans for header (rotate after task completion) - uses translation keys
function getHeaderSlogans() {
    return [
        t('slogan.desktop_agent'),
        t('slogan.ai_workflow'),
        t('slogan.less_clicks'),
        t('slogan.intelligent_assistant'),
        t('slogan.automate_day'),
        t('slogan.productivity_reimagined'),
        t('slogan.work_simple_done'),
        t('slogan.ai_power'),
        t('slogan.workflow_supercharged'),
        t('slogan.intelligence_on_demand'),
        t('slogan.work_smarter'),
        t('slogan.save_time')
    ];
}
let sloganIndex = 0;

function rotateSlogan() {
    const sloganEl = document.getElementById('headerSlogan');
    if (sloganEl) {
        sloganEl.classList.add('fade');
        setTimeout(() => {
            const slogans = getHeaderSlogans();
            sloganIndex = (sloganIndex + 1) % slogans.length;
            sloganEl.textContent = slogans[sloganIndex];
            sloganEl.classList.remove('fade');
        }, 300);
    }
}

// =============================================================================
// System Panel (Developer Mode)
// =============================================================================

let currentTestTaskId = null;
let testPollInterval = null;
let contextPollInterval = null;  // For live context updates during agent execution

// Store last context for debugging
let lastContext = {
    systemPrompt: '',
    userPrompt: '',
    toolResults: [],
    systemTokens: 0,
    userTokens: 0,
    toolTokens: 0,
    totalTokens: 0,
    limit: 200000,
    iteration: 0,
    maxIterations: 0,
    anonymization: {}  // {placeholder: original} mappings
};

function openSystemPanel() {
    document.getElementById('tileGrid').classList.add('hidden');
    document.getElementById('systemPanel').classList.remove('hidden');
    // Update badge icon to show panel is open
    document.getElementById('systemBadgeIcon').textContent = 'close';
    // Load system info
    loadSystemInfo();
    // Update context display
    updateContextDisplay();
}

function closeSystemPanel() {
    document.getElementById('systemPanel').classList.add('hidden');
    document.getElementById('tileGrid').classList.remove('hidden');
    // Reset badge icon
    document.getElementById('systemBadgeIcon').textContent = 'smart_toy';
    if (testPollInterval) {
        clearInterval(testPollInterval);
        testPollInterval = null;
    }
    stopContextPolling();
}

function switchSystemTab(tab) {
    // Update tab buttons
    document.querySelectorAll('.system-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('sysTab' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.add('active');

    // Update tab content
    document.querySelectorAll('.system-tab-content').forEach(c => c.classList.add('hidden'));
    document.getElementById('sysContent' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.remove('hidden');

    // Update badge icon based on tab
    const icons = { overview: 'dashboard', tests: 'science', context: 'code', logs: 'article' };
    document.getElementById('systemBadgeIcon').textContent = icons[tab] || 'smart_toy';

    // Tab-specific actions
    if (tab === 'tests') {
        document.getElementById('testStatus').textContent = t('tests.select_scope');
        document.getElementById('testSummary').classList.add('hidden');
        document.getElementById('testProgress').classList.add('hidden');
        document.getElementById('testOutput').textContent = '';
    } else if (tab === 'logs') {
        refreshLogs();
    }
}

async function loadSystemInfo() {
    try {
        const res = await fetch(`${API}/system/info`);
        if (res.ok) {
            const info = await res.json();
            const versionText = info.build ? `${info.version} (build ${info.build})` : info.version || '-';
            document.getElementById('sysVersion').textContent = versionText;
            document.getElementById('sysUptime').textContent = info.uptime || '-';
            document.getElementById('sysPython').textContent = info.python || '-';
            document.getElementById('sysCostToday').textContent = info.cost_today || '$0.00';
            document.getElementById('sysCostMonth').textContent = info.cost_month || '$0.00';
            document.getElementById('sysCostTotal').textContent = info.cost_total || '$0.00';
        }
    } catch (e) {
        console.error('[System] Failed to load info:', e);
    }
}

async function refreshLogs() {
    const systemOutput = document.getElementById('logsSystemOutput');
    const agentOutput = document.getElementById('logsAgentOutput');
    const anonOutput = document.getElementById('logsAnonOutput');

    try {
        const res = await fetch(`${API}/system/logs`);
        if (res.ok) {
            const data = await res.json();

            if (systemOutput) {
                systemOutput.textContent = data.system || t('logs.no_logs');
                systemOutput.scrollTop = systemOutput.scrollHeight;
            }

            if (agentOutput) {
                agentOutput.textContent = data.agent || t('logs.no_agent_log');
            }

            if (anonOutput) {
                anonOutput.textContent = data.anon || t('logs.no_anon_log');
            }
        }
    } catch (e) {
        if (systemOutput) systemOutput.textContent = t('logs.error_loading');
        if (agentOutput) agentOutput.textContent = t('logs.error_loading');
        if (anonOutput) anonOutput.textContent = t('logs.error_loading');
    }
}

function switchLogsSubTab(tab) {
    // Remove active class from all sub-tabs
    document.querySelectorAll('.logs-subtab').forEach(t => t.classList.remove('active'));

    // Add active class to clicked sub-tab
    const subtabId = 'logsSubtab' + tab.charAt(0).toUpperCase() + tab.slice(1);
    const subtab = document.getElementById(subtabId);
    if (subtab) subtab.classList.add('active');

    // Hide all sub-tab content
    document.querySelectorAll('.logs-subtab-content').forEach(c => c.classList.add('hidden'));

    // Show selected content
    const contentId = 'logsContent' + tab.charAt(0).toUpperCase() + tab.slice(1);
    const content = document.getElementById(contentId);
    if (content) content.classList.remove('hidden');

    // Load data for specific sub-tabs
    if (tab === 'context') {
        updateSettingsContextTab();
    }
}

async function reloadConfig() {
    try {
        const res = await fetch(`${API}/system/reload`, { method: 'POST' });
        if (res.ok) {
            alert(t('config.reloaded'));
            location.reload();
        }
    } catch (e) {
        alert(t('config.reload_error'));
    }
}

function openLogFile(logType) {
    // If logType specified, open specific log; otherwise open logs folder
    if (logType) {
        fetch(`${API}/system/open-log/${logType}`, { method: 'POST' });
    } else {
        fetch(`${API}/system/open-logs`, { method: 'POST' });
    }
}

// Legacy aliases for compatibility
function openDevPanel() { openSystemPanel(); }
function closeDevPanel() { closeSystemPanel(); }

// =============================================================================
// Context Polling (Live Stats)
// =============================================================================

function startContextPolling() {
    // Only start if not already polling
    if (contextPollInterval) return;

    // Poll every 2 seconds - always update stats bar, optionally update dev panel
    contextPollInterval = setInterval(async () => {
        // Fetch context and update stats bar (always)
        await fetchAndUpdateContext();
    }, 2000);
    console.log('[DevPanel] Context polling started');
}

function maybeStartContextPolling() {
    // Start context polling if system panel is open or during task execution
    if (currentTaskId) {
        startContextPolling();
    }
}

async function fetchAndUpdateContext() {
    // Fetch latest context from server
    try {
        const res = await fetch(`${API}/dev/context`);
        if (res.ok) {
            const data = await res.json();
            // Update local context from server data
            lastContext.systemPrompt = data.system_prompt || '';
            lastContext.userPrompt = data.user_prompt || '';
            lastContext.toolResults = (data.tool_results || []).map(t => `[${t.tool}]\n${t.result}`);
            lastContext.systemTokens = estimateTokens(lastContext.systemPrompt);
            lastContext.userTokens = estimateTokens(lastContext.userPrompt);
            lastContext.toolTokens = lastContext.toolResults.reduce((sum, r) => sum + estimateTokens(r), 0);
            lastContext.totalTokens = lastContext.systemTokens + lastContext.userTokens + lastContext.toolTokens;

            // Set limit based on model
            const model = (data.model || '').toLowerCase();
            if (model.includes('gemini')) {
                lastContext.limit = 1000000;
            } else if (model.includes('qwen') || model.includes('mistral')) {
                lastContext.limit = 32000;
            } else {
                lastContext.limit = 200000;
            }

            // Always update stats bar
            updateContextStatBar();

            // Always update dev panel content (so it's ready when tab is opened)
            updateContextDevPanel();

            console.log('[DevPanel] Context fetched:', {
                systemLen: lastContext.systemPrompt.length,
                userLen: lastContext.userPrompt.length,
                toolCount: lastContext.toolResults.length,
                model: data.model
            });
        } else {
            console.log('[DevPanel] Context fetch failed:', res.status);
        }
    } catch (e) {
        console.log('[DevPanel] Could not fetch context:', e);
    }
}

// Helper: Only update element if value changed (prevents flickering)
function setIfChanged(el, value) {
    if (el && el.textContent !== value) {
        el.textContent = value;
    }
}

function updateContextDevPanel() {
    // Update Developer Panel UI (only if values changed to prevent flickering)
    setIfChanged(document.getElementById('ctxSystemPrompt'), lastContext.systemPrompt || t('context.no_context'));
    setIfChanged(document.getElementById('ctxUserPrompt'), lastContext.userPrompt || '-');
    setIfChanged(document.getElementById('ctxToolResults'), lastContext.toolResults.length > 0
        ? lastContext.toolResults.join('\n\n---\n\n')
        : '-');

    setIfChanged(document.getElementById('ctxSystemTokens'), formatTokens(lastContext.systemTokens));
    setIfChanged(document.getElementById('ctxUserTokens'), formatTokens(lastContext.userTokens));
    setIfChanged(document.getElementById('ctxToolTokens'), formatTokens(lastContext.toolTokens));
    setIfChanged(document.getElementById('ctxTotalTokens'), formatTokens(lastContext.totalTokens) +
        ' (' + (lastContext.totalTokens / lastContext.limit * 100).toFixed(1) + '%)');
    setIfChanged(document.getElementById('ctxLimit'), formatTokens(lastContext.limit));

    // Update Anonymization section
    const anonSection = document.getElementById('ctxAnonymizationSection');
    const anonContent = document.getElementById('ctxAnonymization');
    const anonCount = document.getElementById('ctxAnonymizationCount');
    const anonMappings = lastContext.anonymization || {};
    const mappingCount = Object.keys(anonMappings).length;

    if (anonSection && anonContent) {
        if (mappingCount > 0) {
            anonSection.style.display = 'block';
            if (anonCount) anonCount.textContent = mappingCount;
            // Format mappings as table-like display
            let html = '<div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 12px;">';
            for (const [placeholder, original] of Object.entries(anonMappings)) {
                html += `<span style="color: var(--status-warning); font-weight: 500;">${escapeHtml(placeholder)}</span>`;
                html += `<span style="color: var(--text-muted);">← ${escapeHtml(original)}</span>`;
            }
            html += '</div>';
            anonContent.innerHTML = html;
        } else {
            anonSection.style.display = 'none';
        }
    }
}

function stopContextPolling() {
    if (contextPollInterval) {
        clearInterval(contextPollInterval);
        contextPollInterval = null;
        console.log('[DevPanel] Context polling stopped');
    }
}

// Update context from task status response (centralized - no separate API call needed)
function updateDevContextFromTask(devContext) {
    if (!devContext) return;

    // Update lastContext from task data
    lastContext.systemPrompt = devContext.system_prompt || '';
    lastContext.userPrompt = devContext.user_prompt || '';
    lastContext.toolResults = (devContext.tool_results || []).map(t => `[${t.tool}]\n${t.result}`);
    lastContext.systemTokens = estimateTokens(lastContext.systemPrompt);
    lastContext.userTokens = estimateTokens(lastContext.userPrompt);
    lastContext.toolTokens = lastContext.toolResults.reduce((sum, r) => sum + estimateTokens(r), 0);
    lastContext.totalTokens = lastContext.systemTokens + lastContext.userTokens + lastContext.toolTokens;
    lastContext.iteration = devContext.iteration || 0;
    lastContext.maxIterations = devContext.max_iterations || 0;
    lastContext.anonymization = devContext.anonymization || {};

    // Set limit based on model
    const model = (devContext.model || '').toLowerCase();
    if (model.includes('gemini')) {
        lastContext.limit = 1000000;
    } else if (model.includes('qwen') || model.includes('mistral')) {
        lastContext.limit = 32000;
    } else {
        lastContext.limit = 200000;
    }

    // Update processing overlay context display (only if changed to prevent flickering)
    const processingCtx = document.getElementById('aiProcessingContext');
    const processingCtxVal = document.getElementById('aiProcessingContextValue');

    // Build context string - show iteration info even without token data
    let contextStr = '';
    if (lastContext.totalTokens > 0) {
        const percent = (lastContext.totalTokens / lastContext.limit * 100).toFixed(1);
        contextStr = `Context: ${formatTokens(lastContext.totalTokens)} (${percent}%) | Sys: ${formatTokens(lastContext.systemTokens)} | User: ${formatTokens(lastContext.userTokens)} | Tools: ${formatTokens(lastContext.toolTokens)}`;
    }
    if (lastContext.iteration > 0 && lastContext.maxIterations > 0) {
        if (contextStr) {
            contextStr += ` | Step ${lastContext.iteration}/${lastContext.maxIterations}`;
        } else {
            contextStr = `Step ${lastContext.iteration}/${lastContext.maxIterations}`;
        }
    }

    // Show if we have any info (tokens OR iteration)
    if (processingCtx && processingCtxVal && contextStr) {
        if (processingCtx.style.display === 'none') processingCtx.style.display = '';
        setIfChanged(processingCtxVal, contextStr.replace('Context: ', ''));
    }

    // Update context in thinking mode (append mode)
    if (isAppendMode && contextStr && processingState.mode === 'thinking') {
        const mainContext = `${formatTokens(lastContext.totalTokens)} / ${formatTokens(lastContext.limit)} (${(lastContext.totalTokens / lastContext.limit * 100).toFixed(1)}%)`;
        const breakdown = `System: ${formatTokens(lastContext.systemTokens)} · Prompt: ${formatTokens(lastContext.userTokens)} · Tools: ${formatTokens(lastContext.toolTokens)}`;
        updateProcessingContext(mainContext, breakdown);
    }

    // Update stats bar
    updateContextStatBar();

    // Update dev panel if visible
    updateContextDevPanel();
}

// Legacy alias for backwards compatibility
function openTestRunner() { openDevPanel(); }
function closeTestPanel() { closeDevPanel(); }

function switchDevTab(tab) {
    // Update tab buttons
    document.querySelectorAll('.dev-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.add('active');

    // Update tab content
    document.querySelectorAll('.dev-tab-content').forEach(c => c.classList.add('hidden'));
    document.getElementById('tabContent' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.remove('hidden');

    // Manage context polling based on tab
    if (tab === 'context') {
        updateContextDisplay();
        // Start live polling if a task is running
        if (currentTaskId) {
            startContextPolling();
        }
    } else {
        // Stop polling when leaving context tab
        stopContextPolling();
    }
}

async function updateContextDisplay() {
    // Delegate to fetchAndUpdateContext which updates both stats bar and dev panel
    await fetchAndUpdateContext();
}

function updateContextStatBar() {
    const container = document.getElementById('statContextContainer');
    const statEl = document.getElementById('statContext');
    if (!container || !statEl) return;

    // Show context stat if we have data (only update if changed to prevent flickering)
    if (lastContext.totalTokens > 0) {
        if (container.style.display === 'none') container.style.display = '';
        const percent = (lastContext.totalTokens / lastContext.limit * 100).toFixed(1);
        const newText = `${formatTokens(lastContext.totalTokens)} / ${formatTokens(lastContext.limit)} (${percent}%)`;
        const newTitle = `System: ${formatTokens(lastContext.systemTokens)}\nUser: ${formatTokens(lastContext.userTokens)}\nTools: ${formatTokens(lastContext.toolTokens)}`;
        setIfChanged(statEl, newText);
        if (statEl.title !== newTitle) statEl.title = newTitle;
    } else if (container.style.display !== 'none') {
        container.style.display = 'none';
    }
}

function formatTokens(tokens) {
    if (tokens >= 1000) return (tokens / 1000).toFixed(1) + 'K';
    return tokens.toString();
}

function estimateTokens(text) {
    if (!text) return 0;
    return Math.floor(text.length / 3.5);
}

function captureContext(systemPrompt, userPrompt, model = 'claude') {
    lastContext.systemPrompt = systemPrompt;
    lastContext.userPrompt = userPrompt;
    lastContext.toolResults = [];
    lastContext.systemTokens = estimateTokens(systemPrompt);
    lastContext.userTokens = estimateTokens(userPrompt);
    lastContext.toolTokens = 0;
    lastContext.totalTokens = lastContext.systemTokens + lastContext.userTokens;

    // Set limit based on model
    if (model.toLowerCase().includes('gemini')) {
        lastContext.limit = 1000000;
    } else if (model.toLowerCase().includes('qwen') || model.toLowerCase().includes('mistral')) {
        lastContext.limit = 32000;
    } else {
        lastContext.limit = 200000;
    }
}

function addToolResult(toolName, result) {
    const entry = `[${toolName}]\n${result}`;
    lastContext.toolResults.push(entry);
    const tokens = estimateTokens(result);
    lastContext.toolTokens += tokens;
    lastContext.totalTokens = lastContext.systemTokens + lastContext.userTokens + lastContext.toolTokens;
}

async function copyContext(type) {
    let text = '';
    switch(type) {
        case 'system':
            text = lastContext.systemPrompt;
            break;
        case 'user':
            text = lastContext.userPrompt;
            break;
        case 'all':
            text = `=== SYSTEM PROMPT ===\n${lastContext.systemPrompt}\n\n=== USER PROMPT ===\n${lastContext.userPrompt}\n\n=== TOOL RESULTS ===\n${lastContext.toolResults.join('\n\n---\n\n')}`;
            break;
    }
    try {
        await navigator.clipboard.writeText(text);
        showSnackbar(t('ui.copied_to_clipboard'));
    } catch (e) {
        console.error('Copy failed:', e);
    }
}

// =============================================================================
// Testing Functions
// =============================================================================

// Helper to get test elements (settings panel only)
function getTestElements() {
    return {
        status: document.getElementById('testStatusSettings'),
        progress: document.getElementById('testProgressSettings'),
        progressText: document.getElementById('testProgressTextSettings'),
        progressFill: document.getElementById('testProgressFillSettings'),
        output: document.getElementById('testOutputSettings'),
        summary: document.getElementById('testSummarySettings'),
        passed: document.getElementById('testPassedSettings'),
        failed: document.getElementById('testFailedSettings'),
        skipped: document.getElementById('testSkippedSettings'),
        duration: document.getElementById('testDurationSettings')
    };
}

async function runTests(scope) {
    // Disable buttons
    document.querySelectorAll('.test-btn, .settings-btn').forEach(btn => {
        if (btn.onclick && btn.onclick.toString().includes('runTests')) {
            btn.disabled = true;
        }
    });

    const els = getTestElements();
    if (!els.status) {
        console.error('Test elements not found');
        return;
    }

    els.status.textContent = t('tests.starting', {scope: scope});
    els.progress.classList.remove('hidden');
    els.progressText.textContent = t('tests.initializing');
    els.output.textContent = '';
    els.summary.classList.add('hidden');

    try {
        const res = await fetch(`${API}/tests/run?scope=${scope}`);
        const data = await res.json();

        if (data.task_id) {
            currentTestTaskId = data.task_id;
            els.progressText.textContent = t('tests.running');
            pollTestStatus();
        } else {
            els.status.textContent = t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error'));
            els.progress.classList.add('hidden');
            document.querySelectorAll('.test-btn, .settings-btn').forEach(btn => btn.disabled = false);
        }
    } catch (e) {
        els.status.textContent = t('task.connection_error') + ' ' + e.message;
        els.progress.classList.add('hidden');
        document.querySelectorAll('.test-btn, .settings-btn').forEach(btn => btn.disabled = false);
    }
}

function pollTestStatus() {
    if (testPollInterval) clearInterval(testPollInterval);

    testPollInterval = setInterval(async () => {
        if (!currentTestTaskId) return;

        try {
            const res = await fetch(`${API}/tests/status/${currentTestTaskId}`);
            const data = await res.json();

            const els = getTestElements();
            if (!els.status) return;

            // Update output if available
            if (data.output && els.output) {
                els.output.textContent = data.output;
                els.output.scrollTop = els.output.scrollHeight;
            }

            if (data.status === 'running') {
                els.progressText.textContent = t('tests.running');
            } else if (data.status === 'done' || data.status === 'failed') {
                clearInterval(testPollInterval);
                testPollInterval = null;

                els.progress.classList.add('hidden');
                els.status.textContent = data.status === 'done' ? '✅ ' + t('tests.completed') : '❌ ' + t('tests.failed');

                // Show summary
                els.summary.classList.remove('hidden');
                els.passed.textContent = t('tests.passed', {count: data.passed || 0});
                els.passed.className = data.passed > 0 ? 'passed success' : 'passed';
                els.failed.textContent = t('tests.failed_count', {count: data.failed || 0});
                els.failed.className = data.failed > 0 ? 'failed error' : 'failed';
                els.skipped.textContent = t('tests.skipped', {count: data.skipped || 0});
                els.duration.textContent = `${data.duration || 0}s`;

                document.querySelectorAll('.test-btn, .settings-btn').forEach(btn => btn.disabled = false);
            } else if (data.status === 'timeout' || data.status === 'error') {
                clearInterval(testPollInterval);
                testPollInterval = null;

                els.progress.classList.add('hidden');
                els.status.textContent = '❌ ' + (data.error || t('task.error'));
                document.querySelectorAll('.test-btn, .settings-btn').forEach(btn => btn.disabled = false);
            }
        } catch (e) {
            console.error('Poll test status failed:', e);
        }
    }, 1000);
}

// =============================================================================
// Watcher Panel (Email Watchers/Scheduler)
// =============================================================================

let watcherState = null;
let watcherPollInterval = null;

async function loadWatcherStatus() {
    try {
        const res = await fetch(API + '/watchers');
        if (res.ok) {
            watcherState = await res.json();
            updateWatcherBadge();
            updateWatcherPanel();
        }
    } catch (e) {
        console.warn('Could not load watcher status:', e);
    }
}

function updateWatcherBadge() {
    const badge = document.getElementById('watcherBadge');
    const icon = document.getElementById('watcherIcon');
    const status = document.getElementById('watcherStatus');
    const count = document.getElementById('watcherCount');

    if (!watcherState || !badge) return;

    badge.classList.remove('active', 'paused', 'error');

    if (watcherState.enabled && watcherState.running) {
        badge.classList.add('active');
        icon.textContent = 'timer';
        status.textContent = t('watcher.status_active');

        if (watcherState.stats && watcherState.stats.processed_today > 0) {
            count.textContent = watcherState.stats.processed_today;
            count.style.display = 'inline';
        } else {
            count.style.display = 'none';
        }
    } else if (watcherState.enabled) {
        badge.classList.add('paused');
        icon.textContent = 'pause_circle';
        status.textContent = t('watcher.status_paused');
        count.style.display = 'none';
    } else {
        icon.textContent = 'schedule';
        status.textContent = t('scheduler.title');
        count.style.display = 'none';
    }

    // Update tooltip
    let tooltip = `${t('scheduler.title')}\n`;
    tooltip += `${t('scheduler.status')} ${watcherState.running ? t('watcher.status_active') : t('watcher.status_off')}\n`;
    if (watcherState.stats) {
        tooltip += `${t('watcher.processed_today', {count: watcherState.stats.processed_today || 0})}\n`;
        tooltip += `${t('watcher.actions_today', {count: watcherState.stats.actions_today || 0})}\n`;
    }
    if (watcherState.last_check) {
        tooltip += t('watcher.last_check_time', {time: new Date(watcherState.last_check).toLocaleTimeString()});
    }
    badge.title = tooltip;
}

function updateWatcherPanel() {
    if (!watcherState) return;

    // Update stats
    document.getElementById('watcherRunningStatus').textContent =
        watcherState.running ? '✅ ' + t('watcher.status_active') : (watcherState.enabled ? '⏸️ ' + t('watcher.status_paused') : '❌ ' + t('watcher.status_off'));

    if (watcherState.stats) {
        document.getElementById('watcherProcessed').textContent = watcherState.stats.processed_today || 0;
        document.getElementById('watcherActions').textContent = watcherState.stats.actions_today || 0;
    }

    if (watcherState.last_check) {
        document.getElementById('watcherLastCheck').textContent =
            new Date(watcherState.last_check).toLocaleTimeString();
    } else {
        document.getElementById('watcherLastCheck').textContent = '-';
    }

    if (watcherState.next_check_in !== null && watcherState.next_check_in !== undefined) {
        document.getElementById('watcherNextCheck').textContent = `in ${watcherState.next_check_in}s`;
    } else {
        document.getElementById('watcherNextCheck').textContent = '-';
    }

    // Update toggle button icon
    const toggleIcon = document.getElementById('watcherToggleIcon');
    if (toggleIcon) {
        toggleIcon.textContent = watcherState.running ? 'pause' : 'play_arrow';
    }

    // Update activity log
    renderWatcherLog(watcherState.recent_actions || []);
}

function renderWatcherLog(log) {
    const container = document.getElementById('watcherLog');
    if (!log || log.length === 0) {
        container.innerHTML = '<div class="watcher-empty-state">' + t('scheduler.no_activity') + '</div>';
        return;
    }

    container.innerHTML = log.map(item => {
        const actionIcons = {
            'move_to_folder': '📁',
            'flag': '🚩',
            'delete': '🗑️',
            'trigger_agent': '🤖'
        };
        const icon = actionIcons[item.action] || '📧';

        return `<div class="watcher-action-item">
            <span class="watcher-action-time">${item.time || ''}</span>
            <span class="watcher-action-icon">${icon}</span>
            <span class="watcher-action-desc">
                <strong>${item.email || ''}</strong>
                <span class="watcher-action-result">${item.result || ''}</span>
            </span>
        </div>`;
    }).join('');
}

function toggleWatcherPanel() {
    const panel = document.getElementById('watcherPanel');
    if (panel.classList.contains('visible')) {
        panel.classList.remove('visible');
    } else {
        loadWatcherStatus();
        panel.classList.add('visible');
    }
}

async function toggleWatcher() {
    try {
        const res = await fetch(API + '/watchers/toggle', { method: 'POST' });
        if (res.ok) {
            await loadWatcherStatus();
        }
    } catch (e) {
        console.error('Toggle watcher failed:', e);
    }
}

async function checkNow() {
    const btn = document.querySelector('.watcher-check-btn');
    if (btn) {
        btn.disabled = true;
        btn.querySelector('.material-icons').classList.add('spinning');
    }

    try {
        const res = await fetch(API + '/watchers/check-now', { method: 'POST' });
        if (res.ok) {
            await loadWatcherStatus();
        }
    } catch (e) {
        console.error('Check now failed:', e);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.querySelector('.material-icons').classList.remove('spinning');
        }
    }
}

// =============================================================================
// User Preferences (persistent in workspace/.state/preferences.json)
// =============================================================================

/**
 * Load user preferences from server and apply them.
 * Called on page load.
 */
async function loadPreferences() {
    try {
        const res = await fetch(API + '/preferences');
        if (!res.ok) return;
        const prefs = await res.json();

        // Load pinned agents and apply to tiles
        if (prefs.ui?.pinned_agents) {
            try {
                const pinned = JSON.parse(prefs.ui.pinned_agents);
                pinnedAgents = new Set(pinned);
                applyPinnedStatesToTiles();
            } catch (e) {
                serverLog('[Preferences] Error parsing pinned_agents: ' + e.message);
            }
        }

        // Apply category preference (use setTimeout to ensure all initializations are complete)
        if (prefs.ui?.selected_category) {
            setTimeout(() => {
                filterByCategory(prefs.ui.selected_category, false);  // false = don't save back
                serverLog('[Preferences] Applied category filter: ' + prefs.ui.selected_category);
            }, 200);
        }

        // Restore settings panel if requested (after language change)
        if (prefs.ui?._restore_settings && prefs.ui._restore_settings !== '') {
            const tabToRestore = prefs.ui._restore_settings;
            // Clear the restore flag FIRST (awaited to ensure it's saved)
            await savePreference('ui._restore_settings', '');
            // Open settings panel and switch to the correct tab
            setTimeout(() => {
                openSettings();
                const tab = document.querySelector(`[data-tab="${tabToRestore}"]`);
                if (tab) tab.click();
            }, 100);
        }

        serverLog('[Preferences] Loaded: ' + JSON.stringify(prefs));
    } catch (e) {
        serverLog('[Preferences] Error loading: ' + e.message);
    }
}

/**
 * Save a single preference to server.
 * @param {string} key - Dot-notation key, e.g. "ui.selected_category"
 * @param {string} value - Value to save
 */
async function savePreference(key, value) {
    try {
        await fetch(API + '/preferences', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value})
        });
        serverLog('[Preferences] Saved: ' + key + ' = ' + value);
    } catch (e) {
        serverLog('[Preferences] Error saving: ' + e.message);
    }
}

// =============================================================================
// Pinned Agents
// =============================================================================

/**
 * Check if an agent is pinned.
 * @param {string} agentName - Agent name to check
 * @returns {boolean}
 */
function isAgentPinned(agentName) {
    return pinnedAgents.has(agentName);
}

/**
 * Toggle pin state for an agent.
 * @param {string} agentName - Agent name to toggle
 */
async function togglePinAgent(agentName) {
    if (pinnedAgents.has(agentName)) {
        pinnedAgents.delete(agentName);
    } else {
        pinnedAgents.add(agentName);
    }

    // Update tile's data-category
    updateTilePinnedState(agentName);

    // Save to preferences
    await savePreference('ui.pinned_agents', JSON.stringify([...pinnedAgents]));
}

/**
 * Update a tile's data-category to include/exclude 'pinned'.
 * @param {string} agentName - Agent name
 */
function updateTilePinnedState(agentName) {
    const tile = document.querySelector(`.tile[onclick*="'${agentName}'"]`);
    if (!tile) return;

    let categories = (tile.dataset.category || '').split('|').filter(c => c && c !== 'pinned');
    if (pinnedAgents.has(agentName)) {
        categories.unshift('pinned');  // Add pinned at the start
    }
    tile.dataset.category = categories.join('|');
}

/**
 * Apply pinned state to all tiles after loading preferences.
 */
function applyPinnedStatesToTiles() {
    pinnedAgents.forEach(agentName => {
        updateTilePinnedState(agentName);
    });
}

/**
 * Toggle hidden state for an agent (expert mode only).
 * @param {string} agentName - Agent name to toggle
 */
async function toggleAgentHidden(agentName) {
    try {
        const response = await fetch(`${API}/agents/${agentName}/toggle-hidden`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.status === 'ok') {
            serverLog('[Agents] Toggled hidden for: ' + agentName + ' (now ' + (data.hidden ? 'hidden' : 'visible') + ')');
            // Refresh will be triggered by SSE event from backend
        } else {
            serverError('[Agents] Failed to toggle hidden: ' + (data.message || 'Unknown error'));
        }
    } catch (error) {
        serverError('[Agents] Error toggling hidden: ' + error.message);
    }
}

// =============================================================================
// Category Filtering
// =============================================================================

let currentCategory = 'all';

/**
 * Filtert Tiles nach Suchtext (Name oder ID)
 */
function filterTilesBySearch(searchText) {
    currentSearchFilter = searchText.toLowerCase().trim();

    // Clear-Button Toggle
    const clearBtn = document.querySelector('.dropdown-search .clear-search-btn');
    if (clearBtn) {
        clearBtn.style.display = currentSearchFilter ? 'flex' : 'none';
    }

    applyAllFilters();
}

/**
 * Suchfeld leeren
 */
function clearCategorySearch(event) {
    event.stopPropagation();
    const input = document.getElementById('categorySearchInput');
    if (input) {
        input.value = '';
        filterTilesBySearch('');
        input.focus();
    }
}

/**
 * Kombinierte Filter-Logik (Kategorie + Suche)
 */
function applyAllFilters() {
    const tiles = document.querySelectorAll('.tile');
    const isHiddenCategory = currentCategory === 'hidden';

    // Body-Klasse für Hidden-Tiles CSS
    document.body.classList.toggle('show-hidden-tiles', isHiddenCategory);

    tiles.forEach(tile => {
        const tileName = tile.querySelector('.tile-name')?.textContent?.toLowerCase() || '';
        const tileId = tile.id?.replace('tile-', '')?.toLowerCase() || '';
        const isHiddenTile = tile.dataset.hidden === 'true';
        const tileCategories = (tile.dataset.category || '').split('|')
                               .map(c => c.trim()).filter(c => c);

        // Suchfilter prüfen
        const matchesSearch = !currentSearchFilter ||
                              tileName.includes(currentSearchFilter) ||
                              tileId.includes(currentSearchFilter);

        // Kategoriefilter prüfen
        let matchesCategory;
        if (isHiddenCategory) {
            // Hidden-Kategorie: nur hidden Tiles zeigen
            matchesCategory = isHiddenTile;
        } else if (currentCategory === 'all') {
            // Alle: normale Tiles (nicht hidden)
            matchesCategory = !isHiddenTile;
        } else {
            // Spezifische Kategorie: normale Tiles mit passender Kategorie
            matchesCategory = !isHiddenTile && tileCategories.includes(currentCategory);
        }

        // Anzeigen wenn beide Filter passen
        tile.style.display = (matchesSearch && matchesCategory) ? '' : 'none';
    });
}

/**
 * Filter tiles by category.
 * @param {string} category - Category to filter by ('all', 'hidden', or category name)
 * @param {boolean} persist - Whether to save preference (default: true)
 */
function filterByCategory(category, persist = true) {
    currentCategory = category;

    // Update dropdown label and icon
    const label = document.getElementById('categoryLabel');
    const icon = document.getElementById('categoryIcon');
    const categories = JSON.parse(document.getElementById('categoryData')?.value || '{}');
    if (category === 'all') {
        label.textContent = t('ui.all_categories');
        icon.textContent = 'apps';
    } else if (category === 'hidden') {
        label.textContent = 'Hidden';
        icon.textContent = 'visibility_off';
    } else {
        label.textContent = categories[category]?.label || category;
        icon.textContent = categories[category]?.icon || 'folder';
    }

    // Update active state in dropdown
    document.querySelectorAll('#categoryMenu .dropdown-item').forEach(item => {
        item.classList.toggle('active', item.dataset.category === category);
    });

    // Close dropdown
    document.getElementById('categoryMenu')?.classList.remove('show');

    // Kombinierte Filter anwenden (ersetzt die alte Tile-Filter-Logik)
    applyAllFilters();

    // Save preference to server (unless loading from preferences)
    if (persist) {
        savePreference('ui.selected_category', category);
    }
}

function toggleCategoryMenu() {
    const menu = document.getElementById('categoryMenu');
    const isOpen = menu.classList.contains('show');
    // Close all dropdowns first
    document.querySelectorAll('.dropdown-menu').forEach(m => m.classList.remove('show'));
    if (!isOpen) {
        menu.classList.add('show');
        // Focus search input when opening
        setTimeout(() => {
            document.getElementById('categorySearchInput')?.focus();
        }, 50);
    }
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const categoryDropdown = document.getElementById('categoryDropdown');
    const categoryMenu = document.getElementById('categoryMenu');
    if (categoryMenu && categoryMenu.classList.contains('show')) {
        // Check if click is outside the dropdown
        if (!categoryDropdown?.contains(e.target)) {
            categoryMenu.classList.remove('show');
        }
    }
});

// Close dropdown on ESC key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const categoryMenu = document.getElementById('categoryMenu');
        if (categoryMenu && categoryMenu.classList.contains('show')) {
            categoryMenu.classList.remove('show');
        }
    }
});

// =============================================================================
// Ctrl+Hover Category Context Menu (Tile View Only)
// =============================================================================

let categoryContextMenu = null;
let categoryContextMouseX = 0;
let categoryContextMouseY = 0;

// Track mouse position for context menu
document.addEventListener('mousemove', (e) => {
    categoryContextMouseX = e.clientX;
    categoryContextMouseY = e.clientY;
});

// Create floating category menu (once)
function createCategoryContextMenu() {
    if (categoryContextMenu) return;

    // Clone items from the header dropdown
    const sourceMenu = document.getElementById('categoryMenu');
    if (!sourceMenu) return;

    categoryContextMenu = document.createElement('div');
    categoryContextMenu.className = 'category-context-menu';
    categoryContextMenu.innerHTML = sourceMenu.innerHTML;

    // Update onclick handlers to also hide context menu
    categoryContextMenu.querySelectorAll('.dropdown-item').forEach(item => {
        const category = item.dataset.category;
        item.onclick = () => {
            filterByCategory(category);
            hideCategoryContextMenu();
        };
    });

    document.body.appendChild(categoryContextMenu);
}

function showCategoryContextMenu() {
    // Only in tile view (tile-grid visible)
    const tileGrid = document.querySelector('.tile-grid');
    if (!tileGrid || tileGrid.classList.contains('hidden')) return;

    createCategoryContextMenu();
    if (!categoryContextMenu) return;

    // Don't reposition if already visible (key repeat)
    if (categoryContextMenu.classList.contains('show')) return;

    // Update active state
    categoryContextMenu.querySelectorAll('.dropdown-item').forEach(item => {
        item.classList.toggle('active', item.dataset.category === currentCategory);
    });

    // Position near mouse, ensure it stays on screen
    let x = categoryContextMouseX;
    let y = categoryContextMouseY + 10;

    // Adjust if too close to right edge
    const menuWidth = 200;
    if (x + menuWidth > window.innerWidth) {
        x = window.innerWidth - menuWidth - 10;
    }

    // Adjust if too close to bottom
    const menuHeight = 300;
    if (y + menuHeight > window.innerHeight) {
        y = categoryContextMouseY - menuHeight - 10;
    }

    categoryContextMenu.style.left = x + 'px';
    categoryContextMenu.style.top = y + 'px';
    categoryContextMenu.classList.add('show');
}

function hideCategoryContextMenu() {
    if (categoryContextMenu) {
        categoryContextMenu.classList.remove('show');
    }
}

// Space key shows category context menu (only in tile view, not in input fields)
document.addEventListener('keydown', (e) => {
    if (e.key === ' ' && !e.ctrlKey && !e.shiftKey && !e.altKey) {
        // Don't trigger if focus is in an input field
        const activeEl = document.activeElement;
        if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable)) {
            return;
        }
        // Only show if tile-grid is visible
        const tileGrid = document.querySelector('.tile-grid');
        if (tileGrid && !tileGrid.classList.contains('hidden')) {
            e.preventDefault();  // Prevent page scroll
            showCategoryContextMenu();
        }
    }
});

document.addEventListener('keyup', (e) => {
    if (e.key === ' ') {
        hideCategoryContextMenu();
    }
});

// =============================================================================
// Initialization: Watcher Polling & Random Slogan
// =============================================================================

// Poll watcher status every 30 seconds
setInterval(loadWatcherStatus, 30000);
// Load on startup
loadWatcherStatus();

// Set random slogan on page load - uses getHeaderSlogans() for translations
(function setRandomSlogan() {
    const el = document.getElementById('headerSlogan');
    if (el) {
        const slogans = getHeaderSlogans();
        el.textContent = slogans[Math.floor(Math.random() * slogans.length)];
    }
})();

// =============================================================================
// Demo Mode
// =============================================================================

async function toggleDemoMode() {
    try {
        const current = await fetch(API + '/demo-mode').then(r => r.json());
        const newState = !current.enabled;

        await fetch(API + '/demo-mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enabled: newState})
        });

        updateDemoBadge(newState);
        showToast(newState ? t('demo.enabled') : t('demo.disabled'), 3000);
    } catch (e) {
        console.error('Demo mode toggle failed:', e);
        showToast(t('demo.error'), 3000);
    }
}

function updateDemoBadge(enabled) {
    const badge = document.getElementById('demoBadge');
    const status = document.getElementById('demoStatus');
    if (badge) {
        badge.classList.toggle('demo-on', enabled);
        if (status) {
            status.textContent = enabled ? t('demo.on') : t('demo.off');
        }
    }
}

async function initDemoMode() {
    try {
        const config = await fetch(API + '/demo-mode').then(r => r.json());
        const badge = document.getElementById('demoBadge');
        if (badge) {
            // Show badge if show_toggle is true (default)
            if (config.show_toggle !== false) {
                badge.style.display = 'flex';
            }
            updateDemoBadge(config.enabled);
        }
    } catch (e) {
        console.error('Failed to init demo mode:', e);
    }
}

// =============================================================================
// Hamburger Menu (Mobile)
// =============================================================================

function toggleHamburgerMenu() {
    const menu = document.getElementById('hamburgerMenu');
    const backdrop = document.getElementById('hamburgerBackdrop');
    const isOpen = menu.classList.contains('open');
    
    if (isOpen) {
        closeHamburgerMenu();
    } else {
        openHamburgerMenu();
    }
}

function openHamburgerMenu() {
    const menu = document.getElementById('hamburgerMenu');
    const backdrop = document.getElementById('hamburgerBackdrop');
    
    menu.classList.add('open');
    backdrop.classList.add('show');
    document.body.style.overflow = 'hidden';  // Prevent body scroll
    
    // Update menu values
    updateHamburgerMenuValues();
}

function closeHamburgerMenu() {
    const menu = document.getElementById('hamburgerMenu');
    const backdrop = document.getElementById('hamburgerBackdrop');
    
    menu.classList.remove('open');
    backdrop.classList.remove('show');
    document.body.style.overflow = '';  // Restore body scroll
}

function updateHamburgerMenuValues() {
    // Update cost display in hamburger menu
    const costDisplay = document.getElementById('totalCostDisplay');
    const hamburgerCost = document.getElementById('hamburgerCostValue');
    if (costDisplay && hamburgerCost) {
        hamburgerCost.textContent = costDisplay.textContent;
    }

    // Update category display in hamburger menu
    const categoryLabel = document.getElementById('categoryLabel');
    const hamburgerCategoryValue = document.getElementById('hamburgerCategoryValue');
    if (categoryLabel && hamburgerCategoryValue) {
        hamburgerCategoryValue.textContent = categoryLabel.textContent;
    }

    // Update content mode display in hamburger menu
    const contentModeLabel = document.getElementById('contentModeLabel');
    const hamburgerContentModeValue = document.getElementById('hamburgerContentModeValue');
    if (contentModeLabel && hamburgerContentModeValue) {
        hamburgerContentModeValue.textContent = contentModeLabel.textContent;
    }

    // Update demo mode display in hamburger menu
    const demoStatus = document.getElementById('demoStatus');
    const hamburgerDemo = document.getElementById('hamburgerDemo');
    const hamburgerDemoValue = document.getElementById('hamburgerDemoValue');
    const demoBadge = document.getElementById('demoBadge');
    if (hamburgerDemo && demoBadge) {
        // Show hamburger demo item if demo badge is visible
        if (demoBadge.style.display !== 'none') {
            hamburgerDemo.style.display = 'flex';
            if (hamburgerDemoValue && demoStatus) {
                hamburgerDemoValue.textContent = demoStatus.textContent;
            }
        }
    }
}

// Toggle hamburger category submenu
function toggleHamburgerCategoryMenu() {
    const item = document.getElementById('hamburgerCategory');
    const submenu = document.getElementById('hamburgerCategoryMenu');
    if (item && submenu) {
        item.classList.toggle('expanded');
        submenu.classList.toggle('open');
    }
}

// Toggle hamburger content mode submenu
function toggleHamburgerContentModeMenu() {
    const item = document.getElementById('hamburgerContentMode');
    const submenu = document.getElementById('hamburgerContentModeMenu');
    if (item && submenu) {
        item.classList.toggle('expanded');
        submenu.classList.toggle('open');
    }
}

// Update hamburger menu values periodically
setInterval(updateHamburgerMenuValues, 2000);

// Close hamburger menu on ESC key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const menu = document.getElementById('hamburgerMenu');
        if (menu && menu.classList.contains('open')) {
            closeHamburgerMenu();
        }
    }
});

// =============================================================================
// [030] ViewContext Event Listeners
// =============================================================================

/**
 * Handle view-switched: Restore stats, overlay, context for viewed task.
 */
document.addEventListener('da:view-switched', (e) => {
    const { taskState, previousTaskId } = e.detail;
    if (!taskState) return;

    console.log('[UI] View switched to task:', e.detail.taskId);

    // Restore stats from TaskState
    if (taskState.stats && (taskState.stats.backend || taskState.stats.model)) {
        updateStatsPanel({
            backend: taskState.stats.backend || '-',
            model: taskState.stats.model || '-',
            duration: taskState.stats.duration || '-',
            tokens: taskState.stats.tokens || '-',
            cost: taskState.stats.cost || '-'
        });
    }

    // Restore context stats from TaskState
    if (taskState.context && taskState.context.totalTokens > 0) {
        let contextStr = '';
        if (taskState.context.iteration && taskState.context.maxIterations) {
            contextStr = `Step ${taskState.context.iteration}/${taskState.context.maxIterations}`;
        }
        let breakdownStr = '';
        const parts = [];
        if (taskState.context.systemTokens > 0) parts.push(`System: ${formatTokens(taskState.context.systemTokens)}`);
        if (taskState.context.userTokens > 0) parts.push(`Prompt: ${formatTokens(taskState.context.userTokens)}`);
        if (taskState.context.toolTokens > 0) parts.push(`Tools: ${formatTokens(taskState.context.toolTokens)}`);
        if (parts.length > 0) breakdownStr = parts.join(' · ');
        updateProcessingContext(contextStr, breakdownStr);
    }

    // [066] A2: Restore overlay state via State Machine
    ViewContext._applyUIForPhase(taskState.uiPhase || 'idle', { message: taskState.agentName || '' });

    // [033] Restore anonymization badge from TaskState
    if (taskState.anon.stats && taskState.anon.stats.total_entities > 0) {
        // Has anon stats with entities - show count badge
        lastAnonStats = taskState.anon.stats;
        lastAnonTotal = taskState.anon.stats.total_entities || 0;
        lastToolCallsAnonymized = taskState.anon.stats.tool_calls_anonymized || 0;
        updateAnonBadge(taskState.anon.stats);
    } else if (taskState.anon.enabled) {
        // Anon enabled but no stats yet - show ON
        lastAnonStats = null;
        lastAnonTotal = 0;
        lastToolCallsAnonymized = 0;
        resetAnonBadge(false);
    } else {
        // Anon disabled - show OFF
        lastAnonStats = null;
        lastAnonTotal = 0;
        lastToolCallsAnonymized = 0;
        resetAnonBadge(true);
    }
});

/**
 * Handle task-completed: Hide overlay and show final stats for viewed task.
 */
document.addEventListener('da:task-completed', (e) => {
    const { taskId, finalStats } = e.detail;

    // Only update UI if this is the viewed task
    if (!ViewContext.isViewed(taskId)) return;

    // Final stats are already written - the task_complete SSE handler updates UI
    // This event is mainly for background tasks that complete while not viewed
    console.log('[UI] Task completed:', taskId);
});
