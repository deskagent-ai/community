/**
 * WebUI Comparison Module
 * Split view for comparing agent execution across multiple backends.
 * Shows parallel streaming output with live metrics.
 * Depends on: webui-core.js (state, API), webui-ui.js (helpers)
 */

// =============================================================================
// Comparison State
// =============================================================================

let comparisonOverlay = null;
let comparisonSSEConnections = [];
let comparisonStartTimes = {};

// =============================================================================
// Split View Creation
// =============================================================================

/**
 * Start parallel comparison of an agent across multiple backends.
 * @param {string} agentName - Name of the agent to run
 * @param {Array<string>} backends - List of backends to compare
 * @param {HTMLElement} tile - The tile element that triggered this
 * @param {boolean} dryRun - Whether to run in dry-run mode (default: true)
 */
async function startParallelComparison(agentName, backends, tile, dryRun = true) {
    serverLog('[Comparison] Starting parallel comparison for: ' + agentName);
    serverLog('[Comparison] Backends: ' + backends.join(', ') + ' | dry_run: ' + dryRun);

    // Clean up any existing comparison
    closeComparisonView();

    // Create split view overlay
    comparisonOverlay = createSplitViewOverlay(agentName, backends, dryRun);
    document.body.appendChild(comparisonOverlay);

    // Start all backend tasks
    for (let i = 0; i < backends.length; i++) {
        const backend = backends[i];
        comparisonStartTimes[backend] = Date.now();

        try {
            // Start agent with specific backend
            const params = new URLSearchParams({
                backend: backend,
                dry_run: dryRun ? 'true' : 'false'
            });
            const res = await fetch(`${API}/agent/${agentName}?${params}`);
            if (!res.ok) {
                updateComparisonColumn(i, null, 'error', `HTTP ${res.status}`);
                continue;
            }

            const data = await res.json();
            const taskId = data.task_id;

            if (!taskId) {
                updateComparisonColumn(i, null, 'error', 'No task_id returned');
                continue;
            }

            // Connect SSE for this backend
            connectComparisonSSE(taskId, i, backend);

        } catch (err) {
            serverError('[Comparison] Failed to start ' + backend + ': ' + err);
            updateComparisonColumn(i, null, 'error', err.message);
        }
    }
}

/**
 * Create the split view overlay for comparing backends.
 * @param {string} agentName - Name of the agent
 * @param {Array<string>} backends - List of backends
 * @param {boolean} dryRun - Whether running in dry-run mode
 * @returns {HTMLElement} The overlay element
 */
function createSplitViewOverlay(agentName, backends, dryRun = true) {
    const overlay = document.createElement('div');
    overlay.className = 'comparison-overlay';
    overlay.id = 'comparisonOverlay';

    // Determine column width based on backend count
    const colCount = Math.min(backends.length, 4);
    const colWidth = Math.floor(100 / colCount);

    // Build columns HTML
    const columnsHtml = backends.map((backend, idx) => `
        <div class="comparison-column" data-backend="${escapeHtml(backend)}" data-index="${idx}">
            <div class="comparison-column-header">
                <span class="material-icons">${getBackendIcon(backend)}</span>
                <span class="comparison-backend-name">${escapeHtml(backend)}</span>
                <span class="comparison-status-indicator running" title="${t('comparison.status_running')}">
                    <span class="material-icons">sync</span>
                </span>
            </div>
            <div class="comparison-column-content" id="comparisonContent${idx}">
                <div class="comparison-loading">
                    <span class="material-icons rotating">sync</span>
                    <span>${t('workflow.starting')}</span>
                </div>
            </div>
            <div class="comparison-column-metrics" id="comparisonMetrics${idx}">
                <div class="comparison-metric">
                    <span class="material-icons">schedule</span>
                    <span class="comparison-metric-value" id="comparisonTime${idx}">--</span>
                </div>
                <div class="comparison-metric">
                    <span class="material-icons">token</span>
                    <span class="comparison-metric-value" id="comparisonTokens${idx}">--</span>
                </div>
                <div class="comparison-metric">
                    <span class="material-icons">payments</span>
                    <span class="comparison-metric-value" id="comparisonCost${idx}">$--</span>
                </div>
            </div>
        </div>
    `).join('');

    overlay.innerHTML = `
        <div class="comparison-dialog" style="--col-count: ${colCount};">
            <div class="comparison-header">
                <span class="material-icons">compare</span>
                <h3>Backend Comparison: ${escapeHtml(agentName)}</h3>
                ${dryRun ? '<span class="comparison-dry-run-badge"><span class="material-icons">visibility</span>' + t('comparison.dry_run_badge') + '</span>' : ''}
                <button class="comparison-close-btn" onclick="closeComparisonView()" title="${t('dialog.close')}">
                    <span class="material-icons">close</span>
                </button>
            </div>
            <div class="comparison-columns">
                ${columnsHtml}
            </div>
            <div class="comparison-footer">
                <div class="comparison-summary" id="comparisonSummary">
                    ${t('comparison.comparing_backends', {count: backends.length})}
                </div>
                <div class="comparison-actions">
                    <button class="btn-secondary" onclick="downloadComparisonResults()">
                        <span class="material-icons">download</span> ${t('comparison.export_json')}
                    </button>
                    <button class="btn-primary" onclick="closeComparisonView()">
                        <span class="material-icons">check</span> ${t('dialog.close')}
                    </button>
                </div>
            </div>
        </div>
    `;

    // Close on overlay click (but not dialog click)
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closeComparisonView();
        }
    });

    // Close on Escape
    const keyHandler = (e) => {
        if (e.key === 'Escape') {
            closeComparisonView();
            document.removeEventListener('keydown', keyHandler);
        }
    };
    document.addEventListener('keydown', keyHandler);
    overlay._keyHandler = keyHandler;

    return overlay;
}

// =============================================================================
// SSE Streaming
// =============================================================================

/**
 * Connect SSE to stream output to a comparison column.
 * @param {string} taskId - The task ID to stream from
 * @param {number} columnIndex - The column index to update
 * @param {string} backend - The backend name
 */
function connectComparisonSSE(taskId, columnIndex, backend) {
    const eventSource = new EventSource(`${API}/task/${taskId}/stream`);
    comparisonSSEConnections.push(eventSource);

    let responseBuffer = '';
    let thinkingBuffer = '';
    let taskCompleted = false;  // Track if task finished (success/error/cancelled)

    // Helper to parse SSE data
    const parseData = (event) => {
        try {
            return JSON.parse(event.data);
        } catch (err) {
            serverError('[Comparison] SSE parse error: ' + err);
            return null;
        }
    };

    // Task start event
    eventSource.addEventListener('task_start', (event) => {
        const data = parseData(event);
        if (data) {
            serverLog('[Comparison] Task started for ' + backend + ': ' + data.task_id);
        }
    });

    // Token streaming event
    eventSource.addEventListener('token', (event) => {
        const data = parseData(event);
        if (data) {
            if (data.is_thinking) {
                thinkingBuffer += data.token || '';
            } else {
                responseBuffer += data.token || '';
                updateComparisonColumnContent(columnIndex, responseBuffer, 'streaming');
            }
        }
    });

    // Content sync event (full content replace, e.g., when tool markers are updated)
    eventSource.addEventListener('content_sync', (event) => {
        const data = parseData(event);
        if (data && data.content !== undefined) {
            if (data.is_thinking) {
                thinkingBuffer = data.content;
            } else {
                responseBuffer = data.content;
                updateComparisonColumnContent(columnIndex, responseBuffer, 'streaming');
            }
        }
    });

    // Tool call event
    eventSource.addEventListener('tool_call', (event) => {
        const data = parseData(event);
        if (data && data.tool_name) {
            const toolInfo = data.tool_name + (data.status === 'complete' && data.duration ? ` | ${data.duration}s` : ' ⏳');
            updateComparisonColumnTool(columnIndex, toolInfo, data.status);
        }
    });

    // Task complete event
    eventSource.addEventListener('task_complete', (event) => {
        taskCompleted = true;
        const data = parseData(event);
        serverLog('[Comparison] Task complete for ' + backend);
        if (data) {
            updateComparisonColumn(columnIndex, data, 'success');
        }
        eventSource.close();
    });

    // Task error event
    eventSource.addEventListener('task_error', (event) => {
        taskCompleted = true;
        const data = parseData(event);
        serverLog('[Comparison] Task error for ' + backend + ': ' + (data?.error || 'Unknown'));
        updateComparisonColumn(columnIndex, null, 'error', data?.error || 'Unknown error');
        eventSource.close();
    });

    // Task cancelled event
    eventSource.addEventListener('task_cancelled', (event) => {
        taskCompleted = true;
        serverLog('[Comparison] Task cancelled for ' + backend);
        updateComparisonColumn(columnIndex, null, 'error', 'Task cancelled');
        eventSource.close();
    });

    // Ping keepalive (ignore)
    eventSource.addEventListener('ping', () => {});

    // Connection error handler
    eventSource.onerror = (err) => {
        // Ignore if task already completed (connection close after completion is normal)
        if (taskCompleted) {
            eventSource.close();
            return;
        }
        // Only treat as error if we haven't received any content yet
        if (responseBuffer === '' && thinkingBuffer === '') {
            serverLog('[Comparison] SSE connection error for ' + backend);
            const content = document.getElementById('comparisonContent' + columnIndex);
            if (content && content.querySelector('.comparison-loading')) {
                updateComparisonColumn(columnIndex, null, 'error', 'Connection failed');
            }
        }
        eventSource.close();
    };
}

// =============================================================================
// Column Updates
// =============================================================================

/**
 * Update a comparison column with streaming content.
 */
function updateComparisonColumnContent(columnIndex, content, status) {
    const contentEl = document.getElementById('comparisonContent' + columnIndex);
    if (!contentEl) return;

    // Remove loading indicator
    const loading = contentEl.querySelector('.comparison-loading');
    if (loading) loading.remove();

    // Render markdown content (truncated for split view)
    const truncated = content.length > 2000 ? content.substring(0, 2000) + '\n\n...(truncated)' : content;
    contentEl.innerHTML = `<div class="comparison-output">${marked.parse(truncated)}</div>`;

    // Update timer
    updateComparisonTimer(columnIndex);
}

// Track tools per column for comparison view
const comparisonToolsState = {};

/**
 * Update a comparison column with tool call info.
 * Shows tool badges like the single view does.
 */
function updateComparisonColumnTool(columnIndex, toolInfo, status) {
    const contentEl = document.getElementById('comparisonContent' + columnIndex);
    if (!contentEl) return;

    // Initialize tools state for this column
    if (!comparisonToolsState[columnIndex]) {
        comparisonToolsState[columnIndex] = [];
    }

    // Parse tool name from toolInfo (format: "tool_name | 0.5s" or "tool_name ⏳")
    const toolName = toolInfo.split(' ')[0];

    // Update or add tool
    const existingIndex = comparisonToolsState[columnIndex].findIndex(t => t.name === toolName);
    if (existingIndex >= 0) {
        comparisonToolsState[columnIndex][existingIndex] = { name: toolName, info: toolInfo, status };
    } else {
        comparisonToolsState[columnIndex].push({ name: toolName, info: toolInfo, status });
    }

    // Render tools bar
    let toolsEl = contentEl.querySelector('.comparison-tools');
    if (!toolsEl) {
        toolsEl = document.createElement('div');
        toolsEl.className = 'comparison-tools';
        contentEl.prepend(toolsEl);
    }

    // Show last 5 tools as badges
    const tools = comparisonToolsState[columnIndex].slice(-5);
    toolsEl.innerHTML = tools.map(t => {
        const isComplete = t.status === 'complete';
        const icon = isComplete ? '✓' : '⏳';
        const shortName = t.name.replace(/^(outlook_|mcp__proxy__|graph_|paperless_)/, '');
        return `<span class="tool-badge ${isComplete ? 'complete' : 'running'}" title="${escapeHtml(t.info)}">${icon} ${escapeHtml(shortName)}</span>`;
    }).join(' ');
}

/**
 * Update comparison column with final result.
 */
function updateComparisonColumn(columnIndex, result, status, errorMsg = null) {
    const column = document.querySelector(`.comparison-column[data-index="${columnIndex}"]`);
    if (!column) return;

    const backend = column.dataset.backend;
    const contentEl = document.getElementById('comparisonContent' + columnIndex);
    const indicator = column.querySelector('.comparison-status-indicator');

    // Calculate duration
    const startTime = comparisonStartTimes[backend] || Date.now();
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);

    // Update status indicator
    if (indicator) {
        indicator.classList.remove('running');
        if (status === 'success') {
            indicator.classList.add('success');
            indicator.innerHTML = '<span class="material-icons">check_circle</span>';
            indicator.title = t('comparison.status_completed');
        } else if (status === 'error') {
            indicator.classList.add('error');
            indicator.innerHTML = '<span class="material-icons">error</span>';
            indicator.title = errorMsg || t('task.error');
        }
    }

    // Update content
    if (contentEl) {
        if (status === 'error') {
            contentEl.innerHTML = `<div class="comparison-error">
                <span class="material-icons">error</span>
                <span>${escapeHtml(errorMsg || 'Unknown error')}</span>
            </div>`;
        } else if (result) {
            // Show response preview - only if we have new content
            // (streaming content is already in contentEl from token events)
            const preview = result.response || result.content || '';
            if (preview) {
                const truncated = preview.length > 2000 ? preview.substring(0, 2000) + '\n\n...(truncated)' : preview;
                contentEl.innerHTML = `<div class="comparison-output">${marked.parse(truncated)}</div>`;
            }
            // If no preview in result, keep the existing streamed content
        }
    }

    // Update metrics
    document.getElementById('comparisonTime' + columnIndex).textContent = duration + 's';

    if (result) {
        const tokens = result.tokens || {};
        const inTok = tokens.input || result.input_tokens || 0;
        const outTok = tokens.output || result.output_tokens || 0;
        document.getElementById('comparisonTokens' + columnIndex).textContent =
            inTok || outTok ? `${inTok}/${outTok}` : '--';

        const cost = result.cost_usd || result.cost || 0;
        document.getElementById('comparisonCost' + columnIndex).textContent =
            cost > 0 ? `$${cost.toFixed(4)}` : '$0';
    }

    // Check if all backends are done
    checkComparisonComplete();
}

/**
 * Update timer for a running comparison column.
 */
function updateComparisonTimer(columnIndex) {
    const column = document.querySelector(`.comparison-column[data-index="${columnIndex}"]`);
    if (!column) return;

    const backend = column.dataset.backend;
    const startTime = comparisonStartTimes[backend];
    if (!startTime) return;

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const timeEl = document.getElementById('comparisonTime' + columnIndex);
    if (timeEl) {
        timeEl.textContent = duration + 's';
    }
}

// =============================================================================
// Completion & Summary
// =============================================================================

/**
 * Check if all comparisons are complete and update summary.
 */
function checkComparisonComplete() {
    const columns = document.querySelectorAll('.comparison-column');
    const indicators = document.querySelectorAll('.comparison-status-indicator');

    let completed = 0;
    let successful = 0;
    let fastest = null;
    let fastestTime = Infinity;
    let cheapest = null;
    let cheapestCost = Infinity;

    indicators.forEach((indicator, idx) => {
        if (indicator.classList.contains('success') || indicator.classList.contains('error')) {
            completed++;
            if (indicator.classList.contains('success')) {
                successful++;

                // Get metrics
                const timeEl = document.getElementById('comparisonTime' + idx);
                const costEl = document.getElementById('comparisonCost' + idx);

                if (timeEl) {
                    const time = parseFloat(timeEl.textContent);
                    if (time < fastestTime) {
                        fastestTime = time;
                        fastest = columns[idx].dataset.backend;
                    }
                }

                if (costEl) {
                    const costText = costEl.textContent.replace('$', '');
                    const cost = parseFloat(costText);
                    if (!isNaN(cost) && cost < cheapestCost) {
                        cheapestCost = cost;
                        cheapest = columns[idx].dataset.backend;
                    }
                }
            }
        }
    });

    if (completed === columns.length) {
        // All done - update summary
        const summary = document.getElementById('comparisonSummary');
        if (summary) {
            let summaryHtml = `<span class="comparison-result-count">${successful}/${columns.length} ${t('comparison.successful')}</span>`;

            if (fastest) {
                summaryHtml += ` | <span class="comparison-winner"><span class="material-icons">speed</span> ${t('comparison.fastest')}: <strong>${fastest}</strong> (${fastestTime}s)</span>`;
            }
            if (cheapest && cheapestCost > 0) {
                summaryHtml += ` | <span class="comparison-winner"><span class="material-icons">savings</span> ${t('comparison.cheapest')}: <strong>${cheapest}</strong> ($${cheapestCost.toFixed(4)})</span>`;
            }

            summary.innerHTML = summaryHtml;
        }

        serverLog('[Comparison] Complete: ' + successful + '/' + columns.length + ' successful');
    }
}

// =============================================================================
// Cleanup & Export
// =============================================================================

/**
 * Close the comparison view and clean up.
 */
function closeComparisonView() {
    // Close all SSE connections
    comparisonSSEConnections.forEach(sse => {
        try { sse.close(); } catch (e) {}
    });
    comparisonSSEConnections = [];
    comparisonStartTimes = {};

    // Clear tool state for all columns
    for (const key in comparisonToolsState) {
        delete comparisonToolsState[key];
    }

    // Remove overlay
    if (comparisonOverlay) {
        if (comparisonOverlay._keyHandler) {
            document.removeEventListener('keydown', comparisonOverlay._keyHandler);
        }
        comparisonOverlay.remove();
        comparisonOverlay = null;
    }
}

/**
 * Download comparison results as JSON.
 */
function downloadComparisonResults() {
    const columns = document.querySelectorAll('.comparison-column');
    const results = {};

    columns.forEach((col, idx) => {
        const backend = col.dataset.backend;
        const timeEl = document.getElementById('comparisonTime' + idx);
        const tokensEl = document.getElementById('comparisonTokens' + idx);
        const costEl = document.getElementById('comparisonCost' + idx);
        const indicator = col.querySelector('.comparison-status-indicator');
        const contentEl = col.querySelector('.comparison-column-content');

        // Get response text from the content element
        let response = '';
        if (contentEl) {
            // Try to get the text content, stripping HTML
            response = contentEl.innerText || contentEl.textContent || '';
        }

        results[backend] = {
            success: indicator.classList.contains('success'),
            duration_sec: timeEl ? parseFloat(timeEl.textContent) : 0,
            tokens: tokensEl ? tokensEl.textContent : '--',
            cost: costEl ? costEl.textContent : '$--',
            response: response.trim()
        };
    });

    const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'comparison_' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
    a.click();
    URL.revokeObjectURL(url);
}

// =============================================================================
// Results Dialog (Post-Comparison Summary)
// =============================================================================

/**
 * Show comparison results in a summary dialog.
 * Called when comparison endpoint returns (non-streaming mode).
 */
function showComparisonResults(comparison) {
    closeComparisonView();

    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    // Build results table
    const backends = comparison.backends || {};
    const rows = Object.entries(backends).map(([name, data]) => `
        <tr class="${data.success ? '' : 'comparison-row-error'}">
            <td>
                <span class="material-icons" style="font-size: 14px; vertical-align: middle; margin-right: 4px;">${getBackendIcon(name)}</span>
                <strong>${escapeHtml(name)}</strong>
            </td>
            <td>${data.duration_sec ? data.duration_sec.toFixed(1) + 's' : '--'}</td>
            <td>${data.tokens?.input || 0} / ${data.tokens?.output || 0}</td>
            <td>$${data.cost_usd?.toFixed(4) || '0.0000'}</td>
            <td>
                <span class="material-icons" style="color: ${data.success ? 'var(--success)' : 'var(--error)'};">
                    ${data.success ? 'check_circle' : 'cancel'}
                </span>
            </td>
        </tr>
    `).join('');

    const winner = comparison.winner || {};

    overlay.innerHTML = `
        <div class="confirm-dialog comparison-results-dialog">
            <div class="confirm-header">
                <span class="material-icons">compare</span>
                <h3>Backend Comparison: ${escapeHtml(comparison.agent)}</h3>
            </div>
            <div style="padding: 16px 0;">
                <table class="comparison-results-table">
                    <thead>
                        <tr>
                            <th>${t('comparison.backend')}</th>
                            <th>${t('comparison.time')}</th>
                            <th>${t('comparison.tokens_in_out')}</th>
                            <th>${t('comparison.cost')}</th>
                            <th>${t('comparison.status')}</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>

                ${winner.fastest || winner.cheapest ? `
                <div class="comparison-winners">
                    ${winner.fastest ? `<span><span class="material-icons">speed</span> ${t('comparison.fastest')}: <strong>${winner.fastest}</strong></span>` : ''}
                    ${winner.cheapest ? `<span><span class="material-icons">savings</span> ${t('comparison.cheapest')}: <strong>${winner.cheapest}</strong></span>` : ''}
                </div>
                ` : ''}

                ${comparison.file ? `
                <p style="font-size: 11px; color: var(--text-secondary); margin-top: 12px;">
                    ${t('comparison.results_saved_to')}: ${escapeHtml(comparison.file)}
                </p>
                ` : ''}
            </div>
            <div class="confirm-buttons">
                <button class="btn-confirm" onclick="this.closest('.confirm-overlay').remove()">${t('dialog.close')}</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
}

// =============================================================================
// Helper: Get Backend Icon
// =============================================================================

/**
 * Get Material icon name for a backend.
 */
function getBackendIcon(backend) {
    const name = (backend || '').toLowerCase();
    if (name.includes('claude')) return 'smart_toy';
    if (name.includes('gemini')) return 'auto_awesome';
    if (name.includes('openai') || name.includes('gpt')) return 'psychology';
    if (name.includes('ollama') || name.includes('qwen') || name.includes('mistral')) return 'memory';
    return 'model_training';
}
