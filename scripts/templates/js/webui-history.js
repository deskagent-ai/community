/**
 * WebUI History Module
 * Slide-in panel for chat history management.
 * Depends on: webui-core.js (state, API), webui-ui.js (showToast)
 */

// =============================================================================
// State Variables
// =============================================================================

let historyPanelOpen = false;
let historyDetailOpen = false;
let historyPinned = false;
let historySessionsCache = [];
let selectedSessionId = null;
let currentHistoryFilter = 'all';

// Track which session IDs are currently running
const runningSessions = new Set();

// Touch device detection - no hover, so disable auto-close
const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);

// =============================================================================
// Current Chat Session Highlight [024]
// =============================================================================

/**
 * Highlight the session card that is currently shown in the chat window.
 * Removes .current-chat from all cards, then adds it to the matching card.
 * @param {string|null} sessionId - The session ID to highlight, or null to clear
 */
function highlightCurrentChatSession(sessionId) {
    document.querySelectorAll('.history-session-card.current-chat').forEach(card => {
        card.classList.remove('current-chat');
    });
    if (sessionId) {
        const card = document.querySelector(`.history-session-card[data-session-id="${sessionId}"]`);
        if (card) {
            card.classList.add('current-chat');
        }
    }
}

// =============================================================================
// Panel Controls
// =============================================================================

/**
 * Sync running sessions state from server before rendering history.
 * Ensures correct running indicators even if SSE events were missed.
 */
async function syncRunningSessionsFromServer() {
    try {
        const res = await fetch(API + '/task/active');
        if (res.ok) {
            const data = await res.json();
            if (data.running_sessions && Array.isArray(data.running_sessions)) {
                runningSessions.clear();
                data.running_sessions.forEach(sid => runningSessions.add(sid));
            }
            // [072] Populate session-to-task mapping for thinking overlay on history switch
            if (data.session_task_map && typeof data.session_task_map === 'object') {
                for (const [sid, tid] of Object.entries(data.session_task_map)) {
                    if (tid) {
                        sessionTaskMap[sid] = tid;
                        ViewContext.mapSessionToTask(sid, tid);
                    }
                }
            }
        }
    } catch (e) {
        console.warn('[History] Failed to sync running sessions:', e);
    }
}

/**
 * Open the history panel with slide-in animation
 */
async function openHistoryPanel() {
    const panel = document.getElementById('historyPanel');
    const edgeTrigger = document.getElementById('historyEdgeTrigger');

    if (!panel) return;

    // Close any open context menu
    if (typeof closeContextMenu === 'function') {
        closeContextMenu();
    }

    panel.classList.remove('peek');
    panel.classList.add('open');
    historyPanelOpen = true;

    // Hide edge trigger
    if (edgeTrigger) {
        edgeTrigger.classList.add('hidden');
    }

    // Sync running sessions before loading history
    await syncRunningSessionsFromServer();

    // Load history data
    loadHistory();

    serverLog('History panel opened');
}

/**
 * Close the history panel
 */
function closeHistoryPanel() {
    const panel = document.getElementById('historyPanel');
    const edgeTrigger = document.getElementById('historyEdgeTrigger');
    const pinBtn = document.getElementById('historyPinBtn');

    if (!panel) return;

    panel.classList.remove('open', 'peek', 'pinned');
    document.body.classList.remove('history-pinned');
    historyPanelOpen = false;
    historyPinned = false;

    // Clear pinned state in server preferences
    savePreference('ui.history_pinned', false);

    // Reset pin button
    if (pinBtn) pinBtn.title = t('history.pin');

    // Show edge trigger again
    if (edgeTrigger) {
        edgeTrigger.classList.remove('hidden');
    }

    // Close detail panel if open
    closeSessionDetail();

    serverLog('History panel closed');
}

/**
 * Toggle peek mode (partial slide-in on hover)
 */
function peekHistoryPanel() {
    const panel = document.getElementById('historyPanel');
    if (!panel || historyPanelOpen) return;

    panel.classList.toggle('peek');
}

/**
 * Toggle pinned mode for history panel
 * When pinned: panel stays open, main content shrinks, no auto-close
 */
function toggleHistoryPin() {
    const panel = document.getElementById('historyPanel');
    const pinBtn = document.getElementById('historyPinBtn');

    if (!panel) return;

    historyPinned = !historyPinned;

    // Persist pinned state to server preferences
    savePreference('ui.history_pinned', historyPinned);

    if (historyPinned) {
        // Pin the panel
        panel.classList.add('pinned');
        document.body.classList.add('history-pinned');
        if (pinBtn) pinBtn.title = t('history.unpin');

        // Ensure panel is open
        if (!historyPanelOpen) {
            openHistoryPanel();
        }

        serverLog('History panel pinned');
    } else {
        // Unpin the panel
        panel.classList.remove('pinned');
        document.body.classList.remove('history-pinned');
        if (pinBtn) pinBtn.title = t('history.pin');

        serverLog('History panel unpinned');
    }
}

// =============================================================================
// Data Loading
// =============================================================================

/**
 * Load chat history sessions from the server
 */
async function loadHistory() {
    try {
        const res = await fetch(API + '/history/sessions');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        historySessionsCache = data.sessions || [];

        renderSessionList(historySessionsCache);
        updateHistoryStats(data);

    } catch (error) {
        serverError('Failed to load history: ' + error.message);
        showEmptyState(t('history.load_failed'));
    }
}

/**
 * Load history quietly (without error toasts) - for SSE event refreshes
 * #18 - Added proper error handling
 */
async function loadHistoryQuiet() {
    try {
        const res = await fetch(API + '/history/sessions');
        if (!res.ok) {
            // #18 - Log error but don't update cache on failure
            console.error('[History] Fetch failed:', res.status);
            return;  // Don't update cache on error
        }

        const data = await res.json();
        historySessionsCache = data.sessions || [];

        // Only re-render if panel is open
        if (historyPanelOpen) {
            renderSessionList(historySessionsCache);
            updateHistoryStats(data);
        }
    } catch (error) {
        // #18 - Log error properly for debugging
        console.error('[History] Fetch error:', error);
    }
}

// #19 - Debounce history refresh to prevent rapid consecutive calls
let historyRefreshTimeout = null;

/**
 * Schedule a debounced history refresh.
 * Multiple calls within 500ms will result in only one actual refresh.
 */
function scheduleHistoryRefresh() {
    if (historyRefreshTimeout) {
        clearTimeout(historyRefreshTimeout);
    }
    historyRefreshTimeout = setTimeout(loadHistoryQuiet, 150);
}

/**
 * Render the session list in the panel
 */
function renderSessionList(sessions) {
    const listContainer = document.getElementById('historySessionList');
    if (!listContainer) return;

    // During startup (backend not ready), show "Loading..." instead of "No history"
    // This prevents the misleading "No chat history yet" message
    if (typeof backendReady !== 'undefined' && !backendReady) {
        showLoadingState();
        return;
    }

    // Apply current filter
    const filteredSessions = filterSessions(sessions, currentHistoryFilter);

    if (filteredSessions.length === 0) {
        showEmptyState(t('history.empty'));
        return;
    }

    let html = '';
    for (const session of filteredSessions) {
        html += renderSessionCard(session);
    }

    listContainer.innerHTML = html;
}

/**
 * Render a single session card
 */
function renderSessionCard(session) {
    const isActive = session.status === 'active';
    const agentName = session.agent_name || 'chat';

    // Check if THIS SPECIFIC session is currently running (by session ID)
    const isRunning = runningSessions.has(session.id);

    // Status: running > active > completed
    const statusClass = isRunning ? 'running' : (isActive ? 'active' : 'completed');
    const backend = session.backend || 'unknown';

    // Use backend for color class (gemini, claude, openai, etc.)
    const backendClass = getAgentColorClass(backend);

    // Format display: show agent name and backend separately
    const displayName = formatAgentDisplayName(agentName);

    const dateStr = formatSessionDate(session.created_at || session.updated_at);

    // Preview: use stored preview, or show status for running sessions
    let preview;
    let previewClass = '';
    if (isRunning && (!session.preview || session.preview === 'No messages yet')) {
        preview = t('history.agent_running');
        previewClass = 'running';
    } else {
        preview = truncateText(session.preview || t('history.no_messages'), 50);
    }

    const turnCount = session.turn_count || 0;
    const tokenCount = formatTokenCount(session.total_tokens || 0);
    const cost = session.total_cost_usd || 0;

    // Get trigger icon and label
    const triggerInfo = getTriggerInfo(session.triggered_by);

    // Build workflow info line if triggered by workflow
    let workflowInfoHtml = '';
    if (session.triggered_by === 'workflow') {
        // Extract workflow name from preview if it starts with "Workflow: "
        const workflowMatch = (session.preview || '').match(/^Workflow:\s*(\S+)/);
        const workflowName = workflowMatch ? workflowMatch[1] : (session.agent_name || 'Workflow');

        // If session is running, try to get current step from runningTasks.workflows
        let stepInfo = '';
        if (isRunning && typeof runningTasks !== 'undefined' && runningTasks.workflows) {
            // Find any workflow with step info
            for (const [wfId, instances] of Object.entries(runningTasks.workflows)) {
                for (const [runId, instance] of Object.entries(instances)) {
                    if (instance.step > 0 && instance.total_steps > 0) {
                        stepInfo = ` (${t('workflow.step')} ${instance.step}/${instance.total_steps})`;
                        break;
                    }
                }
                if (stepInfo) break;
            }
        }

        workflowInfoHtml = `<div class="history-workflow-info">
            <span class="material-icons">account_tree</span>
            Workflow: ${escapeHtml(workflowName)}${stepInfo}
        </div>`;
    }

    // [024] Check if this session is currently shown in chat
    const isCurrentChat = session.id === currentSessionId;

    return `
        <div class="history-session-card ${isActive ? 'active' : ''} ${session.triggered_by === 'workflow' ? 'workflow-session' : ''} ${isCurrentChat ? 'current-chat' : ''}"
             data-session-id="${session.id}">
            <div class="history-session-header">
                <span class="history-status-dot ${statusClass}"></span>
                <span class="history-session-agent ${backendClass}">${escapeHtml(displayName)}</span>
                <span class="history-backend-badge ${backendClass}">${escapeHtml(backend)}</span>
                <span class="history-trigger-badge" title="${triggerInfo.label}">
                    <span class="material-icons">${triggerInfo.icon}</span>
                </span>
                ${session.anonymization_enabled === true ? `<span class="history-anon-badge" title="${t('history.anonymization_active')}"><span class="material-icons">shield</span></span>` : ''}
                <span class="history-session-date">${dateStr}</span>
            </div>
            ${workflowInfoHtml}
            <div class="history-session-preview ${previewClass}">${previewClass === 'running' ? '<span class="material-icons spinning">autorenew</span> ' + escapeHtml(preview) : '"' + escapeHtml(preview) + '"'}</div>
            <div class="history-session-meta">
                <span title="Messages"><span class="material-icons">chat</span> ${turnCount}</span>
                <span title="Tokens"><span class="material-icons">token</span> ${tokenCount}</span>
                <span title="Cost"><span class="material-icons">attach_money</span> ${cost.toFixed(2)}</span>
            </div>
            <div class="history-session-actions">
                <button class="history-quick-btn primary" onclick="event.stopPropagation(); continueSession('${session.id}')" title="${t('history.open_conversation')}">
                    <span class="material-icons">play_arrow</span>
                    ${t('history.open')}
                </button>
                <button class="history-quick-btn secondary" onclick="event.stopPropagation(); showTransferMenuForSession('${session.id}')" title="${t('history.transfer_backend')}">
                    <span class="material-icons">swap_horiz</span>
                </button>
                <button class="history-quick-btn danger" onclick="event.stopPropagation(); deleteSession('${session.id}')" title="${t('history.delete_session')}">
                    <span class="material-icons">delete</span>
                </button>
            </div>
        </div>
    `;
}

/**
 * Get trigger icon and label for display
 */
function getTriggerInfo(triggeredBy) {
    const triggers = {
        'webui': { icon: 'mouse', label: t('history.trigger.webui') },
        'voice': { icon: 'mic', label: t('history.trigger.voice') },
        'email_watcher': { icon: 'mark_email_read', label: t('history.trigger.email_watcher') },
        'workflow': { icon: 'account_tree', label: t('history.trigger.workflow') },
        'api': { icon: 'api', label: t('history.trigger.api') },
        'auto_chain': { icon: 'link', label: t('history.trigger.auto_chain') || 'Auto-Chain' }
    };
    return triggers[triggeredBy] || triggers['webui'];
}

/**
 * Show empty state message
 */
function showEmptyState(message) {
    const listContainer = document.getElementById('historySessionList');
    if (!listContainer) return;

    listContainer.innerHTML = `
        <div class="history-empty-state">
            <span class="material-icons">inbox</span>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

/**
 * Show loading state during startup
 */
function showLoadingState() {
    const listContainer = document.getElementById('historySessionList');
    if (!listContainer) return;

    listContainer.innerHTML = `
        <div class="history-empty-state history-loading-state">
            <span class="material-icons spinning">autorenew</span>
            <p>${t('history.loading') || 'Loading...'}</p>
        </div>
    `;
}

/**
 * Update footer stats
 */
function updateHistoryStats(data) {
    const sessionCount = document.getElementById('historySessionCount');
    const turnCount = document.getElementById('historyTurnCount');
    const totalCostEl = document.getElementById('historyTotalCost');

    // Handle undefined data (e.g., after delete all)
    const stats = data || { total: 0, total_turns: 0, total_cost_usd: 0 };

    if (sessionCount) {
        sessionCount.textContent = `${stats.total || stats.sessions?.length || 0} sessions`;
    }
    if (turnCount) {
        turnCount.textContent = `${stats.total_turns || 0} turns`;
    }
    if (totalCostEl) {
        const cost = stats.total_cost_usd || 0;
        totalCostEl.textContent = `$${cost.toFixed(2)}`;
    }
}

// =============================================================================
// Filtering
// =============================================================================

/**
 * Filter sessions by type
 */
function filterHistory(filterType) {
    currentHistoryFilter = filterType;

    // Persist filter to localStorage
    localStorage.setItem('historyFilter', filterType);

    // Update filter chip active states
    document.querySelectorAll('.history-filter-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.filter === filterType);
    });

    // Re-render with filter
    renderSessionList(historySessionsCache);
}

/**
 * Apply filter to sessions array
 */
function filterSessions(sessions, filter) {
    if (filter === 'all') return sessions;

    return sessions.filter(session => {
        if (filter === 'active') {
            return session.status === 'active';
        }
        // Filter by agent_name or backend
        const agentName = (session.agent_name || '').toLowerCase();
        const backend = (session.backend || '').toLowerCase();
        const filterLower = filter.toLowerCase();
        return agentName.includes(filterLower) || backend.includes(filterLower);
    });
}

// =============================================================================
// Session Detail
// =============================================================================

/**
 * Show session detail panel with full conversation
 */
async function showSessionDetail(sessionId) {
    selectedSessionId = sessionId;

    // Highlight selected card
    document.querySelectorAll('.history-session-card').forEach(card => {
        card.classList.toggle('selected', card.dataset.sessionId === sessionId);
    });

    try {
        const res = await fetch(API + `/history/sessions/${sessionId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const session = await res.json();
        renderSessionDetail(session);

        // Show detail panel
        const detailPanel = document.getElementById('historySessionDetail');
        if (detailPanel) {
            detailPanel.classList.add('visible');
            historyDetailOpen = true;
        }

    } catch (error) {
        serverError('Failed to load session detail: ' + error.message);
        showToast(t('history.load_session_failed'));
    }
}

// ========== [060] Dialog History Rendering ==========

/**
 * Strip ---DIALOG_META--- block from content (for markdown rendering fallback).
 */
function stripDialogMeta(content) {
    const idx = content.indexOf('\n---DIALOG_META---\n');
    return idx >= 0 ? content.substring(0, idx) : content;
}

/**
 * Parse dialog metadata from a turn's content.
 * Returns {text, meta} or null if no metadata marker found.
 */
function parseDialogMeta(content) {
    const separator = '\n---DIALOG_META---\n';
    const idx = content.indexOf(separator);
    if (idx < 0) return null;
    const text = content.substring(0, idx);
    const jsonStr = content.substring(idx + separator.length);
    try {
        return { text, meta: JSON.parse(jsonStr) };
    } catch (e) {
        console.warn('[History] Failed to parse dialog metadata:', e);
        return null;
    }
}

/**
 * Render a read-only dialog card for history display.
 */
function renderHistoryDialogCard(text, meta, role) {
    if (role === 'assistant') {
        if (meta.type === 'question') {
            return renderHistoryQuestionCard(meta);
        } else {
            return renderHistoryConfirmationCard(meta);
        }
    } else if (role === 'user') {
        return renderHistoryDialogResponse(text, meta);
    }
    return null;
}

function renderHistoryQuestionCard(meta) {
    // Data rows (e.g. contact data shown with question)
    let dataHtml = '';
    const data = meta.data || {};
    const dataKeys = Object.keys(data).filter(k => k !== 'type');
    if (dataKeys.length > 0) {
        const rows = dataKeys.map(key =>
            `<div class="inline-question-data-row">
                <span class="data-label">${escapeHtml(key)}:</span>
                <span class="data-value">${escapeHtml(String(data[key] || ''))}</span>
            </div>`
        ).join('');
        dataHtml = `<div class="inline-question-data">${rows}</div>`;
    }

    // Options as read-only badges (not clickable buttons)
    let optionsHtml = '';
    const options = meta.options || [];
    if (options.length > 0) {
        const badges = options.map(opt =>
            `<span class="history-dialog-option">${escapeHtml(opt.label || opt.value)}</span>`
        ).join('');
        optionsHtml = `<div class="history-dialog-options">${badges}</div>`;
    }

    return `<div class="inline-question-box history-readonly">
        <div class="inline-question-content">
            <p class="inline-question-text">${escapeHtml(meta.question || '')}</p>
            ${dataHtml}
            ${optionsHtml}
        </div>
    </div>`;
}

function renderHistoryConfirmationCard(meta) {
    // Form fields as read-only display
    let fieldsHtml = '';
    const data = meta.data || {};
    const dataKeys = Object.keys(data);
    if (dataKeys.length > 0) {
        const rows = dataKeys.map(key =>
            `<div class="inline-confirm-field">
                <label>${escapeHtml(key)}</label>
                <div class="history-field-value">${escapeHtml(String(data[key] || ''))}</div>
            </div>`
        ).join('');
        fieldsHtml = `<div class="inline-confirm-fields">${rows}</div>`;
    }

    return `<div class="inline-confirm-box history-readonly">
        <div class="inline-confirm-content">
            <div class="inline-confirm-header">
                <span class="material-icons">help_outline</span>
                <h4>${t('dialog.confirmation_required') || 'Bestätigung erforderlich'}</h4>
            </div>
            <p class="inline-confirm-question">${escapeHtml(meta.question || '')}</p>
            ${fieldsHtml}
        </div>
    </div>`;
}

function renderHistoryDialogResponse(text, meta) {
    if (meta.type === 'question_response') {
        return `<div class="inline-question-answered history-readonly">
            <span class="answer-checkmark">&#10003;</span>
            ${escapeHtml(meta.selected || '')}
        </div>`;
    } else if (meta.type === 'confirmation_response') {
        if (meta.confirmed) {
            let fieldsHtml = '';
            if (meta.data && Object.keys(meta.data).length > 0) {
                const rows = Object.entries(meta.data).map(([key, val]) =>
                    `<div class="inline-question-data-row">
                        <span class="data-label">${escapeHtml(key)}:</span>
                        <span class="data-value">${escapeHtml(String(val || ''))}</span>
                    </div>`
                ).join('');
                fieldsHtml = `<div class="inline-question-data">${rows}</div>`;
            }
            return `<div class="inline-question-answered history-readonly">
                <span class="answer-checkmark">&#10003;</span>
                <strong>${t('dialog.confirmed') || 'Bestätigt'}</strong>
                ${fieldsHtml}
            </div>`;
        } else {
            return `<div class="inline-question-answered history-readonly cancelled">
                <span class="answer-checkmark">&#10007;</span>
                <strong>${t('dialog.cancelled') || 'Abgebrochen'}</strong>
            </div>`;
        }
    }
    return null;
}

// ========== End [060] ==========

/**
 * Render session detail content
 */
function renderSessionDetail(session) {
    const agentBadge = document.getElementById('detailAgentBadge');
    const backendBadge = document.getElementById('detailBackendBadge');
    const titleEl = document.getElementById('detailSessionTitle');
    const contentEl = document.getElementById('historyDetailContent');

    // V2 Link System: Load link_map from session for placeholder resolution
    if (session.link_map && typeof setLinkMap === 'function') {
        setLinkMap(session.link_map);
    }

    // Get agent display name and backend
    const agentName = session.agent_name || 'chat';
    const backend = session.backend || 'unknown';
    const displayName = formatAgentDisplayName(agentName);
    const backendClass = getAgentColorClass(backend);

    if (agentBadge) {
        agentBadge.className = 'history-session-agent ' + backendClass;
        agentBadge.textContent = displayName;
    }

    // Show backend badge if element exists
    if (backendBadge) {
        backendBadge.className = 'history-backend-badge ' + backendClass;
        backendBadge.textContent = backend;
    }

    if (titleEl) {
        // Generate title from first user message or use default
        const firstUserTurn = (session.turns || []).find(t => t.role === 'user');
        const title = firstUserTurn ? truncateText(stripDialogMeta(firstUserTurn.content), 40) : t('history.chat_session');
        titleEl.textContent = title;
    }

    if (contentEl) {
        const turns = session.turns || [];
        let html = '';

        for (const turn of turns) {
            const role = turn.role || 'user';
            const roleClass = role === 'assistant' ? 'assistant' : 'user';
            const roleLabel = role === 'assistant' ? t('conversation.assistant') : t('conversation.you');
            const content = turn.content || '';

            // [060] Check for dialog metadata
            const dialogData = parseDialogMeta(content);
            if (dialogData && dialogData.meta) {
                const cardHtml = renderHistoryDialogCard(dialogData.text, dialogData.meta, role);
                if (cardHtml) {
                    html += `
                        <div class="history-turn ${roleClass}">
                            <div class="history-turn-header">${roleLabel}</div>
                            <div class="history-turn-content">${cardHtml}</div>
                        </div>
                    `;
                    continue;
                }
            }

            html += `
                <div class="history-turn ${roleClass}">
                    <div class="history-turn-header">${roleLabel}</div>
                    <div class="history-turn-content">${escapeHtml(stripDialogMeta(content))}</div>
                </div>
            `;
        }

        contentEl.innerHTML = html || '<p style="color: var(--text-muted);">' + t('history.no_messages_in_session') + '</p>';
    }
}

/**
 * Close session detail panel
 */
function closeSessionDetail() {
    const detailPanel = document.getElementById('historySessionDetail');
    if (detailPanel) {
        detailPanel.classList.remove('visible');
        historyDetailOpen = false;
    }

    selectedSessionId = null;

    // Remove selected highlight
    document.querySelectorAll('.history-session-card.selected').forEach(card => {
        card.classList.remove('selected');
    });

    // Hide transfer menu if visible
    hideTransferMenu();
}

// =============================================================================
// Live Stream Subscription (for running sessions opened from history)
// =============================================================================

// Active live stream connection (only one at a time)
let liveStreamEventSource = null;

/**
 * Subscribe to live SSE stream for a running session
 * @param {string} taskId - The task ID to subscribe to
 * @param {HTMLElement} resultContent - The result content element to append to
 * @param {boolean} isWorkflowSession - Whether this is a workflow session
 */
function subscribeToLiveStream(taskId, resultContent, isWorkflowSession) {
    // Close any existing live stream connection
    if (liveStreamEventSource) {
        liveStreamEventSource.close();
        liveStreamEventSource = null;
    }

    console.log('[History] Subscribing to live stream for task:', taskId);

    // Add a live indicator div
    let liveDiv = resultContent.querySelector('.live-stream-indicator');
    if (!liveDiv) {
        liveDiv = document.createElement('div');
        liveDiv.className = 'live-stream-indicator';
        liveDiv.innerHTML = '<span class="material-icons">fiber_manual_record</span> Live';
        resultContent.appendChild(liveDiv);
    }

    // Create EventSource for task stream
    const eventSource = new EventSource(API + '/task/' + taskId + '/stream');
    liveStreamEventSource = eventSource;

    // Track accumulated content
    let accumulatedContent = '';
    let streamDiv = null;

    eventSource.onopen = () => {
        console.log('[History] Live stream connected for task:', taskId);
    };

    // Handle token events (streaming text)
    eventSource.addEventListener('token', (e) => {
        const data = JSON.parse(e.data);
        accumulatedContent += data.token;

        // Create or update stream div
        if (!streamDiv) {
            // Add assistant turn for streaming content
            streamDiv = document.createElement('div');
            streamDiv.className = 'conversation-turn assistant-turn streaming';
            streamDiv.innerHTML = `
                <div class="turn-header"><span class="material-icons">smart_toy</span> DeskAgent</div>
                <div class="turn-content"></div>
            `;
            // Insert before live indicator
            if (liveDiv && liveDiv.parentNode) {
                liveDiv.parentNode.insertBefore(streamDiv, liveDiv);
            } else {
                resultContent.appendChild(streamDiv);
            }
        }

        // Update content (render markdown)
        const contentDiv = streamDiv.querySelector('.turn-content');
        if (contentDiv) {
            // Render markdown with chart support
            if (typeof renderMarkdownWithCharts === 'function') {
                contentDiv.innerHTML = renderMarkdownWithCharts(accumulatedContent);
            } else {
                contentDiv.textContent = accumulatedContent;
            }
        }

        // Auto-scroll to bottom
        resultContent.scrollTop = resultContent.scrollHeight;
    });

    // Handle content_sync events (full content replacement)
    eventSource.addEventListener('content_sync', (e) => {
        const data = JSON.parse(e.data);
        accumulatedContent = data.content;

        if (streamDiv) {
            const contentDiv = streamDiv.querySelector('.turn-content');
            if (contentDiv) {
                // Render markdown with chart support
                if (typeof renderMarkdownWithCharts === 'function') {
                    contentDiv.innerHTML = renderMarkdownWithCharts(accumulatedContent);
                } else {
                    contentDiv.textContent = accumulatedContent;
                }
            }
        }
        resultContent.scrollTop = resultContent.scrollHeight;
    });

    // Handle task_complete event
    eventSource.addEventListener('task_complete', (e) => {
        console.log('[History] Live stream task complete');
        cleanupLiveStream(liveDiv, streamDiv);
        eventSource.close();
        liveStreamEventSource = null;
    });

    // Handle errors
    eventSource.onerror = (e) => {
        console.log('[History] Live stream error or closed');
        cleanupLiveStream(liveDiv, streamDiv);
        eventSource.close();
        liveStreamEventSource = null;
    };
}

/**
 * Clean up live stream UI elements
 */
function cleanupLiveStream(liveDiv, streamDiv) {
    if (liveDiv && liveDiv.parentNode) {
        liveDiv.remove();
    }
    if (streamDiv) {
        streamDiv.classList.remove('streaming');
    }
}

// =============================================================================
// Session Actions
// =============================================================================

/**
 * Continue a session (load history and open chat)
 */
async function continueSession(sessionId) {
    try {
        // [024] Track which session is now shown in chat
        currentSessionId = sessionId;
        document.dispatchEvent(new CustomEvent('da:current-session-changed', { detail: { sessionId: sessionId } }));

        // First fetch the full session with all turns
        const sessionRes = await fetch(API + `/history/sessions/${sessionId}`);
        if (!sessionRes.ok) throw new Error(`HTTP ${sessionRes.status}`);
        const session = await sessionRes.json();

        // [030] ViewContext: Check if this session has a running task
        const runningTaskId = ViewContext.getTaskForSession(sessionId);
        if (runningTaskId) {
            // [073] Ensure TaskState exists (may be missing after SSE-Reconnect/Page-Reload)
            let taskState = ViewContext.getTask(runningTaskId);
            if (!taskState) {
                taskState = ViewContext.registerTask(
                    runningTaskId, sessionId,
                    session.agent_name || 'chat',
                    session.backend || 'unknown',
                    null, 'reconnect'
                );
                // [073] Set overlay startTime so timer doesn't show 0
                taskState.overlay.startTime = Date.now();
                // idle -> loading is a valid transition
                ViewContext.transitionTask(runningTaskId, 'loading');
            }
            ViewContext.switchView(runningTaskId, sessionId);
        } else {
            // Completed session - create virtual TaskState from session metadata
            const taskState = ViewContext.createFromSession(session);
            ViewContext.switchView(taskState.taskId, sessionId);
        }

        // V2 Link System: Load link_map from session for placeholder resolution
        if (session.link_map && typeof setLinkMap === 'function') {
            setLinkMap(session.link_map);
        }

        // Check if this is a workflow session - use dedicated workflow view
        const isWorkflowSession = session.triggered_by === 'workflow' || session.backend === 'workflow';

        if (isWorkflowSession) {
            // Use workflow-specific display
            openWorkflowFromHistory(session);
            return;
        }

        // Regular agent session - continue with chat view
        // Then call continue endpoint to mark session as continued
        const continueRes = await fetch(API + `/history/sessions/${sessionId}/continue`, {
            method: 'POST'
        });
        if (!continueRes.ok) throw new Error(`HTTP ${continueRes.status}`);

        // FIX [039]: Parse response to get sdk_session_id for resume
        const continueData = await continueRes.json();
        if (continueData.sdk_session_id) {
            window._resumeSessionId = continueData.sdk_session_id;
            console.log('[History] SDK session ID stored for resume:', continueData.sdk_session_id.substring(0, 20) + '...');
        }

        // Close history panel (unless pinned)
        if (!historyPinned) {
            closeHistoryPanel();
        }

        const agentName = session.agent_name || 'chat';
        const backend = session.backend || agentName;

        // Set chat globals
        if (typeof currentChatBackend !== 'undefined') currentChatBackend = backend;
        if (typeof currentChatName !== 'undefined') currentChatName = agentName;

        // Find and pin the corresponding tile
        let tile = document.getElementById('tile-' + agentName) || document.getElementById('tile-' + backend);

        // [074] Hidden tiles can't be pinned visually - use session tile instead
        if (tile && tile.dataset.hidden === 'true') {
            tile = null;
        }

        if (!tile && typeof createSessionMiniTile === 'function') {
            tile = createSessionMiniTile(agentName, backend, sessionId);
        }

        if (tile && typeof pinTile === 'function') {
            pinTile(tile);
        }

        // Hide tiles and show prompt area for regular sessions
        if (typeof hideTiles === 'function') hideTiles();
        if (typeof showPromptArea === 'function') showPromptArea();

        // Get result elements
        const resultPanel = document.getElementById('resultPanel');
        const resultTitle = document.getElementById('resultTitle');
        const resultContent = document.getElementById('resultContent');
        const promptInput = document.getElementById('promptInput');

        if (resultTitle) resultTitle.textContent = `Chat: ${backend}`;
        if (promptInput) promptInput.placeholder = `Chat mit ${backend}...`;

        // Build conversation HTML from turns
        let html = '';
        const turns = session.turns || [];

        if (turns.length === 0) {
            html = `<div class="chat-intro">
                <span class="material-icons">chat</span>
                <p>${t('history.start_conversation', {backend: backend})}</p>
            </div>`;
        } else {
            for (const turn of turns) {
                const content = turn.content || '';

                // [060] Check for dialog metadata
                const dialogData = parseDialogMeta(content);
                if (dialogData && dialogData.meta) {
                    const cardHtml = renderHistoryDialogCard(dialogData.text, dialogData.meta, turn.role);
                    if (cardHtml) {
                        if (turn.role === 'user') {
                            html += `<div class="conversation-turn user-turn">
                                <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
                                <div class="turn-content">${cardHtml}</div>
                            </div>`;
                        } else {
                            html += `<div class="conversation-turn assistant-turn">
                                <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                                <div class="turn-content">${cardHtml}</div>
                            </div>`;
                        }
                        continue;
                    }
                }

                // Fallback: normal rendering (strip dialog meta to prevent --- showing as <hr>)
                const cleanContent = stripDialogMeta(content);
                if (turn.role === 'user') {
                    html += `<div class="conversation-turn user-turn">
                        <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
                        <div class="turn-content">${escapeHtml(cleanContent)}</div>
                    </div>`;
                } else if (turn.role === 'assistant') {
                    // Render markdown with chart support
                    const parsedHtml = (typeof renderMarkdownWithCharts === 'function')
                        ? renderMarkdownWithCharts(cleanContent)
                        : escapeHtml(cleanContent).replace(/\n/g, '<br>');
                    html += `<div class="conversation-turn assistant-turn">
                        <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                        <div class="turn-content">${parsedHtml}</div>
                    </div>`;
                }
            }
        }

        if (resultContent) {
            resultContent.innerHTML = html;
            resultContent.className = 'result-content';
        }
        if (resultPanel) resultPanel.classList.add('visible');

        // [067] D14: Migrate to ViewContext API
        ViewContext.viewedIsAppendMode = true;
        if (typeof userPromptDisplayed !== 'undefined') userPromptDisplayed = true;
        if (promptInput) promptInput.focus();

        if (resultContent) {
            resultContent.scrollTop = resultContent.scrollHeight;
        }

        // [066] A4: Detect task phase for running tasks (overlay handled by transitionTask)
        if (runningTaskId) {
            try {
                const statusRes = await fetch(API + '/task/' + runningTaskId + '/status');
                const statusData = await statusRes.json();
                if (statusData.pending_input) {
                    // Show dialog directly - showConfirmationDialog handles phase transition
                    showConfirmationDialog(runningTaskId, statusData.pending_input, tile, agentName, true);
                } else if (statusData.status === 'running') {
                    // Reconnect SSE for running task
                    // [073] loading->streaming is valid after Phase 1 registerTask+transitionTask('loading')
                    ViewContext.transitionTask(runningTaskId, 'streaming');
                    streamTask(runningTaskId, tile, agentName, true);
                }
            } catch (e) {
                console.log('[History] Phase detection failed:', e.message);
            }
        } else {
            hideProcessingOverlay();
        }

        showToast(t('history.session_resumed'));
        serverLog('Continued session: ' + sessionId);

    } catch (error) {
        serverError('Failed to continue session: ' + error.message);
        showToast(t('history.continue_session_failed'));
    }
}

/**
 * Open a workflow session from history in workflow view format.
 * Shows the workflow tile with steps + input + response (read-only).
 */
function openWorkflowFromHistory(session) {
    console.log('[History] Opening workflow session:', session.id, session.agent_name);

    // Close history panel (unless pinned)
    if (!historyPinned) {
        closeHistoryPanel();
    }

    // Hide tiles and prompt area (workflow is read-only)
    if (typeof hideTiles === 'function') hideTiles();
    if (typeof hidePromptArea === 'function') hidePromptArea();

    // Get result elements
    const resultPanel = document.getElementById('resultPanel');
    const resultTitle = document.getElementById('resultTitle');
    const resultContent = document.getElementById('resultContent');

    const workflowName = session.agent_name || 'Workflow';

    if (resultTitle) {
        resultTitle.textContent = workflowName;
    }

    // Build workflow view HTML
    let html = '';

    // Workflow header with icon
    html += `<div class="workflow-history-header">
        <span class="material-icons">account_tree</span>
        <span>Workflow</span>
    </div>`;

    // Workflow steps (completed)
    html += `<div class="workflow-steps-history">
        <div class="workflow-step completed"><span class="material-icons">check_circle</span> Start Processing</div>
        <div class="workflow-step completed"><span class="material-icons">check_circle</span> Check Blocklist</div>
        <div class="workflow-step completed"><span class="material-icons">check_circle</span> Generate Reply</div>
        <div class="workflow-step completed"><span class="material-icons">check_circle</span> Send And Archive</div>
        <div class="workflow-step completed final"><span class="material-icons">check_circle</span> ${t('workflow.workflow_completed')}</div>
    </div>`;

    // Turns: input email + AI response
    const turns = session.turns || [];
    for (const turn of turns) {
        if (turn.role === 'user') {
            // [060] Check for dialog response metadata
            const dialogData = parseDialogMeta(turn.content);
            if (dialogData && dialogData.meta) {
                const cardHtml = renderHistoryDialogCard(dialogData.text, dialogData.meta, 'user');
                if (cardHtml) {
                    html += `<div class="conversation-turn user-turn">
                        <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
                        <div class="turn-content">${cardHtml}</div>
                    </div>`;
                    continue;
                }
            }
            // Input email
            html += `<div class="conversation-turn user-turn">
                <div class="turn-header"><span class="material-icons">email</span> ${t('workflow.incoming_email')}</div>
                <div class="turn-content" style="white-space:pre-wrap">${escapeHtml(stripDialogMeta(turn.content))}</div>
            </div>`;
        } else if (turn.role === 'assistant') {
            // [060] Check for dialog metadata
            const dialogData = parseDialogMeta(turn.content);
            if (dialogData && dialogData.meta) {
                const cardHtml = renderHistoryDialogCard(dialogData.text, dialogData.meta, 'assistant');
                if (cardHtml) {
                    html += `<div class="conversation-turn assistant-turn">
                        <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                        <div class="turn-content">${cardHtml}</div>
                    </div>`;
                    continue;
                }
            }
            // AI response - render markdown with chart support
            const cleanContent = stripDialogMeta(turn.content);
            const parsedHtml = (typeof renderMarkdownWithCharts === 'function')
                ? renderMarkdownWithCharts(cleanContent)
                : escapeHtml(cleanContent).replace(/\n/g, '<br>');
            html += `<div class="conversation-turn assistant-turn">
                <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                <div class="turn-content">${parsedHtml}</div>
            </div>`;
        }
    }

    if (resultContent) {
        resultContent.innerHTML = html;
        resultContent.className = 'result-content workflow-history-view';
    }
    if (resultPanel) resultPanel.classList.add('visible');

    // Create and pin a workflow mini-tile
    if (typeof createWorkflowMiniTile === 'function') {
        const tile = createWorkflowMiniTile(workflowName, session.id);
        if (tile && typeof pinTile === 'function') {
            pinTile(tile);
        }
    }

    showToast(t('history.workflow_session_opened'));
    serverLog('Opened workflow from history: ' + session.id);
}

/**
 * Continue the currently selected session
 */
function continueSelectedSession() {
    if (selectedSessionId) {
        continueSession(selectedSessionId);
    }
}

/**
 * Delete a session - shows inline confirmation in the card
 */
function deleteSession(sessionId) {
    showInlineDeleteConfirm(sessionId);
}

/**
 * Show inline delete confirmation inside the session card
 */
function showInlineDeleteConfirm(sessionId) {
    const card = document.querySelector(`.history-session-card[data-session-id="${sessionId}"]`);
    if (!card) return;

    // Store original content for restoration
    card.dataset.originalContent = card.innerHTML;

    // Replace with confirmation UI
    card.classList.add('confirming-delete');
    card.innerHTML = `
        <div class="history-delete-confirm">
            <span class="material-icons">delete_forever</span>
            <span class="history-delete-text">${t('history.delete_this_session')}</span>
            <div class="history-delete-actions">
                <button class="history-quick-btn secondary" onclick="event.stopPropagation(); cancelInlineDelete('${sessionId}')">
                    ${t('dialog.cancel')}
                </button>
                <button class="history-quick-btn danger-fill" onclick="event.stopPropagation(); confirmInlineDelete('${sessionId}')">
                    ${t('dialog.delete')}
                </button>
            </div>
        </div>
    `;
}

/**
 * Cancel inline delete - restore original card content
 */
function cancelInlineDelete(sessionId) {
    const card = document.querySelector(`.history-session-card[data-session-id="${sessionId}"]`);
    if (!card || !card.dataset.originalContent) return;

    // Restore original content
    card.innerHTML = card.dataset.originalContent;
    card.classList.remove('confirming-delete');
    delete card.dataset.originalContent;
}

/**
 * Confirm inline delete - actually delete the session
 */
async function confirmInlineDelete(sessionId) {
    const card = document.querySelector(`.history-session-card[data-session-id="${sessionId}"]`);

    try {
        const res = await fetch(API + `/history/sessions/${sessionId}`, {
            method: 'DELETE'
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        // Animate card removal
        if (card) {
            card.style.transition = 'all 0.3s ease';
            card.style.opacity = '0';
            card.style.transform = 'translateX(100%)';
            card.style.maxHeight = card.offsetHeight + 'px';

            setTimeout(() => {
                card.style.maxHeight = '0';
                card.style.padding = '0';
                card.style.margin = '0';
                card.style.border = 'none';
            }, 150);

            setTimeout(() => {
                card.remove();
            }, 400);
        }

        // Remove from cache
        historySessionsCache = historySessionsCache.filter(s => s.id !== sessionId);

        // Close detail if this session was selected
        if (selectedSessionId === sessionId) {
            closeSessionDetail();
        }

        // Check if list is now empty
        setTimeout(() => {
            if (historySessionsCache.length === 0) {
                showEmptyState(t('history.empty'));
            }
        }, 450);

        showToast(t('history.session_deleted'));
        serverLog('Deleted session: ' + sessionId);

    } catch (error) {
        serverError('Failed to delete session: ' + error.message);
        showToast(t('history.delete_session_failed'));

        // Restore card on error
        cancelInlineDelete(sessionId);
    }
}

// =============================================================================
// Delete All Sessions
// =============================================================================

/**
 * Show delete all confirmation dialog
 */
function showDeleteAllConfirm() {
    const sessionCount = historySessionsCache.length;
    if (sessionCount === 0) {
        showToast(t('history.no_sessions_to_delete'));
        return;
    }

    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.id = 'deleteAllOverlay';
    overlay.className = 'history-delete-overlay';
    overlay.innerHTML = `
        <div class="history-delete-modal">
            <span class="material-icons delete-all-icon">delete_sweep</span>
            <h3>${t('history.delete_all_sessions', {count: sessionCount})}</h3>
            <p>${t('history.action_cannot_be_undone')}</p>
            <div class="history-delete-modal-actions">
                <button class="history-quick-btn secondary" onclick="cancelDeleteAll()">${t('dialog.cancel')}</button>
                <button class="history-quick-btn danger-fill" onclick="confirmDeleteAll()">${t('history.delete_all_btn')}</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    // Animate in
    requestAnimationFrame(() => overlay.classList.add('visible'));
}

/**
 * Cancel delete all
 */
function cancelDeleteAll() {
    const overlay = document.getElementById('deleteAllOverlay');
    if (overlay) {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    }
}

/**
 * Confirm delete all sessions
 */
async function confirmDeleteAll() {
    const overlay = document.getElementById('deleteAllOverlay');

    try {
        const res = await fetch(API + '/history/sessions', {
            method: 'DELETE'
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();

        // Close overlay
        if (overlay) {
            overlay.classList.remove('visible');
            setTimeout(() => overlay.remove(), 200);
        }

        // Clear cache and UI
        historySessionsCache = [];
        closeSessionDetail();
        showEmptyState(t('history.empty'));
        updateHistoryStats();

        showToast(t('history.deleted_sessions', {count: data.deleted || t('header.all').toLowerCase()}));
        serverLog('Deleted all sessions');

    } catch (error) {
        serverError('Failed to delete all sessions: ' + error.message);
        showToast(t('history.delete_sessions_failed'));

        // Close overlay on error too
        if (overlay) {
            overlay.classList.remove('visible');
            setTimeout(() => overlay.remove(), 200);
        }
    }
}

// =============================================================================
// Transfer Feature
// =============================================================================

/**
 * Show transfer menu for a specific session
 */
function showTransferMenuForSession(sessionId) {
    selectedSessionId = sessionId;
    showTransferMenu();
}

/**
 * Show the transfer agent menu
 */
function showTransferMenu() {
    const detailPanel = document.getElementById('historySessionDetail');

    // Create transfer menu if it doesn't exist
    let menu = document.getElementById('historyTransferMenu');
    if (!menu) {
        menu = document.createElement('div');
        menu.id = 'historyTransferMenu';
        menu.className = 'history-transfer-menu';
        menu.innerHTML = `
            <div class="history-transfer-menu-header">${t('history.transfer_to')}</div>
            <div class="history-transfer-menu-item" onclick="transferSession('gemini')">
                <span class="material-icons">smart_toy</span>
                <span>Gemini</span>
            </div>
            <div class="history-transfer-menu-item" onclick="transferSession('claude')">
                <span class="material-icons">psychology</span>
                <span>Claude</span>
            </div>
            <div class="history-transfer-menu-item" onclick="transferSession('openai')">
                <span class="material-icons">auto_awesome</span>
                <span>OpenAI</span>
            </div>
        `;

        if (detailPanel) {
            detailPanel.appendChild(menu);
        }
    }

    menu.classList.add('visible');
}

/**
 * Hide the transfer menu
 */
function hideTransferMenu() {
    const menu = document.getElementById('historyTransferMenu');
    if (menu) {
        menu.classList.remove('visible');
    }
}

/**
 * Transfer session to a different agent
 */
async function transferSession(targetAgent) {
    if (!selectedSessionId) return;

    hideTransferMenu();

    try {
        const res = await fetch(API + `/history/sessions/${selectedSessionId}/transfer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_agent: targetAgent })
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        // Close panels and reload
        closeHistoryPanel();

        // Find and pin the target tile before opening chat
        let tile = document.getElementById('tile-' + targetAgent);

        // [074] Hidden tiles can't be pinned visually - use session tile instead
        if (tile && tile.dataset.hidden === 'true') {
            tile = null;
        }

        // Fallback: Create mini-tile if not found
        if (!tile && typeof createSessionMiniTile === 'function') {
            tile = createSessionMiniTile(targetAgent, targetAgent, '');
        }
        if (tile && typeof pinTile === 'function') {
            pinTile(tile);
        }

        // Start chat with new agent
        openChat(targetAgent, targetAgent);

        showToast(t('history.transferred_to', {target: targetAgent}));
        serverLog(`Transferred session ${selectedSessionId} to ${targetAgent}`);

    } catch (error) {
        serverError('Failed to transfer session: ' + error.message);
        showToast(t('history.transfer_failed'));
    }
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Get CSS class for backend badge color.
 * Maps backend identifiers to color classes.
 */
function getAgentColorClass(backend) {
    if (!backend) return 'default';

    const backendLower = backend.toLowerCase();

    // Direct matches for backend types
    if (backendLower === 'gemini' || backendLower === 'gemini_adk') return 'gemini';
    if (backendLower === 'claude' || backendLower === 'claude_sdk' || backendLower === 'claude_cli') return 'claude';
    if (backendLower === 'openai' || backendLower === 'openai_api') return 'openai';
    if (backendLower === 'mistral' || backendLower === 'mistral_local') return 'mistral';
    if (backendLower === 'qwen' || backendLower === 'ollama') return 'ollama';

    // Partial matches as fallback
    if (backendLower.includes('gemini')) return 'gemini';
    if (backendLower.includes('claude')) return 'claude';
    if (backendLower.includes('openai') || backendLower.includes('gpt')) return 'openai';
    if (backendLower.includes('mistral')) return 'mistral';
    if (backendLower.includes('ollama') || backendLower.includes('qwen')) return 'ollama';

    return 'default';
}

/**
 * Format agent name for display.
 * Converts internal names like "chat_claude" to friendly names like "Chat".
 */
function formatAgentDisplayName(agentName) {
    if (!agentName) return 'Chat';

    // Remove backend suffixes to get the base agent type
    let baseName = agentName
        .replace(/_claude$/i, '')
        .replace(/_gemini$/i, '')
        .replace(/_openai$/i, '')
        .replace(/_sdk$/i, '')
        .replace(/_api$/i, '');

    // Capitalize first letter and handle known agent types
    const displayNames = {
        'chat': 'Chat',
        'reply_email': 'Reply Email',
        'daily_check': 'Daily Check',
        'create_offer': 'Create Offer',
        'create_invoice': 'Create Invoice',
        'check_payments': 'Check Payments',
        'check_support': 'Check Support'
    };

    return displayNames[baseName.toLowerCase()] ||
           baseName.charAt(0).toUpperCase() + baseName.slice(1).replace(/_/g, ' ');
}

/**
 * Format session date for display
 */
function formatSessionDate(timestamp) {
    if (!timestamp) return '';

    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
        // Today - show time
        return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } else if (diffDays === 1) {
        return t('history.yesterday');
    } else if (diffDays < 7) {
        return t('history.days_ago', {days: diffDays});
    } else {
        return date.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' });
    }
}

/**
 * Format token count for display
 */
function formatTokenCount(tokens) {
    if (tokens >= 1000) {
        return (tokens / 1000).toFixed(1) + 'k';
    }
    return tokens.toString();
}

/**
 * Truncate text with ellipsis
 */
function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =============================================================================
// Event Listeners
// =============================================================================

let peekTimeout = null;
let closeTimeout = null;
let isMouseOverHistoryArea = false;

document.addEventListener('DOMContentLoaded', function() {
    const panel = document.getElementById('historyPanel');
    const edgeTrigger = document.getElementById('historyEdgeTrigger');
    const detailPanel = document.getElementById('historySessionDetail');
    const pinBtn = document.getElementById('historyPinBtn');

    // Restore pinned state from server preferences (HISTORY_PINNED is injected by backend)
    if (typeof HISTORY_PINNED !== 'undefined' && HISTORY_PINNED && panel) {
        historyPinned = true;
        panel.classList.add('pinned', 'open');
        document.body.classList.add('history-pinned');
        historyPanelOpen = true;
        if (pinBtn) pinBtn.title = t('history.unpin');
        if (edgeTrigger) edgeTrigger.classList.add('hidden');
        // Load history data
        loadHistory();
        console.log('[History] Restored pinned state from preferences');
    }

    // Restore filter from localStorage
    const savedFilter = localStorage.getItem('historyFilter');
    if (savedFilter) {
        currentHistoryFilter = savedFilter;
        // Update filter chip UI
        document.querySelectorAll('.history-filter-chip').forEach(chip => {
            chip.classList.toggle('active', chip.dataset.filter === savedFilter);
        });
        console.log('[History] Restored filter from localStorage:', savedFilter);
    }

    // Edge trigger click - toggle panel (no auto-open on hover)
    if (edgeTrigger) {
        edgeTrigger.addEventListener('click', function() {
            if (historyPanelOpen) {
                closeHistoryPanel();
            } else {
                openHistoryPanel();
            }
        });
    }

    // Panel stays open until explicitly closed (no auto-close on mouse leave)

    // Close detail panel when clicking outside
    document.addEventListener('click', function(e) {
        const detailPanel = document.getElementById('historySessionDetail');
        const historyPanel = document.getElementById('historyPanel');

        if (historyDetailOpen && detailPanel && !detailPanel.contains(e.target) &&
            historyPanel && !historyPanel.contains(e.target)) {
            closeSessionDetail();
        }
    });

    // Keyboard shortcut to close (Escape)
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            if (historyDetailOpen) {
                closeSessionDetail();
            } else if (historyPanelOpen) {
                closeHistoryPanel();
            }
        }
    });

    // Listen for task events via DOM CustomEvents (dispatched by webui-tasks.js).
    // Using document as event bus instead of taskEventSource directly ensures
    // listeners survive SSE reconnects (root cause of sessions not appearing in history).

    // When a task ends, refresh history if panel is open
    document.addEventListener('da:task-ended', (e) => {
        console.log('[History] Task ended event received');
        // Small delay to let runningTasks update first
        setTimeout(() => {
            scheduleHistoryRefresh();
            if (historyPanelOpen && historySessionsCache.length > 0) {
                renderSessionList(historySessionsCache);
            }
        }, 100);
    });

    // When a task starts, update status dots immediately
    document.addEventListener('da:task-started', (e) => {
        console.log('[History] Task started event received');
        setTimeout(() => {
            if (historyPanelOpen && historySessionsCache.length > 0) {
                renderSessionList(historySessionsCache);
            }
        }, 100);
    });

    // Initial state - populate running sessions from server
    document.addEventListener('da:active-tasks', (e) => {
        const data = e.detail;
        console.log('[History] Active tasks received:', data);
        if (data.running_sessions && Array.isArray(data.running_sessions)) {
            runningSessions.clear();
            data.running_sessions.forEach(sid => runningSessions.add(sid));
            console.log('[History] Initialized running sessions:', runningSessions.size);
            if (historyPanelOpen && historySessionsCache.length > 0) {
                renderSessionList(historySessionsCache);
            }
        }
        // [072] Populate session-to-task mapping for thinking overlay on history switch
        if (data.session_task_map && typeof data.session_task_map === 'object') {
            for (const [sid, tid] of Object.entries(data.session_task_map)) {
                if (tid) {
                    sessionTaskMap[sid] = tid;
                    ViewContext.mapSessionToTask(sid, tid);
                }
            }
        }
    });

    // Session started - add to running sessions and refresh history immediately
    // No debounce: new session is a rare, important event that should appear instantly
    document.addEventListener('da:session-started', (e) => {
        const data = e.detail;
        console.log('[History] Session started:', data.session_id);
        if (data.session_id) {
            runningSessions.add(data.session_id);
            loadHistoryQuiet();
        }
    });

    // Session ended - remove from running sessions and refresh history
    document.addEventListener('da:session-ended', (e) => {
        const data = e.detail;
        console.log('[History] Session ended:', data.session_id);
        if (data.session_id) {
            runningSessions.delete(data.session_id);
            scheduleHistoryRefresh();
        }
    });

    // [024] Current chat session changed - update highlight in history panel
    document.addEventListener('da:current-session-changed', (e) => {
        const sessionId = e.detail ? e.detail.sessionId : null;
        console.log('[History] Current chat session changed:', sessionId);
        highlightCurrentChatSession(sessionId);
    });

    // Workflow step - re-render to show current step in workflow sessions
    document.addEventListener('da:workflow-step', (e) => {
        console.log('[History] Workflow step event received');
        if (historyPanelOpen && historySessionsCache.length > 0) {
            renderSessionList(historySessionsCache);
        }
    });

    console.log('[History] DOM event listeners attached (reconnect-safe)');
});
