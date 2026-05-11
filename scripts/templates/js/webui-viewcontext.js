/**
 * WebUI ViewContext Module
 * Central state manager for multi-agent UI support.
 * Tracks per-task state (stats, content, context, overlay) and which task is currently viewed.
 * MUST load after webui-core.js and before webui-tasks.js.
 *
 * Events dispatched:
 * - da:view-switched     { taskId, sessionId, taskState }
 * - da:task-registered   { taskId, sessionId }
 * - da:task-state-updated { taskId, field, data }
 * - da:task-completed    { taskId, finalStats }
 */

// =============================================================================
// [064] UI Phase State Machine
// =============================================================================

const UI_PHASES = {
    IDLE: 'idle',
    LOADING: 'loading',
    STREAMING: 'streaming',
    AWAITING_INPUT: 'awaiting_input',
    THINKING: 'thinking',
    DONE: 'done',
    ERROR: 'error'
};

const VALID_TRANSITIONS = {
    'idle':            ['loading'],
    'loading':         ['streaming', 'awaiting_input', 'error', 'idle'],
    'streaming':       ['awaiting_input', 'done', 'error', 'idle'],
    'awaiting_input':  ['thinking', 'idle', 'error'],
    'thinking':        ['streaming', 'awaiting_input', 'done', 'error', 'idle'],
    'done':            ['idle'],
    'error':           ['idle']
};

// =============================================================================
// ViewContext - Central State Manager
// =============================================================================

const ViewContext = {

    // --- View Management ---
    viewedTaskId: null,
    viewedSessionId: null,

    // --- Task State Storage ---
    taskStates: new Map(),

    // --- Session to Task Mapping (ex-global sessionTaskMap) ---
    sessionTaskMap: new Map(),

    // =========================================================================
    // Task State Factory
    // =========================================================================

    /**
     * Create a new TaskState object with default values.
     * @param {Object} opts - Initial values
     * @returns {Object} TaskState
     */
    _createTaskState(opts = {}) {
        return {
            taskId: opts.taskId || null,
            sessionId: opts.sessionId || null,
            agentName: opts.agentName || null,
            backend: opts.backend || null,
            model: opts.model || null,

            // Stats (updated by SSE events)
            stats: {
                duration: null,
                tokens: null,
                cost: null,
                inputTokens: 0,
                outputTokens: 0,
                costUsd: 0
            },

            // Content (accumulated streaming)
            content: '',

            // Context (token usage per task)
            context: {
                systemTokens: 0,
                userTokens: 0,
                toolTokens: 0,
                totalTokens: 0,
                limit: 200000,
                iteration: 0,
                maxIterations: 0,
                systemPrompt: '',
                userPrompt: '',
                toolResults: [],
                anonymization: {}
            },

            // Overlay state (snapshot for restore on switchView)
            overlay: {
                mode: 'hidden',
                startTime: null,
                toolCount: 0,
                toolHistory: [],
                currentTool: null
            },

            // Chat state (for follow-up prompts)
            chat: {
                backend: opts.backend || null,
                agentName: opts.agentName || null,
                isAppendMode: false
            },

            // Task lifecycle
            pendingTaskId: null,
            taskTile: null,
            userPrompt: null,
            userPromptDisplayed: false,
            cancelRequested: false,

            // Anonymization
            anon: {
                enabled: false,
                stats: null
            },

            // [064] UI Phase (State Machine)
            uiPhase: opts.uiPhase || 'idle',

            // Status
            status: opts.status || 'running',
            isFromHistory: opts.isFromHistory || false,
            isWorkflow: opts.isWorkflow || false,
            triggeredBy: opts.triggeredBy || 'webui'
        };
    },

    // =========================================================================
    // Task Registration
    // =========================================================================

    /**
     * Register a new task. Creates TaskState and optionally switches view.
     * @param {string} taskId
     * @param {string} sessionId
     * @param {string} agentName
     * @param {string} backend
     * @param {string} model
     * @param {string} triggeredBy
     * @returns {Object} The created TaskState
     */
    registerTask(taskId, sessionId, agentName, backend, model, triggeredBy) {
        const state = this._createTaskState({
            taskId,
            sessionId,
            agentName,
            backend,
            model,
            triggeredBy
        });

        this.taskStates.set(taskId, state);

        // Map session to task
        if (sessionId) {
            this.sessionTaskMap.set(sessionId, taskId);
        }

        serverLog('[ViewContext] Registered task: ' + taskId + ' agent=' + agentName + ' backend=' + backend);

        document.dispatchEvent(new CustomEvent('da:task-registered', {
            detail: { taskId, sessionId }
        }));

        return state;
    },

    /**
     * Get a TaskState by taskId.
     * @param {string} taskId
     * @returns {Object|null}
     */
    getTask(taskId) {
        return this.taskStates.get(taskId) || null;
    },

    /**
     * Remove a TaskState.
     * @param {string} taskId
     */
    removeTask(taskId) {
        const state = this.taskStates.get(taskId);
        if (state && state.sessionId) {
            this.sessionTaskMap.delete(state.sessionId);
        }
        this.taskStates.delete(taskId);
    },

    /**
     * Prune completed tasks. Keep max 20 completed, all running stay.
     */
    pruneCompletedTasks() {
        const TERMINAL_TASK_STATES = ['done', 'error', 'cancelled'];
        const completed = [];
        for (const [taskId, state] of this.taskStates) {
            if (TERMINAL_TASK_STATES.includes(state.status)) {
                completed.push({ taskId, state });
            }
        }

        // Sort by most recent first (keep newer ones)
        // No timestamp stored, so just trim from the front (oldest)
        if (completed.length > 20) {
            const toRemove = completed.slice(0, completed.length - 20);
            for (const { taskId } of toRemove) {
                this.removeTask(taskId);
            }
            serverLog('[ViewContext] Pruned ' + toRemove.length + ' completed tasks');
        }
    },

    // =========================================================================
    // View Switching
    // =========================================================================

    /**
     * Switch the viewed task. Fires da:view-switched event.
     * @param {string} taskId
     * @param {string} sessionId
     */
    switchView(taskId, sessionId) {
        const previousTaskId = this.viewedTaskId;
        this.viewedTaskId = taskId;
        this.viewedSessionId = sessionId || null;

        const taskState = this.getTask(taskId);

        serverLog('[ViewContext] switchView: ' + previousTaskId + ' -> ' + taskId);

        document.dispatchEvent(new CustomEvent('da:view-switched', {
            detail: {
                taskId,
                sessionId: sessionId || (taskState ? taskState.sessionId : null),
                taskState,
                previousTaskId
            }
        }));
    },

    /**
     * Check if a taskId is the currently viewed one.
     * @param {string} taskId
     * @returns {boolean}
     */
    isViewed(taskId) {
        return this.viewedTaskId === taskId;
    },

    /**
     * Get the currently viewed TaskState (or null).
     * @returns {Object|null}
     */
    getViewedTask() {
        if (!this.viewedTaskId) return null;
        return this.taskStates.get(this.viewedTaskId) || null;
    },

    // =========================================================================
    // View Properties (getters/setters for backward compat)
    // =========================================================================

    get viewedBackend() {
        const task = this.getViewedTask();
        return task ? task.chat.backend : null;
    },

    get viewedAgentName() {
        const task = this.getViewedTask();
        return task ? task.chat.agentName : null;
    },

    get viewedIsAppendMode() {
        const task = this.getViewedTask();
        return task ? task.chat.isAppendMode : false;
    },

    set viewedIsAppendMode(val) {
        const task = this.getViewedTask();
        if (task) {
            task.chat.isAppendMode = val;
        }
        // [067] Sofort globale Variable syncen (fuer Reads zwischen Set und switchView)
        if (typeof isAppendMode !== 'undefined') {
            isAppendMode = val;
        }
    },

    // =========================================================================
    // Task State Updates (ALWAYS write, regardless of viewed)
    // =========================================================================

    /**
     * Update task stats.
     * @param {string} taskId
     * @param {Object} stats
     */
    updateTaskStats(taskId, stats) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        Object.assign(state.stats, stats);

        document.dispatchEvent(new CustomEvent('da:task-state-updated', {
            detail: { taskId, field: 'stats', data: stats }
        }));
    },

    /**
     * Update task accumulated content.
     * @param {string} taskId
     * @param {string} content
     */
    updateTaskContent(taskId, content) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        state.content = content;
        // No event for content (too frequent during streaming)
    },

    /**
     * Update task context (token stats from dev_context SSE).
     * @param {string} taskId
     * @param {Object} contextData
     */
    updateTaskContext(taskId, contextData) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        Object.assign(state.context, contextData);

        document.dispatchEvent(new CustomEvent('da:task-state-updated', {
            detail: { taskId, field: 'context', data: contextData }
        }));
    },

    /**
     * Update task overlay state (tool calls, mode).
     * @param {string} taskId
     * @param {Object} overlayData
     */
    updateTaskOverlay(taskId, overlayData) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        Object.assign(state.overlay, overlayData);

        document.dispatchEvent(new CustomEvent('da:task-state-updated', {
            detail: { taskId, field: 'overlay', data: overlayData }
        }));
    },

    /**
     * Update task anonymization state.
     * @param {string} taskId
     * @param {Object} anonData
     */
    updateTaskAnon(taskId, anonData) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        state.anon.stats = anonData;
        if (anonData && anonData.total_entities > 0) {
            state.anon.enabled = true;
        }

        document.dispatchEvent(new CustomEvent('da:task-state-updated', {
            detail: { taskId, field: 'anon', data: anonData }
        }));
    },

    /**
     * Update task chat state (backend, agentName, isAppendMode).
     * @param {string} taskId
     * @param {Object} chatState
     */
    updateTaskChat(taskId, chatState) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        Object.assign(state.chat, chatState);
    },

    /**
     * Mark task as completed and store final stats.
     * @param {string} taskId
     * @param {Object} finalStats
     */
    completeTask(taskId, finalStats) {
        const state = this.taskStates.get(taskId);
        if (!state) return;

        state.status = 'completed';
        if (finalStats) {
            Object.assign(state.stats, finalStats);
        }

        serverLog('[ViewContext] Task completed: ' + taskId);

        document.dispatchEvent(new CustomEvent('da:task-completed', {
            detail: { taskId, finalStats }
        }));

        // Prune old completed tasks
        this.pruneCompletedTasks();
    },

    /**
     * Mark task as errored.
     * @param {string} taskId
     * @param {string} error
     */
    errorTask(taskId, error) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        state.status = 'error';

        document.dispatchEvent(new CustomEvent('da:task-completed', {
            detail: { taskId, finalStats: null, error }
        }));
    },

    /**
     * Mark task as cancelled.
     * @param {string} taskId
     */
    cancelTask(taskId) {
        const state = this.taskStates.get(taskId);
        if (!state) return;
        state.status = 'cancelled';

        document.dispatchEvent(new CustomEvent('da:task-completed', {
            detail: { taskId, finalStats: null, cancelled: true }
        }));
    },

    // =========================================================================
    // [064] UI Phase State Machine
    // =========================================================================

    /**
     * Transition a task to a new UI phase.
     * Validates transition, updates state, applies UI changes (if viewed),
     * and syncs backward-compat globals.
     * @param {string} taskId
     * @param {string} newPhase - One of UI_PHASES values
     * @param {Object} data - Optional: { skipUI, message }
     * @returns {boolean} True if transition was valid
     */
    transitionTask(taskId, newPhase, data = {}) {
        const task = this.getTask(taskId);
        if (!task) {
            serverLog('[ViewContext] WARNING: transitionTask unknown task ' + taskId);
            return false;
        }

        // [064] Validate phase value
        const VALID_PHASE_VALUES = Object.values(UI_PHASES);
        if (!VALID_PHASE_VALUES.includes(newPhase)) {
            serverLog('[ViewContext] WARNING: Invalid phase value: ' + newPhase);
            return false;
        }

        const currentPhase = task.uiPhase || 'idle';
        const validNext = VALID_TRANSITIONS[currentPhase] || [];
        if (!validNext.includes(newPhase)) {
            serverLog('[ViewContext] WARNING: Invalid phase: ' + currentPhase + ' -> ' + newPhase + ' task=' + taskId);
            return false;
        }

        task.uiPhase = newPhase;

        // [068] When continuing after dialog confirmation, enable append mode
        // to preserve existing content in the result panel
        if (currentPhase === 'awaiting_input' && newPhase === 'thinking') {
            task.chat.isAppendMode = true;
        }

        serverLog('[ViewContext] Phase: ' + currentPhase + ' -> ' + newPhase + ' task=' + taskId);

        // UI rendering only for currently viewed task
        if (this.isViewed(taskId) && !data.skipUI) {
            this._applyUIForPhase(newPhase, { ...data, _fromPhase: currentPhase });
        }

        // Backward-compat: sync global booleans
        if (this.isViewed(taskId)) {
            this._syncDerivedGlobals(task);
        }

        return true;
    },

    /**
     * Apply UI side-effects for a phase transition (internal).
     * Only called for the currently viewed task.
     * @param {string} phase
     * @param {Object} data
     */
    _applyUIForPhase(phase, data = {}) {
        serverLog('[ViewContext] applyUI phase=' + phase);
        switch (phase) {
            case 'idle':
                if (typeof hideProcessingOverlay === 'function') hideProcessingOverlay();
                break;
            case 'loading':
                if (typeof showProcessingOverlay === 'function') {
                    showProcessingOverlay('loading', data.status || '');
                }
                break;
            case 'streaming': {
                // Agent is still working - actively ensure overlay stays visible.
                // [070] Instead of doing nothing (fragile), verify overlay is still showing.
                // If overlay was hidden by a race condition, re-show it.
                const overlay = document.getElementById('aiProcessingOverlay');
                if (overlay && overlay.dataset.mode === 'hidden') {
                    const fromPhase = data._fromPhase || '';
                    serverLog('[ViewContext] streaming: overlay was hidden (from=' + fromPhase + '), re-showing');
                    if (typeof showThinkingOverlay === 'function') {
                        showThinkingOverlay(true);
                    }
                }
                break;
            }
            case 'awaiting_input':
                if (typeof setLoading === 'function') setLoading(false);
                if (typeof hideProcessingOverlay === 'function') hideProcessingOverlay();
                break;
            case 'thinking':
                if (typeof showThinkingOverlay === 'function') {
                    showThinkingOverlay(true, data.message || '');
                }
                break;
            case 'done':
            case 'error':
                if (typeof hideProcessingOverlay === 'function') hideProcessingOverlay();
                break;
        }
    },

    /**
     * Sync derived global booleans from uiPhase (backward-compat).
     * Maps uiPhase to legacy pendingDialogShown and isAppendMode globals.
     * @param {Object} task - TaskState
     */
    _syncDerivedGlobals(task) {
        const phase = task.uiPhase;
        if (typeof pendingDialogShown !== 'undefined') {
            pendingDialogShown = (phase === 'awaiting_input');
        }
        // [067] Read from task.chat.isAppendMode (Single Source of Truth) instead of deriving from phase
        if (typeof isAppendMode !== 'undefined') {
            isAppendMode = task.chat.isAppendMode;
        }
    },

    /**
     * [067] Check if a dialog can be shown for a task (phase guard).
     * Returns false if task is already awaiting_input or thinking.
     * @param {string} taskId
     * @returns {boolean}
     */
    canShowDialog(taskId) {
        const phase = this.getTaskPhase(taskId);
        return phase !== 'awaiting_input' && phase !== 'thinking';
    },

    /**
     * Get current UI phase for a task.
     * @param {string} taskId
     * @returns {string|null}
     */
    getTaskPhase(taskId) {
        const task = this.getTask(taskId);
        return task ? (task.uiPhase || 'idle') : null;
    },

    // =========================================================================
    // Session Mapping (ex-global sessionTaskMap)
    // =========================================================================

    /**
     * Map a session ID to a task ID.
     * @param {string} sessionId
     * @param {string} taskId
     */
    mapSessionToTask(sessionId, taskId) {
        this.sessionTaskMap.set(sessionId, taskId);
    },

    /**
     * Get task ID for a session.
     * @param {string} sessionId
     * @returns {string|null}
     */
    getTaskForSession(sessionId) {
        return this.sessionTaskMap.get(sessionId) || null;
    },

    /**
     * Remove a session mapping.
     * @param {string} sessionId
     */
    removeSessionMapping(sessionId) {
        this.sessionTaskMap.delete(sessionId);
    },

    // =========================================================================
    // History Session Support
    // =========================================================================

    /**
     * Create a "virtual" TaskState from a completed session (for history display).
     * @param {Object} session - Session object from history API
     * @returns {Object} The created TaskState
     */
    createFromSession(session) {
        const virtualTaskId = 'history_' + session.id;

        const state = this._createTaskState({
            taskId: virtualTaskId,
            sessionId: session.id,
            agentName: session.agent_name || 'chat',
            backend: session.backend || 'unknown',
            status: 'completed',
            isFromHistory: true,
            uiPhase: 'done'  // [064] History sessions are always done
        });

        // Populate stats from session metadata
        state.stats = {
            duration: null,
            tokens: session.total_tokens ? session.total_tokens.toString() : null,
            cost: session.total_cost_usd ? '$' + session.total_cost_usd.toFixed(4) : null,
            inputTokens: 0,
            outputTokens: 0,
            costUsd: session.total_cost_usd || 0
        };

        // Set chat state
        state.chat.backend = session.backend || null;
        state.chat.agentName = session.agent_name || null;
        state.chat.isAppendMode = true;  // History sessions are always append

        // [071] Restore anonymization state from session metadata
        state.anon.enabled = session.anonymization_enabled === true;

        this.taskStates.set(virtualTaskId, state);
        this.sessionTaskMap.set(session.id, virtualTaskId);

        serverLog('[ViewContext] Created from session: ' + session.id + ' -> ' + virtualTaskId);
        return state;
    },

    // =========================================================================
    // Helpers
    // =========================================================================

    /**
     * Get all running task IDs.
     * @returns {string[]}
     */
    getRunningTaskIds() {
        const TERMINAL_TASK_STATES = ['done', 'error', 'cancelled'];
        const running = [];
        for (const [taskId, state] of this.taskStates) {
            if (!TERMINAL_TASK_STATES.includes(state.status)) {
                running.push(taskId);
            }
        }
        return running;
    }
};

// =============================================================================
// [030] Object.defineProperty Aliases for Backward Compatibility
// =============================================================================
// These aliases make existing global reads/writes go through ViewContext.
// webui-core.js declares these as `let` variables which are already initialized.
// We use Object.defineProperty on `window` to intercept reads/writes.
//
// IMPORTANT: `let` variables in non-module scripts are NOT on `window` in strict mode,
// but in non-strict mode (which these scripts use) they behave as window properties
// when declared at the top level. However, `let` in browsers does NOT create
// window properties. So we use a different approach: we keep the `let` variables
// in webui-core.js as-is, and modules that need the ViewContext value should
// read from ViewContext directly. The aliases below work for code that reads
// the global variables via `window.xxx` or implicit global lookup.

// Since `let` variables don't go on window, we need a different approach.
// We'll just keep the existing globals and sync them with ViewContext in key places.
// The main sync points are:
// 1. When ViewContext.switchView() fires da:view-switched
// 2. When agents/tasks write to globals, we also write to ViewContext

/**
 * Sync global variables FROM ViewContext's viewed task.
 * Called on da:view-switched to ensure legacy globals match the viewed task.
 */
function _syncGlobalsFromViewContext() {
    const task = ViewContext.getViewedTask();
    if (!task) return;

    // Sync globals that other modules read directly
    if (typeof currentTaskId !== 'undefined') currentTaskId = ViewContext.viewedTaskId;
    if (typeof currentSessionId !== 'undefined') currentSessionId = ViewContext.viewedSessionId;
    if (typeof currentChatBackend !== 'undefined' && task.chat.backend) {
        currentChatBackend = task.chat.backend;
    }
    if (typeof currentChatName !== 'undefined' && task.chat.agentName) {
        currentChatName = task.chat.agentName;
    }
    if (typeof isAppendMode !== 'undefined') {
        isAppendMode = task.chat.isAppendMode;
    }
    if (typeof loadingStartTime !== 'undefined' && task.overlay.startTime) {
        loadingStartTime = task.overlay.startTime;
    }

    // [064] Sync derived globals from uiPhase
    ViewContext._syncDerivedGlobals(task);
}

// Listen for view-switched to sync globals
document.addEventListener('da:view-switched', _syncGlobalsFromViewContext);

serverLog('[ViewContext] Module loaded (with global sync)');
