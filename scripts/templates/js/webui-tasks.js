/**
 * WebUI Tasks Module
 * Task execution, polling, SSE streaming, result display.
 * Depends on: webui-core.js (state), webui-ui.js (UI helpers), webui-dialogs.js (dialogs)
 */

// Task status classification - used for SSE lifecycle decisions
// Active: running, pending_input (task is alive, SSE stays open)
// Terminal: done, error, cancelled (task ended, SSE can close)
const TERMINAL_TASK_STATES = ['done', 'error', 'cancelled'];

// =============================================================================
// Token Estimation from Cost
// =============================================================================

/**
 * Estimate total tokens from cost_usd when token counts are not available.
 * Uses average price: ~$5.40/1M tokens (80% input @ $3, 20% output @ $15)
 * Returns formatted string with "~" prefix or null if no cost.
 */
function estimateTokensFromCost(costUsd) {
    if (!costUsd || costUsd <= 0) return null;
    // Average price per token: (0.8 * $3 + 0.2 * $15) / 1M = $5.40 / 1M
    const tokensPerDollar = 185185;  // 1M / 5.40
    const estimated = Math.round(costUsd * tokensPerDollar);
    if (estimated < 1000) return '~' + estimated;
    if (estimated < 1000000) return '~' + (estimated / 1000).toFixed(1) + 'K';
    return '~' + (estimated / 1000000).toFixed(2) + 'M';
}

// =============================================================================
// Tool Metadata (loaded dynamically from MCP servers)
// =============================================================================

// Cached tool metadata from backend
let toolMetadata = {};

/**
 * Load tool metadata from backend API.
 * Called once on page load, provides icons/colors for tool badges.
 */
async function loadToolMetadata() {
    try {
        const response = await fetch(API + '/api/tool-metadata');
        if (response.ok) {
            toolMetadata = await response.json();
            serverLog('[Tools] Loaded metadata for ' + Object.keys(toolMetadata).length + ' MCPs');
        }
    } catch (e) {
        serverLog('[Tools] WARNING: Could not load tool metadata: ' + e);
    }
}

/**
 * Update stats bar from task data (AI, Model, Duration).
 * Called immediately on poll to show stats before streaming content arrives.
 * [030] Also writes to ViewContext TaskState for the viewed task.
 */
function updateStatsFromTask(taskData) {
    if (!taskData) return;

    // [030] Write to TaskState if we have a task ID
    const viewedTaskId = ViewContext.viewedTaskId;
    if (viewedTaskId) {
        ViewContext.updateTaskStats(viewedTaskId, {
            backend: taskData.ai_backend || null,
            model: taskData.model || null
        });
    }

    // Show the stats bar
    const statsEl = document.getElementById('resultStats');
    if (statsEl) statsEl.style.display = 'flex';

    // Update AI backend
    if (taskData.ai_backend) {
        const el = document.getElementById('statBackend');
        if (el) {
            el.textContent = taskData.ai_backend;
            el.className = 'stat-value ' + taskData.ai_backend;
        }
    }

    // Update model
    if (taskData.model) {
        const el = document.getElementById('statModel');
        if (el) el.textContent = taskData.model;
    }

    // Update duration from loadingStartTime
    if (loadingStartTime) {
        const elapsed = ((Date.now() - loadingStartTime) / 1000).toFixed(1);
        const el = document.getElementById('statDuration');
        if (el) el.textContent = elapsed + 's';
    }
}

// =============================================================================
// SSE Streaming Configuration
// =============================================================================

// Feature flag: Set to true to use SSE streaming instead of polling
const USE_SSE_STREAMING = true;

// Current EventSource connections
let activeEventSources = {};

// Session to task ID mapping (for subscribing to live streams from history)
// [030] Legacy compat: backed by ViewContext.sessionTaskMap
let sessionTaskMap = {};

/**
 * Get task ID for a running session (used by history module)
 * @param {string} sessionId - The session ID
 * @returns {string|null} The task ID or null if session not running
 */
function getTaskIdForSession(sessionId) {
    // [030] Check ViewContext first, then legacy fallback
    return ViewContext.getTaskForSession(sessionId) || sessionTaskMap[sessionId] || null;
}

// =============================================================================
// Task Cancellation
// =============================================================================

// #9 - Cancel timeout for deadlock prevention
let cancelTimeoutId = null;

async function cancelCurrentTask() {
    // #6 - Check both currentTaskId and pendingTaskId for cancellation
    const taskIdToCancel = currentTaskId || pendingTaskId;
    if (!taskIdToCancel) return;

    // Close SSE connection immediately to stop receiving any more content
    cancelSSEConnection(taskIdToCancel);

    // Get the cancel button from Thinking Overlay (aiProcessingCancel)
    const cancelBtn = document.getElementById('aiProcessingCancel');
    if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.innerHTML = '<span class="material-icons">hourglass_empty</span> ' + t('task.cancelling');
    }

    // Mark task as cancelled IMMEDIATELY to stop polling loop
    cancelRequestedForTask = taskIdToCancel;

    // #9 - Set timeout fallback: force reset UI if task doesn't respond within 5s
    cancelTimeoutId = setTimeout(() => {
        serverLog('[Cancel] Timeout reached, forcing UI reset');
        forceResetUIState(taskIdToCancel);
    }, 5000);

    try {
        const response = await fetch(API + '/task/' + taskIdToCancel + '/cancel', { method: 'POST' });
        const result = await response.json();
        serverLog('[Cancel] Response: ' + JSON.stringify(result));

        // #9 - Clear timeout since we got a response
        if (cancelTimeoutId) {
            clearTimeout(cancelTimeoutId);
            cancelTimeoutId = null;
        }

        // Always return to tiles after cancel request (regardless of server response)
        // The task might already be done, but user explicitly wanted to cancel/return
        forceResetUIState(taskIdToCancel);
        serverLog('[Cancel] Returned to tiles');

    } catch (e) {
        serverLog('[Cancel] ERROR: Cancel failed: ' + e);
        // #9 - Clear timeout on error
        if (cancelTimeoutId) {
            clearTimeout(cancelTimeoutId);
            cancelTimeoutId = null;
        }
        // Even on error, return to tiles - user wanted to cancel
        forceResetUIState(taskIdToCancel);
    } finally {
        // Reset button state (may have been hidden already)
        const btn = document.getElementById('aiProcessingCancel');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="material-icons">close</span> ' + t('processing.cancel') + ' <span class="cancel-hint">' + t('processing.cancel_hint') + '</span>';
        }
    }
}

// #9 - Unified cleanup logic for cancel deadlock prevention
function forceResetUIState(taskId) {
    // Clear cancel-related state
    if (cancelRequestedForTask === taskId) {
        cancelRequestedForTask = null;
    }
    if (currentTaskId === taskId) {
        currentTaskId = null;
    }
    // #6 - Also clear pendingTaskId
    if (pendingTaskId === taskId) {
        pendingTaskId = null;
    }

    // [024] Clear current session highlight on force reset
    if (currentSessionId) {
        currentSessionId = null;
        document.dispatchEvent(new CustomEvent('da:current-session-changed', { detail: { sessionId: null } }));
    }

    // Close any remaining SSE connection
    cancelSSEConnection(taskId);

    // [064] Phase -> idle (force reset) - handles overlay/loading/isAppendMode via _syncDerivedGlobals
    ViewContext.transitionTask(taskId, 'idle');

    // [065] Redundant calls removed (A1) - transitionTask handles showThinkingOverlay, setLoading, isAppendMode
    showTiles();
}

// =============================================================================
// Task Polling (fallback for when SSE is not available)
// =============================================================================

async function pollTask(taskId, tile, name, isAgent) {
    // IMMEDIATE CHECK: If this task was cancelled, use rapid polling to pick up status
    const wasCancelled = (cancelRequestedForTask === taskId);

    try {
        const res = await fetch(API + '/task/' + taskId);
        const data = await res.json();

        if (data.status === 'running') {
            // If cancel was requested, use very fast polling (100ms) to catch status change quickly
            if (wasCancelled) {
                serverLog('[Poll] Rapid polling for cancelled task: ' + taskId);
                setTimeout(() => pollTask(taskId, tile, name, isAgent), 100);
                return;
            }

            // Update stats bar immediately (AI, Model) - even before streaming content
            updateStatsFromTask(data);

            // Update streaming content first (before showing any dialogs)
            if (data.streaming && data.streaming.content) {
                showStreamingContent(name, data.streaming, data);
            }

            // [033] Live update anonymization badge during streaming (with ViewContext guard)
            if (data.anonymization && data.anonymization.total_entities > 0) {
                ViewContext.updateTaskAnon(taskId, data.anonymization);
                if (ViewContext.isViewed(taskId)) {
                    updateAnonBadge(data.anonymization);
                }
            }

            // Live update context from task status (centralized - no separate endpoint needed)
            if (data.dev_context) {
                updateDevContextFromTask(data.dev_context);
            }

            if (data.pending_input) {
                // [067] Phase guard: skip if already handling dialog
                if (!ViewContext.canShowDialog(taskId)) {
                    serverLog('[Tasks] Skip pending_input in pollTask (phase guard)');
                } else {
                    showConfirmationDialog(taskId, data.pending_input, tile, name, isAgent);
                    return;
                }
            }

            // Faster polling: 300ms for streaming, 500ms otherwise (was 500/1000)
            const pollInterval = data.streaming ? 300 : 500;
            setTimeout(() => pollTask(taskId, tile, name, isAgent), pollInterval);
        } else {
            const success = data.status === 'done';
            const cancelled = data.status === 'cancelled';

            // Clear the cancel flag when task completes
            if (cancelRequestedForTask === taskId) {
                cancelRequestedForTask = null;
            }

            // [065] B1: Add transitionTask for pollTask completion path
            const phase = cancelled ? 'idle' : (success ? 'done' : 'error');
            ViewContext.transitionTask(taskId, phase);

            if (tile) showTileResult(tile, success, cancelled);

            // Final context update from task data (no separate fetch needed)
            if (data.dev_context) {
                updateDevContextFromTask(data.dev_context);
            }
            // Hide processing context display (unified overlay)
            const processingCtx = document.getElementById('aiProcessingContext');
            if (processingCtx) processingCtx.style.display = 'none';

            // If cancelled, return directly to tiles - no accumulated content shown
            // [065] B2: isAppendMode removed - handled by transitionTask('idle') in B1
            if (cancelled) {
                showTiles();
                return;
            }

            let content;
            if (success) {
                // Prefer streaming content (full accumulated response) over final result
                // Streaming content contains everything printed during the agent/skill execution
                if (data.streaming && data.streaming.content) {
                    content = data.streaming.content;
                } else {
                    content = data.result;
                }
            } else {
                // For errors/cancelled, also check streaming content first
                if (data.streaming && data.streaming.content) {
                    content = data.streaming.content;
                    if (data.error) {
                        content += '\n\n**' + t('task.error_prefix') + '** ' + data.error;
                    }
                } else {
                    content = data.error || t('task.unknown_error');
                }
            }

            let costStr = '-';
            let costValue = 0;
            const tokenCount = (data.input_tokens || 0) + (data.output_tokens || 0);

            // Use cost_usd from SDK if available, otherwise calculate from tokens
            if (data.cost_usd) {
                costValue = data.cost_usd;
                costStr = '$' + costValue.toFixed(4);
                if (success) {
                    addToCost(costValue, tokenCount);
                }
            } else if (data.input_tokens || data.output_tokens) {
                costValue = calculateCost(data.ai_backend, data.input_tokens || 0, data.output_tokens || 0);
                costStr = costValue > 0 ? '$' + costValue.toFixed(4) : '-';

                if (success && costValue > 0) {
                    addToCost(costValue, tokenCount);
                }
            }

            let tokensStr = '-';
            if (data.input_tokens || data.output_tokens) {
                tokensStr = (data.input_tokens || 0) + ' / ' + (data.output_tokens || 0);
            } else if (data.cost_usd) {
                // Estimate tokens from cost when not available (e.g., Claude SDK)
                tokensStr = estimateTokensFromCost(data.cost_usd) || '-';
            }

            const stats = {
                backend: data.ai_backend || '-',
                model: data.model || '-',
                duration: data.duration ? data.duration + 's' : '-',
                tokens: tokensStr,
                cost: costStr
            };

            // [033] Update anonymization badge if data was anonymized (with ViewContext guard)
            if (data.anonymization && data.anonymization.total_entities > 0) {
                if (ViewContext.isViewed(taskId)) {
                    updateAnonBadge(data.anonymization);
                }
            }

            // Always update stats (even in append mode)
            updateStatsPanel(stats);

            // In append mode, add response to existing content
            if (isAppendMode && success) {
                appendResultToPanel(content, data.anonymization);
                // [067] D9: Migrate to ViewContext API
                ViewContext.updateTaskChat(taskId, { isAppendMode: false });
                showPromptArea(true);  // Re-show prompt area after append (was hidden during loading)
            } else {
                // Show result panel (cancelled case already returned above)
                const errorType = !success ? 'error' : null;
                showResultPanel(name, content, errorType, stats, data.anonymization);
            }

            // Reload session to update context display
            if (success) {
                loadSession();
            }
        }
    } catch (e) {
        // [065] B4: Add transitionTask for pollTask error path
        ViewContext.transitionTask(taskId, 'error');
        if (tile) showTileResult(tile, false);
        showResultPanel(name, t('task.connection_error') + ' ' + e.message, true, null, null);
    }
}

// =============================================================================
// SSE Streaming (preferred method)
// =============================================================================

/**
 * [046] Creates an SSE event handler with task_id validation guard.
 * Ignores events meant for different tasks (defense-in-depth for parallel agents).
 * If event has no task_id or task_id matches, the handler is called normally.
 *
 * @param {string} taskId - Expected task ID for this SSE connection
 * @param {Function} handler - Handler function receiving (data, event)
 * @returns {Function} Guarded event handler
 */
function createGuardedHandler(taskId, handler) {
    return (e) => {
        let data;
        try {
            data = JSON.parse(e.data);
        } catch (parseErr) {
            serverLog('[SSE] ERROR: Invalid JSON in event: ' + parseErr);
            return;
        }
        if (data.task_id && data.task_id !== taskId) {
            serverLog('[SSE] WARNING: Ignoring event for different task: ' + data.task_id + ' expected: ' + taskId);
            return;
        }
        handler(data, e);
    };
}

async function streamTask(taskId, tile, name, isAgent) {
    // #11 - Cleanup existing connection for this task to prevent memory leak
    if (activeEventSources[taskId]) {
        activeEventSources[taskId].close();
        delete activeEventSources[taskId];
    }

    // Accumulated content for real-time display
    let accumulatedContent = '';
    let lastStats = {};
    let lastAnonymization = null;
    // [067] C2: pendingDialogShown removed - transitionTask(loading/streaming) handles this via _syncDerivedGlobals

    // Initial status check - in case task completed very fast before SSE connected
    // This handles the race condition where task fails in <1s
    try {
        const initRes = await fetch(API + '/task/' + taskId + '/status');
        const initData = await initRes.json();

        // Check if task is waiting for user input (pending_input)
        // pending_input can come with status 'running' OR 'pending_input'
        if (initData.pending_input) {
            // [067] Phase guard: skip if already handling dialog
            if (!ViewContext.canShowDialog(taskId)) {
                serverLog('[Tasks] Skip pending_input in streamTask init (phase guard)');
            } else {
                serverLog('[SSE] Task waiting for user input before SSE connect');
                // Show streaming content first if available
                if (initData.streaming?.content) {
                    showStreamingContent(name, initData.streaming, initData);
                }
                showConfirmationDialog(taskId, initData.pending_input, tile, name, isAgent);
                return;  // Don't set up SSE, dialog handles continuation
            }
        }

        if (TERMINAL_TASK_STATES.includes(initData.status)) {
            serverLog('[SSE] Task already completed before SSE connect: ' + initData.status);
            // [065] B5: Add transitionTask for streamTask init-done path
            const initPhase = initData.status === 'done' ? 'done' : (initData.status === 'cancelled' ? 'idle' : 'error');
            ViewContext.transitionTask(taskId, initPhase);

            if (tile) showTileResult(tile, initData.status === 'done', initData.status === 'cancelled');

            // If cancelled, return directly to tiles
            if (initData.status === 'cancelled') {
                showTiles();
                return;
            }

            const errorType = initData.status === 'error' ? 'error' : null;
            showResultPanel(name, initData.result || initData.error || t('task.completed'), errorType, null, null);
            return;  // Don't set up SSE for completed task
        }
    } catch (e) {
        serverLog('[SSE] Initial status check failed, continuing with SSE: ' + e);
    }

    // Create EventSource connection
    const eventSource = new EventSource(API + '/task/' + taskId + '/stream');
    activeEventSources[taskId] = eventSource;

    serverDebug('[SSE-DEBUG] Creating EventSource for task: ' + taskId);

    // Debug: Log connection opened
    eventSource.onopen = () => {
        serverDebug('[SSE-DEBUG] Connection OPENED for task: ' + taskId + ' readyState: ' + eventSource.readyState);
    };

    // Health-check interval: Periodically verify task state as SSE fallback
    // This catches cases where SSE events are lost (connection issues, browser throttling)
    const healthCheckInterval = setInterval(async () => {
        if (!activeEventSources[taskId]) {
            clearInterval(healthCheckInterval);
            return;
        }

        // Log SSE state for debugging
        const states = ['CONNECTING', 'OPEN', 'CLOSED'];
        const currentState = eventSource.readyState;
        serverDebug('[SSE-DEBUG] readyState: ' + states[currentState] + ' (' + currentState + ') for task: ' + taskId);

        // If SSE is not OPEN, let onerror handle reconnection
        if (currentState !== 1) {  // 1 = OPEN
            return;
        }

        // Periodic status check as SSE fallback (every 10 seconds)
        try {
            const res = await fetch(API + '/task/' + taskId + '/status');
            const data = await res.json();

            // Check for pending_input that we might have missed via SSE
            // NOTE: Do NOT close EventSource or stop healthCheck here!
            // The SSE connection must stay alive for multi-round dialogs (Round 2+).
            // pendingDialogShown guard prevents duplicate dialogs.
            if (data.pending_input) {
                // [067] Phase guard: skip if already handling dialog
                if (!ViewContext.canShowDialog(taskId)) {
                    serverLog('[SSE-FALLBACK] Skip pending_input (phase guard)');
                } else {
                    serverLog('[SSE-FALLBACK] Detected pending_input via health check');
                    if (data.streaming?.content) {
                        showStreamingContent(name, data.streaming, data);
                    }
                    showConfirmationDialog(taskId, data.pending_input, tile, name, isAgent);
                }
            }

            // Check if task completed without us receiving the event
            // ONLY terminal states close SSE - pending_input is still active!
            if (TERMINAL_TASK_STATES.includes(data.status)) {
                serverLog('[SSE-FALLBACK] Task completed without SSE event: ' + data.status);
                clearInterval(healthCheckInterval);
                eventSource.close();
                delete activeEventSources[taskId];

                // [065] B6: Add transitionTask for health check completion path
                const hcPhase = data.status === 'done' ? 'done' : (data.status === 'cancelled' ? 'idle' : 'error');
                ViewContext.transitionTask(taskId, hcPhase);

                // Handle completion
                if (tile) showTileResult(tile, data.status === 'done', data.status === 'cancelled');

                if (data.status === 'cancelled') {
                    showTiles();
                    return;
                }

                const content = data.streaming?.content || data.result || '';
                const errorType = data.status === 'error' ? 'error' : null;
                showResultPanel(name, content, errorType, null, data.anonymization);
            }
        } catch (e) {
            serverLog('[SSE-FALLBACK] Health check failed: ' + e.message);
        }
    }, 10000);  // Check every 10 seconds

    // Handle task_start event
    eventSource.addEventListener('task_start', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[SSE] Task started: ' + JSON.stringify(data));
        // #6 - Set currentTaskId here (after SSE confirms task started) instead of on POST response
        // This prevents race condition where fast-completing tasks show wrong UI
        if (pendingTaskId === taskId) {
            currentTaskId = taskId;
            pendingTaskId = null;
        }
        lastStats = {
            backend: data.backend || '-',
            model: data.model || '-'
        };

        // [030] Register task in ViewContext (or update if already registered)
        let taskState = ViewContext.getTask(taskId);
        if (!taskState) {
            taskState = ViewContext.registerTask(taskId, null, name, data.backend, data.model, 'webui');
        } else {
            taskState.backend = data.backend || taskState.backend;
            taskState.model = data.model || taskState.model;
        }
        taskState.anon.enabled = !!data.anon_enabled;
        ViewContext.updateTaskStats(taskId, lastStats);

        // [064/067] Phase: idle -> loading (stay in loading until first token)
        const currentPhase = ViewContext.getTaskPhase(taskId);
        if (currentPhase === 'idle') {
            ViewContext.transitionTask(taskId, 'loading');
        } else if (currentPhase === 'thinking') {
            // After confirmation, agent runs again → stay in thinking until first token
        }
        // If already 'loading' or 'streaming' (chat append mode), no transition needed

        // [033] Reset anonymization badge only if this task is viewed
        if (ViewContext.isViewed(taskId)) {
            resetAnonBadge(!data.anon_enabled);
        }
    });

    // Handle token events (real-time streaming - delta append)
    eventSource.addEventListener('token', (e) => {
        try {
            const data = JSON.parse(e.data);
            // Append delta token to accumulated content
            accumulatedContent += data.token;

            // [064/067] First token → transition to streaming (from loading or thinking)
            const tokenPhase = ViewContext.getTaskPhase(taskId);
            if (tokenPhase === 'thinking' || tokenPhase === 'loading') {
                ViewContext.transitionTask(taskId, 'streaming');
            }

            // [030] State: ALWAYS write to TaskState
            ViewContext.updateTaskContent(taskId, accumulatedContent);

            // [030] UI: Only update if this task is viewed
            if (!ViewContext.isViewed(taskId)) return;

            // Update display with accumulated content
            showStreamingContent(name, {
                content: accumulatedContent,
                is_thinking: data.is_thinking,
                length: data.accumulated_length
            }, {});
        } catch (parseErr) {
            serverLog('[SSE] ERROR: Invalid JSON in token event: ' + parseErr);
        }
    });

    // Handle content_sync events (full content replacement when tool markers are updated)
    eventSource.addEventListener('content_sync', (e) => {
        try {
            const data = JSON.parse(e.data);
            serverLog('[SSE] content_sync received, length: ' + data.length);
            // Replace accumulated content entirely (content was modified, not just appended)
            accumulatedContent = data.content;

            // [030] State: ALWAYS write to TaskState
            ViewContext.updateTaskContent(taskId, accumulatedContent);

            // [030] UI: Only update if this task is viewed
            if (!ViewContext.isViewed(taskId)) return;

            // Update display with synced content
            showStreamingContent(name, {
                content: accumulatedContent,
                is_thinking: data.is_thinking,
                length: data.length
            }, {});
        } catch (parseErr) {
            serverLog('[SSE] ERROR: Invalid JSON in content_sync event: ' + parseErr);
        }
    });

    // Handle anonymization updates
    eventSource.addEventListener('anonymization', (e) => {
        const data = JSON.parse(e.data);
        lastAnonymization = data;

        // [030] State: ALWAYS write to TaskState
        ViewContext.updateTaskAnon(taskId, data);

        // [030] UI: Only update if this task is viewed
        if (!ViewContext.isViewed(taskId)) return;
        updateAnonBadge(data);
    });

    // Handle tool_call updates (show which tool is running)
    eventSource.addEventListener('tool_call', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[SSE] Tool call: ' + JSON.stringify(data));
        const toolName = data.tool_name || '';
        const status = data.status || 'executing';

        // [030] State: ALWAYS write to TaskState
        const taskState = ViewContext.getTask(taskId);
        if (taskState) {
            taskState.overlay.currentTool = toolName;
            if (status === 'complete') {
                taskState.overlay.toolCount++;
                taskState.overlay.toolHistory.push({ name: toolName, duration: data.duration });
            }
            ViewContext.updateTaskOverlay(taskId, taskState.overlay);
        }

        // [030] UI: Only update if this task is viewed
        if (!ViewContext.isViewed(taskId)) return;

        // Update thinking overlay with current tool
        const duration = data.duration ? ` (${data.duration}s)` : '';
        if (status === 'executing') {
            updateThinkingStatus(null, `🔧 ${toolName}...`);
        } else if (status === 'complete') {
            updateThinkingStatus(null, `✓ ${toolName}${duration}`);
        }
        // Also update loading panel tool display
        updateLoadingToolCall(toolName, status, data.duration);
    });

    // Handle dev_context updates (token stats, iteration info, breakdown)
    eventSource.addEventListener('dev_context', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[SSE] Dev context: ' + JSON.stringify(data));

        // [030] State: ALWAYS write to TaskState
        ViewContext.updateTaskContext(taskId, {
            systemTokens: data.system_tokens || 0,
            userTokens: data.user_tokens || 0,
            toolTokens: data.tool_tokens || 0,
            totalTokens: (data.system_tokens || 0) + (data.user_tokens || 0) + (data.tool_tokens || 0),
            iteration: data.iteration || 0,
            maxIterations: data.max_iterations || 0,
            limit: data.context_limit || 200000
        });

        // [030] UI: Only update if this task is viewed
        if (!ViewContext.isViewed(taskId)) return;

        // Build main context string (Step X/Y)
        let contextStr = '';
        if (data.iteration && data.max_iterations) {
            contextStr = `Step ${data.iteration}/${data.max_iterations}`;
        }

        // Build breakdown string if token data available
        let breakdownStr = '';
        const systemTokens = data.system_tokens || 0;
        const userTokens = data.user_tokens || 0;
        const toolTokens = data.tool_tokens || 0;

        if (systemTokens > 0 || userTokens > 0 || toolTokens > 0) {
            const parts = [];
            if (systemTokens > 0) parts.push(`System: ${formatTokens(systemTokens)}`);
            if (userTokens > 0) parts.push(`Prompt: ${formatTokens(userTokens)}`);
            if (toolTokens > 0) parts.push(`Tools: ${formatTokens(toolTokens)}`);
            breakdownStr = parts.join(' · ');
        }

        // Update unified processing overlay (works in both loading and thinking modes)
        updateProcessingContext(contextStr, breakdownStr);
    });

    // Handle pending input (confirmation dialog) - [046] guarded for parallel isolation
    // [064] SSE events are live (not polled) - always forward to showConfirmationDialog
    // which has its own awaiting_input guard against duplicates.
    // HTTP status checks (healthCheck, reconnectTask, streamTask init) keep their phase guard.
    eventSource.addEventListener('pending_input', createGuardedHandler(taskId, (data) => {
        serverLog('[SSE] Pending input: ' + JSON.stringify(data));
        showConfirmationDialog(taskId, data, tile, name, isAgent);
    }));

    // Handle task completion - [046] guarded for parallel isolation
    eventSource.addEventListener('task_complete', createGuardedHandler(taskId, (data) => {
        serverDebug('[SSE-DEBUG] *** TASK_COMPLETE EVENT RECEIVED *** ' + taskId);
        serverLog('[SSE] Task complete: ' + JSON.stringify(data));
        clearInterval(healthCheckInterval);  // Stop health check
        eventSource.close();
        delete activeEventSources[taskId];  // #8 - cleanup to prevent memory leak

        // [064] Phase -> done
        ViewContext.transitionTask(taskId, 'done');

        // [030] State: ALWAYS write final stats to TaskState
        ViewContext.updateTaskContent(taskId, accumulatedContent || data.result || '');
        ViewContext.completeTask(taskId, {
            duration: data.duration ? data.duration + 's' : null,
            tokens: (data.input_tokens || data.output_tokens)
                ? (data.input_tokens || 0) + ' / ' + (data.output_tokens || 0)
                : (estimateTokensFromCost(data.cost_usd) || null),
            cost: data.cost_usd ? '$' + data.cost_usd.toFixed(4) : null,
            inputTokens: data.input_tokens || 0,
            outputTokens: data.output_tokens || 0,
            costUsd: data.cost_usd || 0
        });

        // [030] UI: Only update if this task is viewed
        if (!ViewContext.isViewed(taskId)) return;

        // #8 - Clear cancel flag only if it matches this task
        if (cancelRequestedForTask === taskId) {
            cancelRequestedForTask = null;
        }

        if (tile) showTileResult(tile, true, false);
        // [065] Redundant calls removed (A2) - transitionTask handles showThinkingOverlay, setLoading
        stopAllToolSpinners();  // Ensure all tool spinners stop on completion

        // V2 Link Placeholder System: Load link_map from task_complete event
        if (data.link_map && typeof setLinkMap === 'function') {
            setLinkMap(data.link_map);
            serverLog('[SSE] Link map loaded: ' + Object.keys(data.link_map).length + ' entries');
        }

        // Use accumulated streaming content or result from event
        const content = accumulatedContent || data.result || '';

        // Build stats - include sub-agent costs if present
        let costStr = '-';
        // Show tokens if available, otherwise estimate from cost (e.g., Claude SDK)
        let tokensStr;
        if (data.input_tokens || data.output_tokens) {
            tokensStr = (data.input_tokens || 0) + ' / ' + (data.output_tokens || 0);
        } else if (data.cost_usd) {
            tokensStr = estimateTokensFromCost(data.cost_usd) || '-';
        } else {
            tokensStr = '-';
        }
        let totalCost = data.cost_usd || 0;
        let totalTokens = (data.input_tokens || 0) + (data.output_tokens || 0);

        if (data.sub_agent_costs && data.sub_agent_costs.count > 0) {
            // Add sub-agent costs to totals
            const subCost = data.sub_agent_costs.cost_usd || 0;
            const subIn = data.sub_agent_costs.input_tokens || 0;
            const subOut = data.sub_agent_costs.output_tokens || 0;
            const subCount = data.sub_agent_costs.count || 0;

            totalCost += subCost;
            totalTokens += subIn + subOut;

            // Show breakdown: own cost + sub-agent cost = total
            if (data.cost_usd) {
                costStr = '$' + totalCost.toFixed(4) + ' (' + subCount + ' sub)';
            } else {
                costStr = '$' + subCost.toFixed(4) + ' (' + subCount + ' sub)';
            }
            tokensStr = totalTokens.toLocaleString() + ' total';
        } else if (data.cost_usd) {
            costStr = '$' + data.cost_usd.toFixed(4);
        }

        const stats = {
            backend: lastStats.backend || '-',
            model: lastStats.model || '-',
            duration: data.duration ? data.duration + 's' : '-',
            tokens: tokensStr,
            cost: costStr
        };

        // Track costs (including sub-agents)
        if (totalCost > 0) {
            addToCost(totalCost, totalTokens);
        }

        updateStatsPanel(stats);

        // #7 - Handle append mode with task guard
        if (isAppendMode && currentTaskId === taskId) {
            appendResultToPanel(content, lastAnonymization);
            // [067] D10: Migrate to ViewContext API
            ViewContext.updateTaskChat(taskId, { isAppendMode: false });
            showPromptArea(true);
        } else {
            showResultPanel(name, content, null, stats, lastAnonymization);
        }

        loadSession();
    }));

    // Handle task error - [046] guarded for parallel isolation
    eventSource.addEventListener('task_error', createGuardedHandler(taskId, (data) => {
        serverDebug('[SSE-DEBUG] *** TASK_ERROR EVENT RECEIVED *** ' + taskId);
        serverLog('[SSE] Task error: ' + JSON.stringify(data));
        clearInterval(healthCheckInterval);  // Stop health check
        eventSource.close();
        delete activeEventSources[taskId];  // #8 - cleanup to prevent memory leak

        // [030] State: ALWAYS write to TaskState
        ViewContext.errorTask(taskId, data.error);

        // [064] Phase -> error
        ViewContext.transitionTask(taskId, 'error');

        // [030] UI: Only update if this task is viewed
        if (!ViewContext.isViewed(taskId)) return;

        // [024] Clear current session highlight on error
        if (currentSessionId) {
            currentSessionId = null;
            document.dispatchEvent(new CustomEvent('da:current-session-changed', { detail: { sessionId: null } }));
        }

        if (tile) showTileResult(tile, false, false);
        // [065] Redundant calls removed (A3) - transitionTask handles showThinkingOverlay, setLoading, isAppendMode
        stopAllToolSpinners();  // Ensure all tool spinners stop on error

        // Show accumulated content with error
        let errorContent = accumulatedContent || '';
        if (data.error) {
            errorContent += (errorContent ? '\n\n**' + t('task.error_prefix') + '** ' : '') + data.error;
        }

        showResultPanel(name, errorContent || data.error || t('task.unknown_error'), 'error', null, lastAnonymization);
    }));

    // Handle task cancelled
    eventSource.addEventListener('task_cancelled', (e) => {
        serverDebug('[SSE-DEBUG] *** TASK_CANCELLED EVENT RECEIVED *** ' + taskId);
        serverLog('[SSE] Task cancelled');
        clearInterval(healthCheckInterval);  // Stop health check
        eventSource.close();
        delete activeEventSources[taskId];  // #8 - cleanup to prevent memory leak

        // [030] State: ALWAYS write to TaskState
        ViewContext.cancelTask(taskId);

        // [064] Phase -> idle (cancelled)
        ViewContext.transitionTask(taskId, 'idle');

        // [030] UI: Only update if this task is viewed
        if (!ViewContext.isViewed(taskId)) return;

        // #8 - Clear cancel flag only if it matches this task
        if (cancelRequestedForTask === taskId) {
            cancelRequestedForTask = null;
        }

        if (tile) showTileResult(tile, false, true);
        // [065] Redundant calls removed (A4) - transitionTask handles showThinkingOverlay, setLoading, isAppendMode
        stopAllToolSpinners();  // Ensure all tool spinners stop on cancel

        // Always return directly to tiles on cancel - no accumulated content shown
        showTiles();
    });

    // Handle ping (keepalive)
    eventSource.addEventListener('ping', (e) => {
        // Just a keepalive, nothing to do
    });

    // Handle connection errors
    eventSource.onerror = (e) => {
        const states = ['CONNECTING', 'OPEN', 'CLOSED'];
        const rs = eventSource.readyState;
        serverDebug('[SSE-DEBUG] *** ONERROR EVENT *** ' + taskId +
            ' readyState: ' + states[rs] + ' (' + rs + ')' +
            ' pendingDialogShown: ' + pendingDialogShown +
            ' hasActiveES: ' + !!activeEventSources[taskId] +
            ' type: ' + e.type + ' eventPhase: ' + e.eventPhase);
        // Log to server for debugging
        fetch(API + '/log', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: '[SSE-ONERROR] task=' + taskId +
                ' readyState=' + states[rs] + ' pendingDialog=' + pendingDialogShown +
                ' accLen=' + accumulatedContent.length})
        }).catch(() => {});

        serverLog('[SSE] Connection error, falling back to status endpoint');
        clearInterval(healthCheckInterval);  // Stop health check
        eventSource.close();
        delete activeEventSources[taskId];  // #8 - cleanup to prevent memory leak

        // Fall back to fetching current status
        reconnectTask(taskId, tile, name, isAgent, accumulatedContent);
    };
}

async function reconnectTask(taskId, tile, name, isAgent, previousContent = '') {
    // Fetch current status after SSE disconnect
    try {
        const res = await fetch(API + '/task/' + taskId + '/status');
        const data = await res.json();

        if (data.status === 'running') {
            // Check if task is waiting for user input (pending_input)
            if (data.pending_input) {
                // [067] Phase guard: skip if already handling dialog
                if (!ViewContext.canShowDialog(taskId)) {
                    serverLog('[SSE] Skip pending_input in reconnect (phase guard), reconnecting');
                    streamTask(taskId, tile, name, isAgent);
                    return;
                }
                serverLog('[SSE] Task waiting for user input, showing dialog');
                // Show streaming content first if available
                if (data.streaming?.content) {
                    showStreamingContent(name, data.streaming, data);
                }
                showConfirmationDialog(taskId, data.pending_input, tile, name, isAgent);
                return;
            }
            // Task still running, reconnect SSE
            serverLog('[SSE] Reconnecting to running task: ' + taskId);
            streamTask(taskId, tile, name, isAgent);
        } else {
            // Task completed while disconnected, handle completion
            serverLog('[SSE] Task completed during disconnect: ' + data.status);

            if (cancelRequestedForTask === taskId) {
                cancelRequestedForTask = null;
            }

            // [065] B7: Add transitionTask for reconnectTask completion path
            const rcPhase = data.status === 'done' ? 'done' : (data.status === 'cancelled' ? 'idle' : 'error');
            ViewContext.transitionTask(taskId, rcPhase);

            if (tile) showTileResult(tile, data.status === 'done', data.status === 'cancelled');

            // If cancelled, return directly to tiles
            if (data.status === 'cancelled') {
                showTiles();
                return;
            }

            // Use streaming content from status or previous content
            let content = data.streaming?.content || previousContent || data.result || '';

            const stats = {
                backend: data.ai_backend || '-',
                model: data.model || '-',
                duration: data.duration ? data.duration + 's' : '-',
                tokens: (data.input_tokens || data.output_tokens)
                    ? (data.input_tokens || 0) + ' / ' + (data.output_tokens || 0)
                    : (estimateTokensFromCost(data.cost_usd) || '-'),
                cost: data.cost_usd ? '$' + data.cost_usd.toFixed(4) : '-'
            };

            updateStatsPanel(stats);

            if (data.status === 'done' && isAppendMode) {
                appendResultToPanel(content, data.anonymization);
                // [067] D11: Migrate to ViewContext API
                ViewContext.updateTaskChat(taskId, { isAppendMode: false });
                showPromptArea(true);
            } else {
                const errorType = data.status === 'error' ? 'error' : null;
                showResultPanel(name, content, errorType, stats, data.anonymization);
            }
        }
    } catch (e) {
        serverLog('[SSE] ERROR: Reconnect failed: ' + e);
        // [065] B8: Add transitionTask for reconnectTask error path
        ViewContext.transitionTask(taskId, 'error');
        if (tile) showTileResult(tile, false);
        showResultPanel(name, t('task.connection_error') + ' ' + e.message, 'error', null, null);
    }
}

function cancelSSEConnection(taskId) {
    // Close SSE connection when cancelling a task
    if (activeEventSources[taskId]) {
        activeEventSources[taskId].close();
        delete activeEventSources[taskId];
    }
}

// Wrapper function that chooses between SSE and polling
function startTaskMonitoring(taskId, tile, name, isAgent) {
    if (USE_SSE_STREAMING && typeof EventSource !== 'undefined') {
        streamTask(taskId, tile, name, isAgent);
    } else {
        pollTask(taskId, tile, name, isAgent);
    }
}

// =============================================================================
// Streaming Content Display
// =============================================================================

function showStreamingContent(name, streaming, taskData = null) {
    const loadingText = document.getElementById('aiProcessingText');
    const resultPanel = document.getElementById('resultPanel');

    // Don't update content if inline question box is showing (waiting for user response)
    const questionBox = document.getElementById('inlineQuestionBox');
    if (questionBox) {
        // Question is displayed, don't overwrite the content
        return;
    }

    // Update loading text only if element exists (not in append mode)
    if (loadingText) {
        if (streaming.is_thinking) {
            loadingText.innerHTML = t('task.thinking') + '<span class="loading-dots"></span>';
        } else {
            loadingText.innerHTML = t('task.writing') + '<span class="loading-dots"></span>';
        }
    }

    // Update thinking overlay in append mode
    if (isAppendMode && taskData) {
        const model = taskData.model || '';
        const backend = taskData.ai_backend || '';
        const status = backend && model ? `${name} • ${backend} • ${model}` : name;
        updateThinkingStatus(status);
    }

    const title = document.getElementById('resultTitle');
    const contentEl = document.getElementById('resultContent');
    const statsEl = document.getElementById('resultStats');

    // These elements may not exist in append mode
    if (title) title.textContent = name + ' - ' + t('task.streaming');
    // Show stats bar during streaming (context info updates live)
    if (statsEl) statsEl.style.display = 'flex';

    // Update stats from task data during streaming (with null checks for append mode)
    if (taskData && statsEl) {
        const statBackend = document.getElementById('statBackend');
        const statModel = document.getElementById('statModel');
        const statDuration = document.getElementById('statDuration');
        const statTokens = document.getElementById('statTokens');
        const statTokensContainer = document.getElementById('statTokensContainer');

        if (taskData.ai_backend && statBackend) {
            statBackend.textContent = taskData.ai_backend;
            statBackend.className = 'stat-value ' + taskData.ai_backend;
        }
        if (taskData.model && statModel) {
            statModel.textContent = taskData.model;
        }
        // Update duration from loadingStartTime
        if (loadingStartTime && statDuration) {
            const elapsed = ((Date.now() - loadingStartTime) / 1000).toFixed(1);
            statDuration.textContent = elapsed + 's';
        }
        // Show tokens if available
        if (taskData.usage && statTokens && statTokensContainer) {
            const tokens = `${taskData.usage.input_tokens || '-'} / ${taskData.usage.output_tokens || '-'}`;
            statTokens.textContent = tokens;
            statTokensContainer.style.display = 'flex';
        }
    }

    // Skip content rendering if contentEl doesn't exist
    if (!contentEl) {
        return;
    }

    try {
        // Render markdown with chart support
        const parsedHtml = renderMarkdownWithCharts(streaming.content || '');

        // Debug logging
        serverLog('showStreamingContent: isAppendMode=' + isAppendMode + ' userPrompt=' + (currentUserPrompt?.substring(0, 30) || 'null') + ' displayed=' + userPromptDisplayed);

        if (isAppendMode) {
            // In append mode: update only the streaming section, preserve history
            let streamingDiv = document.getElementById('streamingResponse');
            if (!streamingDiv) {
                // Create streaming response div after the user's question
                streamingDiv = document.createElement('div');
                streamingDiv.id = 'streamingResponse';
                streamingDiv.className = 'conversation-turn assistant-turn';
                contentEl.appendChild(streamingDiv);
            }
            streamingDiv.innerHTML = `<div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div><div class="turn-content">${parsedHtml}</div>`;
        } else {
            // Normal mode: show user prompt first (if not yet displayed), then assistant response
            let html = '';
            if (currentUserPrompt && !userPromptDisplayed) {
                serverLog('showStreamingContent: Adding user prompt to HTML');
                html += `<div class="conversation-turn user-turn">
                    <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
                    <div class="turn-content">${escapeHtml(currentUserPrompt)}</div>
                </div>`;
                userPromptDisplayed = true;
            }
            html += `<div class="conversation-turn assistant-turn" id="streamingResponse">
                <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                <div class="turn-content">${parsedHtml}</div>
            </div>`;
            contentEl.innerHTML = html;
        }
        contentEl.className = 'result-content streaming';
    } catch (e) {
        serverLog('[WebUI] ERROR: Markdown parse error: ' + e);
        serverLog('Markdown parse error: ' + e.message);
        // Fallback: escape HTML and preserve newlines with <br>
        const safeContent = escapeHtml(streaming.content || '').replace(/\n/g, '<br>');
        if (isAppendMode) {
            let streamingDiv = document.getElementById('streamingResponse');
            if (!streamingDiv) {
                streamingDiv = document.createElement('div');
                streamingDiv.id = 'streamingResponse';
                streamingDiv.className = 'conversation-turn assistant-turn';
                contentEl.appendChild(streamingDiv);
            }
            streamingDiv.innerHTML = `<div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div><div class="turn-content">${safeContent}</div>`;
        } else {
            // Normal mode fallback: show user prompt first
            let html = '';
            if (currentUserPrompt && !userPromptDisplayed) {
                html += `<div class="conversation-turn user-turn">
                    <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
                    <div class="turn-content">${escapeHtml(currentUserPrompt)}</div>
                </div>`;
                userPromptDisplayed = true;
            }
            html += `<div class="conversation-turn assistant-turn" id="streamingResponse">
                <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                <div class="turn-content">${safeContent}</div>
            </div>`;
            contentEl.innerHTML = html;
        }
        contentEl.className = 'result-content streaming';
    }

    // Ensure charts are initialized after DOM update
    // MutationObserver may miss innerHTML replacements
    if (typeof reinitializeCharts === 'function') {
        setTimeout(reinitializeCharts, 50);
    }

    contentEl.scrollTop = contentEl.scrollHeight;
    if (resultPanel) resultPanel.classList.add('visible');
}

// =============================================================================
// Tile Result Display
// =============================================================================

function showTileResult(tile, success, cancelled = false) {
    if (!tile) return;  // Guard for programmatic calls without tile
    tile.classList.remove('running', 'qa-running');

    // Quick Access mode: Show status on tile and mark complete
    if (isQuickAccessMode) {
        tile.classList.add(success ? 'qa-success' : 'qa-error');
        tile.classList.add('qa-complete');
        if (currentTaskId) tile.dataset.qaTaskId = currentTaskId;
        // Remove status indicators after 3 seconds but keep qa-complete for button
        setTimeout(() => {
            tile.classList.remove('qa-success', 'qa-error');
        }, 3000);
        return;
    }

    // Normal mode
    if (cancelled) {
        tile.classList.add('cancelled');
    } else {
        tile.classList.add(success ? 'success' : 'error');
    }

    setTimeout(() => {
        tile.classList.remove('success', 'error', 'cancelled');
    }, 2000);
}

// =============================================================================
// Stats Panel
// =============================================================================

function updateStatsPanel(stats) {
    const statsEl = document.getElementById('resultStats');
    if (!statsEl) return;

    if (stats) {
        const statBackend = document.getElementById('statBackend');
        const statModel = document.getElementById('statModel');
        const statDuration = document.getElementById('statDuration');
        const statTokens = document.getElementById('statTokens');
        const statCost = document.getElementById('statCost');
        const statTokensContainer = document.getElementById('statTokensContainer');
        const statCostContainer = document.getElementById('statCostContainer');

        if (statBackend) {
            statBackend.textContent = stats.backend;
            statBackend.className = 'stat-value ' + stats.backend;
        }
        if (statModel) statModel.textContent = stats.model;
        if (statDuration) statDuration.textContent = stats.duration;
        if (statTokens) statTokens.textContent = stats.tokens || '-';
        if (statCost) statCost.textContent = stats.cost || '-';

        if (statTokensContainer) {
            statTokensContainer.style.display =
                (stats.tokens && stats.tokens !== '-') ? 'flex' : 'none';
        }
        if (statCostContainer) {
            statCostContainer.style.display =
                (stats.cost && stats.cost !== '-') ? 'flex' : 'none';
        }

        statsEl.style.display = 'flex';
    } else {
        statsEl.style.display = 'none';
    }
}

// =============================================================================
// Result Panel Display
// =============================================================================

function showResultPanel(name, content, errorType, stats, anonymization) {
    serverLog('[WebUI] showResultPanel() called for: ' + name);

    // Quick Access mode: Store result in sessionStorage instead of showing panel
    if (isQuickAccessMode) {
        const resultData = {
            name: name,
            content: content,
            errorType: errorType,
            stats: stats,
            anonymization: anonymization,
            taskId: currentTaskId,
            timestamp: Date.now()
        };
        sessionStorage.setItem('qa_last_result', JSON.stringify(resultData));
        serverLog('[WebUI] Quick Access mode: Result stored in sessionStorage');
        return;
    }

    const panel = document.getElementById('resultPanel');
    const title = document.getElementById('resultTitle');
    const contentEl = document.getElementById('resultContent');

    // Handle errorType: null (success), 'error', 'cancelled', or legacy boolean
    let titleSuffix = ' - ' + t('result.result');
    if (errorType === 'cancelled') {
        titleSuffix = ' - ' + t('result.cancelled');
    } else if (errorType === 'error' || errorType === true) {
        titleSuffix = ' - ' + t('result.error');
    }
    title.textContent = name + titleSuffix;

    // Update stats via shared function
    updateStatsPanel(stats);

    let anonHtml = '';
    if (anonymization && anonymization.total_entities > 0) {
        // New format: {total_entities, entity_types, tool_calls_anonymized}
        const types = anonymization.entity_types || {};
        const typesList = [];
        if (types.PERSON) typesList.push(`👤 ${types.PERSON} ${t('anon.persons')}`);
        if (types.EMAIL) typesList.push(`📧 ${types.EMAIL} ${t('anon.emails')}`);
        if (types.LOCATION) typesList.push(`📍 ${types.LOCATION} ${t('anon.locations')}`);
        if (types.URL) typesList.push(`🔗 ${types.URL} ${t('anon.urls')}`);
        if (types.PHONE_NUMBER) typesList.push(`📞 ${types.PHONE_NUMBER} ${t('anon.phone_numbers')}`);

        const typesHtml = typesList.length > 0
            ? typesList.map(item => `<div class="anon-type">${item}</div>`).join('')
            : '<div class="anon-type">' + t('anon.no_details') + '</div>';

        anonHtml = `<details class="anon-details">
            <summary>🔒 ${t('anon.pii_protection')} (${anonymization.total_entities} ${t('anon.entities_protected')})</summary>
            <div class="anon-content">
                <div class="anon-info">✅ ${anonymization.tool_calls_anonymized || 0} ${t('anon.tool_calls_anonymized')}</div>
                ${typesHtml}
            </div>
        </details>`;
    } else if (anonymization && Object.keys(anonymization).length > 0 && !anonymization.total_entities) {
        // Legacy format: {placeholder: original} mapping
        const mappings = Object.entries(anonymization).map(([placeholder, original]) => {
            if (typeof original === 'string') {
                const displayOriginal = original.length > 40 ? original.substring(0, 40) + '...' : original;
                return `<div class="anon-mapping">
                    <span class="anon-placeholder">${escapeHtml(placeholder)}</span>
                    <span class="anon-original">${escapeHtml(displayOriginal)}</span>
                </div>`;
            }
            return '';
        }).join('');

        if (mappings) {
            anonHtml = `<details class="anon-details">
                <summary>🔒 ${t('anon.pii_protection')} (${Object.keys(anonymization).length} ${t('anon.replacements')})</summary>
                <div class="anon-content">${mappings}</div>
            </details>`;
        }
    }

    if (errorType) {
        contentEl.textContent = content || t('result.no_content');
        contentEl.className = 'result-content error';
    } else {
        // Render markdown with chart support
        const parsedHtml = renderMarkdownWithCharts(content || t('result.no_content'));

        // Check if streaming div exists (streaming happened) - preserve user prompt
        const streamingDiv = document.getElementById('streamingResponse');
        if (streamingDiv) {
            // Replace only the streaming div content, preserve the user prompt
            streamingDiv.innerHTML = `<div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div><div class="turn-content">${anonHtml}${parsedHtml}</div>`;
            streamingDiv.removeAttribute('id');
        } else {
            // No streaming happened - show user prompt + result
            let html = '';
            if (currentUserPrompt && !userPromptDisplayed) {
                html += `<div class="conversation-turn user-turn">
                    <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
                    <div class="turn-content">${escapeHtml(currentUserPrompt)}</div>
                </div>`;
                userPromptDisplayed = true;
            }
            html += `<div class="conversation-turn assistant-turn">
                <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
                <div class="turn-content">${anonHtml}${parsedHtml}</div>
            </div>`;
            contentEl.innerHTML = html;
        }
        contentEl.className = 'result-content';
    }

    // [066] A3: hideProcessingOverlay removed - all callers use transitionTask() before showResultPanel
    panel.classList.add('visible');
    showPromptArea(true);  // Show with "Antwort an AI Assistenten..." placeholder

    // Stop any spinning tool icons (in case SSE events were lost)
    stopAllToolSpinners();

    // Debug: verify prompt area state after showing
    setTimeout(() => {
        const pa = document.getElementById('promptArea');
        serverDebug('[WebUI] After showResultPanel - promptArea state: ' + JSON.stringify({
            exists: !!pa,
            classList: pa?.className,
            display: pa ? getComputedStyle(pa).display : 'N/A',
            visibility: pa ? getComputedStyle(pa).visibility : 'N/A',
            height: pa ? pa.offsetHeight : 0,
            parentElement: pa?.parentElement?.tagName
        }));
    }, 100);
}

function appendResultToPanel(content, anonymization) {
    const contentEl = document.getElementById('resultContent');
    if (!contentEl) {
        serverLog('[WebUI] ERROR: appendResultToPanel: resultContent element not found');
        return;
    }

    // Render markdown with chart support
    const parsedHtml = renderMarkdownWithCharts(content || t('result.no_response'));

    // Check if there's a streaming div to replace (from showStreamingContent)
    const streamingDiv = document.getElementById('streamingResponse');
    if (streamingDiv) {
        // Replace streaming div content with final result
        streamingDiv.innerHTML = `<div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div><div class="turn-content">${parsedHtml}</div>`;
        streamingDiv.removeAttribute('id');  // Remove ID so next response gets a new div
    } else {
        // No streaming div - append new response
        const responseHtml = `<div class="conversation-turn assistant-turn">
            <div class="turn-header"><span class="material-icons">smart_toy</span> ${t('conversation.assistant')}</div>
            <div class="turn-content">${parsedHtml}</div>
        </div>`;
        contentEl.innerHTML += responseHtml;
    }

    contentEl.className = 'result-content';  // Remove 'streaming' class
    contentEl.scrollTop = contentEl.scrollHeight;

    // Stop any spinning tool icons (SSE events might have been lost)
    stopAllToolSpinners();
}

// =============================================================================
// Tool Call Formatting
// =============================================================================

/**
 * Stop all spinning tool icons when task completes.
 * This handles the case where SSE connection drops and tool_complete events are lost.
 */
function stopAllToolSpinners() {
    const spinningIcons = document.querySelectorAll('.tool-icon.spin');
    if (spinningIcons.length > 0) {
        serverLog('[Tools] Stopping ' + spinningIcons.length + ' spinning tool icons (task completed)');
        spinningIcons.forEach(icon => icon.classList.remove('spin'));
    }
}

/**
 * Format tool calls as nice badges with counters for repeated calls
 * Converts [Tool: tool_name] to styled HTML badges
 * Groups same tools: [move_email] [move_email] [move_email] -> [move_email ×3]
 */
function formatToolCalls(content) {
    if (!content) return content;

    // V2 Link System: Resolve {{LINK:ref}} placeholders before other formatting
    if (typeof resolveLinkPlaceholders === 'function') {
        content = resolveLinkPlaceholders(content);
    }

    // Remove QUESTION_NEEDED and CONFIRMATION_NEEDED blocks (they're handled separately)
    content = content.replace(/QUESTION_NEEDED:\s*[\s\S]*?(?=\n\n|\n[A-Z]|$)/g, '');
    content = content.replace(/CONFIRMATION_NEEDED:\s*[\s\S]*?(?=\n\n|\n[A-Z]|$)/g, '');

    // Tool category detection using dynamic metadata from MCP servers
    function getToolCategory(toolName) {
        const lowerName = toolName.toLowerCase();

        // Check dynamic metadata (loaded from /api/tool-metadata)
        for (const [mcpName, meta] of Object.entries(toolMetadata)) {
            if (lowerName.includes(mcpName)) {
                return {
                    category: mcpName,
                    icon: meta.icon || 'build',
                    color: meta.color || '#757575'
                };
            }
        }

        // Fallback for unknown tools
        return { category: 'unknown', icon: 'build', color: '#757575' };
    }

    function getShortToolName(toolName) {
        // Remove common prefixes: mcp_proxy__, mcp__, etc.
        return toolName
            .replace(/^mcp_proxy__/, '')
            .replace(/^mcp__/, '')
            .replace(/__/g, '.');
    }

    // Pass 1: Count tools and find best duration for each
    // Use a GREEDY regex that matches ANY [Tool: ...] format
    const toolCounts = {};
    const toolDurations = {};
    const toolRegex = /\[Tool:\s*([^\s\]]+)([^\]]*)\]/g;
    const toolMatches = [...content.matchAll(toolRegex)];
    serverDebug('[formatToolCalls] Found ' + toolMatches.length + ' tool markers');
    for (const match of toolMatches) {
        const name = match[1].trim();
        const rest = match[2] || '';
        // Extract duration from rest (e.g., "| 0.5s" or " ⏳ | 0.5s")
        const durMatch = rest.match(/\|\s*([0-9.]+)s/);
        const dur = durMatch ? durMatch[1] : null;
        serverDebug('[formatToolCalls] Tool: ' + name + ' rest: ' + JSON.stringify(rest) + ' duration: ' + dur);
        toolCounts[name] = (toolCounts[name] || 0) + 1;
        if (dur) {
            toolDurations[name] = dur;
        }
    }

    // Pass 2: Replace ALL [Tool: ...] markers with badges
    const rendered = new Set();

    return content.replace(/\[Tool:\s*([^\s\]]+)([^\]]*)\](?:\s*`([^`]*)`)?/g, (match, toolName, rest, inputPreview) => {
        const name = toolName.trim();

        // Skip duplicates (remove from output)
        if (rendered.has(name)) {
            return '';
        }
        rendered.add(name);

        // Extract duration from this match's rest part as fallback
        const durMatch = (rest || '').match(/\|\s*([0-9.]+)s/);
        const thisDuration = durMatch ? durMatch[1] : null;
        // Use the best duration we found (prefer from first pass)
        const bestDuration = toolDurations[name] || thisDuration;

        const { category, icon, color } = getToolCategory(name);
        const shortName = getShortToolName(name);
        const count = toolCounts[name];
        const countHtml = count > 1 ? `<span class="tool-count">×${count}</span>` : '';

        // Icon: always show category icon, spin when processing (no duration)
        const iconHtml = `<span class="material-icons tool-icon${bestDuration ? '' : ' spin'}">${icon}</span>`;

        // Timing inside badge (only when completed)
        let timingHtml = '';
        if (bestDuration) {
            const dur = parseFloat(bestDuration);
            const colorClass = dur > 5 ? 'slow' : dur > 2 ? 'medium' : 'fast';
            timingHtml = `<span class="tool-timing ${colorClass}">${bestDuration}s</span>`;
        }

        // Use CSS custom property for dynamic color from MCP metadata
        return `<span class="tool-call ${category}" style="--tool-color: ${color}">${iconHtml}<span class="tool-name">${shortName}</span>${countHtml}${timingHtml}</span>`;
    });
}

// =============================================================================
// Close Result Panel
// =============================================================================

async function closeResult() {
    // Cancel any running task first
    if (currentTaskId) {
        try {
            await fetch(API + '/task/' + currentTaskId + '/cancel', { method: 'POST' });
        } catch (e) {
            serverLog('[Cancel] ERROR: Cancel failed: ' + e);
        }
    }

    // End current session (user is closing/leaving)
    try {
        await fetch(API + '/session/end', { method: 'POST' });
        serverLog('[Session] Current session ended by user');
    } catch (e) {
        serverLog('[Session] WARNING: Could not end session: ' + e);
    }

    // Clear skill context when closing a skill tile
    if (currentSkillName) {
        try {
            await fetch(API + '/skill-context/' + currentSkillName + '/clear', { method: 'POST' });
            serverLog('[Skill] Skill context cleared: ' + currentSkillName);
        } catch (e) {
            serverLog('[Skill] WARNING: Could not clear skill context: ' + e);
        }
        currentSkillName = null;
    }

    // Clean up any pending question/confirmation dialogs
    cleanupQuestionDialog();

    // Reset correction mode if active
    correctionMode = null;

    // #13 - Reset userPromptDisplayed state
    userPromptDisplayed = false;

    document.getElementById('resultPanel').classList.remove('visible');
    hideProcessingOverlay();  // Hide unified processing overlay
    setLoading(false);

    // Reset chat state
    if (currentChatBackend) {
        currentChatBackend = null;
        currentChatName = null;
        const input = document.getElementById('promptInput');
        if (input) {
            input.placeholder = t('prompt.placeholder');
        }
    }

    // Unpin tile and show all tiles
    unpinTile();
    showTiles();
}

// =============================================================================
// Prompt Submission
// =============================================================================

async function sendPrompt() {
    // Default: continue in current context
    await sendPromptWithContext(true);
}

async function sendPromptWithContext(continueContext = true) {
    const input = document.getElementById('promptInput');
    const btn = document.getElementById('sendBtn');
    const prompt = input.value.trim();

    if (!prompt) return;

    // License check for chat
    const licenseCheck = await checkAgentLicense('chat');
    if (!licenseCheck.allowed) {
        showLicenseRequiredDialog(licenseCheck.reason, licenseCheck.message);
        return;
    }

    // Check if we're in correction mode
    if (correctionMode) {
        await sendCorrection(prompt);
        return;
    }

    // Check if there's a pending question waiting for response
    if (pendingPollContext) {
        // Submit the prompt as the question response
        input.value = '';
        input.placeholder = t('dialog.response_placeholder');
        await submitQuestionResponse(prompt);
        return;
    }

    btn.disabled = true;
    btn.classList.add('running');
    btn.textContent = t('status.processing') + '...';

    // Check if result panel is visible - use append mode
    const resultPanel = document.getElementById('resultPanel');
    const isResultVisible = resultPanel.classList.contains('visible');

    // Debug logging
    serverLog('sendPromptWithContext: isResultVisible=' + isResultVisible + ' continueContext=' + continueContext + ' chatBackend=' + currentChatBackend);

    if (isResultVisible && continueContext) {
        // Append mode: show thinking overlay instead of loading panel
        // [067] D12: Migrate to ViewContext API
        ViewContext.viewedIsAppendMode = true;
        serverLog('sendPromptWithContext: APPEND mode');
        const backendStatus = currentChatBackend ? `Chat • ${currentChatBackend}` : 'Chat';
        showThinkingOverlay(true, backendStatus);

        // Append user question to result content (with attachments if any)
        const contentEl = document.getElementById('resultContent');
        const attachmentDisplay = getAttachmentDisplayText();
        const userPromptHtml = `<div class="conversation-turn user-turn">
            <div class="turn-header"><span class="material-icons">person</span> ${t('conversation.you')}</div>
            <div class="turn-content">${escapeHtml(prompt)}${attachmentDisplay ? '<div class="user-attachments">' + marked.parse(attachmentDisplay) + '</div>' : ''}</div>
        </div>`;
        contentEl.innerHTML += userPromptHtml;
        contentEl.scrollTop = contentEl.scrollHeight;
    } else {
        // Normal mode: hide result, show loading
        // [067] D13: Migrate to ViewContext API
        ViewContext.viewedIsAppendMode = false;
        serverLog('sendPromptWithContext: NORMAL mode (loading panel)');
        // Store user prompt for display in first streaming response
        currentUserPrompt = prompt;
        userPromptDisplayed = false;
        setLoading(true, 'Prompt');
    }

    let data = null;  // [049] Hoisted for catch-block cleanup access
    try {
        // Build request body with optional backend and attachments
        const requestBody = {
            prompt: prompt,
            continue_context: continueContext
        };
        if (currentChatBackend) {
            requestBody.backend = currentChatBackend;
        }
        // Include agent name for chat agents (loads knowledge, instructions, allowed_mcp from config)
        if (currentChatName) {
            requestBody.agent_name = currentChatName;
        }
        // Include chat attachments if any
        if (chatAttachments.length > 0) {
            requestBody.files = chatAttachments;
        }

        // FIX [039]: Include SDK session ID for resume (from History continue)
        if (window._resumeSessionId) {
            requestBody.resume_session_id = window._resumeSessionId;
            window._resumeSessionId = null;  // One-time use, clean up
            serverLog('[Tasks] Including resume_session_id in prompt request');
        }

        const res = await fetch(API + '/prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        data = await res.json();

        if (data.task_id) {
            input.value = '';

            // [049] Register task in ViewContext and switch view (analog zu webui-agents.js:841-862)
            const taskName = currentChatBackend ? `Chat (${currentChatBackend})` : t('result.response');
            let taskState = ViewContext.getTask(data.task_id);
            if (!taskState) {
                taskState = ViewContext.registerTask(
                    data.task_id, null, taskName,
                    data.ai_backend || currentChatBackend || null,
                    data.model || null,
                    'webui'
                );
            }
            taskState.chat.backend = currentChatBackend || null;
            taskState.chat.agentName = currentChatName || null;
            taskState.chat.isAppendMode = isAppendMode;  // WICHTIG: Vor switchView setzen!
            taskState.overlay.startTime = Date.now();
            taskState.overlay.mode = isAppendMode ? 'thinking' : 'loading';

            // [064] Sync uiPhase before switchView (chat sets isAppendMode before task creation)
            ViewContext.transitionTask(data.task_id, 'loading', {skipUI: true});
            if (isAppendMode) {
                ViewContext.transitionTask(data.task_id, 'streaming', {skipUI: true});
            }

            ViewContext.switchView(data.task_id, null);

            // Start context polling for live stats
            maybeStartContextPolling();
            startTaskMonitoring(data.task_id, null, taskName, true);
        } else if (data.result) {
            input.value = '';
            showThinkingOverlay(false);
            setLoading(false);
            if (isAppendMode) {
                appendResultToPanel(data.result, null);
                showPromptArea(true);  // Re-show prompt area (was hidden during loading)
            } else {
                showResultPanel(t('result.response'), data.result, false, null, null);
            }
            // [067] D6: isAppendMode removed - phase transition handles reset
            loadSession();
        } else {
            showThinkingOverlay(false);
            setLoading(false);
            showResultPanel(t('task.error'), data.error || t('task.unknown_error'), true, null, null);
            // [067] D7: isAppendMode removed - phase transition handles reset
        }
    } catch (e) {
        showThinkingOverlay(false);
        setLoading(false);
        // [049] Cleanup TaskState if registered before error
        if (data && data.task_id) {
            const errTask = ViewContext.getTask(data.task_id);
            if (errTask) {
                errTask.overlay.mode = 'hidden';
                errTask.status = 'error';
            }
        }
        showResultPanel(t('task.error'), t('task.connection_error') + ' ' + e.message, true, null, null);
        // [067] D8: isAppendMode removed - phase transition handles reset
    } finally {
        btn.disabled = false;
        btn.classList.remove('running');
        btn.textContent = t('prompt.send');
        // Clear chat attachments after sending
        clearChatAttachments();
    }
}

async function sendCorrection(correctionText) {
    const { taskId, tile, name, isAgent, data } = correctionMode;
    const input = document.getElementById('promptInput');
    const btn = document.getElementById('sendBtn');

    btn.disabled = true;
    btn.classList.add('running');
    btn.textContent = t('task.sending_correction');

    // Build data with user notes
    const fields = { ...data, _user_notes: correctionText };

    try {
        const res = await fetch(`${API}/task/${taskId}/respond`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed: false, data: fields })
        });

        const responseData = await res.json();

        if (res.ok) {
            // Add user's correction to conversation history
            addUserTurnToConversation(t('task.correction_prefix') + ' ' + correctionText);

            input.value = '';
            // Reset prompt placeholder and button
            input.placeholder = t('prompt.placeholder');
            btn.textContent = t('prompt.send');

            // [066] A1: Show thinking via State Machine - old SSE connection continues receiving events
            ViewContext.transitionTask(taskId, 'thinking');
            const loadingText = document.getElementById('aiProcessingText');
            if (loadingText) loadingText.innerHTML = '✏️ ' + t('task.correcting') + '<span class="loading-dots"></span>';
            // Don't create new SSE - the old connection is still running and will receive continuation
        } else {
            alert(t('task.error_prefix') + ' ' + (responseData.error || t('task.unknown_error')));
        }
    } catch (e) {
        alert(t('task.connection_error') + ' ' + e.message);
    } finally {
        btn.disabled = false;
        btn.classList.remove('running');
        correctionMode = null;
    }
}

// =============================================================================
// Prompt Input Event Handler (initialized on DOM ready)
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Load tool metadata for dynamic icons/colors
    loadToolMetadata();

    // Load user preferences (category filter, etc.)
    loadPreferences();

    // Initialize demo mode badge
    initDemoMode();

    // URL parameter overrides (for Quick Access modal)
    const urlParams = new URLSearchParams(window.location.search);
    const urlCategory = urlParams.get('category');
    if (urlCategory) {
        // Apply category filter from URL (don't persist to preferences)
        setTimeout(() => filterByCategory(urlCategory, false), 100);
    }

    const promptInput = document.getElementById('promptInput');
    if (promptInput) {
        promptInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendPrompt();
            }
        });
    }

    // Connect to global task events SSE for running task badges
    connectTaskEvents();
});

// =============================================================================
// Global Task Events SSE (for running task badges on tiles)
// =============================================================================

// State for running tasks: { agents: { name: count }, skills: { name: count }, workflows: { name: count } }
let runningTasks = { agents: {}, skills: {}, workflows: {} };

// Global EventSource for task events
let taskEventSource = null;

/**
 * Connect to /task/events SSE for global task updates.
 * Used to show pulsating badges on tiles when tasks run in background.
 */
function connectTaskEvents() {
    if (taskEventSource) {
        taskEventSource.close();
    }

    taskEventSource = new EventSource(API + '/task/events');
    serverLog('[TaskEvents] Connecting to ' + API + '/task/events');

    taskEventSource.onopen = () => {
        serverLog('[TaskEvents] SSE connection opened');
    };

    // Initial state with all running tasks
    taskEventSource.addEventListener('active_tasks', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Initial state: ' + JSON.stringify(data));
        // Preserve workflows object when merging server state
        runningTasks = {
            agents: data.agents || {},
            skills: data.skills || {},
            workflows: data.workflows || runningTasks.workflows || {}
        };
        updateAllBadges();
        // Notify other modules (e.g. History) via DOM event - survives SSE reconnects
        document.dispatchEvent(new CustomEvent('da:active-tasks', { detail: data }));
    });

    // Task started event
    taskEventSource.addEventListener('task_started', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Task started - name: ' + data.name + ' type: ' + data.type + ' full: ' + JSON.stringify(data));
        const collection = data.type === 'agent' ? 'agents' : 'skills';
        runningTasks[collection][data.name] = (runningTasks[collection][data.name] || 0) + 1;
        serverDebug('[TaskEvents] runningTasks after start: ' + JSON.stringify(runningTasks));
        setTileBadge(data.name, runningTasks[collection][data.name]);
        document.dispatchEvent(new CustomEvent('da:task-started', { detail: data }));
    });

    // Task ended event
    taskEventSource.addEventListener('task_ended', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Task ended: ' + JSON.stringify(data));
        const collection = data.type === 'agent' ? 'agents' : 'skills';
        if (runningTasks[collection][data.name]) {
            runningTasks[collection][data.name]--;
            if (runningTasks[collection][data.name] <= 0) {
                delete runningTasks[collection][data.name];
            }
        }
        setTileBadge(data.name, runningTasks[collection][data.name] || 0);
        document.dispatchEvent(new CustomEvent('da:task-ended', { detail: data }));
    });

    // Session started - show mini-tile for background tasks or pinned tile for workflows
    taskEventSource.addEventListener('session_started', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Session started: ' + data.session_id + ' ' + data.name + ' task_id: ' + data.task_id + ' triggered_by: ' + data.triggered_by);
        if (data.session_id) {
            // Track session -> task_id mapping for live streaming from history
            if (data.task_id) {
                sessionTaskMap[data.session_id] = data.task_id;
                // [030] Sync to ViewContext
                ViewContext.mapSessionToTask(data.session_id, data.task_id);
                // [030] Update TaskState with session ID if registered
                const taskState = ViewContext.getTask(data.task_id);
                if (taskState && !taskState.sessionId) {
                    taskState.sessionId = data.session_id;
                }
                // Track current session for Quick Access Open button
                if (data.task_id === currentTaskId) {
                    currentSessionId = data.session_id;
                    // [024] Notify History panel about current chat session change
                    document.dispatchEvent(new CustomEvent('da:current-session-changed', { detail: { sessionId: data.session_id } }));
                }
            }

            if (data.triggered_by === 'workflow') {
                // Workflow-triggered sessions: embed in workflow tile if present
                // Never show a separate agent tile - the workflow tile handles display
                const workflowTilePinned = typeof pinnedTile !== 'undefined' && pinnedTile &&
                                           pinnedTile.classList.contains('workflow-tile');
                if (workflowTilePinned) {
                    embedAgentInWorkflowStep(data.session_id, data.name, data.task_id);
                }
                // If no workflow tile yet, just track in background - workflow tile will arrive shortly
            } else {
                showBackgroundMiniTile(data.session_id, data.name, data.type);
            }

            // Notify History module via DOM event (survives SSE reconnects)
            document.dispatchEvent(new CustomEvent('da:session-started', { detail: data }));
        }
    });

    // Session ended - remove mini-tile or workflow session tile
    taskEventSource.addEventListener('session_ended', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Session ended: ' + data.session_id);
        if (data.session_id) {
            // Clean up session -> task_id mapping
            delete sessionTaskMap[data.session_id];
            // [030] Sync to ViewContext
            ViewContext.removeSessionMapping(data.session_id);

            // [024] Clear current session highlight when session ends
            if (currentSessionId === data.session_id) {
                currentSessionId = null;
                document.dispatchEvent(new CustomEvent('da:current-session-changed', { detail: { sessionId: null } }));
            }

            // Check if this is a pinned workflow session tile
            const workflowTile = document.getElementById('workflow-session-tile-' + data.session_id);
            if (workflowTile && typeof pinnedTile !== 'undefined' && pinnedTile === workflowTile) {
                // Unpin the workflow tile (this also removes it since _isSessionTile is true)
                if (typeof unpinTile === 'function') {
                    unpinTile();
                }
                // Show tiles again
                if (typeof showTiles === 'function') {
                    showTiles();
                }
                delete backgroundMiniTiles[data.session_id];
            } else {
                removeBackgroundMiniTile(data.session_id);
            }

            // Notify History module via DOM event (survives SSE reconnects)
            document.dispatchEvent(new CustomEvent('da:session-ended', { detail: data }));
        }
    });

    // Workflow started event
    // Structure: workflows[workflow_id][run_id] = { step, total_steps, name, inputs }
    // This allows multiple instances of the same workflow type to run in parallel
    taskEventSource.addEventListener('workflow_started', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Workflow started: ' + JSON.stringify(data));

        // [030] Register workflow as TaskState
        ViewContext.registerTask(
            'workflow_' + data.run_id,
            null,
            data.name || data.workflow_id,
            'workflow',
            null,
            'workflow'
        );
        const wfState = ViewContext.getTask('workflow_' + data.run_id);
        if (wfState) {
            wfState.isWorkflow = true;
        }

        // Ensure workflows object exists
        if (!runningTasks.workflows) runningTasks.workflows = {};
        // Ensure workflow type object exists
        if (!runningTasks.workflows[data.workflow_id]) {
            runningTasks.workflows[data.workflow_id] = {};
        }
        // Add this instance by run_id (including inputs for display)
        runningTasks.workflows[data.workflow_id][data.run_id] = {
            name: data.name,
            step: 0,
            total_steps: data.total_steps || 0,
            inputs: data.inputs || {}
        };
        updateWorkflowBadge(data.workflow_id);

        // Only show workflow tile if user is not actively working (no tile pinned)
        // Workflows are background automation - they shouldn't interrupt manual work
        if (typeof pinnedTile === 'undefined' || !pinnedTile) {
            serverLog('[TaskEvents] Creating workflow tile - no active work');
            showWorkflowTile(data.run_id, data.workflow_id, data.name, data.total_steps || 0, data.inputs || {});
        } else {
            serverLog('[TaskEvents] Workflow running in background - user is working: ' + pinnedTile?.id);
        }
    });

    // Workflow step event
    taskEventSource.addEventListener('workflow_step', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Workflow step: ' + JSON.stringify(data));

        // [030] Update workflow TaskState
        ViewContext.updateTaskOverlay('workflow_' + data.run_id, {
            mode: 'thinking',
            currentTool: data.step_name
        });

        // Ensure workflows object exists
        if (!runningTasks.workflows) runningTasks.workflows = {};
        // Find workflow type containing this run_id and update
        for (const [workflowId, instances] of Object.entries(runningTasks.workflows)) {
            if (instances[data.run_id]) {
                instances[data.run_id].step = data.step_index;
                instances[data.run_id].total_steps = data.total_steps;
                updateWorkflowBadge(workflowId);
                // Update pinned workflow tile step display
                updateWorkflowTileStep(data.run_id, data.step_name, data.step_index, data.total_steps);
                break;
            }
        }
        document.dispatchEvent(new CustomEvent('da:workflow-step', { detail: data }));
    });

    // Workflow ended event
    taskEventSource.addEventListener('workflow_ended', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Workflow ended: ' + JSON.stringify(data));

        // [030] Complete workflow TaskState
        if (data.status === 'completed') {
            ViewContext.completeTask('workflow_' + data.run_id, null);
        } else {
            ViewContext.errorTask('workflow_' + data.run_id, data.error);
        }

        // Ensure workflows object exists
        if (!runningTasks.workflows) runningTasks.workflows = {};
        // Remove this instance
        if (runningTasks.workflows[data.workflow_id]) {
            delete runningTasks.workflows[data.workflow_id][data.run_id];
            // Clean up empty workflow type
            if (Object.keys(runningTasks.workflows[data.workflow_id]).length === 0) {
                delete runningTasks.workflows[data.workflow_id];
            }
        }
        updateWorkflowBadge(data.workflow_id, data.status === 'completed' ? 'success' : 'error');

        // Finalize step timeline - mark last step as completed/failed
        finalizeWorkflowTimeline(data.run_id, data.status === 'completed');

        // Display result/error in the reply container (don't auto-remove tile)
        displayWorkflowResult(data.run_id, data.status === 'completed', data.result || data.error, data.session_id);
    });

    // Preferences changed (pinned agents, etc.) - reload preferences and refresh UI
    taskEventSource.addEventListener('preferences_changed', (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Preferences changed: ' + data.key);
        if (data.key === 'ui.pinned_agents') {
            // Reload pinned agents from server and refresh tile display
            if (typeof loadPreferences === 'function') {
                loadPreferences().then(() => {
                    // Re-apply pinned states and re-filter current category
                    if (typeof applyPinnedStatesToTiles === 'function') {
                        applyPinnedStatesToTiles();
                    }
                    if (typeof filterByCategory === 'function' && typeof currentCategory !== 'undefined') {
                        filterByCategory(currentCategory, false);  // false = don't re-save preference
                    }
                });
            }
        }
    });

    // Agents changed (new/removed agents) - refresh tiles only
    taskEventSource.addEventListener('agents_changed', (e) => {
        serverLog('[TaskEvents] Agents changed, refreshing tiles...');
        // Only refresh tiles, not the entire page
        if (typeof refreshAgentTiles === 'function') {
            refreshAgentTiles();
        }
    });

    // Server restarting notification (sent before shutdown)
    taskEventSource.addEventListener('server_restarting', (e) => {
        serverLog('[TaskEvents] Server is restarting...');
        // Show restart overlay immediately (don't wait for connection timeout)
        if (typeof showServerRestarting === 'function') {
            showServerRestarting();
        }
    });

    // Startup complete notification (sent after background init)
    // Triggers UI refresh to get correct prerequisites and history
    // NOTE: This handler now hides the startup overlay AFTER loading tiles and history
    taskEventSource.addEventListener('startup_complete', async (e) => {
        const data = JSON.parse(e.data);
        serverLog('[TaskEvents] Startup complete: ' + JSON.stringify(data));

        // Mark backend as ready (in case SSE connected before polling detected it)
        if (typeof backendReady !== 'undefined') {
            backendReady = true;
        }

        // Refresh agent tiles to get correct prerequisites badges
        if (typeof refreshAgentTiles === 'function') {
            try {
                await refreshAgentTiles();
            } catch (err) {
                serverLog('[TaskEvents] WARNING: Error refreshing agent tiles: ' + err);
            }
        }

        // Refresh history if panel is open (or was showing "Loading...")
        if (typeof loadHistoryQuiet === 'function') {
            try {
                await loadHistoryQuiet();
            } catch (err) {
                serverLog('[TaskEvents] WARNING: Error loading history: ' + err);
            }
        }

        // NOW hide the startup overlay (after tiles and history are loaded)
        const overlay = document.getElementById('startupOverlay');
        if (overlay && !overlay.classList.contains('hidden')) {
            overlay.classList.add('hidden');
            serverLog('[TaskEvents] Startup overlay hidden after full initialization');
        }
    });

    // Ping (keepalive) - nothing to do
    taskEventSource.addEventListener('ping', (e) => {
        // Keepalive, ignore
    });

    // Handle errors (auto-reconnect)
    taskEventSource.onerror = (e) => {
        serverLog('[TaskEvents] Connection error, reconnecting in 3s...');
        taskEventSource.close();
        taskEventSource = null;
        setTimeout(connectTaskEvents, 3000);
    };
}

/**
 * Disconnect from global task events SSE.
 */
function disconnectTaskEvents() {
    if (taskEventSource) {
        taskEventSource.close();
        taskEventSource = null;
    }
}

/**
 * Update all tile badges from runningTasks state.
 */
function updateAllBadges() {
    // Remove all existing badges
    document.querySelectorAll('.running-badge').forEach(b => b.remove());
    document.querySelectorAll('.tile.has-running-task').forEach(t => {
        t.classList.remove('has-running-task');
    });

    // Add badges for active tasks
    for (const [name, count] of Object.entries(runningTasks.agents)) {
        setTileBadge(name, count);
    }
    for (const [name, count] of Object.entries(runningTasks.skills)) {
        setTileBadge(name, count);
    }
    // Update workflow badges (workflows use nested structure: workflows[id][run_id])
    if (runningTasks.workflows) {
        for (const workflowId of Object.keys(runningTasks.workflows)) {
            updateWorkflowBadge(workflowId);
        }
    }
}

/**
 * Update workflow status on a workflow tile.
 * Uses the existing .workflow-label element for status display.
 * - Top-right label: shows "Workflow" when idle, progress when running
 * - Bottom-right counter: instance count when running
 * @param {string} workflowId - Workflow ID (e.g., 'email_reply')
 * @param {string} finalStatus - Optional final status ('success' or 'error') when workflow ends
 */
function updateWorkflowBadge(workflowId, finalStatus = null) {
    // Find workflow tile by ID (tiles are rendered with id="workflow-{id}")
    const tile = document.getElementById('workflow-' + workflowId);
    if (!tile) {
        serverLog('[TaskEvents] Workflow tile not found: ' + workflowId);
        return;
    }

    const label = tile.querySelector('.workflow-label');
    let counter = tile.querySelector('.workflow-counter');
    const instances = runningTasks.workflows?.[workflowId] || {};
    const instanceList = Object.values(instances);
    const count = instanceList.length;

    serverDebug('[TaskEvents] updateWorkflowBadge: ' + workflowId + ' count: ' + count + ' finalStatus: ' + finalStatus);

    if (count > 0) {
        // === TOP LABEL: Show step progress ===
        if (label) {
            // Find the most advanced instance (highest step)
            const mostAdvanced = instanceList.reduce((best, curr) =>
                (curr.step > best.step) ? curr : best, instanceList[0]);

            label.textContent = mostAdvanced.total_steps > 0
                ? `${mostAdvanced.step}/${mostAdvanced.total_steps}`
                : '...';
            label.classList.remove('success', 'error');
        }

        // === BOTTOM COUNTER: Instance count ===
        if (!counter) {
            counter = document.createElement('div');
            counter.className = 'workflow-counter';
            tile.appendChild(counter);
        }
        counter.textContent = count.toString();

        tile.classList.add('has-running-workflow');
    } else if (finalStatus) {
        // No more running, show final status briefly in label
        if (label) {
            label.textContent = finalStatus === 'success' ? '✓' : '✗';
            label.classList.remove('success', 'error');
            label.classList.add(finalStatus);
        }

        // Remove counter
        if (counter) counter.remove();

        // Reset label after delay
        setTimeout(() => {
            if (label) {
                label.textContent = 'Workflow';
                label.classList.remove('success', 'error');
            }
            tile.classList.remove('has-running-workflow');
        }, 2000);
    } else {
        // No running instances, reset to default
        if (label) {
            label.textContent = 'Workflow';
            label.classList.remove('success', 'error');
        }
        if (counter) counter.remove();
        tile.classList.remove('has-running-workflow');
    }
}

// =============================================================================
// Background Task Mini-Tiles
// =============================================================================

// Track background mini-tiles by task ID
const backgroundMiniTiles = {};

/**
 * Format task name for display (convert snake_case to Title Case)
 */
function formatTaskDisplayName(name) {
    if (!name) return 'Task';
    return name
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

/**
 * Show a mini-tile for a background task.
 * Only shows if no UI tile is currently pinned.
 * @param {string} taskId - Unique task identifier (name + timestamp)
 * @param {string} taskName - Task name for display
 * @param {string} taskType - 'agent', 'skill', or 'workflow'
 */
function showBackgroundMiniTile(taskId, taskName, taskType) {
    // Don't show if a UI tile is already pinned
    if (typeof pinnedTile !== 'undefined' && pinnedTile) {
        serverLog('[MiniTile] UI tile pinned, skipping mini-tile');
        return;
    }

    // Don't show duplicate
    if (backgroundMiniTiles[taskId]) {
        serverLog('[MiniTile] Already showing: ' + taskId);
        return;
    }

    const container = document.getElementById('backgroundTasksContainer');
    if (!container) return;

    const displayName = formatTaskDisplayName(taskName);
    const icon = taskType === 'workflow' ? 'autorenew' : 'smart_toy';

    const miniTile = document.createElement('div');
    miniTile.className = 'background-mini-tile';
    miniTile.id = 'mini-tile-' + taskId;
    miniTile.innerHTML = `
        <span class="material-icons mini-tile-icon">${icon}</span>
        <span class="mini-tile-name">${displayName}</span>
        <div class="mini-tile-spinner"></div>
    `;

    // Click to open history panel
    miniTile.onclick = () => {
        if (typeof openHistoryPanel === 'function') {
            openHistoryPanel();
        }
    };

    container.appendChild(miniTile);
    backgroundMiniTiles[taskId] = miniTile;
    serverLog('[MiniTile] Added: ' + taskId + ' ' + displayName);
}

/**
 * Remove a background mini-tile.
 * @param {string} taskId - Task identifier
 */
function removeBackgroundMiniTile(taskId) {
    const miniTile = backgroundMiniTiles[taskId];
    if (miniTile) {
        miniTile.style.animation = 'miniTileIn 0.2s ease reverse';
        setTimeout(() => {
            miniTile.remove();
        }, 200);
        delete backgroundMiniTiles[taskId];
        serverLog('[MiniTile] Removed: ' + taskId);
    }
}

/**
 * Remove all background mini-tiles.
 */
function clearBackgroundMiniTiles() {
    Object.keys(backgroundMiniTiles).forEach(taskId => {
        removeBackgroundMiniTile(taskId);
    });
}

/**
 * Show a pinned tile for workflow-triggered sessions.
 * Creates a temporary tile and opens the result panel to show streaming output.
 * @param {string} sessionId - Session ID
 * @param {string} taskName - Task name for display
 * @param {string} taskType - 'agent', 'skill', or 'workflow'
 */
function showWorkflowSessionTile(sessionId, taskName, taskType) {
    serverLog('[WorkflowTile] Creating pinned tile for workflow session: ' + sessionId + ' ' + taskName);

    // Don't create if a tile is already pinned
    if (typeof pinnedTile !== 'undefined' && pinnedTile) {
        serverLog('[WorkflowTile] Tile already pinned, using mini-tile instead');
        showBackgroundMiniTile(sessionId, taskName, taskType);
        return;
    }

    // Create a temporary session tile (similar to createSessionMiniTile in webui-ui.js)
    const displayName = formatTaskDisplayName(taskName);
    const icon = taskType === 'workflow' ? 'autorenew' : 'smart_toy';

    const tile = document.createElement('div');
    tile.className = 'tile agent workflow-session-tile';
    tile.id = 'workflow-session-tile-' + sessionId;
    tile._isSessionTile = true;
    tile._sessionId = sessionId;
    tile.innerHTML = `
        <span class="material-icons tile-icon">${icon}</span>
        <span class="tile-name">${displayName}</span>
    `;

    // Add to body (will be positioned by pinTile)
    document.body.appendChild(tile);

    // Pin the tile
    if (typeof pinTile === 'function') {
        pinTile(tile);
    }

    // Hide tile grid and show result panel
    if (typeof hideTiles === 'function') {
        hideTiles();
    }

    // Show result panel with streaming content
    const resultPanel = document.getElementById('resultPanel');
    const resultContent = document.getElementById('resultContent');
    if (resultPanel && resultContent) {
        resultContent.innerHTML = '<div class="streaming-indicator">' + t('workflow.running') + '</div>';
        resultPanel.classList.add('visible');
    }

    // Store reference for cleanup
    backgroundMiniTiles[sessionId] = tile;
    serverLog('[WorkflowTile] Created and pinned: ' + sessionId + ' ' + displayName);
}

/**
 * Show a pinned tile for a running workflow.
 * Uses simplified display: Input (user turn) -> Steps -> AI Output (assistant turn)
 * @param {string} runId - Workflow run ID
 * @param {string} workflowId - Workflow type ID
 * @param {string} workflowName - Display name
 * @param {number} totalSteps - Total number of steps
 * @param {object} inputs - Workflow inputs (e.g., email sender, subject, body)
 */
function showWorkflowTile(runId, workflowId, workflowName, totalSteps, inputs = {}) {
    serverLog('[WorkflowTile] Creating workflow tile: ' + runId + ' ' + workflowName + ' inputs: ' + JSON.stringify(inputs));

    // Don't create if a tile is already pinned
    if (typeof pinnedTile !== 'undefined' && pinnedTile) {
        serverLog('[WorkflowTile] Tile already pinned, skipping');
        return;
    }

    const displayName = formatTaskDisplayName(workflowName);

    const tile = document.createElement('div');
    tile.className = 'tile workflow-tile workflow-pinned-tile';
    tile.id = 'workflow-tile-' + runId;
    tile._isSessionTile = true;
    tile._runId = runId;
    tile._workflowId = workflowId;
    tile.innerHTML = `
        <span class="material-icons tile-icon">autorenew</span>
        <span class="tile-name">${displayName}</span>
        <span class="workflow-step-info">${t('workflow.starting')}</span>
    `;

    // Add to body
    document.body.appendChild(tile);

    // Pin the tile
    if (typeof pinTile === 'function') {
        pinTile(tile);
    }

    // Hide tile grid and show result panel
    if (typeof hideTiles === 'function') {
        hideTiles();
    }

    // Build input display as user turn (reusing conversation-turn pattern)
    let inputHtml = buildWorkflowInputAsUserTurn(inputs);

    // Show result panel with simplified structure:
    // 1. User turn (input data)
    // 2. Step progress list
    // 3. Assistant turn (AI output - added when agent completes)
    const resultPanel = document.getElementById('resultPanel');
    const resultContent = document.getElementById('resultContent');
    if (resultPanel && resultContent) {
        resultContent.innerHTML = `
            ${inputHtml}
            <div class="workflow-steps" data-run-id="${runId}">
                <div class="workflow-step pending" data-step="0">
                    <span class="material-icons">hourglass_empty</span>
                    <span>${t('workflow.workflow_starting')}</span>
                </div>
            </div>
            <div id="workflow-output-${runId}"></div>
        `;
        resultPanel.classList.add('visible');
    }

    // Store reference
    backgroundMiniTiles['workflow-' + runId] = tile;
    serverLog('[WorkflowTile] Created: ' + runId + ' ' + displayName);
}

/**
 * Build workflow input as a user turn (reuses .conversation-turn.user-turn pattern).
 * @param {object} inputs - Workflow inputs
 * @returns {string} HTML string
 */
function buildWorkflowInputAsUserTurn(inputs) {
    if (!inputs || Object.keys(inputs).length === 0) {
        return '';
    }

    // Check if this looks like an email input
    const hasEmail = inputs.sender || inputs.sender_email || inputs.subject || inputs.body;

    if (hasEmail) {
        // Email workflow - show sender/subject/body in user turn format
        const sender = inputs.sender || inputs.sender_email || 'Unknown';
        const email = inputs.sender_email || '';
        const subject = inputs.subject || t('workflow.no_subject');
        const body = inputs.body || '';

        const senderLine = email && email !== sender
            ? `<strong>${escapeHtml(sender)}</strong> &lt;${escapeHtml(email)}&gt;`
            : `<strong>${escapeHtml(sender)}</strong>`;

        return `<div class="conversation-turn user-turn">
            <div class="turn-header">
                <span class="material-icons">email</span>
                ${t('workflow.incoming_email')}
            </div>
            <div class="turn-content">
                <div style="margin-bottom:8px">${senderLine}</div>
                <div style="color:var(--text-secondary);margin-bottom:8px"><strong>${t('workflow.subject')}:</strong> ${escapeHtml(subject)}</div>
                <div style="white-space:pre-wrap">${escapeHtml(body)}</div>
            </div>
        </div>`;
    }

    // Generic input display - show as simple key: value list in user turn
    let contentHtml = '';
    for (const [key, value] of Object.entries(inputs)) {
        if (value && typeof value === 'string' && key !== 'uid' && key !== 'message_id') {
            const displayKey = formatTaskDisplayName(key);
            const displayVal = String(value).length > 200 ? String(value).substring(0, 200) + '...' : String(value);
            contentHtml += `<div><strong>${escapeHtml(displayKey)}:</strong> ${escapeHtml(displayVal)}</div>`;
        }
    }

    if (!contentHtml) return '';

    return `<div class="conversation-turn user-turn">
        <div class="turn-header">
            <span class="material-icons">input</span>
            ${t('workflow.input_data')}
        </div>
        <div class="turn-content">${contentHtml}</div>
    </div>`;
}

/**
 * Update the step display on a workflow tile.
 * Uses simplified step list (.workflow-steps container).
 * @param {string} runId - Workflow run ID
 * @param {string} stepName - Current step name
 * @param {number} stepIndex - Current step (1-based)
 * @param {number} totalSteps - Total steps
 */
function updateWorkflowTileStep(runId, stepName, stepIndex, totalSteps) {
    // Update tile badge
    const tile = document.getElementById('workflow-tile-' + runId);
    if (tile) {
        const stepInfo = tile.querySelector('.workflow-step-info');
        if (stepInfo) {
            stepInfo.textContent = `${stepIndex}/${totalSteps}`;
        }
    }

    // Update step list
    const stepsContainer = document.querySelector(`.workflow-steps[data-run-id="${runId}"]`);
    if (stepsContainer) {
        const displayStepName = formatTaskDisplayName(stepName);

        // Mark previous in-progress step as completed
        const prevInProgress = stepsContainer.querySelector('.workflow-step.in-progress');
        if (prevInProgress) {
            prevInProgress.classList.remove('in-progress');
            prevInProgress.classList.add('completed');
            const icon = prevInProgress.querySelector('.material-icons');
            if (icon) icon.textContent = 'check_circle';
        }

        // Remove initial "starting" placeholder if present
        const placeholder = stepsContainer.querySelector('.workflow-step.pending');
        if (placeholder && stepIndex === 1) {
            placeholder.remove();
        }

        // Add new step as in-progress
        const stepEl = document.createElement('div');
        stepEl.className = 'workflow-step in-progress';
        stepEl.dataset.step = stepIndex;
        stepEl.innerHTML = `
            <span class="material-icons">sync</span>
            <span>${stepIndex}/${totalSteps}: ${displayStepName}</span>
        `;
        stepsContainer.appendChild(stepEl);
    }

    serverLog('[WorkflowTile] Step updated: ' + runId + ' ' + stepName + ' ' + stepIndex + '/' + totalSteps);
}

/**
 * Finalize the workflow steps when workflow ends.
 * @param {string} runId - Workflow run ID
 * @param {boolean} success - Whether workflow completed successfully
 */
function finalizeWorkflowTimeline(runId, success) {
    const stepsContainer = document.querySelector(`.workflow-steps[data-run-id="${runId}"]`);
    if (!stepsContainer) return;

    // Mark the last in-progress step as completed or failed
    const lastInProgress = stepsContainer.querySelector('.workflow-step.in-progress');
    if (lastInProgress) {
        lastInProgress.classList.remove('in-progress');
        lastInProgress.classList.add(success ? 'completed' : 'error');
        const icon = lastInProgress.querySelector('.material-icons');
        if (icon) {
            icon.textContent = success ? 'check_circle' : 'error';
        }
    }

    // Add final status step
    const statusEl = document.createElement('div');
    statusEl.className = `workflow-step ${success ? 'completed' : 'error'}`;
    statusEl.innerHTML = `
        <span class="material-icons">${success ? 'check_circle' : 'error'}</span>
        <span>${success ? t('workflow.workflow_completed') : t('workflow.workflow_failed')}</span>
    `;
    stepsContainer.appendChild(statusEl);

    serverLog('[WorkflowTile] Timeline finalized: ' + runId + ' ' + (success ? 'success' : 'failed'));
}

/**
 * Display workflow result/reply as an assistant turn (reuses .conversation-turn.assistant-turn).
 * Fetches the session to get the actual AI reply if available.
 * @param {string} runId - Workflow run ID
 * @param {boolean} success - Whether workflow completed successfully
 * @param {string} result - Result text or error message
 * @param {string} sessionId - Workflow session ID for fetching the AI reply
 */
async function displayWorkflowResult(runId, success, result, sessionId) {
    // Mark workflow tile as completed (stops spinning icon)
    const tile = document.getElementById('workflow-tile-' + runId);
    if (tile) {
        tile.classList.add('completed');
        // Update icon to check or error
        const icon = tile.querySelector('.tile-icon');
        if (icon) {
            icon.textContent = success ? 'check_circle' : 'error';
        }
    }

    const outputContainer = document.getElementById('workflow-output-' + runId);
    if (!outputContainer) {
        serverLog('[WorkflowTile] Output container not found for: ' + runId);
        return;
    }

    // Skip if agent streaming already displayed the result (avoid duplicate)
    const existingAgentTurn = outputContainer.querySelector('[id^="workflow-agent-turn-"]');
    if (existingAgentTurn && success) {
        serverLog('[WorkflowTile] Agent output already displayed via streaming, skipping duplicate');
        return;
    }

    // If successful, fetch session to get the AI reply
    if (success && sessionId) {
        try {
            const res = await fetch(API + `/history/sessions/${sessionId}`);
            if (res.ok) {
                const session = await res.json();
                const turns = session.turns || [];
                // Find assistant turn (the AI reply)
                const assistantTurn = turns.find(t => t.role === 'assistant');
                if (assistantTurn && assistantTurn.content) {
                    // Display the actual AI reply
                    let formattedContent = assistantTurn.content;
                    if (typeof formatToolCalls === 'function') {
                        formattedContent = formatToolCalls(formattedContent);
                    }
                    let parsedHtml = formattedContent;
                    if (typeof marked !== 'undefined' && marked.parse) {
                        try {
                            parsedHtml = marked.parse(formattedContent);
                            // Resolve URL-encoded link placeholders after markdown rendering
                            if (typeof resolveLinkPlaceholders === 'function') {
                                parsedHtml = resolveLinkPlaceholders(parsedHtml);
                            }
                        } catch (e) {
                            parsedHtml = escapeHtml(assistantTurn.content).replace(/\n/g, '<br>');
                        }
                    }

                    const turnEl = document.createElement('div');
                    turnEl.className = 'conversation-turn assistant-turn';
                    turnEl.innerHTML = `
                        <div class="turn-header">
                            <span class="material-icons">smart_toy</span>
                            ${t('conversation.assistant')}
                        </div>
                        <div class="turn-content">${parsedHtml}</div>
                    `;
                    outputContainer.appendChild(turnEl);

                    // Scroll to show result
                    const resultContent = document.getElementById('resultContent');
                    if (resultContent) {
                        resultContent.scrollTop = resultContent.scrollHeight;
                    }

                    serverLog('[WorkflowTile] AI reply displayed from session: ' + sessionId);
                    return;
                }
            }
        } catch (e) {
            serverLog('[WorkflowTile] WARNING: Failed to fetch session: ' + e);
        }
    }

    // Fallback: If no session or no assistant turn, show status
    if (success && (result === 'Success' || result === 'Skipped' || !result)) {
        // Nothing to show - workflow completed without explicit result
        return;
    }

    // Show error or result as assistant turn
    const displayContent = result || (success ? t('workflow.completed_successfully') : t('workflow.failed'));
    const icon = success ? 'smart_toy' : 'error';
    const label = success ? t('conversation.assistant') : t('workflow.error');

    // Append as assistant turn (reuse existing pattern)
    const turnEl = document.createElement('div');
    turnEl.className = `conversation-turn assistant-turn${success ? '' : ' error'}`;
    turnEl.innerHTML = `
        <div class="turn-header">
            <span class="material-icons">${icon}</span>
            ${label}
        </div>
        <div class="turn-content">${escapeHtml(displayContent)}</div>
    `;
    outputContainer.appendChild(turnEl);

    // Scroll to show result
    const resultContent = document.getElementById('resultContent');
    if (resultContent) {
        resultContent.scrollTop = resultContent.scrollHeight;
    }

    serverLog('[WorkflowTile] Result displayed: ' + runId + ' ' + (success ? 'success' : 'error'));
}

/**
 * Embed agent output as an assistant turn in the workflow output area.
 * Called when an agent is triggered by a workflow and a workflow tile is pinned.
 * @param {string} sessionId - Agent session ID
 * @param {string} agentName - Agent name
 * @param {string} taskId - Task ID for streaming
 */
function embedAgentInWorkflowStep(sessionId, agentName, taskId) {
    serverLog('[WorkflowTile] Embedding agent in workflow: ' + sessionId + ' ' + agentName);

    // Find the workflow output container by looking for run ID in parent
    const pinnedWorkflowTile = document.querySelector('.workflow-pinned-tile[id^="workflow-tile-"]');
    if (!pinnedWorkflowTile) {
        serverLog('[WorkflowTile] No pinned workflow tile, showing mini-tile instead');
        showBackgroundMiniTile(sessionId, agentName, 'agent');
        return;
    }

    const runId = pinnedWorkflowTile._runId;
    const outputContainer = document.getElementById('workflow-output-' + runId);
    if (!outputContainer) {
        serverLog('[WorkflowTile] Output container not found');
        showBackgroundMiniTile(sessionId, agentName, 'agent');
        return;
    }

    // Create assistant turn for streaming output (reuse .conversation-turn.assistant-turn)
    const turnEl = document.createElement('div');
    turnEl.className = 'conversation-turn assistant-turn streaming';
    turnEl.id = 'workflow-agent-turn-' + sessionId;
    turnEl.innerHTML = `
        <div class="turn-header">
            <span class="material-icons">smart_toy</span>
            ${t('conversation.assistant')}
        </div>
        <div class="turn-content" id="agent-output-${sessionId}">
            <span class="loading-dots">...</span>
        </div>
    `;
    outputContainer.appendChild(turnEl);

    // Store reference for streaming
    if (!window._workflowAgentOutputs) {
        window._workflowAgentOutputs = {};
    }
    window._workflowAgentOutputs[taskId] = sessionId;

    // Start streaming to the assistant turn
    if (taskId) {
        streamToWorkflowStep(taskId, sessionId);
    }
}

/**
 * Stream agent output to embedded assistant turn in workflow.
 * @param {string} taskId - Task ID
 * @param {string} sessionId - Session ID
 */
function streamToWorkflowStep(taskId, sessionId) {
    const outputContainer = document.getElementById('agent-output-' + sessionId);
    if (!outputContainer) return;

    const url = `/task/${taskId}/stream`;
    const eventSource = new EventSource(url);
    let content = '';

    eventSource.addEventListener('token', (e) => {
        const data = JSON.parse(e.data);
        if (data.token) {
            content += data.token;
            // Format with markdown if available, otherwise escape HTML
            let html = typeof marked !== 'undefined'
                ? marked.parse(formatToolCalls(content))
                : escapeHtml(content).replace(/\n/g, '<br>');
            // Resolve URL-encoded link placeholders after markdown rendering
            if (typeof resolveLinkPlaceholders === 'function') {
                html = resolveLinkPlaceholders(html);
            }
            outputContainer.innerHTML = html;
            // Scroll result content to show latest
            const resultContent = document.getElementById('resultContent');
            if (resultContent) {
                resultContent.scrollTop = resultContent.scrollHeight;
            }
        }
    });

    eventSource.addEventListener('task_complete', (e) => {
        eventSource.close();
        // Remove streaming class from the turn
        const turnEl = document.getElementById('workflow-agent-turn-' + sessionId);
        if (turnEl) {
            turnEl.classList.remove('streaming');
        }
    });

    eventSource.addEventListener('task_error', (e) => {
        eventSource.close();
        const turnEl = document.getElementById('workflow-agent-turn-' + sessionId);
        if (turnEl) {
            turnEl.classList.remove('streaming');
            turnEl.classList.add('error');
        }
    });

    eventSource.onerror = (e) => {
        eventSource.close();
    };
}

/**
 * Remove a workflow tile when the workflow ends.
 * @param {string} runId - Workflow run ID
 */
function removeWorkflowTile(runId) {
    const tile = document.getElementById('workflow-tile-' + runId);
    if (tile) {
        // If this is the pinned tile, unpin it
        if (typeof pinnedTile !== 'undefined' && pinnedTile === tile) {
            if (typeof unpinTile === 'function') {
                unpinTile();
            }
            if (typeof showTiles === 'function') {
                showTiles();
            }
        } else {
            tile.remove();
        }
        delete backgroundMiniTiles['workflow-' + runId];
        serverLog('[WorkflowTile] Removed: ' + runId);
    }
}

/**
 * Set or remove badge on a tile.
 * @param {string} taskName - Name of the task/agent/skill
 * @param {number} count - Number of running instances (0 to remove)
 */
function setTileBadge(taskName, count) {
    // Find tile by ID (tiles are rendered with id="tile-{name}")
    const tileId = 'tile-' + taskName;
    const tile = document.getElementById(tileId);
    serverDebug('[TaskEvents] setTileBadge: ' + taskName + ' count: ' + count + ' tileId: ' + tileId + ' found: ' + !!tile);
    if (!tile) {
        // Debug: list all tile IDs
        const allTiles = document.querySelectorAll('.tile[id]');
        serverDebug('[TaskEvents] Available tile IDs: ' + Array.from(allTiles).map(t => t.id).join(', '));
        return;
    }

    let badge = tile.querySelector('.running-badge');

    if (count > 0) {
        // Add or update badge
        if (!badge) {
            badge = document.createElement('div');
            badge.className = 'running-badge';
            tile.appendChild(badge);
        }
        // Show count only if > 1
        badge.textContent = count > 1 ? count : '';
        badge.classList.add('active');
        tile.classList.add('has-running-task');
    } else {
        // Remove badge
        if (badge) {
            badge.classList.remove('active');
            setTimeout(() => {
                if (badge.parentNode) badge.remove();
            }, 200);  // Wait for transition
        }
        tile.classList.remove('has-running-task');
    }
}

// =============================================================================
// Quick Access Mode - Chat Popup
// =============================================================================

// Track Quick Access auto-dismiss timer
let qaAutoDismissTimer = null;

/**
 * Open the session in a new browser window.
 * Called from Quick Access mode tile's "Open" button.
 * Uses continueSession() like the history "Open" button.
 * Button stays visible for 15 minutes to allow multiple opens.
 */
function openQuickAccessChat() {
    if (!currentSessionId) {
        showToast(t('quickaccess.no_result') || 'No session available');
        return;
    }

    // Open main DeskAgent in a new window, then continue the session
    const width = 900, height = 700;
    const left = Math.max(0, (screen.width - width) / 2);
    const top = Math.max(0, (screen.height - height) / 2);

    window.open(
        `/?continue=${currentSessionId}`,
        'deskagent_main',
        `width=${width},height=${height},left=${left},top=${top},resizable=yes`
    );

    // Keep Open button visible - start/reset 15-minute auto-dismiss timer
    if (qaAutoDismissTimer) {
        clearTimeout(qaAutoDismissTimer);
    }
    qaAutoDismissTimer = setTimeout(() => {
        if (pinnedTile && isQuickAccessMode) {
            unpinTile();
        }
        qaAutoDismissTimer = null;
    }, 15 * 60 * 1000);  // 15 minutes
}

/**
 * Initialize chat view from sessionStorage (for Quick Access popup windows).
 * Called on DOMContentLoaded when ?view=chat&restore=... URL params present.
 */
function initChatViewFromStorage() {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('view') !== 'chat') return;

    const restoreKey = urlParams.get('restore');
    if (!restoreKey) return;

    let resultJson = null;
    try {
        // Try to get from opener's sessionStorage first
        resultJson = window.opener?.sessionStorage?.getItem(restoreKey);
    } catch (e) {
        serverLog('[WebUI] Could not access opener sessionStorage: ' + e);
    }

    // Fallback to own sessionStorage
    if (!resultJson) {
        resultJson = sessionStorage.getItem(restoreKey);
    }

    if (resultJson) {
        try {
            const result = JSON.parse(resultJson);
            serverLog('[WebUI] Restoring result from storage: ' + result.name);

            // Hide tiles and show result
            hideTiles();

            // Show the result panel with stored data
            // Need to set isQuickAccessMode to false temporarily to show panel
            const wasQAMode = isQuickAccessMode;
            isQuickAccessMode = false;
            showResultPanel(result.name, result.content, result.errorType, result.stats, result.anonymization);
            isQuickAccessMode = wasQAMode;

            showPromptArea(true);
        } catch (e) {
            serverLog('[WebUI] ERROR: Failed to parse stored result: ' + e);
        }
    }
}
