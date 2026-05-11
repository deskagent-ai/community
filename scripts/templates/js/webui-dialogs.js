/**
 * WebUI Dialogs Module
 * Confirmation dialogs (CONFIRMATION_NEEDED), question dialogs (QUESTION_NEEDED),
 * anonymization badge, user response handling.
 * Depends on: webui-core.js (state), webui-ui.js (UI helpers)
 */

// =============================================================================
// Anonymization Badge
// =============================================================================

/**
 * Reset anonymization badge to inactive state.
 * Call this when a task starts to clear previous state.
 * @param {boolean} anonDisabled - true if anonymization is disabled globally
 */
function resetAnonBadge(anonDisabled = false) {
    const badge = document.getElementById('anonBadge');
    const icon = document.getElementById('anonIcon');
    const text = document.getElementById('anonText');

    if (!badge || !icon || !text) return;

    // Reset counters for pulse animation AND previous session stats
    lastAnonTotal = 0;
    lastToolCallsAnonymized = 0;
    lastAnonStats = null;  // [028] Clear old session data so badge shows "ON" not old count

    badge.classList.remove('pulse');

    if (anonDisabled) {
        // Anonymization is disabled - show OFF state
        badge.classList.remove('online');
        badge.classList.add('offline', 'anon-off');
        icon.textContent = 'lock_open';
        text.textContent = 'OFF';
        badge.title = t('anon.pii_disabled');
        badge.style.cursor = 'default';
        badge.onclick = null;
    } else if (lastAnonStats && lastAnonStats.total_entities > 0) {
        // Anonymization enabled AND we have previous stats - keep badge GREEN with count
        badge.classList.remove('offline', 'anon-off');
        badge.classList.add('online');
        icon.textContent = 'verified_user';
        text.textContent = lastAnonStats.total_entities.toString();
        badge.title = `${t('anon.pii_active')}\n${lastAnonStats.total_entities} ${t('anon.entities_protected')}\n\n${t('anon.click_for_details')}`;
        badge.style.cursor = 'pointer';
        badge.onclick = () => showAnonDetails(lastAnonStats);
    } else {
        // Anonymization enabled but no data yet - show GREEN "active" state immediately
        badge.classList.remove('offline', 'anon-off');
        badge.classList.add('online');
        icon.textContent = 'verified_user';
        text.textContent = 'ON';
        badge.title = `${t('anon.pii_active')}\n${t('anon.no_entities_yet')}`;
        badge.style.cursor = 'default';
        badge.onclick = null;
    }
}

function updateAnonBadge(stats) {
    if (!stats) return;

    lastAnonStats = stats;
    const badge = document.getElementById('anonBadge');
    const icon = document.getElementById('anonIcon');
    const text = document.getElementById('anonText');

    if (!badge || !icon || !text) return;

    // Update badge to show active anonymization
    badge.classList.remove('offline', 'anon-off');
    badge.classList.add('online');
    icon.textContent = 'verified_user';

    const total = stats.total_entities || 0;
    const toolCalls = stats.tool_calls_anonymized || 0;

    // Trigger pulse animation when total entities OR tool calls increase
    if (total > lastAnonTotal || toolCalls > lastToolCallsAnonymized) {
        badge.classList.add('pulse');
        setTimeout(() => badge.classList.remove('pulse'), 500);
    }
    lastAnonTotal = total;
    lastToolCallsAnonymized = toolCalls;

    // Simple display: just the total count
    text.textContent = total > 0 ? total.toString() : 'PII';

    // Build tooltip with type breakdown
    const types = stats.entity_types || {};
    const tooltipParts = [];
    if (types.PERSON) tooltipParts.push(`${types.PERSON} ${t('anon.persons')}`);
    if (types.EMAIL || types.EMAIL_ADDRESS) tooltipParts.push(`${types.EMAIL || types.EMAIL_ADDRESS} ${t('anon.emails')}`);
    if (types.LOCATION) tooltipParts.push(`${types.LOCATION} ${t('anon.locations')}`);
    if (types.URL) tooltipParts.push(`${types.URL} ${t('anon.urls')}`);
    if (types.PHONE_NUMBER) tooltipParts.push(`${types.PHONE_NUMBER} ${t('anon.phone_numbers')}`);

    let tooltip = `${t('anon.pii_active')}\n${total} ${t('anon.entities_protected')}`;
    if (tooltipParts.length > 0) {
        tooltip += '\n---\n' + tooltipParts.join('\n');
    }
    tooltip += `\n\n${t('anon.click_for_details')}`;
    badge.title = tooltip;

    // Make badge clickable to show details
    badge.style.cursor = 'pointer';
    badge.onclick = () => showAnonDetails(stats);
}

function showAnonDetails(stats) {
    // Cleanup any modifier tooltip (Ctrl/Shift indicator) that might be showing
    if (typeof cleanupModifierTooltip === 'function') {
        cleanupModifierTooltip();
    }

    // Hide processing overlay while dialog is open (prevents bleed-through)
    const processingOverlay = document.getElementById('aiProcessingOverlay');
    if (processingOverlay) {
        processingOverlay.dataset.mode = 'hidden';
    }

    // Use global lastAnonStats if no stats provided
    stats = stats || lastAnonStats;
    if (!stats) return;

    const types = stats.entity_types || {};
    const typesList = [];
    if (types.PERSON) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">person</span>${types.PERSON} ${t('anon.persons')}`);
    if (types.EMAIL || types.EMAIL_ADDRESS) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">email</span>${types.EMAIL || types.EMAIL_ADDRESS} ${t('anon.emails')}`);
    if (types.LOCATION) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">place</span>${types.LOCATION} ${t('anon.locations')}`);
    if (types.URL) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">link</span>${types.URL} ${t('anon.urls')}`);
    if (types.PHONE_NUMBER) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">phone</span>${types.PHONE_NUMBER} ${t('anon.phone_numbers')}`);
    if (types.IBAN) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">account_balance</span>${types.IBAN} ${t('anon.ibans')}`);
    if (types.DATE_TIME) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">event</span>${types.DATE_TIME} ${t('anon.dates')}`);
    if (types.CREDIT_CARD) typesList.push(`<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 6px; color: var(--text-secondary);">credit_card</span>${types.CREDIT_CARD} ${t('anon.credit_cards')}`)

    // Build mappings table HTML
    const mappings = stats.mappings || {};
    const mappingRows = Object.entries(mappings).map(([placeholder, value]) => {
        // Escape HTML in values
        const safeValue = (value || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const safePlaceholder = placeholder.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `<tr>
            <td style="padding: 4px 8px; font-family: monospace; color: var(--accent); font-size: 11px; white-space: nowrap;">${safePlaceholder}</td>
            <td style="padding: 4px 8px; font-size: 12px; word-break: break-word; max-width: 200px;">${safeValue}</td>
        </tr>`;
    }).join('');

    const mappingsSection = Object.keys(mappings).length > 0 ? `
        <div style="margin-top: 12px; border-top: 1px solid var(--border); padding-top: 12px; min-height: 0; display: flex; flex-direction: column; overflow: hidden;">
            <div style="font-size: 12px; font-weight: 600; margin-bottom: 8px; color: var(--text-secondary); flex-shrink: 0;">${t('anon.replacements')}:</div>
            <div style="overflow-y: auto; flex: 1; min-height: 0;">
                <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
                    <tbody>${mappingRows}</tbody>
                </table>
            </div>
        </div>
    ` : '';

    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="confirm-dialog" style="max-width: 450px; max-height: 80vh; display: flex; flex-direction: column; overflow: hidden;">
            <div class="confirm-header" style="flex-shrink: 0;">
                <span class="material-icons" style="color: var(--success);">verified_user</span>
                <h3>${t('anon.pii_protection')}</h3>
            </div>
            <div style="padding: 16px 20px; flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; flex-shrink: 0;">
                    <div style="background: var(--bg-secondary); padding: 12px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 24px; font-weight: bold; color: var(--success);">${stats.total_entities || 0}</div>
                        <div style="font-size: 12px; color: var(--text-secondary);">${t('anon.entities')}</div>
                    </div>
                    <div style="background: var(--bg-secondary); padding: 12px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 24px; font-weight: bold;">${stats.tool_calls_anonymized || 0}</div>
                        <div style="font-size: 12px; color: var(--text-secondary);">${t('anon.tool_calls')}</div>
                    </div>
                </div>
                <div style="font-size: 13px; flex-shrink: 0;">
                    ${typesList.map(item => `<div style="padding: 4px 0;">${item}</div>`).join('')}
                </div>
                ${mappingsSection}
            </div>
            <div class="confirm-buttons" style="flex-shrink: 0;">
                <button class="btn-confirm" onclick="this.closest('.confirm-overlay').remove()">${t('dialog.close')}</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
}

// =============================================================================
// Dialog State Management
// =============================================================================

function resetPendingDialogState() {
    // Reset all dialog-related state for clean next dialog
    // [067] C1: pendingDialogShown removed - transitionTask() handles this via _syncDerivedGlobals
    // Don't reset pendingPollContext here - let the caller do it when appropriate

    // Reset prompt input placeholder
    const promptInput = document.getElementById('promptInput');
    if (promptInput) {
        promptInput.placeholder = t('prompt.placeholder');
    }

    // #12 - Clear all pending state to prevent session context leak
    pendingPollContext = null;
    isSubmittingResponse = false;  // Reset submission guard
}

function cleanupQuestionDialog() {
    // Remove inline question box if exists
    const questionBox = document.getElementById('inlineQuestionBox');
    if (questionBox) {
        if (questionBox._keyHandler) {
            document.removeEventListener('keydown', questionBox._keyHandler);
        }
        questionBox.remove();
    }

    // Remove inline confirm box if exists
    const confirmBox = document.getElementById('inlineConfirmBox');
    if (confirmBox) {
        if (confirmBox._keyHandler) {
            document.removeEventListener('keydown', confirmBox._keyHandler);
        }
        confirmBox.remove();
    }

    // Remove overlay if exists (legacy fallback)
    const overlay = document.querySelector('.confirm-overlay');
    if (overlay) {
        if (overlay._keyHandler) {
            document.removeEventListener('keydown', overlay._keyHandler);
        }
        overlay.remove();
    }

    // Reset dialog state
    resetPendingDialogState();
}

// =============================================================================
// Confirmation Dialog (CONFIRMATION_NEEDED - Data Forms)
// =============================================================================

function showConfirmationDialog(taskId, input, tile, name, isAgent) {
    // In Quick Access mode, open full UI for dialogs (forms need more space)
    if (typeof isQuickAccessMode !== 'undefined' && isQuickAccessMode) {
        console.log('[WebUI] Quick Access: Opening full UI for dialog, task:', taskId);
        const width = 900, height = 700;
        const left = Math.max(0, (screen.width - width) / 2);
        const top = Math.max(0, (screen.height - height) / 2);
        window.open(
            `/?task=${taskId}&agent=${encodeURIComponent(name)}&isAgent=${isAgent}`,
            'deskagent_main',
            `width=${width},height=${height},left=${left},top=${top},resizable=yes`
        );
        return;  // Don't show inline dialog - full UI will handle it
    }

    // [064/070] Phase-Guard: skip duplicate/stale dialog
    // Guard against awaiting_input (duplicate) AND thinking (stale event after user confirmed)
    const phase = ViewContext.getTaskPhase(taskId);
    if (phase === 'awaiting_input' || phase === 'thinking') {
        serverLog('[Dialog] Skip dialog in phase=' + phase + ' (guard)');
        return;
    }
    ViewContext.transitionTask(taskId, 'awaiting_input');

    removeExistingOverlay('.confirm-overlay');
    removeExistingOverlay('#inlineConfirmBox');

    // Cleanup any modifier tooltip (Ctrl/Shift indicator)
    if (typeof cleanupModifierTooltip === 'function') {
        cleanupModifierTooltip();
    }

    // Store on_cancel behavior for later
    const onCancel = input.on_cancel || 'abort';
    pendingPollContext = { taskId, tile, name, isAgent, onCancel, data: input.data };

    // Check if this is a question dialog (not a data confirmation form)
    // A question dialog:
    // - has type === 'question', OR
    // - has custom options array, OR
    // - has empty/minimal data (no form fields to display)
    const hasCustomOptions = input.options && input.options.length > 0;
    const hasMinimalData = (Object.keys(input.data || {}).length === 0) ||
        (Object.keys(input.data || {}).length === 1 && input.data.type === 'question');
    const isQuestionDialog = input.type === 'question' || hasCustomOptions || hasMinimalData;

    if (isQuestionDialog) {
        showQuestionDialog(taskId, input, tile, name, isAgent, onCancel);
        return;
    }

    const fieldLabels = {
        firma: t('field.company'), company: t('field.company'), name: t('field.name'),
        ansprechpartner: t('field.contact_person'), contact_person: t('field.contact_person'),
        email: t('field.email'), telefon: t('field.phone'), phone: t('field.phone'),
        strasse: t('field.street'), street: t('field.street'),
        plz: t('field.zip'), zip_code: t('field.zip'), zip: t('field.zip'),
        ort: t('field.city'), city: t('field.city'),
        land: t('field.country'), country: t('field.country')
    };

    const fieldsHtml = Object.entries(input.data).map(([key, value]) => {
        const isEditable = input.editable_fields?.includes(key) ?? true;
        const label = fieldLabels[key.toLowerCase()] || key;
        return `
            <div class="inline-confirm-field">
                <label>${escapeHtml(label)}</label>
                <input type="text" name="${escapeHtml(key)}" value="${escapeHtml(value || '')}" ${isEditable ? '' : 'readonly'}>
            </div>
        `;
    }).join('');

    // Build buttons based on on_cancel behavior
    // on_cancel="continue" -> 3 buttons: Cancel, Correct, OK
    // on_cancel="abort" -> 2 buttons: Cancel, OK
    const buttonsHtml = onCancel === 'continue'
        ? `<button class="inline-confirm-btn btn-abort" onclick="submitConfirmation('abort')">${t('dialog.cancel')}</button>
           <button class="inline-confirm-btn btn-correct" onclick="submitConfirmation('correct')">${t('dialog.correct')}</button>
           <button class="inline-confirm-btn btn-confirm" onclick="submitConfirmation(true)">${t('dialog.ok_enter')}</button>`
        : `<button class="inline-confirm-btn btn-cancel" onclick="submitConfirmation(false)">${t('dialog.cancel')}</button>
           <button class="inline-confirm-btn btn-confirm" onclick="submitConfirmation(true)">${t('dialog.ok_enter')}</button>`;

    // Create inline confirmation box (like QUESTION_NEEDED)
    const confirmBox = document.createElement('div');
    confirmBox.className = 'inline-confirm-box';
    confirmBox.id = 'inlineConfirmBox';
    confirmBox.innerHTML = `
        <div class="inline-confirm-content">
            <div class="inline-confirm-header">
                <span class="material-icons">pause_circle</span>
                <h4>${t('dialog.confirmation_required')}</h4>
            </div>
            <p class="inline-confirm-question">${escapeHtml(input.question)}</p>
            <div class="inline-confirm-fields">${fieldsHtml}</div>
            <div class="inline-confirm-buttons">
                ${buttonsHtml}
            </div>
        </div>
    `;

    // Append to result content (inline, not overlay)
    const resultContent = document.getElementById('resultContent');
    resultContent.appendChild(confirmBox);

    // Scroll to confirmation box
    confirmBox.scrollIntoView({ behavior: 'smooth', block: 'end' });

    // Focus first confirm button
    const confirmBtn = confirmBox.querySelector('.btn-confirm');
    if (confirmBtn) confirmBtn.focus();

    const keyHandler = function(e) {
        // Ignore if user is typing in an input field (allow editing data)
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            // But still allow Enter to submit from within an input field
            if (e.key === 'Enter') {
                e.preventDefault();
                document.removeEventListener('keydown', keyHandler);
                submitConfirmation(true);
            }
            return;
        }

        if (e.key === 'Enter') {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            submitConfirmation(true);
        } else if (e.key === 'Escape') {
            // If recording, cancel recording instead of closing dialog
            if (typeof isRecording !== 'undefined' && isRecording) {
                e.preventDefault();
                if (typeof cancelRecording === 'function') cancelRecording();
                return;
            }
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            // #12 - ESC key cleanup: submitConfirmation(false) clears pendingPollContext
            submitConfirmation(false);
        }
    };
    document.addEventListener('keydown', keyHandler);
    confirmBox._keyHandler = keyHandler;

    // [064] Loading/overlay hidden by transitionTask('awaiting_input') above
    document.getElementById('resultPanel').classList.add('visible');

    // Update title to show waiting state
    document.getElementById('resultTitle').textContent = name + ' - ' + t('dialog.waiting_confirmation');
}

async function submitConfirmation(action) {
    if (!pendingPollContext) return;

    const { taskId, tile, name, isAgent, onCancel, data: confirmData } = pendingPollContext;
    const confirmBox = document.getElementById('inlineConfirmBox');
    const overlay = document.querySelector('.confirm-overlay'); // Legacy fallback

    // Handle "correct" action - open prompt window for user input
    if (action === 'correct') {
        // Store correction mode context
        correctionMode = { taskId, tile, name, isAgent, data: confirmData };

        // Close inline dialog
        if (confirmBox) {
            if (confirmBox._keyHandler) document.removeEventListener('keydown', confirmBox._keyHandler);
            confirmBox.remove();
        }
        // Legacy: Close overlay if present
        if (overlay) {
            if (overlay._keyHandler) document.removeEventListener('keydown', overlay._keyHandler);
            overlay.remove();
        }

        // Reset dialog state
        resetPendingDialogState();

        // Show prompt area with correction hint
        setLoading(false);
        hideProcessingOverlay();  // Hide unified processing overlay
        document.getElementById('resultPanel').classList.remove('visible');
        document.querySelector('.tile-grid').classList.add('hidden');

        const promptArea = document.querySelector('.prompt-area');
        promptArea.classList.remove('hidden');

        const promptInput = document.getElementById('promptInput');
        promptInput.placeholder = t('dialog.correction_placeholder');
        promptInput.focus();

        // Update send button text
        document.getElementById('sendBtn').textContent = t('dialog.send_correction');

        pendingPollContext = null;
        return;
    }

    // Collect field values from inline box or legacy overlay
    const fields = {};
    const fieldsContainer = confirmBox || overlay;
    if (fieldsContainer) {
        fieldsContainer.querySelectorAll('.inline-confirm-field input, .confirm-field input').forEach(input => {
            fields[input.name] = input.value;
        });
    }

    // Determine if this is a confirmation (true) or cancellation (false/'abort')
    const confirmed = action === true;

    // [064] Show thinking overlay BEFORE fetch (SSE done event might fire during await!)
    if (confirmed) {
        const loadingText = document.getElementById('aiProcessingText');
        if (loadingText) loadingText.innerHTML = t('dialog.continuing') + '<span class="loading-dots"></span>';
        // [064] Transition to thinking (shows overlay + syncs isAppendMode via globals)
        ViewContext.transitionTask(taskId, 'thinking', {
            message: t('dialog.continuing') + '...'
        });
    }

    // [061] Close dialog and reset state BEFORE fetch to prevent SSE race condition
    // When Round 2 is faster than POST response, SSE pending_input event arrives
    // while pendingDialogShown is still true -> event ignored -> Dialog 2 never shown
    if (confirmBox) {
        if (confirmBox._keyHandler) document.removeEventListener('keydown', confirmBox._keyHandler);
        confirmBox.remove();
    }
    if (overlay) {
        if (overlay._keyHandler) document.removeEventListener('keydown', overlay._keyHandler);
        overlay.remove();
    }
    resetPendingDialogState();

    // #16 - Add timeout to dialog response fetch
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        const res = await fetch(`${API}/task/${taskId}/respond`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed, data: fields }),
            signal: controller.signal
        });
        clearTimeout(timeoutId);

        const data = await res.json();

        if (res.ok) {
            // [061] DOM cleanup already done above (before fetch)

            if (confirmed) {
                // [064] Add user's confirmation with data table to conversation
                let confirmedHtml = '<span class="answer-checkmark">&#10003;</span>\n'
                    + '<strong>' + t('dialog.confirmed') + '</strong>';
                if (Object.keys(fields).length > 0) {
                    confirmedHtml += '<div class="inline-question-data" style="margin-top: 8px;">';
                    for (const [key, val] of Object.entries(fields)) {
                        confirmedHtml += '<div class="inline-question-data-row">'
                            + '<span class="data-label">' + escapeHtml(key) + ':</span> '
                            + '<span class="data-value">' + escapeHtml(String(val || '')) + '</span>'
                            + '</div>';
                    }
                    confirmedHtml += '</div>';
                }
                addUserTurnToConversation(confirmedHtml, true);

                // Remove old streamingResponse ID so new agent content gets a fresh div
                const oldStreamingDiv = document.getElementById('streamingResponse');
                if (oldStreamingDiv) {
                    oldStreamingDiv.removeAttribute('id');
                }
                // Overlay already shown before fetch, SSE will hide it on done

                // Reconnect SSE if connection was lost during dialog
                // (onerror may have killed EventSource while dialog was shown)
                if (!activeEventSources[taskId]) {
                    console.log('[SSE] Reconnecting after confirmation response');
                    streamTask(taskId, tile, name, isAgent);
                }

                // [063] Signal backend that SSE is ready for next round
                // Small delay to ensure EventSource.onopen has fired
                setTimeout(async () => {
                    try {
                        await fetch(`${API}/task/${taskId}/round-ready`, { method: 'POST' });
                        console.log('[Handshake] Round-ready signaled for task', taskId);
                    } catch (e) {
                        console.warn('[Handshake] Failed to signal round-ready:', e);
                    }
                }, 200);
            } else {
                // Add user's cancellation to conversation history
                addUserTurnToConversation(t('dialog.cancelled') + ' ✗');

                // Full abort (either 'abort' action or false with on_cancel='abort')
                const loadingTextEl = document.getElementById('aiProcessingText');
                if (loadingTextEl) loadingTextEl.innerHTML = t('dialog.cancelled');
                // [064] Transition to idle (hides overlays via _applyUIForPhase)
                ViewContext.transitionTask(taskId, 'idle');
                if (tile) showTileResult(tile, false);
                showResultPanel(name, t('dialog.cancelled_by_user'), true, null, null);
            }
        } else {
            // Error response - hide overlay if we showed it
            if (confirmed) {
                // [064] Transition to error (hides overlays + syncs isAppendMode via globals)
                ViewContext.transitionTask(taskId, 'error');
            }
            alert(t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error')));
        }
    } catch (e) {
        clearTimeout(timeoutId);  // #16 - Clear timeout on error
        // Network error - hide overlay if we showed it
        if (confirmed) {
            // [064] Transition to error (hides overlays + syncs isAppendMode via globals)
            ViewContext.transitionTask(taskId, 'error');
        }
        // #16 - Handle timeout specifically
        if (e.name === 'AbortError') {
            console.error('[Dialog] Response timeout after 30s');
            alert(t('task.timeout_error') || 'Request timed out. Please try again.');
        } else {
            alert(t('task.connection_error') + ' ' + e.message);
        }
    }

    pendingPollContext = null;
}

// =============================================================================
// Question Dialog (QUESTION_NEEDED - Button Options)
// =============================================================================

function showQuestionDialog(taskId, input, tile, name, isAgent, onCancel) {
    // Show question INLINE at the end of result content (not as overlay)
    pendingPollContext = { taskId, tile, name, isAgent, onCancel, data: input.data || {} };

    // Remove any existing dialogs (legacy cleanup)
    removeExistingOverlay('.confirm-overlay');
    removeExistingOverlay('#inlineQuestionBox');

    // Cleanup any modifier tooltip (Ctrl/Shift indicator)
    if (typeof cleanupModifierTooltip === 'function') {
        cleanupModifierTooltip();
    }

    // Get custom options or use defaults
    const options = input.options || [
        { value: 'yes', label: t('dialog.yes'), class: 'btn-confirm' },
        { value: 'no', label: t('dialog.no'), class: 'btn-cancel' }
    ];

    // Build buttons from options (user can also type in prompt area below)
    const buttonsHtml = options.map((opt, idx) => {
        const btnClass = opt.class || (idx === 0 ? 'btn-confirm' : 'btn-cancel');
        return `<button class="inline-question-btn ${btnClass}" onclick="submitQuestionResponse('${opt.value}')">${escapeHtml(opt.label)}</button>`;
    }).join('\n           ');

    // Build data display if data object is provided (e.g., contact data for confirmation)
    let dataHtml = '';
    const data = input.data || {};
    const dataKeys = Object.keys(data).filter(k => k !== 'type'); // Exclude internal 'type' field
    if (dataKeys.length > 0) {
        const fieldLabels = {
            firma: t('field.company'), company: t('field.company'), name: t('field.name'),
            ansprechpartner: t('field.contact_person'), contact_person: t('field.contact_person'),
            email: t('field.email'), telefon: t('field.phone'), phone: t('field.phone'),
            strasse: t('field.street'), street: t('field.street'),
            plz: t('field.zip'), zip: t('field.zip'), zip_code: t('field.zip'),
            ort: t('field.city'), city: t('field.city'),
            land: t('field.country'), country: t('field.country')
        };
        const dataRows = dataKeys.map(key => {
            const label = fieldLabels[key.toLowerCase()] || key;
            const value = data[key] || '';
            return `<div class="inline-question-data-row">
                <span class="data-label">${escapeHtml(label)}:</span>
                <span class="data-value">${escapeHtml(value)}</span>
            </div>`;
        }).join('');
        dataHtml = `<div class="inline-question-data">${dataRows}</div>`;
    }

    // Create inline question box
    const questionBox = document.createElement('div');
    questionBox.className = 'inline-question-box';
    questionBox.id = 'inlineQuestionBox';
    questionBox.innerHTML = `
        <div class="inline-question-content">
            <p class="inline-question-text">❓ ${escapeHtml(input.question)}</p>
            ${dataHtml}
            <div class="inline-question-buttons">
                ${buttonsHtml}
            </div>
        </div>
    `;

    // Append to result content
    const resultContent = document.getElementById('resultContent');
    resultContent.appendChild(questionBox);

    // Scroll to question
    questionBox.scrollIntoView({ behavior: 'smooth', block: 'end' });

    // Focus first button
    const firstBtn = questionBox.querySelector('button');
    if (firstBtn) firstBtn.focus();

    // Keyboard shortcuts (only when not typing in input field)
    const keyHandler = function(e) {
        // Ignore keyboard shortcuts if user is typing in an input/textarea
        // (they can submit their custom response via the prompt input)
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }

        if (e.key === 'Enter' || e.key === 'y' || e.key === 'Y' || e.key === 'j' || e.key === 'J') {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            submitQuestionResponse(options[0]?.value || 'yes');
        } else if (e.key === 'Escape' || e.key === 'n' || e.key === 'N') {
            // If recording, cancel recording instead of answering 'no'
            if (typeof isRecording !== 'undefined' && isRecording) {
                e.preventDefault();
                if (typeof cancelRecording === 'function') cancelRecording();
                return;
            }
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            // #12 - ESC/N key cleanup: submitQuestionResponse clears pendingPollContext
            submitQuestionResponse(options[1]?.value || 'no');
        }
    };
    document.addEventListener('keydown', keyHandler);

    // Store keyHandler on the questionBox for cleanup
    questionBox._keyHandler = keyHandler;

    // [064] Loading/overlay hidden by transitionTask('awaiting_input') in showConfirmationDialog
    document.getElementById('resultPanel').classList.add('visible');

    // Update title to show waiting state
    document.getElementById('resultTitle').textContent = name + ' - ' + t('dialog.waiting_response');

    // Show prompt area for custom response input
    showPromptArea(true);
    const promptInput = document.getElementById('promptInput');
    promptInput.placeholder = t('dialog.custom_response_placeholder');
    promptInput.focus();
}

async function submitQuestionResponse(value) {
    if (!pendingPollContext) return;
    if (isSubmittingResponse) return;  // Prevent double submission

    isSubmittingResponse = true;  // Set guard immediately

    const { taskId, tile, name, isAgent } = pendingPollContext;

    // [068] Save context for error recovery (resetPendingDialogState clears it)
    const savedPollContext = { ...pendingPollContext };

    // Find inline question box and overlay
    const questionBox = document.getElementById('inlineQuestionBox');
    const overlay = document.querySelector('.confirm-overlay');

    // For question responses, always send confirmed=true (we have an answer)
    // The actual answer (yes/no/custom text) is in data.response
    // confirmed=false is only for explicit cancellation (X button on tile)
    const confirmed = true;

    // [061] Update dialog UI and reset state BEFORE fetch to prevent SSE race condition
    // When Round 2 is faster than POST response, SSE pending_input event arrives
    // while pendingDialogShown is still true -> event ignored -> Dialog 2 never shown
    if (questionBox && questionBox._keyHandler) {
        document.removeEventListener('keydown', questionBox._keyHandler);
    }
    if (questionBox) {
        const buttonsEl = questionBox.querySelector('.inline-question-buttons');
        if (buttonsEl) buttonsEl.style.display = 'none';
        const answerEl = document.createElement('div');
        answerEl.className = 'inline-question-answered';
        answerEl.innerHTML = `<span class="answer-checkmark">✓</span> <span class="answer-label">${t('dialog.answer')}</span> <strong>${escapeHtml(value)}</strong>`;
        questionBox.querySelector('.inline-question-content').appendChild(answerEl);
        // [069] Remove ID so showStreamingContent() guard no longer blocks rendering
        // The element stays in DOM (question + answer remain visible in chat)
        questionBox.removeAttribute('id');
    }
    if (overlay) {
        if (overlay._keyHandler) document.removeEventListener('keydown', overlay._keyHandler);
        overlay.remove();
    }
    resetPendingDialogState();

    // [068] Transition to thinking BEFORE fetch (consistent with submitConfirmation)
    // SSE done event might fire during await - overlay must already be visible
    ViewContext.transitionTask(taskId, 'thinking', {
        message: t('dialog.continuing') + '...'
    });

    // [068] Add timeout (consistent with submitConfirmation)
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        const res = await fetch(`${API}/task/${taskId}/respond`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed, data: { response: value } }),
            signal: controller.signal
        });
        clearTimeout(timeoutId);

        const data = await res.json();

        if (res.ok) {
            // [061] DOM cleanup already done above (before fetch)

            // Reset prompt placeholder
            const promptInput = document.getElementById('promptInput');
            promptInput.placeholder = t('dialog.response_placeholder');
            promptInput.value = '';

            // [068] transitionTask('thinking') already called BEFORE fetch (above)

            // Keep result panel visible while loading
            document.getElementById('resultPanel').classList.add('visible');

            // Update title to show processing
            document.getElementById('resultTitle').textContent = name + ' - ' + t('dialog.processing_response');

            // Note: We don't call addUserTurnToConversation() here because
            // the user's answer is shown inline below the question
            // The question and answer are stored as separate turns in the database

            // Remove old streamingResponse ID so new agent content gets a fresh div
            // This prevents overwriting the user's answer that's now part of the old div
            const oldStreamingDiv = document.getElementById('streamingResponse');
            if (oldStreamingDiv) {
                oldStreamingDiv.removeAttribute('id');
            }

            // Reconnect SSE if connection was lost during dialog
            // (onerror may have killed EventSource while dialog was shown)
            if (!activeEventSources[taskId]) {
                console.log('[SSE] Reconnecting after question response');
                streamTask(taskId, tile, name, isAgent);
            }

            // [063] Signal backend that SSE is ready for next round
            // Small delay to ensure EventSource.onopen has fired
            setTimeout(async () => {
                try {
                    await fetch(`${API}/task/${taskId}/round-ready`, { method: 'POST' });
                    console.log('[Handshake] Round-ready signaled for task', taskId);
                } catch (e) {
                    console.warn('[Handshake] Failed to signal round-ready:', e);
                }
            }, 200);
            pendingPollContext = null;
            isSubmittingResponse = false;  // Reset guard
            // [064] isAppendMode synced via _syncDerivedGlobals in transitionTask('thinking') above
        } else {
            // [068] Server error → transition to error (consistent with submitConfirmation)
            ViewContext.transitionTask(taskId, 'error');
            console.error('Server error:', data.error || 'Unknown error');
            alert(t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error')));
            isSubmittingResponse = false;  // Reset guard on error
        }
    } catch (err) {
        clearTimeout(timeoutId);
        console.error('Error submitting question response:', err);

        // [068] Rollback via state machine: thinking → awaiting_input (re-enables dialog for retry)
        ViewContext.transitionTask(taskId, 'awaiting_input');
        pendingPollContext = savedPollContext;

        // [061] Rollback UI on fetch error - buttons were already hidden
        if (questionBox) {
            const buttonsEl = questionBox.querySelector('.inline-question-buttons');
            if (buttonsEl) buttonsEl.style.display = '';
            const answerEl = questionBox.querySelector('.inline-question-answered');
            if (answerEl) answerEl.remove();
        }

        // [068] Handle timeout specifically (consistent with submitConfirmation)
        if (err.name === 'AbortError') {
            console.error('[Dialog] Response timeout after 30s');
            alert(t('task.timeout_error') || 'Request timed out. Please try again.');
        } else {
            alert(t('task.connection_error') + ' ' + err.message);
        }
        isSubmittingResponse = false;  // Reset guard on exception
    }
}

// =============================================================================
// User Turn Helper (Conversation History)
// =============================================================================

/**
 * Add a user turn to the conversation history
 * Used when user responds to QUESTION_NEEDED or CONFIRMATION_NEEDED
 */
function addUserTurnToConversation(text, isHtml = false) {
    const contentEl = document.getElementById('resultContent');
    if (!contentEl) return;

    // [064] Support pre-escaped HTML content (e.g. confirmed data table)
    const content = isHtml ? text : escapeHtml(text);
    const userHtml = `<div class="conversation-turn user-turn">
        <div class="turn-header"><span class="material-icons">person</span> ${t('dialog.you')}</div>
        <div class="turn-content">${content}</div>
    </div>`;
    contentEl.innerHTML += userHtml;
    contentEl.scrollTop = contentEl.scrollHeight;
}

// =============================================================================
// HTML Escape Helper
// =============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =============================================================================
// Generic Confirm Dialog
// =============================================================================

/**
 * Show a styled confirmation dialog (replaces native confirm()).
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message
 * @param {Object} options - Optional settings
 * @param {string} options.confirmText - Confirm button text (default: "Delete")
 * @param {string} options.cancelText - Cancel button text (default: "Cancel")
 * @param {string} options.type - Dialog type: "danger", "warning", "info" (default: "danger")
 * @returns {Promise<boolean>} - Resolves to true if confirmed, false if cancelled
 */
function showConfirm(title, message, options = {}) {
    // Cleanup any modifier tooltip (Ctrl/Shift indicator)
    if (typeof cleanupModifierTooltip === 'function') {
        cleanupModifierTooltip();
    }

    return new Promise((resolve) => {
        const confirmText = options.confirmText || t('dialog.delete');
        const cancelText = options.cancelText || t('dialog.cancel');
        const type = options.type || 'danger';

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'confirm-dialog-overlay';
        overlay.innerHTML = `
            <div class="confirm-dialog ${type}">
                <div class="confirm-dialog-header">
                    <span class="material-icons">${type === 'danger' ? 'warning' : type === 'warning' ? 'info' : 'help'}</span>
                    <span>${escapeHtml(title)}</span>
                </div>
                <div class="confirm-dialog-body">
                    ${escapeHtml(message)}
                </div>
                <div class="confirm-dialog-actions">
                    <button class="confirm-dialog-btn cancel">${escapeHtml(cancelText)}</button>
                    <button class="confirm-dialog-btn confirm ${type}">${escapeHtml(confirmText)}</button>
                </div>
            </div>
        `;

        // Handle clicks
        const cancelBtn = overlay.querySelector('.confirm-dialog-btn.cancel');
        const confirmBtn = overlay.querySelector('.confirm-dialog-btn.confirm');

        cancelBtn.onclick = () => {
            overlay.remove();
            resolve(false);
        };

        confirmBtn.onclick = () => {
            overlay.remove();
            resolve(true);
        };

        // Close on overlay click
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                overlay.remove();
                resolve(false);
            }
        };

        // Close on Escape
        const handleEscape = (e) => {
            if (e.key === 'Escape') {
                overlay.remove();
                resolve(false);
                document.removeEventListener('keydown', handleEscape);
            }
        };
        document.addEventListener('keydown', handleEscape);

        document.body.appendChild(overlay);
        confirmBtn.focus();
    });
}

// =============================================================================
// Browser Close Cleanup
// =============================================================================

// #17 - Clean up dialog state when browser/tab closes to prevent orphaned state
window.addEventListener('beforeunload', function() {
    resetPendingDialogState();
    isSubmittingResponse = false;
});
