/**
 * WebUI Settings Panel Module
 *
 * Handles the settings panel including:
 * - Version info and updates
 * - Microsoft Graph API configuration
 * - Teams Watcher configuration
 * - License management
 * - Support/logs functionality
 *
 * Note: Uses global `API` constant defined in webui.html main script
 */

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Sanitize MCP name for use in HTML IDs (replace special chars)
 * @param {string} name - MCP name (e.g., "SAP S/4HANA:sap")
 * @returns {string} - Safe ID (e.g., "SAP_S_4HANA_sap")
 */
function sanitizeMcpId(name) {
    return name.replace(/[^a-zA-Z0-9_-]/g, '_');
}

// =============================================================================
// User Preferences (Language, Theme, UI State)
// =============================================================================

/**
 * Change UI language and reload page
 * Saves current view state to restore after reload
 * @param {string} lang - Language code (de, en)
 */
async function changeLanguage(lang) {
    // Save current view state before reload
    const activeTab = document.querySelector('.settings-tab.active')?.dataset?.tab || 'settingsTabPreferences';
    await savePreference('ui.language', lang);
    await savePreference('ui._restore_settings', activeTab);
    window.location.reload();
}

/**
 * Change UI theme and apply immediately
 * @param {string} theme - Theme name (light, dark)
 */
async function changeTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    await savePreference('ui.theme', theme);
}

/**
 * Save a startup preference and update UI
 * @param {string} key - Preference key (e.g., 'ui.auto_open_browser')
 * @param {boolean} value - Preference value
 */
async function saveStartupPreference(key, value) {
    try {
        const res = await fetch(API + '/preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: key, value: value })
        });
        if (res.ok) {
            console.log('[Prefs] Saved startup setting:', key, '=', value);
        }
    } catch (e) {
        console.error('[Prefs] Error saving startup setting:', e);
    }
}

/**
 * Initialize preference dropdowns with current values
 */
function initPreferenceControls() {
    // Language dropdown - use global LANG constant
    const langDropdown = document.getElementById('prefLanguage');
    if (langDropdown && typeof LANG !== 'undefined') {
        langDropdown.value = LANG;
    }

    // Theme dropdown - read from data-theme attribute
    const themeDropdown = document.getElementById('prefTheme');
    if (themeDropdown) {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
        themeDropdown.value = currentTheme;
    }

    // Load startup settings from preferences
    loadStartupPreferences();

    // Initialize AI model override dropdown
    initBackendOverrideDropdown();
}

/**
 * Initialize the AI backend override dropdown.
 * Loads available backends from /backends and current override from /config/backend_override.
 */
async function initBackendOverrideDropdown() {
    const dropdown = document.getElementById('prefBackendOverride');
    if (!dropdown) return;

    try {
        const res = await fetch(API + '/config/backend_override');
        if (!res.ok) return;
        const data = await res.json();

        // Clear existing options (keep only "Auto")
        dropdown.innerHTML = '';

        // Add Auto option
        const autoOption = document.createElement('option');
        autoOption.value = 'auto';
        autoOption.textContent = t('settings.preferences.ai_model_auto');
        dropdown.appendChild(autoOption);

        // Add separator
        const separator = document.createElement('option');
        separator.disabled = true;
        separator.textContent = '───────────────────';
        dropdown.appendChild(separator);

        // Add available backends
        if (data.available_backends) {
            for (const backend of data.available_backends) {
                const option = document.createElement('option');
                option.value = backend.id;
                // Format: "Backend Name (model-name)"
                const displayName = backend.id.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                option.textContent = `${displayName} (${backend.model})`;
                dropdown.appendChild(option);
            }
        }

        // Set current value
        dropdown.value = data.backend || 'auto';

        // Update hint text
        updateBackendOverrideHint(data.backend || 'auto');

    } catch (e) {
        console.error('[Settings] Failed to load backend override:', e);
    }
}

/**
 * Change the global AI backend override.
 * @param {string} value - Backend ID or "auto"
 */
async function changeBackendOverride(value) {
    try {
        const res = await fetch(API + '/config/backend_override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backend: value })
        });
        if (res.ok) {
            console.log('[Settings] Backend override:', value);
            updateBackendOverrideHint(value);
        } else {
            const err = await res.json();
            console.error('[Settings] Backend override failed:', err);
            // Revert dropdown
            initBackendOverrideDropdown();
        }
    } catch (e) {
        console.error('[Settings] Backend override error:', e);
        initBackendOverrideDropdown();
    }
}

/**
 * Update the hint text below the backend override dropdown.
 * Shows a warning when override is active.
 * @param {string} value - Current backend value
 */
function updateBackendOverrideHint(value) {
    const hint = document.getElementById('backendOverrideHint');
    if (!hint) return;

    if (value && value !== 'auto') {
        const displayName = value.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        hint.textContent = t('settings.preferences.ai_model_override_hint', { backend: displayName });
        hint.classList.remove('hidden');
    } else {
        hint.classList.add('hidden');
        hint.textContent = '';
    }
}

/**
 * Load startup preferences from server and update toggle states
 */
async function loadStartupPreferences() {
    try {
        const res = await fetch(API + '/preferences');
        if (res.ok) {
            const prefs = await res.json();
            if (prefs.ui) {
                const autoBrowser = document.getElementById('prefAutoBrowser');
                if (autoBrowser) autoBrowser.checked = prefs.ui.auto_open_browser || false;

                const autoQuickAccess = document.getElementById('prefAutoQuickAccess');
                if (autoQuickAccess) autoQuickAccess.checked = prefs.ui.auto_open_quick_access || false;
            }
        }
    } catch (e) {
        console.error('[Prefs] Error loading startup preferences:', e);
    }
}

// =============================================================================
// Settings Panel Core
// =============================================================================

async function openSettings(tab = null) {
    document.getElementById('settingsPanel').classList.remove('hidden');
    // Save open state to localStorage
    localStorage.setItem('settingsOpen', 'true');
    // Initialize preference dropdowns with current values
    initPreferenceControls();
    // Load current version
    try {
        const res = await fetch(API + '/version');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('localVersion').textContent = `v${data.version}`;
            // Show commit message tooltip if available
            const infoIcon = document.getElementById('localVersionInfo');
            if (infoIcon) {
                if (data.commit_message) {
                    infoIcon.title = data.commit_message;
                    infoIcon.classList.remove('hidden');
                } else {
                    infoIcon.classList.add('hidden');
                }
            }
        }
    } catch (e) {
        console.error('[Settings] Version fetch failed:', e);
        document.getElementById('localVersion').textContent = t('settings.version.unknown');
    }
    // Load release notes
    loadReleaseNotes();

    // Switch to specific tab if provided
    if (tab) {
        switchSettingsTab(tab);
    }
}

async function loadReleaseNotes(version = null) {
    const notesDiv = document.getElementById('releaseNotes');
    if (!notesDiv) return; // Element not present on this page

    const tagEl = document.getElementById('releaseTag');
    const dateEl = document.getElementById('releaseDate');
    const bodyEl = document.getElementById('releaseBody');

    try {
        const url = version ? API + '/release/notes/' + version : API + '/release/notes';
        const res = await fetch(url);
        const data = await res.json();

        if (data.error) {
            notesDiv.style.display = 'none';
            return;
        }

        // Show release info
        notesDiv.style.display = 'block';
        tagEl.textContent = data.name || ('Release v' + data.version);

        // Format date
        if (data.published_at) {
            const date = new Date(data.published_at);
            dateEl.textContent = date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
        } else {
            dateEl.textContent = '';
        }

        // Parse markdown-like body to HTML
        let body = data.body || '';
        body = body.replace(/^- /gm, '• ');
        body = body.replace(/\n/g, '<br>');
        bodyEl.innerHTML = body;

    } catch (e) {
        notesDiv.style.display = 'none';
    }
}

async function sendLogToSupport() {
    const status = document.getElementById('supportStatus');
    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.support.creating_email');
    status.className = 'update-status info';
    try {
        const res = await fetch(API + '/logs/send', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            status.innerHTML = t('settings.support.email_created') + '<br><small style="opacity:0.8">' + t('settings.support.email_check_outlook') + '</small>';
            status.className = 'update-status success';
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

function closeSettings() {
    document.getElementById('settingsPanel').classList.add('hidden');
    // Save closed state to localStorage
    localStorage.setItem('settingsOpen', 'false');
}

function switchSettingsTab(tab) {
    // Toggle tab buttons
    document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
    const tabId = 'settingsTab' + tab.charAt(0).toUpperCase() + tab.slice(1);
    document.getElementById(tabId).classList.add('active');
    // Toggle content
    document.querySelectorAll('.settings-tab-content').forEach(c => c.classList.add('hidden'));
    const contentId = 'settingsContent' + tab.charAt(0).toUpperCase() + tab.slice(1);
    document.getElementById(contentId).classList.remove('hidden');
    // Save current tab to localStorage
    localStorage.setItem('settingsTab', tab);
    // Load tab-specific data
    if (tab === 'info') {
        loadInfoTab();
    } else if (tab === 'api') {
        loadMSGraphStatus();
        loadTeamsWatcherStatus();
    } else if (tab === 'system') {
        loadSystemTabInfo();
    } else if (tab === 'logs') {
        refreshLogs();
    } else if (tab === 'license') {
        loadLicenseInfo();
    } else if (tab === 'developer') {
        loadDevSettings();
    } else if (tab === 'anonymization') {
        loadAnonymizationSettings();
        loadAnonymizationWhitelist();
    } else if (tab === 'integrations') {
        // loadOAuthProviders also calls loadBrowserIntegrationStatus internally
        loadOAuthProviders();
        loadClaudeDesktopStatus();
    } else if (tab === 'tests') {
        // Test tab is handled by webui-ui.js
    } else if (tab === 'update') {
        // Auto-check for updates when tab is opened
        checkForUpdates();
    }
}

// =============================================================================
// Info Tab Functions
// =============================================================================

function loadInfoTab() {
    // Copy version from localVersion element (set by openSettings)
    const version = document.getElementById('localVersion')?.textContent || '-';
    document.getElementById('infoVersion').textContent = version;
}

// =============================================================================
// License Functions
// =============================================================================

/**
 * Update or create the grace mode banner based on license status.
 * Shows a warning banner when operating in offline/grace mode.
 */
function updateGraceModeBanner(data) {
    let banner = document.getElementById('graceModeBanner');

    if (!data.grace_mode) {
        // Not in grace mode - hide banner if exists
        if (banner) {
            banner.style.display = 'none';
        }
        return;
    }

    // In grace mode - show banner
    if (!banner) {
        // Create banner if it doesn't exist
        banner = document.createElement('div');
        banner.id = 'graceModeBanner';
        banner.className = 'grace-mode-banner';
        // Insert at top of license status card
        const licenseStatus = document.getElementById('licenseStatus');
        if (licenseStatus) {
            licenseStatus.parentNode.insertBefore(banner, licenseStatus);
        }
    }

    // Update banner content based on warning level
    const isWarning = data.grace_show_warning;
    const remaining = data.grace_remaining_hours;
    const remainingText = remaining !== null
        ? (remaining >= 1 ? `${Math.floor(remaining)}h ${Math.round((remaining % 1) * 60)}min` : `${Math.round(remaining * 60)}min`)
        : '?';

    banner.className = isWarning ? 'grace-mode-banner warning' : 'grace-mode-banner';
    banner.innerHTML = `
        <span class="material-icons">${isWarning ? 'warning' : 'cloud_off'}</span>
        <div class="grace-mode-text">
            <strong>${isWarning ? t('license.grace_warning') : t('license.grace_offline')}</strong>
            <span>${isWarning
                ? t('license.grace_warning_text', {remaining: remainingText})
                : t('license.grace_offline_text', {remaining: remainingText})
            }</span>
        </div>
        <button class="grace-mode-retry" onclick="retryLicenseConnection()">
            <span class="material-icons">refresh</span> ${t('license.grace_retry')}
        </button>
    `;
    banner.style.display = 'flex';
}

/**
 * Try to reconnect to the license server.
 */
async function retryLicenseConnection() {
    const btn = document.querySelector('.grace-mode-retry');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('license.grace_retrying');
    }

    try {
        // Trigger a re-activation attempt by calling the activate endpoint
        // This will try to reconnect to the server
        const creds = await (await fetch(API + '/license/credentials')).json();
        if (creds && (creds.code || creds.invoice_number)) {
            const res = await fetch(API + '/license/activate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(creds)
            });
            const data = await res.json();
            if (data.success || (data.licensed && !data.grace_mode)) {
                showNotification(t('license.grace_reconnected'), 'success');
            }
        }
        // Reload license info to update UI
        await loadLicenseInfo();
    } catch (e) {
        showNotification(t('license.grace_failed'), 'error');
        console.error('[License] Retry failed:', e);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="material-icons">refresh</span> ' + t('license.grace_retry');
        }
    }
}

async function loadLicenseInfo() {
    console.log('[License] Loading license info...');
    try {
        const res = await fetch(API + '/license/status');
        const data = await res.json();

        const statusBadge = document.getElementById('licenseStatusBadge');
        const editionBadge = document.getElementById('licenseEdition');
        const licenseName = document.getElementById('licenseName');
        const licenseDeviceId = document.getElementById('licenseDeviceId');
        const licenseExpiry = document.getElementById('licenseExpiry');
        const activationCard = document.getElementById('activationCard');

        // Get action button elements
        const actionBtn = document.getElementById('licenseActionBtn');
        const actionIcon = document.getElementById('licenseActionIcon');
        const actionText = document.getElementById('licenseActionText');

        if (data.licensed) {
            // Licensed state - check for grace mode
            if (statusBadge) {
                if (data.grace_mode) {
                    // Grace mode - offline operation
                    statusBadge.textContent = 'OFFLINE';
                    statusBadge.className = data.grace_show_warning
                        ? 'license-status-badge warning'
                        : 'license-status-badge grace';
                } else {
                    statusBadge.textContent = t('settings.license.active');
                    statusBadge.className = 'license-status-badge active';
                }
            }

            // Show grace mode banner if in grace mode
            updateGraceModeBanner(data);
            if (editionBadge) {
                editionBadge.textContent = data.product || 'Undefined';
                editionBadge.className = 'license-edition-badge pro';
                editionBadge.style.display = '';  // Show when licensed
            }
            if (licenseName) {
                licenseName.textContent = data.email || '-';
            }
            if (licenseExpiry) {
                licenseExpiry.textContent = data.expires_at
                    ? new Date(data.expires_at).toLocaleDateString()
                    : '-';
            }
            // Update button to "Deaktivieren"
            if (actionIcon) actionIcon.textContent = 'cancel';
            if (actionText) actionText.textContent = t('settings.license.deactivate') || 'Deaktivieren';
            if (actionBtn) actionBtn.classList.remove('primary');
            window._licenseIsActive = true;
        } else {
            // Unlicensed state
            if (statusBadge) {
                statusBadge.textContent = t('settings.license.inactive') || 'INAKTIV';
                statusBadge.className = 'license-status-badge inactive';
            }
            if (editionBadge) {
                // Hide edition badge when unlicensed (no TRIAL or other placeholders)
                editionBadge.style.display = 'none';
                editionBadge.textContent = '';
            }
            if (licenseName) {
                licenseName.textContent = '-';
            }
            if (licenseExpiry) {
                licenseExpiry.textContent = '-';
            }
            // Update button to "Aktivieren"
            if (actionIcon) actionIcon.textContent = 'check_circle';
            if (actionText) actionText.textContent = t('settings.license.activate') || 'Aktivieren';
            if (actionBtn) actionBtn.classList.add('primary');
            window._licenseIsActive = false;

            // Hide grace mode banner when unlicensed
            updateGraceModeBanner({ grace_mode: false });
        }

        // Always show device info
        if (licenseDeviceId) {
            licenseDeviceId.textContent = data.device_id || '-';
        }
        const licenseDevice = document.getElementById('licenseDevice');
        if (licenseDevice) {
            licenseDevice.textContent = data.hostname || '-';
        }

        console.log('[License] Status loaded:', data.licensed ? 'Licensed' : 'Unlicensed');

        // Load saved credentials to pre-fill form
        await loadSavedCredentials();
    } catch (e) {
        console.error('[License] Failed to load status:', e);
    }
}

/**
 * Load saved credentials and pre-fill activation form fields.
 * Also checks prefill-setup.json for test/sandbox scenarios.
 */
async function loadSavedCredentials() {
    const invoiceField = document.getElementById('licenseInvoiceNumber');
    const zipField = document.getElementById('licenseZipCode');
    const emailField = document.getElementById('licenseEmail');
    const codeField = document.getElementById('licenseCode');

    try {
        const res = await fetch(API + '/license/credentials');
        const creds = await res.json();

        if (creds && Object.keys(creds).length > 0) {
            console.log('[License] Loading saved credentials:', creds.auth_method);

            if (creds.invoice_number && invoiceField) {
                invoiceField.value = creds.invoice_number;
            }
            if (creds.zip_code && zipField) {
                zipField.value = creds.zip_code;
            }
            if (creds.email && emailField) {
                emailField.value = creds.email;
            }
            if (creds.code && codeField) {
                codeField.value = creds.code;
            }

            // Switch to the correct activation method
            if (creds.auth_method === 'code') {
                switchLicenseMethod('code');
            } else if (creds.auth_method === 'invoice') {
                switchLicenseMethod('invoice');
            }
        }
    } catch (e) {
        console.error('[License] Failed to load saved credentials:', e);
    }

    // Check prefill-setup.json for any empty fields (sandbox testing)
    try {
        const emailEmpty = !emailField?.value;
        const codeEmpty = !codeField?.value;

        if (emailEmpty || codeEmpty) {
            const prefillRes = await fetch(API + '/api/setup/prefill');
            const prefill = await prefillRes.json();

            if (prefill.prefill) {
                console.log('[License] Loading prefill data from prefill-setup.json');

                if (emailEmpty && prefill.license_email && emailField) {
                    emailField.value = prefill.license_email;
                }
                if (codeEmpty && prefill.license_code && codeField) {
                    codeField.value = prefill.license_code;
                    // Switch to code method if we have a code from prefill
                    if (prefill.license_code) {
                        switchLicenseMethod('code');
                    }
                }
            }
        }
    } catch (e) {
        // Prefill is optional, don't log errors
    }
}

// Track current activation method
let licenseActivationMethod = 'invoice';

function switchLicenseMethod(method) {
    licenseActivationMethod = method;

    // Update button states
    const methodInvoice = document.getElementById('methodInvoice');
    const methodCode = document.getElementById('methodCode');
    if (methodInvoice) methodInvoice.classList.toggle('active', method === 'invoice');
    if (methodCode) methodCode.classList.toggle('active', method === 'code');

    // Show/hide appropriate fields
    const invoiceFields = document.getElementById('invoiceFields');
    const codeFields = document.getElementById('codeFields');
    if (invoiceFields) invoiceFields.style.display = method === 'invoice' ? 'block' : 'none';
    if (codeFields) codeFields.style.display = method === 'code' ? 'block' : 'none';

    // Clear status message
    const status = document.getElementById('licenseStatusMsg');
    if (status) status.textContent = '';
}

/**
 * Toggle between activate and deactivate based on current license state.
 */
async function toggleLicenseActivation() {
    if (window._licenseIsActive) {
        await deactivateLicense();
    } else {
        await activateLicense();
    }
}

/**
 * Deactivate the current license.
 */
async function deactivateLicense() {
    const confirmed = await showConfirm(
        t('settings.license.deactivate_title'),
        t('settings.license.deactivate_message'),
        {
            confirmText: t('settings.license.deactivate_button'),
            cancelText: t('dialog.cancel'),
            type: 'warning'
        }
    );
    if (!confirmed) return;

    const status = document.getElementById('licenseStatusMsg');
    status.textContent = t('settings.license.deactivating') || 'Deaktiviere...';
    status.className = 'update-status';

    try {
        const res = await fetch(API + '/license/deactivate', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            status.textContent = t('settings.license.deactivated_success') || 'Lizenz deaktiviert';
            status.className = 'update-status success';
            loadLicenseInfo();
        } else {
            status.textContent = data.error || t('settings.license.server_error');
            status.className = 'update-status error';
        }
    } catch (e) {
        console.error('[License] Deactivation failed:', e);
        status.textContent = t('settings.license.server_error');
        status.className = 'update-status error';
    }
}

async function activateLicense() {
    const status = document.getElementById('licenseStatusMsg');
    const email = document.getElementById('licenseEmail').value.trim();

    let payload = { email: email };

    if (licenseActivationMethod === 'code') {
        // Code activation
        const code = document.getElementById('licenseCode').value.trim();
        if (!code) {
            status.textContent = t('settings.license.enter_code');
            status.className = 'update-status error';
            return;
        }
        payload.code = code;
    } else {
        // Invoice + ZIP activation
        const invoiceNumber = document.getElementById('licenseInvoiceNumber').value.trim();
        const zipCode = document.getElementById('licenseZipCode').value.trim();
        if (!invoiceNumber || !zipCode) {
            status.textContent = t('settings.license.enter_invoice_zip');
            status.className = 'update-status error';
            return;
        }
        payload.invoice_number = invoiceNumber;
        payload.zip_code = zipCode;
    }

    status.textContent = t('settings.license.checking_activation');
    status.className = 'update-status';

    try {
        const res = await fetch(API + '/license/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (data.error || data.detail) {
            status.textContent = data.error || data.detail;
            status.className = 'update-status error';
        } else if (data.success) {
            status.textContent = t('settings.license.activated_success');
            status.className = 'update-status success';
            // Reload license info to update UI
            loadLicenseInfo();
            // Clear input fields
            document.getElementById('licenseInvoiceNumber').value = '';
            document.getElementById('licenseZipCode').value = '';
            document.getElementById('licenseCode').value = '';
            document.getElementById('licenseEmail').value = '';
        } else {
            status.textContent = t('settings.license.server_error');
            status.className = 'update-status error';
        }
    } catch (e) {
        console.error('[License] Activation failed:', e);
        status.textContent = t('settings.license.server_error');
        status.className = 'update-status error';
    }
}

async function deactivateDevice() {
    const confirmed = await showConfirm(
        t('settings.license.deactivate_title'),
        t('settings.license.deactivate_message'),
        {
            confirmText: t('settings.license.deactivate_button'),
            cancelText: t('dialog.cancel'),
            type: 'warning'
        }
    );
    if (!confirmed) return;

    const status = document.getElementById('licenseStatusMsg');
    status.textContent = t('settings.license.deactivating');
    status.className = 'update-status';

    try {
        const res = await fetch(API + '/license/deactivate', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            status.textContent = t('settings.license.deactivated_success');
            status.className = 'update-status success';
            // Reload license info to update UI
            loadLicenseInfo();
        } else {
            status.textContent = data.error || t('settings.license.server_error');
            status.className = 'update-status error';
        }
    } catch (e) {
        console.error('[License] Deactivation failed:', e);
        status.textContent = t('settings.license.server_error');
        status.className = 'update-status error';
    }
}

function openLicensePortal() {
    const portalUrl = window.BRANDING_PORTAL_URL;
    if (!portalUrl) {
        alert('License portal not configured (BRANDING_PORTAL_URL).');
        return;
    }
    window.open(portalUrl + 'dashboard', '_blank');
}

async function loadSystemTabInfo() {
    try {
        const res = await fetch(API + '/system/info');
        if (res.ok) {
            const info = await res.json();
            document.getElementById('systemVersion').textContent = info.version || '-';
            document.getElementById('systemBuild').textContent = info.build || '-';
            document.getElementById('systemPython').textContent = info.python || '-';
            document.getElementById('systemPlatform').textContent = info.platform || '-';
            document.getElementById('systemUptime').textContent = info.uptime || '-';

            // Set directory paths
            if (info.paths) {
                document.getElementById('pathExecutable').textContent = info.paths.executable || '-';
                document.getElementById('pathProject').textContent = info.paths.project || '-';
                document.getElementById('pathWorkspace').textContent = info.paths.workspace || '-';
                document.getElementById('pathConfig').textContent = info.paths.config || '-';
                document.getElementById('pathLogs').textContent = info.paths.logs || '-';
                document.getElementById('pathAgents').textContent = info.paths.agents || '-';
                document.getElementById('pathSkills').textContent = info.paths.skills || '-';
            }

            // Set port information (new in [014])
            if (info.ports) {
                updatePortDisplay('portHttp', 'portHttpStatus', info.ports.http, info.ports.http_running);
                updatePortDisplay('portMcpProxy', 'portMcpProxyStatus', info.ports.mcp_proxy, info.ports.mcp_proxy_running);
                updatePortDisplay('portFastmcp', 'portFastmcpStatus', info.ports.fastmcp, info.ports.fastmcp_running);
            }

            // Set MCP transport mode
            if (info.mcp) {
                document.getElementById('mcpTransport').textContent = info.mcp.transport || '-';
            }

            // Set Public API URL and Swagger link
            if (info.public_api) {
                const urlEl = document.getElementById('publicApiUrl');
                const swaggerEl = document.getElementById('swaggerLink');
                if (urlEl) {
                    urlEl.textContent = info.public_api.url || '-';
                    urlEl.dataset.url = info.public_api.url || '';
                }
                if (swaggerEl) {
                    swaggerEl.href = info.public_api.docs || '#';
                }
            }
        }
    } catch (e) {
        console.error('[System] Failed to load system info:', e);
    }

    // Load MCP and Plugins status
    loadMcpStatus();
    loadPluginsStatus();
}

/**
 * Update port display with value and status indicator.
 * @param {string} portId - Element ID for port number
 * @param {string} statusId - Element ID for status indicator
 * @param {number} port - Port number
 * @param {boolean} running - Whether the service is running
 */
function updatePortDisplay(portId, statusId, port, running) {
    const portEl = document.getElementById(portId);
    const statusEl = document.getElementById(statusId);
    if (portEl) {
        portEl.textContent = port || '-';
    }
    if (statusEl) {
        statusEl.className = 'port-status-indicator ' + (running ? 'running' : 'stopped');
        statusEl.title = running ? 'Running' : 'Not running';
    }
}

/**
 * Copy public API URL to clipboard.
 */
function copyPublicApiUrl() {
    const urlEl = document.getElementById('publicApiUrl');
    const url = urlEl?.dataset?.url || urlEl?.textContent;
    if (url && url !== '-') {
        navigator.clipboard.writeText(url).then(() => {
            showToast(t('settings.system.url_copied') || 'URL copied to clipboard');
        }).catch(e => {
            console.error('[System] Failed to copy URL:', e);
        });
    }
}

async function loadMcpStatus() {
    const container = document.getElementById('mcpStatusList');
    if (!container) return;

    try {
        const res = await fetch(API + '/mcp/status');
        if (res.ok) {
            const data = await res.json();
            const mcps = data.mcps || [];

            if (mcps.length === 0) {
                container.innerHTML = '<div class="mcp-status-empty">Keine MCPs gefunden</div>';
                return;
            }

            container.innerHTML = mcps.map(mcp => {
                const statusClass = mcp.configured ? 'configured' : (mcp.installed ? 'installed' : 'missing');
                const statusIcon = mcp.configured ? 'check_circle' : (mcp.installed ? 'radio_button_unchecked' : 'cancel');
                const statusText = mcp.configured ? t('settings.system.configured') : (mcp.installed ? t('settings.system.installed') : t('settings.system.missing'));
                const tooltip = mcp.description ? ` title="${mcp.description}"` : '';

                return `
                    <div class="mcp-status-item"${tooltip}>
                        <span class="mcp-name-container">
                            <span class="mcp-name">${mcp.name}</span>
                            ${mcp.beta ? '<span class="mcp-badge-beta">BETA</span>' : ''}
                            <span class="material-icons mcp-info-icon" onclick="showMcpInfo('${mcp.name}')" title="${t('settings.system.show_details')}">info_outline</span>
                        </span>
                        <span class="mcp-status ${statusClass}">
                            <span class="material-icons" style="font-size: 14px;">${statusIcon}</span>
                            ${statusText}
                        </span>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        console.error('[System] Failed to load MCP status:', e);
        container.innerHTML = '<div class="mcp-status-empty">' + t('settings.system.error_loading') + '</div>';
    }
}

/**
 * Show detailed MCP information in a dialog.
 * Fetches tool list and description from /mcp/info/{name} API.
 * @param {string} mcpName - Name of the MCP server (e.g., 'outlook', 'billomat')
 */
async function showMcpInfo(mcpName) {
    // Create overlay with loading state
    const overlay = document.createElement('div');
    overlay.className = 'mcp-info-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
        <div class="mcp-info-dialog">
            <div class="mcp-info-header">
                <span class="mcp-info-title">${mcpName}</span>
                <button class="mcp-info-close" onclick="this.closest('.mcp-info-overlay').remove()">
                    <span class="material-icons">close</span>
                </button>
            </div>
            <div class="mcp-info-body">
                <div class="mcp-info-loading">
                    <span class="material-icons spinning">refresh</span>
                    ${t('settings.system.loading_details')}
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Add keyboard handler for Escape
    const handleEscape = (e) => {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', handleEscape);
        }
    };
    document.addEventListener('keydown', handleEscape);

    try {
        const res = await fetch(API + '/mcp/info/' + encodeURIComponent(mcpName));
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();

        // Build dialog content
        const statusClass = data.configured ? 'configured' : 'installed';
        const statusIcon = data.configured ? 'check_circle' : 'radio_button_unchecked';
        const statusText = data.configured ? t('settings.system.configured') : t('settings.system.installed');

        // Build tools list HTML
        let toolsHtml = '';
        if (data.tools && data.tools.length > 0) {
            toolsHtml = `
                <div class="mcp-tools-section">
                    <div class="mcp-tools-header">
                        <span class="material-icons">build</span>
                        Tools (${data.tools.length})
                    </div>
                    <div class="mcp-tools-list">
                        ${data.tools.map(tool => `
                            <div class="mcp-tool-item">
                                <span class="mcp-tool-name">${escapeHtml(tool.name)}</span>
                                ${tool.description ? `<span class="mcp-tool-desc">${escapeHtml(tool.description)}</span>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        } else {
            toolsHtml = `
                <div class="mcp-tools-section">
                    <div class="mcp-tools-header">
                        <span class="material-icons">build</span>
                        Tools
                    </div>
                    <div class="mcp-tools-empty">${t('settings.system.no_tools')}</div>
                </div>
            `;
        }

        // Update dialog body
        const body = overlay.querySelector('.mcp-info-body');
        body.innerHTML = `
            <div class="mcp-info-description">${escapeHtml(data.description || t('settings.system.no_description'))}</div>
            <div class="mcp-info-status">
                <span class="material-icons ${statusClass}">${statusIcon}</span>
                <span>${statusText}</span>
            </div>
            ${toolsHtml}
        `;
    } catch (e) {
        console.error('[MCP Info] Failed to load:', e);
        const body = overlay.querySelector('.mcp-info-body');
        body.innerHTML = `
            <div class="mcp-info-error">
                <span class="material-icons">error</span>
                ${t('settings.system.error_loading')}: ${e.message}
            </div>
        `;
    }
}

async function loadPluginsStatus() {
    const container = document.getElementById('pluginsStatusList');
    if (!container) return;

    try {
        const res = await fetch(API + '/plugins/status');
        if (res.ok) {
            const data = await res.json();
            const plugins = data.plugins || [];

            if (plugins.length === 0) {
                container.innerHTML = '<div class="mcp-status-empty">' + t('settings.system.no_plugins') + '</div>';
                return;
            }

            container.innerHTML = plugins.map(plugin => {
                // Build content badges
                const badges = [];
                if (plugin.agent_count > 0) badges.push(`<span class="plugin-badge agents">${plugin.agent_count} Agents</span>`);
                if (plugin.mcp_count > 0) badges.push(`<span class="plugin-badge mcps">${plugin.mcp_count} MCPs</span>`);
                if (plugin.skill_count > 0) badges.push(`<span class="plugin-badge skills">${plugin.skill_count} Skills</span>`);
                if (plugin.knowledge_count > 0) badges.push(`<span class="plugin-badge knowledge">${plugin.knowledge_count} Knowledge</span>`);

                const statusClass = plugin.error ? 'error' : 'configured';
                const statusIcon = plugin.error ? 'error' : 'check_circle';

                return `
                    <div class="plugin-status-item">
                        <div class="plugin-header">
                            <span class="plugin-name">${plugin.name}</span>
                            <span class="plugin-version">v${plugin.version}</span>
                            <span class="mcp-status ${statusClass}">
                                <span class="material-icons" style="font-size: 14px;">${statusIcon}</span>
                            </span>
                        </div>
                        ${plugin.description ? `<div class="plugin-description">${plugin.description}</div>` : ''}
                        ${plugin.author ? `<div class="plugin-author">by ${plugin.author}</div>` : ''}
                        ${badges.length > 0 ? `<div class="plugin-badges">${badges.join('')}</div>` : ''}
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        console.error('[System] Failed to load plugins status:', e);
        container.innerHTML = '<div class="mcp-status-empty">' + t('settings.system.error_loading') + '</div>';
    }
}

// =============================================================================
// Microsoft Graph API Functions
// =============================================================================

async function loadMSGraphStatus() {
    try {
        const res = await fetch(API + '/msgraph/status');
        const data = await res.json();

        // Update status display
        const statusEl = document.getElementById('msgraphAuthStatus');

        if (data.authenticated) {
            statusEl.innerHTML = '<span style="color: var(--success-color);">&#10003; ' + t('settings.microsoft.connected_as') + ' ' + data.user + '</span>';
        } else {
            statusEl.innerHTML = '<span style="color: var(--text-secondary);">' + t('settings.microsoft.not_connected') + '</span>';
        }

        // Fill config fields
        document.getElementById('msgraphClientId').value = data.client_id || '';
        document.getElementById('msgraphTenantId').value = data.tenant_id || '';
    } catch (e) {
        document.getElementById('msgraphAuthStatus').innerHTML = '<span style="color: var(--error-color);">' + t('settings.microsoft.error_loading') + '</span>';
    }
}

async function saveMSGraphConfig() {
    const status = document.getElementById('msgraphStatusMsg');
    const clientId = document.getElementById('msgraphClientId').value.trim();
    const tenantId = document.getElementById('msgraphTenantId').value.trim();

    if (!clientId || !tenantId) {
        status.innerHTML = t('settings.microsoft.enter_client_tenant');
        status.className = 'update-status error';
        return;
    }

    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.microsoft.saving');
    status.className = 'update-status info';

    try {
        const res = await fetch(API + '/msgraph/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: clientId, tenant_id: tenantId })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            status.innerHTML = t('settings.microsoft.config_saved');
            status.className = 'update-status success';
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

async function authenticateMSGraph() {
    const status = document.getElementById('msgraphStatusMsg');
    const deviceCodeDiv = document.getElementById('msgraphDeviceCode');

    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.microsoft.starting_auth');
    status.className = 'update-status info';

    try {
        const res = await fetch(API + '/msgraph/authenticate', { method: 'POST' });
        const data = await res.json();

        if (data.user_code) {
            // Show device code
            document.getElementById('msgraphUserCode').textContent = data.user_code;
            document.getElementById('msgraphVerifyUrl').href = data.verification_uri;
            document.getElementById('msgraphVerifyUrl').textContent = data.verification_uri;
            deviceCodeDiv.classList.remove('hidden');
            status.innerHTML = t('settings.microsoft.code_generated');
            status.className = 'update-status info';
            // Auto-open login page in new tab
            window.open(data.verification_uri, '_blank');
        } else if (data.already_authenticated) {
            status.innerHTML = t('settings.microsoft.already_connected_as') + ' ' + data.user;
            status.className = 'update-status success';
            loadMSGraphStatus();
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

async function completeMSGraphAuth() {
    const status = document.getElementById('msgraphStatusMsg');
    const deviceCodeDiv = document.getElementById('msgraphDeviceCode');

    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.microsoft.checking_login');
    status.className = 'update-status info';

    try {
        const res = await fetch(API + '/msgraph/complete-auth', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            deviceCodeDiv.classList.add('hidden');
            status.innerHTML = t('settings.microsoft.connected_success') + ' ' + data.user;
            status.className = 'update-status success';
            loadMSGraphStatus();
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('settings.microsoft.login_not_complete'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

async function logoutMSGraph() {
    const status = document.getElementById('msgraphStatusMsg');

    try {
        const res = await fetch(API + '/msgraph/logout', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            status.innerHTML = t('settings.microsoft.logged_out');
            status.className = 'update-status success';
            loadMSGraphStatus();
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

// =============================================================================
// Teams Watcher Functions
// =============================================================================

async function loadTeamsWatcherStatus() {
    try {
        const res = await fetch(API + '/teams-watcher/status');
        const data = await res.json();

        // Update config fields
        document.getElementById('teamsWatcherEnabled').value = data.enabled ? 'true' : 'false';
        document.getElementById('teamsWatcherInterval').value = data.poll_interval || 10;
        document.getElementById('teamsWatcherAgent').value = data.agent || 'chat';
        document.getElementById('teamsWatcherWebhook').value = data.response_webhook || 'deskagent';

        // Update status badge
        const badge = document.getElementById('teamsWatcherStatusBadge');
        if (data.running) {
            badge.textContent = '● ' + t('settings.teams.status_active');
            badge.style.background = 'var(--success-color)';
            badge.style.color = 'white';
        } else if (data.enabled && data.channel_id) {
            badge.textContent = '○ ' + t('settings.teams.status_ready');
            badge.style.background = 'var(--warning-color)';
            badge.style.color = 'white';
        } else if (!data.channel_id) {
            badge.textContent = t('settings.teams.status_not_configured');
            badge.style.background = 'var(--bg-tertiary)';
            badge.style.color = 'var(--text-secondary)';
        } else {
            badge.textContent = t('settings.teams.status_disabled');
            badge.style.background = 'var(--bg-tertiary)';
            badge.style.color = 'var(--text-secondary)';
        }

        // Statistics
        const msgCount = data.stats?.messages_today ?? 0;
        document.getElementById('teamsWatcherMsgToday').textContent =
            msgCount + ' ' + t('settings.teams.messages');

    } catch (e) {
        console.error('[TeamsWatcher] Load error:', e);
    }
}

async function saveTeamsWatcherConfig() {
    const status = document.getElementById('teamsWatcherStatusMsg');
    const enabled = document.getElementById('teamsWatcherEnabled').value === 'true';
    const interval = parseInt(document.getElementById('teamsWatcherInterval').value) || 10;
    const agent = document.getElementById('teamsWatcherAgent').value.trim() || 'chat';
    const webhook = document.getElementById('teamsWatcherWebhook').value.trim() || 'deskagent';

    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.microsoft.saving');
    status.className = 'update-status info';

    try {
        const res = await fetch(API + '/teams-watcher/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled: enabled,
                poll_interval: interval,
                agent: agent,
                response_webhook: webhook
            })
        });
        const data = await res.json();

        if (data.status === 'ok') {
            status.innerHTML = t('settings.microsoft.config_saved');
            status.className = 'update-status success';
            loadTeamsWatcherStatus();
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('task.unknown_error'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

async function setupTeamsWatcher() {
    const status = document.getElementById('teamsWatcherStatusMsg');
    const channelName = document.getElementById('teamsWatcherChannelName').value.trim();

    if (!channelName) {
        status.innerHTML = t('settings.teams.enter_channel');
        status.className = 'update-status error';
        return;
    }

    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.teams.searching_channel') + ' "' + channelName + '"...';
    status.className = 'update-status info';

    try {
        const res = await fetch(API + '/teams-watcher/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_name: channelName })
        });
        const data = await res.json();

        if (data.status === 'ok') {
            status.innerHTML = t('settings.teams.channel_found') + ': ' + data.channel_name;
            status.className = 'update-status success';
            loadTeamsWatcherStatus();
        } else {
            status.innerHTML = t('task.error_prefix') + ' ' + (data.error || t('settings.teams.channel_not_found'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    }
}

// =============================================================================
// Update Functions
// =============================================================================

// Format release notes for display
function formatReleaseNotes(rawNotes) {
    if (!rawNotes) return '';
    return rawNotes
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/^###+ (.+)$/gm, '<strong>$1</strong>')
        .replace(/^## (.+)$/gm, '<strong style="font-size:1.1em">$1</strong>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/^\* (.+)$/gm, '&bull; $1')
        .replace(/^- (.+)$/gm, '&bull; $1')
        .replace(/\n/g, '<br>');
}

// Cache for version data
let versionDataCache = null;

async function checkForUpdates() {
    const status = document.getElementById('settingsUpdateStatus');
    const updateBtn = document.getElementById('updateBtn');
    const statusBadge = document.getElementById('updateStatusBadge');
    const newVersionSection = document.getElementById('updateNewVersion');
    const currentNotesEl = document.getElementById('currentVersionNotes');
    const newNotesEl = document.getElementById('newVersionNotes');

    // Show checking status
    statusBadge.className = 'update-status-badge';
    statusBadge.innerHTML = '<span class="material-icons spinning">refresh</span><span>' + t('settings.update.checking') + '</span>';
    status.textContent = '';
    status.className = 'update-status';
    updateBtn.classList.add('hidden');
    newVersionSection.classList.add('hidden');

    try {
        // Get version check result
        const checkRes = await fetch(API + '/version/check');
        const checkData = checkRes.ok ? await checkRes.json() : null;

        // Get version list for release notes
        const listRes = await fetch(API + '/version/list');
        const listData = listRes.ok ? await listRes.json() : { versions: [] };
        versionDataCache = listData.versions || [];

        // Find current version notes
        const localVersion = checkData?.local_version;
        const remoteVersion = checkData?.remote_version;

        const currentVersionData = versionDataCache.find(v => v.version === localVersion);
        const newVersionData = versionDataCache.find(v => v.version === remoteVersion);

        // Show current version notes
        if (currentVersionData && (currentVersionData.notes || currentVersionData.message)) {
            currentNotesEl.innerHTML = formatReleaseNotes(currentVersionData.notes || currentVersionData.message);
            currentNotesEl.style.display = 'block';
        } else {
            currentNotesEl.style.display = 'none';
        }

        if (checkData?.error) {
            status.textContent = checkData.error;
            status.classList.add('error');
            statusBadge.className = 'update-status-badge error';
            statusBadge.innerHTML = '<span class="material-icons">error</span><span>' + t('settings.update.check_error') + '</span>';
        } else if (checkData?.update_available) {
            // Show update available
            document.getElementById('remoteVersion').textContent = `v${remoteVersion}`;
            newVersionSection.classList.remove('hidden');
            statusBadge.className = 'update-status-badge update-available';
            statusBadge.innerHTML = '<span class="material-icons">upgrade</span><span>' + t('settings.update.available_excl') + '</span>';
            updateBtn.classList.remove('hidden');

            // Show new version notes
            if (newVersionData && (newVersionData.notes || newVersionData.message)) {
                newNotesEl.innerHTML = formatReleaseNotes(newVersionData.notes || newVersionData.message);
                newNotesEl.style.display = 'block';
            }
        } else {
            // Already up to date
            statusBadge.className = 'update-status-badge success';
            statusBadge.innerHTML = '<span class="material-icons">check_circle</span><span>' + t('settings.update.up_to_date') + '</span>';
        }

        // Load version history
        await loadVersionList();
    } catch (e) {
        status.textContent = t('settings.update.check_error') + ': ' + e.message;
        status.classList.add('error');
        statusBadge.className = 'update-status-badge error';
        statusBadge.innerHTML = '<span class="material-icons">cloud_off</span><span>' + t('settings.update.offline') + '</span>';
    } finally {
        // Check complete - status badge already updated
    }
}

function toggleVersionHistory() {
    const content = document.getElementById('versionHistoryContent');
    const icon = document.getElementById('versionHistoryExpandIcon');
    content.classList.toggle('hidden');
    icon.textContent = content.classList.contains('hidden') ? 'expand_more' : 'expand_less';

    // Load versions on first expand
    if (!content.classList.contains('hidden') && !versionsLoaded) {
        loadVersionList();
    }
}

async function runUpdate() {
    const updateBtn = document.getElementById('updateBtn');
    const status = document.getElementById('settingsUpdateStatus');

    updateBtn.disabled = true;
    updateBtn.innerHTML = '<span class="material-icons spinning">download</span> ' + t('settings.update.loading');

    const platform = getPlatform();

    try {
        // Get latest version info
        const res = await fetch(API + '/version/list');
        if (res.ok) {
            const data = await res.json();
            const versions = data.versions || [];

            if (versions.length > 0) {
                const latest = versions[0]; // First is newest
                const downloadUrl = platform === 'macos' ? latest.macos_url : latest.windows_url;

                if (downloadUrl) {
                    // Start download
                    window.open(downloadUrl, '_blank');
                    showDownloadInstructions();
                    status.textContent = '';
                    updateBtn.innerHTML = '<span class="material-icons">download</span> ' + t('settings.update.install');
                    updateBtn.disabled = false;
                } else {
                    status.textContent = t('settings.versions.unavailable');
                    status.className = 'update-status error';
                }
            }
        }
    } catch (e) {
        status.textContent = t('settings.update.error') + ': ' + e.message;
        status.className = 'update-status error';
    } finally {
        updateBtn.disabled = false;
        updateBtn.innerHTML = '<span class="material-icons">download</span> ' + t('settings.update.install');
    }
}

// =============================================================================
// Version List
// =============================================================================

let currentVersion = null;
let versionsLoaded = false;

// Detect platform
function getPlatform() {
    const ua = navigator.userAgent.toLowerCase();
    if (ua.includes('win')) return 'windows';
    if (ua.includes('mac')) return 'macos';
    return 'unknown';
}

// Show download instructions after starting download
function showDownloadInstructions() {
    const instructions = document.getElementById('downloadInstructions');
    if (instructions) {
        instructions.classList.remove('hidden');
    }
}

// Download installer and show instructions
function downloadInstaller(url, version) {
    // Start download
    window.open(url, '_blank');
    showDownloadInstructions();
}

// Helper to compare versions
function compareVersions(a, b) {
    const pa = a.split('.').map(Number);
    const pb = b.split('.').map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const na = pa[i] || 0, nb = pb[i] || 0;
        if (na > nb) return 1;
        if (na < nb) return -1;
    }
    return 0;
}

async function loadVersionList() {
    const list = document.getElementById('versionList');
    list.innerHTML = '<div class="loading-versions">' + t('settings.update.loading') + '</div>';

    const platform = getPlatform();

    try {
        // Get current version first
        const versionRes = await fetch(API + '/version');
        if (versionRes.ok) {
            const versionData = await versionRes.json();
            currentVersion = versionData.version;
        }

        // Get available versions
        const res = await fetch(API + '/version/list');
        if (res.ok) {
            const data = await res.json();
            const versions = data.versions || [];

            if (versions.length === 0) {
                list.innerHTML = '<div class="version-list-empty">' + t('settings.versions.none_found') + '</div>';
                return;
            }

            let html = '';
            for (const v of versions) {
                const isCurrent = v.version === currentVersion;
                const isOlder = currentVersion && compareVersions(v.version, currentVersion) < 0;

                // Release notes - format for display
                const rawNotes = v.notes || v.message || '';
                const notesHtml = rawNotes
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/^## (.+)$/gm, '<strong>$1</strong>')  // ## Headers
                    .replace(/^\* (.+)$/gm, '• $1')  // * Bullet points
                    .replace(/^- (.+)$/gm, '• $1')   // - Bullet points
                    .replace(/\n/g, '<br>');         // Line breaks

                // Platform-specific download URLs
                // Use archive URL for older versions (downgrades), stable URL for updates
                const stableUrl = platform === 'macos' ? v.macos_url : v.windows_url;
                const archiveUrl = platform === 'macos' ? v.macos_archive_url : v.windows_archive_url;

                // Date formatting
                const dateStr = v.date ? `<span class="version-date">${v.date}</span>` : '';

                // Action button
                let actionBtn = '';
                if (isCurrent) {
                    actionBtn = `<span class="version-badge current"><span class="material-icons">check</span>${t('settings.versions.installed')}</span>`;
                } else if (isOlder && archiveUrl) {
                    // Downgrade: use versioned archive URL
                    actionBtn = `<button class="version-btn downgrade" onclick="downloadInstaller('${archiveUrl}', '${v.version}')">
                        <span class="material-icons">history</span> Downgrade
                    </button>`;
                } else if (!isOlder && stableUrl) {
                    // Update: use stable URL (latest)
                    actionBtn = `<button class="version-btn upgrade" onclick="downloadInstaller('${stableUrl}', '${v.version}')">
                        <span class="material-icons">upgrade</span> Update
                    </button>`;
                } else {
                    // No installer available for this platform/version
                    actionBtn = `<span class="version-badge unavailable">${t('settings.versions.unavailable')}</span>`;
                }

                html += `
                    <div class="version-list-item ${isCurrent ? 'current' : ''} ${isOlder ? 'older' : ''}">
                        <div class="version-item-header">
                            <span class="version-tag">v${v.version}</span>
                            ${dateStr}
                            <span class="version-actions">
                                ${actionBtn}
                            </span>
                        </div>
                        ${notesHtml ? `<div class="version-notes">${notesHtml}</div>` : ''}
                    </div>
                `;
            }
            list.innerHTML = html;
            versionsLoaded = true;
        } else {
            list.innerHTML = '<div class="version-list-empty">' + t('settings.versions.error_loading') + '</div>';
        }
    } catch (e) {
        list.innerHTML = '<div class="version-list-empty">' + t('task.error_prefix') + ' ' + e.message + '</div>';
    }
}

async function installVersion(version) {
    const status = document.getElementById('settingsUpdateStatus');
    const statusBadge = document.getElementById('updateStatusBadge');
    status.innerHTML = `
        <div class="update-progress">${t('settings.install.progress')} v${version}...</div>
    `;
    status.className = 'update-status info';
    statusBadge.className = 'update-status-badge installing';
    statusBadge.innerHTML = '<span class="material-icons spinning">sync</span><span>' + t('settings.update.installing') + '</span>';

    // Disable all version buttons
    document.querySelectorAll('.version-btn').forEach(btn => btn.disabled = true);

    try {
        const res = await fetch(API + '/version/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version: version })
        });

        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                status.innerHTML = `
                    <div class="update-progress">v${version} ${t('settings.install.success')}</div>
                `;
                status.className = 'update-status success';
                statusBadge.className = 'update-status-badge success';
                statusBadge.innerHTML = '<span class="material-icons">check_circle</span><span>' + t('settings.install.restart_required') + '</span>';

                // Update the version list to show new current version
                currentVersion = version;
                document.getElementById('localVersion').textContent = `v${version}`;
                versionsLoaded = false;
                await loadVersionList();

                // Show restart button
                const updateBtn = document.getElementById('updateBtn');
                const checkBtn = document.getElementById('checkUpdateBtn');
                checkBtn.classList.add('hidden');
                updateBtn.classList.remove('hidden');
                updateBtn.innerHTML = '<span class="material-icons">restart_alt</span> ' + t('settings.update.restart');
                updateBtn.className = 'update-btn-primary accent';
                updateBtn.onclick = () => {
                    fetch(API + '/restart', { method: 'POST' });
                    statusBadge.innerHTML = '<span class="material-icons spinning">sync</span><span>' + t('settings.update.restarting') + '</span>';
                };
                updateBtn.disabled = false;
            } else {
                status.innerHTML = `<div class="update-progress">${t('settings.install.failed')}: ${data.error || t('task.unknown_error')}</div>`;
                status.className = 'update-status error';
                statusBadge.className = 'update-status-badge error';
                statusBadge.innerHTML = '<span class="material-icons">error</span><span>' + t('settings.install.failed') + '</span>';
            }
        } else {
            status.innerHTML = '<div class="update-progress">' + t('settings.install.failed') + '</div>';
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = `<div class="update-progress">${t('task.error_prefix')} ${e.message}</div>`;
        status.className = 'update-status error';
    } finally {
        // Re-enable version buttons
        document.querySelectorAll('.version-btn').forEach(btn => btn.disabled = false);
    }
}

// =============================================================================
// Developer Tab Functions
// =============================================================================

async function loadDevSettings() {
    // Load developer mode toggle state
    try {
        const res = await fetch(API + '/config/developer_mode');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('devModeToggle').checked = data.enabled || false;
        }
    } catch (e) {
        console.error('[Dev] Failed to load dev mode:', e);
    }

    // Load agents for comparison dropdown
    try {
        const res = await fetch(API + '/agents');
        if (res.ok) {
            const data = await res.json();
            const select = document.getElementById('devCompareAgent');
            if (select && data.agents) {
                select.innerHTML = '<option value="">' + t('settings.developer.select_agent') + '</option>';
                data.agents.forEach(agent => {
                    select.innerHTML += `<option value="${agent.id}">${agent.name}</option>`;
                });
            }
        }
    } catch (e) {
        console.error('[Dev] Failed to load agents:', e);
    }

    // Load backends for comparison checkboxes
    try {
        const res = await fetch(API + '/backends');
        if (res.ok) {
            const data = await res.json();
            const container = document.getElementById('devCompareBackends');
            if (container && data.backends) {
                container.innerHTML = '';
                data.backends.forEach(backend => {
                    container.innerHTML += `
                        <label style="display: flex; align-items: center; gap: 4px; font-size: 12px;">
                            <input type="checkbox" value="${backend.id}" checked>
                            ${backend.id}
                        </label>
                    `;
                });
            }
        }
    } catch (e) {
        console.error('[Dev] Failed to load backends:', e);
    }

    // Refresh debug status
    refreshDevStatus();
}

async function toggleDevMode() {
    const enabled = document.getElementById('devModeToggle').checked;
    try {
        const res = await fetch(API + '/config/developer_mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        if (res.ok) {
            console.log('[Dev] Developer mode:', enabled ? 'enabled' : 'disabled');
        }
    } catch (e) {
        console.error('[Dev] Failed to toggle dev mode:', e);
        // Revert toggle on error
        document.getElementById('devModeToggle').checked = !enabled;
    }
}

async function refreshDevStatus() {
    // Anonymization status
    try {
        const res = await fetch(API + '/status');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('devAnonStatus').textContent =
                data.anonymization?.enabled ? 'Enabled' : 'Disabled';
            document.getElementById('devActiveTasks').textContent =
                data.active_tasks || '0';
            document.getElementById('devMcpCount').textContent =
                data.mcp_servers || '-';
        }
    } catch (e) {
        console.error('[Dev] Failed to refresh status:', e);
    }
}

async function runBackendComparison() {
    const agentSelect = document.getElementById('devCompareAgent');
    const status = document.getElementById('devCompareStatus');
    const btn = document.getElementById('devCompareBtn');

    const agentName = agentSelect.value;
    if (!agentName) {
        status.innerHTML = t('settings.developer.select_agent_error');
        status.className = 'update-status error';
        return;
    }

    // Get selected backends
    const checkboxes = document.querySelectorAll('#devCompareBackends input[type="checkbox"]:checked');
    const backends = Array.from(checkboxes).map(cb => cb.value);

    if (backends.length < 2) {
        status.innerHTML = t('settings.developer.min_backends');
        status.className = 'update-status error';
        return;
    }

    btn.disabled = true;
    status.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.developer.comparing');
    status.className = 'update-status info';

    try {
        const res = await fetch(API + '/compare/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent_name: agentName,
                backends: backends,
                dry_run: true
            })
        });

        if (res.ok) {
            const data = await res.json();
            status.innerHTML = t('settings.developer.comparison_started') + ': ' + (data.task_id || 'OK');
            status.className = 'update-status success';
        } else {
            const data = await res.json();
            status.innerHTML = t('task.error_prefix') + ' ' + (data.detail || t('task.unknown_error'));
            status.className = 'update-status error';
        }
    } catch (e) {
        status.innerHTML = t('task.error_prefix') + ' ' + e.message;
        status.className = 'update-status error';
    } finally {
        btn.disabled = false;
    }
}

// =============================================================================
// Anonymization Settings & Test Functions
// =============================================================================

/**
 * Load anonymization settings from system.json
 */
async function loadAnonymizationSettings() {
    try {
        const res = await fetch(API + '/anonymization/settings');
        if (res.ok) {
            const data = await res.json();
            const enabledCheckbox = document.getElementById('anonEnabled');
            const logCheckbox = document.getElementById('anonLogEnabled');
            if (enabledCheckbox) enabledCheckbox.checked = data.enabled !== false;
            if (logCheckbox) logCheckbox.checked = data.log_anonymization === true;
        }
    } catch (e) {
        console.error('Failed to load anonymization settings:', e);
    }
}

/**
 * Toggle anonymization enabled setting
 */
async function toggleAnonymization(enabled) {
    try {
        const res = await fetch(API + '/anonymization/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'enabled', value: enabled })
        });
        if (res.ok) {
            showNotification(enabled ? 'Anonymization enabled' : 'Anonymization disabled', 'success');
            // Update header badge immediately to reflect the new state
            if (typeof resetAnonBadge === 'function') {
                resetAnonBadge(!enabled);
            }
        }
    } catch (e) {
        console.error('Failed to toggle anonymization:', e);
        showNotification('Failed to update setting', 'error');
    }
}

/**
 * Toggle anonymization logging setting
 */
async function toggleAnonymizationLog(enabled) {
    try {
        const res = await fetch(API + '/anonymization/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'log_anonymization', value: enabled })
        });
        if (res.ok) {
            showNotification(enabled ? 'Anonymization logging enabled' : 'Anonymization logging disabled', 'success');
        }
    } catch (e) {
        console.error('Failed to toggle anonymization log:', e);
        showNotification('Failed to update setting', 'error');
    }
}

/**
 * Load and display the anonymization whitelist
 */
async function loadAnonymizationWhitelist() {
    const container = document.getElementById('whitelistDisplay');
    const badge = document.getElementById('whitelistCount');
    if (!container) return;

    container.innerHTML = '<span class="material-icons spinning">refresh</span> Loading...';

    try {
        const res = await fetch(API + '/anonymization/whitelist');
        if (res.ok) {
            const data = await res.json();
            if (data.error) {
                container.innerHTML = `<span style="color: var(--status-error);">${data.error}</span>`;
                return;
            }

            // Update badge
            if (badge) badge.textContent = data.count;

            let html = '<div style="display: flex; flex-wrap: wrap; gap: 4px;">';
            data.whitelist.forEach(term => {
                html += `<span style="background: var(--bg-secondary); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${term}</span>`;
            });
            html += '</div>';

            container.innerHTML = html;
        } else {
            container.innerHTML = '<span style="color: var(--status-error);">Failed to load whitelist</span>';
        }
    } catch (e) {
        container.innerHTML = `<span style="color: var(--status-error);">Error: ${e.message}</span>`;
    }
}

/**
 * Run anonymization test on recent emails
 */
async function runAnonymizationTest() {
    const countInput = document.getElementById('anonTestCount');
    const resultsDiv = document.getElementById('anonTestResults');
    const btn = document.querySelector('#settingsContentAnonymization .settings-button');

    const count = parseInt(countInput.value) || 5;

    // Disable button and show loading
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons spinning">refresh</span> Testing...';
    }
    resultsDiv.innerHTML = '<div style="text-align: center; padding: 20px;"><span class="material-icons spinning" style="font-size: 32px;">refresh</span><div style="margin-top: 8px;">Fetching and testing emails...</div></div>';

    try {
        // Add timeout for long-running requests (60 seconds)
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000);

        const res = await fetch(API + '/anonymization/test?count=' + count, {
            method: 'POST',
            signal: controller.signal
        });
        clearTimeout(timeoutId);

        if (!res.ok) {
            throw new Error(`Server error: ${res.status} ${res.statusText}`);
        }

        const data = await res.json();

        if (data.error) {
            let errorHtml = `<div style="color: var(--status-error); padding: 12px;">
                <div style="font-weight: 500; margin-bottom: 8px;">${data.error}</div>`;
            if (data.details) {
                errorHtml += `<div style="font-size: 11px; color: var(--text-muted);">${data.details}</div>`;
            }
            errorHtml += '</div>';
            resultsDiv.innerHTML = errorHtml;
            return;
        }

        let html = `<div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">
            Source: <strong>${data.source}</strong> |
            Emails: <strong>${data.email_count}</strong> |
            Whitelist: <strong>${data.whitelist_count}</strong> terms
        </div>
        <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 12px;">
            <span style="background: #f59e0b; color: white; padding: 1px 5px; border-radius: 3px; margin-right: 4px;">Orange</span> Anonymized (hover for original)
            <span style="margin-left: 12px;"><span style="background: #10b981; color: white; padding: 1px 5px; border-radius: 3px; margin-right: 4px;">Green</span> Whitelist protected</span>
        </div>`;

        data.results.forEach((result, i) => {
            const hasEntities = result.entity_count > 0;
            const statusIcon = hasEntities ? 'security' : 'check_circle';
            const statusColor = hasEntities ? 'var(--status-warning)' : 'var(--status-success)';

            html += `<div class="anon-result" style="border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                    <span class="material-icons" style="color: ${statusColor};">${statusIcon}</span>
                    <strong style="flex: 1;">${escapeHtml(result.subject)}</strong>
                    <span style="font-size: 11px; color: var(--text-muted);">${escapeHtml(result.sender)}</span>
                </div>`;

            if (hasEntities) {
                html += `<div style="margin-bottom: 8px;">
                    <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">Detected Entities (${result.entity_count}):</div>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px;">`;
                for (const [placeholder, original] of Object.entries(result.mappings)) {
                    html += `<span style="background: var(--status-warning); color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px;" title="${escapeHtml(original)}">${escapeHtml(placeholder)}</span>`;
                }
                html += '</div></div>';
            }

            if (result.whitelist_protected && result.whitelist_protected.length > 0) {
                html += `<div style="margin-bottom: 8px;">
                    <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">Protected by Whitelist:</div>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px;">`;
                result.whitelist_protected.forEach(term => {
                    html += `<span style="background: var(--status-success); color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px;">${escapeHtml(term)}</span>`;
                });
                html += '</div></div>';
            }

            // Anonymized text with highlighted placeholders (hover for original)
            const anonymizedHighlighted = highlightAnonymizedText(result.anonymized, result.mappings, result.whitelist_protected);

            html += `<div style="margin-top: 8px;">
                <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 4px;">Anonymized (hover placeholders for original):</div>
                <div style="background: var(--bg-secondary); padding: 8px; border-radius: 4px; font-size: 11px; max-height: 300px; overflow: auto; white-space: pre-wrap;">${anonymizedHighlighted}</div>
            </div>`;

            html += '</div>';
        });

        resultsDiv.innerHTML = html;
    } catch (e) {
        let errorMsg = e.message;
        if (e.name === 'AbortError') {
            errorMsg = 'Request timed out (60s). Try fewer emails or check if Outlook is responding.';
        } else if (e.message.includes('fetch')) {
            errorMsg = 'Connection lost. Server may have restarted - please refresh the page.';
        }
        resultsDiv.innerHTML = `<div style="color: var(--status-error); padding: 12px;">
            <div style="font-weight: 500; margin-bottom: 8px;">Error</div>
            <div style="font-size: 11px;">${errorMsg}</div>
        </div>`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="material-icons">play_arrow</span> Run Test';
        }
    }
}

/**
 * Helper function to escape HTML entities
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Highlight anonymized text with tooltips showing original values
 */
function highlightAnonymizedText(text, mappings, whitelistHits) {
    let result = escapeHtml(text);

    // Highlight placeholders with tooltip showing original value (orange)
    if (mappings) {
        for (const [placeholder, original] of Object.entries(mappings)) {
            const escapedPlaceholder = escapeHtml(placeholder);
            const escapedOriginal = escapeHtml(original);
            const regex = new RegExp(escapedPlaceholder.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
            result = result.replace(regex, `<span style="background: #f59e0b; color: white; padding: 1px 4px; border-radius: 3px; font-weight: 500; cursor: help;" title="Original: ${escapedOriginal}">${escapedPlaceholder}</span>`);
        }
    }

    // Highlight whitelist protected terms (green)
    if (whitelistHits && whitelistHits.length > 0) {
        for (const term of whitelistHits) {
            const escaped = escapeHtml(term);
            const regex = new RegExp(escaped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
            result = result.replace(regex, `<span style="background: #10b981; color: white; padding: 1px 4px; border-radius: 3px;" title="Protected by whitelist">${escaped}</span>`);
        }
    }

    return result;
}

// =============================================================================
// Integrations Hub Functions
// =============================================================================

/**
 * Cache for loaded integration config values (to avoid flickering on re-render)
 */
let integrationConfigCache = {};
let _integrationsLoading = false; // Guard against parallel loads

/**
 * Load all integrations from the unified /api/integrations/list endpoint
 * Displays integrations grouped by auth_type with appropriate UI for each
 */
async function loadIntegrations() {
    const container = document.getElementById('oauthProvidersList');
    if (!container) return;

    // Prevent parallel loads (slow PCs can trigger multiple times)
    if (_integrationsLoading) {
        console.log('[Integrations] Already loading, skipping duplicate call');
        return;
    }
    _integrationsLoading = true;
    _settingsApiActive++; // Signal connection checker to be more tolerant

    container.innerHTML = '<div class="oauth-loading"><span class="material-icons spinning">refresh</span> ' + t('settings.integrations.loading') + '</div>';

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout
        const res = await fetch(API + '/api/integrations/list', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const integrations = await res.json();

        if (integrations.length === 0) {
            container.innerHTML = '<div class="oauth-empty">' + t('settings.integrations.no_providers') + '</div>';
            return;
        }

        // Group by auth_type for display
        const grouped = {
            oauth: integrations.filter(i => i.config.auth_type === 'oauth'),
            api_key: integrations.filter(i => i.config.auth_type === 'api_key'),
            credentials: integrations.filter(i => i.config.auth_type === 'credentials'),
            none: integrations.filter(i => i.config.auth_type === 'none')
        };

        let html = '';

        // OAuth Integrations (Cloud services with OAuth flow)
        if (grouped.oauth.length > 0) {
            html += `<div class="integration-group">
                <div class="integration-group-header">
                    <span class="material-icons">cloud</span>
                    <span>${t('settings.integrations.group_oauth')}</span>
                </div>`;
            for (const integration of grouped.oauth) {
                html += renderOAuthCard(integration);
            }
            html += '</div>';
        }

        // Credentials Section (API Keys + Username/Password combined)
        if (grouped.api_key.length > 0 || grouped.credentials.length > 0) {
            html += `<div class="integration-group">
                <div class="integration-group-header">
                    <span class="material-icons">key</span>
                    <span>${t('settings.integrations.group_credentials')}</span>
                </div>`;
            // API Key integrations first
            for (const integration of grouped.api_key) {
                html += renderApiKeyCard(integration);
            }
            // Then Username/Password integrations
            for (const integration of grouped.credentials) {
                html += renderCredentialsCard(integration);
            }
            html += '</div>';
        }

        // Local Integrations (no auth required)
        if (grouped.none.length > 0) {
            html += `<div class="integration-group">
                <div class="integration-group-header">
                    <span class="material-icons">computer</span>
                    <span>${t('settings.integrations.group_local')}</span>
                </div>`;
            for (const integration of grouped.none) {
                html += renderLocalCard(integration);
            }
            html += '</div>';
        }

        container.innerHTML = html;

        // Load current config values for expandable sections
        loadIntegrationConfigValues();

        // Load browser integration status (for toggle button)
        loadBrowserIntegrationStatus();

    } catch (e) {
        if (e.name === 'AbortError') {
            console.warn('[Integrations] Load timed out');
            container.innerHTML = `<div class="oauth-error"><span class="material-icons">error</span> ${t('settings.integrations.error_loading')}: Timeout</div>`;
        } else {
            console.error('[Integrations] Failed to load:', e);
            container.innerHTML = `<div class="oauth-error"><span class="material-icons">error</span> ${t('settings.integrations.error_loading')}: ${e.message}</div>`;
        }
    } finally {
        _integrationsLoading = false;
        _settingsApiActive = Math.max(0, _settingsApiActive - 1);
    }
}

/**
 * Render an OAuth integration card
 */
function renderOAuthCard(integration) {
    const { mcp_name, config, status } = integration;
    const isConnected = status === 'connected';
    const isConfigured = status !== 'not_configured';
    const statusClass = isConnected ? 'connected' : (isConfigured ? 'disconnected' : 'not-configured');
    const statusIcon = isConnected ? 'check_circle' : (isConfigured ? 'link_off' : 'settings');
    const statusText = isConnected
        ? t('settings.integrations.connected')
        : (isConfigured ? t('settings.integrations.disconnected') : t('settings.integrations.not_configured'));
    const iconColor = config.color || 'var(--accent-primary)';
    const betaBadge = config.beta ? '<span class="integration-beta-badge">BETA</span>' : '';

    // Advanced section for OAuth providers with configurable fields (like msgraph)
    let advancedSection = '';
    if (config.fields && config.fields.length > 0) {
        const fieldsHtml = config.fields.map(f => `
            <div class="oauth-advanced-field">
                <label>${escapeHtml(f.label)}${f.required ? ' *' : ''}:</label>
                <input type="${f.type === 'password' ? 'password' : 'text'}"
                       id="integration_${mcp_name}_${f.key}"
                       placeholder="${escapeHtml(f.hint || f.default || '')}"
                       data-integration="${mcp_name}"
                       data-field="${f.key}">
            </div>
        `).join('');

        advancedSection = `
            <div class="oauth-advanced-toggle" onclick="toggleIntegrationAdvanced('${mcp_name}')">
                <span class="material-icons" id="advancedIcon_${mcp_name}">expand_more</span>
                <span>${t('settings.integrations.advanced')}</span>
            </div>
            <div class="oauth-advanced-section hidden" id="advancedSection_${mcp_name}">
                <p style="font-size: 11px; color: var(--text-secondary); margin-bottom: 8px;">
                    ${config.description || t('settings.integrations.optional_config')}
                </p>
                ${fieldsHtml}
                <button class="oauth-btn small" onclick="saveIntegrationConfig('${mcp_name}')">
                    <span class="material-icons">save</span> ${t('settings.integrations.save')}
                </button>
            </div>
        `;
    }

    // Action buttons
    let actionButtons = '';
    if (isConnected) {
        actionButtons = `<button class="oauth-btn disconnect" onclick="disconnectOAuth('${mcp_name}')" title="${t('settings.integrations.disconnect')}">
            <span class="material-icons">link_off</span> ${t('settings.integrations.disconnect')}
        </button>`;
    } else if (isConfigured) {
        actionButtons = `<button class="oauth-btn connect" onclick="connectOAuth('${mcp_name}')" title="${t('settings.integrations.connect')}">
            <span class="material-icons">login</span> ${t('settings.integrations.connect')}
        </button>`;
    } else {
        actionButtons = `<button class="oauth-btn configure" onclick="showOAuthConfigHint('${mcp_name}')" title="${t('settings.integrations.configure')}">
            <span class="material-icons">settings</span> ${t('settings.integrations.configure')}
        </button>`;
    }

    return `
        <div class="oauth-provider-card ${statusClass}" data-provider="${mcp_name}" data-auth-type="oauth">
            <div class="oauth-provider-icon" style="background: ${iconColor}20; color: ${iconColor};">
                <span class="material-icons">${config.icon || 'cloud'}</span>
            </div>
            <div class="oauth-provider-info">
                <div class="oauth-provider-name">
                    ${escapeHtml(config.name || mcp_name)}${betaBadge}
                    <span class="material-icons integration-info-icon" onclick="event.stopPropagation(); showMcpInfo('${mcp_name}')" title="${t('settings.system.show_details')}">info_outline</span>
                </div>
                <div class="oauth-provider-status ${statusClass}">
                    <span class="material-icons">${statusIcon}</span>
                    <span>${statusText}</span>
                </div>
                ${advancedSection}
            </div>
            <div class="oauth-provider-actions">
                ${actionButtons}
            </div>
        </div>
    `;
}

/**
 * Render an API Key integration card with inline form
 */
function renderApiKeyCard(integration) {
    const { mcp_name, config, status } = integration;
    const isConfigured = status === 'configured';
    const statusClass = isConfigured ? 'configured' : 'not-configured';
    const statusIcon = isConfigured ? 'check_circle' : 'key_off';
    const statusText = isConfigured ? t('settings.integrations.configured') : t('settings.integrations.not_configured');
    const iconColor = config.color || 'var(--accent-primary)';
    const betaBadge = config.beta ? '<span class="integration-beta-badge">BETA</span>' : '';

    // Build form fields
    const fieldsHtml = (config.fields || []).map(f => `
        <div class="integration-field">
            <label for="integration_${mcp_name}_${f.key}">${escapeHtml(f.label)}${f.required ? ' *' : ''}</label>
            <input type="${f.type === 'password' ? 'password' : 'text'}"
                   id="integration_${mcp_name}_${f.key}"
                   placeholder="${escapeHtml(f.hint || '')}"
                   data-integration="${mcp_name}"
                   data-field="${f.key}"
                   ${f.required ? 'required' : ''}>
        </div>
    `).join('');

    return `
        <div class="oauth-provider-card ${statusClass}" data-provider="${mcp_name}" data-auth-type="api_key">
            <div class="oauth-provider-icon" style="background: ${iconColor}20; color: ${iconColor};">
                <span class="material-icons">${config.icon || 'key'}</span>
            </div>
            <div class="oauth-provider-info">
                <div class="oauth-provider-name">
                    ${escapeHtml(config.name || mcp_name)}${betaBadge}
                    <span class="material-icons integration-info-icon" onclick="event.stopPropagation(); showMcpInfo('${mcp_name}')" title="${t('settings.system.show_details')}">info_outline</span>
                </div>
                <div class="oauth-provider-status ${statusClass}">
                    <span class="material-icons">${statusIcon}</span>
                    <span>${statusText}</span>
                </div>
                <div class="integration-config-toggle" onclick="toggleIntegrationConfig('${mcp_name}')">
                    <span class="material-icons" id="configIcon_${mcp_name}">expand_more</span>
                    <span id="configToggleText_${mcp_name}">${t('settings.integrations.show_config')}</span>
                </div>
                <div class="integration-config-form hidden" id="configForm_${mcp_name}">
                    ${fieldsHtml}
                    <div class="integration-actions">
                        <button class="oauth-btn small connect" onclick="saveIntegrationConfig('${mcp_name}')">
                            <span class="material-icons">save</span> ${t('settings.integrations.save')}
                        </button>
                        <button class="oauth-btn small" onclick="testIntegration('${mcp_name}')">
                            <span class="material-icons">play_arrow</span> ${t('settings.integrations.test')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Render a Credentials integration card with username/password form
 */
function renderCredentialsCard(integration) {
    const { mcp_name, config, status } = integration;
    const isConfigured = status === 'configured';
    const statusClass = isConfigured ? 'configured' : 'not-configured';
    const statusIcon = isConfigured ? 'check_circle' : 'person_off';
    const statusText = isConfigured ? t('settings.integrations.configured') : t('settings.integrations.not_configured');
    const iconColor = config.color || 'var(--accent-primary)';
    const betaBadge = config.beta ? '<span class="integration-beta-badge">BETA</span>' : '';

    // Build form fields
    const fieldsHtml = (config.fields || []).map(f => `
        <div class="integration-field">
            <label for="integration_${mcp_name}_${f.key}">${escapeHtml(f.label)}${f.required ? ' *' : ''}</label>
            <input type="${f.type === 'password' ? 'password' : 'text'}"
                   id="integration_${mcp_name}_${f.key}"
                   placeholder="${escapeHtml(f.hint || '')}"
                   data-integration="${mcp_name}"
                   data-field="${f.key}"
                   ${f.required ? 'required' : ''}>
        </div>
    `).join('');

    return `
        <div class="oauth-provider-card ${statusClass}" data-provider="${mcp_name}" data-auth-type="credentials">
            <div class="oauth-provider-icon" style="background: ${iconColor}20; color: ${iconColor};">
                <span class="material-icons">${config.icon || 'person'}</span>
            </div>
            <div class="oauth-provider-info">
                <div class="oauth-provider-name">
                    ${escapeHtml(config.name || mcp_name)}${betaBadge}
                    <span class="material-icons integration-info-icon" onclick="event.stopPropagation(); showMcpInfo('${mcp_name}')" title="${t('settings.system.show_details')}">info_outline</span>
                </div>
                <div class="oauth-provider-status ${statusClass}">
                    <span class="material-icons">${statusIcon}</span>
                    <span>${statusText}</span>
                </div>
                <div class="integration-config-toggle" onclick="toggleIntegrationConfig('${mcp_name}')">
                    <span class="material-icons" id="configIcon_${mcp_name}">expand_more</span>
                    <span id="configToggleText_${mcp_name}">${t('settings.integrations.show_config')}</span>
                </div>
                <div class="integration-config-form hidden" id="configForm_${mcp_name}">
                    ${fieldsHtml}
                    <div class="integration-actions">
                        <button class="oauth-btn small connect" onclick="saveIntegrationConfig('${mcp_name}')">
                            <span class="material-icons">save</span> ${t('settings.integrations.save')}
                        </button>
                        <button class="oauth-btn small" onclick="testIntegration('${mcp_name}')">
                            <span class="material-icons">play_arrow</span> ${t('settings.integrations.test')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Render a local integration card (no auth required)
 * Special handling for 'browser' MCP: shows enable/disable toggle
 */
function renderLocalCard(integration) {
    const { mcp_name, config, status } = integration;
    const isAvailable = status !== 'disabled';
    const statusClass = isAvailable ? 'available' : 'unavailable';
    const statusIcon = isAvailable ? 'check_circle' : 'block';
    const statusText = isAvailable ? t('settings.integrations.available') : t('settings.integrations.unavailable');
    const iconColor = config.color || 'var(--accent-primary)';
    const betaBadge = config.beta ? '<span class="integration-beta-badge">BETA</span>' : '';

    // Special handling for browser MCP - show toggle button
    const isBrowser = mcp_name === 'browser';
    const toggleButton = isBrowser ? `
        <button id="browserToggleBtn" class="btn-small" onclick="event.stopPropagation(); toggleBrowserIntegration()" style="margin-left: auto;">
            ${t('settings.integrations.browser_enable') || 'Aktivieren'}
        </button>
    ` : '';

    // For browser: show dynamic status that will be updated by loadBrowserIntegrationStatus()
    const browserStatus = isBrowser ? `
        <div class="oauth-provider-status" id="browserIntegrationStatus">
            <span id="browserStatusIcon" class="status-dot status-inactive"></span>
            <span id="browserStatusText">${t('settings.integrations.browser_inactive') || 'Nicht aktiviert'}</span>
        </div>
    ` : `
        <div class="oauth-provider-status ${statusClass}">
            <span class="material-icons">${statusIcon}</span>
            <span>${statusText}</span>
        </div>
    `;

    return `
        <div class="oauth-provider-card ${statusClass}" data-provider="${mcp_name}" data-auth-type="none">
            <div class="oauth-provider-icon" style="background: ${iconColor}20; color: ${iconColor};">
                <span class="material-icons">${config.icon || 'computer'}</span>
            </div>
            <div class="oauth-provider-info" style="flex: 1;">
                <div class="oauth-provider-name">
                    ${escapeHtml(config.name || mcp_name)}${betaBadge}
                    <span class="material-icons integration-info-icon" onclick="event.stopPropagation(); showMcpInfo('${mcp_name}')" title="${t('settings.system.show_details')}">info_outline</span>
                </div>
                ${browserStatus}
                ${config.description ? `<div class="integration-description">${escapeHtml(config.description)}</div>` : ''}
            </div>
            ${toggleButton}
        </div>
    `;
}

/**
 * Toggle the configuration form for an integration
 */
function toggleIntegrationConfig(mcpName) {
    const form = document.getElementById(`configForm_${mcpName}`);
    const icon = document.getElementById(`configIcon_${mcpName}`);
    const toggleText = document.getElementById(`configToggleText_${mcpName}`);
    if (form && icon) {
        const wasHidden = form.classList.contains('hidden');
        form.classList.toggle('hidden');
        const isNowHidden = form.classList.contains('hidden');
        icon.textContent = isNowHidden ? 'expand_more' : 'expand_less';

        // Update toggle text
        if (toggleText) {
            toggleText.textContent = isNowHidden
                ? t('settings.integrations.show_config')
                : t('settings.integrations.hide_config');
        }

        // Load current values when expanding
        if (wasHidden) {
            loadIntegrationConfigForMcp(mcpName);
        }
    }
}

/**
 * Toggle the advanced section for OAuth integrations
 */
function toggleIntegrationAdvanced(mcpName) {
    const section = document.getElementById(`advancedSection_${mcpName}`);
    const icon = document.getElementById(`advancedIcon_${mcpName}`);
    if (section && icon) {
        const wasHidden = section.classList.contains('hidden');
        section.classList.toggle('hidden');
        icon.textContent = section.classList.contains('hidden') ? 'expand_more' : 'expand_less';

        // Load current values when expanding
        if (wasHidden) {
            loadIntegrationConfigForMcp(mcpName);
        }
    }
}

/**
 * Load current config values for an integration
 */
async function loadIntegrationConfigForMcp(mcpName) {
    try {
        const res = await fetch(API + `/api/integrations/${encodeURIComponent(mcpName)}/config`);
        if (!res.ok) return;

        const data = await res.json();
        integrationConfigCache[mcpName] = data.config || {};

        // Fill in the form fields
        for (const [key, value] of Object.entries(data.config || {})) {
            const input = document.getElementById(`integration_${mcpName}_${key}`);
            if (input && value) {
                // For passwords, show masked value indicator
                if (input.type === 'password' && value) {
                    input.placeholder = '••••••••';
                } else {
                    input.value = value;
                }
            }
        }
    } catch (e) {
        console.error(`[Integrations] Failed to load config for ${mcpName}:`, e);
    }
}

/**
 * Load config values for all visible integrations
 */
async function loadIntegrationConfigValues() {
    const cards = document.querySelectorAll('[data-provider]');
    // Parallel fetch all configs instead of sequential (much faster on slow PCs)
    const promises = Array.from(cards).map(async (card) => {
        const mcpName = card.dataset.provider;
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);
            const res = await fetch(API + `/api/integrations/${encodeURIComponent(mcpName)}/config`, { signal: controller.signal });
            clearTimeout(timeoutId);
            if (res.ok) {
                const data = await res.json();
                integrationConfigCache[mcpName] = data.config || {};
            }
        } catch (e) {
            // Ignore errors/timeouts for individual integrations
        }
    });
    await Promise.all(promises);
}

/**
 * Save integration configuration
 */
async function saveIntegrationConfig(mcpName) {
    // Collect all field values for this integration
    const config = {};
    const inputs = document.querySelectorAll(`[data-integration="${mcpName}"]`);

    for (const input of inputs) {
        const key = input.dataset.field;
        const value = input.value.trim();
        if (value) {
            config[key] = value;
        }
    }

    try {
        const res = await fetch(API + `/api/integrations/${encodeURIComponent(mcpName)}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });

        if (res.ok) {
            showNotification(t('settings.integrations.config_saved'), 'success');
            // Reload to update status
            loadIntegrations();
        } else {
            const data = await res.json();
            showNotification(data.detail || t('settings.integrations.config_error'), 'error');
        }
    } catch (e) {
        console.error(`[Integrations] Failed to save config for ${mcpName}:`, e);
        showNotification(t('settings.integrations.config_error'), 'error');
    }
}

/**
 * Test an integration connection
 */
async function testIntegration(mcpName) {
    const btn = document.querySelector(`[data-provider="${mcpName}"] button[onclick*="testIntegration"]`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.integrations.testing');
    }

    try {
        const res = await fetch(API + `/api/integrations/${encodeURIComponent(mcpName)}/test`, {
            method: 'POST'
        });

        const data = await res.json();

        if (data.success) {
            showNotification(data.message || t('settings.integrations.test_success'), 'success');
        } else {
            showNotification(data.message || t('settings.integrations.test_failed'), 'error');
        }
    } catch (e) {
        console.error(`[Integrations] Test failed for ${mcpName}:`, e);
        showNotification(t('settings.integrations.test_failed'), 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<span class="material-icons">play_arrow</span> ${t('settings.integrations.test')}`;
        }
    }
}

// Alias for backwards compatibility
const loadOAuthProviders = loadIntegrations;

/**
 * Start OAuth flow for a provider
 * @param {string} provider - Provider name (e.g., 'linkedin', 'google')
 */
async function connectOAuth(provider) {
    // Open a blank window immediately in the click handler context.
    // Browsers block window.open() after an async gap (fetch/await),
    // so we must open it synchronously and set the URL later.
    const preOpenedWindow = window.open('about:blank', '_blank');

    try {
        // Show loading state
        const btn = document.querySelector(`.oauth-provider-card button[onclick*="${provider}"]`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="material-icons spinning">refresh</span> ' + t('settings.integrations.connecting');
        }

        const res = await fetch(API + '/oauth/' + provider + '/start', {
            method: 'POST'
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || `HTTP ${res.status}`);
        }

        const data = await res.json();

        if (data.custom_auth && data.auth_url && data.user_code) {
            // Device code flow (e.g., Microsoft 365) - navigate pre-opened window
            if (preOpenedWindow) {
                preOpenedWindow.location.href = data.auth_url;
            } else {
                window.open(data.auth_url, '_blank');
            }
            // Show the code prominently (html=true to render styled code, with ID for later hiding)
            showNotification(`Code: <strong style="font-size: 1.4em; letter-spacing: 3px; background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 4px; margin: 0 8px;">${data.user_code}</strong> - Gib diesen Code im Browser-Tab ein`, 'info', 60000, true, 'oauth-code-notification');
            // Poll for completion
            pollOAuthCompletion(provider, null);
        } else if (data.custom_auth && data.auth_url) {
            // Device code flow without user_code - navigate pre-opened window
            if (preOpenedWindow) {
                preOpenedWindow.location.href = data.auth_url;
            } else {
                window.open(data.auth_url, '_blank');
            }
            showNotification(t('settings.integrations.complete_in_browser'), 'info');
            pollOAuthCompletion(provider, null);
        } else if (data.custom_auth) {
            // MCP handles its own OAuth flow (opens browser itself) - close pre-opened window
            if (preOpenedWindow) preOpenedWindow.close();
            showNotification(t('settings.integrations.complete_in_browser'), 'info');
            pollOAuthCompletion(provider, null);
        } else if (data.auth_url) {
            // Standard OAuth - navigate pre-opened window
            if (preOpenedWindow) {
                preOpenedWindow.location.href = data.auth_url;
            } else {
                // Fallback if pre-opened window was blocked anyway
                window.open(data.auth_url, 'oauth_' + provider, 'width=600,height=700');
            }
            showNotification(t('settings.integrations.complete_in_browser'), 'info');
            pollOAuthCompletion(provider, preOpenedWindow);
        } else {
            if (preOpenedWindow) preOpenedWindow.close();
            throw new Error(data.error || t('settings.integrations.no_auth_url'));
        }
    } catch (e) {
        // Close the pre-opened window on error
        if (preOpenedWindow && !preOpenedWindow.closed) preOpenedWindow.close();
        console.error('[OAuth] Connect error:', e);
        showNotification(t('task.error_prefix') + ' ' + e.message, 'error');
        // Reload to reset button state
        loadOAuthProviders();
    }
}

/**
 * Poll for OAuth completion after user completes auth in popup
 * @param {string} provider - Provider name
 * @param {Window} authWindow - The popup window
 */
function pollOAuthCompletion(provider, authWindow) {
    let attempts = 0;
    const maxAttempts = 120; // 2 minutes max (1 second interval)

    const pollInterval = setInterval(async () => {
        attempts++;

        // Check if window was closed
        if (authWindow && authWindow.closed) {
            clearInterval(pollInterval);
            // Hide the code notification if it's still showing
            hideNotification('oauth-code-notification');
            // Reload providers to check if auth succeeded
            await loadOAuthProviders();
            return;
        }

        // Timeout after max attempts
        if (attempts >= maxAttempts) {
            clearInterval(pollInterval);
            if (authWindow && !authWindow.closed) {
                authWindow.close();
            }
            // Hide the code notification if it's still showing
            hideNotification('oauth-code-notification');
            showNotification(t('settings.integrations.auth_timeout'), 'warning');
            loadOAuthProviders();
            return;
        }

        // Check status every 2 seconds (after first 3 quick checks)
        if (attempts > 3 && attempts % 2 !== 0) return;

        try {
            const res = await fetch(API + '/oauth/' + provider + '/status');
            if (res.ok) {
                const data = await res.json();
                // API returns status: "connected" not connected: true
                if (data.status === 'connected') {
                    clearInterval(pollInterval);
                    if (authWindow && !authWindow.closed) {
                        authWindow.close();
                    }
                    // Hide the code notification if it's still showing
                    hideNotification('oauth-code-notification');
                    showNotification(t('settings.integrations.connected_success'), 'success');
                    loadOAuthProviders();
                }
            }
        } catch (e) {
            // Ignore polling errors
        }
    }, 1000);
}

/**
 * Disconnect/revoke OAuth for a provider
 * @param {string} provider - Provider name
 */
async function disconnectOAuth(provider) {
    console.log('[OAuth] disconnectOAuth called for:', provider);

    if (!confirm(t('settings.integrations.disconnect_confirm'))) {
        console.log('[OAuth] User cancelled disconnect');
        return;
    }

    console.log('[OAuth] User confirmed disconnect, sending request...');

    try {
        // Show loading state
        const btn = document.querySelector(`.oauth-provider-card button[onclick*="${provider}"]`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="material-icons spinning">refresh</span>';
        }

        const url = API + '/oauth/' + provider + '/disconnect';
        console.log('[OAuth] POST to:', url);

        const res = await fetch(url, {
            method: 'POST'
        });

        console.log('[OAuth] Response status:', res.status);

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || `HTTP ${res.status}`);
        }

        console.log('[OAuth] Disconnect successful');
        showNotification(t('settings.integrations.disconnected_success'), 'success');
        loadOAuthProviders();
    } catch (e) {
        console.error('[OAuth] Disconnect error:', e);
        showNotification(t('task.error_prefix') + ' ' + e.message, 'error');
        loadOAuthProviders();
    }
}

/**
 * Show hint for configuring an OAuth provider
 * @param {string} provider - Provider name
 */
function showOAuthConfigHint(provider) {
    showNotification(
        t('settings.integrations.config_hint').replace('{provider}', provider),
        'info',
        5000
    );
}

/**
 * Toggle msgraph advanced section visibility (backwards compatibility)
 * Now delegates to the generic toggleIntegrationAdvanced function
 */
function toggleMsgraphAdvanced() {
    toggleIntegrationAdvanced('msgraph');
}

/**
 * Load msgraph custom app config (backwards compatibility)
 * Now delegates to the generic loadIntegrationConfigForMcp function
 */
async function loadMsgraphCustomAppConfig() {
    await loadIntegrationConfigForMcp('msgraph');
}

/**
 * Save msgraph custom app config (backwards compatibility)
 * Now delegates to the generic saveIntegrationConfig function
 */
async function saveMsgraphCustomApp() {
    await saveIntegrationConfig('msgraph');
}

// =============================================================================
// UI State Persistence (localStorage)
// =============================================================================

// =============================================================================
// Prompt Sub-Tab Functions (in Logs tab)
// =============================================================================

const CONTEXT_MAX_DISPLAY_CHARS = 50000;  // Truncate prompts > 50KB for performance

async function updateSettingsContextTab() {
    try {
        const res = await fetch(`${API}/dev/context`);
        if (!res.ok) {
            console.log('[Prompt] Fetch failed:', res.status);
            return;
        }
        const data = await res.json();

        // Update token stats
        const systemTokens = estimateTokens(data.system_prompt || '');
        const userTokens = estimateTokens(data.user_prompt || '');
        const toolTokens = (data.tool_results || []).reduce((sum, t) => sum + estimateTokens(t.result || ''), 0);
        const totalTokens = systemTokens + userTokens + toolTokens;

        setIfChanged(document.getElementById('ctxSystemTokens'), formatTokens(systemTokens));
        setIfChanged(document.getElementById('ctxUserTokens'), formatTokens(userTokens));
        setIfChanged(document.getElementById('ctxToolTokens'), formatTokens(toolTokens));
        setIfChanged(document.getElementById('ctxTotalTokens'), formatTokens(totalTokens));

        // Update prompts (with truncation for performance)
        const systemPrompt = data.system_prompt || '';
        const userPrompt = data.user_prompt || '';

        const systemPromptEl = document.getElementById('ctxSystemPrompt');
        const userPromptEl = document.getElementById('ctxUserPrompt');

        if (systemPromptEl) {
            if (systemPrompt.length > CONTEXT_MAX_DISPLAY_CHARS) {
                systemPromptEl.textContent = systemPrompt.substring(0, CONTEXT_MAX_DISPLAY_CHARS) +
                    `\n\n... [Truncated - ${formatTokens(systemPrompt.length - CONTEXT_MAX_DISPLAY_CHARS)} chars more]`;
            } else {
                systemPromptEl.textContent = systemPrompt || t('context.no_context');
            }
        }

        if (userPromptEl) {
            if (userPrompt.length > CONTEXT_MAX_DISPLAY_CHARS) {
                userPromptEl.textContent = userPrompt.substring(0, CONTEXT_MAX_DISPLAY_CHARS) +
                    `\n\n... [Truncated - ${formatTokens(userPrompt.length - CONTEXT_MAX_DISPLAY_CHARS)} chars more]`;
            } else {
                userPromptEl.textContent = userPrompt || '-';
            }
        }

        // Update anonymization section
        const anonSection = document.getElementById('ctxAnonymizationSection');
        const anonContent = document.getElementById('ctxAnonymization');
        const anonCount = document.getElementById('ctxAnonymizationCount');
        const anonMappings = data.anonymization || {};
        const mappingCount = Object.keys(anonMappings).length;

        if (anonSection && anonContent) {
            if (mappingCount > 0) {
                anonSection.style.display = 'block';
                if (anonCount) anonCount.textContent = mappingCount;
                // Format mappings as table-like display
                let html = '<div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 12px;">';
                for (const [placeholder, original] of Object.entries(anonMappings)) {
                    html += `<span style="color: var(--status-warning); font-weight: 500;">${escapeHtml(placeholder)}</span>`;
                    html += `<span style="color: var(--text-muted);">\u2190 ${escapeHtml(original)}</span>`;
                }
                html += '</div>';
                anonContent.innerHTML = html;
            } else {
                anonSection.style.display = 'none';
            }
        }

        console.log('[Prompt] Tab updated:', {
            systemLen: systemPrompt.length,
            userLen: userPrompt.length,
            toolTokens: toolTokens,
            anonMappings: mappingCount
        });
    } catch (e) {
        console.error('[Prompt] Failed to update tab:', e);
    }
}

/**
 * Restore UI state from localStorage on page load.
 * This restores:
 * - Settings panel open/closed state
 * - Current settings tab
 */
function restoreUIState() {
    // Check for URL parameter from setup wizard (takes priority)
    const urlParams = new URLSearchParams(window.location.search);
    const openSettingsParam = urlParams.get('openSettings');

    if (openSettingsParam) {
        // Open settings with specified tab (from setup wizard)
        setTimeout(() => {
            openSettings(openSettingsParam);
            // Clean up URL to prevent re-opening on refresh
            window.history.replaceState({}, '', window.location.pathname);
        }, 100);
        return; // Don't process other restore logic
    }

    // Check if settings panel should be open (from localStorage)
    const settingsOpen = localStorage.getItem('settingsOpen');
    const savedTab = localStorage.getItem('settingsTab');

    if (settingsOpen === 'true') {
        // Open settings panel
        openSettings();

        // Restore saved tab if any
        if (savedTab) {
            // Small delay to ensure panel is rendered
            setTimeout(() => {
                switchSettingsTab(savedTab);
            }, 100);
        }
    }
}

// Restore UI state on page load
document.addEventListener('DOMContentLoaded', restoreUIState);

/**
 * Check license on first start and show activation overlay if not licensed.
 * Only shows once per workspace (tracked via localStorage).
 * @param {string|null} openSettingsFromUrl - URL parameter captured synchronously at DOMContentLoaded
 */
async function checkFirstStartLicense(openSettingsFromUrl = null) {
    // Don't check if we're on the setup page
    if (window.location.pathname === '/setup') return;

    // Don't show overlay if coming from setup wizard or URL parameter (already opens settings)
    // Note: openSettingsFromUrl is captured BEFORE setTimeout to avoid race condition with URL cleanup
    if (openSettingsFromUrl) return;

    // After setup wizard: show notification instead of overlay
    if (sessionStorage.getItem('setupWizardCompleted')) {
        try {
            const res = await fetch(API + '/license/status');
            const data = await res.json();
            if (!data.licensed) {
                showNotification(
                    t('license.missing_notification') || 'Bitte aktivieren Sie Ihre Lizenz',
                    'warning',
                    5000
                );
            }
        } catch (e) {
            console.error('[License] Check after setup failed:', e);
        }
        return;
    }

    // Check if we already showed this overlay in this session
    const shownKey = 'licenseOverlayShown';
    if (sessionStorage.getItem(shownKey)) return;

    try {
        const res = await fetch(API + '/license/status');
        const data = await res.json();

        if (!data.licensed) {
            // Mark as shown for this session
            sessionStorage.setItem(shownKey, 'true');

            // Show activation overlay
            showFirstStartLicenseOverlay();
        }
    } catch (e) {
        console.error('[License] First start check failed:', e);
    }
}

/**
 * Show the first-start license activation overlay.
 */
function showFirstStartLicenseOverlay() {
    // Close settings panel if open (overlay should be on top of everything)
    const settingsPanel = document.getElementById('settingsPanel');
    if (settingsPanel && !settingsPanel.classList.contains('hidden')) {
        settingsPanel.classList.add('hidden');
    }

    // Remove any existing overlay
    const existing = document.querySelector('.license-first-start-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay license-first-start-overlay';
    overlay.style.cssText = 'position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 10000;';

    overlay.innerHTML = `
        <div class="confirm-dialog license-dialog" style="max-width: 420px; text-align: center;">
            <div class="confirm-header" style="justify-content: center;">
                <span class="material-icons" style="color: var(--primary-color); font-size: 48px;">vpn_key</span>
            </div>
            <h3 style="margin: 16px 0 8px;">${t('license.welcome_title')}</h3>
            <div class="confirm-content">
                <p style="margin: 0 0 24px; color: var(--text-secondary);">
                    ${t('license.welcome_message')}
                </p>
            </div>
            <div class="confirm-buttons" style="justify-content: center;">
                <button class="btn-confirm" onclick="openSettings('license'); this.closest('.confirm-overlay').remove();"
                    style="display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 24px;">
                    <span class="material-icons" style="font-size: 20px;">vpn_key</span>
                    ${t('license.activate_license')}
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
}

// Check license on page load (minimal delay to ensure page is ready)
document.addEventListener('DOMContentLoaded', () => {
    // Capture URL params SYNCHRONOUSLY before any setTimeout modifies them
    // This prevents race condition with restoreUIState() which clears the URL
    const urlParams = new URLSearchParams(window.location.search);
    const openSettingsFromUrl = urlParams.get('openSettings');

    setTimeout(() => checkFirstStartLicense(openSettingsFromUrl), 100);
});

// =============================================================================
// Browser Integration Functions
// =============================================================================

/**
 * Load browser integration status and update UI
 */
async function loadBrowserIntegrationStatus() {
    const statusIcon = document.getElementById('browserStatusIcon');
    const statusText = document.getElementById('browserStatusText');
    const toggleBtn = document.getElementById('browserToggleBtn');

    if (!statusIcon || !statusText || !toggleBtn) return;

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);
        const response = await fetch('/browser-consent/status', { signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await response.json();

        if (data.consent_given) {
            statusIcon.className = 'status-dot status-active';
            statusText.textContent = t('settings.integrations.browser_active') || 'Aktiviert';
            toggleBtn.textContent = t('settings.integrations.browser_disable') || 'Deaktivieren';
            toggleBtn.classList.add('btn-danger');
        } else {
            statusIcon.className = 'status-dot status-inactive';
            statusText.textContent = t('settings.integrations.browser_inactive') || 'Nicht aktiviert';
            toggleBtn.textContent = t('settings.integrations.browser_enable') || 'Aktivieren';
            toggleBtn.classList.remove('btn-danger');
        }
    } catch (error) {
        console.error('[Settings] Error loading browser integration status:', error);
    }
}

/**
 * Toggle browser integration on/off
 */
async function toggleBrowserIntegration() {
    const statusIcon = document.getElementById('browserStatusIcon');
    const statusText = document.getElementById('browserStatusText');
    const toggleBtn = document.getElementById('browserToggleBtn');

    if (!toggleBtn) return;

    // Check current state
    const isActive = statusIcon?.classList.contains('status-active');

    toggleBtn.disabled = true;
    toggleBtn.textContent = '...';

    try {
        const endpoint = isActive ? '/browser-consent/revoke' : '/browser-consent/grant';
        const response = await fetch(endpoint, { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            if (isActive) {
                showNotification(t('settings.integrations.browser_disabled') || 'Browser-Integration deaktiviert', 'info');
            } else {
                showNotification(t('settings.integrations.browser_enabled') || 'Browser-Integration aktiviert', 'success');
            }
            // Reload status
            await loadBrowserIntegrationStatus();
        } else {
            showNotification(result.detail || t('task.error'), 'error');
        }
    } catch (error) {
        console.error('[Settings] Error toggling browser integration:', error);
        showNotification(t('task.connection_error'), 'error');
    }

    toggleBtn.disabled = false;
}


// =============================================================================
// Claude Desktop Integration
// =============================================================================

/**
 * Load Claude Desktop integration status
 */
async function loadClaudeDesktopStatus() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);
        const res = await fetch(API + '/claude-desktop/status', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (!res.ok) return;
        const data = await res.json();

        const statusText = document.getElementById('claudeDesktopStatusText');
        const setupBtn = document.getElementById('claudeDesktopSetupBtn');
        const removeBtn = document.getElementById('claudeDesktopRemoveBtn');
        const badge = document.getElementById('claudeDesktopStatusBadge');

        if (data.configured_in_claude) {
            // Configured
            if (statusText) {
                statusText.innerHTML = '<span style="color: var(--success-color); font-weight: 500;">Konfiguriert</span>'
                    + '<br><span style="color: var(--text-muted); font-size: 11px;">' + (data.config_path || '') + '</span>';
            }
            if (setupBtn) { setupBtn.style.display = 'none'; }
            if (removeBtn) { removeBtn.style.display = ''; }
            if (badge) {
                badge.textContent = 'Aktiv';
                badge.style.display = '';
                badge.style.background = 'var(--success-color)';
                badge.style.color = 'white';
            }
        } else {
            // Not configured
            if (statusText) {
                statusText.innerHTML = '<span style="color: var(--text-muted);">Nicht eingerichtet</span>';
            }
            if (setupBtn) { setupBtn.style.display = ''; }
            if (removeBtn) { removeBtn.style.display = 'none'; }
            if (badge) { badge.style.display = 'none'; }
        }
        // Load allowed MCPs section
        loadClaudeDesktopAllowedMcps();
    } catch (e) {
        console.error('[ClaudeDesktop] Failed to load status:', e);
    }
}

/**
 * Setup DeskAgent in Claude Desktop (stdio config)
 */
async function setupClaudeDesktop() {
    const btn = document.getElementById('claudeDesktopSetupBtn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-icons spin" style="font-size: 16px;">sync</span> ' + t('settings.claude_desktop.setting_up'); }
    try {
        const res = await fetch(API + '/claude-desktop/setup', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            showNotification(t('settings.claude_desktop.configured'), 'success');
            loadClaudeDesktopStatus();
        } else {
            showNotification('Fehler: ' + (data.error || 'Unbekannt'), 'error');
        }
    } catch (e) {
        showNotification(t('settings.claude_desktop.connection_error'), 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 4px;">add_circle</span> ' + t('settings.claude_desktop.setup'); }
    }
}

/**
 * Remove DeskAgent from Claude Desktop config
 */
async function removeClaudeDesktop() {
    const btn = document.getElementById('claudeDesktopRemoveBtn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-icons spin" style="font-size: 16px;">sync</span> ...'; }
    try {
        const res = await fetch(API + '/claude-desktop/remove', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            showNotification(t('settings.claude_desktop.removed'), 'success');
            loadClaudeDesktopStatus();
        } else {
            showNotification('Fehler: ' + (data.error || 'Unbekannt'), 'error');
        }
    } catch (e) {
        showNotification(t('settings.claude_desktop.connection_error'), 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-icons" style="font-size: 16px; vertical-align: middle; margin-right: 4px;">remove_circle</span> ' + t('settings.claude_desktop.remove'); }
    }
}

// =============================================================================
// Claude Desktop - Allowed MCPs
// =============================================================================

let _claudeDesktopMcpSavedState = []; // Track saved state to detect changes

/**
 * Load allowed MCPs for Claude Desktop
 */
async function loadClaudeDesktopAllowedMcps() {
    const section = document.getElementById('claudeDesktopMcpSection');
    const container = document.getElementById('claudeDesktopMcpList');
    if (!section || !container) return;

    try {
        const res = await fetch(API + '/claude-desktop/allowed-mcps');
        if (!res.ok) return;
        const data = await res.json();

        const allowed = data.allowed_mcps || [];
        const available = data.available_mcps || [];
        _claudeDesktopMcpSavedState = [...allowed];

        if (available.length === 0) {
            container.innerHTML = '<span style="color: var(--text-muted); font-size: 11px;">Keine MCP-Server gefunden</span>';
            return;
        }

        // Render chip-style checkboxes
        let html = '';
        for (const mcp of available) {
            const checked = allowed.length === 0 || allowed.includes(mcp);
            const id = 'cdMcp_' + mcp;
            html += `<label for="${id}" style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; `
                + `background: ${checked ? 'var(--accent-primary)' : 'var(--bg-secondary)'}; `
                + `color: ${checked ? 'white' : 'var(--text-secondary)'}; `
                + `border-radius: 14px; font-size: 11px; cursor: pointer; transition: all 0.15s; user-select: none;">`
                + `<input type="checkbox" id="${id}" value="${mcp}" ${checked ? 'checked' : ''} `
                + `onchange="onClaudeDesktopMcpChange(this)" style="display: none;">`
                + `${mcp}</label>`;
        }
        container.innerHTML = html;
        section.style.display = '';
        updateClaudeDesktopMcpCount();
    } catch (e) {
        console.error('[ClaudeDesktop] Failed to load allowed MCPs:', e);
    }
}

/**
 * Handle MCP checkbox change - update chip style and show save button
 */
function onClaudeDesktopMcpChange(checkbox) {
    const label = checkbox.parentElement;
    if (checkbox.checked) {
        label.style.background = 'var(--accent-primary)';
        label.style.color = 'white';
    } else {
        label.style.background = 'var(--bg-secondary)';
        label.style.color = 'var(--text-secondary)';
    }
    updateClaudeDesktopMcpCount();

    // Show save button if state changed
    const current = getSelectedClaudeDesktopMcps();
    const changed = JSON.stringify(current.sort()) !== JSON.stringify([..._claudeDesktopMcpSavedState].sort());
    const saveBtn = document.getElementById('claudeDesktopMcpSaveBtn');
    if (saveBtn) saveBtn.style.display = changed ? '' : 'none';
}

/**
 * Get currently selected MCPs
 */
function getSelectedClaudeDesktopMcps() {
    const checkboxes = document.querySelectorAll('#claudeDesktopMcpList input[type="checkbox"]');
    return Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);
}

/**
 * Update the MCP count display
 */
function updateClaudeDesktopMcpCount() {
    const countEl = document.getElementById('claudeDesktopMcpCount');
    if (!countEl) return;
    const total = document.querySelectorAll('#claudeDesktopMcpList input[type="checkbox"]').length;
    const selected = document.querySelectorAll('#claudeDesktopMcpList input[type="checkbox"]:checked').length;
    countEl.textContent = `${selected} / ${total}`;
}

/**
 * Select/deselect all MCPs
 */
function selectAllClaudeDesktopMcps(selectAll) {
    const checkboxes = document.querySelectorAll('#claudeDesktopMcpList input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.checked = selectAll;
        onClaudeDesktopMcpChange(cb);
    });
}

/**
 * Save allowed MCPs to backend
 */
async function saveClaudeDesktopMcps() {
    const btn = document.getElementById('claudeDesktopMcpSaveBtn');
    if (btn) btn.disabled = true;

    const selected = getSelectedClaudeDesktopMcps();
    try {
        const res = await fetch(API + '/claude-desktop/allowed-mcps', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ allowed_mcps: selected })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            _claudeDesktopMcpSavedState = [...selected];
            if (btn) btn.style.display = 'none';
            showNotification(t('settings.claude_desktop.mcp_saved'), 'success');
        } else {
            showNotification(t('settings.claude_desktop.save_error'), 'error');
        }
    } catch (e) {
        showNotification(t('settings.claude_desktop.connection_error'), 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}


/**
 * Copy text to clipboard with notification
 */
async function copyToClipboard(text, message) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification(message || 'Kopiert', 'success');
    } catch (e) {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showNotification(message || 'Kopiert', 'success');
    }
}

