/**
 * WebUI Agents Module
 * Agent/skill execution, input dialogs, file uploads, chat attachments.
 * Depends on: webui-core.js (state), webui-ui.js (UI helpers), webui-dialogs.js, webui-tasks.js
 */

// =============================================================================
// Tile Grid Refresh (for SSE agents_changed events)
// =============================================================================

/**
 * Refresh agent tiles without full page reload.
 * Fetches the main page and extracts only the tile-grid content.
 */
async function refreshAgentTiles() {
    try {
        console.log('[Agents] Refreshing tiles...');

        // Fetch the main page HTML (with cache-busting to get fresh prerequisites)
        const response = await fetch(API.replace('/api', '/'), {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache' }
        });
        if (!response.ok) {
            console.error('[Agents] Failed to fetch page for tile refresh');
            return;
        }

        const html = await response.text();

        // Parse HTML and extract tile-grid content
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const newTileGrid = doc.getElementById('tileGrid');

        if (!newTileGrid) {
            console.error('[Agents] Could not find tileGrid in fetched HTML');
            return;
        }

        // Replace current tile-grid content
        const currentTileGrid = document.getElementById('tileGrid');
        if (currentTileGrid) {
            currentTileGrid.innerHTML = newTileGrid.innerHTML;
            // Re-attach event handlers that were lost during innerHTML replacement
            if (typeof attachTileContextMenuHandlers === 'function') {
                attachTileContextMenuHandlers();
            }
            console.log('[Agents] Tiles refreshed successfully');
        }
    } catch (error) {
        console.error('[Agents] Failed to refresh tiles:', error);
    }
}

// =============================================================================
// Chat Attachments - File uploads in chat prompt
// =============================================================================

// Store for chat attachments (file paths)
let chatAttachments = [];

// Open file upload dialog for chat
async function openChatFileUpload() {
    // Check if pywebview is available (native file picker)
    if (typeof pywebview !== 'undefined' && pywebview.api && pywebview.api.select_files) {
        try {
            const result = await pywebview.api.select_files({
                multiple: true,
                accept: '.pdf,.png,.jpg,.jpeg,.gif,.bmp,.txt,.md,.csv,.json,.xml'
            });
            if (result && result.paths && result.paths.length > 0) {
                addChatAttachments(result.paths);
            }
        } catch (e) {
            console.error('[ChatAttach] pywebview error:', e);
            // Fallback to HTML file input
            openChatFileInputFallback();
        }
    } else {
        // Browser fallback: use HTML file input
        openChatFileInputFallback();
    }
}

// Browser fallback: HTML file input
function openChatFileInputFallback() {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.pdf,.png,.jpg,.jpeg,.gif,.bmp,.txt,.md,.csv,.json,.xml';
    input.style.display = 'none';

    input.onchange = async (e) => {
        const files = e.target.files;
        if (files.length > 0) {
            // Upload files to server
            const formData = new FormData();
            for (const file of files) {
                formData.append('files', file, file.name);
            }

            try {
                const attachBtn = document.getElementById('attachBtn');
                attachBtn.classList.add('uploading');

                const res = await fetch(API + '/upload/file', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                attachBtn.classList.remove('uploading');

                if (data.paths && data.paths.length > 0) {
                    addChatAttachments(data.paths);
                }
            } catch (err) {
                console.error('[ChatAttach] Upload error:', err);
                const attachBtn = document.getElementById('attachBtn');
                attachBtn.classList.remove('uploading');
            }
        }
        input.remove();
    };

    document.body.appendChild(input);
    input.click();
}

// Add files to chat attachments
function addChatAttachments(paths) {
    chatAttachments = [...chatAttachments, ...paths];
    updateChatAttachmentDisplay();
}

// Remove a chat attachment
function removeChatAttachment(index) {
    chatAttachments.splice(index, 1);
    updateChatAttachmentDisplay();
}

// Clear all chat attachments
function clearChatAttachments() {
    chatAttachments = [];
    updateChatAttachmentDisplay();
}

// Update the visual display of attachments
function updateChatAttachmentDisplay() {
    const container = document.getElementById('chatAttachments');
    const list = document.getElementById('chatAttachmentList');

    if (chatAttachments.length === 0) {
        container.classList.remove('has-files');
        list.innerHTML = '';
        return;
    }

    container.classList.add('has-files');

    list.innerHTML = chatAttachments.map((path, idx) => {
        const filename = path.split(/[\\/]/).pop();
        const ext = filename.split('.').pop().toLowerCase();

        // Icon based on file type
        let icon = 'description';
        if (['pdf'].includes(ext)) icon = 'picture_as_pdf';
        else if (['png', 'jpg', 'jpeg', 'gif', 'bmp'].includes(ext)) icon = 'image';
        else if (['txt', 'md'].includes(ext)) icon = 'article';
        else if (['csv', 'json', 'xml'].includes(ext)) icon = 'code';

        return `<div class="chat-attachment-item">
            <span class="material-icons">${icon}</span>
            <span class="chat-attachment-name" title="${escapeHtml(path)}">${escapeHtml(filename)}</span>
            <button class="chat-attachment-remove" onclick="removeChatAttachment(${idx})" title="${t('agent.remove')}">
                <span class="material-icons">close</span>
            </button>
        </div>`;
    }).join('');
}

// Get formatted file list for prompt display
function getAttachmentDisplayText() {
    if (chatAttachments.length === 0) return '';

    const fileNames = chatAttachments.map(p => p.split(/[\\\/]/).pop());
    return '\n\n**' + t('agent.attached_files') + '**\n' + fileNames.map(f => '- ' + f).join('\n');
}

// =============================================================================
// Input Dialog - Collect inputs before agent starts
// =============================================================================

// Store for collected input values
let inputDialogData = {};
let inputDialogTile = null;
let inputDialogAgentName = null;
let inputDialogOverrideBackend = null;  // Store backend override from backend selection dialog
let inputDialogDisableAnon = false;  // [044] Store disable_anon override from context menu

// Fetch input definitions for an agent
async function getAgentInputs(name) {
    const url = API + '/agent/' + name + '/inputs';
    serverDebug('[Agent] getAgentInputs: fetching ' + url);
    try {
        const res = await fetch(url);
        serverDebug('[Agent] getAgentInputs: response status ' + res.status);
        const data = await res.json();
        serverDebug('[Agent] getAgentInputs: got ' + (data.inputs ? data.inputs.length : 0) + ' inputs');
        return data.inputs || [];
    } catch (e) {
        serverError('[Agent] getAgentInputs: ' + e.message);
        return [];
    }
}

// Show input dialog for agent
function showInputDialog(name, inputs, tile) {
    // Remove any existing overlay and reset state
    removeExistingOverlay('.confirm-overlay');
    inputDialogData = {};
    inputDialogTile = tile;
    inputDialogAgentName = name;

    // Build input fields HTML
    const fieldsHtml = inputs.map(input => buildInputFieldHtml(input)).join('');

    // Create overlay using utility
    const overlay = createModalOverlay({ id: 'inputDialogOverlay', closeOnClick: false });
    overlay.innerHTML = `
        <div class="input-dialog">
            <div class="input-header">
                <span class="material-icons">upload_file</span>
                <h3>${escapeHtml(name)}</h3>
                <button class="input-close" onclick="closeInputDialog()">
                    <span class="material-icons">close</span>
                </button>
            </div>
            <div class="input-fields">
                ${fieldsHtml}
            </div>
            <div class="input-buttons">
                <button class="btn-cancel" onclick="closeInputDialog()">${t('dialog.cancel')}</button>
                <button class="btn-confirm" onclick="submitInputDialog()">
                    <span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 4px;">play_arrow</span>
                    ${t('agent.start')}
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Setup file dropzones
    setupFileDropzones();

    // Setup voice input buttons for textareas (if voice available)
    if (typeof initVoiceButtonsInContainer === 'function') {
        initVoiceButtonsInContainer(overlay);
    }

    // Setup text input error clearing
    overlay.querySelectorAll('.input-field[data-type="text"] input, .input-field[data-type="text"] textarea').forEach(input => {
        input.addEventListener('input', () => {
            const fieldDiv = input.closest('.input-field');
            if (fieldDiv) fieldDiv.classList.remove('error', 'shake');
        });
    });

    // Focus first input
    const firstInput = overlay.querySelector('input, textarea');
    if (firstInput) firstInput.focus();

    // Keyboard handler - Shift+Enter to submit, Escape to cancel
    const keyHandler = function(e) {
        if (e.key === 'Escape') {
            // If recording, cancel recording instead of closing dialog
            if (typeof isRecording !== 'undefined' && isRecording) {
                e.preventDefault();
                if (typeof cancelRecording === 'function') cancelRecording();
                return;
            }
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            closeInputDialog();
        } else if (e.key === 'Enter' && e.shiftKey) {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            submitInputDialog();
        }
    };
    document.addEventListener('keydown', keyHandler);
    overlay._keyHandler = keyHandler;
}

// Build HTML for a single input field
function buildInputFieldHtml(input) {
    const required = input.required ? '<span class="required">*</span>' : '';
    const name = input.id || input.name;  // Support both "id" and "name" fields

    if (input.type === 'file') {
        const multiple = input.multiple ? t('agent.multiple_files') : t('agent.single_file');
        const folders = input.folders ? t('agent.or_folders') : '';
        const accept = input.accept ? ` (${input.accept})` : '';

        return `
            <div class="input-field" data-field="${escapeHtml(name)}" data-type="file" data-multiple="${input.multiple || false}" data-folders="${input.folders || false}" data-accept="${escapeHtml(input.accept || '')}">
                <label>${escapeHtml(input.label || name)}${required}</label>
                <div class="file-dropzone" data-field="${escapeHtml(name)}">
                    <span class="material-icons">folder_open</span>
                    <div class="file-dropzone-text">${t('agent.click_to_select')}</div>
                    <div class="file-dropzone-hint">${multiple}${folders}${accept}</div>
                </div>
                <div class="file-list" id="fileList_${escapeHtml(name)}"></div>
            </div>
        `;
    } else {
        // Text input
        const placeholder = input.placeholder ? `placeholder="${escapeHtml(input.placeholder)}"` : '';
        const defaultVal = input.default || '';

        if (input.multiline) {
            const rows = input.rows || 8;  // Default 8 rows for multiline
            return `
                <div class="input-field" data-field="${escapeHtml(name)}" data-type="text">
                    <label>${escapeHtml(input.label || name)}${required}</label>
                    <textarea name="${escapeHtml(name)}" rows="${rows}" ${placeholder}>${escapeHtml(defaultVal)}</textarea>
                </div>
            `;
        } else {
            return `
                <div class="input-field" data-field="${escapeHtml(name)}" data-type="text">
                    <label>${escapeHtml(input.label || name)}${required}</label>
                    <input type="text" name="${escapeHtml(name)}" value="${escapeHtml(defaultVal)}" ${placeholder}>
                </div>
            `;
        }
    }
}

// Setup drag & drop and click handlers for file dropzones
function setupFileDropzones() {
    const dropzones = document.querySelectorAll('.file-dropzone');

    dropzones.forEach(dropzone => {
        const fieldName = dropzone.dataset.field;
        const fieldDiv = dropzone.closest('.input-field');
        const multiple = fieldDiv.dataset.multiple === 'true';
        const folders = fieldDiv.dataset.folders === 'true';
        const accept = fieldDiv.dataset.accept;

        // Initialize storage
        if (!inputDialogData[fieldName]) {
            inputDialogData[fieldName] = [];
        }

        // Drag events
        dropzone.addEventListener('dragenter', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');

            // Get dropped files/folders
            const paths = [];

            if (e.dataTransfer.files) {
                for (const file of e.dataTransfer.files) {
                    // pywebview exposes file.path for local files
                    const path = file.path || file.name;
                    if (path) paths.push(path);
                }
            }

            // Check if we got full paths (contain path separator) or just filenames
            const hasFullPaths = paths.some(p => p.includes('/') || p.includes('\\'));

            if (paths.length > 0 && !hasFullPaths) {
                // Drag & drop only gave us filenames - show error
                alert(t('agent.drag_drop_error'));
                return;
            }

            handleFilesAdded(fieldName, paths, multiple);
        });

        // Click to open file picker (uses pywebview API if available)
        dropzone.addEventListener('click', async () => {
            try {
                let paths = [];

                serverDebug('[FilePicker] Click - pywebview available: ' + !!(window.pywebview && window.pywebview.api));

                // Use pywebview file dialog if available
                if (window.pywebview && window.pywebview.api) {
                    if (folders) {
                        // Folder picker
                        serverDebug('[FilePicker] Calling select_folder()');
                        const result = await window.pywebview.api.select_folder();
                        serverDebug('[FilePicker] select_folder result: ' + (result ? 'success' : 'cancelled'));
                        if (result) paths = [result];
                    } else {
                        // File picker
                        const fileTypes = accept ? accept.split(',').map(t => t.trim()) : ['*'];
                        serverDebug('[FilePicker] Calling select_files(' + multiple + ', ' + fileTypes.join(',') + ')');
                        const result = await window.pywebview.api.select_files(multiple, fileTypes);
                        serverDebug('[FilePicker] select_files result: ' + (result ? (Array.isArray(result) ? result.length + ' files' : '1 file') : 'cancelled'));
                        if (result) paths = Array.isArray(result) ? result : [result];
                    }
                    serverDebug('[FilePicker] Paths collected: ' + paths.length);
                } else {
                    // Browser fallback: Upload files to server temp folder
                    // Note: Folder selection not possible in browser, but file selection always works
                    // (folders flag just means "also allow folders" in pywebview, not "only folders")

                    // Create hidden file input for browser file picker
                    const input = document.createElement('input');
                    input.type = 'file';
                    input.multiple = multiple;
                    if (accept) input.accept = accept;

                    input.onchange = async () => {
                        if (!input.files || input.files.length === 0) return;

                        // Show upload indicator on dropzone
                        dropzone.classList.add('uploading');
                        const textEl = dropzone.querySelector('.file-dropzone-text');
                        const originalText = textEl.textContent;
                        textEl.textContent = t('agent.uploading');

                        try {
                            // Upload files to server
                            const formData = new FormData();
                            for (const file of input.files) {
                                formData.append('files', file);
                            }

                            serverDebug('[Upload] Uploading ' + input.files.length + ' files...');
                            const response = await fetch(API + '/upload/file', {
                                method: 'POST',
                                body: formData
                            });

                            const result = await response.json();
                            serverDebug('[Upload] Result: ' + (result.paths ? result.paths.length + ' files uploaded' : 'error'));

                            if (result.paths && result.paths.length > 0) {
                                handleFilesAdded(fieldName, result.paths, multiple);
                            } else if (result.error) {
                                alert(t('agent.upload_failed') + ' ' + result.error);
                            }
                        } catch (e) {
                            serverError('[Upload] ' + e.message);
                            alert(t('agent.upload_failed') + ' ' + e.message);
                        } finally {
                            // Reset dropzone appearance
                            dropzone.classList.remove('uploading');
                            textEl.textContent = originalText;
                        }
                    };

                    input.click();
                    return; // handleFilesAdded is called in onchange callback
                }

                handleFilesAdded(fieldName, paths, multiple);
            } catch (e) {
                console.error('File picker error:', e);
            }
        });
    });
}

// Handle files being added to a field
function handleFilesAdded(fieldName, paths, multiple) {
    if (!paths || paths.length === 0) return;

    // Clear error state when files are added
    const fieldDiv = document.querySelector(`.input-field[data-field="${fieldName}"]`);
    if (fieldDiv) fieldDiv.classList.remove('error', 'shake');

    if (multiple) {
        // Add to existing list
        inputDialogData[fieldName] = [...(inputDialogData[fieldName] || []), ...paths];
    } else {
        // Replace with single file
        inputDialogData[fieldName] = [paths[0]];
    }

    updateFileList(fieldName);
}

// Update the visual file list
function updateFileList(fieldName) {
    const listEl = document.getElementById('fileList_' + fieldName);
    if (!listEl) return;

    const files = inputDialogData[fieldName] || [];

    if (files.length === 0) {
        listEl.innerHTML = '';
        return;
    }

    listEl.innerHTML = files.map((path, idx) => {
        const name = path.split(/[/\\]/).pop();
        const isFolder = !name.includes('.');
        const icon = isFolder ? 'folder' : 'description';

        return `
            <div class="file-item">
                <span class="material-icons">${icon}</span>
                <span class="file-item-name" title="${escapeHtml(path)}">${escapeHtml(name)}</span>
                <button class="file-item-remove" onclick="removeFile('${escapeHtml(fieldName)}', ${idx})">
                    <span class="material-icons">close</span>
                </button>
            </div>
        `;
    }).join('');
}

// Remove a file from the list
function removeFile(fieldName, idx) {
    if (inputDialogData[fieldName]) {
        inputDialogData[fieldName].splice(idx, 1);
        updateFileList(fieldName);
    }
}

// Close the input dialog
function closeInputDialog() {
    const overlay = document.getElementById('inputDialogOverlay');
    if (overlay) {
        if (overlay._keyHandler) {
            document.removeEventListener('keydown', overlay._keyHandler);
        }
        overlay.remove();
    }

    // Unpin tile if it was pinned
    if (inputDialogTile) {
        unpinTile(inputDialogTile);
    }

    inputDialogData = {};
    inputDialogTile = null;
    inputDialogAgentName = null;
    inputDialogOverrideBackend = null;
    inputDialogDisableAnon = false;  // [044]
}

// =============================================================================
// Backend Selection Dialog - When configured backend is not available
// =============================================================================

/**
 * Show dialog to select an alternative backend when the configured one is not available.
 *
 * @param {string} agentName - Name of the agent
 * @param {string} configuredBackend - The backend that was configured but not available
 * @param {Array} availableBackends - List of {name, display, model} for available backends
 * @param {string} recommended - Name of the recommended backend (usually first available)
 * @param {Function} onSelect - Callback when user selects a backend (receives backend name)
 * @param {Function} onCancel - Callback when user cancels
 */
function showBackendSelectionDialog(agentName, configuredBackend, availableBackends, recommended, onSelect, onCancel) {
    // Remove any existing overlay
    removeExistingOverlay('#backendSelectionOverlay');

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.id = 'backendSelectionOverlay';

    // Build backend options HTML
    const backendOptions = availableBackends.map((b, i) => {
        const icon = getBackendIcon(b.name);
        const isRecommended = b.name === recommended;
        return `
            <label class="backend-option ${isRecommended ? 'recommended' : ''}">
                <input type="radio" name="selectedBackend" value="${escapeHtml(b.name)}" ${i === 0 ? 'checked' : ''}>
                <span class="material-icons backend-icon">${icon}</span>
                <span class="backend-info">
                    <span class="backend-name">${escapeHtml(b.display || b.name)}</span>
                    ${b.model ? `<span class="backend-model">${escapeHtml(b.model)}</span>` : ''}
                </span>
                ${isRecommended ? `<span class="recommended-badge">${t('backend.recommended')}</span>` : ''}
            </label>
        `;
    }).join('');

    overlay.innerHTML = `
        <div class="input-dialog backend-dialog">
            <div class="input-header warning-header">
                <span class="material-icons">warning</span>
                <h3>${t('backend.not_available')}</h3>
                <button class="input-close" onclick="closeBackendSelectionDialog(false)">
                    <span class="material-icons">close</span>
                </button>
            </div>
            <div class="backend-message">
                ${t('backend.configured_not_available', {backend: escapeHtml(configuredBackend), agent: escapeHtml(agentName)})}
            </div>
            <div class="backend-options">
                ${backendOptions}
            </div>
            <div class="input-buttons">
                <button class="btn-cancel" onclick="closeBackendSelectionDialog(false)">${t('dialog.cancel')}</button>
                <button class="btn-confirm" onclick="closeBackendSelectionDialog(true)">
                    <span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 4px;">play_arrow</span>
                    ${t('backend.continue')}
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Store callbacks for close handler
    overlay._onSelect = onSelect;
    overlay._onCancel = onCancel;

    // Keyboard handler - Enter to confirm, Escape to cancel
    const keyHandler = function(e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            closeBackendSelectionDialog(false);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            closeBackendSelectionDialog(true);
        }
    };
    document.addEventListener('keydown', keyHandler);
    overlay._keyHandler = keyHandler;

    serverLog('[BackendDialog] Showing for agent: ' + agentName + ', configured: ' + configuredBackend);
}

/**
 * Close the backend selection dialog.
 *
 * @param {boolean} proceed - True if user wants to proceed with selected backend
 */
function closeBackendSelectionDialog(proceed) {
    const overlay = document.getElementById('backendSelectionOverlay');
    if (!overlay) return;

    // Remove keyboard handler
    if (overlay._keyHandler) {
        document.removeEventListener('keydown', overlay._keyHandler);
    }

    if (proceed && overlay._onSelect) {
        const selected = document.querySelector('#backendSelectionOverlay input[name="selectedBackend"]:checked');
        if (selected) {
            overlay._onSelect(selected.value);
        }
    } else if (overlay._onCancel) {
        overlay._onCancel();
    }

    overlay.remove();
}

// Submit the input dialog and start agent
async function submitInputDialog() {
    const overlay = document.getElementById('inputDialogOverlay');
    if (!overlay) return;

    // Collect text input values
    overlay.querySelectorAll('.input-field').forEach(field => {
        const fieldName = field.dataset.field;
        const fieldType = field.dataset.type;

        if (fieldType === 'text') {
            const input = field.querySelector('input, textarea');
            if (input) {
                inputDialogData[fieldName] = input.value;
            }
        }
        // File fields are already in inputDialogData
    });

    // Clear previous errors
    overlay.querySelectorAll('.input-field.error').forEach(f => {
        f.classList.remove('error', 'shake');
    });

    // Validate required fields
    const fields = overlay.querySelectorAll('.input-field');
    let hasError = false;
    let firstErrorField = null;

    for (const field of fields) {
        const fieldName = field.dataset.field;
        const label = field.querySelector('label');
        const isRequired = label && label.querySelector('.required');

        if (isRequired) {
            const value = inputDialogData[fieldName];
            const isEmpty = !value || (Array.isArray(value) && value.length === 0);

            if (isEmpty) {
                field.classList.add('error', 'shake');
                hasError = true;
                if (!firstErrorField) firstErrorField = field;
                // Remove shake after animation
                setTimeout(() => field.classList.remove('shake'), 400);
            }
        }
    }

    if (hasError) {
        // Focus first error field
        if (firstErrorField) {
            const input = firstErrorField.querySelector('input, textarea');
            if (input) input.focus();
        }
        return;
    }

    // Remove keyboard handler
    if (overlay._keyHandler) {
        document.removeEventListener('keydown', overlay._keyHandler);
    }

    // Close dialog
    overlay.remove();

    // Execute agent with inputs
    const name = inputDialogAgentName;
    const tile = inputDialogTile;
    const inputs = { ...inputDialogData };
    const overrideBackend = inputDialogOverrideBackend;
    const disableAnon = inputDialogDisableAnon;  // [044]

    // Reset dialog state
    inputDialogData = {};
    inputDialogTile = null;
    inputDialogAgentName = null;
    inputDialogOverrideBackend = null;
    inputDialogDisableAnon = false;  // [044]

    // Start agent with inputs
    await executeAgentWithInputs(name, tile, inputs, overrideBackend, disableAnon);
}

// =============================================================================
// Agent Execution
// =============================================================================

// Execute agent with collected inputs
async function executeAgentWithInputs(name, tile, inputs, overrideBackend = null, disableAnon = false) {
    serverLog('[Agent] Starting: ' + name + ' (with inputs)' + (overrideBackend ? ' backend: ' + overrideBackend : '') + (disableAnon ? ' [NO ANON]' : ''));
    serverDebug('[Agent] Inputs: ' + Object.keys(inputs).join(', '));

    // Reset pending dialog state for new task
    resetPendingDialogState();

    // Clear any previous cancel request
    cancelRequestedForTask = null;

    // [067] D1: isAppendMode removed - default false in _createTaskState
    // Build user prompt including input values
    let promptParts = [`${t('agent.start_prefix')} ${name}`];
    for (const [key, value] of Object.entries(inputs)) {
        if (Array.isArray(value) && value.length > 0) {
            // File inputs - show filenames
            const filenames = value.map(p => p.split(/[/\\]/).pop()).join(', ');
            promptParts.push(`${key}: ${filenames}`);
        } else if (typeof value === 'string' && value.trim()) {
            // Text inputs - show value (truncate if very long)
            const displayVal = value.length > 500 ? value.substring(0, 500) + '...' : value;
            promptParts.push(`${key}: ${displayVal}`);
        }
    }
    currentUserPrompt = promptParts.join('\n');
    userPromptDisplayed = false;

    // Quick Access mode: Add running status to tile
    if (isQuickAccessMode && tile) {
        tile.classList.add('qa-running');
        addQuickAccessChatButton(tile);
    }

    setLoading(true, name, t('agent.starting'));

    // [044] Reset anon badge for disableAnon
    if (disableAnon) {
        resetAnonBadge(true);  // Show OFF state
    }

    try {
        serverDebug('[Agent] Sending POST to /agent/' + name);
        // Build request body with optional backend override and disable_anon
        const requestBody = {
            inputs: inputs,
            initial_prompt: currentUserPrompt  // Store for History display
        };
        if (overrideBackend) {
            requestBody.backend = overrideBackend;
        }
        if (disableAnon) {
            requestBody.disable_anon = true;
        }
        const res = await fetch(API + '/agent/' + name, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        serverDebug('[Agent] Response status: ' + res.status);
        const data = await res.json();

        if (data.task_id) {
            // #6 - Use pendingTaskId instead of currentTaskId to prevent race condition
            // currentTaskId will be set when task_start SSE event is received
            pendingTaskId = data.task_id;
            currentTaskTile = tile;
            // Set chat backend for follow-up messages (stay on same backend)
            currentChatBackend = data.ai_backend || null;
            currentChatName = name;

            // [030] Register task in ViewContext and switch view
            const taskState = ViewContext.registerTask(
                data.task_id, null, name,
                data.ai_backend || null, data.model || null, 'webui'
            );
            taskState.chat.backend = data.ai_backend || null;
            taskState.chat.agentName = name;
            taskState.pendingTaskId = data.task_id;
            taskState.taskTile = tile;
            taskState.userPrompt = currentUserPrompt;
            taskState.overlay.startTime = Date.now();
            taskState.overlay.mode = 'loading';
            ViewContext.switchView(data.task_id, null);

            // Start context polling if context tab is visible
            maybeStartContextPolling();
            const aiInfo = data.model ? `${data.ai_backend} • ${data.model}` : data.ai_backend || 'Agent';
            loadingStartTime = Date.now();
            const statusEl1 = document.getElementById('aiProcessingStatus');
            if (statusEl1) statusEl1.textContent = `${name} • ${aiInfo}`;
            // Update stats bar immediately with backend/model info
            updateStatsFromTask(data);
            startTaskMonitoring(data.task_id, tile, name, true);
        } else {
            showTileResult(tile, true);
            setLoading(false);
        }
    } catch (e) {
        console.error('[Agent] Error in runAgentWithInputs:', e);
        showTileResult(tile, false);
        setLoading(false);
    }
}

// Show prerequisites warning dialog
async function showPrerequisiteWarning(agentName) {
    serverLog('[Prerequisites] Showing warning for: ' + agentName);

    try {
        // Fetch prerequisites info and license status in parallel
        const [prereqResponse, licenseResponse] = await Promise.all([
            fetch(`/agent/${agentName}/prerequisites`),
            fetch(API + '/license/status').catch(() => null)
        ]);

        if (!prereqResponse.ok) {
            console.error('Failed to fetch prerequisites:', prereqResponse.status);
            return;
        }
        const data = await prereqResponse.json();

        // Parse license data
        let isLicensed = false;
        let licenseData = null;
        if (licenseResponse && licenseResponse.ok) {
            try {
                licenseData = await licenseResponse.json();
                isLicensed = licenseData.licensed === true;
            } catch (e) {
                console.warn('[Prerequisites] License parse failed:', e);
            }
        }

        if (data.ready) {
            // Prerequisites are now met, run agent normally
            const tile = document.getElementById(`tile-${agentName}`);
            runAgent(tile, { shiftKey: false, ctrlKey: false }, agentName);
            return;
        }

        // Build dialog content with cards
        let contentHtml = '';

        // Show license warning first if not licensed
        if (!isLicensed) {
            contentHtml += `
                <div class="prereq-card license-warning">
                    <div class="prereq-card-header">
                        <span class="material-icons">vpn_key</span>
                        <strong>${t('prereq.license_title')}</strong>
                    </div>
                    <div class="prereq-card-requirement">${t('prereq.no_license')}</div>
                    <ol class="prereq-card-steps">
                        <li><a href="/setup" onclick="event.preventDefault(); this.closest('.confirm-overlay').remove(); window.location.href='/setup';">${t('prereq.open_setup')}</a></li>
                        <li>${t('prereq.enter_license')}</li>
                    </ol>
                </div>`;
        }

        // Show missing backend - point to Setup Wizard
        if (data.missing_backend) {
            contentHtml += `
                <div class="prereq-card">
                    <div class="prereq-card-header">
                        <span class="material-icons">smart_toy</span>
                        <strong>AI Backend</strong>
                    </div>
                    <div class="prereq-card-requirement">${t('prereq.backend_not_configured', {backend: data.missing_backend})}</div>
                    <ol class="prereq-card-steps">
                        <li><a href="/setup" onclick="event.preventDefault(); this.closest('.confirm-overlay').remove(); window.location.href='/setup';">${t('prereq.open_setup')}</a></li>
                        <li>${t('prereq.configure_backend')}</li>
                    </ol>
                </div>`;
        }

        // Show missing MCPs
        for (const mcp of data.missing_mcps) {
            const hint = data.hints[mcp] || {};
            const name = hint.name || mcp;
            const requirement = hint.requirement || t('prereq.config_missing');
            const steps = hint.setup_steps || [];
            const icon = getPrereqIcon(mcp);

            contentHtml += `
                <div class="prereq-card">
                    <div class="prereq-card-header">
                        <span class="material-icons">${icon}</span>
                        <strong>${name}</strong>
                    </div>
                    <div class="prereq-card-requirement">${requirement}</div>`;

            if (steps.length > 0) {
                contentHtml += `<ol class="prereq-card-steps">`;
                for (const step of steps) {
                    contentHtml += `<li>${step}</li>`;
                }
                contentHtml += `</ol>`;
            }

            if (hint.alternative) {
                contentHtml += `<p class="prereq-card-alternative">Alternative: ${hint.alternative}</p>`;
            }

            contentHtml += `</div>`;
        }

        // Remove any existing overlay
        removeExistingOverlay('.confirm-overlay');

        const overlay = createModalOverlay({
            id: 'prereqWarningOverlay',
            closeOnClick: true
        });

        // Setup Wizard button (primary action)
        const setupWizardBtn = `<button class="btn-confirm" onclick="this.closest('.confirm-overlay').remove(); window.location.href='/setup';">
                <span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 4px;">settings</span>
                Setup Wizard
           </button>`;

        // "Force start" only available with license (secondary/muted style)
        const forceStartBtn = isLicensed
            ? `<button class="btn-secondary" style="opacity: 0.7;" onclick="runAgentForce('${agentName}'); this.closest('.confirm-overlay').remove();">
                    ${t('prereq.force_start')}
               </button>`
            : '';

        overlay.innerHTML = `
            <div class="confirm-dialog prereq-dialog" style="max-width: 480px;">
                <div class="confirm-header">
                    <span class="material-icons" style="color: var(--warning-color); font-size: 28px;">warning</span>
                    <h3>${t('prereq.setup_required')}</h3>
                </div>
                <div class="confirm-content" style="max-height: 400px; overflow-y: auto; padding: 0 4px;">
                    <p class="prereq-intro">
                        ${t('prereq.services_not_configured')}
                    </p>
                    ${contentHtml}
                </div>
                <div class="confirm-buttons">
                    <button class="btn-cancel" onclick="this.closest('.confirm-overlay').remove()">
                        ${t('prereq.close')}
                    </button>
                    ${setupWizardBtn}
                    ${forceStartBtn}
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

    } catch (error) {
        console.error('Error showing prerequisite warning:', error);
    }
}

// Get icon for prerequisite MCP
function getPrereqIcon(mcp) {
    const icons = {
        'outlook': 'mail',
        'msgraph': 'cloud',
        'gmail': 'mail',
        'billomat': 'receipt_long',
        'lexware': 'receipt_long',
        'userecho': 'support_agent',
        'sepa': 'account_balance',
        'ecodms': 'folder',
        'paperless': 'description',
        'filesystem': 'folder_open',
        'excel': 'table_chart',
        'pdf': 'picture_as_pdf',
        'clipboard': 'content_paste',
        'datastore': 'storage',
        'browser': 'language',
        'telegram': 'telegram',
        'linkedin': 'work',
        'instagram': 'photo_camera'
    };
    return icons[mcp] || 'extension';
}

// Force run agent (skip prerequisites check)
function runAgentForce(agentName) {
    serverLog('[Agent] Force running agent: ' + agentName);
    const tile = document.getElementById(`tile-${agentName}`);
    const fakeEvent = { shiftKey: false, ctrlKey: false, metaKey: false };
    runAgent(tile, fakeEvent, agentName);
}

// Helper to clear tile loading state
function clearTileLoading(tile) {
    if (tile) {
        tile.classList.remove('tile-loading');
    }
}

// Run agent (main entry point)
async function runAgent(tile, e, name) {
    serverDebug('[Agent] runAgent called for: ' + name);

    // Check if backend is ready (prevents clicks during startup)
    if (!backendReady) {
        serverLog('[Agent] Backend not ready, ignoring click');
        showToast(t('startup.please_wait') || 'Please wait...', 2000);
        return;
    }

    // Immediate visual feedback - show tile is loading (fixes "no reaction on click" issue)
    if (tile) {
        tile.classList.add('tile-loading');
    }

    // License check before running agent
    const licenseCheck = await checkAgentLicense(name);
    if (!licenseCheck.allowed) {
        clearTileLoading(tile);
        showLicenseRequiredDialog(licenseCheck.reason, licenseCheck.message);
        return;
    }

    // Check if using fallback backend (configured backend not available, using different one)
    const fallbackBackend = tile?.getAttribute('data-fallback-backend');
    if (fallbackBackend) {
        serverLog('[Agent] Using fallback backend: ' + fallbackBackend);
        showNotification(t('prereq.backend_fallback', {fallback: fallbackBackend}), 'warning', 4000);
    }

    const shiftPressed = e.shiftKey;  // Detect Shift key for additional context
    const ctrlPressed = e.ctrlKey || e.metaKey;  // Detect Ctrl/Cmd key for edit mode

    // Ctrl+Shift+Click: Safe preview mode (dry-run / backend comparison)
    if (ctrlPressed && shiftPressed) {
        clearTileLoading(tile);
        serverLog('[Preview] Starting for: ' + name);
        await startSafePreview(name, tile);
        return;
    }

    // Ctrl+Click: Open edit agent with this agent name pre-filled for editing
    // EDIT_AGENT is configured in agents.json (default: 'create_agent')
    const editAgentName = (typeof EDIT_AGENT !== 'undefined') ? EDIT_AGENT : 'create_agent';
    if (ctrlPressed && name !== editAgentName) {
        clearTileLoading(tile);
        serverLog('[Edit] Opening editor for: ' + name);

        // Find the edit agent tile to pin (not the clicked agent's tile)
        const editAgentTile = document.querySelector(`.tile.agent[onclick*="${editAgentName}"]`);
        const tileToPin = editAgentTile || tile;  // Fallback to clicked tile if not found

        // Pre-fill the agent_name input and open the edit agent dialog
        const editInputs = [
            {
                name: 'agent_name',
                type: 'text',
                label: t('edit.agent_name'),
                required: false,
                default: name
            },
            {
                name: 'description',
                type: 'text',
                label: t('edit.what_to_change'),
                required: true,
                multiline: true,
                rows: 10,
                placeholder: t('edit.change_placeholder')
            }
        ];
        pinTile(tileToPin);
        showInputDialog(editAgentName, editInputs, tileToPin);
        return;
    }

    // Check if agent's configured backend is available
    serverDebug('[Agent] Checking backend for: ' + name);
    try {
        const backendCheck = await fetch(API + '/agent/' + name + '/check-backend').then(r => r.json());

        if (!backendCheck.available) {
            serverLog('[Agent] Backend "' + backendCheck.configured_backend + '" not available for: ' + name);

            if (!backendCheck.available_backends || backendCheck.available_backends.length === 0) {
                clearTileLoading(tile);
                showNotification(t('backend.none_available'), 'error');
                return;
            }

            // Show backend selection dialog (loading cleared when dialog shown)
            clearTileLoading(tile);
            showBackendSelectionDialog(
                name,
                backendCheck.configured_backend,
                backendCheck.available_backends,
                backendCheck.recommended,
                (selectedBackend) => {
                    // User selected a backend - continue with that backend
                    serverLog('[Agent] User selected backend: ' + selectedBackend);
                    proceedWithAgent(tile, e, name, selectedBackend);
                },
                () => {
                    // User cancelled
                    serverLog('[Agent] Backend selection cancelled');
                }
            );
            return;
        }
    } catch (err) {
        serverError('[Agent] Backend check failed: ' + err);
        // Continue anyway - let the backend handle it
    }

    // Continue with normal flow (backend available or check failed)
    // Loading state cleared in proceedWithAgent when tile is pinned
    await proceedWithAgent(tile, e, name, null);
}

/**
 * Continue with agent execution after backend check.
 * This is the main execution flow extracted from runAgent().
 *
 * @param {HTMLElement} tile - The tile element
 * @param {Event} e - The click event (for modifier keys)
 * @param {string} name - Agent name
 * @param {string|null} overrideBackend - Backend to use (if user selected an alternative)
 * @param {boolean} disableAnon - [044] If true, skip anonymization (Expert Mode override)
 */
async function proceedWithAgent(tile, e, name, overrideBackend, disableAnon = false) {
    const shiftPressed = e.shiftKey;

    // Clear loading state from runAgent (pinTile will handle visual state from here)
    clearTileLoading(tile);

    // Check if agent has inputs defined
    serverDebug('[Agent] Fetching inputs for: ' + name);
    const inputs = await getAgentInputs(name);
    serverDebug('[Agent] Got ' + (inputs ? inputs.length : 0) + ' inputs, shiftPressed: ' + shiftPressed);

    // If Shift pressed, inject context input field (Pre-Prompt)
    if (shiftPressed) {
        // Quick Access mode: Open separate preprompt window
        if (isQuickAccessMode) {
            serverLog('[Agent] Shift+Click in Quick Access: Opening preprompt window for ' + name);
            try {
                await fetch(`${API}/api/preprompt/open?agent=${encodeURIComponent(name)}`, {
                    method: 'POST'
                });
            } catch (e) {
                serverError('[Agent] Failed to open preprompt window: ' + e);
                showToast(t('agent.preprompt_failed') || 'Failed to open Pre-Prompt window');
            }
            return;
        }

        // Normal mode: Show input dialog with context field
        const contextInput = {
            name: '_context',
            type: 'text',
            label: t('agent.additional_context'),
            placeholder: t('agent.context_placeholder'),
            multiline: true,
            rows: 6,
            required: false
        };

        // Prepend context input to existing inputs (or create new array)
        const allInputs = [contextInput, ...(inputs || [])];

        serverLog('[Agent] Shift+Click: Context dialog for ' + name);
        pinTile(tile);
        inputDialogOverrideBackend = overrideBackend;  // Store for later use
        inputDialogDisableAnon = disableAnon;  // [044] Store for later use
        showInputDialog(name, allInputs, tile);
        return;
    }

    if (inputs && inputs.length > 0) {
        serverDebug('[Agent] Showing input dialog');
        // Pin tile and show input dialog
        pinTile(tile);
        inputDialogOverrideBackend = overrideBackend;  // Store for later use
        inputDialogDisableAnon = disableAnon;  // [044] Store for later use
        showInputDialog(name, inputs, tile);
        return;
    }

    serverLog('[Agent] Starting: ' + name + (overrideBackend ? ' with backend: ' + overrideBackend : ''));
    // No inputs - run agent directly
    // Don't add .running class - we're immediately pinning which should be static
    // The .running animation is for unpinned tiles in the grid

    // Reset pending dialog state for new task
    resetPendingDialogState();

    // Clear any previous cancel request
    cancelRequestedForTask = null;

    // [028] Reset anonymization badge immediately for visual feedback (don't wait for SSE)
    // [044] If disableAnon, show OFF state immediately
    resetAnonBadge(disableAnon);

    // [067] D2: isAppendMode removed - default false in _createTaskState
    currentUserPrompt = `${t('agent.start_prefix')} ${name}`;
    userPromptDisplayed = false;

    // Pin the tile to top-left corner
    pinTile(tile);

    // Quick Access mode: Add running status to tile
    if (isQuickAccessMode) {
        tile.classList.add('qa-running');
        addQuickAccessChatButton(tile);
    }

    setLoading(true, name, t('agent.starting'));

    try {
        // Build URL with optional backend override and disable_anon
        let url = API + '/agent/' + name;
        const params = new URLSearchParams();
        if (overrideBackend) {
            params.set('backend', overrideBackend);
        }
        if (disableAnon) {
            params.set('disable_anon', 'true');
        }
        if (params.toString()) {
            url += '?' + params.toString();
        }
        const res = await fetch(url);
        const data = await res.json();
        serverDebug('[Agent] Server response - task_id: ' + data.task_id + ', backend: ' + (data.ai_backend || 'unknown'));

        if (data.task_id) {
            // #6 - Use pendingTaskId instead of currentTaskId to prevent race condition
            // currentTaskId will be set when task_start SSE event is received
            pendingTaskId = data.task_id;
            currentTaskTile = tile;
            // Set chat backend for follow-up messages (stay on same backend)
            currentChatBackend = data.ai_backend || null;
            currentChatName = name;

            // [030] Register task in ViewContext and switch view
            const taskState = ViewContext.registerTask(
                data.task_id, null, name,
                data.ai_backend || null, data.model || null, 'webui'
            );
            taskState.chat.backend = data.ai_backend || null;
            taskState.chat.agentName = name;
            taskState.pendingTaskId = data.task_id;
            taskState.taskTile = tile;
            taskState.userPrompt = currentUserPrompt;
            taskState.overlay.startTime = Date.now();
            taskState.overlay.mode = 'loading';
            ViewContext.switchView(data.task_id, null);

            // Start context polling if context tab is visible
            maybeStartContextPolling();
            const aiInfo = data.model ? `${data.ai_backend} • ${data.model}` : data.ai_backend || 'Agent';
            loadingStartTime = Date.now();
            const statusEl2 = document.getElementById('aiProcessingStatus');
            if (statusEl2) statusEl2.textContent = `${name} • ${aiInfo}`;
            // Update stats bar immediately with backend/model info
            updateStatsFromTask(data);
            startTaskMonitoring(data.task_id, tile, name, true);
        } else {
            showTileResult(tile, true);
            setLoading(false);
        }
    } catch (e) {
        console.error('[Agent] Error in runAgent:', e);
        showTileResult(tile, false);
        setLoading(false);
    }
}


// =============================================================================
// Safe Preview Mode (Ctrl+Shift+Click) - Dry-run / Backend Comparison
// =============================================================================

/**
 * Get all enabled backends from the server.
 * @returns {Promise<Array>} List of enabled backend names
 */
async function getEnabledBackends() {
    try {
        const res = await fetch(API + '/backends');
        const data = await res.json();
        return data.enabled || [];
    } catch (e) {
        serverLog('[Backends] Error fetching backends: ' + e);
        return [];
    }
}

/**
 * Start safe preview mode for an agent.
 * - Single backend: Runs dry-run (simulates destructive operations)
 * - Multiple backends: Shows comparison view with parallel execution
 *
 * @param {string} agentName - Name of the agent to preview
 * @param {HTMLElement} tile - The tile element
 */
async function startSafePreview(agentName, tile) {
    serverLog('[Preview] Starting safe preview for: ' + agentName);

    // Get enabled backends
    const backends = await getEnabledBackends();
    serverLog('[Preview] Enabled backends: ' + backends.join(', '));

    if (backends.length === 0) {
        showNotification(t('agent.no_backends'), 'error');
        return;
    }

    if (backends.length === 1) {
        // Single backend: Run dry-run mode
        await runAgentDryRun(agentName, backends[0], tile);
    } else {
        // Multiple backends: Show comparison dialog
        await showBackendComparisonDialog(agentName, backends, tile);
    }
}

/**
 * Run agent in dry-run mode (single backend).
 * Simulates destructive operations without executing them.
 *
 * @param {string} agentName - Name of the agent
 * @param {string} backend - Backend to use
 * @param {HTMLElement} tile - The tile element
 */
async function runAgentDryRun(agentName, backend, tile) {
    serverLog('[DryRun] Running agent: ' + agentName + ' on backend: ' + backend);

    // Pin tile and show loading
    pinTile(tile);
    setLoading(true, agentName, t('agent.preview_running'));

    try {
        // Call agent with dry_run=true
        const res = await fetch(API + '/agent/' + agentName + '?dry_run=true&backend=' + backend);
        const data = await res.json();

        if (data.task_id) {
            // #6 - Use pendingTaskId instead of currentTaskId to prevent race condition
            // currentTaskId will be set when task_start SSE event is received
            pendingTaskId = data.task_id;
            currentTaskTile = tile;
            currentChatBackend = backend;
            currentChatName = agentName;

            // [049] Register task in ViewContext and switch view
            const dryRunName = agentName + ' (' + t('agent.preview') + ')';
            let taskState = ViewContext.getTask(data.task_id);
            if (!taskState) {
                taskState = ViewContext.registerTask(
                    data.task_id, null, dryRunName,
                    backend, data.model || null, 'webui'
                );
            }
            taskState.chat.backend = backend;
            taskState.chat.agentName = agentName;
            taskState.taskTile = tile;
            taskState.overlay.startTime = Date.now();
            taskState.overlay.mode = 'loading';
            ViewContext.switchView(data.task_id, null);

            loadingStartTime = Date.now();
            const statusEl3 = document.getElementById('aiProcessingStatus');
            if (statusEl3) statusEl3.textContent = `${agentName} • ${backend} (${t('agent.preview')})`;
            // Update stats bar immediately with backend/model info
            updateStatsFromTask({ai_backend: backend, model: data.model});

            // Start monitoring with dry-run indicator
            startTaskMonitoring(data.task_id, tile, dryRunName, true);
        } else {
            showTileResult(tile, false);
            setLoading(false);
        }
    } catch (e) {
        serverLog('[DryRun] Error: ' + e);
        showTileResult(tile, false);
        setLoading(false);
    }
}

/**
 * Show backend comparison dialog.
 * Allows user to select backends and run comparison.
 *
 * @param {string} agentName - Name of the agent
 * @param {Array} backends - List of available backends
 * @param {HTMLElement} tile - The tile element
 */
async function showBackendComparisonDialog(agentName, backends, tile) {
    // Create comparison dialog
    const overlay = document.createElement('div');
    overlay.id = 'comparisonOverlay';
    overlay.className = 'modal-overlay';

    // Build backend checkboxes
    const checkboxesHtml = backends.map((b, i) => `
        <label class="comparison-backend-option">
            <input type="checkbox" name="backend" value="${b}" checked>
            <span>${b}</span>
        </label>
    `).join('');

    overlay.innerHTML = `
        <div class="comparison-dialog">
            <div class="comparison-header">
                <span class="material-icons">compare</span>
                <h3>${t('comparison.title')} ${agentName}</h3>
                <button class="close-btn" onclick="closeComparisonDialog()">
                    <span class="material-icons">close</span>
                </button>
            </div>
            <div class="comparison-content">
                <p>${t('comparison.select_backends')}</p>
                <div class="comparison-backends">
                    ${checkboxesHtml}
                </div>
                <div class="comparison-options">
                    <label>
                        <input type="checkbox" id="comparisonDryRun" checked>
                        ${t('comparison.dry_run')}
                    </label>
                </div>
            </div>
            <div class="comparison-actions">
                <button class="btn-secondary" onclick="closeComparisonDialog()">${t('dialog.cancel')}</button>
                <button class="btn-primary" onclick="startBackendComparison('${agentName}')">
                    <span class="material-icons">play_arrow</span>
                    ${t('comparison.compare')}
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Store tile reference for later
    window._comparisonTile = tile;
}

/**
 * Close the comparison dialog.
 */
function closeComparisonDialog() {
    const overlay = document.getElementById('comparisonOverlay');
    if (overlay) {
        overlay.remove();
    }
    window._comparisonTile = null;
}

/**
 * Start backend comparison with selected backends.
 *
 * @param {string} agentName - Name of the agent
 */
async function startBackendComparison(agentName) {
    // Get selected backends
    const checkboxes = document.querySelectorAll('#comparisonOverlay input[name="backend"]:checked');
    const backends = Array.from(checkboxes).map(cb => cb.value);

    if (backends.length === 0) {
        showNotification(t('comparison.select_one'), 'warning');
        return;
    }

    const dryRun = document.getElementById('comparisonDryRun')?.checked ?? true;

    serverLog('[Compare] Starting comparison: ' + agentName + ' backends: ' + backends.join(', ') + ' dry_run: ' + dryRun);

    // Close dialog
    closeComparisonDialog();

    const tile = window._comparisonTile;

    // Use split view parallel comparison (streaming) if available
    if (typeof startParallelComparison === 'function') {
        await startParallelComparison(agentName, backends, tile, dryRun);
    } else {
        // Fallback to batch comparison via /test/compare endpoint
        if (tile) {
            pinTile(tile);
        }
        setLoading(true, agentName, t('comparison.running'));

        try {
            const res = await fetch(API + '/test/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    agent_name: agentName,
                    backends: backends,
                    dry_run: dryRun
                })
            });

            const comparison = await res.json();
            setLoading(false);

            // Show comparison results
            showComparisonResults(comparison);

        } catch (e) {
            serverLog('[Compare] Error: ' + e);
            setLoading(false);
            showNotification(t('comparison.failed') + ' ' + e.message, 'error');
        }
    }
}

/**
 * Show comparison results in a dialog.
 *
 * @param {Object} comparison - Comparison result from server
 */
function showComparisonResults(comparison) {
    const overlay = document.createElement('div');
    overlay.id = 'comparisonResultsOverlay';
    overlay.className = 'modal-overlay';

    // Build results table rows
    const rows = Object.entries(comparison.backends || {}).map(([name, data]) => {
        const statusIcon = data.success ? '✓' : '✗';
        const statusClass = data.success ? 'success' : 'error';
        const duration = data.duration_sec?.toFixed(1) || '0.0';
        const tokens = `${data.tokens?.input || 0} / ${data.tokens?.output || 0}`;
        const cost = data.cost_usd ? `$${data.cost_usd.toFixed(4)}` : '$0.0000';

        return `
            <tr class="${statusClass}">
                <td><strong>${name}</strong></td>
                <td>${duration}s</td>
                <td>${tokens}</td>
                <td>${cost}</td>
                <td>${statusIcon}</td>
            </tr>
        `;
    }).join('');

    // Build winner badges
    const winner = comparison.winner || {};
    const winnerHtml = [];
    if (winner.fastest) winnerHtml.push(`<span class="winner-badge fastest">⚡ ${winner.fastest}</span>`);
    if (winner.cheapest) winnerHtml.push(`<span class="winner-badge cheapest">💰 ${winner.cheapest}</span>`);
    if (winner.most_tokens) winnerHtml.push(`<span class="winner-badge tokens">📝 ${winner.most_tokens}</span>`);

    overlay.innerHTML = `
        <div class="comparison-dialog comparison-results">
            <div class="comparison-header">
                <span class="material-icons">analytics</span>
                <h3>${t('comparison.result')} ${comparison.agent}</h3>
                <button class="close-btn" onclick="closeComparisonResults()">
                    <span class="material-icons">close</span>
                </button>
            </div>
            <div class="comparison-content">
                ${comparison.dry_run ? '<div class="dry-run-badge">' + t('comparison.dry_run_mode') + '</div>' : ''}
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>${t('comparison.backend')}</th>
                            <th>${t('comparison.time')}</th>
                            <th>${t('result.tokens')}</th>
                            <th>${t('comparison.cost')}</th>
                            <th>OK</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
                <div class="comparison-winners">
                    ${winnerHtml.join('')}
                </div>
            </div>
            <div class="comparison-actions">
                ${comparison.file ? `
                    <button class="btn-secondary" onclick="downloadComparison('${comparison.file}')">
                        <span class="material-icons">download</span>
                        JSON
                    </button>
                ` : ''}
                <button class="btn-primary" onclick="closeComparisonResults()">${t('dialog.close')}</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
}

/**
 * Close comparison results dialog.
 */
function closeComparisonResults() {
    const overlay = document.getElementById('comparisonResultsOverlay');
    if (overlay) {
        overlay.remove();
    }
}

/**
 * Download comparison JSON file.
 *
 * @param {string} filePath - Path to the comparison file
 */
function downloadComparison(filePath) {
    // Extract filename from path
    const filename = filePath.split(/[/\\]/).pop();

    // Fetch the file content
    fetch(API + '/test/comparison/' + filename)
        .then(res => res.json())
        .then(data => {
            // Create download
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
        })
        .catch(e => {
            serverLog('[Download] Error: ' + e);
            showNotification(t('comparison.download_failed'), 'error');
        });
}


// Run skill
async function runSkill(tile, e, name) {
    // Check if backend is ready (prevents clicks during startup)
    if (!backendReady) {
        serverLog('[Skill] Backend not ready, ignoring click');
        showToast(t('startup.please_wait') || 'Please wait...', 2000);
        return;
    }

    // Immediate visual feedback - show tile is loading
    if (tile) {
        tile.classList.add('tile-loading');
    }

    // License check before running skill
    const licenseCheck = await checkAgentLicense(name);
    if (!licenseCheck.allowed) {
        clearTileLoading(tile);
        showLicenseRequiredDialog(licenseCheck.reason, licenseCheck.message);
        return;
    }

    // Clear loading state - pinTile will handle visual state from here
    clearTileLoading(tile);

    // Clear previous session when starting a new skill
    await clearHistory();

    // Track current skill for context clearing
    currentSkillName = name;

    // Reset pending dialog state for new task
    resetPendingDialogState();

    // Clear any previous cancel request
    cancelRequestedForTask = null;

    // [067] D3: isAppendMode removed - default false in _createTaskState
    currentUserPrompt = `${t('skill.start_prefix')} ${name}`;
    userPromptDisplayed = false;

    // Pin the tile to top-left corner
    pinTile(tile);
    setLoading(true, name, t('skill.skill'));

    try {
        const res = await fetch(API + '/skill/' + name);
        const data = await res.json();

        if (data.task_id) {
            // #6 - Use pendingTaskId instead of currentTaskId to prevent race condition
            // currentTaskId will be set when task_start SSE event is received
            pendingTaskId = data.task_id;
            currentTaskTile = tile;

            // [049] Register task in ViewContext and switch view
            let taskState = ViewContext.getTask(data.task_id);
            if (!taskState) {
                taskState = ViewContext.registerTask(
                    data.task_id, null, name,
                    data.ai_backend || null, data.model || null, 'webui'
                );
            }
            taskState.taskTile = tile;
            taskState.overlay.startTime = Date.now();
            taskState.overlay.mode = 'loading';
            ViewContext.switchView(data.task_id, null);

            // Start context polling if context tab is visible
            maybeStartContextPolling();
            startTaskMonitoring(data.task_id, tile, name, false);
        } else {
            showTileResult(tile, true);
            setLoading(false);
        }
    } catch (e) {
        showTileResult(tile, false);
        setLoading(false);
    }
}

// Start workflow
async function startWorkflow(workflowId) {
    // Get the clicked tile (if called from UI event)
    const tile = (typeof event !== 'undefined' && event && event.currentTarget) ? event.currentTarget : null;
    if (tile) pinTile(tile);
    setLoading(true, workflowId, t('workflow.workflow'));

    try {
        const res = await fetch(API + '/workflows/' + workflowId + '/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await res.json();

        if (data.run_id) {
            // Workflow started successfully
            showTileResult(tile, true);
            addToHistory('system', t('workflow.started', {id: workflowId, run_id: data.run_id.substring(0, 8)}));
        } else if (data.error) {
            showTileResult(tile, false);
            addToHistory('error', `${t('workflow.error')} ${data.error}`);
        }
    } catch (e) {
        showTileResult(tile, false);
        addToHistory('error', `${t('workflow.start_failed')} ${e.message}`);
    } finally {
        setLoading(false);
    }
}

// Open chat with specific backend
async function openChat(chatId, backend) {
    // Check if backend is ready (prevents clicks during startup)
    if (!backendReady) {
        serverLog('[Chat] Backend not ready, ignoring click');
        showToast(t('startup.please_wait') || 'Please wait...', 2000);
        return;
    }

    // Get the clicked tile (if called from UI event)
    // Use optional chaining to safely access event.currentTarget
    // (event may be undefined or stale when called programmatically)
    let tile = (typeof event !== 'undefined' && event?.currentTarget) ? event.currentTarget : null;

    // Fallback: Try to find tile by ID (for programmatic calls like from History)
    if (!tile) {
        tile = document.getElementById('tile-' + chatId) || document.getElementById('tile-' + backend);
    }

    // Fallback: Create mini-tile if still not found
    if (!tile && typeof createSessionMiniTile === 'function') {
        tile = createSessionMiniTile(chatId, backend, '');
    }

    if (tile) pinTile(tile);

    // Clear existing conversation
    await clearHistory();

    // Set the chat backend
    currentChatBackend = backend;
    currentChatName = chatId;

    // [067] D4: isAppendMode removed - default false in _createTaskState
    currentUserPrompt = null;
    userPromptDisplayed = false;

    // Hide tiles, show prompt area
    hideTiles();

    // Show prompt area
    showPromptArea();

    // Focus on input
    const input = document.getElementById('promptInput');
    input.placeholder = t('chat.with', {backend: backend});
    input.focus();

    // Show a minimal result panel with chat intro
    const resultPanel = document.getElementById('resultPanel');
    const resultTitle = document.getElementById('resultTitle');
    const resultContent = document.getElementById('resultContent');

    if (resultTitle) resultTitle.textContent = `${t('chat.title')} ${backend}`;
    resultContent.innerHTML = `<div class="chat-intro">
        <span class="material-icons">chat</span>
        <p>${t('chat.start_conversation')} <strong>${backend}</strong>.</p>
        <p class="chat-hint">${t('chat.all_tools_available')}</p>
    </div>`;

    resultPanel.classList.add('visible');
    serverLog('openChat: resultPanel visible=' + resultPanel.classList.contains('visible'));
}

// =============================================================================
// Shift/Ctrl Key Visual Feedback for Agent Tiles
// =============================================================================

let modifierTooltip = null;
let lastMouseX = 0;
let lastMouseY = 0;
let currentModifier = null;  // 'shift', 'ctrl', or 'compare'

/**
 * Remove modifier tooltip and reset state
 */
function cleanupModifierTooltip() {
    if (modifierTooltip) {
        modifierTooltip.remove();
        modifierTooltip = null;
    }
    currentModifier = null;
    // Reset cursor on all agent tiles
    document.querySelectorAll('.tile.agent').forEach(tile => {
        tile.style.cursor = '';
    });
}

// Track mouse position continuously
document.addEventListener('mousemove', (e) => {
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    if (modifierTooltip) {
        modifierTooltip.style.left = (e.clientX + 15) + 'px';
        modifierTooltip.style.top = (e.clientY + 15) + 'px';
    }
});

// Cleanup tooltip when window loses focus (prevents stuck tooltip)
window.addEventListener('blur', cleanupModifierTooltip);

// Cleanup tooltip when page visibility changes
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        cleanupModifierTooltip();
    }
});

// Cleanup tooltip when tileGrid becomes hidden (e.g., agent starts, chat opens)
const tileGridObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
            const target = mutation.target;
            if (target.classList.contains('hidden') && modifierTooltip) {
                cleanupModifierTooltip();
            }
        }
    }
});

// Start observing tileGrid when DOM is ready
function initTileGridObserver() {
    const tileGrid = document.getElementById('tileGrid');
    if (tileGrid) {
        tileGridObserver.observe(tileGrid, { attributes: true, attributeFilter: ['class'] });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTileGridObserver);
} else {
    initTileGridObserver();
}

document.addEventListener('keydown', (e) => {
    // Only show tooltip when hovering over an agent tile
    const elementUnderMouse = document.elementFromPoint(lastMouseX, lastMouseY);
    const hoveredTile = elementUnderMouse?.closest('.tile.agent');
    if (!hoveredTile) {
        return;
    }

    // Ctrl+Shift: Preview mode (comparison)
    if (e.ctrlKey && e.shiftKey && !modifierTooltip) {
        currentModifier = 'compare';
        hoveredTile.style.cursor = 'zoom-in';

        // Create floating tooltip that follows mouse
        modifierTooltip = document.createElement('div');
        modifierTooltip.className = 'shift-tooltip compare-tooltip';
        modifierTooltip.innerHTML = '<span class="material-icons" style="font-size: 14px; vertical-align: middle; margin-right: 4px;">compare</span>' + t('agent.preview');
        modifierTooltip.style.left = (lastMouseX + 15) + 'px';
        modifierTooltip.style.top = (lastMouseY + 15) + 'px';
        document.body.appendChild(modifierTooltip);
        return; // Don't show Shift or Ctrl tooltip
    }

    // Shift key: Add context
    if (e.key === 'Shift' && !modifierTooltip && !e.ctrlKey) {
        currentModifier = 'shift';
        hoveredTile.style.cursor = 'copy';

        // Create floating tooltip that follows mouse
        modifierTooltip = document.createElement('div');
        modifierTooltip.className = 'shift-tooltip';
        modifierTooltip.innerHTML = '<span class="material-icons" style="font-size: 14px; vertical-align: middle; margin-right: 4px;">add_comment</span>' + t('tooltip.context');
        modifierTooltip.style.left = (lastMouseX + 15) + 'px';
        modifierTooltip.style.top = (lastMouseY + 15) + 'px';
        document.body.appendChild(modifierTooltip);
    }

    // Ctrl key: Edit agent
    if ((e.key === 'Control' || e.key === 'Meta') && !modifierTooltip && !e.shiftKey) {
        currentModifier = 'ctrl';
        hoveredTile.style.cursor = 'pointer';

        // Create floating tooltip that follows mouse
        modifierTooltip = document.createElement('div');
        modifierTooltip.className = 'shift-tooltip ctrl-tooltip';
        modifierTooltip.innerHTML = '<span class="material-icons" style="font-size: 14px; vertical-align: middle; margin-right: 4px;">edit</span>' + t('context_menu.edit');
        modifierTooltip.style.left = (lastMouseX + 15) + 'px';
        modifierTooltip.style.top = (lastMouseY + 15) + 'px';
        document.body.appendChild(modifierTooltip);
    }
});

document.addEventListener('keyup', (e) => {
    if (e.key === 'Shift' || e.key === 'Control' || e.key === 'Meta') {
        cleanupModifierTooltip();
    }
});

// =============================================================================
// Right-Click Context Menu for Agent Tiles
// =============================================================================

let activeContextMenu = null;
let contextMenuRequestId = 0;  // Track async requests to prevent race conditions

// Cache for backends to avoid delay on context menu
let cachedBackends = null;
let backendsLastFetched = 0;
const BACKENDS_CACHE_TTL = 60000;  // 1 minute cache

/**
 * Get backends synchronously if cached, otherwise return default
 * @returns {Object} Backends object with enabled array and default
 */
function getBackendsSync() {
    const now = Date.now();
    if (cachedBackends && (now - backendsLastFetched) < BACKENDS_CACHE_TTL) {
        return cachedBackends;
    }
    // Trigger async refresh in background
    refreshBackendsCache();
    return cachedBackends || { enabled: [], default: 'claude_sdk' };
}

/**
 * Refresh backends cache in background
 */
async function refreshBackendsCache() {
    try {
        const res = await fetch(API + '/backends');
        if (res.ok) {
            cachedBackends = await res.json();
            backendsLastFetched = Date.now();
        }
    } catch (err) {
        serverError('[ContextMenu] Failed to fetch backends: ' + err);
    }
}

// Pre-fetch backends on page load
document.addEventListener('DOMContentLoaded', () => {
    refreshBackendsCache();
});

/**
 * Close any open context menu
 */
function closeContextMenu() {
    if (activeContextMenu) {
        activeContextMenu.remove();
        activeContextMenu = null;
    }
    // Increment request ID to invalidate any pending async requests
    contextMenuRequestId++;
}

/**
 * Get agent name from tile's onclick attribute
 * @param {HTMLElement} tile - The tile element
 * @returns {string|null} Agent name or null
 */
function getAgentNameFromTile(tile) {
    const onclick = tile.getAttribute('onclick');
    if (!onclick) return null;
    const match = onclick.match(/runAgent\(this,\s*event,\s*'([^']+)'\)/);
    return match ? match[1] : null;
}

/**
 * Show context menu for agent tile
 * @param {MouseEvent} e - Right-click event
 * @param {HTMLElement} tile - The tile element
 * @param {string} agentName - Name of the agent
 */
function showAgentContextMenu(e, tile, agentName) {
    e.preventDefault();
    e.stopPropagation();
    closeContextMenu();

    // Get edit agent name from config
    const editAgentName = (typeof EDIT_AGENT !== 'undefined') ? EDIT_AGENT : 'create_agent';

    // Use cached backends synchronously (pre-fetched on page load)
    const backends = getBackendsSync();

    const menu = document.createElement('div');
    menu.className = 'context-menu';

    // Build menu items
    let menuHTML = `
        <div class="context-menu-item" data-action="run">
            <span class="material-icons">play_arrow</span>
            <span>${t('context_menu.run')}</span>
        </div>
        <div class="context-menu-item" data-action="preview">
            <span class="material-icons">visibility</span>
            <span>${t('context_menu.preview')}</span>
            <span class="context-menu-hint">Ctrl+Shift</span>
        </div>
        <div class="context-menu-item" data-action="preprompt">
            <span class="material-icons">add_comment</span>
            <span>${t('context_menu.preprompt')}</span>
            <span class="context-menu-hint">Shift</span>
        </div>
    `;

    // Add backend options if multiple backends are available
    if (backends.enabled && backends.enabled.length > 1) {
        menuHTML += `<div class="context-menu-separator"></div>`;
        menuHTML += `<div class="context-menu-label">${t('context_menu.run_with')}</div>`;

        for (const backend of backends.enabled) {
            const isDefault = backend === backends.default;
            const icon = getBackendIcon(backend);
            menuHTML += `
                <div class="context-menu-item" data-action="run-backend" data-backend="${backend}">
                    <span class="material-icons">${icon}</span>
                    <span>${backend}${isDefault ? ' ' + t('context_menu.default') : ''}</span>
                </div>
            `;
        }
    }

    // [044] Expert Mode: Run without Anonymization (hidden in Simple Mode)
    if (!document.body.classList.contains('simple-mode')) {
        menuHTML += `<div class="context-menu-separator expert-only"></div>`;
        menuHTML += `<div class="context-menu-label expert-only">${t('context_menu.expert_options')}</div>`;
        menuHTML += `
            <div class="context-menu-item expert-only" data-action="run-no-anon">
                <span class="material-icons">lock_open</span>
                <span>${t('context_menu.run_no_anon')}</span>
            </div>
        `;
    }

    // Pin/Unpin option
    const isPinned = isAgentPinned(agentName);
    const pinIcon = isPinned ? 'push_pin' : 'push_pin';
    const pinLabel = isPinned ? t('context_menu.unpin') : t('context_menu.pin');

    // Hide/Unhide option (hidden in simple mode via CSS)
    const isHidden = tile.dataset.hidden === 'true';
    const hideIcon = isHidden ? 'visibility' : 'visibility_off';
    const hideLabel = isHidden ? t('context_menu.unhide') : t('context_menu.hide');

    menuHTML += `
        <div class="context-menu-separator"></div>
        <div class="context-menu-item" data-action="toggle-pin">
            <span class="material-icons${isPinned ? '' : ' outlined'}">${pinIcon}</span>
            <span>${pinLabel}</span>
        </div>
        <div class="context-menu-item" data-action="toggle-hidden">
            <span class="material-icons">${hideIcon}</span>
            <span>${hideLabel}</span>
        </div>
        <div class="context-menu-separator"></div>
        <div class="context-menu-item" data-action="edit">
            <span class="material-icons">edit</span>
            <span>${t('context_menu.edit')}</span>
            <span class="context-menu-hint">Ctrl</span>
        </div>
        <div class="context-menu-item" data-action="improve">
            <span class="material-icons">auto_fix_high</span>
            <span>${t('context_menu.improve')}</span>
        </div>
    `;

    // Expert Mode: Add "Open in Editor" option (hidden in Simple Mode)
    if (!document.body.classList.contains('simple-mode')) {
        menuHTML += `
            <div class="context-menu-separator expert-only"></div>
            <div class="context-menu-item expert-only" data-action="open-editor">
                <span class="material-icons">code</span>
                <span>${t('context_menu.open_editor')}</span>
            </div>
        `;
    }

    menu.innerHTML = menuHTML;

    // Position menu at mouse cursor
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';

    document.body.appendChild(menu);
    activeContextMenu = menu;

    // Ensure menu stays within viewport
    const rect = menu.getBoundingClientRect();
    const padding = 12;  // Edge padding

    // Horizontal: Constrain to viewport
    if (rect.width >= window.innerWidth - padding * 2) {
        // Menu wider than viewport - center it
        menu.style.left = padding + 'px';
        menu.style.maxWidth = (window.innerWidth - padding * 2) + 'px';
    } else if (rect.right > window.innerWidth - padding) {
        menu.style.left = Math.max(padding, window.innerWidth - rect.width - padding) + 'px';
    } else if (rect.left < padding) {
        menu.style.left = padding + 'px';
    }

    // Vertical: Constrain to viewport
    if (rect.bottom > window.innerHeight - padding) {
        menu.style.top = Math.max(padding, e.clientY - rect.height) + 'px';
    }

    // Handle menu item clicks
    menu.querySelectorAll('.context-menu-item').forEach(item => {
        item.addEventListener('click', async () => {
            const action = item.dataset.action;
            closeContextMenu();

            switch (action) {
                case 'run':
                    // Normal run - simulate regular click
                    runAgent(tile, { shiftKey: false, ctrlKey: false }, agentName);
                    break;
                case 'preview':
                    // Preview mode - same as Ctrl+Shift+Click
                    await startSafePreview(agentName, tile);
                    break;
                case 'preprompt':
                    // Pre-Prompt mode - same as Shift+Click (add context)
                    addAgentToContext(agentName, tile);
                    break;
                case 'run-backend':
                    // Run with specific backend
                    const backend = item.dataset.backend;
                    serverLog('[ContextMenu] Running ' + agentName + ' with backend: ' + backend);
                    runAgentWithBackend(agentName, backend, tile);
                    break;
                case 'run-no-anon':
                    // [044] Expert Mode: Run without anonymization
                    serverLog('[ContextMenu] Running ' + agentName + ' WITHOUT anonymization (expert override)');
                    proceedWithAgent(tile, { shiftKey: false, ctrlKey: false, metaKey: false }, agentName, null, true);
                    break;
                case 'edit':
                    // Edit mode - same as Ctrl+Click
                    if (agentName !== editAgentName) {
                        const editAgentTile = document.querySelector(`.tile.agent[onclick*="${editAgentName}"]`);
                        const tileToPin = editAgentTile || tile;
                        const editInputs = [
                            {
                                name: 'agent_name',
                                type: 'text',
                                label: t('edit.agent_name'),
                                required: false,
                                default: agentName
                            },
                            {
                                name: 'description',
                                type: 'text',
                                label: t('edit.what_to_change'),
                                required: true,
                                multiline: true,
                                rows: 10,
                                placeholder: t('edit.change_placeholder')
                            }
                        ];
                        pinTile(tileToPin);
                        showInputDialog(editAgentName, editInputs, tileToPin);
                    }
                    break;
                case 'improve':
                    // Improve mode - start improve_agent with agent name
                    serverLog('[ContextMenu] Starting improve_agent for: ' + agentName);
                    // Create a temporary session tile for improve_agent (it has no UI tile in category:system)
                    const improveTile = typeof createSessionMiniTile === 'function'
                        ? createSessionMiniTile('improve_agent', 'claude_sdk', '')
                        : tile;
                    await executeAgentWithInputs('improve_agent', improveTile, { agent_name: agentName });
                    break;
                case 'toggle-pin':
                    // Toggle pin state for agent
                    await togglePinAgent(agentName);
                    serverLog('[ContextMenu] Toggled pin for: ' + agentName + ' (now ' + (isAgentPinned(agentName) ? 'pinned' : 'unpinned') + ')');
                    break;
                case 'toggle-hidden':
                    // Toggle hidden state for agent (expert mode only)
                    await toggleAgentHidden(agentName);
                    break;
                case 'open-editor':
                    // Open agent file in editor (expert mode only)
                    openAgentEditor(agentName);
                    break;
            }
        });
    });

    serverLog('[ContextMenu] Opened for agent: ' + agentName);
}

/**
 * Get icon for backend type
 * @param {string} backend - Backend name
 * @returns {string} Material icon name
 */
function getBackendIcon(backend) {
    const backendLower = backend.toLowerCase();
    if (backendLower.includes('claude')) return 'smart_toy';
    if (backendLower.includes('gemini')) return 'auto_awesome';
    if (backendLower.includes('openai') || backendLower.includes('gpt')) return 'psychology';
    if (backendLower.includes('ollama') || backendLower.includes('qwen') || backendLower.includes('mistral')) return 'memory';
    return 'model_training';
}

/**
 * Run agent with specific backend override
 * @param {string} agentName - Name of the agent
 * @param {string} backend - Backend to use
 * @param {HTMLElement} tile - The tile element
 */
async function runAgentWithBackend(agentName, backend, tile) {
    // Reuse proceedWithAgent logic with backend override
    // This ensures inputs are shown and all logic is consistent
    serverLog('[Agent] Running with backend override: ' + agentName + ' (' + backend + ')');
    const fakeEvent = { shiftKey: false, ctrlKey: false, metaKey: false };
    await proceedWithAgent(tile, fakeEvent, agentName, backend);
}

/**
 * Add context to an agent before running (Pre-Prompt feature).
 * In Quick Access mode: Opens a separate overlay window for context input.
 * In normal mode: Opens the input dialog with a context field (equivalent to Shift+Click).
 * @param {string} agentName - Name of the agent
 * @param {HTMLElement} tile - The tile element
 */
async function addAgentToContext(agentName, tile) {
    serverLog('[PrePrompt] Opening context dialog for: ' + agentName);

    // Quick Access mode: Open separate preprompt window
    if (isQuickAccessMode) {
        serverLog('[PrePrompt] Quick Access mode - opening overlay window');
        try {
            await fetch(`${API}/api/preprompt/open?agent=${encodeURIComponent(agentName)}`, {
                method: 'POST'
            });
        } catch (e) {
            serverError('[PrePrompt] Failed to open preprompt window: ' + e);
            showToast(t('agent.preprompt_failed') || 'Failed to open Pre-Prompt window');
        }
        return;
    }

    // Normal mode: Show input dialog with context field
    const inputs = await getAgentInputs(agentName);

    // Create context input field
    const contextInput = {
        name: '_context',
        type: 'text',
        label: t('agent.additional_context'),
        placeholder: t('agent.context_placeholder'),
        multiline: true,
        rows: 6,
        required: false
    };

    // Prepend context input to existing inputs
    const allInputs = [contextInput, ...(inputs || [])];

    // Pin tile and show input dialog
    pinTile(tile);
    inputDialogOverrideBackend = null;  // No backend override
    inputDialogDisableAnon = false;  // [044] No anon override from pre-prompt
    showInputDialog(agentName, allInputs, tile);
}

/**
 * Attach context menu handlers to all agent tiles.
 * Called on DOMContentLoaded and after refreshAgentTiles() to re-attach lost handlers.
 */
function attachTileContextMenuHandlers() {
    document.querySelectorAll('.tile.agent').forEach(tile => {
        // Skip if handler already attached (prevents duplicates)
        if (tile.hasAttribute('data-ctx-attached')) return;
        tile.setAttribute('data-ctx-attached', 'true');

        tile.addEventListener('contextmenu', (e) => {
            const agentName = getAgentNameFromTile(tile);
            if (agentName) {
                showAgentContextMenu(e, tile, agentName);
            }
        });
    });
}

// Attach context menu to all agent tiles on page load
document.addEventListener('DOMContentLoaded', () => {
    attachTileContextMenuHandlers();
});

// Close context menu when clicking elsewhere
document.addEventListener('click', (e) => {
    if (activeContextMenu && !activeContextMenu.contains(e.target)) {
        closeContextMenu();
    }
});

// Close context menu on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && activeContextMenu) {
        closeContextMenu();
    }
});

// Global ESC handler for cancelling running agents
document.addEventListener('keydown', (e) => {
    // Only cancel if ESC pressed, task is running, and no context menu/dialog is open
    // #6 - Check both currentTaskId and pendingTaskId (task may not have started SSE yet)
    if (e.key === 'Escape' && (currentTaskId || pendingTaskId) && !cancelRequestedForTask && !activeContextMenu) {
        // Don't cancel if an input dialog is open (handled by dialog's own ESC handler)
        const inputDialog = document.getElementById('agentInputDialog');
        if (inputDialog && inputDialog.classList.contains('visible')) {
            return; // Let the dialog's ESC handler handle it
        }
        e.preventDefault();
        cancelCurrentTask();
    }
});

// =============================================================================
// Helper: Start context polling when a task starts (updates stats bar live)
// =============================================================================

function maybeStartContextPolling() {
    // Always start polling when a task is running - updates the stats bar
    startContextPolling();
    // Also do an immediate fetch
    fetchAndUpdateContext();
}

// =============================================================================
// Quick Access Mode - Tile-only status display
// =============================================================================

/**
 * Add the "Open Chat" button to a pinned tile in Quick Access mode.
 * This button appears after task completion to open full result in popup.
 */
function addQuickAccessChatButton(tile) {
    // Check if button already exists
    let btn = tile.querySelector('.qa-chat-btn');
    if (!btn) {
        btn = document.createElement('button');
        btn.className = 'qa-chat-btn';
        btn.innerHTML = '<span class="material-icons" style="font-size:14px">open_in_new</span> Open';
        btn.onclick = (e) => {
            e.stopPropagation();
            openQuickAccessChat();
        };
        tile.appendChild(btn);
    }
}

// =============================================================================
// License Check - Soft lock for unlicensed users
// =============================================================================

/**
 * Check if agent can be executed with current license.
 * @param {string} agentName - Name of agent to run
 * @returns {Promise<{allowed: boolean, reason?: string, message?: string}>}
 */
async function checkAgentLicense(agentName) {
    try {
        const res = await fetch(API + '/license/check-agent?agent_name=' + encodeURIComponent(agentName));
        return await res.json();
    } catch (e) {
        // Network error - allow execution (graceful degradation)
        console.warn('[License] Check failed, allowing execution:', e);
        return { allowed: true };
    }
}

/**
 * Show the "License Required" dialog when user tries to run an agent without license.
 * @param {string} reason - Error reason code
 * @param {string} message - User-friendly message
 */
function showLicenseRequiredDialog(reason, message) {
    // Remove any existing overlay
    removeExistingOverlay('.confirm-overlay');

    const overlay = createModalOverlay({
        id: 'licenseRequiredOverlay',
        closeOnClick: true
    });

    overlay.innerHTML = `
        <div class="confirm-dialog license-dialog">
            <div class="confirm-header">
                <span class="material-icons" style="color: var(--warning-color); font-size: 28px;">lock</span>
                <h3>${t('license.required_title')}</h3>
            </div>
            <div class="confirm-content">
                <p style="margin: 16px 0; color: var(--text-secondary);">
                    ${message || t('license.required_message')}
                </p>
            </div>
            <div class="confirm-buttons">
                <button class="btn-cancel" onclick="this.closest('.confirm-overlay').remove()">
                    ${t('dialog.close')}
                </button>
                <button class="btn-confirm" onclick="openSettings('license'); this.closest('.confirm-overlay').remove();" style="display: inline-flex; align-items: center; justify-content: center; gap: 6px;">
                    <span class="material-icons" style="font-size: 18px; line-height: 1;">vpn_key</span>${t('license.activate_now')}
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
}

// =============================================================================
// Agent Editor (Expert Mode - File Editing)
// =============================================================================

let currentEditingAgent = null;

/**
 * Open agent file in editor dialog
 * @param {string} agentName - Name of the agent to edit
 */
async function openAgentEditor(agentName) {
    closeContextMenu();
    try {
        const res = await fetch(API + '/agents/' + encodeURIComponent(agentName) + '/content');
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to load agent');
        }
        const data = await res.json();

        currentEditingAgent = data;

        // Update dialog elements
        document.getElementById('editorAgentName').textContent =
            (data.editable ? 'Edit: ' : 'View: ') + data.name;
        document.getElementById('editorSource').textContent = data.source;
        document.getElementById('editorSource').className = 'source-badge ' + data.source;
        document.getElementById('editorPath').textContent = data.file_path;
        document.getElementById('agentEditorContent').value = data.content;
        document.getElementById('agentEditorContent').readOnly = !data.editable;

        // Ensure Save button has correct content and visibility
        const saveBtn = document.getElementById('btnSaveAgent');
        saveBtn.innerHTML = '<span class="material-icons">save</span> Save';
        saveBtn.style.display = data.editable ? 'inline-flex' : 'none';

        // Show dialog
        document.getElementById('agentEditorDialog').classList.remove('hidden');

        serverLog('[Editor] Opened agent: ' + agentName + ' (source: ' + data.source + ', editable: ' + data.editable + ')');
    } catch (err) {
        console.error('[Editor] Error loading agent:', err);
        alert('Failed to load agent: ' + err.message);
    }
}

/**
 * Close the agent editor dialog
 */
function closeAgentEditor() {
    document.getElementById('agentEditorDialog').classList.add('hidden');
    currentEditingAgent = null;
}

/**
 * Save the current agent content
 */
async function saveAgentContent() {
    if (!currentEditingAgent || !currentEditingAgent.editable) return;

    const content = document.getElementById('agentEditorContent').value;
    const saveBtn = document.getElementById('btnSaveAgent');

    try {
        // Show saving state
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="material-icons rotating">sync</span> Saving...';

        const res = await fetch(API + '/agents/' + encodeURIComponent(currentEditingAgent.name) + '/content', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Save failed');
        }

        serverLog('[Editor] Saved agent: ' + currentEditingAgent.name);

        closeAgentEditor();

        // Refresh tiles (agents may have changed)
        if (typeof refreshAgentTiles === 'function') {
            await refreshAgentTiles();
        }
    } catch (err) {
        console.error('[Editor] Error saving agent:', err);
        alert('Failed to save: ' + err.message);
    } finally {
        // Reset button state
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<span class="material-icons">save</span> Save';
    }
}
