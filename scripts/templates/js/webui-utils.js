/**
 * WebUI Utility Functions
 *
 * Common utilities for DOM manipulation, overlays, badges, and formatting.
 * These functions are used across the WebUI components.
 */

// =============================================================================
// Global Constants (shared across all modules)
// =============================================================================

// API base URL - same origin, no prefix needed
const API = '';

// =============================================================================
// Translation Helper (i18n)
// =============================================================================

/**
 * Translate a key with optional parameter substitution.
 * Uses the global T (translations) object loaded from the server.
 *
 * @param {string} key - Translation key like "dialog.confirm" or "header.all"
 * @param {object} params - Optional params for substitution like {count: 5}
 * @returns {string} Translated string or key as fallback if not found
 *
 * @example
 * t('dialog.confirm')  // Returns "Bestätigen" (German) or "Confirm" (English)
 * t('history.sessions', {count: 5})  // Returns "5 sessions" with substitution
 */
function t(key, params) {
    // Get translation from global T object, fallback to key name
    let str = (typeof T !== 'undefined' && T && T[key]) ? T[key] : key;

    // Parameter substitution: replace {paramName} with values
    if (params && typeof params === 'object') {
        Object.entries(params).forEach(([k, v]) => {
            str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
        });
    }

    return str;
}

/**
 * Translate all static HTML elements with data-i18n attributes.
 * Call this on page load to translate static content.
 *
 * Supports multiple attribute types:
 * - data-i18n="key" - Translates textContent
 * - data-i18n-title="key" - Translates title attribute
 * - data-i18n-placeholder="key" - Translates placeholder attribute
 *
 * @example
 * <span data-i18n="header.all">Alle</span>
 * <button data-i18n="dialog.confirm" data-i18n-title="tooltip.confirm">OK</button>
 * <input data-i18n-placeholder="prompt.placeholder">
 */
function translateStaticElements() {
    // Translate text content
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (key) {
            // Use innerHTML for elements with data-i18n-html attribute (for <strong>, <em> etc.)
            if (el.hasAttribute('data-i18n-html')) {
                el.innerHTML = t(key);
            } else {
                el.textContent = t(key);
            }
        }
    });

    // Translate title attributes
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        if (key) {
            el.title = t(key);
        }
    });

    // Translate placeholder attributes
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (key) {
            el.placeholder = t(key);
        }
    });

    // Translate aria-label attributes
    document.querySelectorAll('[data-i18n-aria]').forEach(el => {
        const key = el.getAttribute('data-i18n-aria');
        if (key) {
            el.setAttribute('aria-label', t(key));
        }
    });
}

// =============================================================================
// Browser Error Logging
// =============================================================================

/**
 * Global error handler that logs JavaScript errors to the server.
 * This helps debug issues that occur in the browser.
 */
window.onerror = function(message, source, lineno, colno, error) {
    const errorData = {
        message: message,
        source: source,
        line: lineno,
        column: colno,
        stack: error?.stack || null,
        userAgent: navigator.userAgent,
        url: window.location.href
    };

    // Log to console for immediate visibility
    console.error('[WebUI Error]', errorData);

    // Send to server (fire and forget)
    try {
        fetch(API + '/log/browser-error', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(errorData)
        }).catch(() => {}); // Ignore fetch errors
    } catch (e) {
        // Ignore if fetch fails
    }

    // Return false to let the error propagate to console
    return false;
};

/**
 * Handle unhandled promise rejections
 */
window.onunhandledrejection = function(event) {
    const errorData = {
        message: 'Unhandled Promise Rejection: ' + (event.reason?.message || event.reason),
        stack: event.reason?.stack || null,
        userAgent: navigator.userAgent,
        url: window.location.href
    };

    console.error('[WebUI Unhandled Rejection]', errorData);

    try {
        fetch(API + '/log/browser-error', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(errorData)
        }).catch(() => {});
    } catch (e) {}
};

// =============================================================================
// Modal Overlay Utilities
// =============================================================================

/**
 * Create a modal overlay element with consistent styling and behavior.
 * @param {Object} options - Configuration options
 * @param {string} options.id - Optional ID for the overlay
 * @param {string} options.className - CSS class name (default: 'confirm-overlay')
 * @param {boolean} options.closeOnClick - Close when clicking outside dialog (default: true)
 * @param {Function} options.onClose - Callback when overlay is closed
 * @returns {HTMLDivElement} The overlay element (not yet appended to DOM)
 */
function createModalOverlay(options = {}) {
    const {
        id = null,
        className = 'confirm-overlay',
        closeOnClick = true,
        onClose = null
    } = options;

    const overlay = document.createElement('div');
    overlay.className = className;
    if (id) overlay.id = id;

    if (closeOnClick) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                if (onClose) onClose();
                overlay.remove();
            }
        });
    }

    return overlay;
}

/**
 * Remove existing overlay by ID or class name.
 * @param {string} selector - ID (with #) or class selector (with .)
 */
function removeExistingOverlay(selector) {
    const existing = document.querySelector(selector);
    if (existing) existing.remove();
}

/**
 * Add keyboard handler to overlay with common patterns (Escape to close, Enter to confirm).
 * @param {HTMLElement} overlay - The overlay element
 * @param {Object} handlers - Handler configuration
 * @param {Function} handlers.onEscape - Called when Escape is pressed
 * @param {Function} handlers.onEnter - Called when Enter is pressed
 * @param {boolean} handlers.allowInputEditing - Skip handlers when focus is in input/textarea
 * @returns {Function} The key handler function (for cleanup)
 */
function addOverlayKeyHandler(overlay, handlers = {}) {
    const { onEscape, onEnter, allowInputEditing = true } = handlers;

    const keyHandler = function(e) {
        if (allowInputEditing && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
            // Allow Escape even in inputs
            if (e.key === 'Escape' && onEscape) {
                e.preventDefault();
                document.removeEventListener('keydown', keyHandler);
                onEscape();
            }
            return;
        }

        if (e.key === 'Escape' && onEscape) {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            onEscape();
        } else if (e.key === 'Enter' && onEnter) {
            e.preventDefault();
            document.removeEventListener('keydown', keyHandler);
            onEnter();
        }
    };

    document.addEventListener('keydown', keyHandler);
    overlay._keyHandler = keyHandler; // Store for cleanup
    return keyHandler;
}

// =============================================================================
// Badge and UI Element Utilities
// =============================================================================

/**
 * Update a badge element with status information.
 * @param {Object} config - Badge configuration
 * @param {HTMLElement} config.badge - The badge container element
 * @param {HTMLElement} config.icon - The icon element (optional)
 * @param {HTMLElement} config.text - The text element
 * @param {HTMLElement} config.count - The count element (optional)
 * @param {string} config.iconName - Material icon name
 * @param {string} config.textContent - Text to display
 * @param {number} config.countValue - Count value (optional)
 * @param {string} config.badgeClass - CSS class for badge state
 */
function updateBadge(config) {
    const { badge, icon, text, count, iconName, textContent, countValue, badgeClass } = config;

    if (badge && badgeClass !== undefined) {
        // Remove existing state classes and add new one
        badge.className = badge.className.replace(/\b(online|offline|warning|error|enabled|disabled)\b/g, '').trim();
        if (badgeClass) badge.classList.add(badgeClass);
    }
    if (icon && iconName) icon.textContent = iconName;
    if (text && textContent !== undefined) text.textContent = textContent;
    if (count) {
        if (countValue !== undefined && countValue > 0) {
            count.textContent = countValue;
            count.style.display = '';
        } else {
            count.style.display = 'none';
        }
    }
}

/**
 * Set element visibility with display property.
 * @param {HTMLElement} element - The element
 * @param {boolean} visible - Whether to show or hide
 * @param {string} displayValue - Display value when visible (default: '')
 */
function setVisible(element, visible, displayValue = '') {
    if (element) element.style.display = visible ? displayValue : 'none';
}

// =============================================================================
// Formatting Utilities
// =============================================================================

/**
 * Format seconds into human-readable time string.
 * @param {number} seconds - Seconds to format
 * @returns {string} Formatted time (e.g., "1:05" or "0:45")
 */
function formatTimeSeconds(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} text - Text to escape
 * @returns {string} Escaped text safe for innerHTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =============================================================================
// Link Placeholder System (V2)
// =============================================================================

// Global link map for current session (link_ref -> web_link)
let _currentLinkMap = {};

/**
 * Set the link map for the current session.
 * Called when loading a session from history or receiving link_map from API.
 * @param {Object} linkMap - Object mapping link_ref to web_link
 */
function setLinkMap(linkMap) {
    _currentLinkMap = linkMap || {};
}

/**
 * Add links to the current map (used during streaming).
 * @param {Object} newLinks - Object with new link_ref -> web_link mappings
 */
function addToLinkMap(newLinks) {
    if (newLinks && typeof newLinks === 'object') {
        Object.assign(_currentLinkMap, newLinks);
    }
}

/**
 * Get the current link map.
 * @returns {Object} Current link_ref -> web_link mapping
 */
function getLinkMap() {
    return _currentLinkMap;
}

/**
 * Clear the link map (call when starting a new session).
 */
function clearLinkMap() {
    _currentLinkMap = {};
}

/**
 * Resolve {{LINK:ref}} placeholders in content using the current link map.
 * Called before displaying content to replace placeholders with actual URLs.
 *
 * @param {string} content - Content with {{LINK:ref}} placeholders
 * @param {Object} linkMap - Optional link map to use (defaults to current)
 * @returns {string} Content with placeholders replaced by URLs
 *
 * @example
 * resolveLinkPlaceholders('[Email]({{LINK:a3f2b1c8}})')
 * // Returns: '[Email](https://outlook.office.com/mail/...)'
 */
function resolveLinkPlaceholders(content, linkMap) {
    if (!content) return content;

    const map = linkMap || _currentLinkMap;
    if (!map || Object.keys(map).length === 0) return content;

    // Pattern 1: {{LINK:ref}} - normal form (before markdown rendering)
    content = content.replace(/\{\{LINK:([a-fA-F0-9]+)\}\}/gi, (match, ref) => {
        const url = map[ref.toLowerCase()] || map[ref];
        return url || `(Ref: ${ref})`;  // Fallback if not found
    });

    // Pattern 2: %7B%7BLINK:ref%7D%7D - URL encoded form (in href attributes after markdown)
    // This happens when markdown renders [text]({{LINK:ref}}) and browser encodes the URL
    content = content.replace(/%7B%7BLINK:([a-fA-F0-9]+)%7D%7D/gi, (match, ref) => {
        const url = map[ref.toLowerCase()] || map[ref];
        return url || `(Ref: ${ref})`;
    });

    return content;
}

/**
 * Truncate text to a maximum length with ellipsis.
 * @param {string} text - Text to truncate
 * @param {number} maxLength - Maximum length
 * @returns {string} Truncated text
 */
function truncateText(text, maxLength) {
    if (!text || text.length <= maxLength) return text;
    return text.substring(0, maxLength - 3) + '...';
}

// =============================================================================
// DOM Helpers
// =============================================================================

/**
 * Only update element if value changed (prevents flickering).
 * @param {HTMLElement} element - The element to update
 * @param {string} property - Property to update ('textContent', 'innerHTML', 'value')
 * @param {*} value - New value
 */
function updateIfChanged(element, property, value) {
    if (element && element[property] !== value) {
        element[property] = value;
    }
}

/**
 * Add or remove a class based on condition.
 * @param {HTMLElement} element - The element
 * @param {string} className - CSS class name
 * @param {boolean} condition - If true, add class; if false, remove
 */
function toggleClass(element, className, condition) {
    if (element) {
        element.classList.toggle(className, condition);
    }
}
