/**
 * Voice Input Module for DeskAgent
 *
 * Provides voice-to-text transcription using OpenAI Whisper API.
 * Only available when:
 * - voice_input.enabled is true in system.json (default: true)
 * - OpenAI API key is configured in backends.json
 */

// =============================================================================
// Voice Recording State & Config
// =============================================================================

let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let voiceAvailable = false;
let voiceCancelled = false;  // ESC pressed during recording

// Config from server (loaded on init)
let voiceAutoSubmit = true;
let voiceHotkey = 'Ctrl+M';

// Dynamic target for voice input (null = main promptInput)
let activeVoiceTarget = null;
let activeVoiceButton = null;

// =============================================================================
// Voice Availability Check
// =============================================================================

/**
 * Check if voice input is available and load config.
 * Called on page load to show/hide the voice button.
 */
async function checkVoiceAvailability() {
    try {
        const res = await fetch(API + '/transcribe/status');
        if (res.ok) {
            const data = await res.json();
            voiceAvailable = data.available === true;

            // Load config options
            if (data.auto_submit !== undefined) {
                voiceAutoSubmit = data.auto_submit;
            }
            if (data.hotkey) {
                voiceHotkey = data.hotkey;
            }

            const voiceBtn = document.getElementById('voiceBtn');
            if (voiceBtn) {
                if (voiceAvailable) {
                    voiceBtn.classList.remove('hidden');
                    voiceBtn.title = t('voice.input_hotkey', {hotkey: voiceHotkey});
                    console.log(`[Voice] Whisper available, hotkey: ${voiceHotkey}, auto_submit: ${voiceAutoSubmit}`);
                } else {
                    voiceBtn.classList.add('hidden');
                    console.log('[Voice] Whisper not available:', data.reason);
                }
            }
        }
    } catch (e) {
        console.warn('[Voice] Could not check availability:', e);
    }
}

// =============================================================================
// Recording Controls
// =============================================================================

/**
 * Toggle voice recording on/off.
 * @param {HTMLElement} targetInput - Optional target input element (default: #promptInput)
 * @param {HTMLElement} voiceBtn - Optional voice button element (default: #voiceBtn)
 */
async function toggleVoiceRecording(targetInput = null, voiceBtn = null) {
    if (isRecording) {
        stopRecording(false);  // Normal stop, not cancelled
    } else {
        // Set target for this recording session
        activeVoiceTarget = targetInput || document.getElementById('promptInput');
        activeVoiceButton = voiceBtn || document.getElementById('voiceBtn');
        await startRecording();
    }
}

/**
 * Cancel recording (ESC pressed).
 */
function cancelRecording() {
    if (isRecording) {
        stopRecording(true);  // Cancelled
    }
}

/**
 * Start audio recording using MediaRecorder API.
 */
async function startRecording() {
    const voiceBtn = activeVoiceButton || document.getElementById('voiceBtn');
    voiceCancelled = false;

    try {
        // Request microphone permission
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount: 1,
                sampleRate: 16000
            }
        });

        // Create MediaRecorder (prefer webm with opus codec)
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/webm')
                ? 'audio/webm'
                : 'audio/mp4';

        mediaRecorder = new MediaRecorder(stream, { mimeType });
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = async () => {
            // Stop all tracks to release microphone
            stream.getTracks().forEach(track => track.stop());

            // Check if cancelled
            if (voiceCancelled) {
                console.log('[Voice] Recording cancelled');
                resetVoiceButton();
                return;
            }

            // Send audio for transcription
            await sendAudioForTranscription();
        };

        // Start recording
        mediaRecorder.start();
        isRecording = true;

        // Update button appearance
        voiceBtn.classList.add('recording');
        voiceBtn.querySelector('.material-icons').textContent = 'stop';
        voiceBtn.title = t('voice.stop_recording');

        console.log('[Voice] Recording started');

    } catch (err) {
        console.error('[Voice] Microphone error:', err);

        if (err.name === 'NotAllowedError') {
            showToast(t('voice.mic_access_denied'));
        } else if (err.name === 'NotFoundError') {
            showToast(t('voice.no_microphone'));
        } else {
            showToast(t('voice.mic_error', {error: err.message}));
        }
    }
}

/**
 * Stop audio recording.
 * @param {boolean} cancelled - True if ESC was pressed (don't submit)
 */
function stopRecording(cancelled = false) {
    if (mediaRecorder && isRecording) {
        voiceCancelled = cancelled;
        mediaRecorder.stop();
        isRecording = false;

        if (cancelled) {
            // Immediately reset for cancelled recording
            resetVoiceButton();
        } else {
            // Show processing state for normal stop
            const voiceBtn = activeVoiceButton || document.getElementById('voiceBtn');
            if (voiceBtn) {
                voiceBtn.classList.remove('recording');
                voiceBtn.classList.add('processing');
                voiceBtn.querySelector('.material-icons').textContent = 'hourglass_empty';
                voiceBtn.title = t('voice.transcribing');
            }
            console.log('[Voice] Recording stopped, processing...');
        }
    }
}

// =============================================================================
// Transcription
// =============================================================================

/**
 * Send recorded audio to backend for Whisper transcription.
 */
async function sendAudioForTranscription() {
    // Get target input (use activeVoiceTarget if set, otherwise fall back to promptInput)
    const targetInput = activeVoiceTarget || document.getElementById('promptInput');
    const isMainPrompt = !activeVoiceTarget || activeVoiceTarget.id === 'promptInput';

    try {
        // Create audio blob from chunks
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });

        if (audioBlob.size < 1000) {
            showToast(t('voice.recording_too_short'));
            resetVoiceButton();
            return;
        }

        console.log('[Voice] Sending audio:', audioBlob.size, 'bytes');

        // Create form data
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');

        // Send to transcription endpoint
        const res = await fetch(API + '/transcribe', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Transcription failed');
        }

        const result = await res.json();

        if (result.success && result.text) {
            // Insert transcribed text into target input
            const currentText = targetInput.value;
            const newText = currentText
                ? currentText + ' ' + result.text
                : result.text;
            targetInput.value = newText;
            targetInput.focus();

            // Trigger input event for any listeners
            targetInput.dispatchEvent(new Event('input', { bubbles: true }));

            console.log('[Voice] Transcription:', result.text);

            // Auto-submit ONLY for main prompt input (not for dialog fields)
            if (isMainPrompt && voiceAutoSubmit && typeof sendPrompt === 'function') {
                console.log('[Voice] Auto-submitting...');
                resetVoiceButton();
                sendPrompt();
                return;
            }
        } else {
            showToast(t('voice.no_speech_detected'));
        }

    } catch (err) {
        console.error('[Voice] Transcription error:', err);
        showToast(t('voice.transcription_failed', {error: err.message}));
    } finally {
        resetVoiceButton();
    }
}

/**
 * Reset voice button to initial state.
 * @param {HTMLElement} specificBtn - Optional specific button to reset (default: activeVoiceButton or #voiceBtn)
 */
function resetVoiceButton(specificBtn = null) {
    const voiceBtn = specificBtn || activeVoiceButton || document.getElementById('voiceBtn');
    if (voiceBtn) {
        voiceBtn.classList.remove('recording', 'processing');
        const icon = voiceBtn.querySelector('.material-icons');
        if (icon) icon.textContent = 'mic';

        // Set appropriate title based on button type
        if (voiceBtn.id === 'voiceBtn') {
            voiceBtn.title = t('voice.input_hotkey', {hotkey: voiceHotkey});
        } else {
            voiceBtn.title = t('voice.input');
        }
    }

    // Reset state
    isRecording = false;
    audioChunks = [];
    mediaRecorder = null;
    voiceCancelled = false;
    activeVoiceTarget = null;
    activeVoiceButton = null;
}

// =============================================================================
// Inline Voice Button Creation (for dialogs)
// =============================================================================

/**
 * Create an inline voice button for a text input or textarea.
 * Used in agent input dialogs and other forms.
 *
 * @param {HTMLElement} targetInput - The input or textarea element
 * @param {HTMLElement} container - Optional container to append button to (default: targetInput.parentElement)
 * @returns {HTMLElement|null} - The created button, or null if voice not available
 */
function createInlineVoiceButton(targetInput, container = null) {
    if (!voiceAvailable || !targetInput) return null;

    const parent = container || targetInput.parentElement;
    if (!parent) return null;

    // Ensure parent has relative positioning for absolute button placement
    const parentStyle = window.getComputedStyle(parent);
    if (parentStyle.position === 'static') {
        parent.style.position = 'relative';
    }

    // Create voice button
    const voiceBtn = document.createElement('button');
    voiceBtn.type = 'button';
    voiceBtn.className = 'input-field-voice-btn';
    voiceBtn.title = t('voice.input');
    voiceBtn.innerHTML = '<span class="material-icons">mic</span>';

    // Click handler
    voiceBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleVoiceRecording(targetInput, voiceBtn);
    });

    // Append to parent
    parent.appendChild(voiceBtn);

    return voiceBtn;
}

/**
 * Initialize voice buttons for all textareas in a container.
 * Call this after dynamically creating a dialog with text fields.
 *
 * @param {HTMLElement} container - The container element (e.g., dialog)
 */
function initVoiceButtonsInContainer(container) {
    if (!voiceAvailable || !container) return;

    // Find all textareas and multiline-capable inputs
    const textareas = container.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        // Only add if not already has a voice button sibling
        const parent = textarea.parentElement;
        if (parent && !parent.querySelector('.input-field-voice-btn')) {
            createInlineVoiceButton(textarea);
        }
    });
}

// =============================================================================
// Hotkey Parsing
// =============================================================================

/**
 * Parse hotkey string like "Ctrl+M" or "Ctrl+Shift+V" into key parts.
 */
function parseHotkey(hotkeyStr) {
    const parts = hotkeyStr.toLowerCase().split('+');
    return {
        ctrl: parts.includes('ctrl'),
        shift: parts.includes('shift'),
        alt: parts.includes('alt'),
        key: parts[parts.length - 1]  // Last part is the key
    };
}

/**
 * Check if a keyboard event matches the configured hotkey.
 */
function matchesHotkey(e, hotkey) {
    const parsed = parseHotkey(hotkey);
    return e.ctrlKey === parsed.ctrl &&
           e.shiftKey === parsed.shift &&
           e.altKey === parsed.alt &&
           e.key.toLowerCase() === parsed.key;
}

// =============================================================================
// Initialization & Hotkey
// =============================================================================

// Check voice availability when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Small delay to ensure API constant is defined
    setTimeout(checkVoiceAvailability, 100);
});

// Dynamic hotkey handler
document.addEventListener('keydown', (e) => {
    // ESC during recording = cancel
    if (e.key === 'Escape' && isRecording) {
        e.preventDefault();
        cancelRecording();
        return;
    }

    // Configured hotkey to toggle voice recording
    if (matchesHotkey(e, voiceHotkey)) {
        const activeElement = document.activeElement;
        const isInOtherInput = activeElement &&
            (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA') &&
            activeElement.id !== 'promptInput';

        // Allow hotkey when in promptInput or not in any input
        if (!isInOtherInput && voiceAvailable) {
            e.preventDefault();
            toggleVoiceRecording();
        }
    }
});
