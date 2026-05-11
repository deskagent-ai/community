/**
 * WebUI Core Module
 * Global state variables, pricing/costs, connection status, session management.
 * This module MUST load first as other modules depend on these globals.
 */

// =============================================================================
// State Variables (used across all modules)
// =============================================================================

let activeTaskCount = 0;
let loadingStartTime = null;
let loadingTimerInterval = null;
let thinkingStartTime = null;
let thinkingTimerInterval = null;
let currentTaskId = null;  // Track current task for cancellation
let pendingTaskId = null;  // #6 - Track task ID before SSE confirms start (prevents race condition)
let currentTaskTile = null;  // Track tile for result display
let currentSessionId = null;  // Track current session for Quick Access Open button
let pinnedTile = null;  // Track pinned tile during processing
let currentChatBackend = null;  // Current chat backend (null = default)
let currentChatName = null;  // Current chat name for display
let currentSkillName = null;  // Current skill name for context clearing
let isSubmittingResponse = false;  // Guard against double submission of question responses
let cancelRequestedForTask = null;  // Track which task was cancelled to stop polling immediately
let currentUserPrompt = null;  // Initial user prompt to display in conversation
let userPromptDisplayed = false;  // Track if user prompt was already shown
let isChatMode = false;  // Track if we're in Chat mode (started via openChat)
let pinnedAgents = new Set();  // Track user-pinned favorite agents
let backendReady = false;  // Track if backend is ready (startup complete)

// Quick Access mode detection
let isQuickAccessMode = false;

/**
 * Detect if we're running in Quick Access mode (compact overlay window).
 * Quick Access mode is triggered by ?quickaccess=1 URL param or very narrow window.
 */
function detectQuickAccessMode() {
    const urlParams = new URLSearchParams(window.location.search);
    isQuickAccessMode = urlParams.has('quickaccess') || window.innerWidth < 300;
    if (isQuickAccessMode) {
        document.body.classList.add('quick-access-mode');
        console.log('[WebUI] Quick Access mode detected');
    }

    // #10 - Update Quick Access mode on resize (only when no task is running)
    window.addEventListener('resize', function() {
        const wasQuickAccess = isQuickAccessMode;
        const newQuickAccess = window.innerWidth < 300;
        if (wasQuickAccess !== newQuickAccess && !currentTaskId) {
            isQuickAccessMode = newQuickAccess;
            if (newQuickAccess) {
                document.body.classList.add('quick-access-mode');
            } else {
                document.body.classList.remove('quick-access-mode');
            }
            console.log('[WebUI] Quick Access mode changed to:', newQuickAccess);
        }
    });
}

/**
 * Open the full browser view (from Quick Access mode).
 * Opens the main WebUI in the default browser without quickaccess param.
 */
function openBrowserView() {
    const baseUrl = window.location.origin + '/';
    window.open(baseUrl, '_blank');
}

/**
 * Open Quick Access overlay window (from browser mode).
 * Calls API endpoint to trigger the pywebview Quick Access window.
 */
async function openQuickAccess() {
    try {
        const res = await fetch(`${API}/quickaccess/toggle`, { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
            // Fallback: show toast with hotkey hint
            showToast(data.message || t('quickaccess.use_hotkey') || 'Use Alt+Q to open Quick Access');
        }
    } catch (e) {
        console.error('[WebUI] Failed to open Quick Access:', e);
        showToast(t('quickaccess.use_hotkey') || 'Use Alt+Q to open Quick Access');
    }
}

// =============================================================================
// UI Heartbeat (prevents duplicate browser tabs on restart)
// =============================================================================

let heartbeatInterval = null;
const HEARTBEAT_INTERVAL = 15000; // 15 seconds

/**
 * Start sending periodic heartbeats to the server.
 * This signals that a browser tab is open, preventing duplicate tabs on restart.
 */
function startUIHeartbeat() {
    // Send initial heartbeat immediately
    sendHeartbeat();

    // Then send every 15 seconds
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL);

    // Also send heartbeat on visibility change (tab becomes visible)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            sendHeartbeat();
        }
    });

    console.log('[Heartbeat] Started UI heartbeat');
}

/**
 * Send a single heartbeat to the server.
 */
async function sendHeartbeat() {
    try {
        await fetch(API + '/ui/heartbeat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: getClientId() })
        });
    } catch (e) {
        // Silently ignore errors (server might be restarting)
    }
}

/**
 * Get or create a unique client ID for this tab.
 */
function getClientId() {
    let clientId = sessionStorage.getItem('deskagent_client_id');
    if (!clientId) {
        clientId = 'tab_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        sessionStorage.setItem('deskagent_client_id', clientId);
    }
    return clientId;
}

// Pricing and cost tracking (server-side persistent storage)
let pricingConfig = null;
let totalCost = 0;
let todayCost = 0;
let totalTokens = 0;
let billableTotalCost = 0;  // Only API-billed costs (excludes SDK/local backends)

// Anthropic Admin API data (if configured)
let anthropicAvailable = false;
let anthropicTotalCost = null;
let costSource = 'local';

// Connection status
let isOnline = true;
let consecutiveFailures = 0;
let _settingsApiActive = 0; // Counter for in-flight settings API calls
const CONNECTION_CHECK_INTERVAL = 8000; // 8 seconds
const CONNECTION_TIMEOUT = 6000; // 6 seconds (generous for high CPU load)
const CONNECTION_FAILURES_THRESHOLD = 3; // failures before showing overlay

// Session/Context management
let currentSession = null;
let isAppendMode = false;  // True when continuing conversation with result panel open

// Anonymization tracking
let lastAnonStats = null;
let anonEnabled = false;  // Updated after DOM ready
let lastAnonTotal = 0;  // Track previous total for pulse animation
let lastToolCallsAnonymized = 0;  // Track tool calls for pulse animation

// Dialog state
let pendingPollContext = null;
let correctionMode = null; // {taskId, tile, name, isAgent, data} when waiting for user correction
let pendingDialogShown = false;

// =============================================================================
// Frontend Logging
// =============================================================================
// Log levels: "minimal" (errors only), "normal" (actions), "verbose" (debug)

function getLogLevel() {
    return (typeof BROWSER_LOG_LEVEL !== 'undefined') ? BROWSER_LOG_LEVEL : 'normal';
}

/**
 * Log important actions (always logged unless minimal)
 * Use for: user actions, task starts/completions, errors
 */
function serverLog(message) {
    const level = getLogLevel();
    // Always log to browser console
    console.log('[WebUI]', message);
    // Send to server unless minimal (errors only)
    if (level !== 'minimal') {
        fetch(API + '/log', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: '[WebUI] ' + message })
        }).catch(() => {});
    }
}

/**
 * Log verbose debug info (only in verbose mode)
 * Use for: detailed debugging, data dumps, development
 */
function serverDebug(message) {
    const level = getLogLevel();
    // Always log to browser console
    console.log('[WebUI:Debug]', message);
    // Only send to server in verbose mode
    if (level === 'verbose') {
        fetch(API + '/log', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: '[WebUI:Debug] ' + message })
        }).catch(() => {});
    }
}

/**
 * Log errors (always logged)
 */
function serverError(message) {
    console.error('[WebUI:Error]', message);
    fetch(API + '/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: '[WebUI:Error] ' + message })
    }).catch(() => {});
}

// Global error handlers - catch JavaScript errors and send to server log
window.onerror = function(message, source, lineno, colno, error) {
    const errorMsg = `${message} at ${source}:${lineno}:${colno}`;
    serverError(errorMsg);
    return false; // Allow default error handling
};

window.onunhandledrejection = function(event) {
    const errorMsg = `UNHANDLED PROMISE: ${event.reason}`;
    serverError(errorMsg);
};

// =============================================================================
// Pricing & Cost Management
// =============================================================================

async function loadPricingConfig() {
    try {
        const res = await fetch(API + '/pricing');
        if (res.ok) {
            pricingConfig = await res.json();
        }
    } catch (e) {
        console.warn('Could not load pricing config:', e);
    }
}

async function loadCostSummary() {
    try {
        const res = await fetch(API + '/costs');
        if (res.ok) {
            const data = await res.json();
            totalCost = data.total_usd || 0;
            todayCost = data.today_usd || 0;
            totalTokens = data.total_tokens || 0;
            billableTotalCost = data.billable_total_usd || 0;  // Only API-billed costs

            // Store Anthropic API data if available
            anthropicAvailable = data.anthropic_available || false;
            anthropicTotalCost = data.anthropic?.total_usd || null;
            costSource = data.recommended_source || 'local';

            updateTotalCostDisplay();
        }
    } catch (e) {
        console.warn('Could not load costs:', e);
    }
}

function updateTotalCostDisplay() {
    const el = document.getElementById('totalCostDisplay');
    if (el) {
        // If no billable costs (all SDK/local), show "—" instead of $0.00
        if (billableTotalCost === 0 && totalCost === 0) {
            el.textContent = '—';
            el.title = `${t('costs.tokens')}: ${totalTokens.toLocaleString()}\n(${t('costs.no_billable') || 'No billable API costs'})`;
            return;
        }

        // Determine which cost to show (prefer Anthropic if available, but only for billable)
        const displayCost = (anthropicAvailable && anthropicTotalCost !== null)
            ? anthropicTotalCost
            : billableTotalCost;
        const sourceIndicator = anthropicAvailable ? ' ✓' : '';

        // Show billable cost only (compact)
        if (displayCost === 0) {
            el.textContent = '—';
        } else {
            el.textContent = '$' + displayCost.toFixed(2) + sourceIndicator;
        }

        // Enhanced tooltip
        let tooltip = `${t('costs.total')}: $${totalCost.toFixed(4)} (${t('costs.local')})\n${t('costs.billable') || 'Billable'}: $${billableTotalCost.toFixed(4)}\n${t('costs.today')}: $${todayCost.toFixed(4)}\n${t('costs.tokens')}: ${totalTokens.toLocaleString()}`;
        if (anthropicAvailable && anthropicTotalCost !== null) {
            tooltip += `\n\nAnthropic API: $${anthropicTotalCost.toFixed(4)} ✓`;
        }
        el.title = tooltip;
    }
}

function addToCost(cost, tokens) {
    // Just update display - server tracks persistently
    if (cost > 0) {
        totalCost += cost;
        todayCost += cost;
    }
    if (tokens > 0) {
        totalTokens += tokens;
    }
    updateTotalCostDisplay();
}

async function resetTotalCost() {
    // Fetch cost comparison (includes both local and Anthropic data)
    try {
        const res = await fetch(API + '/costs/comparison');
        if (!res.ok) throw new Error('Failed to load costs');
        const comparisonData = await res.json();
        const data = comparisonData.local || {};

        // Update global tracking
        anthropicAvailable = comparisonData.anthropic_available || false;
        anthropicTotalCost = comparisonData.anthropic?.total_usd || null;

        // Helper: Estimate tokens from cost when not available
        function estimateTokens(costUsd) {
            if (!costUsd || costUsd <= 0) return null;
            // Average: (0.8 * $3 + 0.2 * $15) / 1M = $5.40 / 1M tokens
            const estimated = Math.round(costUsd * 185185);
            if (estimated < 1000) return '~' + estimated;
            if (estimated < 1000000) return '~' + (estimated / 1000).toFixed(1) + 'K';
            return '~' + (estimated / 1000000).toFixed(2) + 'M';
        }

        // Build backend breakdown (show "—" for non-billable backends)
        let backendHtml = '';
        if (data.by_backend && Object.keys(data.by_backend).length > 0) {
            backendHtml = `<h4 style="margin: 12px 0 8px 0;">${t('costs.by_backend')}:</h4><table style="width:100%; font-size: 13px; border-collapse: collapse;">`;
            backendHtml += `<tr style="background: var(--bg-secondary);"><th style="text-align:left; padding:4px;">Backend</th><th style="text-align:right; padding:4px;">${t('costs.cost')}</th><th style="text-align:right; padding:4px;">${t('costs.tokens')}</th><th style="text-align:right; padding:4px;">Tasks</th></tr>`;
            for (const [backend, stats] of Object.entries(data.by_backend)) {
                // Check if backend is billable (from pricing config, default true)
                const isBillable = pricingConfig?.backends?.[backend]?.billable !== false;
                const costDisplay = isBillable ? `$${stats.cost_usd.toFixed(4)}` : '—';
                const totalTokens = (stats.input_tokens || 0) + (stats.output_tokens || 0);
                // Show actual tokens, or estimate from cost if not available
                const tokensDisplay = totalTokens > 0
                    ? totalTokens.toLocaleString()
                    : (estimateTokens(stats.cost_usd) || '—');
                backendHtml += `<tr><td style="padding:4px;">${backend}</td><td style="text-align:right; padding:4px;">${costDisplay}</td><td style="text-align:right; padding:4px;">${tokensDisplay}</td><td style="text-align:right; padding:4px;">${stats.task_count}</td></tr>`;
            }
            backendHtml += '</table>';
        }

        // Build model breakdown
        let modelHtml = '';
        if (data.by_model && Object.keys(data.by_model).length > 0) {
            modelHtml = `<h4 style="margin: 12px 0 8px 0;">${t('costs.by_model')}:</h4><table style="width:100%; font-size: 13px; border-collapse: collapse;">`;
            modelHtml += `<tr style="background: var(--bg-secondary);"><th style="text-align:left; padding:4px;">Model</th><th style="text-align:right; padding:4px;">${t('costs.cost')}</th><th style="text-align:right; padding:4px;">${t('costs.tokens')}</th><th style="text-align:right; padding:4px;">Tasks</th></tr>`;
            for (const [model, stats] of Object.entries(data.by_model)) {
                const shortModel = model.length > 25 ? model.substring(0, 25) + '...' : model;
                const totalTokens = (stats.input_tokens || 0) + (stats.output_tokens || 0);
                // Show actual tokens, or estimate from cost if not available
                const tokensDisplay = totalTokens > 0
                    ? totalTokens.toLocaleString()
                    : (estimateTokens(stats.cost_usd) || '—');
                modelHtml += `<tr><td style="padding:4px;" title="${model}">${shortModel}</td><td style="text-align:right; padding:4px;">$${stats.cost_usd.toFixed(4)}</td><td style="text-align:right; padding:4px;">${tokensDisplay}</td><td style="text-align:right; padding:4px;">${stats.task_count}</td></tr>`;
            }
            modelHtml += '</table>';
        }

        // Show dialog with comparison data
        showCostDialog(data, backendHtml, modelHtml, comparisonData);
    } catch (e) {
        console.error('Error loading cost details:', e);
        alert(`${t('header.api_costs')}\n\n${t('costs.total')}: $${totalCost.toFixed(4)}\n${t('costs.today')}: $${todayCost.toFixed(4)}\n${t('costs.tokens')}: ${totalTokens.toLocaleString()}`);
    }
}

function showCostDialog(data, backendHtml, modelHtml, comparisonData = null) {
    // Create overlay
    const overlay = document.createElement('div');
    overlay.id = 'costDialogOverlay';
    overlay.style.cssText = 'position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); z-index:9999; display:flex; align-items:center; justify-content:center;';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    // Create dialog
    const dialog = document.createElement('div');
    dialog.style.cssText = 'background:var(--bg-primary); border-radius:12px; padding:24px; max-width:450px; width:90%; max-height:80vh; overflow-y:auto; box-shadow:0 8px 32px rgba(0,0,0,0.3);';

    // Build Anthropic comparison section if available
    let anthropicHtml = '';
    if (comparisonData && comparisonData.anthropic_available && comparisonData.anthropic) {
        const localCost = data.total_usd || 0;
        const anthropicCost = comparisonData.anthropic.total_usd || 0;
        const diff = localCost - anthropicCost;
        const diffPercent = anthropicCost > 0 ? ((diff / anthropicCost) * 100).toFixed(1) : 0;
        const diffColor = diff > 0 ? '#dc3545' : (diff < 0 ? '#28a745' : 'var(--text-secondary)');
        const diffSign = diff > 0 ? '+' : '';

        anthropicHtml = `
            <div style="background:linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); padding:16px; border-radius:8px; margin-bottom:16px; color:white;">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
                    <span style="font-size:18px;">✓</span>
                    <span style="font-weight:bold;">${t('costs.anthropic_verified')}</span>
                </div>
                <table style="width:100%; font-size:14px;">
                    <tr>
                        <td style="padding:4px 0;">${t('costs.local_calculated')}:</td>
                        <td style="text-align:right; padding:4px 0;">$${localCost.toFixed(4)}</td>
                    </tr>
                    <tr>
                        <td style="padding:4px 0;"><strong>Anthropic API:</strong></td>
                        <td style="text-align:right; padding:4px 0;"><strong>$${anthropicCost.toFixed(4)}</strong></td>
                    </tr>
                    <tr style="border-top:1px solid rgba(255,255,255,0.2);">
                        <td style="padding:8px 0 0 0;">${t('costs.difference')}:</td>
                        <td style="text-align:right; padding:8px 0 0 0; color:${diff > 0 ? '#ff6b6b' : '#69db7c'};">${diffSign}$${Math.abs(diff).toFixed(4)} (${diffSign}${diffPercent}%)</td>
                    </tr>
                </table>
                ${comparisonData.cache_age_seconds ? `<div style="font-size:11px; opacity:0.7; margin-top:8px;">${t('costs.cache')}: ${Math.floor(comparisonData.cache_age_seconds / 60)} ${t('costs.minutes_old')}</div>` : ''}
            </div>
        `;
    } else if (comparisonData && comparisonData.anthropic_configured && !comparisonData.anthropic_available) {
        // Configured but not available (error or waiting)
        const errorMsg = comparisonData.last_error || t('costs.not_available');
        anthropicHtml = `
            <div style="background:var(--bg-secondary); padding:12px; border-radius:8px; margin-bottom:16px; border-left:3px solid #ffc107;">
                <div style="display:flex; align-items:center; gap:8px; color:#ffc107;">
                    <span class="material-icons" style="font-size:18px;">warning</span>
                    <span>${t('costs.anthropic_configured_unavailable')}</span>
                </div>
                <div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">${errorMsg}</div>
            </div>
        `;
    }

    // Determine main display cost
    const displayCost = (comparisonData && comparisonData.anthropic_available && comparisonData.anthropic)
        ? comparisonData.anthropic.total_usd
        : (data.total_usd || 0);

    dialog.innerHTML = `
        <h3 style="margin:0 0 16px 0; display:flex; align-items:center; gap:8px;">
            <span class="material-icons">paid</span> ${t('header.api_costs')}
        </h3>
        ${anthropicHtml}
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px;">
            <div style="background:var(--bg-secondary); padding:12px; border-radius:8px; text-align:center;">
                <div style="font-size:24px; font-weight:bold; color:var(--accent-color);">$${displayCost.toFixed(2)}</div>
                <div style="font-size:12px; color:var(--text-secondary);">${t('costs.total')}${comparisonData && comparisonData.anthropic_available ? ' (API)' : ''}</div>
            </div>
            <div style="background:var(--bg-secondary); padding:12px; border-radius:8px; text-align:center;">
                <div style="font-size:24px; font-weight:bold;">$${todayCost.toFixed(2)}</div>
                <div style="font-size:12px; color:var(--text-secondary);">${t('costs.today')} (${t('costs.local')})</div>
            </div>
        </div>
        <div style="font-size:13px; color:var(--text-secondary); margin-bottom:8px;">
            Tasks: ${data.task_count || 0} | ${t('costs.tokens')}: ${((data.total_input_tokens || 0) + (data.total_output_tokens || 0)).toLocaleString()}
        </div>
        ${backendHtml}
        ${modelHtml}
        <div style="display:flex; gap:12px; margin-top:20px;">
            <button onclick="this.closest('#costDialogOverlay').remove()" style="flex:1; padding:10px; border:none; border-radius:6px; background:var(--bg-secondary); color:var(--text-primary); cursor:pointer;">
                ${t('dialog.close')}
            </button>
            ${comparisonData && comparisonData.anthropic_configured ? `
            <button onclick="refreshAnthropicCosts()" style="padding:10px 16px; border:none; border-radius:6px; background:var(--accent-color); color:white; cursor:pointer;" title="${t('costs.reload_anthropic')}">
                <span class="material-icons" style="font-size:16px; vertical-align:middle;">refresh</span>
            </button>
            ` : ''}
            <button onclick="confirmResetCosts()" style="padding:10px 20px; border:none; border-radius:6px; background:#dc3545; color:white; cursor:pointer;">
                <span class="material-icons" style="font-size:16px; vertical-align:middle;">restart_alt</span> Reset
            </button>
        </div>
    `;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
}

async function confirmResetCosts() {
    if (!confirm(t('costs.confirm_reset'))) {
        return;
    }

    try {
        const res = await fetch(API + '/costs/reset', { method: 'POST' });
        if (res.ok) {
            totalCost = 0;
            todayCost = 0;
            totalTokens = 0;
            updateTotalCostDisplay();
            document.getElementById('costDialogOverlay')?.remove();
            showToast(t('costs.reset_success'));
        } else {
            alert(t('costs.reset_error'));
        }
    } catch (e) {
        console.error('Reset error:', e);
        alert(t('task.error_prefix') + ' ' + e.message);
    }
}

async function refreshAnthropicCosts() {
    // Force refresh from Anthropic API (invalidate cache)
    try {
        const res = await fetch(API + '/costs/anthropic/refresh', { method: 'POST' });
        if (res.ok) {
            showToast(t('costs.loading_anthropic'));
            // Close dialog and reopen with fresh data
            document.getElementById('costDialogOverlay')?.remove();
            // Small delay to let cache invalidate
            setTimeout(() => resetTotalCost(), 500);
        } else {
            const data = await res.json();
            alert(t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error')));
        }
    } catch (e) {
        console.error('Refresh error:', e);
        alert(t('task.error_prefix') + ' ' + e.message);
    }
}

function calculateCost(aiBackend, inputTokens, outputTokens) {
    const defaultPricing = { input: 3, output: 15 };
    let rate = defaultPricing;

    if (pricingConfig) {
        // First try backend-specific pricing
        if (aiBackend && pricingConfig.backends && pricingConfig.backends[aiBackend]) {
            rate = pricingConfig.backends[aiBackend];
        } else if (pricingConfig.default) {
            rate = pricingConfig.default;
        }
    }

    const inputCost = (inputTokens / 1_000_000) * rate.input;
    const outputCost = (outputTokens / 1_000_000) * rate.output;
    return inputCost + outputCost;
}

// =============================================================================
// Connection Status
// =============================================================================

async function checkConnection() {
    const overlay = document.getElementById('connectionLostOverlay');
    if (!overlay) return;

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CONNECTION_TIMEOUT);

        const res = await fetch(API + '/status', { signal: controller.signal });
        clearTimeout(timeoutId);

        if (res.ok) {
            consecutiveFailures = 0;
            if (!isOnline) {
                // Connection restored!
                isOnline = true;
                showConnectionRestored(overlay);
            }
        } else {
            handleConnectionFailure(overlay);
        }
    } catch (e) {
        handleConnectionFailure(overlay);
    }
}

function handleConnectionFailure(overlay) {
    consecutiveFailures++;
    // Don't show connection-lost during startup (we have our own startup overlay)
    if (!backendReady) return;
    // Be more tolerant when settings API calls are in-flight (server busy)
    const threshold = _settingsApiActive > 0
        ? CONNECTION_FAILURES_THRESHOLD + 3  // 6 failures = 48s when server is busy
        : CONNECTION_FAILURES_THRESHOLD;
    // Only show overlay after multiple consecutive failures (tolerant for high CPU load)
    if (consecutiveFailures >= threshold && isOnline) {
        isOnline = false;
        showReconnecting(overlay);
    }
}

/**
 * Show "Reconnecting..." overlay with spinner
 */
function showReconnecting(overlay) {
    const icon = document.getElementById('connectionIcon');
    const status = document.getElementById('connectionStatus');

    if (icon) icon.textContent = 'sync';
    if (status) status.textContent = t('status.reconnecting') || 'Verbindung wird wiederhergestellt';

    overlay.classList.remove('connected');
    overlay.classList.add('visible', 'reconnecting');
}

/**
 * Show brief "Connected!" message then hide overlay
 */
function showConnectionRestored(overlay) {
    // If server was restarted, reload page to get fresh JS/CSS
    if (window._serverWasRestarted) {
        console.log('[Connection] Server was restarted, reloading page for fresh code');
        window._serverWasRestarted = false;
        location.reload();
        return;
    }

    const icon = document.getElementById('connectionIcon');
    const status = document.getElementById('connectionStatus');

    if (icon) icon.textContent = 'check_circle';
    if (status) status.textContent = t('status.connected') || 'Verbunden!';

    overlay.classList.remove('reconnecting');
    overlay.classList.add('connected');

    // Hide after brief delay
    setTimeout(() => {
        overlay.classList.remove('visible', 'connected');
        // Reset for next time
        if (icon) icon.textContent = 'wifi_off';
        if (status) status.textContent = t('status.connection_lost') || 'Verbindung unterbrochen';
    }, 1000);
}

/**
 * Show "Server is restarting..." overlay (called via SSE before shutdown)
 */
function showServerRestarting() {
    const overlay = document.getElementById('connectionLostOverlay');
    if (!overlay) return;

    const icon = document.getElementById('connectionIcon');
    const status = document.getElementById('connectionStatus');

    if (icon) icon.textContent = 'refresh';
    if (status) status.textContent = t('status.server_restarting') || 'Server startet neu...';

    // Mark as offline so checkConnection will show "connected" when back
    isOnline = false;
    consecutiveFailures = CONNECTION_FAILURES_THRESHOLD;
    // Flag: reload page when server comes back (code may have changed)
    window._serverWasRestarted = true;

    overlay.classList.remove('connected');
    overlay.classList.add('visible', 'reconnecting');

    console.log('[Connection] Server restart notification received');
}

// =============================================================================
// Session Management
// =============================================================================

async function loadSession() {
    try {
        const res = await fetch(API + '/session');
        if (res.ok) {
            currentSession = await res.json();
        }
    } catch (e) {
        console.warn('Could not load session:', e);
    }
}

async function clearHistory() {
    try {
        await fetch(API + '/session/clear', { method: 'POST' });
        console.log('Conversation history cleared');
    } catch (e) {
        console.error('Failed to clear history:', e);
    }
}

async function startNewContext() {
    const input = document.getElementById('promptInput');
    const prompt = input.value.trim();

    // Clear displayed content (new context = fresh UI)
    const resultContent = document.getElementById('resultContent');
    if (resultContent) {
        resultContent.innerHTML = '';
    }

    // Clear server-side history
    await clearHistory();

    if (!prompt) {
        // Just cleared context, nothing to send
        return;
    }

    // Send as new conversation (without history)
    await sendPromptWithContext(false);
}

// =============================================================================
// Content Mode Management
// =============================================================================

function toggleContentModeMenu() {
    const menu = document.getElementById('contentModeMenu');
    const dropdown = document.getElementById('contentModeDropdown');
    menu.classList.toggle('show');
    dropdown.classList.toggle('open');
}

async function setContentMode(mode) {
    try {
        const res = await fetch(API + '/content-mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: mode, save: true})
        });
        if (res.ok) {
            // Close menu and reload
            document.getElementById('contentModeMenu')?.classList.remove('show');
            document.getElementById('contentModeDropdown')?.classList.remove('open');
            location.reload();
        }
    } catch (e) {
        console.error('Could not set content mode:', e);
    }
}

// =============================================================================
// Global Event Listeners (Content Mode Dropdown)
// =============================================================================

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    const dropdown = document.getElementById('contentModeDropdown');
    if (dropdown && !dropdown.contains(e.target)) {
        document.getElementById('contentModeMenu')?.classList.remove('show');
        dropdown.classList.remove('open');
    }
});

// Open external links in new tab/window
document.addEventListener('click', function(e) {
    const link = e.target.closest('a[href]');
    if (link) {
        const href = link.getAttribute('href');
        // Check if it's an external link (http/https)
        if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
            e.preventDefault();
            // Detect if running in WebView (pywebview) or browser
            const isWebView = window.pywebview !== undefined || navigator.userAgent.includes('pywebview');
            if (isWebView) {
                // WebView: use API to open in system browser
                fetch(API + '/open-url', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: href})
                }).catch(() => window.open(href, '_blank'));
            } else {
                // Browser: open in new tab directly
                window.open(href, '_blank', 'noopener,noreferrer');
            }
        }
    }
});

// =============================================================================
// Initialization
// =============================================================================

// Initialize on load
loadPricingConfig();
loadCostSummary();

// Start connection checker
checkConnection();
setInterval(checkConnection, CONNECTION_CHECK_INTERVAL);

// Load session on startup
loadSession();

// =============================================================================
// Startup Backend Connection
// =============================================================================

/**
 * Wait for backend to be ready before enabling UI.
 * Shows startup overlay until /status responds successfully.
 */
async function waitForBackend() {
    const overlay = document.getElementById('startupOverlay');
    const statusEl = overlay?.querySelector('.startup-status');

    // Disable tiles during startup
    document.querySelectorAll('.tile').forEach(tile => {
        tile.classList.add('disabled');
    });

    // Retry until backend responds AND is fully ready
    let attempts = 0;
    const maxAttempts = 60; // 30 seconds max (server starts fast, but plugins may take time)

    while (!backendReady && attempts < maxAttempts) {
        try {
            const response = await fetch(API + '/status');
            if (response.ok) {
                const data = await response.json();
                // Check if backend startup is complete (not just server running)
                if (data.ready === true) {
                    backendReady = true;
                    break;
                }
                // Server running but not fully ready yet
                if (statusEl) {
                    statusEl.textContent = 'Loading plugins...';
                }
            }
        } catch (e) {
            // Server not running yet
            if (statusEl) {
                statusEl.textContent = attempts > 3
                    ? `Waiting for server... (${attempts})`
                    : 'Connecting...';
            }
        }

        attempts++;
        await new Promise(r => setTimeout(r, 500)); // 500ms retry interval
    }

    // Backend ready - update status but keep overlay visible until startup_complete
    if (backendReady) {
        // Update status to show we're loading UI components
        if (statusEl) statusEl.textContent = 'Loading UI...';

        // Enable tiles (but overlay still visible)
        document.querySelectorAll('.tile').forEach(tile => {
            tile.classList.remove('disabled');
        });
        console.log('[WebUI] Backend ready after', attempts, 'attempts, waiting for startup_complete event');

        // Fix: Re-load license info after backend is ready to fix race condition
        setTimeout(() => {
            if (typeof loadLicenseInfo === 'function') {
                loadLicenseInfo();
            }
        }, 500);

        // Fallback: Hide overlay after 10s if SSE startup_complete never arrives
        setTimeout(() => {
            if (overlay && !overlay.classList.contains('hidden')) {
                console.warn('[WebUI] Fallback: hiding overlay after 10s timeout (SSE may have failed)');
                overlay.classList.add('hidden');
            }
        }, 10000);
    } else {
        if (statusEl) statusEl.textContent = 'Connection failed';
        console.error('[WebUI] Backend connection failed after', maxAttempts, 'attempts');
    }
}

// Update anonEnabled after DOM ready and translate static elements
document.addEventListener('DOMContentLoaded', async function() {
    // Wait for backend before enabling UI
    await waitForBackend();

    // Refresh prerequisites cache and tiles to get correct badges after startup
    // (initial HTML may have stale badges if MCPs weren't loaded yet or cache is stale)
    // Note: refreshAgentTiles is defined in webui-agents.js which loads after webui-core.js
    // Wait for window.load to ensure all scripts are loaded
    async function refreshPrerequisitesAndTiles() {
        // First, clear the prerequisites cache to force fresh checks
        try {
            await fetch(API + '/api/mcp/refresh-prerequisites', { method: 'POST' });
            console.log('[WebUI] Prerequisites cache refreshed');
        } catch (err) {
            console.warn('[WebUI] Could not refresh prerequisites cache:', err);
        }
        // Then refresh tiles with fresh data
        if (typeof refreshAgentTiles === 'function') {
            await refreshAgentTiles();
        }
    }

    if (document.readyState === 'complete') {
        // Page already fully loaded
        await refreshPrerequisitesAndTiles();
    } else {
        // Wait for all scripts to load
        window.addEventListener('load', async () => {
            await refreshPrerequisitesAndTiles();
        });
    }

    // Start UI heartbeat to signal tab is open (prevents duplicate tabs on restart)
    startUIHeartbeat();

    // Detect Quick Access mode early (affects UI behavior)
    detectQuickAccessMode();

    anonEnabled = document.getElementById('anonBadge')?.classList.contains('online');
    // Translate all static HTML elements with data-i18n attributes
    if (typeof translateStaticElements === 'function') {
        translateStaticElements();
    }

    // Initialize chat view from storage (for Quick Access popup windows)
    if (typeof initChatViewFromStorage === 'function') {
        initChatViewFromStorage();
    }

    // Handle ?continue=sessionId URL parameter (from Quick Access Open button)
    const urlParams = new URLSearchParams(window.location.search);
    const continueSessionId = urlParams.get('continue');
    if (continueSessionId && typeof continueSession === 'function') {
        // Small delay to ensure UI is ready
        setTimeout(() => {
            continueSession(continueSessionId);
            // Clean up URL
            window.history.replaceState({}, '', window.location.pathname);
        }, 100);
    }

    // Handle ?task=taskId URL parameter (from Quick Access dialog redirect)
    // When a dialog is needed in Quick Access mode, the full UI opens with this parameter
    const takeoverTaskId = urlParams.get('task');
    const takeoverAgent = urlParams.get('agent');
    const takeoverIsAgent = urlParams.get('isAgent') === 'true';
    if (takeoverTaskId && takeoverAgent) {
        console.log('[WebUI] Taking over task from Quick Access:', takeoverTaskId, 'agent:', takeoverAgent);
        setTimeout(() => {
            // Find tile for this agent
            let tile = document.getElementById('tile-' + takeoverAgent);
            if (!tile) {
                // Fallback: use first matching tile by data-name attribute
                tile = document.querySelector(`[data-name="${takeoverAgent}"]`);
            }

            if (tile && typeof pinTile === 'function') {
                pinTile(tile);
            }

            // Hide tiles and prepare UI for task display
            if (typeof hideTiles === 'function') hideTiles();
            if (typeof showPromptArea === 'function') showPromptArea();

            // Poll the task - this will detect pending_input and show the dialog
            if (typeof pollTask === 'function') {
                pollTask(takeoverTaskId, tile, takeoverAgent, takeoverIsAgent);
            }

            // Clean up URL
            window.history.replaceState({}, '', window.location.pathname);
        }, 100);
    }
});

// =============================================================================
// Simple Mode Toggle
// =============================================================================

/**
 * Toggle between Simple and Expert mode.
 * Simple mode hides advanced features for non-technical users.
 */
async function toggleSimpleMode() {
    try {
        const res = await fetch(API + '/toggle-simple-mode', { method: 'POST' });
        if (res.ok) {
            // Reload page to apply new mode
            window.location.reload();
        } else {
            console.error('Failed to toggle simple mode');
            showToast(t('mode.switch_error'));
        }
    } catch (e) {
        console.error('Error toggling simple mode:', e);
        showToast(t('mode.switch_error'));
    }
}
